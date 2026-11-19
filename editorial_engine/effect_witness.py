"""Independent, reproducible pixel witnesses for aligned effect-on/control MP4s.

The caller owns the control recipe and source-clock correspondence. These
metrics quantify visible mechanics; they do not infer exact reference style.
"""
from pathlib import Path
from hashlib import file_digest
import cv2
import numpy as np

FRAME_BUDGET = 3600


def frame_set(path, indices):
    ids = tuple(indices)
    if (not ids or len(ids) != len(set(ids)) or
            any(type(i) is not int or not 0 <= i < FRAME_BUDGET for i in ids)):
        raise ValueError("request unique bounded source-clock frame indices")
    required = set(ids)
    kept = {}
    decoder = cv2.VideoCapture(str(Path(path).resolve()))
    try:
        if not decoder.isOpened():
            raise ValueError("could not decode effect witness video")
        for index in range(max(required) + 1):
            ok, frame = decoder.read()
            if not ok:
                raise ValueError(f"missing witness frame {index}")
            if index in required:
                kept[index] = frame
    finally:
        decoder.release()
    return kept


def sha(path):
    with Path(path).open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def _check_pair(effect, control, roi):
    if (not isinstance(effect, np.ndarray) or not isinstance(control, np.ndarray) or
            effect.ndim != 3 or effect.shape[2] != 3 or effect.shape != control.shape or
            effect.dtype != np.uint8 or control.dtype != np.uint8):
        raise ValueError("require aligned uint8 BGR rasters of equal dimensions")
    if (not isinstance(roi, (tuple, list)) or len(roi) != 4 or any(type(i) is not int for i in roi)):
        raise ValueError("explicit integer region is required")
    x, y, r, b = roi
    h, w = effect.shape[:2]
    if not (0 <= x < r <= w and 0 <= y < b <= h):
        raise ValueError("region leaves the source raster")
    return x, y, r, b


def contrast_witness(effect, control, roi, *, threshold=24, axis_x=None):
    """Pixel delta at the final decode. Record outside deltas as codec-sensitive."""
    x, y, r, b = _check_pair(effect, control, roi)
    if type(threshold) is not int or not 1 <= threshold <= 255:
        raise ValueError("invalid delta threshold")
    if axis_x is not None and (type(axis_x) is not int or not x < axis_x < r):
        raise ValueError("optional split axis must lie inside the region")
    delta = cv2.absdiff(effect, control).max(axis=2)
    region = delta[y:b, x:r]
    yy, xx = np.where(region >= threshold)
    outside = int(np.count_nonzero(delta >= threshold)) - len(xx)
    center = None
    if len(xx):
        weights = region[yy, xx].astype(np.float64)
        center = [float(np.average(xx, weights=weights) + x),
                  float(np.average(yy, weights=weights) + y)]
    point_side = None if axis_x is None or center is None else "right" if center[0] > axis_x else "left" if center[0] < axis_x else "centered"
    return {"region": [x, y, r, b], "threshold_8bit": threshold,
            "inside_changed_pixels": len(xx), "outside_changed_pixels": outside,
            "delta_mean_8bit": float(region.mean()), "delta_p95_8bit": float(np.percentile(region, 95)),
            "weighted_centroid_px": center, "side_of_axis": point_side,
            "outside_is_codec_sensitive": True}


def preencode_scope_witness(effect, control, *, material_support, protection):
    """Check the exact compositor inputs to the encoder, excluding codec spread.

    The verifier must provide masks localized independently of the output delta.
    Material support includes every allowed optical and glow region. Protection
    carries fully protected pixels (255); feathered pixels are intentionally
    not treated as fully protected.
    """
    if not isinstance(effect, np.ndarray) or effect.ndim != 3:
        raise ValueError("three-channel raster required")
    h, w = effect.shape[:2]
    _check_pair(effect, control, [0, 0, w, h])
    if (not isinstance(material_support, np.ndarray) or material_support.shape != (h, w)
            or material_support.dtype != np.bool_
            or not isinstance(protection, np.ndarray) or protection.shape != (h, w)
            or protection.dtype != np.uint8):
        raise ValueError("explicit raster-sized support and protection required")
    if not material_support.any() or material_support.all() or not (protection == 255).any():
        raise ValueError("use nontrivial independent scope and protection")
    delta = np.any(effect != control, axis=2)
    changed = int(delta.sum())
    outside = int((delta & ~material_support).sum())
    protected = int((delta & (protection == 255)).sum())
    return {"changed_px": changed, "outside_material_changed_px": outside,
            "fully_protected_changed_px": protected,
            "status": "out_of_scope_change" if outside or protected else
            "scoped_effect_visible" if changed else "no_visible_effect"}


def refraction_motion_witness(effect, control, roi, *, min_tracks=4, luma_delta_floor=6, controls_provenance=None):
    """Find consistent texture displacement between an on/zero-strength pair."""
    x, y, r, b = _check_pair(effect, control, roi)
    if type(min_tracks) is not int or not 3 <= min_tracks <= 64:
        raise ValueError("invalid texture landmark minimum")
    if type(luma_delta_floor) is not int or not 1<=luma_delta_floor<=64:
        raise ValueError("invalid luma delta floor")
    raw = cv2.cvtColor(control, cv2.COLOR_BGR2GRAY)
    out = cv2.cvtColor(effect, cv2.COLOR_BGR2GRAY)
    # Track image features in the differential support, not unaffected parts of
    # the capsule. Threshold is explicit and must be fixed across candidates.
    change = (cv2.absdiff(raw,out) >= luma_delta_floor).astype(np.uint8)*255
    mask = np.zeros_like(raw)
    mask[y:b, x:r] = change[y:b, x:r]
    anchors = cv2.goodFeaturesToTrack(raw, maxCorners=64, qualityLevel=.01,
                                      minDistance=5, mask=mask)
    opts = dict(winSize=(13, 13), maxLevel=1,
                criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, .005))
    stats = {"accepted_tracks": 0, "median_displacement_px": None, "mean_displacement_px": None,
             "p90_displacement_px": None, "status": "insufficient_texture",
             "luma_delta_floor_8bit":luma_delta_floor, "candidate_features":0 if anchors is None else len(anchors),
             "controlled_difference": controls_provenance}
    if anchors is None or len(anchors) < min_tracks:
        return stats
    following, st, _ = cv2.calcOpticalFlowPyrLK(raw, out, anchors, None, **opts)
    if following is None or st is None:
        return stats
    backward, stb, _ = cv2.calcOpticalFlowPyrLK(out, raw, following, None, **opts)
    if backward is None or stb is None:
        return stats
    fb = np.linalg.norm((anchors - backward)[:, 0], axis=1)
    moved = np.linalg.norm((following - anchors)[:, 0], axis=1)
    good = st.ravel().astype(bool) & stb.ravel().astype(bool) & np.isfinite(moved) & (fb <= .75) & (moved <= 32)
    pts = following[:, 0]
    good &= (pts[:, 0] >= x) & (pts[:, 0] < r) & (pts[:, 1] >= y) & (pts[:, 1] < b)
    n = int(good.sum())
    stats["accepted_tracks"] = n
    if n >= min_tracks:
        m = moved[good]
        stats.update(median_displacement_px=float(np.median(m)), mean_displacement_px=float(m.mean()),
                     p90_displacement_px=float(np.percentile(m, 90)), status="texture_motion_measured")
    return stats
