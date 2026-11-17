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
    prepared = adapter.prepare(pid, "edit", expected_revision=current["revision"])
    assert prepared["kind"] == "assembly"
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


def review_note(stage="clone"):
    return {"id": "note-" + stage, "kind": stage, "time": "00:00.2", "component": "Tipografia",
            "text": "Conferir o espaçamento deste título.", "resolved": False}


def test_review_draft_survives_autosave_and_supplies_notes_without_approval(adapter, videos):
    current = create(adapter, sourceType="brief")
    pid = current["project_id"]
    note = review_note()
    current = adapter.save_project(pid, {"comments": [{**note, "asset_id": "forged", "binding": "forged"}],
                                         "cloneConfirm": True, "cloneApproval": {"valid": True, "serverRecorded": True}},
                                   current["revision"])
    assert current["state"]["comments"] == [note]
    assert current["state"]["cloneConfirm"] is True
    assert current["state"]["cloneApproval"] is None
    # The panel can annotate a local preview before its first server upload.
    current = upload(adapter, current, "clone", videos["blue"])
    assert current["state"]["comments"] == [note]
    assert current["state"]["cloneConfirm"] is False
    current = adapter.save_project(pid, {"cloneConfirm": True, "cloneChecks": {"0": "fix"}}, current["revision"])
    current = adapter.save_project(pid, {"name": "QA revisão após autosave"}, current["revision"])
    restored = EngineAdapter(adapter.data_dir).get_project(pid)
    assert restored["state"]["cloneConfirm"] is True
    assert restored["state"]["comments"] == [note]
    assert restored["state"]["cloneApproval"] is None
    notes = "\n".join(f"{item['time']} · {item['component']}: {item['text']}" for item in restored["state"]["comments"])
    reviewed = adapter.record_review(pid, "clone", "rejected", True, current["state"]["assets"]["clone"][0]["id"],
                                     notes=notes, checks={"0": "fix"}, expected_revision=current["revision"])
    assert reviewed["approval"]["clone"]["notes"] == notes
    assert reviewed["approval"]["clone"]["decision"] == "rejected"
    assert reviewed["state"]["cloneApproval"] is None


@pytest.mark.parametrize("changed_role,cleared", [("ref", {"clone", "final"}), ("clone", {"clone", "final"}),
                                                ("result", {"final"})])
def test_review_drafts_do_not_transfer_to_another_reference_or_preview(adapter, videos, changed_role, cleared):
    current = upload(adapter, create(adapter), "ref", videos["blue"])
    current = upload(adapter, current, "clone", videos["red"])
    current = approve(adapter, current)
    current = upload(adapter, current, "result", videos["lime"])
    current = adapter.save_project(current["project_id"], {"cloneConfirm": True, "finalConfirm": True,
                                   "cloneChecks": {"0": "ok"}, "finalChecks": {"0": "ok"},
                                   "comments": [review_note("clone"), review_note("final")]}, current["revision"])
    assert current["state"]["cloneConfirm"] and current["state"]["finalConfirm"]
    changed = upload(adapter, current, changed_role, videos["lime" if changed_role == "ref" else "blue"])
    for stage in ("clone", "final"):
        assert changed["state"][stage + "Confirm"] is (stage not in cleared)
        assert bool(changed["state"][stage + "Checks"]) is (stage not in cleared)
        assert any(item["kind"] == stage for item in changed["state"]["comments"]) is (stage not in cleared)
        if stage in cleared:
            assert changed["state"][stage + "Approval"] is None
    # Even submitting stale checked boxes together with a changed reference cannot
    # carry a prior confirmation or notes into the new reference's review.
    stale = deepcopy(changed["state"])
    stale.update(objective="Uma referência com outra direção", cloneConfirm=True, finalConfirm=True,
                 comments=[review_note("clone"), review_note("final")],
                 cloneApproval={"valid": True, "serverRecorded": True}, finalApproval={"valid": True, "serverRecorded": True})
    saved = adapter.save_project(changed["project_id"], stale, changed["revision"])
    assert not saved["state"]["cloneConfirm"] and not saved["state"]["finalConfirm"]
    assert saved["state"]["comments"] == []
    assert saved["state"]["cloneApproval"] is None and saved["state"]["finalApproval"] is None


def test_review_draft_rejects_malformed_values(adapter):
    current = create(adapter)
    for payload in ({"cloneConfirm": "true"}, {"comments": [{**review_note(), "time": "not-a-time"}]},
                    {"comments": [review_note(), review_note()]}, {"comments": [{**review_note(), "resolved": "yes"}]}):
        with pytest.raises(ValidationError, match="ui_review_draft"):
            adapter.save_project(current["project_id"], payload, current["revision"])
    assert adapter.get_project(current["project_id"])["revision"] == current["revision"]


def test_legacy_project_binds_existing_preview_before_accepting_draft_changes(adapter, videos):
    current = upload(adapter, create(adapter), "clone", videos["blue"])
    path = adapter.data_dir / current["project_id"] / "record.json"
    legacy = json.loads(path.read_text())
    legacy.pop("review_draft_bindings")  # Adapter fixture from before draft bindings existed.
    path.write_text(json.dumps(legacy))
    changed = adapter.save_project(current["project_id"], {"objective": "Changed source direction",
                                   "cloneConfirm": True, "comments": [review_note()]}, current["revision"])
    assert changed["state"]["cloneConfirm"] is False
    assert changed["state"]["comments"] == []
    assert changed["state"]["cloneApproval"] is None


def test_host_upload_retry_reuses_asset_without_revision_or_review_changes(adapter, videos):
    current = upload(adapter, create(adapter, sourceType="brief"), "clone", videos["blue"], host_file_id="file-native-1")
    asset_id = current["asset_id"]
    assert current["asset"]["hostFileId"] == "file-native-1"
    assert current["state"]["assets"]["clone"][0]["hostFileId"] == "file-native-1"
    current = approve(adapter, current)
    restored = EngineAdapter(adapter.data_dir).get_project(current["project_id"])
    retried = upload(adapter, restored, "clone", videos["blue"], host_file_id="file-native-1")
    assert retried["idempotent"] is True
    assert retried["asset_id"] == asset_id
    assert retried["revision"] == restored["revision"]
    assert retried["state"]["history"] == restored["state"]["history"]
    assert retried["approval"] == restored["approval"]
    assert retried["approval"]["clone"]["valid"]
    assert len(retried["state"]["assets"]["clone"]) == 1
    assert len(list((adapter.data_dir / current["project_id"] / "media").iterdir())) == 1
    with pytest.raises(ValidationError, match="revision_conflict"):
        adapter.import_local_file(current["project_id"], "clone", videos["blue"], "blue.mp4", "video/mp4",
                                  host_file_id="file-native-1", expected_revision=restored["revision"] - 1)


def test_host_upload_id_reuse_verifies_bytes_and_media_type(adapter, videos, tmp_path):
    current = upload(adapter, create(adapter), "ref", videos["blue"], host_file_id="file-native-1")
    with pytest.raises(ValidationError, match="host_file_conflict"):
        upload(adapter, current, "ref", videos["red"], host_file_id="file-native-1")
    with pytest.raises(ValidationError, match="host_file_conflict"):
        adapter.import_local_file(current["project_id"], "ref", videos["blue"], "blue.webm", "video/webm",
                                  host_file_id="file-native-1", expected_revision=current["revision"])
    invalid = tmp_path / "invalid.mp4"
    invalid.write_text("A host file ID cannot certify these bytes as video.")
    with pytest.raises(ValidationError, match="invalid_media"):
        upload(adapter, current, "ref", invalid, host_file_id="file-native-1")
    reloaded = adapter.get_project(current["project_id"])
    assert reloaded["revision"] == current["revision"]
    assert len(reloaded["state"]["assets"]["ref"]) == 1


def test_host_upload_identity_is_scoped_to_project_role_and_shot(adapter, videos):
    current = create(adapter, shots=[{"id": "shot-one", "seconds": .5}, {"id": "shot-two", "seconds": .5}])
    current = upload(adapter, current, "ref", videos["blue"], host_file_id="same-host-file")
    identifiers = {current["asset_id"]}
    current = upload(adapter, current, "footage", videos["blue"], host_file_id="same-host-file")
    identifiers.add(current["asset_id"])
    for shot_id in ("shot-one", "shot-two"):
        current = upload(adapter, current, "shot", videos["blue"], host_file_id="same-host-file", shot_id=shot_id)
        identifiers.add(current["asset_id"])
    assert len(identifiers) == 4
    other = upload(adapter, create(adapter), "ref", videos["red"], host_file_id="same-host-file")
    assert other["asset_id"] not in identifiers
    assert other["asset"]["sha256"] != current["asset"]["sha256"]
