"""Reference event inventory with explicit source binding and uncertainty.

A scene title or uninterrupted video duration is not proof of complete events.
Frame indices are exact on the original fixed FPS clock, [start, end).
"""
from __future__ import annotations

from fractions import Fraction
import re

ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")


def _integer(value, title, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{title}: expected integer >= {minimum}")
    return value


def _id(value, title):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError(f"{title}: invalid identifier")
    return value


def validate_reference_scenes(manifest: dict, *, source_sha256: str, fps: str, frame_count: int) -> dict:
    """Validate an authored inventory; no ML discovery or semantic approval occurs."""
    if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "source_sha256", "fps", "frame_count", "scenes"}:
        raise ValueError("Unexpected reference-scene manifest fields")
    if manifest["schema"] != "editor-ultra-reference-scenes/1":
        raise ValueError("Unsupported scene manifest version")
    if manifest["source_sha256"] != source_sha256:
        raise ValueError("Scene manifest must bind to current reference bytes")
    try:
        if Fraction(manifest["fps"]) != Fraction(fps):
            raise ValueError("Scene manifest uses wrong clock")
    except (ZeroDivisionError, TypeError) as exc:
        raise ValueError("Invalid scene manifest clock") from exc
    if _integer(manifest["frame_count"], "frame_count", 1) != frame_count:
        raise ValueError("Scene manifest uses wrong number of frames")
    scenes = manifest["scenes"]
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 500:
        raise ValueError("Scene manifest must contain 1 to 500 scenes")
    previous = 0
    scene_ids, event_ids = set(), set()
    pending = []
    for scene in scenes:
        if not isinstance(scene, dict) or set(scene) != {
                "id", "start_frame", "end_frame", "elements", "events", "unresolved"}:
            raise ValueError("Scene must declare bounds, elements, events and unknowns")
        identifier = _id(scene["id"], "scene")
        if identifier in scene_ids:
            raise ValueError("Duplicate scene ID")
        scene_ids.add(identifier)
        first = _integer(scene["start_frame"], "start_frame")
        last = _integer(scene["end_frame"], "end_frame", 1)
        if first != previous or last <= first or last > frame_count:
            raise ValueError(f"Scene {identifier} leaves a gap, overlaps or exceeds the source")
        previous = last
        elements = scene["elements"]
        if not isinstance(elements, list) or len(elements) > 256:
            raise ValueError("Scene elements must be a list")
        if len(set(elements)) != len(elements):
            raise ValueError("Duplicate element")
        for element in elements:
            _id(element, "element")
        events = scene["events"]
        if not isinstance(events, list) or len(events) > 1024 or (not events and not scene["unresolved"]):
            raise ValueError("A scene needs observed events or explicit unresolved evidence")
        for event in events:
            if not isinstance(event, dict) or set(event) != {
                    "id", "element_id", "frame", "action", "observed"}:
                raise ValueError("Event must include exact element, frame and observation status")
            eid = _id(event["id"], "event")
            if eid in event_ids:
                raise ValueError("Duplicate event ID")
            event_ids.add(eid)
            if event["element_id"] not in elements or type(event["observed"]) is not bool:
                raise ValueError("Event must bind to known scene element and observed boolean")
            at = _integer(event["frame"], "event.frame")
            if not first <= at < last:
                raise ValueError("Event outside its parent scene")
            if not isinstance(event["action"], str) or not event["action"].strip():
                raise ValueError("Action must be described, not inferred from scene title")
            if not event["observed"]:
                pending.append({"scene_id": identifier, "event_id": eid, "reason": event["action"]})
        if not isinstance(scene["unresolved"], list):
            raise ValueError("Scene unresolved must be a list")
        for note in scene["unresolved"]:
            if not isinstance(note, str) or not note.strip():
                raise ValueError("Use nonempty unresolved evidence notes")
            pending.append({"scene_id": identifier, "reason": note})
    if previous != frame_count:
        raise ValueError("The last scene must end at source frame_count")
    return {"schema": "editor-ultra-scene-coverage/1", "source_sha256": source_sha256,
            "frame_count": frame_count, "scenes": len(scenes), "events": len(event_ids),
            "unresolved": pending,
            "interpretation": "Author inventory validated, not perceptual certification"}
