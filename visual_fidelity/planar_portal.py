"""Authored four-corner reveals with independent, hashed photographic sources.

This module performs no tracking, inpainting, generation or editorial selection.
``screen_reveal`` gates an upright canvas placement; ``projective`` warps a
source quadrilateral. Both operate in premultiplied alpha, on explicit clocks.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np

from .geometric_replay import _rgba

VERSION = "1.1.0"
SCHEMA = "planar-portal/1"
_UNIT_QUAD = [[0, 0], [1, 0], [1, 1], [0, 1]]
_EASINGS = {"linear", "hold", "smoothstep"}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sequence_sha256(files):
    """Digest ordered frame SHA-256 values, independent of their folder names."""
    if not isinstance(files, list) or not files:
        raise ValueError("Sequence needs an ordered, nonempty files list")
    values = [_digest(_object(entry, "sequence file").get("sha256")) for entry in files]
    return hashlib.sha256("\n".join(values).encode("ascii")).hexdigest()


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a lowercase SHA-256 digest")
    return value


def _object(value, name):
    if not isinstance(value, dict):
        raise ValueError(name + " must be an object")
    return value


def _positive_fraction(value, name):
    if not isinstance(value, str):
        raise ValueError(name + " must be an explicit rational string")
    try:
        result = Fraction(value)
    except (ValueError, TypeError, ZeroDivisionError) as error:
        raise ValueError(name + " must be a valid positive rational") from error
    if result <= 0:
        raise ValueError(name + " must be a valid positive rational")
    return result


def _number(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)) or not math.isfinite(float(value)):
        raise ValueError(name + " must be finite numeric data")
    return float(value)


def _integer(value, name, minimum=0):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
        raise ValueError(name + f" must be an integer >= {minimum}")
    return int(value)


def _quad(value, *, closed=False):
    try:
        points = np.asarray(value, dtype=np.float64)
    except (ValueError, TypeError) as error:
        raise ValueError("quad needs four finite points") from error
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("quad needs four finite points")
    if np.abs(points).max() > 1000:
        raise ValueError("quad exceeds the rasterizer coordinate range")
    edges = np.roll(points, -1, axis=0) - points
    following = np.roll(edges, -1, axis=0)
    cross = edges[:, 0] * following[:, 1] - edges[:, 1] * following[:, 0]
    # Clockwise in image coordinates. A collapsed line is legal only at alpha 0;
    # bow-ties, concave shapes, reversed order and repeated visible corners fail.
    if closed and np.all(np.abs(cross) <= 1e-12):
        return points
    if not np.all(cross > 1e-12):
        raise ValueError("quad must be convex, nondegenerate and clockwise; collapse requires opacity 0")
    return points


def _key_states(keyframes):
    if not isinstance(keyframes, list) or not keyframes:
        raise ValueError("Explicit geometry keyframes are required")
    states = []
    last = -1
    for key in keyframes:
        key = _object(key, "keyframe")
        frame = _integer(key.get("frame"), "keyframe frame")
        if frame <= last:
            raise ValueError("Keyframe frames must increase strictly")
        opacity = _number(key.get("opacity"), "opacity")
        if not 0 <= opacity <= 1:
            raise ValueError("opacity must be in [0,1]")
        easing = key.get("easing")
        if not isinstance(easing, str) or easing not in _EASINGS:
            raise ValueError("Every key needs explicit linear, hold or smoothstep easing")
        states.append((frame, _quad(key.get("quad"), closed=opacity == 0), opacity, easing))
        last = frame
    return states


def _evaluate(states, frame):
    frame = _integer(frame, "frame")
    if not states[0][0] <= frame <= states[-1][0]:
        raise ValueError("Geometry must cover the requested frame; no implicit end hold")
    index = bisect_right([state[0] for state in states], frame) - 1
    a = states[index]
    if frame == a[0] or index == len(states) - 1:
        quad, opacity = a[1].copy(), a[2]
    else:
        b = states[index + 1]
        t = (frame - a[0]) / (b[0] - a[0])
        if a[3] == "hold":
            t = 0.0
        elif a[3] == "smoothstep":
            t = t * t * (3 - 2 * t)
        quad = a[1] + (b[1] - a[1]) * t
        opacity = a[2] + (b[2] - a[2]) * t
    return {"quad": _quad(quad, closed=opacity == 0).tolist(), "opacity": float(opacity)}


def evaluate_quad(keyframes, frame):
    """Evaluate authored geometry; each key's easing controls its outgoing span.

    Interpolated visible quadrilaterals are validated, not merely their keys.
    Coordinates are normalized canvas *edges*, clockwise in image coordinates.
    Corners may lie outside the canvas. No extrapolation or randomization occurs.
    """
    return _evaluate(_key_states(keyframes), frame)


def _coverage_roi(points, size, bounds, feather_px):
    """Same 4x polygon rasterization as geometric_replay, without canvas grids."""
    width, height = size
    x0, y0, x1, y1 = bounds
    # GaussianBlur's float kernel reaches four sigma. Preserve context outside
    # the requested patch so clipping a placement never changes its feather.
    pad = int(math.ceil(4 * feather_px)) + 3 if feather_px else 0
    pixels = points * [width, height]
    if np.abs(pixels).max() > 1e6:
        raise ValueError("Polygon coordinates exceed rasterizer range")
    # Keep every in-canvas vertex in the rasterizer patch. OpenCV's integer
    # line clipping can otherwise change edge rounding when a placement crops
    # an edge halfway along its slope, even after exact coordinate translation.
    low = np.floor(pixels.min(axis=0)).astype(int) - 2 - pad
    high = np.ceil(pixels.max(axis=0)).astype(int) + 2 + pad
    mx0, my0 = max(0, min(x0 - pad, low[0])), max(0, min(y0 - pad, low[1]))
    mx1, my1 = min(width, max(x1 + pad, high[0])), min(height, max(y1 + pad, high[1]))
    # Quantize in the original canvas before subtracting an integer offset;
    # this preserves fractional-edge rounding from the full-frame renderer.
    coordinates = np.rint((pixels * 4 - .5) * 256).astype(np.int64)
    coordinates -= [mx0 * 4 * 256, my0 * 4 * 256]
    supersampled = np.zeros(((my1 - my0) * 4, (mx1 - mx0) * 4), dtype=np.uint8)
    cv2.fillPoly(supersampled, [coordinates.astype(np.int32)], 255, lineType=cv2.LINE_8, shift=8)
    coverage = cv2.resize(supersampled, (mx1 - mx0, my1 - my0), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    if feather_px:
        coverage = cv2.GaussianBlur(coverage, (0, 0), feather_px, borderType=cv2.BORDER_CONSTANT)
    return coverage[y0 - my0:y1 - my0, x0 - mx0:x1 - mx0].copy()


def _compose_opaque(base, layer, block_rows=64):
    """Equivalent uint8 straight-alpha blend, with bounded float working rows."""
    result = base.copy()
    for first in range(0, len(base), block_rows):
        last = min(first + block_rows, len(base))
        block = layer[first:last]
        if not np.any(block[:, :, 3]):
            continue
        if np.all(block[:, :, 3] == 255):
            result[first:last] = block[:, :, :3]
            continue
        alpha = block[:, :, 3:4].astype(np.float32) / 255
        foreground = block[:, :, :3].astype(np.float32) / 255
        background = base[first:last].astype(np.float32) / 255
        foreground *= alpha
        background *= 1 - alpha
        foreground += background
        np.clip(foreground, 0, 1, out=foreground)
        foreground *= 255
        np.rint(foreground, out=foreground)
        result[first:last] = foreground.astype(np.uint8)
    return result


def render_portal_frame(insert, quad, canvas_size, *, mapping, placement=None,
                        source_quad=None, opacity=1.0, feather_px=0.0,
                        occlusion=None, alignment_matrix=None):
    """Return straight uint8 RGBA at ``(width, height)``; inputs are RGB(A).

    ``screen_reveal`` requires normalized ``placement=[x,y,width,height]`` and
    does not rotate its contents with the visibility polygon. ``projective``
    maps a normalized source quad (full image by default) onto the target quad.
    White occlusion keeps the base in front, and black leaves the portal visible.
    Placement is an explicitly sized rectangle, with no automatic contain/crop.
    """
    width = _integer(canvas_size[0], "width", 1)
    height = _integer(canvas_size[1], "height", 1)
    if width * height > 64_000_000:
        raise ValueError("Canvas exceeds 64 million pixels")
    opacity = _number(opacity, "opacity")
    feather_px = _number(feather_px, "feather_px")
    if not 0 <= opacity <= 1 or not 0 <= feather_px <= 128:
        raise ValueError("opacity must be [0,1] and feather_px [0,128]")
    target = _quad(quad, closed=opacity == 0)
    art = _rgba(insert, "insert")
    source_h, source_w = art.shape[:2]
    if mapping == "screen_reveal":
        if source_quad is not None:
            raise ValueError("source_quad applies only to projective mapping")
        if alignment_matrix is not None:
            if placement is not None:
                raise ValueError("Subject alignment and placement are mutually exclusive")
            matrix = np.asarray(alignment_matrix, dtype=np.float64)
            if matrix.shape != (2, 3) or not np.isfinite(matrix).all():
                raise ValueError("Alignment matrix must be finite 2x3")
            linear = matrix[:, :2]
            gram = linear.T @ linear
            if np.linalg.det(linear) <= 0 or not np.allclose(gram, np.eye(2) * gram[0, 0], rtol=1e-7, atol=1e-8):
                raise ValueError("Subject alignment must preserve aspect ratio and orientation")
            corners = np.asarray(_UNIT_QUAD) * [source_w, source_h] - .5
            mapped = _quad((corners @ linear.T + matrix[:, 2] + .5) / [width, height])
            scale = math.sqrt(float(gram[0, 0]))
            interpolation_pad = np.array([math.ceil(scale) + 2] * 2)
        else:
            if not isinstance(placement, (list, tuple)) or len(placement) != 4:
                raise ValueError("screen_reveal requires placement [x,y,width,height]")
            x, y, w, h = [_number(v, "placement") for v in placement]
            if w <= 0 or h <= 0:
                raise ValueError("placement width and height must be positive")
            mapped = _quad([[x, y], [x + w, y], [x + w, y + h], [x, y + h]])
            interpolation_pad = np.ceil([(w * width) / source_w, (h * height) / source_h]).astype(int) + 2
        source = np.array(_UNIT_QUAD, dtype=np.float64)
    elif mapping == "projective":
        if alignment_matrix is not None:
            raise ValueError("Subject alignment uses screen_reveal; the portal window stays separate")
        if placement is not None:
            raise ValueError("placement applies only to screen_reveal mapping")
        mapped = target
        source = _quad(_UNIT_QUAD if source_quad is None else source_quad)
        if np.any((source < 0) | (source > 1)):
            raise ValueError("source_quad must lie inside the insert")
    else:
        raise ValueError("mapping must explicitly be screen_reveal or projective")
    if occlusion is not None:
        matte = np.asarray(occlusion)
        if matte.shape != (height, width):
            raise ValueError("Occlusion must have the exact canvas raster")
        if matte.dtype == np.uint8:
            matte = matte.astype(np.float32) / 255
        elif np.issubdtype(matte.dtype, np.floating):
            matte = matte.astype(np.float32)
        else:
            raise ValueError("Occlusion must be uint8 or float [0,1]")
        if not np.isfinite(matte).all() or np.any((matte < 0) | (matte > 1)):
            raise ValueError("Occlusion must be finite [0,1]")
    if opacity == 0:
        return np.zeros((height, width, 4), dtype=np.uint8)
    margin = int(math.ceil(4 * feather_px)) + 2
    pixels = target * [width, height]
    lower = np.floor(pixels.min(axis=0)).astype(int) - margin
    upper = np.ceil(pixels.max(axis=0)).astype(int) + margin
    if mapping == "screen_reveal":
        placed = mapped * [width, height]
        # Bilinear sampling has a one-source-pixel footprint beyond the image.
        lower = np.maximum(lower, np.floor(placed.min(axis=0)).astype(int) - interpolation_pad)
        upper = np.minimum(upper, np.ceil(placed.max(axis=0)).astype(int) + interpolation_pad)
    x0, y0 = np.maximum(lower, [0, 0])
    x1, y1 = np.minimum(upper, [width, height])
    output = np.zeros((height, width, 4), dtype=np.uint8)
    if x1 <= x0 or y1 <= y0:
        return output
    # Convert edge coordinates to OpenCV's integer-indexed pixel centers.
    from_points = (source * [source_w, source_h] - .5).astype(np.float32)
    to_points = (mapped * [width, height] - .5).astype(np.float32)
    homography = cv2.getPerspectiveTransform(from_points, to_points)
    homography[0] -= x0 * homography[2]
    homography[1] -= y0 * homography[2]
    premultiplied = art.copy()
    premultiplied[:, :, :3] *= premultiplied[:, :, 3:4]
    warped = cv2.warpPerspective(premultiplied, homography, (int(x1 - x0), int(y1 - y0)),
                                 flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                                 borderValue=(0, 0, 0, 0))
    coverage = _coverage_roi(target, (width, height), (x0, y0, x1, y1), feather_px)
    coverage *= opacity
    if occlusion is not None:
        coverage *= 1 - matte[y0:y1, x0:x1]
    warped *= coverage[:, :, None]
    alpha = warped[:, :, 3:4]
    rgb = np.divide(warped[:, :, :3], alpha, out=np.zeros_like(warped[:, :, :3]), where=alpha > 0)
    output[y0:y1, x0:x1] = np.rint(np.clip(np.concatenate([rgb, alpha], axis=2), 0, 1) * 255).astype(np.uint8)
    return output


def _probe_video(path, rate):
    result = subprocess.run(["ffprobe", "-v", "error", "-threads", "1", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height,avg_frame_rate,time_base:frame=best_effort_timestamp_time,width,height",
                             "-show_frames", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True)
    data = json.loads(result.stdout)
    if not data.get("streams") or not data.get("frames"):
        raise ValueError("Video has no decodable frames: " + str(path))
    stream = data["streams"][0]
    if any((frame.get("width"), frame.get("height")) != (stream["width"], stream["height"])
           for frame in data["frames"]):
        raise ValueError("Video raster changes inside the declared source")
    if _positive_fraction(stream["avg_frame_rate"], "Video FPS") != rate:
        raise ValueError("Video FPS differs from the output; no implicit retime")
    timestamps = [float(frame["best_effort_timestamp_time"]) for frame in data["frames"]]
    tolerance = max(2 * float(_positive_fraction(stream["time_base"], "Video time base")), 2e-6)
    expected = np.arange(len(timestamps), dtype=np.float64) / float(rate) + timestamps[0]
    if not np.isfinite(timestamps).all() or np.max(np.abs(expected - timestamps)) > tolerance:
        raise ValueError("Video presentation timestamps do not follow the declared constant cadence")
    return {"width": int(stream["width"]), "height": int(stream["height"]),
            "frames": len(timestamps), "first_pts": timestamps[0]}


class _Source:
    def __init__(self, data, root, count, rate, label):
        if not isinstance(data, dict) or not isinstance(data.get("origin"), str) or not data["origin"].strip():
            raise ValueError(label + " requires a declared origin")
        self.data = data
        self.label = label
        self.kind = data.get("kind")
        self.digest = _digest(data.get("sha256"))
        self.paths = []
        self.digests = []
        self.cap = None
        self.cached = None
        self.next_frame = 0
        self.shape = None
        self.metadata = {}
        if self.kind == "sequence":
            entries = data.get("files")
            if sequence_sha256(entries) != self.digest:
                raise ValueError(label + " sequence digest mismatch")
        elif self.kind in {"image", "video"}:
            entries = [{"path": data.get("path"), "sha256": self.digest}]
        else:
            raise ValueError(label + " kind must be image, video or sequence")
        for entry in entries:
            if not isinstance(entry.get("path"), str) or not entry["path"]:
                raise ValueError(label + " source path is missing")
            path = (root / entry["path"]).resolve()
            digest = _digest(entry.get("sha256"))
            if not path.is_file() or file_sha256(path) != digest:
                raise ValueError(label + " missing file or SHA-256 mismatch: " + str(path))
            self.paths.append(path)
            self.digests.append(digest)
        if len(set(self.paths)) != len(self.paths):
            raise ValueError(label + " sequence cannot silently reuse a frame file")
        if self.kind == "image":
            if data.get("static") is not True or "clock" in data:
                raise ValueError(label + " image needs static:true and no video clock")
            self.start = 0
            self.total = count
        else:
            clock = _object(data.get("clock", {}), label + " clock")
            self.start = _integer(clock.get("start_frame"), label + " start_frame")
            if type(clock.get("step")) is not int or clock["step"] != 1:
                raise ValueError(label + " requires explicit step:1; retime/loop/freeze is unsupported")
            if self.kind == "sequence":
                if _positive_fraction(data.get("fps"), label + " sequence FPS") != rate:
                    raise ValueError(label + " sequence must declare the output FPS")
                self.total = len(self.paths)
            else:
                self.metadata = _probe_video(self.paths[0], rate)
                self.total = self.metadata["frames"]
            if self.start + count > self.total:
                raise ValueError(label + " does not cover every output frame")

    def read(self, output_frame):
        index = self.start + output_frame
        if self.kind == "video":
            if self.cap is None:
                if not hasattr(cv2, "CAP_PROP_N_THREADS"):
                    raise ValueError("OpenCV must expose CAP_PROP_N_THREADS for bounded video decoding")
                self.cap = cv2.VideoCapture(str(self.paths[0]), cv2.CAP_FFMPEG,
                                           [cv2.CAP_PROP_N_THREADS, 1])
                if not self.cap.isOpened():
                    raise ValueError("Cannot decode " + str(self.paths[0]))
                # Decode from the start instead of relying on approximate seeking.
                for _ in range(self.start):
                    if not self.cap.grab():
                        raise ValueError(self.label + " failed before its start frame")
                self.next_frame = self.start
            if index != self.next_frame:
                raise ValueError("Portal readers require sequential output frames")
            ok, value = self.cap.read()
            if not ok:
                raise ValueError(self.label + " failed to decode source frame " + str(index))
            self.next_frame += 1
        elif self.kind == "image" and self.cached is not None:
            return self.cached
        else:
            path = self.paths[index if self.kind == "sequence" else 0]
            value = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if value is None:
                raise ValueError("Cannot decode " + str(path))
        if value.dtype != np.uint8:
            raise ValueError(self.label + " requires 8-bit media")
        if value.ndim == 2:
            value = cv2.cvtColor(value, cv2.COLOR_GRAY2RGB)
        elif value.shape[2] == 4:
            value = cv2.cvtColor(value, cv2.COLOR_BGRA2RGBA)
        else:
            value = cv2.cvtColor(value, cv2.COLOR_BGR2RGB)
        if self.shape is not None and value.shape != self.shape:
            raise ValueError(self.label + " raster/channels changed during the sequence")
        self.shape = value.shape
        if self.kind == "image":
            self.cached = value
        return value

    def verify_unchanged(self):
        for path, expected in zip(self.paths, self.digests):
            if file_sha256(path) != expected:
                raise ValueError(self.label + " changed during rendering")

    def close(self):
        if self.cap is not None:
            self.cap.release()

    def receipt(self):
        return {"kind": self.kind, "sha256": self.digest, "origin": self.data["origin"],
                "files": [{"path": str(path), "sha256": digest} for path, digest in zip(self.paths, self.digests)],
                "start_frame": self.start, "step": 1 if self.kind != "image" else None,
                "static": self.kind == "image", "source_frames": self.total,
                "metadata": self.metadata}


def _alignment_frames(data, sources, states, count, rate, width, height):
    """Bind calibration to the real media before any output is written."""
    if data.get("subject_alignment") is None:
        return {}, None
    from .subject_alignment import validate_alignment_binding
    config = _object(data["subject_alignment"], "subject_alignment")
    if data.get("mapping") != "screen_reveal" or data.get("placement") is not None or data.get("source_quad") is not None:
        raise ValueError("Subject alignment requires screen_reveal without placement/source_quad")
    if "base" not in sources:
        raise ValueError("Subject alignment requires its actual base source")
    policy = config.get("uncovered_policy")
    if policy not in {"reject", "reveal_base"}:
        raise ValueError("Declare uncovered_policy reject or reveal_base; missing scenery is never synthesized")
    bindings = {}
    for side, name in (("source", "insert"), ("base", "base")):
        source = sources[name]
        if source.kind == "video":
            raster = [source.metadata["width"], source.metadata["height"]]
        else:
            from PIL import Image
            with Image.open(source.paths[0]) as image:
                raster = list(image.size)
            if source.kind == "sequence":
                for path in source.paths[1:]:
                    with Image.open(path) as image:
                        if list(image.size) != raster:
                            raise ValueError("Alignment source sequence raster changes between frames")
        bindings[side] = {"kind": source.kind, "sha256": source.digest, "raster": raster,
            "viewport_xywh": source.data.get("viewport_xywh", [0, 0, *raster]),
            "fps": str(rate), "frames": 1 if source.kind == "image" else source.total,
            "revision": source.data.get("revision"),
            "clock": {"start_frame": source.start, "step": 0 if source.kind == "image" else 1}}
    bindings["timeline"] = {"revision": data.get("revision"), "raster": [width, height],
                            "fps": str(rate), "frames": count}
    plan = config.get("plan")
    validate_alignment_binding(plan, bindings)
    samples = {sample["frame"]: sample for sample in plan["frames"]}
    visible = [frame for frame in range(count) if _evaluate(states, frame)["opacity"] > 0]
    if any(frame not in samples or samples[frame]["status"] != "ready" for frame in visible):
        raise ValueError("Every visible portal frame needs its own valid alignment sample; no implicit holds")
    return samples, policy


def render(manifest, output_path, *, mode="composite"):
    """Render verified sources to silent MP4 or a PNG RGBA layer directory.

    ``manifest`` is a JSON path, so relative media paths have an unambiguous
    root. Output and receipt must not already exist. Audio belongs to the parent
    timeline and is deliberately not read, mixed, faded or generated here.
    """
    manifest = Path(manifest).resolve()
    manifest_bytes = manifest.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    data = _object(json.loads(manifest_bytes), "manifest")
    if data.get("schema") != SCHEMA:
        raise ValueError("Expected " + SCHEMA)
    if "audio" in data:
        raise ValueError("Portal render is silent; bind audio in the parent timeline")
    if mode not in {"composite", "layer"}:
        raise ValueError("mode must be composite or layer")
    width = _integer(data.get("width"), "width", 2)
    height = _integer(data.get("height"), "height", 2)
    count = _integer(data.get("frames"), "frames", 1)
    if width * height > 64_000_000 or (mode == "composite" and (width % 2 or height % 2)):
        raise ValueError("MP4 needs even dimensions; canvas limit is 64 million pixels")
    rate = _positive_fraction(data.get("fps"), "fps")
    if rate > 240:
        raise ValueError("fps must be positive and at most 240")
    states = _key_states(_object(data.get("geometry"), "geometry").get("keyframes"))
    if states[0][0] != 0 or states[-1][0] != count - 1:
        raise ValueError("Geometry keyframes must cover exactly frames 0 through frames-1")
    # Fail before writing output if any interpolated visible quad folds over.
    for frame in range(count):
        _evaluate(states, frame)
    output = Path(output_path).resolve()
    receipt_path = output.with_suffix(output.suffix + ".json") if mode == "composite" else output / "portal-render.json"
    if output.exists() or receipt_path.exists():
        raise ValueError("Output/receipt already exists; choose a new path")
    if mode == "composite" and output.suffix.lower() != ".mp4":
        raise ValueError("Composite output must be .mp4")
    sources = {}
    encoder = None
    error_stream = None
    output_created = False
    previous_cv_threads = cv2.getNumThreads()
    cv2.setNumThreads(1)
    try:
        sources["insert"] = _Source(data.get("insert"), manifest.parent, count, rate, "insert")
        if data.get("base") is not None:
            sources["base"] = _Source(data["base"], manifest.parent, count, rate, "base")
            if sources["base"].digest == sources["insert"].digest or set(sources["base"].paths) & set(sources["insert"].paths):
                raise ValueError("Base and insert must be independent, separately hashed sources")
        elif mode == "composite":
            raise ValueError("Composite rendering requires a base source")
        if data.get("occlusion") is not None:
            occlusion = _object(data["occlusion"], "occlusion")
            if "base" not in sources or occlusion.get("base_sha256") != sources["base"].digest:
                raise ValueError("Occlusion must bind to the actual base SHA-256")
            if occlusion.get("coordinate_space") != "canvas":
                raise ValueError("Occlusion must explicitly use canvas coordinates")
            sources["occlusion"] = _Source(occlusion.get("source"), manifest.parent, count, rate, "occlusion")
            if sources["occlusion"].kind == "image" and sources["base"].kind != "image":
                raise ValueError("Moving footage requires a temporal occlusion sequence/video")
            if sources["occlusion"].start != sources["base"].start:
                raise ValueError("Occlusion and base start frames must match")
        if output == manifest or any(output in source.paths for source in sources.values()):
            raise ValueError("Output cannot overwrite inputs")
        alignment, uncovered_policy = _alignment_frames(data, sources, states, count, rate, width, height)
        uncovered_frames = []
        output.parent.mkdir(parents=True, exist_ok=True)
        frame_entries = []
        raw_digest = hashlib.sha256()
        with tempfile.TemporaryDirectory(prefix=".planar-portal-", dir=output.parent) as temporary:
            temp = Path(temporary)
            if mode == "composite":
                error_stream = (temp / "ffmpeg.log").open("w+b")
                encoder = subprocess.Popen(["ffmpeg", "-v", "error", "-n", "-filter_threads", "1", "-f", "rawvideo",
                    "-pix_fmt", "rgb24", "-video_size", f"{width}x{height}", "-framerate", str(rate),
                    "-threads", "1", "-i", "pipe:0", "-an",
                    "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                    "-c:v", "libx264", "-threads", "2",
                    "-tune", "zerolatency", "-crf", "17", "-pix_fmt", "yuv420p",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-movflags", "+faststart", str(temp / "render.mp4")],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=error_stream)
            for frame in range(count):
                current = _evaluate(states, frame)
                art = sources["insert"].read(frame)
                matte = None
                if "occlusion" in sources:
                    image = sources["occlusion"].read(frame)
                    if image.shape[:2] != (height, width):
                        raise ValueError("Occlusion raster differs from canvas")
                    if np.any(image[:, :, :3] != image[:, :, :1]):
                        raise ValueError("Occlusion must be grayscale; no implicit channel/color conversion")
                    if image.shape[2] == 4 and np.any(image[:, :, 3] != 255):
                        raise ValueError("Occlusion coverage is grayscale, not an ambiguous RGBA alpha")
                    matte = image[:, :, 0]
                aligned = alignment.get(frame) if current["opacity"] > 0 else None
                placement = data.get("placement")
                if alignment and aligned is None:
                    placement = [0, 0, 1, 1]  # Invisible frames require no fitted content.
                layer = render_portal_frame(art, current["quad"], (width, height),
                    mapping=data.get("mapping"), placement=placement,
                    source_quad=data.get("source_quad"), opacity=current["opacity"],
                    feather_px=data.get("feather_px", 0), occlusion=matte,
                    alignment_matrix=aligned["matrix"] if aligned else None)
                if aligned is not None:
                    gate = _coverage_roi(np.asarray(current["quad"]), (width, height),
                                         (0, 0, width, height), data.get("feather_px", 0))
                    gate *= current["opacity"]
                    if matte is not None:
                        gate *= 1 - matte.astype(np.float32) / 255
                    expected_alpha = gate * 255
                    uncovered = int(np.count_nonzero((expected_alpha > 3) &
                                                       (layer[:, :, 3].astype(np.float32) < expected_alpha - 3)))
                    if uncovered:
                        if uncovered_policy == "reject":
                            raise ValueError(f"Aligned content leaves {uncovered} uncovered portal pixels at frame {frame}; supply background or explicitly allow the independent base")
                        uncovered_frames.append({"frame": frame, "pixels": uncovered})
                if mode == "composite":
                    base = sources["base"].read(frame)
                    if base.shape[:2] != (height, width) or (base.shape[2] == 4 and np.any(base[:, :, 3] != 255)):
                        raise ValueError("Base must be opaque at the exact canvas raster")
                    result = _compose_opaque(base[:, :, :3], layer)
                    raw_digest.update(result.tobytes())
                    encoder.stdin.write(result.tobytes())
                else:
                    path = temp / f"frame-{frame:06d}.png"
                    if not cv2.imwrite(str(path), cv2.cvtColor(layer, cv2.COLOR_RGBA2BGRA)):
                        raise ValueError("Failed to write portal layer frame")
                    raw_digest.update(layer.tobytes())
                    frame_entries.append({"index": frame, "path": str(output / path.name), "sha256": file_sha256(path)})
            if encoder is not None:
                encoder.stdin.close()
                if encoder.wait() != 0:
                    error_stream.seek(0)
                    raise RuntimeError("FFmpeg failed: " + error_stream.read().decode("utf-8", "replace")[-4000:])
                error_stream.close()
                error_stream = None
                encoder = None
                measured = _probe_video(temp / "render.mp4", rate)
                if (measured["width"], measured["height"], measured["frames"]) != (width, height, count):
                    raise ValueError("Encoded MP4 raster/frame count differs from the authored timeline")
            for source in sources.values():
                source.verify_unchanged()
            if file_sha256(manifest) != manifest_hash:
                raise ValueError("Manifest changed during rendering")
            receipt = {"schema": "planar-portal-render/1", "engine_version": VERSION,
                "manifest_path": str(manifest), "manifest_sha256": manifest_hash,
                "mode": mode, "mapping": data["mapping"], "width": width, "height": height,
                "fps": str(rate), "frames": count, "duration": str(Fraction(count) / rate),
                "output_path": str(output), "raw_frames_sha256": raw_digest.hexdigest(),
                "sources": {name: source.receipt() for name, source in sources.items()},
                "audio": "not_rendered", "visual_review": "pending", "continuous_playback": "pending",
                "user_approval": "pending", "hidden_content_recovery": "not_performed"}
            if alignment:
                receipt["subject_alignment"] = {"plan_sha256": data["subject_alignment"]["plan"]["sha256"],
                    "uncovered_policy": uncovered_policy, "uncovered_frames": uncovered_frames,
                    "transform": "uniform_2d_similarity", "depth_reconstruction": False}
            if mode == "composite":
                receipt["encoded_verification"] = measured
                receipt["output_sha256"] = file_sha256(temp / "render.mp4")
                # Hard-link creation is atomic and refuses an existing destination.
                os.link(temp / "render.mp4", output)
                output_created = True
            else:
                output.mkdir(exist_ok=False)
                output_created = True
                for entry in frame_entries:
                    os.link(temp / Path(entry["path"]).name, entry["path"])
                from editorial_engine.motion_assets import write_layer_manifest
                binding = None
                if "base" in sources and sources["base"].kind != "image":
                    base = sources["base"]
                    binding = {"source_sha256": base.digest, "fps": str(rate),
                               "frame_count": base.total, "start_frame": base.start}
                layer_manifest = write_layer_manifest(frame_entries, output / "motion-layer.json",
                    fps=str(rate), backend="visual_fidelity.planar_portal", method=data["mapping"],
                    origin={"engine_version": VERSION, "manifest_sha256": manifest_hash}, source_binding=binding)
                receipt["layer_manifest"] = str(output / "motion-layer.json")
                receipt["layer_manifest_sha256"] = file_sha256(output / "motion-layer.json")
                receipt["frame_files"] = len(layer_manifest["frames"])
            with receipt_path.open("x", encoding="utf-8") as stream:
                json.dump(receipt, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.write("\n")
            return receipt
    except Exception:
        # Outputs published by this call are incomplete if no receipt succeeded.
        # Never delete caller-owned existing outputs or inputs.
        if output_created and mode == "composite":
            output.unlink(missing_ok=True)
        elif output_created:
            shutil.rmtree(output)
        raise
    finally:
        if encoder is not None:
            if encoder.stdin and not encoder.stdin.closed:
                try:
                    encoder.stdin.close()
                except BrokenPipeError:
                    pass
            if encoder.poll() is None:
                encoder.kill()
            encoder.wait()
        if error_stream is not None:
            error_stream.close()
        for source in sources.values():
            source.close()
        cv2.setNumThreads(previous_cv_threads)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="planar-portal/1 JSON")
    parser.add_argument("output", help="New .mp4 file or new PNG layer directory")
    parser.add_argument("--mode", choices=("composite", "layer"), default="composite")
    args = parser.parse_args()
    print(json.dumps(render(args.manifest, args.output, mode=args.mode), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
