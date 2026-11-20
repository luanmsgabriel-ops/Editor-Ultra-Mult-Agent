import numpy as np
import pytest

from visual_fidelity.numeral_stage import composite_surface, glass_numeral


def test_glass_preserves_counterform_and_transmits_background():
    base = np.full((45, 60, 3), 190, dtype=np.uint8)
    mask = np.zeros(base.shape[:2], np.uint8)
    mask[4:33, 10:38] = 255
    mask[15:21, 19:26] = 0
    output = glass_numeral(base, mask)
    np.testing.assert_array_equal(output[mask == 0], base[mask == 0])
    assert np.all(output[8, 13] != base[8, 13])
    assert not np.array_equal(output[8, 13], output[30, 34])
    base[12:14] += 40
    assert np.all(glass_numeral(base, mask)[12, 13] > output[12, 13])


def test_matte_and_opacity_are_both_applied():
    base = np.full((3, 5, 3), 50, dtype=np.uint8)
    art = np.full_like(base, 250)
    matte = np.full(base.shape[:2], 255, np.uint8)
    matte[:, 2:4] = 0
    result = composite_surface(base, art, matte, .25)
    assert np.all(result[:, :2] == 100) and np.all(result[:, 2:4] == 50)
    with pytest.raises(ValueError):
        composite_surface(base, art, matte[:, :3])


def test_transport_observed_colour_field_in_glyph_coordinates():
    base = np.full((34, 84, 3), 180, dtype=np.uint8)
    mask = np.zeros(base.shape[:2], np.uint8)
    mask[3:31, 20:61] = 255
    grid = np.array([[[-82, -18, -16], [-10, -2, -1]],
                     [[-42, -39, -35], [-65, -60, -54]]])
    rendered = glass_numeral(base, mask, material_delta=grid)
    assert rendered[8, 25, 0] < rendered[8, 54, 0] - 40
    assert rendered[24, 55, 0] < rendered[8, 55, 0] - 30
    np.testing.assert_array_equal(rendered[0], base[0])
