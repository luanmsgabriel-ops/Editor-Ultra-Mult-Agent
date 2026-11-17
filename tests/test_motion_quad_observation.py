import copy
import math

import numpy as np
import pytest

from visual_fidelity.motion_profile import evaluate_element, fit_profile
from visual_fidelity.motion_quad_observation import observations_from_quads, SCHEMA


def _source():
    return {'sha256': 'a' * 64, 'width': 720, 'height': 1280,
            'time_base': '1/30000', 'first_pts': 5000,
            'coordinate_convention': 'opencv_pixel_centers', 'rotation_ccw_applied': 0}


BOX = [100., 200., 160., 90.]
QUAD = np.array([[100, 200], [260, 200], [260, 290], [100, 290]], dtype=float)
CENTER = np.array([180., 245.])


def _transformed(angle=0, scale=1, center=CENTER):
    theta = math.radians(angle)
    matrix = scale * np.array([[math.cos(theta), math.sin(theta)], [-math.sin(theta), math.cos(theta)]])
    return ((QUAD - CENTER) @ matrix.T + center).tolist()


def _sample(frame, *, angle=0, scale=1, segment='shot1', quad='auto'):
    return {'frame': frame, 'pts': 5000 + frame * 1001, 'segment': segment,
            'quad_px': _transformed(angle, scale) if quad == 'auto' else quad,
            'confidence': None, 'visibility': 'visible', 'status': 'observed'}


def _spec(samples, tolerance=2):
    return {'schema': SCHEMA, 'fit_tolerance_px': tolerance,
            'elements': [{'id': 'panel', 'reference_box_px': BOX, 'samples': samples}]}


def test_uniform_scale_rotation_and_translation_are_measured_from_all_corners():
    samples = [_sample(0), _sample(1, angle=37, scale=1.8)]
    samples[1]['quad_px'] = _transformed(37, 1.8, [325, 600])
    samples[1]['provenance'] = {'method': 'reviewed_quad', 'note': 'test fixture'}
    spec, source = _spec(samples), _source()
    saved = copy.deepcopy((spec, source))
    observations = observations_from_quads(source, spec)
    result = observations['elements'][0]['samples'][1]
    assert result['status'] == 'observed'
    np.testing.assert_allclose(result['position_px'], [325, 600], atol=1e-10)
    assert result['scale'] == pytest.approx(1.8)
    assert result['angle_deg_unwrapped'] == pytest.approx(37)
    assert result['diagnostics']['fit_rms_px'] < 1e-10
    assert result['diagnostics']['points_used'] == 4
    assert result['diagnostics']['points_rejected'] == 0
    assert result['confidence'] is None
    assert result['provenance'] == samples[1]['provenance']
    assert (spec, source) == saved
    profile = fit_profile(observations)
    pose = evaluate_element(profile, 'panel', 1001 / 30000)
    assert pose['scale'] == pytest.approx(1.8)
    assert observations['source']['first_pts'] == 5000


def test_perspective_quad_is_missing_instead_of_discarding_bad_corner():
    quad = [[100, 200], [260, 200], [220, 290], [140, 290]]
    observations = observations_from_quads(_source(), _spec([_sample(0, quad=quad)], tolerance=1))
    result = observations['elements'][0]['samples'][0]
    assert result['status'] == 'missing'
    assert result['position_px'] is None and result['scale'] is None
    assert result['quad_px'] == quad
    assert result['diagnostics']['reason'] == 'quad_not_representable_by_similarity'
    assert result['diagnostics']['fit_rms_px'] > 1
    assert result['diagnostics']['points_used'] == 4
    assert result['diagnostics']['points_rejected'] == 0


def test_small_measurement_noise_is_declared_by_rms_and_tolerance():
    quad = QUAD.copy()
    quad[2] += [2, 1]
    result = observations_from_quads(_source(), _spec([_sample(0, quad=quad.tolist())], tolerance=2))
    row = result['elements'][0]['samples'][0]
    assert row['status'] == 'observed'
    assert 0 < row['diagnostics']['fit_rms_px'] < 2
    strict = observations_from_quads(_source(), _spec([_sample(0, quad=quad.tolist())], tolerance=.01))
    assert strict['elements'][0]['samples'][0]['status'] == 'missing'


def test_angle_unwrap_stops_at_missing_frame_gap_and_segment_change():
    missing = _sample(2, quad=None)
    missing.update(status='missing', visibility='unknown', provenance={'reason': 'clipped'})
    samples = [_sample(0, angle=170), _sample(1, angle=-175), missing,
               _sample(3, angle=-170), _sample(5, angle=175),
               _sample(6, angle=-175, segment='shot2')]
    rows = observations_from_quads(_source(), _spec(samples))['elements'][0]['samples']
    assert rows[0]['angle_deg_unwrapped'] == pytest.approx(170)
    assert rows[1]['angle_deg_unwrapped'] == pytest.approx(185)
    assert rows[2]['angle_deg_unwrapped'] is None
    assert rows[3]['angle_deg_unwrapped'] == pytest.approx(-170)
    assert rows[4]['angle_deg_unwrapped'] == pytest.approx(175)
    assert rows[5]['angle_deg_unwrapped'] == pytest.approx(-175)
    assert rows[2]['provenance']['reason'] == 'clipped'


def test_explicit_cut_before_resets_unwrap_without_reordering_corners():
    rows = [_sample(0, angle=170), _sample(1, angle=-175)]
    rows[1]['cut_before'] = True
    result = observations_from_quads(_source(), _spec(rows))['elements'][0]['samples']
    assert result[1]['angle_deg_unwrapped'] == pytest.approx(-175)


@pytest.mark.parametrize('quad', [
    [[100, 200], [100, 290], [260, 290], [260, 200]],
    [[100, 200], [260, 290], [260, 200], [100, 290]],
    [[100, 200], [260, 200], [150, 230], [100, 290]],
    [[100, 200], [260, 200], [260, 200], [100, 290]],
    [[100, 200], [260, 200], [260, float('nan')], [100, 290]],
])
def test_invalid_corner_order_convexity_duplicates_and_nan_are_rejected(quad):
    with pytest.raises(ValueError):
        observations_from_quads(_source(), _spec([_sample(0, quad=quad)]))


def test_core_clock_and_status_validation_remain_enforced():
    with pytest.raises(ValueError, match='strictly increase'):
        observations_from_quads(_source(), _spec([_sample(0), _sample(0)]))
    with pytest.raises(ValueError, match='complete quad'):
        observations_from_quads(_source(), _spec([_sample(0, quad=None)]))
    with pytest.raises(ValueError, match='SHA-256'):
        observations_from_quads({**_source(), 'sha256': 'unknown'}, _spec([_sample(0)]))
    with pytest.raises(ValueError, match='positive'):
        observations_from_quads(_source(), _spec([_sample(0)], tolerance=0))
    invalid = _sample(0, quad=None)
    invalid['status'] = 'invalid'
    with pytest.raises(ValueError, match='status'):
        observations_from_quads(_source(), _spec([invalid]))


def test_occluded_or_clipped_quad_is_never_promoted_to_observation():
    samples = [_sample(0), _sample(1), _sample(2, quad=None)]
    samples[1]['visibility'] = 'occluded'
    samples[2].update(status='missing', visibility='unknown')
    rows = observations_from_quads(_source(), _spec(samples))['elements'][0]['samples']
    assert rows[1]['status'] == 'missing' and rows[1]['scale'] is None
    assert rows[2]['status'] == 'missing' and rows[2]['quad_px'] is None
