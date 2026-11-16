import copy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np

from visual_fidelity.planar_portal import (evaluate_quad, file_sha256, render,
                                          render_portal_frame, sequence_sha256)


QUAD = [[0, 0], [1, 0], [1, 1], [0, 1]]


def key(frame, quad=QUAD, opacity=1, easing="linear"):
    return {"frame": frame, "quad": copy.deepcopy(quad), "opacity": opacity, "easing": easing}


class PortalGeometryTests(unittest.TestCase):
    def test_screen_reveal_preserves_content_orientation(self):
        image = np.zeros((64, 64, 3), dtype=np.uint8)
        image[:, :, 0] = np.arange(64, dtype=np.uint8)[None, :] * 4
        image[:, :, 1] = np.arange(64, dtype=np.uint8)[:, None] * 4
        quad = [[0, .4], [1, .1], [1, .6], [0, .9]]
        reveal = render_portal_frame(image, quad, (64, 64), mapping="screen_reveal", placement=[0, 0, 1, 1])
        np.testing.assert_array_equal(reveal[32, 32, :3], image[32, 32])
        np.testing.assert_array_equal(reveal[38, 20, :3], image[38, 20])
        self.assertEqual(int(reveal[0, 32, 3]), 0)
        self.assertEqual(int(reveal[32, 32, 3]), 255)
        projected = render_portal_frame(image, quad, (64, 64), mapping="projective")
        self.assertGreater(abs(int(projected[30, 40, 1]) - int(image[30, 40, 1])), 10)

    def test_projective_corners_are_not_a_bounding_box_fit(self):
        image = np.zeros((40, 40, 3), dtype=np.uint8)
        image[:20, :20] = [255, 0, 0]
        image[:20, 20:] = [0, 255, 0]
        image[20:, 20:] = [0, 0, 255]
        image[20:, :20] = [255, 255, 0]
        quad = [[.1, .1], [.9, .2], [.8, .9], [.2, .8]]
        out = render_portal_frame(image, quad, (100, 100), mapping="projective")
        np.testing.assert_array_equal(out[20, 20], [255, 0, 0, 255])
        np.testing.assert_array_equal(out[29, 78], [0, 255, 0, 255])
        np.testing.assert_array_equal(out[76, 72], [0, 0, 255, 255])
        np.testing.assert_array_equal(out[70, 27], [255, 255, 0, 255])
        self.assertEqual(int(out[11, 80, 3]), 0)

    def test_premultiplied_resampling_and_occlusion(self):
        image = np.zeros((16, 16, 4), dtype=np.uint8)
        image[:, :, 0] = 255  # Invisible red must not contaminate the edge.
        image[4:12, 4:12] = [0, 255, 0, 255]
        matte = np.zeros((64, 64), dtype=np.uint8)
        matte[:, 32:] = 255
        out = render_portal_frame(image, QUAD, (64, 64), mapping="projective", occlusion=matte)
        visible = out[:, :, 3] > 0
        self.assertTrue(visible.any())
        self.assertEqual(int(out[:, :, 0][visible].max()), 0)
        self.assertEqual(int(out[:, 32:, 3].max()), 0)
        self.assertTrue(np.any((out[:, :, 3] > 0) & (out[:, :, 3] < 255)))

    def test_explicit_easing_and_no_extrapolation(self):
        moved = (np.asarray(QUAD) + [.4, 0]).tolist()
        linear = [key(0), key(4, moved)]
        eased = [key(0, easing="smoothstep"), key(4, moved)]
        held = [key(0, easing="hold"), key(4, moved)]
        self.assertAlmostEqual(evaluate_quad(linear, 1)["quad"][0][0], .1)
        self.assertAlmostEqual(evaluate_quad(eased, 1)["quad"][0][0], .0625)
        self.assertEqual(evaluate_quad(held, 3)["quad"], QUAD)
        self.assertEqual(evaluate_quad(held, 4)["quad"], moved)
        with self.assertRaisesRegex(ValueError, "no implicit end hold"):
            evaluate_quad(linear, 5)
        del linear[0]["easing"]
        with self.assertRaisesRegex(ValueError, "explicit"):
            evaluate_quad(linear, 0)

    def test_closed_offscreen_and_interpolated_fold(self):
        image = np.full((8, 8, 3), 255, dtype=np.uint8)
        offscreen = [[-.5, -.5], [1.5, -.5], [1.5, 1.5], [-.5, 1.5]]
        out = render_portal_frame(image, offscreen, (8, 8), mapping="screen_reveal", placement=[0, 0, 1, 1])
        self.assertTrue(np.all(out[:, :, 3] == 255))
        closed = [[.5, .5]] * 4
        self.assertFalse(render_portal_frame(image, closed, (8, 8), mapping="projective", opacity=0).any())
        with self.assertRaisesRegex(ValueError, "nondegenerate"):
            render_portal_frame(image, closed, (8, 8), mapping="projective", opacity=.1)
        opposite = [[1, 1], [0, 1], [0, 0], [1, 0]]
        with self.assertRaisesRegex(ValueError, "nondegenerate"):
            evaluate_quad([key(0), key(2, opposite)], 1)
        bowtie = [[0, 0], [1, 1], [1, 0], [0, 1]]
        with self.assertRaises(ValueError):
            evaluate_quad([key(0, bowtie, opacity=0)], 0)


class PortalSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        base = np.full((48, 64, 3), [20, 45, 75], dtype=np.uint8)
        self.base = self.image("base.png", base)
        self.insert = self.image("insert.png", np.full((24, 32, 3), [230, 70, 20], dtype=np.uint8))
        self.data = {"schema": "planar-portal/1", "width": 64, "height": 48,
                     "fps": "30/1", "frames": 3, "mapping": "screen_reveal",
                     "placement": [0, 0, 1, 1], "base": self.base, "insert": self.insert,
                     "geometry": {"keyframes": [key(0), key(2)]}}

    def tearDown(self):
        self.temporary.cleanup()

    def image(self, name, rgb):
        path = self.root / name
        self.assertTrue(cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)))
        return {"kind": "image", "path": name, "sha256": file_sha256(path),
                "origin": "Synthetic independent fixture", "static": True}

    def manifest(self):
        path = self.root / "portal.json"
        path.write_text(json.dumps(self.data), encoding="utf-8")
        return path

    def test_real_alpha_layer_import_and_source_integrity(self):
        self.data["geometry"]["keyframes"] = [key(0, opacity=0, easing="hold"), key(1), key(2)]
        hashes = [file_sha256(self.root / spec["path"]) for spec in (self.base, self.insert)]
        result = render(self.manifest(), self.root / "layer", mode="layer")
        from editorial_engine.motion_assets import load_layer
        layer = load_layer(result["layer_manifest"])
        self.assertEqual(layer["frame_count"], 3)
        self.assertEqual(layer["alpha"], "straight")
        first = cv2.imread(layer["frames"][0]["path"], cv2.IMREAD_UNCHANGED)
        second = cv2.imread(layer["frames"][1]["path"], cv2.IMREAD_UNCHANGED)
        self.assertEqual(int(first[:, :, 3].max()), 0)
        self.assertEqual(int(second[24, 32, 3]), 255)
        self.assertEqual(result["continuous_playback"], "pending")
        self.assertEqual(result["audio"], "not_rendered")
        self.assertEqual(hashes, [file_sha256(self.root / spec["path"]) for spec in (self.base, self.insert)])

    def test_wrong_hash_wrong_occlusion_binding_and_output_preservation(self):
        self.data["insert"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            render(self.manifest(), self.root / "no-layer", mode="layer")
        self.assertFalse((self.root / "no-layer").exists())
        self.data["insert"]["sha256"] = file_sha256(self.root / "insert.png")
        self.data["occlusion"] = {"base_sha256": "0" * 64, "coordinate_space": "canvas", "source": self.base}
        with self.assertRaisesRegex(ValueError, "actual base SHA"):
            render(self.manifest(), self.root / "no-layer", mode="layer")
        del self.data["occlusion"]
        existing = self.root / "existing.mp4"
        existing.write_bytes(b"preserve exactly")
        with self.assertRaisesRegex(ValueError, "already exists"):
            render(self.manifest(), existing)
        self.assertEqual(existing.read_bytes(), b"preserve exactly")

    def test_manifest_receipt_hash_is_bound_to_the_bytes_actually_parsed(self):
        path = self.manifest()
        from visual_fidelity import planar_portal
        original = planar_portal._key_states
        def change_after_parsing(keys):
            changed = json.loads(path.read_bytes())
            changed["revision_note"] = "Changed after the render parsed its snapshot"
            path.write_text(json.dumps(changed), encoding="utf-8")
            return original(keys)
        with mock.patch.object(planar_portal, "_key_states", side_effect=change_after_parsing):
            with self.assertRaisesRegex(ValueError, "Manifest changed during rendering"):
                render(path, self.root / "changed-manifest", mode="layer")
        self.assertFalse((self.root / "changed-manifest").exists())

    def test_sequence_is_ordered_hashed_and_never_filled_or_retimed(self):
        files = []
        for i, color in enumerate(([200, 30, 20], [20, 200, 30], [30, 20, 200])):
            item = self.image(f"take-{i}.png", np.full((24, 32, 3), color, dtype=np.uint8))
            files.append({"path": item["path"], "sha256": item["sha256"]})
        self.data["insert"] = {"kind": "sequence", "files": files, "sha256": sequence_sha256(files),
                               "fps": "30/1", "origin": "Three original source frames",
                               "clock": {"start_frame": 0, "step": 1}}
        result = render(self.manifest(), self.root / "sequence", mode="layer")
        for i in range(3):
            actual = cv2.imread(str(self.root / "sequence" / f"frame-{i:06d}.png"), cv2.IMREAD_UNCHANGED)
            expected = cv2.imread(str(self.root / f"take-{i}.png"))
            np.testing.assert_array_equal(actual[24, 32, :3], expected[12, 16])
        self.assertEqual(result["sources"]["insert"]["source_frames"], 3)
        for change, message in (({"fps": "24/1"}, "FPS"),
                                ({"clock": {"start_frame": 1, "step": 1}}, "cover"),
                                ({"clock": {"start_frame": 0, "step": 0}}, "step:1")):
            original = copy.deepcopy(self.data["insert"])
            self.data["insert"].update(change)
            with self.assertRaisesRegex(ValueError, message):
                render(self.manifest(), self.root / "invalid", mode="layer")
            self.data["insert"] = original

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_actual_video_decode_composite_and_exact_clock(self):
        source = self.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x112233:s=64x48:r=30",
                        "-frames:v", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source)], check=True)
        self.data["base"] = {"kind": "video", "path": "source.mp4", "sha256": file_sha256(source),
                             "origin": "Independent synthetic source video", "clock": {"start_frame": 0, "step": 1}}
        self.data["geometry"]["keyframes"] = [key(0, opacity=0, easing="hold"), key(1), key(2)]
        result = render(self.manifest(), self.root / "composite.mp4")
        cap = cv2.VideoCapture(result["output_path"])
        values = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            values.append(frame[24, 32, ::-1].copy())
        cap.release()
        self.assertEqual(len(values), 3)
        self.assertLess(int(values[0][0]), 40)
        self.assertGreater(int(values[1][0]), 210)
        self.assertEqual(result["output_sha256"], file_sha256(self.root / "composite.mp4"))
        self.assertEqual(Fraction(result["duration"]), Fraction(1, 10))
        self.assertEqual(result["sources"]["base"]["sha256"], file_sha256(source))
        self.data["fps"] = "24/1"
        with self.assertRaisesRegex(ValueError, "FPS differs"):
            render(self.manifest(), self.root / "wrong-clock.mp4")
        self.assertFalse((self.root / "wrong-clock.mp4").exists())


if __name__ == "__main__":
    unittest.main()
