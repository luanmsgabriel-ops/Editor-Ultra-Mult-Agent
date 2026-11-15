"""Trace observed fixed lettering and preserve its frame coordinates.

This layer is for known visible words. It neither identifies a font nor invents
occluded glyphs. Source decoding and color/region selection belong to the caller.
"""
from __future__ import annotations
from html import escape
import math
import cv2
import numpy as np
from PIL import Image


def contours_from_mask(mask, tolerance=.27, min_area=.8):
    """Return [hole_parity, points] in parent-before-child drawing order."""
    mask = np.asarray(mask)
    if mask.ndim != 2 or mask.dtype != np.uint8 or not mask.size:
        raise ValueError('mask must be a nonempty uint8 grayscale array')
    if not math.isfinite(tolerance) or tolerance < 0 or not math.isfinite(min_area) or min_area < 0:
        raise ValueError('tolerance and min_area must be finite and nonnegative')
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    result = []
    for i, contour in enumerate(contours):
        if len(contour) < 3 or abs(cv2.contourArea(contour)) < min_area:
            continue
        depth = 0
        parent = hierarchy[0, i, 3]
        while parent >= 0:
            depth += 1
            parent = hierarchy[0, parent, 3]
        polygon = cv2.approxPolyDP(contour, tolerance, True)[:, 0].tolist()
        if len(polygon) >= 3:
            result.append([depth % 2, polygon])
    return result


def _validated(paths, size):
    if len(size) != 2 or any(not isinstance(x, int) or isinstance(x, bool) or not 1 <= x <= 8192 for x in size):
        raise ValueError('size must be integer width, height in1..8192')
    result = []
    for entry in paths:
        if len(entry) != 2 or entry[0] not in (0, 1):
            raise ValueError('each contour needs hole parity and polygon')
        points = np.asarray(entry[1], dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
            raise ValueError('polygon must contain at least three finite xy points')
        if (points < 0).any() or (points[:, 0] > size[0]).any() or (points[:, 1] > size[1]).any():
            raise ValueError('polygon is outside its declared local raster')
        result.append((int(entry[0]), points))
    return result


def mask_from_contours(paths, size, supersample=2):
    """Rasterize vectors without decoding any source footage or font file."""
    if not isinstance(supersample, int) or not 1 <= supersample <= 4:
        raise ValueError('supersample must be an integer from1 to4')
    checked = _validated(paths, size)
    w, h = size
    mask = np.zeros((h * supersample, w * supersample), np.uint8)
    for hole, points in checked:
        cv2.fillPoly(mask, [np.rint(points * supersample).astype(np.int32)], 0 if hole else 255)
    image = Image.fromarray(mask)
    return image.resize((w, h), Image.Resampling.LANCZOS) if supersample > 1 else image


def svg_from_contours(paths, size, color='#c20009'):
    """Export a fixed word/layer as ordinary editable SVG paths."""
    checked = _validated(paths, size)
    if not isinstance(color, str):
        raise ValueError('color must be a CSS color string')
    commands = []
    for _, polygon in checked:
        commands.append('M' + ' L'.join(f'{x:g},{y:g}' for x, y in polygon) + ' Z')
    w, h = size
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<path fill="{escape(color, quote=True)}" fill-rule="evenodd" d="{" ".join(commands)}"/></svg>')
