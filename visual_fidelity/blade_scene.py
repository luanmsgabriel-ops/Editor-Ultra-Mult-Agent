"""Reusable curved solid foreground blades for typographic occlusion scenes."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess


SCHEMA = "editor-ultra.blade-scene.v1"


def swept_blade_mesh(length=3.05, width=0.075, depth=0.045, bow=0.0,
                     z_bow=0.0, steps=96, sides=24, taper=0.7):
    """Closed swept elliptical volume with rounded ends and an authored bow.

    Length follows world Y; the upper endpoint is +Y. The bow is the lateral
    displacement at the middle, while z_bow adds real camera-axis curvature.
    No textured plane or post-render perspective warp is involved.
    """
    if min(length, width, depth) <= 0 or steps < 8 or sides < 8 or not 0 < taper <= 1:
        raise ValueError("Invalid blade dimensions or topology")
    if not all(math.isfinite(x) for x in (length, width, depth, bow, z_bow, taper)):
        raise ValueError("Blade parameters must be finite")
    cap = min(width/2, length/4)
    # Uniform samples alone skip the small cap on a tall thin blade and create
    # a pointed tip. Add rings concentrated around the actual rounded ends.
    cap_t = cap/length
    samples = sorted(set([j/steps for j in range(1, steps)] +
                         [cap_t*(1-math.cos(k*math.pi/16)) for k in range(1, 9)] +
                         [1-cap_t*(1-math.cos(k*math.pi/16)) for k in range(1, 9)]))
    vertices = [(0.0, length/2, 0.0)]
    for t in samples:
        distance = min(t, 1-t)*length
        cap_factor = math.sqrt(max(0, 1-(1-distance/cap)**2)) if distance < cap else 1
        radius = cap_factor*(1-(1-taper)*t)
        cx, cy, cz = bow*math.sin(math.pi*t), (0.5-t)*length, z_bow*math.sin(math.pi*t)
        for i in range(sides):
            theta = i*2*math.pi/sides
            vertices.append((cx+math.cos(theta)*width/2*radius, cy,
                             cz+math.sin(theta)*depth/2*radius))
    bottom = len(vertices)
    vertices.append((0.0, -length/2, 0.0))
    faces = [(0, 1+(i+1) % sides, 1+i) for i in range(sides)]
    for ring in range(len(samples)-1):
        a, b = 1+ring*sides, 1+(ring+1)*sides
        faces.extend((a+i, a+(i+1) % sides, b+(i+1) % sides, b+i) for i in range(sides))
    last = 1+(len(samples)-1)*sides
    faces.extend((last+i, last+(i+1) % sides, bottom) for i in range(sides))
    return vertices, faces


def validate_config(config):
    if config.get("schema", SCHEMA) != SCHEMA:
        raise ValueError("Unsupported blade scene schema")
    if not config.get("blades") or not config.get("frames"):
        raise ValueError("Declare base blades and authored frames")
    ids = [b["id"] for b in config["blades"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Blade IDs must be unique")
    numbers = [row["frame"] for row in config["frames"]]
    if any(not isinstance(n, int) or n < 0 for n in numbers) or numbers != sorted(set(numbers)):
        raise ValueError("Frames must be increasing, unique nonnegative integers")
    for row in config["frames"]:
        if set(row.get("blades", {}))-set(ids):
            raise ValueError("Unknown blade ID in frame overrides")
    return config


def render(config, threads=2, frames=None):
    config = Path(config).resolve(strict=True)
    validate_config(json.loads(config.read_text()))
    executable = shutil.which("blender")
    if not executable:
        raise FileNotFoundError("Blender is unavailable")
    command = [executable, "-b", "--factory-startup", "--threads", str(threads),
               "--python-exit-code", "1", "--python", str(Path(__file__).with_name("blender_blade_scene.py")), "--", str(config)]
    if frames:
        command += ["--frames", ",".join(str(f) for f in frames)]
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--frames")
    args = parser.parse_args()
    render(args.config, args.threads, [int(f) for f in args.frames.split(",")] if args.frames else None)


if __name__ == "__main__":
    main()
