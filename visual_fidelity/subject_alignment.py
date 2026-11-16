"""Measured 2D subject calibration, bound to its media and timeline revision.

This is a similarity transform, not a depth estimate, pose detector or video
generator. Missing controls are never interpolated. Shrinking a photographic
plate leaves transparent pixels; the caller must supply an independent backplate.
"""
from __future__ import annotations

import copy
from fractions import Fraction
import hashlib
import json
import math
import re

import cv2
import numpy as np

VERSION = "1.0.0"
SCHEMA = "subject-alignment/1"
PLAN_SCHEMA = "subject-alignment-plan/1"
_HEAD = {"left_eye", "right_eye", "nose", "left_ear", "right_ear",
         "head_top", "chin", "head_left", "head_right", "head_center"}
_SHOULDERS = {"left_shoulder", "right_shoulder"}
_DEFAULT_ANCHORS = ["left_eye", "right_eye", "nose", "left_ear", "right_ear",
                    "left_shoulder", "right_shoulder"]
_DEFAULT_REQUIRED = ["left_eye", "right_eye", "left_shoulder", "right_shoulder"]
_BINDING_FIELDS = ("kind", "sha256", "raster", "viewport_xywh", "fps", "frames",
                   "revision", "clock")


def _number(value, label):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise ValueError(label + " must be finite numeric data")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(label + " must be finite numeric data")
    return result


def _integer(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(label + f" must be an integer >= {minimum}")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + " must be nonempty text")
    return value


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected lowercase SHA-256")
    return value


def _raster(value, label):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(label + " needs [width, height]")
    return [_integer(v, label, 1) for v in value]


def _fps(value):
    if not isinstance(value, str):
        raise ValueError("FPS must be an explicit rational string")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("Invalid FPS") from error
    if result <= 0:
        raise ValueError("FPS must be positive")
    return f"{result.numerator}/{result.denominator}"


def _viewport(value, raster, label):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError(label + " needs [x, y, width, height]")
    x, y, w, h = [_number(v, label) for v in value]
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > raster[0] or y + h > raster[1]:
        raise ValueError(label + " must be within its raster")
    return [x, y, w, h]


def _media(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + " binding must be an object")
    result = {k: copy.deepcopy(value.get(k)) for k in _BINDING_FIELDS}
    if result["kind"] not in {"image", "video", "sequence"}:
        raise ValueError(label + " kind must be image, video or sequence")
    _digest(result["sha256"])
    result["raster"] = _raster(result["raster"], label + " raster")
    result["viewport_xywh"] = _viewport(result["viewport_xywh"], result["raster"], label + " viewport")
    result["fps"] = _fps(result["fps"])
    _integer(result["frames"], label + " frames", 1)
    _text(result["revision"], label + " revision")
    clock = result["clock"]
    if not isinstance(clock, dict) or set(clock) != {"start_frame", "step"}:
        raise ValueError(label + " requires explicit start_frame and step")
    _integer(clock["start_frame"], label + " start_frame")
    _integer(clock["step"], label + " step")
    if result["kind"] == "image":
        if result["frames"] != 1 or clock != {"start_frame": 0, "step": 0}:
            raise ValueError("A still image needs one frame and explicit stationary clock")
    elif clock["step"] != 1:
        raise ValueError("Video alignment does not perform implicit freeze, skip or retime")
    if clock["start_frame"] >= result["frames"]:
        raise ValueError(label + " clock is outside media")
    mapping = copy.deepcopy(value.get("coordinate_mapping", {
        "raster": result["raster"], "viewport_xywh": result["viewport_xywh"], "units": "pixels"}))
    if not isinstance(mapping, dict) or mapping.get("units") not in {"pixels", "normalized"}:
        raise ValueError(label + " coordinate_mapping units must be pixels or normalized")
    mapping["raster"] = _raster(mapping.get("raster"), label + " measurement raster")
    mapping["viewport_xywh"] = _viewport(mapping.get("viewport_xywh"), mapping["raster"], label + " measurement viewport")
    sx = result["viewport_xywh"][2] / mapping["viewport_xywh"][2]
    sy = result["viewport_xywh"][3] / mapping["viewport_xywh"][3]
    if not math.isclose(sx, sy, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError("Coordinate mapping would distort aspect ratio")
    result["coordinate_mapping"] = mapping
    return result


def _timeline(value):
    if not isinstance(value, dict):
        raise ValueError("timeline binding must be an object")
    return {"revision": _text(value.get("revision"), "timeline revision"),
            "raster": _raster(value.get("raster"), "timeline raster"),
            "fps": _fps(value.get("fps")),
            "frames": _integer(value.get("frames"), "timeline frames", 1)}


def _settings(value):
    if not isinstance(value, dict):
        raise ValueError("settings must be an object")
    result = {"anchor_names": list(_DEFAULT_ANCHORS), "required_anchors": list(_DEFAULT_REQUIRED),
              "min_confidence": .6, "allow_inferred": False, "max_rmse_px": 12.,
              "max_anchor_error_px": 24., "min_scale": .25, "max_scale": 4.,
              "max_rotation_deg": 25., "scale_adjustment": 1., "pivot": "head_center"}
    unknown = set(value) - set(result)
    if unknown:
        raise ValueError("Unknown alignment settings: " + ", ".join(sorted(unknown)))
    result.update(copy.deepcopy(value))
    for key in ("anchor_names", "required_anchors"):
        anchors = result[key]
        if (not isinstance(anchors, list) or not anchors or len(set(anchors)) != len(anchors)
                or not set(anchors) <= _HEAD | _SHOULDERS):
            raise ValueError(key + " must contain distinct supported anatomical anchors")
    if not set(result["required_anchors"]) <= set(result["anchor_names"]):
        raise ValueError("Required anchors must be selected")
    if not _SHOULDERS <= set(result["required_anchors"]) or len(set(result["required_anchors"]) & _HEAD) < 2:
        raise ValueError("Calibration requires both shoulders and at least two head anchors")
    for key in ("min_confidence", "max_rmse_px", "max_anchor_error_px", "min_scale", "max_scale", "max_rotation_deg", "scale_adjustment"):
        result[key] = _number(result[key], key)
    if not 0 <= result["min_confidence"] <= 1:
        raise ValueError("min_confidence must be in [0, 1]")
    if min(result[k] for k in ("max_rmse_px", "max_anchor_error_px", "min_scale", "max_scale", "scale_adjustment")) <= 0:
        raise ValueError("Tolerances and scales must be positive")
    if result["min_scale"] >= result["max_scale"] or not 0 <= result["max_rotation_deg"] <= 180:
        raise ValueError("Invalid scale/rotation limits")
    if not isinstance(result["allow_inferred"], bool):
        raise ValueError("allow_inferred must be boolean")
    if result["pivot"] not in {"head_center", "shoulder_center"}:
        raise ValueError("pivot must be head_center or shoulder_center")
    return result


def _mapped_point(record, media, settings):
    if not isinstance(record, dict):
        return None, "missing"
    state = record.get("state")
    if state not in {"detected", "measured", "inferred"}:
        return None, "unsupported_state"
    if state == "inferred" and not settings["allow_inferred"]:
        return None, "inferred_not_authorized"
    confidence = record.get("confidence")
    if state == "measured":
        if record.get("reviewed") is not True or not isinstance(record.get("method"), str) or not record["method"].strip():
            return None, "manual_measurement_unreviewed"
        if confidence is not None:
            confidence = _number(confidence, "landmark confidence")
            if not 0 <= confidence <= 1:
                raise ValueError("landmark confidence outside [0, 1]")
        weight = 1.  # A declared manual observation, not a fabricated detector score.
    else:
        if confidence is None:
            return None, "unknown_confidence"
        confidence = _number(confidence, "landmark confidence")
        if not 0 <= confidence <= 1:
            raise ValueError("landmark confidence outside [0, 1]")
        if confidence < settings["min_confidence"] or confidence == 0:
            return None, "low_confidence"
        weight = confidence
    xy = record.get("xy")
    if not isinstance(xy, list) or len(xy) != 2:
        return None, "missing_coordinates"
    point = np.asarray([_number(v, "landmark coordinate") for v in xy])
    mapping = media["coordinate_mapping"]
    if mapping["units"] == "normalized":
        point *= mapping["raster"]
    mx, my, mw, mh = mapping["viewport_xywh"]
    if point[0] < mx or point[0] > mx + mw or point[1] < my or point[1] > my + mh:
        return None, "outside_measurement_viewport"
    dx, dy, dw, dh = media["viewport_xywh"]
    point = (point - [mx, my]) * [dw / mw, dh / mh] + [dx, dy]
    return {"xy": point.tolist(), "confidence": confidence, "state": state,
            "weight": weight, "weight_basis": "reviewed_measurement" if state == "measured" else "detector_confidence"}, None


def fit_similarity(source_points, target_points, weights=None):
    """Least-squares proper similarity, mapping source pixels into target pixels.

    Returns a JSON-compatible result. All points participate in residual QC;
    outliers are never discarded to make a failed anatomy fit appear successful.
    """
    source = np.asarray(source_points, dtype=np.float64)
    target = np.asarray(target_points, dtype=np.float64)
    if source.ndim != 2 or source.shape[1:] != (2,) or source.shape != target.shape or len(source) < 3:
        raise ValueError("Fit needs at least three paired 2D controls")
    if not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("Fit controls must be finite")
    weight = np.ones(len(source)) if weights is None else np.array(weights, dtype=np.float64, copy=True)
    if weight.shape != (len(source),) or not np.isfinite(weight).all() or np.any(weight <= 0):
        raise ValueError("Fit weights must be finite and positive")
    weight /= weight.sum()
    source_mean = np.sum(source * weight[:, None], axis=0)
    target_mean = np.sum(target * weight[:, None], axis=0)
    x, y = source - source_mean, target - target_mean
    if np.linalg.matrix_rank(x) < 2 or np.linalg.matrix_rank(y) < 2:
        raise ValueError("Degenerate/collinear anatomical controls")
    u, singular, vt = np.linalg.svd((x * weight[:, None]).T @ y)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        raise ValueError("Controls require reflection; verify anatomical sides")
    scale = float(singular.sum() / np.sum(weight[:, None] * x * x))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid fitted scale")
    translation = target_mean - scale * rotation @ source_mean
    matrix = np.column_stack([scale * rotation, translation])
    residuals = np.linalg.norm(source @ matrix[:, :2].T + matrix[:, 2] - target, axis=1)
    return {"matrix": matrix.tolist(), "scale": scale,
            "rotation_deg": math.degrees(math.atan2(rotation[1, 0], rotation[0, 0])),
            "translation_px": translation.tolist(), "rmse_px": float(np.sqrt(np.sum(weight * residuals ** 2))),
            "max_error_px": float(residuals.max()), "residuals_px": residuals.tolist()}


def _coverage(matrix, source, base):
    sx, sy, sw, sh = source["viewport_xywh"]
    corners = np.array([[sx, sy], [sx + sw, sy], [sx + sw, sy + sh], [sx, sy + sh]])
    footprint = corners @ matrix[:, :2].T + matrix[:, 2]
    bx, by, bw, bh = base["viewport_xywh"]
    needed = np.array([[bx, by], [bx + bw, by], [bx + bw, by + bh], [bx, by + bh]])
    inverse = cv2.invertAffineTransform(matrix)
    back = needed @ inverse[:, :2].T + inverse[:, 2]
    covered = np.all((back >= [sx - 1e-7, sy - 1e-7]) & (back <= [sx + sw + 1e-7, sy + sh + 1e-7]), axis=1)
    return {"source_footprint_px": footprint.tolist(), "target_viewport_xywh": base["viewport_xywh"],
            "target_corner_coverage": covered.tolist(), "covers_target_viewport": bool(covered.all()),
            "requires_background": not bool(covered.all()),
            "alpha_coverage_verified": False,
            "meaning": "Geometric coverage only; alpha holes and the actual portal mask need separate validation."}


def _sample(sample, source, base, timeline, settings):
    if not isinstance(sample, dict):
        raise ValueError("Each sample must be an object")
    frame = _integer(sample.get("frame"), "sample frame")
    if frame >= timeline["frames"]:
        raise ValueError("Alignment frame outside timeline")
    result = {"frame": frame, "status": "blocked", "issues": [], "gaps": [], "anchors": {}, "matrix": None}
    for name, media in (("source", source), ("base", base)):
        actual = _integer(sample.get(name + "_frame"), name + "_frame")
        expected = media["clock"]["start_frame"] + frame * media["clock"]["step"]
        if actual != expected or actual >= media["frames"]:
            raise ValueError(name + " sample frame disagrees with its explicit clock")
        result[name + "_frame"] = actual
    for name in ("source_landmarks", "base_landmarks"):
        if not isinstance(sample.get(name), dict):
            raise ValueError(name + " must be an object, including when empty")
    names, points_source, points_target, raw_weights = [], [], [], []
    for name in settings["anchor_names"]:
        pair = []
        for side, media in (("source", source), ("base", base)):
            control, gap = _mapped_point(sample[side + "_landmarks"].get(name), media, settings)
            if gap:
                result["gaps"].append({"anchor": name, "side": side, "reason": gap,
                                       "required": name in settings["required_anchors"]})
            pair.append(control)
        if all(p is not None for p in pair):
            result["anchors"][name] = {"source": pair[0], "base": pair[1]}
            names.append(name)
            points_source.append(pair[0]["xy"])
            points_target.append(pair[1]["xy"])
            raw_weights.append(min(pair[0]["weight"], pair[1]["weight"]))
    if any(gap["required"] for gap in result["gaps"]):
        result["issues"].append("required_landmarks_unavailable")
        return result
    groups = ["head" if name in _HEAD else "shoulders" for name in names]
    weights = np.asarray(raw_weights)
    for group in ("head", "shoulders"):
        selected = np.array([g == group for g in groups])
        weights[selected] = .5 * weights[selected] / weights[selected].sum()
    try:
        fitted = fit_similarity(points_source, points_target, weights)
    except ValueError as error:
        result["issues"].append(str(error))
        return result
    target = np.asarray(points_target)
    pivot_names = (["left_eye", "right_eye"] if {"left_eye", "right_eye"} <= set(names)
                   else [name for name in names if name in _HEAD])
    if settings["pivot"] == "shoulder_center":
        pivot_names = ["left_shoulder", "right_shoulder"]
    pivot = target[[names.index(name) for name in pivot_names]].mean(axis=0)
    adjusted = np.array(fitted["matrix"])
    adjustment = settings["scale_adjustment"]
    adjusted[:, :2] *= adjustment
    adjusted[:, 2] = pivot + adjustment * (adjusted[:, 2] - pivot)
    final_scale = fitted["scale"] * adjustment
    adjusted_errors = np.linalg.norm(np.asarray(points_source) @ adjusted[:, :2].T + adjusted[:, 2] - target, axis=1)
    for name, residual, after, weight in zip(names, fitted.pop("residuals_px"), adjusted_errors, weights):
        result["anchors"][name].update({"fit_residual_px": residual,
                                       "adjusted_residual_px": float(after), "fit_weight": float(weight)})
    result.update({"fit": fitted, "matrix": adjusted.tolist(), "scale": final_scale,
                   "scale_adjustment": adjustment, "pivot_px": pivot.tolist(), "pivot_anchors": pivot_names,
                   "adjusted_rmse_px": float(np.sqrt(np.sum(weights * adjusted_errors ** 2))),
                   "adjusted_max_error_px": float(adjusted_errors.max()),
                   "coverage": _coverage(adjusted, source, base),
                   "confidence": {"minimum_detector_score": min(
                       (control[side]["confidence"] for control in result["anchors"].values()
                        for side in ("source", "base") if control[side]["confidence"] is not None), default=None),
                       "semantics": "Observed detector scores, not probability of correct anatomy or visual approval."}})
    if fitted["rmse_px"] > settings["max_rmse_px"]:
        result["issues"].append("fit_rmse_exceeds_tolerance")
    if fitted["max_error_px"] > settings["max_anchor_error_px"]:
        result["issues"].append("fit_anchor_error_exceeds_tolerance")
    if result["adjusted_rmse_px"] > settings["max_rmse_px"]:
        result["issues"].append("adjusted_rmse_exceeds_tolerance")
    if result["adjusted_max_error_px"] > settings["max_anchor_error_px"]:
        result["issues"].append("adjusted_anchor_error_exceeds_tolerance")
    if not settings["min_scale"] <= fitted["scale"] <= settings["max_scale"] or not settings["min_scale"] <= final_scale <= settings["max_scale"]:
        result["issues"].append("scale_outside_limits")
    if abs(fitted["rotation_deg"]) > settings["max_rotation_deg"] + 1e-9:
        result["issues"].append("rotation_outside_limits")
    result["status"] = "ready" if not result["issues"] else "blocked"
    return result


def _seal(plan):
    payload = {key: value for key, value in plan.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def calibrate_alignment(request):
    """Compile measured pairs into a sealed, media-bound per-frame plan.

    Sparse samples are legal for diagnosis. They never authorize unlisted frames.
    A blocked frame blocks the plan until controls/assets are corrected.
    """
    if not isinstance(request, dict) or request.get("schema") != SCHEMA:
        raise ValueError("Expected " + SCHEMA)
    source, base = _media(request.get("source"), "source"), _media(request.get("base"), "base")
    timeline, settings = _timeline(request.get("timeline")), _settings(request.get("settings", {}))
    if base["raster"] != timeline["raster"] or base["fps"] != timeline["fps"] or source["fps"] != timeline["fps"]:
        raise ValueError("Media and timeline must have matching explicit FPS; base raster must match canvas")
    samples = request.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("Explicit alignment samples are required")
    frames = [_sample(sample, source, base, timeline, settings) for sample in samples]
    indices = [frame["frame"] for frame in frames]
    if indices != sorted(set(indices)):
        raise ValueError("Alignment samples must be unique and in chronological order")
    plan = {"schema": PLAN_SCHEMA, "version": VERSION, "source": source, "base": base,
            "timeline": timeline, "settings": settings, "frames": frames,
            "status": "ready" if all(frame["status"] == "ready" for frame in frames) else "blocked",
            "sampled_frames": indices, "complete_coverage": len(indices) == timeline["frames"],
            "interpretation": "Measured similarity in 2D; no recovered depth, new identity or generated motion.",
            "evidence": copy.deepcopy(request.get("evidence", {}))}
    plan["sha256"] = _seal(plan)
    return plan


def _verified_plan(plan):
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("Expected " + PLAN_SCHEMA)
    if plan.get("sha256") != _seal(plan):
        raise ValueError("Alignment plan changed; recalibrate instead of reusing approval")
    if plan.get("status") != "ready":
        raise ValueError("Alignment plan is blocked")
    return plan


def validate_alignment_binding(plan, binding):
    """Reject a plan reused on other bytes, framing, clocks, FPS or revisions.

    All media binding fields are mandatory. ``coordinate_mapping`` is optional
    at runtime: if supplied it must match; otherwise the sealed calibration
    mapping remains authoritative. Caller must hash the actual media bytes.
    """
    _verified_plan(plan)
    if not isinstance(binding, dict):
        raise ValueError("Runtime binding must be an object")
    timeline = _timeline(binding.get("timeline"))
    if timeline != plan["timeline"]:
        raise ValueError("Alignment timeline binding mismatch")
    for side in ("source", "base"):
        actual = _media(binding.get(side), side)
        for field in _BINDING_FIELDS:
            if actual[field] != plan[side][field]:
                raise ValueError(f"Alignment {side}.{field} binding mismatch")
        if "coordinate_mapping" in binding[side] and actual["coordinate_mapping"] != plan[side]["coordinate_mapping"]:
            raise ValueError(f"Alignment {side}.coordinate_mapping binding mismatch")
    return True


def alignment_for_frame(plan, frame):
    """Return only an explicitly calibrated frame, with no hold/interpolation."""
    _verified_plan(plan)
    _integer(frame, "alignment frame")
    for sample in plan["frames"]:
        if sample["frame"] == frame:
            if sample["status"] != "ready":
                raise ValueError("Alignment frame is blocked")
            return copy.deepcopy(sample)
    raise ValueError("Missing alignment frame; no implicit gap fill or end hold")


def warp_aligned_rgba(image, matrix, canvas_size):
    """Apply source-to-canvas similarity with premultiplied-alpha resampling.

    Pixels outside the transformed source remain transparent. No background
    filling, inpainting, stretching or original-footage reuse is performed.
    """
    array = np.asarray(image)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[2] not in (3, 4):
        raise ValueError("Image must be uint8 RGB or straight RGBA")
    width, height = _raster(list(canvas_size), "canvas")
    transform = np.asarray(matrix, dtype=np.float64)
    if transform.shape != (2, 3) or not np.isfinite(transform).all():
        raise ValueError("Similarity matrix must be finite 2x3")
    linear = transform[:, :2]
    gram = linear.T @ linear
    if np.linalg.det(linear) <= 0 or not np.allclose(gram, np.eye(2) * gram[0, 0], rtol=1e-7, atol=1e-8):
        raise ValueError("Alignment matrix must preserve aspect ratio and orientation")
    rgba = array if array.shape[2] == 4 else np.dstack([array, np.full(array.shape[:2], 255, dtype=np.uint8)])
    premultiplied = rgba.astype(np.float32) / 255.
    premultiplied[:, :, :3] *= premultiplied[:, :, 3:4]
    warped = cv2.warpAffine(premultiplied, transform, (width, height), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    alpha = warped[:, :, 3:4]
    np.divide(warped[:, :, :3], alpha, out=warped[:, :, :3], where=alpha > 1e-8)
    warped[:, :, :3][alpha[:, :, 0] <= 1e-8] = 0
    return np.clip(np.rint(warped * 255.), 0, 255).astype(np.uint8)
