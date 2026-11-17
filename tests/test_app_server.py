import io
import json
from pathlib import Path
import subprocess
import time

from PIL import Image
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


def test_real_mcp_admission_queue_preview_and_retry(tmp_path, monkeypatch):
    app = create_app(data_dir=tmp_path / "data", base_url=BASE, owner_key=KEY)
    source = tmp_path / "actual.mp4"
    video(source)
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/healthz").json()["ffmpeg"]
        brand = client.get("/brand/e-mark-v1.png")
        assert brand.status_code == 200
        assert brand.headers["content-type"] == "image/png"
        assert "immutable" in brand.headers["cache-control"]
        assert brand.content == (Path(__file__).parents[1] / "editor_ultra_app/brand/e-mark-v1.png").read_bytes()
        assert client.get("/brand/ui.html").status_code == 404
        assert client.post("/uploads/no-project/ref", content=source.read_bytes()).status_code == 401
        assert client.post("/catalog/install", content=b"unauthorized").status_code == 401
        with authorize_owner(BASE, KEY, client=client) as session:
            tools = session.rpc("tools/list")["tools"]
            tools_by_name = {tool["name"]: tool for tool in tools}
            widget_tools = {
                "editor_open", "editor_list_templates", "editor_get_project", "editor_save_project",
                "editor_import_file", "editor_begin_upload", "editor_prepare", "editor_record_review",
                "editor_compare_clone", "editor_compare_temporal",
            }
            assert widget_tools | {"editor_render"} <= tools_by_name.keys()
            opening_tool = tools_by_name["editor_open"]
            assert opening_tool["title"] == "Editor Ultra"
            assert opening_tool["annotations"]["readOnlyHint"] is True
            assert not opening_tool["inputSchema"].get("required")  # Entrypoints invoke the tool with {}.
            assert opening_tool["_meta"]["ui"]["resourceUri"] == UI_URI == "ui://editor-ultra/studio-v8.html"
            assert opening_tool["_meta"]["openai/outputTemplate"] == UI_URI
            assert opening_tool["_meta"]["openai/ui"]["entrypoints"] == [{"type": "global"}, {"type": "thread"}]
            for name in widget_tools:
                assert tools_by_name[name]["_meta"]["openai/widgetAccessible"] is True
            assert tools_by_name["editor_import_file"]["_meta"]["openai/fileParams"] == ["file"]
            assert tools_by_name["editor_begin_upload"]["_meta"]["ui"]["visibility"] == ["app"]
            save_tool = tools_by_name["editor_save_project"]
            assert set(save_tool["inputSchema"]["properties"]) == {"state", "project_id", "expected_revision"}
            assert save_tool["inputSchema"]["required"] == ["state"]
            assert save_tool["inputSchema"]["properties"]["state"]["type"] == "object"
            assert save_tool["inputSchema"]["properties"]["state"]["additionalProperties"] is True
            assert save_tool["annotations"]["readOnlyHint"] is False
            assert {"editor_measure_motion", "editor_request_clone_images"} <= tools_by_name.keys()
            for name, tool in tools_by_name.items():
                if name != "editor_open":
                    metadata = tool.get("_meta", {})
                    assert not metadata.get("ui", {}).get("resourceUri")
                    assert "openai/outputTemplate" not in metadata
            opening = structured(session.call_tool("editor_open", {}))
            assert opening["project"] is None
            assert opening["projects"] == []
            assert opening["upload_capabilities"] == {
                "direct": True, "origin": BASE, "max_bytes": 512 * 1024 * 1024, "ticket_ttl_seconds": 300,
            }
            resource = session.rpc("resources/read", {"uri": UI_URI})["contents"][0]
            assert resource["uri"] == UI_URI
            assert resource["mimeType"] == "text/html;profile=mcp-app"
            assert resource["_meta"]["openai/ui"] == {
                "availableDisplayModes": ["inline", "fullscreen"], "preferredDisplayMode": "fullscreen",
            }
            assert resource["_meta"]["ui"]["csp"] == {"connectDomains": [BASE], "resourceDomains": [BASE]}
            assert resource["text"].strip()
            assert "__CATALOG_DATA__" not in resource["text"]
            assert "EDITOR_ULTRA_OWNER_KEY" not in resource["text"]
            assert "__EDITOR_ULTRA_LOGO_URL__" not in resource["text"]
            assert BASE + "/brand/e-mark-v1.png" in resource["text"]
            for legacy_uri in ("ui://editor-ultra/studio-v1.html", "ui://editor-ultra/studio-v2.html",
                               "ui://editor-ultra/studio-v3.html", "ui://editor-ultra/studio-v4.html",
                               "ui://editor-ultra/studio-v5.html", "ui://editor-ultra/studio-v6.html",
                               "ui://editor-ultra/studio-v7.html"):
                legacy_resource = session.rpc("resources/read", {"uri": legacy_uri})["contents"][0]
                assert legacy_resource["uri"] == legacy_uri
                assert legacy_resource["text"] == resource["text"]
                assert legacy_resource["mimeType"] == resource["mimeType"]
                assert legacy_resource["_meta"] == resource["_meta"]
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

            async def download_fixture(url, directory, max_bytes):
                assert url == "https://files.oaiusercontent.com/synthetic-native-upload.mp4"
                assert source.stat().st_size <= max_bytes
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / "synthetic-native-upload.mp4"
                target.write_bytes(source.read_bytes())
                return target

            monkeypatch.setattr("editor_ultra_app.server.download_attachment", download_fixture)
            native_arguments = {
                "project_id": project_id, "role": "footage", "expected_revision": current["revision"],
                "file": {"file_id": "file-synthetic-native-upload", "file_name": "native.mp4",
                         "mime_type": "video/mp4",
                         "download_url": "https://files.oaiusercontent.com/synthetic-native-upload.mp4"},
            }
            admitted = structured(session.call_tool("editor_import_file", native_arguments))
            assert admitted["asset"]["hostFileId"] == native_arguments["file"]["file_id"]
            received = structured(session.call_tool("editor_get_project", {"project_id": project_id}))
            assert received["state"]["assets"]["footage"][0]["hostFileId"] == native_arguments["file"]["file_id"]
            # Reconcile after a potentially lost response, then retry at the current revision.
            native_arguments["expected_revision"] = received["revision"]
            current = structured(session.call_tool("editor_import_file", native_arguments))
            assert current["idempotent"] is True
            assert current["asset_id"] == admitted["asset_id"]
            assert current["revision"] == received["revision"]
            assert len(current["state"]["assets"]["footage"]) == 1
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


            images = structured(session.call_tool("editor_request_clone_images", {
                "project_id": project_id, "expected_revision": snapshot["revision"], "needs": [{
                    "id": "emblem", "scene_id": "fixture", "frames": [0, 10],
                    "reference_frame": 4, "placement": "planar",
                    "description": "One green emblem against transparent margins.",
                    "reason": "Keep the scene attachment editable.",
                }],
            }))
            assert images["image_request"]["status"] == "awaiting_image_generation"
            still = images["image_request"]["stills"]["4"]
            assert still["role"] == "evidence"
            image = Image.new("RGBA", (20, 20))
            image.paste((64, 255, 64, 255), (2, 2, 18, 18))
            png = io.BytesIO()
            image.save(png, format="PNG")
            uploaded = client.post(f"/uploads/{project_id}/clone_resource?filename=emblem.png",
                                   content=png.getvalue(), headers={
                                       **session.headers, "Content-Type": "image/png",
                                       "X-Editor-Revision": str(images["revision"]),
                                   })
            assert uploaded.status_code == 200, uploaded.text
            assert uploaded.json()["asset"]["type"] == "image/png"
