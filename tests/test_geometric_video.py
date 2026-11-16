import unittest
import numpy as np
from visual_fidelity.geometric_video import viewport,place_foreground,fit_insert

class GeometricVideoTests(unittest.TestCase):
 def test_subject_and_matte_share_the_same_view(self):
  image=np.zeros((80,40,3),np.uint8);image[30:45,12:25]=255
  matte=image[:,:,0].copy()
  viewed=viewport(image,[.45,.5,1.6],40,80)
  alpha=viewport(matte,[.45,.5,1.6],40,80)
  np.testing.assert_array_equal(viewed[:,:,0],alpha)
 def test_transparent_color_does_not_leak_when_placing(self):
  rgb=np.full((12,10,3),[255,0,0],np.uint8);alpha=np.zeros((12,10),np.uint8)
  rgb[3:9,3:7]=[0,255,0];alpha[3:9,3:7]=255
  out=place_foreground(rgb,alpha,[.2,.2,.6,.6],60,72)
  visible=out[:,:,3]>0
  self.assertTrue(visible.any());self.assertEqual(int(out[:,:,0][visible].max()),0)
  self.assertTrue((out[:,:,3]==0).any())
 def test_portal_fit_is_bounded_and_empty_safe(self):
  image=np.full((80,40,3),[20,80,200],np.uint8);a=np.zeros((100,100),np.float32);a[20:30,40:70]=1
  out=fit_insert(image,[.5,.5,1],a)
  np.testing.assert_array_equal(out[25,50],[20,80,200]);self.assertEqual(int(out[a==0].max()),0)
  self.assertEqual(int(fit_insert(image,[.5,.5,1],a*0).max()),0)
 def test_viewport_preserves_aspect_and_rejects_invalid_zoom(self):
  im=np.zeros((80,40,3),np.uint8)
  self.assertEqual(viewport(im,[0,0,2],40,80).shape,im.shape)
  with self.assertRaises(ValueError):viewport(im,[.5,.5,.5],40,80)

if __name__=='__main__':unittest.main()
