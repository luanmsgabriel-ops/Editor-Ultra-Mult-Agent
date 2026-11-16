"""Only injected, explicitly simulated transports; no paid/provider calls."""

import copy
import json
from pathlib import Path

import pytest

from editorial_engine.contracts import ValidationError, digest
from editorial_engine.generation.direction import build_request
from editorial_engine.generation.provider import call_provider, request_payload, validate_editorial_inputs
from test_generation_direction import known_brief
from test_reference_direction import reference_fixture


def original_plan(brief):
    state = {"description": "A static object on a table", "motion": "Still", "camera": "Locked", "audio": "None"}
    duration = brief["target_duration_s"]
    return {"schema": "video-generation-plan/1", "id": "director-fixture", "revision": 1,
            "author": {"kind": "human", "actor": "untrusted response label", "method": "fixture"},
            "brief": brief, "bible": {"visual_style": "Quiet product scene", "invariants": [], "characters": [], "locations": [], "props": []},
            "references": [], "evidence": [], "assets": [], "joins": [],
            "clips": [{"id": "clip-1", "purpose": "Show an object", "duration_s": duration,
                       "use": {"start_s": 0, "end_s": duration}, "character_ids": [], "location_ids": [], "prop_ids": [],
                       "evidence_ids": [], "constraints": [], "shots": [{"id": "shot-1", "start_s": 0, "end_s": duration,
                           "intent": "Show the object", "action": "The object remains still", "composition": "Centered",
                           "camera": "Locked", "performance": "No performer", "lighting": "Soft"}],
                       "dialogue": [], "audio": {"voice_direction": "None", "ambience": "None", "music": "None", "sfx": "None"},
                       "conditioning": [], "post": [], "initial_state": state, "final_state": state}]}


def response(plan):
    return {"choices": [{"message": {"content": json.dumps(plan)}}]}


def call(request, plan, **kwargs):
    return call_provider(request, endpoint="https://director.invalid/v1/chat/completions", model="fixture-model",
                         transport=lambda **_: response(plan), **kwargs)


def adapted_plan(request):
    payload = request_payload(request)
    plan = original_plan(request["brief"])
    plan["references"] = copy.deepcopy(payload["authoring_context"]["references"])
    plan["evidence"] = copy.deepcopy(payload["authoring_context"]["evidence"])
    plan["clips"][0]["evidence_ids"] = [e["id"] for e in plan["evidence"]]
    return plan


def test_original_call_returns_valid_plan_and_honest_simulation_receipt():
    request = build_request(known_brief())
    result = call(request, original_plan(request["brief"]))
    assert result["schema"] == "video-generation-plan/1"
    assert result["author"]["actor"] == "fixture-model"
    receipt = result["provider_receipt"]
    assert receipt["transport_kind"] == "injected_simulation"
    assert receipt["model_inference_executed"] is False
    assert receipt["media_generation_executed"] is False
    assert receipt["provider_input_use"] == "unverified"
    assert receipt["receipt_sha256"] == digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})


def test_manual_editorial_validation_keeps_explicit_limits_and_literal_speech():
    plan = original_plan(build_request(known_brief())["brief"])
    snapshot = copy.deepcopy(plan)
    limits = {"clip_count": 1, "clip_duration_s": plan["clips"][0]["duration_s"], "dialogue_text": ""}
    assert validate_editorial_inputs(plan, limits) is plan
    assert validate_editorial_inputs(plan, {}) is plan
    for inputs, code in (({"clip_count": 2}, "clip_count_changed"),
                         ({"clip_duration_s": 0.75}, "clip_duration_changed"),
                         ({"dialogue_text": "Exact requested speech."}, "literal_dialogue_changed")):
        with pytest.raises(ValidationError, match=code):
            validate_editorial_inputs(plan, inputs)
    assert plan == snapshot
    # Joining authored lines does not permit punctuation or wording changes.
    plan["clips"][0]["dialogue"] = [{"text": "Olá."}, {"text": "Tudo bem?"}]
    assert validate_editorial_inputs(plan, {"dialogue_text": "Olá. Tudo bem?"}) is plan
    with pytest.raises(ValidationError, match="literal_dialogue_changed"):
        validate_editorial_inputs(plan, {"dialogue_text": "Olá, tudo bem?"})


def test_real_image_bytes_and_reference_decisions_reach_transport(tmp_path):
    _, dossier, adaptation = reference_fixture(tmp_path)
    request = build_request(known_brief(mode="adaptation"), reference_dossier=dossier,
                            adaptation=adaptation, include_images=True)
    payload = request_payload(request)
    assert request["review_scope"]["images_embedded"] is True
    assert request["review_scope"]["semantic_inference_executed"] is False
    assert payload["image_manifest"][0]["mime_type"] == "image/png"
    assert payload["reference_context"]["decisions"][1]["action"] == "replace"
    sent = []
    plan = adapted_plan(request)
    result = call_provider(request, endpoint="http://localhost:8765/direct", model="fixture",
                           transport=lambda **args: (sent.append(args), response(plan))[1])
    images = [p for p in sent[0]["body"]["messages"][1]["content"] if p.get("type") == "image_url"]
    assert len(images) == 1 and images[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result["evidence"][0]["provenance"] == dossier["observations"][0]["provenance"]


def test_new_visual_observation_requires_supplied_image_and_limited_scope(tmp_path):
    analysis, _, _ = reference_fixture(tmp_path)
    request = build_request(known_brief(mode="reference_clone"), analysis=analysis, include_images=True)
    plan = adapted_plan(request)
    ref = plan["references"][0]
    plan["evidence"] = [{"id": "new-observation", "source_id": ref["id"], "source_sha256": ref["sha256"],
                         "observation": "The supplied synthetic image is blue.", "scope": "sampled_frames",
                         "interval": {"start_s": 0, "end_s": 1}}]
    plan["clips"][0]["evidence_ids"] = ["new-observation"]
    assert call(request, plan)["evidence"][0]["supplied_image_ids"] == ["evidence:frame:0"]
    for scope in ("continuous_video", "audio_listened"):
        changed = copy.deepcopy(plan)
        changed["evidence"][0]["scope"] = scope
        with pytest.raises(ValidationError, match="unobserved_scope"): call(request, changed)
    without_images = build_request(known_brief(mode="reference_clone"), analysis=analysis)
    with pytest.raises(ValidationError, match="unseen_source"): call(without_images, plan)


def test_changed_source_or_request_blocks_before_any_transport(tmp_path):
    analysis, _, _ = reference_fixture(tmp_path)
    request = build_request(known_brief(), analysis=analysis, include_images=True)
    calls = []
    transport = lambda **_: calls.append(True)
    changed = copy.deepcopy(request)
    changed["body"]["messages"][0]["content"] += "changed"
    with pytest.raises(ValidationError, match="request_hash"):
        call_provider(changed, endpoint="https://director.invalid", model="fixture", transport=transport)
    Path(analysis["sources"][0]["path"]).write_bytes(b"changed bytes")
    with pytest.raises(ValidationError):
        call_provider(request, endpoint="https://director.invalid", model="fixture", transport=transport)
    assert calls == []


def test_changed_brief_and_invented_ready_paths_are_rejected(tmp_path):
    request = build_request(known_brief())
    changed = original_plan(request["brief"])
    changed["brief"] = {**changed["brief"], "objective": "A new objective"}
    with pytest.raises(ValidationError, match="brief_changed"): call(request, changed)
    invented = original_plan(request["brief"])
    invented["assets"] = [{"id": "invented", "kind": "image", "purpose": "Fake ready result", "status": "ready",
                            "route": "chat_image", "evidence_ids": [], "reference_ids": [],
                            "path": str(tmp_path / "not-created.png"), "sha256": "0" * 64}]
    with pytest.raises(ValidationError, match="unprovided_file"): call(request, invented)


def test_response_schema_or_unresolved_brief_has_no_heuristic_fallback():
    request = build_request(known_brief())
    with pytest.raises(ValidationError): call(request, {"guess": "Use dynamic edits"})
    unresolved = build_request({})
    calls = []
    with pytest.raises(ValidationError, match="brief_incomplete"):
        call_provider(unresolved, endpoint="https://director.invalid", model="fixture", transport=lambda **_: calls.append(True))
    assert calls == []


def test_budgets_are_enforced_without_silent_image_drop(tmp_path):
    analysis, _, _ = reference_fixture(tmp_path)
    with pytest.raises(ValidationError, match="image_budget"):
        build_request(known_brief(), analysis=analysis, include_images=True, max_image_bytes=1)
    with pytest.raises(ValidationError, match="request_budget"):
        build_request(known_brief(), max_request_bytes=200)
    request = build_request(known_brief())
    with pytest.raises(ValidationError, match="response_size"):
        call(request, original_plan(request["brief"]), max_response_bytes=20)


def test_attributed_observations_cannot_be_rewritten_as_new_fact(tmp_path):
    _, dossier, adaptation = reference_fixture(tmp_path)
    request = build_request(known_brief(mode="adaptation"), reference_dossier=dossier, adaptation=adaptation)
    plan = adapted_plan(request)
    plan["evidence"][0]["observation"] = "The source has a different camera"
    with pytest.raises(ValidationError, match="attributed_evidence_changed"): call(request, plan)


def test_credentials_are_only_transport_arguments(monkeypatch):
    monkeypatch.setenv("CLONE_TEST_DIRECTOR_TOKEN", "test-secret-not-a-real-credential")
    request = build_request(known_brief())
    captured = []
    result = call_provider(request, endpoint="https://director.invalid/v1", model="fixture",
                           api_key_env="CLONE_TEST_DIRECTOR_TOKEN",
                           transport=lambda **kwargs: (captured.append(kwargs), response(original_plan(request["brief"])))[1])
    assert captured[0]["headers"]["Authorization"] == "Bearer test-secret-not-a-real-credential"
    assert "test-secret-not-a-real-credential" not in json.dumps(result)
    with pytest.raises(ValidationError, match="endpoint"):
        call_provider(request, endpoint="https://user:password@director.invalid", model="fixture", transport=lambda **_: {})


def test_input_change_during_transport_invalidates_return(tmp_path):
    analysis, _, _ = reference_fixture(tmp_path)
    request = build_request(known_brief(), analysis=analysis, include_images=True)
    plan = original_plan(request["brief"])
    def changing_transport(**kwargs):
        Path(analysis["evidence"][0]["artifact"]["path"]).write_bytes(b"Changed during direction")
        return response(plan)
    with pytest.raises(ValidationError):
        call_provider(request, endpoint="https://director.invalid", model="fixture", transport=changing_transport)


def test_template_catalogue_is_verified_authoring_context_not_ready_media(tmp_path):
    from visual_fidelity.reference_bundle import inventory
    package = tmp_path / "package"
    package.mkdir()
    (package / "index.html").write_text("<h1>Original fixture</h1>")
    library = {"schema": "motion-template-library/1", "id": "fixture-library", "version": "1",
               "packages": [{"id": "fixture", "root": "package", "files": inventory(package, excludes=()),
                             "provenance": {"source_folder_ids": [], "source_file_ids": [], "notes": "Synthetic fixture only"}}],
               "templates": [{"schema": "motion-template/1", "id": "fixture-title", "version": "1", "package_id": "fixture",
                              "title": "Title fixture", "description": "Authored project", "functions": ["introduce a subject"],
                              "entrypoint": "index.html", "runtime": {"name": "not executed", "requirements": []},
                              "parameters": {}, "bindings": [], "inputs": {}, "previews": [], "limitations": ["Not rendered"],
                              "state": {"catalogue": "catalogued", "adaptation": "required", "runtime": "not_executed",
                                        "preview": "none", "user_approval": "pending"}}]}
    request = build_request(known_brief(), template_library=library, template_root=tmp_path, template_ids=["fixture-title"])
    payload = request_payload(request)
    candidates = payload["template_library"]["templates"]
    assert candidates[0]["native_effect_ready"] is False
    assert payload["assets"] == []
    assert not any(f["path"].endswith("index.html") for f in payload["file_manifest"])
    (package / "index.html").write_text("<h1>Modified project</h1>")
    with pytest.raises(ValidationError):
        build_request(known_brief(), template_library=library, template_root=tmp_path)
