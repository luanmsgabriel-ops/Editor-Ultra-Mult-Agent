"""Video-real cadence checks: exact clock, moving vs still, bounded windows."""
from pathlib import Path
import subprocess
import pytest

from visual_fidelity.reference_temporal_qa import (
    measure_reference_cadence_gap, validate_windows, window_around_seconds)
from visual_fidelity.reference_fidelity import _clock

def video(path: Path, source: str):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i", source,
                    "-t", "1", "-r", "30", "-c:v", "mpeg4", "-q:v", "2", str(path)], check=True)

def test_matching_video_has_zero_motion_gap(tmp_path):
    original, copy = tmp_path/"original.mp4", tmp_path/"copy.mp4"
    video(original, "testsrc=size=320x180:rate=30")
    copy.write_bytes(original.read_bytes())
    report = measure_reference_cadence_gap(original, copy, tmp_path/"evidence", ranges=[[0, 14], [14, 30]])
    assert report["sample_count"] == 28
    assert report["metrics"]["mean_change_gap"] == 0
    assert report["metrics"]["mean_flow_gap_smallpx_per_frame"] == 0
    assert report["user_approved"] is False
    assert (tmp_path/"evidence"/"temporal_frames.csv").is_file()

def test_motion_vs_static_yields_identifiable_gaps(tmp_path):
    original, still = tmp_path/"moving.mp4", tmp_path/"static.mp4"
    video(original, "testsrc=size=320x180:rate=30")
    video(still, "color=c=black:size=320x180:rate=30")
    report = measure_reference_cadence_gap(original, still, tmp_path/"evidence", ranges=[[0, 30]])
    assert report["metrics"]["mean_change_gap"] > 0
    assert report["metrics"]["mean_flow_gap_smallpx_per_frame"] > 0

def test_source_clock_drives_window_not_duration_guess(tmp_path):
    original = tmp_path/"original.mp4"
    video(original, "testsrc=size=320x180:rate=30")
    clock = _clock(original)
    assert window_around_seconds(clock, .5) == [[0, 30]]
    assert window_around_seconds(clock, .99) == [[0, 30]]
    with pytest.raises(ValueError): window_around_seconds(clock, 1.01)
    with pytest.raises(ValueError): validate_windows([[0, 12], [11, 20]], clock["frame_count"])
    with pytest.raises(ValueError): validate_windows([[0, 241]], 500)
