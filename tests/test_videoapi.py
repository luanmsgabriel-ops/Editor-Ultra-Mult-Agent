"""VIDEOAPI contract tests: all cases are local, no paid generations."""
import io
import json
from urllib.error import HTTPError

import pytest

from editor_ultra_app.videoapi import (
    BASE_URL, POLL_SECONDS, VideoAPIClient, VideoAPIError, VideoAPIJobs, build_payload, safe_media_url,
)


class HTTPResponse:
    def __init__(self, status, data):
        self.status = status
        self.data = json.dumps(data).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size):
        return self.data[:size]


def test_backend_only_bearer_json_and_202_creation():
    observed = []
    def transport(request, timeout):
        observed.append((request.full_url, request.get_method(), request.headers, request.data, timeout))
        return HTTPResponse(202, {"id": "11111111-1111-1111-1111-111111111111", "status": "queued"})
    client = VideoAPIClient("test-key-not-real", transport=transport)
    payload = build_payload("video", "cinematic test", "9:16", 10)
    assert client.create("video", payload)["status"] == "queued"
    url, method, headers, body, timeout = observed[0]
    assert url == BASE_URL + "/v1/videos" and method == "POST"
    assert headers["Authorization"] == "Bearer test-key-not-real"
    assert headers["Content-type"] == "application/json"
    assert json.loads(body) == payload
    assert b"test-key-not-real" not in body
    assert timeout == 25


@pytest.mark.parametrize("status,phrase", [
    (401, "VIDEOAPI_KEY"), (402, "Créditos insuficientes"),
    (413, "grandes"), (429, "Fila"), (503, "temporária"),
])
def test_user_safe_http_errors(status, phrase):
    def transport(request, timeout):
        raise HTTPError(request.full_url, status, "failure", {}, io.BytesIO(b'{"error":"denied"}'))
    client = VideoAPIClient("secret-key", transport=transport)
    with pytest.raises(VideoAPIError) as err:
        client.create("image", build_payload("image", "imagem", "16:9", None))
    assert phrase in str(err.value)
    assert "secret-key" not in str(err.value)
    assert err.value.status_code == status


def test_restrict_payload_image_and_video_contracts():
    assert build_payload("video", "cena", "9:16", 5)["duration_seconds"] == 5
    assert "duration_seconds" not in build_payload("image", "cena", "16:9", None)
    with pytest.raises(VideoAPIError):
        build_payload("video", "cena", "1:1", 10)
    with pytest.raises(VideoAPIError):
        build_payload("video", "cena", "9:16", 8)
    with pytest.raises(VideoAPIError):
        build_payload("image", "cena", "9:16", 10)
    with pytest.raises(VideoAPIError):
        build_payload("video", " ", "9:16", 10)
    with pytest.raises(VideoAPIError):
        build_payload("image", "a", "9:16", None, [{"mime_type": "image/svg+xml", "data_base64": "a"}])
    with pytest.raises(VideoAPIError, match="4,5 MB"):
        build_payload("image", "a", "9:16", None, [{"mime_type": "image/png", "data_base64": "A" * 4_500_001}])


PROVIDER_ID = "11111111-1111-1111-1111-111111111111"


class Provider:
    def __init__(self):
        self.creations = []
        self.checks = []
        self.responses = []

    def create(self, kind, payload):
        self.creations.append((kind, payload))
        return {"id": PROVIDER_ID, "balance": 80}

    def status(self, kind, id_):
        self.checks.append((kind, id_))
        return self.responses.pop(0)


@pytest.mark.parametrize("kind", ["video", "image"])
def test_durable_idempotent_jobs_and_five_second_polling(tmp_path, kind):
    seconds = [100.0]
    provider = Provider()
    jobs = VideoAPIJobs(tmp_path, provider, clock=lambda: seconds[0])
    payload = build_payload(kind, "teste", "9:16", 10 if kind == "video" else None)
    first = jobs.submit("project1", "req1", kind, payload)
    assert first["status"] == "queued" and first["provider_id"] == PROVIDER_ID
    assert first["balance"] == 80
    second = jobs.submit("project1", "req1", kind, payload)
    assert second["job_id"] == first["job_id"] and len(provider.creations) == 1
    with pytest.raises(VideoAPIError, match="Identificador"):
        jobs.submit("project1", "req1", kind, dict(payload, prompt="outro"))
    assert jobs.list("project-other") == []
    provider.responses = [
        {"id": PROVIDER_ID, "status": "generating"},
        {"id": PROVIDER_ID, "status": "done", "url": BASE_URL + "/v1/" + ("videos" if kind == "video" else "images") + "/" + PROVIDER_ID + "/preview",
         "download_url": BASE_URL + "/v1/" + ("videos" if kind == "video" else "images") + "/" + PROVIDER_ID + "/download",
         "duration_seconds": 10 if kind == "video" else None,
         "expires_at": "2026-11-18T12:00:00.000Z"},
    ]
    seconds[0] += 4
    jobs.poll_due()
    assert provider.checks == []
    seconds[0] += 1
    jobs.poll_due()
    assert jobs.list("project1")[0]["status"] == "generating"
    seconds[0] += POLL_SECONDS
    jobs.poll_due()
    result = jobs.list("project1")[0]
    assert result["status"] == "done" and result["url"].endswith("/preview")
    assert result["download_url"].endswith("/download")
    assert result["expires_at"] == "2026-11-18T12:00:00.000Z"
    resumed = VideoAPIJobs(tmp_path, provider, clock=lambda: seconds[0])
    assert resumed.list("project1")[0]["status"] == "done"
    assert len(provider.creations) == 1


def test_failed_job_does_not_submit_again_and_keeps_provider_error(tmp_path):
    now = [10.0]
    provider = Provider()
    jobs = VideoAPIJobs(tmp_path, provider, clock=lambda: now[0])
    jobs.submit("p", "req", "video", build_payload("video", "cena", "16:9", 20))
    provider.responses = [{"status": "failed", "error": "render issue"}]
    now[0] += 5
    jobs.poll_due()
    assert jobs.list("p")[0]["status"] == "failed"
    assert jobs.list("p")[0]["error"] == "render issue"
    now[0] += 5
    jobs.poll_due()
    assert len(provider.checks) == 1


def test_timeout_is_not_incorrectly_labeled_as_refunded(tmp_path):
    now = [0.0]
    provider = Provider()
    jobs = VideoAPIJobs(tmp_path, provider, clock=lambda: now[0])
    jobs.submit("p", "req", "image", build_payload("image", "paisagem", "16:9", None))
    now[0] = 905
    jobs.poll_due()
    row = jobs.list("p")[0]
    assert row["status"] == "timeout"
    assert "pode continuar" in row["error"]
    assert provider.checks == []


def test_unknown_post_result_is_never_automatically_retried(tmp_path):
    class Uncertain(Provider):
        def create(self, kind, payload):
            self.creations.append((kind, payload))
            raise VideoAPIError("network_uncertain", "Resposta desconhecida")
    provider = Uncertain()
    jobs = VideoAPIJobs(tmp_path, provider)
    payload = build_payload("video", "cena", "9:16", 5)
    first = jobs.submit("p", "req", "video", payload)
    assert first["status"] == "submission_uncertain"
    assert jobs.submit("p", "req", "video", payload)["job_id"] == first["job_id"]
    jobs.poll_due()
    assert len(provider.creations) == 1


def test_retries_transient_poll_errors_with_exponential_backoff(tmp_path):
    now = [0.0]
    class Flaky(Provider):
        def status(self, kind, id_):
            self.checks.append(id_)
            if len(self.checks) < 3:
                raise VideoAPIError("http_503", "temporário", 503)
            return {"status": "done", "url": BASE_URL + "/v1/videos/" + id_ + "/preview",
                    "download_url": BASE_URL + "/v1/videos/" + id_ + "/download"}
    provider = Flaky()
    jobs = VideoAPIJobs(tmp_path, provider, clock=lambda: now[0])
    jobs.submit("p", "req", "video", build_payload("video", "cena", "9:16", 10))
    now[0] = 5
    jobs.poll_due()
    assert jobs.list("p")[0]["status"] == "poll_retry"
    now[0] = 9
    jobs.poll_due()
    assert len(provider.checks) == 1
    now[0] = 10
    jobs.poll_due()
    assert len(provider.checks) == 2
    now[0] = 20
    jobs.poll_due()
    assert jobs.list("p")[0]["status"] == "done"


@pytest.mark.parametrize("candidate", [
    "javascript:alert(1)", "http://cdn.test/video.mp4",
    "https://localhost/video.mp4", "https://127.0.0.1/media.mp4",
    "https://user:pass@cdn.example.com/file.mp4", "https://10.0.0.1/file.mp4",
    "https://cdn.example.com:8443/video.mp4", "https://cdn.test/file.mp4",
])
def test_external_media_url_rejects_unsafe_sources(candidate):
    assert safe_media_url(candidate) is None


def test_external_https_media_url_and_recovery_are_read_only(tmp_path):
    preview = "https://cdn.example.com/generated/preview.mp4?signature=abcdef"
    download = "https://cdn.example.com/generated/video.mp4?signature=abcdef"
    assert safe_media_url(preview) == preview
    assert safe_media_url("/v1/videos/abc/download") == BASE_URL + "/v1/videos/abc/download"
    now = [100.0]
    provider = Provider()
    jobs = VideoAPIJobs(tmp_path, provider, clock=lambda: now[0])
    jobs.submit("project", "one-request", "video", build_payload("video", "teste", "9:16", 5))
    provider.responses = [{"status": "done", "url": preview, "download_url": download,
                           "expires_at": "2026-11-19T10:00:00Z"}]
    now[0] = 105
    jobs.poll_due()
    done = jobs.list("project")[0]
    assert done["status"] == "done"
    assert done["url"] == preview and done["download_url"] == download
    with jobs._db() as db:
        db.execute("UPDATE videoapi_jobs SET url=NULL,download_url=NULL WHERE job_id=?", (done["job_id"],))
    provider.responses = [{"status": "done", "url": preview, "download_url": download}]
    result = jobs.recover_media("project", done["job_id"])
    assert result["status"] == "done" and result["url"] == preview and result["download_url"] == download
    assert len(provider.creations) == 1
    with pytest.raises(VideoAPIError, match="não encontrada"):
        jobs.recover_media("other-project", done["job_id"])
