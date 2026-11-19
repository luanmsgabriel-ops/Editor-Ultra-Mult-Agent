import numpy as np,cv2,pytest
from visual_fidelity.liquid_glass import composite_liquid_glass
Q=np.float32([[.2,.3],[.8,.3],[.8,.7],[.2,.7]])
def texture():
 y,x=np.mgrid[:200,:320];a=((x//8+y//8)%2*150+40).astype(np.uint8);return np.repeat(a[:,:,None],3,2)
def test_real_texture_displacement_not_badge():
 a=texture();b=a.copy();c=a.copy();r={}
 composite_liquid_glass(b,Q,receipt=r);composite_liquid_glass(c,Q,strength_px=0)
 assert r['active_refracted_pixels']>3000 and r['refraction_rgb_mae_active']>.05
 assert np.mean(abs(b.astype(float)-c))>2
 assert r['outside_modified_pixels']==0

def test_protected_and_outside_exact():
 a=texture();p=np.zeros(a.shape[:2],np.uint8);p[:,130:200]=255;b=a.copy();r={}
 composite_liquid_glass(b,Q,glow=.8,protection=p,receipt=r)
 assert np.array_equal(a[:,130:200],b[:,130:200])
 assert r['protected_modified_pixels']==0 and r['outside_modified_pixels']==0

def test_zero_opacity_no_glow_identity():
 a=texture();b=a.copy();composite_liquid_glass(b,Q,opacity=0,glow=0);assert np.array_equal(a,b)

def test_invalid_mask_fails():
 with pytest.raises(ValueError):composite_liquid_glass(texture(),Q,protection=np.zeros((2,2),np.uint8))
from visual_fidelity.liquid_glass import audit_refraction

def test_ablation_requires_visible_texture_not_just_displacement_claim():
 assert audit_refraction(texture(),Q)['verdict']=='verified_framebuffer_refraction'
 assert audit_refraction(np.full((200,320,3),100,np.uint8),Q)['verdict']=='inconclusive_no_visible_texture_response'

def test_declared_optical_matte_cannot_be_inferred_or_resized(tmp_path):
    from visual_fidelity.video_anchor import occlusion_at
    import cv2
    import pytest

    with pytest.raises(ValueError, match="Missing required foreground matte"):
        occlusion_at(tmp_path, "m", 0, (40, 60), strict=True)
    (tmp_path / "m").mkdir()
    cv2.imwrite(str(tmp_path / "m/000000.png"), np.zeros((20,30), np.uint8))
    with pytest.raises(ValueError, match="dimensions"):
        occlusion_at(tmp_path, "m", 0, (40, 60), strict=True)
    assert occlusion_at(tmp_path, "m", 0, (40, 60)).shape == (40, 60)
