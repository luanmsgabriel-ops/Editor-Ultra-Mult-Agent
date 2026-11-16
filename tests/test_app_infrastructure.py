import base64
import io
import json
from pathlib import Path
import sqlite3
import stat
import time
import zipfile

import pytest
from PIL import Image

from editor_ultra_app.catalog import Catalog
from editor_ultra_app.jobs import JobQueue
from editor_ultra_app.media import PreviewSigner, allowed_file_url


def test_queue_runs_once_and_preserves_failed_and_interrupted_states(tmp_path):
    calls = []
    queue = JobQueue(tmp_path, lambda job: calls.append(job) or {"actual": True})
    first = queue.enqueue("project", "render", {"kind": "edit"}, "request-123")
    same = queue.enqueue("project", "render", {"kind": "edit"}, "request-123")
    assert first["id"] == same["id"]
    with pytest.raises(ValueError, match="outro pedido"):
        queue.enqueue("project", "render", {"kind": "clone"}, "request-123")
    assert queue._run_one()
    assert not queue._run_one()
    assert len(calls) == 1
    assert queue.get("project", first["id"])["result"] == {"actual": True}
    with pytest.raises(ValueError, match="encontrado"):
        queue.get("other-project", first["id"])
    second = queue.enqueue("project", "render", {}, "request-456")
    with queue._db() as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?", (second["id"],))
    resumed = JobQueue(tmp_path, lambda _: pytest.fail("Unknown job must not run again"))
    assert resumed.get("project", second["id"])["status"] == "interrupted"
    assert not resumed._run_one()


def test_queue_failure_is_not_a_successful_result(tmp_path):
    def fail(job):
        raise ValueError("Missing source")
    queue = JobQueue(tmp_path, fail)
    receipt = queue.enqueue("project", "prepare", {}, "request-789")
    queue._run_one()
    result = queue.get("project", receipt["id"])
    assert result["status"] == "failed" and result["result"] is None
    assert result["error"] == "Missing source"


@pytest.mark.parametrize("url", [
    "http://files.oaiusercontent.com/a", "https://files.oaiusercontent.com.evil.test/a",
    "https://localhost/a", "https://127.0.0.1/a", "file:///etc/passwd",
    "https://metadata.google.internal/", "https://user:pw@files.oaiusercontent.com/a",
    "https://files.oaiusercontent.com:8443/a", "https://drive.google.com/file/1",
])
def test_file_admission_rejects_arbitrary_urls(url):
    with pytest.raises(ValueError):
        allowed_file_url(url)


def test_file_admission_accepts_chatgpt_attachment_origin_only():
    assert allowed_file_url("https://files.oaiusercontent.com/file-abc?sig=opaque") == "files.oaiusercontent.com"


def test_preview_signature_cannot_be_reused_for_another_file(tmp_path):
    from urllib.parse import parse_qs, urlsplit
    signer = PreviewSigner(tmp_path, "https://editor.example.test", "owner" * 10)
    source = tmp_path / "a.mp4"
    source.write_bytes(b"source")
    other = tmp_path / "b.mp4"
    other.write_bytes(b"other")
    params = parse_qs(urlsplit(signer.url(source)).query)
    expires, signature = params["expires"][0], params["signature"][0]
    assert signer.resolve("a.mp4", expires, signature) == source
    with pytest.raises(ValueError):
        signer.resolve("b.mp4", expires, signature)
    with pytest.raises(ValueError):
        signer.resolve("../a.mp4", expires, signature)
    with pytest.raises(ValueError):
        signer.resolve("a.mp4", str(int(time.time()) - 10), signature)
    private = tmp_path / "auth.sqlite3"
    private.write_bytes(b"credentials")
    with pytest.raises(ValueError):
        params = parse_qs(urlsplit(signer.url(private)).query)
        signer.resolve("auth.sqlite3", params["expires"][0], params["signature"][0])


def test_catalog_keeps_previews_private_and_rejects_zip_traversal(tmp_path):
    data = tmp_path / "data"
    signer = PreviewSigner(data, "https://editor.example.test", "owner" * 10)
    catalog = Catalog(data, signer)
    image = io.BytesIO()
    Image.new("RGB", (16, 16), "blue").save(image, format="WEBP")
    gallery = [{"id": "sample", "title": "Sample", "thumbnail": "data:image/webp;base64," + base64.b64encode(image.getvalue()).decode(),
                "previewMode": "sample", "runtime_executed": False}]
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("gallery.json", json.dumps(gallery))
    receipt = catalog.install(archive)
    assert receipt["count"] == 1 and not receipt["runtime_executed"]
    item = catalog.list_templates()["templates"][0]
    assert item["thumbnail"].startswith("https://editor.example.test/media/")
    assert "signature=" in item["thumbnail"]
    assert not item["runtime_executed"]
    invalid = tmp_path / "invalid.zip"
    with zipfile.ZipFile(invalid, "w") as z:
        z.writestr("../../escape", "unsafe")
    with pytest.raises(ValueError):
        catalog.install(invalid)
    assert not (tmp_path / "escape").exists()
    assert catalog.status()["count"] == 1
