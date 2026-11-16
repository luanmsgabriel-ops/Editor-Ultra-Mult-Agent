"""Reference-to-new-content contracts, with attributed synthetic observations."""

import copy

import pytest
from PIL import Image

from editorial_engine.contracts import ValidationError, digest, file_sha256
from editorial_engine.reference_direction import (build_dossier, generation_context,
    to_contextual_profile, validate_adaptation, validate_dossier)


def reference_fixture(tmp_path):
    source = tmp_path / "source.fixture"
    source.write_bytes(b"Synthetic source identity; this is not video playback")
    picture = tmp_path / "frame.png"
    Image.new("RGB", (16, 12), "navy").save(picture)
    author = {"kind": "human", "actor": "fixture author", "method": "Synthetic authored example, no actual playback"}
    location = {"source_id": "source", "source_sha256": file_sha256(source), "clock": "source",
                "interval": {"start_s": 0, "end_s": 1}}
    analysis = {"schema_version": "1.0", "sources": [{"id": "source", "path": str(source),
                 "sha256": file_sha256(source), "duration_s": 2}],
                "evidence": [{"id": "frame:0", **location, "kind": "visual", "observation": "Supplied static fixture.",
                              "provenance": author, "artifact": {"path": str(picture), "sha256": file_sha256(picture), "frame": 0}}],
                "events": [{"id": "event:0", **location, "intent": "Inspect the fixture", "evidence_ids": ["frame:0"]}],
                "capabilities": []}
    observations = [{"id": "composition", "aspect": "composition", "description": "The declared subject occupies the left third.",
                     **location, "evidence_ids": ["frame:0"], "scope": "sampled_frames", "provenance": author, "confidence": 0.6},
                    {"id": "person", "aspect": "identity", "description": "The source features its original presenter.",
                     **location, "evidence_ids": ["frame:0"], "scope": "sampled_frames", "provenance": author, "confidence": 0.5}]
    dossier = build_dossier(analysis, observations, dossier_id="reference-example", author=author)
    adaptation = {"schema": "reference-adaptation/1", "id": "new-presenter", "revision": 1,
                  "dossier_sha256": dossier["dossier_sha256"], "author": author,
                  "replacement_references": [], "decisions": [
                      {"observation_id": "composition", "action": "keep", "rationale": "Preserve the visual hierarchy."},
                      {"observation_id": "person", "action": "replace", "target": "Use a new fictional presenter in a blue jacket.",
                       "rationale": "The new production uses its own character."}]}
    return analysis, dossier, adaptation


def test_projections_preserve_attribution_and_explicit_replacement(tmp_path):
    analysis, dossier, adaptation = reference_fixture(tmp_path)
    before = copy.deepcopy((analysis, dossier, adaptation))
    profile = to_contextual_profile(dossier, adaptation)
    context = generation_context(dossier, adaptation)
    assert profile["keep"][0]["observation"]["description"] == dossier["observations"][0]["description"]
    assert profile["replace"][0]["target"] == adaptation["decisions"][1]["target"]
    assert context["evidence"][0]["provenance"] == dossier["observations"][0]["provenance"]
    assert context["references"][0]["path"] == analysis["sources"][0]["path"]
    assert context["review_scope"]["automatic_perception"] is False
    assert context["review_scope"]["user_approval"] == "unverified"
    assert all(":" not in item["id"] for item in context["references"] + context["evidence"])
    assert (analysis, dossier, adaptation) == before


def test_every_observation_requires_a_decision_and_replace_requires_target(tmp_path):
    _, dossier, adaptation = reference_fixture(tmp_path)
    adaptation["decisions"].pop()
    with pytest.raises(ValidationError, match="adaptation_incomplete"):
        validate_adaptation(adaptation, dossier)
    adaptation["decisions"].append({"observation_id": "person", "action": "replace", "rationale": "Change the person"})
    with pytest.raises(ValidationError):
        validate_adaptation(adaptation, dossier)


def test_dossier_changes_and_foreign_evidence_are_rejected(tmp_path):
    analysis, dossier, _ = reference_fixture(tmp_path)
    damaged = copy.deepcopy(dossier)
    damaged["observations"][0]["description"] = "A changed observation"
    with pytest.raises(ValidationError, match="reference_digest"):
        validate_dossier(damaged)
    observations = copy.deepcopy(dossier["observations"])
    observations[0]["evidence_ids"] = ["absent"]
    with pytest.raises(ValidationError, match="unknown_evidence"):
        build_dossier(analysis, observations, dossier_id="invalid", author=dossier["author"])


def test_file_or_sample_changes_invalidate_the_dossier(tmp_path):
    _, dossier, _ = reference_fixture(tmp_path)
    sample = dossier["analysis"]["evidence"][0]["artifact"]["path"]
    from pathlib import Path
    Path(sample).write_bytes(b"altered sample")
    with pytest.raises(ValidationError):
        validate_dossier(dossier)


def test_a_transcript_does_not_establish_listened_audio(tmp_path):
    analysis, dossier, _ = reference_fixture(tmp_path)
    analysis["evidence"][0]["kind"] = "transcript"
    observation = {**dossier["observations"][0], "scope": "audio_listened", "aspect": "audio"}
    with pytest.raises(ValidationError, match="reference_scope"):
        build_dossier(analysis, [observation], dossier_id="invalid-audio", author=dossier["author"])


def test_stale_duplicate_and_silent_replacement_decisions_are_rejected(tmp_path):
    _, dossier, adaptation = reference_fixture(tmp_path)
    for kind in ("stale", "duplicate", "keep-target"):
        changed = copy.deepcopy(adaptation)
        if kind == "stale": changed["dossier_sha256"] = "0" * 64
        elif kind == "duplicate": changed["decisions"].append(changed["decisions"][0])
        else: changed["decisions"][0]["target"] = "A different camera"
        with pytest.raises(ValidationError): validate_adaptation(changed, dossier)


def test_replacement_references_are_real_and_hash_bound(tmp_path):
    _, dossier, adaptation = reference_fixture(tmp_path)
    image = tmp_path / "replacement.png"
    Image.new("RGB", (12, 12), "blue").save(image)
    reference = {"id": "new-person", "kind": "image", "role": "New character reference",
                 "path": str(image), "sha256": file_sha256(image)}
    adaptation["replacement_references"] = [reference]
    adaptation["decisions"][1]["reference_ids"] = ["new-person"]
    context = generation_context(dossier, adaptation)
    assert context["references"][-1] == reference
    normalized = validate_adaptation(adaptation, dossier)
    assert normalized["adaptation_sha256"] == digest({k: v for k, v in normalized.items() if k != "adaptation_sha256"})
    image.write_bytes(b"changed")
    with pytest.raises(ValidationError): generation_context(dossier, adaptation)
