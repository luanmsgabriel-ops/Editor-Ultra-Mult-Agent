"""Real source-clock native overlay motion: FFmpeg pixels and producer receipts.

Synthetic tests verify technical binding and fail-closed contracts only.
They do not certify a human clone, 3D motion or perceptual fidelity.
"""
from pathlib import Path
import json
import shutil
import subprocess
import numpy as np
from PIL import Image
import cv2
import pytest

from editorial_engine import project as project_engine
from editorial_engine.contracts import ValidationError, file_sha256
from editor_ultra_app.engine import EngineAdapter
from visual_fidelity.native_motion import apply_measured_screen_quads


AUTHOR = {"kind": "human", "actor": "Native motion QA", "method": "Authored synthetic media fixture"}


@pytest.fixture
def motion_project(tmp_path):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("FFmpeg required for actual pixel proof")
    rng = np.random.default_rng(551)
    patch = np.repeat(rng.integers(20, 240, (36, 48), dtype=np.uint8)[:, :, None], 3, axis=2)
    frames = []
    for i in range(10):
        frame = np.full((90, 160, 3), 12, dtype=np.uint8)
        frame[26:62, 30+i:78+i] = patch
        frames.append(frame)
    reference = tmp_path / "reference.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "rawvideo",
        "-pix_fmt", "rgb24", "-s", "160x90", "-r", "10", "-i", "pipe:0",
        "-an", "-c:v", "libx264", "-crf", "12", "-threads", "1",
        "-pix_fmt", "yuv420p", str(reference)
    ], input=np.stack(frames).tobytes(), capture_output=True, check=True, timeout=30)
    base = tmp_path / "new-base.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=10:d=1",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base)
    ], capture_output=True, check=True, timeout=30)
    layer = tmp_path / "panel.png"
    artwork = Image.new("RGBA", (40, 40))
    artwork.paste((0, 235, 25, 255), (2, 2, 38, 38))
    artwork.save(layer)
    adapter = EngineAdapter(tmp_path / "private")
    current = adapter.save_project(None, {"objective": "Measured native screen artwork reconstruction"})
    pid = current["project_id"]

    def add(role, file, mime):
        nonlocal current
        current = adapter.import_local_file(pid, role, file, file.name, mime,
                                            expected_revision=current["revision"])
        return current["asset"]

    ref = add("ref", reference, "video/mp4")
    footage = add("footage", base, "video/mp4")
    request = adapter.request_clone_images(pid, [{
        "id": "panel", "scene_id": "opening", "frames": [0, 10],
        "reference_frame": 4, "placement": "screen",
        "description": "Independent isolated bright green panel in clean transparent margins",
        "reason": "Keep independent pixels and move the screen element with measured source motion",
    }], expected_revision=current["revision"])
    current = request
    art = add("clone_resource", layer, "image/png")
    protection = tmp_path / "protection.json"
    protection.write_text(json.dumps({
        "clock": "source", "source_sha256": footage["sha256"],
        "fps": "10/1", "frame_count": 10,
        "provenance": AUTHOR, "frames": {str(n): [] for n in range(10)},
    }))
    safeguard = add("clone_resource", protection, "application/json")

    prepared = adapter.prepare(pid, "clone", expected_revision=current["revision"],
                               reconstruction={"base_asset_id": footage["id"],
                                               "images": {"panel": art["id"]},
                                               "protection_asset_id": safeguard["id"]})
    stage = adapter._load(pid)["engines"]["clone"]
    analysis = project_engine.artifact(stage["directory"], "analysis:" + footage["id"])
    from test_clone_resources import direction_for
    direction = direction_for(analysis, {"start_s": 0., "end_s": 1.},
                              "panel", "native.overlay")
    # The generic helper authors a spatial_relation, while screen overlay
    # supports a visualization/reveal function. Keep editorial eligibility real.
    for event in direction["event_annotations"]:
        for opportunity in event["opportunities"]:
            opportunity["function"] = "visualize_concept"
    directed = adapter.apply_direction(pid, "clone", direction,
                                       expected_revision=prepared["revision"])
    stage = adapter._load(pid)["engines"]["clone"]
    bundle = project_engine.artifact(stage["directory"], "edit_bundle")
    choices = [d for d in bundle["plan"]["decisions"]
               if d.get("operation") and d["operation"]["operation"] == "overlay"]
    assert len(choices) == 1

    measured = adapter.measure_motion(pid, ref["id"], {
        "schema": "element-motion-measurement/1",
        "elements": [{
            "id": "panel", "range": [0, 10], "seed_frame": 0,
            "roi_px": [30, 26, 48, 36],
        }]
    }, expected_revision=directed["revision"])
    return adapter, measured, choices[0]["id"], ref, footage


def motion_request(current, decision_id):
    return {
        "schema": "editor-ultra-native-measured-motion/1",
        "measurement_id": current["motion_measurement"]["id"],
        "decision_id": decision_id, "element_id": "panel",
        "channels": ["position", "scale", "angle"],
        "pivot_px": [80.0, 45.0], "base_scale": 0.24,
        "time_map": [{"output_time": 0.0, "source_time": 0.0},
                     {"output_time": 0.9, "source_time": 0.9}],
    }


def green_centers(path):
    cap = cv2.VideoCapture(str(path))
    centers = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        green = (frame[:, :, 1] > 115) & (frame[:, :, 2] < 90)
        ys, xs = np.where(green)
        assert len(xs) > 10
        centers.append(float(xs.mean()))
    cap.release()
    return centers


def test_native_overlay_reuses_measured_curves_on_actual_encoded_pixels(motion_project):
    adapter, state, decision_id, ref, footage = motion_project
    pid = state["project_id"]
    rendered = adapter.render(pid, "clone", expected_revision=state["revision"],
                              native_motion=motion_request(state, decision_id))
    assert rendered["preview_kind"] == "reconstruction"
    assert rendered["status"] == "rendered_unreviewed"
    assert rendered["approval"]["clone"] is None
    receipt = rendered["result"]["measured_motion"]
    assert receipt["schema"] == "element-motion-consumption/1"
    assert len(receipt["bindings"]) == 1
    use = receipt["bindings"][0]
    assert use["target"] == "native:" + decision_id
    assert use["frames"] == list(range(10))
    assert use["frame_count"] == 10
    assert use["profile_sha256"] == state["motion_measurement"]["profile_sha256"]
    path = adapter.resolve_asset(pid, rendered["asset_id"])
    assert rendered["asset"]["sha256"] == file_sha256(path)
    assert rendered["asset"]["sha256"] != ref["sha256"]
    assert rendered["result"]["source_sha256"] == footage["sha256"]
    positions = green_centers(path)
    assert len(positions) == 10
    assert positions[-1] - positions[0] == pytest.approx(9, abs=3.5)
    assert rendered["engine"]["clone"]["native_motion"]["render_sha256"] == file_sha256(path)
    assert rendered["engine"]["clone"]["native_motion"]["user_approved"] is False


def test_missing_decision_and_profile_range_fail_closed_before_encoding(motion_project):
    adapter, state, decision_id, *_ = motion_project
    pid = state["project_id"]
    bad = motion_request(state, "unknown-effect")
    with pytest.raises((ValidationError, ValueError), match="decision"):
        adapter.render(pid, "clone", expected_revision=state["revision"], native_motion=bad)
    future = motion_request(state, decision_id)
    future["time_map"][1]["source_time"] = 12.0
    with pytest.raises((ValidationError, ValueError)):
        adapter.render(pid, "clone", expected_revision=state["revision"], native_motion=future)
    assert adapter.get_project(pid)["engine"]["clone"]["native_motion"] is None


def test_native_quads_reject_outside_raster_without_encoder(motion_project):
    adapter, state, decision_id, *_ = motion_project
    pid = state["project_id"]
    profile_id = state["motion_measurement"]["artifacts"]["profile"]["asset_id"]
    profile_path = adapter.resolve_asset(pid, profile_id)
    profile = json.loads(profile_path.read_text())
    from visual_fidelity.motion_profile import profile_digest
    binding = {
        "schema": "element-motion-binding/1",
        "profile": profile, "profile_sha256": profile_digest(profile),
        "stage": "masked_canvas", "element_id": "panel",
        "channels": ["position"], "pivot_px": [80, 45], "base_scale": 1,
        "time_map": [{"output_time": 0, "source_time": 0},
                     {"output_time": 0.9, "source_time": 0.9}],
    }
    corners = {i: np.array([[0., 0.], [1., 0.], [1., 1.], [0., 1.]])
               for i in range(10)}
    with pytest.raises(ValueError, match="outside|leaves output raster"):
        apply_measured_screen_quads(corners, binding, resolution=(160, 90), fps=10)
