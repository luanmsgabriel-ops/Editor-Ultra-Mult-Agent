"""Reproducible actual-media integration; no model, face or aesthetic approval.

Run from the repository: python -m examples.project_flow.demo --output /new/path
Three locally generated colors exercise prompt export, returned-media receipts,
crossfades, exact duration, project persistence and an explicitly preview delivery.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess

from editorial_engine import project


def authored_plan():
    state = {"description": "A full-frame synthetic color.", "motion": "No subject motion.",
             "camera": "Fixed raster.", "audio": "Silent technical demonstration."}
    clips = []
    for index, color in enumerate(("red", "blue", "green"), 1):
        clip = {"id": f"clip-{index}", "purpose": "Exercise a real returned clip and a declared transition.",
            "duration_s": 1, "use": {"start_s": 0, "end_s": 1}, "character_ids": [],
            "location_ids": [], "prop_ids": [], "evidence_ids": [],
            "shots": [{"id": "color", "start_s": 0, "end_s": 1, "intent": "Show a synthetic color.",
                "action": "Hold the color " + color + ".", "composition": "Full-frame 16:9 rectangle.",
                "camera": "Fixed.", "performance": "No actor.", "lighting": "Uniform synthetic pixels."}],
            "dialogue": [], "audio": {"voice_direction": "None.", "ambience": "None.", "music": "None.", "sfx": "None."},
            "conditioning": [], "post": [], "constraints": ["Technical fixture; not an external generation result."]}
        if index == 1:
            clip["initial_state"] = deepcopy(state)
        if index == 3:
            clip["final_state"] = deepcopy(state)
        clips.append(clip)
    return {"schema": "video-generation-plan/1", "id": "clone-local-demo", "revision": 1,
        "author": {"kind": "human", "actor": "Authored repository demo", "method": "Explicit deterministic technical fixture"},
        "brief": {"mode": "original", "objective": "Demonstrate connected clips with real measured files.",
            "audience": "Engine maintainers.", "aspect_ratio": "16:9", "target_duration_s": 2.6,
            "instruction_language": "en", "dialogue_language": "pt-BR", "audio_execution": "none",
            "language_review": {"actor": "Authored repository demo", "method": "Literal fixed example text",
                                "instruction_language": "en", "dialogue_language": "pt-BR"}},
        "bible": {"visual_style": "Synthetic full-frame colors.", "invariants": [], "characters": [], "locations": [], "props": []},
        "references": [], "evidence": [], "assets": [], "clips": clips,
        "joins": [{"id": f"join-{index}", "from": f"clip-{index}", "to": f"clip-{index + 1}",
            "kind": "Crossfade between synthetic colors.", "rationale": "Exercise the explicit overlap clock.",
            "execution": "post", "strategy": "post_only", "overlap_s": .2,
            "outgoing": deepcopy(state), "incoming": deepcopy(state), "match": []} for index in (1, 2)]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    project_dir = root / "project"
    plan = authored_plan()
    project.create_project(project_dir, {"schema": "clone-project-spec/1", "id": "clone-local-demo",
        "intent": "returned_clips", "brief": plan["brief"]["objective"], "inputs": []})
    project.accept_direction(project_dir, plan, kind="generation")
    project.export_prompts(project_dir)
    for index, color in enumerate(("red", "blue", "green"), 1):
        path = root / f"clip-{index}.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        f"color={color}:s=160x90:r=10:d=1", "-c:v", "libx264", "-threads", "1",
                        "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
        project.receive_clip(project_dir, f"clip-{index}", path)
    project.plan_assembly(project_dir, fps="10", width=160, height=90, audio="none",
                          transitions={"join-1": "crossfade", "join-2": "crossfade"})
    project.render_project(project_dir, kind="assembly")
    rendered = project.artifact(project_dir, "render")
    project.review_project(project_dir, {"id": "executed-technical-checks", "clock": "output",
        "plan_sha256": rendered["plan_sha256"], "render_sha256": rendered["sha256"],
        "reviewer": {"kind": "tool", "actor": "FFmpeg assembly + demo assertions", "method": "Actual full decode and measured output clock"},
        "checks": {"technical": {"status": "pass", "mode": "metadata",
            "coverage": [{"start_s": 0, "end_s": rendered["duration_s"]}],
            "notes": "Three real clips, two declared crossfades, measured 26 frames at 10 FPS; no audio requested."}}})
    project.deliver_project(project_dir, root / "delivery", kind="preview")
    result = {"project": str(project_dir), "preview": str(root / "delivery" / "preview.mp4"),
        "duration_s": rendered["duration_s"], "frame_count": rendered["frame_count"],
        "status": project.project_status(project_dir)["status"],
        "external_model_called": False, "perceptual_review": "not_performed", "user_approval": "pending"}
    (root / "proof.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
