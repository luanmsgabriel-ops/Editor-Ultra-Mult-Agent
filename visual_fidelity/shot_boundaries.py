"""Conservative native cut candidates on source-frame order; no video synthesis."""
from __future__ import annotations

from fractions import Fraction
from typing import Iterable

import cv2
import numpy as np
from PIL import Image

SIZE = (72, 48)
ALGORITHM = "adaptive_native_v2"


def _thumb(frame):
    pixels = np.asarray(frame)
    if pixels.ndim != 3 or pixels.shape[-1] != 3 or pixels.dtype != np.uint8:
        raise ValueError("expected H×W×3 uint8 decoded frame")
    if pixels.shape[:2] != SIZE[::-1]:
        pixels = np.asarray(Image.fromarray(pixels).resize(SIZE, Image.Resampling.BOX))
    return pixels


def _difference(a, b):
    return float(np.abs(np.subtract(a, b, dtype=np.int16)).mean())


def _coverage(a, b):
    return float((np.abs(np.subtract(a, b, dtype=np.int16)).max(axis=2) > 32).mean())


def _hist(frame):
    return np.concatenate([np.bincount((frame[..., c] // 16).ravel(), minlength=16)
                           for c in range(3)]) / (3 * frame.shape[0] * frame.shape[1])


def _align(a, b):
    # Fast background translation veto, deliberately from exact pixel geometry.
    # Crops use common valid support; there is no wraparound in the comparison.
    return min(_difference(a[7:-7, 7:-7], b[7+dy:SIZE[1]-7+dy, 7+dx:SIZE[0]-7+dx])
               for dy in (-6, -3, 0, 3, 6) for dx in (-6, -3, 0, 3, 6))


def _same_content_transform(a, b, hist_change):
    """Conservative similarity evidence, never proof of semantic shot continuity.

    ECC matches low-pass luminance under a bounded affine transform. Color
    distribution and singular values veto unrelated/degenerate matches.
    Unknown matches stay hard-cut candidates; transform matches remain tracking
    barriers until a director explicitly reviews them.
    """
    if hist_change > .22:
        return None
    gray = [cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255 for f in (a,b)]
    if min(float(g.std()) for g in gray) < .025:
        return None
    try:
        score, matrix = cv2.findTransformECC(
            gray[0], gray[1], np.eye(2,3,dtype=np.float32), cv2.MOTION_AFFINE,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 70, 1e-5), None, 5)
    except cv2.error:
        return None
    if not np.isfinite(matrix).all() or not np.isfinite(score) or score < .82:
        return None
    try:
        singular = np.linalg.svd(matrix[:,:2], compute_uv=False)
    except np.linalg.LinAlgError:
        return None
    if (min(singular) < .8 or max(singular) > 1.25
            or max(singular)/min(singular) > 1.15
            or np.linalg.det(matrix[:,:2]) <= 0
            or abs(matrix[0,2]) > SIZE[0]*.18 or abs(matrix[1,2]) > SIZE[1]*.18):
        return None
    return {"ecc": round(float(score),5), "affine": matrix.tolist(),
            "histogram_distance": round(hist_change,5)}


def detect_shot_boundaries(frames: Iterable[np.ndarray], fps: int | float | str | Fraction = 30):
    """Frame zero is always the start. Gradual effects do not split tracking."""
    if isinstance(fps, bool):
        raise ValueError("fps must be a positive source frame rate")
    rate = Fraction(str(fps))
    if rate <= 0:
        raise ValueError("fps must be a positive source frame rate")
    data = [_thumb(f) for f in frames]
    n = len(data)
    jumps = [0.0, *(_difference(a, b) for a, b in zip(data, data[1:]))] if n else []
    hist = [_hist(frame) for frame in data]
    cuts, transitions, rejected, uncertain = [0], [], [], []
    flashed = set()
    # A global bright flash returns to substantially the same shot within 1–3 frames.
    # Relative/absolute measurements are both exposed as evidence, not probabilities.
    means = [float(f.mean()) for f in data]
    for i in range(1, n-1):
        if i in flashed or jumps[i] < 19:
            continue
        for end in range(i+1, min(i+4, n)):
            if (min(means[i:end]) - max(means[i-1], means[end]) >= 23
                    and _difference(data[i-1], data[end]) <= 9 and jumps[end] >= 17):
                transitions.append({"kind": "flash_candidate", "start_frame": i,
                                    "end_frame_exclusive": end})
                flashed.update(range(i, end+1))
                break
    for i in range(1, n):
        jump = jumps[i]
        if i in flashed or jump < 13:
            continue
        nearby = jumps[max(1, i-3):i] + jumps[i+1:i+4]
        baseline = float(np.median(nearby)) if nearby else 0.0
        ratio = jump / max(baseline, 5.0)
        coverage = _coverage(data[i-1], data[i])
        hist_change = float(np.abs(hist[i-1] - hist[i]).sum()) / 2
        if not ((jump >= 32 and coverage >= .42 and ratio >= 1.65)
                or (jump >= 16 and coverage >= .30 and ratio >= 2.8 and hist_change >= .10)):
            continue
        aligned = _align(data[i-1], data[i])
        if aligned < 8 and aligned < .39 * jump:
            rejected.append({"frame": i, "reason": "translation_match"})
            continue
        match = _same_content_transform(data[i-1], data[i], hist_change)
        if match is not None:
            uncertain.append(i)
            transitions.append({"kind": "same_content_transform_candidate",
                                "start_frame": i, "end_frame_exclusive": i+1,
                                "pixel_jump": round(jump,3), "match": match,
                                "requires_review": True})
            continue
        cuts.append(i)
        transitions.append({"kind": "hard_cut_candidate", "start_frame": i,
                            "end_frame_exclusive": i+1, "pixel_jump": round(jump, 3),
                            "local_ratio": round(ratio, 3), "changed_fraction": round(coverage, 3)})
    # Detect monotone trips to near-black (not arbitrary morphs/crossfades).
    # Keep these as transition evidence rather than hard-cut boundaries.
    min_steps = max(4, round(float(rate) * .15))
    max_steps = max(min_steps, round(float(rate) * 1.2))
    for sign, kind in ((-1, "fade_out_candidate"), (1, "fade_in_candidate")):
        cursor = 1
        while cursor < n:
            if sign * (means[cursor] - means[cursor-1]) <= .75:
                cursor += 1
                continue
            start = cursor - 1
            while cursor < n and sign * (means[cursor] - means[cursor-1]) > .75 and jumps[cursor] < 30:
                cursor += 1
            count = cursor - 1 - start
            if min_steps <= count <= max_steps and abs(means[cursor-1] - means[start]) >= 24 and min(means[start], means[cursor-1]) <= 18:
                transitions.append({"kind": kind, "start_frame": start, "end_frame_exclusive": cursor})
            if cursor == start + 1:
                cursor += 1
    for event in transitions:
        event.update(start_seconds=float(Fraction(event["start_frame"]) / rate),
                     end_seconds=float(Fraction(event["end_frame_exclusive"]) / rate))
    return {"algorithm": ALGORITHM, "frame_count": n, "fps": str(rate),
            "shot_starts": cuts, "uncertain_boundaries": uncertain,
            "tracking_breaks": sorted(set(cuts + uncertain)), "transitions": sorted(transitions, key=lambda x:x["start_frame"]),
            "rejected": rejected}
