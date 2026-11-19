import unittest
from unittest.mock import patch
import numpy as np
import cv2
from visual_fidelity.shot_boundaries import detect_shot_boundaries, _same_content_transform

class TransformTests(unittest.TestCase):
 def test_bounded_scale_blur_is_uncertain_not_semantic_proof(self):
  rng=np.random.default_rng(41)
  a=cv2.GaussianBlur(rng.integers(0,256,(48,72,3),dtype=np.uint8),(5,5),0)
  a=cv2.normalize(a,None,0,255,cv2.NORM_MINMAX)
  m=cv2.getRotationMatrix2D((36,24),2,1.09)
  b=cv2.warpAffine(a,m,(72,48),borderMode=cv2.BORDER_REFLECT)
  result=_same_content_transform(a,b,.1)
  self.assertIsNotNone(result)
 def test_unrelated_color_rejected(self):
  rng=np.random.default_rng(4);a=rng.integers(0,256,(48,72,3),dtype=np.uint8)
  self.assertIsNone(_same_content_transform(a,a,.4))
 def test_ecc_failure_closed(self):
  a=np.random.default_rng(7).integers(0,256,(48,72,3),dtype=np.uint8)
  with patch('visual_fidelity.shot_boundaries.cv2.findTransformECC',side_effect=cv2.error('no convergence')):
   self.assertIsNone(_same_content_transform(a,a,.1))
 def test_uncertain_keeps_tracking_barrier(self):
  a=np.random.default_rng(5).integers(0,256,(48,72,3),dtype=np.uint8)
  b=np.random.default_rng(6).integers(0,256,(48,72,3),dtype=np.uint8)
  with patch('visual_fidelity.shot_boundaries._same_content_transform',return_value={'ecc':.9}):
   r=detect_shot_boundaries([a]*4+[b]*4)
  self.assertEqual(r['shot_starts'],[0]);self.assertEqual(r['uncertain_boundaries'],[4]);self.assertEqual(r['tracking_breaks'],[0,4])
