import unittest
from fractions import Fraction

import numpy as np
from visual_fidelity.shot_boundaries import detect_shot_boundaries


def flat(level):
    return np.full((48, 72, 3), level, dtype=np.uint8)


class ShotTests(unittest.TestCase):
    def test_empty_and_single(self):
        self.assertEqual(detect_shot_boundaries([])["shot_starts"], [0])
        self.assertEqual(detect_shot_boundaries([flat(40)])["shot_starts"], [0])

    def test_clock_and_hard_cut(self):
        result = detect_shot_boundaries([flat(20)]*11+[flat(160)]*12, "24000/1001")
        self.assertEqual(result["shot_starts"], [0, 11])
        self.assertEqual(result["transitions"][0]["start_seconds"], float(Fraction(11*1001,24000)))

    def test_does_not_drop_authored_two_frame_cut(self):
        result = detect_shot_boundaries([flat(14)]*10+[flat(100)]*2+[flat(220)]*6)
        self.assertEqual(result["shot_starts"], [0, 10, 12])

    def test_flash_is_not_two_cuts(self):
        result = detect_shot_boundaries([flat(40)]*8+[flat(220)]*2+[flat(40)]*8)
        self.assertEqual(result["shot_starts"], [0])
        self.assertEqual([(x["kind"],x["start_frame"],x["end_frame_exclusive"]) for x in result["transitions"]], [("flash_candidate",8,10)])

    def test_fade_is_not_cut(self):
        result = detect_shot_boundaries([flat(70)]*6+[flat(i) for i in range(65,-1,-5)]+[flat(0)]*5)
        self.assertEqual(result["shot_starts"], [0])
        self.assertEqual(result["transitions"][0]["kind"], "fade_out_candidate")

    def test_translation_is_not_cut(self):
        a = np.random.default_rng(91).integers(0,256, (48,72,3), dtype=np.uint8)
        b = np.roll(a, 6, axis=1)
        result = detect_shot_boundaries([a]*9+[b]*8)
        self.assertEqual(result["shot_starts"],[0])
        self.assertEqual(result["rejected"], [{"frame": 9,"reason": "translation_match"}])

    def test_wrong_media_type_and_time_base(self):
        with self.assertRaises(ValueError):
            detect_shot_boundaries([flat(80)], 0)
        with self.assertRaises(ValueError):
            detect_shot_boundaries([flat(80).astype(float)])


if __name__ == "__main__":
    unittest.main()
