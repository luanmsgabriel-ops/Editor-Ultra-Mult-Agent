"""Shot planning must reach the actual director payload and exported prompts."""
from copy import deepcopy
import json

import pytest

from editorial_engine import project as p
from editorial_engine.contracts import ValidationError
from editorial_engine.generation.shot_design import plan_shots
from test_shot_design import design, generation


def _project(tmp_path):
    authored = design()
    planned = plan_shots(authored, verify_files=True)
    directed = generation(planned)
    answers = {**deepcopy(directed["brief"]), "shot_design": authored}
    root = tmp_path / "project"
    p.create_project(root, {"schema": p.SPEC_SCHEMA, "id": "shot-directions", "intent": "original",
        "brief": answers["objective"], "generation_answers": answers, "inputs": []})
    p.request_direction(root, kind="generation", include_images=False)
    directed["shot_mapping"] = {clip["id"]: shot["id"] for clip, shot in zip(directed["clips"], planned["shots"])}
    return root, authored, planned, directed


def test_authored_timing_and_portrait_composition_reach_actual_export(tmp_path):
    root, authored, planned, directed = _project(tmp_path)
    request = p.artifact(root, "generation_request")
    payload = json.loads(request["body"]["messages"][1]["content"])
    assert payload["shot_design_context"] == planned
    p.accept_direction(root, directed, kind="generation")
    adopted = p.artifact(root, "generation_plan")
    assert adopted["shot_design"]["plan"] == planned
    assert "shot_mapping" not in adopted
    p.export_prompts(root)
    pack = p.artifact(root, "prompt_pack")
    prompt = pack["clips"][0]["prompt"]
    assert authored["shots"][0]["actions"][0]["description"] in prompt
    assert authored["shots"][0]["compositions"]["9:16"]["framing"] in prompt
    assert authored["shots"][0]["compositions"]["16:9"]["framing"] not in prompt


def test_current_shot_contract_cannot_be_dropped_or_remapped(tmp_path):
    root, _, _, directed = _project(tmp_path)
    absent = deepcopy(directed)
    absent.pop("shot_mapping")
    with pytest.raises(ValidationError, match="shot_design_mapping"):
        p.accept_direction(root, absent, kind="generation")
    directed["shot_mapping"][directed["clips"][0]["id"]] = "walk"
    with pytest.raises(ValidationError, match="shot_mapping"):
        p.accept_direction(root, directed, kind="generation")


def test_reframing_invalidates_direction_and_export(tmp_path):
    root, _, _, directed = _project(tmp_path)
    p.accept_direction(root, directed, kind="generation")
    p.export_prompts(root)
    revised = deepcopy(p.load_project(root)["spec"])
    revised["generation_answers"]["shot_design"]["shots"][0]["compositions"]["9:16"]["framing"] = "Back up to keep both elbows visible."
    p.update_project(root, revised, reason="Explicit framing correction")
    state = p.project_status(root)
    for key in ("generation_request", "generation_plan", "prompt_pack"):
        assert state["artifacts"][key]["status"] == "stale"
