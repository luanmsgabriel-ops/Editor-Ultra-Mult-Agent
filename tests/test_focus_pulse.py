import numpy as np
import pytest
from visual_fidelity.focus_pulse import FocusPulse,compile_pulses,apply_focus_pulses

def noise():
    return np.random.default_rng(10).integers(0,255,size=(60,80,3),dtype=np.uint8)

def test_exact_neutral_bookends_and_outside():
    frame=noise(); pulses=compile_pulses([FocusPulse(4,11)],frame_count=12)
    assert all(apply_focus_pulses(frame,i,pulses) is frame for i in [1,4,10,11])
    pulse=pulses[0]
    np.testing.assert_allclose([pulse.strength(i) for i in [4,5,6,7,8,9,10]], [0,.25,.75,1,.75,.25,0])
    assert np.count_nonzero(frame!=apply_focus_pulses(frame,7,pulses))>frame.size*.3

def test_preserve_right_prop_pixel_exactly():
    frame=noise(); pulses=compile_pulses([FocusPulse(0,7,protect_right_at=.8)],frame_count=10)
    out=apply_focus_pulses(frame,3,pulses)
    np.testing.assert_array_equal(frame[:,64:],out[:,64:])
    assert not np.array_equal(frame[:,:50],out[:,:50])

@pytest.mark.parametrize('pulses,cuts,locked',[
 ([FocusPulse(1,7)],(4,),()),
 ([FocusPulse(1,7)],(),((4,9),)),
 ([FocusPulse(1,7),FocusPulse(4,12)],(),()),
 ([FocusPulse(1,16)],(),()),
 ([FocusPulse(1,7,sigma_px=float('nan'))],(),()),
 ([FocusPulse(1,7,zoom=.06,protect_right_at=.8)],(),()),
])
def test_fail_closed(pulses,cuts,locked):
    with pytest.raises(ValueError):
        compile_pulses(pulses,frame_count=12,tracking_breaks=cuts,protected_intervals=locked)

def test_zoom_preserves_shape_and_does_not_mutate_source():
    frame=noise();before=frame.copy()
    pulses=compile_pulses([FocusPulse(1,7,sigma_px=0,zoom=.025)],frame_count=12)
    out=apply_focus_pulses(frame,4,pulses)
    assert out.dtype==frame.dtype and out.shape==frame.shape
    np.testing.assert_array_equal(frame,before)
    assert not np.array_equal(out,frame)

def test_generator_bounds_are_not_consumed_by_precheck():
    with pytest.raises(ValueError,match='tracking boundary'):
        compile_pulses(iter([FocusPulse(1,7)]),frame_count=12,tracking_breaks=iter([4]))
    with pytest.raises(ValueError,match='protected transition'):
        compile_pulses(iter([FocusPulse(1,7)]),frame_count=12,protected_intervals=iter([(4,9)]))
