from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
import sqlite3
import subprocess
import uuid

import pytest
from starlette.testclient import TestClient

from editor_ultra_app.server import create_app
from editor_ultra_app.upload_tickets import UploadBinding, UploadTicketError, UploadTicketStore
from scripts.check_app_connection import authorize_owner


BASE = "https://editor.example"
KEY = "test-only-owner-key-012345678901234567890"
ORIGIN = "https://web-sandbox.oaiusercontent.com"


def binding(**values):
    return UploadBinding(**{"upload_id": str(uuid.uuid4()), "project_id": "synthetic-project",
                            "role": "ref", "expected_revision": 1, "file_name": "fixture.mp4",
                            "mime_type": "video/mp4", "size_bytes": 128, **values})


def test_ticket_atomic_claim_rotation_expiry_and_hash_only_storage(tmp_path):
    store = UploadTicketStore(tmp_path)
    item = binding()
    token, expires = store.issue(item)
    assert token.encode() not in store.path.read_bytes()
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT digest FROM tickets").fetchone()[0] == hashlib.sha256(token.encode()).hexdigest()
    assert store.path.stat().st_mode & 0o777 == 0o600

    def claim():
        try:
            return store.claim(item.upload_id, token, item.mime_type, str(item.size_bytes))
        except UploadTicketError as exc:
            return exc

    with ThreadPoolExecutor(2) as pool:
        attempts = list(pool.map(lambda _: claim(), range(2)))
    success = next(value for value in attempts if not isinstance(value, UploadTicketError))
    blocked = next(value for value in attempts if isinstance(value, UploadTicketError))
    assert blocked.code == "upload_in_progress" and blocked.status == 409
    with pytest.raises(UploadTicketError, match="Confira"):
        store.issue(item)
    store.fail(success)
    rotated, _ = store.issue(replace(item, expected_revision=2))
    with pytest.raises(UploadTicketError) as rejected:
        store.claim(item.upload_id, token, item.mime_type, str(item.size_bytes))
    assert rejected.value.status == 401
    current = store.claim(item.upload_id, rotated, item.mime_type, str(item.size_bytes))
    store.complete(current, "synthetic-asset")
    replay = store.claim(item.upload_id, rotated, item.mime_type, str(item.size_bytes))
    assert replay.completed and replay.asset_id == "synthetic-asset"
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE tickets SET expires=0")
    with pytest.raises(UploadTicketError) as expired:
        store.claim(item.upload_id, rotated, item.mime_type, str(item.size_bytes))
    assert expired.value.status == 401  # A receipt does not revive an expired capability.


@pytest.mark.parametrize("changes", [
    {"project_id": "another-project"}, {"role": "footage"}, {"role": "shot", "shot_id": "another-shot"},
    {"file_name": "other.mp4"}, {"mime_type": "video/webm"}, {"size_bytes": 129},
])
def test_upload_uuid_cannot_be_rebound(tmp_path, changes):
    store = UploadTicketStore(tmp_path)
    original = binding()
    store.issue(original)
    with pytest.raises(UploadTicketError) as blocked:
        store.issue(replace(original, **changes))
    assert blocked.value.code == "upload_id_conflict"


def test_invalid_capabilities_do_not_exhaust_owner_rate_and_restart_does_not_replay(tmp_path):
    store = UploadTicketStore(tmp_path)
    item = binding()
    token, _ = store.issue(item)
    for _ in range(121):
        with pytest.raises(UploadTicketError) as invalid:
            store.claim(item.upload_id, "x" * 43, item.mime_type, str(item.size_bytes))
        assert invalid.value.status == 401
    store.claim(item.upload_id, token, item.mime_type, str(item.size_bytes))
    restarted = UploadTicketStore(tmp_path)
    with pytest.raises(UploadTicketError) as interrupted:
        restarted.claim(item.upload_id, token, item.mime_type, str(item.size_bytes))
    assert interrupted.value.status == 401
    renewed, _ = restarted.issue(item)
    assert renewed != token


def test_ticket_ledger_and_pending_counts_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr("editor_ultra_app.upload_tickets.MAX_PENDING", 1)
    monkeypatch.setattr("editor_ultra_app.upload_tickets.MAX_RECORDS", 2)
    store = UploadTicketStore(tmp_path)
    first, second, third = binding(), binding(), binding()
    token, _ = store.issue(first)
    with pytest.raises(UploadTicketError) as full:
        store.issue(second)
    assert full.value.code == "upload_pending_limit"
    store.fail(store.claim(first.upload_id, token, first.mime_type, str(first.size_bytes)))
    token, _ = store.issue(second)
    store.fail(store.claim(second.upload_id, token, second.mime_type, str(second.size_bytes)))
    with pytest.raises(UploadTicketError) as full:
        store.issue(third)
    assert full.value.code == "upload_ledger_full"


def structured(value):
    assert not value.get("isError"), value
    return value["structuredContent"]


@pytest.fixture
def connected(tmp_path):
    app = create_app(data_dir=tmp_path / "data", base_url=BASE, owner_key=KEY)
    source = tmp_path / "synthetic.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=160x90:rate=10:duration=1", "-an", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", str(source)], check=True, timeout=30)
    with TestClient(app, base_url=BASE) as client, authorize_owner(BASE, KEY, client=client) as session:
        project = structured(session.call_tool("editor_save_project", {"state": {
            "schema": "editor-ultra-interface/1", "objective": "Synthetic upload protocol test", "sourceType": "video",
        }}))
        yield app, client, session, project, source.read_bytes()


def begin(session, project, content, **changes):
    arguments = {"project_id": project["project_id"], "role": "ref", "expected_revision": project["revision"],
                 "file_name": "synthetic.mp4", "mime_type": "video/mp4", "size_bytes": len(content),
                 "upload_id": str(uuid.uuid4()), **changes}
    response = session.call_tool("editor_begin_upload", arguments)
    structured(response)
    return arguments, response


def test_direct_upload_cors_private_ticket_and_current_receipt_recovery(connected):
    app, client, session, project, content = connected
    arguments, response = begin(session, project, content)
    grant = response["_meta"]["editor"]["upload"]
    secret = grant["headers"]["Authorization"].split(" ", 1)[1]
    visible = json.dumps({"content": response["content"], "structuredContent": response["structuredContent"]})
    assert secret not in visible and "Authorization" not in visible and KEY not in json.dumps(response)
    assert grant["upload_id"] == arguments["upload_id"] and grant["max_bytes"] == len(content)
    assert grant["url"] == BASE + "/upload-tickets/" + arguments["upload_id"]
    assert app.state.editor_engine.get_project(project["project_id"]) == project

    anonymous = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": "editor_begin_upload", "arguments": arguments}},
                            headers={"Origin": ORIGIN, "Accept": "application/json, text/event-stream"})
    assert anonymous.status_code == 401
    options = client.options(grant["url"], headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                                   "Access-Control-Request-Headers": "authorization,content-type"})
    assert options.status_code == 204
    assert options.headers["access-control-allow-origin"] == "*"
    assert "POST" in options.headers["access-control-allow-methods"]
    assert "Authorization" in options.headers["access-control-allow-headers"]
    assert "access-control-allow-credentials" not in options.headers
    assert options.headers["cache-control"] == "no-store"
    for path in ("/mcp", "/owner/authorize", "/media/no-file", "/catalog/install",
                 f"/uploads/{project['project_id']}/ref"):
        assert "access-control-allow-origin" not in client.options(path, headers={"Origin": ORIGIN}).headers
    for headers in ({}, session.headers, {"Authorization": "Upload " + "x" * 43}):
        rejected = client.post(grant["url"], content=content, headers={"Content-Type": "video/mp4", **headers})
        assert rejected.status_code == 401
        assert rejected.headers["access-control-allow-origin"] == "*"

    posted = client.post(grant["url"], content=content, headers={**grant["headers"], "Origin": ORIGIN})
    assert posted.status_code == 200, posted.text
    current = posted.json()
    assert current["asset"]["hostFileId"] == "direct:" + arguments["upload_id"]
    assert current["revision"] == project["revision"] + 1
    assert current["state"]["cloneApproval"] is None and current["state"]["finalApproval"] is None
    media = next(asset for asset in current["assets"] if asset["id"] == current["asset_id"])
    downloaded = client.get(media["url"])
    assert downloaded.content == content
    assert "access-control-allow-origin" not in downloaded.headers

    # An ordinary later edit must not be undone by the old POST receipt or begin.
    changed = structured(session.call_tool("editor_save_project", {
        "project_id": project["project_id"], "expected_revision": current["revision"],
        "state": {"objective": "Later choices must survive", "assets": {"ref": []}},
    }))
    repeated = client.post(grant["url"], content=content, headers=grant["headers"])
    assert repeated.status_code == 200
    assert repeated.json()["revision"] == changed["revision"]
    assert repeated.json()["state"] == changed["state"]
    recovered = session.call_tool("editor_begin_upload", {**arguments, "expected_revision": changed["revision"]})
    assert structured(recovered)["state"] == changed["state"]
    assert structured(recovered)["asset_id"] == current["asset_id"]
    assert recovered.get("_meta", {}).get("editor", {}).get("upload") is None
    assert app.state.editor_engine.get_project(project["project_id"])["state"] == changed["state"]
    with sqlite3.connect(app.state.editor_upload_tickets.path) as db:
        db.execute("UPDATE tickets SET expires=0")
    assert client.post(grant["url"], content=content, headers=grant["headers"]).status_code == 401
    # Recovery remains an authenticated MCP read; it does not revive that ticket.
    assert structured(session.call_tool("editor_begin_upload", arguments))["revision"] == changed["revision"]
    assert not app.state.editor_queue.list(project["project_id"])


def test_direct_upload_enforces_mime_body_destination_and_revision(connected):
    app, client, session, project, content = connected
    arguments, response = begin(session, project, content)
    grant = response["_meta"]["editor"]["upload"]
    headers = grant["headers"]
    assert client.post(grant["url"], content=content, headers={**headers, "Content-Type": "video/webm"}).status_code == 415
    assert client.post(grant["url"], content=content, headers={**headers, "Content-Length": "1"}).status_code == 413
    overflow = client.post(grant["url"], content=content + b"extra", headers={**headers, "Content-Length": str(len(content))})
    assert overflow.status_code == 413
    assert not list((app.state.editor_engine.data_dir / "incoming").glob("direct-*.upload"))
    assert not app.state.editor_engine.get_project(project["project_id"])["assets"]
    response = session.call_tool("editor_begin_upload", arguments)
    grant = response["_meta"]["editor"]["upload"]
    incomplete = client.post(grant["url"], content=content[:-1],
                             headers={**grant["headers"], "Content-Length": str(len(content))})
    assert incomplete.status_code == 400
    assert session.call_tool("editor_begin_upload", {**arguments, "role": "footage"}).get("isError")
    assert session.call_tool("editor_begin_upload", {**arguments, "upload_id": str(uuid.uuid4()),
                                                      "role": "shot", "shot_id": "missing-shot"}).get("isError")
    response = session.call_tool("editor_begin_upload", arguments)
    grant = response["_meta"]["editor"]["upload"]
    changed = structured(session.call_tool("editor_save_project", {
        "project_id": project["project_id"], "expected_revision": project["revision"], "state": {"objective": "Revision advanced"},
    }))
    stale = client.post(grant["url"], content=content, headers=grant["headers"])
    assert stale.status_code == 409
    assert not app.state.editor_engine.get_project(project["project_id"])["assets"]
    assert app.state.editor_engine.get_project(project["project_id"])["revision"] == changed["revision"]
    assert session.call_tool("editor_begin_upload", arguments).get("isError")
    # Browsers with an empty File.type may use octet-stream; bytes are still probed.
    _, response = begin(session, changed, content, mime_type="application/octet-stream")
    grant = response["_meta"]["editor"]["upload"]
    assert grant["headers"]["Content-Type"] == "application/octet-stream"
    accepted = client.post(grant["url"], content=content, headers=grant["headers"])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["asset"]["type"] == "video/mp4"


def test_commit_receipt_recovers_after_ledger_finalization_failure(connected, monkeypatch):
    app, client, session, project, content = connected
    arguments, response = begin(session, project, content)
    grant = response["_meta"]["editor"]["upload"]

    def interrupted(*args):
        raise OSError("Synthetic failure after engine commit, before ledger finalization")

    monkeypatch.setattr(app.state.editor_upload_tickets, "complete", interrupted)
    assert client.post(grant["url"], content=content, headers=grant["headers"]).status_code == 409
    committed = app.state.editor_engine.get_project(project["project_id"])
    assert len(committed["assets"]) == 1
    # A restarted ledger invalidates incomplete claims, but not the engine receipt.
    UploadTicketStore(app.state.editor_upload_tickets.path.parent)
    recovered = session.call_tool("editor_begin_upload", {**arguments, "expected_revision": committed["revision"]})
    value = structured(recovered)
    assert value["idempotent"] and value["asset_id"] == committed["assets"][0]["id"]
    assert value["state"] == committed["state"] and value["revision"] == committed["revision"]
    assert recovered.get("_meta", {}).get("editor", {}).get("upload") is None
    assert len(app.state.editor_engine.get_project(project["project_id"])["assets"]) == 1
