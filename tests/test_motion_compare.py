import copy

import pytest

from visual_fidelity.motion_compare import audit_profile, compare_profiles
from visual_fidelity.motion_profile import fit_profile
from visual_fidelity.motion_qa import audit


def observations(scales, positions=None, pts=None, missing=()):
    pts = list(range(len(scales))) if pts is None else pts
    return {
        "schema": "element-motion-observations/1",
        "source": {"sha256": "a" * 64, "width": 200, "height": 300,
                   "time_base": "1/10", "first_pts": 0,
                   "coordinate_convention": "opencv_pixel_centers", "rotation_ccw_applied": 0},
        "elements": [{"id": "panel", "model": "similarity_2d",
                      "reference": {"size_px": [40, 60], "anchor": "center"},
                      "samples": [{"frame": i, "pts": pts[i], "segment": "one",
                                   "position_px": None if i in missing else ([100, 150] if positions is None else positions[i]),
                                   "scale": None if i in missing else value,
                                   "angle_deg_unwrapped": None if i in missing else 0,
                                   "confidence": None, "visibility": "unknown" if i in missing else "visible",
                                   "status": "missing" if i in missing else "observed"}
                                  for i, value in enumerate(scales)]}],
    }


def test_centered_zoom_audit_and_legacy_entry_point_report_geometry_not_only_center():
    data = observations([1, 1.2, 1.6, 2])
    profile = fit_profile(data)
    report, rows = audit_profile(profile)
    legacy_report, _ = audit(data)
    element = report["elements"][0]
    assert element["peak_center_speed_px_s"]["value"] == pytest.approx(0)
    assert element["peak_corner_speed_px_s"]["value"] > 100
    assert element["peak_log_scale_velocity_per_s"]["value"] > 0
    assert report["visual_approval"] == "pending"
    assert legacy_report["schema"] == report["schema"]
    assert len(rows) > len(data["elements"][0]["samples"])


def test_centered_zoom_mismatch_is_visible_despite_identical_centers():
    ref = fit_profile(observations([1, 1.2, 1.6, 2]))
    cand = fit_profile(observations([1, 1, 1, 1]))
    result = compare_profiles(ref, cand)
    metrics = result["elements"][0]["metrics"]
    assert metrics["position_error_px"]["maximum"] == 0
    assert metrics["corner_error_px"]["maximum"] > 30
    assert metrics["log_size_error"]["maximum"] > .6
    assert metrics["log_scale_velocity_error_per_s"]["maximum"] > 0
    assert result["automatic_time_warp"] is False


def test_same_endpoints_with_different_easing_do_not_compare_as_equivalent():
    ref = fit_profile(observations([1] * 4, [[20, 30], [25, 30], [80, 30], [100, 30]]))
    cand = fit_profile(observations([1] * 4, [[20, 30], [45, 30], [70, 30], [100, 30]]))
    metrics = compare_profiles(ref, cand)["elements"][0]["metrics"]
    assert metrics["position_error_px"]["maximum"] >= 20
    assert metrics["velocity_error_px_s"]["maximum"] > 10


def test_missing_candidate_evidence_reduces_coverage_instead_of_scoring_zero():
    ref = fit_profile(observations([1, 1.2, 1.4, 1.6, 1.8]))
    cand = fit_profile(observations([1, 1.2, 1.4, 1.6, 1.8], missing=(2,)))
    metrics = compare_profiles(ref, cand, {"subsamples": 1})["elements"][0]["metrics"]
    assert metrics["position_error_px"]["coverage"] == pytest.approx(.8)
    assert metrics["position_error_px"]["matched_samples"] == 4
    assert metrics["position_error_px"]["reference_available_samples"] == 5


def test_explicit_double_duration_uses_chain_rule_for_velocity():
    ref = fit_profile(observations([1, 1.2, 1.4], [[20, 30], [30, 30], [40, 30]], [0, 1, 2]))
    cand = fit_profile(observations([1, 1.2, 1.4], [[20, 30], [30, 30], [40, 30]], [0, 2, 4]))
    mapping = {"time_map": [{"reference_time": 0, "candidate_time": 0},
                            {"reference_time": .2, "candidate_time": .4}]}
    metrics = compare_profiles(ref, cand, mapping)["elements"][0]["metrics"]
    assert metrics["position_error_px"]["maximum"] == pytest.approx(0, abs=1e-9)
    assert metrics["velocity_error_px_s"]["maximum"] == pytest.approx(0, abs=1e-9)
    assert metrics["log_scale_velocity_error_per_s"]["maximum"] == pytest.approx(0, abs=1e-9)


def test_different_rasters_cannot_silently_share_pixel_metrics():
    ref = fit_profile(observations([1, 1]))
    data = observations([1, 1])
    data["source"]["width"] = 400
    cand = fit_profile(data)
    with pytest.raises(ValueError, match="rasters"):
        compare_profiles(ref, cand)
    assert compare_profiles(ref, cand, {"spatial_map": {"scale": 1, "offset_px": [0, 0]}})


def test_unknown_element_and_bad_time_map_fail():
    p = fit_profile(observations([1, 1]))
    with pytest.raises(ValueError, match="Unknown"):
        compare_profiles(p, p, {"elements": [{"reference": "panel", "candidate": "missing"}]})
    with pytest.raises(ValueError, match="increase"):
        compare_profiles(p, p, {"time_map": [{"reference_time": 0, "candidate_time": 1},
                                            {"reference_time": 1, "candidate_time": 0}]})


def test_compare_validates_serialized_coefficients_before_evaluation():
    p = fit_profile(observations([1, 1.3, 1.6]))
    changed = copy.deepcopy(p)
    changed["fit"]["method"] = "unknown"
    with pytest.raises(ValueError):
        compare_profiles(p, changed)


def test_candidate_excursion_between_identical_reference_endpoints_is_detected():
    ref = fit_profile(observations([1, 1], [[100, 150], [100, 150]], [0, 4]))
    cand = fit_profile(observations([1] * 5, [[100, 150], [100, 150], [180, 150], [100, 150], [100, 150]]))
    metrics = compare_profiles(ref, cand)["elements"][0]["metrics"]
    assert metrics["position_error_px"]["maximum"] >= 80
    assert metrics["velocity_error_px_s"]["maximum"] > 0


def test_time_map_roundoff_does_not_turn_final_endpoint_into_a_gap():
    ref = fit_profile(observations([1, 1], pts=[1, 4]))
    cand = fit_profile(observations([1, 1], pts=[2, 9]))
    result = compare_profiles(ref, cand, {"time_map": [
        {"reference_time": .1, "candidate_time": .2},
        {"reference_time": .4, "candidate_time": .9}]})
    assert result["elements"][0]["metrics"]["position_error_px"]["coverage"] == 1
    assert result["elements"][0]["samples"][-1]["candidate_time_s"] == .9


@pytest.mark.parametrize("spec", [
    {"spatial_map": {"sacle": 2}},
    {"spatial_map": []},
    {"time_map": [{"reference_time": 0, "candidate_time": 0, "typo": 1},
                  {"reference_time": 1, "candidate_time": 1}]},
    {"elements": [{"reference": "panel", "candidate": "panel", "ignored": 1}]},
])
def test_comparison_nested_typos_fail_instead_of_changing_alignment(spec):
    p = fit_profile(observations([1, 1]))
    with pytest.raises(ValueError):
        compare_profiles(p, p, spec)


def test_peak_at_a_cut_boundary_remains_incomplete_with_knots_only_sampling():
    data = observations([1] * 6, [[0, 30], [1, 30], [10, 30], [50, 30], [51, 30], [52, 30]])
    for sample in data["elements"][0]["samples"][3:]:
        sample["segment"] = "after-cut"
    profile = fit_profile(data)
    report, rows = audit_profile(profile, subsamples=1)
    assert report["elements"][0]["peak_center_speed_px_s"]["classification"] == "boundary"
    assert any(row["speed_px_s"] is None for row in rows)
    comparison = compare_profiles(profile, profile, {"subsamples": 1})
    assert comparison["elements"][0]["peak_timing"]["center_speed"]["status"] == "boundary"
