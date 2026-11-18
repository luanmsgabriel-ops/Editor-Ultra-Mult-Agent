"""Real, credit-free proof that measured 2D curves reach encoded output pixels.

This is NOT a perceptual-approval or identity/gesture-cloning test.
"""
import json
from pathlib import Path
import shutil
import subprocess

import cv2
import numpy as np
from PIL import Image
import pytest

from editorial_engine.contracts import ValidationError, file_sha256
from editor_ultra_app.engine import EngineAdapter


@pytest.fixture
def prepared(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required")
    adapter = EngineAdapter(tmp_path / "private")
    current = adapter.save_project(None, {"objective": "Proof of existing 2D motion curves"})
    pid = current["project_id"]
    rng = np.random.default_rng(4201)
    texture = np.repeat(rng.integers(35, 235, (48, 56), dtype=np.uint8)[:, :, None], 3, axis=2)
    reference_frames = []
    for index in range(20):
        frame = np.full((96, 128, 3), 12, np.uint8)
        frame[20:68, 20 + index:76 + index] = texture
        reference_frames.append(frame)
    base_frames = [np.full((96, 128, 3), 8, np.uint8) for _ in range(20)]

    def video(frames, name):
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "128x96",
                        "-r", "10", "-i", "pipe:0", "-an", "-c:v", "libx264",
                        "-crf", "12", "-threads", "1", "-pix_fmt", "yuv420p", str(path)],
                       input=np.stack(frames).tobytes(), capture_output=True, check=True, timeout=30)
        return path

    reference, target = video(reference_frames, "reference.mp4"), video(base_frames, "target.mp4")
    overlay = np.zeros((96, 128, 3), dtype=np.uint8)
    overlay[20:68, 20:76] = (45, 225, 245)
    matte = np.zeros((96, 128), dtype=np.uint8)
    matte[20:68, 20:76] = 255
    overlay_path, matte_path = tmp_path / "overlay.png", tmp_path / "matte.png"
    Image.fromarray(overlay).save(overlay_path)
    Image.fromarray(matte).save(matte_path)
    incoming = {}
    for name, role, path, mime in [
        ("ref", "ref", reference, "video/mp4"),
        ("base", "footage", target, "video/mp4"),
        ("overlay", "identity", overlay_path, "image/png"),
        ("matte", "identity", matte_path, "image/png"),
    ]:
        current = adapter.import_local_file(pid, role, path, path.name, mime,
                                            expected_revision=current["revision"])
        incoming[name] = current["asset_id"]
    return adapter, current, incoming, tmp_path


def measured(prepared):
    adapter, current, ids, _ = prepared
    return adapter.measure_motion(current["project_id"], ids["ref"], {
        "schema": "element-motion-measurement/1",
        "elements": [{"id": "panel", "range": [0, 20], "seed_frame": 0,
                      "roi_px": [20, 20, 56, 48]}],
    }, expected_revision=current["revision"])


def application(receipt, ids):
    return {
        "schema": "editor-ultra-measured-motion-application/1",
        "measurement_id": receipt["id"],
        "base_asset_id": ids["base"],
        "overlay_asset_id": ids["overlay"],
        "matte_asset_id": ids["matte"],
        "element_id": "panel",
        "channels": ["position", "scale", "angle"],
        "frame_count": 10,
        "pivot_px": [48.0, 44.0], "base_scale": 1.0,
        "time_map": [{"output_time": 0.0, "source_time": 0.0},
                     {"output_time": 0.9, "source_time": 0.9}],
    }


def test_measured_profile_is_actually_consumed_in_real_encoded_mp4(prepared):
    adapter, current, ids, tmp_path = prepared
    current = measured(prepared)
    measure = current["motion_measurement"]
    rendered = adapter.apply_measured_motion(current["project_id"], application(measure, ids),
                                              expected_revision=current["revision"])
    proof = rendered["motion_application"]
    assert proof["status"] == "rendered_unreviewed"
    assert proof["consumption"]["target"] == "foreground"
    assert proof["consumption"]["frames"] == list(range(10))
    assert proof["consumption"]["frame_count"] == 10
    assert proof["measurement_profile_sha256"] == measure["profile_sha256"]
    assert proof["user_approved"] is False and proof["perceptual_review"] == "pending"
    assert rendered["state"]["cloneApproval"] is None
    assert rendered["state"]["finalApproval"] is None
    movie = adapter.resolve_asset(current["project_id"], rendered["asset_id"])
    assert file_sha256(movie) == proof["render_sha256"]
    sidecar = json.loads(adapter.resolve_asset(current["project_id"],
                        proof["artifacts"]["sidecar"]["asset_id"]).read_text())
    assert sidecar["element_motion"]["bindings"][0]["frame_count"] == 10
    assert sidecar["approval"] == "pending"
    cap = cv2.VideoCapture(str(movie))
    centers = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        pixels = (frame[:, :, 1] > 160) & (frame[:, :, 2] < 140)
        ys, xs = np.where(pixels)
        assert len(xs) > 1300
        centers.append(float(xs.mean()))
    cap.release()
    assert len(centers) == 10
    assert centers[-1] - centers[0] == pytest.approx(9, abs=2.2)
    assert str(adapter.data_dir) not in json.dumps(rendered["motion_application"])
    # New content comes from the differently coloured overlay, not reference frames.
    assert rendered["motion_application"]["source"]["sha256"] == file_sha256(tmp_path / "reference.mp4")


def test_missing_curve_coverage_and_wrong_reference_role_fail_before_render(prepared):
    adapter, _, ids, _ = prepared
    current = measured(prepared)
    spec = application(current["motion_measurement"], ids)
    pid, revision = current["project_id"], current["revision"]
    with pytest.raises((ValidationError, ValueError)):
        adapter.apply_measured_motion(pid, {**spec, "base_asset_id": ids["ref"]},
                                      expected_revision=revision)
    outside = {**spec, "time_map": [{"output_time": 0.0, "source_time": 0.0},
                                    {"output_time": 0.9, "source_time": 10.0}]}
    with pytest.raises((ValidationError, ValueError)):
        adapter.apply_measured_motion(pid, outside, expected_revision=revision)
    assert adapter.get_project(pid)["motion_applications"] == []


def test_stale_revision_never_applies_old_profile(prepared):
    adapter, _, ids, _ = prepared
    current = measured(prepared)
    spec = application(current["motion_measurement"], ids)
    changed = adapter.save_project(current["project_id"], {"objective": "Changed intent"},
                                   expected_revision=current["revision"])
    with pytest.raises((ValidationError, ValueError)):
        adapter.apply_measured_motion(changed["project_id"], spec,
                                      expected_revision=changed["revision"])
    assert adapter.get_project(changed["project_id"])["motion_applications"] == []
