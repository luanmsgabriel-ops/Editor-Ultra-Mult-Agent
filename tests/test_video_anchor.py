from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from visual_fidelity.anchor_camera import parse_colmap, project
from visual_fidelity.anchor_graphics import composite, resample_glyphs
from visual_fidelity.video_anchor import from_transcript, poses_at, prepare, shot_starts


class VideoAnchorTest(unittest.TestCase):
    def test_perspective_import_uses_explicit_frame_keys(self):
        with TemporaryDirectory() as directory:
            model=Path(directory)
            (model/'cameras.txt').write_text('1 PINHOLE 100 100 100 100 50 50\n')
            (model/'images.txt').write_text('1 1 0 0 0 0 0 10 1 shot 001.png\n\n')
            camera=parse_colmap(model,{'shot 001.png':14})['14']
            points=[[-2,-1,0],[2,-1,0],[2,1,0],[-2,1,0]]
            np.testing.assert_allclose(project(points,camera),
                                       [[.3,.4],[.7,.4],[.7,.6],[.3,.6]])
            self.assertIsNone(project(np.array(points)-[0,0,13],camera))

    def test_screen_placement_skips_fully_protected_plan(self):
        frames=[np.zeros((48,96,3),'uint8') for _ in range(4)]
        effect={'text':'teste','frames':[0,4],'protected':[[0,0,1,1]]}
        result=prepare(effect,frames,[0],30,(96,48),Path('.'),defaultdict(list))
        self.assertFalse(result.report['shots'][0]['rendered'])
        self.assertEqual(result.report['missing_frames'],4)

    def test_existing_type_does_not_duplicate(self):
        frames=[np.zeros((48,96,3),'uint8') for _ in range(4)]
        effect={'text':'Evolução','frames':[0,4]}
        found={'lines':['EVOLUCAO ATUAL'],'boxes':[[.12,.4,.4,.8]]}
        result=prepare(effect,frames,[0],30,(96,48),Path('.'),defaultdict(list),
                       ocr=lambda _:found)
        self.assertEqual(result.report['shots'][0]['reason'],'existing_text')
        self.assertEqual(result.report['tracked_frames'],0)

    def test_new_caption_resamples_progress_and_mentions_new_characters(self):
        original=[[.1,.5,.1,.2,-10],[.9,.5,.1,.2,10]]
        middle=poses_at({'0':original,'10':np.array(original)+.02},5,11)
        sampled=resample_glyphs(middle,3)
        np.testing.assert_allclose(sampled[:,0],[.11,.51,.91])
        segments=from_transcript({'segments':[{'start':.2,'end':1.2,'text':'  Texto  novo '}]})
        self.assertEqual(segments[0]['text'],'Texto novo')

    def test_mask_and_cut_prediction(self):
        background=np.zeros((32,32,3),'uint8')
        image=np.full((12,12,4),255,'uint8')
        quad=np.float32([[.25,.25],[.75,.25],[.75,.75],[.25,.75]])
        paint=background.copy()
        occlusion=np.zeros((32,32),'uint8')
        occlusion[:,:16]=255
        composite(paint,image,quad,occlusion=occlusion)
        self.assertFalse(paint[:,:16].any())
        self.assertTrue(paint[:,16:].any())
        self.assertEqual(shot_starts([background,background,np.full_like(background,217)]),[0,2])


if __name__=='__main__':
    unittest.main()
