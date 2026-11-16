"""Meaningful contract regressions; fixture bytes are not video-quality tests."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

from editorial_engine import (
    ValidationError, add_review, apply_patch, build_plan, digest, file_sha256,
    new_review, validate_analysis, validate_catalog, validate_plan,
)


class EngineFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = self.root / "source.fixture"
        source.write_bytes(b"source identity fixture; not a decoded video")
        proof = self.root / "verification.json"
        proof.write_text('{"test_only":true,"method":"fixture attestation"}')
        self.source_sha = file_sha256(source)
        self.proof = {"by": "test-fixture", "method": "fixture attestation only",
                      "artifact_path": str(proof), "artifact_sha256": file_sha256(proof)}
        self.analysis = {
            "schema_version": "1.0",
            "sources": [{"id": "source", "sha256": self.source_sha, "path": str(source),
                         "duration_s": 8.0, "fps": "30/1", "frame_count": 240}],
            "evidence": [
                {"id": evidence_id, **self.ref(0, 4), "kind": kind, "observation": observation,
                 "provenance": {"kind": "human", "actor": "fixture reviewer", "method": "annotated test case"}}
                for evidence_id, kind, observation in [
                    ("visual", "visual", "Presenter points at the available right side."),
                    ("speech", "transcript", "The sentence explains a comparison."),
                ]
            ],
            "events": [{"id": "event", **self.ref(0, 4), "intent": "Clarify the comparison",
                        "evidence_ids": ["visual", "speech"],
                        "opportunities": [{"id": "reveal", "function": "reveal", "why": "Gesture supports a spatial reveal"}]}],
            "capabilities": [],
        }
        self.catalog = {"schema_version": "1.0", "effects": [
            self.effect("visual", "visual", "foreground", "draw", ["reveal", "emphasis"]),
            self.effect("audio", "audio", "audio.transient", "mix", ["emphasis"]),
        ]}
        self.catalog["effects"][1]["parameters"] = {"gain_db": {"type": "number", "minimum": -40, "maximum": -3, "required": True}}
        self.add_capability("draw", "renderer:fixture:draw")
        self.add_capability("mix", "renderer:fixture:mix")

    def ref(self, start, end):
        return {"source_id": "source", "source_sha256": self.source_sha, "clock": "source",
                "interval": {"start_s": start, "end_s": end}}

    def effect(self, effect_id, modality, channel, operation, functions):
        return {"id": effect_id, "version": "test-only", "status": "ready", "modality": modality,
                "functions": functions, "renderer": {"name": "fixture", "operation": operation},
                "requirements": [], "anchors": ["screen", "none"], "binding_requirements": {},
                "parameters": {"text": {"type": "string", "required": True}}, "occupied_channels": [channel]}

    def add_capability(self, capability_id, name, start=0, end=8, status="verified"):
        item = {"id": capability_id, "name": name, **self.ref(start, end), "status": status,
                "evidence_ids": ["visual"], "verification": copy.deepcopy(self.proof)}
        self.analysis["capabilities"].append(item)
        return item

    def candidate(self, proposal_id="visual-choice", effect_id="visual", score=0.8, **overrides):
        result = {"id": proposal_id, "event_id": "event", "effect_id": effect_id, **self.ref(0, 4),
                  "evidence_ids": ["visual", "speech"], "why": "The observed gesture supports this comparison.",
                  "scores": {key: score for key in ("intent_fit", "visual_fit", "style_fit", "timing_fit")},
                  "score_provenance": {"kind": "model", "actor": "test proposal provider", "method": "explicit fixture proposal"},
                  "anchor": {"space": "screen"}, "bindings": {}, "params": {"text": "Compare"},
                  "addresses": ["reveal"]}
        if effect_id == "audio":
            result.update({"anchor": {"space": "none"}, "params": {"gain_db": -15}, "addresses": []})
        if effect_id == "preserve":
            result.update({"params": {}, "anchor": {"space": "none"}, "addresses": []})
        result.update(overrides)
        return result

    def plan(self, candidates=None, **kwargs):
        return build_plan(self.analysis, self.catalog,
                          {"schema_version": "1.0", "candidates": candidates if candidates is not None else [self.candidate()]}, **kwargs)

    def codes(self, plan):
        return {issue["code"] for item in plan["discarded"] for issue in item["issues"]}

    def second_event(self):
        evidence = copy.deepcopy(self.analysis["evidence"][0])
        evidence.update({"id": "visual-second", **self.ref(4, 8)})
        self.analysis["evidence"].append(evidence)
        event = copy.deepcopy(self.analysis["events"][0])
        event.update({"id": "event-second", **self.ref(4, 8), "evidence_ids": ["visual-second"]})
        self.analysis["events"].append(event)


class EditorialPlanningTests(EngineFixture):
    def test_empty_proposals_do_not_invent_semantic_understanding(self):
        plan = self.plan([])
        self.assertEqual(plan["decisions"], [])
        self.assertEqual(plan["unresolved_events"], ["event"])
        self.assertEqual(len(plan["missed_opportunities"]), 1)
        self.assertFalse(plan["validation"]["executable"])

    def test_contract_only_plan_never_claims_file_or_perceptual_verification(self):
        plan = self.plan()
        self.assertEqual(len(plan["decisions"]), 1)
        self.assertFalse(plan["validation"]["executable"])
        self.assertFalse(plan["validation"]["file_integrity_verified"])
        self.assertEqual(plan["planned_opportunities"][0]["status"], "planned_not_render_verified")

    def test_source_and_verification_artifact_hashes_are_checked(self):
        plan = self.plan(verify_files=True)
        self.assertTrue(plan["validation"]["executable"])
        Path(self.proof["artifact_path"]).write_text("changed proof")
        with self.assertRaises(ValidationError) as error:
            self.plan(verify_files=True)
        self.assertEqual(error.exception.issues[0]["code"], "file_hash_mismatch")

    def test_source_bytes_change_invalidates_the_plan(self):
        plan = self.plan(verify_files=True)
        Path(self.analysis["sources"][0]["path"]).write_bytes(b"changed source")
        with self.assertRaises(ValidationError):
            validate_plan(plan, self.analysis, self.catalog, verify_files=True)

    def test_invented_evidence_is_rejected_even_with_perfect_scores(self):
        plan = self.plan([self.candidate(evidence_ids=["invented"], score=1)])
        self.assertEqual(plan["decisions"], [])
        self.assertIn("unknown_evidence", self.codes(plan))

    def test_wrong_clock_and_hash_are_not_repaired_silently(self):
        plan = self.plan([self.candidate("wrong-clock", clock="output"),
                          self.candidate("wrong-hash", source_sha256="0" * 64)])
        self.assertEqual(plan["decisions"], [])
        self.assertEqual(self.codes(plan), {"clock_mismatch", "source_hash_mismatch"})

    def test_evidence_outside_event_cannot_be_borrowed(self):
        self.second_event()
        plan = self.plan([self.candidate(evidence_ids=["visual-second"])])
        self.assertIn("unbound_evidence", self.codes(plan))

    def test_interval_outside_original_source_is_rejected(self):
        plan = self.plan([self.candidate(interval={"start_s": 0, "end_s": 9})])
        self.assertIn("outside_source", self.codes(plan))

    def test_unknown_renderer_availability_is_not_ready(self):
        self.analysis["capabilities"][0]["status"] = "unknown"
        plan = self.plan([self.candidate(), self.candidate("fallback", "preserve")])
        self.assertIn("missing_capability", self.codes(plan))
        self.assertEqual([item["effect_id"] for item in plan["decisions"]], ["preserve"])
        self.assertEqual(plan["missed_opportunities"][0]["reason"], "preserved_with_reason")

    def test_renderer_operation_gate_is_mandatory_even_when_manifest_omits_it(self):
        self.analysis["capabilities"] = []
        plan = self.plan()
        self.assertIn("missing_capability", self.codes(plan))

    def test_partial_tracking_and_mask_proofs_cannot_authorize_full_effect(self):
        effect = self.catalog["effects"][0]
        effect.update({"anchors": ["hand"], "binding_requirements": {"matte": "subject_mask"}})
        self.add_capability("hand", "hand_tracking", 0, 2)
        self.add_capability("matte", "subject_mask")
        candidate = self.candidate(anchor={"space": "hand", "capability_id": "hand"}, bindings={"matte": "matte"})
        self.assertIn("anchor_unverified", self.codes(self.plan([candidate])))
        self.analysis["capabilities"][-2]["interval"]["end_s"] = 4
        self.analysis["capabilities"][-1]["status"] = "failed"
        self.assertIn("binding_unverified", self.codes(self.plan([candidate])))

    def test_camera_anchor_requires_camera_solve_not_depth_estimate(self):
        self.catalog["effects"][0]["anchors"] = ["world"]
        self.add_capability("depth", "monocular_depth")
        candidate = self.candidate(anchor={"space": "world", "capability_id": "depth"})
        self.assertIn("anchor_unverified", self.codes(self.plan([candidate])))

    def test_draft_effect_and_undeclared_parameters_are_rejected(self):
        self.catalog["effects"][0]["status"] = "draft"
        self.assertIn("effect_not_ready", self.codes(self.plan()))
        self.catalog["effects"][0]["status"] = "ready"
        self.assertIn("unknown_parameter", self.codes(self.plan([self.candidate(params={"text": "Compare", "random_effect": True})])))

    def test_audio_and_visual_can_coexist_in_one_event(self):
        plan = self.plan([self.candidate(), self.candidate("impact", "audio")])
        self.assertEqual({item["effect_id"] for item in plan["decisions"]}, {"visual", "audio"})

    def test_same_channel_and_region_conflict_keeps_better_supported_choice(self):
        plan = self.plan([self.candidate("weaker", score=0.65), self.candidate("stronger", score=0.9)])
        self.assertEqual(plan["decisions"][0]["proposal"]["id"], "stronger")
        self.assertIn("occupied_channel", self.codes(plan))
        self.assertEqual(plan["discarded"][0]["blocked_by"], ["stronger"])

    def test_nonoverlapping_regions_can_share_visual_channel(self):
        plan = self.plan([self.candidate("left", region=[0, 0, 0.4, 1]), self.candidate("right", region=[0.6, 0, 0.4, 1])])
        self.assertEqual(len(plan["decisions"]), 2)

    def test_half_open_intervals_do_not_create_false_conflict(self):
        plan = self.plan([self.candidate("first", interval={"start_s": 0, "end_s": 2}),
                          self.candidate("second", interval={"start_s": 2, "end_s": 4})])
        self.assertEqual(len(plan["decisions"]), 2)

    def test_declared_conflict_applies_across_audio_and_visual_channels(self):
        self.catalog["effects"][0]["conflicts"] = ["audio"]
        plan = self.plan([self.candidate(score=0.95), self.candidate("impact", "audio", score=0.7)])
        self.assertEqual(len(plan["decisions"]), 1)
        self.assertIn("declared_effect_conflict", self.codes(plan))

    def test_density_limit_checks_simultaneous_layers_not_total_count(self):
        alternative = copy.deepcopy(self.catalog["effects"][0])
        alternative.update({"id": "second-visual", "occupied_channels": ["background"]})
        self.catalog["effects"].append(alternative)
        plan = self.plan([self.candidate(), self.candidate("background", "second-visual")], policy={"max_visual_layers": 1})
        self.assertIn("visual_layer_limit", self.codes(plan))

    def test_repetition_limit_and_missed_opportunities_are_explicit(self):
        self.second_event()
        second = self.candidate("second", score=0.7, event_id="event-second", evidence_ids=["visual-second"], **self.ref(4, 8))
        plan = self.plan([self.candidate(score=0.95), second], policy={"max_effect_repetitions": 1})
        self.assertIn("repetition_limit", self.codes(plan))
        self.assertIn("event-second", plan["unresolved_events"])
        self.assertEqual(plan["missed_opportunities"][0]["event_id"], "event-second")

    def test_opportunity_id_alone_does_not_prove_editorial_fit(self):
        plan = self.plan([self.candidate("impact", "audio", addresses=["reveal"])])
        self.assertIn("opportunity_function_mismatch", self.codes(plan))
        self.assertEqual(plan["planned_opportunities"], [])

    def test_preserve_does_not_win_merely_for_higher_score(self):
        plan = self.plan([self.candidate(score=0.7), self.candidate("preserve", "preserve", score=1)])
        self.assertEqual([item["effect_id"] for item in plan["decisions"]], ["visual"])
        self.assertIn("preserve_not_needed", self.codes(plan))

    def test_declared_editorial_threshold_cannot_be_bypassed_with_bonus(self):
        plan = self.plan([self.candidate(score=0.1)], policy={"opportunity_bonus": 1})
        self.assertIn("below_editorial_threshold", self.codes(plan))

    def test_fps_and_frame_count_must_share_a_coherent_clock(self):
        self.analysis["sources"][0].update({"fps": "30000/1001", "frame_count": 240, "duration_s": 8.008})
        validate_analysis(self.analysis)
        self.analysis["sources"][0]["frame_count"] = 200
        with self.assertRaises(ValidationError) as error:
            validate_analysis(self.analysis)
        self.assertEqual(error.exception.issues[0]["code"], "frame_clock_mismatch")

    def test_nan_and_boolean_scores_are_invalid(self):
        candidate = self.candidate()
        candidate["scores"]["intent_fit"] = True
        self.assertIn("type", self.codes(self.plan([candidate])))
        candidate["scores"]["intent_fit"] = float("nan")
        with self.assertRaises(ValidationError):
            self.plan([candidate])

    def test_plan_replay_rejects_forged_choice_even_after_digest_recalculation(self):
        plan = self.plan()
        plan["decisions"][0]["operation"]["params"]["text"] = "invented mutation"
        plan["plan_sha256"] = digest({key: value for key, value in plan.items() if key != "plan_sha256"})
        with self.assertRaises(ValidationError) as error:
            validate_plan(plan, self.analysis, self.catalog)
        self.assertEqual(error.exception.issues[0]["code"], "plan_replay_mismatch")

    def test_plan_cannot_forge_user_approval(self):
        plan = self.plan()
        plan["validation"]["approved_by_user"] = True
        plan["plan_sha256"] = digest({key: value for key, value in plan.items() if key != "plan_sha256"})
        with self.assertRaises(ValidationError):
            validate_plan(plan, self.analysis, self.catalog)


class EditorialReviewTests(EngineFixture):
    def setUp(self):
        super().setUp()
        self.current_plan = self.plan(verify_files=True)
        output = self.root / "render.fixture"
        output.write_bytes(b"render identity fixture; not a perceptual playback test")
        self.artifact = {"path": str(output), "sha256": file_sha256(output),
                         "plan_sha256": self.current_plan["plan_sha256"], "duration_s": 4.0, "clock": "output"}

    def report(self, identifier="review", kind="human", mode="continuous", checks=None):
        return {"id": identifier, "reviewer": {"kind": kind, "actor": "test reviewer", "method": "explicit fixture attestation"},
                "plan_sha256": self.current_plan["plan_sha256"], "render_sha256": self.artifact["sha256"],
                "checks": checks if checks is not None else {key: {"status": "pass", "mode": mode,
                          "coverage": [{"start_s": 0, "end_s": 4}], "notes": "Test fixture only; no real playback claimed."}
                          for key in ("technical", "motion", "audio", "editorial")}}

    def patch(self, text="Revised emphasis"):
        decision = self.current_plan["decisions"][0]
        replacement = copy.deepcopy(decision["proposal"])
        replacement["params"]["text"] = text
        return {"base_plan_sha256": self.current_plan["plan_sha256"], "base_version": self.current_plan["version"],
                "reason": "Localized correction requested by the reviewer",
                "updates": [{"decision_id": decision["id"], "expected_revision": decision["revision"], "proposal": replacement}]}

    def test_contract_only_plan_cannot_initialize_render_review(self):
        with self.assertRaises(ValidationError):
            new_review(self.plan(), self.artifact)

    def test_sampling_and_automated_checks_do_not_imply_perceptual_playback(self):
        state = new_review(self.current_plan, self.artifact)
        state = add_review(state, self.current_plan, self.artifact, self.report(mode="sampled"))
        self.assertEqual(state["perceptual"], "unverified")
        self.assertFalse(state["can_finalize"])
        state = add_review(state, self.current_plan, self.artifact, self.report("automated", kind="tool"))
        self.assertEqual(state["technical"], "passed")
        self.assertEqual(state["perceptual"], "unverified")

    def test_continuous_review_stays_separate_from_user_approval(self):
        state = add_review(new_review(self.current_plan, self.artifact), self.current_plan, self.artifact, self.report())
        self.assertEqual(state["technical"], "passed")
        self.assertEqual(state["perceptual"], "passed")
        self.assertEqual(state["user_approval"], "pending")
        self.assertEqual(state["status"], "reviewed")

    def test_gaps_in_coverage_are_not_full_playback(self):
        report = self.report()
        report["checks"]["audio"]["coverage"] = [{"start_s": 0, "end_s": 1}, {"start_s": 2, "end_s": 4}]
        state = add_review(new_review(self.current_plan, self.artifact), self.current_plan, self.artifact, report)
        self.assertEqual(state["coverage"]["audio"]["covered_seconds"], 3)
        self.assertEqual(state["perceptual"], "unverified")

    def test_model_cannot_record_user_approval(self):
        report = self.report(kind="model")
        report["approval"] = {"status": "approved", "confirmation": "Looks acceptable"}
        with self.assertRaises(ValidationError) as error:
            add_review(new_review(self.current_plan, self.artifact), self.current_plan, self.artifact, report)
        self.assertEqual(error.exception.issues[0]["code"], "approval_provenance")

    def test_explicit_user_response_binds_to_current_render(self):
        state = add_review(new_review(self.current_plan, self.artifact), self.current_plan, self.artifact, self.report())
        report = self.report("user", kind="user", checks={})
        report["approval"] = {"status": "approved", "confirmation": "Approved this rendered version"}
        state = add_review(state, self.current_plan, self.artifact, report)
        self.assertEqual(state["status"], "user_approved")

    def test_changed_render_bytes_invalidate_previous_review(self):
        state = add_review(new_review(self.current_plan, self.artifact), self.current_plan, self.artifact, self.report())
        Path(self.artifact["path"]).write_bytes(b"replacement render bytes")
        with self.assertRaises(ValidationError):
            add_review(state, self.current_plan, self.artifact, self.report("new"))
        self.artifact["sha256"] = file_sha256(self.artifact["path"])
        state = add_review(state, self.current_plan, self.artifact, self.report("new", mode="sampled"))
        self.assertEqual(state["perceptual"], "unverified")
        self.assertEqual(len(state["archived_reviews"]), 1)
        self.assertEqual(len(state["reports"]), 1)

    def test_source_clock_cannot_be_used_as_render_review_clock(self):
        report = self.report()
        report["clock"] = "source"
        with self.assertRaises(ValidationError):
            add_review(new_review(self.current_plan, self.artifact), self.current_plan, self.artifact, report)

    def test_partial_preview_is_not_full_plan_approval(self):
        self.current_plan = self.plan([self.candidate(), self.candidate("audio", "audio")], verify_files=True)
        self.artifact.update({"plan_sha256": self.current_plan["plan_sha256"], "decision_ids": [self.current_plan["decisions"][0]["id"]]})
        state = add_review(new_review(self.current_plan, self.artifact), self.current_plan, self.artifact, self.report())
        self.assertTrue(state["can_accept_render"])
        self.assertFalse(state["can_finalize"])
        self.assertEqual(state["status"], "reviewed_partial")

    def test_local_patch_versions_plan_and_invalidates_all_old_approval(self):
        state = add_review(new_review(self.current_plan, self.artifact), self.current_plan, self.artifact, self.report())
        patched = apply_patch(self.current_plan, self.patch(), self.analysis, self.catalog, state)
        self.assertEqual(patched["plan"]["version"], 2)
        self.assertNotEqual(patched["plan"]["plan_sha256"], self.current_plan["plan_sha256"])
        self.assertEqual(patched["review"]["status"], "stale")
        self.assertEqual(patched["review"]["retry_count"], 1)
        self.assertFalse(patched["review"]["can_finalize"])
        self.assertIsNone(patched["review"]["render_sha256"])
        validate_plan(patched["plan"], self.analysis, self.catalog, verify_files=True)

    def test_stale_patch_and_out_of_scope_replacement_are_rejected(self):
        patch = self.patch()
        patch["base_version"] = 100
        with self.assertRaises(ValidationError):
            apply_patch(self.current_plan, patch, self.analysis, self.catalog)
        patch = self.patch()
        patch["updates"][0]["proposal"]["event_id"] = "another-event"
        with self.assertRaises(ValidationError) as error:
            apply_patch(self.current_plan, patch, self.analysis, self.catalog)
        self.assertEqual(error.exception.issues[0]["code"], "patch_scope")

    def test_patch_cannot_silently_discard_its_replacement(self):
        patch = self.patch()
        patch["updates"][0]["proposal"]["scores"] = {key: 0.1 for key in ("intent_fit", "visual_fit", "style_fit", "timing_fit")}
        with self.assertRaises(ValidationError) as error:
            apply_patch(self.current_plan, patch, self.analysis, self.catalog)
        self.assertEqual(error.exception.issues[0]["code"], "invalid_patch_selection")

    def test_patch_cannot_drop_an_unlisted_companion_in_same_event(self):
        replacement_effect = copy.deepcopy(self.catalog["effects"][0])
        replacement_effect.update({"id": "exclusive-visual", "conflicts": ["audio"]})
        self.catalog["effects"].append(replacement_effect)
        self.current_plan = self.plan([self.candidate(score=0.9), self.candidate("z-audio", "audio", score=0.8)], verify_files=True)
        patch = self.patch()
        patch["updates"][0]["proposal"]["effect_id"] = "exclusive-visual"
        with self.assertRaises(ValidationError) as error:
            apply_patch(self.current_plan, patch, self.analysis, self.catalog)
        self.assertEqual(error.exception.issues[0]["code"], "nonlocal_patch")

    def test_history_cannot_change_clock_or_omit_provenance_fields(self):
        patched = apply_patch(self.current_plan, self.patch(), self.analysis, self.catalog)["plan"]
        patched["history"][0]["base_plan_sha256"] = "missing"
        patched["plan_sha256"] = digest({key: value for key, value in patched.items() if key != "plan_sha256"})
        with self.assertRaises(ValidationError) as error:
            validate_plan(patched, self.analysis, self.catalog)
        self.assertEqual(error.exception.issues[0]["code"], "sha256")

    def test_review_repair_budget_cannot_be_reset_by_new_review(self):
        state = new_review(self.current_plan, self.artifact, max_retries=1)
        patched = apply_patch(self.current_plan, self.patch(), self.analysis, self.catalog, state)
        self.current_plan = patched["plan"]
        self.artifact["plan_sha256"] = self.current_plan["plan_sha256"]
        continued = new_review(self.current_plan, self.artifact, max_retries=1)
        self.assertEqual(continued["retry_count"], 1)
        with self.assertRaises(ValidationError) as error:
            apply_patch(self.current_plan, self.patch(), self.analysis, self.catalog, continued)
        self.assertEqual(error.exception.issues[0]["code"], "retry_limit")


if __name__ == "__main__":
    unittest.main()
