import json

import pytest

from visual_fidelity.motion_profile_cli import main
from visual_fidelity.motion_qa import main as legacy_main


def test_bind_render_cannot_overwrite_manifest_with_report_sidecar(tmp_path):
    source = tmp_path / "source.json"
    source.write_text('{"original":true}')
    destination = tmp_path / "bound.json"
    with pytest.raises(SystemExit) as error:
        main(["bind", str(source), str(tmp_path / "profile.json"), str(tmp_path / "bindings.json"),
              str(destination), "--render", str(tmp_path / "bound.mp4")])
    assert error.value.code == 2
    assert source.read_text() == '{"original":true}'
    assert not destination.exists()


def test_legacy_qa_writes_empty_csv_for_all_missing_evidence(tmp_path):
    data = {
        "schema": "element-motion-observations/1",
        "source": {"sha256": "a" * 64, "width": 200, "height": 300,
                   "time_base": "1/30", "first_pts": 0,
                   "coordinate_convention": "opencv_pixel_centers", "rotation_ccw_applied": 0},
        "elements": [{"id": "panel", "model": "similarity_2d", "reference": {},
                      "samples": [{"frame": 0, "pts": 0, "segment": "a", "position_px": None,
                                   "scale": None, "angle_deg_unwrapped": None, "status": "missing",
                                   "visibility": "unknown", "confidence": None}]}],
    }
    source, report, csv = [tmp_path / name for name in ("obs.json", "qa.json", "qa.csv")]
    source.write_text(json.dumps(data))
    assert legacy_main([str(source), "--output", str(report), "--csv", str(csv)]) == 0
    result = json.loads(report.read_text())
    assert result["elements"][0]["sample_count"] == 0
    assert result["elements"][0]["peak_center_speed_px_s"]["classification"] == "unavailable"
    assert csv.read_text() == ""
