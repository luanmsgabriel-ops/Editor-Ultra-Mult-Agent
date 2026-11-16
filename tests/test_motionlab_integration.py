"""Real small raster proofs and boundaries for the pinned MIT Motion Lab bridge."""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine import motionlab

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = bool(shutil.which("node") and (ROOT / "editorial_engine/backends/motionlab/node_modules/@napi-rs/canvas/package.json").is_file())


def scene2d():
    return {"schema_version": "motionlab-scene/1", "id": "moving-square", "mode": "2d",
            "width": 96, "height": 64, "fps": "8/1", "frame_count": 8, "background": None,
            "nodes": [{"id": "square", "type": "rect", "x": 4, "y": 20, "width": 12, "height": 12, "fill": "#ff0000"}],
            "tracks": [{"target": "square", "property": "x", "keys": [{"t": 0, "value": 4, "ease": "linear"}, {"t": 1, "value": 80}]}]}


def scene3d():
    return {"schema_version": "motionlab-scene/1", "id": "rotating-volume", "mode": "3d",
            "width": 96, "height": 64, "fps": "4/1", "frame_count": 4, "background": None,
            "nodes": [{"id": "box", "type": "box", "size": [1.5, 1, .7], "material": {"color": "#4488ff"}}],
            "camera": {"position": [2, 1, 4], "target": [0, 0, 0], "fov": 40},
            "lights": [{"type": "ambient", "color": "#ffffff", "intensity": .15},
                       {"type": "directional", "color": "#ffffff", "intensity": .9, "direction": [1, 2, 3]}],
            "tracks": [{"target": "box", "property": "rotation", "keys": [{"t": 0, "value": [0, 0, 0], "ease": "linear"},
                                                                                 {"t": 1, "value": [.4, 1.5, .2]}]}]}


def pixels(receipt, index=0):
    with Image.open(receipt["frames"][index]["path"]) as image:
        return np.array(image)


class MotionLabContracts(unittest.TestCase):
    def test_vendor_is_the_unchanged_mit_tree(self):
        root = ROOT / "vendor/motionlab"
        manifest = json.loads((root / "provenance.json").read_text())
        self.assertEqual(manifest["commit"], "6a7f1ca62b7b30d534fe181f912606ad4cfc6718")
        self.assertIn("MIT License", (root / "LICENSE").read_text())
        for row in manifest["files"]:
            content = (root / row["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])
            self.assertEqual(hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest(), row["git_blob_sha1"])

    def test_clock_cannot_disagree_or_be_an_approximate_float(self):
        scene = scene2d()
        scene["duration_s"] = 2
        with self.assertRaisesRegex(ValidationError, "duration_s differs"):
            motionlab.validate_scene(scene)
        scene.pop("duration_s")
        scene["fps"] = 29.97
        with self.assertRaisesRegex(ValidationError, "rational"):
            motionlab.validate_scene(scene)

    def test_missing_capabilities_do_not_silently_downgrade(self):
        scene = scene3d()
        scene["nodes"][0]["material"]["roughness"] = .1
        with self.assertRaisesRegex(ValidationError, "Unknown fields"):
            motionlab.validate_scene(scene)
        scene = scene2d()
        scene["nodes"][0]["type"] = "image"
        with self.assertRaisesRegex(ValidationError, "Unsupported node type"):
            motionlab.validate_scene(scene)

    def test_undefined_tracks_duplicate_bindings_and_unknown_parameters_rejected(self):
        for mutate in (lambda s: s["tracks"][0].update(target="invented"),
                       lambda s: s["tracks"].append(copy.deepcopy(s["tracks"][0])),
                       lambda s: s.update(javascript="alert('not a scene')")):
            scene = scene2d()
            mutate(scene)
            with self.assertRaises(ValidationError):
                motionlab.validate_scene(scene)

    def test_fonts_are_required_and_hash_bound(self):
        scene = scene2d()
        scene["tracks"] = []
        scene["nodes"] = [{"id": "title", "type": "text", "text": "Ação", "font_id": "brand", "font_size": 24, "fill": "#ffffff"}]
        with self.assertRaisesRegex(ValidationError, "Missing font"):
            motionlab.validate_scene(scene)
        with tempfile.TemporaryDirectory() as temporary:
            font = Path(temporary) / "font.ttf"
            font.write_bytes(b"not a font")
            scene["fonts"] = [{"id": "brand", "format": "font", "path": str(font), "sha256": "0" * 64}]
            with self.assertRaisesRegex(ValidationError, "Font bytes changed"):
                motionlab.validate_scene(scene)


@unittest.skipUnless(RUNTIME, "Install the pinned Motion Lab adapter dependencies with npm ci")
class MotionLabExecution(unittest.TestCase):
    def test_real_font_is_used_and_missing_glyph_cannot_fallback(self):
        font = Path("/usr/share/fonts/opentype/urw-base35/URWGothic-Book.otf")
        if not font.exists():
            self.skipTest("No installed proof font")
        scene = scene2d()
        scene["frame_count"] = 1
        scene["tracks"] = []
        scene["fonts"] = [{"id": "proof-font", "path": str(font), "sha256": file_sha256(font), "format": "font"}]
        scene["nodes"] = [{"id": "title", "type": "text", "text": "Ação", "font_id": "proof-font", "font_size": 22,
                           "x": 4, "y": 36, "fill": "#ffffff"}]
        with tempfile.TemporaryDirectory() as temporary:
            receipt = motionlab.render(scene, Path(temporary) / "type")
            self.assertGreater((pixels(receipt)[:, :, 3] > 0).sum(), 50)
        scene["nodes"][0]["text"] = "\U0010ffff"
        with self.assertRaisesRegex(ValidationError, "no implicit fallback"):
            motionlab.validate_scene(scene)

    def test_extruded_typeface_geometry_renders_from_explicit_font(self):
        scene = scene3d()
        scene["frame_count"] = 1
        scene["tracks"] = []
        scene["camera"] = {"position": [1.4, .8, 3], "target": [.4, .3, 0], "fov": 40}
        with tempfile.TemporaryDirectory() as temporary:
            font = Path(temporary) / "test-typeface.json"
            # An original one-glyph test outline, not a substituted production alphabet.
            font.write_text(json.dumps({"glyphs": {"L": {"ha": 800, "x_min": 0, "x_max": 750,
                "o": "m 0 0 l 750 0 l 750 180 l 180 180 l 180 1000 l 0 1000 l 0 0"}},
                "familyName": "ProofOnly", "ascender": 1000, "descender": 0,
                "underlinePosition": -100, "underlineThickness": 50,
                "boundingBox": {"yMin": 0, "xMin": 0, "yMax": 1000, "xMax": 750}, "resolution": 1000}))
            scene["fonts"] = [{"id": "proof", "path": str(font), "sha256": file_sha256(font), "format": "three-typeface"}]
            scene["nodes"] = [{"id": "glyph", "type": "text3d", "text": "L", "font_id": "proof", "font_size": 1,
                               "depth": .2, "material": {"color": "#4488ff"}}]
            receipt = motionlab.render(scene, Path(temporary) / "text3d")
            self.assertGreater((pixels(receipt)[:, :, 3] > 0).sum(), 40)

    def test_probe_executes_two_actual_pixel_proofs(self):
        report = motionlab.probe()
        self.assertTrue(report["available"], report)
        self.assertFalse(report["webgl"]["used"])
        for backend in report["backends"].values():
            self.assertGreater(backend["proof"]["visible_pixels"], 0)
            self.assertGreater(backend["proof"]["transparent_pixels"], 0)

    def test_absolute_evaluation_is_order_independent_and_group_specific(self):
        scene = scene2d()
        scene["nodes"].append({"id": "other", "type": "rect", "width": 4, "height": 4, "fill": "#0000ff"})
        scene["tracks"].append({"target": "other", "property": "x", "keys": [{"t": 0, "value": 0, "ease": "linear"}, {"t": 1, "value": 100}]})
        scene["groups"] = {"slow": {"start": 0, "end": 1, "rate": .5, "keys": [{"t": 0, "value": 0}, {"t": 1, "value": 1}]}}
        scene["tracks"][0]["group"] = "slow"
        midpoint = motionlab.evaluate(scene, .5)
        motionlab.evaluate(scene, .9)
        repeated = motionlab.evaluate(scene, .5)
        self.assertEqual(midpoint, repeated)
        self.assertEqual(midpoint["group_times"]["slow"], .25)
        self.assertAlmostEqual(midpoint["nodes"][0]["x"], 23)
        self.assertAlmostEqual(midpoint["nodes"][1]["x"], 50)

    def test_png_alpha_motion_blur_and_hashes_are_actual(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = motionlab.render(scene2d(), Path(temporary) / "render", samples=8, shutter_angle=360)
            self.assertEqual(receipt["fps"], "8/1")
            self.assertEqual(receipt["alpha"], "straight")
            self.assertFalse(receipt["opaque"])
            self.assertGreater(len({frame["sha256"] for frame in receipt["frames"]}), 1)
            image = pixels(receipt, 4)
            partial = (image[:, :, 3] > 0) & (image[:, :, 3] < 255)
            self.assertTrue(partial.any())
            self.assertTrue((image[:, :, 0][partial] >= 250).all(), "Unassociated red must remain red at blurred alpha edges")
            self.assertEqual(file_sha256(receipt["frame_manifest"]), receipt["frame_manifest_sha256"])
            self.assertEqual(receipt["review"]["motion_perceptual"], "unverified")
            with self.assertRaisesRegex(ValidationError, "Output directory must be new"):
                motionlab.render(scene2d(), Path(temporary) / "render")

    def test_exposure_does_not_mix_shots_at_cut(self):
        scene = scene2d()
        scene["tracks"] = []
        scene["cuts"] = [.5]
        scene["nodes"] = [{"id": "before", "type": "rect", "width": 96, "height": 64, "fill": "#ff0000", "end_s": .5},
                          {"id": "after", "type": "rect", "width": 96, "height": 64, "fill": "#0000ff", "start_s": .5}]
        with tempfile.TemporaryDirectory() as temporary:
            receipt = motionlab.render(scene, Path(temporary) / "cut", samples=8, shutter_angle=360)
            np.testing.assert_array_equal(pixels(receipt, 3)[32, 48], [255, 0, 0, 255])
            np.testing.assert_array_equal(pixels(receipt, 4)[32, 48], [0, 0, 255, 255])
            self.assertTrue(all(exposure["time"] >= .5 for exposure in receipt["frames"][4]["exposure"]))

    def test_true_3d_motion_and_light_are_rendered(self):
        with tempfile.TemporaryDirectory() as temporary:
            receipt = motionlab.render(scene3d(), Path(temporary) / "volume", samples=2)
            self.assertEqual(receipt["backend"], "three-cpu-lambert-zbuffer/1")
            self.assertGreater(len({frame["sha256"] for frame in receipt["frames"]}), 1)
            image = pixels(receipt)
            visible = image[:, :, 3] > 0
            self.assertTrue(visible.any())
            self.assertTrue((~visible).any())
            self.assertGreater(len(np.unique(image[:, :, :3][visible], axis=0)), 2)

    def test_3d_z_buffer_is_independent_of_submission_order(self):
        scene = scene3d()
        scene["frame_count"] = 1
        scene["tracks"] = []
        scene["camera"]["position"] = [0, 0, 5]
        scene["nodes"] = [{"id": "near", "type": "box", "size": [1, 1, 1], "position": [0, 0, 1], "material": {"color": "#ff0000", "unlit": True}},
                          {"id": "far", "type": "box", "size": [2, 2, 1], "position": [0, 0, 0], "material": {"color": "#0000ff", "unlit": True}}]
        with tempfile.TemporaryDirectory() as temporary:
            first = motionlab.render(scene, Path(temporary) / "order1")
            scene["nodes"].reverse()
            second = motionlab.render(scene, Path(temporary) / "order2")
            np.testing.assert_array_equal(pixels(first), pixels(second))
            np.testing.assert_array_equal(pixels(first)[32, 48], [255, 0, 0, 255])

    def test_sonic_candidates_require_semantic_selection_and_retain_evidence(self):
        result = motionlab.sonic_candidates(scene2d())
        self.assertEqual(result["status"], "candidates_only")
        self.assertFalse(result["visibility_is_pixel_verified"])
        self.assertGreater(len(result["candidates"]), 0)
        ids = {item["id"] for item in result["evidence"]}
        for candidate in result["candidates"]:
            self.assertIsNone(candidate["sound_asset"])
            self.assertFalse(candidate["semantic_selection"])
            self.assertLess(candidate["time_s"], 1)
            self.assertTrue(set(candidate["evidence_ids"]).issubset(ids))
        disabled = scene3d()
        disabled["nodes"][0]["sound"] = False
        self.assertEqual(motionlab.sonic_candidates(disabled)["candidates"], [])

    def test_cut_jump_is_not_falsely_reported_as_a_glide(self):
        scene = scene2d()
        scene["cuts"] = [.5]
        scene["tracks"][0]["keys"] = [{"t": 0, "value": 0, "ease": "hold"},
                                         {"t": .5, "value": 70, "ease": "hold"}, {"t": 1, "value": 70}]
        self.assertEqual(motionlab.sonic_candidates(scene)["candidates"], [])

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg preview runtime unavailable")
    def test_mp4_preview_remains_separate_from_rgba(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temporary:
            receipt = motionlab.render(scene2d(), Path(temporary) / "preview.mp4", samples=2)
            self.assertTrue(Path(receipt["preview"]["path"]).is_file())
            self.assertEqual(receipt["preview"]["alpha"], "opaque")
            self.assertEqual(receipt["alpha"], "straight")
            self.assertFalse(receipt["opaque"])
            inspected = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
                                                           "stream=nb_read_frames,r_frame_rate", "-of", "json", receipt["preview"]["path"]]))
            self.assertEqual(int(inspected["streams"][0]["nb_read_frames"]), 8)
            self.assertEqual(inspected["streams"][0]["r_frame_rate"], "8/1")


if __name__ == "__main__":
    unittest.main()
