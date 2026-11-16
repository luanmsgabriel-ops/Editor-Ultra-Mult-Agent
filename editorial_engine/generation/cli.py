"""Prepare direction, export portable prompts and inspect returned clips."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ..contracts import ValidationError, digest
from .contracts import assembly_timing, revise_plan, validate_plan


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="action", required=True)
    for name, help_text in (("brief", "Ask only unresolved production questions"),
                            ("request", "Prepare a structured direction request for the host")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("answers", type=Path)
        command.add_argument("--preferences", type=Path)
        command.add_argument("--output", type=Path, required=True)
        if name == "request":
            command.add_argument("--analysis", type=Path)
            command.add_argument("--assets", type=Path)
    check = sub.add_parser("validate", help="Validate a directed plan and its duration arithmetic")
    check.add_argument("plan", type=Path)
    check.add_argument("--verify-files", action="store_true")
    check.add_argument("--output", type=Path)
    assets = sub.add_parser("assets", help="Export missing asset briefs for the host or artist")
    assets.add_argument("plan", type=Path)
    assets.add_argument("--output", type=Path, required=True)
    export = sub.add_parser("export", help="Write a prompt pack, per-clip text and editing instructions")
    export.add_argument("plan", type=Path)
    export.add_argument("output_dir", type=Path)
    export.add_argument("--profile", type=Path, help="A dated capability profile for the exact model/mode/interface")
    export.add_argument("--returns", type=Path, help="JSON mapping of clip IDs to returned-media receipts")
    export.add_argument("--ready", action="store_true", help="Check readiness individually; blocked clips remain explicit")
    receive = sub.add_parser("import", help="Inspect an actual returned video; preserve original media")
    receive.add_argument("plan", type=Path)
    receive.add_argument("clip_id")
    receive.add_argument("video", type=Path)
    receive.add_argument("output_dir", type=Path)
    receive.add_argument("--selected-frame", type=int)
    receive.add_argument("--observation", type=Path)
    receive.add_argument("--export-pack", type=Path, help="Associate the exported clip instructions without claiming provider use")
    receipt = sub.add_parser("verify-return", help="Verify a receipt against current plan and file bytes")
    receipt.add_argument("plan", type=Path)
    receipt.add_argument("receipt", type=Path)
    receipt.add_argument("--output", type=Path)
    revision = sub.add_parser("revise", help="Record a full authored revision and invalidate affected clip dependencies")
    revision.add_argument("previous", type=Path)
    revision.add_argument("revised", type=Path)
    revision.add_argument("--output", type=Path, required=True)
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action in {"brief", "request"}:
            from .direction import briefing, build_request
            preferences = _read(args.preferences) if args.preferences else None
            if args.action == "brief":
                result = briefing(_read(args.answers), profile=preferences)
            else:
                result = build_request(_read(args.answers), profile=preferences,
                                       analysis=_read(args.analysis) if args.analysis else None,
                                       assets=_read(args.assets) if args.assets else None)
        elif args.action == "validate":
            plan = validate_plan(_read(args.plan), verify_files=args.verify_files)
            result = {"schema": "video-generation-validation/1", "status": "structurally_valid",
                      "plan_sha256": digest(plan), "assembly": assembly_timing(plan),
                      "files_checked": args.verify_files, "semantic_review": "not_performed",
                      "video_generation_executed": False}
        elif args.action == "assets":
            plan = validate_plan(_read(args.plan))
            result = {"schema": "video-generation-asset-needs/1", "plan_sha256": digest(plan),
                      "needs": [a for a in plan["assets"] if a["status"] == "needed"],
                      "host_execution_required": True, "generation_executed": False,
                      "instructions": "Create or obtain each resource through its declared route, inspect it, "
                                      "then register its actual absolute path and SHA-256 in a new plan revision."}
        elif args.action == "export":
            from .prompts import compile_pack, render_markdown
            result = compile_pack(_read(args.plan), profile=_read(args.profile) if args.profile else None,
                                  returns=_read(args.returns) if args.returns else None, ready=args.ready)
            args.output_dir.mkdir(parents=True, exist_ok=False)
            _write(args.output_dir / "prompt-pack.json", result)
            with (args.output_dir / "prompts.md").open("x", encoding="utf-8") as stream:
                stream.write(render_markdown(result))
            for index, item in enumerate(result["clips"], 1):
                # IDs are validated before filesystem use; no source-provided path is executed.
                with (args.output_dir / f"{index:02d}-{item['clip_id']}.txt").open("x", encoding="utf-8") as stream:
                    stream.write(item["prompt"] + "\n")
            print(json.dumps({"action": args.action, "output": str(args.output_dir.resolve()),
                              "status": result.get("status"),
                              "clips": [{"id": c["clip_id"], "status": c["status"]} for c in result["clips"]],
                              "generation_executed": False}, ensure_ascii=False))
            return 2 if args.ready and result.get("status") == "blocked" else 0
        elif args.action == "import":
            from .ingest import import_clip
            exported = None
            if args.export_pack:
                pack = _read(args.export_pack)
                matches = [c for c in pack.get("clips", []) if c.get("clip_id") == args.clip_id]
                if len(matches) != 1:
                    raise ValueError("Export pack must contain exactly one matching clip")
                exported = matches[0]
            result = import_clip(_read(args.plan), args.clip_id, args.video, args.output_dir,
                                 selected_frame=args.selected_frame,
                                 observation=_read(args.observation) if args.observation else None,
                                 exported_clip=exported)
            print(json.dumps({"action": args.action, "output": str(args.output_dir.resolve()),
                              "clip_id": result["clip_id"], "receipt_sha256": result["receipt_sha256"],
                              "perceptual_review": "only_as_explicitly_reported",
                              "user_approval": "pending"}, ensure_ascii=False))
            return 0
        elif args.action == "verify-return":
            from .ingest import validate_receipt
            checked = validate_receipt(_read(args.receipt), _read(args.plan), verify_files=True)
            result = {"schema": "video-generation-return-validation/1", "status": "bytes_and_binding_valid",
                      "clip_id": checked["clip_id"], "receipt_sha256": checked["receipt_sha256"],
                      "perceptual_review": "not_performed_by_validation"}
        else:
            result = revise_plan(_read(args.previous), _read(args.revised))
        if args.output:
            _write(args.output, result)
            print(json.dumps({"action": args.action, "output": str(args.output.resolve())}, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        print(json.dumps({"action": args.action, "status": "blocked",
                          "issues": error.issues if isinstance(error, ValidationError)
                          else [{"message": str(error)}]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
