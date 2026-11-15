import json
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from visual_fidelity.body_anchors import (candidate, detect_event, follow_quad, orbit_items,
                                          render_orbit, track_sidecar)
from visual_fidelity.video_anchor import prepare


def body(identifier=0, wrist_y=.5, shoulder_x=.5, gesture=None):
    return {
        'id':identifier,
        'landmarks':{
            'right_wrist':[shoulder_x+.25,wrist_y,0,.99],
            'left_shoulder':[shoulder_x-.13,.36,0,.99],
            'right_shoulder':[shoulder_x+.13,.36,0,.99],
            'left_hip':[shoulder_x-.12,.66,0,.99],
            'right_hip':[shoulder_x+.12,.66,0,.99],
            'nose':[shoulder_x,.19,0,.99],
        },
        'gestures':{'right':gesture} if gesture else {},
    }


class BodyAnchorsTest(unittest.TestCase):
    def test_identity_and_short_gap_inside_shot(self):
        data={'fps':30,'frames':{
            '0':[body(0)], '1':[body(0)], '2':[body(1)], '3':[body(0)],
            '5':[body(1)],'6':[body(1)],
        }}
        tracks,_=track_sidecar(data,0,7,[0,5],30,{'landmark':'right_wrist'})
        self.assertEqual(tracks[2].person_id,0)
        self.assertNotIn(4,tracks)
        self.assertEqual(tracks[5].person_id,1)

    def test_gesture_and_follow_or_freeze(self):
        data={'fps':30,'frames':{str(i):[body(wrist_y=.5-i*.003,
                                              gesture='Open_Palm' if i>=3 else None)] for i in range(8)}}
        spec={'landmark':'right_wrist','trigger':{'gesture':'Open_Palm','side':'right','min_frames':2}}
        tracked,events=track_sidecar(data,0,8,[0],30,spec)
        self.assertEqual(events,[3])
        self.assertLess(tracked[7].point[1],tracked[3].point[1])
        frozen,_=track_sidecar(data,0,8,[0],30,{**spec,'follow':False})
        np.testing.assert_allclose(frozen[7].point,frozen[3].point)

    def test_motion_trigger_and_frame_edge(self):
        items={i:candidate(body(wrist_y=.7-i*.025),'right_wrist',.5) for i in range(10)}
        self.assertEqual(detect_event(items,{'motion':'rise','min_speed':.4},30),4)
        corners=follow_quad(items[9],(720,1280),(.35,.08),{'relation':'right'})
        self.assertLess(float(corners.max()),1.)

    def test_orbit_in_editor_uses_pose_sidecar(self):
        with TemporaryDirectory() as working:
            root=Path(working)
            (root/'pose.json').write_text(json.dumps({'fps':30,'frames':{'0':[body()], '1':[body()]}}))
            frames=[np.zeros((90,60,3),'uint8')]*2
            planned=prepare({'text':'Gira','frames':[0,2],'anchor':{'mode':'orbit','pose':'pose.json'}},
                            frames,[0],30,(60,90),root,defaultdict(list))
            self.assertEqual(planned.report['tracked_frames'],2)
            self.assertEqual(planned.report['frames_with_occlusion_mask'],0)
            self.assertTrue(planned.report['review_required'])

    def test_occlusion_applies_only_to_back_of_orbit(self):
        shot=candidate(body(),'body_center',.5)
        spec={'phase':90,'turn_seconds':4,'ring':False}
        projected=orbit_items(shot,(128,180),spec,[0],[2],0)
        self.assertFalse(projected[0][0])
        self.assertTrue(orbit_items(shot,(128,180),spec,[0],[2],2)[0][0])
        glyph=np.full((32,48,4),255,'uint8')
        matte=np.full((180,128),255,'uint8')
        front=np.zeros((180,128,3),'uint8')
        render_orbit(front,shot,spec,([glyph],[0],[2]),0,(255,255,255),matte,1)
        self.assertTrue(front.any())
        behind=np.zeros_like(front)
        render_orbit(behind,shot,spec,([glyph],[0],[2]),2,(255,255,255),matte,1)
        self.assertFalse(behind.any())


if __name__=='__main__':
    unittest.main()
