"""Real encoded fixtures: partial exit is measurable; disappearance is not."""
import cv2
import numpy as np
from test_motion_observation import _write_video, _texture, _spec
from visual_fidelity.motion_observation import measure_video, _visible_support, _DEFAULTS

def sequence():
    box=(20,50,100,140)
    base=_texture(320,240,box,seed=182)
    matrices=[np.array([[1.,0.,-i*3.3],[0.,1.,i*.12]]) for i in range(24)]
    return box,base,matrices,[cv2.warpAffine(base,m,(320,240),borderValue=40) for m in matrices]

def test_partial_raster_exit_keeps_same_target_measured(tmp_path):
    box,base,matrices,frames=sequence()
    result=measure_video(_write_video(tmp_path,frames),_spec(24,box=box))
    samples=result['elements'][0]['samples']
    assert all(s['status']=='observed' for s in samples)
    for s,m in zip(samples,matrices):
        np.testing.assert_allclose(s['position_px'],m[:,:2]@np.array([70.,120.])+m[:,2],atol=.7)
    assert samples[-1]['diagnostics']['visible_seed_hull_fraction']<.5
    assert samples[8]['diagnostics']['refinement_pyramid_levels']==0

def test_disappearance_stays_missing_and_does_not_reidentify(tmp_path):
    box,base,matrices,frames=sequence()
    frames[12:]=[np.full_like(base,40) for _ in frames[12:]]
    samples=measure_video(_write_video(tmp_path,frames),_spec(24,box=box))['elements'][0]['samples']
    assert all(s['status']=='missing' and s['position_px'] is None for s in samples[12:])

def test_occlusion_inside_raster_does_not_shrink_denominator():
    # A narrow surviving strip of an otherwise on-screen object is insufficient.
    p=np.float32([[x,y] for x in range(20,121,10) for y in range(30,131,10)])[:,None]
    inliers=p[p[:,0,0]<30]
    ok,metrics=_visible_support(p,inliers,np.array([[1.,0.,0.],[0.,1.,0.]]),(320,240),10000.,_DEFAULTS)
    assert not ok
    assert metrics['visible_seed_hull_fraction']==1.

def test_declared_cut_never_bridged_by_seed_refresh(tmp_path):
    box,base,matrices,frames=sequence()
    spec=_spec(24,box=box);spec['cuts']=[8]
    samples=measure_video(_write_video(tmp_path,frames),spec)['elements'][0]['samples']
    assert all(s['status']=='missing' for s in samples[8:])


def test_tiny_inlier_island_rejected_even_with_visible_denominator():
    # 20% remains visible, but 3% original inliers must not pass by normalization.
    p=np.float32([[x,y] for x in range(0,101,5) for y in range(0,101,5)])[:,None]
    small=np.float32([[80,20],[90,20],[100,20],[80,35],[90,35],[100,35]])[:,None]
    ok,metrics=_visible_support(p,small,np.array([[1.,0.,-80.],[0.,1.,0.]]),(320,240),10000.,_DEFAULTS)
    assert metrics['visible_support_coverage']>=_DEFAULTS['min_spatial_coverage']
    assert metrics['seed_feature_hull_coverage']==.03
    assert not ok
