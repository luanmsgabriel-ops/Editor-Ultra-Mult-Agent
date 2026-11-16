"""Portable, hashed RGBA motion layers shared by the three motion adapters.

Frames use a local clock. Placing a layer on footage is an explicit, one-to-one
frame mapping, never a hidden loop, hold or retime. A source binding is required
when a producer bakes source-specific placement/occlusion into its pixels.
"""

from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .contracts import (clone, file_sha256, integer, mapping, nonempty, number,
                        require, sequence, sha256, verify_file)

SCHEMA = "motion-layer/1"


def frame_rate(value) -> Fraction:
    require(isinstance(value, str), "motion_fps", "Motion FPS must be a rational string")
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError("Invalid motion frame rate") from error
    require(0 < rate <= 240, "motion_fps", "Motion FPS must be positive and at most 240")
    return rate


def validate_layer(value: dict, *, verify_files: bool = True) -> dict:
    data = clone(mapping(value, "motion_layer"))
    require(data.get("schema") == SCHEMA, "motion_schema", "Expected motion-layer/1")
    rate = frame_rate(data.get("fps"))
    count = integer(data.get("frame_count"), "frame_count", minimum=1)
    width = integer(data.get("width"), "width", minimum=2)
    height = integer(data.get("height"), "height", minimum=2)
    require(width * height <= 64_000_000, "motion_size", "Motion frame exceeds 64 million pixels")
    require(data.get("alpha") == "straight", "motion_alpha", "RGBA layers must declare straight alpha")
    origin = mapping(data.get("origin"), "origin")
    nonempty(origin.get("backend"), "origin.backend")
    nonempty(origin.get("method"), "origin.method")
    frames = sequence(data.get("frames"), "frames")
    require(len(frames) == count, "motion_gap", "Every motion frame needs a manifest entry")
    paths = set()
    for index, entry in enumerate(frames):
        mapping(entry, "frames entry")
        require(type(entry.get("index")) is int and entry["index"] == index,
                "motion_order", "Motion frames must be contiguous and ordered from zero")
        path = Path(nonempty(entry.get("path"), "frame.path"))
        require(path.is_absolute(), "motion_path", "Frame paths must be absolute")
        require(path.resolve() not in paths, "motion_duplicate", "Each frame requires its own file")
        paths.add(path.resolve())
        sha256(entry.get("sha256"), "frame.sha256")
        if "reading" in entry:
            require(type(entry["reading"]) is bool, "motion_reading", "Reading interval flags must be boolean")
        if "glyph_ids_path" in entry or "glyph_ids_sha256" in entry:
            glyph_path = Path(nonempty(entry.get("glyph_ids_path"), "glyph_ids_path"))
            require(glyph_path.is_absolute(), "motion_path", "Glyph map paths must be absolute")
            sha256(entry.get("glyph_ids_sha256"), "glyph_ids_sha256")
            if verify_files:
                verify_file(str(glyph_path), entry["glyph_ids_sha256"], "glyph map")
                with Image.open(glyph_path) as glyph_image:
                    require(glyph_image.size == (width, height) and glyph_image.mode in {"L", "I", "I;16"},
                            "glyph_map", "Glyph maps must be integer IDs at the layer raster")
        if verify_files:
            verify_file(str(path), entry["sha256"], "motion frame")
            with Image.open(path) as image:
                require(image.format == "PNG" and image.mode == "RGBA", "motion_format", "Expected a PNG with an explicit RGBA channel")
                require(image.size == (width, height), "motion_dimensions", "All motion frames must share the declared raster")
                image.verify()
    binding = data.get("source_binding")
    if binding is not None:
        mapping(binding, "source_binding")
        sha256(binding.get("source_sha256"), "source_binding.source_sha256")
        require(frame_rate(binding.get("fps")) == rate, "motion_binding_clock", "Bound motion must retain the source FPS")
        total = integer(binding.get("frame_count"), "source_binding.frame_count", minimum=1)
        first = integer(binding.get("start_frame"), "source_binding.start_frame")
        require(first + count <= total, "motion_binding_clock", "Bound motion extends past the source")
    return data


def load_layer(path: str | Path, *, verify_files: bool = True) -> dict:
    return validate_layer(json.loads(Path(path).read_text(encoding="utf-8")), verify_files=verify_files)


def write_layer_manifest(frames: list, destination: str | Path, *, fps: str,
                         backend: str, method: str, origin: dict | None = None,
                         source_binding: dict | None = None) -> dict:
    """Register actual RGBA files. Never synthesize missing frames or alpha."""
    require(bool(frames), "motion_empty", "A motion layer requires actual frame files")
    entries = []
    dimensions = None
    for index, item in enumerate(frames):
        if isinstance(item, dict):
            require(item.get("index", index) == index, "motion_order", "Producer frame order is not contiguous")
            path = Path(item["path"]).resolve()
            if "sha256" in item:
                verify_file(str(path), item["sha256"], "producer frame")
        else:
            path = Path(item).resolve()
        with Image.open(path) as image:
            dimensions = dimensions or image.size
            require(image.size == dimensions and image.mode == "RGBA" and image.format == "PNG",
                    "motion_format", "Producer must export equally sized RGBA PNGs")
        entry = {"index": index, "path": str(path), "sha256": file_sha256(path)}
        if isinstance(item, dict):
            entry.update({key: item[key] for key in ("glyph_ids_path", "glyph_ids_sha256", "reading") if key in item})
        entries.append(entry)
    result = {"schema": SCHEMA, "fps": str(frame_rate(fps)), "frame_count": len(entries),
              "width": dimensions[0], "height": dimensions[1], "alpha": "straight", "frames": entries,
              "origin": {**(origin or {}), "backend": backend, "method": method},
              "perceptual_review": "pending", "user_approval": "pending"}
    if source_binding is not None:
        result["source_binding"] = clone(source_binding)
    validate_layer(result)
    destination = Path(destination).resolve()
    require(destination not in {Path(item["path"]) for item in entries}, "motion_overwrite", "Manifest cannot overwrite a frame")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def placement(layer: dict, *, source_sha256: str, fps: Fraction, frame_count: int,
              first: int, last: int, asset_start_frame: int = 0) -> dict[int, dict]:
    """Return a complete source-frame -> asset-frame map, without time rounding."""
    data = validate_layer(layer, verify_files=False)
    require(frame_rate(data["fps"]) == fps, "motion_clock", "Motion FPS differs from the source; render the recipe at the source FPS")
    integer(asset_start_frame, "asset_start_frame")
    require(0 <= first < last <= frame_count, "motion_interval", "Motion placement must stay within the source")
    require(asset_start_frame + last - first <= data["frame_count"], "motion_short", "Motion does not cover the requested interval; no repeat or hold is permitted")
    if data.get("source_binding"):
        bound = data["source_binding"]
        require(bound["source_sha256"] == source_sha256 and bound["frame_count"] == frame_count,
                "motion_source", "Source-specific motion belongs to another source")
        require(first == bound["start_frame"] + asset_start_frame,
                "motion_binding_clock", "Source-specific motion cannot be moved to another source time")
    return {index: data["frames"][asset_start_frame + index - first] for index in range(first, last)}


def frame_rgba(entry: dict, size: tuple[int, int] | None = None) -> np.ndarray:
    verify_file(entry["path"], entry["sha256"], "motion frame at render")
    with Image.open(entry["path"]) as image:
        require(image.mode == "RGBA", "motion_format", "Motion frame lost its RGBA channel")
        if size is not None and image.size != size:
            # Resample premultiplied colour to avoid dark fringes at alpha edges.
            image = image.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")
        return np.asarray(image).copy()


def inspect_placement(entry: dict, corners: np.ndarray, resolution: tuple[int, int],
                      protected: list, *, opacity: float = 1.0, matte=None,
                      min_visible: float = 0.0, min_glyph_visible: float | None = None) -> dict:
    """Measure the actual warped alpha; never move a failing layer to the front."""
    number(min_visible, "min_visible", minimum=0, maximum=1)
    if min_glyph_visible is None:
        min_glyph_visible = .5 if "glyph_ids_path" in entry else 0
    else:
        number(min_glyph_visible, "min_glyph_visible", minimum=0, maximum=1)
        require(min_glyph_visible == 0 or "glyph_ids_path" in entry, "motion_glyph_ids",
                "An explicit glyph visibility floor requires an actual glyph-ID pass")
    art = frame_rgba(entry)
    height, width = art.shape[:2]
    target_w, target_h = resolution
    source_corners = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    target_corners = (np.asarray(corners, dtype="float32") * resolution).astype("float32")
    matrix = cv2.getPerspectiveTransform(source_corners, target_corners)
    from visual_fidelity.anchor_graphics import warp_rgba_patch
    warped = warp_rgba_patch(art, corners, resolution)
    alpha = np.zeros((target_h, target_w), np.float32)
    if warped is not None:
        px, py, patch = warped
        ph, pw = patch.shape[:2]
        alpha[py:py + ph, px:px + pw] = patch[:, :, 3] * opacity
    original_mass = float(alpha.sum())
    unoccluded = alpha.copy()
    if matte is not None:
        require(matte.shape == (target_h, target_w), "motion_matte", "Occlusion matte must match source dimensions")
        alpha *= 1 - matte.astype("float32") / 255
    visible_mass = float(alpha.sum())
    ratio = visible_mass / original_mass if original_mass > 1e-6 else 1.0
    require(ratio + 1e-6 >= min_visible, "motion_occlusion", "Requested layer visibility is impossible with this matte; revise the direction")
    glyph_visibility = []
    if "glyph_ids_path" in entry and entry.get("reading", True) and original_mass > 1e-6:
        verify_file(entry["glyph_ids_path"], entry["glyph_ids_sha256"], "glyph map at placement")
        with Image.open(entry["glyph_ids_path"]) as image:
            ids = np.asarray(image).astype("uint16")
        require(ids.shape == art.shape[:2], "glyph_map", "Glyph map raster differs from the motion frame")
        warped_ids = cv2.warpPerspective(ids, matrix, resolution, flags=cv2.INTER_NEAREST)
        for glyph in np.unique(ids):
            if glyph == 0:
                continue
            pixels = warped_ids == glyph
            before, after = float(unoccluded[pixels].sum()), float(alpha[pixels].sum())
            visible = after / before if before > 1e-6 else 0.0
            require(visible + 1e-6 >= min_glyph_visible, "motion_glyph_occlusion",
                    "An individual glyph fails the requested visibility floor; revise the direction")
            glyph_visibility.append({"glyph_id": int(glyph), "visible_fraction": visible})
    for box in protected:
        x0, y0 = max(0, math.floor(box[0] * target_w)), max(0, math.floor(box[1] * target_h))
        x1, y1 = min(target_w, math.ceil(box[2] * target_w)), min(target_h, math.ceil(box[3] * target_h))
        require(not np.any(alpha[y0:y1, x0:x1] > 1 / 255), "protected_overlap",
                "Animated motion covers a protected face or hand; revise placement or provide valid occlusion")
    return {"visible_alpha_sum": visible_mass, "visible_fraction": ratio,
            "occluded_fraction": 1 - ratio, "frame_index": entry["index"], "glyph_visibility": glyph_visibility,
            "glyph_visibility_status": "measured" if glyph_visibility else "not_measured"}


def contact_sheet(layer: dict, *, maximum: int = 4) -> Image.Image:
    """Labelled frame samples are a preview, never continuous-motion review."""
    data = validate_layer(layer, verify_files=False)
    indices = sorted({round(i * (data["frame_count"] - 1) / max(maximum - 1, 1)) for i in range(maximum)})
    from PIL import ImageDraw
    sheet = Image.new("RGBA", (256 * len(indices), 280), (32, 32, 32, 255))
    draw = ImageDraw.Draw(sheet)
    for column, index in enumerate(indices):
        frame = Image.fromarray(frame_rgba(data["frames"][index]))
        frame.thumbnail((256, 256))
        sheet.alpha_composite(frame, (column * 256 + (256 - frame.width) // 2, (256 - frame.height) // 2))
        draw.text((column * 256 + 8, 260), f"frame {index} | {float(index / frame_rate(data['fps'])):.3f}s", fill="white")
    return sheet
