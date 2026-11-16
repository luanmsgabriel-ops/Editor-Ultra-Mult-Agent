"""Authored timing, environment separation and aspect-ratio regressions."""

from copy import deepcopy
import shutil
import wave

import pytest

from editorial_engine.contracts import digest, file_sha256
from editorial_engine.generation.shot_design import (
    plan_shots, shot_prompt, validate_design, validate_generation_mapping,
)


AUTHOR = {"kind": "human", "actor": "Test author", "method": "Explicit synthetic shot direction"}


def profile():
    return {
        "schema": "video-generation-capabilities/1", "id": "declared-test",
        "tool": "Synthetic fixture", "model": "No model invoked", "mode": "text_to_video",
        "interface": "test", "verification": {
            "status": "verified", "source": "Synthetic fixture only", "checked_at": "2026-01-01"},
        "durations_s": [4, 6, 8, 10], "aspect_ratios": ["9:16", "16:9"],
        "inputs": {}, "outputs": {"audio": False, "speech": False},
        "multi_shot": False, "max_prompt_chars": 10000,
    }


def design():
    result = {
        "schema": "video-shot-design/1", "id": "three-environments", "revision": 1,
        "author": AUTHOR, "aspect_ratios": ["9:16", "16:9"],
        "duration_candidates_s": [4, 6, 8, 10], "target_duration_s": 18,
        "locations": [
            {"id": "cafe", "description": "A warm cafe with one window."},
            {"id": "street", "description": "A quiet street outside the cafe."},
            {"id": "studio", "description": "A studio with a plain blue background."},
        ],
        "shots": [], "joins": [],
    }
    for identifier, duration, breakpoint, location in [
        ("arrival", 4, 1, "cafe"), ("walk", 6, 2, "street"), ("reveal", 8, 3, "studio")
    ]:
        result["shots"].append({
            "id": identifier, "purpose": "Show the authored " + identifier + " action.",
            "subject": "The new performer, preserving her own identity.",
            "performance": "Perform the two described gestures at their authored pace.",
            "lighting": "Soft light motivated by the described environment.",
            "location_ids": [location], "use_duration_s": duration,
            "handles": {"in_s": 0, "out_s": 0},
            "camera": {"purpose": "Make both hands readable", "movement": "Locked camera."},
            "actions": [
                {"id": "prepare", "start_s": 0, "end_s": breakpoint, "description": "Raise the closed notebook."},
                {"id": "show", "start_s": breakpoint, "end_s": duration, "description": "Open the notebook and hold it while breathing naturally."},
            ],
            "compositions": {
                "9:16": {"framing": "Medium shot with both hands inside the narrow frame.",
                    "rationale": "Reserve vertical space for the notebook opening.",
                    "subject_zone": [0.2, 0.12, 0.8, 0.9], "gesture_zone": [0.1, 0.3, 0.9, 0.8]},
                "16:9": {"framing": "Wider shot showing the environment to the right.",
                    "rationale": "Keep the environment visible without shrinking the hands.",
                    "subject_zone": [0.12, 0.1, 0.55, 0.95], "gesture_zone": [0.1, 0.2, 0.65, 0.9]},
            },
        })
    result["joins"] = [
        {"id": "outside", "from": "arrival", "to": "walk", "kind": "cut",
         "execution": "post", "overlap_s": 0, "rationale": "Move the story outside."},
        {"id": "studio", "from": "walk", "to": "reveal", "kind": "cut",
         "execution": "post", "overlap_s": 0, "rationale": "Show the studio reveal."},
    ]
    return result


def one_shot():
    value = design()
    value["shots"] = value["shots"][:1]
    value["joins"] = []
    value["target_duration_s"] = 4
    return value


def codes(result):
    return {i["code"] for i in result["issues"] if i["blocking"]}


def generation(plan, ratio="9:16"):
    """A full generation contract bound to the independent shot design fixture."""
    state = {"description": "Authored state.", "motion": "Authored motion.",
             "camera": "Locked camera.", "audio": "None."}
    result = {
        "schema": "video-generation-plan/1", "id": "directed", "revision": 1,
        "author": AUTHOR,
        "brief": {"mode": "original", "objective": "Demonstrate three authored environments.",
            "audience": "Test reviewers", "aspect_ratio": ratio,
            "target_duration_s": plan["timing"]["final_duration_s"],
            "instruction_language": "en", "dialogue_language": "pt-BR", "audio_execution": "none"},
        "bible": {"visual_style": "Authored test style", "invariants": [], "characters": [],
                  "locations": [], "props": []},
        "references": [], "evidence": [], "assets": [], "clips": [], "joins": [],
    }
    for index, shot in enumerate(plan["shots"]):
        clip = {
            "id": "clip-" + shot["id"], "purpose": "Execute the authored shot.",
            "duration_s": shot["generated_duration_s"], "use": deepcopy(shot["use"]),
            "character_ids": [], "location_ids": [], "prop_ids": [], "evidence_ids": [],
            "constraints": [], "conditioning": [], "post": [], "dialogue": [],
            "audio": {"voice_direction": "None", "ambience": "None", "music": "None", "sfx": "None"},
            "shots": [{"id": "take", "start_s": 0, "end_s": shot["generated_duration_s"],
                "intent": "Show the action.", "action": "Perform the authored gestures.",
                "composition": shot["compositions"][ratio]["framing"], "camera": "Locked.",
                "performance": "As authored.", "lighting": "As authored."}],
        }
        if index == 0:
            clip["initial_state"] = state
        if index == len(plan["shots"]) - 1:
            clip["final_state"] = state
        result["clips"].append(clip)
    for join in plan["joins"]:
        result["joins"].append({
            "id": join["id"], "from": "clip-" + join["from"], "to": "clip-" + join["to"],
            "kind": join["kind"], "rationale": join["rationale"], "execution": join["execution"],
            "strategy": "post_only", "overlap_s": join["overlap_s"],
            "outgoing": state, "incoming": state, "match": [],
        })
    return result


def test_three_environments_choose_4_6_8_without_inferring_duration_from_action_count():
    authored = design()
    before = deepcopy(authored)
    result = plan_shots(authored, profile=profile())
    assert result["status"] == "planned"
    assert [s["generated_duration_s"] for s in result["shots"]] == [4, 6, 8]
    assert [len(s["actions"]) for s in authored["shots"]] == [2, 2, 2]
    assert result["timing"]["exact_final_s"] == "18"
    assert [r["start_s"] for r in result["timing"]["timeline"]] == [0, 4, 10]
    assert authored == before
    assert result["verification"]["capabilities_live_checked"] is False
    assert result["verification"]["media_generated"] is False


def test_two_half_second_dissolves_yield_17_seconds_without_hidden_extension():
    value = design()
    value["target_duration_s"] = 17
    for join in value["joins"]:
        join.update(kind="dissolve", overlap_s=0.5)
    result = plan_shots(value, profile=profile())
    assert result["status"] == "planned"
    assert result["timing"]["generated_duration_s"] == 18
    assert result["timing"]["final_duration_s"] == 17
    assert [r["start_s"] for r in result["timing"]["timeline"]] == [0, 3.5, 9]
    assert "execution=post; overlap_s=0.5" in result["shots"][0]["prompts"]["9:16"]
    assert "without duplicating its transition effect" in result["shots"][0]["prompts"]["9:16"]


def test_handles_and_surplus_are_explicit_and_action_clock_moves_into_generated_clip():
    value = one_shot()
    shot = value["shots"][0]
    shot["handles"] = {"in_s": 0.5, "out_s": 0.25,
                      "in_direction": "Bring the notebook into the initial position.",
                      "out_direction": "Continue the final natural breathing and keep the notebook open."}
    result = plan_shots(value, profile=profile())
    assert result["shots"][0]["minimum_generation_s"] == 4.75
    assert result["shots"][0]["generated_duration_s"] == 6
    assert "shot_excess_unassigned" in codes(result)
    shot["excess_policy"] = "tail_handle"
    result = plan_shots(value, profile=profile())
    assert result["status"] == "planned"
    assert result["shots"][0]["use"] == {"start_s": 0.5, "end_s": 4.5}
    assert result["shots"][0]["handles"]["effective_out_s"] == 1.5
    assert "Authored action 0.5–1.5 s" in result["shots"][0]["prompts"]["9:16"]
    assert result["timing"]["final_duration_s"] == 4


def test_explicit_eight_seconds_is_honored_and_shorter_explicit_duration_is_blocked():
    value = one_shot()
    value["shots"][0].update(generated_duration_s=8, excess_policy="tail_handle")
    value["shots"][0]["handles"]["out_direction"] = "Maintain the authored live pose."
    result = plan_shots(value, profile=profile())
    assert result["shots"][0]["generated_duration_s"] == 8
    assert result["status"] == "planned"
    value["shots"][0]["use_duration_s"] = 9
    value["shots"][0]["actions"][-1]["end_s"] = 9
    assert "shot_duration_short" in codes(plan_shots(value, profile=profile()))


def test_maximum_duration_does_not_force_speedup_or_automatic_split():
    value = one_shot()
    value["shots"][0]["use_duration_s"] = 12
    value["shots"][0]["actions"][-1]["end_s"] = 12
    value["target_duration_s"] = 12
    result = plan_shots(value, profile=profile())
    assert "shot_duration_unavailable" in codes(result)
    assert result["shots"][0]["generated_duration_s"] is None
    assert len(result["shots"]) == 1
    assert result["questions"]
    assert result["verification"]["automatic_retime"] is False


def test_missing_semantics_return_questions_without_keyword_emotions_or_camera_rules():
    value = one_shot()
    value["shots"][0]["purpose"] = "Urgent exciting viral reveal."
    del value["shots"][0]["performance"]
    del value["shots"][0]["camera"]
    result = plan_shots(value)
    assert result["status"] == "blocked"
    prompt = result["shots"][0]["prompts"]["9:16"]
    assert "Urgent exciting viral reveal." in prompt
    assert "Camera movement:" not in prompt
    assert "Performance:" not in prompt
    assert any(q["id"].endswith(".performance") for q in result["questions"])


def test_multiple_environments_need_separate_shots_unless_continuous_change_is_authored():
    value = one_shot()
    shot = value["shots"][0]
    shot["location_ids"] = ["cafe", "street"]
    assert "shot_environment_split" in codes(plan_shots(value))
    shot["environment_transition"] = {
        "mode": "continuous", "start_s": 1, "end_s": 3,
        "description": "Walk through the open cafe door into the street without a cut.",
        "camera_path": "Follow behind at a constant distance through the doorway.",
    }
    result = plan_shots(value)
    assert result["status"] == "planned"
    assert "without a cut" in result["shots"][0]["prompts"]["16:9"]


def test_ratio_composition_is_authored_per_format_without_crop_defaults():
    value = one_shot()
    result = plan_shots(value)
    prompts = result["shots"][0]["prompts"]
    assert "narrow frame" in prompts["9:16"]
    assert "environment to the right" in prompts["16:9"]
    assert "[0.2, 0.12, 0.8, 0.9]" in prompts["9:16"]
    del value["shots"][0]["compositions"]["16:9"]
    result = plan_shots(value)
    assert "shot_composition_needed" in codes(result)
    assert "narrow frame" not in result["shots"][0]["prompts"]["16:9"]
    assert not result["verification"]["automatic_crop"]


def test_invalid_normalized_zones_are_not_clipped_silently():
    value = one_shot()
    value["shots"][0]["compositions"]["9:16"]["gesture_zone"] = [-0.1, 0.2, 1, 0.8]
    with pytest.raises(ValueError, match="range"):
        validate_design(value)
    value["shots"][0]["compositions"]["9:16"]["gesture_zone"] = [0.7, 0.2, 0.4, 0.8]
    with pytest.raises(ValueError, match="shot_zone"):
        validate_design(value)


def test_gaps_and_late_action_cannot_be_hidden_by_clip_duration():
    value = one_shot()
    value["shots"][0]["actions"][1]["start_s"] = 2
    assert "shot_action_gap" in codes(plan_shots(value))
    value["shots"][0]["actions"][1]["end_s"] = 5
    assert "shot_content_trimmed" in codes(plan_shots(value))


def test_simultaneous_actions_use_their_union_not_sum_of_lengths():
    value = one_shot()
    value["shots"][0]["actions"].append({
        "id": "breath", "start_s": 0, "end_s": 4, "description": "Breathe naturally throughout."})
    result = plan_shots(value)
    assert result["status"] == "planned"
    assert result["shots"][0]["required_content_s"] == 4
    assert result["shots"][0]["generated_duration_s"] == 4


def test_estimated_voice_is_not_measured_and_long_voice_blocks_use_without_rewriting():
    value = one_shot()
    voice = {"id": "line", "text": "Minha fala permanece exatamente assim.",
             "start_s": 0.5, "end_s": 3.5, "timing_basis": "estimated", "provenance": AUTHOR}
    value["shots"][0]["voice"] = [voice]
    result = plan_shots(value)
    assert result["status"] == "planned"
    assert result["shots"][0]["voice"][0]["verification"] == "authored_estimate"
    assert voice["text"] in result["shots"][0]["prompts"]["9:16"]
    voice["end_s"] = 5
    assert "shot_content_trimmed" in codes(plan_shots(value))
    voice["timing_basis"] = "measured"
    with pytest.raises(ValueError, match="Expected an object"):
        plan_shots(value)


@pytest.mark.skipif(not shutil.which("ffprobe"), reason="FFprobe is needed for real audio duration verification")
def test_measured_voice_has_real_source_coverage_and_no_claim_of_listening(tmp_path):
    audio = tmp_path / "two-seconds.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\0\0" * 16000)
    value = one_shot()
    voice = {"id": "line", "text": "Synthetic timing fixture; no speech recognition claimed.",
        "start_s": 1, "end_s": 3, "timing_basis": "measured", "provenance": AUTHOR,
        "source": {"path": str(audio), "sha256": file_sha256(audio), "start_s": 0, "end_s": 2}}
    value["shots"][0]["voice"] = [voice]
    result = plan_shots(value, verify_files=True)
    assert result["shots"][0]["voice"][0]["verification"] == "source_bytes_and_audio_duration_verified"
    assert result["verification"]["audio_listened"] is False
    voice["source"].update(start_s=1, end_s=3)
    with pytest.raises(ValueError, match="shot_voice_coverage"):
        plan_shots(value, verify_files=True)
    voice["source"].update(start_s=0, end_s=1)
    with pytest.raises(ValueError, match="shot_voice_retime"):
        plan_shots(value)


def test_profile_duration_candidates_are_reused_but_range_increments_are_not_invented():
    value = one_shot()
    del value["duration_candidates_s"]
    result = plan_shots(value, profile=profile())
    assert result["status"] == "planned"
    assert result["candidate_origin"] == "profile_durations"
    capabilities = profile()
    del capabilities["durations_s"]
    capabilities["duration_range_s"] = {"min": 4, "max": 10}
    result = plan_shots(value, profile=capabilities)
    assert "duration_candidates_needed" in codes(result)
    assert result["duration_candidates_s"] == []


def test_capability_status_is_attributed_and_unsupported_ratio_is_blocked():
    capabilities = profile()
    capabilities["verification"]["status"] = "unverified"
    result = plan_shots(one_shot(), profile=capabilities)
    assert result["status"] == "planned"
    assert any(i["code"] == "shot_profile_unverified" and not i["blocking"] for i in result["issues"])
    assert result["verification"]["capabilities_live_checked"] is False
    capabilities["aspect_ratios"] = ["9:16"]
    assert "shot_ratio_unsupported" in codes(plan_shots(one_shot(), profile=capabilities))


def test_missing_join_and_colliding_overlaps_do_not_create_a_valid_timeline():
    value = design()
    value["joins"] = value["joins"][:1]
    result = plan_shots(value)
    assert "shot_join_needed" in codes(result)
    assert result["timing"] is None
    value = design()
    for join in value["joins"]:
        join.update(kind="dissolve", overlap_s=3.5)
    result = plan_shots(value)
    assert "shot_overlap_collision" in codes(result)
    assert result["timing"] is None


def test_target_mismatch_requires_authored_revision_instead_of_filler():
    value = design()
    value["target_duration_s"] = 20
    result = plan_shots(value)
    assert "shot_target_mismatch" in codes(result)
    assert result["timing"]["final_duration_s"] == 18
    assert len(result["shots"]) == 3


def test_generation_mapping_binds_both_formats_and_rejects_reordered_or_modified_use():
    planned = plan_shots(design(), profile=profile())
    binding = {"clip-" + s["id"]: s["id"] for s in planned["shots"]}
    for ratio in ("9:16", "16:9"):
        receipt = validate_generation_mapping(planned, generation(planned, ratio), binding)
        assert receipt["timing_bound"] is True
        assert receipt["aspect_ratio"] == ratio
        assert receipt["semantic_prompt_review"] == "pending"
    changed = generation(planned)
    changed["clips"][0]["use"]["end_s"] = 3
    changed["brief"]["target_duration_s"] = 17
    with pytest.raises(ValueError, match="shot_mapping_use"):
        validate_generation_mapping(planned, changed, binding)
    wrong = {**binding, "clip-arrival": "walk", "clip-walk": "arrival"}
    with pytest.raises(ValueError, match="shot_mapping"):
        validate_generation_mapping(planned, generation(planned), wrong)


def test_generation_mapping_rejects_duration_ratio_overlap_and_resealed_plan_forgery():
    planned = plan_shots(design())
    binding = {"clip-" + s["id"]: s["id"] for s in planned["shots"]}
    changed = generation(planned)
    changed["clips"][0]["duration_s"] = 6
    changed["clips"][0]["shots"][0]["end_s"] = 6
    with pytest.raises(ValueError, match="shot_mapping_duration"):
        validate_generation_mapping(planned, changed, binding)
    changed = generation(planned)
    changed["brief"]["aspect_ratio"] = "1:1"
    with pytest.raises(ValueError, match="shot_mapping_ratio"):
        validate_generation_mapping(planned, changed, binding)
    changed = generation(planned)
    changed["joins"][0].update(overlap_s=0.5, kind="dissolve")
    changed["brief"]["target_duration_s"] = 17.5
    with pytest.raises(ValueError, match="shot_mapping_overlap"):
        validate_generation_mapping(planned, changed, binding)
    forged = deepcopy(planned)
    forged["shots"][0]["generated_duration_s"] = 6
    forged["plan_sha256"] = digest({k: v for k, v in forged.items() if k != "plan_sha256"})
    with pytest.raises(ValueError, match="shot_result_changed"):
        validate_generation_mapping(forged, generation(planned), binding)


def test_full_generation_validator_can_call_mapping_without_recursion():
    from editorial_engine.generation.contracts import clip_fingerprint, validate_plan
    planned = plan_shots(design(), profile=profile())
    directed = generation(planned)
    baseline = clip_fingerprint(directed, "clip-arrival")
    directed["shot_design"] = {
        "plan": planned,
        "clip_to_shot": {"clip-" + s["id"]: s["id"] for s in planned["shots"]},
    }
    checked = validate_plan(directed)
    assert checked["shot_design"]["plan"]["plan_sha256"] == planned["plan_sha256"]
    assert clip_fingerprint(directed, "clip-arrival") != baseline
    directed["clips"][0]["use"]["end_s"] = 3
    directed["brief"]["target_duration_s"] = 17
    with pytest.raises(ValueError, match="shot_mapping_use"):
        validate_plan(directed)


def test_prompt_helper_preserves_visual_direction_and_seams_without_duplicate_voice():
    value = design()
    literal = "Esta frase literal vai para o áudio produzido em pós."
    value["shots"][0]["voice"] = [{
        "id": "line", "text": literal, "start_s": 0.5, "end_s": 3.5,
        "timing_basis": "estimated", "provenance": AUTHOR,
    }]
    value["joins"][0]["outgoing"] = "End with the notebook open and hands below the face."
    planned = plan_shots(value)
    full = shot_prompt(planned, "arrival", "9:16")
    assert full == planned["shots"][0]["prompts"]["9:16"]
    assert full.count(literal) == 1
    visual = shot_prompt(planned, "arrival", "9:16", include_voice=False)
    assert literal not in visual
    assert "Literal voice" not in visual
    assert "Raise the closed notebook." in visual
    assert "Camera purpose: Make both hands readable" in visual
    assert "narrow frame" in visual
    assert "End with the notebook open and hands below the face." in visual
    assert "execution=post" in visual
    assert planned["design"]["shots"][0]["voice"][0]["text"] == literal
    with pytest.raises(ValueError, match="shot_mapping_ratio"):
        shot_prompt(planned, "arrival", "1:1")
    with pytest.raises(ValueError, match="shot_prompt_id"):
        shot_prompt(planned, "unknown", "9:16")
    with pytest.raises(ValueError, match="include_voice"):
        shot_prompt(planned, "arrival", "9:16", include_voice="false")
