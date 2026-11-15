import unittest
import numpy as np
from PIL import Image
from visual_fidelity.reference_replay import SourceClock, camera_plane_homography, warp_rgba, compose_bound_layers, decontaminate_matte_edge

class ReplayTests(unittest.TestCase):
 def test_spoken_cut_continuity(self):
  blue=SourceClock(679,722,112);close=SourceClock(722,799,155)
  self.assertEqual(blue.frame(708,240),141)
  self.assertEqual(blue.frame(721,240)+1,close.frame(722,240))
 def test_no_implicit_loop(self):
  with self.assertRaises(ValueError):SourceClock(0,100,230).frame(20,240)
  with self.assertRaises(ValueError):SourceClock(0,10,0).frame(10,240)
 def test_camera_plane_moves_with_physical_translation(self):
  h=camera_plane_homography(np.eye(3),(0,0,5),100,(50,50),(0,0,0),(1,0,0),(0,1,0))
  h2=camera_plane_homography(np.eye(3),(1,0,5),100,(50,50),(0,0,0),(1,0,0),(0,1,0))
  p=np.array([.5,.7,1]);a=h@p;b=h2@p;a/=a[2];b/=b[2]
  self.assertAlmostEqual(b[0]-a[0],20);self.assertAlmostEqual(b[1],a[1])
 def test_subpixel_warp_preserves_white_alpha_edge(self):
  a=np.zeros((10,10,4),np.uint8);a[3:7,3:7]=255
  H=np.eye(3);H[0,2]=.5
  b=np.asarray(warp_rgba(Image.fromarray(a),H,(10,10)))
  edge=(b[:,:,3]>0)&(b[:,:,3]<255)
  self.assertTrue(edge.any());self.assertTrue((b[:,:,:3][edge]>250).all())
 def test_required_role_cannot_disappear(self):
  with self.assertRaisesRegex(ValueError,'subject'):
   compose_bound_layers((4,4),['bg','subject'],{'bg':lambda _:Image.new('RGBA',(4,4))},0)
 def test_foreground_covers_complete_subject_non_destructively(self):
  subject=Image.new('RGBA',(4,4),'red');front=Image.new('RGBA',(4,4),(0,255,0,128))
  out=compose_bound_layers((4,4),['subject','front'],{'subject':lambda _:subject,'front':lambda _:front},0)
  self.assertEqual(subject.getpixel((0,0)),(255,0,0,255));self.assertEqual(out.getpixel((0,0)),(127,128,0,255))
 def test_matte_color_extension_keeps_alpha_and_solid_interior(self):
  a=np.zeros((16,16,4),np.uint8);a[2:14,2:14]=(220,215,200,100);a[4:12,4:12]=(70,30,20,255)
  b=np.asarray(decontaminate_matte_edge(Image.fromarray(a),2))
  self.assertTrue(np.array_equal(a[:,:,3],b[:,:,3]));self.assertTrue(np.array_equal(a[6:10,6:10],b[6:10,6:10]));self.assertEqual(b[3,3,0],70)
if __name__=='__main__':unittest.main()
