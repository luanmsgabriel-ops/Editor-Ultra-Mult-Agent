"""Real tiny-video regressions for return integrity, timing and attribution."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from editorial_engine.contracts import ValidationError, digest, file_sha256
from editorial_engine.generation.contracts import clip_fingerprint, validate_plan
from editorial_engine.generation.ingest import import_clip, validate_receipt


def plan_fixture(count=1, duration=1, strategy="prompt_only"):
    state = {"description": "A sphere remains centered.", "motion": "The sphere rolls right.",
             "camera": "Fixed camera.", "audio": "Room tone; speech is absent."}
    clips = []
    for index in range(count):
        clip = {"id": f"clip{index + 1}", "purpose": "Show the direction of motion.",
                "duration_s": duration, "use": {"start_s": 0, "end_s": duration},
                "character_ids": [], "location_ids": [], "prop_ids": [], "evidence_ids": [],
                "shots": [{"id": "wide", "start_s": 0, "end_s": duration,
                           "intent": "Establish direction.", "action": "A sphere rolls right.",
                           "composition": "Wide centered view.", "camera": "Fixed.",
                           "performance": "Even tempo.", "lighting": "Soft overhead light."}],
                "dialogue": [], "audio": {"voice_direction": "None.", "ambience": "Room tone.",
                                           "music": "None.", "sfx": "None."},
                "conditioning": [], "post": [], "constraints": []}
        if index == 0:
            clip["initial_state"] = copy.deepcopy(state)
        if index == count - 1:
            clip["final_state"] = copy.deepcopy(state)
        clips.append(clip)
    plan = {"schema": "video-generation-plan/1", "id": "return-study", "revision": 1,
            "author": {"kind": "human", "actor": "test director", "method": "original fixture"},
            "brief": {"mode": "original", "objective": "Demonstrate directional continuity.",
                      "audience": "Test reviewers.", "aspect_ratio": "3:2",
                      "target_duration_s": count * duration,
                      "instruction_language": "en", "dialogue_language": "pt-BR"},
            "bible": {"visual_style": "Neutral studio.", "invariants": [],
                      "characters": [], "locations": [], "props": []},
            "references": [], "evidence": [], "assets": [], "clips": clips,
            "joins": [{"id": f"join{i}", "from": f"clip{i}", "to": f"clip{i + 1}",
                       "kind": "motion_match", "rationale": "Retain the rightward movement.",
                       "execution": "generation", "strategy": strategy, "overlap_s": 0,
                       "outgoing": copy.deepcopy(state), "incoming": copy.deepcopy(state),
                       "match": ["motion direction"]} for i in range(1, count)]}
    return validate_plan(plan)


def observation(scope="continuous_video", **extra):
    return {"actor": "fixture reviewer", "method": "declared synthetic playback review",
            "scope": scope, "description": "A synthetic moving pattern is present.",
            "motion": "Pattern changes across the observed frames.", "camera": "Fixed test raster.",
            "audio": "Not listened to.", **extra}


def reseal(receipt):
    receipt["receipt_sha256"] = digest({k: v for k, v in receipt.items() if k != "receipt_sha256"})
    return receipt


def parent_export(plan, parent):
    frame = parent["selected_frame"]
    item = {"clip_id": "clip2", "clip_fingerprint": clip_fingerprint(plan, "clip2"),
            "prompt": "Continue the sphere motion from the supplied frame.", "settings": {},
            "attachments": [{"role": "start_frame", "field": "image", "status": "ready",
                             "source_clip_id": "clip1", "receipt_sha256": parent["receipt_sha256"],
                             "path": frame["path"], "sha256": frame["sha256"]}],
            "postproduction": [], "dependencies": [{"kind": "returned_clip", "clip_id": "clip1",
                "clip_fingerprint": parent["clip_fingerprint"], "receipt_sha256": parent["receipt_sha256"],
                "path": parent["path"], "sha256": parent["sha256"],
                "selected_frame_sha256": frame["sha256"], "selected_frame": copy.deepcopy(frame)}],
            "issues": [], "status": "ready"}
    item["export_sha256"] = digest(item)
    return item


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and FFprobe are required")
class GenerationIngestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        cls.root = Path(cls.workspace.name)
        cls.video = cls.root / "synthetic.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                        "testsrc2=size=96x64:rate=4:duration=1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(cls.video)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.plan = plan_fixture()

    def receive(self, *, plan=None, clip_id="clip1", video=None, name="receipt", **kwargs):
        return import_clip(plan or self.plan, clip_id, video or self.video,
                           self.directory / name, **kwargs)

    def test_actual_video_clock_and_artifact_hashes_are_measured(self):
        original_sha = file_sha256(self.video)
        receipt = self.receive()
        self.assertEqual(receipt["actual"]["duration"], "1/1")
        self.assertEqual(receipt["actual"]["fps"], "4/1")
        self.assertEqual(receipt["actual"]["frame_count"], 4)
        self.assertEqual((receipt["actual"]["width"], receipt["actual"]["height"]), (96, 64))
        self.assertFalse(receipt["actual"]["audio"])
        self.assertEqual([f["index"] for f in receipt["sampled_frames"]], [0, 3])
        self.assertEqual(receipt["sampled_frames"][-1]["pts"], "3/4")
        self.assertEqual(receipt, json.loads(Path(receipt["receipt_path"]).read_text()))
        self.assertEqual(validate_receipt(receipt, self.plan), receipt)
        self.assertEqual(file_sha256(self.video), original_sha)

    def test_import_never_selects_an_exit_or_approves_the_result_implicitly(self):
        receipt = self.receive(observation=observation())
        self.assertIsNone(receipt["selected_frame"])
        self.assertEqual(receipt["boundary"]["status"], "not_selected")
        self.assertEqual(receipt["verification"]["user_approval"], "unverified")
        self.assertEqual(receipt["verification"]["perceptual_quality"], "unverified")
        self.assertEqual(receipt["verification"]["audio_listening"], "unverified")
        self.assertEqual(receipt["dependency_binding"]["status"], "unverified")

    def test_motion_observation_and_editorial_continuity_acceptance_remain_distinct(self):
        unassessed = self.receive(selected_frame=3, observation=observation())
        self.assertEqual(unassessed["boundary"]["status"], "observed")
        self.assertEqual(unassessed["observation"]["continuity_decision"]["status"], "unassessed")
        for status in ("accept", "revise"):
            observed = observation(continuity_decision={"status": status, "actor": "continuity director",
                                   "reason": "Explicit editorial decision for this synthetic boundary."})
            receipt = self.receive(name=status, selected_frame=3, observation=observed)
            self.assertEqual(receipt["observation"]["continuity_decision"]["status"], status)
            self.assertEqual(receipt["verification"]["user_approval"], "unverified")
            validate_receipt(receipt, self.plan)
        with self.assertRaises(ValidationError):
            self.receive(name="bad", observation=observation(continuity_decision={"status": "approved"}))

    def test_early_exit_selection_requires_explicit_plan_revision_without_trim(self):
        before = copy.deepcopy(self.plan)
        receipt = self.receive(selected_frame=2, observation=observation())
        self.assertEqual(receipt["selected_frame"]["recommended_use_end_s"], 0.75)
        self.assertEqual(receipt["planned_use"]["end_s"], 1)
        self.assertEqual(receipt["actual"]["frame_count"], 4)
        self.assertEqual(receipt["boundary"]["status"], "needs_plan_revision")
        self.assertFalse(receipt["boundary"]["matches_planned_use"])
        self.assertEqual(receipt["boundary"]["delta_s"], -0.25)
        self.assertEqual(self.plan, before)
        self.assertEqual(validate_receipt(receipt, self.plan), receipt)

    def test_explicit_revised_use_can_end_at_the_selected_earlier_frame(self):
        self.plan["clips"][0]["use"]["end_s"] = 0.75
        self.plan["brief"]["target_duration_s"] = 0.75
        receipt = self.receive(selected_frame=2, observation=observation())
        self.assertEqual(receipt["boundary"]["status"], "observed")
        self.assertEqual(receipt["usable"]["unused_tail_s"], 0.25)
        self.assertEqual(receipt["actual"]["duration_s"], 1)

    def test_still_observation_cannot_claim_motion_at_the_boundary(self):
        receipt = self.receive(selected_frame=3, observation=observation("sampled_frames"))
        self.assertTrue(receipt["boundary"]["matches_planned_use"])
        self.assertEqual(receipt["boundary"]["status"], "needs_observation")
        with self.assertRaises(ValidationError):
            self.receive(name="single", selected_frame=3,
                         observation=observation("boundary_window", frame_range={"start_frame": 3, "end_frame": 4}))

    def test_boundary_window_must_cover_selected_frame(self):
        receipt = self.receive(selected_frame=3, observation=observation(
            "boundary_window", frame_range={"start_frame": 0, "end_frame": 2}))
        self.assertEqual(receipt["boundary"]["status"], "needs_observation")
        covered = self.receive(name="covered", selected_frame=3, observation=observation(
            "boundary_window", frame_range={"start_frame": 2, "end_frame": 4}))
        self.assertEqual(covered["boundary"]["status"], "observed")

    def test_actual_shorter_than_planned_use_is_preserved_and_marked_unusable(self):
        plan = plan_fixture(duration=2)
        receipt = self.receive(plan=plan)
        self.assertEqual(receipt["requested_duration_s"], 2)
        self.assertEqual(receipt["actual"]["duration_s"], 1)
        self.assertFalse(receipt["usable"]["covers_planned_use"])
        self.assertEqual(receipt["usable"]["status"], "needs_plan_revision")
        self.assertEqual(receipt["planned_use"]["end_s"], 2)
        validate_receipt(receipt, plan)

    def test_non_frame_aligned_planned_cut_is_not_rounded_silently(self):
        self.plan["clips"][0]["use"]["end_s"] = 0.7
        self.plan["brief"]["target_duration_s"] = 0.7
        receipt = self.receive(selected_frame=2, observation=observation())
        self.assertTrue(receipt["usable"]["covers_planned_use"])
        self.assertFalse(receipt["usable"]["frame_aligned_use"])
        self.assertEqual(receipt["usable"]["status"], "needs_plan_revision")
        self.assertEqual(receipt["planned_use"]["end_s"], 0.7)

    def test_raster_mismatch_does_not_trigger_an_implicit_crop(self):
        self.plan["brief"]["aspect_ratio"] = "9:16"
        original_sha = file_sha256(self.video)
        receipt = self.receive(selected_frame=3, observation=observation())
        self.assertEqual(receipt["usable"]["status"], "requires_conform")
        self.assertIn("actual_raster_aspect_differs_from_plan", receipt["usable"]["issues"])
        self.assertEqual((receipt["actual"]["width"], receipt["actual"]["height"]), (96, 64))
        self.assertEqual(file_sha256(self.video), original_sha)
        validate_receipt(receipt, self.plan)

    def test_display_rotation_is_reported_without_rotating_the_conditioning_frame(self):
        source = self.directory / "rotated.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-display_rotation:v:0", "90",
                        "-i", str(self.video), "-c", "copy", str(source)], check=True)
        receipt = self.receive(video=source)
        self.assertTrue(receipt["actual"]["rotation"])
        self.assertEqual((receipt["actual"]["width"], receipt["actual"]["height"]), (96, 64))
        self.assertIn("display_rotation_requires_explicit_conform", receipt["usable"]["issues"])
        self.assertEqual(receipt["usable"]["status"], "requires_conform")
        validate_receipt(receipt, self.plan)

    def test_longer_audio_does_not_change_the_measured_video_duration_or_attest_listening(self):
        source = self.directory / "with-audio.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(self.video),
                        "-f", "lavfi", "-i", "sine=frequency=400:duration=2:sample_rate=48000",
                        "-c:v", "copy", "-c:a", "aac", str(source)], check=True)
        receipt = self.receive(video=source)
        self.assertTrue(receipt["actual"]["audio"])
        self.assertEqual(receipt["actual"]["duration_s"], 1)
        self.assertGreater(float(receipt["actual"]["container_duration_s"]), 1.5)
        self.assertEqual(receipt["actual"]["audio_streams"][0]["sample_rate"], "48000")
        self.assertEqual(receipt["verification"]["audio_listening"], "unverified")
        validate_receipt(receipt, self.plan)

    def test_changed_source_bytes_invalidate_a_receipt(self):
        source = self.directory / "source.mp4"
        shutil.copyfile(self.video, source)
        receipt = self.receive(video=source)
        with source.open("ab") as stream:
            stream.write(b"changed bytes")
        with self.assertRaises(ValidationError) as caught:
            validate_receipt(receipt, self.plan)
        self.assertEqual(caught.exception.issues[0]["code"], "file_hash_mismatch")

    def test_receipt_mutation_and_resealed_false_metadata_are_rejected(self):
        receipt = self.receive()
        receipt["actual"]["width"] = 192
        with self.assertRaises(ValidationError) as caught:
            validate_receipt(receipt, self.plan)
        self.assertEqual(caught.exception.issues[0]["code"], "receipt_digest")
        reseal(receipt)
        with self.assertRaises(ValidationError) as caught:
            validate_receipt(receipt, self.plan)
        self.assertEqual(caught.exception.issues[0]["code"], "media_metadata")

    def test_rehashed_wrong_frame_pixels_cannot_forge_the_exit(self):
        receipt = self.receive(selected_frame=3, observation=observation())
        first, last = receipt["sampled_frames"]
        self.assertNotEqual(first["pixel_sha256"], last["pixel_sha256"])
        for key in ("path", "sha256", "pixel_sha256"):
            receipt["selected_frame"][key] = first[key]
        reseal(receipt)
        with self.assertRaises(ValidationError) as caught:
            validate_receipt(receipt, self.plan)
        self.assertEqual(caught.exception.issues[0]["code"], "frame_source_pixels")

    def test_tampered_png_and_fake_approval_are_rejected(self):
        receipt = self.receive()
        Path(receipt["sampled_frames"][0]["path"]).write_bytes(b"not png")
        with self.assertRaises(ValidationError):
            validate_receipt(receipt, self.plan)
        receipt["verification"]["user_approval"] = "approved"
        reseal(receipt)
        with self.assertRaises(ValidationError) as caught:
            validate_receipt(receipt, self.plan, verify_files=False)
        self.assertEqual(caught.exception.issues[0]["code"], "receipt_attestation")

    def test_clip_scoped_staleness_does_not_invalidate_an_unrelated_revision(self):
        plan = plan_fixture(count=3)
        receipt = self.receive(plan=plan)
        revised = copy.deepcopy(plan)
        revised["revision"] = 2
        revised["clips"][2]["purpose"] = "Explain the ending."
        self.assertEqual(validate_receipt(receipt, revised, verify_files=False), receipt)
        revised["clips"][0]["shots"][0]["action"] = "The sphere rolls left."
        with self.assertRaises(ValidationError) as caught:
            validate_receipt(receipt, revised, verify_files=False)
        self.assertEqual(caught.exception.issues[0]["code"], "stale_receipt")

    def test_explicit_frame_index_is_checked_and_existing_output_is_preserved(self):
        for value in (True, -1, 4, 1.5):
            with self.subTest(index=value), self.assertRaises(ValidationError):
                self.receive(selected_frame=value)
        receipt = self.receive()
        saved = Path(receipt["receipt_path"]).read_bytes()
        with self.assertRaises(ValidationError) as caught:
            self.receive()
        self.assertEqual(caught.exception.issues[0]["code"], "output_exists")
        self.assertEqual(Path(receipt["receipt_path"]).read_bytes(), saved)

    def test_non_video_probe_failure_does_not_create_a_valid_receipt(self):
        fake = self.directory / "not-a-video.mp4"
        fake.write_text("metadata is not a decoded video")
        with self.assertRaises(ValidationError):
            self.receive(video=fake)
        self.assertFalse((self.directory / "receipt").exists())

    def test_rational_frame_rate_and_last_frame_duration_are_retained(self):
        source = self.directory / "fractional.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                        "testsrc2=size=96x64:rate=30000/1001", "-frames:v", "3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
        plan = plan_fixture(duration=0.1001)
        receipt = self.receive(plan=plan, video=source, selected_frame=2, observation=observation())
        self.assertEqual(receipt["actual"]["fps"], "30000/1001")
        self.assertEqual(receipt["actual"]["duration"], "1001/10000")
        self.assertEqual(receipt["selected_frame"]["pts"], "1001/15000")
        self.assertEqual(receipt["selected_frame"]["duration"], "1001/30000")
        self.assertEqual(receipt["boundary"]["status"], "observed")
        validate_receipt(receipt, plan)

    def test_vfr_is_measured_and_requires_explicit_conform(self):
        source = self.directory / "variable.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-f", "lavfi", "-i",
                        "testsrc2=size=96x64:rate=4:duration=1", "-vf",
                        "select=not(eq(n\\,2))", "-fps_mode", "vfr",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
        plan = plan_fixture(duration=1)
        receipt = self.receive(plan=plan, video=source)
        self.assertEqual(receipt["actual"]["clock"], "vfr")
        self.assertEqual(receipt["actual"]["frame_count"], 3)
        self.assertEqual(receipt["usable"]["status"], "requires_conform")
        self.assertEqual(receipt["actual"]["frame_clock"][2]["pts_s"], 0.75)
        validate_receipt(receipt, plan)

    def test_export_binding_checks_parent_bytes_but_never_claims_provider_input_use(self):
        plan = plan_fixture(count=2, strategy="observed_frame")
        parent = self.receive(plan=plan, name="parent", selected_frame=3, observation=observation())
        export = parent_export(plan, parent)
        child = self.receive(plan=plan, clip_id="clip2", name="child", exported_clip=export)
        self.assertEqual(child["dependency_binding"]["status"], "export_bound")
        self.assertEqual(child["dependency_binding"]["provider_input_use"], "unverified")
        self.assertEqual(child["dependencies"][0]["receipt_sha256"], parent["receipt_sha256"])
        self.assertEqual(validate_receipt(child, plan), child)
        revised = copy.deepcopy(plan)
        revised["clips"][0]["purpose"] = "Use another source action."
        self.assertEqual(clip_fingerprint(plan, "clip2"), clip_fingerprint(revised, "clip2"))
        with self.assertRaises(ValidationError) as caught:
            validate_receipt(child, revised, verify_files=False)
        self.assertEqual(caught.exception.issues[0]["code"], "stale_dependency")

    def test_export_digest_and_parent_selected_frame_are_not_interchangeable(self):
        plan = plan_fixture(count=2, strategy="observed_frame")
        parent = self.receive(plan=plan, name="parent", selected_frame=3, observation=observation())
        export = parent_export(plan, parent)
        export["prompt"] = "Different instruction."
        with self.assertRaises(ValidationError) as caught:
            self.receive(plan=plan, clip_id="clip2", name="child", exported_clip=export)
        self.assertEqual(caught.exception.issues[0]["code"], "export_digest")
        export = parent_export(plan, parent)
        export["dependencies"][0]["selected_frame_sha256"] = "0" * 64
        export["export_sha256"] = digest({k: v for k, v in export.items() if k != "export_sha256"})
        with self.assertRaises(ValidationError) as caught:
            self.receive(plan=plan, clip_id="clip2", name="child", exported_clip=export)
        self.assertEqual(caught.exception.issues[0]["code"], "return_dependency")

    def test_child_without_source_export_has_no_invented_parent_input_evidence(self):
        plan = plan_fixture(count=2, strategy="observed_frame")
        receipt = self.receive(plan=plan, clip_id="clip2")
        self.assertEqual(receipt["dependencies"], [])
        self.assertIsNone(receipt["source_export"])
        self.assertEqual(receipt["dependency_binding"]["status"], "unverified")
        validate_receipt(receipt, plan)

    def test_native_extension_full_sequence_requires_an_explicit_output_mapping(self):
        plan = plan_fixture(count=2, strategy="native_extension")
        parent = self.receive(plan=plan, name="parent")
        item = {"clip_id": "clip2", "clip_fingerprint": clip_fingerprint(plan, "clip2"),
                "prompt": "Extend the supplied video.", "settings": {"extension_output": "full_sequence"},
                "attachments": [{"role": "previous_video", "field": "video", "status": "ready",
                                 "source_clip_id": "clip1", "receipt_sha256": parent["receipt_sha256"],
                                 "path": parent["path"], "sha256": parent["sha256"]}],
                "postproduction": [], "dependencies": [{"kind": "returned_clip", "clip_id": "clip1",
                    "clip_fingerprint": parent["clip_fingerprint"], "receipt_sha256": parent["receipt_sha256"],
                    "path": parent["path"], "sha256": parent["sha256"]}], "issues": [], "status": "draft"}
        item["export_sha256"] = digest(item)
        full = self.receive(plan=plan, clip_id="clip2", name="full", exported_clip=item)
        self.assertEqual(full["output_semantics"]["mode"], "full_sequence")
        self.assertEqual(full["usable"]["status"], "needs_plan_revision")
        self.assertEqual(full["planned_use"], plan["clips"][1]["use"])
        validate_receipt(full, plan)
        unknown = self.receive(plan=plan, clip_id="clip2", name="unknown")
        self.assertEqual(unknown["output_semantics"]["mode"], "unresolved")
        self.assertEqual(unknown["usable"]["status"], "needs_plan_revision")
        item["settings"]["extension_output"] = "appended_clip"
        item["export_sha256"] = digest({k: v for k, v in item.items() if k != "export_sha256"})
        appended = self.receive(plan=plan, clip_id="clip2", name="appended", exported_clip=item)
        self.assertEqual(appended["output_semantics"]["mode"], "appended_clip")
        self.assertEqual(appended["usable"]["status"], "usable")
        self.assertEqual(appended["verification"]["provider_input_use"], "unverified")
        validate_receipt(appended, plan)


if __name__ == "__main__":
    unittest.main()
