import numpy as np
import cv2
import pytest
from visual_fidelity.observed_vectors import contours_from_mask, mask_from_contours, svg_from_contours


def test_preserves_counter_and_island():
    mask=np.zeros((100,130),np.uint8)
    cv2.circle(mask,(65,50),40,255,-1)
    cv2.circle(mask,(65,50),23,0,-1)
    cv2.circle(mask,(65,50),6,255,-1)
    paths=contours_from_mask(mask)
    decoded=np.asarray(mask_from_contours(paths,(130,100),1))
    assert decoded[50,65]==255
    assert decoded[50,80]==0
    assert decoded[50,98]==255
    assert (decoded==mask).mean()>.97
    assert 'fill-rule="evenodd"' in svg_from_contours(paths,(130,100))


def test_empty_masks_keep_dimensions():
    paths=contours_from_mask(np.zeros((20,30),np.uint8))
    decoded=mask_from_contours(paths,(30,20),2)
    assert decoded.size==(30,20)
    assert np.asarray(decoded).sum()==0


@pytest.mark.parametrize('points', [[[0,0],[1,1],[float('nan'),0]], [[0,0],[99,1],[1,1]]])
def test_rejects_nonfinite_and_wrong_coordinate_space(points):
    with pytest.raises(ValueError):mask_from_contours([[0,points]],(20,20))
