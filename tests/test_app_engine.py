"""Private bridge, explicit review gates and actual FFmpeg integration.

Synthetic media only: these tests prove execution and state binding, not clone
fidelity, recognition of a person, or editorial/perceptual approval.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from editorial_engine.contracts import ValidationError, file_sha256
from editor_ultra_app.engine import EngineAdapter


@pytest.fixture
def adapter(tmp_path):
    return EngineAdapter(tmp_path / "private")


@pytest.fixture
def videos(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real FFmpeg and FFprobe are required")
    result = {}
    for color in ("blue", "red", "lime"):
        path = tmp_path / (color + ".mp4")
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        f"color={color}:s=64x64:r=10:d=0.5", "-c:v", "libx264", "-threads", "1",
                        "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
        result[color] = path
    return result


def create(adapter, **state):
    return adapter.save_project(None, {"name": "QA técnico — mídia sintética, sem aprovação estética",
                                      "objective": "Explicit synthetic bridge integration.", **state}, 0)


def upload(adapter, snapshot, role, path, **kwargs):
    return adapter.import_local_file(snapshot["project_id"], role, path, path.name, "video/mp4",
                                     expected_revision=snapshot["revision"], **kwargs)


def approve(adapter, snapshot, stage="clone"):
    return adapter.record_review(snapshot["project_id"], stage, "approved", True,
                                  snapshot["state"]["assets"]["clone" if stage == "clone" else "result"][0]["id"],
                                  "Explicit synthetic protocol fixture, not a perceptual review.",
                                  expected_revision=snapshot["revision"])


def authored_preservation(analysis):
    author = {"kind": "human", "actor": "Authored bridge test", "method": "Known synthetic preservation fixture"}
    candidates = [{"id": "preserve-" + str(index), "event_id": event["id"], "effect_id": "preserve",
                   "source_id": event["source_id"], "source_sha256": event["source_sha256"], "clock": "source",
                   "interval": event["interval"], "evidence_ids": event["evidence_ids"],
                   "why": "Preserve the exact known synthetic raster and source clock.",
                   "scores": dict.fromkeys(("intent_fit", "visual_fit", "style_fit", "timing_fit"), .9),
                   "score_provenance": author, "bindings": {}, "params": {}, "addresses": []}
                  for index, event in enumerate(analysis["events"])]
    return {"schema_version": "1.0", "provenance": author, "evidence_annotations": [],
            "event_annotations": [{"id": event["id"], "intent": "Preserve the synthetic source", "opportunities": []}
                                  for event in analysis["events"]],
            "proposals": {"schema_version": "1.0", "candidates": candidates},
            "limitations": ["Technical fixture. No claim of clone reconstruction or aesthetic assessment."]}


def assembly_plan(assets):
    return {"schema": "video-assembly/1", "id": "bridge-assembly", "revision": 1,
            "sources": [{"id": "source-" + str(i), "path": "asset:" + item["id"], "sha256": item["sha256"]}
                        for i, item in enumerate(assets)],
            "clips": [{"id": "clip-" + str(i), "source_id": "source-" + str(i),
                       "use": {"start_s": 0, "end_s": .5}, "fit": "reject", "reframe_fps": "reject",
                       "audio": {"mode": "silence", "gain_db": 0}} for i in range(len(assets))],
            "joins": [{"from": "clip-" + str(i), "to": "clip-" + str(i + 1),
                       "transition": "crossfade", "duration_s": .2} for i in range(len(assets) - 1)],
            "output": {"fps": "10/1", "width": 64, "height": 64,
                       "audio": {"mode": "none", "sample_rate": 48000, "channels": 2, "missing": "reject"}}}


def test_server_owns_approvals_assets_and_revisions(adapter, videos):
    created = create(adapter, cloneApproval={"valid": True, "serverRecorded": True}, revision=999)
    assert created["revision"] == 1
    assert created["state"]["cloneApproval"] is None
    assert len(adapter.list_projects()) == 1
    assert "path" not in json.dumps(adapter.list_projects())
    with pytest.raises(ValidationError, match="revision_conflict"):
        adapter.save_project(created["project_id"], {"name": "Stale"}, 0)
    with pytest.raises(ValidationError, match="unknown_asset"):
        adapter.save_project(created["project_id"], {"assets": {"ref": [{"id": "invented", "path": "/etc/passwd"}]}}, 1)
    uploaded = upload(adapter, created, "ref", videos["blue"])
    assert uploaded["state"]["assets"]["ref"][0]["server"]
    assert "path" not in uploaded["state"]["assets"]["ref"][0]
    assert Path(uploaded["assets"][0]["path"]).is_file()  # Internal host envelope for signing.
    other = create(adapter)
    with pytest.raises(ValidationError, match="asset_missing"):
        adapter.resolve_asset(other["project_id"], uploaded["asset_id"])
    with pytest.raises(ValidationError, match="project_id"):
        adapter.get_project("../escape")


def test_real_study_and_new_footage_edit_remain_explicit(adapter, videos):
    current = upload(adapter, create(adapter), "ref", videos["blue"])
    pid = current["project_id"]
    prepared = adapter.prepare(pid, "clone", expected_revision=current["revision"])
    assert prepared["status"] == "awaiting_direction"
    assert prepared["analysis"]["events"]
    assert str(adapter.data_dir) not in json.dumps(prepared["request"])
    assert prepared["state"]["cloneApproval"] is None
    directed = adapter.apply_direction(pid, "clone", authored_preservation(prepared["analysis"]),
                                       expected_revision=prepared["revision"])
    rendered = adapter.render(pid, "clone", expected_revision=directed["revision"])
    assert rendered["preview_kind"] == "reference_study"
    assert rendered["asset"]["sha256"] == file_sha256(videos["blue"])
    assert not rendered["approval"]["clone"]
    approved = approve(adapter, rendered)
    assert approved["approval"]["clone"]["valid"]
    incoming = upload(adapter, approved, "footage", videos["red"])
    edit = adapter.prepare(pid, "edit", expected_revision=incoming["revision"])
    assert edit["analysis"]["sources"][0]["sha256"] == file_sha256(videos["red"])
    direction = adapter.apply_direction(pid, "edit", authored_preservation(edit["analysis"]), expected_revision=edit["revision"])
    output = adapter.render(pid, "edit", expected_revision=direction["revision"])
    assert output["asset"]["sha256"] == file_sha256(videos["red"])
    assert output["asset"]["sha256"] != file_sha256(videos["blue"])
    final = approve(adapter, output, "final")
    assert final["approval"]["final"]["valid"]
    revised = adapter.save_project(pid, {"objective": "A changed reference requirement."}, final["revision"])
    assert revised["state"]["cloneApproval"] is None
    assert revised["state"]["finalApproval"] is None
    with pytest.raises(ValidationError, match="stale_review"):
        adapter.record_review(pid, "clone", "approved", True, rendered["asset_id"], expected_revision=revised["revision"])
    with pytest.raises(ValidationError, match="result_missing"):
        adapter.get_result(pid)
    new_preview = upload(adapter, revised, "clone", videos["lime"])
    assert adapter.get_result(pid, "clone")["asset_id"] == new_preview["asset_id"]
    assert adapter.get_result(pid, "clone")["preview_kind"] == "externally_produced"


def test_direction_change_requires_a_new_preview(adapter, videos):
    current = upload(adapter, create(adapter), "ref", videos["blue"])
    prepared = adapter.prepare(current["project_id"], "clone")
    first = adapter.apply_direction(current["project_id"], "clone", authored_preservation(prepared["analysis"]))
    first = adapter.render(current["project_id"], "clone")
    approve(adapter, first)
    revised = authored_preservation(prepared["analysis"])
    revised["limitations"].append("An explicit revised direction must receive its own preview review.")
    changed = adapter.apply_direction(current["project_id"], "clone", revised)
    assert changed["state"]["cloneApproval"] is None
    with pytest.raises(ValidationError, match="stale_review"):
        adapter.record_review(current["project_id"], "clone", "approved", True, first["asset_id"])
    with pytest.raises(ValidationError, match="result_missing"):
        adapter.get_result(current["project_id"], "clone")


def test_actual_multi_source_render_and_reference_substitution_guard(adapter, videos):
    current = upload(adapter, create(adapter), "ref", videos["blue"])
    current = upload(adapter, current, "clone", videos["blue"])
    current = approve(adapter, current)
    current = upload(adapter, current, "footage", videos["red"])
    current = upload(adapter, current, "footage", videos["lime"])
    pid = current["project_id"]
    prepared = adapter.prepare(pid, "assembly", expected_revision=current["revision"])
    plan = assembly_plan(prepared["state"]["assets"]["footage"])
    malicious = deepcopy(plan)
    ref = prepared["state"]["assets"]["ref"][0]
    malicious["sources"][0].update(path="asset:" + ref["id"], sha256=ref["sha256"])
    with pytest.raises(ValidationError, match="assembly_source"):
        adapter.apply_direction(pid, "assembly", malicious)
    approved = adapter.apply_direction(pid, "assembly", plan, expected_revision=prepared["revision"])
    rendered = adapter.render(pid, "assembly", expected_revision=approved["revision"])
    receipt = rendered["result"]
    assert receipt["runtime_executed"] is True
    assert receipt["frame_count"] == 8
    assert receipt["duration_s"] == .8
    assert receipt["sha256"] not in {file_sha256(path) for path in videos.values()}
    path = adapter.resolve_asset(pid, rendered["asset_id"])
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
    assert len(raw) == 8 * 64 * 64 * 3
    assert raw[0] > 240 and raw[1] < 10  # Encoded red opening.
    assert raw[-2] > 240 and raw[-3] < 10  # Encoded green closing.
    assert rendered["state"]["finalApproval"] is None
    assert adapter.get_result(pid, "assembly")["asset_id"] == rendered["asset_id"]


def test_unsafe_direction_and_mislabeled_media_do_not_execute(adapter, videos, tmp_path):
    current = upload(adapter, create(adapter), "ref", videos["blue"])
    adapter.prepare(current["project_id"], "clone")
    for value in ({"command": "touch /tmp/never"}, {"path": "/etc/passwd"}, {"path": "https://example.com/media.mp4"}):
        with pytest.raises(ValidationError, match="unsafe_direction|direction_path"):
            adapter.apply_direction(current["project_id"], "clone", value)
    invalid = tmp_path / "wrong.mp4"
    invalid.write_text("not a media file")
    with pytest.raises(ValidationError, match="invalid_media"):
        upload(adapter, adapter.get_project(current["project_id"]), "footage", invalid)
    with pytest.raises(ValidationError, match="engine_kind"):
        adapter.render(current["project_id"], "generation")


def test_received_clips_invalidate_when_prompt_choices_change(adapter, videos):
    state = create(adapter, mode="generate", shots=[{"id": "shot-1", "seconds": .5, "action": "First authored shot."}])
    state = upload(adapter, state, "clone", videos["blue"])
    state = approve(adapter, state)
    state = upload(adapter, state, "shot", videos["red"], shot_id="shot-1")
    assert state["state"]["shots"][0]["returned_current"]
    changed = deepcopy(state["state"])
    changed["shots"][0]["action"] = "A new requested action."
    state = adapter.save_project(state["project_id"], changed, state["revision"])
    assert not state["state"]["shots"][0]["returned_current"]
    with pytest.raises(ValidationError, match="stale_clip"):
        adapter.prepare(state["project_id"], "assembly")


def test_explicit_confirmation_and_current_preview_are_required(adapter, videos):
    state = upload(adapter, create(adapter), "clone", videos["blue"])
    first = state["asset_id"]
    with pytest.raises(ValidationError, match="review_confirmation"):
        adapter.record_review(state["project_id"], "clone", "approved", False, first)
    state = upload(adapter, state, "clone", videos["red"])
    with pytest.raises(ValidationError, match="stale_review"):
        adapter.record_review(state["project_id"], "clone", "approved", True, first)
    assert approve(adapter, state)["approval"]["clone"]["valid"]
    rejected = adapter.record_review(state["project_id"], "clone", "rejected", True, state["asset_id"],
                                     "Typography needs revision.", checks={"0": "fix", "1": ""})
    assert rejected["state"]["cloneApproval"] is None
    assert rejected["approval"]["clone"]["decision"] == "rejected"
    with pytest.raises(ValidationError, match="review_checks"):
        adapter.record_review(state["project_id"], "clone", "approved", True, state["asset_id"], checks={"0": "fix"})


def test_image_brief_route_requests_host_production_without_claiming_render(adapter):
    created = create(adapter, sourceType="brief")
    prepared = adapter.prepare(created["project_id"], "clone")
    assert prepared["status"] == "awaiting_host_production"
    assert prepared["request"]["schema"] == "editor-ultra-host-production-request/1"
    assert not prepared["state"]["assets"]["clone"]
    with pytest.raises(ValidationError, match="host_production_required"):
        adapter.render(created["project_id"], "clone")


def test_generation_exports_actual_prompts_and_receives_versioned_clips_only(adapter, videos):
    from examples.project_flow.demo import authored_plan
    plan = authored_plan()
    for clip in plan["clips"]:
        clip["duration_s"] = .5
        clip["use"]["end_s"] = .5
        clip["shots"][0]["end_s"] = .5
    plan["brief"]["target_duration_s"] = 1.1
    plan["brief"]["instruction_language"] = "pt-BR"
    plan["brief"]["language_review"]["instruction_language"] = "pt-BR"
    current = create(adapter, sourceType="brief", mode="generate", targetDuration=1.1, ratio="16:9",
                     objective=plan["brief"]["objective"], audience=plan["brief"]["audience"],
                     shots=[{"id": c["id"], "seconds": .5, "action": c["shots"][0]["action"]} for c in plan["clips"]])
    current = upload(adapter, current, "clone", videos["blue"])
    current = approve(adapter, current)
    prepared = adapter.prepare(current["project_id"], "generation", expected_revision=current["revision"])
    assert prepared["request"]["media_generation_executed"] is False
    directed = adapter.apply_direction(current["project_id"], "generation", plan, expected_revision=prepared["revision"])
    assert directed["status"] == "prompts_exported"
    assert len(directed["prompt_pack"]["clips"]) == 3
    assert directed["video_generation_policy"]["automatic_video_generation"] is False
    assert adapter.get_result(current["project_id"], "generation")["status"] == "prompts_exported"
    received = upload(adapter, directed, "shot", videos["red"], shot_id="clip-1")
    assert received["state"]["shots"][0]["returned_current"]
    stored = adapter._load(current["project_id"])
    assert stored["files"][received["asset_id"]]["generation_receipt"]["clip_id"] == "clip-1"
    plan["revision"] = 2
    plan["clips"][0]["shots"][0]["action"] = "Hold another explicitly authored synthetic color."
    revised = adapter.apply_direction(current["project_id"], "generation", plan, expected_revision=received["revision"])
    assert not revised["state"]["shots"][0]["returned_current"]
