import pytest
from visual_fidelity.foreground_keyframes import Pose, poses

def test_neutral_endpoints_and_motion_inside_same_shot():
    curve=poses([Pose(10,0,0,1,0,0),Pose(14,90,10,1,0,1),Pose(18,150,20,1,0,0)],start=10,end=19,cuts=(8,19))
    assert len(curve)==9 and curve[14].opacity==1 and curve[10].opacity==curve[18].opacity==0
    assert curve[12].x==45 and 0<curve[12].opacity<1

def test_cannot_bridge_a_cut_or_force_visible_edges():
    p=[Pose(4,0,0,1,0,0),Pose(9,100,10,1,0,0)]
    with pytest.raises(ValueError,match='boundary'):
        poses(p,start=4,end=10,cuts=(8,))
    with pytest.raises(ValueError,match='neutral'):
        poses([p[0],Pose(9,100,10,1,0,1)],start=4,end=10)
