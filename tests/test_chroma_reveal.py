import numpy as np
from visual_fidelity.chroma_reveal import cyan_coverage, illuminated_reveal


def test_color_isolated_from_white_and_yellow():
    frame = np.uint8([[[245,245,245], [20,240,240], [200,190,20]]])
    np.testing.assert_array_equal(cyan_coverage(frame), [[0,0,1]])


def test_reveal_respects_clock_and_alpha():
    frame = np.full((25,100,3), 30, np.uint8)
    mask = np.zeros((25,100),np.uint8)
    mask[5:22,10:25] = 255
    mask[5:22,77:92] = 255
    def at(p):
        return illuminated_reveal(frame,mask,p,ink=(190,160,8),glow=(70,240,245),feather=2)
    np.testing.assert_array_equal(at(0),frame)
    assert np.any(at(.5)[:,10:25]!=frame[:,10:25])
    np.testing.assert_array_equal(at(.5)[:,77:],frame[:,77:])
    np.testing.assert_array_equal(at(1)[mask==0],frame[mask==0])
    np.testing.assert_array_equal(at(1)[10,84],(190,160,8))
