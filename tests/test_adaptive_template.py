from unittest import TestCase

import numpy as np

from visual_fidelity.adaptive_template import inspect_pose, place_screen, speech_cues
from visual_fidelity.context_art import draw_icon


class AdaptiveTemplateTests(TestCase):
    def test_quantities_are_taken_from_speech_and_generic_icons_are_rejected(self):
        speech = [{'start': 0, 'end': 3, 'text': 'Dos 42 voos programados, cinco foram cancelados.'}]
        cues = speech_cues(speech)
        self.assertEqual({c['title'] for c in cues}, {'42 VOOS PROGRAMADOS', '5 CANCELADOS'})
        self.assertNotIn('29 VOOS PROGRAMADOS', [c['title'] for c in cues])
        with self.assertRaisesRegex(ValueError, 'matching speech'):
            speech_cues(speech, [{'title': 'Presente', 'icon': 'clock', 'evidence': '42 voos programados'}])
        self.assertEqual(draw_icon('plane', (180, 0, 11), (255, 245, 230)).getchannel('A').getextrema(), (0, 255))

    def test_closeup_stays_on_original_plate_and_uses_free_space(self):
        primary = {'landmarks': {'nose':[.50,.52,0,.99],'left_eye':[.47,.49,0,.99],
                                 'right_eye':[.53,.49,0,.99],
                                 'left_shoulder':[.2,.68,0,.99], 'right_shoulder':[.8,.68,0,.99]}}
        pose = {'fps': 25, 'frames': {str(i): [primary] for i in range(25)},
                'hands': {'5': [{'side':'left','landmarks': {'hand_wrist':[.5,.16,0,1.]}}]}}
        protected, _, shots = inspect_pose(pose, 25, [0], 25)
        self.assertEqual(shots[0]['framing'], 'close_or_partial')
        self.assertEqual(shots[0]['subject'], 'original_plate')
        self.assertEqual(shots[0]['feet_visible_frames'], 0)
        self.assertEqual(shots[0]['hands_visible_frames'], 1)
        corners, _ = place_screen(0, 25, protected, (720,1280))
        self.assertEqual(set(corners),set(range(25))-{5})
        self.assertTrue(np.max(corners[0][:,1]) < .44)
