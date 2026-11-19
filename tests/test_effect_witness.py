import numpy as np
import pytest
from editorial_engine.effect_witness import contrast_witness, refraction_motion_witness

def test_local_emitter_side_and_no_invented_presence():
    b=np.zeros((100,200,3),np.uint8)
    a=b.copy()
    assert contrast_witness(a,b,(20,10,180,90),axis_x=100)['side_of_axis'] is None
    a[40:50,140:150]=[50,70,230]
    q=contrast_witness(a,b,(20,10,180,90),axis_x=100)
    assert q['inside_changed_pixels']==100 and q['outside_changed_pixels']==0 and q['side_of_axis']=='right'

def test_unrelated_changes_are_not_discarded():
    b=np.zeros((100,200,3),np.uint8); a=b.copy(); a[5:9,4:8]=255
    q=contrast_witness(a,b,(20,10,180,90),axis_x=100)
    assert q['inside_changed_pixels']==0 and q['outside_changed_pixels']==16

def test_texture_required_for_optical_witness():
    a=np.zeros((100,200,3),np.uint8)
    assert refraction_motion_witness(a,a,(20,10,180,90))['status']=='insufficient_texture'
    b=np.random.default_rng(123).integers(0,255,(100,200,3),dtype=np.uint8)
    c=np.roll(b,2,axis=1)
    q=refraction_motion_witness(c,b,(30,15,175,85))
    assert q['accepted_tracks']>=4 and q['median_displacement_px']==pytest.approx(2,abs=.3)

def test_bad_regions_fail_closed():
    a=np.zeros((100,200,3),np.uint8)
    with pytest.raises(ValueError,match='region'):
        contrast_witness(a,a,(0,0,201,101))
    with pytest.raises(ValueError,match='aligned'):
        refraction_motion_witness(a,a[:,1:],(1,1,20,20))


def test_preencode_scope_distinguishes_protection_and_support():
    from editorial_engine.effect_witness import preencode_scope_witness
    c=np.zeros((40,60,3),np.uint8)
    a=c.copy()
    m=np.zeros((40,60),bool)
    m[10:30,10:40]=True
    p=np.zeros((40,60),np.uint8)
    p[12:16,16:20]=255
    a[20:22,21:24]=2
    kwargs=dict(material_support=m,protection=p)
    assert preencode_scope_witness(a,c,**kwargs)==dict(
        changed_px=6,outside_material_changed_px=0,fully_protected_changed_px=0,status="scoped_effect_visible")
    a[2,4]=1
    a[12,16]=1
    assert preencode_scope_witness(a,c,**kwargs)==dict(
        changed_px=8,outside_material_changed_px=1,fully_protected_changed_px=1,status="out_of_scope_change")
    with pytest.raises(ValueError,match="nontrivial"):
        preencode_scope_witness(a,c,material_support=np.ones_like(m),protection=p)
