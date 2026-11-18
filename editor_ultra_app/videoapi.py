"""Server-only VIDEOAPI client and restart-safe generation polling.

No provider key, image base64 or request payload is returned to the UI or logged.
Generation is always an explicit, separately confirmed user action.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


BASE_URL = "https://videoapi-wheat.vercel.app"
RATIOS = {"16:9", "9:16"}
VIDEO_SECONDS = {5, 10, 20, 30}
MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
POLL_SECONDS = 5
TIMEOUT_SECONDS = 15 * 60
MAX_JSON_BYTES = 4_500_000
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
REQUEST_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


class VideoAPIError(ValueError):
    def __init__(self, code: str, message: str, status_code: int | None = None):
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def _error_from_http(status: int, body: dict) -> VideoAPIError:
    raw = body.get("error")
    detail = str(raw)[:350] if isinstance(raw, str) else "Erro não detalhado."
    explanations = {
        400: "Pedido inválido: " + detail,
        401: "Chave VIDEOAPI_KEY ausente, inválida ou bloqueada. Configure-a somente no servidor.",
        402: "Créditos insuficientes na VIDEOAPI. Recarregue seu saldo antes de gerar.",
        404: "Geração não encontrada para esta chave.",
        413: "Referências muito grandes: o JSON enviado excedeu o limite do serviço.",
        429: "Fila da VIDEOAPI cheia (até 8 pedidos pendentes). Aguarde e tente novamente.",
    }
    if status >= 500:
        message = "A VIDEOAPI apresentou falha temporária. Confira o pedido antes de reenviar para evitar cobranças duplicadas."
    else:
        message = explanations.get(status, "Falha VIDEOAPI (HTTP " + str(status) + "): " + detail)
    return VideoAPIError("http_" + str(status), message, status)


def safe_media_url(value: object) -> str | None:
    """Validate provider-supplied playback/download HTTPS links; never fetch them server-side."""
    if not isinstance(value, str) or not (0 < len(value) <= 4096):
        return None
    if value.startswith("/v1/"):
        value = BASE_URL + value
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme != "https" or not host or "." not in host or
                parsed.username or parsed.password or parsed.port not in (None, 443) or
                any(c in value for c in "\r\n\x00")):
            return None
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test")):
            return None
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not address.is_global:
                return None
        return value
    except ValueError:
        return None


def _media_fields(details: dict) -> tuple[str | None, str | None]:
    nested = details.get("result")
    nested = nested if isinstance(nested, dict) else {}
    def first(*names):
        return next((value for name in names for value in (safe_media_url(details.get(name)),
                      safe_media_url(nested.get(name))) if value), None)
    return (first("url", "preview_url", "video_url", "image_url", "output_url"),
            first("download_url", "downloadUrl", "file_url", "output_url"))


class VideoAPIClient:
    def __init__(self, api_key: str | None = None, *, transport=None):
        self._key = api_key if api_key is not None else os.environ.get("VIDEOAPI_KEY", "")
        self._transport = transport or urlopen

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        if not self._key:
            raise VideoAPIError("not_configured", "VIDEOAPI_KEY não configurada no ambiente do servidor.")
        if not re.fullmatch(r"/v1/(videos|images|key|balance)(/[A-Za-z0-9-]{1,64})?", path):
            raise VideoAPIError("invalid_route", "Rota da VIDEOAPI não permitida.")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8") if payload is not None else None
        if body is not None and len(body) > MAX_JSON_BYTES:
            raise VideoAPIError("payload_too_large", "Imagens excedem o limite de 4,5 MB do corpo JSON da VIDEOAPI.", 413)
        req = Request(
            BASE_URL + path,
            data=body,
            method=method,
            headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json",
                     "Accept": "application/json"},
        )
        try:
            with self._transport(req, timeout=25) as response:
                data = response.read(128 * 1024 + 1)
                if len(data) > 128 * 1024:
                    raise VideoAPIError("invalid_response", "Resposta da VIDEOAPI maior que o esperado.")
                parsed = json.loads(data)
                if not isinstance(parsed, dict):
                    raise ValueError("Not a JSON object")
                if method == "POST" and response.status != 202:
                    raise VideoAPIError("invalid_response", "A VIDEOAPI não confirmou a criação (HTTP 202 esperado).")
                return parsed
        except HTTPError as exc:
            try:
                details = json.loads(exc.read(4096))
            except (ValueError, OSError):
                details = {}
            raise _error_from_http(exc.code, details if isinstance(details, dict) else {}) from None
        except (URLError, TimeoutError, ConnectionError, OSError) as exc:
            # Never include exception/request repr, which might expose auth metadata.
            raise VideoAPIError("network_uncertain", "Não foi possível confirmar a comunicação com a VIDEOAPI.") from None
        except (ValueError, UnicodeError) as exc:
            if isinstance(exc, VideoAPIError):
                raise
            raise VideoAPIError("invalid_response", "A VIDEOAPI retornou JSON inválido.") from None

    def create(self, kind: str, payload: dict) -> dict:
        return self.request("POST", "/v1/" + ("videos" if kind == "video" else "images"), payload)

    def status(self, kind: str, provider_id: str) -> dict:
        if not UUID_RE.fullmatch(provider_id):
            raise VideoAPIError("invalid_id", "Identificador de geração inválido.")
        return self.request("GET", "/v1/" + ("videos" if kind == "video" else "images") + "/" + provider_id)

    def account(self) -> dict:
        result = self.request("GET", "/v1/key")
        # /v1/key may expose key metadata: whitelist only non-secret fields.
        keys = ("balance", "price_per_video", "price_per_image", "remaining_videos", "remaining_images", "tier_name")
        return {key: result[key] for key in keys if key in result}


def build_payload(kind: str, prompt: str, aspect_ratio: str, duration_seconds: int | None,
                  images: list[dict] | None = None) -> dict:
    if kind not in {"video", "image"}:
        raise VideoAPIError("kind", "Escolha vídeo ou imagem.")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 5000:
        raise VideoAPIError("prompt", "O prompt deve conter de 1 a 5.000 caracteres.")
    if aspect_ratio not in RATIOS:
        raise VideoAPIError("ratio", "Use proporção 16:9 ou 9:16.")
    payload = {"prompt": prompt.strip(), "aspect_ratio": aspect_ratio}
    if kind == "video":
        if type(duration_seconds) is not int or duration_seconds not in VIDEO_SECONDS:
            raise VideoAPIError("duration", "Use 5, 10, 20 ou 30 segundos.")
        payload["duration_seconds"] = duration_seconds
    elif duration_seconds is not None:
        raise VideoAPIError("duration", "Imagens não aceitam duration_seconds.")
    if images:
        if not isinstance(images, list) or len(images) > 3:
            raise VideoAPIError("images", "É permitido usar até 3 imagens de referência.")
        for item in images:
            if not isinstance(item, dict) or item.get("mime_type") not in MIME_TYPES:
                raise VideoAPIError("image_type", "Referência precisa ser PNG, JPEG ou WebP.")
            if not isinstance(item.get("data_base64"), str):
                raise VideoAPIError("image_data", "Imagem de referência inválida.")
        payload["images"] = images
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_JSON_BYTES:
        raise VideoAPIError("payload_too_large", "O corpo JSON com referências excede 4,5 MB.", 413)
    return payload


class VideoAPIJobs:
    """Owns paid submissions, idempotency and provider polling independently of render jobs."""

    _columns = ("job_id", "project_id", "request_id", "fingerprint", "kind", "status",
                "provider_id", "created", "updated", "next_poll", "deadline", "error",
                "url", "download_url", "expires_at", "balance", "requested_seconds", "duration_seconds")

    def __init__(self, directory: Path, client: VideoAPIClient | None = None,
                 *, clock=None):
        self.client = client or VideoAPIClient()
        self.clock = clock or time.time
        self.db_path = directory / "videoapi-jobs.sqlite3"
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS videoapi_jobs (
                job_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, request_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                provider_id TEXT, created REAL NOT NULL, updated REAL NOT NULL,
                next_poll REAL NOT NULL, deadline REAL NOT NULL, error TEXT,
                url TEXT, download_url TEXT, expires_at TEXT, balance REAL,
                requested_seconds INTEGER, duration_seconds INTEGER, retry_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(project_id, request_id)
            )""")
            # An ambiguous crash while submitting must never lead to a second paid POST.
            db.execute("UPDATE videoapi_jobs SET status='submission_uncertain', "
                       "error='Envio não confirmado após reinício. Não repita sem conferir o histórico do provedor.' "
                       "WHERE status='submitting'")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _view(self, row) -> dict | None:
        if row is None:
            return None
        return {key: row[key] for key in self._columns if key != "fingerprint"}

    def list(self, project_id: str) -> list[dict]:
        with self.lock, self._db() as db:
            return [self._view(r) for r in db.execute(
                "SELECT * FROM videoapi_jobs WHERE project_id=? ORDER BY created DESC LIMIT 30", (project_id,))]

    def get(self, project_id: str, job_id: str) -> dict | None:
        """Inspect one exact completed-generation record without submitting a new job."""
        with self.lock, self._db() as db:
            return self._view(db.execute(
                "SELECT * FROM videoapi_jobs WHERE project_id=? AND job_id=?",
                (project_id, job_id)).fetchone())

    def submit(self, project_id: str, request_id: str, kind: str, payload: dict) -> dict:
        if not REQUEST_RE.fullmatch(request_id):
            raise VideoAPIError("request_id", "Identificador da solicitação inválido.")
        digest = hashlib.sha256(json.dumps({"kind": kind, "payload": payload}, sort_keys=True).encode()).hexdigest()
        now = self.clock()
        with self.lock, self._db() as db:
            previous = db.execute("SELECT * FROM videoapi_jobs WHERE project_id=? AND request_id=?",
                                  (project_id, request_id)).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise VideoAPIError("request_conflict", "Identificador já utilizado para outro pedido.")
                return self._view(previous)
            db.execute("""INSERT INTO videoapi_jobs
                (job_id,project_id,request_id,fingerprint,kind,status,created,updated,next_poll,deadline,requested_seconds)
                VALUES (?,?,?,?,?,'submitting',?,?,?,?,?)""",
                (str(uuid4()), project_id, request_id, digest, kind, now, now, now + POLL_SECONDS,
                 now + TIMEOUT_SECONDS, payload.get("duration_seconds")))
            saved = db.execute("SELECT * FROM videoapi_jobs WHERE project_id=? AND request_id=?",
                               (project_id, request_id)).fetchone()
            job_id = saved["job_id"]
        try:
            created = self.client.create(kind, payload)
            provider_id = created.get("id")
            if not isinstance(provider_id, str) or not UUID_RE.fullmatch(provider_id):
                raise VideoAPIError("submission_uncertain", "O provedor não devolveu um ID válido. Confira o histórico antes de reenviar.")
            with self.lock, self._db() as db:
                db.execute("""UPDATE videoapi_jobs SET status='queued',provider_id=?,balance=?,updated=?,next_poll=?
                              WHERE job_id=?""", (provider_id, created.get("balance"), self.clock(),
                                                  self.clock() + POLL_SECONDS, job_id))
        except VideoAPIError as exc:
            # A clear 4xx failure means no job was accepted. Network/5xx/invalid reply are ambiguous.
            definite = exc.status_code is not None and 400 <= exc.status_code < 500
            with self.lock, self._db() as db:
                db.execute("UPDATE videoapi_jobs SET status=?,error=?,updated=? WHERE job_id=?",
                           ("request_rejected" if definite else "submission_uncertain", str(exc),
                            self.clock(), job_id))
        with self.lock, self._db() as db:
            return self._view(db.execute("SELECT * FROM videoapi_jobs WHERE job_id=?", (job_id,)).fetchone())

    def recover_media(self, project_id: str, job_id: str) -> dict:
        """GET-only recovery for a completed job; never submits or charges a second generation."""
        with self.lock, self._db() as db:
            row = db.execute("SELECT * FROM videoapi_jobs WHERE project_id=? AND job_id=?",
                             (project_id, job_id)).fetchone()
        if row is None:
            raise VideoAPIError("job_missing", "Geração não encontrada neste projeto.")
        if row["status"] != "done" or not row["provider_id"]:
            raise VideoAPIError("not_done", "A geração ainda não terminou.")
        details = self.client.status(row["kind"], row["provider_id"])
        if details.get("status") != "done":
            raise VideoAPIError("provider_not_done", "O provedor ainda não disponibilizou a mídia.")
        preview, download = _media_fields(details)
        if not preview and not download:
            keys = ", ".join(sorted(k for k in details if isinstance(k, str) and
                                     k not in {"prompt", "images", "metadata", "api_key"}))[:240]
            raise VideoAPIError("media_missing", "Vídeo concluído, mas sem URLs compatíveis. Campos retornados: " + keys)
        with self.lock, self._db() as db:
            db.execute("""UPDATE videoapi_jobs SET url=?,download_url=?,expires_at=?,updated=?
                          WHERE project_id=? AND job_id=? AND status='done'""",
                       (preview or row["url"], download or row["download_url"],
                        details.get("expires_at") or row["expires_at"], self.clock(), project_id, job_id))
            updated = db.execute("SELECT * FROM videoapi_jobs WHERE project_id=? AND job_id=?",
                                 (project_id, job_id)).fetchone()
        return self._view(updated)

    def poll_due(self):
        now = self.clock()
        with self.lock, self._db() as db:
            rows = db.execute("""SELECT * FROM videoapi_jobs WHERE status IN ('queued','generating','poll_retry')
                                 AND next_poll<=? ORDER BY next_poll LIMIT 10""", (now,)).fetchall()
        for row in rows:
            if now >= row["deadline"]:
                with self.lock, self._db() as db:
                    db.execute("""UPDATE videoapi_jobs SET status='timeout',
                        error='Limite de 15 minutos atingido. O provedor pode continuar trabalhando; confira o histórico antes de reenviar.',
                        updated=? WHERE job_id=? AND status IN ('queued','generating','poll_retry')""",
                        (now, row["job_id"]))
                continue
            try:
                details = self.client.status(row["kind"], row["provider_id"])
                status = details.get("status")
                if status not in {"queued", "generating", "done", "failed"}:
                    raise VideoAPIError("invalid_status", "Status desconhecido retornado pelo provedor.")
                preview, download = _media_fields(details)
                with self.lock, self._db() as db:
                    db.execute("""UPDATE videoapi_jobs SET status=?,updated=?,next_poll=?,error=?,
                                  url=?,download_url=?,expires_at=?,duration_seconds=?,retry_count=0
                                  WHERE job_id=? AND status IN ('queued','generating','poll_retry')""",
                               (status, now, now + POLL_SECONDS,
                                str(details.get("error") or "Falha sem detalhes.")[:1000] if status == "failed" else None,
                                preview if status == "done" else None,
                                download if status == "done" else None,
                                details.get("expires_at") if status == "done" else None,
                                details.get("duration_seconds") if status == "done" else None,
                                row["job_id"]))
            except VideoAPIError as exc:
                # GET errors never re-submit a paid generation. Back off temporary failures.
                attempts = min(8, row["retry_count"] + 1)
                if exc.status_code in {401, 402, 404}:
                    next_status, delay = "poll_error", POLL_SECONDS
                elif exc.status_code == 429:
                    next_status, delay = "poll_retry", max(15, POLL_SECONDS * (2 ** (attempts - 1)))
                else:
                    next_status, delay = "poll_retry", min(120, POLL_SECONDS * (2 ** (attempts - 1)))
                with self.lock, self._db() as db:
                    db.execute("UPDATE videoapi_jobs SET status=?,error=?,updated=?,next_poll=?,retry_count=? WHERE job_id=?",
                               (next_status, str(exc), now, now + delay, attempts, row["job_id"]))

    def _loop(self):
        while not self.stop_event.wait(1):
            try:
                self.poll_due()
            except Exception:
                # Worker exceptions must never expose credentials or crash the studio.
                pass

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, name="editor-videoapi-poller", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            self.thread = None
