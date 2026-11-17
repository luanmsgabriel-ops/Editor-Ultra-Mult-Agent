"""Resource admission and a real planar PNG reconstruction through the app adapter."""

import json
import subprocess
from zipfile import ZipFile

import cv2
import numpy as np
from PIL import Image
import pytest

from editorial_engine import project as engine_project
from editorial_engine.contracts import ValidationError
from editor_ultra_app.engine import EngineAdapter

AUTHOR = {"kind": "human", "actor": "visual test", "method": "Explicitly authored test footage"}


def write_video(path, color):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s=160x90:r=10:d=1",
         "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=30,
    )


def direction_for(analysis, interval, asset, operation, capability=None, shutter=.6):
    source = analysis["sources"][0]
    evidence = [item for item in analysis["evidence"] if item["kind"] == "visual"
                and item["interval"]["start_s"] < interval["end_s"]
                and item["interval"]["end_s"] > interval["start_s"]]
    events = analysis["events"]
    event = next(item for item in events if item["interval"]["start_s"] <= interval["start_s"]
                 and interval["end_s"] <= item["interval"]["end_s"])
    use_matte = operation == "native.projected_behind"
    bindings = {"asset": "asset:" + asset, **({"matte": "matte"} if use_matte else {})}
    return {
        "schema_version": "1.0", "provenance": AUTHOR,
        "evidence_annotations": [{"id": item["id"], "observation": "Blue reconstructed stage and aligned composition area."}
                                 for item in evidence],
        "event_annotations": [{
            "id": item["id"], "intent": "Compose the generated reconstruction element.",
            "opportunities": [{"id": "shield", "function": "spatial_relation",
                               "why": "It follows the position of its reconstructed attachment plane."}]
            if item["id"] == event["id"] else [],
        } for item in events],
        "proposals": {"schema_version": "1.0", "candidates": [{
            "id": "shield-layer", "source_id": source["id"], "source_sha256": source["sha256"],
            "clock": "source", "event_id": event["id"], "interval": interval,
            "effect_id": operation, "evidence_ids": [item["id"] for item in evidence],
            "why": "Bind the exact alpha asset to its spatial element.",
            "scores": dict.fromkeys(("intent_fit", "visual_fit", "style_fit", "timing_fit"), .99),
            "addresses": ["shield"], "region": [0, 0, 1, 1],
            "anchor": {"space": "planar", "capability_id": capability} if capability else {"space": "screen"},
            "bindings": bindings,
            "params": {"animation": "hold", **({"shutter_fraction": shutter} if capability else {})},
        }]},
        "limitations": [],
    }


def test_png_request_moves_through_real_render(tmp_path):
    adapter = EngineAdapter(tmp_path / "app")
    instance = adapter.save_project(None, {"schema": "editor-ultra-interface/1", "sourceType": "video"})
    project_id, revision = instance["project_id"], instance["revision"]

    def add(role, path, mime):
        nonlocal revision
        result = adapter.import_local_file(project_id, role, path, path.name, mime, expected_revision=revision)
        revision = result["revision"]
        return result["asset"]

    ref = tmp_path / "reference.mp4"
    base = tmp_path / "plate.mp4"
    write_video(ref, "red")
    write_video(base, "blue")
    add("ref", ref, "video/mp4")
    plate = add("footage", base, "video/mp4")
    req = adapter.request_clone_images(project_id, [{
        "id": "shield", "scene_id": "scene-1", "frames": [0, 10], "reference_frame": 5,
        "placement": "planar_behind", "description": "Green shield with transparent margins.",
        "reason": "Keep the designed texture and use the moving planar anchor.",
    }], expected_revision=revision)
    revision = req["revision"]
    assert req["image_request"]["status"] == "awaiting_image_generation"
    with pytest.raises(ValidationError, match="verified PNG"):
        adapter.prepare(project_id, "clone", expected_revision=revision,
                        reconstruction={"base_asset_id": plate["id"]})
    icon = tmp_path / "shield.png"
    Image.new("RGB", (40,40), "green").save(icon)
    with pytest.raises(ValidationError, match="transparent background"):
        add("clone_resource", icon, "image/png")
    art = Image.new("RGBA", (40,40))
    art.paste((22,247,104,255), (1,1,39,39))
    art.save(icon)
    green = add("clone_resource", icon, "image/png")
    declarations = {"source_sha256": plate["sha256"], "clock": "source", "fps": "10/1",
                    "frame_count": 10, "provenance": AUTHOR}
    protection = tmp_path / "protection.json"
    protection.write_text(json.dumps({**declarations, "frames": {str(n): [] for n in range(10)}}))
    protect = add("clone_resource", protection, "application/json")
    projection = tmp_path / "projection.json"
    quads = {}
    for n in range(10):
        x = .1 + n * .037
        quads[str(n)] = [[x,.2],[x+.36,.2],[x+.36,.8],[x,.8]]
    projection.write_text(json.dumps({**declarations, "quads": quads}))
    planar = add("clone_resource", projection, "application/json")
    masks = tmp_path / "alpha.zip"
    mask = Image.new("L", (160,90))
    mask.paste(255,(70,30,90,60))
    import io
    buffer = io.BytesIO()
    mask.save(buffer, format="PNG")
    with ZipFile(masks, "w") as archive:
        archive.writestr("alpha.json", json.dumps({"clock": "source", "source_sha256": plate["sha256"],
                                                  "fps": "10/1", "frames": 10, "resolution": [160,90]}))
        for n in range(10):
            archive.writestr(f"{n:06d}.png", buffer.getvalue())
    matte = add("clone_resource", masks, "application/zip")
    ready = adapter.prepare(project_id, "clone", expected_revision=revision, reconstruction={
        "base_asset_id": plate["id"], "images": {"shield": green["id"]},
        "protection_asset_id": protect["id"], "projection_asset_id": planar["id"],
        "matte_asset_id": matte["id"],
    })
    assert ready["preview_kind"] == "reconstruction"
    stage = adapter._load(project_id)["engines"]["clone"]
    analysis = engine_project.artifact(stage["directory"], "analysis:" + plate["id"])
    interval = {"start_s": 0., "end_s": 1.}
    ignored = direction_for(analysis, interval, "shield", "native.overlay")
    with pytest.raises(ValidationError, match="requested placement"):
        adapter.apply_direction(project_id, "clone", ignored, expected_revision=ready["revision"])
    direction = direction_for(analysis, interval, "shield", "native.projected_behind", "planar:0:10")
    applied = adapter.apply_direction(project_id, "clone", direction, expected_revision=ready["revision"])
    completed = adapter.render(project_id, "clone", expected_revision=applied["revision"])
    assert completed["preview_kind"] == "reconstruction"
    assert completed["approval"]["clone"] is None
    assert completed["result"]["image_bindings"]["shield"]["sha256"] == green["sha256"]
    assert completed["result"]["compilation"][0]["shutter_fraction"] == .6
    assert adapter.get_result(project_id, "clone")["preview_kind"] == "reconstruction"
    reader = cv2.VideoCapture(str(adapter.resolve_asset(project_id, completed["asset_id"])))
    reader.set(cv2.CAP_PROP_POS_FRAMES, 5)
    ok, frame = reader.read()
    reader.release()
    assert ok and int(frame[45,64,1]) > 120
    assert int(frame[45,79,0]) > 170 and int(frame[45,79,1]) < 30
    assert np.mean(frame[:,:,1] > 100) > .05


def test_measured_corners_keep_source_frames_and_reject_gaps():
    from editor_ultra_app.clone_resources import measured_quads
    from test_motion_profile import observations
    from visual_fidelity.motion_profile import fit_profile

    samples = [{"position_px": [350 + frame * 5, 640]} for frame in range(5)]
    track = observations(samples)
    track["source"]["fps"] = "30/1"
    clock = {"width": 720, "height": 1280, "fps": "30/1", "frame_count": 5}
    profile = fit_profile(track)
    quads = measured_quads(profile, "panel", [1, 4], clock)
    assert set(quads) == {"1", "2", "3"}
    assert quads["3"][0][0] - quads["1"][0][0] == pytest.approx(10/720, abs=1e-7)
    track["elements"][0]["samples"][2]["cut_before"] = True
    with pytest.raises(ValidationError, match="trajectory cannot span"):
        measured_quads(fit_profile(track), "panel", [1, 4], clock)
