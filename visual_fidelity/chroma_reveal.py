"""Separate a colored motion accent from neutral pixels and reveal replacement lettering."""
import numpy as np
import cv2


def cyan_coverage(bgr, start=12., solid=160.):
    """Coverage estimate for cyan accents on an achromatic background, in BGR."""
    if bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.dtype != np.uint8:
        raise ValueError("Expected a BGR uint8 frame")
    if not 0 <= start < solid <= 255:
        raise ValueError("Invalid chroma thresholds")
    b, g, r = cv2.split(bgr.astype(np.float32))
    return np.clip((np.minimum(b, g) - r - start) / (solid - start), 0., 1.)


def illuminated_reveal(bgr, mask, progress, *, ink, glow, feather=5.):
    """Reveal true glyph alpha from left to right with a luminous advancing edge.

    The fixed layout prevents jumps between glyphs. Glow follows foreground ink
    and vanishes at the endpoints. The input image and mask are never modified.
    """
    if bgr.ndim != 3 or bgr.shape[2] != 3 or bgr.dtype != np.uint8 or mask.shape != bgr.shape[:2] or mask.dtype != np.uint8:
        raise ValueError("Expected matching BGR/alpha uint8 rasters")
    if not np.isfinite(progress) or not np.isfinite(feather) or feather <= 0:
        raise ValueError("Invalid progress or feather")
    if progress <= 0 or not np.any(mask):
        return bgr.copy()
    alpha = mask.astype(np.float32) / 255
    if progress >= 1:
        return np.rint(bgr + (np.float32(ink)-bgr)*alpha[..., None]).clip(0,255).astype(np.uint8)
    x, _, w, _ = cv2.boundingRect(mask)
    front = x - feather * 2 + (w + feather * 4) * progress
    delta = np.arange(mask.shape[1], dtype=np.float32)[None, :] - front
    shown = alpha * np.clip(.5-delta/(feather*2), 0, 1)
    hot = np.exp(-.5*(delta/(feather*1.7))**2)
    color = np.float32(ink)+(np.float32(glow)-np.float32(ink))*hot[..., None]
    halo = cv2.GaussianBlur(shown*hot, (0,0), feather*1.25)
    base = bgr + (np.float32(glow)-bgr)*np.minimum(halo*.95,1)[...,None]
    return np.rint(base+(color-base)*shown[...,None]).clip(0,255).astype(np.uint8)
