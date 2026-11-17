"""Timing claims stay bounded by observed support and sampled peak ambiguity."""

import copy
import unittest

from visual_fidelity.motion_peaks import classify_peak, compare_peaks


def series(values, times=None):
    return [{"time_s": time, "value": value}
            for time, value in zip(range(len(values)) if times is None else times, values)]


class MotionPeakTests(unittest.TestCase):
    def test_unique_interior_peaks_have_signed_sampled_lag(self):
        reference = series([0, 1, 4, 1, 0, 0])
        candidate = series([0, 0, 1, 4, 1, 0])
        report = compare_peaks(reference, candidate)
        self.assertEqual(report["status"], "unique_peaks")
        self.assertEqual(report["peak_time_error_s"], 1)
        self.assertEqual(report["absolute_peak_time_error_s"], 1)
        self.assertEqual(report["reference"]["peak_time_bracket_s"], [1, 3])
        self.assertEqual(compare_peaks(candidate, reference)["peak_time_error_s"], -1)

    def test_plateaus_have_windows_without_argmax_time(self):
        reference = series([0, 2, 2, 2, 0, 0])
        candidate = series([0, 0, 2, 2, 2, 0])
        peak = classify_peak(reference)
        self.assertEqual(peak["classification"], "plateau")
        self.assertIsNone(peak["peak_time_s"])
        self.assertEqual(peak["peak_intervals_s"], [[1, 3]])
        report = compare_peaks(reference, candidate)
        self.assertEqual(report["status"], "peak_intervals")
        self.assertIsNone(report["peak_time_error_s"])
        self.assertEqual(report["minimum_interval_separation_s"], 0)
        self.assertEqual(report["possible_peak_time_error_interval_s"], [-1, 3])

    def test_nonoverlapping_plateau_windows_report_only_minimum_separation(self):
        reference = series([0, 2, 2, 0, 0, 0, 0, 0])
        candidate = series([0, 0, 0, 0, 0, 2, 2, 0])
        report = compare_peaks(reference, candidate)
        self.assertEqual(report["minimum_interval_separation_s"], 3)
        self.assertEqual(report["possible_peak_time_error_interval_s"], [3, 5])
        self.assertIsNone(report["peak_time_error_s"])

    def test_unique_peak_against_plateau_remains_interval_comparison(self):
        report = compare_peaks(series([0, 2, 0, 0, 0]), series([0, 0, 2, 2, 0]))
        self.assertEqual(report["status"], "peak_intervals")
        self.assertEqual(report["minimum_interval_separation_s"], 1)
        self.assertIsNone(report["peak_time_error_s"])

    def test_near_maximum_tolerance_does_not_invent_a_unique_peak(self):
        data = series([0, .995, 1, .994, 0])
        self.assertEqual(classify_peak(data)["classification"], "plateau")
        exact = classify_peak(data, relative_tolerance=0, absolute_tolerance=0)
        self.assertEqual(exact["classification"], "unique_interior")
        self.assertEqual(exact["peak_time_s"], 2)

    def test_maximum_at_series_edge_is_not_a_complete_peak(self):
        for values in ([4, 2, 0], [0, 2, 4], [4], [4, 4, 4]):
            with self.subTest(values=values):
                peak = classify_peak(series(values))
                self.assertEqual(peak["classification"], "boundary")
                self.assertIsNone(peak["peak_time_s"])
                self.assertTrue(peak["candidates"][0]["boundary_reasons"])
                report = compare_peaks(series(values), series([0, 4, 0]))
                self.assertIsNone(report["peak_time_error_s"])
                self.assertIsNone(report["minimum_interval_separation_s"])

    def test_disjoint_equal_peaks_are_ambiguous(self):
        data = series([0, 4, 0, 4, 0])
        peak = classify_peak(data)
        self.assertEqual(peak["classification"], "ambiguous")
        self.assertEqual(peak["peak_intervals_s"], [[1, 1], [3, 3]])
        self.assertIsNone(peak["peak_time_s"])
        report = compare_peaks(data, series([0, 4, 0, 0, 0]))
        self.assertEqual(report["status"], "ambiguous")
        self.assertIsNone(report["peak_time_error_s"])

    def test_explicit_gap_is_not_interpolated_or_part_of_plateau(self):
        for data, reason in ((series([0, None, 4, 0]), "gap_before"),
                             (series([0, 4, None, 0]), "gap_after")):
            with self.subTest(reason=reason):
                peak = classify_peak(data)
                self.assertEqual(peak["classification"], "boundary")
                self.assertIn(reason, peak["candidates"][0]["boundary_reasons"])
                self.assertEqual(peak["support"]["missing_sample_count"], 1)
        split = classify_peak(series([0, 4, None, 4, 0]))
        self.assertEqual(split["classification"], "ambiguous")
        self.assertEqual(split["peak_intervals_s"], [[1, 1], [3, 3]])

    def test_irregular_spacing_is_accepted_without_creating_evidence(self):
        data = series([0, 4, 0], [0, .13, 10])
        before = copy.deepcopy(data)
        peak = classify_peak(data)
        self.assertEqual(peak["classification"], "unique_interior")
        self.assertEqual(peak["peak_time_s"], .13)
        self.assertEqual(peak["peak_time_bracket_s"], [0, 10])
        self.assertEqual(data, before)

    def test_zero_and_below_absolute_tolerance_have_no_motion_peak(self):
        for values in ([0, 0, 0], [0, 1e-10, 0], [0, None, 0]):
            with self.subTest(values=values):
                peak = classify_peak(series(values))
                self.assertEqual(peak["classification"], "no_motion")
                self.assertIsNone(peak["peak_time_s"])
                self.assertEqual(peak["peak_intervals_s"], [])
        mismatch = compare_peaks(series([0, 0, 0]), series([0, 1, 0]))
        self.assertTrue(mismatch["motion_mismatch"])
        self.assertIsNone(mismatch["peak_time_error_s"])
        equal = compare_peaks(series([0, 0, 0]), series([0, 0, 0]))
        self.assertFalse(equal["motion_mismatch"])

    def test_empty_and_all_missing_inputs_are_unavailable(self):
        for data in ([], series([None, None])):
            with self.subTest(data=data):
                peak = classify_peak(data)
                self.assertEqual(peak["classification"], "unavailable")
                self.assertIsNone(peak["maximum_value"])
                self.assertIsNone(compare_peaks(data, series([0, 1, 0]))["peak_time_error_s"])

    def test_sample_validation_rejects_invalid_numbers_order_and_shape(self):
        invalid = [None, {}, [1], [{"time_s": 0}], [{"value": 1}],
                   series([0, -1, 0]), series([0, float("nan"), 0]),
                   series([0, float("inf"), 0]), series([0, True, 0]),
                   series([0, 1], [0, 0]), series([0, 1], [1, 0]),
                   series([0, 1], [0, float("inf")]), series([0, 1], [0, True])]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                classify_peak(data)

    def test_tolerance_validation_rejects_invalid_values(self):
        for kwargs in ({"relative_tolerance": -1}, {"relative_tolerance": 1},
                       {"relative_tolerance": float("nan")}, {"relative_tolerance": True},
                       {"absolute_tolerance": -1}, {"absolute_tolerance": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                classify_peak(series([0, 1, 0]), **kwargs)


if __name__ == "__main__":
    unittest.main()
