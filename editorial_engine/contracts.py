"""Versioned, JSON-only contracts for evidence-grounded editorial decisions.

These validators verify identities, time ranges and attestations. They do not
infer meaning from filenames, transcripts or keywords, nor certify aesthetics.
"""

from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
EPSILON = 1e-8


class ValidationError(ValueError):
    """A machine-readable contract violation, suitable for model repair."""

    def __init__(self, code: str, message: str, path: str = "") -> None:
        self.issues = [{"code": code, "message": message, "path": path}]
        super().__init__(f"{path + ': ' if path else ''}{message} [{code}]")


def require(condition: bool, code: str, message: str, path: str = "") -> None:
    if not condition:
        raise ValidationError(code, message, path)


def mapping(value: Any, path: str) -> dict:
    require(isinstance(value, dict), "type", "Expected an object", path)
    return value


def sequence(value: Any, path: str) -> list:
    require(isinstance(value, list), "type", "Expected an array", path)
    return value


def nonempty(value: Any, path: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), "type", "Expected a nonempty string", path)
    return value


def number(value: Any, path: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool), "type", "Expected a finite number", path)
    require(math.isfinite(value), "nonfinite", "Number must be finite", path)
    require(minimum is None or value >= minimum, "range", f"Number must be >= {minimum}", path)
    require(maximum is None or value <= maximum, "range", f"Number must be <= {maximum}", path)
    return value


def integer(value: Any, path: str, *, minimum: int = 0) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value >= minimum,
            "type", f"Expected an integer >= {minimum}", path)
    return value


def sha256(value: Any, path: str) -> str:
    require(isinstance(value, str) and len(value) == 64 and
            all(c in "0123456789abcdef" for c in value), "sha256", "Expected lowercase SHA-256", path)
    return value


def clone(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ValidationError("json", "Value must contain only finite JSON data") from exc


def digest(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("json", "Value must contain only finite JSON data") from exc
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: str | Path) -> str:
    candidate = Path(path)
    require(candidate.is_file(), "file_missing", "Artifact does not exist", str(path))
    hasher = hashlib.sha256()
    with candidate.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def verify_file(path: Any, expected_sha256: str, label: str) -> None:
    nonempty(path, label)
    require(file_sha256(path) == expected_sha256, "file_hash_mismatch",
            "Artifact bytes do not match the declared SHA-256", label)


def interval(value: Any, path: str, *, duration_s: float | None = None) -> dict:
    item = mapping(value, path)
    start = number(item.get("start_s"), path + ".start_s", minimum=0)
    end = number(item.get("end_s"), path + ".end_s", minimum=0)
    require(end > start, "interval", "Intervals are nonempty and half-open [start, end)", path)
    require(duration_s is None or end <= duration_s + EPSILON,
            "outside_source", "Interval exceeds source duration", path)
    return item


def contains(outer: dict, inner: dict) -> bool:
    return outer["start_s"] <= inner["start_s"] + EPSILON and outer["end_s"] + EPSILON >= inner["end_s"]


def overlaps(left: dict, right: dict) -> bool:
    return min(left["end_s"], right["end_s"]) - max(left["start_s"], right["start_s"]) > EPSILON


def strings(value: Any, path: str, *, allow_empty: bool = True) -> list[str]:
    items = sequence(value, path)
    require(allow_empty or bool(items), "empty", "Array must not be empty", path)
    for position, item in enumerate(items):
        nonempty(item, f"{path}[{position}]")
    require(len(items) == len(set(items)), "duplicate", "Array contains duplicate identifiers", path)
    return items


def index_by_id(items: Any, path: str) -> dict[str, dict]:
    result = {}
    for position, raw in enumerate(sequence(items, path)):
        item = mapping(raw, f"{path}[{position}]")
        identifier = nonempty(item.get("id"), f"{path}[{position}].id")
        require(identifier not in result, "duplicate_id", f"Duplicate ID {identifier}", path)
        result[identifier] = item
    return result


def provenance(value: Any, path: str, *, kinds: set[str] | None = None) -> dict:
    item = mapping(value, path)
    allowed = kinds or {"human", "model", "tool"}
    require(isinstance(item.get("kind"), str) and item["kind"] in allowed, "provenance", "Unsupported provenance kind", path + ".kind")
    nonempty(item.get("actor"), path + ".actor")
    nonempty(item.get("method"), path + ".method")
    return item


def source_reference(item: dict, sources: dict[str, dict], path: str) -> dict:
    source_id = nonempty(item.get("source_id"), path + ".source_id")
    require(source_id in sources, "unknown_source", f"Unknown source {source_id}", path)
    source = sources[source_id]
    sha256(item.get("source_sha256"), path + ".source_sha256")
    require(item["source_sha256"] == source["sha256"], "source_hash_mismatch", "Source identity changed", path)
    require(item.get("clock") == "source", "clock_mismatch", "Analysis and proposals must use the source clock", path + ".clock")
    interval(item.get("interval"), path + ".interval", duration_s=source["duration_s"])
    return source


def validate_analysis(analysis: dict, *, verify_files: bool = False) -> dict:
    """Validate source-grounded observations; optionally verify original/proof bytes.

    ``verify_files=False`` is a contract-only inspection, never execution proof.
    A capability's verified status is an explicit upstream attestation; checking
    its report hash proves report integrity, not that the report is truthful.
    """
    data = clone(mapping(analysis, "analysis"))
    require(type(verify_files) is bool, "type", "verify_files must be boolean")
    require(data.get("schema_version") == SCHEMA_VERSION, "schema_version", "Unsupported analysis version")
    sources = index_by_id(data.get("sources"), "sources")
    require(bool(sources), "empty", "At least one source is required", "sources")
    for source_id, source in sources.items():
        path = f"sources.{source_id}"
        sha256(source.get("sha256"), path + ".sha256")
        number(source.get("duration_s"), path + ".duration_s", minimum=EPSILON)
        if "fps" in source:
            nonempty(source["fps"], path + ".fps")
            try:
                fps = Fraction(source["fps"])
            except (ValueError, ZeroDivisionError) as exc:
                raise ValidationError("fps", "FPS must be a positive rational string", path) from exc
            require(fps > 0, "fps", "FPS must be positive", path)
        if "frame_count" in source:
            integer(source["frame_count"], path + ".frame_count", minimum=1)
            if "fps" in source:
                expected = source["frame_count"] / float(fps)
                require(abs(expected - source["duration_s"]) <= 1 / float(fps) + EPSILON,
                        "frame_clock_mismatch", "Frame count, FPS and duration disagree by more than one frame", path)
        if "path" in source:
            nonempty(source["path"], path + ".path")
        if verify_files:
            verify_file(source.get("path"), source["sha256"], path + ".path")

    evidence = index_by_id(data.get("evidence"), "evidence")
    for evidence_id, item in evidence.items():
        path = f"evidence.{evidence_id}"
        source_reference(item, sources, path)
        require(item.get("kind") in ("visual", "audio", "transcript", "tracking", "mask", "camera", "metadata"),
                "evidence_kind", "Unsupported evidence kind", path)
        nonempty(item.get("observation"), path + ".observation")
        provenance(item.get("provenance"), path + ".provenance")

    def check_evidence(item: dict, path: str, *, required: bool = True) -> None:
        refs = strings(item.get("evidence_ids", []), path + ".evidence_ids", allow_empty=not required)
        for ref in refs:
            require(ref in evidence, "unknown_evidence", f"Unknown evidence {ref}", path)
            observed = evidence[ref]
            require(observed["source_id"] == item["source_id"], "evidence_source_mismatch",
                    "Evidence belongs to another source", path)
            require(overlaps(observed["interval"], item["interval"]), "evidence_time_mismatch",
                    "Evidence does not overlap the claimed interval", path)

    events = index_by_id(data.get("events"), "events")
    require(bool(events), "empty", "At least one editorial event is required", "events")
    for event_id, event in events.items():
        path = f"events.{event_id}"
        source_reference(event, sources, path)
        nonempty(event.get("intent"), path + ".intent")
        check_evidence(event, path)
        for opportunity_id, opportunity in index_by_id(event.get("opportunities", []), path + ".opportunities").items():
            nonempty(opportunity.get("function"), f"{path}.opportunities.{opportunity_id}.function")
            nonempty(opportunity.get("why"), f"{path}.opportunities.{opportunity_id}.why")

    capabilities = index_by_id(data.get("capabilities", []), "capabilities")
    for capability_id, capability in capabilities.items():
        path = f"capabilities.{capability_id}"
        source_reference(capability, sources, path)
        nonempty(capability.get("name"), path + ".name")
        require(capability.get("status") in ("verified", "unknown", "failed"), "capability_status",
                "Capability must be verified, unknown or failed", path)
        check_evidence(capability, path, required=capability["status"] == "verified")
        if capability["status"] == "verified":
            proof = mapping(capability.get("verification"), path + ".verification")
            nonempty(proof.get("by"), path + ".verification.by")
            nonempty(proof.get("method"), path + ".verification.method")
            sha256(proof.get("artifact_sha256"), path + ".verification.artifact_sha256")
            if verify_files:
                verify_file(proof.get("artifact_path"), proof["artifact_sha256"], path + ".verification.artifact_path")
    return data
