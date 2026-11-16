"""Evidence -> explicit direction -> sealed plan -> native render -> real review."""

import argparse
import json
from pathlib import Path

from .contracts import ValidationError
from .directions import build_request, call_provider, plan_direction
from .native import native_catalog, render_bundle
from .perception import prepare_analysis, write_json
from .planner import apply_patch, validate_plan
from .review import add_review, new_review


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="action", required=True)
    catalog = sub.add_parser("catalog", help="Write manifests for implemented native adapters")
    catalog.add_argument("--output", type=Path, required=True)
    prepare = sub.add_parser("prepare", help="Extract source evidence and verified resource receipts")
    prepare.add_argument("source", type=Path)
    prepare.add_argument("work", type=Path)
    for key in ("transcript", "pose", "mattes", "protection", "projection", "assets"):
        prepare.add_argument("--" + key, type=Path)
    prepare.add_argument("--sample-every-s", type=float, default=1.)
    request = sub.add_parser("request", help="Prepare a source-grounded multimodal direction request")
    request.add_argument("analysis", type=Path)
    request.add_argument("catalog", type=Path)
    brief = request.add_mutually_exclusive_group(required=True)
    brief.add_argument("--brief")
    brief.add_argument("--brief-file", type=Path)
    request.add_argument("--reference-profile", type=Path)
    request.add_argument("--lessons", type=Path)
    request.add_argument("--no-images", action="store_true")
    request.add_argument("--max-frames", type=int, default=24)
    request.add_argument("--output", type=Path, required=True)
    direct = sub.add_parser("direct", help="Send the prepared evidence to an explicitly configured model endpoint")
    direct.add_argument("request", type=Path)
    direct.add_argument("--endpoint", required=True, help="Full compatible chat-completions URL; sends prepared samples")
    direct.add_argument("--model", required=True)
    direct.add_argument("--api-key-env")
    direct.add_argument("--output", type=Path, required=True)
    plan = sub.add_parser("plan", help="Validate semantic direction and reconcile explicit candidates")
    plan.add_argument("analysis", type=Path)
    plan.add_argument("catalog", type=Path)
    plan.add_argument("direction", type=Path)
    plan.add_argument("--plan-id", default="contextual-plan")
    plan.add_argument("--policy", type=Path)
    plan.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate", help="Validate plan identity, resources and dependencies")
    check.add_argument("bundle", type=Path)
    render = sub.add_parser("render", help="Execute selected native operations on the original source clock")
    render.add_argument("bundle", type=Path)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--font", type=Path)
    render.add_argument("--script-font", type=Path)
    render.add_argument("--style", type=Path)
    render.add_argument("--artifact", type=Path)
    review = sub.add_parser("review", help="Bind performed QA to the exact rendered file")
    review.add_argument("bundle", type=Path)
    review.add_argument("artifact", type=Path)
    review.add_argument("--state", type=Path)
    review.add_argument("--report", type=Path)
    review.add_argument("--max-retries", type=int, default=2)
    review.add_argument("--output", type=Path, required=True)
    patch = sub.add_parser("patch", help="Apply a scoped decision patch and invalidate stale review")
    patch.add_argument("bundle", type=Path)
    patch.add_argument("patch", type=Path)
    patch.add_argument("--review", type=Path, required=True)
    patch.add_argument("--output", type=Path, required=True)
    patch.add_argument("--review-output", type=Path, required=True)
    return root


def main(argv=None):
    argparser = parser()
    args = argparser.parse_args(argv)
    try:
        if args.action == "catalog":
            result = native_catalog()
        elif args.action == "prepare":
            result = prepare_analysis(args.source, args.work, **{key: getattr(args, key) for key in
                ("transcript", "pose", "mattes", "protection", "projection", "assets", "sample_every_s")})
            print(json.dumps({"analysis": str(args.work / "analysis.json"), "catalog": str(args.work / "catalog.json"),
                              "sources": len(result["sources"]), "events": len(result["events"]),
                              "semantic_status": result["preparation"]["semantic_status"]}))
            return 0
        elif args.action == "request":
            brief = args.brief if args.brief is not None else args.brief_file.read_text(encoding="utf-8")
            result = build_request(read(args.analysis), read(args.catalog), brief,
                    reference_profile=read(args.reference_profile) if args.reference_profile else None,
                    lessons=read(args.lessons) if args.lessons else None,
                    include_images=not args.no_images, max_frames=args.max_frames)
        elif args.action == "direct":
            result = call_provider(read(args.request), endpoint=args.endpoint, model=args.model, api_key_env=args.api_key_env)
        elif args.action == "plan":
            result = plan_direction(read(args.analysis), read(args.catalog), read(args.direction), plan_id=args.plan_id,
                                    policy=read(args.policy) if args.policy else None)
        elif args.action == "validate":
            bundle = read(args.bundle)
            result = validate_plan(bundle["plan"], bundle["analysis"], bundle["catalog"], verify_files=True)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        elif args.action == "render":
            artifact_path = args.artifact or args.output.with_suffix(args.output.suffix + ".artifact.json")
            if artifact_path.exists():
                raise ValueError("Use a new artifact manifest path")
            result = render_bundle(read(args.bundle), args.output, font=args.font, script_font=args.script_font,
                                   style=read(args.style) if args.style else None)
            write_json(artifact_path, result)
            print(json.dumps({"path": result["path"], "sha256": result["sha256"], "artifact": str(artifact_path),
                              "perceptual_review": result["perceptual_review"], "user_approval": "pending"}))
            return 0
        elif args.action == "review":
            bundle, artifact = read(args.bundle), read(args.artifact)
            if bool(args.state) != bool(args.report):
                raise ValueError("Provide both --state and --report to append a review; omit both to initialize")
            result = (add_review(read(args.state), bundle["plan"], artifact, read(args.report)) if args.state
                      else new_review(bundle["plan"], artifact, max_retries=args.max_retries))
        else:
            if args.output.exists() or args.review_output.exists():
                raise ValueError("Patch outputs must be new files")
            bundle = read(args.bundle)
            changed = apply_patch(bundle["plan"], read(args.patch), bundle["analysis"], bundle["catalog"], read(args.review))
            bundle["plan"] = changed["plan"]
            result = bundle
            write_json(args.review_output, changed["review"])
        write_json(args.output, result)
        print(json.dumps({"output": str(args.output), "action": args.action}, ensure_ascii=False))
        return 0
    except (ValidationError, ValueError, KeyError, OSError, RuntimeError) as error:
        print(json.dumps({"status": "blocked", "action": args.action,
                          "issues": error.issues if isinstance(error, ValidationError) else [{"message": str(error)}]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
