import unittest
from unittest.mock import patch

import numpy as np

from visual_fidelity.auto_placement import choose_anchor


class AutoPlacementTest(unittest.TestCase):
    def setUp(self):
        detector = patch('visual_fidelity.auto_placement._detector', return_value=None)
        detector.start()
        self.addCleanup(detector.stop)
        self.frame = np.full((120, 208, 3), 24, dtype=np.uint8)

    def test_choose_a_different_anchor_for_a_different_subject(self):
        a = choose_anchor([self.frame], (.3, .16), protected=[(0, 0, .61, 1)])
        b = choose_anchor([self.frame], (.3, .16), protected=[(.39, 0, 1, 1)])
        self.assertGreaterEqual(a['bounds'][0], .61)
        self.assertLessEqual(b['bounds'][2], .39)
        self.assertEqual(a['protected_overlap'], 0)
        self.assertEqual(b['protected_overlap'], 0)

    def test_protection_covers_subject_movement_and_reports_no_open_area(self):
        moving = [[(0, 0, .58, 1)], [(.42, 0, 1, 1)]]
        result = choose_anchor([self.frame, self.frame], (.24, .13), protected=moving)
        self.assertTrue(result['review_required'])
        self.assertEqual(result['protected_overlap'], 1)

    def test_choose_ink_using_the_scene_and_prefer_the_previous_anchor(self):
        bright = np.full_like(self.frame, 232)
        dark = choose_anchor([self.frame], (.2, .1))
        light = choose_anchor([bright], (.2, .1), previous=(.24, .24))
        self.assertGreater(dark['color'][0], 230)
        self.assertLess(light['color'][0], 30)
        np.testing.assert_allclose(light['center'], [.24, .24])
        self.assertGreaterEqual(light['contrast'], 4.5)

    def test_prefer_negative_space_to_a_high_motion_textured_area(self):
        step_y, step_x = np.indices(self.frame.shape[:2])
        checkers = (((step_y//3+step_x//3)%2)*242).astype(np.uint8)
        frames = [self.frame.copy(), self.frame.copy()]
        for frame, pattern in zip(frames, (checkers, 242-checkers)):
            frame[:, :133] = pattern[:, :133, None]
        result = choose_anchor(frames, (.25, .12))
        self.assertGreater(result['bounds'][0], .62)

    def test_thin_protected_mask_survives_analysis_downsampling(self):
        frame = np.zeros((640, 640, 3), 'uint8')
        # One bright mask pixel occupies a partial downsampled pixel. The
        # caption filling the canvas still needs a review signal.
        mask = np.zeros(frame.shape[:2], 'uint8')
        mask[201, 401] = 255
        result = choose_anchor([frame], (1, 1), protected=mask)
        self.assertTrue(result['review_required'])

    def test_validate_bounds(self):
        with self.assertRaisesRegex(ValueError, 'Protected'):
            choose_anchor([self.frame], (.2, .12), protected=[(-1, 0, .5, 1)])


if __name__ == '__main__':
    unittest.main()
