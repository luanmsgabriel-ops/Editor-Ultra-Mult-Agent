"""Measure a blurred word resolving into letters, then bind that motion to new text.

Input mattes must isolate one horizontal title within a fixed ROI. Frames where
glyphs merge supply group motion only. Use complete, shaped artwork for scripts
with joining glyphs, or when separate glyph motion cannot be observed.
"""
from dataclasses import dataclass
import math
import unicodedata

import cv2
import numpy as np
from PIL import ImageFont

from .anchor_graphics import ink
from .type_layout import glyph_metrics


@dataclass(frozen=True)
class TitleSample:
    # Boxes are (center x, center y, width, height) in source ROI pixels.
    group: np.ndarray
    letters: np.ndarray | None
    edge_sigma: float
    opacity: float


def _center_box(x, y, w, h):
    return [x + w / 2, y + h / 2, w, h]


def measure_title(coverage, *, glyph_count, min_area):
    """Estimate geometry, edge spread and ink strength from a [0,1] matte."""
    alpha = np.asarray(coverage, dtype=np.float32)
    if alpha.ndim != 2 or alpha.size == 0 or not np.isfinite(alpha).all() or alpha.min() < 0 or alpha.max() > 1:
        raise ValueError("Expected a finite, two-dimensional coverage matte in [0,1]")
    if glyph_count < 1 or min_area < 1:
        raise ValueError("Expected a positive glyph count and minimum component size")
    _, labels, stats, centroids = cv2.connectedComponentsWithStats((alpha > .24).astype(np.uint8))
    ids = np.flatnonzero(stats[1:, cv2.CC_STAT_AREA] >= min_area) + 1
    if not ids.size:
        return None
    # A small detached accent is part of its base glyph. Associate only when
    # there is exactly one plausible base vertically underneath it.
    boxes = {i: list(stats[i, :4]) for i in ids}
    used = set(ids)
    for i in np.flatnonzero(stats[1:, cv2.CC_STAT_AREA] >= max(2, min_area * .06)) + 1:
        x, y, width, height, area = stats[i]
        possible = [
            j for j in ids
            if j in boxes and stats[j, 0] <= centroids[i, 0] < stats[j, 0] + stats[j, 2]
            and 0 <= stats[j, 1] - (y + height) <= .4 * stats[j, 3]
            and area <= .38 * stats[j, 4] and width <= stats[j, 2]
        ]
        if len(possible) == 1:
            j = possible[0]
            p, q, w, h = boxes[j]
            l, top = min(p, x), min(y, q)
            boxes[j] = [l, top, max(p+w, x+width)-l, max(q+h, y+height)-top]
            boxes.pop(i, None)
            used.add(i)
    mask = np.isin(labels, list(used))
    box = np.asarray(_center_box(*cv2.boundingRect(mask.astype(np.uint8))))
    letters = None
    if len(boxes) == glyph_count:
        ordered = sorted(boxes.values(), key=lambda coords: coords[0] + coords[2] / 2)
        letters = np.asarray([_center_box(*coords) for coords in ordered])
    peak = float(np.percentile(alpha[mask], 90))
    # A blurred step has slope 1 / (sigma * sqrt(2*pi)) at its midpoint.
    edge = mask & (alpha < peak * .76) & (alpha > peak * .26)
    dx = cv2.Sobel(alpha, cv2.CV_32F, 1, 0, ksize=1) / 2
    dy = cv2.Sobel(alpha, cv2.CV_32F, 0, 1, ksize=1) / 2
    slope = np.percentile(np.hypot(dx[edge], dy[edge]), 75) if edge.any() else 0.
    sigma = float(peak / (slope * math.sqrt(2 * math.pi))) if slope > .001 else 0.
    return TitleSample(box, letters, sigma, peak)


def _letter_transform(sample, rest):
    count = len(rest.letters)
    identity = np.tile((0., 0., 1., 1.), (count, 1))
    if sample.letters is None:
        return identity
    if sample.letters.shape != rest.letters.shape:
        raise ValueError("Inconsistent number of glyphs in observed title")
    local_xy = (sample.letters[:, :2] - sample.group[:2]) / sample.group[2:]
    rest_xy = (rest.letters[:, :2] - rest.group[:2]) / rest.group[2:]
    size_ratio = (sample.letters[:, 2:] / sample.group[2:]) / (rest.letters[:, 2:] / rest.group[2:])
    return np.column_stack((local_xy - rest_xy, size_ratio))


class BoundTitle:
    """Shape a replacement once. Replay measured offsets relative to its own kerning."""

    def __init__(self, text, font: ImageFont.FreeTypeFont, rest: TitleSample):
        if rest is None or rest.letters is None:
            raise ValueError("The resting sample must resolve all source glyphs")
        self.rest = rest
        text = unicodedata.normalize("NFC", text)
        metrics, self.width = glyph_metrics(text, font)
        left, top, right, bottom = font.getbbox(text, anchor="ls")
        self.height = bottom - top
        if self.width <= 0 or self.height <= 0 or not text.strip():
            raise ValueError("The replacement must contain visible glyphs")
        self.glyphs = []
        for entry in metrics:
            char = entry["char"]
            if char.isspace():
                continue
            l, t, r, b = font.getbbox(char, anchor="ls")
            x = entry["origin"] + (l+r)/2
            y = (t+b-top-bottom)/2
            self.glyphs.append((x / self.width - .5, y / self.height, np.asarray(ink(font, char))))

    def mask(self, size, center, width, a: TitleSample, b: TitleSample, mix):
        """Return a coverage matte at an interpolated time between observed frames."""
        if width <= 0 or not 0 <= mix <= 1:
            raise ValueError("Expected a positive width and interpolation fraction in [0,1]")
        rest = self.rest
        group = (1-mix) * a.group + mix * b.group
        moves = (1-mix) * _letter_transform(a, rest) + mix * _letter_transform(b, rest)
        # Sample residual tracks by horizontal ink position, not character index.
        grid = (rest.letters[:, 0] - rest.group[0]) / rest.group[2]
        target_height = width * self.height / self.width
        w, h = group[2:] / rest.group[2:] * (width, target_height)
        cx, cy = np.asarray(center) + (group[:2]-rest.group[:2]) / rest.group[2:] * (width, target_height)
        matte = np.zeros((size[1], size[0]), np.uint8)
        for x, y, glyph in self.glyphs:
            dx, dy, sx, sy = [np.interp(x, grid, values) for values in moves.T]
            gw = max(1, round(glyph.shape[1] / self.width * w * sx))
            gh = max(1, round(glyph.shape[0] / self.height * h * sy))
            left, top = round(cx + (x+dx)*w - gw/2), round(cy + (y+dy)*h - gh/2)
            x0, y0 = max(0, left), max(0, top)
            x1, y1 = min(size[0], left+gw), min(size[1], top+gh)
            if x1 <= x0 or y1 <= y0:
                continue
            scaled = cv2.resize(glyph, (gw, gh), interpolation=cv2.INTER_AREA if gw < glyph.shape[1] else cv2.INTER_CUBIC)
            patch = matte[y0:y1, x0:x1]
            np.maximum(patch, scaled[y0-top:y1-top, x0-left:x1-left], out=patch)
        sigma = ((1-mix)*a.edge_sigma + mix*b.edge_sigma) * target_height / rest.group[3]
        if sigma >= .3:
            matte = cv2.GaussianBlur(matte, (0, 0), sigmaX=sigma, borderType=cv2.BORDER_CONSTANT)
        opacity = (1-mix)*a.opacity + mix*b.opacity
        return np.rint(matte * opacity).astype(np.uint8)
