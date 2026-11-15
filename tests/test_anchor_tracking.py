from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from visual_fidelity.anchor_tracking import load_tapir_tracks, track_planar


class AnchorTrackingTest(unittest.TestCase):
    def test_opencv_planar_follows_perspective_and_stops_at_cut(self):
        width, height = 320, 200
        rng = np.random.default_rng(421)
        texture = np.full((height, width), 85, np.uint8)
        for x, y in rng.integers([62, 56], [240, 155], size=(80, 2)):
            cv2.circle(texture, (int(x), int(y)), 2, int(rng.integers(18, 222)), -1)
        quad = np.float32([[.15,.23],[.80,.23],[.80,.82],[.15,.82]])
        scale = [width, height]
        transforms = [np.array([[1,.0005*index,1.7*index], [0,1,1.3*index],
                                [index*1.e-5,0,1]]) for index in range(6)]
        frames = [cv2.warpPerspective(texture, h, (width,height), borderValue=85) for h in transforms]
        frames += [np.full_like(texture,245), texture]
        found = track_planar(frames,quad)
        for h, actual in zip(transforms,found):
            self.assertIsNotNone(actual)
            expected = cv2.perspectiveTransform((quad*scale)[None],h)[0]/scale
            np.testing.assert_allclose(actual,expected,atol=.009,rtol=0)
        self.assertEqual(found[6:], [None,None])

    def test_imported_points_ignore_occlusion_then_recover(self):
        width,height=240,160
        frames=[np.zeros((height,width),np.uint8)]*5
        quad=np.float32([[.25,.25],[.75,.25],[.75,.75],[.25,.75]])
        plane=np.float32([[.28,.28],[.67,.30],[.67,.68],[.30,.65],[.45,.45]])
        ext=np.float32([[.06,.10],[.92,.10],[.90,.9],[.09,.91]])
        pos=np.concatenate([plane,ext])
        shift=np.asarray([[0,0],[0,0],[.03,.01],[.045,.015],[.06,.02]])
        data=pos[:,None]+shift[None]
        data[5:]*=.86
        scores=np.full((1,len(pos),5),-7.,dtype='float32')
        scores[:,2:5,3]=7.
        with TemporaryDirectory() as directory:
            path=Path(directory)/'tapir.npz'
            np.savez(path,tracks=(data*np.array([120,80]))[None],occlusion=scores,
                     expected_dist=scores,image_size=[120,80])
            found=track_planar(frames,quad,start=1,tracks=path)
        self.assertIsNone(found[0])
        np.testing.assert_allclose(found[1],quad)
        np.testing.assert_allclose(found[2],quad+shift[2],atol=1e-6)
        self.assertIsNone(found[3])
        np.testing.assert_allclose(found[4],quad+shift[4],atol=1e-6)

    def test_validation_and_layout(self):
        with self.assertRaisesRegex(ValueError,'TL, TR, BR, BL'):
            track_planar([np.zeros((160,160),np.uint8)], [[.3,.3],[.3,.7],[.7,.7],[.7,.3]])
        field=np.zeros((3,5,2),'float32')
        positions,visible=load_tapir_tracks({'tracks':field, 'visibility':np.ones(field.shape[:2]),
            'layout':'TP','coordinates':'normalized'},(100,150),3)
        self.assertEqual(positions.shape,(5,3,2))
        self.assertEqual(visible.shape,(5,3))
        with self.assertRaisesRegex(ValueError,'NPZ tem 3 quadros'):
            load_tapir_tracks({'tracks':field, 'visibility':np.ones(field.shape[:2]),
                'layout':'TP','coordinates':'normalized'}, (100,150), 4)


if __name__=='__main__':
    unittest.main()
