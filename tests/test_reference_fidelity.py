"""Real codec and strict reference-manifest regression tests."""
import shutil
import subprocess

import pytest

from visual_fidelity.reference_fidelity import audit_pair, sample_frame_indices, _clock
from visual_fidelity.reference_scene import validate_reference_scenes


def _media(path, color, duration=1):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d={duration}",
                    "-c:v", "mpeg4", "-q:v", "2", str(path)], check=True)


def test_aligned_comparison_is_evidence_not_approval(tmp_path):
    reference, clone = tmp_path/"reference.mp4", tmp_path/"clone.mp4"
    _media(reference, "blue")
    shutil.copyfile(reference, clone)
    report = audit_pair(reference, clone, tmp_path/"evidence", [0, 5, 29])
    assert len(report["samples"]) == 3
    assert all(row["mae_rgb"] == 0 and row["ssim_luma"] == 1
               and row["edge_f1_1px"] == 1 for row in report["samples"])
    assert report["user_approval"] is False
    assert report["frame_alignment"] == "exact_same_index_no_retime"
    assert (tmp_path/"evidence"/"comparison_report.json").exists()
    assert (tmp_path/"evidence"/"aligned_contact_sheet.jpg").exists()


def test_alignment_rejects_invalid_frames(tmp_path):
    a, b = tmp_path/"a.mp4", tmp_path/"b.mp4"
    _media(a, "red")
    _media(b, "blue")
    with pytest.raises(ValueError, match="unique"):
        audit_pair(a, b, tmp_path/"out", [0, 0])
    with pytest.raises(ValueError, match="outside"):
        audit_pair(a, b, tmp_path/"out", [30])
    with pytest.raises(ValueError, match="exist"):
        audit_pair(a, tmp_path/"missing.mp4", tmp_path/"out", [0])


def test_alignment_rejects_clock_mismatch(tmp_path):
    a, b = tmp_path/"a.mp4", tmp_path/"b.mp4"
    _media(a, "red")
    _media(b, "red", duration=2)
    with pytest.raises(ValueError, match="FPS, frame count"):
        audit_pair(a, b, tmp_path/"out", [0])


def _manifest():
    return {"schema": "editor-ultra-reference-scenes/1",
            "source_sha256": "f"*64, "fps": "30/1", "frame_count": 30, "scenes": [
                {"id": "sceneA", "start_frame": 0, "end_frame": 10,
                 "elements": ["letter"], "events": [
                     {"id": "reveal", "element_id": "letter", "frame": 2,
                      "action": "letter emerges", "observed": True}], "unresolved": []},
                {"id": "sceneB", "start_frame": 10, "end_frame": 30,
                 "elements": ["camera"], "events": [
                     {"id": "orbit", "element_id": "camera", "frame": 18,
                      "action": "camera orbit geometry uncertain", "observed": False}],
                 "unresolved": ["Hidden geometry unknown"]}]}


def test_manifest_tracks_unknowns_and_refuses_gaps():
    manifest = _manifest()
    report = validate_reference_scenes(manifest, source_sha256="f"*64, fps="30", frame_count=30)
    assert report["scenes"] == 2 and report["events"] == 2
    assert len(report["unresolved"]) == 2
    manifest["scenes"][1]["start_frame"] = 11
    with pytest.raises(ValueError, match="gap"):
        validate_reference_scenes(manifest, source_sha256="f"*64, fps="30", frame_count=30)


def test_manifest_requires_known_elements_and_current_source():
    manifest = _manifest()
    with pytest.raises(ValueError, match="source"):
        validate_reference_scenes(manifest, source_sha256="a"*64, fps="30", frame_count=30)
    manifest["scenes"][1]["events"][0]["element_id"] = "unbound"
    with pytest.raises(ValueError, match="known"):
        validate_reference_scenes(manifest, source_sha256="f"*64, fps="30", frame_count=30)


def test_sampling_uses_real_video_frame_clock_not_container_duration(tmp_path):
    reference = tmp_path / "reference.mp4"
    _media(reference, "blue", duration=1)
    count = _clock(reference)["frame_count"]
    selected = sample_frame_indices(count)
    assert len(selected) == 16
    assert selected[0] == 0 and selected[-1] == count - 1
    assert selected == sorted(set(selected))
    assert sample_frame_indices(1) == [0]
    assert sample_frame_indices(3) == [0, 1, 2]
    with pytest.raises(ValueError):
        sample_frame_indices(0)
    with pytest.raises(ValueError):
        sample_frame_indices(2214, max_samples=17)
