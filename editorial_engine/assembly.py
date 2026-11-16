"""Explicit multi-source assembly, real FFmpeg execution and measured receipts.

The assembly preserves playback speed. Frame-rate resampling and raster fitting
are opt-in operations recorded on each clip. Generation returns retain their
original receipts; an assembled intermediate does not complete pending post.
"""

from __future__ import annotations

from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .contracts import (ValidationError, clone, digest, file_sha256, integer, mapping, nonempty,
                        number, require, sequence, sha256, verify_file)

SCHEMA = "video-assembly/1"
TRANSITIONS = {"cut": None, "crossfade": "fade", "fadeblack": "fadeblack",
               "wipeleft": "wipeleft", "wiperight": "wiperight",
               "slideleft": "slideleft", "slideright": "slideright"}
_TOLERANCE = Fraction(1, 10_000_000)


def _fields(value, required, optional=(), label="object"):
    mapping(value, label)
    require(set(value) >= set(required) and set(value) <= set(required) | set(optional),
            "assembly_fields", "Missing or unknown fields in " + label, label)
    return value


def _time(value, label):
    require(type(value) in {int, float, str} and not isinstance(value, bool),
            "assembly_time", "Use a finite nonnegative time or rational string", label)
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError, OverflowError) as error:
        raise ValidationError("assembly_time", "Use a finite nonnegative time or rational string", label) from error
    require(result >= 0, "assembly_time", "Time cannot be negative", label)
    return result


def _round(value):
    """Nearest integer, with a positive half rounded up, independent of float."""
    return (value.numerator * 2 + value.denominator) // (2 * value.denominator)


def _frames(value, rate, label):
    count = _round(value * rate)
    require(abs(Fraction(count, 1) / rate - value) <= _TOLERANCE,
            "assembly_frame_alignment", "Time must coincide with an output frame boundary", label)
    return count


def _seconds(value):
    return format(float(value), ".12f")


def _run(arguments):
    try:
        result = subprocess.run(arguments, capture_output=True, check=False)
    except OSError as error:
        raise ValidationError("assembly_backend", "Media command could not run: " + str(error)) from error
    require(result.returncode == 0, "assembly_backend",
            result.stderr.decode("utf-8", errors="replace")[-1800:] or "Media command failed")
    return result.stdout


def _read_media(path):
    # Reuse the existing decoded-frame probe and gap-sensitive audio clock.
    from .generation.ingest import _probe
    from .audio_render import _probe as audio_probe, _audio_clock, AudioRenderError
    media = _probe(path)
    require(media["clock"] == "cfr", "assembly_vfr", "Conform variable-rate video explicitly before assembly")
    require(abs(Fraction(media["source_start_pts"])) <= Fraction(media["time_base"]),
            "assembly_origin", "Normalize the source video start explicitly before assembly")
    require(media["sample_aspect_ratio"] in {"1:1", "1/1"} and
            not any(abs(value) % 360 for value in media["rotation"]),
            "assembly_raster", "Resolve non-square pixels or display rotation explicitly before assembly")
    require(len(media["audio_streams"]) <= 1, "assembly_audio_tracks",
            "Select a single source audio track explicitly before assembly")
    try:
        audio = _audio_clock(Path(path), audio_probe(Path(path))) if media["audio"] else None
    except AudioRenderError as error:
        raise ValidationError("assembly_audio_source", str(error), str(path)) from error
    if audio is not None:
        audio = {**audio, "origin": str(audio["origin"])}
    return {**media, "audio_clock": audio}


def _checked_generation(plan, receipts, verify_files):
    from .generation.contracts import validate_plan
    from .generation.ingest import validate_receipt
    directed = validate_plan(plan, verify_files=verify_files)
    raw = mapping(receipts, "generation.receipts")
    required = {clip["id"] for clip in directed["clips"]}
    require(set(raw) == required, "assembly_returns", "Supply exactly one current receipt for each generated clip")
    checked = {key: validate_receipt(value, directed, clip_id=key, verify_files=verify_files)
               for key, value in raw.items()}
    for clip in directed["clips"]:
        receipt = checked[clip["id"]]
        require(receipt["usable"]["covers_planned_use"] and receipt["usable"]["frame_aligned_use"],
                "assembly_return_use", "Returned media does not cover the exact planned useful range", clip["id"])
        require(receipt["output_semantics"]["mode"] in {"independent_clip", "appended_clip"},
                "assembly_extension", "A full extended sequence needs an explicit source-to-clip mapping", clip["id"])
    for join in directed["joins"]:
        if join["strategy"] not in {"observed_frame", "native_extension"}:
            continue
        parent, child = checked[join["from"]], checked[join["to"]]
        dependencies = child["dependencies"]
        dependency = next((d for d in dependencies if d["clip_id"] == join["from"]), None)
        expected = {"clip_id": parent["clip_id"], "clip_fingerprint": parent["clip_fingerprint"],
                    "receipt_sha256": parent["receipt_sha256"], "path": parent["path"], "sha256": parent["sha256"]}
        require(dependency is not None and all(dependency.get(k) == v for k, v in expected.items()),
                "assembly_stale_dependency", "Returned clip is bound to an older parent result", join["to"])
        if join["strategy"] == "observed_frame":
            selected, observed = parent["selected_frame"], parent["observation"]
            require(isinstance(selected, dict) and dependency.get("selected_frame") == selected and
                    dependency.get("selected_frame_sha256") == selected["sha256"],
                    "assembly_stale_dependency", "Returned clip uses a different parent frame", join["to"])
            require(parent["boundary"]["status"] == "observed" and parent["boundary"]["matches_planned_use"] and
                    isinstance(observed, dict) and observed["scope"] in {"boundary_window", "continuous_video"} and
                    observed.get("continuity_decision", {}).get("status") == "accept",
                    "assembly_continuity", "Observed-frame conditioning needs an accepted, reviewed boundary", join["id"])
        else:
            use_end = next(c["use"]["end_s"] for c in directed["clips"] if c["id"] == join["from"])
            require(abs(Fraction(parent["actual"]["duration"]) - Fraction(str(use_end))) <= _TOLERANCE,
                    "assembly_extension", "Extension source end differs from the authored useful end", join["id"])
    return directed, checked


def validate_assembly(plan, *, verify_files=True):
    """Return a measured validation report, leaving the authored plan untouched."""
    require(type(verify_files) is bool, "type", "verify_files must be boolean")
    data = clone(plan)
    _fields(data, {"schema", "id", "revision", "sources", "clips", "joins", "output"},
            {"generation", "pending_post", "plan_sha256"}, "assembly")
    require(data["schema"] == SCHEMA, "assembly_schema", "Unsupported assembly contract")
    nonempty(data["id"], "assembly.id")
    integer(data["revision"], "assembly.revision", minimum=1)
    unsigned = {k: v for k, v in data.items() if k != "plan_sha256"}
    identity = digest(unsigned)
    if "plan_sha256" in data:
        require(data["plan_sha256"] == identity, "assembly_plan_changed", "Assembly changed without a new sealed plan")
    output = _fields(data["output"], {"fps", "width", "height", "audio"}, label="output")
    rate = _time(output["fps"], "output.fps")
    require(rate > 0, "assembly_fps", "Output FPS must be positive")
    for dimension in ("width", "height"):
        integer(output[dimension], "output." + dimension, minimum=2)
        require(output[dimension] % 2 == 0, "assembly_raster", "H.264 output dimensions must be even")
    audio = _fields(output["audio"], {"mode", "sample_rate", "channels", "missing"}, label="output.audio")
    require(audio["mode"] in {"source", "none"} and audio["missing"] in {"reject", "silence"},
            "assembly_audio", "Declare source/none output and reject/silence for unavailable audio")
    require(audio["sample_rate"] == 48000 and type(audio["sample_rate"]) is int and
            audio["channels"] == 2 and type(audio["channels"]) is int,
            "assembly_audio", "This executor uses explicit 48000 Hz stereo audio")
    sources, measured = {}, {}
    for source in sequence(data["sources"], "sources"):
        _fields(source, {"id", "path", "sha256"}, label="source")
        key = nonempty(source["id"], "source.id")
        require(key not in sources, "assembly_source_id", "Duplicate source ID")
        require(isinstance(source["path"], str) and Path(source["path"]).is_absolute(),
                "assembly_source_path", "Use an absolute local source path")
        sha256(source["sha256"], "source.sha256")
        if verify_files:
            verify_file(source["path"], source["sha256"], "source." + key)
            measured[key] = _read_media(source["path"])
        sources[key] = source
    clips = sequence(data["clips"], "clips")
    require(bool(clips), "assembly_clips", "At least one authored clip is required")
    identifiers, lengths, ranges = [], [], []
    for clip in clips:
        _fields(clip, {"id", "source_id", "use", "fit", "reframe_fps", "audio"}, label="clip")
        key = nonempty(clip["id"], "clip.id")
        require(key not in identifiers and clip["source_id"] in sources,
                "assembly_clip", "Clip IDs must be unique and sources must exist", key)
        identifiers.append(key)
        _fields(clip["use"], {"start_s", "end_s"}, label="clip.use")
        start, end = (_time(clip["use"][k], key + "." + k) for k in ("start_s", "end_s"))
        require(end > start, "assembly_use", "Use a nonempty explicit source interval", key)
        require(clip["fit"] in {"reject", "contain", "cover"} and clip["reframe_fps"] in {"reject", "resample"},
                "assembly_normalization", "Declare raster fit and FPS policy", key)
        _fields(clip["audio"], {"mode", "gain_db"}, label="clip.audio")
        require(clip["audio"]["mode"] in {"source", "silence"}, "assembly_audio", "Unknown clip audio policy", key)
        number(clip["audio"]["gain_db"], "clip.audio.gain_db", minimum=-60, maximum=0)
        length = _frames(end - start, rate, key + ".duration")
        require(length > 0, "assembly_use", "Clip needs at least one output frame", key)
        first = last = None
        if verify_files:
            actual = measured[clip["source_id"]]
            source_rate = Fraction(actual["fps"])
            first, last = _frames(start, source_rate, key + ".start_s"), _frames(end, source_rate, key + ".end_s")
            require(last <= actual["frame_count"], "assembly_source_short", "Source does not cover the selected frames", key)
            require(source_rate == rate or clip["reframe_fps"] == "resample", "assembly_fps_mismatch",
                    "FPS conversion must be explicitly declared as resample", key)
            require((actual["width"], actual["height"]) == (output["width"], output["height"]) or clip["fit"] != "reject",
                    "assembly_size_mismatch", "Raster conversion requires explicit contain or cover", key)
            clock = actual["audio_clock"]
            if audio["mode"] == "source" and clip["audio"]["mode"] == "source" and audio["missing"] == "reject":
                require(clock is not None, "assembly_audio_missing", "Source audio is required", key)
                origin = Fraction(clock["origin"])
                stop = origin + Fraction(clock["sample_count"], clock["sample_rate"])
                require(origin <= start + Fraction(1, clock["sample_rate"]) and stop >= end - Fraction(1, clock["sample_rate"]),
                        "assembly_audio_short", "Audio does not cover this clip; authorize silence or supply a complete source", key)
        lengths.append(length)
        ranges.append((first, last))
    require({c["source_id"] for c in clips} == set(sources), "assembly_unused_source", "Every declared source must be used")
    joins = sequence(data["joins"], "joins")
    require(len(joins) == len(clips) - 1, "assembly_joins", "Declare exactly one join for each adjacent clip pair")
    overlaps = []
    for index, join in enumerate(joins):
        _fields(join, {"from", "to", "transition", "duration_s"}, label="join")
        require((join["from"], join["to"]) == tuple(identifiers[index:index + 2]),
                "assembly_join_order", "Joins must follow the authored clip order")
        require(join["transition"] in TRANSITIONS, "assembly_transition", "Unsupported transition; no automatic substitute is used")
        duration = _time(join["duration_s"], "join.duration_s")
        frames = _frames(duration, rate, "join.duration_s")
        require((join["transition"] == "cut" and frames == 0) or (join["transition"] != "cut" and frames > 0),
                "assembly_transition", "Cuts have zero overlap; other transitions need a positive overlap")
        require(frames < min(lengths[index:index + 2]), "assembly_overlap", "An overlap cannot consume a complete clip")
        overlaps.append(frames)
    for index, length in enumerate(lengths):
        require((overlaps[index - 1] if index else 0) + (overlaps[index] if index < len(overlaps) else 0) <= length,
                "assembly_overlap", "Incoming and outgoing transitions collide", identifiers[index])
    timeline, cursor = [], 0
    for index, clip in enumerate(clips):
        cursor -= overlaps[index - 1] if index else 0
        end = cursor + lengths[index]
        timeline.append({"clip_id": clip["id"], "source_id": clip["source_id"], "use": clone(clip["use"]),
                         "start_frame": cursor, "end_frame": end, "frames": lengths[index],
                         "start_s": float(Fraction(cursor, 1) / rate), "end_s": float(Fraction(end, 1) / rate),
                         "source_first_frame": ranges[index][0], "source_end_frame": ranges[index][1],
                         "audio_samples": _round(Fraction(end * 48000, 1) / rate) - _round(Fraction(cursor * 48000, 1) / rate),
                         "fit": clip["fit"], "reframe_fps": clip["reframe_fps"]})
        cursor = end
    pending = sequence(data.get("pending_post", []), "pending_post")
    pending_ids = set()
    for item in pending:
        mapping(item, "pending_post.item")
        key = nonempty(item.get("id"), "pending_post.id")
        require(key not in pending_ids and item.get("status") == "pending", "assembly_pending_post",
                "Each pending operation needs a unique ID and pending status", key)
        pending_ids.add(key)
        nonempty(item.get("kind"), "pending_post.kind")
        span = _fields(item.get("timeline_interval"), {"start_s", "end_s"}, label="pending_post.timeline_interval")
        a, b = (_time(span[name], key + "." + name) for name in ("start_s", "end_s"))
        require(0 <= a < b <= Fraction(cursor, 1) / rate + _TOLERANCE,
                "assembly_pending_post", "Pending operation must use a valid output-clock interval", key)
    if "generation" in data:
        origin = _fields(data["generation"], {"plan", "plan_sha256", "receipts", "transition_map"}, label="generation")
        require(origin["plan_sha256"] == digest(origin["plan"]), "assembly_generation_changed", "Generation plan snapshot changed")
        directed, returned = _checked_generation(origin["plan"], origin["receipts"], verify_files)
        require(directed["brief"].get("audio_execution") != "none" or audio["mode"] == "none",
                "assembly_generation_audio", "A silent generation plan requires an explicitly silent assembly")
        require(not directed["brief"].get("require_generated_audio", False) or
                (audio["mode"] == "source" and audio["missing"] == "reject"),
                "assembly_generation_audio", "Required generated audio cannot be dropped or replaced with silence")
        require(identifiers == [c["id"] for c in directed["clips"]], "assembly_generation_order", "Generation order changed")
        for clip, original in zip(clips, directed["clips"]):
            r = returned[clip["id"]]
            source = sources[clip["source_id"]]
            require(clip["use"] == original["use"] and source["path"] == r["path"] and source["sha256"] == r["sha256"],
                    "assembly_generation_binding", "Assembly no longer uses the declared returned clip and range", clip["id"])
        expected_joins = _generation_joins(directed, origin["transition_map"])
        require(joins == expected_joins and pending == _generation_post(directed), "assembly_generation_changed",
                "Generation joins or pending post were removed or changed")
        require(abs(Fraction(cursor, 1) / rate - Fraction(str(directed["brief"]["target_duration_s"]))) <= _TOLERANCE,
                "assembly_generation_duration", "Assembly differs from the authored final duration")
    if verify_files:
        for source in sources.values():
            verify_file(source["path"], source["sha256"], "source_after_validation")
    return {"schema": "video-assembly-validation/1", "plan_sha256": identity, "files_verified": verify_files,
            "output": clone(output), "sources": measured, "timeline": timeline,
            "overlap_frames": overlaps, "frame_count": cursor, "duration_s": float(Fraction(cursor, 1) / rate),
            "duration": str(Fraction(cursor, 1) / rate), "audio_samples": _round(Fraction(cursor * 48000, 1) / rate),
            "pending_post": clone(pending), "perceptual_review": "not_performed"}


def _generation_joins(plan, transitions):
    explicit = mapping(transitions, "transition_map")
    require(set(explicit) <= {j["id"] for j in plan["joins"]}, "assembly_transition_map", "Unknown generated join ID")
    pairs = {(j["from"], j["to"]): j for j in plan["joins"]}
    result = []
    for a, b in zip(plan["clips"], plan["clips"][1:]):
        join = pairs[(a["id"], b["id"])]
        transition = explicit.get(join["id"])
        if transition is None:
            require(join["execution"] == "generation" and join["overlap_s"] == 0,
                    "assembly_transition_map", "Explicitly map each post/hybrid join to a supported assembly transition", join["id"])
            transition = "cut"
        require(isinstance(transition, str) and transition in TRANSITIONS,
                "assembly_transition", "Unsupported requested assembly transition", join["id"])
        result.append({"from": a["id"], "to": b["id"], "transition": transition, "duration_s": join["overlap_s"]})
    return result


def _generation_post(plan):
    from .generation.contracts import assembly_timing
    locations = {row["clip_id"]: row for row in assembly_timing(plan)["timeline"]}
    assets = {asset["id"]: asset for asset in plan["assets"]}
    pending = []
    for clip in plan["clips"]:
        shift = Fraction(str(locations[clip["id"]]["start_s"])) - Fraction(str(clip["use"]["start_s"]))
        for post in clip["post"]:
            record = {"id": "post:" + clip["id"] + ":" + post["id"], "clip_id": clip["id"],
                      "kind": post["kind"], "status": "pending", "instruction": clone(post),
                      "timeline_interval": {key: float(shift + Fraction(str(post[key]))) for key in ("start_s", "end_s")}}
            if post.get("asset_id"):
                record["asset"] = clone(assets[post["asset_id"]])
            pending.append(record)
    if plan["brief"].get("audio_execution", "generation") == "post":
        pending.extend({"id": "audio-post:" + clip["id"], "clip_id": clip["id"], "kind": "audio_post", "status": "pending",
                        "timeline_interval": {key: locations[clip["id"]][key] for key in ("start_s", "end_s")},
                        "dialogue": clone(clip["dialogue"]),
                        "direction": clone(clip["audio"]),
                        "lip_sync_unresolved": any(d["mode"] == "on_camera" for d in clip["dialogue"])} for clip in plan["clips"])
    return pending


def from_generation(plan, receipts, *, fps, width, height, fit="reject", fps_policy="reject",
                    audio="source", missing_audio="silence", transitions=None):
    """Bind actual returned clips to an explicit, sealed assembly plan.

Post/hybrid joins require a caller-authored transition map. Effects and speech
destined to post remain pending; this function never claims they were applied.
"""
    directed, checked = _checked_generation(plan, receipts, True)
    transition_map = clone(transitions or {})
    data = {"schema": SCHEMA, "id": directed["id"] + "-assembly", "revision": directed["revision"],
            "sources": [{"id": c["id"], "path": checked[c["id"]]["path"], "sha256": checked[c["id"]]["sha256"]}
                        for c in directed["clips"]],
            "clips": [{"id": c["id"], "source_id": c["id"], "use": clone(c["use"]), "fit": fit,
                       "reframe_fps": fps_policy, "audio": {"mode": "source", "gain_db": 0}} for c in directed["clips"]],
            "joins": _generation_joins(directed, transition_map),
            "output": {"fps": str(fps), "width": width, "height": height,
                       "audio": {"mode": audio, "sample_rate": 48000, "channels": 2, "missing": missing_audio}},
            "generation": {"plan": directed, "plan_sha256": digest(directed), "receipts": checked,
                           "transition_map": transition_map}, "pending_post": _generation_post(directed)}
    data["plan_sha256"] = digest(data)
    validate_assembly(data, verify_files=True)
    return data


def _filters(plan, checked):
    output, rate = plan["output"], Fraction(str(plan["output"]["fps"]))
    # setpts/concat can remove the frame-rate hint. Reassert CFR on the already
    # frame-aligned clock; conversions from another rate were authorized above.
    tb = f"fps=fps={rate}:start_time=0:round=near:eof_action=round,settb=expr=1/{rate.numerator}"
    source_by_id = {s["id"]: s for s in plan["sources"]}
    arguments, filters = [], []
    has_audio = output["audio"]["mode"] == "source"
    for index, (clip, row) in enumerate(zip(plan["clips"], checked["timeline"])):
        source, media = source_by_id[clip["source_id"]], checked["sources"][clip["source_id"]]
        arguments += ["-noautorotate", "-protocol_whitelist", "file,pipe", "-i", source["path"]]
        chain = [f"trim=start_frame={row['source_first_frame']}:end_frame={row['source_end_frame']}", "setpts=PTS-STARTPTS"]
        if clip["fit"] != "reject":
            w, h = output["width"], output["height"]
            if clip["fit"] == "contain":
                chain += [f"scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2",
                          f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"]
            else:
                chain += [f"scale={w}:{h}:force_original_aspect_ratio=increase:force_divisible_by=2",
                          f"crop={w}:{h}:(iw-ow)/2:(ih-oh)/2"]
        chain += ["setsar=1", "format=yuv420p", tb]
        filters.append(f"[{index}:{media['stream_index']}]" + ",".join(chain) + f"[v{index}]")
        if has_audio:
            samples = row["audio_samples"]
            if clip["audio"]["mode"] == "silence" or not media["audio"]:
                audio_chain = f"anullsrc=r=48000:cl=stereo,atrim=end_sample={samples},asetpts=N/SR/TB"
            else:
                start = _round(_time(clip["use"]["start_s"], "use") * 48000)
                stream = media["audio_streams"][0]["index"]
                audio_chain = (f"[{index}:{stream}]aresample=48000:async=0:first_pts=0,"
                               f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                               f"atrim=start_sample={start}:end_sample={start + samples},asetpts=N/SR/TB")
                if output["audio"]["missing"] == "silence":
                    audio_chain += f",apad=whole_len={samples},atrim=end_sample={samples}"
                audio_chain += f",volume={float(clip['audio']['gain_db']):.8f}dB"
            filters.append(audio_chain + f"[a{index}]")
    video, audio = "v0", "a0"
    for index, join in enumerate(plan["joins"], 1):
        vnext, anext = f"vx{index}", f"ax{index}"
        overlap = checked["overlap_frames"][index - 1]
        if join["transition"] == "cut":
            filters.append(f"[{video}][v{index}]concat=n=2:v=1:a=0,{tb}[{vnext}]")
            if has_audio:
                filters.append(f"[{audio}][a{index}]concat=n=2:v=0:a=1,asetpts=N/SR/TB[{anext}]")
        else:
            offset = Fraction(checked["timeline"][index]["start_frame"], 1) / rate
            filters.append(f"[{video}][v{index}]xfade=transition={TRANSITIONS[join['transition']]}:"
                           f"duration={_seconds(Fraction(overlap, 1) / rate)}:offset={_seconds(offset)},{tb}[{vnext}]")
            if has_audio:
                boundary = checked["timeline"][index - 1]["end_frame"]
                samples = (_round(Fraction(boundary * 48000, 1) / rate) -
                           _round(Fraction(checked["timeline"][index]["start_frame"] * 48000, 1) / rate))
                filters.append(f"[{audio}][a{index}]acrossfade=ns={samples}:c1=tri:c2=tri,asetpts=N/SR/TB[{anext}]")
        video, audio = vnext, anext
    return arguments, ";".join(filters), video, audio if has_audio else None


def _review_plan(plan, checked):
    result = {"schema": "assembly-review-plan/1", "plan_id": plan["id"], "version": plan["revision"],
              "assembly_plan_sha256": checked["plan_sha256"],
              "decisions": [{"id": "clip:" + c["id"]} for c in plan["clips"]],
              "validation": {"executable": True, "scope": "assembly_only", "perceptual_review": "not_performed"},
              "pending_post": clone(checked["pending_post"]), "history": []}
    result["plan_sha256"] = digest(result)
    return result


def render_assembly(plan, output_dir):
    """Render real clips, verify clocks and create an immutable result directory."""
    require(shutil.which("ffmpeg") and shutil.which("ffprobe"), "assembly_backend", "FFmpeg and FFprobe are required")
    data = clone(plan)
    checked = validate_assembly(data, verify_files=True)
    output = Path(output_dir).expanduser().resolve()
    require(not output.exists(), "assembly_output_exists", "Use a new output directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    arguments, graph, video_label, audio_label = _filters(data, checked)
    from .generation.ingest import _probe
    from .audio_render import _pcm_measure, _probe as audio_probe, _audio_clock
    with tempfile.TemporaryDirectory(prefix="assembly-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        stage.mkdir()
        picture, pcm, rendered = stage / "picture.mp4", stage / "audio.wav", stage / "render.mp4"
        command = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-filter_complex_threads", "1",
                   *arguments, "-filter_complex", graph, "-map", f"[{video_label}]", "-an",
                   "-map_metadata", "-1", "-map_chapters", "-1", "-c:v", "libx264", "-preset", "medium",
                   "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough", str(picture)]
        if audio_label:
            command += ["-map", f"[{audio_label}]", "-vn", "-c:a", "pcm_f32le", "-ar", "48000", "-ac", "2", str(pcm)]
        _run(command)
        picture_media = _probe(picture)
        require(picture_media["clock"] == "cfr" and picture_media["frame_count"] == checked["frame_count"] and
                Fraction(picture_media["fps"]) == Fraction(str(data["output"]["fps"])) and
                (picture_media["width"], picture_media["height"]) == (data["output"]["width"], data["output"]["height"]),
                "assembly_render_clock", "Rendered picture differs from the authored frame clock or raster")
        audio_report = {"mode": "none"}
        if audio_label:
            pcm_metrics = _pcm_measure(pcm, 48000)
            require(pcm_metrics["sample_count"] == checked["audio_samples"], "assembly_audio_clock",
                    "Mixed PCM sample count differs from the authored timeline")
            require(pcm_metrics["sample_peak"] <= 1.00001, "assembly_audio_peak", "Lower the explicit clip gains; mixed PCM clips")
            _run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-i", str(picture), "-i", str(pcm),
                  "-map", "0:v:0", "-map", "1:a:0", "-map_metadata", "-1", "-map_chapters", "-1",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                  "-movflags", "+faststart", str(rendered)])
            encoded = _pcm_measure(rendered, 48000)
            encoded_clock = _audio_clock(rendered, audio_probe(rendered))
            require(encoded_clock is not None and abs(Fraction(encoded_clock["origin"])) <= Fraction(1, 48000),
                    "assembly_audio_origin", "Encoded audio is not aligned with the output video")
            padding = encoded["sample_count"] - checked["audio_samples"]
            require(0 <= padding < 1024 and encoded["sample_peak"] <= 1.00001,
                    "assembly_audio_encode", "AAC output has unexpected padding or clipped samples")
            audio_report = {"mode": "source", "missing_policy": data["output"]["audio"]["missing"],
                            "target_samples": checked["audio_samples"], "pcm": pcm_metrics, "encoded": encoded,
                            "aac_padding_samples": padding, "crossfade_curve": "linear",
                            "pcm_path": str(output / "audio.wav"), "pcm_sha256": file_sha256(pcm),
                            "listened": False, "voice_isolation": False}
        else:
            os.rename(picture, rendered)
        actual = _probe(rendered)
        require(actual["frame_count"] == checked["frame_count"] and actual["clock"] == "cfr" and
                Fraction(actual["fps"]) == Fraction(str(data["output"]["fps"])) and
                abs(Fraction(actual["duration"]) - Fraction(checked["duration"])) <= Fraction(actual["time_base"]),
                "assembly_output_clock", "Encoded video changed the authored timeline")
        _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(rendered), "-f", "null", "-"])
        for source in data["sources"]:
            verify_file(source["path"], source["sha256"], "source_after_render")
        if "generation" in data:
            _checked_generation(data["generation"]["plan"], data["generation"]["receipts"], True)
        if picture.exists():
            picture.unlink()
        review_plan = _review_plan(data, checked)
        receipt = {"schema": "video-assembly-result/1", "path": str(output / "render.mp4"), "sha256": file_sha256(rendered),
                   "clock": "output", "fps": str(data["output"]["fps"]), "frame_count": checked["frame_count"],
                   "duration_s": actual["duration_s"], "plan_sha256": review_plan["plan_sha256"],
                   "assembly_plan_sha256": checked["plan_sha256"], "review_plan": review_plan,
                   "decision_ids": [d["id"] for d in review_plan["decisions"]],
                   "sources": clone(data["sources"]), "timeline": checked["timeline"], "joins": clone(data["joins"]),
                   "source_measurements": {key: {name: media[name] for name in
                       ("duration_s", "duration", "fps", "frame_count", "width", "height", "audio_clock")}
                       for key, media in checked["sources"].items()},
                   "audio": audio_report, "pending_post": clone(checked["pending_post"]),
                   "status": "assembled_with_pending_post" if checked["pending_post"] else "assembled",
                   "delivery_ready": False, "technical_checks": {"decode": "pass", "clock": "pass", "source_unchanged": "pass"},
                   "perceptual_review": {"motion": "unverified", "audio": "unverified", "editorial": "unverified"},
                   "user_approval": "pending", "runtime_executed": True,
                   "implementation_sha256": file_sha256(__file__),
                   "receipt_path": str(output / "receipt.json")}
        receipt["receipt_sha256"] = digest(receipt)
        (stage / "assembly.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (stage / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (stage / "filter-complex.txt").write_text(graph + "\n", encoding="utf-8")
        require(not output.exists(), "assembly_output_exists", "Output appeared while rendering; keep the new result separate")
        os.rename(stage, output)
    return receipt
