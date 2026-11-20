import cv2
import numpy as np

from editorial_engine.effect_edit import _world_layer
from visual_fidelity.anchor_camera import project
from visual_fidelity.planar_portal import render_portal_frame


def test_world_card_extrudes_texture_silhouette_and_composites_soft_edges():
    canvas = (160, 160)
    camera = {"K": [[200, 0, 80], [0, 200, 80], [0, 0, 1]],
              "R": np.eye(3), "t": np.zeros(3), "size": canvas}
    horizontal = np.array([.8, 0, -.6])
    vertical = np.array([0., 1., 0.])
    forward = np.cross(horizontal, vertical)
    center = np.array([0., 0., 5.])
    track = {"cameras": [camera], "axes": [horizontal, vertical, forward],
             "center": center, "card_width": 2.}
    front = np.array([center - horizontal - vertical, center + horizontal - vertical,
                      center + horizontal + vertical, center - horizontal + vertical])
    quad = project(front, camera)
    alpha = np.zeros((64, 64), np.uint8)
    cv2.circle(alpha, (32, 32), 22, 255, -1, cv2.LINE_AA)
    cv2.circle(alpha, (32, 32), 10, 0, -1, cv2.LINE_AA)
    art = np.full((64, 64, 4), (240, 20, 20, 0), np.uint8)
    art[:, :, 3] = alpha

    output = _world_layer(art, track, 0, canvas, 1.)
    corners = np.rint(quad * canvas).astype(int)
    assert not np.any(output[corners[:, 1], corners[:, 0], 3])
    assert output[80, 80, 3] == 0
    face = render_portal_frame(art, quad, canvas, mapping="projective")
    outside = (face[:, :, 3] == 0) & (output[:, :, 3] > 150)
    assert np.count_nonzero(outside) > 10
    # A partially covered red edge over the side picks up the side's dark color.
    partial = (face[:, :, 3] > 35) & (face[:, :, 3] < 180)
    assert np.any(partial & (output[:, :, 3] > 200) & (output[:, :, 0] < 205))
    faded = _world_layer(art, track, 0, canvas, .5)
    np.testing.assert_array_equal(faded[:, :, 3], np.rint(output[:, :, 3] * .5))
