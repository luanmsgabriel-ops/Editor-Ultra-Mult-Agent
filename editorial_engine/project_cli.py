"""One persistent project from input, through direction and media, to delivery."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import ValidationError
from . import project as engine


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8")) if path else None


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="action", required=True)
    sub.add_parser("routes", help="List the eleven supported entry routes")
    def command(name, help_text):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("project", type=Path)
        return item
    initialize = command("init", "Create a versioned project from an explicit specification")
    initialize.add_argument("spec", type=Path)
    update = command("update", "Revise inputs/brief and invalidate dependent artifacts")
    update.add_argument("spec", type=Path)
    update.add_argument("--reason", required=True)
    command("status", "Show current artifacts, stale dependencies and concrete next actions")
    command("advance", "Resume local preparation and export the next direction request")
    recreation = command("recreation", "Plan independent performer video, geometry and composition dependencies")
    recreation.add_argument("--assets", type=Path, help="Actual independent resources with provenance and source bindings")
    recreation.add_argument("--queue", action="store_true", help="Export typed missing production tasks without generating media")
    recreation_adopt = command("recreation-adopt", "Adopt a verified production result with performer, lineage and clock declarations")
    recreation_adopt.add_argument("request_id")
    recreation_adopt.add_argument("descriptor", type=Path)
    fork = command("fork", "Branch an existing project without modifying its sources")
    fork.add_argument("parent", type=Path)
    fork.add_argument("--id", dest="project_id")
    for name in ("prepare", "prepare-film"):
        prepare = command(name, "Prepare current video evidence for direction")
        if name == "prepare":
            prepare.add_argument("input_id")
        prepare.add_argument("--resources", type=Path, help="JSON mapping to transcript, pose, mattes, protection, projection or assets")
        prepare.add_argument("--sample-every-s", type=float, default=1.0)
    resources = command("prepare-resources", "Connect typed production results to source analysis")
    resources.add_argument("input_id")
    resources.add_argument("bindings", type=Path)
    resources.add_argument("--asset-request", action="append", dest="asset_requests")
    reference = command("reference", "Register attributed observations of the reference")
    reference.add_argument("input_id")
    reference.add_argument("observations", type=Path)
    reference.add_argument("--author", type=Path, required=True)
    reference.add_argument("--adaptation", type=Path)
    adaptation = command("adapt", "Define what to keep and replace in each observation")
    adaptation.add_argument("input_id")
    adaptation.add_argument("contract", type=Path)
    request = command("request", "Build a multimodal edit or generation direction request")
    request.add_argument("--kind", choices=["edit", "generation"], required=True)
    request.add_argument("--input", dest="input_id")
    request.add_argument("--reference", dest="reference_id")
    request.add_argument("--assets", type=Path)
    request.add_argument("--no-images", action="store_true")
    request.add_argument("--max-frames", type=int, default=24)
    request.add_argument("--template-input", dest="template_input_id")
    request.add_argument("--template-root", type=Path)
    request.add_argument("--template-id", action="append", dest="template_ids")
    direct = command("direct", "Call an explicitly configured direction endpoint once")
    direct.add_argument("--kind", choices=["edit", "generation"], required=True)
    direct.add_argument("--endpoint", required=True)
    direct.add_argument("--model", required=True)
    direct.add_argument("--api-key-env")
    plan = command("plan", "Validate and adopt an authored direction or a new generation plan revision")
    plan.add_argument("direction", type=Path)
    plan.add_argument("--kind", choices=["edit", "generation"], required=True)
    plan.add_argument("--input", dest="input_id")
    export = command("export", "Export portable per-clip prompts and pending dependencies")
    export.add_argument("--profile", type=Path)
    export.add_argument("--ready", action="store_true")
    receive = command("receive", "Import an actual externally generated clip")
    receive.add_argument("clip_id")
    receive.add_argument("video", type=Path)
    receive.add_argument("--selected-frame", type=int)
    receive.add_argument("--observation", type=Path)
    queue = command("queue", "Add a typed production request; no command is loaded from JSON")
    queue.add_argument("request", type=Path)
    command("queue-assets", "Create production work items for missing generation assets")
    produce = command("produce", "Execute a registered native adapter or export a manual task")
    produce.add_argument("request_id")
    produce.add_argument("--estimated-cost", type=float, default=0)
    resource = command("receive-resource", "Import verified image, voice, motion or tracking output")
    resource.add_argument("request_id")
    resource.add_argument("file", type=Path)
    resource.add_argument("--provenance", type=Path, required=True)
    resource.add_argument("--kind")
    resource.add_argument("--template-instance", type=Path, help="Optional JSON path/hash descriptor; defaults to the current instantiated task")
    fulfill = command("fulfill", "Adopt a real produced asset in a new generation-plan revision")
    fulfill.add_argument("asset_id")
    fulfill.add_argument("request_id")
    adopt = command("adopt", "Use a produced template, image or voice as a new concrete project input")
    adopt.add_argument("request_id")
    adopt.add_argument("input_id")
    adopt.add_argument("--role", required=True, choices=sorted(engine.INPUT_ROLES))
    adopt.add_argument("--purpose", required=True)
    assembly = command("assemble", "Validate an authored montage or derive one from current clip receipts")
    assembly.add_argument("--plan", type=Path)
    assembly.add_argument("--fps")
    assembly.add_argument("--width", type=int)
    assembly.add_argument("--height", type=int)
    assembly.add_argument("--fit", choices=["reject", "contain", "cover"], default="reject")
    assembly.add_argument("--fps-policy", choices=["reject", "resample"], default="reject")
    assembly.add_argument("--audio", choices=["source", "none"], default="source")
    assembly.add_argument("--missing-audio", choices=["reject", "silence"], default="silence")
    assembly.add_argument("--transitions", type=Path)
    assembly.add_argument("--reference", dest="reference_id")
    render = command("render", "Render the actual contextual edit or multi-source montage")
    render.add_argument("--kind", choices=["edit", "assembly"], required=True)
    render.add_argument("--font", type=Path)
    render.add_argument("--script-font", type=Path)
    render.add_argument("--style", type=Path)
    finish = command("receive-finish", "Import a completed external finishing pass on the same frame clock")
    finish.add_argument("video", type=Path)
    finish.add_argument("--provenance", type=Path, required=True)
    review = command("review", "Attach performed audiovisual review to the current film's hashes")
    review.add_argument("report", type=Path)
    patch = command("patch", "Apply a scoped contextual repair and preserve review budget/history")
    patch.add_argument("patch", type=Path)
    delivery = command("deliver", "Package verified final video, preview or prompts in a new directory")
    delivery.add_argument("output_dir", type=Path)
    delivery.add_argument("--kind", choices=["final", "preview", "prompts"], default="final")
    delivery.add_argument("--without-dependencies", action="store_true")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        action = args.action
        if action == "routes":
            print(json.dumps(engine.ROUTES, ensure_ascii=False, indent=2))
            return 0
        if action == "init":
            engine.create_project(args.project, _read(args.spec))
        elif action == "update":
            engine.update_project(args.project, _read(args.spec), reason=args.reason)
        elif action == "status":
            print(json.dumps(engine.project_status(args.project), ensure_ascii=False, indent=2))
            return 0
        elif action == "advance":
            engine.advance_project(args.project)
        elif action == "recreation":
            engine.plan_recreation(args.project, assets=_read(args.assets), queue=args.queue)
        elif action == "recreation-adopt":
            engine.adopt_recreation_asset(args.project, args.request_id, _read(args.descriptor))
        elif action == "fork":
            engine.fork_project(args.project, args.parent, project_id=args.project_id)
        elif action in {"prepare", "prepare-film"}:
            kwargs = {"resources": _read(args.resources), "sample_every_s": args.sample_every_s}
            if action == "prepare":
                engine.prepare_input(args.project, args.input_id, **kwargs)
            else:
                engine.prepare_render(args.project, **kwargs)
        elif action == "prepare-resources":
            engine.prepare_with_results(args.project, args.input_id, _read(args.bindings), asset_requests=args.asset_requests)
        elif action == "reference":
            engine.describe_reference(args.project, args.input_id, _read(args.observations),
                                      author=_read(args.author), adaptation=_read(args.adaptation))
        elif action == "adapt":
            engine.adapt_reference(args.project, args.input_id, _read(args.contract))
        elif action == "request":
            engine.request_direction(args.project, kind=args.kind, input_id=args.input_id, reference_id=args.reference_id,
                assets=_read(args.assets), include_images=not args.no_images, max_frames=args.max_frames,
                template_input_id=args.template_input_id, template_root=args.template_root, template_ids=args.template_ids)
        elif action == "direct":
            engine.direct_project(args.project, kind=args.kind, endpoint=args.endpoint, model=args.model, api_key_env=args.api_key_env)
        elif action == "plan":
            engine.accept_direction(args.project, _read(args.direction), kind=args.kind, input_id=args.input_id)
        elif action == "export":
            engine.export_prompts(args.project, profile=_read(args.profile), ready=args.ready)
        elif action == "receive":
            engine.receive_clip(args.project, args.clip_id, args.video, selected_frame=args.selected_frame, observation=_read(args.observation))
        elif action == "queue":
            engine.queue_production(args.project, _read(args.request))
        elif action == "queue-assets":
            engine.queue_missing_assets(args.project)
        elif action == "produce":
            engine.produce(args.project, args.request_id, estimated_cost=args.estimated_cost)
        elif action == "receive-resource":
            engine.receive_production(args.project, args.request_id, args.file, provenance=_read(args.provenance), kind=args.kind,
                                      template_instance=_read(args.template_instance))
        elif action == "fulfill":
            engine.fulfill_asset(args.project, args.asset_id, args.request_id)
        elif action == "adopt":
            engine.adopt_production(args.project, args.request_id, input_id=args.input_id, role=args.role, purpose=args.purpose)
        elif action == "assemble":
            engine.plan_assembly(args.project, _read(args.plan), fps=args.fps, width=args.width, height=args.height,
                fit=args.fit, fps_policy=args.fps_policy, audio=args.audio, missing_audio=args.missing_audio,
                transitions=_read(args.transitions), reference_id=args.reference_id)
        elif action == "render":
            engine.render_project(args.project, kind=args.kind, font=args.font, script_font=args.script_font, style=_read(args.style))
        elif action == "receive-finish":
            engine.import_finished_video(args.project, args.video, provenance=_read(args.provenance))
        elif action == "review":
            engine.review_project(args.project, _read(args.report))
        elif action == "patch":
            engine.patch_edit(args.project, _read(args.patch))
        elif action == "deliver":
            engine.deliver_project(args.project, args.output_dir, kind=args.kind, include_dependencies=not args.without_dependencies)
        status = engine.project_status(args.project)
        print(json.dumps({"action": action, "project": str(args.project.resolve()), "revision": status["revision"],
                          "status": status["status"], "next_actions": status["work_items"]}, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError, RuntimeError) as error:
        print(json.dumps({"action": args.action, "status": "blocked",
                          "issues": error.issues if isinstance(error, ValidationError) else [{"message": str(error)}]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
