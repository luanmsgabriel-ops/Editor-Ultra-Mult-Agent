from unittest import TestCase

import numpy as np

from visual_fidelity.body_depth import hand_passes, hand_track, protect_front


class BodyDepthTests(TestCase):
    def test_rear_arc_is_occluded_while_front_arc_remains_visible(self):
        size=(260,460)
        opaque=np.full((460,260),255,np.uint8)
        clear=np.zeros_like(opaque)
        behind, front = hand_passes(size,(.5,.8,.12),opaque,.3)
        unoccluded, same_front = hand_passes(size,(.5,.8,.12),clear,.3)
        self.assertFalse(behind.any())
        self.assertTrue(unoccluded.any())
        self.assertTrue(front.any())
        np.testing.assert_array_equal(front,same_front)

    def test_front_type_respects_protected_area(self):
        coverage=np.full((100,100),255,np.uint8)
        protect_front(coverage,[[.25,.20,.75,.60]])
        self.assertFalse(coverage[20:60,25:75].any())
        self.assertEqual(coverage[80,50],255)

    def test_hand_tracking_ends_when_landmarks_disappear(self):
        face={'landmarks':dict.fromkeys(('nose','left_eye','right_eye'),[.7,.45,0,.9])}
        hand={'side':'right','landmarks':dict.fromkeys(('hand_wrist','middle_mcp','index_mcp'),[.15,.8,0,1.])}
        pose={'frames':{str(i):[face] for i in range(9)},
              'hands':{str(i):[hand] for i in [1,2,3,6,7]}}
        safe={i:[[.55,.32,.8,.54]] for i in range(9)}
        track=hand_track(pose,safe,'right',0,9)
        self.assertEqual(list(track),[1,2,3])
