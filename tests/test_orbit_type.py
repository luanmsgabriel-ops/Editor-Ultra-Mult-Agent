from dataclasses import replace
import math
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from visual_fidelity.orbit_type import OrbitSpec,project_ring,render_orbit_type,text_metrics,composite_orbit

FONT=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
pytestmark=pytest.mark.skipif(not FONT.exists(),reason='DejaVuSans required for raster smoke tests')

def spec():
    return OrbitSpec(size=(180,180),center=(90,90),radius_x=65,radius_z=45,
                     camera_distance=350,font_size=25,repeats=3,strip_width=6,thickness=2)

def test_depth_projection_has_front_back_and_larger_near_scale():
    s=spec();front=project_ring(0,10,s);back=project_ring(math.pi,10,s)
    assert front[2]>0>back[2]
    a=project_ring(0,-10,s);b=project_ring(math.pi,-10,s)
    assert np.linalg.norm(np.subtract(front[:2],a[:2]))>np.linalg.norm(np.subtract(back[:2],b[:2]))

def test_opaque_holdout_removes_rear_but_preserves_front():
    s=spec();rear,front=render_orbit_type('WIDE',FONT,s)
    blocked,retained=render_orbit_type('WIDE',FONT,s,Image.new('L',s.size,255))
    assert rear.getchannel('A').getbbox() is not None
    assert blocked.getchannel('A').getbbox() is None
    assert np.array_equal(np.asarray(front),np.asarray(retained))
    assert retained.getchannel('A').getbbox() is not None

def test_subject_composition_respects_both_depth_orders():
    size=(20,20);bg=Image.new('RGBA',size,'white');subject=Image.new('RGBA',size,(0,100,0,255))
    rear=Image.new('RGBA',size,(255,0,0,255));front=Image.new('RGBA',size)
    front.putpixel((10,10),(0,0,255,255))
    im=composite_orbit(bg,subject,rear,front)
    assert im.getpixel((0,0))==(0,100,0,255)
    assert im.getpixel((10,10))==(0,0,255,255)

def test_phase_wrap_is_continuous():
    s=spec();a=render_orbit_type('2 kun',FONT,s);b=render_orbit_type('2 kun',FONT,replace(s,phase=2*math.pi))
    for x,y in zip(a,b):assert np.abs(np.asarray(x,dtype=float)-np.asarray(y,dtype=float)).mean()<.05

def test_width_uses_glyph_metrics_and_kerning():
    poses,width=text_metrics('Wi',FONT,40)
    assert poses[0][2]>poses[1][2]*2
    assert poses[1][1]>0 and width>poses[0][2]

def test_invalid_camera_clearance_and_mismatched_holdout():
    with pytest.raises(ValueError):render_orbit_type('x',FONT,replace(spec(),camera_distance=50))
    with pytest.raises(ValueError):render_orbit_type('x',FONT,spec(),Image.new('L',(2,2)))

def test_opaque_cylinder_has_no_transparent_strip_seams(monkeypatch):
    import visual_fidelity.orbit_type as orbit
    monkeypatch.setattr(orbit,'_texture',lambda *args:(np.full((40,256),255,np.uint8),64))
    rear,front=render_orbit_type('x',FONT,replace(spec(),tilt_deg=0,pitch_deg=0,thickness=0))
    alpha=np.asarray(front.getchannel('A'))
    assert alpha[90,45:135].min()==255
