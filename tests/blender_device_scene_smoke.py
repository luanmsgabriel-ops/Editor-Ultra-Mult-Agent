"""Rendered regression for UV attachment and independent, world-Y-up camera.

blender -b --factory-startup --threads 4 --python-exit-code 1 \
  --python tests/blender_device_scene_smoke.py

Set DEVICE_SCENE_TEST_OUTPUT to keep the three rendered diagnostic frames.
This test uses only a synthetic texture; no private assets are required.
"""
import json
import math
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from visual_fidelity.device_scene import frame_state, validate_config
from visual_fidelity.blender_device_scene import apply_state, build, project_metadata


def main():
    output = Path(os.environ.get("DEVICE_SCENE_TEST_OUTPUT", tempfile.mkdtemp(prefix="device-scene-")))
    output.mkdir(parents=True, exist_ok=True)
    texture = bpy.data.images.new("Synthetic UV quadrant target", width=64, height=128)
    palette = {"TL": (0.9, 0.02, 0.02, 1), "TR": (0.02, 0.9, 0.02, 1),
               "BL": (0.02, 0.02, 0.9, 1), "BR": (0.9, 0.8, 0.02, 1)}
    colors = []
    for y in range(128):
        for x in range(64):
            colors.extend(palette[("T" if y >= 64 else "B")+("L" if x < 32 else "R")])
    texture.pixels.foreach_set(colors)
    texture.filepath_raw = str(output/"uv-quadrants.png")
    texture.file_format = "PNG"
    texture.save()
    config = validate_config({"resolution": [240, 426], "samples": 4,
        "camera": {"location": [0, 0, 2.8], "target": [0, 0, 0], "lens_mm": 50},
        "devices": [{"id": "test", "screen_texture": str(output/"uv-quadrants.png"),
                     "front_sensor": False, "screen_reflection": 0.0, "camera_layout": "bar"}],
        "frames": [{"frame": 0},
                   {"frame": 1, "camera": {"location": [1.1, 0.5, 2.8]}},
                   {"frame": 2, "devices": {"test": {"rotation_deg": [14, -30, 11]}}}]})
    rig = build(config)
    camera_positions, device_matrices, projected = [], [], []
    for row in config["frames"]:
        state = frame_state(config, row)
        apply_state(rig, state)
        scene = rig["scene"]
        path = output/f"uv-{row['frame']:03d}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        width, height = image.size
        pixels = list(image.pixels)
        spec = rig["screen_specs"]["test"]
        root = rig["roots"]["test"]
        for label, x, y in (("TL", -.25, .25), ("TR", .25, .25), ("BL", -.25, -.25), ("BR", .25, -.25)):
            point = root.matrix_world @ Vector((x*spec["width"], y*spec["height"], spec["z"]))
            p = world_to_camera_view(scene, rig["camera"], point)
            px, py = int(p.x*width), int(p.y*height)
            color = pixels[4*(py*width+px):4*(py*width+px)+4]
            assert color[3] > .95, (label, "display alpha", color)
            if label == "BR":
                assert min(color[0], color[1]) > color[2]*4, (label, color)
            else:
                expected = {"TL": 0, "TR": 1, "BL": 2}[label]
                assert color[expected] > max(color[i] for i in range(3) if i != expected)*4, (label, color)
        camera_positions.append(list(rig["camera"].location))
        device_matrices.append([list(v) for v in root.matrix_world])
        meta = project_metadata(rig, state)
        projected.append(meta["devices"]["test"]["screen_pixels"])
        bpy.data.images.remove(image)
    assert device_matrices[0] == device_matrices[1], "Camera movement moved the phone"
    assert camera_positions[0] == camera_positions[2], "Phone rotation moved the camera"
    assert math.dist(projected[0][0], projected[1][0]) > 2, "Camera orbit did not change the perspective"
    # A camera orbit with no authored roll must retain world +Y as screen-up.
    state = frame_state(config, config["frames"][1])
    apply_state(rig, state)
    origin = world_to_camera_view(rig["scene"], rig["camera"], Vector((0, 0, 0)))
    top = world_to_camera_view(rig["scene"], rig["camera"], Vector((0, 0.7, 0)))
    assert top.y > origin.y and abs(top.x-origin.x) < .07, "Unexpected camera roll while orbiting"
    # The back is also geometry: separate full-width bar and three lens barrels.
    names = {o.name for o in rig["roots"]["test"].children_recursive}
    assert "test.Full width camera bar" in names
    assert all(f"test.Lens {i} barrel" in names for i in range(1, 4))
    result = {"passed": True, "rendered_frames": 3, "checks": ["UV colors under camera motion", "UV colors under phone rotation", "independent transforms", "world Y up", "solid rear camera geometry"], "output": str(output)}
    (output/"uv-check.json").write_text(json.dumps(result, indent=2)+"\n")
    print("DEVICE_SCENE_SMOKE", json.dumps(result))


if __name__ == "__main__":
    main()
