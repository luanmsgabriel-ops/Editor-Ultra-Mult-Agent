"""Measured 2D curves applied to native renderer screen quads.

Geometry is evaluated on the actual output frame clock. Validation happens
before FFmpeg starts; consumption is recorded only by the compositing loop.
No extrapolation, hidden perspective solve or source/reference pixel reuse.
"""
from __future__ import annotations

from fractions import Fraction
import math

import cv2
import numpy as np

from .motion_binding import validate_binding, transform_at


def apply_measured_screen_quads(corners, binding, *, resolution, fps):
    """Return transformed normalized screen quads without changing inputs.

    Native compositor uses a normalized screen quad for artwork. MotionKit's
    masked_canvas transform applies on the FULL output raster. The pivot and
    offsets therefore must be explicitly authored in that raster's pixels.
    """
    if not isinstance(corners, dict) or not corners:
        raise ValueError("An actual native frame quad sequence is required")
    if binding.get("stage") != "masked_canvas":
        raise ValueError("Native measured motion requires masked_canvas stage")
    w, h = resolution
    if (not isinstance(w, int) or not isinstance(h, int) or min(w, h) <= 0
            or len(set(corners)) != len(corners)):
        raise ValueError("Invalid native frame dimensions")
    rate = Fraction(fps)
    if rate <= 0:
        raise ValueError("Output FPS must be positive")
    validate_binding(binding, image_size=(w, h), canvas_size=(w, h))
    result = {}
    for index, raw in corners.items():
        if type(index) is not int or index < 0:
            raise ValueError("Native frame index must be nonnegative")
        quad = np.asarray(raw, dtype=np.float64)
        if quad.shape != (4, 2) or not np.isfinite(quad).all():
            raise ValueError("Native measured quad must have four finite corners")
        motion = transform_at(binding, float(Fraction(index, 1) / rate),
                              (w, h), (w, h))
        p = np.asarray(motion.pivot, dtype=np.float64)
        matrix = cv2.getRotationMatrix2D(tuple(p), motion.angle, motion.scale)
        matrix[:, 2] += (motion.x, motion.y)
        pixels = quad * [w, h]
        transformed = np.column_stack((pixels, np.ones(4))) @ matrix.T
        unit = transformed / [w, h]
        if not np.isfinite(unit).all() or np.any(unit < -1e-7) or np.any(unit > 1+1e-7):
            raise ValueError("Measured native effect leaves output raster")
        result[index] = unit.astype(np.float64)
    return result
