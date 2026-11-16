"""Original synthetic fixtures exercise export contracts, not video quality."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from editorial_engine.contracts import ValidationError, digest, file_sha256
from editorial_engine.generation.contracts import clip_fingerprint
from editorial_engine.generation.prompts import compile_pack, render_markdown, validate_profile


def state(description):
    return {"description": description, "motion": "The hand moves slowly toward the map.",
            "camera": "Eye-level static camera.", "audio": "Quiet room tone."}


def plan_fixture(count=2, strategy="prompt_only", overlap=0):
    clips, joins = [], []
    for i in range(count):
        clip = {"id": "clip" + str(i + 1), "purpose": "Show the next step in the route.",
                "duration_s": 10, "use": {"start_s": 0, "end_s": 10},
                "character_ids": ["mara"], "location_ids": ["room"], "prop_ids": ["map"],
                "evidence_ids": [], "constraints": ["Keep the map markings unchanged."],
                "shots": [{"id": "shot" + str(i + 1), "start_s": 0, "end_s": 10,
                           "intent": "Make the route legible.", "action": "Mara traces a route with one finger.",
                           "composition": "Mara and the map share the frame.", "camera": "Hold a medium shot.",
                           "performance": "A calm, focused explanation.", "lighting": "Soft daylight from the left."}],
                "dialogue": [{"speaker_id": "mara", "text": "A próxima parada fica aqui.", "start_s": 1, "end_s": 4,
                              "mode": "on_camera", "delivery": "Natural Brazilian Portuguese."}],
                "audio": {"voice_direction": "Keep Mara's established voice.", "ambience": "Quiet room tone.",
                          "music": "No score.", "sfx": "No added effects."},
                "conditioning": [], "post": []}
        if i == 0:
            clip["initial_state"] = state("Mara holds the map open.")
        if i == count - 1:
            clip["final_state"] = state("Mara rests her finger on the final stop.")
        clips.append(clip)
        if i:
            joins.append({"id": "join" + str(i), "from": "clip" + str(i), "to": clip["id"],
                          "kind": "match on action", "rationale": "Continue the explanation of one route.",
                          "execution": "hybrid" if overlap else "generation", "strategy": strategy,
                          "overlap_s": overlap, "outgoing": state("Finger reaches the blue route marker."),
                          "incoming": state("Finger continues from the blue route marker."),
                          "match": ["Mara's wardrobe", "map orientation", "screen direction"]})
    return {"schema": "video-generation-plan/1", "id": "route-demo", "revision": 1,
            "author": {"kind": "human", "actor": "fixture author", "method": "original synthetic test"},
            "brief": {"mode": "original", "objective": "Explain a short route.", "audience": "Local visitors",
                      "aspect_ratio": "9:16", "target_duration_s": 10 * count - overlap * (count - 1),
                      "instruction_language": "en", "dialogue_language": "pt-BR",
                      "language_review": {"actor": "fixture author", "method": "reviewed synthetic prose",
                                          "instruction_language": "en", "dialogue_language": "pt-BR"}},
            "bible": {"visual_style": "Restrained photographic realism.", "invariants": ["Stable afternoon light."],
                      "characters": [{"id": "mara", "identity": "Mara is a fictional adult with short dark curls.",
                                      "wardrobe": "A cobalt jacket over a white shirt.", "voice": "A clear, warm alto.",
                                      "invariants": ["The jacket remains cobalt."]}],
                      "locations": [{"id": "room", "description": "A bright room with a plain wooden table."}],
                      "props": [{"id": "map", "description": "A folded paper map with one blue route."}]},
            "references": [], "evidence": [], "assets": [], "clips": clips, "joins": joins}


def profile_fixture():
    return {"schema": "video-generation-capabilities/1", "id": "synthetic-test-profile", "tool": "Fixture tool",
            "model": "fixture-model", "mode": "directed-video", "interface": "manual-test-interface",
            "verification": {"status": "verified", "source": "fixture://synthetic-specification", "checked_at": "2026-11-16"},
            "durations_s": [5, 10], "aspect_ratios": ["9:16", "16:9"], "max_prompt_chars": 15000,
            "inputs": {role: {"supported": True, "max_count": count, "field": field}
                       for role, count, field in [("start_frame", 1, "initial_image"), ("end_frame", 1, "final_image"),
                                                  ("identity_image", 2, "identity_images"), ("previous_video", 1, "source_video")]},
            "outputs": {"audio": True, "speech": True}, "multi_shot": True}


def codes(pack, index=0):
    return {issue["code"] for issue in pack["clips"][index]["issues"]}


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.image = self.root / "boundary.png"
        Image.new("RGB", (24, 32), "#2277aa").save(self.image)

    def tearDown(self):
        self.tmp.cleanup()

    def image_asset(self, identifier="boundary"):
        return {"id": identifier, "kind": "image", "purpose": "Shared framing reference.", "route": "user",
                "status": "ready", "path": str(self.image), "sha256": file_sha256(self.image),
                "evidence_ids": [], "reference_ids": []}

    def planned(self, needed=False):
        plan = plan_fixture(strategy="planned_frame")
        asset = self.image_asset()
        if needed:
            asset.update(status="needed", route="chat_image", prompt="Draw an original route planning scene.")
            del asset["path"], asset["sha256"]
        plan["assets"].append(asset)
        plan["joins"][0]["handoff_asset_id"] = asset["id"]
        return plan

    def receipt(self, plan, clip_id="clip1", *, tag="one", selected=True):
        # This helper is used only with the receipt validator stubbed. Ingest's
        # own tests exercise actual probing, frame extraction and source hashes.
        video = self.root / (tag + ".mp4")
        video.write_bytes(tag.encode())
        result = {"schema": "video-generation-result/1", "clip_id": clip_id,
                  "clip_fingerprint": clip_fingerprint(plan, clip_id), "path": str(video), "sha256": file_sha256(video),
                  "actual": {"duration_s": 10}, "usable": {"status": "usable", "covers_planned_use": True},
                  "boundary": {"status": "observed", "matches_planned_use": True},
                  "observation": {"actor": "test viewer", "method": "declared playback review", "scope": "boundary_window",
                                  "description": "Finger reaches the blue mark.", "motion": "Hand travels rightward.",
                                  "camera": "Static", "audio": "Room tone", "frame_range": {"start_frame": 290, "end_frame": 300},
                                  "continuity_decision": {"status": "accept", "actor": "fixture director", "reason": "Synthetic boundary selected for this test."}},
                  "dependencies": []}
        if selected:
            result["selected_frame"] = {"index": 299, "path": str(self.image), "sha256": file_sha256(self.image),
                                        "pts_s": 299 / 30, "duration_s": 1 / 30, "recommended_use_end_s": 10,
                                        "source_sha256": result["sha256"], "source_frame_index": 299}
        result["receipt_sha256"] = digest(result)
        return result

    def test_neutral_draft_is_useful_and_makes_no_execution_claims(self):
        pack = compile_pack(plan_fixture())
        self.assertEqual(pack["status"], "draft")
        self.assertFalse(pack["generation_performed"])
        self.assertFalse(pack["translation_performed"])
        self.assertFalse(pack["capabilities_live_checked"])
        for clip in pack["clips"]:
            self.assertIn("short dark curls", clip["prompt"])
            self.assertIn("cobalt jacket", clip["prompt"])
            self.assertIn("clear, warm alto", clip["prompt"])
            self.assertIn("A próxima parada fica aqui.", clip["prompt"])
            self.assertEqual(clip["settings"]["duration_s"], 10)
            self.assertIn("profile_needed", {i["code"] for i in clip["issues"]})
            self.assertEqual(clip["export_sha256"], digest({k: v for k, v in clip.items() if k != "export_sha256"}))

    def test_ready_export_is_per_clip_without_automatic_approval(self):
        pack = compile_pack(plan_fixture(strategy="observed_frame"), profile=profile_fixture(), ready=True)
        self.assertEqual(pack["status"], "partially_ready")
        self.assertEqual([c["status"] for c in pack["clips"]], ["ready", "blocked"])
        self.assertIn("return_needed", codes(pack, 1))
        self.assertFalse(pack["assembly"]["automatic_approval"])

    def test_planned_shared_image_binds_both_sides(self):
        plan = self.planned()
        plan["clips"][0]["conditioning"] = [{"role": "end_frame", "asset_id": "boundary"}]
        pack = compile_pack(plan, profile=profile_fixture(), ready=True)
        self.assertEqual(pack["status"], "ready")
        left, right = (c["attachments"] for c in pack["clips"])
        self.assertEqual(len(left), 1)
        self.assertEqual([left[0]["role"], right[0]["role"]], ["end_frame", "start_frame"])
        self.assertEqual(left[0]["sha256"], right[0]["sha256"])
        self.assertEqual(left[0]["field"], "final_image")
        self.assertNotIn(str(self.image), pack["clips"][0]["prompt"])

    def test_missing_planned_image_leaves_real_request_without_fake_path(self):
        pack = compile_pack(self.planned(needed=True), profile=profile_fixture(), ready=True)
        self.assertEqual(pack["status"], "blocked")
        self.assertEqual(pack["asset_requests"][0]["route"], "chat_image")
        for clip in pack["clips"]:
            self.assertNotIn("path", clip["attachments"][0])
            self.assertIn("asset_needed", {i["code"] for i in clip["issues"]})

    def test_conflicting_shared_frame_is_rejected(self):
        plan = self.planned()
        other = self.image_asset("other")
        plan["assets"].append(other)
        plan["clips"][1]["conditioning"] = [{"role": "start_frame", "asset_id": "other"}]
        with self.assertRaisesRegex(ValueError, "same shared image"):
            compile_pack(plan)

    def test_file_tampering_blocks_export_and_excludes_unverified_path(self):
        plan = self.planned()
        self.image.write_bytes(b"changed")
        pack = compile_pack(plan, profile=profile_fixture(), ready=True)
        self.assertIn("file_unverified", codes(pack))
        self.assertEqual(pack["clips"][0]["status"], "blocked")
        self.assertNotIn("path", pack["clips"][0]["attachments"][0])

    def test_hash_correct_but_corrupt_image_is_not_ready(self):
        self.image.write_bytes(b"not an image")
        pack = compile_pack(self.planned(), profile=profile_fixture(), ready=True)
        self.assertIn("media_unverified", codes(pack))
        self.assertNotIn("path", pack["clips"][0]["attachments"][0])

    def test_unknown_and_unsupported_input_roles_are_distinct_blockers(self):
        profile = profile_fixture()
        del profile["inputs"]["end_frame"]
        pack = compile_pack(self.planned(), profile=profile, ready=True)
        self.assertIn("input_capability_unknown", codes(pack))
        profile["inputs"]["end_frame"] = {"supported": False, "max_count": 0, "field": ""}
        pack = compile_pack(self.planned(), profile=profile, ready=True)
        self.assertIn("input_unsupported", codes(pack))
        self.assertIsNone(pack["clips"][0]["attachments"][0]["field"])

    def test_profile_rejects_ambiguous_values_without_assuming_support(self):
        profile = profile_fixture()
        profile["inputs"]["start_frame"]["supported"] = "true"
        with self.assertRaises(ValidationError):
            validate_profile(profile)
        profile = profile_fixture()
        profile["verification"]["source"] = ""
        with self.assertRaises(ValidationError):
            validate_profile(profile)
        profile = profile_fixture()
        profile["duration_range_s"] = {"min": 3, "max": 15}
        with self.assertRaises(ValidationError):
            validate_profile(profile)
        del profile["durations_s"]
        self.assertEqual(validate_profile(profile)["duration_range_s"]["max"], 15)

    def test_duration_and_multishot_are_not_universally_supported(self):
        profile = profile_fixture()
        profile["durations_s"] = [5]
        self.assertIn("duration_unsupported", codes(compile_pack(plan_fixture(), profile=profile, ready=True)))
        plan = plan_fixture()
        shot = plan["clips"][0]["shots"][0]
        shot["end_s"] = 5
        second = copy.deepcopy(shot)
        second.update(id="second-shot", start_s=5, end_s=10)
        plan["clips"][0]["shots"].append(second)
        profile = profile_fixture()
        profile["multi_shot"] = None
        self.assertIn("multi_shot_unsupported", codes(compile_pack(plan, profile=profile, ready=True)))

    def test_prompt_limit_never_truncates_or_silently_compresses(self):
        plan, profile = plan_fixture(), profile_fixture()
        original = compile_pack(plan, profile=profile)["clips"][0]["prompt"]
        profile["max_prompt_chars"] = 80
        pack = compile_pack(plan, profile=profile, ready=True)
        self.assertEqual(pack["clips"][0]["prompt"], original)
        self.assertIn("prompt_too_long", codes(pack))
        self.assertEqual(pack["clips"][0]["prompt_chars"], len(original))

    def test_language_review_is_an_attestation_not_translation(self):
        plan = plan_fixture()
        del plan["brief"]["language_review"]
        pack = compile_pack(plan, profile=profile_fixture(), ready=True)
        self.assertIn("language_review_missing", codes(pack))
        self.assertFalse(pack["translation_performed"])
        self.assertIn("A próxima parada fica aqui.", pack["clips"][0]["prompt"])

    def test_exact_post_text_is_kept_out_of_generation_prompt(self):
        plan = plan_fixture()
        plan["clips"][0]["post"] = [{"id": "title", "kind": "text", "brief": "Use the exact title: Próxima estação!",
                                    "start_s": 2, "end_s": 5}]
        pack = compile_pack(plan, profile=profile_fixture(), ready=True)
        self.assertNotIn("Próxima estação!", pack["clips"][0]["prompt"])
        self.assertIn("Próxima estação!", pack["clips"][0]["postproduction"][0]["brief"])

    def test_post_only_asset_has_verified_path_hash_and_markdown_manifest(self):
        plan = plan_fixture()
        plan["assets"] = [self.image_asset("logo")]
        plan["clips"][0]["post"] = [{"id": "logo-overlay", "kind": "logo", "brief": "Place the supplied brand mark in the empty corner.",
                                    "start_s": 7, "end_s": 9, "asset_id": "logo"}]
        pack = compile_pack(plan, profile=profile_fixture(), ready=True)
        self.assertEqual(pack["status"], "ready")
        self.assertEqual(pack["clips"][0]["attachments"], [])
        resource = pack["clips"][0]["post_assets"][0]
        self.assertEqual(resource["asset_id"], "logo")
        self.assertEqual(resource["path"], str(self.image))
        self.assertEqual(resource["sha256"], file_sha256(self.image))
        self.assertIn(str(self.image), render_markdown(pack))
        self.image.write_bytes(b"tampered")
        pack = compile_pack(plan, profile=profile_fixture(), ready=True)
        self.assertEqual(pack["clips"][0]["status"], "blocked")
        self.assertNotIn("path", pack["clips"][0]["post_assets"][0])

    def test_post_voice_can_use_silent_model_but_not_unresolved_lipsync(self):
        plan, profile = plan_fixture(), profile_fixture()
        plan["brief"]["audio_execution"] = "post"
        profile["outputs"] = {"audio": False, "speech": False}
        pack = compile_pack(plan, profile=profile, ready=True)
        self.assertIn("lip_sync_unresolved", codes(pack))
        for clip in plan["clips"]:
            clip["dialogue"][0]["mode"] = "off_screen"
        pack = compile_pack(plan, profile=profile, ready=True)
        self.assertEqual(pack["status"], "ready")
        self.assertNotIn("A próxima parada fica aqui.", pack["clips"][0]["prompt"])
        self.assertEqual(pack["clips"][0]["postproduction"][0]["dialogue"][0]["text"], "A próxima parada fica aqui.")

    def test_nonverbal_generated_audio_still_requires_audio_capability(self):
        plan, profile = plan_fixture(), profile_fixture()
        for clip in plan["clips"]:
            clip["dialogue"] = []
            clip["audio"]["ambience"] = "Wind moves through the open window."
        profile["outputs"] = {"audio": False, "speech": False}
        pack = compile_pack(plan, profile=profile, ready=True)
        self.assertIn("audio_unsupported", codes(pack))
        plan["brief"]["audio_execution"] = "post"
        self.assertEqual(compile_pack(plan, profile=profile, ready=True)["status"], "ready")

    def test_explicit_silent_mode_needs_neither_audio_model_nor_post_voice(self):
        plan, profile = plan_fixture(), profile_fixture()
        plan["brief"]["audio_execution"] = "none"
        profile["outputs"] = {"audio": False, "speech": False}
        for clip in plan["clips"]:
            clip["dialogue"] = []
        pack = compile_pack(plan, profile=profile, ready=True)
        self.assertEqual(pack["status"], "ready")
        for clip in pack["clips"]:
            self.assertNotIn("AUDIO", clip["prompt"])
            self.assertNotIn("clear, warm alto", clip["prompt"])
            self.assertNotIn("Quiet room tone", clip["prompt"])
            self.assertFalse(any(item["kind"] == "audio" for item in clip["postproduction"]))

    def test_assembly_accounts_for_overlaps(self):
        pack = compile_pack(plan_fixture(count=3, overlap=0.5))
        self.assertEqual(pack["assembly"]["generated_duration_s"], 30)
        self.assertEqual(pack["assembly"]["final_duration_s"], 29)
        self.assertEqual(pack["assembly"]["timeline"][1]["start_s"], 9.5)

    def test_unrelated_clip_change_and_revision_do_not_invalidate_first_export(self):
        original = plan_fixture(count=3)
        changed = copy.deepcopy(original)
        changed["revision"] += 1
        changed["clips"][2]["shots"][0]["performance"] = "A more deliberate delivery."
        before, after = [compile_pack(p, profile=profile_fixture()) for p in (original, changed)]
        self.assertEqual(before["clips"][0]["export_sha256"], after["clips"][0]["export_sha256"])
        self.assertNotEqual(before["clips"][2]["export_sha256"], after["clips"][2]["export_sha256"])
        self.assertNotEqual(before["plan_sha256"], after["plan_sha256"])

    @patch("editorial_engine.generation.prompts._validate_return", side_effect=lambda receipt, plan, clip_id: copy.deepcopy(receipt))
    def test_observed_frame_requires_motion_review_and_matching_use(self, _validator):
        plan = plan_fixture(strategy="observed_frame")
        receipt = self.receipt(plan)
        pack = compile_pack(plan, profile=profile_fixture(), returns=[receipt], ready=True)
        self.assertEqual(pack["status"], "ready")
        self.assertEqual(pack["clips"][1]["attachments"][0]["sha256"], file_sha256(self.image))
        self.assertEqual(pack["clips"][1]["dependencies"][0]["receipt_sha256"], receipt["receipt_sha256"])
        self.assertIn("selected_frame", pack["clips"][1]["dependencies"][0])
        receipt["observation"]["continuity_decision"]["status"] = "unassessed"
        self.assertIn("continuity_not_accepted", codes(compile_pack(plan, profile=profile_fixture(), returns=[receipt], ready=True), 1))
        receipt["observation"]["continuity_decision"]["status"] = "accept"
        receipt["observation"]["scope"] = "sampled_frames"
        pack = compile_pack(plan, profile=profile_fixture(), returns=[receipt], ready=True)
        self.assertIn("motion_observation_needed", codes(pack, 1))
        receipt["selected_frame"]["recommended_use_end_s"] = 9.5
        self.assertIn("selected_frame_use_mismatch", codes(compile_pack(plan, profile=profile_fixture(), returns=[receipt], ready=True), 1))

    @patch("editorial_engine.generation.prompts._validate_return", side_effect=lambda receipt, plan, clip_id: copy.deepcopy(receipt))
    def test_actual_parent_receipt_bytes_participate_in_child_export_hash(self, _validator):
        plan = plan_fixture(strategy="observed_frame")
        first, second = self.receipt(plan), self.receipt(plan, tag="second")
        one, two = [compile_pack(plan, profile=profile_fixture(), returns=[r], ready=True) for r in (first, second)]
        self.assertEqual(one["clips"][1]["clip_fingerprint"], two["clips"][1]["clip_fingerprint"])
        self.assertNotEqual(one["clips"][1]["export_sha256"], two["clips"][1]["export_sha256"])

    @patch("editorial_engine.generation.prompts._validate_return", side_effect=lambda receipt, plan, clip_id: copy.deepcopy(receipt))
    def test_stale_receipt_chain_blocks_downstream_generation(self, _validator):
        plan = plan_fixture(count=3, strategy="observed_frame")
        parent = self.receipt(plan)
        child = self.receipt(plan, "clip2", tag="child")
        child["dependencies"] = [{"clip_id": "clip1", "receipt_sha256": "0" * 64}]
        pack = compile_pack(plan, profile=profile_fixture(), returns=[parent, child], ready=True)
        self.assertEqual(pack["clips"][1]["status"], "ready")
        self.assertEqual(pack["clips"][2]["status"], "blocked")
        self.assertIn("return_dependency_stale", codes(pack, 2))

    @patch("editorial_engine.generation.prompts._validate_return", side_effect=lambda receipt, plan, clip_id: copy.deepcopy(receipt))
    def test_parent_receipt_hash_alone_does_not_authorize_another_frame(self, _validator):
        plan = plan_fixture(count=3, strategy="observed_frame")
        parent = self.receipt(plan)
        exported = compile_pack(plan, profile=profile_fixture(), returns=[parent], ready=True)["clips"][1]
        child = self.receipt(plan, "clip2", tag="child")
        child["dependencies"] = copy.deepcopy(exported["dependencies"])
        child["dependencies"][0]["selected_frame"]["index"] = 298
        self.assertEqual(child["dependencies"][0]["receipt_sha256"], parent["receipt_sha256"])
        pack = compile_pack(plan, profile=profile_fixture(), returns=[parent, child], ready=True)
        self.assertEqual(pack["clips"][2]["status"], "blocked")
        self.assertIn("return_dependency_stale", codes(pack, 2))

    @patch("editorial_engine.generation.prompts._validate_return", side_effect=ValueError("Stale source or clip fingerprint"))
    def test_invalid_return_is_a_precise_blocker_without_fake_frame(self, _validator):
        plan = plan_fixture(strategy="observed_frame")
        pack = compile_pack(plan, profile=profile_fixture(), returns=[self.receipt(plan)], ready=True)
        self.assertIn("return_invalid", codes(pack, 1))
        self.assertNotIn("path", pack["clips"][1]["attachments"][0])

    @patch("editorial_engine.generation.prompts._validate_return", side_effect=lambda receipt, plan, clip_id: copy.deepcopy(receipt))
    def test_native_extension_requires_explicit_output_semantics(self, _validator):
        plan, profile = plan_fixture(strategy="native_extension"), profile_fixture()
        receipt = self.receipt(plan, selected=False)
        pack = compile_pack(plan, profile=profile, returns=[receipt], ready=True)
        self.assertIn("extension_output_unresolved", codes(pack, 1))
        profile["extension_output"] = "appended_clip"
        pack = compile_pack(plan, profile=profile, returns=[receipt], ready=True)
        self.assertEqual(pack["status"], "ready")
        self.assertEqual(pack["clips"][1]["attachments"][0]["role"], "previous_video")
        profile["extension_output"] = "full_sequence"
        self.assertEqual(compile_pack(plan, profile=profile, returns=[receipt], ready=True)["clips"][1]["status"], "blocked")

    def test_markdown_contains_complete_prompts_and_safe_fences(self):
        plan = plan_fixture()
        plan["clips"][0]["constraints"].append("Keep this literal marker: ```.")
        pack = compile_pack(plan)
        text = render_markdown(pack)
        for clip in pack["clips"]:
            self.assertIn(clip["prompt"], text)
        self.assertIn("````", text)
        self.assertIn("### Attachments", text)
        self.assertIn("### Postproduction", text)


if __name__ == "__main__":
    unittest.main()
