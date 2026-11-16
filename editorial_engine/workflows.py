"""Recipe contracts and an offline, resumable execution ledger.

This module validates technical execution, not editorial or visual approval.
It never downloads models or calls providers. A caller supplies measured
availability and an executor callback. Monetary amounts use one declared unit
with six decimal places; a reservation must be an upper bound enforced by the
executor, not a promise that an external provider cannot overspend.

Executor signature: executor(bound_workflow, job_key) -> mapping with
artifact_path, artifact_sha256 and actual_cost. An explicit failed result may
instead contain status="failed", actual_cost and error. An exception or missing
actual cost leaves the job unknown and the reservation held until reconciliation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


class WorkflowError(ValueError):
    """Invalid or unsafe execution request."""


class RecipeError(WorkflowError):
    pass


class PreflightBlocked(WorkflowError):
    pass


class BudgetError(WorkflowError):
    pass


class ArtifactError(WorkflowError):
    pass


class ExecutionUnknown(WorkflowError):
    pass


_MODES = {"none", "screen", "planar", "3d"}
_TYPES = {"string", "number", "integer", "boolean", "json",
          "image", "video", "audio", "mask"}
_PLACEHOLDER = re.compile(r"\{\{[^{}]*\}\}|\$\{[^{}]*\}|(?<!\{)\{[A-Za-z_][A-Za-z0-9_.-]*\}(?!\})")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_SCALE = 1_000_000


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise WorkflowError("Contract values must be finite JSON values") from exc


def _declares_video_generation(plan: Mapping, recipe: Mapping) -> bool:
    """Check explicit task contracts, never guess from node/provider names.

    The ledger is not a sandbox for arbitrary Python. Local processing is a
    caller attestation; a declared external_video/video_generation task cannot
    use that attestation to override the prompt-export rule.
    """
    declarations = [plan, recipe]
    request = plan.get("request") if isinstance(plan, Mapping) else None
    if isinstance(request, Mapping):
        declarations.append(request)
    for declaration in declarations:
        if not isinstance(declaration, Mapping):
            continue
        if declaration.get("operation") in {"external_video", "video_generation"}:
            return True
        if declaration.get("execution_kind") == "video_generation":
            return True
    return False


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _value_valid(value: Any, spec: Mapping, name: str) -> None:
    kind = spec["type"]
    if kind in {"string", "image", "video", "audio", "mask"}:
        valid = isinstance(value, str) and (kind == "string" or bool(value))
    elif kind == "boolean":
        valid = isinstance(value, bool)
    elif kind == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif kind == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        valid = valid and math.isfinite(value)
    else:
        _canonical(value)
        valid = True
    if not valid:
        raise RecipeError(f"Input {name!r} has invalid type; expected {kind}")
    if kind in {"number", "integer"}:
        if "min" in spec and value < spec["min"]:
            raise RecipeError(f"Input {name!r} is below its minimum")
        if "max" in spec and value > spec["max"]:
            raise RecipeError(f"Input {name!r} exceeds its maximum")
    if "enum" in spec and value not in spec["enum"]:
        raise RecipeError(f"Input {name!r} is outside its enum")


def _check_graph(graph: Mapping) -> None:
    links = {key: set() for key in graph}

    def walk(value: Any, owner: str) -> None:
        if isinstance(value, list):
            if len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                if isinstance(value[1], bool) or value[1] < 0 or value[0] not in graph:
                    raise RecipeError(f"Dangling workflow link in node {owner!r}: {value!r}")
                links[owner].add(value[0])
            else:
                for item in value:
                    walk(item, owner)
        elif isinstance(value, Mapping):
            for item in value.values():
                walk(item, owner)

    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not isinstance(node, Mapping):
            raise RecipeError("Workflow nodes must have string IDs and object values")
        if not isinstance(node.get("class_type"), str) or not node["class_type"]:
            raise RecipeError(f"Node {node_id!r} needs a class_type")
        if not isinstance(node.get("inputs"), Mapping):
            raise RecipeError(f"Node {node_id!r} needs an inputs object")
        walk(node["inputs"], node_id)

    done, active = set(), set()

    def visit(node_id: str) -> None:
        if node_id in active:
            raise RecipeError("Workflow contains a node cycle")
        if node_id in done:
            return
        active.add(node_id)
        for dep in links[node_id]:
            visit(dep)
        active.remove(node_id)
        done.add(node_id)

    for node_id in graph:
        visit(node_id)


def validate_recipe(recipe: Mapping) -> None:
    """Validate a JSON recipe without claiming host availability."""
    if not isinstance(recipe, Mapping):
        raise RecipeError("Recipe must be an object")
    _canonical(recipe)
    for field in ("id", "version"):
        if not isinstance(recipe.get(field), str) or not recipe[field].strip():
            raise RecipeError(f"Recipe requires {field}")
    if not isinstance(recipe.get("spatial_mode"), str) or recipe["spatial_mode"] not in _MODES:
        raise RecipeError("spatial_mode must be none, screen, planar or 3d")
    graph = recipe.get("workflow")
    if not isinstance(graph, Mapping) or not graph:
        raise RecipeError("Recipe needs a nonempty API workflow")
    _check_graph(graph)
    specs, bindings = recipe.get("inputs", {}), recipe.get("bindings", {})
    if not isinstance(specs, Mapping) or not isinstance(bindings, Mapping):
        raise RecipeError("inputs and bindings must be objects")
    bound_fields = set()
    for name, spec in specs.items():
        if not isinstance(name, str) or not isinstance(spec, Mapping) or spec.get("type") not in _TYPES:
            raise RecipeError(f"Invalid input declaration {name!r}")
        if "required" in spec and not isinstance(spec["required"], bool):
            raise RecipeError(f"Input {name!r} required must be boolean")
        for boundary in ("min", "max"):
            if boundary in spec and (isinstance(spec[boundary], bool) or
                    not isinstance(spec[boundary], (int, float)) or
                    not math.isfinite(spec[boundary])):
                raise RecipeError(f"Input {name!r} needs a finite numeric {boundary}")
        if "min" in spec and "max" in spec and spec["min"] > spec["max"]:
            raise RecipeError(f"Input {name!r} has an inverted range")
        if "enum" in spec and (not isinstance(spec["enum"], list) or not spec["enum"]):
            raise RecipeError(f"Input {name!r} needs a nonempty enum")
        if name not in bindings:
            raise RecipeError(f"Input {name!r} has no binding")
        if "default" in spec:
            _value_valid(spec["default"], spec, name)
    for name, targets in bindings.items():
        if name not in specs or not isinstance(targets, list) or not targets:
            raise RecipeError(f"Invalid binding for {name!r}")
        for target in targets:
            if not isinstance(target, Mapping):
                raise RecipeError("Binding target must be an object")
            node_id, field = target.get("node"), target.get("field")
            if not isinstance(node_id, str) or node_id not in graph:
                raise RecipeError(f"Dangling binding node for {name!r}")
            if not isinstance(field, str) or field not in graph[node_id]["inputs"]:
                raise RecipeError(f"Dangling binding field for {name!r}")
            pair = (node_id, field)
            if pair in bound_fields:
                raise RecipeError(f"Multiple inputs bind the same field {pair!r}")
            bound_fields.add(pair)
    requirements = recipe.get("requirements", {})
    if not isinstance(requirements, Mapping):
        raise RecipeError("requirements must be an object")
    if set(requirements) - {"models", "capabilities"}:
        raise RecipeError("Unknown requirement category")
    for category in ("models", "capabilities"):
        values = requirements.get(category, [])
        if (not isinstance(values, list) or
                any(not isinstance(item, str) or not item for item in values) or
                len(set(values)) != len(values)):
            raise RecipeError(f"Invalid {category} requirement list")
    fallback = recipe.get("fallback")
    if fallback is not None and (not isinstance(fallback, str) or not fallback):
        raise RecipeError("fallback must be a recipe ID or null")


def bind_workflow(recipe: Mapping, params: Mapping) -> dict:
    """Bind complete values, then reject dangling links/unfilled placeholders."""
    validate_recipe(recipe)
    if not isinstance(params, Mapping):
        raise RecipeError("params must be an object")
    _canonical(params)
    specs = recipe.get("inputs", {})
    unknown = set(params) - set(specs)
    if unknown:
        raise RecipeError(f"Undeclared inputs: {sorted(unknown)}")
    graph = copy.deepcopy(recipe["workflow"])
    for name, spec in specs.items():
        if name in params:
            value = params[name]
        elif "default" in spec:
            value = spec["default"]
        elif spec.get("required", True):
            raise RecipeError(f"Missing required input {name!r}")
        else:
            continue
        _value_valid(value, spec, name)
        for target in recipe["bindings"][name]:
            graph[target["node"]]["inputs"][target["field"]] = copy.deepcopy(value)
    if any(_PLACEHOLDER.search(text) for text in _strings(graph)):
        raise RecipeError("Unresolved placeholder in bound workflow")
    _check_graph(graph)
    return graph


def preflight_recipe(recipe: Mapping, availability: Mapping) -> dict:
    """Read explicit host observations; absent/unknown readiness is blocked.

    availability has models, capabilities and nodes maps. A ready entry is
    exactly True or {"status": "ready"}. A record with a path is also checked
    against the local file and its optional sha256. The caller is responsible
    for obtaining these observations from the actual execution host.
    """
    validate_recipe(recipe)
    reasons = []
    requirements = recipe.get("requirements", {})
    categories = {
        "models": requirements.get("models", []),
        "capabilities": requirements.get("capabilities", []),
        "nodes": sorted({node["class_type"] for node in recipe["workflow"].values()}),
    }
    for category, names in categories.items():
        observed = availability.get(category, {}) if isinstance(availability, Mapping) else {}
        if not isinstance(observed, Mapping):
            observed = {}
        for name in names:
            record = observed.get(name)
            ready = record is True or (isinstance(record, Mapping) and record.get("status") == "ready")
            if not ready:
                reasons.append(f"{category}:{name}:unknown_or_unavailable")
                continue
            if isinstance(record, Mapping) and "path" in record:
                try:
                    evidence = artifact_evidence(record["path"], record.get("sha256"))
                    if not evidence["size"]:
                        raise ArtifactError("Empty resource")
                except (OSError, WorkflowError, TypeError) as exc:
                    reasons.append(f"{category}:{name}:invalid_file:{exc}")
    return {"status": "blocked" if reasons else "ready", "recipe_id": recipe["id"],
            "reasons": reasons}


def resolve_recipe(recipe_id: str, registry: Mapping, availability: Mapping,
                   required_spatial_mode: str | None = None) -> dict:
    """Follow declared fallbacks, recording every step and preserving space."""
    path, attempts = [], []
    current, required = recipe_id, required_spatial_mode
    while current:
        if current in path:
            return {"status": "blocked", "recipe_id": None, "path": path + [current],
                    "attempts": attempts, "reasons": ["fallback_cycle"]}
        path.append(current)
        recipe = registry.get(current)
        if recipe is None:
            return {"status": "blocked", "recipe_id": None, "path": path,
                    "attempts": attempts, "reasons": [f"missing_recipe:{current}"]}
        validate_recipe(recipe)
        if recipe["id"] != current:
            raise RecipeError("Registry key does not match recipe ID")
        required = required or recipe["spatial_mode"]
        if recipe["spatial_mode"] != required:
            return {"status": "blocked", "recipe_id": None, "path": path,
                    "attempts": attempts, "reasons": ["spatial_fallback_forbidden"]}
        check = preflight_recipe(recipe, availability)
        attempts.append(check)
        if check["status"] == "ready":
            return {"status": "ready", "recipe_id": current, "path": path,
                    "attempts": attempts, "reasons": []}
        current = recipe.get("fallback")
    return {"status": "blocked", "recipe_id": None, "path": path,
            "attempts": attempts, "reasons": ["no_ready_recipe"]}


def artifact_evidence(path: str | Path, expected_sha256: str | None = None) -> dict:
    """Hash a real nonempty file; detect modifications during the read."""
    if expected_sha256 is not None and not _SHA.fullmatch(str(expected_sha256)):
        raise ArtifactError("Expected SHA-256 must contain 64 lowercase hex characters")
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise ArtifactError("Artifact is not a regular file")
    before = resolved.stat()
    digest = hashlib.sha256()
    with resolved.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = resolved.stat()
    fields = ("st_size", "st_mtime_ns", "st_ino", "st_dev")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise ArtifactError("Artifact changed while hashing")
    if not after.st_size:
        raise ArtifactError("Artifact is empty")
    sha = digest.hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ArtifactError("Artifact SHA-256 mismatch")
    return {"path": str(resolved), "sha256": sha, "size": after.st_size}


def _verify_sources(artifact: Mapping, sources: Mapping) -> None:
    for source in sources.values():
        if Path(artifact["path"]).samefile(source["path"]):
            raise ArtifactError("Output must be separate from source")
        artifact_evidence(source["path"], source["sha256"])


def _money(value: Any, *, allow_none: bool = False) -> int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool):
        raise BudgetError("Cost must be a nonnegative finite number")
    try:
        number = Decimal(str(value))
        scaled = number * _SCALE
        if not number.is_finite() or number < 0 or scaled != scaled.to_integral_value():
            raise BudgetError("Cost requires a finite nonnegative value with at most six decimals")
        result = int(scaled)
        if result > 9_000_000_000_000_000_000:
            raise BudgetError("Cost exceeds ledger range")
        return result
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BudgetError("Cost must be a nonnegative finite number") from exc


def _units(value: int | None) -> float | None:
    return None if value is None else value / _SCALE


class WorkflowLedger:
    """SQLite journal with atomic claims, reservations and settled accounting.

    A running or unknown job is never replayed automatically. After an
    interrupted worker, reconcile_job records verified output/cost or a known
    failure. Only an explicit retry_failed=True starts a new failed-job attempt.
    """

    def __init__(self, db_path: str | Path, budget_limit: Any = None, unit: str = "credits"):
        if str(db_path) == ":memory:":
            raise WorkflowError("The execution ledger requires a durable SQLite file")
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        limit = _money(budget_limit, allow_none=True)
        if not isinstance(unit, str) or not unit.strip():
            raise BudgetError("A budget unit is required")
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings(
                    id INTEGER PRIMARY KEY CHECK(id=1), limit_micros INTEGER, unit TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reservations(
                    id TEXT PRIMARY KEY, reserved_micros INTEGER, actual_micros INTEGER,
                    settled INTEGER NOT NULL DEFAULT 0 CHECK(settled IN(0,1)));
                CREATE TABLE IF NOT EXISTS jobs(
                    key TEXT PRIMARY KEY, status TEXT NOT NULL, specification TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0, reservation_id TEXT,
                    token TEXT, artifact TEXT, error TEXT, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, job_key TEXT NOT NULL,
                    attempt INTEGER NOT NULL, status TEXT NOT NULL, detail TEXT, at REAL NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO settings VALUES(1,?,?)", (limit, unit))
            existing = db.execute("SELECT limit_micros,unit FROM settings WHERE id=1").fetchone()
            if existing["unit"] != unit or (limit is not None and existing["limit_micros"] != limit):
                raise BudgetError("Existing ledger budget or unit differs")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _totals(db: sqlite3.Connection) -> tuple[int, int, int]:
        row = db.execute("""
            SELECT COALESCE(SUM(CASE WHEN settled=1 THEN actual_micros ELSE 0 END),0) spent,
                   COALESCE(SUM(CASE WHEN settled=0 THEN reserved_micros ELSE 0 END),0) held,
                   COALESCE(SUM(CASE WHEN settled=0 AND reserved_micros IS NULL THEN 1 ELSE 0 END),0) unknown
            FROM reservations
        """).fetchone()
        return row["spent"], row["held"], row["unknown"]

    def budget(self) -> dict:
        with self._connect() as db:
            db.execute("BEGIN")
            settings = db.execute("SELECT * FROM settings WHERE id=1").fetchone()
            spent, held, unknown = self._totals(db)
            return {"unit": settings["unit"], "limit": _units(settings["limit_micros"]),
                    "spent": _units(spent), "reserved": _units(held),
                    "unknown_reservations": unknown,
                    "remaining": None if settings["limit_micros"] is None else
                    _units(settings["limit_micros"] - spent - held)}

    def _reserve(self, db: sqlite3.Connection, reservation_id: str, amount: int | None) -> bool:
        old = db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
        if old:
            if old["reserved_micros"] != amount:
                raise BudgetError("Reservation ID reused with another estimate")
            return False
        limit = db.execute("SELECT limit_micros FROM settings WHERE id=1").fetchone()[0]
        spent, held, unknown = self._totals(db)
        if limit is not None:
            if amount is None or unknown:
                raise BudgetError("Unknown cost blocks a finite budget")
            if spent + held + amount > limit:
                raise BudgetError("Reservation would exceed budget")
        db.execute("INSERT INTO reservations(id,reserved_micros) VALUES(?,?)",
                   (reservation_id, amount))
        return True

    def reserve_budget(self, reservation_id: str, estimated_cost: Any) -> dict:
        """Reserve before starting a job. Reusing an identical ID is idempotent."""
        if not isinstance(reservation_id, str) or not reservation_id:
            raise BudgetError("Reservation ID is required")
        if reservation_id.startswith("job:"):
            raise BudgetError("The job: reservation namespace is managed by run()")
        amount = _money(estimated_cost, allow_none=True)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            created = self._reserve(db, reservation_id, amount)
            reservation = db.execute("SELECT * FROM reservations WHERE id=?",
                                     (reservation_id,)).fetchone()
        return {**self.budget(), "reservation_id": reservation_id, "reused": not created,
                "reservation_state": "settled" if reservation["settled"] else "held"}

    @staticmethod
    def _settle(db: sqlite3.Connection, reservation_id: str, actual: int) -> bool:
        old = db.execute("SELECT * FROM reservations WHERE id=?", (reservation_id,)).fetchone()
        if not old:
            raise BudgetError("Unknown reservation")
        if old["settled"]:
            if old["actual_micros"] != actual:
                raise BudgetError("Reservation was already settled at another cost")
        else:
            db.execute("UPDATE reservations SET actual_micros=?,settled=1 WHERE id=?",
                       (actual, reservation_id))
        return old["reserved_micros"] is not None and actual > old["reserved_micros"]

    def release_reservation(self, reservation_id: str, actual_cost: Any) -> dict:
        """Release the hold, recording real cost exactly once (including zero).

        Actual overrun is accounted, never hidden or clamped to the estimate.
        This method does not assert that a workflow produced a valid artifact.
        """
        actual = _money(actual_cost)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM jobs WHERE reservation_id=? AND status IN('running','unknown')",
                          (reservation_id,)).fetchone():
                raise BudgetError("Use reconcile_job for an active or unknown job reservation")
            overrun = self._settle(db, reservation_id, actual)
        return {**self.budget(), "reservation_overrun": overrun}

    @staticmethod
    def _event(db, key, attempt, status, detail=None):
        db.execute("INSERT INTO events(job_key,attempt,status,detail,at) VALUES(?,?,?,?,?)",
                   (key, attempt, status, detail, time.time()))

    def get_job(self, job_key: str, verify_artifact: bool = True) -> dict | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE key=?", (job_key,)).fetchone()
            if not row:
                return None
            job = dict(row)
            job["specification"] = json.loads(job["specification"])
            job["artifact"] = json.loads(job["artifact"]) if job["artifact"] else None
            reservation = db.execute("SELECT * FROM reservations WHERE id=?",
                                     (job["reservation_id"],)).fetchone()
            job["cost"] = ({"reserved": _units(reservation["reserved_micros"]),
                            "actual": _units(reservation["actual_micros"]),
                            "settled": bool(reservation["settled"])}
                           if reservation else None)
            if verify_artifact and job["status"] == "succeeded":
                try:
                    if not job["artifact"]:
                        raise ArtifactError("Success has no artifact evidence")
                    evidence = artifact_evidence(job["artifact"]["path"], job["artifact"]["sha256"])
                    if evidence["size"] != job["artifact"]["size"]:
                        raise ArtifactError("Artifact size changed")
                except (OSError, WorkflowError, KeyError, TypeError) as exc:
                    job["status"], job["error"] = "unknown", f"artifact_invalid:{exc}"
                    db.execute("UPDATE jobs SET status='unknown',error=?,updated=? WHERE key=?",
                               (job["error"], time.time(), job_key))
                    self._event(db, job_key, job["attempt"], "unknown", job["error"])
            job.pop("token", None)
            return job

    def unresolved_production_jobs(self, request_sha256: str) -> list[dict]:
        """Find historical pending jobs even after an export directory changes.

        No reservation is created or reconciled here. This lookup keeps an
        execution-policy change from disguising an old video job as a new
        external task merely because the former adapter is no longer used.
        """
        if not isinstance(request_sha256, str) or not _SHA.fullmatch(request_sha256):
            raise WorkflowError("A production request SHA-256 is required")
        with self._connect() as db:
            rows = db.execute("SELECT key,specification FROM jobs WHERE status IN ('unknown','running') ORDER BY updated,key").fetchall()
        keys = []
        for row in rows:
            specification = json.loads(row["specification"])
            plan = specification.get("plan", {})
            request = plan.get("request", {}) if isinstance(plan, Mapping) else {}
            if isinstance(request, Mapping) and request.get("request_sha256") == request_sha256:
                keys.append(row["key"])
        jobs = [self.get_job(key, verify_artifact=False) for key in keys]
        return [job for job in jobs if job and job["status"] in {"unknown", "running"}]

    def _unknown(self, key: str, token: str, reason: str) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            if row and row["token"] == token and row["status"] == "running":
                db.execute("UPDATE jobs SET status='unknown',error=?,updated=? WHERE key=?",
                           (reason, time.time(), key))
                self._event(db, key, row["attempt"], "unknown", reason)

    def _complete(self, key: str, token: str, actual: int, artifact: dict | None,
                  error: str | None) -> dict:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            if not row or row["token"] != token or row["status"] not in {"running", "unknown"}:
                raise WorkflowError("Job is no longer owned by this execution attempt")
            overrun = self._settle(db, row["reservation_id"], actual)
            if overrun:
                error = "actual_cost_exceeds_reservation" + (f":{error}" if error else "")
            status = "succeeded" if artifact and not error else "failed"
            db.execute("UPDATE jobs SET status=?,artifact=?,error=?,updated=? WHERE key=?",
                       (status, _canonical(artifact) if artifact else None, error, time.time(), key))
            self._event(db, key, row["attempt"], status, error)
        return self.get_job(key)

    def reconcile_job(self, job_key: str, *, actual_cost: Any,
                      artifact_path: str | Path | None = None,
                      artifact_sha256: str | None = None, error: str | None = None) -> dict:
        """Resolve an interrupted/unknown attempt with independently known facts.

        Confirm the worker has stopped before reconciliation. Omit artifact only
        to declare a known failure. A recovered artifact needs its expected hash.
        Reconciliation never starts or spends on another execution.
        """
        actual = _money(actual_cost)
        artifact = None
        if artifact_path is not None:
            if artifact_sha256 is None:
                raise ArtifactError("Recovered artifact needs expected SHA-256")
            artifact = artifact_evidence(artifact_path, artifact_sha256)
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE key=?", (job_key,)).fetchone()
            if not row:
                raise WorkflowError("Unknown job")
            if artifact is not None:
                _verify_sources(artifact, json.loads(row["specification"])["source_files"])
            if row["status"] not in {"running", "unknown"}:
                reservation = db.execute("SELECT * FROM reservations WHERE id=?",
                                         (row["reservation_id"],)).fetchone()
                existing_artifact = json.loads(row["artifact"]) if row["artifact"] else None
                if (reservation and reservation["settled"] and reservation["actual_micros"] == actual
                        and existing_artifact == artifact):
                    return self.get_job(job_key)
                raise WorkflowError("Only running or unknown jobs can be reconciled")
            token = row["token"]
        return self._complete(job_key, token, actual, artifact,
                              error if artifact else (error or "reconciled_failure"))

    def run(self, *, plan: Mapping, source_paths: Mapping[str, str | Path],
            recipe: Mapping, params: Mapping, availability: Mapping,
            executor: Callable[[dict, str], Mapping], estimated_cost: Any,
            retry_failed: bool = False) -> dict:
        """Execute once per content identity; return existing work on repetition."""
        graph = bind_workflow(recipe, params)
        if not isinstance(source_paths, Mapping) or not source_paths:
            raise WorkflowError("At least one source file is required")
        sources = {name: artifact_evidence(path) for name, path in source_paths.items()}
        if any(not isinstance(name, str) or not name for name in sources):
            raise WorkflowError("Source names must be nonempty strings")
        tracked_paths = {source["path"] for source in sources.values()}
        for name, spec in recipe.get("inputs", {}).items():
            if spec["type"] in {"image", "video", "audio", "mask"}:
                value = params.get(name, spec.get("default"))
                if value is not None and str(Path(value).resolve(strict=True)) not in tracked_paths:
                    raise RecipeError(f"Untracked media input {name!r}; include it in source_paths")
        identity = {"plan": plan, "recipe": recipe, "params": params,
                    "sources": {name: {"sha256": item["sha256"], "size": item["size"]}
                                for name, item in sources.items()}}
        key = hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()
        old = self.get_job(key)
        if old and (old["status"] != "failed" or not retry_failed):
            return {**old, "reused": True}
        if _declares_video_generation(plan, recipe):
            raise PreflightBlocked("video_generation_prompt_only: export the authored video prompts and import user-supplied returned media; no video-generation callback was called")
        check = preflight_recipe(recipe, availability)
        if check["status"] != "ready":
            raise PreflightBlocked("; ".join(check["reasons"]))
        amount = _money(estimated_cost, allow_none=True)
        token = uuid.uuid4().hex
        claimed = False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
            if row is None or (row["status"] == "failed" and retry_failed):
                attempt = 1 if row is None else row["attempt"] + 1
                reservation_id = f"job:{key}:{attempt}"
                self._reserve(db, reservation_id, amount)
                specification = {**identity, "source_files": sources}
                db.execute("""
                    INSERT INTO jobs(key,status,specification,attempt,reservation_id,token,updated)
                    VALUES(?,'planned',?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET status='planned',
                    attempt=excluded.attempt,reservation_id=excluded.reservation_id,
                    token=excluded.token,artifact=NULL,error=NULL,updated=excluded.updated
                """, (key, _canonical(specification), attempt, reservation_id, token, time.time()))
                self._event(db, key, attempt, "planned")
                db.execute("UPDATE jobs SET status='running' WHERE key=?", (key,))
                self._event(db, key, attempt, "running")
                claimed = True
        if not claimed:
            return {**self.get_job(key), "reused": True}
        try:
            outcome = executor(copy.deepcopy(graph), key)
        except Exception as exc:
            self._unknown(key, token, f"executor_exception:{type(exc).__name__}:{exc}")
            raise ExecutionUnknown(f"Job {key} interrupted; reservation held for reconciliation") from exc
        if not isinstance(outcome, Mapping):
            self._unknown(key, token, "executor_result_not_object")
            raise ExecutionUnknown(f"Job {key} returned no execution evidence")
        if outcome.get("status") not in (None, "succeeded", "failed"):
            self._unknown(key, token, "executor_result_not_terminal")
            raise ExecutionUnknown(f"Job {key} did not report a terminal execution result")
        try:
            actual = _money(outcome.get("actual_cost"))
        except BudgetError as exc:
            self._unknown(key, token, "actual_cost_unknown")
            raise ExecutionUnknown(f"Job {key} has unknown actual cost; reservation retained") from exc
        artifact, error = None, None
        if outcome.get("status") == "failed":
            error = str(outcome.get("error") or "executor_failed")
        elif "exit_code" in outcome and outcome["exit_code"] != 0:
            error = f"executor_exit_code:{outcome['exit_code']}"
        else:
            try:
                if not outcome.get("artifact_sha256") or not outcome.get("artifact_path"):
                    raise ArtifactError("Executor must report artifact_path and artifact_sha256")
                artifact = artifact_evidence(outcome["artifact_path"], outcome["artifact_sha256"])
                _verify_sources(artifact, sources)
            except (OSError, WorkflowError, TypeError) as exc:
                error = f"artifact_or_source_invalid:{exc}"
        result = self._complete(key, token, actual, artifact, error)
        return {**result, "reused": False}
