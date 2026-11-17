"""Synthetic clock/geometry regressions for measured motion curves.

These tests validate equations, supported evidence and serialization.  They do
not establish tracking quality or visual approval of a reference recreation.
"""

import copy
from fractions import Fraction
import json
import math
import unittest

import numpy as np

from visual_fidelity.motion_profile import (
    evaluate_element, evaluate_kinematics, fit_profile, profile_digest,
    sample_times, validate_profile,
)


def observations(specs, *, first_pts=0, time_base="1/15360"):
    samples = []
    for index, fields in enumerate(specs):
        row = {"frame": index, "pts": first_pts + index * 512, "segment": "entry",
               "position_px": [360, 640], "scale": 1, "angle_deg_unwrapped": 0,
               "confidence": None, "visibility": "visible", "status": "observed"}
        row.update(fields)
        samples.append(row)
    return {"schema": "element-motion-observations/1",
            "source": {"sha256": "a" * 64, "width": 720, "height": 1280,
                       "time_base": time_base, "first_pts": first_pts,
                       "coordinate_convention": "opencv_pixel_centers", "rotation_ccw_applied": 0},
            "elements": [{"id": "panel", "model": "similarity_2d",
                          "reference": {"size_px": [20, 10], "anchor": "center"}, "samples": samples}]}


class MotionProfileTests(unittest.TestCase):
    def test_centered_zoom_has_zero_center_speed_but_moving_corners(self):
        profile = fit_profile(observations([{"scale": .5}, {"scale": 1}, {"scale": 2}]))
        k = evaluate_kinematics(profile, "panel", 1 / 30)
        log_speed = 30 * math.log(2)
        self.assertEqual(k["velocity_px_s"], [0, 0])
        self.assertEqual(k["speed_px_s"], 0)
        self.assertAlmostEqual(k["log_scale_velocity_per_s"], log_speed)
        self.assertAlmostEqual(k["scale_velocity_per_s"], log_speed)
        self.assertAlmostEqual(k["scale_acceleration_per_s2"], log_speed ** 2)
        self.assertAlmostEqual(k["corners"][0]["speed_px_s"], math.hypot(10, 5) * log_speed)
        np.testing.assert_allclose(k["corners"][0]["position_px"], [350, 635])
        self.assertTrue(validate_profile(json.loads(json.dumps(profile))))

    def test_centered_ccw_rotation_and_complete_turns_are_preserved(self):
        profile = fit_profile(observations([{"angle_deg_unwrapped": 0}, {"angle_deg_unwrapped": 90},
                                            {"angle_deg_unwrapped": 360}]))
        k = evaluate_kinematics(profile, "panel", 1 / 30)
        self.assertEqual(k["speed_px_s"], 0)
        self.assertGreater(k["angular_velocity_deg_s"], 0)
        # OpenCV +90 turns the top-left offset (-10,-5) into (-5,+10).
        np.testing.assert_allclose(k["corners"][0]["position_px"], [355, 650], atol=1e-10)
        expected = math.radians(k["angular_velocity_deg_s"]) * math.hypot(10, 5)
        self.assertAlmostEqual(k["corners"][0]["speed_px_s"], expected)
        self.assertEqual(evaluate_element(profile, "panel", 2 / 30)["angle_deg_unwrapped"], 360)

    def test_overshoot_and_reversal_are_not_replaced_by_endpoint_easing(self):
        profile = fit_profile(observations([{"position_px": [0, 0]}, {"position_px": [12, 0]},
                                            {"position_px": [10, 0]}, {"position_px": [10, 0]}]))
        self.assertEqual(evaluate_element(profile, "panel", 1 / 30)["position_px"], [12, 0])
        self.assertGreater(evaluate_kinematics(profile, "panel", .5 / 30)["velocity_px_s"][0], 0)
        self.assertLess(evaluate_kinematics(profile, "panel", 1.5 / 30)["velocity_px_s"][0], 0)
        self.assertEqual(evaluate_kinematics(profile, "panel", 2.5 / 30)["velocity_px_s"], [0, 0])
        for t in np.linspace(0, .1, 41):
            self.assertLessEqual(evaluate_element(profile, "panel", float(t))["position_px"][0], 12)

    def test_observed_acceleration_is_derivative_of_render_pose(self):
        profile = fit_profile(observations([
            {"position_px": [100, 200], "scale": 1, "angle_deg_unwrapped": 10},
            {"position_px": [120, 210], "scale": 1.4, "angle_deg_unwrapped": 25},
            {"position_px": [150, 215], "scale": 2, "angle_deg_unwrapped": 40},
        ]))
        t, epsilon = .02, 1e-6
        minus = evaluate_kinematics(profile, "panel", t - epsilon)
        at = evaluate_kinematics(profile, "panel", t)
        plus = evaluate_kinematics(profile, "panel", t + epsilon)
        for i, probe in enumerate(at["corners"]):
            numerical_velocity = (np.asarray(plus["corners"][i]["position_px"]) - minus["corners"][i]["position_px"]) / (2 * epsilon)
            numerical_acceleration = (np.asarray(plus["corners"][i]["velocity_px_s"]) - minus["corners"][i]["velocity_px_s"]) / (2 * epsilon)
            np.testing.assert_allclose(probe["velocity_px_s"], numerical_velocity, rtol=1e-7, atol=1e-5)
            np.testing.assert_allclose(probe["acceleration_px_s2"], numerical_acceleration, rtol=1e-7, atol=1e-3)

    def test_explicit_missing_sample_blocks_every_interpolation_policy(self):
        data = observations([{}, {"status": "missing"}, {}])
        profile = fit_profile(data, max_gap_frames=10)
        for t in (.5 / 30, 1 / 30, 1.5 / 30):
            pose = evaluate_element(profile, "panel", t)
            self.assertIsNone(pose["position_px"])
            self.assertIsNone(pose["scale"])
        self.assertEqual(evaluate_element(profile, "panel", 0)["channel_status"]["position_px"], "observed")
        self.assertIsNone(evaluate_kinematics(profile, "panel", 0)["speed_px_s"])

    def test_omitted_frame_gap_only_bridges_with_explicit_setting(self):
        data = observations([{"position_px": [0, 0]}, {"frame": 2, "pts": 1024, "position_px": [20, 0]}])
        self.assertIsNone(evaluate_element(fit_profile(data), "panel", 1 / 30)["position_px"])
        profile = fit_profile(data, max_gap_frames=2)
        self.assertEqual(evaluate_element(profile, "panel", 1 / 30)["position_px"], [10, 0])
        coverage = profile["elements"][0]["channels"]["position_px"]["coverage"]
        self.assertEqual(coverage["interpolated_omitted_frames"], 1)
        self.assertAlmostEqual(coverage["observation_fraction"], 2 / 3)

    def test_segment_changes_and_cut_before_do_not_create_speed_spikes(self):
        for marker in ({"segment": "second-shot"}, {"cut_before": True}):
            with self.subTest(marker=marker):
                data = observations([{"position_px": [0, 0]}, {"position_px": [1, 0]},
                                     {"position_px": [999, 0], **marker}])
                profile = fit_profile(data)
                self.assertIsNone(evaluate_element(profile, "panel", 1.5 / 30)["position_px"])
                self.assertAlmostEqual(evaluate_kinematics(profile, "panel", .5 / 30)["speed_px_s"], 30)
                self.assertIsNone(evaluate_kinematics(profile, "panel", 2 / 30)["speed_px_s"])

    def test_partial_channel_support_does_not_hide_other_motion(self):
        profile = fit_profile(observations([{"position_px": [0, 0]}, {"position_px": [5, 0], "scale": None},
                                            {"position_px": [10, 0]}]))
        pose = evaluate_element(profile, "panel", 1 / 30)
        self.assertEqual(pose["position_px"], [5, 0])
        self.assertIsNone(pose["scale"])
        self.assertEqual(pose["angle_deg_unwrapped"], 0)
        self.assertIsNone(evaluate_kinematics(profile, "panel", 1 / 30)["corners"])

    def test_unknown_confidence_is_preserved_and_threshold_is_explicit(self):
        data = observations([{}, {"confidence": .8}, {"confidence": .2}])
        no_filter = fit_profile(data)
        channel = no_filter["elements"][0]["channels"]["scale"]
        self.assertEqual(channel["segments"][0]["confidence"], [None, .8, .2])
        self.assertEqual(channel["coverage"]["unknown_confidence_retained"], 1)
        filtered = fit_profile(data, min_confidence=.5)
        self.assertIsNone(evaluate_element(filtered, "panel", 0)["scale"])
        self.assertEqual(evaluate_element(filtered, "panel", 1 / 30)["scale"], 1)
        self.assertIsNone(evaluate_element(filtered, "panel", 2 / 30)["scale"])
        self.assertEqual(filtered["elements"][0]["coverage"]["rejection_reasons"], {"unknown_confidence": 1, "low_confidence": 1})

    def test_occlusion_is_missing_support_not_zero_opacity(self):
        profile = fit_profile(observations([{}, {"visibility": "occluded"}, {}]))
        pose = evaluate_element(profile, "panel", 1 / 30)
        self.assertIsNone(pose["position_px"])
        self.assertNotIn("opacity", pose)
        self.assertEqual(profile["elements"][0]["coverage"]["rejection_reasons"], {"occluded": 1})

    def test_no_extrapolation_and_singleton_has_unknown_derivatives(self):
        profile = fit_profile(observations([{}]))
        for t in (-1e-9, 1e-9):
            self.assertIsNone(evaluate_element(profile, "panel", t)["scale"])
        self.assertEqual(evaluate_element(profile, "panel", 0)["scale"], 1)
        self.assertIsNone(evaluate_kinematics(profile, "panel", 0)["angular_velocity_deg_s"])
        self.assertIsNone(evaluate_kinematics(profile, "panel", 0)["corners"][0]["speed_px_s"])

    def test_vfr_uses_pts_and_preserves_first_timestamp(self):
        data = observations([{"pts": 9000, "position_px": [0, 0]},
                             {"pts": 9010, "position_px": [1, 0]},
                             {"pts": 9040, "position_px": [4, 0]}], first_pts=9000, time_base="1/1000")
        data["source"]["fps"] = "30000/1001"
        profile = fit_profile(data)
        self.assertEqual(sample_times(profile, "panel"), [0, .01, .04])
        self.assertAlmostEqual(evaluate_element(profile, "panel", .025)["position_px"][0], 2.5)
        self.assertAlmostEqual(evaluate_kinematics(profile, "panel", .025)["speed_px_s"], 100)
        self.assertEqual(profile["source"]["first_pts"], 9000)
        self.assertTrue(validate_profile(profile))

    def test_rational_clock_large_pts_and_duplicate_images(self):
        first = 2 ** 60
        data = observations([{"pts": first}, {"pts": first + 1001}, {"pts": first + 2002}],
                            first_pts=first, time_base="1/30000")
        profile = fit_profile(data)
        expected = float(Fraction(1001, 30000))
        self.assertEqual(sample_times(profile, "panel")[1], expected)
        self.assertEqual(evaluate_kinematics(profile, "panel", expected)["speed_px_s"], 0)
        self.assertEqual(evaluate_element(profile, "panel", expected)["channel_status"]["scale"], "observed")

    def test_linear_method_has_correct_units_and_serializes(self):
        profile = fit_profile(observations([{"position_px": [0, 0]}, {"position_px": [3, 4]}]), method="linear")
        k = evaluate_kinematics(profile, "panel", .5 / 30)
        self.assertAlmostEqual(k["speed_px_s"], 150)
        self.assertEqual(k["acceleration_px_s2"], [0, 0])
        self.assertTrue(validate_profile(json.loads(json.dumps(profile))))

    def test_independent_elements_do_not_cancel_each_others_velocity(self):
        data = observations([{"position_px": [0, 0]}, {"position_px": [10, 0]}])
        second = copy.deepcopy(data["elements"][0])
        second["id"] = "second"
        second["samples"][1]["position_px"] = [-10, 0]
        data["elements"].append(second)
        profile = fit_profile(data)
        self.assertAlmostEqual(evaluate_kinematics(profile, "panel", .5 / 30)["velocity_px_s"][0], 300)
        self.assertAlmostEqual(evaluate_kinematics(profile, "second", .5 / 30)["velocity_px_s"][0], -300)

    def test_hash_is_order_independent_and_detects_changes(self):
        profile = fit_profile(observations([{}, {"scale": 2}]))
        reordered = json.loads(json.dumps(profile, sort_keys=True))
        self.assertEqual(profile_digest(profile), profile_digest(reordered))
        reordered["source"]["sha256"] = "b" * 64
        self.assertNotEqual(profile_digest(profile), profile_digest(reordered))

    def test_validate_rejects_tampered_coefficients_clock_and_schema(self):
        profile = fit_profile(observations([{}, {"scale": 2}]))
        bad = copy.deepcopy(profile)
        bad["elements"][0]["channels"]["scale"]["segments"][0]["coefficients"][0][2][0] += .1
        with self.assertRaisesRegex(ValueError, "coefficients"):
            validate_profile(bad)
        bad = copy.deepcopy(profile)
        bad["source"]["time_base"] = "1/30000"
        with self.assertRaisesRegex(ValueError, "PTS clock"):
            validate_profile(bad)
        bad = copy.deepcopy(profile)
        bad["schema"] = "element-motion-curves/2"
        with self.assertRaises(ValueError):
            validate_profile(bad)

    def test_validate_rejects_nonfinite_serialized_data(self):
        profile = fit_profile(observations([{}, {}]))
        profile["elements"][0]["channels"]["scale"]["segments"][0]["coefficients"][0][0][0] = float("nan")
        with self.assertRaises(ValueError):
            validate_profile(profile)
        with self.assertRaises(ValueError):
            profile_digest(profile)

    def test_invalid_sample_numbers_order_scale_and_model_are_rejected(self):
        invalid = [
            {"pts": 0}, {"pts": -1}, {"pts": 3.5}, {"frame": 0}, {"frame": True},
            {"scale": 0}, {"scale": -1}, {"scale": float("inf")},
            {"angle_deg_unwrapped": float("nan")}, {"position_px": [0, float("nan")]},
            {"confidence": 1.1}, {"confidence": float("inf")}, {"segment": ""},
            {"visibility": "predicted"}, {"status": "inferred"}, {"cut_before": 1},
        ]
        for replacement in invalid:
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                fit_profile(observations([{}, replacement]))
        data = observations([{}])
        data["elements"][0]["model"] = "homography"
        with self.assertRaisesRegex(ValueError, "perspective"):
            fit_profile(data)

    def test_unknown_element_bad_time_and_method_fail_clearly(self):
        profile = fit_profile(observations([{}]))
        with self.assertRaisesRegex(ValueError, "Unknown motion element"):
            evaluate_element(profile, "absent", 0)
        for value in (float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evaluate_element(profile, "panel", value)
        with self.assertRaises(ValueError):
            fit_profile(observations([{}]), method="ease-out")
        with self.assertRaises(ValueError):
            fit_profile(observations([{}]), max_gap_frames=0)

    def test_fit_does_not_modify_observations_and_residuals_are_training_only(self):
        data = observations([{}, {"position_px": [360.1, 640.2], "scale": 1.2}])
        original = copy.deepcopy(data)
        profile = fit_profile(data)
        self.assertEqual(data, original)
        for channel in profile["elements"][0]["channels"].values():
            self.assertTrue(channel["residuals"]["training_only"])
            self.assertLess(channel["residuals"]["max"], 1e-10)


if __name__ == "__main__":
    unittest.main()
