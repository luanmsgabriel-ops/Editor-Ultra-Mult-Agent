"""Cross-PR smoke: reference scene + measured-motion render + VIDEOAPI result import.

Executes real local FFmpeg/MP4 work and authenticated MCP, but deliberately
never calls the paid VIDEOAPI POST or asserts aesthetic clone quality.
"""
import json
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np
from PIL import Image
import pytest
from starlette.testclient import TestClient

from editorial_engine.contracts import file_sha256
from editor_ultra_app.engine import EngineAdapter
from editor_ultra_app.server import create_app
from editor_ultra_app.videoapi import VideoAPIJobs, build_payload
from scripts.check_app_connection import authorize_owner


BASE = "https://editor.example"
KEY = "test-only-p0-integrated-key-012345678901234567890"


def media(tmp_path):
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("real FFmpeg required")
    rng = np.random.default_rng(4201)
    pattern = np.repeat(rng.integers(35, 235, (48, 56), dtype=np.uint8)[:, :, None], 3, axis=2)
    ref, base = [], []
    for i in range(20):
        img = np.full((96, 128, 3), 12, np.uint8)
        img[20:68, 20+i:76+i] = pattern
        ref.append(img)
        base.append(np.full((96, 128, 3), 8, np.uint8))

    def encode(frames, name):
        target = tmp_path / name
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                        "-f", "rawvideo", "-pix_fmt", "rgb24",
                        "-s", "128x96", "-r", "10", "-i", "pipe:0",
                        "-an", "-c:v", "libx264", "-crf", "12",
                        "-threads", "1", "-pix_fmt", "yuv420p", str(target)],
                       input=np.stack(frames).tobytes(), capture_output=True,
                       check=True, timeout=30)
        return target

    reference = encode(ref, "reference.mp4")
    new_base = encode(base, "independent-base.mp4")
    overlay = np.zeros((96, 128, 3), np.uint8)
    overlay[20:68, 20:76] = (45, 225, 245)
    mask = np.zeros((96, 128), np.uint8)
    mask[20:68, 20:76] = 255
    layer = tmp_path / "new-layer.png"
    matte = tmp_path / "new-layer-matte.png"
    Image.fromarray(overlay).save(layer)
    Image.fromarray(mask).save(matte)
    return reference, new_base, layer, matte


def structured(result):
    assert not result.get("isError"), result
    return result["structuredContent"]


def completed(session, pid, identifier):
    for _ in range(160):
        state = structured(session.call_tool("editor_get_project", {"project_id": pid}))
        job = next(x for x in state["jobs"] if x["id"] == identifier)
        if job["status"] not in {"queued", "running"}:
            assert job["status"] == "completed", job
            return job, state
        time.sleep(.05)
    pytest.fail("Integrated MCP job failed to finish")


def test_one_project_executes_all_integrated_local_bridges_without_paid_generation(tmp_path, monkeypatch):
    reference, new_base, layer, matte = media(tmp_path)
    root = tmp_path / "private"
    adapter = EngineAdapter(root)
    state = adapter.save_project(None, {"objective": "Integrated synthetic P0 evidence",
                                        "mode": "ready"})
    pid = state["project_id"]
    ids = {}
    for key, role, path, mime in [
        ("ref", "ref", reference, "video/mp4"),
        ("base", "footage", new_base, "video/mp4"),
        ("overlay", "identity", layer, "image/png"),
        ("matte", "identity", matte, "image/png"),
        ("clone", "clone", new_base, "video/mp4"),
    ]:
        state = adapter.import_local_file(pid, role, path, path.name, mime,
                                          expected_revision=state["revision"])
        ids[key] = state["asset_id"]
    manifest = {"schema": "editor-ultra-reference-scenes/1",
                "source_sha256": file_sha256(reference), "fps": "10/1",
                "frame_count": 20, "scenes": [{
                    "id": "entire", "start_frame": 0, "end_frame": 20,
                    "elements": ["panel"],
                    "events": [{"id": "move", "element_id": "panel", "frame": 1,
                                "action": "panel moves right", "observed": True}],
                    "unresolved": [],
                }]}
    state = adapter.register_reference_scenes(pid, manifest,
                                              expected_revision=state["revision"])

    app = create_app(data_dir=root, base_url=BASE, owner_key=KEY)

    def fake_download(url, directory, *, max_bytes):
        assert url.startswith("https://www.videoapi.com.br/")
        assert max_bytes > new_base.stat().st_size
        Path(directory).mkdir(parents=True, exist_ok=True)
        target = Path(directory) / "mock-return.mp4"
        target.write_bytes(new_base.read_bytes())
        return target

    monkeypatch.setattr("editor_ultra_app.server.download_completed_video", fake_download)
    with TestClient(app, base_url=BASE) as client:
        with authorize_owner(BASE, KEY, client=client) as session:
            names = {x["name"] for x in session.rpc("tools/list")["tools"]}
            assert {"editor_route_reference_scenes", "editor_audit_scene_batch",
                    "editor_apply_measured_motion", "editor_import_videoapi_result",
                    "editor_request_clone_images", "editor_videoapi_generate"} <= names
            routed = structured(session.call_tool("editor_route_reference_scenes", {
                "project_id": pid, "expected_revision": state["revision"],
                "request_id": "p0-combined-route-001",
                "choices": {"schema": "editor-ultra-scene-routing/1",
                            "scenes": [{"scene_id": "entire", "needs": ["preserve"]}]},
            }))
            _, state = completed(session, pid, routed["id"])
            assert state["scene_route"]["current"]

            measured = structured(session.call_tool("editor_measure_motion", {
                "project_id": pid, "asset_id": ids["ref"],
                "expected_revision": state["revision"],
                "request_id": "p0-combined-measure-001",
                "specification": {
                    "schema": "element-motion-measurement/1",
                    "elements": [{
                        "id": "panel", "range": [0, 20], "seed_frame": 0,
                        "roi_px": [20, 20, 56, 48],
                    }],
                },
            }))
            result, state = completed(session, pid, measured["id"])
            receipt = result["result"]["motion_measurement"]
            assert receipt["scope"] == "evidence_not_applied"
            spec = {
                "schema": "editor-ultra-measured-motion-application/1",
                "measurement_id": receipt["id"], "base_asset_id": ids["base"],
                "overlay_asset_id": ids["overlay"], "matte_asset_id": ids["matte"],
                "element_id": "panel", "channels": ["position", "scale", "angle"],
                "frame_count": 10, "pivot_px": [48.0, 44.0], "base_scale": 1.0,
                "time_map": [{"output_time": 0.0, "source_time": 0.0},
                             {"output_time": 0.9, "source_time": 0.9}],
            }
            queued = structured(session.call_tool("editor_apply_measured_motion", {
                "project_id": pid, "expected_revision": state["revision"],
                "request_id": "p0-combined-render-001", "specification": spec,
            }))
            result, state = completed(session, pid, queued["id"])
            application = result["result"]["motion_application"]
            assert application["consumption"]["frame_count"] == 10
            assert application["status"] == "rendered_unreviewed"
            assert state["approval"]["clone"] is None

            qa_job = structured(session.call_tool("editor_audit_scene_batch", {
                "project_id": pid, "expected_revision": state["revision"],
                "request_id": "p0-combined-qa-001", "scene_ids": ["entire"],
            }))
            _, state = completed(session, pid, qa_job["id"])
            assert state["scene_quality_gate"]["status"] == "technical_evidence_complete_visual_review_pending"
            assert state["approval"]["clone"] is None

            class FakeProvider:
                def __init__(self):
                    self.calls = 0
                def create(self, kind, payload):
                    self.calls += 1
                    return {"id": "11111111-1111-1111-1111-111111111111"}

            provider = FakeProvider()
            fake_jobs = VideoAPIJobs(root, client=provider)
            submitted = fake_jobs.submit(pid, "fixture-finished-video", "video",
                                         build_payload("video", "synthetic done", "9:16", 5))
            with fake_jobs._db() as db:
                db.execute("UPDATE videoapi_jobs SET status='done',download_url=? WHERE job_id=?",
                           ("https://www.videoapi.com.br/fixture/video.mp4", submitted["job_id"]))
            queued = structured(session.call_tool("editor_import_videoapi_result", {
                "project_id": pid, "expected_revision": state["revision"],
                "request_id": "p0-combined-import-001",
                "videoapi_job_id": submitted["job_id"],
            }))
            imported, state = completed(session, pid, queued["id"])
            assert imported["result"]["asset"]["provenance"]["job_id"] == submitted["job_id"]
            assert imported["result"]["asset"]["role"] == "footage"
            assert imported["result"]["status"] == "videoapi_imported"
            assert state["approval"]["clone"] is None
            assert state["approval"]["final"] is None
            assert provider.calls == 1  # only fixture setup, never an extra paid POST
