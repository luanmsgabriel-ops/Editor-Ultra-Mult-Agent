import json
import subprocess
import sys

import numpy as np
import pytest

from visual_fidelity.effect_pixel_audit import _comparison, _interval, _observe

CYAN = (255, 255, 0)
HSV = ((80, 150, 75), (100, 255, 255))


def write_clip(path, frames, fps):
    h, w = frames[0].shape[:2]
    subprocess.run([
        'ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24',
        '-s', f'{w}x{h}', '-r', str(fps), '-i', '-', '-c:v', 'ffv1', str(path)
    ], input=np.stack(frames).tobytes(), check=True)


def test_cli_uses_real_clocks_and_removes_unchanged_background(tmp_path):
    h, w = 60, 80
    empty = np.zeros((h, w, 3), np.uint8)
    wall = empty.copy()
    wall[:12, :, :] = CYAN  # Unchanged scenery matches the effect's hue.
    ref = [empty.copy() for _ in range(4)]
    rendered = [wall.copy() for _ in range(6)]
    for picture in ref[2:] + rendered[3:]:
        picture[30:42, 32:48] = CYAN
    for name, frames, rate in [('ref', ref, 4), ('render', rendered, 6), ('clean', [wall]*6, 6)]:
        write_clip(tmp_path / f'{name}.mkv', frames, rate)
    spec = {'effects': [{
        'id': 'title', 'hsv': HSV, 'min_area': .01,
        'reference': {'frames': [0, 4]}, 'render': {'frames': [0, 6]}
    }]}
    filename = tmp_path / 'spec.json'
    report = tmp_path / 'report.json'
    filename.write_text(json.dumps(spec))
    subprocess.run([
        sys.executable, '-m', 'visual_fidelity', 'effect-pixel-audit',
        str(tmp_path / 'ref.mkv'), str(tmp_path / 'render.mkv'), str(filename),
        str(report), '--clean-render-source', str(tmp_path / 'clean.mkv')
    ], check=True)
    entry = json.loads(report.read_text())['effects'][0]
    assert entry['reference']['first_visible_frame'] == 2
    assert entry['render']['first_visible_frame'] == 3
    assert entry['metrics']['presence_iou'] == pytest.approx(1.)
    assert entry['metrics']['mean_absolute_area_difference'] == pytest.approx(0.)
    assert entry['metrics']['onset_shift_phase'] == pytest.approx(0.)
    assert entry['render']['observations'][3]['center'] == pytest.approx([.5, .6])
    assert _observe(wall, None, {}, HSV, .01, 24, None)['center'] is not None
    assert _observe(wall, wall, {}, HSV, .01, 24, None)['center'] is None


def test_matte_and_roi_both_apply_in_full_screen_coordinates():
    frame = np.full((10, 20, 3), CYAN, np.uint8)
    matte = np.zeros(frame.shape[:2], np.uint8)
    matte[4:8] = 255
    out = _observe(frame, None, {'roi': [.50, .1, .75, .6]}, HSV, .01, 24, matte)
    assert out['area_fraction'] == pytest.approx(.05)
    assert out['center'] == pytest.approx([.625, .5])
    with pytest.raises(ValueError, match='dimensions'):
        _observe(frame, None, {}, HSV, .01, 24, matte[:, :-1])


def test_one_frame_false_negative_counts_and_empty_tracks_give_no_match():
    blank = {'area_fraction': 0., 'center': None}
    effect = {'area_fraction': .05, 'center': [.5, .5]}
    out = _comparison([blank, effect, blank], [blank] * 8)
    assert out['missing_phase_fraction'] == pytest.approx(1/3)
    assert out['presence_iou'] == 0.
    assert out['mean_center_distance_normalized_xy'] is None
    assert _comparison([blank], [blank])['presence_iou'] is None


def test_wrong_native_interval_is_rejected():
    with pytest.raises(ValueError, match='interval'):
        _interval({'frames': [0, 5]}, 4)
