import numpy as np
import pytest
from editorial_engine.thermal_emitter import measure_emitter

@pytest.mark.parametrize('color,side,x,bgr',[('warm','right',22,(0,35,70)),('cool','left',9,(100,55,0))])
def test_detects_only_correct_color_and_side(color, side, x, bgr):
    off=np.full((24,36,3),80,np.uint8); on=off.copy()
    on[3:10,x:x+2]=(off[3:10,x:x+2]+bgr)
    v=measure_emitter(on,off,[0,0,36,24],side,color)
    assert v['strong_px']==14 and v['target_px']==14
    assert v['target_energy_fraction']==1 and v['centroid_x_px']==x+.5

def test_neutral_grade_rejected():
    off=np.full((24,36,3),80,np.uint8); on=off.copy()
    on[3:12]=120
    v=measure_emitter(on,off,[0,0,36,24],'right','warm')
    assert not v['strong_px'] and v['centroid_x_px'] is None

def test_out_of_roi_change_not_scored():
    off=np.full((24,36,3),80,np.uint8);on=off.copy();on[:3,:,2]=210
    v=measure_emitter(on,off,[0,3,36,24],'right','warm')
    assert v['strong_px']==0

def test_counterexample_wrong_side_exposed():
    off=np.full((24,36,3),80,np.uint8);on=off.copy();on[3,6,2]=210
    v=measure_emitter(on,off,[0,0,36,24],'right','warm')
    assert v['opposite_px']==1 and v['target_energy_fraction']==0

def test_reject_geometry_mismatch():
    off=np.zeros((24,36,3),np.uint8)
    with pytest.raises(ValueError): measure_emitter(off,off,[0,0,16,24],'right','warm')
    with pytest.raises(ValueError): measure_emitter(off[1:],off,[0,0,26,20],'right','warm')


@pytest.mark.parametrize("failure", [None, "single_spike", "residue", "wrong_side", "clock"])
def test_pair_demands_temporal_side_and_controls(tmp_path, monkeypatch, failure):
    from editorial_engine import effect_phase_review, effect_witness
    from editorial_engine.thermal_emitter import analyze_thermal_pair
    a, b = tmp_path / "on", tmp_path / "off"
    a.write_bytes(b"render-on")
    b.write_bytes(b"render-off")
    off = np.full((24,36,3), 80, np.uint8)
    frames = {i: off.copy() for i in range(6)}
    for f in ([1] if failure == "single_spike" else [1,2]):
        x = 6 if failure == "wrong_side" else 22
        frames[f][4:8,x:x+2,2] = 160
    for f in (3,4):
        frames[f][4:8,6:8,:2] = 160
    if failure == "residue":
        frames[0][4:8,22:24,2] = 160
    monkeypatch.setattr(effect_witness, "frame_set",
                        lambda p, fs: {f: frames[f] if p == a else off for f in fs})
    monkeypatch.setattr(effect_phase_review, "presentation_clock",
                        lambda p: ((36,24), range(5 if failure == "clock" and p == b else 6)))
    spec = dict(active_sha256=effect_witness.sha(a), control_sha256=effect_witness.sha(b),
                roi=[0,0,36,24], gain=17, min_area=7, min_side_fraction=.95,
                max_control_px=0, warm=[1,2], cool=[3,4], controls=[0,5])
    if failure == "clock":
        with pytest.raises(ValueError, match="aligned"):
            analyze_thermal_pair(a,b,spec)
    else:
        verdict = analyze_thermal_pair(a,b,spec)
        assert verdict["status"] == ("changes_required" if failure else "thermal_direction_witnessed")
        assert not verdict["aesthetic_approved"]
