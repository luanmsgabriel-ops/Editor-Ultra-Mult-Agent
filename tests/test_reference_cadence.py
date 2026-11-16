import pytest

from visual_fidelity.reference_cadence import SCHEMA, apply_cadence, musical_position


def test_reference_cut_moves_layers_and_keeps_mask_on_its_original_clock():
    template = {
        'fps': 24, 'frames': 12,
        'frame_bindings': [
            {'frame': i, 'shot': 'a' if i < 3 else 'b',
             'insert': {'source': 'raw', 'frame': i},
             'foreground': {'source': 'raw', 'frame': i, 'matte': f'{i}.png'},
             'mask': {'kind': 'full', 'keyframes': [
                 {'frame': 0, 'opacity': 0}, {'frame': 10, 'opacity': 1},
             ]}}
            for i in range(12)
        ],
    }
    reference = {
        'schema': SCHEMA, 'source_sha256': 'reference', 'status': 'model_inference',
        'fps': '30', 'frames': 20, 'cuts': [{'frame': 10, 'time': 10 / 30}],
        'cut_detector': 'transnet_v2', 'motion_backend': 'raft_small',
        'music': {'backend': 'beat_this'}, 'markers': {},
    }

    result = apply_cadence(template, reference, [{'template_frame': 3, 'reference_cut': 10}])
    assert result['shots'][1]['start'] == 8
    assert result['frame_bindings'][7]['shot'] == 'a'
    frame = result['frame_bindings'][8]
    assert frame['insert']['frame'] == frame['foreground']['frame'] == 3
    assert frame['foreground']['matte'] == '3.png'
    assert frame['mask'] == {'kind': 'full', 'opacity': .3}
    assert 'keyframes' in template['frame_bindings'][3]['mask']


def test_music_retarget_keeps_fractional_beat_position():
    from visual_fidelity.reference_cadence import project_time

    position = musical_position(1.75, {'beats': [1, 2, 3], 'cues': []})
    result = project_time(position, {'beats': [.5, 1.3, 2.1]}, beat_offset=1)
    assert result == pytest.approx(1.9)
    assert position['offset_from_nearest_beat_ms'] == -250
    with pytest.raises(ValueError, match='corresponding beat'):
        project_time(position, {'beats': [.5, 1.3]}, beat_offset=1)
