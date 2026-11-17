"""Trusted, local adapter between the ChatGPT panel and the existing engine.

The panel supplies choices and opaque file IDs. This adapter owns file paths,
project revisions and approvals. It never authors editorial observations or
submits a video-generation job. Reference-study renders are explicitly distinct
from a faithful reconstruction and from editing a new person's footage.
"""

from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import datetime, timezone
from fractions import Fraction
import fcntl
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError as ModelValidationError, model_validator

from editorial_engine import project as engine
from editorial_engine.contracts import ValidationError, clone, digest, file_sha256, require, verify_file


ROLES = {"ref", "clone", "footage", "identity", "narration", "logo", "result", "shot"}
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_INPUTS = 128
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_TEXT_FIELDS = {"name", "objective", "adapt", "sourceLink", "identityLabel", "narration",
                "music", "editNotes", "audience"}
_SOURCE_FIELDS = {"sourceType", "sourceLink", "objective", "adapt", "ratio", "preserve", "templateId"}
MOTION_LIMITS = {"max_elements": 4, "max_interval_frames": 300, "max_element_frames": 600,
                 "max_source_seconds": 120, "max_source_frames": 3600,
                 "max_source_pixels": 1920 * 1080, "max_source_side": 4096,
                 "max_source_fps": 120, "max_decoded_pixels": 4_000_000_000,
                 "max_cached_gray_bytes": 128 * 1024 * 1024,
                 "max_artifact_bytes": 16 * 1024 * 1024}
MotionFrameIndex = Annotated[int, Field(strict=True, ge=0, le=3600)]
MotionCutIndex = Annotated[int, Field(strict=True, ge=1, lt=3600)]


class MotionTrackerSettings(BaseModel):
    """Bounded CPU settings; no producer/model/command selection is accepted."""
    model_config = ConfigDict(extra="forbid", strict=True)
    max_corners: int = Field(default=240, ge=6, le=512)
    min_points: int = Field(default=6, ge=3, le=64)
    quality_level: float = Field(default=.01, ge=.0001, le=1, allow_inf_nan=False)
    min_distance_px: float = Field(default=4, ge=.5, le=100, allow_inf_nan=False)
    window_size: int = Field(default=31, ge=5, le=51)
    pyramid_levels: int = Field(default=4, ge=0, le=4)
    fb_max_px: float = Field(default=1.5, ge=.1, le=10, allow_inf_nan=False)
    ransac_max_px: float = Field(default=2, ge=.1, le=10, allow_inf_nan=False)
    min_inlier_ratio: float = Field(default=.6, ge=.1, le=1, allow_inf_nan=False)
    min_spatial_coverage: float = Field(default=.12, ge=.01, le=1, allow_inf_nan=False)
    max_step_scale_ratio: float = Field(default=2.5, ge=1, le=4, allow_inf_nan=False)
    max_step_angle_deg: float = Field(default=120, gt=0, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_tracker(self):
        if self.window_size % 2 != 1 or self.min_points > self.max_corners:
            raise ValueError("Use an odd LK window and max_corners >= min_points")
        return self


class MotionElementSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    frame_range: list[MotionFrameIndex] = Field(alias="range", min_length=2, max_length=2,
                                   description="Source frame [start,end), at most 300 frames per element")
    seed_frame: int = Field(ge=0, lt=3600)
    roi_px: list[float] = Field(min_length=4, max_length=4,
                               description="Seed feature box [x,y,width,height] in explicitly oriented source pixels")
    reference_box_px: list[float] | None = Field(default=None, min_length=4, max_length=4)
    segment: str | None = Field(default=None, min_length=1, max_length=96,
                                pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    mask_asset_id: str | None = Field(default=None, min_length=1, max_length=96,
                                      pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$",
                                      description="Optional image asset ID belonging to this project; paths and URLs are forbidden")

    @model_validator(mode="after")
    def valid_element(self):
        start,end=self.frame_range
        if not 0<=start<=self.seed_frame<end<=MOTION_LIMITS["max_source_frames"]:
            raise ValueError("Range and seed must be ordered inside the bounded source clock")
        if end-start>MOTION_LIMITS["max_interval_frames"]:
            raise ValueError("Select a transition window of at most 300 frames per element")
        for box in (self.roi_px,self.reference_box_px):
            if box is not None and (not all(math.isfinite(v) and abs(v)<=16384 for v in box) or box[2]<=0 or box[3]<=0):
                raise ValueError("Boxes need finite bounded pixel coordinates and positive size")
        if self.roi_px[0]<0 or self.roi_px[1]<0:
            raise ValueError("Seed ROI must start inside the source raster")
        return self


class MotionMeasurementSpecification(BaseModel):
    """One bounded evidence request; fitting is PCHIP without bridging missing frames."""
    model_config = ConfigDict(extra="forbid", strict=True, json_schema_extra={"x-resource-limits": MOTION_LIMITS})
    schema_name: Literal["element-motion-measurement/1"] = Field(default="element-motion-measurement/1", alias="schema")
    rotation_ccw: Literal[0,90,180,270] | None = None
    cuts: list[MotionCutIndex] = Field(default_factory=list, max_length=128,
                            description="Sorted unique first-frame indices of explicitly declared cuts")
    elements: list[MotionElementSpecification] = Field(min_length=1, max_length=4)
    tracker: MotionTrackerSettings = Field(default_factory=MotionTrackerSettings)

    @model_validator(mode="after")
    def valid_request(self):
        if self.cuts!=sorted(set(self.cuts)) or any(not 0<c<MOTION_LIMITS["max_source_frames"] for c in self.cuts):
            raise ValueError("Cuts must be sorted unique positive frame indices below 3600")
        if len({e.id for e in self.elements})!=len(self.elements):
            raise ValueError("Element IDs must be unique")
        if sum(e.frame_range[1]-e.frame_range[0] for e in self.elements)>MOTION_LIMITS["max_element_frames"]:
            raise ValueError("Request exceeds the 600 element-frame CPU budget")
        return self


def _now():
    return datetime.now(timezone.utc).isoformat()


def stored_bytes(directory):
    """Account for durable bytes while SQLite may remove transient WAL files."""
    total=0
    for path in Path(directory).rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():total+=path.stat().st_size
        except FileNotFoundError:
            # Job polling can checkpoint/remove a WAL between discovery and stat.
            continue
    return total


def _text(value, limit=20000):
    require(isinstance(value, str) and len(value) <= limit, "ui_text", "Expected bounded text")
    return value


def _number(value, minimum=0, maximum=600):
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and minimum <= value <= maximum,
            "ui_number", "Expected a finite number inside the allowed range")
    return value


def _identifier(value):
    require(isinstance(value, str) and bool(_ID.fullmatch(value)) and ".." not in value,
            "ui_identifier", "Invalid identifier")
    return value


def _default_state(project_id):
    return {"schema": "editor-ultra-interface/1", "id": project_id, "name": "Meu próximo vídeo",
            "step": 0, "sourceType": "video", "sourceLink": "", "objective": "", "adapt": "",
            "ratio": "9:16", "targetDuration": 30, "preserve": [], "templateId": None,
            "mode": "ready", "identityLabel": "Clone de Luan", "narration": "", "music": "",
            "editNotes": "", "audience": "", "shots": [], "comments": [],
            "assets": {role: [] for role in ROLES - {"shot"}}, "sourceRev": 1, "editRev": 1,
            "cloneChecks": {}, "finalChecks": {}, "cloneConfirm": False, "finalConfirm": False}


class EngineAdapter:
    """All paths come from the trusted host or this adapter, never browser JSON.

    ``import_local_file.source`` is a host-materialized upload, not a tool input
    accepting arbitrary local paths. MCP authentication and upload transport are
    the caller's responsibility. Calls are synchronous; enqueue costly calls in
    the connector worker. Mutation checks use the UI revision, not engine revision.
    """

    def __init__(self, data_dir: Path, *, template_library: Path | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Host configuration only; browser JSON can select an ID, never this path.
        self.template_library = Path(template_library).resolve() if template_library else None

    def _directory(self, project_id):
        require(isinstance(project_id, str), "project_id", "Expected an opaque project ID")
        try:
            parsed = uuid.UUID(project_id)
        except (ValueError, AttributeError) as exc:
            raise ValidationError("project_id", "Invalid project ID") from exc
        require(str(parsed) == project_id, "project_id", "Use the canonical project ID")
        path = self.data_dir / project_id
        require(path.resolve().parent == self.data_dir and not path.is_symlink(),
                "project_path", "Project must remain inside the private data directory")
        return path

    def _load(self, project_id):
        path = self._directory(project_id) / "record.json"
        require(path.is_file(), "project_missing", "Project not found")
        result = json.loads(path.read_text(encoding="utf-8"))
        require(result.get("project_id") == project_id, "project_identity", "Stored project identity differs")
        if "review_draft_bindings" not in result:
            # Establish legacy projects' prior context before applying a mutation.
            self._sync_review_drafts(result)
        return result

    @contextmanager
    def _lock(self, project_id):
        directory = self._directory(project_id)
        require(directory.is_dir(), "project_missing", "Project not found")
        with (directory / ".adapter.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValidationError("project_busy", "Another operation is running for this project") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _expect(self, record, expected_revision):
        require(expected_revision is None or (type(expected_revision) is int
                and expected_revision == record["revision"]),
                "revision_conflict", "Reload the project before submitting this change")

    def _write(self, record, action):
        self._sync_review_drafts(record)
        record["revision"] += 1
        record["updated_at"] = _now()
        record["history"].append({"at": record["updated_at"], "action": action,
                                  "revision": record["revision"]})
        record["history"] = record["history"][-300:]
        root = self._directory(record["project_id"])
        temp = root / (".record-" + uuid.uuid4().hex + ".json")
        temp.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        os.replace(temp, root / "record.json")

    def _public_file(self, item):
        keys = ("id", "name", "type", "size", "sha256", "duration", "width", "height", "fps", "role", "shot_id", "hostFileId")
        return {**{key: item[key] for key in keys if key in item}, "asset_id": item["id"],
                "available": True, "server": True}

    def _selected(self, record, role):
        return [record["files"][item["id"]] for item in record["state"]["assets"].get(role, [])]

    def _shot_files(self, record):
        return [record["files"][item["id"]] for shot in record["state"]["shots"] for item in shot.get("files", [])]

    def _clone_binding(self, record):
        state = record["state"]
        library = Path(self.template_library) if self.template_library else None
        return digest({"choices": {key: state.get(key) for key in _SOURCE_FIELDS},
                       "template_catalog": file_sha256(library) if state.get("templateId") and library and library.is_file() else None,
                       "reference": [item["sha256"] for item in self._selected(record, "ref")]})

    def _generation_basis(self, record):
        state = record["state"]
        shots = [{k: v for k, v in shot.items() if k not in {"files", "receivedRev", "receivedSignature"}}
                 for shot in state["shots"]]
        return digest({"source": self._clone_binding(record), "shots": shots,
                       "approved_clone": record["approvals"].get("clone"),
                       "identity": [a["sha256"] for a in self._selected(record, "identity")],
                       "narration_files": [a["sha256"] for a in self._selected(record, "narration")],
                       "answers": {k: state.get(k) for k in ("identityLabel", "narration", "music", "audience", "targetDuration")}})

    def _generation_binding(self, record):
        basis = self._generation_basis(record)
        entry = record["engines"].get("generation", {})
        plan = entry.get("direction_hash") if entry.get("binding") == basis else None
        return digest({"basis": basis, "authored_plan": plan})

    def _edit_binding(self, record):
        state = record["state"]
        return digest({"source": self._clone_binding(record), "generation": self._generation_binding(record),
                       "choices": {key: state.get(key) for key in ("mode", "music", "editNotes", "targetDuration")},
                       "inputs": {role: [a["sha256"] for a in self._selected(record, role)]
                                  for role in ("clone", "footage", "narration", "logo")},
                       "clips": [a["sha256"] for a in self._shot_files(record)],
                       "clone_approval": record["approvals"].get("clone")})

    def _approval_valid(self, record, stage):
        approval = record["approvals"].get(stage)
        role = "clone" if stage == "clone" else "result"
        current = self._selected(record, role)
        binding = self._clone_binding(record) if stage == "clone" else self._edit_binding(record)
        return bool(approval and approval["decision"] == "approved" and current
                    and approval["assetId"] == current[0]["id"]
                    and approval["sha256"] == current[0]["sha256"]
                    and approval["binding"] == binding
                    and current[0].get("basis_binding") == self._preview_binding(record, stage)
                    and (stage == "clone" or self._approval_valid(record, "clone")))

    def _preview_binding(self, record, stage):
        return digest({"basis": self._clone_binding(record) if stage == "clone" else self._edit_binding(record),
                       "version": record.get("preview_versions", {}).get(stage, 0)})

    def _sync_review_drafts(self, record):
        """Bind draft review fields to the current preview without recording approval."""
        bindings = record.setdefault("review_draft_bindings", {})
        state = record["state"]
        for stage, role in (("clone", "clone"), ("final", "result")):
            selected = self._selected(record, role)
            preview = selected[0] if selected else None
            context = {"asset_id": preview["id"] if preview else None,
                       "binding": self._preview_binding(record, stage)}
            previous = bindings.get(stage)
            changed = previous is not None and previous != context
            stale = preview is not None and preview.get("basis_binding") != context["binding"]
            if changed or stale:
                state[stage + "Confirm"] = False
                state[stage + "Checks"] = {}
            if changed:
                # Notes written before the first preview upload remain useful when
                # that same direction receives its first real file. A confirmation
                # still resets; later files never inherit a previous file's notes.
                first_preview = (previous["asset_id"] is None and preview is not None
                                 and previous["binding"] == context["binding"])
                if not first_preview:
                    state["comments"] = [item for item in state["comments"] if item["kind"] != stage]
            bindings[stage] = context

    def _invalidate(self, record, before):
        clone_changed = before[0] != self._clone_binding(record)
        selected = self._selected(record, "clone")
        prior = record["approvals"].get("clone")
        preview_changed = prior and (not selected or prior["assetId"] != selected[0]["id"])
        if clone_changed:
            record["state"]["sourceRev"] += 1
        if clone_changed or preview_changed:
            record["approvals"]["clone"] = None
            record["state"].update(cloneChecks={}, cloneConfirm=False)
        edit_changed = before[1] != self._edit_binding(record)
        if clone_changed or edit_changed:
            record["state"]["editRev"] += 1
            record["approvals"]["final"] = None
            record["state"].update(finalChecks={}, finalConfirm=False)

    def _snapshot(self, record):
        state = clone(record["state"])
        state.update(revision=record["revision"], history=clone(record["history"]))
        generation_binding = self._generation_binding(record)
        for shot in state["shots"]:
            shot["returned_current"] = bool(shot.get("files") and shot.get("receivedSignature") == generation_binding
                                             and shot["out"] <= shot["files"][0].get("duration", 0))
        approvals = {}
        for stage in ("clone", "final"):
            valid = self._approval_valid(record, stage)
            value = clone(record["approvals"].get(stage))
            if value:
                value.update(valid=valid, serverRecorded=True)
            approvals[stage] = value
            state[stage + "Approval"] = value if valid else None
        public_engines = {}
        for stage, item in record["engines"].items():
            current = item["binding"] == self._stage_binding(record, stage)
            public_engines[stage] = {"current": current, "status": item.get("status", "prepared") if current else "stale",
                                     "preview_kind": "reference_study" if stage == "clone" else stage}
        return {"project_id": record["project_id"], "revision": record["revision"], "state": state,
                "engine": public_engines, "approval": approvals,
                "motion_measurements": [self._motion_public(record, item)
                                        for item in record.get("motion_measurements", [])[-20:]],
                "quality_evidence": clone(record.get("quality_evidence", [])),
                "temporal_evidence": clone(record.get("temporal_evidence", [])),
                "reference_scene_inventory": clone(record.get("reference_scene_inventory")),
                # Internal host envelope. The MCP layer signs these paths and removes them
                # before exposing a response. state.assets never contains a local path.
                "assets": [{**self._public_file(item), "path": item["path"]}
                           for item in record["files"].values()],
                "video_generation_policy": {"mode": "prompt_export_only", "automatic_video_generation": False}}

    def get_project(self, project_id):
        return self._snapshot(self._load(project_id))

    def list_projects(self):
        result = []
        for directory in self.data_dir.iterdir():
            if directory.is_symlink() or not directory.is_dir():
                continue
            try:
                record = self._load(directory.name)
            except (ValidationError, ValueError, OSError):
                continue
            result.append({"project_id": record["project_id"], "revision": record["revision"],
                           "name": record["state"]["name"], "updated_at": record.get("updated_at"),
                           "clone_approved": self._approval_valid(record, "clone"),
                           "final_approved": self._approval_valid(record, "final")})
        return sorted(result, key=lambda item: item.get("updated_at") or "", reverse=True)

    def _file_ids(self, record, values, role, shot_id=None):
        require(isinstance(values, list) and len(values) <= MAX_INPUTS, "ui_files", "Expected bounded file selections")
        result = []
        seen = set()
        for raw in values:
            identifier = raw.get("id", raw.get("asset_id")) if isinstance(raw, dict) else raw
            item = record["files"].get(identifier) if isinstance(identifier, str) else None
            require(item and item["role"] == role and (role != "shot" or item.get("shot_id") == shot_id),
                    "unknown_asset", "Use a file uploaded to this project and role")
            require(identifier not in seen, "duplicate_asset", "File is selected more than once")
            seen.add(identifier)
            result.append(self._public_file(item))
        return result

    def _merge_ui(self, record, incoming):
        require(isinstance(incoming, dict), "ui_state", "Expected a project object")
        require(incoming.get("schema", "editor-ultra-interface/1") == "editor-ultra-interface/1",
                "ui_schema", "Unsupported interface state")
        state = record["state"]
        for key in _TEXT_FIELDS:
            if key in incoming:
                state[key] = _text(incoming[key])
        for key, choices in {"sourceType": {"video", "image", "template", "brief"}, "ratio": {"9:16", "16:9"},
                             "mode": {"ready", "generate"}}.items():
            if key in incoming:
                require(incoming[key] in choices, "ui_choice", "Unsupported selection: " + key)
                state[key] = incoming[key]
        if "step" in incoming:
            require(type(incoming["step"]) is int and 0 <= incoming["step"] <= 4, "ui_step", "Invalid step")
            state["step"] = incoming["step"]
        if "targetDuration" in incoming:
            state["targetDuration"] = _number(incoming["targetDuration"], .1, 600)
        if "preserve" in incoming:
            require(isinstance(incoming["preserve"], list) and len(incoming["preserve"]) <= 30,
                    "ui_preserve", "Expected bounded preservation choices")
            state["preserve"] = [_text(v, 200) for v in incoming["preserve"]]
        if "templateId" in incoming:
            state["templateId"] = None if incoming["templateId"] is None else _identifier(incoming["templateId"])
        if "assets" in incoming:
            require(isinstance(incoming["assets"], dict), "ui_assets", "Expected asset selections")
            for role in ROLES - {"shot"}:
                if role in incoming["assets"]:
                    state["assets"][role] = self._file_ids(record, incoming["assets"][role], role)
        if "shots" in incoming:
            require(isinstance(incoming["shots"], list) and len(incoming["shots"]) <= 40, "ui_shots", "At most 40 shots")
            old = {s["id"]: s for s in state["shots"]}
            shots = []
            for raw in incoming["shots"]:
                require(isinstance(raw, dict), "ui_shot", "Expected a shot object")
                identifier = _identifier(raw.get("id"))
                require(identifier not in {s["id"] for s in shots}, "ui_shot", "Duplicate shot ID")
                seconds = _number(raw.get("seconds", 8), .1, 120)
                start = _number(raw.get("in", 0), 0, seconds)
                end = _number(raw.get("out", seconds), 0, seconds)
                require(start < end, "ui_trim", "Shot end must be after its start")
                shot = {"id": identifier, "seconds": seconds, "in": start, "out": end,
                        **{key: _text(raw.get(key, ""), 5000) for key in ("environment", "action", "camera")}}
                previous = old.get(identifier, {})
                shot["files"] = self._file_ids(record, raw.get("files", previous.get("files", [])), "shot", identifier)
                shot["rev"] = previous.get("rev", 0) + int(any(previous.get(k) != v for k, v in shot.items() if k != "files"))
                shot["receivedSignature"] = previous.get("receivedSignature")
                shots.append(shot)
            state["shots"] = shots
        for key in ("cloneChecks", "finalChecks"):
            if key in incoming:
                require(isinstance(incoming[key], dict) and len(incoming[key]) <= 30, "ui_checks", "Invalid checklist")
                require(all(str(k).isdigit() and v in {"", "ok", "na", "fix"} for k, v in incoming[key].items()),
                        "ui_checks", "Unsupported checklist value")
                state[key] = clone(incoming[key])
        for key in ("cloneConfirm", "finalConfirm"):
            if key in incoming:
                require(type(incoming[key]) is bool, "ui_review_draft", "Review draft confirmation must be a boolean")
                state[key] = incoming[key]
        if "comments" in incoming:
            require(isinstance(incoming["comments"], list) and len(incoming["comments"]) <= 200,
                    "ui_review_draft", "At most 200 review notes are allowed")
            comments, identifiers = [], set()
            for raw in incoming["comments"]:
                require(isinstance(raw, dict) and raw.get("kind") in {"clone", "final"},
                        "ui_review_draft", "Choose the review stage for each note")
                identifier = _identifier(raw.get("id"))
                require(identifier not in identifiers, "ui_review_draft", "Review note IDs must be unique")
                identifiers.add(identifier)
                time = _text(raw.get("time", ""), 20)
                text = _text(raw.get("text", ""), 2000)
                require(bool(re.fullmatch(r"\d{1,3}:[0-5]\d(?:[.,]\d+)?", time)) and bool(text.strip()),
                        "ui_review_draft", "Use a mm:ss timecode and a nonempty review note")
                resolved = raw.get("resolved", False)
                require(type(resolved) is bool, "ui_review_draft", "Review note resolution must be a boolean")
                comments.append({"id": identifier, "kind": raw["kind"], "time": time, "text": text,
                                 "component": _text(raw.get("component", ""), 120), "resolved": resolved})
            state["comments"] = comments
        # Approvals, file paths/hashes, revisions, and histories are never imported.

    def save_project(self, project_id: str | None, state: dict, expected_revision: int | None = None):
        if project_id is None:
            require(expected_revision in (None, 0), "revision_conflict", "A new project has no previous revision")
            project_id = str(uuid.uuid4())
            directory = self._directory(project_id)
            directory.mkdir(mode=0o700)
            record = {"project_id": project_id, "revision": 0, "state": _default_state(project_id),
                      "files": {}, "engines": {}, "approvals": {"clone": None, "final": None},
                      "preview_versions": {"clone": 0, "final": 0}, "history": []}
            try:
                self._merge_ui(record, state)
                self._write(record, "Projeto criado")
            except Exception:
                # Only the just-created empty adapter directory is removed.
                if not any(directory.iterdir()):
                    directory.rmdir()
                raise
            return self._snapshot(record)
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            before = self._clone_binding(record), self._edit_binding(record)
            self._merge_ui(record, state)
            self._invalidate(record, before)
            self._write(record, "Escolhas atualizadas")
            return self._snapshot(record)

    def _measure(self, path, mime_type):
        if mime_type.startswith("image/"):
            from PIL import Image
            with Image.open(path) as image:
                require(image.width * image.height <= 40_000_000, "image_size", "Image exceeds the pixel limit")
                image.verify()
            with Image.open(path) as image:
                return {"width": image.width, "height": image.height,
                        "type": Image.MIME.get(image.format, mime_type)}
        command = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-show_streams", "-show_format", "-of", "json", str(path)]
        try:
            result = subprocess.run(command, check=True, capture_output=True, timeout=40)
            media = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise ValidationError("invalid_media", "The uploaded file could not be inspected") from exc
        fmt = media.get("format", {})
        require(not set(fmt.get("format_name", "").split(",")) & {"hls", "dash", "concat", "image2", "image2pipe", "png_pipe", "jpeg_pipe", "webp_pipe"},
                "invalid_media", "Provide self-contained media, not a still image or playlist labelled as video")
        streams = media.get("streams", [])
        videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
        audios = [s for s in streams if s.get("codec_type") == "audio"]
        require(bool(videos) if mime_type.startswith("video/") else bool(audios), "invalid_media", "Missing required media stream")
        duration = float(fmt.get("duration", (videos or audios)[0].get("duration", 0)))
        require(math.isfinite(duration) and 0 < duration <= 600, "media_duration", "Media must be between 0 and 600 seconds")
        info = {"duration": duration, "type": mime_type}
        if videos:
            require(len(videos) == 1, "video_stream", "Only one video stream is supported")
            info.update(width=videos[0]["width"], height=videos[0]["height"], fps=videos[0].get("avg_frame_rate"))
        return info

    def import_local_file(self, project_id, role, source: Path, filename: str, mime_type: str,
                          shot_id=None, *, expected_revision=None, host_file_id=None):
        require(role in ROLES, "asset_role", "Unsupported media role")
        require(isinstance(mime_type, str), "asset_type", "Declare a MIME type")
        if host_file_id is not None:
            require(bool(_text(host_file_id, 300).strip()), "host_file_id", "Use a nonempty host file identifier")
        allowed = {"narration": ("audio/",), "logo": ("image/",), "footage": ("video/",),
                   "result": ("video/",), "shot": ("video/",)}.get(role, ("video/", "image/"))
        require(mime_type.startswith(allowed), "asset_type", "Media type does not match the selected role")
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            shot = next((s for s in record["state"]["shots"] if s["id"] == shot_id), None)
            require(role != "shot" or shot is not None, "shot_missing", "Select an existing shot")
            before = self._clone_binding(record), self._edit_binding(record)
            source = Path(source)
            require(source.is_file() and not source.is_symlink() and 0 < source.stat().st_size <= MAX_FILE_BYTES,
                    "asset_file", "Supply a regular uploaded file under 512 MiB")
            previous = next((item for item in record["files"].values()
                             if host_file_id is not None and item.get("hostFileId") == host_file_id
                             and item["role"] == role and item.get("shot_id") == shot_id), None)
            if previous is not None:
                # An acknowledged host upload can be retried after a lost response.
                # The identifier never substitutes for inspecting and hashing bytes.
                info = self._measure(source, mime_type)
                require(file_sha256(source) == previous["sha256"] and info["type"] == previous["type"],
                        "host_file_conflict", "This host file identifier already belongs to different media")
                self.resolve_asset(project_id, previous["id"])
                return {**self._snapshot(record), "asset_id": previous["id"],
                        "asset": self._public_file(previous), "idempotent": True}
            require(sum(not x.get("internal") for x in record["files"].values()) < MAX_INPUTS,
                    "asset_limit", "Project input limit reached")
            identifier = uuid.uuid4().hex
            suffix = mimetypes.guess_extension(mime_type) or ".bin"
            directory = self._directory(project_id) / "media"
            directory.mkdir(exist_ok=True, mode=0o700)
            destination = directory / (identifier + suffix)
            try:
                with source.open("rb") as incoming, destination.open("xb") as output:
                    shutil.copyfileobj(incoming, output)
                info = self._measure(destination, mime_type)
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            item = {"id": identifier, "name": Path(_text(filename, 500)).name or identifier + suffix,
                    "path": str(destination), "size": destination.stat().st_size, "sha256": file_sha256(destination),
                    "role": role, "shot_id": shot_id, **info}
            if host_file_id is not None:
                item["hostFileId"] = host_file_id
            if role in {"clone", "result"}:
                item["basis_binding"] = self._preview_binding(record, "clone" if role == "clone" else "final")
            record["files"][identifier] = item
            public = self._public_file(item)
            if role == "shot":
                generation = record["engines"].get("generation", {})
                if generation.get("binding") == self._generation_basis(record) and generation.get("direction_hash"):
                    clip_id = generation.get("clip_mapping", {}).get(shot_id)
                    require(clip_id, "shot_mapping", "Bind the UI shot to a clip in the authored generation plan")
                    engine.receive_clip(generation["directory"], clip_id, destination)
                    item["generation_clip_id"] = clip_id
                    item["generation_receipt"] = self._portable(record, engine.artifact(generation["directory"], "return:" + clip_id))
                shot["files"] = [public]
                shot["receivedSignature"] = self._generation_binding(record)
                shot["receivedRev"] = shot["rev"]
            elif role in {"clone", "result", "narration", "logo"}:
                record["state"]["assets"][role] = [public]
            else:
                record["state"]["assets"][role].append(public)
            if role == "clone":
                record["approvals"]["clone"] = None
            if role == "result":
                record["approvals"]["final"] = None
            self._invalidate(record, before)
            self._write(record, "Arquivo recebido: " + role)
            return {**self._snapshot(record), "asset_id": identifier, "asset": public}

    def resolve_asset(self, project_id, asset_id):
        record = self._load(project_id)
        item = record["files"].get(asset_id) if isinstance(asset_id, str) else None
        require(item is not None, "asset_missing", "File not found in this project")
        path = Path(item["path"])
        require(path.resolve().is_relative_to(self._directory(project_id)) and not path.is_symlink(),
                "asset_path", "File escaped the private project")
        verify_file(str(path), item["sha256"], "asset")
        return path

    def _motion_public(self, record, measurement):
        """Evidence stays historical when its project revision or bytes change."""
        result=clone(measurement)
        reason=None
        if measurement["project_revision"]!=record["revision"]:
            reason="project_revision_changed"
        else:
            dependencies=[measurement["source"],*measurement.get("masks",[]),
                          *measurement["artifacts"].values()]
            for dependency in dependencies:
                item=record["files"].get(dependency["asset_id"])
                if not item or item["sha256"]!=dependency["sha256"]:
                    reason="source_mask_or_artifact_changed";break
                try:
                    path=Path(item["path"])
                    require(path.resolve().is_relative_to(self._directory(record["project_id"]))
                            and not path.is_symlink(),"asset_path","Motion evidence escaped the project")
                    verify_file(str(path),dependency["sha256"],"motion evidence")
                except (ValidationError,OSError):
                    reason="source_mask_or_artifact_changed";break
        result.update(current=reason is None,status="measured" if reason is None else "stale",
                      stale_reason=reason)
        return result

    def _motion_storage(self, required):
        limit=int(os.environ.get("EDITOR_ULTRA_MAX_STORAGE_MB","850"))*1024*1024
        used=stored_bytes(self.data_dir)
        require(0<=required<=MOTION_LIMITS["max_artifact_bytes"] and used+required<=limit,
                "motion_storage","Insufficient project storage for the motion evidence")
        require(shutil.disk_usage(self.data_dir).free>=required+64*1024*1024,
                "motion_storage","Insufficient free disk space for the motion evidence")

    def measure_motion(self, project_id, asset_id, specification, *, expected_revision=None):
        """Measure selected elements; store evidence without applying or approving it.

        Input paths are resolved solely from this project's verified asset IDs.
        The request cannot register code, invoke generators, retime footage or
        select arbitrary files. The existing durable MCP job owns idempotency.
        """
        from visual_fidelity import motion_observation, motion_profile, motion_compare
        require(isinstance(specification,dict),"motion_specification","Expected a bounded measurement object")
        try:
            model=MotionMeasurementSpecification.model_validate(specification)
        except ModelValidationError as exc:
            details="; ".join(".".join(map(str,error["loc"]))+": "+error["msg"]
                              for error in exc.errors(include_input=False,include_url=False)[:3])
            raise ValidationError("motion_specification","Invalid bounded motion specification: "+details) from None
        public_spec=model.model_dump(by_alias=True,exclude_none=True)
        with self._lock(project_id):
            record=self._load(project_id);self._expect(record,expected_revision)
            source_path=self.resolve_asset(project_id,asset_id)
            source=record["files"][asset_id]
            require(source["type"].startswith("video/"),"motion_source","Motion measurement requires a video asset")
            self._motion_storage(MOTION_LIMITS["max_artifact_bytes"])
            metadata=self._measure(source_path,source["type"])
            width,height=metadata["width"],metadata["height"];pixels=width*height
            require(0<metadata["duration"]<=MOTION_LIMITS["max_source_seconds"]
                    and 16<=width<=MOTION_LIMITS["max_source_side"]
                    and 16<=height<=MOTION_LIMITS["max_source_side"]
                    and pixels<=MOTION_LIMITS["max_source_pixels"],
                    "motion_budget","Motion sources must be at most 120 seconds and Full HD; select or prepare an explicit smaller source")
            try:
                rate=Fraction(str(metadata.get("fps")))
            except (ValueError,ZeroDivisionError):
                raise ValidationError("motion_budget","Motion source needs a usable bounded nominal FPS") from None
            require(0<rate<=MOTION_LIMITS["max_source_fps"]
                    and math.ceil(metadata["duration"]*float(rate))<=MOTION_LIMITS["max_source_frames"]+2,
                    "motion_budget","Motion source exceeds the 3600-frame CPU clock budget")
            clock=motion_observation.probe_clock(source_path)
            require(clock["frames"]<=MOTION_LIMITS["max_source_frames"]
                    and clock["frames"]*pixels<=MOTION_LIMITS["max_decoded_pixels"],
                    "motion_budget","Motion source exceeds the decoded-frame CPU budget")
            selected={frame for element in model.elements for frame in range(*element.frame_range)}
            require(len(selected)*pixels<=MOTION_LIMITS["max_cached_gray_bytes"],
                    "motion_budget","Selected windows exceed the 128 MiB grayscale cache; split the measurement into shorter windows")
            require(selected and max(selected)<clock["frames"],
                    "motion_range","Measurement interval exceeds the actual source frame count")
            execution_spec=clone(public_spec);mask_inputs=[];mask_by_element={}
            for element in execution_spec["elements"]:
                mask_id=element.pop("mask_asset_id",None)
                if mask_id is not None:
                    mask_path=self.resolve_asset(project_id,mask_id)
                    mask=record["files"][mask_id]
                    require(mask["type"].startswith("image/"),"motion_mask","A seed mask must be an image asset in this project")
                    element["mask_path"]=str(mask_path)
                    binding={"asset_id":mask_id,"sha256":mask["sha256"]}
                    mask_by_element[element["id"]]=binding
                    if binding not in mask_inputs:mask_inputs.append(binding)
            input_revision=record["revision"];identifier=uuid.uuid4().hex
            application_binding={"schema":"editor-ultra-motion-evidence-binding/1",
                                 "project_id":project_id,"measurement_id":identifier,
                                 "input_revision":input_revision,"project_revision":input_revision+1,
                                 "source":{"asset_id":asset_id,"sha256":source["sha256"]},
                                 "masks":mask_inputs,"specification_sha256":digest(public_spec),
                                 "scope":"evidence_not_applied"}
            observations=motion_observation.measure_video(source_path,execution_spec)
            require(observations["source"]["sha256"]==source["sha256"],
                    "motion_source_changed","The source changed while motion was being measured")
            self.resolve_asset(project_id,asset_id)
            for element in observations["elements"]:
                if element["id"] in mask_by_element:
                    expected=mask_by_element[element["id"]];receipt=element["selection"]["mask"]
                    self.resolve_asset(project_id,expected["asset_id"])
                    require(receipt and receipt["sha256"]==expected["sha256"],
                            "motion_mask_changed","The seed mask changed while motion was being measured")
                    receipt.pop("path",None);receipt["asset_id"]=expected["asset_id"]
            observations["application_binding"]=clone(application_binding)
            observations["measurement"]["application_specification"]=public_spec
            profile=motion_profile.fit_profile(observations,method="pchip",max_gap_frames=1)
            profile["application_binding"]=clone(application_binding)
            audit,rows=motion_compare.audit_profile(profile,subsamples=4)
            audit["application_binding"]=clone(application_binding)
            documents={"observations":observations,"profile":profile,"qa":audit}
            encoded={key:json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+"\n"
                     for key,value in documents.items()}
            import io
            csv_text=io.StringIO(newline="")
            if rows:
                writer=csv.DictWriter(csv_text,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            else:csv_text.write("element_id,time_s\n")
            encoded["csv"]=csv_text.getvalue()
            actual_bytes=sum(len(value.encode("utf-8")) for value in encoded.values())
            self._motion_storage(actual_bytes)
            directory=self._directory(project_id)/"motion-evidence"/identifier
            directory.mkdir(parents=True,exist_ok=False,mode=0o700)
            artifacts={}
            try:
                for kind,value in encoded.items():
                    path=directory/(kind+(".csv" if kind=="csv" else ".json"))
                    with path.open("x",encoding="utf-8",newline="") as handle:handle.write(value)
                    artifacts[kind]=self._public_file(self._register_internal(record,path,role="evidence"))
                measurement={**application_binding,"schema":"editor-ultra-motion-measurement/1",
                             "id":identifier,"created_at":_now(),"artifacts":artifacts,
                             "profile_sha256":motion_profile.profile_digest(profile),
                             "render_status":"pending_not_applied","visual_approval":"pending",
                             "user_approved":False,"perceptual_playback":False,
                             "summary":{"method":observations["measurement"]["method"],
                                        "clock_kind":observations["source"]["clock_kind"],
                                        "requested_element_frames":sum(e.frame_range[1]-e.frame_range[0] for e in model.elements),
                                        "cached_gray_bytes":len(selected)*pixels,"csv_rows":len(rows),
                                        "elements":audit["elements"]},
                             "limits":clone(MOTION_LIMITS),
                             "next_action":"Inspect evidence and author explicit bindings; this operation has not applied motion to a render"}
                record.setdefault("motion_measurements",[]).append(measurement)
                self._write(record,"Movimento medido; evidência pendente de aplicação")
            except BaseException:
                shutil.rmtree(directory,ignore_errors=True)
                raise
            return {**self._snapshot(record),"status":"motion_measured",
                    "motion_measurement":self._motion_public(record,measurement)}

    def _stage_binding(self, record, stage):
        return self._clone_binding(record) if stage == "clone" else self._generation_basis(record) if stage == "generation" else self._edit_binding(record)

    def _brief(self, record, stage):
        s = record["state"]
        lines = [s["objective"] or "Preparar este projeto audiovisual a partir das escolhas e dos arquivos fornecidos.",
                 "Preservar: " + "; ".join(s["preserve"]), "Adaptação solicitada: " + s["adapt"],
                 "Formato solicitado: " + s["ratio"], "Direção adicional: " + s["editNotes"]]
        if stage == "clone":
            lines.append("ESTUDO TÉCNICO DA REFERÊNCIA: o render usa a referência como base de estudo. Não representa nova pessoa, recuperação de camadas ocultas ou fidelidade certificada. A direção deve ser autorada a partir de inspeção real; preservar sem intervenção não constitui clonagem.")
        else:
            lines.append("Usar exclusivamente a nova filmagem como fonte da edição. Referência e prévia orientam estilo; refazer tracking e máscaras. Não inferir observações, fontes, recursos ou efeitos indisponíveis.")
        return "\n".join(lines)

    def _new_engine(self, record, stage, inputs, intent):
        old = record["engines"].get(stage)
        binding = self._stage_binding(record, stage)
        if old and old["binding"] == binding:
            return Path(old["directory"])
        directory = self._directory(record["project_id"]) / "engines" / (stage + "-" + uuid.uuid4().hex)
        s = record["state"]
        if s.get("templateId") and self.template_library:
            library = Path(self.template_library).resolve()
            require(library.is_file(), "template_missing", "The selected template catalog is not installed")
            inputs = [*inputs, {"id": "selected-template-library", "role": "template_library", "media_type": "json",
                                "status": "ready", "path": str(library), "sha256": file_sha256(library)}]
        answers = {"objective": s["objective"] or self._brief(record, stage), "aspect_ratio": s["ratio"],
                   "target_duration_s": s["targetDuration"], "instruction_language": "pt-BR", "dialogue_language": "pt-BR"}
        if stage == "generation":
            answers.update(ui_scene_requests=[{k: shot[k] for k in ("id", "seconds", "in", "out", "environment", "action", "camera")}
                                               for shot in s["shots"]],
                           identity_request=s["identityLabel"], narration_request=s["narration"], music_request=s["music"])
        if s["audience"]:
            answers["audience"] = s["audience"]
        spec = {"schema": engine.SPEC_SCHEMA, "id": stage + "-" + record["project_id"], "intent": intent,
                "brief": self._brief(record, stage), "inputs": inputs,
                "generation_answers": answers if stage == "generation" else {}, "preferences": {},
                "requirements": [], "settings": {"max_review_retries": 2}}
        engine.create_project(directory, spec)
        record["engines"][stage] = {"binding": binding, "directory": str(directory), "status": "created"}
        return directory

    def _input(self, item, role=None):
        return {"id": item["id"], "role": role or {"ref": "reference", "footage": "footage", "identity": "image",
                "narration": "audio", "logo": "image"}.get(item["role"], "resource"),
                "media_type": item["type"].split("/")[0], "status": "ready", "path": item["path"],
                "sha256": item["sha256"], "purpose": item["role"]}

    def _register_internal(self, record, path, *, role="evidence", name=None):
        path = Path(path)
        require(path.resolve().is_relative_to(self._directory(record["project_id"])), "asset_path", "Internal file outside project")
        for item in record["files"].values():
            if item["path"] == str(path):
                return item
        require(path.is_file() and not path.is_symlink(), "artifact_missing", "Engine file is missing")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        item = {"id": uuid.uuid4().hex, "name": name or path.name, "path": str(path), "type": mime,
                "size": path.stat().st_size, "sha256": file_sha256(path), "role": role, "internal": True}
        record["files"][item["id"]] = item
        return item

    def _portable(self, record, value):
        """Return opaque handles instead of server filesystem paths, including JSON text payloads."""
        if isinstance(value, dict):
            return {k: self._portable(record, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._portable(record, v) for v in value]
        if isinstance(value, str):
            if value.startswith("/"):
                path = Path(value)
                if path.is_file() and path.resolve().is_relative_to(self._directory(record["project_id"])):
                    return "asset:" + self._register_internal(record, path)["id"]
                return "[private resource unavailable]"
            if value.startswith("{"):
                try:
                    return json.dumps(self._portable(record, json.loads(value)), ensure_ascii=False)
                except ValueError:
                    pass
        return value

    def _direction_payload(self, record, value):
        """Resolve declared file handles; do not accept commands, URLs or arbitrary paths."""
        if isinstance(value, dict):
            result = {}
            for key, raw in value.items():
                require(key not in {"command", "shell", "exec", "argv", "endpoint", "api_key", "api_key_env"},
                        "unsafe_direction", "Executable or credential fields are not accepted")
                if key == "path" or key.endswith("_path"):
                    require(isinstance(raw, str) and raw.startswith("asset:"), "direction_path", "Use asset:<id> for file references")
                    result[key] = str(self.resolve_asset(record["project_id"], raw[6:]))
                else:
                    result[key] = self._direction_payload(record, raw)
            return result
        if isinstance(value, list):
            return [self._direction_payload(record, v) for v in value]
        require(not isinstance(value, str) or not value.startswith(("file:", "http://", "https://", "/", "\\")),
                "direction_path", "Network and filesystem addresses are not executable direction inputs")
        return value

    def _prepare(self, record, stage):
        require(stage in {"clone", "edit", "generation", "assembly"}, "engine_kind", "Unsupported stage")
        refs = self._selected(record, "ref")
        if stage == "clone":
            videos = [a for a in refs if a["type"].startswith("video/")]
            if len(videos) != 1:
                context = None
                if record["state"].get("templateId") and self.template_library:
                    from editorial_engine.templates import library_request
                    context = library_request(Path(self.template_library),
                                              template_ids=[record["state"]["templateId"]], verify_files=True)
                record["engines"][stage] = {"binding": self._stage_binding(record, stage), "directory": None,
                                            "status": "awaiting_host_production"}
                return {"kind": stage, "status": "awaiting_host_production",
                        "request": self._portable(record, {"schema": "editor-ultra-host-production-request/1",
                            "brief": {"objective": record["state"]["objective"], "adaptation": record["state"]["adapt"],
                                      "ratio": record["state"]["ratio"], "notes": record["state"]["editNotes"]},
                            "references": [self._public_file(a) for a in refs],
                            "template_context": context,
                            "required": "Inspect the supplied inputs, author the production direction and produce a real preview; import that file as role clone for explicit review.",
                            "priorities": record["state"]["preserve"]}),
                        "limitations": ["Image/template/brief input has no universal automatic cloning renderer.",
                                        "A source URL is a user note; no download or external generation was executed.",
                                        "Template context describes verified catalog options and does not assert their execution."]}
            source = videos[0]
            # Only this explicitly labelled study may use reference bytes as its source.
            directory = self._new_engine(record, stage, [self._input(source, "footage")], "edit")
            engine.advance_project(directory)
            if record["state"].get("templateId") and self.template_library:
                engine.request_direction(directory, kind="edit", input_id=source["id"],
                                         template_input_id="selected-template-library",
                                         template_ids=[record["state"]["templateId"]])
            request = engine.artifact(directory, "edit_request")
        elif stage == "generation":
            require(self._approval_valid(record, "clone"), "clone_approval_required", "Approve the current real clone preview before preparing generation")
            inputs = [self._input(a) for a in refs + self._selected(record, "identity") + self._selected(record, "narration")]
            require(not any(a["media_type"] == "video" and a["role"] == "image" for a in inputs),
                    "identity_kind", "Video identity references need an explicit resource mapping in the authored plan")
            videos = [a for a in refs if a["type"].startswith("video/")]
            directory = self._new_engine(record, stage, inputs, "reference_generate" if videos else "original")
            status = engine.advance_project(directory)
            current = engine.load_project(directory)["artifacts"]
            if current.get("generation_request", {}).get("status") != "current":
                request = {"schema": "editor-ultra-reference-authoring-request/1", "status": status,
                           "required": "Provide observed reference evidence and an explicit keep/replace adaptation before generation direction.",
                           "analyses": {a["id"]: engine.artifact(directory, "analysis:" + a["id"]) for a in videos}}
            else:
                if record["state"].get("templateId") and self.template_library:
                    engine.request_direction(directory, kind="generation",
                                             reference_id=videos[0]["id"] if len(videos) == 1 else None,
                                             template_input_id="selected-template-library",
                                             template_ids=[record["state"]["templateId"]])
                request = engine.artifact(directory, "generation_request")
        else:
            require(self._approval_valid(record, "clone"), "clone_approval_required", "Approve the current real clone preview first")
            sources = self._selected(record, "footage") if record["state"]["mode"] == "ready" else self._shot_files(record)
            require(bool(sources), "footage_required", "Upload the actual new footage")
            if record["state"]["mode"] == "generate":
                signature = self._generation_binding(record)
                require(all(s.get("files") and s.get("receivedSignature") == signature for s in record["state"]["shots"]),
                        "stale_clip", "Receive every clip against the current direction")
                require(all(s["out"] <= s["files"][0].get("duration", 0) for s in record["state"]["shots"]),
                        "clip_duration", "The actual returned video must cover its declared trim")
            ref_hashes = {a["sha256"] for a in refs}
            require(not any(a["sha256"] in ref_hashes for a in sources), "reference_as_footage", "New footage cannot be the reference video")
            if stage == "edit":
                require(len(sources) == 1, "assembly_required", "Multiple sources need an explicit assembly plan before finishing")
            directory = self._new_engine(record, stage, [self._input(a, "footage") for a in sources],
                                         "edit" if stage == "edit" else "montage")
            if stage == "assembly":
                request = {"schema": "editor-ultra-assembly-request/1", "sources": [self._public_file(a) for a in sources],
                           "required": "Author video-assembly/1 with asset:<id> sources, explicit trims, output clock, audio and transitions."}
            else:
                engine.advance_project(directory)
                if record["state"].get("templateId") and self.template_library:
                    engine.request_direction(directory, kind="edit", input_id=sources[0]["id"],
                                             template_input_id="selected-template-library",
                                             template_ids=[record["state"]["templateId"]])
                request = engine.artifact(directory, "edit_request")
        record["engines"][stage]["status"] = "awaiting_direction"
        result = {"kind": stage, "status": "awaiting_direction", "request": self._portable(record, request)}
        if stage in {"clone", "edit"}:
            analysis = engine.artifact(directory, "analysis:" + source["id"] if stage == "clone" else "analysis:" + sources[0]["id"])
            result["analysis"] = self._portable(record, analysis)
        result["limitations"] = ["No semantic observations, faithful-clone claim or user approval are inferred.",
                                "Reference study uses reference pixels; new footage editing does not.",
                                "Video generation exports prompts only."]
        return result

    def prepare(self, project_id, kind, *, expected_revision=None):
        kind = "generation" if kind == "prompts" else kind
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            # The UI's edit action must expose the existing multi-source route.
            # Only routing is selected here; trims/order/transitions still need authorship.
            if kind == "edit":
                sources = (self._selected(record, "footage") if record["state"]["mode"] == "ready"
                           else self._shot_files(record))
                if len(sources) > 1:
                    kind = "assembly"
            result = self._prepare(record, kind)
            self._write(record, "Preparação real: " + kind)
            return {**self._snapshot(record), **result}

    def apply_direction(self, project_id, kind, direction: dict, *, expected_revision=None):
        require(kind in {"clone", "edit", "generation", "assembly"}, "engine_kind", "Unsupported direction kind")
        require(isinstance(direction, dict) and len(json.dumps(direction)) <= 4 * 1024 * 1024,
                "direction_size", "Direction must be a bounded JSON object")
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            stage = record["engines"].get(kind)
            if not stage or stage["binding"] != self._stage_binding(record, kind):
                self._prepare(record, kind)
                stage = record["engines"][kind]
            require(stage.get("directory"), "host_production_required", "This route requires an externally produced preview, then import and review")
            directory = Path(stage["directory"])
            payload = self._direction_payload(record, clone(direction))
            if kind == "generation" and "reference" in payload:
                ref = payload["reference"]
                reference_id = ref.get("input_id")
                require(reference_id in {a["id"] for a in self._selected(record, "ref")}, "reference_input", "Choose a reference belonging to this project")
                engine.describe_reference(directory, reference_id, ref["observations"], author=ref["author"])
                dossier = engine.artifact(directory, "dossier:" + reference_id)
                adaptation = {**ref["adaptation"], "dossier_sha256": dossier["dossier_sha256"]}
                engine.adapt_reference(directory, reference_id, adaptation)
                template_options = ({"template_input_id": "selected-template-library",
                                     "template_ids": [record["state"]["templateId"]]}
                                    if record["state"].get("templateId") and self.template_library else {})
                engine.request_direction(directory, kind="generation", reference_id=reference_id,
                                         include_images=False, **template_options)
                if "plan" not in payload:
                    result = self._portable(record, engine.artifact(directory, "generation_request"))
                    self._write(record, "Referência observada e pedido de geração preparado")
                    return {**self._snapshot(record), "status": "awaiting_direction", "request": result}
            plan = payload.get("plan", payload)
            if kind == "generation":
                shot_ids = {shot["id"] for shot in record["state"]["shots"]}
                clip_ids = {clip.get("id") for clip in plan.get("clips", [])}
                mapping = payload.get("ui_shot_mapping", {identifier: identifier for identifier in shot_ids})
                require(isinstance(mapping, dict) and set(mapping) == shot_ids
                        and all(value in clip_ids for value in mapping.values())
                        and len(set(mapping.values())) == len(mapping),
                        "shot_mapping", "Use matching UI shot/plan clip IDs, or provide an explicit ui_shot_mapping")
            if kind == "assembly":
                selected = self._selected(record, "footage") if record["state"]["mode"] == "ready" else self._shot_files(record)
                authorized = {item["path"]: item["sha256"] for item in selected}
                require(all(authorized.get(source.get("path")) == source.get("sha256")
                            for source in plan.get("sources", [])),
                        "assembly_source", "Assembly sources must be the selected new footage")
                engine.plan_assembly(directory, plan)
            else:
                engine.accept_direction(directory, plan, kind="generation" if kind == "generation" else "edit")
            before = self._clone_binding(record), self._edit_binding(record)
            stage["direction_hash"] = digest({"plan": plan, "ui_shot_mapping": mapping}) if kind == "generation" else digest(plan)
            if kind == "generation":
                stage["clip_mapping"] = mapping
            versions = record.setdefault("preview_versions", {"clone": 0, "final": 0})
            if kind == "clone":
                versions["clone"] += 1
                record["approvals"]["clone"] = None
            if kind in {"clone", "edit", "assembly"}:
                versions["final"] += 1
                record["approvals"]["final"] = None
            self._invalidate(record, before)
            stage["status"] = "ready_export" if kind == "generation" else "ready_render"
            if kind == "generation":
                engine.export_prompts(directory)
                stage["status"] = "prompts_exported"
                result = {"prompt_pack": self._portable(record, engine.artifact(directory, "prompt_pack"))}
            else:
                result = {}
            self._write(record, "Direção validada: " + kind)
            return {**self._snapshot(record), "status": stage["status"], **result}

    def render(self, project_id, kind, *, expected_revision=None):
        require(kind in {"clone", "edit", "assembly"}, "engine_kind", "Only local study, editing and assembly can render")
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            stage = record["engines"].get(kind)
            require(stage and stage["binding"] == self._stage_binding(record, kind), "stale_direction", "Prepare and author current direction before rendering")
            require(stage.get("directory"), "host_production_required", "No renderer has been prepared for this route; import a real produced preview")
            require(kind == "clone" or self._approval_valid(record, "clone"), "clone_approval_required", "Current preview approval is required")
            directory = Path(stage["directory"])
            engine.render_project(directory, kind="assembly" if kind == "assembly" else "edit")
            rendered = engine.artifact(directory, "render")
            role = "clone" if kind == "clone" else "result"
            item = self._register_internal(record, rendered["path"], role=role,
                                           name="Estudo-da-referencia.mp4" if kind == "clone" else "Edicao-renderizada.mp4")
            item.update(duration=rendered["duration_s"], fps=rendered["fps"])
            item["basis_binding"] = self._preview_binding(record, "clone" if kind == "clone" else "final")
            public = self._public_file(item)
            before = self._clone_binding(record), self._edit_binding(record)
            record["state"]["assets"][role] = [public]
            record["approvals"]["clone" if kind == "clone" else "final"] = None
            self._invalidate(record, before)
            stage["status"] = "rendered_unreviewed"
            stage["render_asset_id"] = item["id"]
            receipt = self._portable(record, rendered)
            self._write(record, "Render real concluído: " + ("estudo da referência" if kind == "clone" else kind))
            return {**self._snapshot(record), "status": "rendered_unreviewed", "asset_id": item["id"],
                    "asset": public, "result": receipt,
                    "preview_kind": "reference_study" if kind == "clone" else kind}

    def compare_clone(self, project_id, frames=None, *, expected_revision=None):
        """Compare selected reference/clone at exact frames and persist evidence.

        Never creates or approves a new clone. Runs only on verified, project-owned
        asset IDs; neither the caller nor a project document can supply a path.
        """
        from visual_fidelity.reference_fidelity import audit_pair, _clock, sample_frame_indices
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            references = [a for a in self._selected(record, "ref") if a["type"].startswith("video/")]
            candidates = [a for a in self._selected(record, "clone") if a["type"].startswith("video/")]
            require(len(references) == 1 and len(candidates) == 1,
                    "fidelity_inputs", "Exactly one reference video and one clone video are required")
            reference, candidate = references[0], candidates[0]
            ref_path = self.resolve_asset(project_id, reference["id"])
            clone_path = self.resolve_asset(project_id, candidate["id"])
            # Legacy imports may lack nb_frames metadata. Always resolve the
            # sample window against the source bytes now, not container duration.
            actual_frame_count = _clock(ref_path)["frame_count"]
            if frames is None:
                frames = sample_frame_indices(actual_frame_count)
            directory = self._directory(project_id) / "fidelity" / uuid.uuid4().hex
            try:
                report = audit_pair(ref_path, clone_path, directory, frames)
                report_item = self._register_internal(record, directory / "comparison_report.json",
                                                       role="evidence")
                image_item = self._register_internal(record, directory / "aligned_contact_sheet.jpg",
                                                      role="evidence")
            except Exception:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            entry = {"reference_asset_id": reference["id"], "clone_asset_id": candidate["id"],
                     "source_sha256": reference["sha256"], "clone_sha256": candidate["sha256"],
                     "report_asset_id": report_item["id"], "image_asset_id": image_item["id"],
                     "frames": list(frames), "status": "diagnostic_not_approved"}
            record.setdefault("quality_evidence", []).append(entry)
            record["quality_evidence"] = record["quality_evidence"][-30:]
            self._write(record, "Comparação exata de referência e clone; sem aprovação")
            return {**self._snapshot(record), "status": "quality_evidence_recorded",
                    "comparison": report, "report_asset": self._public_file(report_item),
                    "image_asset": self._public_file(image_item)}

    def compare_temporal(self, project_id, *, center_s=0.0, expected_revision=None):
        """Inspect a bounded three-second source-clock window at the selected time.

        The motion diagnostics remain evidence. They do not replace authored
        element trajectories, a scene reconstruction, or a user's rejection.
        """
        from visual_fidelity.reference_fidelity import _clock
        from visual_fidelity.reference_temporal_qa import (
            measure_reference_cadence_gap, window_around_seconds)
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            refs = [a for a in self._selected(record, "ref") if a["type"].startswith("video/")]
            copies = [a for a in self._selected(record, "clone") if a["type"].startswith("video/")]
            require(len(refs) == 1 and len(copies) == 1, "cadence_inputs",
                    "A reference video and clone video must be selected")
            source, candidate = refs[0], copies[0]
            ref_path = self.resolve_asset(project_id, source["id"])
            candidate_path = self.resolve_asset(project_id, candidate["id"])
            windows = window_around_seconds(_clock(ref_path), center_s)
            folder = self._directory(project_id) / "cadence" / uuid.uuid4().hex
            try:
                report = measure_reference_cadence_gap(ref_path, candidate_path, folder, ranges=windows)
                report_asset = self._register_internal(record, folder / "temporal_report.json", role="evidence")
                csv_asset = self._register_internal(record, folder / "temporal_frames.csv", role="evidence")
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise
            evidence = {"source_asset_id": source["id"], "candidate_asset_id": candidate["id"],
                        "source_sha256": source["sha256"], "candidate_sha256": candidate["sha256"],
                        "report_asset_id": report_asset["id"], "csv_asset_id": csv_asset["id"],
                        "windows": windows, "status": "diagnostic_not_approved"}
            record.setdefault("temporal_evidence", []).append(evidence)
            record["temporal_evidence"] = record["temporal_evidence"][-30:]
            self._write(record, "Cadência comparada em janela real; sem aprovação")
            return {**self._snapshot(record), "status": "temporal_evidence_recorded",
                    "temporal_comparison": report, "report_asset": self._public_file(report_asset),
                    "csv_asset": self._public_file(csv_asset)}

    def register_reference_scenes(self, project_id, manifest, *, expected_revision=None):
        """Store an authored, complete-clock event manifest bound to source bytes."""
        from visual_fidelity.reference_fidelity import _clock
        from visual_fidelity.reference_scene import validate_reference_scenes
        require(isinstance(manifest, dict) and len(json.dumps(manifest, ensure_ascii=False)) <= 1024 * 1024,
                "scene_manifest_size", "Scene manifest must be a bounded JSON object")
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            references = [a for a in self._selected(record, "ref") if a["type"].startswith("video/")]
            require(len(references) == 1, "scene_source", "Select exactly one video reference")
            reference = references[0]
            clock = _clock(self.resolve_asset(project_id, reference["id"]))
            coverage = validate_reference_scenes(manifest, source_sha256=reference["sha256"],
                                                 fps=clock["fps"], frame_count=clock["frame_count"])
            directory = self._directory(project_id) / "scene_inventories"
            directory.mkdir(parents=True, exist_ok=True)
            destination = directory / (uuid.uuid4().hex + ".json")
            destination.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                                   encoding="utf-8")
            item = self._register_internal(record, destination, role="evidence")
            record["reference_scene_inventory"] = {"asset_id": item["id"], "source_sha256": reference["sha256"],
                                                   "coverage": coverage, "status": "authored_unreviewed"}
            self._write(record, "Inventário de cenas registrado; observações não aprovadas")
            return {**self._snapshot(record), "status": "scene_inventory_registered",
                    "scene_inventory": coverage, "asset": self._public_file(item)}

    def record_review(self, project_id, stage, decision, confirmation, asset_id, notes="", *,
                      checks=None, expected_revision=None, actor="authenticated-user"):
        require(stage in {"clone", "final"} and decision in {"approved", "rejected"}, "review_choice", "Invalid review decision")
        require(confirmation is True, "review_confirmation", "Explicit confirmation is required")
        _text(notes)
        _text(actor, 200)
        with self._lock(project_id):
            record = self._load(project_id)
            self._expect(record, expected_revision)
            role = "clone" if stage == "clone" else "result"
            current = self._selected(record, role)
            require(current and current[0]["id"] == asset_id, "stale_review", "Review must identify the current preview file")
            require(current[0].get("basis_binding") == self._preview_binding(record, stage),
                    "stale_review", "This preview belongs to previous choices or direction; render or import a current preview")
            self.resolve_asset(project_id, asset_id)
            require(stage == "clone" or self._approval_valid(record, "clone"), "clone_approval_required", "The clone approval is no longer current")
            if checks is not None:
                allowed = {"ok", "na"} if decision == "approved" else {"ok", "na", "fix", ""}
                require(isinstance(checks, dict) and all(value in allowed for value in checks.values()),
                        "review_checks", "Resolve pending checklist items before approval")
            binding = self._clone_binding(record) if stage == "clone" else self._edit_binding(record)
            approval = {"at": _now(), "assetId": asset_id, "sha256": current[0]["sha256"], "binding": binding,
                        "sourceRev": record["state"]["sourceRev"], "editRev": record["state"]["editRev"],
                        "decision": decision, "confirmation": True, "notes": notes, "actor": actor,
                        "checks": clone(checks or {})}
            record["approvals"][stage] = approval
            if stage == "clone":
                record["approvals"]["final"] = None
            for engine_kind, entry in record["engines"].items():
                if entry.get("render_asset_id") != asset_id:
                    continue
                rendered = engine.artifact(entry["directory"], "render")
                review_plan = engine.artifact(entry["directory"], "review_plan")
                engine.review_project(entry["directory"], {"id": "user-" + uuid.uuid4().hex,
                    "plan_sha256": review_plan["plan_sha256"], "render_sha256": rendered["sha256"], "clock": "output",
                    "reviewer": {"kind": "user", "actor": actor, "method": "Explicit panel decision for the displayed file"},
                    "checks": {}, "approval": {"status": decision, "confirmation": notes or "Confirmed in the review panel"}})
            self._write(record, "Decisão explícita: " + stage + " " + decision)
            return self._snapshot(record)

    def get_result(self, project_id, stage="edit"):
        record = self._load(project_id)
        require(stage in {"clone", "edit", "assembly", "generation"}, "engine_kind", "Unsupported result kind")
        entry = record["engines"].get(stage)
        if stage == "generation":
            require(entry and entry["binding"] == self._stage_binding(record, stage)
                    and entry.get("status") == "prompts_exported", "result_missing", "No current exported prompts are available")
            pack = self._portable(record, engine.artifact(entry["directory"], "prompt_pack"))
            return {**self._snapshot(record), "status": "prompts_exported", "prompt_pack": pack}
        role = "clone" if stage == "clone" else "result"
        current = self._selected(record, role)
        if not entry or not entry.get("render_asset_id") or (current and current[0]["id"] != entry.get("render_asset_id")):
            review_stage = "clone" if stage == "clone" else "final"
            require(current and current[0].get("basis_binding") == self._preview_binding(record, review_stage),
                    "result_missing", "No current produced preview is available")
            item = current[0]
            self.resolve_asset(project_id, item["id"])
            return {**self._snapshot(record), "asset_id": item["id"], "asset": self._public_file(item),
                    "preview_kind": "externally_produced", "status": "received_for_review"}
        require(entry and entry["binding"] == self._stage_binding(record, stage) and entry.get("render_asset_id"),
                "result_missing", "No current engine result is available for this stage")
        item = record["files"][entry["render_asset_id"]]
        require(item.get("basis_binding") == self._preview_binding(record, "clone" if stage == "clone" else "final"),
                "result_missing", "The previous render does not represent the current direction")
        self.resolve_asset(project_id, item["id"])
        return {**self._snapshot(record), "asset_id": item["id"], "asset": self._public_file(item),
                "preview_kind": "reference_study" if stage == "clone" else stage}
