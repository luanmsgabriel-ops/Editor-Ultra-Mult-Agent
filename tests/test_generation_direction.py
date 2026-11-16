"""Direction requests preserve decisions, source identities and review scope."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from editorial_engine.contracts import ValidationError, digest, file_sha256
from editorial_engine.generation.contracts import validate_plan
from editorial_engine.generation.direction import briefing, build_request, response_contract


def known_brief(**changes):
    data = {"mode": "original", "objective": "Show how a small object changes the scene.",
            "audience": "People who enjoy visual demonstrations.", "target_duration_s": 30,
            "aspect_ratio": "9:16", "instruction_language": "en", "dialogue_language": "pt-BR",
            "subject_mode": "faceless", "characters": [], "voice_source": "none",
            "audio_execution": "none", "text_policy": "none", "target_tool": "undecided"}
    data.update(changes)
    return data


class AdaptiveBriefingTests(unittest.TestCase):
    def test_current_decisions_replace_preferences_including_false_and_empty(self):
        profile = {"defaults": {"brief": {"objective": "Old campaign"}, "subject_mode": "avatar",
                                "characters": [{"id": "former", "identity": "A previous character"}],
                                "require_generated_audio": True, "has_avatar": True,
                                "voice_source": "new", "text_policy": "generated"}}
        answers = known_brief(require_generated_audio=False, has_avatar=False)
        original_answers, original_profile = copy.deepcopy(answers), copy.deepcopy(profile)
        result = briefing(answers, profile=profile)
        self.assertEqual(result["resolved"]["objective"], answers["objective"])
        self.assertEqual(result["resolved"]["characters"], [])
        self.assertFalse(result["resolved"]["has_avatar"])
        self.assertFalse(result["resolved"]["require_generated_audio"])
        self.assertEqual(result["next_questions"], [])
        self.assertEqual(answers, original_answers)
        self.assertEqual(profile, original_profile)

    def test_missing_reference_intent_is_not_silently_original_creation(self):
        result = briefing({"references": [{"id": "source"}], "objective": "Adapt the reference",
                           "audience": "Customers", "target_duration_s": 30, "aspect_ratio": "16:9"})
        self.assertNotIn("mode", result["resolved"])
        self.assertEqual(result["next_questions"][0]["id"], "reference_intent")
        self.assertFalse(result["ready_for_direction"])
        self.assertLessEqual(len(result["next_questions"]), 3)
        continued = briefing({**result["resolved"], "mode": "adaptation", "subject_mode": "product",
                              "voice_source": "none", "text_policy": "post", "target_tool": "undecided"})
        self.assertNotIn("reference_intent", continued["missing"])
        self.assertTrue(continued["ready_for_direction"])

    def test_unknown_tool_does_not_block_direction_or_invent_capabilities(self):
        result = briefing(known_brief())
        self.assertTrue(result["ready_for_direction"])
        self.assertFalse(result["capabilities_verified"])
        self.assertNotIn("clip_duration_s", result["resolved"])
        self.assertNotIn("target_tool", result["missing"])

    def test_generated_duration_is_not_assumed_to_equal_final_duration(self):
        inputs = known_brief(clip_count=3, clip_duration_s=10, overlap_s=0.5)
        del inputs["target_duration_s"]
        result = briefing(inputs)
        self.assertNotIn("target_duration_s", result["resolved"])
        self.assertIn("duration", result["missing"])
        self.assertFalse(result["ready_for_direction"])

    def test_voice_and_avatar_questions_are_conditional_and_not_repeated(self):
        inputs = known_brief(subject_mode="avatar", characters=[], voice_source="source")
        del inputs["characters"]
        del inputs["audio_execution"]
        result = briefing(inputs)
        self.assertIn("identity", result["missing"])
        self.assertIn("avatar_status", result["missing"])
        self.assertIn("audio_execution", result["missing"])
        self.assertIn("source_audio", result["missing"])
        completed = briefing({**inputs, "identity": "Use the supplied face and wardrobe references",
                              "avatar_status": "reference_images", "audio_execution": "post",
                              "source_audio": {"status": "needed"}})
        self.assertNotIn("identity", completed["missing"])
        self.assertNotIn("avatar_status", completed["missing"])
        self.assertNotIn("audio_execution", completed["missing"])
        self.assertNotIn("source_audio", completed["missing"])

    def test_empty_mapping_clears_preferences_and_reviews_do_not_cross_projects(self):
        review = {"actor": "previous author", "method": "reviewed another script",
                  "instruction_language": "en", "dialogue_language": "pt-BR"}
        profile = {"identity": {"hair": "Previously chosen hair"}, "language_review": review}
        result = briefing(known_brief(identity={}), profile=profile)
        self.assertEqual(result["resolved"]["identity"], {})
        self.assertNotIn("language_review", result["resolved"])
        request = build_request(known_brief(), profile=profile)
        self.assertNotIn("language_review", request["brief"])
        current = {**review, "actor": "current director", "method": "reviewed this script"}
        request = build_request(known_brief(language_review=current), profile=profile)
        self.assertEqual(request["brief"]["language_review"], current)
        partial = briefing(known_brief(language_review={"actor": "current director"}), profile=profile)
        self.assertEqual(partial["resolved"]["language_review"], {"actor": "current director"})

    def test_no_speech_still_needs_an_audio_workflow_choice(self):
        inputs = known_brief(voice_source="none")
        del inputs["audio_execution"]
        result = briefing(inputs)
        self.assertIn("audio_execution", result["missing"])
        self.assertNotIn("audio_execution", result["resolved"])
        continued = briefing({**result["resolved"], "audio_execution": "none"})
        self.assertNotIn("audio_execution", continued["missing"])

    def test_capability_schema_is_not_mixed_into_preference_defaults(self):
        profile = {"schema": "video-generation-capabilities/1", "id": "declared-mode",
                   "tool": "Declared tool", "durations_s": [10]}
        result = briefing(known_brief(), profile=profile)
        self.assertEqual(result["resolved"]["capabilities"], profile)
        self.assertNotIn("durations_s", result["resolved"])
        self.assertFalse(result["capabilities_verified"])

    def test_rejects_invalid_known_values_and_non_json_data(self):
        for changes in ({"target_duration_s": -1}, {"target_duration_s": float("nan")},
                        {"clip_count": True}, {"characters": "someone"},
                        {"audio_execution": "automatic"}, {"aspect_ratio": "0:16"},
                        {"voice_source": {}}, {"subject_mode": []}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                briefing(known_brief(**changes))


class DirectorRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.fixture"
        self.source.write_bytes(b"Reference identity fixture, not audiovisual playback.")
        source_hash = file_sha256(self.source)
        ref = {"source_id": "reference", "source_sha256": source_hash, "clock": "source",
               "interval": {"start_s": 0, "end_s": 1}}
        self.analysis = {"schema_version": "1.0",
                         "sources": [{"id": "reference", "path": str(self.source),
                                      "sha256": source_hash, "duration_s": 2}],
                         "evidence": [{"id": "sample", **ref, "kind": "visual",
                                       "observation": "Fixture note: the object is on the left.",
                                       "provenance": {"kind": "human", "actor": "test reviewer",
                                                      "method": "Authored test fixture, no actual viewing"}}],
                         "events": [{"id": "reveal", **ref, "intent": "Reveal an object",
                                     "evidence_ids": ["sample"]}], "capabilities": []}

    def test_request_carries_complete_contract_without_claiming_inference(self):
        request = build_request(known_brief())
        self.assertEqual(request["request_sha256"], digest(request["body"]))
        self.assertFalse(request["model_inference_executed"])
        self.assertFalse(request["media_generation_executed"])
        self.assertFalse(request["review_scope"]["continuous_motion_review"])
        self.assertFalse(request["review_scope"]["listened_audio"])
        schema = request["response_contract"]["json_schema"]
        self.assertEqual(set(schema["required"]),
                         {"schema", "id", "revision", "author", "brief", "bible", "references",
                          "evidence", "assets", "clips", "joins"})
        self.assertIn("performance", schema["$defs"]["shot"]["required"])
        self.assertIn("outgoing", schema["$defs"]["join"]["required"])
        self.assertIn("incoming", schema["$defs"]["join"]["required"])
        self.assertIn("post", schema["$defs"]["clip"]["required"])
        payload = json.loads(request["body"]["messages"][1]["content"])
        self.assertIsNone(payload["analysis"])
        self.assertNotIn("language_review", request["brief"])
        if payload["example"]["plan"] is not None:
            validated = validate_plan(payload["example"]["plan"])
            self.assertEqual(sum(c["duration_s"] for c in validated["clips"]), 30)
        # Mutable outputs from one request must not mutate a subsequent schema.
        schema["$defs"]["state"]["properties"]["motion"]["minLength"] = 0
        self.assertEqual(response_contract()["json_schema"]["$defs"]["state"]["properties"]["motion"]["minLength"], 1)

    def test_source_notes_are_attributed_and_hash_bound_not_new_observations(self):
        original = copy.deepcopy(self.analysis)
        request = build_request(known_brief(mode="reference_clone"), analysis=self.analysis)
        payload = json.loads(request["body"]["messages"][1]["content"])
        self.assertEqual(payload["analysis"], original)
        self.assertEqual(request["analysis_sha256"], digest(original))
        self.assertEqual(request["brief"]["mode"], "reference_clone")
        self.assertNotIn("reference", request["briefing"]["missing"])
        self.assertTrue(request["review_scope"]["source_bytes_verified"])
        self.assertFalse(request["review_scope"]["semantic_inference_executed"])
        self.assertFalse(request["review_scope"]["images_embedded"])
        self.assertFalse(request["review_scope"]["user_approval_recorded"])
        self.assertEqual(self.analysis, original)
        self.source.write_bytes(b"different source")
        with self.assertRaises(ValidationError):
            build_request(known_brief(), analysis=self.analysis)

    def test_ready_asset_and_evidence_artifact_bytes_are_verified(self):
        asset_path = self.root / "image.fixture"
        asset_path.write_bytes(b"Identity-only asset fixture")
        asset = {"id": "identity", "kind": "image", "purpose": "A planned identity reference",
                 "route": "user", "status": "ready", "path": str(asset_path),
                 "sha256": file_sha256(asset_path), "evidence_ids": [], "reference_ids": []}
        self.analysis["evidence"][0]["artifact"] = {"path": str(asset_path), "sha256": file_sha256(asset_path)}
        request = build_request(known_brief(), analysis=self.analysis, assets=[asset])
        self.assertEqual(request["review_scope"]["ready_asset_bytes_verified"], ["identity"])
        asset_path.write_bytes(b"tampered")
        with self.assertRaises(ValidationError):
            build_request(known_brief(), assets=[asset])
        with self.assertRaises(ValidationError):
            build_request(known_brief(), analysis=self.analysis)

    def test_missing_images_remain_needs_and_no_file_is_fabricated(self):
        need = {"id": "opening", "kind": "image", "purpose": "Establish the initial composition",
                "route": "chat_image", "status": "needed", "prompt": "Create a plain blue cube on a table.",
                "evidence_ids": [], "reference_ids": []}
        request = build_request(known_brief(), assets={"assets": [need]})
        payload = json.loads(request["body"]["messages"][1]["content"])
        self.assertEqual(payload["assets"], [need])
        self.assertEqual(request["review_scope"]["ready_asset_bytes_verified"], [])
        self.assertFalse(request["media_generation_executed"])
        self.assertEqual(list(self.root.iterdir()), [self.source])
        with self.assertRaises(ValidationError):
            build_request(known_brief(), assets=[{**need, "path": "/not-created.png"}])
        with self.assertRaises(ValidationError):
            build_request(known_brief(), assets=[{**need, "kind": "video"}])

    def test_literal_speech_is_data_and_language_is_not_automatically_attested(self):
        speech = 'Olha o que mudou: "agora" é a palavra exata.'
        request = build_request(known_brief(dialogue_text=speech, audio_execution="post", voice_source="new"))
        payload = json.loads(request["body"]["messages"][1]["content"])
        self.assertEqual(payload["editorial_inputs"]["dialogue_text"], speech)
        self.assertEqual(request["brief"]["audio_execution"], "post")
        self.assertNotIn("language_review", request["brief"])


if __name__ == "__main__":
    unittest.main()
