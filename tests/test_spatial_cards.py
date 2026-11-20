import numpy as np

from visual_fidelity.spatial_cards import SpatialCard, composite_cards, register_anchor


def test_registration_and_lit_extrusion_remain_independent_of_texture():
    frame = np.full((120, 120, 3), 240, np.uint8)
    camera = dict(K=[[200,0,60],[0,200,60],[0,0,1]], R=np.eye(3), t=[0,0,0])
    track = dict(center=[0,0,5], axes=np.eye(3), card_width=1)
    observed = (67, 42)
    corrected = register_anchor(camera, track['center'], observed)
    xyz = np.array(track['center']) + corrected['t']
    px = np.asarray(camera['K']) @ xyz
    np.testing.assert_allclose(px[:2]/px[2], observed)
    art = np.full((40, 40, 4), [20, 170, 220, 255], np.uint8)
    card = SpatialCard(art, (0.,0.,0.), thickness=.18, radius=.01, angles=(4,34,0))
    result = composite_cards(frame, track, camera, [card], observation_px=observed)
    assert (result[42,67] == [220,170,20]).all()
    assert (result[:,:,0] < 110).any()  # exposed extruded edge
    assert ((result[:,:,0] == result[:,:,1]) & (result[:,:,0] < 239)).any()  # receiver shadow
    assert np.all(frame == 240)
    assert np.array_equal(composite_cards(frame, track, camera, [card], opacity=0), frame)


def test_near_card_occludes_far_card_independent_of_input_order():
    frame = np.full((100, 100, 3), 255, np.uint8)
    camera = dict(K=[[180, 0, 50], [0, 180, 50], [0, 0, 1]], R=np.eye(3), t=[0, 0, 0])
    track = dict(center=[0, 0, 5], axes=np.eye(3), card_width=1)
    blue = np.full((32, 32, 4), [20, 60, 230, 255], np.uint8)
    gold = np.full((32, 32, 4), [230, 200, 60, 255], np.uint8)
    far = SpatialCard(blue, (0, 0, .02), width=1)
    near = SpatialCard(gold, (.2, .1, -.12), width=.4, angles=(6, 8, 7))
    original = composite_cards(frame, track, camera, [far, near])
    reversed_order = composite_cards(frame, track, camera, [near, far])
    assert np.array_equal(original, reversed_order)
    assert (original[54, 57] == [60, 200, 230]).all()
    assert (original[45, 38] == [230, 60, 20]).all()
