"""Classify sampled motion peaks without assigning an invented time to a plateau.

Inputs are nonnegative intensities evaluated on the comparison clock already:
absolute angular/log-scale rates, center speeds or corner speeds, for example.
This module does not align clocks, resample, bridge None values, or interpolate a
peak time.  Irregular time spacing is valid; an omitted row alone is not evidence
of a gap.  Missing support must be represented explicitly by ``value=None``.
"""

from __future__ import annotations

import math


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def classify_peak(samples, *, relative_tolerance=.01, absolute_tolerance=1e-8):
    """Describe maxima within a declared tolerance of the available sampled peak.

    ``unique_interior`` needs a single near-maximum sample with valid, lower
    immediate neighbors.  Consecutive near-maximal samples form a ``plateau``.
    Either shape becomes ``boundary`` if its support meets a series edge or None.
    Disjoint near-maximum runs are ``ambiguous``; none is chosen automatically.
    Values at or below absolute_tolerance are ``no_motion``.

    The peak bracket describes the neighboring sample times, not a statistical
    confidence interval.  Classification concerns available samples only; gaps
    elsewhere may still contain unseen peaks.
    """
    relative = _finite(relative_tolerance, "relative_tolerance")
    absolute = _finite(absolute_tolerance, "absolute_tolerance")
    if not 0 <= relative < 1 or absolute < 0:
        raise ValueError("relative_tolerance must be in [0,1), absolute_tolerance must be >=0")
    if not isinstance(samples, list):
        raise ValueError("samples must be a list")
    rows = []
    for sample in samples:
        if not isinstance(sample, dict) or "time_s" not in sample or "value" not in sample:
            raise ValueError("Each sample needs time_s and value")
        time_s = _finite(sample["time_s"], "time_s")
        value = None if sample["value"] is None else _finite(sample["value"], "value")
        if value is not None and value < 0:
            raise ValueError("Peak intensities must be nonnegative")
        if rows and time_s <= rows[-1][0]:
            raise ValueError("Sample times must strictly increase")
        rows.append((time_s, value))
    available = [value for _, value in rows if value is not None]
    maximum = max(available) if available else None
    effective = max(absolute, maximum * relative) if maximum is not None else None
    result = {
        "classification": "unavailable",
        "maximum_value": maximum,
        "peak_time_s": None,
        "peak_time_bracket_s": None,
        "peak_intervals_s": [],
        "candidates": [],
        "tolerance": {"relative": relative, "absolute": absolute, "effective": effective},
        "support": {"sample_count": len(rows), "valid_sample_count": len(available),
                    "missing_sample_count": len(rows) - len(available),
                    "time_interval_s": [rows[0][0], rows[-1][0]] if rows else None},
        "sampling": "sampled_maxima; no_peak_time_interpolation",
    }
    if maximum is None:
        return result
    if maximum <= absolute:
        result["classification"] = "no_motion"
        return result

    threshold = maximum - effective
    runs = []
    run = []
    for index, (_, value) in enumerate(rows):
        if value is not None and value >= threshold:
            run.append(index)
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)

    for run in runs:
        first, last = run[0], run[-1]
        boundary_reasons = []
        if first == 0:
            boundary_reasons.append("series_start")
        elif rows[first - 1][1] is None:
            boundary_reasons.append("gap_before")
        if last == len(rows) - 1:
            boundary_reasons.append("series_end")
        elif rows[last + 1][1] is None:
            boundary_reasons.append("gap_after")
        left = rows[first - 1][0] if first > 0 and rows[first - 1][1] is not None else None
        right = rows[last + 1][0] if last + 1 < len(rows) and rows[last + 1][1] is not None else None
        interval = [rows[first][0], rows[last][0]]
        result["peak_intervals_s"].append(interval)
        result["candidates"].append({
            "interval_s": interval, "sample_count": len(run),
            "shape": "single_sample" if len(run) == 1 else "plateau",
            "neighbor_bracket_s": [left, right],
            "bounded_by_valid_lower_neighbors": not boundary_reasons,
            "boundary_reasons": boundary_reasons,
        })
    if len(runs) != 1:
        result["classification"] = "ambiguous"
    elif result["candidates"][0]["boundary_reasons"]:
        result["classification"] = "boundary"
    elif len(runs[0]) > 1:
        result["classification"] = "plateau"
    else:
        result["classification"] = "unique_interior"
        result["peak_time_s"] = rows[runs[0][0]][0]
        result["peak_time_bracket_s"] = result["candidates"][0]["neighbor_bracket_s"]
    return result


def compare_peaks(reference_samples, candidate_samples, **kwargs):
    """Compare already aligned sampled peaks; candidate minus reference is signed.

    A scalar timing error exists only for two unique interior sampled peaks.
    A single bounded plateau can be compared as an interval, including against a
    unique peak.  Interval separation is zero when their peak windows overlap;
    it does not assert that their exact peak times are equal.  Unbounded or
    ambiguous peaks do not receive a timing score.
    """
    reference = classify_peak(reference_samples, **kwargs)
    candidate = classify_peak(candidate_samples, **kwargs)
    kinds = {reference["classification"], candidate["classification"]}
    result = {
        "status": "unavailable", "reference": reference, "candidate": candidate,
        "peak_time_error_s": None, "absolute_peak_time_error_s": None,
        "minimum_interval_separation_s": None, "possible_peak_time_error_interval_s": None,
        "timing_basis": "sampled_peaks_on_supplied_clock; no_alignment_or_extrapolation",
    }
    for unavailable in ("unavailable", "no_motion", "ambiguous", "boundary"):
        if unavailable in kinds:
            result["status"] = unavailable
            if unavailable == "no_motion":
                result["motion_mismatch"] = len(kinds) > 1
            return result

    r_start, r_end = reference["peak_intervals_s"][0]
    c_start, c_end = candidate["peak_intervals_s"][0]
    lag_interval = [_finite(c_start - r_end, "peak lag"), _finite(c_end - r_start, "peak lag")]
    result["possible_peak_time_error_interval_s"] = lag_interval
    result["minimum_interval_separation_s"] = max(0., lag_interval[0], -lag_interval[1])
    if kinds == {"unique_interior"}:
        lag = _finite(candidate["peak_time_s"] - reference["peak_time_s"], "peak time error")
        result["status"] = "unique_peaks"
        result["peak_time_error_s"] = lag
        result["absolute_peak_time_error_s"] = abs(lag)
    else:
        result["status"] = "peak_intervals"
    return result
