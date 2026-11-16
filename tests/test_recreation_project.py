"""Project/generation integration for independent performer recreation.

Synthetic calibration video tests orchestration and byte/clock contracts only;
it does not establish an actual identity change or audiovisual acceptance.
"""

from copy import deepcopy
import json
import subprocess

from PIL import Image
import pytest

from editorial_engine import project as p
from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine.generation.contracts import clip_fingerprint
from editorial_engine.generation.prompts import compile_pack
from editorial_engine.production import production_request, validate_request
from editorial_engine.project_cli import main
from editorial_engine.recreation import build_plan
from test_generation_workflow import _fixture, _video
from test_recreation import spec as recreation_spec, media


def _project(tmp_path, *, intent="original", recreation=True, same_footage=False):
    reference = _video(tmp_path / "reference.mp4")
    directed, profile = _fixture()
    for join in directed["joins"]:
        join["strategy"] = "prompt_only"
    independent = recreation_spec()
    independent["reference"].update(id="reference", path=str(reference), sha256=file_sha256(reference))
    independent["clock"] = {"width": 64, "height": 64, "fps": "10/1", "frame_count": 15}
    independent["performance"][0]["end_frame"] = 15
    independent["transformation"]["intervals"] = [{"start_frame": 0, "end_frame": 15}]
    target = independent["target_character"]
    directed["bible"]["characters"] = [{**target, "wardrobe": "Authored fixture costume.", "voice": "None.", "invariants": []}]
    for clip in directed["clips"]:
        clip["character_ids"] = [target["id"]]
    value = {"schema": p.SPEC_SCHEMA, "id": "recreation-project", "intent": intent,
             "brief": directed["brief"]["objective"], "generation_answers": deepcopy(directed["brief"]),
             "inputs": [{"id": "reference", "role": "reference", "media_type": "video", "path": str(reference)}]}
    if recreation:
        value["recreation"] = independent
    if same_footage:
        value["inputs"].append({"id": "take", "role": "footage", "media_type": "video", "path": str(reference)})
    root = tmp_path / "project"
    p.create_project(root, value)
    return root, reference, directed, profile


def _adapt(root, *, aspect="identity"):
    analysis = p.artifact(root, "analysis:reference")
    frame = next(item for item in analysis["evidence"] if item["id"] == "frame:0")
    author = {"kind": "human", "actor": "integration fixture", "method": "Declared protocol observation, not actual perception"}
    observation = {"id": "chosen-aspect", "aspect": aspect, "description": "An explicitly authored test requirement.",
                   "source_id": frame["source_id"], "source_sha256": frame["source_sha256"], "clock": "source",
                   "interval": frame["interval"], "evidence_ids": ["frame:0"], "scope": "human_note",
                   "provenance": author, "confidence": 1}
    p.describe_reference(root, "reference", [observation], author=author)
    dossier = p.artifact(root, "dossier:reference")
    p.adapt_reference(root, "reference", {"schema": "reference-adaptation/1", "id": "replacement", "revision": 1,
        "dossier_sha256": dossier["dossier_sha256"], "author": author, "replacement_references": [],
        "decisions": [{"observation_id": "chosen-aspect", "action": "replace", "target": "An original fictional adult performer.",
                       "rationale": "Exercise an explicit replacement without reusing photographic pixels."}]})


def _ready_base(tmp_path):
    path = tmp_path / "independent-base.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:size=64x64:rate=10",
                    "-frames:v", "15", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path)],
                   check=True, capture_output=True, timeout=20)
    asset = media()
    asset.update(path=str(path), sha256=file_sha256(path), fps="10/1", frame_count=15,
                 coverage=[{"start_frame": 0, "end_frame": 15, "source_start_frame": 0}])
    return asset


def _assembly(source):
    return {"schema": "video-assembly/1", "id": "single-source", "revision": 1,
            "sources": [{"id": "take", "path": str(source), "sha256": file_sha256(source)}],
            "clips": [{"id": "clip", "source_id": "take", "use": {"start_s": 0, "end_s": .5},
                       "fit": "reject", "reframe_fps": "reject", "audio": {"mode": "silence", "gain_db": 0}}],
            "joins": [], "output": {"fps": "10", "width": 64, "height": 64,
                "audio": {"mode": "none", "sample_rate": 48000, "channels": 2, "missing": "reject"}}}


def test_cli_queue_advance_and_direction_body_bind_current_recreation(tmp_path, capsys):
    root, _, directed, profile = _project(tmp_path)
    assert main(["recreation", str(root), "--queue"]) == 0
    state = p.load_project(root)
    keys = [key for key in state["artifacts"] if key.startswith("production:")]
    assert len(keys) == 3
    for key in keys:
        assert validate_request(p.artifact(root, key), verify_files=True)
    p.advance_project(root)
    _adapt(root)
    p.advance_project(root)
    plan = p.artifact(root, "recreation_plan")
    request = p.artifact(root, "generation_request")
    payload = json.loads(request["body"]["messages"][1]["content"][0]["text"])
    assert payload["recreation_context"]["plan_sha256"] == plan["plan_sha256"]
    assert payload["recreation_stage"] == "base_video"
    assert request["media_generation_executed"] is False
    p.accept_direction(root, directed, kind="generation")
    accepted = p.artifact(root, "generation_plan")
    assert accepted["recreation"]["plan"] == plan
    p.export_prompts(root, profile=profile, ready=True)
    pack = p.artifact(root, "prompt_pack")
    assert pack["status"] == "ready"
    assert all("INDEPENDENT RECREATION STAGE: base_video" in clip["prompt"] for clip in pack["clips"])
    before = clip_fingerprint(accepted, "clip-1")
    revised_spec = deepcopy(plan["spec"])
    revised_spec["alignment"]["intent"] = "Refined authored placement."
    revised = deepcopy(accepted)
    revised["recreation"]["plan"] = build_plan(revised_spec)
    assert clip_fingerprint(revised, "clip-1") != before
    assert "recreation_media_needed" in capsys.readouterr().out


def test_legacy_explicit_identity_replacement_requires_recreation_and_blocks_original_edit(tmp_path):
    root, _, _, _ = _project(tmp_path, intent="style_transfer", recreation=False, same_footage=True)
    p.advance_project(root)
    _adapt(root)
    status = p.advance_project(root)
    assert "recreation_required" in {item["code"] for item in status["work_items"]}
    with pytest.raises(ValidationError, match="recreation_required"):
        p.request_direction(root, kind="edit", input_id="take", reference_id="reference")


def test_reference_cannot_be_footage_or_edit_assembly_source_even_with_valid_new_base(tmp_path):
    root, reference, _, _ = _project(tmp_path)
    changed = deepcopy(p.load_project(root)["spec"])
    changed["inputs"].append({"id": "take", "role": "footage", "media_type": "video", "path": str(reference)})
    with pytest.raises(ValidationError, match="recreation_reference_pixels"):
        p.update_project(root, changed, reason="Exercise known-reference source rejection")
    p.plan_recreation(root, assets=[_ready_base(tmp_path)])
    p.prepare_input(root, "reference")
    with pytest.raises(ValidationError, match="recreation_(source|reference_pixels)"):
        p.request_direction(root, kind="edit", input_id="reference")
    with pytest.raises(ValidationError, match="recreation_(source|reference_pixels)"):
        p.plan_assembly(root, _assembly(reference))


@pytest.mark.parametrize("kind", ["video", "file"])
def test_production_rejects_known_reference_bytes_regardless_of_input_label(tmp_path, kind):
    root, reference, _, _ = _project(tmp_path)
    request = production_request("forbidden-input", "manual_asset", prompt="Synthetic dependency guard fixture.",
        output_kind="video", inputs=[{"id": "source", "kind": kind, "path": str(reference), "sha256": file_sha256(reference)}])
    with pytest.raises(ValidationError, match="recreation_reference_pixels"):
        p.queue_production(root, request)


def test_png_conditioning_declared_as_video_blocks_export_readiness(tmp_path):
    plan, profile = _fixture()
    image = tmp_path / "not-a-video.png"
    Image.new("RGB", (64, 64), "red").save(image)
    plan["assets"] = [{"id": "bad-video", "kind": "video", "purpose": "Exercise real media-type validation.",
                       "route": "reuse", "status": "ready", "path": str(image), "sha256": file_sha256(image),
                       "reference_ids": [], "evidence_ids": []}]
    plan["clips"][0]["conditioning"] = [{"role": "motion_video", "asset_id": "bad-video"}]
    profile["inputs"]["motion_video"] = {"supported": True, "max_count": 1, "field": "motion-video"}
    pack = compile_pack(plan, profile=profile, ready=True)
    assert pack["clips"][0]["status"] == "blocked"
    assert "media_unverified" in {issue["code"] for issue in pack["clips"][0]["issues"]}


def test_returned_independent_takes_can_be_assembled_to_produce_the_base(tmp_path):
    root, _, directed, profile = _project(tmp_path)
    p.advance_project(root)
    _adapt(root)
    p.advance_project(root)
    p.accept_direction(root, directed, kind="generation")
    p.export_prompts(root, profile=profile, ready=True)
    take = _video(tmp_path / "new-take.mp4", replacement=True)
    for clip in directed["clips"]:
        p.receive_clip(root, clip["id"], take)
    p.plan_assembly(root, fps="10", width=64, height=64, audio="none")
    assembly = p.artifact(root, "assembly_plan")
    assert all(source["sha256"] == file_sha256(take) for source in assembly["sources"])
    p.render_project(root, kind="assembly")
    assert p.artifact(root, "render")["frame_count"] == 15
    assert not p.project_status(root)["ready_for_final_delivery"]


def test_received_base_is_adopted_with_explicit_lineage_then_requeues_current_dependencies(tmp_path):
    root, reference, _, _ = _project(tmp_path)
    p.plan_recreation(root, queue=True)
    p.advance_project(root)
    _adapt(root)
    p.advance_project(root)
    before = p.load_project(root)
    request_id = next(key.split(":", 1)[1] for key, record in before["artifacts"].items()
                      if key.startswith("production:")
                      and p.artifact(root, key)["context"]["recreation_role"] == "base_video")
    base = _ready_base(tmp_path)
    p.receive_production(root, request_id, base["path"], provenance={
        "actor": "integration fixture", "method": "Actual local calibration video; no identity or quality claim", "simulated": False})
    actual_result = p.artifact(root, "result:" + request_id)
    unchanged_revision = p.load_project(root)["revision"]
    missing_lineage = deepcopy(base)
    del missing_lineage["provenance"]
    with pytest.raises(ValidationError):
        p.adopt_recreation_asset(root, request_id, missing_lineage)
    contaminated = deepcopy(base)
    contaminated["provenance"]["ancestor_sha256s"] = [file_sha256(reference)]
    with pytest.raises(ValidationError, match="recreation_reference_pixels"):
        p.adopt_recreation_asset(root, request_id, contaminated)
    assert p.load_project(root)["revision"] == unchanged_revision
    adopted = p.adopt_recreation_asset(root, request_id, base)
    snapshot_dependencies = [key.removeprefix("artifact:")
                             for key in adopted["artifacts"]["recreation_plan"]["dependencies"]
                             if key.startswith("artifact:snapshot:")]
    assert len(snapshot_dependencies) == 1
    frozen_key = snapshot_dependencies[0]
    assert p.artifact(root, frozen_key) == actual_result
    assert p.project_status(root)["artifacts"]["generation_request"]["status"] == "stale"
    assert p.artifact(root, "recreation_plan")["assets"][0]["sha256"] == file_sha256(base["path"])
    p.plan_recreation(root, queue=True)
    queued = p.load_project(root)
    requests = [p.artifact(root, key) for key, record in queued["artifacts"].items()
                if key.startswith("production:") and record["status"] == "current"]
    assert "base_video" not in {request["context"]["recreation_role"] for request in requests}
    tracking = next(request for request in requests if request["context"]["recreation_role"] == "tracking")
    assert tracking["source_binding"]["source_sha256"] == base["sha256"]
    revised_spec = deepcopy(queued["spec"])
    revised_spec["generation_answers"]["recreation_stage"] = "transformed_image_or_video"
    p.update_project(root, revised_spec, reason="Explicitly direct the transformed temporal layer after the new base")
    p.advance_project(root)
    request = p.artifact(root, "generation_request")
    payload = json.loads(request["body"]["messages"][1]["content"][0]["text"])
    assert request["recreation_stage"] == "transformed_image_or_video"
    supplied = next(asset for asset in payload["assets"] if asset.get("recreation_role") == "base_video")
    assert supplied["sha256"] == base["sha256"] and supplied["path"] == base["path"]
    assert p.artifact(root, frozen_key) == actual_result
    assert p.artifact(root, "recreation_plan")["verification"]["identity_verified"] is False
