"""Prepare factual evidence and native capabilities without inventing semantics.

Source frames are sampled for a human or multimodal director. Pixel differences
are candidate cuts, not a learned scene detector. Pose, masks and transcript
must already identify the same source. Semantic interpretation is a separate,
explicit step in directions.py.
"""

from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image

from .contracts import (clone, file_sha256, nonempty, number, provenance,
                        require, validate_analysis, verify_file)
from .native import OPERATIONS, implementation_fingerprint, native_catalog, probe_native_backend


def write_json(path: str | Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _spans(indices):
    groups = []
    for index in sorted(set(indices)):
        if not groups or index != groups[-1][-1] + 1:
            groups.append([])
        groups[-1].append(index)
    return [(group[0], group[-1] + 1) for group in groups]


def prepare_analysis(source: str | Path, work: str | Path, *, transcript=None,
                     pose=None, mattes=None, protection=None, projection=None,
                     assets=None, sample_every_s=1.0) -> dict:
    from visual_fidelity.reference_cadence import video_clock
    from visual_fidelity.video_anchor import frames_of, quad, shot_starts
    from visual_fidelity.adaptive_template import inspect_pose

    source, work = Path(source).resolve(), Path(work).resolve()
    require(source.is_file(), "source_missing", "Source file is missing")
    require(not work.exists() or not any(work.iterdir()), "work_not_empty", "Use an empty analysis directory")
    number(sample_every_s, "sample_every_s", minimum=.05, maximum=10)
    require(shutil.which("ffmpeg") and shutil.which("ffprobe"), "media_backend", "FFmpeg and FFprobe are required")
    rate, count = video_clock(source)
    source_hash, duration = file_sha256(source), float(count / rate)
    work.mkdir(parents=True, exist_ok=True)
    source_record = {"id": "source", "path": str(source), "sha256": source_hash,
                     "duration_s": duration, "fps": str(rate), "frame_count": count}
    analysis = {"schema_version": "1.0", "sources": [source_record], "evidence": [],
                "events": [], "capabilities": [],
                "preparation": {"semantic_status": "awaiting_direction", "sample_every_s": sample_every_s,
                                "cut_detector": "pixel_difference_candidate", "audio_semantics": "unverified"}}
    def location(first=0, last=count):
        return {"source_id": "source", "source_sha256": source_hash, "clock": "source",
                "interval": {"start_s": float(first / rate), "end_s": float(last / rate)}}

    def evidence(identifier, kind, observation, first=0, last=count, **extra):
        item = {"id": identifier, **location(first, last), "kind": kind, "observation": observation,
                "provenance": {"kind": "tool", "actor": "editorial_engine.prepare", "method": "source-bound technical extraction"}, **extra}
        analysis["evidence"].append(item)
        return identifier

    def receipt(name, payload):
        path = work / "receipts" / f"{name}.json"
        payload = {**payload, "source_sha256": source_hash, "fps": str(rate), "frame_count": count}
        write_json(path, payload)
        return path

    def capability(identifier, name, proof, *, first=0, last=count, kind="metadata"):
        ev = evidence("proof:" + identifier, kind, f"Verified bytes and technical receipt for {name}; semantic suitability remains for the director.", first, last)
        analysis["capabilities"].append({"id": identifier, "name": name, **location(first, last),
             "status": "verified", "evidence_ids": [ev], "verification": {
                 "by": "editorial_engine.prepare", "method": "source hash, clock, file hash and declared resource checks",
                 "artifact_path": str(proof), "artifact_sha256": file_sha256(proof)}})

    mini = []
    resolution = None
    for image in frames_of(source, analysis=True):
        resolution = resolution or image.shape[1::-1]
        mini.append(cv2.resize(image, (72, 48), interpolation=cv2.INTER_AREA))
    require(len(mini) == count, "decode_count", "Decoded source count differs from the source clock")
    cuts = shot_starts(mini)
    del mini
    evidence("source-clock", "metadata", f"CFR source: {count} frames at {rate} fps. Pixel cut candidates: {cuts}.")

    stride = max(1, round(sample_every_s * float(rate)))
    sample_ids = {0, count - 1, *range(0, count, stride)}
    around = max(1, round(.12 * float(rate)))
    for cut in cuts:
        sample_ids.update(i for i in (cut - around, cut - 1, cut, cut + 1, cut + around) if 0 <= i < count)
    (work / "frames").mkdir()
    for index, image in enumerate(frames_of(source)):
        if index == 0:
            source_dimensions = image.shape[1::-1]
            source_record["resolution"] = list(source_dimensions)
        if index not in sample_ids:
            continue
        height, width = image.shape[:2]
        scale = min(1, 960 / max(width, height))
        small = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
        path = work / "frames" / f"{index:06d}.jpg"
        require(cv2.imwrite(str(path), small), "frame_write", "Could not save source sample")
        evidence(f"frame:{index}", "visual", "Uninterpreted source frame; inspect the attached pixels before describing the scene.", index, index + 1,
                 artifact={"path": str(path), "sha256": file_sha256(path), "frame": index, "sampled": True})

    segments = []
    if transcript:
        raw = _load(transcript)
        require(raw.get("source_sha256") == source_hash, "transcript_source", "Transcript must identify the same source SHA-256")
        require(raw.get("clock", "source") == "source", "transcript_clock", "Transcript timestamps must use the source clock")
        require(isinstance(raw.get("segments"), list), "transcript", "Transcript needs segments")
        previous_end = 0.0
        for position, segment in enumerate(raw["segments"]):
            start, end = segment["start"], segment["end"]
            number(start, "segment.start", minimum=0)
            number(end, "segment.end", minimum=0, maximum=duration)
            require(start >= previous_end and end > start, "transcript_interval", "Speech segments must be ordered and nonoverlapping")
            nonempty(segment["text"], "segment.text")
            first, last = int(start * float(rate)), min(count, max(int(start * float(rate)) + 1, int(np.ceil(end * float(rate)))))
            identifier = evidence(f"speech:{position}", "transcript", segment["text"], first, last,
                transcript_artifact={"path": str(Path(transcript).resolve()), "sha256": file_sha256(transcript)})
            analysis["evidence"][-1]["interval"] = {"start_s": start, "end_s": end}
            segments.append((start, end, identifier))
            previous_end = end
        analysis["preparation"]["audio_semantics"] = "transcript_only; listening_not_performed"

    # Cover silence/gaps too, so the director can discover visual opportunities.
    boundaries = sorted({0.0, duration, *(float(c / rate) for c in cuts),
                         *(time for start, end, _ in segments for time in (start, end))})
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        if end - start < 1e-8:
            continue
        refs = [item["id"] for item in analysis["evidence"]
                if item["interval"]["start_s"] < end and item["interval"]["end_s"] > start]
        analysis["events"].append({"id": f"event:{index}", **location(),
             "interval": {"start_s": start, "end_s": end}, "intent": "requires_direction",
             "evidence_ids": refs, "opportunities": []})

    backend = probe_native_backend()
    runtime = receipt("native-runtime", {"kind": "native_runtime", "implementation": implementation_fingerprint(),
                "cut_candidates": cuts, "operations": list(OPERATIONS),
                "checks": {"source_decode": "pass", "ffmpeg_present": True, "ffprobe_present": True,
                           "opencv": cv2.__version__, "backend": backend, "applied_to_source": False}})
    for operation in OPERATIONS:
        if not backend["audio_available" if operation == "sfx_spot" else "visual_available"]:
            continue
        capability("renderer:" + operation, "renderer:native:" + operation, runtime)

    pose_data, protected = None, None
    if pose:
        pose = Path(pose).resolve()
        pose_data = _load(pose)
        require(pose_data.get("clock", "source") == "source", "pose_clock", "Pose must use the source clock")
        require(pose_data.get("source_sha256") == source_hash and Fraction(str(pose_data["fps"])) == rate
                and len(pose_data["frames"]) == count, "pose_source", "Pose must match the source and full frame clock")
        inspected = clone(pose_data)
        inspected["fps"] = float(rate)
        protected, gestures, shots = inspect_pose(inspected, count, cuts, float(rate))
        analysis["preparation"].update(gesture_candidates=gestures, shot_measurements=shots)
        proof = receipt("pose", {"kind": "pose", "path": str(pose), "files": [{"path": str(pose), "sha256": file_sha256(pose)}]})
        from visual_fidelity.body_depth import landmarks, hand_track
        good_body = [i for i in range(count) if len(pose_data["frames"].get(str(i), [])) == 1
                     and len(landmarks(pose_data["frames"][str(i)][0], ("left_shoulder", "right_shoulder"))) == 2
                     and protected.get(i)]
        for first, last in _spans(good_body):
            capability(f"body:{first}:{last}", "body_tracking", proof, first=first, last=last, kind="tracking")
        for side in ("left", "right"):
            for first, last in zip(cuts, [*cuts[1:], count]):
                track = hand_track(pose_data, protected, side, first, last)
                for a, b in _spans(track):
                    capability(f"hand:{side}:{a}:{b}", "hand_tracking", proof, first=a, last=b, kind="tracking")
    if protection:
        supplied = _load(protection)
        require(supplied.get("clock", "source") == "source", "protection_clock", "Protection must use the source clock")
        require(supplied.get("source_sha256") == source_hash and Fraction(str(supplied["fps"])) == rate
                and supplied["frame_count"] == count, "protection_source", "Protection annotations need the source clock")
        provenance(supplied.get("provenance"), "protection.provenance")
        protected = {i: supplied["frames"].get(str(i)) for i in range(count)}
        protection_origin = {"path": str(Path(protection).resolve()), "sha256": file_sha256(protection), "provenance": supplied["provenance"]}
    else:
        protection_origin = {"method": "pose_face_and_hand_boxes", "no_person": "unknown"}
    if protected is not None:
        for regions in protected.values():
            if regions is None:
                continue
            require(isinstance(regions, list), "protection_boxes", "Protected regions must be a list or null")
            for box in regions:
                require(len(box) == 4 and all(isinstance(v, (int, float)) and np.isfinite(v) and 0 <= v <= 1 for v in box)
                        and box[0] < box[2] and box[1] < box[3], "protection_boxes", "Protected region is invalid")
        proof = receipt("protected-regions", {"kind": "protected_regions", "frames": {str(k): v for k, v in protected.items()},
                                              "origin": protection_origin})
        for first, last in _spans(i for i, boxes in protected.items() if boxes is not None):
            capability(f"protection:{first}:{last}", "protected_regions", proof, first=first, last=last, kind="tracking")

    if mattes:
        directory = Path(mattes).resolve()
        alpha = _load(directory / "alpha.json")
        require(alpha.get("clock", "source") == "source", "matte_clock", "Masks must use the source clock")
        require(alpha.get("source_sha256") == source_hash and Fraction(str(alpha["fps"])) == rate
                and alpha["frames"] == count, "matte_source", "Masks must match source and frame count")
        frame_hashes, originals = {}, []
        declared_size = tuple(alpha.get("resolution", source_dimensions))
        require(len(declared_size) == 2 and all(type(n) is int and n > 0 for n in declared_size),
                "matte_dimensions", "Declared mask resolution is invalid")
        # Existing subject_alpha produces a smaller, proportionally scaled grid.
        # Accept its declared grid and explicitly normalize a new immutable copy.
        require(abs(declared_size[0] / declared_size[1] - source_dimensions[0] / source_dimensions[1]) <= 1 / min(declared_size),
                "matte_aspect", "Mask aspect ratio does not match the source grid")
        normalized = work / "normalized-mattes" if declared_size != source_dimensions else directory
        if normalized != directory:
            normalized.mkdir()
        for index in range(count):
            path = directory / f"{index:06d}.png"
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            require(image is not None, "matte_gap", "Subject mask is missing", str(index))
            require(image.shape[::-1] == declared_size, "matte_dimensions", "Mask differs from its declared grid", str(index))
            originals.append({"path": str(path), "sha256": file_sha256(path)})
            if normalized != directory:
                image = cv2.resize(image, source_dimensions, interpolation=cv2.INTER_LINEAR)
                require(cv2.imwrite(str(normalized / path.name), image), "matte_write", "Could not normalize mask")
            frame_hashes[str(index)] = file_sha256(normalized / path.name)
        proof = receipt("subject-mask", {"kind": "subject_mask", "directory": str(normalized), "frame_sha256": frame_hashes,
                  "normalization": {"from": list(declared_size), "to": list(source_dimensions),
                                    "method": "cv2.INTER_LINEAR" if normalized != directory else "identity", "clock_unchanged": True},
                  "files": [{"path": str(directory / "alpha.json"), "sha256": file_sha256(directory / "alpha.json")}, *originals]})
        capability("matte", "subject_mask", proof, kind="mask")

    if projection:
        supplied = _load(projection)
        require(supplied.get("clock", "source") == "source", "projection_clock", "Projection must use the source clock")
        require(supplied.get("source_sha256") == source_hash and Fraction(str(supplied["fps"])) == rate
                and supplied["frame_count"] == count, "projection_source", "Planar tracks need the source clock")
        provenance(supplied.get("provenance"), "projection.provenance")
        for frame, points in supplied["quads"].items():
            require(str(int(frame)) == frame and 0 <= int(frame) < count, "projection_frame", "Projection frame is invalid")
            quad(points)
        proof = receipt("planar", {**supplied, "kind": "planar_tracking",
                        "files": [{"path": str(Path(projection).resolve()), "sha256": file_sha256(projection)}]})
        for first, last in _spans(map(int, supplied["quads"])):
            capability(f"planar:{first}:{last}", "planar_tracking", proof, first=first, last=last, kind="tracking")

    if assets:
        inventory = _load(assets) if isinstance(assets, (str, Path)) else clone(assets)
        require(isinstance(inventory.get("assets"), list), "assets", "Asset inventory needs an assets list")
        seen = set()
        for item in inventory["assets"]:
            identifier = nonempty(item["id"], "asset.id")
            require(identifier not in seen, "asset_id", "Asset identifiers must be unique")
            seen.add(identifier)
            # Filenames never become semantic labels; use metadata from the curator.
            payload = {"catalog_metadata": {key: item[key] for key in ("description", "functions", "license", "provenance") if key in item}}
            if item["kind"] == "image":
                path = Path(item["path"]).resolve()
                with Image.open(path) as image:
                    image.verify()
                payload.update(kind="image_asset", path=str(path), files=[{"path": str(path), "sha256": file_sha256(path)}])
            elif item["kind"] == "sfx":
                from audiovisual.semantic_audio import verify_asset
                verify_asset(item["asset"])
                payload.update(kind="audio_asset", asset=item["asset"])
            elif item["kind"] == "motion":
                from .motion_assets import load_layer, frame_rate
                path = Path(item["path"]).resolve()
                layer = load_layer(path)
                require(frame_rate(layer["fps"]) == rate, "motion_clock",
                        "Render motion at the source frame rate before preparing its asset")
                if layer.get("source_binding"):
                    bound = layer["source_binding"]
                    require(bound["source_sha256"] == source_hash and bound["frame_count"] == count,
                            "motion_source", "Motion was authored for a different source")
                payload.update(kind="motion_asset", path=str(path),
                    motion={key: layer[key] for key in ("fps", "frame_count", "width", "height", "alpha", "origin")},
                    source_binding=layer.get("source_binding"),
                    files=[{"path": str(path), "sha256": file_sha256(path)},
                           *[{"path": frame["path"], "sha256": frame["sha256"]} for frame in layer["frames"]],
                           *[{"path": frame["glyph_ids_path"], "sha256": frame["glyph_ids_sha256"]}
                             for frame in layer["frames"] if "glyph_ids_path" in frame]])
                if item.get("sonic_candidates"):
                    sonic_ref = item["sonic_candidates"]
                    verify_file(sonic_ref["path"], sonic_ref["sha256"], "motion sound candidates")
                    sonic = _load(sonic_ref["path"])
                    require(sonic.get("schema_version") == "motionlab-sonic/1" and sonic.get("clock") == "scene_seconds",
                            "sonic_schema", "Expected scene-clock motion sound candidates")
                    require(sonic.get("scene_sha256") == layer["origin"].get("recipe_sha256"),
                            "sonic_scene", "Sound candidates must identify the rendered scene recipe")
                    payload["motion_audio_candidates"] = sonic
                    payload["files"].append(sonic_ref)
            else:
                raise ValueError("Supported prepared asset kinds are image, motion and sfx")
            proof = receipt(f"asset-{len(seen)}", payload)
            capability("asset:" + identifier, payload["kind"], proof)
    # Bind factual resource observations to overlapping events for explicit citations.
    for event in analysis["events"]:
        event["evidence_ids"] = [item["id"] for item in analysis["evidence"]
             if item["interval"]["start_s"] < event["interval"]["end_s"] and item["interval"]["end_s"] > event["interval"]["start_s"]]
    verify_file(str(source), source_hash, "original source after preparation")
    validate_analysis(analysis, verify_files=True)
    write_json(work / "analysis.json", analysis)
    write_json(work / "catalog.json", native_catalog())
    return analysis
