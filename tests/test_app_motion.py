"""Real CPU motion measurement through the private adapter and MCP job queue.

The two-second clip is deterministic synthetic evidence. Passing these tests
does not approve the aesthetics of a clone or authorize applying its movement.
"""
from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np
from PIL import Image
import pytest
from starlette.testclient import TestClient

from editorial_engine.contracts import ValidationError, file_sha256
from editor_ultra_app.engine import EngineAdapter
from editor_ultra_app.server import create_app
from scripts.check_app_connection import authorize_owner
from visual_fidelity.motion_profile import profile_digest


BASE = "https://editor.example"
KEY = "test-only-motion-owner-key-012345678901234567890"


@pytest.fixture(scope="module")
def motion_video(tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real FFmpeg and FFprobe are required")
    path = tmp_path_factory.mktemp("motion-source") / "translated-patch.mp4"
    rng = np.random.default_rng(4201)
    patch = rng.integers(35, 235, (48, 56), dtype=np.uint8)
    texture = np.repeat(patch[:, :, None], 3, axis=2)
    frames = []
    for index in range(20):
        frame = np.full((96, 128, 3), 12, np.uint8)
        frame[20:68, 20 + index:76 + index] = texture
        frames.append(frame)
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "128x96", "-r", "10", "-i", "pipe:0", "-an", "-c:v", "libx264",
        "-crf", "12", "-threads", "1", "-pix_fmt", "yuv420p", str(path),
    ], input=np.stack(frames).tobytes(), capture_output=True, check=True, timeout=30)
    return path


@pytest.fixture
def adapter(tmp_path):
    return EngineAdapter(tmp_path / "private")


def create(adapter):
    return adapter.save_project(None, {
        "name": "Medição técnica sintética",
        "objective": "Measure known synthetic translation; no aesthetic approval.",
    }, 0)


def upload(adapter, current, role, path, mime="video/mp4"):
    return adapter.import_local_file(current["project_id"], role, path, path.name, mime,
                                     expected_revision=current["revision"])


def source_project(adapter, video):
    return upload(adapter, create(adapter), "ref", video)


def specification():
    return {
        "schema": "element-motion-measurement/1",
        "elements": [{"id": "panel", "range": [0, 20], "seed_frame": 0,
                      "roi_px": [20, 20, 56, 48]}],
    }


def measure(adapter, current, spec=None, asset_id=None):
    return adapter.measure_motion(current["project_id"], asset_id or current["asset_id"],
                                   specification() if spec is None else spec,
                                   expected_revision=current["revision"])


def read_artifact(adapter, pid, measurement, name):
    item = measurement["artifacts"][name]
    path = adapter.resolve_asset(pid, item["asset_id"])
    assert file_sha256(path) == item["sha256"]
    return path


def test_real_measurement_exports_bound_observations_curves_qa_and_csv(adapter, motion_video):
    current = source_project(adapter, motion_video)
    completed = measure(adapter, current)
    receipt = completed["motion_measurement"]
    assert receipt["source"]["asset_id"] == current["asset_id"]
    assert receipt["source"]["sha256"] == file_sha256(motion_video)
    assert receipt["input_revision"] == current["revision"]
    assert receipt["project_revision"] == completed["revision"] == current["revision"] + 1
    assert receipt["scope"] == "evidence_not_applied"
    assert receipt["render_status"] == "pending_not_applied"
    assert receipt["visual_approval"] == "pending" and receipt["user_approved"] is False
    assert {"observations", "profile", "qa", "csv"} <= set(receipt["artifacts"])
    assert completed["state"]["cloneApproval"] is None
    assert completed["state"]["finalApproval"] is None
    assert completed["video_generation_policy"]["automatic_video_generation"] is False

    pid = current["project_id"]
    observations = json.loads(read_artifact(adapter, pid, receipt, "observations").read_text())
    profile = json.loads(read_artifact(adapter, pid, receipt, "profile").read_text())
    qa = json.loads(read_artifact(adapter, pid, receipt, "qa").read_text())
    assert observations["schema"] == "element-motion-observations/1"
    assert profile["schema"] == "element-motion-curves/1"
    assert qa["schema"] == "element-motion-audit/1"
    assert observations["source"]["sha256"] == profile["source"]["sha256"] == qa["source_sha256"] == file_sha256(motion_video)
    assert receipt["profile_sha256"] == profile_digest(profile) == qa["profile_sha256"]
    assert observations["measurement"]["model_inference"] is False
    samples = observations["elements"][0]["samples"]
    tracked = [row for row in samples if row["status"] == "observed"]
    assert len(samples) == 20 and len(tracked) >= 18
    assert tracked[-1]["position_px"][0] - tracked[0]["position_px"][0] == pytest.approx(19, abs=1.0)
    assert tracked[-1]["position_px"][1] == pytest.approx(tracked[0]["position_px"][1], abs=.5)
    assert all(row["confidence"] is None for row in tracked)

    with read_artifact(adapter, pid, receipt, "csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) > 20
    assert {"time_s", "speed_px_s", "scale", "angle_deg_unwrapped"} <= set(rows[0])
    speeds = [float(row["speed_px_s"]) for row in rows if row["speed_px_s"]]
    assert np.median(speeds) == pytest.approx(10, abs=1.0)
    assert receipt["summary"]["elements"]
    saved = next(item for item in adapter.get_project(pid)["motion_measurements"] if item["id"] == receipt["id"])
    assert saved["current"] is True
    assert str(adapter.data_dir) not in json.dumps(receipt)


def test_mask_asset_is_resolved_and_receipts_do_not_expose_private_paths(adapter, motion_video, tmp_path):
    current = source_project(adapter, motion_video)
    source_id = current["asset_id"]
    mask = tmp_path / "seed-mask.png"
    Image.new("L", (128, 96), 255).save(mask)
    current = upload(adapter, current, "logo", mask, "image/png")
    mask_id = current["asset_id"]
    spec = specification()
    spec["elements"][0]["mask_asset_id"] = mask_id
    result = measure(adapter, current, spec, source_id)
    receipt = result["motion_measurement"]
    data = json.loads(read_artifact(adapter, current["project_id"], receipt, "observations").read_text())
    recorded = data["elements"][0]["selection"]["mask"]
    assert recorded["asset_id"] == mask_id and recorded["sha256"] == file_sha256(mask)
    assert recorded["positive_pixels"] > 0
    for name in ("observations", "profile", "qa"):
        text = read_artifact(adapter, current["project_id"], receipt, name).read_text()
        assert str(adapter.data_dir) not in text
        assert str(mask) not in text


def test_source_and_mask_ids_are_scoped_to_project_and_media_type(adapter, motion_video, tmp_path):
    current = source_project(adapter, motion_video)
    other = source_project(adapter, motion_video)
    with pytest.raises(ValidationError, match="asset_missing"):
        measure(adapter, current, asset_id=other["asset_id"])
    mask = tmp_path / "mask.png"
    Image.new("L", (128, 96), 255).save(mask)
    foreign_mask = upload(adapter, other, "logo", mask, "image/png")
    spec = specification()
    spec["elements"][0]["mask_asset_id"] = foreign_mask["asset_id"]
    with pytest.raises(ValidationError, match="asset_missing"):
        measure(adapter, current, spec)
    spec["elements"][0]["mask_asset_id"] = current["asset_id"]
    with pytest.raises(ValueError):
        measure(adapter, current, spec)
    image_source = upload(adapter, current, "logo", mask, "image/png")
    with pytest.raises(ValueError):
        measure(adapter, image_source)


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(command="python arbitrary.py"),
    lambda s: s["elements"][0].update(mask_path="/etc/passwd"),
    lambda s: s["elements"][0].update(mask_path="https://example.test/mask.png"),
    lambda s: s["elements"][0].update(mask_asset_id="../outside"),
    lambda s: s.update(tracker={"exec": "arbitrary()"}),
    lambda s: s.update(tracker={"max_corners": 10000000}),
    lambda s: s.update(tracker={"window_size": 1000001}),
    lambda s: s["elements"][0].update(range=[0, 301]),
    lambda s: s.update(elements=[{**s["elements"][0], "id": f"panel-{i}"} for i in range(5)]),
])
def test_invalid_or_unbounded_specification_fails_before_tracking(adapter, motion_video, monkeypatch, mutation):
    from visual_fidelity import motion_observation
    current = source_project(adapter, motion_video)
    spec = specification()
    mutation(spec)
    monkeypatch.setattr(motion_observation, "measure_video", lambda *_args, **_kwargs: pytest.fail("Unsafe or excessive input reached tracking"))
    before = adapter.get_project(current["project_id"])
    with pytest.raises(ValueError):
        measure(adapter, current, spec)
    after = adapter.get_project(current["project_id"])
    assert after["revision"] == before["revision"]
    assert len(after["assets"]) == len(before["assets"])


def test_stale_revision_fails_before_tracking(adapter, motion_video, monkeypatch):
    from visual_fidelity import motion_observation
    current = source_project(adapter, motion_video)
    changed = adapter.save_project(current["project_id"], {"editNotes": "Revised context"}, current["revision"])
    monkeypatch.setattr(motion_observation, "measure_video", lambda *_args, **_kwargs: pytest.fail("Stale revision reached tracking"))
    with pytest.raises(ValidationError, match="revision_conflict"):
        measure(adapter, current)
    assert adapter.get_project(current["project_id"])["revision"] == changed["revision"]


def test_measurement_becomes_stale_after_context_revision_without_losing_artifacts(adapter, motion_video):
    current = source_project(adapter, motion_video)
    completed = measure(adapter, current)
    receipt = completed["motion_measurement"]
    profile_path = read_artifact(adapter, current["project_id"], receipt, "profile")
    original = profile_path.read_bytes()
    revised = adapter.save_project(current["project_id"], {"objective": "Revised editorial requirement"}, completed["revision"])
    old = next(m for m in revised["motion_measurements"] if m["id"] == receipt["id"])
    assert old["current"] is False
    assert old["scope"] == "evidence_not_applied" and old["user_approved"] is False
    assert profile_path.read_bytes() == original
    assert revised["state"]["cloneApproval"] is None and revised["state"]["finalApproval"] is None


def test_measurement_source_hash_change_invalidates_current_status(adapter, motion_video):
    current = source_project(adapter, motion_video)
    completed = measure(adapter, current)
    receipt = completed["motion_measurement"]
    source = adapter.resolve_asset(current["project_id"], current["asset_id"])
    source.write_bytes(source.read_bytes() + b"changed bytes")
    snapshot = adapter.get_project(current["project_id"])
    old = next(m for m in snapshot["motion_measurements"] if m["id"] == receipt["id"])
    assert old["current"] is False
    assert read_artifact(adapter, current["project_id"], receipt, "profile").is_file()
    with pytest.raises(ValidationError):
        adapter.measure_motion(current["project_id"], current["asset_id"], specification(), expected_revision=completed["revision"])


def structured(result):
    assert not result.get("isError"), result
    return result["structuredContent"]


def recursive_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from recursive_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from recursive_dicts(child)


def test_mcp_measurement_job_exports_evidence_and_retries_idempotently(tmp_path, motion_video):
    app = create_app(data_dir=tmp_path / "data", base_url=BASE, owner_key=KEY)
    with TestClient(app, base_url=BASE) as client:
        with authorize_owner(BASE, KEY, client=client) as session:
            tools = session.rpc("tools/list")["tools"]
            tool = next(t for t in tools if t["name"] == "editor_measure_motion")
            schema = tool["inputSchema"]
            assert {"project_id", "asset_id", "specification", "expected_revision", "request_id"} <= set(schema["properties"])
            assert any(node.get("maxItems") == 4 for node in recursive_dicts(schema))
            created = structured(session.call_tool("editor_save_project", {"state": {"objective": "Known synthetic motion evidence"}}))
            pid = created["project_id"]
            headers = {**session.headers, "Content-Type": "video/mp4", "X-Editor-Revision": str(created["revision"])}
            response = client.post(f"/uploads/{pid}/ref?filename=synthetic-motion.mp4", content=motion_video.read_bytes(), headers=headers)
            assert response.status_code == 200, response.text
            current = response.json()
            arguments = {"project_id": pid, "asset_id": current["asset_id"], "specification": specification(),
                         "expected_revision": current["revision"], "request_id": "motion-measure-integration-1"}
            queued = structured(session.call_tool("editor_measure_motion", arguments))
            assert queued["operation"] == "measure_motion"
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                snapshot = structured(session.call_tool("editor_get_project", {"project_id": pid}))
                job = next(j for j in snapshot["jobs"] if j["id"] == queued["id"])
                if job["status"] not in {"queued", "running"}:
                    break
                time.sleep(.05)
            assert job["status"] == "completed", job
            receipt = job["result"]["motion_measurement"]
            assert receipt["scope"] == "evidence_not_applied" and receipt["user_approved"] is False
            profile_id = receipt["artifacts"]["profile"]["asset_id"]
            link = structured(session.call_tool("editor_get_asset", {"project_id": pid, "asset_id": profile_id}))
            exported = client.get(link["url"])
            assert exported.status_code == 200
            profile = exported.json()
            assert profile["schema"] == "element-motion-curves/1"
            assert profile["source"]["sha256"] == file_sha256(motion_video)
            assert str(tmp_path / "data") not in exported.text
            repeat = structured(session.call_tool("editor_measure_motion", arguments))
            assert repeat["job_id"] == job["id"] and repeat["status"] == "completed"
            assert repeat["result"]["motion_measurement"]["id"] == receipt["id"]
            latest = structured(session.call_tool("editor_get_project", {"project_id": pid}))
            assert len(latest["motion_measurements"]) == 1
            conflict = deepcopy(arguments)
            conflict["specification"]["elements"][0]["roi_px"][0] = 21
            assert session.call_tool("editor_measure_motion", conflict).get("isError")
            assert latest["state"]["cloneApproval"] is None and latest["state"]["finalApproval"] is None
