"""Composite the extruded Blender title into the Festival plate."""
import argparse
import json
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image, ImageFilter


def read_frame(pipe, size):
    data = pipe.read(size)
    if len(data) != size:
        raise ValueError("The stage plate ended before all requested frames.")
    return data


def perspective_coefficients(source, destination):
    system = []
    measurements = []
    for (u, v), (x, y) in zip(source, destination):
        system.extend(((x, y, 1, 0, 0, 0, -u*x, -u*y),
                       (0, 0, 0, x, y, 1, -v*x, -v*y)))
        measurements.extend((u, v))
    return np.linalg.solve(system, measurements)


def ease(progress):
    progress = min(max(progress, 0), 1)
    return progress * progress * (3 - 2 * progress)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plate", type=Path)
    parser.add_argument("letters", type=Path)
    parser.add_argument("placement", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.placement.read_text(encoding="utf-8"))
    width, height = config["resolucao"]
    start, end = config["origem_frames"]
    title = Image.open(args.letters).convert("RGBA")
    extent = np.array([(0, 0), (title.width-1, 0), (title.width-1, title.height-1), (0, title.height-1)])
    keyframes = sorted((int(frame), vertices) for frame, vertices in config["keyframes"].items())
    timestamps = [frame for frame, _ in keyframes]
    vertices = np.array([corners for _, corners in keyframes])
    source_cmd = ["ffmpeg", "-v", "error", "-threads", "2", "-i", str(args.plate), "-an", "-vf",
                  f"trim=start_frame={start}:end_frame={end},setsar=1,scale={width}:{height}",
                  "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    target_cmd = ["ffmpeg", "-y", "-v", "error", "-filter_threads", "2", "-f", "rawvideo",
                  "-pixel_format", "rgb24", "-video_size", f"{width}x{height}", "-framerate",
                  config["relogio"], "-i", "-", "-an", "-vf", "scale=out_color_matrix=bt709,format=yuv420p",
                  "-c:v", "libx264", "-threads", "3", "-crf", "16", "-color_primaries", "bt709",
                  "-color_trc", "bt709", "-colorspace", "bt709", "-movflags", "+faststart", str(args.output)]
    with subprocess.Popen(source_cmd, stdout=subprocess.PIPE) as source:
        with subprocess.Popen(target_cmd, stdin=subprocess.PIPE) as result:
            for index in range(end-start):
                pixels = read_frame(source.stdout, width * height * 3)
                plate = Image.frombytes("RGB", (width, height), pixels).convert("RGBA")
                position = np.array([np.interp(index, timestamps, vertices[:, corner, axis])
                                     for corner in range(4) for axis in range(2)]).reshape(4, 2)
                left, top = np.floor(position.min(axis=0)-12).astype(int)
                right, bottom = np.ceil(position.max(axis=0)+12).astype(int)
                crop = (left, top, right, bottom)
                scene = plate.crop(crop)
                layer = title.transform(scene.size, Image.Transform.PERSPECTIVE,
                                        tuple(perspective_coefficients(extent, position-(left, top))),
                                        Image.Resampling.BICUBIC)
                scene_array = np.asarray(scene).astype(np.float32)
                alpha = np.asarray(layer.getchannel("A")).astype(np.float32)
                luma = scene_array[..., :3] @ np.array([.50, .38, .12])
                glow = Image.new("RGBA", scene.size, (255, 143, 67, 0))
                entry = ease((index + 1) / 9)
                opacity = entry * np.clip(1.05-(luma-74)/270, .62, 1)
                layer.putalpha(Image.fromarray(np.round(alpha*opacity).astype(np.uint8)))
                glow.putalpha(layer.getchannel("A").filter(ImageFilter.GaussianBlur(4)).point(lambda a: round(a*.28)))
                scene = Image.alpha_composite(Image.alpha_composite(scene, glow), layer)
                plate.paste(scene, (left, top))
                result.stdin.write(plate.convert("RGB").tobytes())
            result.stdin.close()
            source_return = source.wait()
            result_return = result.wait()
            if source_return or result_return:
                raise RuntimeError(f"FFmpeg failed: decoder {source_return}, encoder {result_return}")


if __name__ == "__main__":
    main()
