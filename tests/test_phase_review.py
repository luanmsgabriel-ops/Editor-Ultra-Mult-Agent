import numpy as np
import pytest

from editorial_engine import effect_phase_review as review


@pytest.fixture
def pair(tmp_path, monkeypatch):
    a,b=tmp_path/'a',tmp_path/'b'
    a.write_bytes(b'active')
    b.write_bytes(b'control')
    rng=np.random.default_rng(234)
    texture=rng.integers(0,256,(120,180,3),dtype=np.uint8)
    smooth=texture.copy()
    moved=np.roll(texture,2,axis=1)
    seq={a:{1:moved,2:smooth},b:{1:texture,2:texture}}
    monkeypatch.setattr(review,'frame_set',lambda p,fs:{i:seq[p][i] for i in fs})
    monkeypatch.setattr(review,'presentation_clock',lambda p:((180,120),(0,1,2)))
    spec=dict(roi=[30,20,155,95],min_tracks=4,min_median_px=.6,luma_delta_floor=6)
    c=dict(schema="ultra-phase-pair/1",active_sha256=review.sha(a),
           control_sha256=review.sha(b),phases={'cold':dict(frame=1,**spec),'warm':dict(frame=2,**spec)})
    return a,b,c


def test_both_phases_needed(pair):
    a,b,c=pair
    r=review.analyze_pair(a,b,c)
    assert r['status']=='changes_required'
    assert r['phases']['cold']['status']=='meets_optical_floor'
    assert r['phases']['warm']['status']=='blocked_insufficient_texture'


def test_optical_success_does_not_approve_deliverable(pair):
    a,b,c=pair
    c['phases']['warm']['frame']=1
    r=review.analyze_pair(a,b,c)
    assert r['status']=='optical_floor_witnessed'
    assert not r['aesthetic_approved'] and not r['review_eligibility_evaluated']


def test_unpinned_control_is_rejected(pair):
    a,b,c=pair
    b.write_bytes(b'edited after preparation')
    with pytest.raises(ValueError,match='bound bytes'):
        review.analyze_pair(a,b,c)


def test_invalid_threshold_is_rejected(pair):
    a,b,c=pair
    c['phases']['cold']['min_median_px']=True
    with pytest.raises(ValueError,match='acceptance floor'):
        review.analyze_pair(a,b,c)


def test_different_presentation_clock_is_rejected(pair, monkeypatch):
    a,b,c=pair
    monkeypatch.setattr(review,'presentation_clock',lambda p:((180,120),(0,1,2 if p==a else 3)))
    with pytest.raises(ValueError,match="aligned"):
        review.analyze_pair(a,b,c)
