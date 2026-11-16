from unittest import TestCase

import numpy as np
from PIL import Image

from visual_fidelity.editorial_motion import diagonal_wipe, kinetic_frame, treatment


class EditorialMotionTests(TestCase):
    def test_speech_function_selects_a_cutaway_or_tracked_lettering(self):
        self.assertEqual(treatment({'treatment':'alert','icon':'signal','title':'Falha'}), 'signal')
        self.assertEqual(treatment({'treatment':'metric','icon':'clock','title':'14 ATRASADOS'}), 'metric')
        self.assertEqual(treatment({'treatment':'metric','icon':'clock','title':'CERCA DE 4 HORAS'}), 'clock')
        self.assertEqual(treatment({'treatment':'headline','title':'Marca','gesture':{'frame':20}}), 'signature')
        self.assertEqual(treatment({'treatment':'headline','title':'Gancho'}), 'kinetic_type')

    def test_diagonal_wipe_returns_to_the_underlying_video(self):
        source = np.full((10,20,3), 49, dtype=np.uint8)
        cutaway = np.full_like(source, 172)
        for entering in (True, False):
            picture = source.copy()
            diagonal_wipe(picture, cutaway, 0, entering)
            np.testing.assert_array_equal(picture, source)
            diagonal_wipe(picture, cutaway, 1, entering)
            np.testing.assert_array_equal(picture, cutaway)

    def test_kinetic_type_changes_coverage_on_entry_and_exit(self):
        letters = Image.new('RGBA', (600,90),(180,12,30,255))
        beginning = kinetic_frame((letters,None), 0, 1.8)
        hold = kinetic_frame((letters,None), .7, 1.8)
        exit_frame = kinetic_frame((letters,None), 1.8, 1.8)
        self.assertLess(np.count_nonzero(beginning[:,:,3]), np.count_nonzero(hold[:,:,3]) / 2)
        self.assertEqual(np.count_nonzero(exit_frame[:,:,3]), 0)
