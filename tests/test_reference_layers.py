import cv2
import numpy as np

from visual_fidelity.geometric_replay import mask
from visual_fidelity.geometric_video import compose_layers
from visual_fidelity.reference_layers import analyze_layers, apply_layers


def test_analysis_infers_depth_and_independent_content_switches(tmp_path):
    width, height = 240, 160
    base = np.full((height, width, 3), 20, np.uint8)
    subject = np.zeros((height, width), np.uint8)
    subject[34:129, 75:166] = 255
    foreground = np.dstack([np.full_like(base, 80), subject])
    matte = tmp_path / 'subject.png'
    cv2.imwrite(str(matte), subject)
    vertical = {'kind': 'bands', 'axis': 'x', 'intervals': [[.42, .59]]}
    horizontal = {'kind': 'bands', 'axis': 'y', 'intervals': [[.40, .63]]}
    a = mask(vertical, width, height)
    b = mask(horizontal, width, height)
    video = tmp_path / 'observed.avi'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'FFV1'), 30, (width, height))
    assert writer.isOpened()
    writer.write(compose_layers(base, foreground, []))
    for frame in range(1, 13):
        before = np.full_like(base, 145 if frame < 5 else 250)
        after = np.full_like(base, 230)
        if frame >= 8:
            after[:] = (40, 250, 100)
        writer.write(compose_layers(base, foreground, [
            ('behind_subject', before, a), ('in_front_of_subject', after, b),
        ]))
    writer.release()
    geometry = [{'frame': frame, 'mask': {'kind': 'union', 'shapes': [vertical, horizontal]}}
                for frame in range(1, 13)]
    effect = analyze_layers(video, geometry, matte, 0, min_pixels=60)
    back, front = effect['tracks']
    assert back['depth'] == 'behind_subject'
    assert front['depth'] == 'in_front_of_subject'
    assert [x['frame'] for x in back['switches']] == [5]
    assert [x['frame'] for x in front['switches']] == [8]
    output = apply_layers(
        {'fps': 30, 'frame_bindings': [{'frame': i, 'foreground': {'matte': 'matte.png'}}
                                       for i in range(13)]},
        effect,
        {slot['id']: {'source': slot['id']} for t in effect['tracks'] for slot in t['content_slots']},
    )
    for i, expected in [(4, ('layer-1-content-1', 'layer-2-content-1')),
                        (5, ('layer-1-content-2', 'layer-2-content-1')),
                        (8, ('layer-1-content-2', 'layer-2-content-2'))]:
        assert [layer['insert']['source'] for layer in output['frame_bindings'][i]['layers']] == list(expected)
    frame = compose_layers(base, foreground, [('behind_subject', before, a),
                                              ('in_front_of_subject', after, b)])
    assert (frame[45, 114] == 80).all()  # The subject holds out the back strip.
    assert (frame[70, 114] == after[70, 114]).all()  # The front strip wins at the crossing.
