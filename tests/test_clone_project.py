"""Real small-media project integration, with explicitly synthetic direction.

Fixtures exercise provenance/review gates; they do not claim aesthetic judgment,
external model execution, spoken-word recognition or user approval.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from editorial_engine import project as p
from editorial_engine.contracts import ValidationError, digest, file_sha256
from editorial_engine.project_cli import main
from test_generation_workflow import _fixture, _video


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=64x64:r=10:d=0.5",
                    "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
    return path


def spec(intent="original", video=None):
    return {"schema": p.SPEC_SCHEMA, "id": "synthetic-project", "intent": intent,
            "brief": "Test the project protocol with explicit synthetic media.",
            "inputs": [{"id": "take", "role": "footage", "media_type": "video", "path": str(video)}] if video else []}


def direction(analysis):
    author = {"kind": "human", "actor": "test fixture", "method": "Authored synthetic preservation fixture, no model inference"}
    candidates = []
    for i, event in enumerate(analysis["events"]):
        candidates.append({"id": "preserve-" + str(i), "event_id": event["id"], "effect_id": "preserve",
            "source_id": event["source_id"], "source_sha256": event["source_sha256"], "clock": "source",
            "interval": event["interval"], "evidence_ids": event["evidence_ids"], "why": "Preserve the known test raster and clock.",
            "scores": dict.fromkeys(("intent_fit", "visual_fit", "style_fit", "timing_fit"), .9),
            "score_provenance": author, "bindings": {}, "params": {}, "addresses": []})
    return {"schema_version": "1.0", "provenance": author, "evidence_annotations": [],
            "event_annotations": [{"id": e["id"], "intent": "Preserve the synthetic clock", "opportunities": []}
                                  for e in analysis["events"]],
            "proposals": {"schema_version": "1.0", "candidates": candidates},
            "limitations": ["Synthetic integration fixture; no perception or aesthetic quality claim"]}


def report(root, *, identifier="fixture-review", full=False, fail=False):
    rendered, plan = p.artifact(root, "render"), p.artifact(root, "review_plan")
    return {"id": identifier, "plan_sha256": plan["plan_sha256"], "render_sha256": rendered["sha256"],
            "clock": "output", "reviewer": {"kind": "human", "actor": "synthetic protocol fixture",
                "method": "Exercise review coverage rules; this is not a user approval or production aesthetic review."},
            "checks": {key: {"status": "fail" if fail else "pass", "mode": "continuous" if full else "metadata",
                "coverage": [{"start_s": 0, "end_s": rendered["duration_s"]}], "notes": "Synthetic protocol assertion."}
                for key in (["technical", "motion", "audio", "editorial"] if full else ["technical"])}}


def edit(root, video):
    p.create_project(root, spec("edit", video))
    p.advance_project(root)
    p.accept_direction(root, direction(p.artifact(root, "analysis:take")), kind="edit")
    p.render_project(root, kind="edit")


def generation_plan():
    plan, profile = _fixture()
    for join in plan["joins"]:
        join["strategy"] = "prompt_only"
    return plan, profile


def test_all_entry_routes_have_honest_next_actions_and_no_implicit_generation(tmp_path):
    assert len(p.ROUTES) == 11
    for intent in p.ROUTES:
        root = tmp_path / intent
        p.create_project(root, spec(intent))
        state = p.project_status(root)
        assert not state["ready_for_final_delivery"]
        assert state["work_items"]
        assert not state["artifacts"]


def test_empty_original_exports_brief_questions_and_resume_does_not_repeat_work(tmp_path):
    root = tmp_path / "project"
    p.create_project(root, spec())
    first = p.advance_project(root)
    assert any(item["code"] == "brief_needed" for item in first["work_items"])
    revision = p.load_project(root)["revision"]
    assert p.advance_project(root)["revision"] == revision
    request = p.artifact(root, "generation_request")
    assert request["model_inference_executed"] is False
    assert request["media_generation_executed"] is False


def test_actual_edit_full_review_and_delivery_preserve_sources_and_reject_overwrite(tmp_path, video):
    original = file_sha256(video)
    root = tmp_path / "project"
    edit(root, video)
    rendered = p.artifact(root, "render")
    assert rendered["sha256"] == original  # Authored preservation copies bytes.
    assert not p.project_status(root)["ready_for_final_delivery"]
    p.review_project(root, report(root))
    with pytest.raises(ValidationError, match="delivery_blocked"):
        p.deliver_project(root, tmp_path / "too-early")
    p.review_project(root, report(root, identifier="continuous-fixture", full=True))
    assert p.project_status(root)["ready_for_final_delivery"]
    state = p.deliver_project(root, tmp_path / "delivery")
    delivered = p.artifact(root, "delivery")
    assert delivered["user_approval"] == "pending"
    assert file_sha256(tmp_path / "delivery" / "final.mp4") == original
    assert file_sha256(video) == original
    assert len(list((root / "revisions").glob("*.json"))) == state["revision"]
    with pytest.raises(ValidationError, match="delivery_exists"):
        p.deliver_project(root, tmp_path / "delivery")


def test_changing_input_invalidates_downstream_without_erasing_prior_versions(tmp_path, video):
    root = tmp_path / "project"
    edit(root, video)
    before = p.load_project(root)
    snapshot = (root / "revisions" / f"{before['revision']:06d}.json").read_bytes()
    replacement = _video(tmp_path / "new.mp4", replacement=True)
    changed = deepcopy(before["spec"])
    changed["inputs"][0].update(path=str(replacement), sha256=file_sha256(replacement))
    p.update_project(root, changed, reason="Explicit new take")
    status = p.project_status(root)
    for key in ("analysis:take", "edit_request", "edit_bundle", "render", "review"):
        assert status["artifacts"][key]["status"] == "stale"
    assert (root / "revisions" / f"{before['revision']:06d}.json").read_bytes() == snapshot
    with pytest.raises(ValidationError, match="artifact_needed"):
        p.render_project(root, kind="edit")


def test_actual_returned_clips_assemble_and_plan_revision_invalidates_only_affected_clip(tmp_path, video):
    root = tmp_path / "project"
    p.create_project(root, spec("returned_clips"))
    plan, profile = generation_plan()
    p.accept_direction(root, plan, kind="generation")
    p.export_prompts(root, profile=profile, ready=True)
    for clip in plan["clips"]:
        p.receive_clip(root, clip["id"], video)
    p.plan_assembly(root, fps="10", width=64, height=64, audio="none")
    p.render_project(root, kind="assembly")
    rendered = p.artifact(root, "render")
    assert rendered["frame_count"] == 15
    assert rendered["duration_s"] == 1.5
    assert not p.artifact(root, "review")["can_finalize"]
    revised = deepcopy(plan)
    revised["revision"] = 2
    revised["clips"][0]["purpose"] = "An explicitly revised opening purpose."
    p.accept_direction(root, revised, kind="generation")
    status = p.project_status(root)
    assert status["artifacts"]["return:clip-1"]["status"] == "stale"
    assert status["artifacts"]["return:clip-2"]["status"] == "current"
    assert status["artifacts"]["return:clip-3"]["status"] == "current"
    assert status["artifacts"]["render"]["status"] == "stale"


def test_assembly_to_contextual_finishing_has_no_dependency_cycle(tmp_path, video):
    root = tmp_path / "project"
    p.create_project(root, spec("returned_clips"))
    plan, _ = generation_plan()
    p.accept_direction(root, plan, kind="generation")
    for clip in plan["clips"]:
        p.receive_clip(root, clip["id"], video)
    p.plan_assembly(root, fps="10", width=64, height=64, audio="none")
    p.render_project(root, kind="assembly")
    p.prepare_render(root)
    p.request_direction(root, kind="edit", input_id="film")
    p.accept_direction(root, direction(p.artifact(root, "analysis:film")), kind="edit")
    p.render_project(root, kind="edit")
    status = p.project_status(root)
    for key in ("render_base", "analysis:film", "edit_bundle", "render", "review"):
        assert status["artifacts"][key]["status"] == "current"
    assert p.artifact(root, "review")["archived_reviews"]
    assert not status["ready_for_final_delivery"]
    # Reusing live stage names for a second finishing pass must snapshot the DAG.
    p.prepare_render(root)
    p.request_direction(root, kind="edit", input_id="film")
    p.accept_direction(root, direction(p.artifact(root, "analysis:film")), kind="edit")
    p.render_project(root, kind="edit")
    assert p.project_status(root)["artifacts"]["render"]["status"] == "current"


def test_production_request_export_import_and_asset_adoption_are_separate(tmp_path):
    root = tmp_path / "project"
    p.create_project(root, spec())
    plan, _ = generation_plan()
    plan["assets"] = [{"id": "badge", "kind": "image", "purpose": "A badge in the synthetic film.",
                       "route": "chat_image", "status": "needed", "prompt": "Draw a blue square.", "evidence_ids": [], "reference_ids": []}]
    p.accept_direction(root, plan, kind="generation")
    p.queue_missing_assets(root)
    p.produce(root, "asset-badge")
    assert p.artifact(root, "execution:asset-badge")["status"] == "awaiting_external"
    with pytest.raises(ValidationError, match="artifact_needed"):
        p.fulfill_asset(root, "badge", "asset-badge")
    image = tmp_path / "badge.png"
    Image.new("RGBA", (16, 16), "blue").save(image)
    p.receive_production(root, "asset-badge", image,
                         provenance={"actor": "PIL fixture", "method": "Actual local synthetic raster", "simulated": False})
    p.fulfill_asset(root, "badge", "asset-badge")
    received = p.artifact(root, "generation_plan")
    assert received["revision"] == 2
    assert received["assets"][0]["status"] == "ready"
    assert received["assets"][0]["sha256"] == file_sha256(image)


def test_simulated_provider_resource_cannot_satisfy_a_real_need(tmp_path):
    root = tmp_path / "project"
    p.create_project(root, spec())
    plan, _ = generation_plan()
    plan["assets"] = [{"id": "badge", "kind": "image", "purpose": "Synthetic fixture.",
                       "route": "chat_image", "status": "needed", "prompt": "Blue.", "evidence_ids": [], "reference_ids": []}]
    p.accept_direction(root, plan, kind="generation")
    p.queue_missing_assets(root)
    image = tmp_path / "simulated.png"
    Image.new("RGB", (16, 16), "blue").save(image)
    p.receive_production(root, "asset-badge", image,
                         provenance={"actor": "fake-provider", "method": "Simulated transport", "simulated": True})
    with pytest.raises(ValidationError, match="simulated_resource"):
        p.fulfill_asset(root, "badge", "asset-badge")


def test_reference_keep_replace_contract_enters_edit_request(tmp_path, video):
    root = tmp_path / "project"
    value = spec("style_transfer", video)
    value["inputs"].append({"id": "reference", "role": "reference", "media_type": "video", "path": str(video)})
    p.create_project(root, value)
    p.advance_project(root)
    analysis = p.artifact(root, "analysis:reference")
    frame = next(e for e in analysis["evidence"] if e["id"] == "frame:0")
    author = {"kind": "human", "actor": "test fixture", "method": "Known raster input, no model inference"}
    observation = {"id": "color", "aspect": "color", "description": "Known blue fixture.",
                   "source_id": frame["source_id"], "source_sha256": frame["source_sha256"],
                   "clock": "source", "interval": frame["interval"], "evidence_ids": ["frame:0"],
                   "scope": "sampled_frames", "provenance": author, "confidence": 1}
    p.describe_reference(root, "reference", [observation], author=author)
    dossier = p.artifact(root, "dossier:reference")
    p.adapt_reference(root, "reference", {"schema": "reference-adaptation/1", "id": "adapt", "revision": 1,
        "dossier_sha256": dossier["dossier_sha256"], "author": author,
        "decisions": [{"observation_id": "color", "action": "replace", "target": "A red object.",
                       "rationale": "Explicit fixture replacement."}], "replacement_references": []})
    p.request_direction(root, kind="edit", input_id="take", reference_id="reference")
    request = p.artifact(root, "edit_request")
    payload = json.loads(request["body"]["messages"][1]["content"][0]["text"])
    assert "A red object." in json.dumps(payload["reference_profile"])
    assert not request["model_inference_executed"]


def test_changed_render_bytes_block_delivery_and_fork_retains_prior_review(tmp_path, video):
    root = tmp_path / "project"
    edit(root, video)
    p.review_project(root, report(root, full=True))
    fork = tmp_path / "branch"
    p.fork_project(fork, root)
    assert p.artifact(fork, "review")["review_sha256"] == p.artifact(root, "review")["review_sha256"]
    rendered = p.artifact(root, "render")
    with Path(rendered["path"]).open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValidationError, match="file_hash_mismatch"):
        p.deliver_project(fork, tmp_path / "bad-delivery")


def test_cli_init_advance_status_use_same_persistent_project(tmp_path, capsys):
    source = tmp_path / "spec.json"
    source.write_text(json.dumps(spec()))
    root = tmp_path / "cli-project"
    assert main(["init", str(root), str(source)]) == 0
    assert main(["advance", str(root)]) == 0
    assert main(["status", str(root)]) == 0
    assert p.load_project(root)["revision"] == 2
    assert "brief_needed" in capsys.readouterr().out


def test_reference_route_and_manual_brief_cannot_be_bypassed(tmp_path, video):
    root = tmp_path / "reference-project"
    value = spec("reference_generate")
    value["inputs"] = [{"id": "ref", "role": "reference", "media_type": "video", "path": str(video)}]
    p.create_project(root, value)
    plan, _ = generation_plan()
    with pytest.raises(ValidationError, match="generation_request_needed"):
        p.accept_direction(root, plan, kind="generation")
    manual = tmp_path / "manual-project"
    value = spec()
    value["generation_answers"] = {"clip_count": 2, "clip_duration_s": .75}
    p.create_project(manual, value)
    with pytest.raises(ValidationError):
        p.accept_direction(manual, plan, kind="generation")


def test_corrupted_previous_plan_cannot_forge_revision_sequence(tmp_path):
    root = tmp_path / "project"
    p.create_project(root, spec())
    plan, _ = generation_plan()
    state = p.accept_direction(root, plan, kind="generation")
    path = Path(state["artifacts"]["generation_plan"]["path"])
    changed = deepcopy(plan)
    changed["revision"] = 40
    path.write_text(json.dumps(changed))
    changed["revision"] = 41
    with pytest.raises(ValidationError, match="file_hash_mismatch"):
        p.accept_direction(root, changed, kind="generation")


def test_template_manual_return_uses_the_instantiated_task_and_never_its_bootstrap(tmp_path):
    from test_production import template_library, template_callback
    needed, marker, _ = template_library(tmp_path)
    root = tmp_path / "project"
    p.create_project(root, spec())
    p.queue_production(root, needed)
    p.produce(root, needed["id"])
    staged = p.artifact(root, "execution:" + needed["id"])
    assert staged["status"] == "instantiated_not_rendered"
    instance = json.loads(Path(staged["template_instance"]["path"]).read_text())
    external = tmp_path / "external-output"
    external.mkdir()
    returned = template_callback({"template_instance": instance, "output_dir": str(external)})
    p.receive_production(root, needed["id"], returned["artifact_path"], provenance={"actor": "local fixture renderer",
        "method": "Executed original RGBA fixture frames locally; no external provider", "simulated": False})
    assert p.artifact(root, "result:" + needed["id"])["kind"] == "motion_layer"
    assert not marker.exists()
    p.adopt_production(root, needed["id"], input_id="authored-layer", role="resource", purpose="Actual motion output")
    assert p.load_project(root)["spec"]["inputs"][0]["path"].endswith("motion-layer.json")


def test_post_completion_requires_its_own_continuous_review_and_two_finishes_work(tmp_path, video):
    root = tmp_path / "project"
    p.create_project(root, spec("montage", video))
    pending = {"id": "title", "kind": "text", "status": "pending", "timeline_interval": {"start_s": 0, "end_s": .5}}
    assembly = {"schema": "video-assembly/1", "id": "pending-film", "revision": 1,
        "sources": [{"id": "source", "path": str(video), "sha256": file_sha256(video)}],
        "clips": [{"id": "clip", "source_id": "source", "use": {"start_s": 0, "end_s": .5},
                   "fit": "reject", "reframe_fps": "reject", "audio": {"mode": "silence", "gain_db": 0}}],
        "joins": [], "output": {"fps": "10", "width": 64, "height": 64,
            "audio": {"mode": "none", "sample_rate": 48000, "channels": 2, "missing": "silence"}}, "pending_post": [pending]}
    p.plan_assembly(root, assembly)
    p.render_project(root, kind="assembly")
    external = _video(tmp_path / "finished.mp4")
    origin = {"kind": "human", "actor": "test fixture", "method": "Synthetic external finishing protocol, not a typography claim"}
    p.import_finished_video(root, external, provenance=origin)
    p.import_finished_video(root, external, provenance=origin)
    # Second identical finishing return cannot claim it applied pending work.
    assert not p.project_status(root)["ready_for_final_delivery"]
    p.import_finished_video(root, video, provenance=origin)
    finished = p.artifact(root, "render")
    post_id = p.pending_post_items(finished)[0]["id"]
    p.review_project(root, report(root, full=True))
    weak = report(root, identifier="weak")
    weak["post_resolutions"] = [{"id": post_id, "status": "resolved", "notes": "Only metadata checked."}]
    with pytest.raises(ValidationError, match="post_review_scope"):
        p.review_project(root, weak)
    assert not p.project_status(root)["ready_for_final_delivery"]
    complete = report(root, identifier="resolved", full=True)
    complete["post_resolutions"] = [{"id": post_id, "status": "resolved", "notes": "Synthetic protocol assertion, not production approval."}]
    p.review_project(root, complete)
    assert p.project_status(root)["ready_for_final_delivery"]
