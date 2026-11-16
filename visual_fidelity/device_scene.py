"""Author and render real 3D smartphone scenes with an independent camera.

This module contains dependency-free geometry and recipe validation. Blender's
renderer lives in ``blender_device_scene.py``; no video-generation service is used.
Coordinates: X right, Y up, Z out of the display. Dimensions share arbitrary units.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import subprocess


SCHEMA = "editor-ultra.device-scene.v1"
DEFAULT_GEOMETRY = {
    "width": 0.78, "height": 1.634, "depth": 0.0875,
    "corner_radius": 0.078, "screen_margin": 0.021,
    "edge_bevel": 0.005, "corner_segments": 12,
}
DEFAULT_CAMERA = {
    "location": [0.0, 0.0, 3.6], "target": [0.0, 0.0, 0.0],
    "lens_mm": 50.0, "sensor_width_mm": 36.0, "roll_deg": 0.0,
    "dof": {"enabled": False, "fstop": 4.0},
}


def merge(base, update):
    """Merge dictionaries without changing either input (lists are replaced)."""
    result = deepcopy(base)
    for key, value in update.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else deepcopy(value)
    return result


def rounded_rect_outline(width, height, radius, segments=12):
    """Counter-clockwise rounded rectangle with genuine curved side geometry."""
    if not all(math.isfinite(v) for v in (width, height, radius)):
        raise ValueError("Geometry must be finite")
    if min(width, height) <= 0 or not 0 < radius <= min(width, height)/2 or segments < 2:
        raise ValueError("Invalid rounded rectangle")
    points = []
    for cx, cy, start in ((width/2-radius, height/2-radius, 0),
                          (-width/2+radius, height/2-radius, 90),
                          (-width/2+radius, -height/2+radius, 180),
                          (width/2-radius, -height/2+radius, 270)):
        for i in range(segments+1):
            angle = math.radians(start + 90*i/segments)
            point = (cx + radius*math.cos(angle), cy + radius*math.sin(angle))
            if not points or math.dist(points[-1], point) > 1e-10:
                points.append(point)
    if math.dist(points[0], points[-1]) < 1e-10:
        points.pop()
    return points


def rounded_prism(width, height, depth, radius, segments=12):
    """Closed manifold prism; caps and sidewalls remain separate faces."""
    if not math.isfinite(depth) or depth <= 0:
        raise ValueError("Depth must be positive")
    contour = rounded_rect_outline(width, height, radius, segments)
    n = len(contour)
    vertices = [(x, y, z) for z in (-depth/2, depth/2) for x, y in contour]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2*n))]
    faces += [(i, (i+1) % n, (i+1) % n+n, i+n) for i in range(n)]
    return vertices, faces


def screen_uv(x, y, width, height):
    """UV mapping fixed to the display; image top is the phone's +Y edge."""
    return (x/width+0.5, y/height+0.5)


def screen_geometry(geometry=None):
    g = merge(DEFAULT_GEOMETRY, geometry or {})
    margin = g["screen_margin"]
    return {"width": g["width"]-2*margin, "height": g["height"]-2*margin,
            "radius": max(g["corner_radius"]-margin, 0.001),
            "z": g["depth"]/2+0.004}


def _finite_vector(value, length, label):
    if not isinstance(value, (list, tuple)) or len(value) != length or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in value):
        raise ValueError(f"{label} must contain {length} finite numbers")


def _validate_rotation(state, label):
    if "rotation_quaternion_wxyz" in state:
        q = state["rotation_quaternion_wxyz"]
        _finite_vector(q, 4, label+".rotation_quaternion_wxyz")
        if sum(v*v for v in q) < 1e-12:
            raise ValueError("Rotation quaternion cannot be zero")
    if "rotation_matrix" in state:
        matrix = state["rotation_matrix"]
        if not isinstance(matrix, list) or len(matrix) != 3:
            raise ValueError("Rotation matrix must be 3x3")
        for row in matrix:
            _finite_vector(row, 3, label+".rotation_matrix row")
        for i in range(3):
            for j in range(3):
                if abs(sum(matrix[i][k]*matrix[j][k] for k in range(3))-(1 if i == j else 0)) > 1e-4:
                    raise ValueError("Rotation matrix must be orthonormal")
        a, b, c = matrix
        determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
        if abs(determinant-1) > 1e-4:
            raise ValueError("Rotation matrix must have determinant +1")


def _merge_pose(base, update):
    result = merge(base, update)
    rotations = {"rotation_deg", "rotation_quaternion_wxyz", "rotation_matrix"}
    supplied = rotations.intersection(update)
    if len(supplied) > 1:
        raise ValueError("Supply one orientation representation per pose")
    if supplied:
        for key in rotations-supplied:
            result.pop(key, None)
    return result


def validate_config(config):
    """Reject impossible camera/geometry and ambiguous frame schedules early."""
    c = deepcopy(config)
    if c.get("schema", SCHEMA) != SCHEMA:
        raise ValueError("Unsupported device scene schema")
    c["schema"] = SCHEMA
    resolution = c.get("resolution", [720, 1280])
    _finite_vector(resolution, 2, "resolution")
    if any(int(v) != v or v < 16 for v in resolution):
        raise ValueError("Resolution dimensions must be integers >=16")
    if int(c.get("fps", 30)) < 1 or int(c.get("samples", 12)) < 1:
        raise ValueError("fps and samples must be positive")
    if c.get("engine", "CYCLES") not in {"CYCLES", "BLENDER_EEVEE_NEXT"}:
        raise ValueError("Only real Blender render engines are supported")
    devices = c.get("devices", [{"id": "phone"}])
    if not devices or not isinstance(devices, list):
        raise ValueError("At least one device is required")
    ids = [d.get("id") for d in devices]
    if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
        raise ValueError("Device IDs must be unique nonempty strings")
    for d in devices:
        g = merge(DEFAULT_GEOMETRY, d.get("geometry", {}))
        rounded_prism(g["width"], g["height"], g["depth"], g["corner_radius"], int(g["corner_segments"]))
        if not 0 < g["screen_margin"] < min(g["width"], g["height"])/4:
            raise ValueError("Invalid screen margin")
        if not 0 <= g["edge_bevel"] < g["depth"]/2:
            raise ValueError("Invalid chassis edge bevel")
        if d.get("camera_layout", "island") not in {"island", "bar"}:
            raise ValueError("camera_layout must be island or bar")
        card_ids = [card.get("id", f"card{index+1}") for index, card in enumerate(d.get("cards", []))]
        if len(set(card_ids)) != len(card_ids):
            raise ValueError("Card IDs must be unique within a device")
        for card in d.get("cards", []):
            _finite_vector(card.get("rect_uv"), 4, "card.rect_uv")
            if min(card["rect_uv"][2:]) <= 0:
                raise ValueError("Card width and height must be positive")
    c["devices"] = devices
    frames = c.get("frames", [{"frame": 0}])
    numbers = [f.get("frame") for f in frames]
    if not frames or any(not isinstance(f, int) or f < 0 for f in numbers) or numbers != sorted(set(numbers)):
        raise ValueError("Frames must be unique, increasing nonnegative integers")
    c["frames"] = frames
    for row in frames:
        overrides = row.get("devices", {})
        if not isinstance(overrides, dict) or set(overrides)-set(ids):
            raise ValueError("Frame device overrides must reference known IDs")
        camera = merge(DEFAULT_CAMERA, merge(c.get("camera", {}), row.get("camera", {})))
        for key in ("location", "target"):
            _finite_vector(camera[key], 3, "camera."+key)
        _validate_rotation(camera, "camera")
        if "up" in camera:
            _finite_vector(camera["up"], 3, "camera.up")
            if sum(v*v for v in camera["up"]) < 1e-12:
                raise ValueError("Camera up cannot be zero")
        if not {"rotation_quaternion_wxyz", "rotation_matrix"}.intersection(camera) and math.dist(camera["location"], camera["target"]) < 1e-6:
            raise ValueError("Camera location and target must be distinct")
        for key in ("lens_mm", "sensor_width_mm"):
            if not math.isfinite(camera[key]) or camera[key] <= 0:
                raise ValueError(f"camera.{key} must be positive")
        if camera["dof"]["fstop"] <= 0:
            raise ValueError("DOF fstop must be positive")
        for d in devices:
            state = merge(d, overrides.get(d["id"], {}))
            _validate_rotation(state, d["id"])
            if state.get("style", "studio") not in {"studio", "clay", "matte"}:
                raise ValueError("style must be studio, clay or matte")
            if state.get("screen_mode", "texture") not in {"texture", "black", "color"}:
                raise ValueError("screen_mode must be texture, black or color")
            for key, default in (("location", [0, 0, 0]), ("rotation_deg", [0, 0, 0]), ("scale", [1, 1, 1])):
                _finite_vector(state.get(key, default), 3, f"{d['id']}.{key}")
            if any(v <= 0 for v in state.get("scale", [1, 1, 1])):
                raise ValueError("Device scale must be positive")
    return c


def frame_state(config, row):
    """Each row overrides the base recipe, never the previously rendered frame."""
    camera = _merge_pose(merge(DEFAULT_CAMERA, config.get("camera", {})), row.get("camera", {}))
    devices = [_merge_pose(d, row.get("devices", {}).get(d["id"], {})) for d in config["devices"]]
    return {"frame": row["frame"], "camera": camera, "devices": devices}


def load_config(path):
    path = Path(path).resolve(strict=True)
    config = validate_config(json.loads(path.read_text(encoding="utf-8")))
    # Absolute paths in the resolved recipe make a render independent of cwd.
    def resolve_assets(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"screen_texture", "back_texture", "texture"} and isinstance(item, str):
                    asset = Path(item)
                    value[key] = str((path.parent/asset).resolve()) if not asset.is_absolute() else str(asset)
                else:
                    resolve_assets(item)
        elif isinstance(value, list):
            for item in value:
                resolve_assets(item)
    resolve_assets(config)
    if "output" in config:
        config["output"] = str((path.parent/config["output"]).resolve())
    return config


def render(config_path, blender="blender", threads=4, frames=None):
    binary = shutil.which(blender)
    if not binary:
        raise FileNotFoundError("Blender is not installed")
    # Validate before starting a heavyweight process; renderer checks paths too.
    load_config(config_path)
    command = [binary, "--background", "--factory-startup", "--threads", str(threads),
               "--python-exit-code", "1", "--python", str(Path(__file__).with_name("blender_device_scene.py")),
               "--", str(Path(config_path).resolve())]
    if frames:
        command += ["--frames", ",".join(str(n) for n in frames)]
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    check = subs.add_parser("validate")
    check.add_argument("config", type=Path)
    run = subs.add_parser("render")
    run.add_argument("config", type=Path)
    run.add_argument("--blender", default="blender")
    run.add_argument("--threads", type=int, default=4)
    run.add_argument("--frames", help="Comma-separated authored frame IDs")
    args = parser.parse_args()
    if args.command == "validate":
        c = load_config(args.config)
        print(json.dumps({"schema": c["schema"], "devices": len(c["devices"]), "frames": len(c["frames"])}))
    else:
        render(args.config, args.blender, args.threads, [int(n) for n in args.frames.split(",")] if args.frames else None)


if __name__ == "__main__":
    main()
