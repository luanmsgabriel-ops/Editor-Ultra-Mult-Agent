"""Real RGBA/MP4 integration: clocks, occlusion, protection and asset integrity."""

import copy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image, ImageDraw

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine.directions import build_request, plan_direction
from editorial_engine.motion_assets import inspect_placement, load_layer, placement, write_layer_manifest
from editorial_engine.native import native_catalog, render_bundle
from editorial_engine.perception import prepare_analysis, write_json


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Real media integration")
class MotionAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="motion-assets-")
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "source.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
            "color=c=0x101820:s=160x120:r=20:d=1", "-vf",
            "drawbox=x=64:y=36:w=32:h=48:color=blue:t=fill", "-c:v", "libx264",
            "-threads", "1", "-pix_fmt", "yuv420p", str(cls.source)], check=True, capture_output=True)
        cls.source_hash = file_sha256(cls.source)
        cls.protection = cls.root / "protection.json"
        write_json(cls.protection, {"source_sha256": cls.source_hash, "fps": "20", "frame_count": 20,
            "provenance": {"kind": "human", "actor": "test-fixture", "method": "Known synthetic rectangle"},
            "frames": {str(i): [[.4, .3, .6, .7]] for i in range(20)}})
        cls.mattes = cls.root / "mattes"
        cls.mattes.mkdir()
        write_json(cls.mattes / "alpha.json", {"source_sha256": cls.source_hash, "fps": "20", "frames": 20})
        matte = np.zeros((120, 160), np.uint8)
        matte[36:84, 64:96] = 255
        for i in range(20):
            cv2.imwrite(str(cls.mattes / f"{i:06d}.png"), matte)
        cls.frame_paths = []
        for i in range(16):
            art = Image.new("RGBA", (160, 120))
            draw = ImageDraw.Draw(art)
            draw.rectangle((20 + i * 4, 48, 44 + i * 4, 72), fill=(255, 150, 0, 255))
            path = cls.root / f"layer-{i:06d}.png"
            art.save(path)
            cls.frame_paths.append(path)
        cls.manifest_path = cls.root / "layer.json"
        cls.layer = write_layer_manifest(cls.frame_paths, cls.manifest_path, fps="20", backend="fixture",
                                        method="Known moving square; synthetic technical proof")
        cls.assets = {"assets": [{"id": "moving", "kind": "motion", "path": str(cls.manifest_path),
                                   "description": "Synthetic animated square", "functions": ["reveal"]}]}
        cls.analysis = prepare_analysis(cls.source, cls.root / "prepared", protection=cls.protection,
                                       mattes=cls.mattes, assets=cls.assets, sample_every_s=.1)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def bundle(self, *, behind=True, params=None):
        event = self.analysis["events"][0]
        provenance = {"kind": "human", "actor": "test-fixture", "method": "Known rectangle/animation intent"}
        bindings = {"asset": "asset:moving", **({"matte": "matte"} if behind else {})}
        direction = {"schema_version": "1.0", "provenance": provenance,
            "event_annotations": [{"id": event["id"], "intent": "Reveal an animated square behind the known object",
                "opportunities": [{"id": "reveal", "function": "reveal", "why": "Known synthetic animation"}]}],
            "evidence_annotations": [{"id": "frame:6", "observation": "Known blue rectangle at the centre of a dark synthetic frame."}],
            "limitations": ["Synthetic technical fixture"],
            "proposals": {"schema_version": "1.0", "candidates": [{"id": "motion", "event_id": event["id"],
                "effect_id": "native.motion_behind" if behind else "native.motion_layer",
                "source_id": "source", "source_sha256": self.source_hash, "clock": "source",
                "interval": {"start_s": .1, "end_s": .9}, "evidence_ids": ["frame:6"],
                "why": "Demonstrate the known moving rectangle and real matte without relocating the source",
                "scores": dict.fromkeys(("intent_fit", "visual_fit", "style_fit", "timing_fit"), .9),
                "score_provenance": provenance, "anchor": {"space": "screen"}, "bindings": bindings,
                "params": params or {}, "addresses": ["reveal"], "region": [0, 0, 1, 1]}]}}
        return plan_direction(self.analysis, native_catalog(), direction)

    def output(self, name):
        return Path(tempfile.mkdtemp(dir=self.root)) / name

    @staticmethod
    def frame(path, index):
        capture = cv2.VideoCapture(str(path))
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        success, frame = capture.read()
        capture.release()
        if not success:
            raise AssertionError("Rendered frame did not decode")
        return frame

    def test_real_motion_changes_position_and_preserves_subject_and_clock(self):
        output = self.output("behind.mp4")
        artifact = render_bundle(self.bundle(), output)
        self.assertEqual((artifact["fps"], artifact["frame_count"]), ("20", 20))
        original = self.frame(self.source, 8)
        for index in (2, 8, 16):
            frame = self.frame(output, index)
            self.assertLess(np.abs(frame[42:78, 69:90].astype(float) - original[42:78, 69:90]).mean(), 4)
        early, late = self.frame(output, 2), self.frame(output, 16)
        self.assertGreater(early[52:68, 26:40, 2].mean(), late[52:68, 26:40, 2].mean() + 100)
        for index in (0, 19):
            self.assertLess(np.abs(self.frame(output, index).astype(float) - self.frame(self.source, index)).mean(), 4)
        self.assertEqual(file_sha256(self.source), self.source_hash)
        self.assertEqual(len(artifact["compilation"][0]["motion_frames"]), 16)

    def test_front_layer_cannot_cross_protected_subject(self):
        output = self.output("bad.mp4")
        with self.assertRaises(ValidationError) as error:
            render_bundle(self.bundle(behind=False), output)
        self.assertIn("protected_overlap", str(error.exception))
        self.assertFalse(output.exists())

    def test_visibility_failure_never_changes_behind_to_front(self):
        output = self.output("unreadable.mp4")
        with self.assertRaises(ValidationError) as error:
            render_bundle(self.bundle(params={"min_visible_fraction": .9}), output)
        self.assertIn("motion_occlusion", str(error.exception))
        self.assertFalse(output.exists())

    def test_short_layer_never_repeats_its_last_frame(self):
        with self.assertRaises(ValidationError) as error:
            render_bundle(self.bundle(params={"asset_start_frame": 1}), self.output("short.mp4"))
        self.assertIn("motion_short", str(error.exception))

    def test_tampered_frame_rejected_before_render(self):
        temporary = self.output("layer.json")
        changed = copy.deepcopy(self.layer)
        path = temporary.with_suffix(".png")
        Image.new("RGBA", (160, 120), (0, 255, 0, 255)).save(path)
        changed["frames"][0]["path"] = str(path)
        with self.assertRaises(ValidationError):
            from editorial_engine.motion_assets import validate_layer
            validate_layer(changed)

    def test_bound_layers_reject_other_sources_and_times(self):
        layer = copy.deepcopy(self.layer)
        layer["source_binding"] = {"source_sha256": self.source_hash, "fps": "20", "frame_count": 20, "start_frame": 2}
        mapped = placement(layer, source_sha256=self.source_hash, fps=Fraction(20), frame_count=20, first=2, last=18)
        self.assertEqual(mapped[2]["index"], 0)
        with self.assertRaises(ValidationError):
            placement(layer, source_sha256=self.source_hash, fps=Fraction(20), frame_count=20, first=1, last=17)
        with self.assertRaises(ValidationError):
            placement(layer, source_sha256="0" * 64, fps=Fraction(20), frame_count=20, first=2, last=18)
        with self.assertRaises(ValidationError):
            placement(layer, source_sha256=self.source_hash, fps=Fraction(30000, 1001), frame_count=20, first=2, last=18)

    def test_all_rgba_frames_required_and_ordered(self):
        from editorial_engine.motion_assets import validate_layer
        missing = copy.deepcopy(self.layer)
        missing["frames"].pop(5)
        with self.assertRaises(ValidationError):
            validate_layer(missing)
        unordered = copy.deepcopy(self.layer)
        unordered["frames"][0], unordered["frames"][1] = unordered["frames"][1], unordered["frames"][0]
        with self.assertRaises(ValidationError):
            validate_layer(unordered)

    def test_director_receives_motion_samples_and_explicit_scope(self):
        request = build_request(self.analysis, native_catalog(), "Reveal the animated square", max_frames=3)
        self.assertEqual(request["review_scope"]["motion_asset_capability_ids"], ["asset:moving"])
        self.assertFalse(request["review_scope"]["continuous_motion_review"])
        payload = json.loads(request["body"]["messages"][1]["content"][0]["text"])
        self.assertEqual(payload["motion_guidance"]["schema"], "motion-guidance/1")
        motion = next(row["motion_asset"] for row in payload["resources"] if row["capability_id"] == "asset:moving")
        self.assertEqual(motion["frame_count"], 16)

    def test_single_hidden_glyph_fails_even_when_word_fraction_passes(self):
        directory = self.output("glyphs").parent
        rgba = np.zeros((20, 40, 4), np.uint8)
        rgba[4:16, 4:16] = [255, 200, 100, 255]
        rgba[4:16, 24:36] = [255, 200, 100, 255]
        ids = np.zeros((20, 40), np.uint16)
        ids[4:16, 4:16], ids[4:16, 24:36] = 1, 2
        image_path, id_path = directory / "rgba.png", directory / "ids.png"
        Image.fromarray(rgba).save(image_path)
        Image.fromarray(ids).save(id_path)
        entry = {"index": 0, "path": str(image_path), "sha256": file_sha256(image_path),
                 "glyph_ids_path": str(id_path), "glyph_ids_sha256": file_sha256(id_path), "reading": True}
        matte = np.zeros((20, 40), np.uint8)
        matte[:, :20] = 255
        with self.assertRaises(ValidationError) as error:
            inspect_placement(entry, np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]), (40, 20), [],
                              matte=matte, min_visible=.4, min_glyph_visible=.5)
        self.assertIn("motion_glyph_occlusion", str(error.exception))

    def test_motion_sound_candidates_map_to_samples_without_selecting_audio(self):
        from editorial_engine.motion_events import map_sonic_candidates
        candidates = {"schema_version": "motionlab-sonic/1", "clock": "scene_seconds", "fps": "20",
                      "frame_count": 16, "scene_sha256": "1" * 64,
                      "candidates": [{"id": "excluded", "time_s": .1}, {"id": "movement", "time_s": .25301}]}
        result = map_sonic_candidates(candidates, self.source, source_first_frame=4,
                                      source_last_frame=16, asset_start_frame=4)
        self.assertEqual(result["candidates"][0]["target_sample"], 12144)
        self.assertAlmostEqual(result["candidates"][0]["rounding_error_samples"], -.48)
        self.assertEqual(result["excluded"][0]["id"], "excluded")
        self.assertIsNone(result["candidates"][0]["sound_asset"])
        self.assertFalse(result["audio_listened"])
        self.assertFalse(result["sfx_selected"])

    def test_explicit_glyph_requirement_without_id_pass_is_blocked(self):
        with self.assertRaises(ValidationError) as error:
            inspect_placement(self.layer["frames"][0], np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]),
                              (160, 120), [], min_glyph_visible=.5)
        self.assertIn("motion_glyph_ids", str(error.exception))

    def test_source_end_rounding_never_schedules_an_out_of_range_sample(self):
        from editorial_engine.motion_events import map_sonic_candidates
        candidates = {"schema_version": "motionlab-sonic/1", "clock": "scene_seconds", "fps": "20",
                      "frame_count": 20, "scene_sha256": "1" * 64,
                      "candidates": [{"id": "too-close-to-end", "time_s": .999999}]}
        with self.assertRaises(ValidationError) as error:
            map_sonic_candidates(candidates, self.source, source_first_frame=0)
        self.assertIn("sonic_quantization", str(error.exception))

    def test_protection_measures_the_actual_subpixel_compositor_footprint(self):
        from visual_fidelity.anchor_graphics import composite
        raster = np.zeros((39, 73, 4), np.uint8)
        raster[5:34, 7] = [255, 255, 255, 255]
        path = self.output("thin.png")
        Image.fromarray(raster).save(path)
        entry = {"index": 0, "path": str(path), "sha256": file_sha256(path)}
        corners = np.float32([[.123, .178], [.878, .168], [.837, .857], [.132, .821]])
        composed = np.zeros((37, 51, 3), np.uint8)
        composite(composed, raster, corners)
        y, x = np.unravel_index(np.argmax(composed[:, :, 0]), composed.shape[:2])
        self.assertGreater(composed[y, x, 0], 1)
        box = [x / 51, y / 37, (x + 1) / 51, (y + 1) / 37]
        with self.assertRaises(ValidationError) as error:
            inspect_placement(entry, corners, (51, 37), [box])
        self.assertIn("protected_overlap", str(error.exception))


if __name__ == "__main__":
    unittest.main()
