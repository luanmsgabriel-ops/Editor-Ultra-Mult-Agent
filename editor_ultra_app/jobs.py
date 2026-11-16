"""Small durable, serial queue; never retry a render whose outcome is unknown."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable
import uuid


class JobQueue:
    def __init__(self, directory: Path, execute: Callable[[dict], dict]):
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "app-jobs.sqlite3"
        self.execute = execute
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL, operation TEXT NOT NULL,
                request_key TEXT NOT NULL, digest TEXT NOT NULL, arguments TEXT NOT NULL,
                status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                result TEXT, error TEXT, UNIQUE(project_id, request_key))""")
            db.execute("UPDATE jobs SET status='interrupted', error=?, updated=? WHERE status='running'",
                       ("O serviço reiniciou durante a execução. Confira os artefatos antes de repetir.", time.time()))

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _view(row):
        if row is None:
            raise ValueError("Trabalho não encontrado.")
        value = {k: row[k] for k in ("id", "project_id", "operation", "status", "created", "updated", "error")}
        value["job_id"] = value["id"]
        value["request_id"] = row["request_key"]
        value["kind"] = json.loads(row["arguments"]).get("kind")
        value["result"] = json.loads(row["result"]) if row["result"] else None
        return value

    def enqueue(self, project_id: str, operation: str, arguments: dict, request_key: str):
        if not isinstance(request_key, str) or not 8 <= len(request_key) <= 120:
            raise ValueError("Forneça uma chave de execução com 8–120 caracteres.")
        serialized = json.dumps(arguments, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256((operation + serialized).encode()).hexdigest()
        now = time.time()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM jobs WHERE project_id=? AND request_key=?", (project_id, request_key)).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise ValueError("Esta chave já identifica outro pedido. Atualize o pedido antes de executar.")
                return self._view(existing)
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 20:
                raise ValueError("Fila cheia. Aguarde um trabalho terminar.")
            if db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')", (project_id,)).fetchone():
                raise ValueError("Este projeto já possui uma execução em andamento.")
            identifier = uuid.uuid4().hex
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (identifier, project_id, operation, request_key, digest, serialized, "queued", now, now, None, None))
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone()
        self.wake.set()
        return self._view(row)

    def existing_request(self, project_id: str, operation: str, arguments: dict, request_key: str):
        serialized = json.dumps(arguments, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256((operation + serialized).encode()).hexdigest()
        with self._db() as db:
            existing = db.execute("SELECT * FROM jobs WHERE project_id=? AND request_key=?", (project_id, request_key)).fetchone()
            if existing is None:
                return None
            if existing["digest"] != digest:
                raise ValueError("Esta chave já identifica outro pedido. Atualize o pedido antes de executar.")
            return self._view(existing)

    def get(self, project_id: str, job_id: str):
        with self._db() as db:
            return self._view(db.execute("SELECT * FROM jobs WHERE id=? AND project_id=?", (job_id, project_id)).fetchone())

    def list(self, project_id: str):
        with self._db() as db:
            return [self._view(r) for r in db.execute("SELECT * FROM jobs WHERE project_id=? ORDER BY created DESC LIMIT 30", (project_id,))]

    def assert_idle(self, project_id: str):
        with self._db() as db:
            if db.execute("SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')", (project_id,)).fetchone():
                raise ValueError("Aguarde a execução atual antes de alterar este projeto.")

    def _run_one(self):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return False
            db.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), row["id"]))
        try:
            result = self.execute({"project_id": row["project_id"], "operation": row["operation"],
                                   **json.loads(row["arguments"])})
            encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
            status, error = "completed", None
        except Exception as exc:
            # No signed download URLs, access keys or request bodies belong in logs.
            encoded, status = None, "failed"
            error = str(exc)[:1800]
        with self._db() as db:
            db.execute("UPDATE jobs SET status=?,result=?,error=?,updated=? WHERE id=?",
                       (status, encoded, error, time.time(), row["id"]))
        return True

    def _loop(self):
        while not self.stop_event.is_set():
            if not self._run_one():
                self.wake.wait(1)
                self.wake.clear()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="editor-ultra-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)
