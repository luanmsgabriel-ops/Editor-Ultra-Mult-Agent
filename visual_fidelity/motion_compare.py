"""Audit measured geometry and compare profiles on an explicitly aligned clock.

These reports describe geometric error and evidence coverage. They never turn
photometric activity, missing observations or a code test into visual approval.
"""
from __future__ import annotations

from bisect import bisect_right
import math

import numpy as np

from .motion_profile import (
    evaluate_element, evaluate_kinematics, profile_digest, sample_times,
    validate_profile,
)
from .motion_peaks import classify_peak, compare_peaks


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _elements(profile):
    return {element["id"]: element for element in profile["elements"]}


def _sampled_peak(rows, key, *, absolute=False):
    classified = classify_peak([
        {"time_s": row["time_s"],
         "value": None if row.get(key) is None else abs(row[key]) if absolute else row[key]}
        for row in rows])
    return {"value": classified["maximum_value"], "time_s": classified["peak_time_s"], **classified}


def _vector_norm(value):
    return None if value is None else float(np.linalg.norm(value))


def _intensities(kinematics, spatial_scale=1.0, clock_rate=1.0):
    corners = kinematics.get("corners") or []
    corner_speeds = [p["speed_px_s"] for p in corners if p.get("speed_px_s") is not None]
    speed = kinematics.get("speed_px_s")
    angular, zoom = kinematics.get("angular_velocity_deg_s"), kinematics.get("log_scale_velocity_per_s")
    return {
        "center_speed": None if speed is None else speed * spatial_scale * clock_rate,
        "corner_speed": max(corner_speeds) * spatial_scale * clock_rate if corner_speeds else None,
        "angular_speed": None if angular is None else abs(angular) * clock_rate,
        "log_scale_speed": None if zoom is None else abs(zoom) * clock_rate,
    }


def _gap_markers(knots, pose_at):
    """Keep an explicit missing row between disconnected valid endpoints."""
    markers = []
    for a, b in zip(knots, knots[1:]):
        middle = (a + b) / 2
        left, right, mid = pose_at(a), pose_at(b), pose_at(middle)
        if any(left.get(k) is not None and right.get(k) is not None and mid.get(k) is None
               for k in ("position_px", "scale", "angle_deg_unwrapped")):
            markers.append(middle)
    return markers


def audit_profile(profile, *, subsamples=4):
    """Return (report, flat rows) using the exact curve evaluator used by render.

    Subsamples refine the derivative report; they do not create new observations.
    Peaks remain labelled sampled peaks. Gaps return missing values, never zero.
    """
    validate_profile(profile)
    if type(subsamples) is not int or not 1 <= subsamples <= 32:
        raise ValueError("subsamples must be an integer in [1,32]")
    diagonal = math.hypot(profile["source"]["width"], profile["source"]["height"])
    rows, elements = [], []
    for element in profile["elements"]:
        knots = sample_times(profile, element["id"])
        times = set(knots)
        for start, end in zip(knots, knots[1:]):
            times.update(start + (end - start) * j / subsamples for j in range(1, subsamples))
        if subsamples == 1:
            times.update(_gap_markers(knots, lambda t: evaluate_element(profile, element["id"], t)))
        current = []
        for time_s in sorted(times):
            pose = evaluate_element(profile, element["id"], time_s)
            motion = evaluate_kinematics(profile, element["id"], time_s)
            position, velocity = pose.get("position_px"), motion.get("velocity_px_s")
            corners = motion.get("corners") or []
            corner_speeds = [c["speed_px_s"] for c in corners if c.get("speed_px_s") is not None]
            speed = motion.get("speed_px_s")
            row = {
                "element_id": element["id"], "time_s": time_s,
                "at_observation_time": time_s in knots,
                "x_px": None if position is None else position[0],
                "y_px": None if position is None else position[1],
                "scale": pose.get("scale"), "angle_deg_unwrapped": pose.get("angle_deg_unwrapped"),
                "vx_px_s": None if velocity is None else velocity[0],
                "vy_px_s": None if velocity is None else velocity[1],
                "speed_px_s": speed,
                "speed_diagonals_s": None if speed is None else speed / diagonal,
                "acceleration_px_s2": _vector_norm(motion.get("acceleration_px_s2")),
                "log_scale_velocity_per_s": motion.get("log_scale_velocity_per_s"),
                "angular_velocity_deg_s": motion.get("angular_velocity_deg_s"),
                "maximum_corner_speed_px_s": max(corner_speeds) if corner_speeds else None,
            }
            current.append(row)
        rows.extend(current)
        elements.append({
            "id": element["id"], "sample_count": len(current),
            "coverage": element.get("coverage"),
            "channel_coverage": {name: channel.get("coverage") for name, channel in element["channels"].items()},
            "channel_residuals": {name: channel.get("residuals") for name, channel in element["channels"].items()},
            "peak_center_speed_px_s": _sampled_peak(current, "speed_px_s"),
            "peak_corner_speed_px_s": _sampled_peak(current, "maximum_corner_speed_px_s"),
            "peak_center_acceleration_px_s2": _sampled_peak(current, "acceleration_px_s2"),
            "peak_angular_velocity_deg_s": _sampled_peak(current, "angular_velocity_deg_s", absolute=True),
            "peak_log_scale_velocity_per_s": _sampled_peak(current, "log_scale_velocity_per_s", absolute=True),
        })
    return {
        "schema": "element-motion-audit/1", "profile_sha256": profile_digest(profile),
        "source_sha256": profile["source"]["sha256"], "elements": elements,
        "sampling": {"subsamples_per_knot_interval": subsamples,
                     "explicit_gap_markers": True, "new_observations_created": False, "peaks": "sampled"},
        "units": {"translation": "source_px/s", "normalized_translation": "image_diagonal/s",
                  "acceleration": "source_px/s^2", "rotation": "degrees/s", "scale": "log_scale/s"},
        "visual_approval": "pending", "perceptual_playback": False,
    }, rows


def _time_mapping(spec):
    points = spec.get("time_map")
    if points is None:
        return None
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("time_map requires at least two reference_time/candidate_time points")
    result = []
    for point in points:
        if not isinstance(point, dict) or set(point) != {"reference_time", "candidate_time"}:
            raise ValueError("Each time_map point requires exactly reference_time and candidate_time")
        pair = (_finite(point["reference_time"], "reference_time"),
                _finite(point["candidate_time"], "candidate_time"))
        if result and (pair[0] <= result[-1][0] or pair[1] <= result[-1][1]):
            raise ValueError("Comparison time_map must increase in both clocks")
        result.append(pair)
    return result


def _map_time(time_s, points):
    if points is None:
        return time_s, 1.0
    if time_s < points[0][0] - 1e-10 or time_s > points[-1][0] + 1e-10:
        return None, None
    index = max(0, min(len(points) - 2, bisect_right([p[0] for p in points], time_s) - 1))
    a, b = points[index], points[index + 1]
    rate = (b[1] - a[1]) / (b[0] - a[0])
    # Return exact stored endpoints. .2 + (.4-.1)*(.7/.3) can otherwise
    # exceed a valid .9 endpoint by an ulp and look like an evidence gap.
    if abs(time_s - a[0]) <= 1e-10:
        return a[1], rate
    if abs(time_s - b[0]) <= 1e-10:
        return b[1], rate
    mapped = a[1] + (time_s - a[0]) * rate
    return min(b[1], max(a[1], mapped)), rate


def _stats(rows, field, expected):
    values = [(r["reference_time_s"], r[field]) for r in rows if r[field] is not None]
    if not values:
        return {"matched_samples": 0, "reference_available_samples": expected,
                "coverage": None if not expected else 0.0,
                "rmse": None, "mean": None, "p95": None, "maximum": None, "maximum_time_s": None}
    arr = np.asarray([v for _, v in values], dtype=float)
    index = int(np.argmax(arr))
    return {"matched_samples": len(values), "reference_available_samples": expected,
            "coverage": len(values) / expected if expected else None,
            "rmse": float(np.sqrt(np.mean(arr * arr))), "mean": float(np.mean(arr)),
            "p95": float(np.quantile(arr, .95)), "maximum": float(arr[index]),
            "maximum_time_s": values[index][0]}


def compare_profiles(reference, candidate, spec=None):
    """Compare observed profiles without fitting away timing or spatial errors.

    An optional time_map explicitly maps reference seconds to candidate seconds.
    An optional spatial_map maps candidate pixels into the reference raster using
    one uniform scale and a translation. Both profiles' knots, plus explicit
    subsamples, are compared, with chain-rule correction of candidate velocities.
    This can expose an excursion between identical reference endpoints. Every
    row distinguishes observed knots from interpolation under the fitted model.
    """
    validate_profile(reference); validate_profile(candidate)
    spec = {} if spec is None else spec
    if not isinstance(spec, dict):
        raise ValueError("Comparison specification must be an object")
    if set(spec) - {"time_map", "spatial_map", "angle_offset_deg", "elements", "subsamples"}:
        raise ValueError("Unknown comparison specification fields")
    if ((reference["source"]["width"], reference["source"]["height"]) !=
            (candidate["source"]["width"], candidate["source"]["height"]) and "spatial_map" not in spec):
        raise ValueError("Different rasters require an explicit uniform spatial_map")
    mapping = _time_mapping(spec)
    subsamples = spec.get("subsamples", 4)
    if type(subsamples) is not int or not 1 <= subsamples <= 32:
        raise ValueError("subsamples must be an integer in [1,32]")
    spatial = spec.get("spatial_map", {})
    if not isinstance(spatial, dict) or set(spatial) - {"scale", "offset_px"}:
        raise ValueError("Unknown spatial_map fields")
    scale = _finite(spatial.get("scale", 1.0), "spatial scale")
    if scale <= 0:
        raise ValueError("Spatial scale must be positive")
    offset = spatial.get("offset_px", [0, 0])
    if not isinstance(offset, (list, tuple)) or len(offset) != 2:
        raise ValueError("Spatial offset requires two pixel coordinates")
    offset = np.array([_finite(v, "offset_px") for v in offset])
    angle_offset = _finite(spec.get("angle_offset_deg", 0), "angle_offset_deg")
    refs, candidates = _elements(reference), _elements(candidate)
    pairs = spec.get("elements", [{"reference": key, "candidate": key} for key in refs])
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("At least one element comparison is required")
    results = []
    fields = ("position_error_px", "corner_error_px", "angle_error_deg", "log_size_error",
              "velocity_error_px_s", "angular_velocity_error_deg_s", "log_scale_velocity_error_per_s")
    for pair in pairs:
        if (not isinstance(pair, dict) or set(pair) != {"reference", "candidate"}
                or any(not isinstance(v, str) or not v for v in pair.values())):
            raise ValueError("Element pairs require exactly reference and candidate IDs")
        rid, cid = pair["reference"], pair["candidate"]
        if rid not in refs or cid not in candidates:
            raise ValueError("Unknown reference or candidate element")
        rows, expected = [], dict.fromkeys(fields, 0)
        peak_series = {name: {"reference": [], "candidate": []}
                       for name in ("center_speed", "corner_speed", "angular_speed", "log_scale_speed")}
        r_size = refs[rid].get("reference", {}).get("size_px")
        c_size = candidates[cid].get("reference", {}).get("size_px")
        reference_knots = sample_times(reference, rid)
        times = set(reference_knots)
        inverse = None if mapping is None else [(b, a) for a, b in mapping]
        for candidate_knot in sample_times(candidate, cid):
            mapped, _ = _map_time(candidate_knot, inverse)
            if reference_knots and mapped is not None and reference_knots[0] <= mapped <= reference_knots[-1]:
                times.add(mapped)
        knots = sorted(times)
        for a, b in zip(knots, knots[1:]):
            times.update(a + (b-a)*j/subsamples for j in range(1, subsamples))
        if subsamples == 1:
            times.update(_gap_markers(knots, lambda t: evaluate_element(reference, rid, t)))
            def candidate_pose(t):
                candidate_t, _ = _map_time(t, mapping)
                return {} if candidate_t is None else evaluate_element(candidate, cid, candidate_t)
            times.update(_gap_markers(knots, candidate_pose))
        for time_s in sorted(times):
            candidate_time, clock_rate = _map_time(time_s, mapping)
            rp = evaluate_element(reference, rid, time_s)
            rk = evaluate_kinematics(reference, rid, time_s)
            cp = {} if candidate_time is None else evaluate_element(candidate, cid, candidate_time)
            ck = {} if candidate_time is None else evaluate_kinematics(candidate, cid, candidate_time)
            for origin, intensities in (("reference", _intensities(rk)),
                                        ("candidate", _intensities(ck, scale, clock_rate or 1.0))):
                for name, value in intensities.items():
                    peak_series[name][origin].append({"time_s": time_s, "value": value})
            row = {"reference_time_s": time_s, "candidate_time_s": candidate_time,
                   "reference_channel_status": rp.get("channel_status"),
                   "candidate_channel_status": cp.get("channel_status"),
                   **dict.fromkeys(fields)}
            if rp.get("position_px") is not None:
                expected["position_error_px"] += 1
                if cp.get("position_px") is not None:
                    row["position_error_px"] = float(np.linalg.norm(np.asarray(cp["position_px"]) * scale + offset - rp["position_px"]))
            if rp.get("angle_deg_unwrapped") is not None:
                expected["angle_error_deg"] += 1
                if cp.get("angle_deg_unwrapped") is not None:
                    row["angle_error_deg"] = abs(cp["angle_deg_unwrapped"] + angle_offset - rp["angle_deg_unwrapped"])
            if rp.get("scale") is not None and r_size is not None:
                expected["log_size_error"] += 1
                if cp.get("scale") is not None and c_size is not None:
                    row["log_size_error"] = abs(math.log(cp["scale"] * scale * math.hypot(*c_size) / (rp["scale"] * math.hypot(*r_size))))
            rc, cc = rk.get("corners") or [], ck.get("corners") or []
            if len(rc) == 4 and all(c.get("position_px") is not None for c in rc):
                expected["corner_error_px"] += 1
                if len(cc) == 4 and all(c.get("position_px") is not None for c in cc):
                    # An angular offset changes corresponding corner geometry;
                    # callers should align the profile, not hide it in this metric.
                    if angle_offset:
                        raise ValueError("Corner comparison requires angle_offset_deg=0")
                    delta = np.array([c["position_px"] for c in cc]) * scale + offset - np.array([c["position_px"] for c in rc])
                    row["corner_error_px"] = float(np.sqrt(np.mean(np.sum(delta * delta, axis=1))))
            for key, out, factor in (("velocity_px_s", "velocity_error_px_s", scale),
                                     ("angular_velocity_deg_s", "angular_velocity_error_deg_s", 1),
                                     ("log_scale_velocity_per_s", "log_scale_velocity_error_per_s", 1)):
                if rk.get(key) is not None:
                    expected[out] += 1
                    if ck.get(key) is not None:
                        row[out] = float(np.linalg.norm(np.asarray(ck[key]) * clock_rate * factor - rk[key]))
            rows.append(row)
        results.append({"reference_element": rid, "candidate_element": cid,
                        "metrics": {field: _stats(rows, field, expected[field]) for field in fields},
                        "peak_timing": {name: compare_peaks(series["reference"], series["candidate"])
                                        for name, series in peak_series.items()}, "samples": rows})
    return {"schema": "element-motion-comparison/1", "reference_profile_sha256": profile_digest(reference),
            "candidate_profile_sha256": profile_digest(candidate), "alignment": spec,
            "clock": "explicit_mapping_or_identity", "automatic_time_warp": False,
            "mapped_velocity_at_time_knots": "right_hand_derivative; final_knot_uses_left",
            "sampling": {"grid": "union_of_reference_and_aligned_candidate_knots",
                         "subsamples_per_interval": subsamples, "explicit_gap_markers": True,
                         "new_observations_created": False},
            "elements": results,
            "limitations": ["Error is measured only where both profiles have evidence.",
                            "Derivatives come from fitted curves, not ground-truth physical velocities.",
                            "Rows may compare interpolated poses; channel_status distinguishes these from observations.",
                            "No aggregate fidelity percentage or aesthetic approval is produced."],
            "visual_approval": "pending"}
