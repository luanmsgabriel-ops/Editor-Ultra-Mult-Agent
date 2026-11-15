import unittest
from PIL import Image
from visual_fidelity.motion_layers import Transform,compose_group,transform_layer

class MotionLayersTests(unittest.TestCase):
    def test_occlusion_does_not_destroy_underlying_asset(self):
        red=Image.new('RGBA',(20,20),'red');white=Image.new('RGBA',(10,10),'white');original=red.tobytes()
        result=compose_group((40,40),[(red,Transform(x=5,y=5)),(white,Transform(x=10,y=10))])
        self.assertEqual(result.getpixel((12,12)),(255,255,255,255));self.assertEqual(red.tobytes(),original)
        revealed=compose_group((40,40),[(red,Transform(x=5,y=5)),(white,Transform(x=26,y=26))])
        self.assertEqual(revealed.getpixel((12,12)),(255,0,0,255))
    def test_parent_moves_all_children_together(self):
        a=Image.new('RGBA',(4,4),'red');b=Image.new('RGBA',(4,4),'blue')
        result=compose_group((50,50),[(a,Transform(x=2,y=2)),(b,Transform(x=12,y=2))],Transform(x=5,y=7))
        self.assertEqual(result.getpixel((8,10)),(255,0,0,255));self.assertEqual(result.getpixel((18,10)),(0,0,255,255))
    def test_transparent_rgb_cannot_bleed_into_edge(self):
        im=Image.new('RGBA',(20,20),(0,255,0,0));im.paste((255,0,0,255),(5,5,15,15))
        out=transform_layer(im,Transform(angle=19,pivot=(10,10)))
        for r,g,b,a in out.getdata():
            if a>5:self.assertEqual(g,0)

if __name__=='__main__':unittest.main()
