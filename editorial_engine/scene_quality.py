"""Batch-by-scene reference QA on the unmodified source frame clock.

Produces exact-frame images and measured 2D rhythm evidence. Metrics are
diagnostic, not a percentage of clone fidelity or an aesthetic decision.
"""
from __future__ import annotations

import csv
from fractions import Fraction
import json
import math
from pathlib import Path
import shutil

from .contracts import digest, file_sha256
from visual_fidelity.reference_fidelity import _clock, audit_pair
from visual_fidelity.reference_temporal_qa import measure_reference_cadence_gap

MAX_SCENES = 4
MAX_TEMPORAL_WINDOW = 90


def _sample(scene):
    start, end = scene["start_frame"], scene["end_frame"]
    return sorted({start, (start + end - 1) // 2, end - 1})


def _window(scene):
    first, last = scene["start_frame"], scene["end_frame"]
    if last - first < 3:
        return None
    size = min(last - first, MAX_TEMPORAL_WINDOW)
    offset = (last - first - size) // 2
    return [first + offset, first + offset + size]


def validate_selection(manifest, scene_ids):
    if (not isinstance(scene_ids, list) or not 1 <= len(scene_ids) <= MAX_SCENES
            or any(not isinstance(value, str) for value in scene_ids)
            or len(set(scene_ids)) != len(scene_ids)):
        raise ValueError("Select 1 to 4 unique scene IDs")
    scenes = {row["id"]: row for row in manifest["scenes"]}
    if set(scene_ids) - set(scenes):
        raise ValueError("QA scene ID is absent from the registered reference inventory")
    ordered = [scenes[identifier] for identifier in scene_ids]
    if ordered != sorted(ordered, key=lambda item: item["start_frame"]):
        raise ValueError("QA scenes must be selected in reference clock order")
    return ordered


def audit_scenes(reference, candidate, manifest, scene_ids, output):
    """One bounded 2D temporal analysis plus exact-frame spatial analysis per scene."""
    reference, candidate, output = Path(reference), Path(candidate), Path(output)
    scenes = validate_selection(manifest, scene_ids)
    clock = _clock(reference)
    if clock != _clock(candidate):
        raise ValueError("Source/clone clocks and rasters must match; implicit retime forbidden")
    if (clock["fps"] != str(Fraction(manifest["fps"])) and
            Fraction(clock["fps"]) != Fraction(manifest["fps"])):
        raise ValueError("Source clock changed since scene inventory")
    if clock["frame_count"] != manifest["frame_count"]:
        raise ValueError("Source frames changed since scene inventory")
    expected = manifest["source_sha256"]
    if file_sha256(reference) != expected:
        raise ValueError("Reference bytes changed since scene inventory")
    if output.exists():
        raise ValueError("Use a new, immutable QA evidence directory")
    output.mkdir(parents=True, mode=0o700)
    try:
        windows = [(scene["id"], _window(scene)) for scene in scenes]
        temporal = None
        active = [(identifier, window) for identifier, window in windows if window]
        if active:
            temporal = measure_reference_cadence_gap(
                reference, candidate, output / "temporal",
                ranges=[window for _, window in active])
        time_by_scene = {}
        if temporal is not None:
            with (output / "temporal" / "temporal_frames.csv").open(
                    "r", encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                for row in reader:
                    key = active[int(row["window"])][0]
                    time_by_scene.setdefault(key, []).append(row)
        entries = []
        for scene in scenes:
            scene_id = scene["id"]
            folder = output / ("scene-" + scene_id)
            frames = _sample(scene)
            comparison = audit_pair(reference, candidate, folder, frames)
            rows = time_by_scene.get(scene_id, [])
            temporal_summary = {
                "status": "compared" if rows else "insufficient_frames_for_temporal_flow",
                "window": _window(scene), "pairs": len(rows),
                "mean_change_gap": round(sum(float(x["change_gap"]) for x in rows) / len(rows), 6) if rows else None,
                "mean_flow_gap": round(sum(float(x["flow_gap_smallpx_per_frame"]) for x in rows) / len(rows), 6) if rows else None,
                "max_flow_gap": max(float(x["flow_gap_smallpx_per_frame"]) for x in rows) if rows else None,
            }
            entries.append({
                "scene_id": scene_id, "frame_range": [scene["start_frame"], scene["end_frame"]],
                "sample_frames": frames, "spatial_metrics": comparison["diagnostics"],
                "temporal": temporal_summary,
                "comparison_report": {"path": str(folder / "comparison_report.json"),
                                      "sha256": file_sha256(folder / "comparison_report.json")},
                "contact_sheet": {"path": str(folder / "aligned_contact_sheet.jpg"),
                                  "sha256": file_sha256(folder / "aligned_contact_sheet.jpg")},
                "status": "diagnostic_review_pending", "user_approved": False,
            })
        summary = {
            "schema": "editor-ultra-scene-qa-batch/1",
            "reference_sha256": expected, "candidate_sha256": file_sha256(candidate),
            "scene_manifest_sha256": digest(manifest),
            "clock": clock, "status": "technical_diagnostics_not_visual_approval",
            "scenes": entries, "temporal_report": {
                "path": str(output / "temporal" / "temporal_report.json"),
                "sha256": file_sha256(output / "temporal" / "temporal_report.json"),
            } if temporal else None,
            "perceptual_review": "pending", "user_approved": False,
            "limitations": ["Aligned 2D frames and optical flow cannot identify 3D motion",
                            "One bounded temporal window per scene; other frames remain unmeasured",
                            "No audio listening, user review or automatic pass percentage"],
        }
        (output / "batch.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8")
        return summary
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
