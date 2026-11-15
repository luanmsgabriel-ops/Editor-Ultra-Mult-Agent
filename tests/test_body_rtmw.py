import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from visual_fidelity.body_rtmw import import_predictions, normalize_people


def person():
    points = np.full((133, 2), [40., 30.])
    points[5:7] = [[22, 24], [42, 24]]
    points[11:13] = [[25, 56], [44, 56]]
    points[91] = [28., 48.]
    points[99] = [31., 41.]
    scores = np.full(133, .8)
    scores[99] = .92
    return {'keypoints': points.tolist(), 'keypoint_scores': scores.tolist()}


class BodyRTMWTest(unittest.TestCase):
    def test_wholebody_schema_keeps_feet_face_hands_and_virtual_palm(self):
        pose = person()
        pose['keypoint_scores'][21] = .01
        result = normalize_people([pose], 80, 100)[0]
        landmarks = result['landmarks']
        self.assertEqual(landmarks['left_wrist'], [.5, .3, 0., .8])
        self.assertEqual(landmarks['left_hand_wrist'], [.35, .48, 0., .8])
        self.assertEqual(landmarks['left_index_tip'], [.3875, .41, 0., .92])
        self.assertEqual(landmarks['left_foot_index'], landmarks['left_big_toe'])
        self.assertIn('face_67', landmarks)
        self.assertIn('right_pinky_tip', landmarks)
        self.assertLessEqual(landmarks['left_palm'][-1], .8)
        self.assertNotIn('right_small_toe', landmarks)

    def test_preserves_video_index_and_empty_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'poses.json'
            path.write_text(json.dumps({'instance_info': [
                {'frame_id': 1, 'instances': [person()]},
                {'frame_id': 2, 'instances': []},
                {'frame_id': 3, 'instances': [person()]},
            ]}), encoding='utf-8')
            result = import_predictions(path, 80, 100, 30, 1, .05)
        self.assertEqual(result['resolution'], [80, 100])
        self.assertEqual(list(result['frames']), ['0', '1', '2'])
        self.assertEqual(result['frames']['1'], [])
        self.assertEqual(result['frames']['0'][0]['id'], result['frames']['2'][0]['id'])

    def test_rejects_body_only_pose(self):
        pose = person()
        pose['keypoints'] = pose['keypoints'][:17]
        with self.assertRaisesRegex(ValueError, 'WholeBody 133'):
            normalize_people([pose], 80, 100)


if __name__ == '__main__':
    unittest.main()
