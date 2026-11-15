"""Reusable complete lettering layers and advance-aware curved Latin typography.

No reference words, image paths or frame numbers live in this module. Path text
uses pair kerning, not equal angles per character. This is 2D typesetting with
tangent rotation; it does not claim to recover a 3D font or hidden reference ink.
"""
from dataclasses import dataclass
from math import sin, cos, radians, degrees, isfinite, hypot, ceil
from typing import Sequence
import unicodedata

from PIL import Image, ImageDraw, ImageFont


@dataclass(frozen=True)
class LetteringProvenance:
    source: str
    complete: bool
    reconstruction: str | None = None

    def validate(self):
        if self.source not in {"font", "authored", "observed", "observed_fragment"}:
            raise ValueError("Unknown lettering source")
        if self.complete and self.source == "observed_fragment" and not self.reconstruction:
            raise ValueError("Occluded contours cannot be declared complete without reconstruction")
        if self.source in {"font", "authored"} and not self.complete:
            raise ValueError("Mark a deliberately clipped asset as observed_fragment instead")


@dataclass(frozen=True)
class LetteringLayer:
    image: Image.Image
    provenance: LetteringProvenance
    position: tuple[int, int] = (0, 0)
    z: float = 0.0
    name: str = ""


def compose_layers(size: tuple[int, int], layers: Sequence[LetteringLayer], *, require_complete=True):
    """Compose whole layers back-to-front without changing any source alpha.

    Visibility is a result of compositing, never destructively baked into the
    lower word. A complete source remains recoverable when a top layer moves.
    """
    canvas = Image.new("RGBA", size)
    for layer in sorted(layers, key=lambda item: item.z):
        layer.provenance.validate()
        if require_complete and not layer.provenance.complete:
            raise ValueError(f"Incomplete lettering: {layer.name}")
        if layer.image.mode != "RGBA":
            raise ValueError("Lettering layers must preserve RGBA alpha")
        canvas.alpha_composite(layer.image, layer.position)
    return canvas


def text_mask(text: str, font: ImageFont.FreeTypeFont, *, padding=2):
    """Render a complete word, including overhangs and descenders, to L alpha."""
    if padding < 0:
        raise ValueError("padding must be nonnegative")
    box = font.getbbox(text, anchor="ls")
    x0, y0, x1, y1 = box
    mask = Image.new("L", (max(1, x1-x0+2*padding), max(1, y1-y0+2*padding)))
    ImageDraw.Draw(mask).text((padding-x0, padding-y0), text, font=font, fill=255, anchor="ls")
    return mask


def glyph_metrics(text: str, font: ImageFont.FreeTypeFont, tracking=0.0):
    """Return shaped Latin advances and origin offsets with pair kerning.

    Discretionary ligatures are disabled because characters are individually
    rotated. Combining sequences must first be NFC-composed; joining scripts
    should be supplied as complete lettering layers instead.
    """
    if unicodedata.normalize("NFC", text) != text or any(unicodedata.combining(c) for c in text):
        raise ValueError("Use NFC composed letters or a complete shaped lettering layer")
    if not isfinite(tracking):
        raise ValueError("tracking must be finite")
    def length(value):
        return float(font.getlength(value, features=["-liga"]))
    width = length(text) + max(0, len(text)-1)*tracking
    entries = []
    for i, char in enumerate(text):
        advance = length(char)
        origin = length(text[:i+1])-advance+i*tracking
        entries.append({"char": char, "origin": origin, "advance": advance,
                        "center": origin+advance/2})
    return entries, width


def layout_arc(text, font, *, center, radius, center_angle=0.0, tracking=0.0):
    """Place baseline glyph centers at arc distances measured in font pixels.

    center_angle is clockwise from the top of the circle in screen coordinates.
    Glyph angles are PIL rotations (positive counter-clockwise).
    """
    if not isfinite(radius) or radius <= 0:
        raise ValueError("radius must be positive and finite")
    if len(center) != 2 or not all(isfinite(v) for v in center) or not isfinite(center_angle):
        raise ValueError("center and angle must be finite")
    metrics, width = glyph_metrics(text, font, tracking)
    result = []
    for metric in metrics:
        theta = radians(center_angle)+(metric["center"]-width/2)/radius
        result.append({**metric, "x": center[0]+radius*sin(theta),
                       "y": center[1]-radius*cos(theta), "angle": -degrees(theta)})
    return result


def render_arc(size, text, font, *, center, radius, center_angle=0.0, tracking=0.0, color=(255,255,255,255)):
    """Render an arc with each character rotated about its baseline center."""
    output = Image.new("RGBA", size)
    for glyph in layout_arc(text, font, center=center, radius=radius,
                            center_angle=center_angle, tracking=tracking):
        if glyph["char"].isspace():
            continue
        box = font.getbbox(glyph["char"], anchor="ls")
        # A square centered on baseline origin preserves the pivot when rotated.
        extent = ceil(hypot(max(abs(box[0]-glyph["advance"]/2), abs(box[2]-glyph["advance"]/2)),
                            max(abs(box[1]), abs(box[3]))))+4
        stamp = Image.new("RGBA", (extent*2+1, extent*2+1))
        ImageDraw.Draw(stamp).text((extent-glyph["advance"]/2, extent), glyph["char"],
                                  font=font, fill=color, anchor="ls")
        stamp = stamp.rotate(glyph["angle"], resample=Image.Resampling.BICUBIC)
        output.alpha_composite(stamp, (round(glyph["x"]-extent), round(glyph["y"]-extent)))
    return output
