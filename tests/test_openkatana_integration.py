"""Execute pinned OpenKatana pixels and DSP; no model or aesthetic assertions."""

import copy
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import numpy as np
from PIL import Image

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine.openkatana import (
    UPSTREAM_COMMIT, analyze_audio, analyze_reference, make_clockmap, preview_effect,
    probe_openkatana, render_blender, render_scene3d, render_timeline,
)
from editorial_engine import openkatana as adapter
from visual_fidelity.reference_cadence import video_clock


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Local media runtime required")
class OpenKatanaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="openkatana-integration-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.root = Path(cls.directory.name)
        cls.source = cls.root / "source.mp4"
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=96x96:r=10:d=1",
            "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(cls.source),
        ], capture_output=True, check=True)
        cls.source_hash = file_sha256(cls.source)
        cls.project = cls.root / "project"
        (cls.project / "frames").mkdir(parents=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(cls.source),
                        "-start_number", "0", str(cls.project / "frames" / "%05d.png")],
                       capture_output=True, check=True)
        cls.timeline = {"canvas": {"w": 96, "h": 96, "fps": 10, "frames": 10},
                        "clips": {"source": {"frames_dir": "frames", "n": 10, "fps": 10,
                                               "w": 96, "h": 96, "pattern": "%05d.png"}},
                        "shots": [{"f0": 0, "f1": 10, "clip": "source", "speed": 1}]}
        cls.clockmap = make_clockmap(cls.timeline, {"source": {
            "kind": "source", "path": str(cls.source), "sha256": cls.source_hash,
            "fps": "10", "frame_count": 10, "origin_frame": 0,
        }})
        cls.readiness = probe_openkatana(check_browser=False)
        cls.audio = cls.root / "beats.wav"
        rate = 22050
        samples = np.zeros(rate * 8)
        t = np.arange(round(.06 * rate)) / rate
        pulse = .65 * np.sin(2 * np.pi * 80 * t) * np.exp(-55 * t)
        for position in np.arange(.25, 7.8, .5):
            start = round(position * rate)
            samples[start:start + len(pulse)] += pulse
        with wave.open(str(cls.audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(np.rint(samples * 32767).astype("<i2").tobytes())

    def setUp(self):
        self.case = Path(tempfile.mkdtemp(prefix="case-", dir=self.root))

    def test_reference_measurement_keeps_analysis_and_source_clocks_separate(self):
        report = analyze_reference(self.source, self.case / "reference", start_s=.2, duration_s=.6,
                                   measures=("cuts", "cadence", "look"))
        self.assertEqual(report["upstream"]["commit"], UPSTREAM_COMMIT)
        self.assertEqual(report["results"]["fps"], 60)
        self.assertEqual(report["results"]["source_fps"], 10)
        self.assertEqual(report["results"]["frames"], 36)
        self.assertEqual(report["clockmap"]["source_offset_s"], "0.2")
        self.assertIn("saturation", report["results"]["look"]["overall"])
        self.assertEqual(file_sha256(self.source), self.source_hash)
        self.assertEqual(file_sha256(report["receipt"]["path"]), report["receipt"]["sha256"])
        self.assertFalse(report["external_model_executed"])
        self.assertEqual(report["perceptual_review"], "not_performed")

    def test_real_audio_dsp_estimates_known_pulses_and_keeps_source_offset(self):
        before = file_sha256(self.audio)
        report = analyze_audio(self.audio, self.case / "audio", start_s=.5, duration_s=6, fps="10")
        self.assertAlmostEqual(report["results"]["bpm"], 120, delta=1)
        self.assertGreaterEqual(len(report["results"]["beats"]), 10)
        self.assertEqual(report["clockmap"]["source_offset_s"], "0.5")
        self.assertIn("octave", report["results"])
        self.assertIn("downbeat_confidence", report["results"])
        self.assertEqual(file_sha256(self.audio), before)
        self.assertTrue(any(item["path"].endswith(".png") for item in report["artifacts"]))

    def test_real_effect_executes_upstream_engine_and_changes_pixels(self):
        if self.readiness["capabilities"]["timeline_node_canvas"] != "ready":
            self.skipTest("Node Canvas runtime is not available")
        report = preview_effect(self.source, self.case / "preview", effect="local_rgb_split",
                                params={"amount": 80}, start_s=.2, duration_s=.6)
        self.assertEqual(report["runtime"]["runtime"], "node-canvas")
        self.assertEqual(video_clock(Path(report["path"])), (Fraction(10), 6))
        self.assertEqual(report["clockmap"]["clips"]["source"]["origin_frame"], 2)
        self.assertEqual(report["alpha"], "opaque")
        self.assertTrue(report["source_bindings"][0]["source_pixels_verified"])
        self.assertEqual(report["source_bindings"][0]["frames_compared"], 6)
        original = np.asarray(Image.open(self.case / "preview" / "project" / "source" / "00000.png")).astype(float)
        result = np.asarray(Image.open(report["frames"][0]["path"]).convert("RGB")).astype(float)
        # Compare the actual decoded plate with the renderer PNG, excluding
        # H.264 as an explanation for an effect that never ran.
        self.assertGreater(np.abs(original - result).mean(), 5)
        self.assertEqual(len(report["frames"]), 6)
        for item in report["frames"]:
            self.assertEqual(file_sha256(item["path"]), item["sha256"])
        self.assertEqual(file_sha256(report["path"]), report["sha256"])
        self.assertEqual(file_sha256(self.source), self.source_hash)
        self.assertEqual(report["user_approval"], "pending")

    def test_missing_or_changed_clockmap_blocks_before_render(self):
        with self.assertRaisesRegex(ValidationError, "clockmap_required"):
            render_timeline(self.project, self.timeline, self.case / "missing")
        changed = copy.deepcopy(self.timeline)
        changed["shots"][0]["speed"] = .5
        with self.assertRaisesRegex(ValidationError, "clockmap_sampling"):
            render_timeline(self.project, changed, self.case / "retimed", clockmap=self.clockmap)
        self.assertFalse((self.case / "missing").exists())
        self.assertFalse((self.case / "retimed").exists())

    def test_source_samples_cannot_silently_clamp_negative_inpoint_or_speed_ramp(self):
        negative = copy.deepcopy(self.timeline)
        negative["shots"][0]["srcf"] = -10
        mapping = make_clockmap(negative, self.clockmap["clips"])
        with self.assertRaisesRegex(ValidationError, "source_sample_bounds"):
            render_timeline(self.project, negative, self.case / "negative", clockmap=mapping)
        ramp = copy.deepcopy(self.timeline)
        ramp["canvas"].update(fps=24, frames=48)
        ramp["clips"]["source"]["fps"] = 24
        ramp["shots"][0].update(f1=48, speed=0, speed1=20)
        mapping = make_clockmap(ramp, {"source": {"kind": "authored_sequence", "fps": "24", "frame_count": 10,
            "origin_frame": 0, "provenance": "Explicit rate for a synthetic PNG fixture"}})
        with self.assertRaisesRegex(ValidationError, "source_sample_bounds"):
            render_timeline(self.project, ramp, self.case / "ramp", clockmap=mapping)
        self.assertFalse((self.case / "negative").exists())
        self.assertFalse((self.case / "ramp").exists())

    def test_intentional_source_hold_is_explicit_and_reported(self):
        if self.readiness["capabilities"]["timeline_node_canvas"] != "ready":
            self.skipTest("Node Canvas runtime is not available")
        timeline = copy.deepcopy(self.timeline)
        timeline["canvas"]["frames"] = 12
        timeline["shots"][0]["f1"] = 12
        mapping = make_clockmap(timeline, self.clockmap["clips"])
        self.assertEqual(mapping["shots"][0]["loop"], "clamp")
        self.assertFalse(mapping["shots"][0]["loop_explicit"])
        with self.assertRaisesRegex(ValidationError, "source_sample_bounds"):
            render_timeline(self.project, timeline, self.case / "hidden-hold", clockmap=mapping)
        timeline["shots"][0]["loop"] = "clamp"
        mapping = make_clockmap(timeline, self.clockmap["clips"])
        report = render_timeline(self.project, timeline, self.case / "explicit-hold", clockmap=mapping)
        repetitions = report["sampling_audit"]["explicit_repetitions"]
        self.assertEqual(repetitions[0]["mode"], "clamp")
        self.assertEqual(repetitions[0]["out_of_range_samples"], 2)
        self.assertEqual(repetitions[0]["first_output_frame"], 10)
        self.assertEqual(video_clock(Path(report["path"])), (Fraction(10), 12))

    def test_proxy_pixels_from_another_source_cannot_borrow_a_valid_video_hash(self):
        project = self.case / "different-pixels"
        shutil.copytree(self.project, project)
        Image.new("RGB", (96, 96), (255, 0, 0)).save(project / "frames" / "00000.png")
        with self.assertRaisesRegex(ValidationError, "source_binding_pixels"):
            render_timeline(project, self.timeline, self.case / "mismatched", clockmap=self.clockmap)
        self.assertFalse((self.case / "mismatched").exists())

    def test_preview_preserves_fractional_source_clock_exactly(self):
        if self.readiness["capabilities"]["timeline_node_canvas"] != "ready":
            self.skipTest("Node Canvas runtime is not available")
        source = self.case / "ntsc.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=96x96:r=30000/1001",
                        "-frames:v", "6", "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(source)],
                       capture_output=True, check=True)
        report = preview_effect(source, self.case / "ntsc-preview", effect="local_rgb_split", params={"amount": 80})
        self.assertEqual(report["fps"], "30000/1001")
        self.assertEqual(report["clockmap"]["fps"], "30000/1001")
        self.assertEqual(video_clock(Path(report["path"])), (Fraction(30000, 1001), 6))

    def test_blender_dependency_change_is_rejected_against_worker_prerender_hash(self):
        source = self.case / "scene.blend"
        source.write_bytes(b"fixture: no renderer will run")
        texture = self.case / "texture.png"
        texture.write_bytes(b"original texture")
        before = file_sha256(texture)
        bridge = adapter._module("blender_bridge")
        def changed_texture(*args, **kwargs):
            texture.write_bytes(b"changed during rendering")
            return {"dependencies": {str(texture): before}}
        with patch("editorial_engine.openkatana._blender_probe", return_value={"status": "ready"}), \
             patch.object(bridge, "render_blender", side_effect=changed_texture):
            with self.assertRaisesRegex(ValidationError, "source_changed"):
                render_blender(source, self.case / "changed-blender")
        self.assertFalse((self.case / "changed-blender" / "adapter-receipt.json").exists())

    def test_nonexistent_configured_blender_is_not_ready(self):
        with patch.dict(os.environ, {"OPENKATANA_BLENDER": str(self.case / "missing-blender")}):
            report = probe_openkatana(check_browser=False)
        self.assertEqual(report["capabilities"]["blender"], "blocked")
        self.assertEqual(report["blender"]["status"], "blocked")

    def test_preview_does_not_round_time_or_downgrade_spatial_request(self):
        with self.assertRaisesRegex(ValidationError, "preview_clock"):
            preview_effect(self.source, self.case / "subframe", effect="local_rgb_split", start_s=.05)
        with self.assertRaisesRegex(ValidationError, "spatial_mode"):
            preview_effect(self.source, self.case / "fake-3d", effect="local_rgb_split", spatial_mode="3d")
        self.assertFalse((self.case / "subframe").exists())
        self.assertFalse((self.case / "fake-3d").exists())

    def test_unavailable_webgl_does_not_call_a_2d_renderer(self):
        with patch("editorial_engine.openkatana._browser_probe",
                   return_value={"status": "blocked", "webgl": False, "reason": "Unavailable test capability"}):
            with self.assertRaisesRegex(ValidationError, "webgl_unavailable"):
                render_scene3d(self.project, {}, self.case / "scene")
        self.assertFalse((self.case / "scene").exists())

    @unittest.skipUnless(shutil.which("blender"), "Optional installed Blender")
    def test_blender_bridge_produces_real_geometry_and_rgba_sequence(self):
        scene = self.case / "scene.py"
        scene.write_text("""import bpy, mathutils
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 2
scene.cycles.use_denoising = False
scene.render.threads_mode = 'FIXED'
scene.render.threads = 2
scene.render.resolution_x = 64
scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
scene.render.fps = 10
scene.frame_start = 1
scene.frame_end = 2
scene.render.film_transparent = True
bpy.ops.mesh.primitive_cube_add(size=1)
bpy.context.object.rotation_euler = (.2, .3, .2)
bpy.ops.object.camera_add(location=(2, -3, 2))
camera = bpy.context.object
camera.rotation_euler = (mathutils.Vector((0, 0, 0)) - camera.location).to_track_quat('-Z', 'Y').to_euler()
scene.camera = camera
bpy.ops.object.light_add(type='AREA', location=(1, -2, 4))
bpy.context.object.data.energy = 500
""", encoding="utf-8")
        before = file_sha256(scene)
        report = render_blender(scene, self.case / "blender", engine="CYCLES", trusted_script=True)
        self.assertEqual(report["runtime"]["runtime"], "blender")
        self.assertEqual(report["runtime"]["engine"], "CYCLES")
        self.assertEqual(video_clock(Path(report["path"])), (Fraction(10), 2))
        self.assertEqual(report["alpha"], "straight")
        image = np.asarray(Image.open(report["frames"][0]["path"]).convert("RGBA"))
        self.assertGreater(np.count_nonzero(image[:, :, 3] > 200), 50)
        self.assertGreater(np.count_nonzero(image[:, :, 3] == 0), 50)
        self.assertEqual(file_sha256(scene), before)
        self.assertFalse(report["clockmap"]["camera_solve_on_footage"])
        self.assertIsNone(report["external_api_called"])
        self.assertIsNone(report["external_model_executed"])
        self.assertIsNone(report["credits_used"])
        self.assertEqual(report["external_activity"], "not_observed_trusted_code")


if __name__ == "__main__":
    unittest.main()
