import copy,unittest
import numpy as np
from visual_fidelity.geometric_replay import mask,compose,evaluate,frame_schedule

class GeometricReplayTests(unittest.TestCase):
    def test_replacement_endpoints_and_foreground_full_occlusion(self):
        base=np.zeros((9,13,3),np.uint8);base[:]=[0,40,220]
        insert=np.zeros_like(base);insert[:]=[240,20,0]
        self.assertTrue(np.array_equal(compose(base,insert,np.zeros((9,13))),base))
        self.assertTrue(np.array_equal(compose(base,insert,np.ones((9,13))),insert))
        front=np.zeros((9,13,4),np.uint8);front[:]=[20,200,40,255]
        self.assertTrue(np.array_equal(compose(base,insert,np.ones((9,13)),front),front[:,:,:3]))
    def test_partial_alpha_composites_without_transparent_rgb_leak(self):
        base=np.array([[[0.,0.,1.,1.]]],np.float32)
        insert=np.array([[[1.,0.,0.,.5]]],np.float32)
        out=compose(base,insert,np.array([[.5]],np.float32))
        np.testing.assert_allclose(out,[[[.25,0,.75,1]]],atol=1e-6)
        insert[0,0]=[0,1,0,0]
        np.testing.assert_allclose(compose(base,insert,np.ones((1,1))),base)
        transparent=np.array([[[1.,0.,0.,0.]]],np.float32)
        np.testing.assert_allclose(compose(transparent,insert,np.ones((1,1))),np.zeros((1,1,4)))
    def test_strip_orientation_thickness_is_pixel_space_across_aspect_ratios(self):
        for width,height in [(200,100),(100,200)]:
            horizontal=mask({'kind':'strip','angle':0,'width':.1},width,height)
            vertical=mask({'kind':'strip','angle':90,'width':.1},width,height)
            self.assertAlmostEqual(float(horizontal[:,width//2].sum()),height*.1,places=4)
            self.assertAlmostEqual(float(vertical[height//2,:].sum()),height*.1,places=4)
            self.assertEqual(horizontal.dtype,np.float32)
        zero=mask({'kind':'strip','width':0},30,20);self.assertFalse(zero.any())
    def test_polygon_ellipse_and_x_geometry(self):
        polygon=mask({'kind':'polygon','points':[[.2,.2],[.8,.2],[.8,.8],[.2,.8]]},100,200)
        self.assertEqual(polygon[100,50],1);self.assertEqual(polygon[10,50],0)
        ellipse=mask({'kind':'ellipse','center':[.5,.5],'radii':[.2,.1]},200,100)
        self.assertEqual(ellipse[50,100],1);self.assertEqual(ellipse[70,100],0)
        rotated=mask({'kind':'ellipse','center':[.5,.5],'radii':[.2,.1],'angle':90},200,100)
        self.assertEqual(rotated[70,100],1)
        x=mask({'kind':'x','width':.1},100,100)
        expected=np.maximum(mask({'kind':'strip','angle':45,'width':.1},100,100),mask({'kind':'strip','angle':-45,'width':.1},100,100))
        np.testing.assert_array_equal(x,expected)
        self.assertTrue(((x>0)&(x<1)).any())
    def test_linear_gradient_endpoints_invert_and_composition(self):
        spec={'kind':'linear_gradient','axis':'x','start':.25,'end':.75}
        # Five-pixel centers are .1,.3,.5,.7,.9: midpoint must blend equally.
        alpha=mask(spec,5,3)
        self.assertEqual(float(alpha[1,0]),1)
        self.assertEqual(float(alpha[1,4]),0)
        self.assertAlmostEqual(float(alpha[1,2]),.5)
        reverse=mask({**spec,'invert':True},5,3)
        np.testing.assert_allclose(alpha+reverse,1)
        base=np.zeros((3,5,3),np.float32);base[:,:,2]=1
        insert=np.zeros_like(base);insert[:,:,0]=1
        out=compose(base,insert,alpha)
        np.testing.assert_allclose(out[1,0],[1,0,0])
        np.testing.assert_allclose(out[1,4],[0,0,1])
        np.testing.assert_allclose(out[1,2],[.5,0,.5])
        vertical=mask({**spec,'axis':'y'},3,5)
        np.testing.assert_allclose(vertical,alpha.T)
        with self.assertRaises(ValueError):mask({**spec,'start':.75,'end':.25},5,3)
    def test_band_arrays_and_boolean_masks(self):
        a={'kind':'bands','axis':'x','intervals':[[.1,.2],[.7,.9]]}
        b={'kind':'bands','axis':'y','intervals':[[.4,.6]]}
        union=mask({'kind':'union','shapes':[a,b]},100,100)
        self.assertEqual(union[50,50],1);self.assertEqual(union[20,15],1);self.assertEqual(union[20,50],0)
        subtraction=mask({'kind':'subtract','shapes':[a,copy.deepcopy(a)]},100,100)
        self.assertFalse(subtraction.any())
    def test_keyframe_endpoints_midpoint_hold_and_no_input_mutation(self):
        spec={'kind':'strip','angle':0,'width':.1,'center':[.5,.5],
              'keyframes':[{'frame':3,'width':0},{'frame':7,'width':.4},{'frame':11,'center':[.6,.5]}]}
        original=copy.deepcopy(spec)
        self.assertEqual(evaluate(spec,0)['width'],0)
        self.assertAlmostEqual(evaluate(spec,5)['width'],.2)
        self.assertEqual(evaluate(spec,8)['width'],.4)
        self.assertEqual(evaluate(spec,20)['center'],[.6,.5])
        self.assertFalse(mask(spec,40,20,frame=3).any())
        self.assertTrue(mask(spec,40,20,frame=7).any())
        self.assertEqual(spec,original)
    def test_nested_animation_keeps_integer_child_frame_keys(self):
        spec={'kind':'union','opacity':1,'shapes':[{'kind':'strip','width':0,'keyframes':[{'frame':0,'width':0},{'frame':10,'width':.4}]}], 'keyframes':[{'frame':0,'opacity':0},{'frame':10,'opacity':1}]}
        value=mask(spec,100,100,frame=5)
        self.assertAlmostEqual(float(value[50,50]),.5)
        self.assertEqual(float(value[0,50]),0)
    def test_rational_frame_schedule_no_accumulation(self):
        times=frame_schedule('24000/1001',24001)
        self.assertEqual(times[0],0);self.assertEqual(times[-1],1001.)
        np.testing.assert_array_equal(frame_schedule(24,3,start_frame=24),[1,25/24,26/24])
        for fps,frames in [(0,24),(float('nan'),24),(24,0),(True,24)]:
            with self.assertRaises(ValueError):frame_schedule(fps,frames)
    def test_invalid_shapes_arrays_clocks_rejected(self):
        for spec in [{'kind':'strip','width':-1},{'kind':'strip','width':float('nan')},
                     {'kind':'ellipse','radii':[-1,.1]},{'kind':'polygon','points':[[0,0],[1,1]]},
                     {'kind':'bands','axis':'y','intervals':[[.7,.2]]}]:
            with self.assertRaises(ValueError):mask(spec,20,30)
        with self.assertRaises(ValueError):evaluate({'keyframes':[{'frame':2},{'frame':1}]},0)
        with self.assertRaises(ValueError):compose(np.zeros((2,2,3),np.uint8),np.zeros((3,3,3),np.uint8),np.ones((2,2)))
        with self.assertRaises(ValueError):compose(np.zeros((2,2,3),np.uint8),np.zeros((2,2,3),np.uint8),np.full((2,2),255))

if __name__=='__main__':unittest.main()
