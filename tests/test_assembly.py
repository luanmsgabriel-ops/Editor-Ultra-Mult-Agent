"""Real color/tone assembly checks: explicit edits, clocks and stale inputs."""

import copy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import numpy as np

from editorial_engine.assembly import from_generation, render_assembly, validate_assembly
from editorial_engine.contracts import ValidationError, digest, file_sha256
from editorial_engine.generation.ingest import import_clip
from editorial_engine.review import new_review
import test_generation_ingest as generation_fixtures


def video(path, color, *, rate=10, size="96x64", tone=None, duration=1):
    args = ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
            f"color={color}:s={size}:r={rate}:d={duration}"]
    if tone:
        args += ["-f", "lavfi", "-i", f"sine=frequency={tone}:sample_rate=48000:duration={duration}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if tone:
        args += ["-c:a", "aac", "-b:a", "128k"]
    subprocess.run([*args, str(path)], capture_output=True, check=True)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and FFprobe are required")
class AssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        cls.root = Path(cls.workspace.name)
        cls.red, cls.blue, cls.green, cls.square = (cls.root / name for name in ("red.mp4", "blue.mp4", "green.mp4", "square.mp4"))
        video(cls.red, "red", tone=440, duration=1.2)
        video(cls.blue, "blue")
        video(cls.green, "lime", tone=880)
        video(cls.square, "blue", size="64x64", rate=20)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.work.cleanup)
        self.directory = Path(self.work.name)

    def plan(self, paths=None, *, transition="cut", overlap=0):
        paths = paths or [self.red, self.blue]
        clips = [{"id": f"clip{i}", "source_id": f"source{i}", "use": {"start_s": 0, "end_s": 1},
                  "fit": "reject", "reframe_fps": "reject", "audio": {"mode": "source", "gain_db": 0}}
                 for i in range(len(paths))]
        return {"schema": "video-assembly/1", "id": "assembly-fixture", "revision": 1,
                "sources": [{"id": f"source{i}", "path": str(path), "sha256": file_sha256(path)} for i, path in enumerate(paths)],
                "clips": clips, "joins": [{"from": f"clip{i}", "to": f"clip{i + 1}", "transition": transition,
                                           "duration_s": overlap} for i in range(len(paths) - 1)],
                "output": {"fps": "10/1", "width": 96, "height": 64,
                           "audio": {"mode": "source", "sample_rate": 48000, "channels": 2, "missing": "silence"}}}

    def frames(self, path):
        raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
                                       "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
        return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 64, 96, 3)

    def pcm(self, path):
        raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0",
                                       "-ac", "2", "-ar", "48000", "-f", "f32le", "pipe:1"])
        return np.frombuffer(raw, dtype="<f4").reshape(-1, 2)

    def test_real_cut_trim_missing_audio_and_review_binding(self):
        plan = self.plan()
        plan["clips"][0]["use"] = {"start_s": .2, "end_s": 1}
        plan["clips"][1]["use"]["end_s"] = .6
        original = {s["path"]: s["sha256"] for s in plan["sources"]}
        receipt = render_assembly(plan, self.directory / "cut")
        self.assertEqual(receipt["frame_count"], 14)
        self.assertAlmostEqual(receipt["duration_s"], 1.4)
        frames = self.frames(receipt["path"])
        self.assertEqual(len(frames), 14)
        self.assertGreater(frames[7, 32, 48, 0], 240)
        self.assertGreater(frames[8, 32, 48, 2], 240)
        pcm = self.pcm(receipt["audio"]["pcm_path"])
        self.assertEqual(len(pcm), 67200)
        self.assertGreater(float(np.max(abs(pcm[:38400]))), .03)
        self.assertLess(float(np.max(abs(pcm[38400:]))), 1e-7)
        for path, checksum in original.items():
            self.assertEqual(file_sha256(path), checksum)
        review = new_review(receipt["review_plan"], receipt)
        self.assertFalse(review["can_finalize"])
        self.assertEqual(review["user_approval"], "pending")
        self.assertFalse(receipt["delivery_ready"])
        self.assertEqual(json.loads(Path(receipt["receipt_path"]).read_text()), receipt)

    def test_real_crossfade_preserves_overlap_frame_and_audio_timing(self):
        receipt = render_assembly(self.plan([self.red, self.green], transition="crossfade", overlap=.4), self.directory / "crossfade")
        self.assertEqual(receipt["frame_count"], 16)
        self.assertEqual(receipt["audio"]["target_samples"], 76800)
        frames = self.frames(receipt["path"])
        self.assertGreater(frames[8, 32, 48, 0], 60)
        self.assertGreater(frames[8, 32, 48, 1], 60)
        self.assertGreater(frames[-1, 32, 48, 1], 240)
        samples = self.pcm(receipt["audio"]["pcm_path"])[:, 0]
        self.assertEqual(len(samples), 76800)
        def energy(start, frequency):
            window = samples[int(start * 48000):int((start + .1) * 48000)]
            return abs(np.dot(window, np.exp(-2j * np.pi * frequency * np.arange(len(window)) / 48000))) / len(window)
        self.assertGreater(energy(.2, 440), energy(.2, 880) * 10)
        self.assertGreater(energy(1.2, 880), energy(1.2, 440) * 10)
        self.assertGreater(energy(.75, 440), .005)
        self.assertGreater(energy(.75, 880), .005)

    def test_three_clips_mixed_joins_keep_fractional_fps_and_sample_clock(self):
        red, green = self.directory / "rational-red.mp4", self.directory / "rational-green.mp4"
        video(red, "red", rate="30000/1001", tone=440, duration=1.001)
        video(green, "lime", rate="30000/1001", tone=880, duration=1.001)
        for transitions in (("cut", "wipeleft"), ("crossfade", "cut")):
            with self.subTest(transitions=transitions):
                plan = self.plan([red, green, red])
                plan["output"]["fps"] = "30000/1001"
                for clip in plan["clips"]:
                    clip["use"]["end_s"] = "7007/30000"  # Exactly seven source frames.
                for join, kind in zip(plan["joins"], transitions):
                    join.update(transition=kind, duration_s=0 if kind == "cut" else "1001/15000")
                receipt = render_assembly(plan, self.directory / (transitions[0] + "-mixed"))
                self.assertEqual(receipt["frame_count"], 19)
                self.assertEqual(receipt["fps"], "30000/1001")
                self.assertEqual(receipt["audio"]["target_samples"], 30430)
                self.assertEqual(len(self.pcm(receipt["audio"]["pcm_path"])), 30430)
                self.assertAlmostEqual(receipt["duration_s"], float(Fraction(19019, 30000)))

    def test_explicit_fps_and_raster_normalization_is_measured(self):
        plan = self.plan([self.square])
        with self.assertRaises(ValidationError) as caught:
            validate_assembly(plan)
        self.assertEqual(caught.exception.issues[0]["code"], "assembly_fps_mismatch")
        plan["clips"][0]["reframe_fps"] = "resample"
        with self.assertRaises(ValidationError) as caught:
            validate_assembly(plan)
        self.assertEqual(caught.exception.issues[0]["code"], "assembly_size_mismatch")
        for fit in ("contain", "cover"):
            with self.subTest(fit=fit):
                plan["clips"][0]["fit"] = fit
                plan["output"]["audio"]["mode"] = "none"
                receipt = render_assembly(plan, self.directory / fit)
                pixels = self.frames(receipt["path"])
                self.assertEqual(len(pixels), 10)
                self.assertEqual(receipt["timeline"][0]["reframe_fps"], "resample")
                self.assertLess(pixels[0, 32, 0].max(), 4) if fit == "contain" else self.assertGreater(pixels[0, 32, 0, 2], 240)

    def test_declared_missing_audio_rejection_and_invalid_ranges_do_not_render(self):
        plan = self.plan([self.blue])
        plan["output"]["audio"]["missing"] = "reject"
        with self.assertRaises(ValidationError) as caught:
            render_assembly(plan, self.directory / "blocked")
        self.assertEqual(caught.exception.issues[0]["code"], "assembly_audio_missing")
        self.assertFalse((self.directory / "blocked").exists())
        for span in ({"start_s": 0, "end_s": 1.1}, {"start_s": .01, "end_s": 1}):
            broken = self.plan([self.blue])
            broken["clips"][0]["use"] = span
            with self.subTest(span=span), self.assertRaises(ValidationError):
                validate_assembly(broken)

    def test_source_tampering_sealed_plan_and_existing_output_are_blocked(self):
        copied = self.directory / "copy.mp4"
        shutil.copyfile(self.blue, copied)
        plan = self.plan([copied])
        plan["plan_sha256"] = digest(plan)
        changed = copy.deepcopy(plan)
        changed["clips"][0]["audio"]["gain_db"] = -12
        with self.assertRaises(ValidationError) as caught:
            validate_assembly(changed)
        self.assertEqual(caught.exception.issues[0]["code"], "assembly_plan_changed")
        copied.write_bytes(copied.read_bytes() + b"modified")
        with self.assertRaises(ValidationError):
            render_assembly(plan, self.directory / "altered")
        self.assertFalse((self.directory / "altered").exists())
        existing = self.directory / "existing"
        existing.mkdir()
        with self.assertRaises(ValidationError):
            render_assembly(self.plan([self.blue]), existing)

    def test_generation_bridge_keeps_pending_post_and_rejects_stale_plan(self):
        plan = generation_fixtures.plan_fixture(count=2)
        plan["clips"][1]["post"] = [{"id": "title", "kind": "text", "brief": "Add an exact title after assembly.",
                                     "start_s": 0, "end_s": .5}]
        returns = {"clip1": import_clip(plan, "clip1", self.blue, self.directory / "return1"),
                   "clip2": import_clip(plan, "clip2", self.green, self.directory / "return2")}
        assembled = from_generation(plan, returns, fps="10/1", width=96, height=64)
        self.assertEqual(assembled["pending_post"][0]["id"], "post:clip2:title")
        self.assertEqual(assembled["pending_post"][0]["timeline_interval"], {"start_s": 1., "end_s": 1.5})
        receipt = render_assembly(assembled, self.directory / "generated")
        self.assertEqual(receipt["frame_count"], 20)
        self.assertEqual(receipt["status"], "assembled_with_pending_post")
        changed = copy.deepcopy(plan)
        changed["clips"][0]["shots"][0]["action"] = "The sphere stops."
        with self.assertRaises(ValidationError) as caught:
            from_generation(changed, returns, fps="10/1", width=96, height=64)
        self.assertEqual(caught.exception.issues[0]["code"], "stale_receipt")

    def test_generation_silent_brief_and_required_audio_cannot_be_overridden(self):
        for audio_execution, required in (("none", False), ("generation", True)):
            with self.subTest(audio_execution=audio_execution):
                plan = generation_fixtures.plan_fixture(count=1)
                plan["brief"].update(audio_execution=audio_execution, require_generated_audio=required)
                returned = import_clip(plan, "clip1", self.green, self.directory / audio_execution)
                with self.assertRaises(ValidationError) as caught:
                    from_generation(plan, {"clip1": returned}, fps="10/1", width=96, height=64)
                self.assertEqual(caught.exception.issues[0]["code"], "assembly_generation_audio")
                assembly = from_generation(plan, {"clip1": returned}, fps="10/1", width=96, height=64,
                                           audio="none" if audio_execution == "none" else "source", missing_audio="reject")
                self.assertEqual(assembly["output"]["audio"]["mode"], "none" if audio_execution == "none" else "source")

    def test_generation_parent_result_cannot_be_replaced_silently(self):
        plan = generation_fixtures.plan_fixture(count=2, strategy="observed_frame")
        obs = generation_fixtures.observation(continuity_decision={"status": "accept", "actor": "test editor", "reason": "Synthetic boundary fixture."})
        parent = import_clip(plan, "clip1", self.blue, self.directory / "parent", selected_frame=9, observation=obs)
        child = import_clip(plan, "clip2", self.green, self.directory / "child", exported_clip=generation_fixtures.parent_export(plan, parent))
        replaced = import_clip(plan, "clip1", self.green, self.directory / "replaced", selected_frame=9, observation=obs)
        with self.assertRaises(ValidationError) as caught:
            from_generation(plan, {"clip1": replaced, "clip2": child}, fps="10/1", width=96, height=64)
        self.assertEqual(caught.exception.issues[0]["code"], "assembly_stale_dependency")

    def test_post_transition_requires_explicit_supported_mapping(self):
        plan = generation_fixtures.plan_fixture(count=2)
        plan["brief"]["target_duration_s"] = 1.6
        plan["joins"][0].update(execution="post", strategy="post_only", overlap_s=.4, kind="authored dissolve")
        returns = {"clip1": import_clip(plan, "clip1", self.blue, self.directory / "r1"),
                   "clip2": import_clip(plan, "clip2", self.green, self.directory / "r2")}
        with self.assertRaises(ValidationError) as caught:
            from_generation(plan, returns, fps="10/1", width=96, height=64)
        self.assertEqual(caught.exception.issues[0]["code"], "assembly_transition_map")
        assembled = from_generation(plan, returns, fps="10/1", width=96, height=64, transitions={"join1": "crossfade"})
        self.assertEqual(validate_assembly(assembled, verify_files=False)["frame_count"], 16)
        broken = self.plan(transition="random-wipe")
        with self.assertRaises(ValidationError):
            validate_assembly(broken, verify_files=False)


if __name__ == "__main__":
    unittest.main()
