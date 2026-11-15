import unittest
import numpy as np
from PIL import Image,ImageDraw
from visual_fidelity.light_sweep import Sweep,light_sweep

class LightSweepTests(unittest.TestCase):
    def asset(self):
        im=Image.new('RGBA',(160,100));d=ImageDraw.Draw(im)
        d.rectangle((10,10,149,89),fill=(180,0,12,255));d.ellipse((65,25,95,75),fill=(0,0,0,0));return im
    def test_alpha_and_counter_never_filled(self):
        im=self.asset();out=light_sweep(im,.5)
        np.testing.assert_array_equal(np.array(im)[:,:,3],np.array(out)[:,:,3])
        self.assertEqual(out.getpixel((80,50))[3],0)
    def test_light_moves_across_surface(self):
        im=self.asset();base=np.array(im)[:,:,0].astype(float)
        centers=[]
        for phase in [.25,.75]:
            delta=np.maximum(0,np.array(light_sweep(im,phase,Sweep(angle=0)))[:,:,0]-base)
            centers.append((delta*np.arange(im.width)[None,:]).sum()/delta.sum())
        self.assertGreater(centers[1]-centers[0],60)
    def test_mask_excludes_other_lettering(self):
        im=self.asset();m=Image.new('L',im.size);ImageDraw.Draw(m).rectangle((0,0,79,99),fill=255)
        a=np.array(light_sweep(im,.5,surface_mask=m));b=np.array(im)
        np.testing.assert_array_equal(a[:,80:],b[:,80:])
    def test_blank_zero_and_outside_are_identity(self):
        for im in [self.asset(),Image.new('RGBA',(20,20))]:
            for phase,cfg in [(-1,Sweep()),(.5,Sweep(intensity=0)),(2,Sweep())]:
                self.assertEqual(im.tobytes(),light_sweep(im,phase,cfg).tobytes())
    def test_bad_parameters_rejected(self):
        for cfg in [Sweep(width=0),Sweep(intensity=2),Sweep(angle=float('nan'))]:
            with self.assertRaises(ValueError):light_sweep(self.asset(),.5,cfg)

if __name__=='__main__':unittest.main()
