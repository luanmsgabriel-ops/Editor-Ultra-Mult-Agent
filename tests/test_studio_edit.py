import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from visual_fidelity import studio_edit as se

class StudioEditTests(unittest.TestCase):
    def manifest(self):
        return {'version':se.VERSION,'fps':24,'frames':10,'shots':[{'id':'one','start':0,'end':10,'layers':[]}]}
    def editor(self,root,d=None):
        editor=se.Editor.__new__(se.Editor);editor.root=Path(root);editor.cache={};editor.d=d or self.manifest()
        return editor
    def test_source_clock_loop_is_explicit_and_reverse_bounded(self):
        self.assertEqual(se.source_frame({'source':{'start':8,'speed':1,'loop':True}},3,10),1)
        self.assertEqual(se.source_frame({'source':{'start':8,'speed':-2}},3,10),2)
        with self.assertRaises(ValueError):se.source_frame({'source':{'start':8}},3,10)
        with self.assertRaises(ValueError):se.source_frame({'source':{'loop':True}},1,0)
        with self.assertRaises(ValueError):se.source_frame({'source':{'speed':float('nan')}},1,10)
    def test_manifest_rejects_nonfinite_clocks_and_invalid_animation(self):
        d=self.manifest();self.assertTrue(se.validate_manifest(d))
        for field,value in [('fps',float('nan')),('frames',10.5),('frames',True)]:
            invalid=copy.deepcopy(d);invalid[field]=value
            with self.assertRaises(ValueError):se.validate_manifest(invalid)
        d['shots'][0].update(person={},source={'speed':1,'start':0})
        d['shots'][0]['person']={'keys':[{'u':.7,'x':0},{'u':.2,'x':1}]}
        with self.assertRaises(ValueError):se.validate_manifest(d)
    def test_quad_warp_keeps_straight_color_and_honors_opacity(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);im=np.zeros((8,8,4),np.uint8)
            im[:,:,:3]=[0,255,0] # Transparent poison color must not contaminate red edge.
            im[:,:4]=[255,0,0,255];Image.fromarray(im).save(root/'asset.png')
            (root/'quad.json').write_text(json.dumps([[[10.25,10.25],[34.25,10.25],[34.25,34.25],[10.25,34.25]]]))
            editor=self.editor(root)
            result=editor.layer({'kind':'image','path':'asset.png','quad_file':'quad.json','opacity':.5},.5,3)
            rgba=np.asarray(result);visible=rgba[:,:,3]>8
            self.assertGreater(visible.sum(),50)
            self.assertLessEqual(rgba[:,:,3].max(),128)
            self.assertGreater(rgba[visible,0].min(),245)
            self.assertLess(rgba[visible,1].max(),5)
    def test_cached_image_is_not_changed_by_layer_opacity(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'asset.png';Image.new('RGBA',(10,10),(200,40,20,255)).save(path)
            editor=self.editor(root);layer={'kind':'panel','path':'asset.png','opacity':.2}
            faded=editor.layer(layer,0,0);full=editor.layer({**layer,'opacity':1},0,0)
            self.assertEqual(faded.getpixel((5,5))[3],51)
            self.assertEqual(full.getpixel((5,5))[3],255)
            self.assertEqual(se.load(str(path)).getpixel((5,5))[3],255)
    def test_z_order_is_sorted_and_orbit_has_single_alpha_occlusion(self):
        d=self.manifest();s=d['shots'][0]
        s['layers']=[{'kind':'image','z':8,'color':'blue'},{'kind':'image','z':-1,'color':'red'},{'kind':'image','z':2,'color':'green'}]
        editor=self.editor('.',d);editor.layer=lambda l,u,local:Image.new('RGBA',se.SIZE,l['color'])
        self.assertEqual(editor.frame(2).getpixel((100,100)),(0,0,255))
        s.update(layers=[],person={'opacity':1},source={'start':0},orbit={'text':'x','font':'fake.ttf'})
        editor.subject=lambda *a:(Image.new('RGBA',se.SIZE,(255,0,0,128)),0)
        rear=Image.new('RGBA',se.SIZE,(0,0,255,255));front=Image.new('RGBA',se.SIZE)
        with patch.object(se,'render_orbit_type',return_value=(rear,front)) as render:
            color=editor.frame(2).getpixel((100,100))
            self.assertEqual(color,(128,0,127))
            self.assertNotIn('occluder_alpha',render.call_args.kwargs)
    def test_invalid_frame_and_render_ranges_fail_before_export(self):
        editor=self.editor('.')
        for frame in (-1,10):
            with self.assertRaises(ValueError):editor.frame(frame)
        for start,end in [(0,0),(-1,2),(9,3)]:
            with self.assertRaises(ValueError):editor.render('/tmp/not-created-studio-test.mp4',start,end)

if __name__=='__main__':unittest.main()
