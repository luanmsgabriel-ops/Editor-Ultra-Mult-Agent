import json
from pathlib import Path
import subprocess
import time

from starlette.testclient import TestClient

from editor_ultra_app.server import create_app, UI_URI
from scripts.check_app_connection import authorize_owner


BASE = "https://editor.example"
KEY = "test-only-owner-key-012345678901234567890"


def video(path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=160x90:rate=10:duration=1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   check=True, timeout=30)


def structured(result):
    assert not result.get("isError"), result
    return result["structuredContent"]


def test_real_mcp_admission_queue_preview_and_retry(tmp_path):
    app = create_app(data_dir=tmp_path / "data", base_url=BASE, owner_key=KEY)
    source = tmp_path / "actual.mp4"
    video(source)
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/healthz").json()["ffmpeg"]
        assert client.post("/uploads/no-project/ref", content=source.read_bytes()).status_code == 401
        assert client.post("/catalog/install", content=b"unauthorized").status_code == 401
        with authorize_owner(BASE, KEY, client=client) as session:
            tools = session.rpc("tools/list")["tools"]
            assert {"editor_open", "editor_import_file", "editor_prepare", "editor_render"} <= {t["name"] for t in tools}
            opening = structured(session.call_tool("editor_open", {}))
            assert opening["projects"] == []
            resource = session.rpc("resources/read", {"uri": UI_URI})["contents"][0]
            assert resource["mimeType"] == "text/html;profile=mcp-app"
            assert "__CATALOG_DATA__" not in resource["text"]
            assert "EDITOR_ULTRA_OWNER_KEY" not in resource["text"]
            created = structured(session.call_tool("editor_save_project", {"state": {
                "schema": "editor-ultra-interface/1", "objective": "Technical connection test", "sourceType": "video",
            }}))
            project_id, rev = created["project_id"], created["revision"]
            headers = {**session.headers, "Content-Type": "video/mp4", "X-Editor-Revision": str(rev)}
            imported = client.post(f"/uploads/{project_id}/ref?filename=actual.mp4", content=source.read_bytes(), headers=headers)
            assert imported.status_code == 200, imported.text
            current = imported.json()
            asset = structured(session.call_tool("editor_get_asset", {"project_id": project_id, "asset_id": current["asset_id"]}))
            assert client.get(asset["url"]).content == source.read_bytes()
            assert client.get(asset["url"].split("?")[0]).status_code == 403
            arguments = {"project_id": project_id, "kind": "clone", "expected_revision": current["revision"], "request_id": "native-prepare-test-1"}
            queued = structured(session.call_tool("editor_prepare", arguments))
            assert queued["status"] == "queued"
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                snapshot = structured(session.call_tool("editor_get_project", {"project_id": project_id}))
                job = next(j for j in snapshot["jobs"] if j["id"] == queued["id"])
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(.05)
            assert job["status"] == "completed", job
            assert job["result"]["status"] == "awaiting_direction"
            assert "request" in job["result"] and "analysis" in job["result"]
            repeated = structured(session.call_tool("editor_prepare", arguments))
            assert repeated["job_id"] == job["id"] and repeated["status"] == "completed"
            assert snapshot["state"]["cloneApproval"] is None
            assert snapshot["state"]["finalApproval"] is None
            conflict = session.call_tool("editor_save_project", {"project_id": project_id, "expected_revision": rev, "state": {"objective": "stale"}})
            assert conflict.get("isError")
