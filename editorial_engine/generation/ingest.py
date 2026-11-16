"""Receive generated video as evidence, without changing its edit or pixels.

Hashes identify bytes; observations remain attributed claims. Selecting a frame
does not authorize a trim, certify motion, or prove which inputs a provider used.
The caller supplies an explicit clip id and, optionally, the exact prompt export.
"""

from __future__ import annotations

import hashlib
import io
import json
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess

from PIL import Image

from ..contracts import (ValidationError, clone, digest, file_sha256, integer,
                         mapping, nonempty, number, require, sequence, sha256,
                         verify_file)
from .contracts import clip_fingerprint, validate_plan

RESULT_SCHEMA = "video-generation-result/1"
OBSERVATION_SCOPES = {"sampled_frames", "boundary_window", "continuous_video",
                      "audio_listened", "human_note"}
_ROUNDING = Fraction(1, 1_000_000_000)


def _rational(value, path, *, positive=False):
    nonempty(value, path)
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValidationError("media_clock", "Expected a rational time", path) from exc
    require(not positive or result > 0, "media_clock", "Time/rate must be positive", path)
    return result


def _ratio(value):
    return f"{value.numerator}/{value.denominator}"


def _run(argv):
    require(shutil.which(argv[0]) is not None, "media_tool_missing", f"Install {argv[0]}")
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValidationError("media_tool_failed", f"{argv[0]} could not finish") from exc
    require(result.returncode == 0, "media_tool_failed",
            f"{argv[0]} failed: " + result.stderr.decode("utf-8", errors="replace")[-1800:])
    return result.stdout


def _probe_json(argv):
    try:
        return json.loads(_run(argv))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError("media_probe", "ffprobe returned invalid metadata") from exc


def _probe(path):
    """Measure decoded frame PTS; never infer duration from the file name."""
    metadata = _probe_json(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", "-protocol_whitelist", "file,pipe", str(path)])
    format_name = metadata.get("format", {}).get("format_name", "")
    require(not set(format_name.split(",")) & {"hls", "dash", "concat", "image2", "image2pipe",
                                               "png_pipe", "jpeg_pipe", "webp_pipe"},
            "video_stream", "Supply a self-contained video; a still image or a media playlist is not a returned video")
    streams = metadata.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")]
    require(len(videos) == 1, "video_stream", "Supply one real video stream, without alternate video tracks")
    video = videos[0]
    # Select the exact stream identified above, including files with cover art.
    stream_index = integer(video.get("index"), "stream.index")
    raw_frames = _probe_json([
        "ffprobe", "-v", "error", "-select_streams", str(stream_index),
        "-show_frames", "-show_entries", "frame=best_effort_timestamp,pkt_duration,duration",
        "-of", "json", "-protocol_whitelist", "file,pipe", str(path),
    ]).get("frames", [])
    require(bool(raw_frames), "video_frames", "No decodable video frames were found")
    tick = _rational(video.get("time_base"), "stream.time_base", positive=True)
    timestamps = []
    for position, frame in enumerate(raw_frames):
        stamp = frame.get("best_effort_timestamp")
        require(isinstance(stamp, int) and not isinstance(stamp, bool), "media_clock",
                "Every decoded frame needs an integer presentation timestamp", f"frames[{position}]")
        require(not timestamps or stamp > timestamps[-1], "media_clock",
                "Frame presentation timestamps must strictly increase")
        timestamps.append(stamp)
    origin = timestamps[0] * tick
    try:
        rate = Fraction(video.get("avg_frame_rate", "0/1"))
    except (ValueError, ZeroDivisionError):
        rate = Fraction()
    last_ticks = raw_frames[-1].get("duration", raw_frames[-1].get("pkt_duration"))
    last_duration = last_ticks * tick if isinstance(last_ticks, int) and last_ticks > 0 else None
    duration_basis = "frame_duration"
    if last_duration is None and isinstance(video.get("duration_ts"), int):
        stream_start = video.get("start_pts", timestamps[0])
        if isinstance(stream_start, int):
            last_duration = (stream_start + video["duration_ts"] - timestamps[-1]) * tick
            duration_basis = "stream_duration"
    require(last_duration is not None and last_duration > 0, "media_clock",
            "The final decoded frame has no verifiable duration; conform explicitly before importing")
    durations = [(b - a) * tick for a, b in zip(timestamps, timestamps[1:])] + [last_duration]
    duration = (timestamps[-1] - timestamps[0]) * tick + last_duration
    constant = rate > 0 and all(
        abs((stamp - timestamps[0]) * tick - Fraction(index, 1) / rate) <= tick
        and abs(durations[index] - 1 / rate) <= tick
        for index, stamp in enumerate(timestamps)
    )
    measured_rate = rate if constant else Fraction(len(timestamps), 1) / duration
    frame_clock = [{"index": i, "pts_ticks": stamp, "source_pts": _ratio(stamp * tick),
                    "pts": _ratio(stamp * tick - origin), "pts_s": float(stamp * tick - origin),
                    "duration": _ratio(durations[i]), "duration_s": float(durations[i])}
                   for i, stamp in enumerate(timestamps)]
    audio_streams = [{"index": s["index"], "codec": s.get("codec_name"),
                      "sample_rate": s.get("sample_rate"), "channels": s.get("channels"),
                      "start_time": s.get("start_time"), "duration": s.get("duration")}
                     for s in streams if s.get("codec_type") == "audio"]
    return {
        "duration_s": float(duration), "duration": _ratio(duration),
        "duration_basis": duration_basis, "fps": _ratio(measured_rate),
        "fps_basis": "constant_frame_clock" if constant else "frame_count_over_duration",
        "frame_count": len(timestamps), "width": video["width"], "height": video["height"],
        "sample_aspect_ratio": video.get("sample_aspect_ratio", "1:1"),
        "rotation": [s["rotation"] for s in video.get("side_data_list", []) if "rotation" in s],
        "audio": bool(audio_streams), "audio_streams": audio_streams,
        "clock": "cfr" if constant else "vfr", "time_base": _ratio(tick),
        "clock_origin": "first_decoded_video_frame", "source_start_pts": _ratio(origin),
        "stream_index": stream_index, "codec": video.get("codec_name"),
        "container_duration_s": metadata.get("format", {}).get("duration"),
        "frame_clock": frame_clock,
    }


def _frame_png(path, index, stream_index):
    return _run(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-noautorotate",
                 "-protocol_whitelist", "file,pipe",
                 "-i", str(path), "-map", f"0:{stream_index}",
                 "-vf", f"select=eq(n\\,{index})", "-frames:v", "1", "-an",
                 "-c:v", "png", "-f", "image2pipe", "pipe:1"])


def _pixel_digest(png, actual):
    try:
        with Image.open(io.BytesIO(png)) as image:
            require(image.format == "PNG", "frame_format", "Proof frames must be PNG files")
            require(image.size == (actual["width"], actual["height"]),
                    "frame_size", "Proof frame raster differs from the source video")
            image.load()
            return hashlib.sha256(image.convert("RGBA").tobytes()).hexdigest()
    except (OSError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("frame_decode", "Proof frame could not be decoded") from exc


def _write_frame(video_path, source_sha, actual, index, output):
    png = _frame_png(video_path, index, actual["stream_index"])
    pixel_sha = _pixel_digest(png, actual)
    output.write_bytes(png)
    clock = actual["frame_clock"][index]
    end = Fraction(clock["pts"]) + Fraction(clock["duration"])
    return {**clone(clock), "source_frame_index": index, "source_sha256": source_sha,
            "path": str(output), "sha256": file_sha256(output), "pixel_sha256": pixel_sha,
            "recommended_use_end_s": float(end), "recommended_use_end": _ratio(end)}


def _observation(raw, actual):
    if raw is None:
        return None
    item = clone(mapping(raw, "observation"))
    for field in ("actor", "method", "description", "motion", "camera", "audio"):
        nonempty(item.get(field), "observation." + field)
    require(item.get("scope") in OBSERVATION_SCOPES, "observation_scope",
            "Declare what was actually inspected", "observation.scope")
    decision = item.setdefault("continuity_decision", {
        "status": "unassessed", "actor": item["actor"],
        "reason": "The observation does not include an editorial acceptance of this continuity boundary",
    })
    mapping(decision, "observation.continuity_decision")
    require(isinstance(decision.get("status"), str) and
            decision["status"] in {"accept", "revise", "unassessed"},
            "continuity_decision", "Declare accept, revise or unassessed for continuity")
    for field in ("actor", "reason"):
        nonempty(decision.get(field), "observation.continuity_decision." + field)
    if item["scope"] in {"boundary_window", "continuous_video"}:
        require(actual["frame_count"] >= 2, "observation_range", "Motion review requires multiple actual frames")
    if item["scope"] == "boundary_window" or "frame_range" in item:
        window = mapping(item.get("frame_range"), "observation.frame_range")
        start = integer(window.get("start_frame"), "observation.frame_range.start_frame")
        end = integer(window.get("end_frame"), "observation.frame_range.end_frame", minimum=1)
        require(start < end <= actual["frame_count"], "observation_range",
                "Observation uses a half-open range within this actual video")
        if item["scope"] in {"boundary_window", "continuous_video"}:
            require(end - start >= 2, "observation_range", "Motion review requires more than one still frame")
    return item


def _output_semantics(plan, clip_id, exported):
    incoming = next((j for j in plan["joins"] if j["to"] == clip_id and
                     j["strategy"] == "native_extension"), None)
    if incoming is None:
        return {"mode": "independent_clip", "basis": "plan_without_native_extension"}
    if exported is None:
        mode = None
    else:
        exported = mapping(exported, "source_export")
        mode = mapping(exported.get("settings"), "source_export.settings").get("extension_output")
    if isinstance(mode, str) and mode in {"appended_clip", "full_sequence"}:
        return {"mode": mode, "basis": "source_export_declaration"}
    return {"mode": "unresolved", "basis": "no_extension_output_declaration"}


def _usable(actual, use, aspect_ratio, output_semantics):
    duration = Fraction(actual["duration"])
    start, end = (Fraction(str(use[key])) for key in ("start_s", "end_s"))
    covers = start >= 0 and end <= duration + _ROUNDING
    boundaries = [Fraction(f["pts"]) for f in actual["frame_clock"]] + [duration]
    aligned = all(any(abs(value - point) <= _ROUNDING for point in boundaries) for value in (start, end))
    issues = []
    if not covers:
        issues.append("actual_video_shorter_than_planned_use")
    if not aligned:
        issues.append("planned_use_is_not_on_actual_frame_boundaries")
    if actual["clock"] != "cfr":
        issues.append("variable_frame_rate_requires_explicit_conform")
    expected_width, expected_height = (int(v) for v in aspect_ratio.split(":"))
    raster_matches = actual["width"] * expected_height == actual["height"] * expected_width
    if not raster_matches:
        issues.append("actual_raster_aspect_differs_from_plan")
    square_pixels = actual["sample_aspect_ratio"] in {"1:1", "1/1"}
    if not square_pixels:
        issues.append("non_square_or_unknown_pixel_aspect_requires_explicit_conform")
    unrotated = not any(abs(rotation) % 360 for rotation in actual["rotation"])
    if not unrotated:
        issues.append("display_rotation_requires_explicit_conform")
    extension_resolved = output_semantics["mode"] in {"independent_clip", "appended_clip"}
    if not extension_resolved:
        issues.append("native_extension_output_requires_explicit_mapping")
    if not covers or not aligned or not extension_resolved:
        status = "needs_plan_revision"
    elif actual["clock"] != "cfr" or not raster_matches or not square_pixels or not unrotated:
        status = "requires_conform"
    else:
        status = "usable"
    return {"status": status, "covers_planned_use": covers,
            "frame_aligned_use": aligned, "issues": issues,
            "raster_matches_plan": raster_matches,
            "unused_tail_s": float(max(Fraction(), duration - end))}


def _boundary(selected, observation, use, usable):
    if selected is None:
        return {"status": "not_selected", "matches_planned_use": False,
                "delta_s": None, "reason": "No exit frame was explicitly selected"}
    delta = Fraction(selected["recommended_use_end"]) - Fraction(str(use["end_s"]))
    matches = abs(delta) <= _ROUNDING
    if not matches or usable["status"] != "usable":
        return {"status": "needs_plan_revision", "matches_planned_use": matches,
                "delta_s": float(delta),
                "reason": "Revise the planned use explicitly or supply compatible media; selection does not trim"}
    motion_observed = observation is not None and observation["scope"] in {"boundary_window", "continuous_video"}
    if motion_observed and "frame_range" in observation:
        window = observation["frame_range"]
        motion_observed = window["start_frame"] <= selected["index"] < window["end_frame"]
    return {"status": "observed" if motion_observed else "needs_observation",
            "matches_planned_use": True, "delta_s": float(delta),
            "reason": ("Attributed motion observation covers the selected boundary; perceptual quality is not certified"
                       if motion_observed else "Review the exit in a boundary window or continuous playback")}


def _frame_check(frame, source, source_sha, actual, label, verify_files):
    frame = mapping(frame, label)
    index = integer(frame.get("index"), label + ".index")
    integer(frame.get("source_frame_index"), label + ".source_frame_index")
    require(index < actual["frame_count"] and frame.get("source_frame_index") == index,
            "frame_index", "Proof frame index must refer to this video's decoded frame order", label)
    require(frame.get("source_sha256") == source_sha, "frame_source", "Proof frame belongs to other source bytes", label)
    expected = actual["frame_clock"][index]
    require(all(frame.get(key) == value for key, value in expected.items()),
            "frame_clock", "Proof frame timing differs from the measured source", label)
    end = Fraction(expected["pts"]) + Fraction(expected["duration"])
    require(frame.get("recommended_use_end") == _ratio(end)
            and frame.get("recommended_use_end_s") == float(end),
            "frame_clock", "Boundary must be the end of the selected frame", label)
    nonempty(frame.get("path"), label + ".path")
    require(Path(frame["path"]).is_absolute(), "absolute_path", "Use absolute artifact paths", label)
    sha256(frame.get("sha256"), label + ".sha256")
    sha256(frame.get("pixel_sha256"), label + ".pixel_sha256")
    if verify_files:
        verify_file(frame["path"], frame["sha256"], label + ".path")
        stored = _pixel_digest(Path(frame["path"]).read_bytes(), actual)
        decoded = _pixel_digest(_frame_png(source, index, actual["stream_index"]), actual)
        require(stored == decoded == frame["pixel_sha256"], "frame_source_pixels",
                "Proof pixels do not match the declared frame of the actual video", label)


def _actual_check(actual):
    actual = mapping(actual, "actual")
    duration = _rational(actual.get("duration"), "actual.duration", positive=True)
    number(actual.get("duration_s"), "actual.duration_s", minimum=0)
    require(float(duration) == actual["duration_s"], "media_clock", "Duration fields disagree")
    _rational(actual.get("fps"), "actual.fps", positive=True)
    tick = _rational(actual.get("time_base"), "actual.time_base", positive=True)
    origin = _rational(actual.get("source_start_pts"), "actual.source_start_pts")
    for field in ("width", "height", "frame_count"):
        integer(actual.get(field), "actual." + field, minimum=1)
    integer(actual.get("stream_index"), "actual.stream_index")
    require(type(actual.get("audio")) is bool and actual.get("clock") in {"cfr", "vfr"},
            "media_metadata", "Declare audio presence and the measured frame clock")
    require(actual.get("clock_origin") == "first_decoded_video_frame", "media_clock", "Unknown timestamp origin")
    nonempty(actual.get("sample_aspect_ratio"), "actual.sample_aspect_ratio")
    for value in sequence(actual.get("rotation"), "actual.rotation"):
        number(value, "actual.rotation[]")
    require(bool(sequence(actual.get("audio_streams"), "actual.audio_streams")) == actual["audio"],
            "media_metadata", "Audio presence and audio stream list disagree")
    frames = sequence(actual.get("frame_clock"), "actual.frame_clock")
    require(len(frames) == actual["frame_count"], "media_clock", "Frame count and measured clock disagree")
    expected_pts = Fraction()
    for index, frame in enumerate(frames):
        mapping(frame, f"actual.frame_clock[{index}]")
        integer(frame.get("index"), "frame.index")
        number(frame.get("pts_s"), "frame.pts_s", minimum=0)
        number(frame.get("duration_s"), "frame.duration_s", minimum=0)
        pts = _rational(frame.get("pts"), "frame.pts")
        frame_duration = _rational(frame.get("duration"), "frame.duration", positive=True)
        source_pts = _rational(frame.get("source_pts"), "frame.source_pts")
        stamp = frame.get("pts_ticks")
        require(type(stamp) is int and stamp * tick == source_pts == origin + pts,
                "media_clock", "Source and local PTS disagree")
        require(frame.get("index") == index and pts == expected_pts and
                frame.get("pts_s") == float(pts) and frame.get("duration_s") == float(frame_duration),
                "media_clock", "Decoded frame order or local timestamps disagree")
        expected_pts = pts + frame_duration
    require(expected_pts == duration, "media_clock", "Final frame and actual duration disagree")


def _export_check(exported, plan, clip_id, verify_files):
    """Check an export snapshot without asserting that a provider consumed it."""
    if exported is None:
        return [], {"status": "unverified", "provider_input_use": "unverified",
                    "reason": "No source export was supplied; returned bytes do not prove conditioning inputs"}
    exported = mapping(exported, "source_export")
    sha256(exported.get("export_sha256"), "source_export.export_sha256")
    require(digest({k: v for k, v in exported.items() if k != "export_sha256"}) == exported["export_sha256"],
            "export_digest", "Source export changed after it was compiled")
    require(exported.get("clip_id") == clip_id and exported.get("clip_fingerprint") == clip_fingerprint(plan, clip_id),
            "export_clip", "Source export refers to another clip or revision")
    mapping(exported.get("settings"), "source_export.settings")
    dependencies = sequence(exported.get("dependencies"), "source_export.dependencies")
    attachments = sequence(exported.get("attachments"), "source_export.attachments")
    for index, dependency in enumerate(dependencies):
        mapping(dependency, f"source_export.dependencies[{index}]")
        nonempty(dependency.get("clip_id"), f"source_export.dependencies[{index}].clip_id")
    for index, attachment in enumerate(attachments):
        mapping(attachment, f"source_export.attachments[{index}]")
        if "path" in attachment or "sha256" in attachment:
            nonempty(attachment.get("path"), "attachment.path")
            sha256(attachment.get("sha256"), "attachment.sha256")
            require(Path(attachment["path"]).is_absolute(), "absolute_path", "Use absolute attachment paths")
            if verify_files:
                verify_file(attachment["path"], attachment["sha256"], "attachment.path")
    incoming = next((j for j in plan["joins"] if j["to"] == clip_id and
                     j["strategy"] in {"observed_frame", "native_extension"}), None)
    expected_ids = {incoming["from"]} if incoming else set()
    require(len(dependencies) == len(expected_ids) and {d.get("clip_id") for d in dependencies} == expected_ids,
            "return_dependency", "Export must bind exactly the returned media required by the incoming join")
    for index, dependency in enumerate(dependencies):
        label = f"dependencies[{index}]"
        mapping(dependency, label)
        require(dependency.get("kind") == "returned_clip", "return_dependency", "Unknown dependency kind", label)
        parent_id = dependency["clip_id"]
        require(dependency.get("clip_fingerprint") == clip_fingerprint(plan, parent_id),
                "stale_dependency", "Parent instructions changed since this video was generated", label)
        for field in ("receipt_sha256", "sha256"):
            sha256(dependency.get(field), label + "." + field)
        nonempty(dependency.get("path"), label + ".path")
        require(Path(dependency["path"]).is_absolute(), "absolute_path", "Use absolute parent media paths", label)
        if verify_files:
            verify_file(dependency["path"], dependency["sha256"], label + ".path")
        matches = [a for a in attachments if a.get("source_clip_id") == parent_id and
                   a.get("receipt_sha256") == dependency["receipt_sha256"]]
        if incoming["strategy"] == "observed_frame":
            frame = mapping(dependency.get("selected_frame"), label + ".selected_frame")
            require(dependency.get("selected_frame_sha256") == frame.get("sha256") and any(
                a.get("role") == "start_frame" and a.get("path") == frame.get("path") and
                a.get("sha256") == frame.get("sha256") for a in matches),
                "return_dependency", "Exported start frame differs from the parent selection", label)
            if verify_files:
                parent_actual = _probe(dependency["path"])
                _frame_check(frame, dependency["path"], dependency["sha256"], parent_actual, label + ".selected_frame", True)
                verify_file(dependency["path"], dependency["sha256"], label + ".path")
        else:
            require(any(a.get("role") == "previous_video" and a.get("path") == dependency["path"] and
                        a.get("sha256") == dependency["sha256"] for a in matches),
                    "return_dependency", "Extension input differs from the parent video", label)
    return clone(dependencies), {"status": "export_bound", "provider_input_use": "unverified",
                                 "export_sha256": exported["export_sha256"],
                                 "reason": "Export bytes and dependencies are bound; provider input use is not attested"}


def import_clip(plan, clip_id, video_path, output_dir, *, selected_frame=None,
                observation=None, exported_clip=None):
    """Import real media and write a new receipt directory without altering use.

    ``selected_frame`` is a zero-based decoded frame index, explicitly chosen by
    the caller. ``boundary_window`` observations declare a half-open frame_range.
    No selection or observation is inferred from metadata or contact frames.
    """
    plan = validate_plan(plan)
    clip = next((c for c in plan["clips"] if c["id"] == clip_id), None)
    require(clip is not None, "unknown_clip", "Unknown clip " + str(clip_id))
    source = Path(video_path).expanduser().resolve()
    source_sha = file_sha256(source)
    actual = _probe(source)
    observed = _observation(observation, actual)
    if selected_frame is not None:
        integer(selected_frame, "selected_frame")
        require(selected_frame < actual["frame_count"], "frame_index", "Selected frame is outside the actual video")
    exported = clone(exported_clip) if exported_clip is not None else None
    dependencies, binding = _export_check(exported, plan, clip_id, True)
    output = Path(output_dir).expanduser().resolve()
    require(not output.exists(), "output_exists", "Use a new receipt directory; existing files will not be overwritten")
    output.mkdir(parents=True, exist_ok=False)
    samples = [_write_frame(source, source_sha, actual, index, output / f"frame-{index:06d}.png")
               for index in sorted({0, actual["frame_count"] - 1})]
    selected = None
    if selected_frame is not None:
        selected = next((clone(f) for f in samples if f["index"] == selected_frame), None)
        if selected is None:
            selected = _write_frame(source, source_sha, actual, selected_frame,
                                    output / f"frame-{selected_frame:06d}.png")
    semantics = _output_semantics(plan, clip_id, exported)
    usable = _usable(actual, clip["use"], plan["brief"]["aspect_ratio"], semantics)
    receipt = {
        "schema": RESULT_SCHEMA, "clip_id": clip_id, "clip_fingerprint": clip_fingerprint(plan, clip_id),
        "plan_sha256": digest(plan), "path": str(source), "sha256": source_sha,
        "receipt_path": str(output / "receipt.json"), "actual": actual,
        "requested_duration_s": clip["duration_s"], "planned_use": clone(clip["use"]),
        "usable": usable, "output_semantics": semantics, "sampled_frames": samples, "selected_frame": selected,
        "observation": observed, "boundary": _boundary(selected, observed, clip["use"], usable),
        "source_export": exported, "dependencies": dependencies, "dependency_binding": binding,
        "verification": {"metadata": "measured_ffprobe", "sample_scope": "sampled_frames",
                         "perceptual_quality": "unverified", "audio_listening": "unverified",
                         "user_approval": "unverified", "provider_input_use": "unverified"},
    }
    verify_file(str(source), source_sha, "source_after_import")
    # Recheck exported input bytes after probing/extracting, before persisting.
    _export_check(exported, plan, clip_id, True)
    receipt["receipt_sha256"] = digest(receipt)
    Path(receipt["receipt_path"]).write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def validate_receipt(receipt, plan, *, clip_id=None, verify_files=True):
    """Validate scope, checksum, observed source and frame bindings.

    ``verify_files=False`` only inspects the contract. SHA-256 is integrity, not
    authentication. Comparing dependencies to the current receipt graph belongs
    to compile_pack, which has that graph; this function checks their plan/files.
    """
    require(type(verify_files) is bool, "type", "verify_files must be boolean")
    data = clone(mapping(receipt, "receipt"))
    plan = validate_plan(plan)
    require(data.get("schema") == RESULT_SCHEMA, "result_schema", "Unsupported video receipt")
    sha256(data.get("receipt_sha256"), "receipt.receipt_sha256")
    require(digest({k: v for k, v in data.items() if k != "receipt_sha256"}) == data["receipt_sha256"],
            "receipt_digest", "Receipt changed after import")
    identifier = nonempty(data.get("clip_id"), "receipt.clip_id")
    require(clip_id is None or identifier == clip_id, "return_clip", "Receipt belongs to another clip")
    clip = next((c for c in plan["clips"] if c["id"] == identifier), None)
    require(clip is not None, "unknown_clip", "Receipt clip does not exist in this plan")
    require(data.get("clip_fingerprint") == clip_fingerprint(plan, identifier),
            "stale_receipt", "Clip instructions, identity, assets or joins changed since import")
    sha256(data.get("plan_sha256"), "receipt.plan_sha256")
    require(data.get("planned_use") == clip["use"] and data.get("requested_duration_s") == clip["duration_s"],
            "planned_actual", "Receipt's planned fields differ from this clip revision")
    nonempty(data.get("path"), "receipt.path")
    require(Path(data["path"]).is_absolute(), "absolute_path", "Use an absolute video path")
    sha256(data.get("sha256"), "receipt.sha256")
    _actual_check(data.get("actual"))
    if verify_files:
        verify_file(data["path"], data["sha256"], "receipt.path")
        require(digest(_probe(data["path"])) == digest(data["actual"]), "media_metadata",
                "Recorded metadata differs from the actual decoded video")
    actual = data["actual"]
    samples = sequence(data.get("sampled_frames"), "sampled_frames")
    for index, frame in enumerate(samples):
        mapping(frame, f"sampled_frames[{index}]")
    require({f.get("index") for f in samples} == {0, actual["frame_count"] - 1}
            and len(samples) == len({0, actual["frame_count"] - 1}),
            "sample_scope", "Receipt needs explicitly sampled first/last frames")
    for index, frame in enumerate(samples):
        _frame_check(frame, data["path"], data["sha256"], actual, f"sampled_frames[{index}]", verify_files)
    if data.get("selected_frame") is not None:
        _frame_check(data["selected_frame"], data["path"], data["sha256"], actual, "selected_frame", verify_files)
    observed = _observation(data.get("observation"), actual)
    require(observed == data.get("observation"), "observation_contract",
            "Receipts must retain the explicit continuity decision, including unassessed")
    semantics = _output_semantics(plan, identifier, data.get("source_export"))
    require(data.get("output_semantics") == semantics, "output_semantics",
            "Extension output must remain distinct from an independent returned clip")
    usable = _usable(actual, clip["use"], plan["brief"]["aspect_ratio"], semantics)
    require(data.get("usable") == usable, "usable_result", "Usability does not match measured timing and planned use")
    require(data.get("boundary") == _boundary(data.get("selected_frame"), observed, clip["use"], usable),
            "boundary_status", "Boundary state does not match selection, use or actual observation scope")
    dependencies, binding = _export_check(data.get("source_export"), plan, identifier, verify_files)
    require(data.get("dependencies") == dependencies and data.get("dependency_binding") == binding,
            "return_dependency", "Stored dependencies differ from the source export")
    expected_verification = {"metadata": "measured_ffprobe", "sample_scope": "sampled_frames",
                             "perceptual_quality": "unverified", "audio_listening": "unverified",
                             "user_approval": "unverified", "provider_input_use": "unverified"}
    require(data.get("verification") == expected_verification, "receipt_attestation",
            "Ingestion cannot certify perceptual quality, listening, provider inputs or user approval")
    if verify_files:
        verify_file(data["path"], data["sha256"], "source_after_validation")
    return data
