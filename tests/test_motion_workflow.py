"""Producers must survive export, preparation and direction without losing evidence."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from editorial_engine.contracts import file_sha256
from editorial_engine.directions import build_request
from editorial_engine.motion import render_recipe
from editorial_engine.motion_assets import load_layer
from editorial_engine.motion_events import map_sonic_candidates
from editorial_engine.native import native_catalog
from editorial_engine.perception import prepare_analysis


@pytest.mark.parametrize("backend", ["motionlab", "motngrfx"])
def test_real_producer_reaches_contextual_direction_with_its_clock_and_evidence(tmp_path, backend):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real producer integration needs FFmpeg and FFprobe")
    source = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=0x101820:s=96x64:r=8:d=1", "-c:v", "libx264", "-threads", "1",
                    "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
    source_hash = file_sha256(source)
    options = {}
    if backend == "motionlab":
        runtime = Path(__file__).resolve().parents[1] / "editorial_engine/backends/motionlab/node_modules/@napi-rs/canvas/package.json"
        if not shutil.which("node") or not runtime.is_file():
            pytest.skip("Install the locked Motion Lab Node dependencies")
        recipe = {"schema_version": "motionlab-scene/1", "id": "workflow-proof", "mode": "2d",
                  "width": 96, "height": 64, "fps": "8/1", "frame_count": 8, "background": None,
                  "nodes": [{"id": "square", "type": "rect", "x": 4, "y": 20,
                             "width": 12, "height": 12, "fill": "#ff0000"}],
                  "tracks": [{"target": "square", "property": "x", "keys": [
                      {"t": 0, "value": 4, "ease": "linear"}, {"t": 1, "value": 80}]}]}
    else:
        if not shutil.which("fc-match"):
            pytest.skip("A system font is required for the typography proof")
        font = subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans"],
                              check=True, capture_output=True, text=True).stdout
        if not Path(font).is_file():
            pytest.skip("No real system font")
        options = {"font": font, "font_license": "System font; OS license retained; no font redistributed"}
        recipe = {"schema": "motngrfx-motion/1", "text": "AÓ", "fps": "8/1", "frame_count": 8,
                  "width": 96, "height": 64, "font_size": 24, "extrusion_px": 4,
                  "animation": {"module": "rotate", "keyframes": [
                      {"frame": 0, "rotation_deg": [-15, 0, 0]},
                      {"frame": 7, "rotation_deg": [15, 0, 0]}]}}
    rendered = render_recipe(backend, recipe, tmp_path / "rendered", asset_id="proof", **options)
    registered = rendered["contextual_asset"]
    layer = load_layer(registered["manifest_path"])
    assert layer["frame_count"] == 8 and layer["fps"] == "8"
    assert layer["origin"]["execution_in_this_call"] is True
    assert layer["origin"]["upstream_commit"]
    assert registered["user_approval"] == "pending"
    inventory = json.loads(Path(registered["inventory_path"]).read_text())
    analysis = prepare_analysis(source, tmp_path / "prepared", assets=inventory, sample_every_s=.125)
    request = build_request(analysis, native_catalog(), brief="Inspect the authored layer before selecting its use")
    payload = json.loads(request["body"]["messages"][1]["content"][0]["text"])
    resource = next(row for row in payload["resources"] if row["capability_id"] == "asset:proof")
    assert resource["motion_asset"]["frame_count"] == 8
    assert payload["review_scope"]["motion_asset_capability_ids"] == ["asset:proof"]
    if backend == "motionlab":
        sonic = resource["motion_audio_candidates"]
        assert sonic["scene_sha256"] == layer["origin"]["recipe_sha256"]
        mapped = map_sonic_candidates(sonic, source, source_first_frame=0, source_last_frame=8)
        assert mapped["sfx_selected"] is False and mapped["audio_listened"] is False
        assert all(0 <= row["target_sample"] < 48000 for row in mapped["candidates"])
    else:
        assert all(row["glyph_ids_sha256"] and Path(row["glyph_ids_path"]).is_file() for row in layer["frames"])
    assert file_sha256(source) == source_hash
