"""Composite a group of textured, rounded extruded cards with a registered camera."""
from dataclasses import dataclass
import math

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from .anchor_camera import project
from .planar_portal import render_portal_frame


@dataclass(frozen=True)
class SpatialCard:
    """Offsets, width and thickness use the tracked card width as the unit."""
    texture: np.ndarray  # square RGBA, including rounded corner alpha
    offset: tuple[float, float, float]
    width: float = 1.
    thickness: float = .09
    radius: float = .12  # fraction of the face width
    angles: tuple[float, float, float] = (0., 0., 0.)  # pitch, yaw, roll in degrees
    edge_rgb: tuple[int, int, int] = (91, 102, 127)


def register_anchor(camera, point, observation_px):
    """Correct transverse translation against an observed anchor on the receiver.

    The relative depth, intrinsics and orientation of the solved camera are
    preserved. An observed wall constraint is useful when the camera was fitted
    mostly on the foreground person instead of the wall behind the cards.
    """
    K = np.asarray(camera['K'], dtype=float)
    original = np.asarray(camera['R']) @ point + camera['t']
    observation = np.asarray(observation_px, dtype=float)
    if observation.shape != (2,) or not np.isfinite(observation).all() or original[2] <= 0:
        raise ValueError("Anchor observation needs a finite pixel position and positive depth")
    corrected = np.linalg.solve(K, [*observation, 1.]) * original[2]
    return {**camera, 't': np.asarray(camera['t']) + corrected - original}


def _outline(radius):
    corners = [(1-radius, radius, -90), (1-radius, 1-radius, 0),
               (radius, 1-radius, 90), (radius, radius, 180)]
    points = []
    for x, y, start in corners:
        for angle in np.linspace(start, start+90, 6):
            a = math.radians(angle)
            points.append([x + radius*math.cos(a), y + radius*math.sin(a)])
    return np.array(points, np.float32)


_UNIT = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32)


def _perimeter(quad, outline):
    matrix = cv2.getPerspectiveTransform(_UNIT, quad.astype(np.float32))
    return cv2.perspectiveTransform(outline[None], matrix)[0]


def composite_cards(frame_bgr, track, camera, cards, *, observation_px=None, opacity=1.):
    """Render non-intersecting, independently posed opaque meshes, far to near.

    All cards share a virtual planar receiver behind the anchor. Textures use
    straight RGBA with the declared corner radius. A common world-space light
    casts down-right shadows onto this receiver. No input pixels are mutated.
    """
    if not np.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError("Group opacity must be between zero and one")
    if not opacity or not cards:
        return frame_bgr.copy()
    height, width = frame_bgr.shape[:2]
    size = np.array([width, height])
    camera = {**camera, 'size': size}
    anchor = np.array(track['center'])
    axes = np.array(track['axes'])
    unit = float(track['card_width'])
    if observation_px is not None:
        camera = register_anchor(camera, anchor, observation_px)
    entries = []
    key_light = np.array([-.45, -.72, -.53])
    # Local z points away from the camera, towards the virtual wall.
    light_direction = np.array([.64, .85, 1.])
    receiver_z = .34
    for card in cards:
        if (card.width <= 0 or card.thickness <= 0 or not 0 <= card.radius < .5
                or not np.isfinite([*card.offset, *card.angles, card.width, card.thickness]).all()):
            raise ValueError('Invalid spatial card dimensions or pose')
        basis = Rotation.from_euler('xyz', card.angles, degrees=True).as_matrix().T
        center = np.asarray(card.offset)
        front = center + ((_UNIT - .5) * card.width) @ basis[:2]
        back = front + basis[2] * card.thickness
        shadow = front + (receiver_z - front[:, 2:3]) * light_direction
        projected = []
        for corners in (front, back, shadow):
            quad = project(anchor + unit * corners @ axes, camera)
            if quad is None:
                raise ValueError("Card crosses the camera near plane")
            projected.append(quad * size)
        qfront, qback, qshadow = projected
        outline = _outline(card.radius)
        pfront, pback, pshadow = [_perimeter(q, outline) for q in projected]
        world_center = anchor + unit * center @ axes
        depth = (np.asarray(camera['R']) @ world_center + camera['t'])[2]
        entries.append((depth, card, basis, outline, qfront, pfront, pback, pshadow))
    entries.sort(key=lambda item: -item[0])
    out = frame_bgr.copy()
    shadow_mask = np.zeros((height, width), np.uint8)
    for _, _, _, _, _, _, _, contour in entries:
        cv2.fillConvexPoly(shadow_mask, np.rint(contour*16).astype(np.int32), 255, cv2.LINE_AA, shift=4)
    shadow_mask = cv2.GaussianBlur(shadow_mask, (0, 0), max(1., width*.004))
    out = np.rint(out * (1. - .32*shadow_mask[..., None]/255.)).astype(np.uint8)
    for _, card, basis, outline, front, near, far, _ in entries:
        # The mesh is convex. Faces visible from the front camera have their
        # outside edge to the right of the clockwise front contour.
        for i, start in enumerate(near):
            j = (i+1) % len(near)
            edge = near[j] - start
            across = far[i] - start
            if edge[0]*across[1] - edge[1]*across[0] >= 0:
                continue
            tangent = outline[j] - outline[i]
            normal = tangent[1]*basis[0] - tangent[0]*basis[1]
            light = max(0., np.dot(normal / np.linalg.norm(normal), key_light))
            bgr = tuple((np.asarray(card.edge_rgb)[::-1] * (.45 + .55*light)).astype(int).tolist())
            polygon = [start, near[j], far[j], far[i]]
            cv2.fillConvexPoly(out, np.rint(np.asarray(polygon)*16).astype(np.int32),
                               bgr, cv2.LINE_AA, shift=4)
        layer = render_portal_frame(card.texture, front/size, tuple(size.tolist()), mapping='projective')
        rect_x, rect_y, rect_w, rect_h = cv2.boundingRect(layer[:, :, 3])
        region = np.s_[rect_y:rect_y+rect_h, rect_x:rect_x+rect_w]
        ink = layer[region]
        alpha = ink[:, :, 3:4].astype(np.float32)/255
        out[region] = np.rint(out[region]*(1-alpha) + ink[:, :, 2::-1]*alpha).astype(np.uint8)
    return cv2.addWeighted(frame_bgr, 1-opacity, out, opacity, 0)
