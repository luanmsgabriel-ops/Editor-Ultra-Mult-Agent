"""Regression tests execute the tracker on decoded, encoded synthetic footage."""
from fractions import Fraction
import json
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from visual_fidelity.motion_observation import measure_video, probe_clock, SPEC_SCHEMA


pytestmark = pytest.mark.skipif(not shutil.which('ffprobe'), reason='ffprobe required')


def _write_video(tmp_path, frames, name='source.mkv', fps=25):
    path = tmp_path / name
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'FFV1'), fps,
                             (width, height), isColor=frames[0].ndim == 3)
    assert writer.isOpened(), 'FFV1 encoder unavailable'
    for frame in frames:
        writer.write(frame)
    writer.release()
    return path


def _texture(width=320, height=240, box=(95, 70, 130, 100), seed=42):
    frame = np.full((height, width), 40, np.uint8)
    x, y, w, h = box
    rng = np.random.default_rng(seed)
    patch = rng.integers(55, 220, size=(h, w), dtype=np.uint8)
    patch = cv2.GaussianBlur(patch, (3, 3), .65)
    frame[y:y + h, x:x + w] = patch
    return frame


def _spec(count, seed=0, box=(95, 70, 130, 100)):
    return {'schema': SPEC_SCHEMA, 'elements': [
        {'id': 'panel', 'range': [0, count], 'seed_frame': seed, 'roi_px': list(box)},
    ]}


def test_real_encoded_similarity_tracks_scale_rotation_center_and_backward_seed(tmp_path):
    base = _texture()
    center = np.array([160., 120.])
    matrices = []
    for frame in range(10):
        matrix = cv2.getRotationMatrix2D(tuple(center), frame * 2., 1 + frame * .035)
        matrix[:, 2] += [frame * 1.5, frame * -.7]
        matrices.append(matrix)
    images = [cv2.warpAffine(base, m, (320, 240), borderValue=40) for m in matrices]
    video = _write_video(tmp_path, images)
    result = measure_video(video, _spec(len(images)))
    samples = result['elements'][0]['samples']
    assert all(s['status'] == 'observed' for s in samples)
    assert result['source']['clock_kind'] == 'cfr'
    assert result['source']['time_base'] == '1/1000'
    assert all(s['confidence'] is None for s in samples)
    for sample, matrix in zip(samples, matrices):
        expected = matrix[:, :2] @ center + matrix[:, 2]
        np.testing.assert_allclose(sample['position_px'], expected, atol=.6)
        assert sample['scale'] == pytest.approx(np.hypot(matrix[0, 0], matrix[0, 1]), abs=.012)
        assert sample['angle_deg_unwrapped'] == pytest.approx(sample['frame'] * 2., abs=.5)
    # Seed in the middle: both halves are measured, with seed-relative scale.
    reverse = measure_video(video, _spec(len(images), seed=5, box=(108, 74, 119, 85)))
    track = reverse['elements'][0]['samples']
    assert all(s['status'] == 'observed' for s in track)
    assert track[0]['scale'] == pytest.approx(1 / 1.175, abs=.015)
    assert track[9]['scale'] == pytest.approx(1.315 / 1.175, abs=.015)
    assert track[0]['angle_deg_unwrapped'] == pytest.approx(-10., abs=.6)
    assert track[9]['angle_deg_unwrapped'] == pytest.approx(8., abs=.6)


def test_independent_rois_do_not_cancel_opposite_movements(tmp_path):
    width, height = 400, 200
    left_box, right_box = (30, 60, 100, 80), (260, 60, 100, 80)
    left = _texture(width, height, left_box, 12)
    right = _texture(width, height, right_box, 21)
    images = []
    for i in range(8):
        frame = np.full((height, width), 40, np.uint8)
        l = cv2.warpAffine(left, np.float32([[1, 0, i * 2], [0, 1, 0]]), (width, height), borderValue=40)
        r = cv2.warpAffine(right, np.float32([[1, 0, -i * 2], [0, 1, 0]]), (width, height), borderValue=40)
        frame[:, :width // 2] = l[:, :width // 2]
        frame[:, width // 2:] = r[:, width // 2:]
        images.append(frame)
    spec = {'schema': SPEC_SCHEMA, 'elements': [
        {'id': name, 'range': [0, 8], 'seed_frame': 0, 'roi_px': list(box)}
        for name, box in [('left', left_box), ('right', right_box)]
    ]}
    elements = measure_video(_write_video(tmp_path, images), spec)['elements']
    assert elements[0]['samples'][-1]['position_px'][0] == pytest.approx(94., abs=.5)
    assert elements[1]['samples'][-1]['position_px'][0] == pytest.approx(296., abs=.5)


def test_cut_and_loss_remain_missing_instead_of_joining_other_shot(tmp_path):
    base = _texture()
    frames = [base.copy() for _ in range(7)]
    frames[3] = np.full_like(base, 255)
    spec = _spec(7)
    result = measure_video(_write_video(tmp_path, frames), spec)
    samples = result['elements'][0]['samples']
    assert all(s['status'] == 'observed' for s in samples[:3])
    assert all(s['status'] == 'missing' and s['position_px'] is None for s in samples[3:])
    assert samples[3]['diagnostics']['luminance_activity'] > 100
    assert samples[3]['visibility'] == 'unknown'  # Lost tracking does not prove occlusion.
    spec['cuts'] = [3]
    cut = measure_video(_write_video(tmp_path, [base] * 7, name='cut.mkv'), spec)
    assert cut['elements'][0]['samples'][3]['diagnostics']['reason'] == 'declared_cut_requires_new_seed'
    assert cut['elements'][0]['samples'][2]['segment'] != cut['elements'][0]['samples'][3]['segment']


def test_brightness_activity_is_not_translation_and_seed_geometry_is_explicit(tmp_path):
    base = _texture()
    frames = [np.uint8(base.astype(np.int16) + offset) for offset in [0, 5, 10, 15, 20]]
    spec = _spec(5)
    spec['elements'][0]['reference_box_px'] = [70, 40, 180, 160]
    result = measure_video(_write_video(tmp_path, frames), spec)
    element = result['elements'][0]
    assert element['reference']['size_px'] == [180., 160.]
    for sample in element['samples']:
        assert sample['status'] == 'observed'
        np.testing.assert_allclose(sample['position_px'], [160, 120], atol=.25)
        assert sample['scale'] == pytest.approx(1, abs=.004)
    assert element['samples'][1]['diagnostics']['luminance_activity'] == 5


def test_mask_constrains_seed_features_and_reports_sparse_texture(tmp_path):
    base = _texture()
    path = _write_video(tmp_path, [base] * 4)
    mask_path = tmp_path / 'mask.png'
    cv2.imwrite(str(mask_path), np.zeros_like(base))
    spec = _spec(4)
    spec['elements'][0]['mask_path'] = str(mask_path)
    element = measure_video(path, spec)['elements'][0]
    assert element['samples'][0]['diagnostics']['features'] == 0
    assert element['samples'][0]['diagnostics']['seed_geometry_is_authored']
    assert all(s['status'] == 'missing' for s in element['samples'][1:])
    assert element['selection']['mask']['positive_pixels'] == 0


def test_real_variable_timestamps_are_preserved(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required')
    source = _write_video(tmp_path, [_texture()] * 6)
    vfr = tmp_path / 'vfr.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-vf',
        r'setpts=if(lt(N\,2)\,N/(25*TB)\,(2/25+(N-2)*3/25)/TB)',
        '-fps_mode', 'vfr', '-c:v', 'ffv1', str(vfr)], check=True)
    clock = probe_clock(vfr)
    assert clock['clock_kind'] == 'vfr'
    assert len(set(np.diff(clock['frame_pts']))) > 1
    result = measure_video(vfr, _spec(6))
    assert [s['pts'] for s in result['elements'][0]['samples']] == clock['frame_pts']
    assert Fraction(result['source']['time_base']) > 0


@pytest.mark.parametrize('change', [
    {'cuts': [2, 1]}, {'cuts': [0]}, {'tracker': {'fb_max_px': float('nan')}},
    {'tracker': {'unknown': 2}}, {'rotation_ccw': 45},
])
def test_invalid_configuration_is_rejected(tmp_path, change):
    video = _write_video(tmp_path, [_texture()] * 3)
    with pytest.raises(ValueError):
        measure_video(video, {**_spec(3), **change})


def test_nonmonotonic_pts_rejected_without_repair(monkeypatch):
    payload = {'streams': [{'time_base': '1/1000', 'width': 320, 'height': 240,
                            'avg_frame_rate': '25/1'}], 'frames': [{'pts': 0}, {'pts': 40}, {'pts': 40}]}
    class Result:
        stdout = json.dumps(payload)
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: Result())
    with pytest.raises(ValueError, match='strictly increase'):
        probe_clock('mock-only.mov')


def test_explicit_orientation_changes_the_raster_once(tmp_path):
    video = _write_video(tmp_path, [_texture()] * 4)
    spec = _spec(4, box=(70, 95, 100, 130))
    spec['rotation_ccw'] = 90
    result = measure_video(video, spec)
    assert [result['source']['width'], result['source']['height']] == [240, 320]
    assert result['source']['rotation_ccw_applied'] == 90
    assert all(s['status'] == 'observed' for s in result['elements'][0]['samples'])
