import copy
import math
import unittest

import numpy as np

from visual_fidelity.subject_alignment import (alignment_for_frame, calibrate_alignment,
                                              fit_similarity, validate_alignment_binding,
                                              warp_aligned_rgba)


POINTS = {"left_eye": [62, 24], "right_eye": [38, 24], "nose": [50, 34],
          "left_ear": [68, 30], "right_ear": [32, 30],
          "left_shoulder": [80, 75], "right_shoulder": [20, 75]}


def controls(points):
    return {name: {"xy": list(xy), "state": "detected", "confidence": .9}
            for name, xy in points.items()}


def transformed(points, scale=.8, angle=5., translation=(12., 9.)):
    a = math.radians(angle)
    matrix = scale * np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    return {name: (matrix @ xy + translation).tolist() for name, xy in points.items()}


def request(target=None):
    media = {"kind": "video", "sha256": "b" * 64, "raster": [100, 100],
             "viewport_xywh": [0, 0, 100, 100], "fps": "30/1", "frames": 5,
             "revision": "base-r2", "clock": {"start_frame": 0, "step": 1}}
    source = {**copy.deepcopy(media), "kind": "image", "sha256": "a" * 64, "frames": 1,
              "revision": "source-r1", "clock": {"start_frame": 0, "step": 0}}
    return {"schema": "subject-alignment/1", "source": source, "base": media,
            "timeline": {"raster": [100, 100], "fps": "30/1", "frames": 5, "revision": "edit-r2"},
            "settings": {}, "samples": [{"frame": 0, "source_frame": 0, "base_frame": 0,
                                           "source_landmarks": controls(POINTS),
                                           "base_landmarks": controls(target or transformed(POINTS))}]}


class SimilarityTests(unittest.TestCase):
    def test_measured_uniform_transform_recovers_scale_rotation_translation(self):
        data = request()
        original = copy.deepcopy(data)
        plan = calibrate_alignment(data)
        result = alignment_for_frame(plan, 0)
        self.assertEqual(data, original)
        self.assertEqual(plan["status"], "ready")
        self.assertAlmostEqual(result["scale"], .8)
        self.assertAlmostEqual(result["fit"]["rotation_deg"], 5.)
        np.testing.assert_allclose(result["fit"]["translation_px"], [12., 9.], atol=1e-10)
        self.assertLess(result["fit"]["rmse_px"], 1e-10)
        a = np.asarray(result["matrix"])[:, :2]
        np.testing.assert_allclose(a.T @ a, np.eye(2) * .8 ** 2, atol=1e-12)
        weights = result["anchors"]
        self.assertAlmostEqual(sum(weights[n]["fit_weight"] for n in ("left_shoulder", "right_shoulder")), .5)

    def test_crop_coordinates_and_normalized_measurements_map_to_actual_canvas(self):
        data = request(POINTS)
        data["source"]["coordinate_mapping"] = {
            "raster": [200, 300], "viewport_xywh": [20, 40, 100, 100], "units": "normalized"}
        for record in data["samples"][0]["source_landmarks"].values():
            record["xy"] = [(record["xy"][0] + 20) / 200, (record["xy"][1] + 40) / 300]
        data["base"]["raster"] = [200, 200]
        data["base"]["viewport_xywh"] = [50, 50, 100, 100]
        data["base"]["coordinate_mapping"] = {
            "raster": [100, 100], "viewport_xywh": [0, 0, 100, 100], "units": "pixels"}
        data["timeline"]["raster"] = [200, 200]
        result = alignment_for_frame(calibrate_alignment(data), 0)
        np.testing.assert_allclose(result["matrix"], [[1, 0, 50], [0, 1, 50]], atol=1e-10)
        self.assertTrue(result["coverage"]["covers_target_viewport"])

    def test_explicit_reduction_preserves_anatomical_pivot_and_reports_holes(self):
        data = request(POINTS)
        data["settings"] = {"scale_adjustment": .9, "pivot": "head_center"}
        result = alignment_for_frame(calibrate_alignment(data), 0)
        matrix = np.asarray(result["matrix"])
        pivot = np.array([50., 24.])
        np.testing.assert_allclose(matrix[:, :2] @ pivot + matrix[:, 2], pivot)
        self.assertAlmostEqual(result["scale"], .9)
        self.assertGreater(result["adjusted_rmse_px"], 0)
        self.assertTrue(result["coverage"]["requires_background"])
        self.assertFalse(result["coverage"]["alpha_coverage_verified"])

    def test_bad_anatomical_fit_blocks_instead_of_anisotropic_stretch(self):
        target = {name: [xy[0], .5 * xy[1] + 15] for name, xy in POINTS.items()}
        data = request(target)
        data["settings"] = {"max_rmse_px": 2, "max_anchor_error_px": 3}
        plan = calibrate_alignment(data)
        self.assertEqual(plan["status"], "blocked")
        self.assertIn("fit_rmse_exceeds_tolerance", plan["frames"][0]["issues"])
        with self.assertRaisesRegex(ValueError, "blocked"):
            alignment_for_frame(plan, 0)

    def test_reflection_and_degenerate_controls_rejected(self):
        with self.assertRaisesRegex(ValueError, "reflection"):
            fit_similarity([[0, 0], [2, 0], [0, 2]], [[0, 0], [-2, 0], [0, 2]])
        with self.assertRaisesRegex(ValueError, "collinear"):
            fit_similarity([[0, 0], [1, 1], [2, 2]], [[0, 0], [1, 1], [2, 2]])

    def test_solver_does_not_mutate_caller_weights_and_zero_rotation_allows_roundoff(self):
        points = list(POINTS.values())
        weights = np.full(len(points), 5.)
        fit_similarity(points, points, weights)
        np.testing.assert_array_equal(weights, np.full(len(points), 5.))
        data = request(POINTS)
        data["settings"]["max_rotation_deg"] = 0
        self.assertEqual(calibrate_alignment(data)["status"], "ready")

    def test_scale_rotation_and_authored_adjustment_each_obey_tolerances(self):
        cases = [(request(), {"min_scale": .9}, "scale_outside_limits"),
                 (request(), {"max_rotation_deg": 2}, "rotation_outside_limits"),
                 (request(POINTS), {"scale_adjustment": .3}, "adjusted_anchor_error_exceeds_tolerance")]
        for data, settings, issue in cases:
            with self.subTest(issue=issue):
                data["settings"] = settings
                plan = calibrate_alignment(data)
                self.assertEqual(plan["status"], "blocked")
                self.assertIn(issue, plan["frames"][0]["issues"])

    def test_coordinate_mapping_cannot_distort_aspect(self):
        data = request()
        data["source"]["coordinate_mapping"] = {
            "raster": [100, 200], "viewport_xywh": [0, 0, 100, 200], "units": "pixels"}
        with self.assertRaisesRegex(ValueError, "aspect"):
            calibrate_alignment(data)


class EvidenceAndBindingTests(unittest.TestCase):
    def test_missing_or_unscored_required_controls_are_explicit_blockers(self):
        for change, reason in (("missing", "missing"), (None, "unknown_confidence"), (.2, "low_confidence")):
            with self.subTest(reason=reason):
                data = request()
                landmarks = data["samples"][0]["base_landmarks"]
                if change == "missing":
                    del landmarks["left_shoulder"]
                else:
                    landmarks["left_shoulder"]["confidence"] = change
                plan = calibrate_alignment(data)
                self.assertEqual(plan["status"], "blocked")
                self.assertTrue(any(g["reason"] == reason and g["required"] for g in plan["frames"][0]["gaps"]))

    def test_manual_controls_keep_unknown_score_and_require_measurement_review(self):
        data = request()
        for side in ("source_landmarks", "base_landmarks"):
            for landmark in data["samples"][0][side].values():
                landmark.update(state="measured", confidence=None, reviewed=True, method="manual frame inspection")
        plan = calibrate_alignment(data)
        self.assertEqual(plan["status"], "ready")
        self.assertIsNone(plan["frames"][0]["confidence"]["minimum_detector_score"])
        data["samples"][0]["base_landmarks"]["left_eye"]["reviewed"] = False
        self.assertEqual(calibrate_alignment(data)["status"], "blocked")

    def test_optional_gap_not_silently_replaced_and_inferred_needs_opt_in(self):
        data = request()
        del data["samples"][0]["source_landmarks"]["nose"]
        plan = calibrate_alignment(data)
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["frames"][0]["gaps"][0]["anchor"], "nose")
        self.assertNotIn("nose", plan["frames"][0]["anchors"])
        data["samples"][0]["base_landmarks"]["left_eye"]["state"] = "inferred"
        self.assertEqual(calibrate_alignment(data)["status"], "blocked")
        data["settings"]["allow_inferred"] = True
        self.assertEqual(calibrate_alignment(data)["status"], "ready")

    def test_no_implicit_temporal_gap_fill_freeze_or_cross_clock(self):
        data = request()
        plan = calibrate_alignment(data)
        self.assertFalse(plan["complete_coverage"])
        with self.assertRaisesRegex(ValueError, "Missing alignment frame"):
            alignment_for_frame(plan, 1)
        data["samples"][0]["base_frame"] = 1
        with self.assertRaisesRegex(ValueError, "clock"):
            calibrate_alignment(data)
        data = request()
        data["base"]["clock"]["step"] = 0
        with self.assertRaisesRegex(ValueError, "freeze"):
            calibrate_alignment(data)

    def test_runtime_binding_rejects_other_bytes_raster_viewport_clock_fps_and_revision(self):
        data = request()
        plan = calibrate_alignment(data)
        binding = {k: copy.deepcopy(data[k]) for k in ("source", "base", "timeline")}
        self.assertTrue(validate_alignment_binding(plan, binding))
        changes = [("source", "sha256", "c" * 64), ("base", "sha256", "c" * 64),
                   ("base", "revision", "other-take"), ("source", "revision", "new-design"),
                   ("base", "raster", [120, 100]), ("base", "fps", "24/1"),
                   ("base", "viewport_xywh", [0, 0, 90, 90]),
                   ("base", "clock", {"start_frame": 1, "step": 1}),
                   ("timeline", "revision", "edit-r3"), ("timeline", "frames", 4)]
        for side, key, value in changes:
            with self.subTest(side=side, field=key):
                other = copy.deepcopy(binding)
                other[side][key] = value
                with self.assertRaisesRegex(ValueError, "binding mismatch"):
                    validate_alignment_binding(plan, other)

    def test_explicit_measurement_mapping_change_and_plan_tamper_are_rejected(self):
        data = request()
        plan = calibrate_alignment(data)
        binding = {k: copy.deepcopy(data[k]) for k in ("source", "base", "timeline")}
        binding["source"]["coordinate_mapping"] = {
            "raster": [100, 100], "viewport_xywh": [0, 0, 100, 100], "units": "normalized"}
        with self.assertRaisesRegex(ValueError, "coordinate_mapping"):
            validate_alignment_binding(plan, binding)
        plan["frames"][0]["matrix"][0][2] += 1
        with self.assertRaisesRegex(ValueError, "changed"):
            alignment_for_frame(plan, 0)

    def test_rational_fps_is_normalized_but_unverified_float_or_bool_refused(self):
        data = request()
        data["source"]["fps"] = "60/2"
        self.assertEqual(calibrate_alignment(data)["source"]["fps"], "30/1")
        data["source"]["fps"] = 30
        with self.assertRaisesRegex(ValueError, "rational"):
            calibrate_alignment(data)
        data = request()
        data["samples"][0]["frame"] = True
        with self.assertRaisesRegex(ValueError, "integer"):
            calibrate_alignment(data)


class AlphaWarpTests(unittest.TestCase):
    def test_uncovered_background_is_transparent_and_no_invisible_color_bleeds(self):
        rgba = np.zeros((12, 12, 4), dtype=np.uint8)
        rgba[:, :, 0] = 255
        rgba[2:10, 2:10] = [0, 255, 0, 255]
        result = warp_aligned_rgba(rgba, [[1.25, 0, 2.3], [0, 1.25, 3.4]], (24, 24))
        visible = result[:, :, 3] > 0
        self.assertTrue(visible.any())
        self.assertTrue(np.any((result[:, :, 3] > 0) & (result[:, :, 3] < 255)))
        self.assertEqual(int(result[:, :, 0][visible].max()), 0)
        np.testing.assert_array_equal(result[0, 0], [0, 0, 0, 0])

    def test_renderer_refuses_affine_stretch_and_reflection(self):
        rgb = np.full((12, 12, 3), 128, dtype=np.uint8)
        for matrix in ([[1, 0, 0], [0, 2, 0]], [[-1, 0, 10], [0, 1, 0]]):
            with self.assertRaisesRegex(ValueError, "aspect ratio"):
                warp_aligned_rgba(rgb, matrix, (20, 20))


if __name__ == "__main__":
    unittest.main()
