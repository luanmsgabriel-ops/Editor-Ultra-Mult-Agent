"""Independent recreation requirements reject known false substitutions.

These tests verify contracts and real file types. Synthetic footage is never a
test of performer identity, plausible performance, or perceptual acceptance.
"""

import copy
from pathlib import Path
import shutil
import subprocess

from PIL import Image
import pytest

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine.production import validate_request
from editorial_engine.recreation import (build_plan, generation_context,
    production_requests, validate_generation_assets, validate_plan)


def spec():
    return {"schema": "independent-recreation-spec/1", "id": "new-performer", "revision": 1,
            "author": {"kind": "human", "actor": "test-director", "method": "Authored contract fixture"},
            "reference": {"id": "editing-reference", "sha256": "1" * 64, "character_id": "old-performer"},
            "target_character": {"id": "new-performer", "identity": "An original fictional adult performer."},
            "clock": {"width": 24, "height": 32, "fps": "30/1", "frame_count": 60},
            "performance": [{"id": "open-portal", "scope": "user_instruction", "start_frame": 0,
                             "end_frame": 60, "description": "Open the hands while the head and shoulders move."}],
            "transformation": {"motion": "temporal_performance", "description": "A stylized same-character costume.",
                               "intervals": [{"start_frame": 10, "end_frame": 60}]},
            "alignment": {"intent": "Set the transformed layer slightly behind the newly tracked shoulder plane."}}


def origin():
    return {"kind": "human", "actor": "test-author", "method": "Authored fixture; not a real performer result",
            "origin": "independent_generation", "reference_pixels_used": False, "ancestor_sha256s": []}


def media(role="base_video", *, kind="video", hashchar="2"):
    item = {"id": role + "-asset", "role": role, "kind": kind, "path": "/fixture/" + role + ".mp4",
            "sha256": hashchar * 64, "character_id": "new-performer", "provenance": origin()}
    if kind == "video":
        item.update(performance_kind="temporal_video", fps="30/1", frame_count=60,
                    coverage=[{"start_frame": 0, "end_frame": 60, "source_start_frame": 0}])
    if role == "transformed_image_or_video" and kind == "video":
        item["performance_source_sha256"] = "2" * 64
    return item


def geometry(role="tracking", *, hashchar="4"):
    return {"id": role + "-asset", "role": role,
            "kind": {"tracking": "planar_tracking", "subject_alignment": "json", "occlusion": "mattes"}[role],
            "path": "/fixture/" + role + ".json", "sha256": hashchar * 64,
            "fps": "30/1", "frame_count": 60,
            "coverage": [{"start_frame": 0, "end_frame": 60, "source_start_frame": 0}],
            "source_binding": {"asset_id": "base_video-asset", "source_sha256": "2" * 64,
                               "fps": "30/1", "frame_count": 60},
            "reanchored": True, "tracking_sha256": "4" * 64, "transformed_sha256": "3" * 64}


def layers():
    return [media(), media("transformed_image_or_video", hashchar="3"), geometry(),
            geometry("subject_alignment", hashchar="5"), geometry("occlusion", hashchar="6")]


def test_missing_layers_form_a_concrete_plan_and_never_fabricate_bindings():
    planned = build_plan(spec())
    assert validate_plan(planned) == planned
    steps = {step["id"]: step for step in planned["steps"]}
    assert steps["base_video"]["acceptable_kinds"] == ["video"]
    assert steps["base_video"]["required_intervals"] == [{"start_frame": 0, "end_frame": 60}]
    assert steps["transformed_image_or_video"]["blocked_by"] == ["base_video"]
    assert steps["subject_alignment"]["status"] == "needed"
    requests = production_requests(planned)
    assert {request["context"]["recreation_role"] for request in requests} == {
        "base_video", "transformed_image_or_video", "composition"}
    base = next(request for request in requests if request["context"]["recreation_role"] == "base_video")
    transformed = next(request for request in requests if request["context"]["recreation_role"] == "transformed_image_or_video")
    assert base["unresolved"] == [] and base["inputs"] == []
    assert transformed["unresolved"] == ["base_video"]
    for request in requests:
        assert validate_request(request) == request
        assert ":" not in request["id"] and len(request["id"]) <= 96
    assert planned["verification"]["identity_verified"] is False
    assert planned["verification"]["source_independence"] == "declared_lineage_only"
    assert generation_context(planned)["base_video_from_frame_zero"] is True


@pytest.mark.parametrize("role", ["base_video", "transformed_image_or_video"])
def test_image_cannot_fill_a_temporal_performance_slot(role):
    with pytest.raises(ValidationError, match="recreation_media_kind"):
        build_plan(spec(), [media(role, kind="image")])


def test_static_artwork_is_an_explicit_choice_and_not_a_new_performance():
    chosen = spec()
    chosen["transformation"]["motion"] = "static_overlay"
    result = build_plan(chosen, [media("transformed_image_or_video", kind="image", hashchar="3")])
    assert result["steps"][1]["status"] == "supplied_unreviewed"
    assert result["steps"][0]["status"] == "needed"
    animated = media()
    animated["performance_kind"] = "animated_still"
    with pytest.raises(ValidationError, match="recreation_still_performance"):
        build_plan(chosen, [animated])


@pytest.mark.parametrize("change", ["same_hash", "ancestor", "known_derivative", "pixels", "origin", "simulated"])
def test_known_reference_reuse_and_simulated_media_are_rejected(change):
    chosen, base = spec(), media()
    if change == "same_hash":
        base["sha256"] = "1" * 64
    elif change == "ancestor":
        base["provenance"]["ancestor_sha256s"] = ["1" * 64]
    elif change == "known_derivative":
        chosen["known_reference_derivative_sha256s"] = [base["sha256"]]
    elif change == "pixels":
        base["provenance"]["reference_pixels_used"] = True
    elif change == "origin":
        base["provenance"]["origin"] = "reference_derived"
    else:
        base["provenance"]["simulated"] = True
    with pytest.raises(ValidationError, match="recreation_(reference_pixels|simulated)"):
        build_plan(chosen, [base])


@pytest.mark.parametrize("coverage", [
    [{"start_frame": 1, "end_frame": 60, "source_start_frame": 0}],
    [{"start_frame": 0, "end_frame": 20, "source_start_frame": 0},
     {"start_frame": 21, "end_frame": 60, "source_start_frame": 21}],
    [{"start_frame": 0, "end_frame": 60, "source_start_frame": 1}],
])
def test_missing_opening_internal_gap_or_insufficient_frames_blocks_adoption(coverage):
    base = media()
    base["coverage"] = coverage
    with pytest.raises(ValidationError, match="recreation_coverage"):
        build_plan(spec(), [base])


def test_target_identity_is_a_planning_gap_and_same_or_wrong_identity_is_rejected():
    chosen = spec()
    chosen["target_character"] = None
    draft = build_plan(chosen)
    assert draft["issues"][0]["code"] == "target_identity_needed"
    assert "target_identity_needed" in production_requests(draft)[0]["unresolved"]
    with pytest.raises(ValidationError, match="recreation_identity_needed"):
        build_plan(chosen, [media()])
    chosen = spec()
    chosen["target_character"]["id"] = "old-performer"
    with pytest.raises(ValidationError, match="recreation_same_character"):
        build_plan(chosen)
    base = media()
    base["character_id"] = "another-declared-character"
    with pytest.raises(ValidationError, match="recreation_character"):
        build_plan(spec(), [base])


def test_transform_motion_requires_new_performance_binding():
    transformed = media("transformed_image_or_video", hashchar="3")
    with pytest.raises(ValidationError, match="recreation_performance_source"):
        build_plan(spec(), [transformed])
    transformed["performance_source_sha256"] = "1" * 64
    with pytest.raises(ValidationError, match="recreation_performance_source"):
        build_plan(spec(), [media(), transformed])


@pytest.mark.parametrize("change", ["source", "reanchored", "missing_flag", "clock", "coverage"])
def test_tracking_cannot_be_relabelled_from_another_performer(change):
    tracked = geometry()
    if change == "source":
        tracked["source_binding"]["source_sha256"] = "1" * 64
    elif change == "reanchored":
        tracked["reanchored"] = False
    elif change == "missing_flag":
        del tracked["reanchored"]
    elif change == "clock":
        tracked["source_binding"]["frame_count"] = 59
    else:
        tracked["coverage"][0]["start_frame"] = 2
    with pytest.raises(ValidationError, match="recreation_(reanchor|coverage)"):
        build_plan(spec(), [media(), tracked])


def test_actual_base_enables_source_bound_tracking_requests_and_preserves_local_alignment_task():
    planned = build_plan(spec(), [media()])
    requests = production_requests(planned)
    tracked = next(request for request in requests if request["operation"] == "planar_tracking")
    assert tracked["source_binding"] == {"input_id": "base_video-asset", "source_sha256": "2" * 64,
                                         "fps": "30/1", "frame_count": 60}
    assert len(tracked["inputs"]) == 1
    assert all(request["context"]["recreation_role"] != "subject_alignment" for request in requests)
    transformed = next(request for request in requests if request["context"]["recreation_role"] == "transformed_image_or_video")
    assert transformed["inputs"][0]["sha256"] == "2" * 64
    assert transformed["unresolved"] == []


def test_alignment_and_occlusion_require_current_measured_dependencies():
    ready = layers()
    assert all(step["status"] == "supplied_unreviewed" for step in build_plan(spec(), ready)["steps"][:-1])
    bad = copy.deepcopy(ready)
    bad[3]["transformed_sha256"] = "7" * 64
    with pytest.raises(ValidationError, match="recreation_alignment_source"):
        build_plan(spec(), bad)
    bad = copy.deepcopy(ready)
    bad[4]["tracking_sha256"] = "7" * 64
    with pytest.raises(ValidationError, match="recreation_tracking_needed"):
        build_plan(spec(), bad)
    composition = media("composition", hashchar="7")
    composition["dependency_sha256s"] = [item["sha256"] for item in ready]
    completed = build_plan(spec(), [*ready, composition])
    assert completed["steps"][-1]["status"] == "supplied_unreviewed"
    assert completed["verification"]["continuous_visual_review"] == "pending"
    with pytest.raises(ValidationError, match="recreation_composition_dependencies"):
        build_plan(spec(), [media(), composition])


def test_modified_derived_status_or_semantic_claim_cannot_be_imported():
    planned = build_plan(spec())
    planned["verification"]["identity_verified"] = True
    with pytest.raises(ValidationError, match="recreation_plan_changed"):
        validate_plan(planned)


def generated_contract(recreation, stage="base_video"):
    target = copy.deepcopy(recreation["spec"]["target_character"])
    return {"recreation": {"plan": recreation, "stage": stage, "character_id": target["id"] if target else None},
            "brief": {"target_duration_s": 2},
            "bible": {"characters": [target] if target else []},
            "clips": [{"character_ids": [target["id"]] if target else [], "conditioning": []}],
            "assets": []}


def test_generation_of_base_has_no_circular_dependency_or_forced_duplicate_layer():
    planned = build_plan(spec())
    draft = generated_contract(planned)
    assert validate_generation_assets(planned, draft) == draft
    missing = spec()
    missing["target_character"] = None
    unresolved = build_plan(missing)
    assert validate_generation_assets(unresolved, generated_contract(unresolved))["recreation"]["plan"]["issues"]
    draft["brief"]["target_duration_s"] = 1
    with pytest.raises(ValidationError, match="recreation_coverage"):
        validate_generation_assets(planned, draft)


def test_generation_stages_require_coherent_identity_and_explicit_missing_dependencies():
    planned = build_plan(spec())
    draft = generated_contract(planned, "transformed_image_or_video")
    with pytest.raises(ValidationError, match="recreation_generation_mapping"):
        validate_generation_assets(planned, draft)
    draft["assets"] = [{"id": "new-base", "kind": "video", "status": "needed", "route": "external_video",
                        "recreation_role": "base_video"}]
    assert validate_generation_assets(planned, draft) == draft
    draft["bible"]["characters"][0]["identity"] = "Another unbound identity"
    with pytest.raises(ValidationError, match="recreation_character"):
        validate_generation_assets(planned, draft)


def test_generation_rejects_reference_input_ready_unbound_media_and_circular_conditioning():
    planned = build_plan(spec())
    draft = generated_contract(planned)
    draft["assets"] = [{"id": "old-source", "kind": "video", "status": "ready", "sha256": "1" * 64}]
    with pytest.raises(ValidationError, match="recreation_reference_pixels"):
        validate_generation_assets(planned, draft)
    draft["assets"] = [{"id": "new-base", "kind": "video", "status": "ready", "path": "/fixture/base_video.mp4",
                        "sha256": "2" * 64, "recreation_role": "base_video"}]
    with pytest.raises(ValidationError, match="recreation_generation_media"):
        validate_generation_assets(planned, draft)
    draft["assets"] = [{"id": "new-base", "kind": "video", "status": "needed", "route": "external_video",
                        "recreation_role": "base_video"}]
    draft["clips"][0]["conditioning"] = [{"role": "motion_video", "asset_id": "new-base"}]
    with pytest.raises(ValidationError, match="recreation_generation_cycle"):
        validate_generation_assets(planned, draft)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe required")
def test_real_video_probe_rejects_png_mislabeled_as_video_and_false_frame_count(tmp_path):
    fake = tmp_path / "still.png"
    Image.new("RGB", (24, 32), "blue").save(fake)
    base = media()
    base.update(path=str(fake), sha256=file_sha256(fake))
    with pytest.raises(ValidationError, match="video_stream"):
        build_plan(spec(), [base], verify_files=True)
    actual = tmp_path / "calibration.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=24x32:rate=30:duration=2",
                    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(actual)], check=True)
    base.update(path=str(actual), sha256=file_sha256(actual))
    result = build_plan(spec(), [base], verify_files=True)
    assert result["verification"]["identity_verified"] is False
    base["frame_count"] = 61
    with pytest.raises(ValidationError, match="recreation_media_clock"):
        build_plan(spec(), [base], verify_files=True)
