import unittest
import numpy as np
from PIL import Image
from visual_fidelity.optical_lens import magnify
class LensTests(unittest.TestCase):
 def test_lens_enlarges_actual_content_and_preserves_outside(self):
  y,x=np.mgrid[:100,:100];rgb=np.zeros((100,100,3),np.uint8);rgb[:,:,0]=x*2
  base=Image.fromarray(rgb).convert('RGBA');layer=magnify(base,(50,50),20,2)
  self.assertEqual(layer.getpixel((0,0))[3],0)
  # At x60 the sample comes from x55, not x60. This tests actual magnification.
  self.assertLess(abs(layer.getpixel((60,50))[0]-110),3)
  self.assertEqual(layer.getpixel((50,50))[3],255)
 def test_invalid_optics_rejected(self):
  for radius,zoom in [(0,2),(10,.5),(float('nan'),2)]:
   with self.assertRaises(ValueError):magnify(Image.new('RGBA',(30,30)),(15,15),radius,zoom)
