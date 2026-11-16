"""Real media through export -> import -> dependent export, without a provider."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess

from editorial_engine.generation.cli import main
from editorial_engine.generation.ingest import import_clip, validate_receipt
from editorial_engine.generation.prompts import compile_pack


def _fixture():
    state = {"description": "A synthetic test pattern.", "motion": "The pattern changes across frames.",
             "camera": "Fixed raster.", "audio": "No audio."}
    clips = []
    for i in range(3):
        clip = {"id": f"clip-{i + 1}", "purpose": "Exercise a returned-frame dependency with synthetic media.",
                "duration_s": .5, "use": {"start_s": 0, "end_s": .5}, "character_ids": [],
                "location_ids": [], "prop_ids": [], "evidence_ids": [],
                "shots": [{"id": "pattern", "start_s": 0, "end_s": .5, "intent": "Test clock and binding.",
                           "action": "Change a test pattern.", "composition": "Full square raster.",
                           "camera": "Fixed.", "performance": "No actor.", "lighting": "Emissive color bars."}],
                "dialogue": [], "audio": {"voice_direction": "None.", "ambience": "None.",
                                           "music": "None.", "sfx": "None."},
                "conditioning": [], "post": [], "constraints": ["Synthetic contract example only."]}
        if i == 0:
            clip["initial_state"] = deepcopy(state)
        if i == 2:
            clip["final_state"] = deepcopy(state)
        clips.append(clip)
    plan = {"schema": "video-generation-plan/1", "id": "synthetic-chain", "revision": 1,
            "author": {"kind": "human", "actor": "test fixture", "method": "Synthetic protocol input."},
            "brief": {"mode": "original", "objective": "Test dependent exports.", "audience": "Test runner.",
                      "aspect_ratio": "1:1", "target_duration_s": 1.5, "instruction_language": "en",
                      "dialogue_language": "pt-BR", "audio_execution": "none",
                      "language_review": {"actor": "test fixture", "method": "Fixed authored fixture.",
                                          "instruction_language": "en", "dialogue_language": "pt-BR"}},
            "bible": {"visual_style": "Synthetic test pattern.", "invariants": [], "characters": [],
                      "locations": [], "props": []}, "references": [], "evidence": [], "assets": [],
            "clips": clips, "joins": [{"id": f"join-{i + 1}", "from": clips[i]["id"],
                                       "to": clips[i + 1]["id"], "kind": "Continue from reviewed test frame.",
                                       "rationale": "Test actual dependency binding.", "execution": "generation",
                                       "strategy": "observed_frame", "overlap_s": 0,
                                       "outgoing": deepcopy(state), "incoming": deepcopy(state), "match": []}
                                      for i in range(2)]}
    profile = {"schema": "video-generation-capabilities/1", "id": "synthetic-only", "tool": "Test fixture",
               "model": "No actual generation model", "mode": "image_to_video", "interface": "test",
               "verification": {"status": "verified", "source": "Synthetic integration fixture; not a provider claim.",
                                "checked_at": "2026-11-16"}, "durations_s": [.5], "aspect_ratios": ["1:1"],
               "max_prompt_chars": 20000, "inputs": {"start_frame": {"supported": True, "max_count": 1,
                                                                        "field": "initial image"}},
               "outputs": {"audio": False, "speech": False}, "multi_shot": False}
    return plan, profile


def _video(path, *, replacement=False):
    source = "color=c=blue:size=64x64:rate=10" if replacement else "testsrc2=size=64x64:rate=10"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", source, "-frames:v", "5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path)], check=True,
                   capture_output=True, timeout=20)
    return path


def _observation():
    return {"actor": "synthetic protocol fixture", "method": "Exercise review fields; not an aesthetic evaluation.",
            "scope": "boundary_window", "frame_range": {"start_frame": 0, "end_frame": 5},
            "description": "Synthetic pattern in a square raster.", "motion": "Pattern changes across test frames.",
            "camera": "Fixed raster.", "audio": "No audio stream.",
            "continuity_decision": {"status": "accept", "actor": "synthetic protocol fixture",
                                    "reason": "Test the affirmative decision path; no production approval claimed."}}


def test_real_return_chain_and_changed_parent_block_stale_descendants(tmp_path):
    plan, profile = _fixture()
    initial = compile_pack(plan, profile=profile, ready=True)
    assert [c["status"] for c in initial["clips"]] == ["ready", "blocked", "blocked"]
    video = _video(tmp_path / "pattern.mp4")
    first = import_clip(plan, "clip-1", video, tmp_path / "return-1", selected_frame=4,
                        observation=_observation(), exported_clip=initial["clips"][0])
    validate_receipt(first, plan)
    next_pack = compile_pack(plan, profile=profile, returns={"clip-1": first}, ready=True)
    assert [c["status"] for c in next_pack["clips"]] == ["ready", "ready", "blocked"]
    assert next_pack["clips"][1]["attachments"][0]["sha256"] == first["selected_frame"]["sha256"]
    second = import_clip(plan, "clip-2", video, tmp_path / "return-2", selected_frame=4,
                         observation=_observation(), exported_clip=next_pack["clips"][1])
    final = compile_pack(plan, profile=profile, returns={"clip-1": first, "clip-2": second}, ready=True)
    assert final["status"] == "ready"
    assert final["generation_performed"] is False
    replacement = import_clip(plan, "clip-1", _video(tmp_path / "blue.mp4", replacement=True),
                              tmp_path / "replacement", selected_frame=4, observation=_observation(),
                              exported_clip=initial["clips"][0])
    changed = compile_pack(plan, profile=profile, returns={"clip-1": replacement, "clip-2": second}, ready=True)
    assert changed["clips"][2]["status"] == "blocked"
    assert "return_dependency_stale" in {i["code"] for i in changed["clips"][2]["issues"]}


def test_observed_but_rejected_frame_cannot_become_the_next_input(tmp_path):
    plan, profile = _fixture()
    observation = _observation()
    observation["continuity_decision"].update(status="revise", reason="Simulated unusable boundary.")
    receipt = import_clip(plan, "clip-1", _video(tmp_path / "pattern.mp4"), tmp_path / "return",
                          selected_frame=4, observation=observation)
    pack = compile_pack(plan, profile=profile, returns={"clip-1": receipt}, ready=True)
    assert pack["clips"][1]["status"] == "blocked"


def test_cli_export_import_and_verify_are_concrete_and_non_destructive(tmp_path):
    plan, profile = _fixture()
    plan_path, profile_path = tmp_path / "plan.json", tmp_path / "profile.json"
    plan_path.write_text(json.dumps(plan))
    profile_path.write_text(json.dumps(profile))
    output = tmp_path / "export"
    assert main(["export", str(plan_path), str(output), "--profile", str(profile_path), "--ready"]) == 0
    assert (output / "prompt-pack.json").is_file()
    assert (output / "prompts.md").is_file()
    assert (output / "01-clip-1.txt").is_file()
    before = (output / "prompt-pack.json").read_bytes()
    assert main(["export", str(plan_path), str(output)]) == 2
    assert (output / "prompt-pack.json").read_bytes() == before
    video = _video(tmp_path / "pattern.mp4")
    received = tmp_path / "imported"
    assert main(["import", str(plan_path), "clip-1", str(video), str(received),
                 "--export-pack", str(output / "prompt-pack.json")]) == 0
    assert main(["verify-return", str(plan_path), str(received / "receipt.json")]) == 0
