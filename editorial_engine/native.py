"""Compile a sealed editorial plan into the existing source-preserving renderer.

Only implemented operations are exposed. A proposal cannot supply arbitrary
code, a command, an asset path or a new tracking result. Those come from hashed
capability receipts created before direction. Missing coverage is an error;
the executor never changes the editorial decision to a simpler effect.
"""

from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageFont

from .contracts import (clone, digest, file_sha256, index_by_id, number,
                        require, validate_analysis, verify_file)
from .planner import validate_plan

BUNDLE_SCHEMA = "contextual-edit/1"
OPERATIONS = ("kinetic_type", "overlay", "behind_subject", "projected_asset",
              "body_orbit", "hand_accent", "sfx_spot", "motion_layer", "motion_behind", "projected_behind")


def native_catalog() -> dict:
    """Return only adapters implemented here; readiness still needs a receipt."""
    def effect(identifier, operation, functions, *, modality="visual", anchors=None,
               requirements=None, bindings=None, parameters=None, channels=None):
        return {"id": identifier, "version": "1.0", "status": "ready",
                "functions": functions, "modality": modality,
                "renderer": {"name": "native", "operation": operation},
                "requirements": requirements or [], "anchors": anchors or ["screen"],
                "binding_requirements": bindings or {}, "parameters": parameters or {},
                "occupied_channels": channels or ["foreground_graphic"], "fallbacks": ["preserve"]}

    animation = {"animation": {"type": "string", "enum": ["hold", "fade", "pop", "slide"]},
                 "entrance_seconds": {"type": "number", "minimum": 0.05, "maximum": 2}}
    projection_animation = {**animation, "shutter_fraction": {"type": "number", "minimum": 0, "maximum": 1}}
    title = {"title": {"type": "string", "required": True},
             "subtitle": {"type": "string"}}
    return {"schema_version": "1.0", "effects": [
        effect("native.kinetic_type", "kinetic_type", ["emphasize", "explain", "identify"],
               requirements=["protected_regions"], parameters=title),
        effect("native.overlay", "overlay", ["visualize_concept", "emphasize", "reveal"],
               requirements=["protected_regions"], bindings={"asset": "image_asset"}, parameters=animation),
        effect("native.behind_subject", "behind_subject", ["visualize_concept", "spatial_relation", "reveal"],
               requirements=["protected_regions"], bindings={"asset": "image_asset", "matte": "subject_mask"},
               parameters=animation, channels=["background_graphic"]),
        effect("native.motion_layer", "motion_layer", ["visualize_concept", "emphasize", "explain", "reveal", "reinforce_action"],
               requirements=["protected_regions"], bindings={"asset": "motion_asset"},
               parameters={"asset_start_frame": {"type": "integer", "minimum": 0}, **animation}),
        effect("native.motion_behind", "motion_behind", ["visualize_concept", "spatial_relation", "reveal", "emphasize"],
               requirements=["protected_regions"], bindings={"asset": "motion_asset", "matte": "subject_mask"},
               parameters={"asset_start_frame": {"type": "integer", "minimum": 0},
                           "min_visible_fraction": {"type": "number", "minimum": 0, "maximum": 1},
                           "min_glyph_visible_fraction": {"type": "number", "minimum": 0, "maximum": 1}, **animation},
               channels=["background_graphic"]),
        effect("native.projected_asset", "projected_asset", ["visualize_concept", "spatial_relation", "identify"],
               anchors=["planar"], requirements=["protected_regions"], bindings={"asset": "image_asset"},
               parameters=projection_animation, channels=["environment_graphic"]),
        effect("native.projected_behind", "projected_behind", ["visualize_concept", "spatial_relation", "identify"],
               anchors=["planar"], requirements=["protected_regions"],
               bindings={"asset": "image_asset", "matte": "subject_mask"},
               parameters=projection_animation, channels=["background_graphic"]),
        effect("native.body_orbit", "body_orbit", ["emphasize", "spatial_relation", "reveal"],
               anchors=["body"], requirements=["protected_regions"], bindings={"matte": "subject_mask"},
               parameters={"title": title["title"]}, channels=["body_graphic"]),
        effect("native.hand_accent", "hand_accent", ["reinforce_action", "emphasize", "spatial_relation"],
               anchors=["hand"], requirements=["protected_regions"], bindings={"matte": "subject_mask"},
               parameters={"side": {"type": "string", "required": True, "enum": ["left", "right"]}},
               channels=["hand_graphic"]),
        effect("native.sfx", "sfx_spot", ["accent", "transition", "reinforce_action", "atmosphere"],
               modality="audio", anchors=["none"], bindings={"asset": "audio_asset"},
               parameters={"target_sample": {"type": "integer", "minimum": 0, "required": True},
                           "sample_rate": {"type": "integer", "enum": [48000], "required": True},
                           "gain_db": {"type": "number", "minimum": -60, "maximum": 0},
                           "trim_in": {"type": "integer", "minimum": 0},
                           "trim_out": {"type": "integer", "minimum": 1},
                           "negative_start_policy": {"type": "string", "enum": ["reject", "trim_start"]}},
               channels=["sfx_accent"]),
    ]}


def implementation_fingerprint() -> dict:
    root = Path(__file__).resolve().parents[1]
    names = ["editorial_engine/native.py", "visual_fidelity/video_anchor.py",
             "visual_fidelity/anchor_graphics.py", "visual_fidelity/editorial_motion.py",
             "visual_fidelity/body_depth.py", "visual_fidelity/orbit_type.py",
             "audiovisual/semantic_audio.py", "editorial_engine/audio_render.py",
             "editorial_engine/motion_assets.py"]
    return {name: file_sha256(root / name) for name in names if (root / name).is_file()}


def probe_native_backend() -> dict:
    """Probe actual codec/filter features; this is readiness, not a render QA."""
    import importlib
    require(shutil.which("ffmpeg") and shutil.which("ffprobe"), "media_backend", "FFmpeg and FFprobe are required")
    encoders_text = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True).stdout
    filters_text = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=True).stdout
    def names(text):
        return {line.split()[1] for line in text.splitlines() if len(line.split()) >= 2}
    encoders, filters = names(encoders_text), names(filters_text)
    missing = []
    for module in ("visual_fidelity.video_anchor", "visual_fidelity.body_depth", "visual_fidelity.editorial_motion"):
        try:
            importlib.import_module(module)
        except (ImportError, OSError) as error:
            missing.append({"module": module, "reason": type(error).__name__})
    visual = "libx264" in encoders and not missing
    required_audio_filters = {"aresample", "atrim", "asetpts", "adelay", "amix", "apad", "volume", "alimiter", "sidechaincompress", "asplit"}
    try:
        importlib.import_module("editorial_engine.audio_render")
        audio_import = True
    except (ImportError, OSError):
        audio_import = False
    audio = audio_import and {"aac", "pcm_f32le"} <= encoders and required_audio_filters <= filters
    return {"visual_available": visual, "audio_available": audio, "missing_imports": missing,
            "libx264": "libx264" in encoders, "aac": "aac" in encoders,
            "missing_audio_filters": sorted(required_audio_filters - filters), "applied_to_source": False}


def _read_receipt(capability: dict) -> dict:
    proof = capability["verification"]
    verify_file(proof["artifact_path"], proof["artifact_sha256"], capability["id"])
    receipt = json.loads(Path(proof["artifact_path"]).read_text(encoding="utf-8"))
    require(receipt.get("source_sha256") == capability["source_sha256"],
            "receipt_source", "Native receipt belongs to a different source", capability["id"])
    for asset in receipt.get("files", []):
        verify_file(asset["path"], asset["sha256"], capability["id"])
    return receipt


def _frames(interval: dict, rate: Fraction, count: int) -> tuple[int, int]:
    # Decimal strings avoid a second binary float rounding at a frame boundary.
    first = math.ceil(Fraction(str(interval["start_s"])) * rate - Fraction(1, 10**7))
    last = math.ceil(Fraction(str(interval["end_s"])) * rate - Fraction(1, 10**7))
    require(0 <= first < last <= count, "frame_interval", "Decision has no valid complete frame interval")
    return first, last


def _protected(capabilities, decision, source, rate, count):
    caps = [capabilities[key] for key in decision["capability_ids"]
            if capabilities[key]["name"] == "protected_regions"]
    require(bool(caps), "protection_missing", "Visual render requires measured protected regions")
    proof = _read_receipt(caps[0])
    require(proof.get("kind") == "protected_regions", "receipt_kind", "Invalid protection receipt")
    require(Fraction(proof["fps"]) == rate and proof["frame_count"] == count,
            "receipt_clock", "Protected regions use a different frame clock")
    boxes = {}
    first, last = _frames(decision["interval"], rate, count)
    for index in range(first, last):
        regions = proof["frames"].get(str(index))
        require(isinstance(regions, list), "protection_gap", "Protected regions are unknown for a rendered frame", str(index))
        for box in regions:
            require(isinstance(box, list) and len(box) == 4, "protection_box", "Invalid protected box")
            for x in box:
                number(x, "protected coordinate", minimum=0, maximum=1)
            require(box[0] < box[2] and box[1] < box[3], "protection_box", "Empty protected box")
        boxes[index] = regions
    return boxes


def _bound_file(receipt, path):
    bound = [entry for entry in receipt.get("files", []) if Path(entry["path"]).resolve() == Path(path).resolve()]
    require(len(bound) == 1, "unbound_resource", "Opened resource must appear exactly once in the hashed file manifest")
    verify_file(str(path), bound[0]["sha256"], "bound native resource")


def _matte(capability, first, last, resolution, rate, count):
    receipt = _read_receipt(capability)
    require(receipt.get("kind") == "subject_mask", "receipt_kind", "Expected a subject mask receipt")
    require(Fraction(receipt["fps"]) == rate and receipt["frame_count"] == count,
            "matte_clock", "Mask receipt uses a different source frame clock")
    directory = Path(receipt["directory"])
    for index in range(first, last):
        path = directory / f"{index:06d}.png"
        require(str(index) in receipt["frame_sha256"], "matte_gap", "Mask hash is missing", str(index))
        verify_file(str(path), receipt["frame_sha256"][str(index)], "subject_mask")
        alpha = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        require(alpha is not None and alpha.shape[::-1] == resolution,
                "matte_dimensions", "Mask must match source pixels exactly", str(index))
    return directory


def _pose(capability, rate, count):
    receipt = _read_receipt(capability)
    require(receipt.get("kind") == "pose", "receipt_kind", "Expected a pose receipt")
    _bound_file(receipt, receipt["path"])
    pose = json.loads(Path(receipt["path"]).read_text(encoding="utf-8"))
    require(pose["source_sha256"] == capability["source_sha256"] and Fraction(str(pose["fps"])) == rate
            and len(pose["frames"]) == count, "pose_clock", "Pose source or clock changed")
    return pose


def _safe_quad(corners, protected, *, expansion=1.0):
    from visual_fidelity.adaptive_template import overlap
    center = corners.mean(axis=0)
    envelope = center + (corners - center) * expansion
    require(bool(np.all(envelope >= 0) and np.all(envelope <= 1)),
            "outside_picture", "Effect animation would leave the picture")
    require(not any(overlap(envelope, box) for box in protected),
            "protected_overlap", "Effect would cover a measured face or hand")


def render_bundle(bundle: dict, output: str | Path, *, font: str | Path | None = None,
                  script_font: str | Path | None = None, style: dict | None = None) -> dict:
    from visual_fidelity.body_depth import hand_track, orbit_track, verify_orbit
    from visual_fidelity.reference_cadence import video_clock
    from visual_fidelity.video_anchor import Prepared, render, screen_quad, quad

    require(bundle.get("schema") == BUNDLE_SCHEMA, "bundle_schema", "Unsupported contextual edit bundle")
    analysis, catalog, plan = bundle["analysis"], bundle["catalog"], bundle["plan"]
    validation = validate_plan(plan, analysis, catalog, verify_files=True)
    require(validation["executable_now"] and plan["validation"]["executable"],
            "plan_not_executable", "Every event needs an eligible explicit decision before rendering")
    require(len(analysis["sources"]) == 1, "native_scope", "Native adapter currently renders one unchanged source clock")
    source = analysis["sources"][0]
    source_path = Path(source["path"]).resolve()
    output = Path(output).resolve()
    require(output != source_path and not output.exists(), "output_exists", "Choose a new output; source and existing renders are immutable")
    capabilities = index_by_id(analysis["capabilities"], "capabilities")
    # Also protect all bound resources, not only the picture, against overwrite.
    resources = {Path(cap["verification"]["artifact_path"]).resolve()
                 for cap in capabilities.values() if cap["status"] == "verified"}
    require(output not in resources, "output_resource", "Output cannot overwrite an analysis resource")
    rate, count = video_clock(source_path)
    require(rate == Fraction(source["fps"]) and count == source["frame_count"],
            "source_clock", "Source clock no longer matches the analysis")
    reader = cv2.VideoCapture(str(source_path))
    ok, image = reader.read()
    reader.release()
    require(ok, "decode", "Source video could not be decoded")
    resolution = image.shape[1::-1]
    require(all(n % 2 == 0 for n in resolution), "dimensions", "Native H.264 adapter requires even source dimensions")
    style = clone(style or {"paper": [255, 247, 236], "ink": [177, 12, 25]})
    for name in ("paper", "ink"):
        color = style.get(name)
        require(isinstance(color, list) and len(color) == 3 and
                all(type(v) is int and 0 <= v <= 255 for v in color), "style", "Style colors must be RGB bytes")
    needs_font = any(d["effect_id"] in {"native.kinetic_type", "native.body_orbit"} for d in plan["decisions"])
    settings = {"style": style, "font_sha256": None, "script_font_sha256": None}
    if needs_font:
        require(font is not None and Path(font).is_file(), "font_missing", "Supply the actual chosen font for typography")
        script_font = script_font or font
        ImageFont.truetype(str(font), 24)
        ImageFont.truetype(str(script_font), 24)
        settings.update(font_sha256=file_sha256(font), script_font_sha256=file_sha256(script_font))

    layers, cues, checks = [], [], []
    expected_implementation = implementation_fingerprint()
    for decision in plan["decisions"]:
        operation = decision["operation"]
        if operation is None:
            checks.append({"decision_id": decision["id"], "status": "preserve"})
            continue
        kind = operation["operation"]
        require(operation["renderer"] == "native" and kind in OPERATIONS,
                "unsupported_renderer", "This adapter cannot execute the selected renderer", decision["id"])
        renderer_caps = [capabilities[key] for key in decision["capability_ids"]
                         if capabilities[key]["name"] == f"renderer:native:{kind}"]
        require(bool(renderer_caps), "renderer_receipt", "Missing native implementation receipt")
        runtime = _read_receipt(renderer_caps[0])
        require(runtime.get("implementation") == expected_implementation,
                "renderer_changed", "Renderer implementation changed; prepare new capabilities and replan")
        params, bindings = operation["params"], operation["bindings"]
        if kind == "sfx_spot":
            from audiovisual.semantic_audio import spot_sfx, verify_asset
            receipt = _read_receipt(capabilities[bindings["asset"]])
            require(receipt["kind"] == "audio_asset", "receipt_kind", "Expected audio asset")
            asset = receipt["asset"]
            verify_asset(asset)
            cue = {"id": decision["id"], "asset": asset, "gain_db": params.get("gain_db", -12),
                   **{k: v for k, v in params.items() if k != "sample_rate"}, "require_reviewed_anchor": True}
            spot = spot_sfx(asset, target_sample=params["target_sample"], timeline_sample_rate=48000,
                            **{k: params[k] for k in ("trim_in", "trim_out", "source_attack_sample", "negative_start_policy") if k in params},
                            require_reviewed_anchor=True)
            target = Fraction(params["target_sample"], 48000)
            require(Fraction(str(decision["interval"]["start_s"])) <= target < Fraction(str(decision["interval"]["end_s"])),
                    "audio_interval", "SFX target must lie inside the editorial decision interval")
            # The decision interval reserves the actual audible pre-roll and tail.
            start = spot["sfx"]["timeline_start_sample"]
            length = spot["sfx"]["trim_out"] - spot["sfx"]["trim_in"]
            require(start >= math.floor(Fraction(str(decision["interval"]["start_s"])) * 48000) and
                    start + length <= math.ceil(Fraction(str(decision["interval"]["end_s"])) * 48000),
                    "audio_coverage", "SFX audible extent exceeds the reserved decision interval")
            cues.append(cue)
            checks.append({"decision_id": decision["id"], "status": "audio_preflight", "spot": spot})
            continue

        first, last = _frames(decision["interval"], rate, count)
        protected = _protected(capabilities, decision, source, rate, count)
        bounds = decision["proposal"].get("region", [0, 0, 1, 1])
        x, y, w, h = bounds
        effect = {"id": decision["id"], "animation": params.get("animation", "hold"),
                  "entrance_seconds": params.get("entrance_seconds", .23)}
        motion_layer = None
        if kind in {"motion_layer", "motion_behind"}:
            from .motion_assets import load_layer, placement, inspect_placement
            receipt = _read_receipt(capabilities[bindings["asset"]])
            require(receipt.get("kind") == "motion_asset", "receipt_kind", "Expected a prepared motion asset")
            _bound_file(receipt, receipt["path"])
            motion_layer = load_layer(receipt["path"])
            frame_map = placement(motion_layer, source_sha256=source["sha256"], fps=rate, frame_count=count,
                                  first=first, last=last, asset_start_frame=params.get("asset_start_frame", 0))
            effect["motion_frames"] = frame_map
        art_w, art_h = w, h
        center = (x + w / 2, y + h / 2)
        # region reserves the full animated envelope, not just the final pose.
        if effect["animation"] == "pop":
            art_w, art_h = w / 1.1, h / 1.1
        elif effect["animation"] == "slide":
            art_h = h / 1.27
            center = (x + w / 2, y + art_h / 2)
        if kind == "kinetic_type":
            # Existing lettering is authored at 900x210. Fit, never stretch it.
            aspect = 900 / 210
            pixel_w = min(w * resolution[0], h * resolution[1] * aspect)
            art_w, art_h = pixel_w / resolution[0], pixel_w / aspect / resolution[1]
        elif motion_layer is not None:
            aspect = motion_layer["width"] / motion_layer["height"]
            pixel_w = min(art_w * resolution[0], art_h * resolution[1] * aspect)
            art_w, art_h = pixel_w / resolution[0], pixel_w / aspect / resolution[1]
        corners = {i: screen_quad(center, (art_w, art_h)) for i in range(first, last)}
        pixel_size = (max(4, round(art_w * resolution[0])), max(4, round(art_h * resolution[1])))
        mode, evidence = "screen", []
        if kind in {"body_orbit", "hand_accent"}:
            require(bounds == [0, 0, 1, 1], "spatial_reservation", "Body and hand compositors must reserve the full frame for their channel")
            anchor_cap = capabilities[operation["anchor"]["capability_id"]]
            pose = _pose(anchor_cap, rate, count)
            matte = _matte(capabilities[bindings["matte"]], first, last, resolution, rate, count)
            cuts = runtime.get("cut_candidates", [])
            require(not any(first < cut < last for cut in cuts), "tracking_cut", "Spatial effect crosses a candidate shot cut")
            if kind == "body_orbit":
                track = orbit_track(pose, protected, first, last, matte)
                require(len(track) == last - first, "orbit_unavailable", "Measured scene cannot support the requested orbit over every frame")
                evidence = verify_orbit(track, resolution, matte, params["title"], str(font), tuple(style["ink"]), float(rate))
                require(bool(evidence), "orbit_passes", "Orbit did not demonstrate front/rear visibility and occlusion")
                effect["body_depth"] = {"kind": "orbit", "title": params["title"], "font": str(font),
                                        "mattes": str(matte), "ink": style["ink"]}
                mode = "body_orbit"
            else:
                track = hand_track(pose, protected, params["side"], first, last)
                require(set(track) == set(range(first, last)), "hand_gap", "Hand tracking does not cover every requested frame")
                effect["body_depth"] = {"kind": "hand_track", "mattes": str(matte), "ink": style["ink"]}
                mode = "hand_track"
            corners, pixel_size = track, resolution
        else:
            if kind in {"projected_asset", "projected_behind"}:
                receipt = _read_receipt(capabilities[operation["anchor"]["capability_id"]])
                require(receipt.get("kind") == "planar_tracking", "receipt_kind", "Expected measured planar quads")
                require(Fraction(receipt["fps"]) == rate and receipt["frame_count"] == count,
                        "projection_clock", "Planar quads use a different clock")
                require(not any(first < cut < last for cut in runtime.get("cut_candidates", [])),
                        "tracking_cut", "Projection crosses a candidate shot cut")
                corners = {i: quad(receipt["quads"][str(i)]) for i in range(first, last)}
                mode = "planar"
                effect["shutter_fraction"] = params.get("shutter_fraction", 0)
            if kind in {"behind_subject", "motion_behind", "projected_behind"}:
                matte = _matte(capabilities[bindings["matte"]], first, last, resolution, rate, count)
                effect["occlusion"] = str(matte)
            from visual_fidelity.anchor_graphics import motion
            speed = max(1, round(effect["entrance_seconds"] * rate))
            for index, points in corners.items():
                visible_points, opacity = motion(points, (index - first + 1) / speed, effect["animation"], fit_inside=mode == "screen")
                if opacity > 0:
                    require(bool(np.all(visible_points.min(axis=0) >= np.array([x, y]) - 1e-6) and
                                 np.all(visible_points.max(axis=0) <= np.array([x + w, y + h]) + 1e-6)),
                            "region_coverage", "Animated/tracked effect exceeds its reserved region")
                    if motion_layer is not None:
                        mask = (cv2.imread(str(matte / f"{index:06d}.png"), cv2.IMREAD_GRAYSCALE)
                                if kind == "motion_behind" else None)
                        evidence.append(inspect_placement(frame_map[index], visible_points, resolution,
                            protected[index], opacity=opacity, matte=mask,
                            min_visible=params.get("min_visible_fraction", 0),
                            min_glyph_visible=params.get("min_glyph_visible_fraction")))
                    elif kind not in {"behind_subject", "projected_behind"}:
                        _safe_quad(visible_points, protected[index])
            if kind == "kinetic_type":
                require(bool(params["title"].strip()), "empty_title", "Typography requires a nonempty title")
                effect["editorial_scene"] = {"kind": "kinetic_type",
                    "cue": {"title": params["title"], "script": params.get("subtitle", "")},
                    "style": style, "condensed": str(font), "script": str(script_font)}
            elif motion_layer is None:
                receipt = _read_receipt(capabilities[bindings["asset"]])
                require(receipt.get("kind") == "image_asset", "receipt_kind", "Expected a prepared image asset")
                _bound_file(receipt, receipt["path"])
                with Image.open(receipt["path"]) as asset:
                    asset.verify()
                effect["asset"] = receipt["path"]
                if receipt.get("catalog_metadata", {}).get("provenance", {}).get("method") == "host_generated_png":
                    effect["fit_asset"] = True
                    if mode == "planar":
                        # The projected corners describe the PNG canvas itself.
                        with Image.open(receipt["path"]) as png:
                            width, height = png.size
                        scale = min(1, 1024 / max(width, height))
                        pixel_size = (max(4, round(width * scale)), max(4, round(height * scale)))
            if motion_layer is not None:
                require(any(row["visible_alpha_sum"] > 1 for row in evidence), "motion_invisible",
                        "The selected motion is invisible for the entire interval; revise the decision")
        effect["native_operation"] = kind
        consumed = ({key: capabilities[cap_id]["verification"]["artifact_sha256"]
                     for key, cap_id in bindings.items()} if bindings else {})
        layers.append(Prepared(effect, first, last, corners, {}, {"mode": mode}, pixel_size, {}, None))
        checks.append({"decision_id": decision["id"], "status": "compiled", "frames": [first, last],
                       "coverage": len(corners), "mode": mode, "consumed_receipts": consumed,
                       "shutter_fraction": effect.get("shutter_fraction", 0),
                       "motion_frames": evidence if motion_layer is not None else None,
                       "sampled_orbit_evidence": evidence if motion_layer is None else []})

    depth_order = {"behind_subject": 0, "motion_behind": 0, "projected_behind": 0, "projected_asset": 1,
                   "overlay": 2, "motion_layer": 2, "kinetic_type": 2, "body_orbit": 3, "hand_accent": 4}
    layers.sort(key=lambda layer: (depth_order[layer.effect["native_operation"]], layer.first, layer.effect["id"]))
    require(output.suffix.lower() == (".mp4" if layers or cues else source_path.suffix.lower()),
            "output_container", "Native effects use MP4; byte-preserving output must keep the source extension")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="contextual-render-", dir=output.parent) as temporary:
        visual_output = Path(temporary) / "visual.mp4"
        if layers:
            render(source_path, visual_output, resolution, rate, layers, Path(font) if font else None, Path("/"))
        else:
            shutil.copyfile(source_path, visual_output)
        audio_report = None
        if cues:
            from .audio_render import mix_sfx
            final_output = Path(temporary) / "final.mp4"
            audio_report = mix_sfx(source_path, visual_output, final_output, cues)
        else:
            final_output = visual_output
        result_rate, result_count = video_clock(final_output)
        require(result_rate == rate and result_count == count, "render_clock", "Rendered video changed source frame clock")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(final_output), "-f", "null", "-"],
                       capture_output=True, check=True)
        verify_file(str(source_path), source["sha256"], "original source after render")
        # The final path is created only after the full render and technical checks.
        with output.open("xb") as destination, final_output.open("rb") as rendered:
            shutil.copyfileobj(rendered, destination)
    artifact = {"path": str(output), "sha256": file_sha256(output), "plan_sha256": plan["plan_sha256"],
                "duration_s": float(count / rate), "clock": "output",
                "decision_ids": [d["id"] for d in plan["decisions"]],
                "source_sha256": source["sha256"], "fps": str(rate), "frame_count": count,
                "implementation": expected_implementation, "render_settings": settings,
                "render_settings_sha256": digest(settings), "compilation": checks, "audio": audio_report,
                "technical_checks": {"decode": "pass", "source_unchanged": "pass", "clock": "pass"},
                "perceptual_review": {"motion": "unverified", "audio": "unverified", "editorial": "unverified"},
                "user_approval": "pending"}
    if audio_report is not None:
        audio_report["output_path"] = str(output)
        audio_report["intermediate_artifacts_retained"] = False
    return artifact
