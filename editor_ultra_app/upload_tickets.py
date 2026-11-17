"""Short, single-file upload capabilities; no OAuth or owner secrets enter the UI.

The durable ledger contains hashes and immutable destinations, never plaintext
capabilities or cached project snapshots. A receiving claim survives a lost HTTP
response; after process restart the engine's direct:UUID receipt is authoritative.
This service deliberately runs as one process over one private volume.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import hashlib
import hmac
import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

from .media import MAX_FILE_BYTES
from .clone_resources import MAX_RESOURCE_BYTES, RESOURCE_TYPES


TICKET_TTL_SECONDS = 300
MAX_PENDING = 64
MAX_RECORDS = 4096
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_ROLES = {"ref", "clone", "footage", "identity", "narration", "logo", "result", "shot", "clone_resource"}


class UploadTicketError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.status = code, status
        super().__init__(message)


def _fail(code: str, message: str, status: int = 400):
    raise UploadTicketError(code, message, status)


def _identifier(value: str) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value)) and ".." not in value


def _upload_id(value: str) -> bool:
    try:
        return isinstance(value, str) and len(value) == 36 and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


@dataclass(frozen=True)
class UploadBinding:
    upload_id: str
    project_id: str
    role: str
    expected_revision: int
    file_name: str
    mime_type: str
    size_bytes: int
    shot_id: str | None = None

    def __post_init__(self):
        if not _upload_id(self.upload_id) or not _identifier(self.project_id):
            _fail("upload_identifier", "Use os identificadores do projeto e do envio atual.")
        if self.role not in _ROLES or (self.shot_id is not None and not _identifier(self.shot_id)):
            _fail("upload_destination", "Escolha um papel e uma tomada válidos para o arquivo.")
        if (self.role == "shot") != (self.shot_id is not None):
            _fail("upload_destination", "A tomada é obrigatória e exclusiva para um clipe devolvido.")
        if type(self.expected_revision) is not int or self.expected_revision < 0:
            _fail("upload_revision", "A revisão atual do projeto é obrigatória.")
        if (not isinstance(self.file_name, str) or not 1 <= len(self.file_name) <= 240
                or self.file_name in {".", ".."} or not self.file_name.strip()
                or any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in self.file_name)):
            _fail("upload_filename", "Use apenas o nome do arquivo, sem caminho.")
        if not isinstance(self.mime_type, str) or len(self.mime_type) > 150 or not _MIME.fullmatch(self.mime_type):
            _fail("upload_mime", "O formato de mídia declarado é inválido.")
        if type(self.size_bytes) is not int or not 0 < self.size_bytes <= MAX_FILE_BYTES:
            _fail("upload_size", "O arquivo deve ter conteúdo e até 512 MiB.", 413)
        allowed = {"narration": ("audio/",), "logo": ("image/",), "footage": ("video/",),
                   "result": ("video/",), "shot": ("video/",)}.get(self.role, ("video/", "image/"))
        if self.role == "clone_resource":
            if self.engine_mime not in RESOURCE_TYPES:
                _fail("upload_mime", "Use PNG, JSON, ZIP de máscaras, TTF ou OTF.", 415)
            if self.size_bytes > MAX_RESOURCE_BYTES:
                _fail("upload_size", "O recurso de clonagem deve ter até 40 MiB.", 413)
        elif not self.engine_mime.startswith(allowed):
            _fail("upload_mime", "O formato do arquivo não corresponde ao papel escolhido.", 415)

    @property
    def host_file_id(self) -> str:
        return "direct:" + self.upload_id

    @property
    def engine_mime(self) -> str:
        # Some browsers omit File.type. The wire type stays bound exactly; the
        # engine still inspects actual media before admitting this inferred type.
        if self.mime_type == "application/octet-stream":
            return mimetypes.guess_type(self.file_name)[0] or self.mime_type
        return self.mime_type

    def identity(self) -> str:
        value = asdict(self)
        # A new ticket may use the latest revision after an explicit retry, but
        # its UUID cannot be redirected to another file, project, role or shot.
        value.pop("expected_revision")
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class UploadClaim:
    binding: UploadBinding
    digest: str = field(repr=False)
    completed: bool = False
    asset_id: str | None = None


class UploadTicketStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "upload-tickets.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ValueError("Upload ledger must be a private regular file")
        handle = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(handle)
        self.path.chmod(0o600)
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tickets (
                    upload_id TEXT PRIMARY KEY, identity TEXT NOT NULL,
                    expected_revision INTEGER NOT NULL, digest TEXT NOT NULL,
                    expires INTEGER NOT NULL, state TEXT NOT NULL,
                    asset_id TEXT, created REAL NOT NULL, updated REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS limits (
                    action TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL
                );
            """)
            # Never retry an interrupted stream on startup. The next authenticated
            # begin checks the engine receipt before it can mint a new capability.
            db.execute("UPDATE tickets SET state='failed', digest='', expires=0 WHERE state='receiving'")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _rate(self, action: str, limit: int):
        with self._db() as db:
            self._rate_db(db, action, limit)

    @staticmethod
    def _rate_db(db, action: str, limit: int):
        now = time.time()
        row = db.execute("SELECT count,expires FROM limits WHERE action=?", (action,)).fetchone()
        if row and row["expires"] > now and row["count"] >= limit:
            _fail("upload_rate_limit", "Aguarde um minuto antes de repetir o envio.", 429)
        if row and row["expires"] > now:
            db.execute("UPDATE limits SET count=count+1 WHERE action=?", (action,))
        else:
            db.execute("INSERT OR REPLACE INTO limits VALUES (?,?,?)", (action, 1, now + 60))

    @staticmethod
    def _same(row, binding: UploadBinding):
        if row and row["identity"] != binding.identity():
            _fail("upload_id_conflict", "Este envio já pertence a outro arquivo ou destino. Selecione o arquivo novamente.", 409)

    def check_binding(self, binding: UploadBinding):
        with self._db() as db:
            self._same(db.execute("SELECT identity FROM tickets WHERE upload_id=?", (binding.upload_id,)).fetchone(), binding)

    def issue(self, binding: UploadBinding) -> tuple[str, int]:
        self._rate("issue", 60)
        now = time.time()
        token, expires = secrets.token_urlsafe(32), int(now) + TICKET_TTL_SECONDS
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._db() as db:
            row = db.execute("SELECT * FROM tickets WHERE upload_id=?", (binding.upload_id,)).fetchone()
            self._same(row, binding)
            if row and row["state"] in {"receiving", "completed"}:
                _fail("upload_in_progress" if row["state"] == "receiving" else "upload_already_received",
                      "Confira o recebimento no projeto antes de tentar novamente.", 409)
            if not row and db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] >= MAX_RECORDS:
                _fail("upload_ledger_full", "O registro privado de envios atingiu seu limite.", 429)
            pending = db.execute("SELECT COUNT(*) FROM tickets WHERE upload_id != ? AND "
                                 "(state='receiving' OR (state='issued' AND expires>?))",
                                 (binding.upload_id, now)).fetchone()[0]
            if pending >= MAX_PENDING:
                _fail("upload_pending_limit", "Há envios pendentes demais. Conclua ou aguarde os envios atuais.", 429)
            db.execute("""INSERT INTO tickets VALUES (?,?,?,?,?,'issued',NULL,?,?)
                ON CONFLICT(upload_id) DO UPDATE SET expected_revision=excluded.expected_revision,
                    digest=excluded.digest, expires=excluded.expires, state='issued', updated=excluded.updated""",
                       (binding.upload_id, binding.identity(), binding.expected_revision, digest, expires, now, now))
        return token, expires

    def claim(self, upload_id: str, token: str, content_type: str, content_length: str | None) -> UploadClaim:
        if not _upload_id(upload_id) or not isinstance(token, str) or not _TOKEN.fullmatch(token):
            _fail("upload_ticket_invalid_or_expired", "A autorização de envio é inválida ou expirou.", 401)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._db() as db:
            row = db.execute("SELECT * FROM tickets WHERE upload_id=?", (upload_id,)).fetchone()
            if (not row or not hmac.compare_digest(row["digest"], digest)
                    or row["expires"] <= time.time() or row["state"] == "failed"):
                _fail("upload_ticket_invalid_or_expired", "A autorização de envio é inválida ou expirou.", 401)
            # Invalid capabilities cannot exhaust the legitimate owner's quota.
            self._rate_db(db, "claim", 120)
            binding = UploadBinding(**json.loads(row["identity"]), expected_revision=row["expected_revision"])
            if content_type != binding.mime_type:
                _fail("upload_content_type", "O formato enviado não corresponde à autorização.", 415)
            if content_length is not None:
                if not re.fullmatch(r"[0-9]{1,12}", content_length) or int(content_length) != binding.size_bytes:
                    _fail("upload_content_length", "O tamanho enviado não corresponde à autorização.", 413)
            if row["state"] == "receiving":
                _fail("upload_in_progress", "Este arquivo ainda está sendo recebido. Confira o projeto antes de repetir.", 409)
            if row["state"] == "completed":
                return UploadClaim(binding, digest, True, row["asset_id"])
            db.execute("UPDATE tickets SET state='receiving',updated=? WHERE upload_id=?", (time.time(), upload_id))
            return UploadClaim(binding, digest)

    def assert_claim(self, claim: UploadClaim):
        with self._db() as db:
            row = db.execute("SELECT digest,state FROM tickets WHERE upload_id=?", (claim.binding.upload_id,)).fetchone()
            if not row or row["state"] != "receiving" or not hmac.compare_digest(row["digest"], claim.digest):
                _fail("upload_claim_lost", "Confira o recebimento no projeto antes de tentar novamente.", 409)

    def complete(self, claim: UploadClaim, asset_id: str):
        with self._db() as db:
            changed = db.execute("UPDATE tickets SET state='completed',asset_id=?,updated=? "
                                 "WHERE upload_id=? AND digest=? AND state='receiving'",
                                 (asset_id, time.time(), claim.binding.upload_id, claim.digest)).rowcount
            if not changed:
                _fail("upload_claim_lost", "Confira o recebimento no projeto antes de tentar novamente.", 409)

    def recover(self, binding: UploadBinding, asset_id: str):
        with self._db() as db:
            row = db.execute("SELECT identity FROM tickets WHERE upload_id=?", (binding.upload_id,)).fetchone()
            self._same(row, binding)
            if row:
                db.execute("UPDATE tickets SET state='completed',asset_id=?,updated=? WHERE upload_id=?",
                           (asset_id, time.time(), binding.upload_id))

    def fail(self, claim: UploadClaim):
        with self._db() as db:
            db.execute("UPDATE tickets SET state='failed',updated=? WHERE upload_id=? AND digest=? AND state='receiving'",
                       (time.time(), claim.binding.upload_id, claim.digest))
