"""No-cost VIDEOAPI result import, exact-host egress and immutable media proof."""
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import time

import pytest
from starlette.testclient import TestClient

from editorial_engine.contracts import file_sha256
from editor_ultra_app.server import create_app
from editor_ultra_app.videoapi import VideoAPIError, VideoAPIJobs, build_payload
from editor_ultra_app.videoapi_import import (
    DEFAULT_HOSTS, download_completed_video, verified_origin, _pinned_get,
)
from scripts.check_app_connection import authorize_owner

BASE = "https://editor.example"
KEY = "test-only-import-owner-key-012345678901234567890"
GOOD_URL = "https://www.videoapi.com.br/generated/clip.mp4?token=test"


class Response:
    def __init__(self, status, contents=b"", headers=None):
        self.status = status
        self.body = BytesIO(contents)
        self.headers = headers or {}
    def getheader(self, name):
        return next((v for k, v in self.headers.items() if k.lower() == name.lower()), None)
    def read(self, number):
        return self.body.read(number)


class Connection:
    def __init__(self):
        self.closed = False
    def close(self):
        self.closed = True


def test_only_verified_provider_hosts_and_no_unsafe_redirects(tmp_path):
    assert "www.videoapi.com.br" in DEFAULT_HOSTS
    assert verified_origin(GOOD_URL) == GOOD_URL
    for address in [
        "http://www.videoapi.com.br/video.mp4",
        "https://127.0.0.1/private.mp4", "https://localhost/admin",
        "https://evil.example/media.mp4", "https://www.videoapi.com.br:8443/video.mp4",
        "https://www.videoapi.com.br/video.mp4#fragment",
    ]:
        with pytest.raises(VideoAPIError):
            verified_origin(address)
    calls = []
    def redirect(url):
        calls.append(url)
        return Connection(), Response(302, headers={"Location": "https://localhost/private"})
    with pytest.raises(VideoAPIError, match="domínio"):
        download_completed_video(GOOD_URL, tmp_path, fetch=redirect)
    assert calls == [GOOD_URL]
    assert list(tmp_path.iterdir()) == []


def test_provider_download_enforces_bytes_mime_and_cleanup(tmp_path):
    clip = b"\x00\x00\x00\x18ftypmp42test-video"
    visits = []
    def valid(url):
        visits.append(url)
        return Connection(), Response(200, clip, {"Content-Type": "video/mp4",
                                                   "Content-Length": str(len(clip))})
    downloaded = download_completed_video(GOOD_URL, tmp_path, max_bytes=100, fetch=valid)
    assert downloaded.read_bytes() == clip and visits == [GOOD_URL]
    downloaded.unlink()
    with pytest.raises(VideoAPIError, match="limite"):
        download_completed_video(GOOD_URL, tmp_path, max_bytes=8, fetch=valid)
    assert not list(tmp_path.iterdir())
    def malformed(url):
        return Connection(), Response(200, b'{"not":"mp4"}', {"Content-Type": "application/json"})
    with pytest.raises(VideoAPIError, match="arquivo de vídeo"):
        download_completed_video(GOOD_URL, tmp_path, fetch=malformed)
    assert not list(tmp_path.iterdir())


def test_dns_rebinding_to_private_ip_is_rejected(monkeypatch):
    import editor_ultra_app.videoapi_import as module
    monkeypatch.setattr(module.socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(VideoAPIError, match="endereços públicos"):
        _pinned_get(GOOD_URL)


def structured(response):
    assert not response.get("isError"), response
    return response["structuredContent"]


class FakeProvider:
    def __init__(self):
        self.submissions = 0
    def create(self, kind, payload):
        self.submissions += 1
        return {"id": "11111111-1111-1111-1111-111111111111"}
    def status(self, kind, provider_id):
        raise AssertionError("Import must never ask to generate or regenerate media")


def generated_video(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required for actual media admission")
    clip = tmp_path / "synthetic-provider.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=160x90:rate=10:duration=1",
                    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                   check=True, timeout=30)
    return clip


def set_done(directory, project_id, kind="video"):
    provider = FakeProvider()
    jobs = VideoAPIJobs(directory, client=provider)
    record = jobs.submit(project_id, "videoapi-import-test", kind,
                         build_payload(kind, "Synthetic provider fixture", "16:9",
                                       5 if kind == "video" else None))
    with jobs._db() as db:
        db.execute("UPDATE videoapi_jobs SET status='done', url=?, download_url=? WHERE job_id=?",
                   (GOOD_URL, GOOD_URL, record["job_id"]))
    assert provider.submissions == 1
    return record["job_id"], provider


def wait_job(session, project_id, job_id):
    for _ in range(120):
        value = structured(session.call_tool("editor_get_project", {"project_id": project_id}))
        job = next(j for j in value["jobs"] if j["id"] == job_id)
        if job["status"] not in {"queued", "running"}:
            return job, value
        time.sleep(.05)
    pytest.fail("VIDEOAPI import did not settle")


def test_completed_generated_video_is_imported_once_into_real_project(monkeypatch, tmp_path):
    directory = tmp_path / "private"
    app = create_app(data_dir=directory, base_url=BASE, owner_key=KEY)
    video = generated_video(tmp_path)
    copied = []
    def provider_download(url, folder, *, max_bytes):
        assert url == GOOD_URL and max_bytes >= video.stat().st_size
        assert "private" in str(folder)
        copied.append(url)
        folder.mkdir(exist_ok=True)
        target = folder / ("import-" + str(len(copied)) + ".mp4")
        target.write_bytes(video.read_bytes())
        return target
    monkeypatch.setattr("editor_ultra_app.server.download_completed_video", provider_download)
    with TestClient(app, base_url=BASE) as client:
        with authorize_owner(BASE, KEY, client=client) as session:
            tools = {tool["name"] for tool in session.rpc("tools/list")["tools"]}
            assert "editor_import_videoapi_result" in tools
            project = structured(session.call_tool("editor_save_project", {
                "state": {"objective": "Collect completed VIDEOAPI media", "mode": "ready"},
            }))
            pid = project["project_id"]
            job_id, provider = set_done(directory, pid)
            args = {"project_id": pid, "videoapi_job_id": job_id,
                    "expected_revision": project["revision"], "request_id": "import-existing-videoapi-001"}
            first = structured(session.call_tool("editor_import_videoapi_result", args))
            queued, state = wait_job(session, pid, first["id"])
            assert queued["status"] == "completed", queued
            completed = queued["result"]
            assert completed["status"] == "videoapi_imported"
            assert completed["asset"]["role"] == "footage"
            assert completed["asset"]["provenance"]["provider"] == "VIDEOAPI"
            assert completed["asset"]["provenance"]["job_id"] == job_id
            assert completed["asset"]["hostFileId"] == "videoapi:" + job_id
            imported = structured(session.call_tool("editor_get_asset", {
                "project_id": pid, "asset_id": completed["asset_id"]}))
            assert client.get(imported["url"]).content == video.read_bytes()
            assert completed["asset"]["sha256"] == file_sha256(video)
            assert state["state"]["assets"]["footage"][0]["id"] == completed["asset_id"]
            assert provider.submissions == 1 and copied == [GOOD_URL]
            duplicate = structured(session.call_tool("editor_import_videoapi_result", args))
            assert duplicate["id"] == first["id"] and duplicate["status"] == "completed"
            next_args = {**args, "expected_revision": state["revision"],
                         "request_id": "import-existing-videoapi-002"}
            next_job = structured(session.call_tool("editor_import_videoapi_result", next_args))
            verified, next_state = wait_job(session, pid, next_job["id"])
            assert verified["status"] == "completed"
            assert verified["result"]["idempotent"] is True
            assert copied == [GOOD_URL] and len(next_state["state"]["assets"]["footage"]) == 1


def test_image_job_cannot_be_imported_as_video(monkeypatch, tmp_path):
    directory = tmp_path / "private"
    app = create_app(data_dir=directory, base_url=BASE, owner_key=KEY)
    monkeypatch.setattr("editor_ultra_app.server.download_completed_video",
                        lambda *a, **k: pytest.fail("Image job was downloaded"))
    with TestClient(app, base_url=BASE) as client:
        with authorize_owner(BASE, KEY, client=client) as session:
            project = structured(session.call_tool("editor_save_project", {
                "state": {"objective": "No image conversion"},
            }))
            job_id, _ = set_done(directory, project["project_id"], kind="image")
            receipt = structured(session.call_tool("editor_import_videoapi_result", {
                "project_id": project["project_id"], "videoapi_job_id": job_id,
                "expected_revision": project["revision"], "request_id": "reject-image-import-001"}))
            complete, _ = wait_job(session, project["project_id"], receipt["id"])
            assert complete["status"] == "failed" and "vídeo concluída" in complete["error"]
