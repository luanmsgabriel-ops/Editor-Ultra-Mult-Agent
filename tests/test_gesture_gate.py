import pytest
from visual_fidelity.gesture_gate import gesture_gate

def hand(f,**overrides):
    return {**dict(frame=f,point=[.57,.71],confidence=.93,visible=True,in_frame=True,track="hand-a",shot=1),**overrides}

def test_only_confirmed_in_frame_observations_are_emitted():
    assert gesture_gate([hand(i) for i in (0,1,2,3)])=={2:(.57,.71),3:(.57,.71)}

@pytest.mark.parametrize('broken',[{'visible':False},{'track':'hand-b'},{'shot':2},{'confidence':float('nan')},{'point':[1.1,.5]},{'track':None}])
def test_no_crossing_invisible_cut_changed_track_or_invalid_points(broken):
    assert gesture_gate([hand(0),hand(1),hand(2,**broken),hand(3),hand(4)])=={}

def test_missing_and_duplicate_frames_do_not_join_streams():
    assert not gesture_gate([hand(0),hand(1),hand(3),hand(4)])
    with pytest.raises(ValueError,match="unique frames"):
        gesture_gate([hand(0),hand(0)])
