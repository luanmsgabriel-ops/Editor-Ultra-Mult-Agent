"""Measure an element, fit reusable curves, bind them to render and compare geometry."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    measure = commands.add_parser("measure", help="Track explicit element ROIs with LK and robust similarity fitting")
    measure.add_argument("video", type=Path)
    measure.add_argument("spec", type=Path)
    measure.add_argument("output", type=Path)
    quads = commands.add_parser("import-quads", help="Convert ordered measured quads to similarity observations; reject incompatible perspective")
    quads.add_argument("source", type=Path, help="JSON containing source clock/raster/hash metadata, or an observations JSON with a source member")
    quads.add_argument("spec", type=Path)
    quads.add_argument("output", type=Path)
    fit = commands.add_parser("fit", help="Fit position, log-scale and unwrapped rotation on the source PTS clock")
    fit.add_argument("observations", type=Path)
    fit.add_argument("output", type=Path)
    fit.add_argument("--method", choices=("pchip", "linear"), default="pchip")
    fit.add_argument("--min-confidence", type=float)
    fit.add_argument("--max-gap-frames", type=int, default=1,
                     help="Maximum frame gap allowed within a continuous interpolation segment (default 1)")
    inspect = commands.add_parser("inspect", help="Export separate translation, zoom and rotation metrics")
    inspect.add_argument("profile", type=Path)
    inspect.add_argument("output", type=Path)
    inspect.add_argument("--csv", type=Path)
    inspect.add_argument("--subsamples", type=int, default=4)
    compare = commands.add_parser("compare", help="Compare profiles on the same explicitly aligned clock, without DTW")
    compare.add_argument("reference", type=Path)
    compare.add_argument("candidate", type=Path)
    compare.add_argument("output", type=Path)
    compare.add_argument("--spec", type=Path)
    bind = commands.add_parser("bind", help="Bind measured motion to a geometric timeline")
    bind.add_argument("timeline", type=Path)
    bind.add_argument("profile", type=Path)
    bind.add_argument("bindings", type=Path)
    bind.add_argument("output", type=Path)
    bind.add_argument("--render", type=Path)
    args = parser.parse_args(argv)
    inputs = [getattr(args, key, None) for key in ("video", "source", "spec", "observations", "profile", "reference", "candidate", "timeline", "bindings")]
    outputs = [args.output, getattr(args, "csv", None), getattr(args, "render", None)]
    if getattr(args, "render", None) is not None:
        outputs.extend([args.render.with_suffix(".json"),
                        args.render.with_name(args.render.stem + "-silent.mp4")])
    inputs = {p.resolve() for p in inputs if p is not None}
    destinations = [p.resolve() for p in outputs if p is not None]
    if len(set(destinations)) != len(destinations) or inputs.intersection(destinations):
        parser.error("Use distinct paths for inputs, report, CSV and render; preserve the originals")
    if any(path.exists() for path in destinations):
        parser.error("Output paths must be new; choose a new version to preserve prior files")
    if args.command == "measure":
        from .motion_observation import measure_video
        spec = _load(args.spec)
        # Mask paths are project files, resolved relative to their specification.
        for element in spec.get("elements", []):
            if element.get("mask_path"):
                element["mask_path"] = str((args.spec.parent / element["mask_path"]).resolve())
        result = measure_video(args.video, spec)
    elif args.command == "import-quads":
        from .motion_quad_observation import observations_from_quads
        metadata = _load(args.source)
        result = observations_from_quads(metadata.get("source", metadata), _load(args.spec))
    elif args.command == "fit":
        from .motion_profile import fit_profile
        result = fit_profile(_load(args.observations), method=args.method,
                             min_confidence=args.min_confidence, max_gap_frames=args.max_gap_frames)
    elif args.command == "inspect":
        from .motion_compare import audit_profile
        result, rows = audit_profile(_load(args.profile), subsamples=args.subsamples)
        if args.csv:
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            with args.csv.open("w", newline="", encoding="utf-8") as handle:
                if rows:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader(); writer.writerows(rows)
    elif args.command == "compare":
        from .motion_compare import compare_profiles
        result = compare_profiles(_load(args.reference), _load(args.candidate),
                                  None if args.spec is None else _load(args.spec))
    else:
        from .motion_binding import bind_timeline_motion
        from .edit_contract import validate_edit
        if args.output.resolve().parent != args.timeline.resolve().parent:
            parser.error("The output timeline must share the input directory to preserve media paths")
        result = bind_timeline_motion(_load(args.timeline), _load(args.profile), _load(args.bindings))
        validate_edit(result, args.output.parent)
    _save(args.output, result)
    if args.command == "bind" and args.render:
        from .geometric_video import render
        render(args.output, args.render)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
