import unittest
import cv2
import numpy as np
from visual_fidelity.studio_matte import StudioMatte,polygon_trimap,alpha_bounds,fill_small_holes

class StudioMatteTests(unittest.TestCase):
    def scene(self,dx=0):
        im=np.full((160,120,3),205,np.uint8)
        cv2.rectangle(im,(30+dx,25),(85+dx,130),(40,65,90),-1)
        # White foreground prop very similar to backdrop, explicit seed needed.
        cv2.rectangle(im,(43+dx,110),(69+dx,145),(230,230,230),-1)
        return im
    def trimap(self):
        m=np.zeros((160,120),np.uint8);m[15:150,20:100]=2
        m[25:131,30:86]=3;m[35:120,40:75]=1
        m[110:146,43:70]=3;m[115:140,48:65]=1
        return m
    def test_source_preserved_and_white_prop_kept(self):
        im=self.scene();original=im.copy();m=StudioMatte(initial_iterations=3).process(im,self.trimap())
        self.assertTrue(np.array_equal(im,original))
        self.assertGreater(m[130,55],250);self.assertEqual(m[155,55],0)
        self.assertEqual(m[90,15],0)
        self.assertIsNotNone(alpha_bounds(m))
    def test_temporal_tracks_translation_without_stale_silhouette(self):
        engine=StudioMatte(initial_iterations=3,uncertainty_px=8)
        engine.process(self.scene(),self.trimap())
        alpha=engine.process(self.scene(5))
        self.assertGreater(alpha[60,88],240)
        self.assertLess(alpha[60,31],10)
        self.assertGreater(alpha[135,60],240)
    def test_seed_required_and_raster_changes_rejected(self):
        engine=StudioMatte()
        with self.assertRaises(ValueError):engine.process(self.scene())
        engine.process(self.scene(),self.trimap())
        with self.assertRaises(ValueError):engine.process(np.zeros((40,40,3),np.uint8))
    def test_small_interior_holes_filled_but_floor_gap_stays(self):
        mask=np.zeros((100,100),np.uint8);mask[20:80,20:80]=255
        mask[40:45,40:45]=0;mask[60:81,55:65]=0
        fixed=fill_small_holes(mask,30)
        self.assertEqual(fixed[42,42],255)
        self.assertEqual(fixed[70,60],0)
        self.assertEqual(fixed[0,0],0)
    def test_normalized_seed_configuration(self):
        m=polygon_trimap((100,200),[{'label':1,'points':[[.2,.2],[.8,.2],[.8,.8],[.2,.8]]}])
        self.assertEqual(m[50,100],1);self.assertEqual(m[0,0],0)
        with self.assertRaises(ValueError):polygon_trimap((100,200),[{'label':1,'points':[[2,0],[0,0],[1,1]]}])
if __name__=='__main__':unittest.main()
