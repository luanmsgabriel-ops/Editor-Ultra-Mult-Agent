"""NumPy-only adaptations from MOTNGRFX, Copyright 2026 okkazoo.

SPDX-License-Identifier: Apache-2.0
Upstream commit: 8c0ddc816616a95f55bddc606eecea3fd5ba5ef1.
Changed by Editor Ultra: removed torch/xp, registry, palette and Bundle coupling;
made hinge parameters explicit; removed front/behind substitution and quotas.
Original source snapshots and provenance are under upstream/ and UPSTREAM.json.
"""
from __future__ import annotations

import math
import numpy as np


def ease(role, u):
    """Adapted from tools/mathtype/kit/camera.py's role-based easing."""
    u = float(np.clip(u, 0.0, 1.0))
    if role == "linear":
        return u
    if role == "smooth":
        return u**3 * (u * (u * 6 - 15) + 10)
    if role == "arrive":
        return 1 - (1 - u)**5
    if role == "exit":
        return u**4
    if role == "camera":
        return 0.5 * (2*u)**3 if u < 0.5 else 1 - 0.5*(2-2*u)**3
    raise ValueError(f"Unknown ease role: {role}")


def rotation(yaw, pitch, roll):
    """Original camera.rot matrix; inputs are radians, world y is up."""
    cy, sy = np.cos(yaw), np.sin(yaw)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cr, sr = np.cos(roll), np.sin(roll)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
    Rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


def project(points, distance, focal, center):
    """camera.project specialized to a fixed +Z camera, retaining true depth."""
    p = np.asarray(points, np.float64)
    depth = float(distance) - p[..., 2]
    if np.any(depth <= 1.0):
        raise ValueError("Geometry crosses the camera near plane")
    xy = np.stack((center[0] + focal*p[..., 0]/depth,
                   center[1] - focal*p[..., 1]/depth), axis=-1)
    return xy, depth


def _segment(t, a, b):
    return float(np.clip((t-a) / max(b-a, 1e-9), 0.0, 1.0))


def _eio(x, p):
    """Original _depth.eio symmetric power curve."""
    x = float(np.clip(x, 0.0, 1.0))
    if x <= 0 or x >= 1:
        return x
    a, b = x**p, (1-x)**p
    return a/(a+b)


def hinge_state(progress, glyph_index, glyph_count, cap_height, stagger=0.10):
    """Adapt HingeUnfold.letter_state's tip/rise/upright/sink/push mechanics.

    Same five original timing curves; progress maps the supplied build window
    onto the original 2.6-second mechanic. No strand or palette substitution.
    """
    total = 2.6 + stagger*max(glyph_count-1, 0)
    t = float(np.clip(progress, 0.0, 1.0))*total - glyph_index*stagger
    tip = _eio(_segment(t, 0.0, 0.7), 2.6)
    rise = _eio(_segment(t, 0.35, 1.1), 2.4)
    up = _eio(_segment(t, 1.2, 2.0), 2.6)
    sink = _eio(_segment(t, 1.1, 1.8), 2.4)
    push = _eio(_segment(t, 1.8, 2.6), 2.6)
    angle = 0.5*math.pi*(tip-up)
    lift = cap_height*(0.75*rise*(1-sink)+0.12*sink*rise+0.5*push)
    return angle, lift


def visibility(alpha, occluder, glyph_ids=None):
    """Adapt overlay_mode.word_visibility to weighted alpha and per-frame IDs.

    This measures coverage, not recognition/readability by a person. Unlike the
    upstream legibility guard, this function never changes the layer order.
    """
    a = np.asarray(alpha, np.float64)
    o = np.asarray(occluder, np.float64)
    area = float(a.sum())
    if area <= 1e-9:
        return {"visible": 0.0, "occluded": 0.0, "glyph_visible": [], "area_px": 0.0}
    hidden = a*o
    vis = 1.0 - float(hidden.sum())/area
    letters = []
    if glyph_ids is not None:
        for glyph in sorted(int(x) for x in np.unique(glyph_ids) if x):
            mask = glyph_ids == glyph
            n = float(a[mask].sum())
            letters.append({"id": glyph, "visible": 1.0-float(hidden[mask].sum())/max(n,1e-9)})
    return {"visible": vis, "occluded": 1.0-vis, "glyph_visible": letters, "area_px": area}

