"""Fit and evaluate measured element motion on its original presentation clock.

The serializable curves, rather than a second easing implementation, supply both
render poses and kinematics.  Angles are already unwrapped, visually CCW degrees
in the OpenCV x-right/y-down raster.  Scale is relative to the declared reference
geometry and is interpolated in log space.  No channel extrapolates across a cut,
an explicit missing/occluded/rejected observation, or an excessive frame gap.

Call ``validate_profile`` once when loading a profile from disk.  Evaluation only
performs lightweight schema/element checks; renderers should pin ``profile_digest``
when they bind a curve.  Training residuals of these interpolating curves are not
tracking accuracy or visual approval.  PCHIP acceleration at an interior knot is
the right-hand value (the last knot uses its left-hand value).
"""

from __future__ import annotations

from bisect import bisect_right
import copy
from fractions import Fraction
import hashlib
import json
import math

import numpy as np
from scipy.interpolate import PchipInterpolator


OBSERVATION_SCHEMA = "element-motion-observations/1"
SCHEMA = "element-motion-curves/1"
CHANNELS = {"position_px": 2, "scale": 1, "angle_deg_unwrapped": 1}


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _integer(value, name, minimum=None):
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError(f"{name} must be an integer" + (f" >= {minimum}" if minimum is not None else ""))
    return value


def _canonical(value):
    def check(item):
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("JSON values must be finite")
    check(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Motion data must be finite JSON data") from exc


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def profile_digest(profile):
    """SHA-256 of sorted, compact UTF-8 JSON; no embedded digest is excluded."""
    if not isinstance(profile, dict) or profile.get("schema") != SCHEMA:
        raise ValueError(f"Expected {SCHEMA}")
    return _digest(profile)


def _source(source):
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    for key in ("width", "height"):
        _integer(source.get(key), f"source.{key}", 1)
    digest = source.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
        raise ValueError("source.sha256 must be a SHA-256 hex digest")
    _integer(source.get("first_pts"), "source.first_pts")
    if not isinstance(source.get("time_base"), str):
        raise ValueError("source.time_base must be a rational string")
    try:
        tick = Fraction(source["time_base"])
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError("Invalid source.time_base") from exc
    if tick <= 0:
        raise ValueError("source.time_base must be positive")
    if source.get("coordinate_convention") != "opencv_pixel_centers":
        raise ValueError("Expected opencv_pixel_centers coordinates")
    rotation = _integer(source.get("rotation_ccw_applied"), "source.rotation_ccw_applied")
    if rotation not in (0, 90, 180, 270):
        raise ValueError("Applied raster rotation must be 0, 90, 180 or 270")
    if "fps" in source:
        if isinstance(source["fps"], bool):
            raise ValueError("source.fps must be positive")
        try:
            fps = Fraction(str(source["fps"]))
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("Invalid source.fps") from exc
        if fps <= 0:
            raise ValueError("source.fps must be positive")
    return tick


def _time(source, tick, pts):
    if pts < source["first_pts"]:
        raise ValueError("Sample PTS precedes source.first_pts")
    try:
        return _number(float((pts - source["first_pts"]) * tick), "sample time")
    except OverflowError as exc:
        raise ValueError("Sample time exceeds finite range") from exc


def _reference(reference):
    if not isinstance(reference, dict):
        raise ValueError("reference must be an object")
    if "size_px" in reference:
        if not isinstance(reference["size_px"], (list, tuple)) or len(reference["size_px"]) != 2:
            raise ValueError("reference.size_px must have two dimensions")
        if any(_number(v, "reference.size_px") <= 0 for v in reference["size_px"]):
            raise ValueError("reference.size_px must be positive")
    if "anchor" in reference and not isinstance(reference["anchor"], str):
        raise ValueError("reference.anchor must be a string")


def _value(value, name):
    if value is None:
        return None
    if CHANNELS[name] == 2:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("position_px must contain two coordinates or be null")
        return [_number(v, name) for v in value]
    number = _number(value, name)
    if name == "scale" and number <= 0:
        raise ValueError("scale must be positive")
    return number


def _domain_values(values, name):
    result = np.asarray(values, dtype=np.float64).reshape(len(values), CHANNELS[name])
    return np.log(result) if name == "scale" else result


def _coefficients(times, values, name, method):
    if len(times) == 1:
        return []
    ys = _domain_values(values, name)
    if method == "pchip":
        coefficients = np.moveaxis(PchipInterpolator(times, ys, axis=0, extrapolate=False).c, 1, 0)
    else:
        coefficients = np.zeros((len(times) - 1, 4, CHANNELS[name]), dtype=np.float64)
        coefficients[:, 2] = np.diff(ys, axis=0) / np.diff(times)[:, None]
        coefficients[:, 3] = ys[:-1]
    if not np.isfinite(coefficients).all():
        raise ValueError("Curve coefficients exceed finite range")
    return coefficients.tolist()


def _segment(rows, name, method):
    return {
        "segment": rows[0]["segment"],
        "times_s": [row["time_s"] for row in rows],
        "frames": [row["frame"] for row in rows],
        "pts": [row["pts"] for row in rows],
        "values": [row[name] for row in rows],
        "confidence": [row["confidence"] for row in rows],
        "visibility": [row["visibility"] for row in rows],
        "coefficients": _coefficients([r["time_s"] for r in rows], [r[name] for r in rows], name, method),
    }


def _segment_value(segment, name, time_s):
    times = segment["times_s"]
    if not times[0] <= time_s <= times[-1]:
        return None
    if len(times) == 1:
        return np.asarray(segment["values"][0], dtype=float).reshape(CHANNELS[name]), None, None
    index = min(len(times) - 2, bisect_right(times, time_s) - 1)
    delta = time_s - times[index]
    a, b, c, d = np.asarray(segment["coefficients"][index], dtype=float)
    value = ((a * delta + b) * delta + c) * delta + d
    first = (3 * a * delta + 2 * b) * delta + c
    second = 6 * a * delta + 2 * b
    if name == "scale":
        with np.errstate(over="ignore", invalid="ignore"):
            scale = np.exp(value)
            first, second = scale * first, scale * (second + first * first)
            value = scale
    if not all(np.isfinite(item).all() for item in (value, first, second)):
        raise ValueError("Evaluated motion exceeds finite range")
    return value, first, second


def _residuals(segments, name):
    errors = []
    for segment in segments:
        for time_s, target in zip(segment["times_s"], segment["values"]):
            fitted = _segment_value(segment, name, time_s)[0]
            errors.append(math.hypot(*(fitted - np.asarray(target)).ravel()))
    largest = max(errors) if errors else 0
    rms = largest * math.sqrt(sum((e / largest) ** 2 for e in errors) / len(errors)) if largest else 0
    return {"samples": len(errors), "rms": rms if errors else None,
            "max": max(errors) if errors else None, "training_only": True,
            "units": {"position_px": "pixels", "scale": "relative_scale", "angle_deg_unwrapped": "degrees"}[name]}


def fit_profile(observations, *, method="pchip", min_confidence=None, max_gap_frames=1):
    """Fit independently supported channels, without filling rejected observations.

    ``max_gap_frames`` is the largest allowed difference of retained frame indices,
    not a count of missing frames.  Default 1 requires consecutive frames.  A larger
    value explicitly permits interpolation over omitted rows; explicit missing or
    rejected rows always split the channel.  With a confidence threshold, unknown
    confidence is rejected.  Without one it is retained as unknown, never set to 1.
    """
    if not isinstance(observations, dict) or observations.get("schema") != OBSERVATION_SCHEMA:
        raise ValueError(f"Expected {OBSERVATION_SCHEMA}")
    observation_digest = _digest(observations)
    if method not in ("pchip", "linear"):
        raise ValueError("method must be pchip or linear")
    _integer(max_gap_frames, "max_gap_frames", 1)
    if min_confidence is not None and not 0 <= _number(min_confidence, "min_confidence") <= 1:
        raise ValueError("min_confidence must be in [0, 1]")
    source = observations.get("source")
    tick = _source(source)
    elements = observations.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("elements must be a nonempty list")
    output = []
    identifiers = set()
    for element in elements:
        if not isinstance(element, dict):
            raise ValueError("Each element must be an object")
        ident = element.get("id")
        if not isinstance(ident, str) or not ident or ident in identifiers:
            raise ValueError("Element ids must be unique nonempty strings")
        identifiers.add(ident)
        if element.get("model") != "similarity_2d":
            raise ValueError("Only similarity_2d is supported; do not flatten perspective motion")
        reference = element.get("reference", {})
        _reference(reference)
        samples = element.get("samples")
        if not isinstance(samples, list) or not samples:
            raise ValueError("Each element needs a nonempty samples list")
        rows = []
        previous = None
        rejection_counts = {}
        for sample in samples:
            if not isinstance(sample, dict):
                raise ValueError("Samples must be objects")
            frame = _integer(sample.get("frame"), "sample.frame", 0)
            pts = _integer(sample.get("pts"), "sample.pts")
            time_s = _time(source, tick, pts)
            if previous and (frame <= previous[0] or pts <= previous[1] or time_s <= previous[2]):
                raise ValueError("Sample frames, PTS and representable times must strictly increase")
            previous = frame, pts, time_s
            segment = sample.get("segment")
            if not isinstance(segment, str) or not segment:
                raise ValueError("Each sample needs a nonempty segment id")
            confidence = sample.get("confidence")
            if confidence is not None and not 0 <= _number(confidence, "confidence") <= 1:
                raise ValueError("confidence must be null or in [0, 1]")
            status, visibility = sample.get("status"), sample.get("visibility")
            if status not in ("observed", "missing"):
                raise ValueError("status must be observed or missing")
            if visibility not in ("visible", "occluded", "unknown"):
                raise ValueError("visibility must be visible, occluded or unknown")
            if "cut_before" in sample and type(sample["cut_before"]) is not bool:
                raise ValueError("cut_before must be boolean")
            reason = ("missing" if status == "missing" else "occluded" if visibility == "occluded" else
                      "unknown_confidence" if min_confidence is not None and confidence is None else
                      "low_confidence" if min_confidence is not None and confidence < min_confidence else None)
            if reason:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            rows.append(dict(frame=frame, pts=pts, time_s=time_s, segment=segment, confidence=confidence,
                             visibility=visibility, reason=reason, cut_before=sample.get("cut_before", False),
                             **{name: _value(sample.get(name), name) for name in CHANNELS}))
        channels = {}
        for name, dimension in CHANNELS.items():
            segments, run = [], []
            for row in rows:
                valid = row["reason"] is None and row[name] is not None
                split = run and (not valid or row["cut_before"] or row["segment"] != run[-1]["segment"] or
                                 row["frame"] - run[-1]["frame"] > max_gap_frames)
                if split:
                    segments.append(_segment(run, name, method))
                    run = []
                if valid:
                    run.append(row)
            if run:
                segments.append(_segment(run, name, method))
            retained = sum(len(s["frames"]) for s in segments)
            covered_time = sum(s["times_s"][-1] - s["times_s"][0] for s in segments)
            duration = rows[-1]["time_s"] - rows[0]["time_s"]
            channels[name] = {
                "dimension": dimension, "domain": "log" if name == "scale" else "linear", "segments": segments,
                "coverage": {
                    "provided_samples": len(rows), "retained_samples": retained,
                    "frame_span": rows[-1]["frame"] - rows[0]["frame"] + 1,
                    "observation_fraction": retained / (rows[-1]["frame"] - rows[0]["frame"] + 1),
                    "supported_duration_s": covered_time,
                    "supported_time_fraction": covered_time / duration if duration else float(bool(retained)),
                    "interpolated_omitted_frames": sum(b - a - 1 for s in segments for a, b in zip(s["frames"], s["frames"][1:])),
                    "unknown_confidence_retained": sum(c is None for s in segments for c in s["confidence"]),
                },
                "residuals": _residuals(segments, name),
            }
        output.append({"id": ident, "model": "similarity_2d", "reference": copy.deepcopy(reference), "channels": channels,
                       "coverage": {"provided_samples": len(rows), "rejected_samples": sum(rejection_counts.values()),
                                    "rejection_reasons": rejection_counts,
                                    "unknown_confidence_samples": sum(r["confidence"] is None for r in rows)}})
    profile = {"schema": SCHEMA, "source": copy.deepcopy(source), "observations_sha256": observation_digest,
            "fit": {"method": method, "min_confidence": min_confidence, "max_gap_frames": max_gap_frames,
                    "confidence_policy": "filter_only; unknown_is_not_one", "extrapolation": "none",
                    "derivatives": "same_piecewise_polynomial; right_at_interior_knots"},
               "elements": output}
    _canonical(profile)  # Reject finite inputs whose arithmetic overflowed.
    return profile


def _element(profile, element_id):
    if not isinstance(profile, dict) or profile.get("schema") != SCHEMA:
        raise ValueError(f"Expected {SCHEMA}")
    for element in profile.get("elements", []):
        if element.get("id") == element_id:
            return element
    raise ValueError(f"Unknown motion element: {element_id}")


def _evaluate_channels(element, time_s):
    result = {}
    for name in CHANNELS:
        found = None
        for segment in element["channels"][name]["segments"]:
            value = _segment_value(segment, name, time_s)
            if value is not None:
                found = (value, "observed" if time_s in segment["times_s"] else "interpolated")
                break
        result[name] = found
    return result


def _plain(value, name):
    return value.tolist() if CHANNELS[name] > 1 else float(value[0])


def evaluate_element(profile, element_id, time_s):
    """Return supported pose channels; unavailable channels are explicitly None."""
    time_s = _number(time_s, "time_s")
    evaluated = _evaluate_channels(_element(profile, element_id), time_s)
    pose = {name: _plain(item[0][0], name) if item else None for name, item in evaluated.items()}
    return {**pose, "time_s": time_s,
            "channel_status": {name: item[1] if item else "unavailable" for name, item in evaluated.items()}}


def evaluate_kinematics(profile, element_id, time_s):
    """Evaluate derivatives in seconds, plus OpenCV-convention corner probes.

    Centered zoom/rotation has zero center speed but nonzero probe speed.  Probes
    describe the declared 2D rectangle, not physical 3D velocity or recovered
    object depth.  Singleton observations have unknown derivatives.
    """
    time_s = _number(time_s, "time_s")
    element = _element(profile, element_id)
    evaluated = _evaluate_channels(element, time_s)

    def derivative(name, order):
        item = evaluated[name]
        return _plain(item[0][order], name) if item and item[0][order] is not None else None

    position, scale, angle = (derivative(name, 0) for name in CHANNELS)
    velocity, acceleration = derivative("position_px", 1), derivative("position_px", 2)
    sv, sa = derivative("scale", 1), derivative("scale", 2)
    av, aa = derivative("angle_deg_unwrapped", 1), derivative("angle_deg_unwrapped", 2)
    result = {"time_s": time_s, "velocity_px_s": velocity, "acceleration_px_s2": acceleration,
              "speed_px_s": math.hypot(*velocity) if velocity is not None else None,
              "scale_velocity_per_s": sv, "scale_acceleration_per_s2": sa,
              "log_scale_velocity_per_s": sv / scale if sv is not None else None,
              "log_scale_acceleration_per_s2": sa / scale - (sv / scale) ** 2 if sa is not None else None,
              "angular_velocity_deg_s": av, "angular_acceleration_deg_s2": aa, "corners": None}
    reference = element["reference"]
    if position is None or scale is None or angle is None:
        result["corners_unavailable_reason"] = "incomplete_pose"
        return result
    if "size_px" not in reference or reference.get("anchor") != "center":
        result["corners_unavailable_reason"] = "center_anchor_and_reference_size_required"
        return result
    w, h = reference["size_px"]
    theta = math.radians(angle)
    c, s = math.cos(theta), math.sin(theta)
    rotation = np.array([[c, s], [-s, c]])
    center = np.asarray(position)
    complete_velocity = velocity is not None and sv is not None and av is not None
    complete_acceleration = complete_velocity and acceleration is not None and sa is not None and aa is not None
    corners = []
    for label, local in zip(("TL", "TR", "BR", "BL"), ((-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2))):
        rotated = rotation @ local
        turned = np.array([rotated[1], -rotated[0]])
        xy = center + scale * rotated
        v = np.asarray(velocity) + sv * rotated + scale * math.radians(av) * turned if complete_velocity else None
        a = (np.asarray(acceleration) + (sa - scale * math.radians(av) ** 2) * rotated +
             (2 * sv * math.radians(av) + scale * math.radians(aa)) * turned) if complete_acceleration else None
        if any(value is not None and not np.isfinite(value).all() for value in (xy, v, a)):
            raise ValueError("Probe kinematics exceed finite range")
        corners.append({"name": label, "position_px": xy.tolist(), "velocity_px_s": v.tolist() if v is not None else None,
                        "acceleration_px_s2": a.tolist() if a is not None else None,
                        "speed_px_s": math.hypot(*v) if v is not None else None})
    result["corners"] = corners
    return result


def sample_times(profile, element_id):
    """Sorted union of retained knots, in seconds since source.first_pts."""
    element = _element(profile, element_id)
    return sorted({time_s for channel in element["channels"].values() for segment in channel["segments"] for time_s in segment["times_s"]})


def validate_profile(profile):
    """Validate serialized curves once before rendering, including coefficients.

    Recomputing coefficients from retained knots detects inconsistent serialized
    curves.  A caller-pinned digest separately detects any change to the evidence,
    clock, knots or metadata; this validator does not establish media provenance.
    """
    profile_digest(profile)
    digest = profile.get("observations_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("observations_sha256 must be a SHA-256 hex digest")
    source = profile.get("source")
    tick = _source(source)
    fit = profile.get("fit", {})
    method = fit.get("method")
    if method not in ("pchip", "linear") or fit.get("extrapolation") != "none":
        raise ValueError("Unsupported curve interpolation or extrapolation")
    gap = _integer(fit.get("max_gap_frames"), "max_gap_frames", 1)
    threshold = fit.get("min_confidence")
    if threshold is not None and not 0 <= _number(threshold, "min_confidence") <= 1:
        raise ValueError("Invalid confidence threshold")
    elements = profile.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("elements must be a nonempty list")
    identifiers = set()
    for element in elements:
        if not isinstance(element, dict) or not isinstance(element.get("id"), str) or not element["id"] or element["id"] in identifiers:
            raise ValueError("Element ids must be unique nonempty strings")
        identifiers.add(element["id"])
        if element.get("model") != "similarity_2d":
            raise ValueError("Unsupported motion model")
        _reference(element.get("reference"))
        channels = element.get("channels")
        if not isinstance(channels, dict) or set(channels) != set(CHANNELS):
            raise ValueError("Profile must declare all channels, even when unsupported")
        for name, dimension in CHANNELS.items():
            channel = channels[name]
            if not isinstance(channel, dict) or type(channel.get("dimension")) is not int or channel["dimension"] != dimension or channel.get("domain") != ("log" if name == "scale" else "linear"):
                raise ValueError("Invalid channel domain or dimension")
            segments = channel.get("segments")
            if not isinstance(segments, list):
                raise ValueError("segments must be a list")
            previous = None
            for segment in segments:
                if not isinstance(segment, dict) or not isinstance(segment.get("segment"), str) or not segment["segment"]:
                    raise ValueError("Invalid segment")
                arrays = [segment.get(key) for key in ("times_s", "frames", "pts", "values", "confidence", "visibility")]
                if any(not isinstance(array, list) for array in arrays) or not arrays[0] or len({len(a) for a in arrays}) != 1:
                    raise ValueError("Segment sample arrays must have equal nonzero lengths")
                times, frames, pts, values, confidence, visibility = arrays
                last = None
                for time_s, frame, stamp, value, quality, visible in zip(times, frames, pts, values, confidence, visibility):
                    _number(time_s, "time_s")
                    _integer(frame, "frame", 0)
                    _integer(stamp, "pts")
                    if time_s != _time(source, tick, stamp):
                        raise ValueError("Curve time differs from its PTS clock")
                    if previous is not None and (time_s <= previous[0] or frame <= previous[1] or stamp <= previous[2]):
                        raise ValueError("Channel samples overlap or are unordered")
                    if last is not None and frame - last > gap:
                        raise ValueError("Curve bridges an unsupported frame gap")
                    previous, last = (time_s, frame, stamp), frame
                    if _value(value, name) is None:
                        raise ValueError("Fitted samples cannot be null")
                    if quality is not None and not 0 <= _number(quality, "confidence") <= 1:
                        raise ValueError("Invalid retained confidence")
                    if threshold is not None and (quality is None or quality < threshold):
                        raise ValueError("Curve contains rejected confidence")
                    if visible not in ("visible", "unknown"):
                        raise ValueError("Curve contains an occluded sample")
                expected = np.asarray(_coefficients(times, values, name, method))
                try:
                    serialized = segment.get("coefficients")
                    def numeric_coefficients(item):
                        if isinstance(item, list):
                            return [numeric_coefficients(child) for child in item]
                        return _number(item, "coefficient")
                    actual = np.asarray(numeric_coefficients(serialized), dtype=float)
                except (TypeError, ValueError) as exc:
                    raise ValueError("Invalid curve coefficients") from exc
                if actual.shape != expected.shape or not np.isfinite(actual).all() or not np.allclose(actual, expected, rtol=1e-12, atol=1e-12):
                    raise ValueError("Curve coefficients do not match retained observations")
    return True
