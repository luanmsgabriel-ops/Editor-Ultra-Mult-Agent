"""Compare editable type to a reference, or preserve a fixed wordmark as SVG."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
from fontTools.ttLib import TTFont, TTLibError
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, features


def read_ink(
    source: Path,
    crop: tuple[int, int, int, int] | None = None,
    *,
    polarity: str = "dark",
    threshold: int | None = None,
    min_area: int = 2,
    ink_rgb: tuple[int, int, int] | None = None,
    color_tolerance: float = 12.0,
    open_radius: int = 0,
) -> np.ndarray:
    """Read a tightly framed still where the word has clear tonal contrast."""
    with Image.open(source) as picture:
        rgba = ImageOps.exif_transpose(picture).convert("RGBA")
        if crop:
            left, top, right, bottom = crop
            if not 0 <= left < right <= rgba.width or not 0 <= top < bottom <= rgba.height:
                raise ValueError(f"Crop {crop} is outside {rgba.size}.")
            rgba = rgba.crop(crop)
        background = (255, 255, 255, 255) if polarity == "dark" else (0, 0, 0, 255)
        canvas = Image.alpha_composite(Image.new("RGBA", rgba.size, background), rgba)
        if ink_rgb is None:
            luminance = np.asarray(canvas.convert("L"))
            strength = 255 - luminance if polarity == "dark" else luminance
            flag = cv2.THRESH_BINARY | (cv2.THRESH_OTSU if threshold is None else 0)
            _, ink = cv2.threshold(strength, threshold or 0, 255, flag)
        else:
            pixels = np.asarray(canvas.convert("RGB"), dtype="float32")
            distance = np.linalg.norm(pixels - ink_rgb, axis=-1)
            ink = np.where(distance <= color_tolerance, 255, 0).astype("uint8")
    if open_radius:
        diameter = open_radius * 2 + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (diameter, diameter))
        ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel)
    labels, pixels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    components = [index for index in range(1, labels) if stats[index, cv2.CC_STAT_AREA] >= min_area]
    if not components:
        raise ValueError("No lettering found. Check the crop, threshold and polarity.")
    cleaned = np.where(np.isin(pixels, components), 255, 0).astype("uint8")
    return trim(cleaned)


def trim(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("Empty typography mask.")
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def font_ink(
    font_path: Path,
    text: str,
    *,
    axes: dict[str, float] | None = None,
    language: str | None = None,
    direction: str | None = None,
) -> tuple[np.ndarray, dict]:
    """Use FontTools for names, coverage and axes, and RAQM/HarfBuzz for layout."""
    if not features.check_feature("raqm"):
        raise RuntimeError("Pillow was built without RAQM/HarfBuzz. Install a RAQM-enabled build.")
    with TTFont(font_path, fontNumber=0, lazy=True) as font:
        names = font["name"]
        family = names.getBestFamilyName() or font_path.stem
        style = names.getBestSubFamilyName() or "Regular"
        cmap = font.getBestCmap() or {}
        font_axes = font["fvar"].axes if "fvar" in font else []
        axis_tags = {axis.axisTag for axis in font_axes}
        missing = sorted(set(axes or {}) - axis_tags)
        omitted = sorted({
            character for character in text if character.isalnum() and ord(character) not in cmap
        })
        if missing:
            raise ValueError(f"{family} {style} lacks variation axes {', '.join(missing)}.")
        if omitted:
            raise ValueError(f"{family} {style} lacks characters {', '.join(omitted)}.")
        axes_used = {
            axis.axisTag: (axes or {}).get(axis.axisTag, axis.defaultValue) for axis in font_axes
        }
        for axis in font_axes:
            value = axes_used[axis.axisTag]
            if not axis.minValue <= value <= axis.maxValue:
                raise ValueError(f"{axis.axisTag}={value:g} is outside {axis.minValue:g}–{axis.maxValue:g}.")

    renderer = ImageFont.truetype(font_path, 160, layout_engine=ImageFont.Layout.RAQM)
    if axes and axes_used:
        renderer.set_variation_by_axes(list(axes_used.values()))
    placement = {"font": renderer, "language": language, "direction": direction}
    pen = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = pen.textbbox((0, 0), text, **placement)
    if left == right or top == bottom:
        raise ValueError("Render requires visible text.")
    image = Image.new("L", (right - left + 4, bottom - top + 4))
    ImageDraw.Draw(image).text((2 - left, 2 - top), text, fill=255, **placement)
    return trim(np.asarray(image)), {
        "path": str(font_path),
        "family": family,
        "style": style,
        "axes": axes_used,
    }


def at_height(mask: np.ndarray, height: int = 128) -> np.ndarray:
    width = max(1, round(mask.shape[1] * height / mask.shape[0]))
    return cv2.resize(mask, (width, height), interpolation=cv2.INTER_AREA if height < mask.shape[0]
                      else cv2.INTER_CUBIC).astype("float32") / 255


def likeness(reference: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    """Compare centered ink boxes at equal height, without distorting aspect ratio."""
    height, width = reference.shape
    mask = at_height(candidate, height)
    combined = max(width, mask.shape[1])
    target, shot = (np.zeros((height, combined), dtype="float32") for _ in range(2))
    for canvas, ink in ((target, reference), (shot, mask)):
        offset = (combined - ink.shape[1]) // 2
        canvas[:, offset:offset + ink.shape[1]] = ink
    columns_a, columns_b = target.sum(axis=0) / height, shot.sum(axis=0) / height
    return {
        "outline_iou": round(float(np.minimum(target, shot).sum() / np.maximum(target, shot).sum()), 4),
        "column_profile_iou": round(float(np.minimum(columns_a, columns_b).sum() /
                                          np.maximum(columns_a, columns_b).sum()), 4),
        "relative_width_error": round(float((mask.shape[1] - width) / width), 4),
    }


def compare(
    reference: np.ndarray,
    text: str,
    paths: list[Path],
    *,
    axes: dict[str, float] | None = None,
    language: str | None = None,
    direction: str | None = None,
) -> tuple[dict, list[np.ndarray]]:
    normalized = at_height(reference)
    comparisons = []
    skipped = []
    for path in paths:
        try:
            mask, metadata = font_ink(path, text, axes=axes, language=language, direction=direction)
        except (OSError, ValueError, TTLibError) as error:
            skipped.append({"path": str(path), "reason": str(error)})
            continue
        metadata.update(likeness(normalized, mask))
        comparisons.append((metadata, mask))
    if not comparisons:
        reasons = "; ".join(f"{entry['path']}: {entry['reason']}" for entry in skipped)
        raise ValueError(f"No candidate font could be rendered. {reasons}")
    comparisons.sort(key=lambda result: result[0]["outline_iou"], reverse=True)
    return {
        "text": text,
        "reference_ink_px": [reference.shape[1], reference.shape[0]],
        "harfbuzz_version": features.version_feature("harfbuzz"),
        "metrics": "Centred at equal ink height; width and spacing are not stretched.",
        "candidates": [entry for entry, _ in comparisons],
        "skipped": skipped,
    }, [reference] + [mask for _, mask in comparisons]


def save_preview(destination: Path, report: dict, masks: list[np.ndarray]) -> None:
    height = 72
    length = max(mask.shape[1] * height / mask.shape[0] for mask in masks)
    height = max(1, int(height * min(1, 1300 / length)))
    display = [at_height(mask, height) for mask in masks]
    margin, row = 18, height + 42
    image = Image.new("L", (max(mask.shape[1] for mask in display) + margin * 2,
                            row * len(display) + margin), 255)
    draw = ImageDraw.Draw(image)
    captions = ["Reference"] + [
        f"{entry['family']} {entry['style']}   IoU {entry['outline_iou']:.1%}"
        for entry in report["candidates"]
    ]
    for index, (caption, mask) in enumerate(zip(captions, display)):
        y = index * row + margin
        draw.text((margin, y), caption, fill=48)
        image.paste(Image.fromarray(np.uint8(255 * (1 - mask))), (margin, y + 21))
    image.save(destination)


def trace_svg(ink: np.ndarray, tolerance: float = 0.65) -> str:
    """Keep wordmark contours and holes as editable SVG paths."""
    if not np.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Trace tolerance must be a finite non-negative number.")
    # Padding keeps open crop edges from confusing the contour hierarchy.
    padded = cv2.copyMakeBorder(ink, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    contours = cv2.findContours(padded, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)[0]
    commands = []
    for contour in contours:
        if cv2.contourArea(contour) == 0:
            # A single-pixel detail such as a registration mark dot still has visible ink.
            x, y, width, height = cv2.boundingRect(contour)
            commands.append(f"M{x-1} {y-1}h{width}v{height}h{-width}Z")
            continue
        points = cv2.approxPolyDP(contour, tolerance, True).reshape(-1, 2)
        if len(points) < 3:
            points = contour.reshape(-1, 2)
        coords = " ".join(f"{x:g},{y:g}" for x, y in points - 0.5)
        commands.append(f"M{coords}Z")
    height, width = ink.shape
    path = " ".join(commands)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">\n'
            f'  <path d="{path}" fill="currentColor" fill-rule="evenodd"/>\n</svg>\n')


def parse_axes(entries: list[str]) -> dict[str, float]:
    axes = {}
    for entry in entries:
        tag, found, number = entry.partition("=")
        if not found or len(tag) != 4 or not np.isfinite(float(number)):
            raise ValueError(f"Bad axis {entry!r}; use wght=500.")
        axes[tag] = float(number)
    return axes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rank = commands.add_parser("rank", help="Compare the same text in local font candidates.")
    trace = commands.add_parser("trace", help="Trace a fixed wordmark as a reusable SVG.")
    for command in (rank, trace):
        command.add_argument("image", type=Path, help="Reference still or tightly framed image.")
        command.add_argument("--crop", nargs=4, type=int, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
        command.add_argument("--polarity", choices=("dark", "light"), default="dark")
        command.add_argument("--threshold", type=int, help="Set ink threshold 0–255; otherwise use Otsu.")
        command.add_argument("--min-area", type=int, default=2, help="Drop smaller connected ink regions.")
        command.add_argument("--ink-rgb", nargs=3, type=int, metavar=("R", "G", "B"),
                             help="Isolate ink with a known RGB color from a textured background.")
        command.add_argument("--color-tolerance", type=float, default=12.0,
                             help="RGB distance accepted with --ink-rgb.")
        command.add_argument("--open-radius", type=int, default=0,
                             help="Remove thin attached texture with an elliptical kernel radius in pixels.")
        command.add_argument("--output", required=True, type=Path)
    rank.add_argument("--text", required=True, help="Exact reference text, including punctuation.")
    rank.add_argument("--font", type=Path, required=True, action="append", help="Repeat for local OTF/TTF files.")
    rank.add_argument("--axis", action="append", default=[], help="Repeat to select axes such as wght=500.")
    rank.add_argument("--language")
    rank.add_argument("--direction", choices=("ltr", "rtl", "ttb"))
    rank.add_argument("--preview", type=Path)
    trace.add_argument("--tolerance", type=float, default=0.65, help="Maximum contour simplification in pixels.")
    args = parser.parse_args()
    if not 0 <= args.open_radius <= 100:
        parser.error("Open radius must be between 0 and 100 pixels.")
    if (args.threshold is not None and not 0 <= args.threshold <= 255) or args.min_area < 1:
        parser.error("Threshold must be 0–255 and minimum area must be at least 1.")
    if args.ink_rgb and (not all(0 <= channel <= 255 for channel in args.ink_rgb) or
                        not np.isfinite(args.color_tolerance) or args.color_tolerance < 0):
        parser.error("Ink RGB channels must be 0–255 and color tolerance must be non-negative.")
    try:
        reference = read_ink(
            args.image, tuple(args.crop) if args.crop else None,
            polarity=args.polarity, threshold=args.threshold, min_area=args.min_area,
            ink_rgb=tuple(args.ink_rgb) if args.ink_rgb else None,
            color_tolerance=args.color_tolerance, open_radius=args.open_radius,
        )
        if args.command == "trace":
            contents = trace_svg(reference, args.tolerance)
        else:
            report, masks = compare(
                reference, args.text, args.font,
                axes=parse_axes(args.axis), language=args.language, direction=args.direction,
            )
            contents = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
            if args.preview:
                save_preview(args.preview, report, masks)
        args.output.write_text(contents, encoding="utf-8")
    except (OSError, RuntimeError, ValueError, TTLibError) as error:
        parser.exit(1, f"Typography: {error}\n")


if __name__ == "__main__":
    main()
