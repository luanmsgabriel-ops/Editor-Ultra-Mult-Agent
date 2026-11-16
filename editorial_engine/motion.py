"""Run pinned motion backends and export assets for contextual editing.

No model downloads, paid services or creative decisions run implicitly. The
director authors a recipe; this CLI renders and records actual outputs. Use
the resulting inventory with `editorial_engine prepare --assets`.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys

from .contracts import ValidationError, clone, digest, file_sha256, require
from .motion_assets import load_layer, write_layer_manifest
from .motion_guidance import motion_guidance


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def probe_backends() -> dict:
    result = {"schema": "motion-backends/1", "backends": {}, "model_downloads": False,
              "paid_calls": False, "perceptual_validation": "not_performed"}
    for name, function in (("openkatana", "probe_openkatana"), ("motionlab", "probe"),
                           ("motngrfx", "probe_motngrfx")):
        try:
            module = importlib.import_module("editorial_engine." + name)
            result["backends"][name] = getattr(module, function)()
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            result["backends"][name] = {"available": False, "reason": str(error), "render_executed": False}
    return result


def export_contextual_asset(result: dict, output_dir: str | Path, *, backend: str,
                            asset_id: str = "authored-motion", description: str | None = None,
                            executed_here: bool = False) -> dict:
    """Register an executed producer's actual sequence, not a promised capability."""
    frames = result.get("frames")
    require(isinstance(frames, list) and bool(frames), "motion_export", "Backend did not return an actual frame sequence")
    require(result.get("alpha") == "straight", "motion_alpha", "Producer must explicitly declare straight alpha")
    require(result.get("frame_count") == len(frames), "motion_gap", "Producer frame count differs from its file sequence")
    readings = {row["frame"]: row["reading"] for row in result.get("metrics", [])
                if isinstance(row, dict) and "frame" in row and "reading" in row}
    frames = [{**row, **({"reading": readings[row["index"]]} if row["index"] in readings else {})} for row in frames]
    require(isinstance(asset_id, str) and bool(asset_id.strip()), "asset_id", "Motion asset needs an identifier")
    root = Path(output_dir).resolve()
    target = root / "motion-layer.json"
    manifest = write_layer_manifest(frames, target, fps=str(result["fps"]), backend=backend,
        method=("Backend executed in this call; individual files and alpha verified" if executed_here else
                "Imported producer-attested sequence; file bytes and alpha verified, producer not re-executed"),
        origin={"producer_schema": result.get("schema", result.get("schema_version")),
                "producer_version": result.get("backend_version", result.get("version")),
                "producer_sha256": digest(result), "implementation": result.get("implementation", result.get("provenance")),
                "recipe_sha256": result.get("spec_sha256", result.get("scene_sha256")),
                "execution_in_this_call": executed_here,
                "upstream_commit": result.get("upstream_commit", result.get("provenance", {}).get("upstream_commit",
                                                result.get("upstream", {}).get("commit")))},
        source_binding=result.get("source_binding"))
    require((manifest["width"], manifest["height"]) == (result.get("width"), result.get("height")),
            "motion_dimensions", "Producer raster differs from its frame files")
    inventory = {"assets": [{"id": asset_id, "kind": "motion", "path": str(target),
        "description": description or "Rendered motion layer; inspect its content and movement before assigning an editorial function.",
        "provenance": {"backend": backend, "manifest_sha256": file_sha256(target),
                       "producer_sha256": digest(result)}}]}
    if result.get("sonic_candidates") is not None:
        sonic_path = root / "sonic-candidates.json"
        _write(sonic_path, result["sonic_candidates"])
        inventory["assets"][0]["sonic_candidates"] = {"path": str(sonic_path), "sha256": file_sha256(sonic_path)}
    _write(root / "inventory.json", inventory)
    from .motion_assets import contact_sheet
    contact_sheet(manifest).save(root / "motion-contact.png")
    return {"manifest_path": str(target), "manifest_sha256": file_sha256(target),
            "inventory_path": str(root / "inventory.json"), "preview_path": str(root / "motion-contact.png"),
            "frame_count": manifest["frame_count"], "fps": manifest["fps"],
            "continuous_motion_review": False, "user_approval": "pending"}


def render_recipe(backend: str, recipe: dict, output_dir: str | Path, *, font=None,
                   font_license=None, samples=1, shutter_angle=210, project=None,
                   asset_id="authored-motion", description=None, trusted_script=False) -> dict:
    """Render a declarative recipe using an explicit backend, then register it."""
    output = Path(output_dir).resolve()
    require(not trusted_script or backend == "openkatana3d", "trusted_code",
            "Trusted scene scripts are supported only by the explicit OpenKatana 3D route")
    require(not output.exists(), "output_exists", "Use a new output directory for every motion revision")
    output.parent.mkdir(parents=True, exist_ok=True)
    producer = output / "producer"
    if backend == "motionlab":
        from .motionlab import render, sonic_candidates
        output.mkdir()
        result = render(recipe, producer / "preview.mp4", samples=samples, shutter_angle=shutter_angle)
        result["sonic_candidates"] = sonic_candidates(recipe)
    elif backend == "motngrfx":
        from .motngrfx import render_sequence
        require(font is not None and font_license is not None, "font_required", "MOTNGRFX requires a real font and its license attestation")
        output.mkdir()
        result = render_sequence(recipe, producer, font_path=font, font_license=font_license)
    elif backend in {"openkatana", "openkatana3d"}:
        from . import openkatana
        require(project is not None, "project_required", "OpenKatana needs an explicit project directory")
        output.mkdir()
        result = (openkatana.render_timeline(project, recipe, producer) if backend == "openkatana"
                  else openkatana.render_scene3d(project, recipe, producer, trusted_script=trusted_script))
    else:
        raise ValueError("Unknown motion backend")
    result = clone(result)
    receipt = {"schema": "motion-run/1", "backend": backend, "recipe_sha256": digest(recipe),
               "producer": result, "perceptual_review": "pending", "user_approval": "pending"}
    # A timeline render may be intentionally opaque. Register only explicitly
    # straight-alpha sequences; never invent an alpha channel for an MP4.
    if result.get("alpha") == "straight" and isinstance(result.get("frames"), list):
        receipt["contextual_asset"] = export_contextual_asset(result, output, backend=backend,
            asset_id=asset_id, description=description, executed_here=True)
    else:
        receipt["contextual_asset"] = None
        receipt["asset_export_reason"] = "Producer did not expose a straight-alpha PNG sequence; use the verified video as a standalone render."
    _write(output / "run.json", receipt)
    return receipt


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="action", required=True)
    probe = sub.add_parser("probe", help="Measure local availability; does not download models")
    probe.add_argument("--output", type=Path)
    guide = sub.add_parser("guidance", help="Write the director's motion option cards")
    guide.add_argument("--output", type=Path, required=True)
    render = sub.add_parser("render", help="Execute one authored recipe and export reusable frames")
    render.add_argument("backend", choices=("openkatana", "openkatana3d", "motionlab", "motngrfx"))
    render.add_argument("recipe", type=Path)
    render.add_argument("output", type=Path)
    render.add_argument("--font", type=Path)
    render.add_argument("--font-license")
    render.add_argument("--samples", type=int, default=1)
    render.add_argument("--shutter-angle", type=float, default=210)
    render.add_argument("--project", type=Path)
    render.add_argument("--asset-id", default="authored-motion")
    render.add_argument("--description")
    render.add_argument("--trusted-script", action="store_true",
                        help="Explicitly allow authored code in an OpenKatana 3D scene")
    blender = sub.add_parser("render-blender", help="Run the explicit local Blender bridge")
    blender.add_argument("source", type=Path, help="Existing .blend file or explicitly trusted .py script")
    blender.add_argument("output", type=Path)
    blender.add_argument("--engine", default="BLENDER_EEVEE")
    blender.add_argument("--start", type=int)
    blender.add_argument("--end", type=int)
    blender.add_argument("--trusted-script", action="store_true")
    for action in ("reference", "audio", "preview"):
        item = sub.add_parser(action, help={"reference": "Measure cuts, cadence and transitions",
            "audio": "Measure musical attacks and timing", "preview": "Render one bounded OpenKatana effect"}[action])
        item.add_argument("source", type=Path)
        item.add_argument("output", type=Path)
        item.add_argument("--start-s", type=float, default=0)
        item.add_argument("--duration-s", type=float)
        if action == "preview":
            item.add_argument("--effect", required=True)
            item.add_argument("--params", type=Path, required=True)
    evaluate = sub.add_parser("evaluate", help="Evaluate a Motion Lab scene at an absolute time")
    evaluate.add_argument("recipe", type=Path)
    evaluate.add_argument("--time-s", type=float, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    sonic = sub.add_parser("sonic-candidates", help="Derive SFX candidates from authored scene telemetry")
    sonic.add_argument("recipe", type=Path)
    sonic.add_argument("--output", type=Path, required=True)
    sonic_map = sub.add_parser("map-sonic", help="Map motion events into source audio samples without selecting an SFX")
    sonic_map.add_argument("candidates", type=Path)
    sonic_map.add_argument("source", type=Path)
    sonic_map.add_argument("--source-first-frame", type=int, required=True)
    sonic_map.add_argument("--source-last-frame", type=int)
    sonic_map.add_argument("--asset-start-frame", type=int, default=0)
    sonic_map.add_argument("--output", type=Path, required=True)
    register = sub.add_parser("register", help="Register an existing producer's verified RGBA sequence")
    register.add_argument("producer", type=Path)
    register.add_argument("output", type=Path)
    register.add_argument("--backend", required=True)
    register.add_argument("--asset-id", default="authored-motion")
    register.add_argument("--description")
    compose = sub.add_parser("composite-type", help="Apply a full-frame MOTNGRFX sequence with strict all-frame QA")
    compose.add_argument("source", type=Path)
    compose.add_argument("manifest", type=Path, help="Original MOTNGRFX producer manifest, including glyph IDs")
    compose.add_argument("output", type=Path)
    compose.add_argument("--mode", choices=("front", "behind"), default="front")
    compose.add_argument("--matte", type=Path)
    compose.add_argument("--cuts", type=int, nargs="*", default=[])
    compose.add_argument("--min-visible", type=float, default=.70)
    compose.add_argument("--min-occluded", type=float, default=0)
    compose.add_argument("--min-glyph-visible", type=float, default=.50)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "probe":
            result = probe_backends()
            if args.output:
                _write(args.output, result)
        elif args.action == "guidance":
            result = motion_guidance()
            _write(args.output, result)
        elif args.action == "render":
            result = render_recipe(args.backend, _read(args.recipe), args.output, font=args.font,
                font_license=args.font_license, samples=args.samples, shutter_angle=args.shutter_angle,
                project=args.project, asset_id=args.asset_id, description=args.description,
                trusted_script=args.trusted_script)
        elif args.action == "render-blender":
            from .openkatana import render_blender
            result = render_blender(args.source, args.output, engine=args.engine,
                                    start=args.start, end=args.end, trusted_script=args.trusted_script)
        elif args.action in {"reference", "audio", "preview"}:
            from . import openkatana
            kwargs = {"start_s": args.start_s}
            if args.duration_s is not None:
                kwargs["duration_s"] = args.duration_s
            if args.action == "preview":
                result = openkatana.preview_effect(args.source, args.output, effect=args.effect,
                                                   params=_read(args.params), **kwargs)
            else:
                function = openkatana.analyze_reference if args.action == "reference" else openkatana.analyze_audio
                result = function(args.source, args.output, **kwargs)
        elif args.action in {"evaluate", "sonic-candidates"}:
            from . import motionlab
            scene = _read(args.recipe)
            result = motionlab.evaluate(scene, args.time_s) if args.action == "evaluate" else motionlab.sonic_candidates(scene)
            _write(args.output, result)
        elif args.action == "register":
            require(not args.output.exists(), "output_exists", "Use a new registration directory")
            result = export_contextual_asset(_read(args.producer), args.output, backend=args.backend,
                                              asset_id=args.asset_id, description=args.description)
        elif args.action == "map-sonic":
            from .motion_events import map_sonic_candidates
            result = map_sonic_candidates(_read(args.candidates), args.source, source_first_frame=args.source_first_frame,
                source_last_frame=args.source_last_frame, asset_start_frame=args.asset_start_frame)
            _write(args.output, result)
        else:
            from .motngrfx import render_on_video
            result = render_on_video(args.source, args.output, args.manifest, mode=args.mode,
                                     matte=args.matte, cut_frames=args.cuts, min_visible=args.min_visible,
                                     min_occluded=args.min_occluded, min_glyph_visible=args.min_glyph_visible)
        # Keep large per-frame receipts in files, not terminal output.
        summary = {"action": args.action, "status": "completed"}
        if args.action == "probe":
            summary["availability"] = result
        else:
            summary["output"] = str(args.output)
            if isinstance(result, dict) and result.get("contextual_asset"):
                summary["contextual_asset"] = result["contextual_asset"]
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValidationError, ValueError, OSError, RuntimeError, KeyError, ImportError) as error:
        print(json.dumps({"action": args.action, "status": "blocked",
                          "issues": error.issues if isinstance(error, ValidationError) else [{"message": str(error)}]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
