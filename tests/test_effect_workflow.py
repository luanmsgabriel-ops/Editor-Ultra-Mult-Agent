"""Authenticated reference-to-render workflow on independently created media."""

import json
import subprocess
import time

import cv2
import numpy as np
from starlette.testclient import TestClient

from editor_ultra_app.server import create_app
from scripts.check_app_connection import authorize_owner

BASE = "https://editor.example"
KEY = "test-only-effect-owner-key-012345678901234567890"


def encode(frames, path, *, audio=False):
    height, width = frames[0].shape[:2]
    args = ["ffmpeg", "-v", "error", "-f", "rawvideo", "-pixel_format", "bgr24",
            "-video_size", f"{width}x{height}", "-framerate", "12", "-i", "pipe:0"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=470:duration={len(frames) / 12:.8f}", "-c:a", "aac"]
    subprocess.run(args + ["-c:v", "libx264", "-threads", "2", "-crf", "10", "-pix_fmt", "yuv420p", str(path)],
                   input=b"".join(frame.tobytes() for frame in frames), check=True, capture_output=True, timeout=25)


def media(tmp_path):
    width, height, count = 320, 192, 40
    matrix = np.array([[290., 0., width / 2], [0., 290., height / 2], [0., 0., 1.]])
    seed_points = np.array([(x, y) for y in (23, 52, 138, 166) for x in (49, 78, 118, 186, 239, 266)])
    depths = 4.3 + np.asarray([(index % 7) * .31 for index, _ in enumerate(seed_points)])
    targets = np.column_stack((seed_points, np.ones(len(seed_points)))) @ np.linalg.inv(matrix).T
    world = targets * depths[:, None]
    frames = []
    for offset in range(count):
        rvec = np.array([0., .003 * offset, 0.])
        tvec = np.array([-.028 * offset, .001 * offset, 0.])
        xy = cv2.projectPoints(world, rvec, tvec, matrix, None)[0].reshape(-1, 2)
        frame = np.full((height, width, 3), (38, 45, 50) if offset < 20 else (121, 130, 161), np.uint8)
        for index, point in enumerate(xy):
            x, y = np.rint(point).astype(int)
            color = (200 + index % 4 * 12, 171, 228 - index % 7 * 8)
            cv2.rectangle(frame, (x - 4, y - 4), (x + 3, y + 3), color, -1)
            cv2.line(frame, (x - 3, y + 2), (x + 2, y - 3), (91, 46, 98), 1)
        if offset < 15:
            x = 110 + offset * 2
            cv2.rectangle(frame, (x, 70), (x + 34, 101), (14, 18, 247), -1)
        frames.append(frame)
    ref = tmp_path / "reference.mp4"
    ref_frames = [np.full_like(frame, (80, 30, 20) if i < 18 else (27, 143, 38))
                  for i, frame in enumerate(frames)]
    texture = np.random.default_rng(195).integers(18, 245, (50, 60, 1), dtype=np.uint8)
    for i in range(17):
        ref_frames[i][36:86, 41 + i:101 + i] = texture
    ref_frames[17][:] = (255, 255, 255)
    encode(ref_frames, ref)
    footage = tmp_path / "footage.mp4"
    encode(frames, footage, audio=True)
    calibration = {"intrinsics": matrix.tolist(), "world_points": world.tolist(),
                   "image_points": (seed_points / [width, height]).tolist()}
    return ref, footage, calibration


def structured(response):
    assert not response.get("isError"), response
    return response["structuredContent"]


def test_effect_library_choice_camera_occlusion_and_revision(tmp_path):
    ref, footage, calibration = media(tmp_path)
    app = create_app(data_dir=tmp_path / "data", base_url=BASE, owner_key=KEY)
    with TestClient(app, base_url=BASE) as client, authorize_owner(BASE, KEY, client=client) as session:
        current = structured(session.call_tool("editor_save_project", {"state": {"name": "Projeto de efeitos"}}))
        project_id = current["project_id"]
        assets = {}
        for role, path in (("ref", ref), ("footage", footage)):
            received = client.post(
                f"/uploads/{project_id}/{role}?filename={path.name}", content=path.read_bytes(),
                headers={**session.headers, "Content-Type": "video/mp4", "X-Editor-Revision": str(current["revision"])},
            )
            assert received.status_code == 200, received.text
            current = received.json()
            assets[role] = current["asset_id"]

        def job(command, *, succeeds=True, widget=False, measure=False):
            nonlocal current
            revision = current["revision"]
            request_id = f"effects-{revision}-{command['action']}"
            args = {"project_id": project_id, "expected_revision": revision}
            if measure:
                queued = structured(session.call_tool("editor_measure_motion", {
                    **args, "asset_id": assets["ref"], "request_id": request_id,
                    "specification": {"schema": "element-motion-measurement/1",
                                      "elements": [{"id": "title", "range": [0, 12], "seed_frame": 0,
                                                    "roi_px": [41, 36, 60, 50]}]},
                }))
            elif widget:
                args["state"] = {"ui_action": "effect_workflow", "request_id": request_id, "command": command}
                queued = structured(session.call_tool("editor_save_project", args))
            else:
                args.update(command=command, request_id=request_id)
                queued = structured(session.call_tool("editor_effect_workflow", args))
            until = time.monotonic() + 30
            while time.monotonic() < until:
                current = structured(session.call_tool("editor_get_project", {"project_id": project_id}))
                result = next(item for item in current["jobs"] if item["id"] == queued["id"])
                if result["status"] not in {"queued", "running"}:
                    assert result["status"] == ("completed" if succeeds else "failed"), result
                    return current["effect_workflow"] if succeeds else result
                time.sleep(.05)
            raise AssertionError(f"Job did not complete: {command}")

        work = job({"action": "analyze", "role": "ref", "asset_id": assets["ref"],
                    "source_url": "https://example.com/reference"}, widget=True)
        assert work["ref"]["current"]
        assert work["ref"]["events"] and work["ref"]["proxy"]["url"]
        assert "path" not in work["ref"]["proxy"]
        job({"action": "measure_motion"}, measure=True)
        measurement = current["motion_measurements"][-1]
        for effect, title in (("type", "Legenda de produto"), ("world", "Cartão espacial"), ("flash", "Flash branco")):
            command = {"action": "publish", "effect": effect, "title": title, "recipe_id": f"reference-{effect}",
                       "version": "1.0.0", "description": "Técnica recriada para a prova de referência.",
                       "tags": ["produto"], "reference_range": [12, 20], "confirmed": True}
            if effect == "type":
                command.update(motion_measurement_id=measurement["id"], motion_element_id="title",
                               reference_range=[0, 12])
            work = job(command)
            assert work["published"][-1]["demo_kind"] == "synthetic"
        rows = structured(session.call_tool("editor_list_effects", {"query": "produto"}))["effect_library"]
        assert len(rows) == 3
        assert all(client.get(row["demo"]["url"]).status_code == 200 for row in rows)

        work = job({"action": "analyze", "role": "footage", "asset_id": assets["footage"]})
        assert [20, 40] in [row["range"] for row in work["footage"]["shots"]]
        assert work["footage"]["audio"]["present"]
        work = job({"action": "suggest", "opportunities": [
            {"range": [23, 35], "intent": "Identificar o item apresentado", "effects": ["type"]},
        ]})
        assert all(item["range"][0] >= 23 and item["range"][1] <= 35 for item in work["suggestions"])
        assert work["suggestions"]
        work = job({"action": "suggest", "query": "produto"})
        assert any(item["recipe"]["effect"] == "flash" for item in work["suggestions"])

        work = job({"action": "select", "recipe_id": "reference-world", "version": "1.0.0",
                    "range": [0, 12], "text": "Produto em 3D", "anchor": [.51, .45],
                    "calibration": calibration,
                    "occlusion": [[.344, .365], [.45, .365], [.45, .526], [.344, .526]]})
        application = work["selections"][0]["id"]
        work = job({"action": "select", "recipe_id": "reference-flash", "version": "1.0.0", "range": [18, 22]})
        work = job({"action": "select", "recipe_id": "reference-type", "version": "1.0.0",
                    "range": [24, 36], "text": "Detalhes do produto"})
        work = job({"action": "render", "preview": True, "application_id": application})
        assert work["render"]["kind"] == "preview"
        result = job({"action": "review", "asset_id": work["render"]["asset_id"], "decision": "approved",
                      "confirmed": True}, succeeds=False)
        assert "completo" in result["error"]

        work = job({"action": "render", "preview": False})
        render = work["render"]
        assert render["current"] and render["source_range"] == [0, 40]
        receipt = client.get(render["receipt"]["url"]).json()
        motion = next(item["motion"] for item in receipt["applications"] if item["effect"] == "type")
        assert motion[0][1] == 0
        assert motion[-1][1] > .025
        camera = receipt["spatial"][application]
        assert camera["method"] == "calibrated_pnp"
        assert camera["cache_hit"]
        assert len(camera["cameras"]) == 12
        assert max(row["reprojection_px"] for row in camera["cameras"]) < 1.75
        assert np.linalg.norm(np.array(camera["cameras"][-1]["t"]) - camera["cameras"][0]["t"]) > .1
        assert sum(receipt["coverage"][application]["occlusion_pixels"]) > 100
        assert receipt["audio_source_present"]
        output = tmp_path / "verified-edit.mp4"
        output.write_bytes(client.get(render["media"]["url"]).content)
        probe = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)]))
        assert [item["codec_type"] for item in probe["streams"]] == ["video", "audio"]
        assert probe["streams"][0]["nb_frames"] == "40"
        cap = cv2.VideoCapture(str(output))
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 6)
            ok, frame = cap.read()
            assert ok
            # The foreground remains red where it crosses the composited card.
            assert int(frame[78, 135, 2]) > 170 and int(frame[78, 135, 0]) < 80
            # A cyan border appears in a region that has no such color in the source.
            blue, green, red = np.moveaxis(frame[65:108, 158:205].astype(int), 2, 0)
            assert np.count_nonzero((blue - red > 30) & (green - red > 30)) > 12
        finally:
            cap.release()
        work = job({"action": "review", "asset_id": render["asset_id"], "decision": "approved", "confirmed": True})
        assert work["review"]["sha256"] == render["sha256"]
        work = job({"action": "remove", "application_id": application})
        assert work["render"]["current"] is False


def test_automatic_world_track_requires_parallax_and_keeps_a_moving_camera():
    import pytest

    from visual_fidelity.world_tracking import solve_world_track

    width, height = 360, 240
    focal = width * 1.15
    matrix = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1.]])
    rng = np.random.default_rng(7)
    pixels = np.array([(x, y) for y in range(38, 210, 18) for x in range(78, 310, 19)])
    depth = rng.uniform(3.5, 9., size=len(pixels))
    world = (np.column_stack((pixels, np.ones(len(pixels)))) @ np.linalg.inv(matrix).T) * depth[:, None]
    patches = [rng.integers(45, 235, size=(7, 7), dtype=np.uint8) for _ in pixels]
    frames = []
    for i in range(20):
        coordinates = cv2.projectPoints(world, np.array([.0004 * i, .001 * i, 0]),
                                        np.array([-.018 * i, 0., 0.]), matrix, None)[0].reshape(-1, 2)
        frame = np.full((height, width), 20, np.uint8)
        for (x, y), patch in zip(np.rint(coordinates).astype(int), patches):
            frame[y - 3:y + 4, x - 3:x + 4] = patch
        frames.append(frame)
    track = solve_world_track(frames)
    assert track["method"] == "relative_two_view_pnp_assumed_intrinsics"
    assert len(track["cameras"]) == 20
    assert track["cameras"][-1]["t"][0] < -.5
    assert max(camera["reprojection_px"] for camera in track["cameras"]) < 1.5
    with pytest.raises(ValueError, match="paralaxe"):
        solve_world_track([frames[0]] * 4)
