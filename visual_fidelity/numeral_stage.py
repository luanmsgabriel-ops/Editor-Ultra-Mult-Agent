"""Compositing primitives for an outlined glass numeral over a moving surface."""
import cv2
import numpy as np


def _coverage(mask, shape):
    mask = np.asarray(mask)
    if mask.dtype != np.uint8 or mask.shape != shape:
        raise ValueError("Coverage must be an 8-bit single-channel mask the size of the plate.")
    return mask.astype(np.float32) / 255


def glass_numeral(plate, coverage, top_left=(0, 186, 198), bottom_right=(48, 65, 72),
                  material_delta=None):
    """Shade the visible glyph bounds in RGB. Counterforms retain the clean plate."""
    if plate.dtype != np.uint8 or plate.ndim != 3 or plate.shape[2] != 3:
        raise ValueError("The plate must be RGB uint8.")
    alpha = _coverage(coverage, plate.shape[:2])
    y, x = np.nonzero(alpha)
    if not len(x):
        return plate.copy()
    left, right = x.min(), x.max() + 1
    top, bottom = y.min(), y.max() + 1
    area = np.s_[top:bottom, left:right]
    h, w = bottom - top, right - left
    v, u = np.ogrid[0:1:complex(h), 0:1:complex(w)]
    # Diagonal transmission and grazing edges give the face definition while
    # retaining the texture of the background inside the glass.
    position = np.clip(.70 * v + .30 * u, 0, 1)
    hue = np.asarray(top_left) + position[..., None] * (np.asarray(bottom_right) - top_left)
    transmission = .22 + .47 * ((1 - v) * u + v * (1 - u))
    material = transmission[..., None] * plate[area] + (1 - transmission[..., None]) * hue
    if material_delta is not None:
        # A calibration grid stores RGB differences between the observed material
        # and its clean plate, sampled at fixed relative positions.
        grid = np.asarray(material_delta, dtype=np.float32)
        if grid.ndim != 3 or grid.shape[2] != 3 or min(grid.shape[:2]) < 2 or not np.isfinite(grid).all():
            raise ValueError("Material calibration must be a finite RGB grid of at least 2 × 2.")
        material = np.clip(plate[area] + cv2.resize(grid, (w, h), interpolation=cv2.INTER_LINEAR), 0, 255)
    a = alpha[area]
    dist = cv2.distanceTransform(np.pad((a > .5).astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    bevel = np.clip(2.2 - dist * 210 / max(h, 1), 0, 1)
    edge_color = np.array([8, 96, 104]) * (1 - v[..., None]) + np.array([27, 40, 45]) * v[..., None]
    material += bevel[..., None] * (edge_color - material)
    result = plate.copy()
    result[area] = np.uint8(np.clip(np.rint(plate[area] + a[..., None] * (material - plate[area])), 0, 255))
    return result


def composite_surface(frame, stage, surface, opacity=1.):
    """Composite only inside the measured visible surface, preserving foreground occluders."""
    if frame.shape != stage.shape or frame.dtype != np.uint8 or stage.dtype != np.uint8:
        raise ValueError("Stage and footage must have the same raster and uint8 dtype.")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("Stage and footage must have three channels.")
    if not np.isfinite(opacity) or not 0 <= opacity <= 1:
        raise ValueError("Opacity must be in [0,1].")
    alpha = (_coverage(surface, frame.shape[:2]) * opacity)[..., None]
    return np.rint(frame + alpha * (stage.astype(np.float32) - frame)).astype(np.uint8)
