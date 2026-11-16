"""Real media integration for measured alignment inside a fixed portal window."""
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

from visual_fidelity.planar_portal import (file_sha256, render, render_portal_frame,
                                          sequence_sha256)
from visual_fidelity.subject_alignment import calibrate_alignment, warp_aligned_rgba


FULL = [[0, 0], [1, 0], [1, 1], [0, 1]]
WINDOW = [[.25, .25], [.75, .25], [.75, .75], [.25, .75]]
ANCHORS = {"left_eye": [20, 8], "right_eye": [12, 8], "nose": [16, 11],
           "left_ear": [22, 10], "right_ear": [10, 10],
           "left_shoulder": [26, 24], "right_shoulder": [6, 24]}


def key(frame, quad=FULL, opacity=1., easing="linear"):
    return {"frame": frame, "quad": copy.deepcopy(quad), "opacity": opacity, "easing": easing}


def landmarks(points):
    return {name: {"xy": list(point), "state": "detected", "confidence": .95}
            for name, point in points.items()}


class PortalAlignmentRasterTests(unittest.TestCase):
    def test_roi_matches_independent_premultiplied_affine_warp(self):
        rng = np.random.default_rng(1)
        art = rng.integers(0, 256, (32, 32, 4), dtype=np.uint8)
        art[:, :, 3] = 255
        for scale, angle in ((1, 0), (.75, 0), (.825643, -9.38492), (1.45, 12.3)):
            with self.subTest(scale=scale, rotation=angle):
                radians = np.radians(angle)
                matrix = [[scale * np.cos(radians), -scale * np.sin(radians), 17.3],
                          [scale * np.sin(radians), scale * np.cos(radians), 13.4]]
                actual = render_portal_frame(art, FULL, (64, 64), mapping="screen_reveal",
                                             alignment_matrix=matrix)
                expected = warp_aligned_rgba(art, matrix, (64, 64))
                self.assertLessEqual(int(np.abs(actual.astype(int) - expected.astype(int)).max()), 1)

    def test_scaling_contents_does_not_scale_portal_or_its_occlusion(self):
        yy, xx = np.indices((64, 64))
        art = np.stack([xx * 3, yy * 3, np.full_like(xx, 180)], axis=-1).astype(np.uint8)
        matte = np.zeros((64, 64), np.uint8)
        matte[:, 35:] = 255
        original = render_portal_frame(art, WINDOW, (64, 64), mapping="screen_reveal",
                                       alignment_matrix=[[1, 0, 0], [0, 1, 0]], occlusion=matte)
        smaller = render_portal_frame(art, WINDOW, (64, 64), mapping="screen_reveal",
                                      alignment_matrix=[[.75, 0, 8], [0, .75, 8]], occlusion=matte)
        np.testing.assert_array_equal(original[:, :, 3], smaller[:, :, 3])
        self.assertEqual(int(smaller[30, 34, 3]), 255)
        self.assertEqual(int(smaller[30, 35, 3]), 0)
        self.assertEqual(int(smaller[12, 30, 3]), 0)
        self.assertGreater(int(np.abs(smaller[20:30, 20:30, :3].astype(int) -
                                      original[20:30, 20:30, :3].astype(int)).max()), 1)

    def test_alignment_rejects_aspect_distortion_and_conflicting_placement(self):
        art = np.full((32, 32, 3), 180, np.uint8)
        with self.assertRaisesRegex(ValueError, "aspect ratio"):
            render_portal_frame(art, FULL, (64, 64), mapping="screen_reveal",
                                alignment_matrix=[[1, 0, 0], [0, 1.2, 0]])
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            render_portal_frame(art, FULL, (64, 64), mapping="screen_reveal",
                                alignment_matrix=[[1, 0, 0], [0, 1, 0]], placement=[0, 0, 1, 1])
        with self.assertRaisesRegex(ValueError, "window stays separate"):
            render_portal_frame(art, FULL, (64, 64), mapping="projective",
                                alignment_matrix=[[1, 0, 0], [0, 1, 0]])


class PortalAlignmentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.rate = "12/1"
        self.count = 3
        self.base_rgb = np.full((64, 64, 3), [20, 45, 160], np.uint8)
        yy, xx = np.indices((32, 32))
        self.insert_rgb = np.stack([xx * 7, yy * 7, np.full_like(xx, 40)], axis=-1).astype(np.uint8)
        self.base = self.image("base.png", self.base_rgb, "base-r1")
        self.insert = self.image("insert.png", self.insert_rgb, "insert-r1")
        self.data = {"schema": "planar-portal/1", "revision": "timeline-r2",
                     "width": 64, "height": 64, "fps": self.rate, "frames": self.count,
                     "base": self.base, "insert": self.insert, "mapping": "screen_reveal",
                     "geometry": {"keyframes": [key(0), key(self.count - 1)]}}

    def tearDown(self):
        self.temporary.cleanup()

    def image(self, name, rgb, revision):
        path = self.root / name
        self.assertTrue(cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)))
        return {"kind": "image", "path": name, "sha256": file_sha256(path),
                "origin": "Independent synthetic alignment fixture", "static": True, "revision": revision}

    def binding(self, spec, raster):
        return {"kind": spec["kind"], "sha256": spec["sha256"], "raster": raster,
                "viewport_xywh": spec.get("viewport_xywh", [0, 0, *raster]), "fps": self.rate,
                "frames": 1 if spec["kind"] == "image" else spec["fixture_frames"],
                "revision": spec["revision"],
                "clock": {"start_frame": 0, "step": 0} if spec["kind"] == "image" else spec["clock"]}

    def calibration(self, scale=1.5, offset=(8., 8.), active=None, policy="reveal_base", request_edit=None):
        active = list(range(self.count)) if active is None else active
        target = {name: (np.asarray(xy) * scale + offset).tolist() for name, xy in ANCHORS.items()}
        request = {"schema": "subject-alignment/1", "source": self.binding(self.data["insert"], [32, 32]),
                   "base": self.binding(self.data["base"], [64, 64]),
                   "timeline": {"revision": self.data["revision"], "raster": [64, 64],
                                "fps": self.rate, "frames": self.count},
                   "settings": {"max_rmse_px": 1., "max_anchor_error_px": 2.}, "samples": []}
        for frame in active:
            sample = {"frame": frame, "source_landmarks": landmarks(ANCHORS), "base_landmarks": landmarks(target)}
            for side in ("source", "base"):
                clock = request[side]["clock"]
                sample[side + "_frame"] = clock["start_frame"] + frame * clock["step"]
            request["samples"].append(sample)
        if request_edit is not None:
            request_edit(request)
        plan = calibrate_alignment(request)
        self.data["subject_alignment"] = {"plan": plan, "uncovered_policy": policy}
        return plan

    def manifest(self):
        path = self.root / "portal.json"
        path.write_text(json.dumps(self.data), encoding="utf-8")
        return path

    def read_rgba(self, path):
        return cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGRA2RGBA)

    def assert_rejected(self, pattern):
        output = self.root / "rejected"
        with self.assertRaisesRegex(ValueError, pattern):
            render(self.manifest(), output, mode="layer")
        self.assertFalse(output.exists())

    def test_real_png_layer_uses_fitted_pixels_and_records_actual_assets(self):
        plan = self.calibration()
        result = render(self.manifest(), self.root / "layer", mode="layer")
        expected = warp_aligned_rgba(self.insert_rgb, plan["frames"][0]["matrix"], (64, 64))
        for index in range(self.count):
            actual = self.read_rgba(self.root / "layer" / f"frame-{index:06d}.png")
            self.assertLessEqual(int(np.abs(actual.astype(int) - expected.astype(int)).max()), 1)
        self.assertEqual(result["sources"]["insert"]["sha256"], file_sha256(self.root / "insert.png"))
        self.assertEqual(result["sources"]["base"]["sha256"], file_sha256(self.root / "base.png"))
        self.assertEqual(result["subject_alignment"]["plan_sha256"], plan["sha256"])
        self.assertEqual(len(result["subject_alignment"]["uncovered_frames"]), self.count)
        self.assertFalse(result["subject_alignment"]["depth_reconstruction"])
        self.assertEqual(result["visual_review"], "pending")

    def test_changed_file_bytes_and_rehashed_replacement_are_both_rejected(self):
        self.calibration()
        changed = np.full((32, 32, 3), [250, 1, 30], np.uint8)
        replacement = self.image("insert.png", changed, "insert-r1")
        self.assert_rejected("SHA-256 mismatch")
        self.data["insert"].update(replacement)
        self.assert_rejected("source.sha256 binding mismatch")

    def test_runtime_revision_viewport_and_canvas_binding_cannot_drift(self):
        self.calibration()
        original = copy.deepcopy(self.data)
        changes = [("base", "revision", "new-take"), ("insert", "revision", "new-art"),
                   (None, "revision", "timeline-r3"),
                   ("insert", "viewport_xywh", [0, 0, 30, 30]),
                   (None, "width", 66), (None, "fps", "24/1")]
        for side, field, value in changes:
            with self.subTest(side=side, field=field):
                self.data = copy.deepcopy(original)
                (self.data if side is None else self.data[side])[field] = value
                self.assert_rejected("binding mismatch")

    def test_actual_source_raster_overrides_incorrect_calibration_metadata(self):
        self.calibration(request_edit=lambda request: request["source"].update(
            raster=[40, 40], viewport_xywh=[0, 0, 40, 40]))
        self.assert_rejected("source.raster binding mismatch")

    def test_missing_active_frame_blocks_but_closed_frame_needs_no_fit(self):
        self.calibration(active=[0, 2])
        self.assert_rejected("Every visible portal frame")
        self.data["geometry"]["keyframes"] = [key(0, opacity=0, easing="hold"), key(1), key(2)]
        self.calibration(active=[1, 2])
        result = render(self.manifest(), self.root / "closed-first", mode="layer")
        first = self.read_rgba(self.root / "closed-first/frame-000000.png")
        self.assertEqual(int(first.max()), 0)
        self.assertEqual(result["frames"], 3)

    def test_incompatible_fit_is_blocked_before_render(self):
        def mismatch(request):
            request["samples"][1]["base_landmarks"]["left_shoulder"]["xy"] = [60, 60]
        plan = self.calibration(request_edit=mismatch)
        self.assertEqual(plan["status"], "blocked")
        self.assert_rejected("plan is blocked")

    def test_reject_policy_catches_uncovered_pixels_in_opaque_and_translucent_portals(self):
        for opacity in (1., .5):
            with self.subTest(opacity=opacity):
                self.data["geometry"]["keyframes"] = [key(0, opacity=opacity), key(2, opacity=opacity)]
                self.calibration(scale=.75, offset=(20, 20), policy="reject")
                self.assert_rejected("uncovered portal pixels")

    def test_reject_policy_catches_holes_behind_partial_occlusion(self):
        matte = self.image("occlusion.png", np.full((64, 64, 3), 128, np.uint8), "matte-r1")
        self.data["occlusion"] = {"base_sha256": self.base["sha256"], "coordinate_space": "canvas", "source": matte}
        self.calibration(scale=.75, offset=(20, 20), policy="reject")
        self.assert_rejected("uncovered portal pixels")

    def test_fully_occluded_uncovered_pixels_do_not_require_a_hidden_background(self):
        matte = self.image("occlusion.png", np.full((64, 64, 3), 255, np.uint8), "matte-r1")
        self.data["occlusion"] = {"base_sha256": self.base["sha256"], "coordinate_space": "canvas", "source": matte}
        self.calibration(scale=.75, offset=(20, 20), policy="reject")
        result = render(self.manifest(), self.root / "occluded", mode="layer")
        self.assertFalse(result["subject_alignment"]["uncovered_frames"])
        self.assertEqual(int(self.read_rgba(self.root / "occluded/frame-000001.png")[:, :, 3].max()), 0)

    def test_covered_portal_passes_reject_even_when_full_viewport_is_not_covered(self):
        self.data["geometry"]["keyframes"] = [key(0, WINDOW), key(2, WINDOW)]
        plan = self.calibration(policy="reject")
        self.assertTrue(plan["frames"][0]["coverage"]["requires_background"])
        result = render(self.manifest(), self.root / "covered-window", mode="layer")
        self.assertFalse(result["subject_alignment"]["uncovered_frames"])

    def test_uncovered_policy_is_explicit_and_never_implicit_reference_fill(self):
        self.calibration()
        del self.data["subject_alignment"]["uncovered_policy"]
        self.assert_rejected("Declare uncovered_policy")

    def test_sequence_base_raster_drift_is_caught_in_layer_mode(self):
        files = []
        for frame, shape in enumerate(((64, 64), (60, 64), (64, 64))):
            spec = self.image(f"base-{frame}.png", np.full((*shape, 3), 70 + frame, np.uint8), "base-r1")
            files.append({"path": spec["path"], "sha256": spec["sha256"]})
        self.data["base"] = {"kind": "sequence", "files": files, "sha256": sequence_sha256(files),
                             "fps": self.rate, "origin": "Independent synthetic sequence",
                             "clock": {"start_frame": 0, "step": 1}, "revision": "base-seq-r1", "fixture_frames": 3}
        self.calibration()
        self.assert_rejected("raster|dimensions")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_real_one_second_video_keeps_frame_clocks_and_explicit_base_reveal(self):
        self.count = 12
        def video(name, arrays, revision, start):
            path = self.root / name
            h, w = arrays[0].shape[:2]
            subprocess.run(["ffmpeg", "-v", "error", "-threads", "1", "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", self.rate,
                            "-i", "pipe:0", "-an", "-c:v", "libx264rgb", "-preset", "ultrafast",
                            "-crf", "0", "-threads", "1", str(path)],
                           input=b"".join(array.tobytes() for array in arrays), check=True, capture_output=True)
            return {"kind": "video", "path": name, "sha256": file_sha256(path),
                    "origin": "Independent synthetic video with a unique color per frame",
                    "clock": {"start_frame": start, "step": 1}, "revision": revision,
                    "fixture_frames": len(arrays)}
        bases = [np.full((64, 64, 3), [20, 40 + frame * 3, 160], np.uint8) for frame in range(13)]
        inserts = [np.full((32, 32, 3), [40 + frame * 12, 70, 30], np.uint8) for frame in range(14)]
        self.data["base"] = video("base.mp4", bases, "base-video-r1", 1)
        self.data["insert"] = video("insert.mp4", inserts, "insert-video-r1", 2)
        self.data["frames"] = self.count
        self.data["geometry"]["keyframes"] = [key(0, opacity=0, easing="hold"), key(1), key(11)]
        plan = self.calibration(scale=.75, offset=(20, 20), active=list(range(1, 12)), policy="reveal_base")
        result = render(self.manifest(), self.root / "actual.mp4")
        cap = cv2.VideoCapture(result["output_path"], cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
        decoded = []
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            decoded.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        cap.release()
        self.assertEqual(len(decoded), 12)
        for frame, rgb in enumerate(decoded):
            # Corner stays the actual base; shrink never fills it with source pixels.
            actual_corner = np.median(rgb[2:8, 2:8], axis=(0, 1))
            self.assertLessEqual(float(np.abs(actual_corner - bases[frame + 1][0, 0]).max()), 5.)
            expected_center = bases[frame + 1][0, 0] if frame == 0 else inserts[frame + 2][0, 0]
            self.assertLessEqual(float(np.abs(np.median(rgb[28:36, 28:36], axis=(0, 1)) - expected_center).max()), 5.)
        self.assertEqual(Fraction(result["duration"]), 1)
        self.assertEqual(result["sources"]["insert"]["start_frame"], 2)
        self.assertEqual(result["sources"]["base"]["start_frame"], 1)
        self.assertEqual(result["subject_alignment"]["plan_sha256"], plan["sha256"])
        self.assertEqual([row["frame"] for row in result["subject_alignment"]["uncovered_frames"]], list(range(1, 12)))
        self.assertEqual(result["output_sha256"], file_sha256(self.root / "actual.mp4"))


if __name__ == "__main__":
    unittest.main()
