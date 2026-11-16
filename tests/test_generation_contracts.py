"""Timing and dependency regressions for provider-independent video planning."""

import json
from pathlib import Path

import pytest

from editorial_engine.contracts import file_sha256
from editorial_engine.generation import (assembly_timing, clip_fingerprint,
                                         effective_states, revise_plan, validate_plan)


EXAMPLE = Path(__file__).resolve().parents[1] / "examples/video_generation/three-clips-plan.json"


def example():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_three_clips_and_two_crossfades_change_the_actual_edit_length():
    plan = example()
    assert assembly_timing(plan)["final_duration_s"] == 30
    for join in plan["joins"]:
        join["overlap_s"] = .5
        join["execution"] = "hybrid"
    with pytest.raises(ValueError, match="duration_mismatch"):
        validate_plan(plan)
    plan["brief"]["target_duration_s"] = 29
    timing = assembly_timing(plan)
    assert timing["generated_duration_s"] == 30
    assert timing["final_duration_s"] == 29
    assert timing["timeline"][1]["start_s"] == 9.5
    assert timing["timeline"][2]["start_s"] == 19


def test_each_boundary_has_one_owner_and_one_conditioning_image():
    plan = example()
    assert effective_states(plan, "clip-1")[1] == plan["joins"][0]["outgoing"]
    assert effective_states(plan, "clip-2")[0] == plan["joins"][0]["incoming"]
    plan["clips"][1]["conditioning"].append({"role": "start_frame", "asset_id": "closing"})
    with pytest.raises(ValueError, match="conflicting_handoff"):
        validate_plan(plan)
    plan = example()
    plan["clips"][1]["initial_state"] = plan["clips"][0]["initial_state"]
    with pytest.raises(ValueError, match="duplicate_boundary"):
        validate_plan(plan)


def test_local_direction_revision_preserves_independent_clips():
    previous, revised = example(), example()
    revised["revision"] = 2
    revised["clips"][1]["shots"][0]["camera"] = "Keep the camera stationary through the platform reveal."
    changed = revise_plan(previous, revised)
    assert changed["changed_clips"] == ["clip-2"]
    assert changed["unchanged_clips"] == ["clip-1", "clip-3"]
    assert clip_fingerprint(previous, "clip-1") == clip_fingerprint(revised, "clip-1")
    assert not changed["automatic_approval"]


def test_global_identity_and_shared_join_changes_invalidate_their_consumers():
    previous, revised = example(), example()
    revised["revision"] = 2
    revised["bible"]["characters"][0]["wardrobe"] = "A dark blue linen jacket, cream top and dark trousers."
    assert revise_plan(previous, revised)["invalidated_clips"] == ["clip-1", "clip-2", "clip-3"]
    revised = example()
    revised["revision"] = 2
    revised["joins"][0]["incoming"]["motion"] = "Move gently upward, according to the revised direction."
    assert revise_plan(previous, revised)["invalidated_clips"] == ["clip-1", "clip-2"]


def test_return_dependent_chain_is_invalidated_beyond_the_local_edit():
    previous = example()
    for join in previous["joins"]:
        join["strategy"] = "observed_frame"
        del join["handoff_asset_id"]
    revised = json.loads(json.dumps(previous))
    revised["revision"] = 2
    revised["clips"][0]["shots"][0]["action"] = "The presenter raises the notebook with her right hand."
    report = revise_plan(previous, revised)
    assert report["changed_clips"] == ["clip-1"]
    assert report["invalidated_clips"] == ["clip-1", "clip-2", "clip-3"]


def test_gapped_shots_cannot_hide_an_undirected_interval():
    plan = example()
    plan["clips"][0]["shots"][1]["start_s"] = 4.2
    with pytest.raises(ValueError, match="shot_coverage"):
        validate_plan(plan)


def test_use_range_must_not_silently_cut_a_spoken_line():
    plan = example()
    plan["clips"][0]["use"]["start_s"] = 1
    plan["brief"]["target_duration_s"] = 29
    with pytest.raises(ValueError, match="speech_trimmed"):
        validate_plan(plan)


def test_silent_mode_is_explicit_and_does_not_discard_dialogue():
    plan = example()
    plan["brief"]["audio_execution"] = "none"
    with pytest.raises(ValueError, match="silent_dialogue"):
        validate_plan(plan)
    for clip in plan["clips"]:
        clip["dialogue"] = []
    validate_plan(plan)
    plan["brief"]["require_generated_audio"] = True
    with pytest.raises(ValueError, match="audio_conflict"):
        validate_plan(plan)


def test_use_range_must_not_hide_a_required_post_event():
    plan = example()
    plan["clips"][0]["dialogue"] = []
    plan["clips"][0]["use"]["start_s"] = 4
    plan["brief"]["target_duration_s"] = 26
    with pytest.raises(ValueError, match="post_trimmed"):
        validate_plan(plan)


def test_needed_images_are_valid_planning_work_but_ready_means_real_bytes(tmp_path):
    plan = validate_plan(example(), verify_files=True)
    assert all(a["status"] == "needed" for a in plan["assets"])
    path = tmp_path / "image.png"
    path.write_bytes(b"placeholder byte provenance test only")
    plan["assets"][0].update(status="ready", path=str(path), sha256=file_sha256(path))
    validate_plan(plan, verify_files=True)
    path.write_bytes(b"changed bytes")
    with pytest.raises(ValueError, match="file_hash_mismatch"):
        validate_plan(plan, verify_files=True)


def test_reference_mode_needs_observations_bound_to_the_actual_source(tmp_path):
    plan = example()
    plan["brief"]["mode"] = "reference_clone"
    with pytest.raises(ValueError, match="empty"):
        validate_plan(plan)
    source = tmp_path / "reference.mp4"
    source.write_bytes(b"synthetic source identity fixture, not a decoded video")
    source_hash = file_sha256(source)
    plan["references"] = [{"id": "ref", "kind": "video", "path": str(source), "sha256": source_hash,
                            "role": "Pacing reference", "duration_s": 30}]
    plan["evidence"] = [{"id": "e1", "source_id": "ref", "source_sha256": source_hash,
                         "interval": {"start_s": 0, "end_s": 30}, "scope": "human_note",
                         "observation": "Synthetic observation for a binding regression, not perceptual review."}]
    for item in plan["assets"] + plan["clips"]:
        item["evidence_ids"] = ["e1"]
    validate_plan(plan, verify_files=True)
    plan["evidence"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="evidence_hash"):
        validate_plan(plan)
