"""Executable, declarative bridge to the last MIT Motion Lab revision.

Authorship is explicit JSON. The bridge does not interpret prompts or select an
editing intention. Canvas2D uses upstream graph drawing; the independent 3D
backend uses real Three.js geometry with an original CPU z-buffer renderer.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from .contracts import ValidationError, clone, digest, file_sha256, integer, number, require, sha256

VERSION = "1.0.0"
UPSTREAM_COMMIT = "6a7f1ca62b7b30d534fe181f912606ad4cfc6718"
UPSTREAM_REPOSITORY = "https://github.com/AndreXes03/motion-lab"
_ROOT = Path(__file__).resolve().parents[1]
_VENDOR = _ROOT / "vendor" / "motionlab"
_ADAPTER = Path(__file__).resolve().parent / "backends" / "motionlab"
_VENDOR_MANIFEST_SHA256 = "9adca91ed06628b84f3330c10e533901567cf33345ae7d002e570cb4d711a96c"
_EASINGS = {"smooth", "linear", "hold", "in", "out", "inOut", "bezier"}
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_PIXELS = 3840 * 2160
_MAX_FRAMES = 18000
_NODE_COMMON = {"id", "type", "children", "start_s", "end_s", "sound"}
_NODE_2D = {"x", "y", "rotation", "scaleX", "scaleY", "opacity", "fill", "stroke", "lineWidth",
            "clip", "blend", "fillRule", "dash", "dashOffset"}
_NODE_3D = {"position", "rotation", "scale", "material"}
_SHAPES_2D = {"group": set(), "rect": {"width", "height", "cornerRadius"}, "circle": {"radius"},
              "path": {"commands"}, "text": {"text", "font_id", "font_size", "align", "baseline", "maxWidth"}}
_SHAPES_3D = {"group": set(), "box": {"size"}, "sphere": {"radius", "segments", "rings"},
              "plane": {"size"}, "torus": {"radius", "tube", "rings", "segments"},
              "text3d": {"text", "font_id", "font_size", "depth", "curve_segments"}}
_BLENDS = {"source-over", "source-in", "source-out", "source-atop", "destination-over", "destination-in",
           "destination-out", "destination-atop", "lighter", "copy", "xor", "multiply", "screen", "overlay",
           "darken", "lighten", "color-dodge", "color-burn", "hard-light", "soft-light", "difference",
           "exclusion", "hue", "saturation", "color", "luminosity"}


def _object(value: Any, label: str, fields: set[str]) -> dict:
    require(isinstance(value, dict), "motion_type", "Expected an object", label)
    require(not (set(value) - fields), "motion_field", f"Unknown fields: {sorted(set(value) - fields)}", label)
    return value


def _identifier(value: Any, label: str) -> str:
    require(isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value)), "motion_id",
            "Use 1–80 ASCII letters, digits, underscore or hyphen", label)
    return value


def _color(value: Any, label: str, *, nullable: bool = False) -> None:
    require((nullable and value is None) or (isinstance(value, str) and bool(_COLOR.fullmatch(value))),
            "motion_color", "Expected #RRGGBB" + (" or null" if nullable else ""), label)


def _vector(value: Any, size: int, label: str, *, minimum: float | None = None) -> None:
    require(isinstance(value, list) and len(value) == size, "motion_vector", f"Expected a vector of {size} numbers", label)
    for i, component in enumerate(value):
        number(component, f"{label}[{i}]", minimum=minimum, maximum=1e6)
        require(abs(component) <= 1e6, "motion_range", "Coordinate magnitude exceeds 1e6", label)


def _keys(value: Any, label: str, duration: float, *, dimensions: int = 1,
          minimum: float | None = None, maximum: float | None = None, default_ease: str = "smooth") -> None:
    require(isinstance(value, list) and 1 <= len(value) <= 1000, "motion_keys", "Expected 1–1000 keys", label)
    previous = -1.0
    for i, key in enumerate(value):
        p = f"{label}[{i}]"
        _object(key, p, {"t", "value", "ease", "bezier"})
        t = number(key.get("t"), p + ".t", minimum=0, maximum=duration)
        require(t > previous, "motion_key_order", "Key times must strictly increase", p)
        previous = t
        values = key.get("value")
        if dimensions > 1:
            _vector(values, dimensions, p + ".value", minimum=minimum)
        else:
            values = [values]
        for v in values:
            number(v, p + ".value", minimum=minimum, maximum=maximum)
        ease = key.setdefault("ease", default_ease)
        require(ease in _EASINGS, "motion_easing", "Unknown easing", p)
        if ease == "bezier":
            _vector(key.get("bezier"), 4, p + ".bezier", minimum=0)
            require(all(v <= 1 for v in key["bezier"]), "motion_bezier", "Bezier coordinates must be 0..1", p)
        else:
            require("bezier" not in key, "motion_bezier", "Bezier values require bezier easing", p)


def _path_geometry(shape: dict, label: str) -> None:
    kind = shape["type"]
    if kind == "rect":
        number(shape.get("width"), label + ".width", minimum=0, maximum=1e6)
        number(shape.get("height"), label + ".height", minimum=0, maximum=1e6)
        if "cornerRadius" in shape:
            number(shape["cornerRadius"], label + ".cornerRadius", minimum=0, maximum=1e6)
    elif kind == "circle":
        number(shape.get("radius"), label + ".radius", minimum=0, maximum=1e6)
    else:
        commands = shape.get("commands")
        require(isinstance(commands, list) and 1 <= len(commands) <= 10000,
                "motion_path", "Expected 1–10000 path commands", label)
        arity = {"M": 2, "L": 2, "Q": 4, "C": 6, "A": 5, "Z": 0}
        for c in commands:
            require(isinstance(c, list) and len(c) > 0 and c[0] in arity and len(c) == arity[c[0]] + 1,
                    "motion_path", "Malformed path command", label)
            for component in c[1:]:
                number(component, label, minimum=-1e6, maximum=1e6)
            if c[0] == "A":
                require(c[3] >= 0, "motion_path", "Arc radius cannot be negative", label)


def validate_scene(scene: dict) -> dict:
    """Normalize finite JSON and reject unsupported fields, paths, clocks or geometry.

    Defaults are technical (identity transforms, camera clipping); no style,
    sound file or meaning is inferred. Font files are always bound to a SHA-256.
    """
    result = clone(scene)
    _object(result, "scene", {"schema_version", "id", "mode", "width", "height", "fps", "frame_count", "duration_s",
                              "background", "nodes", "tracks", "groups", "cuts", "fonts", "camera", "lights", "provenance"})
    require(result.get("schema_version") == "motionlab-scene/1", "motion_schema", "Expected motionlab-scene/1", "scene")
    _identifier(result.get("id"), "scene.id")
    mode = result.get("mode")
    require(mode in {"2d", "3d"}, "motion_mode", "Mode must be 2d or 3d", "scene.mode")
    width = integer(result.get("width"), "scene.width", minimum=1)
    height = integer(result.get("height"), "scene.height", minimum=1)
    require(width * height <= _MAX_PIXELS and width <= 7680 and height <= 7680,
            "motion_budget", "Raster exceeds the declared render limit", "scene")
    fps = result.get("fps")
    require(isinstance(fps, str) and re.fullmatch(r"[1-9][0-9]*/[1-9][0-9]*", fps) is not None,
            "motion_clock", "FPS must be a positive rational string such as 30000/1001", "scene.fps")
    ratio = Fraction(fps)
    require(Fraction(1) <= ratio <= Fraction(240), "motion_clock", "FPS must be between 1 and 240", "scene.fps")
    count = integer(result.get("frame_count"), "scene.frame_count", minimum=1)
    duration = float(Fraction(count) / ratio)
    require(count <= _MAX_FRAMES and duration <= 600, "motion_budget", "Limit: 18000 frames and 600 seconds", "scene")
    if "duration_s" in result:
        number(result["duration_s"], "scene.duration_s", minimum=0)
        require(math.isclose(result["duration_s"], duration, abs_tol=1e-8, rel_tol=0),
                "motion_clock", "duration_s differs from frame_count/fps", "scene.duration_s")
    result["fps"] = f"{ratio.numerator}/{ratio.denominator}"
    result["duration_s"] = duration
    result.setdefault("background", None)
    _color(result["background"], "scene.background", nullable=True)
    cuts = result.setdefault("cuts", [])
    require(isinstance(cuts, list), "motion_type", "cuts must be an array", "scene.cuts")
    for t in cuts:
        number(t, "scene.cuts", minimum=0, maximum=duration)
    require(cuts == sorted(set(cuts)), "motion_cuts", "Cuts must be unique and sorted", "scene.cuts")
    fonts = result.setdefault("fonts", [])
    require(isinstance(fonts, list) and len(fonts) <= 32, "motion_fonts", "Expected up to 32 fonts", "scene.fonts")
    font_index = {}
    for font in fonts:
        _object(font, "font", {"id", "path", "sha256", "format"})
        font_id = _identifier(font.get("id"), "font.id")
        require(font_id not in font_index, "motion_font", "Duplicate font ID", font_id)
        require(font.get("format") in {"font", "three-typeface"}, "motion_font", "Unknown font format", font_id)
        require(isinstance(font.get("path"), str), "motion_font", "Font path must be a local file", font_id)
        font["path"] = str(Path(font["path"]).expanduser().resolve())
        sha256(font.get("sha256"), "font.sha256")
        require(file_sha256(font["path"]) == font["sha256"], "motion_font_hash", "Font bytes changed", font_id)
        require(Path(font["path"]).stat().st_size <= 32 * 1024 * 1024, "motion_budget", "Font exceeds 32 MiB", font_id)
        font_index[font_id] = font
    font_coverage = {}

    def verify_glyphs(font: dict, text: str, label: str) -> None:
        if font["id"] not in font_coverage:
            try:
                if font["format"] == "three-typeface":
                    data = json.loads(Path(font["path"]).read_text(encoding="utf8"))
                    require(isinstance(data.get("glyphs"), dict), "motion_font", "Typeface has no glyph map", label)
                    font_coverage[font["id"]] = set(data["glyphs"])
                else:
                    try:
                        from fontTools.ttLib import TTFont, TTLibError
                    except ImportError as exc:
                        raise ValidationError("motion_dependency", "fonttools is required to verify font coverage") from exc
                    try:
                        with TTFont(font["path"], lazy=True) as face:
                            font_coverage[font["id"]] = {chr(code) for code in (face.getBestCmap() or {})}
                    except TTLibError as exc:
                        raise ValidationError("motion_font", "Invalid TTF/OTF font", label) from exc
            except (OSError, ValueError, KeyError) as exc:
                if isinstance(exc, ValidationError):
                    raise
                raise ValidationError("motion_font", "Font cannot be parsed for glyph coverage", label) from exc
        missing = sorted(set(text) - font_coverage[font["id"]])
        require(not missing, "motion_glyph_missing", f"Font lacks characters: {missing}; no implicit fallback font", label)
    nodes = result.get("nodes")
    require(isinstance(nodes, list) and bool(nodes), "motion_nodes", "Expected nonempty nodes", "scene.nodes")
    node_index = {}

    def visit(node: dict, label: str, depth: int = 0) -> None:
        require(depth <= 32, "motion_budget", "Node hierarchy exceeds 32 levels", label)
        shapes = _SHAPES_2D if mode == "2d" else _SHAPES_3D
        require(isinstance(node, dict) and node.get("type") in shapes, "motion_node_type", "Unsupported node type", label)
        kind = node["type"]
        _object(node, label, _NODE_COMMON | (_NODE_2D if mode == "2d" else _NODE_3D) | shapes[kind])
        node_id = _identifier(node.get("id"), label + ".id")
        require(node_id not in node_index and node_id != "camera", "motion_id", "Duplicate or reserved node ID", node_id)
        node_index[node_id] = node
        require(len(node_index) <= 500, "motion_budget", "Limit: 500 nodes", "scene.nodes")
        start = number(node.get("start_s", 0), label + ".start_s", minimum=0, maximum=duration)
        end = number(node.get("end_s", duration), label + ".end_s", minimum=0, maximum=duration)
        require(end > start, "motion_interval", "Node end_s must exceed start_s", label)
        if "sound" in node:
            require(isinstance(node["sound"], bool), "motion_type", "sound must be boolean", label)
        children = node.get("children", [])
        require(isinstance(children, list), "motion_type", "children must be an array", label)
        if mode == "2d":
            for field in {"x", "y", "rotation", "scaleX", "scaleY", "dashOffset"} & set(node):
                number(node[field], label + "." + field, minimum=-1e6, maximum=1e6)
            if "opacity" in node:
                number(node["opacity"], label + ".opacity", minimum=0, maximum=1)
            if "lineWidth" in node:
                number(node["lineWidth"], label + ".lineWidth", minimum=.001, maximum=1e6)
            for field in {"fill", "stroke"} & set(node):
                _color(node[field], label + "." + field, nullable=True)
            if kind != "group":
                require(node.get("fill") is not None or node.get("stroke") is not None,
                        "motion_paint", "Explicit fill or stroke required", label)
            if "blend" in node:
                require(node["blend"] in _BLENDS, "motion_blend", "Unsupported blend operation", label)
            if "fillRule" in node:
                require(node["fillRule"] in {"nonzero", "evenodd"}, "motion_path", "Unknown fill rule", label)
            if "dash" in node:
                require(isinstance(node["dash"], list) and len(node["dash"]) <= 64, "motion_path", "Invalid dash pattern", label)
                for segment in node["dash"]:
                    number(segment, label + ".dash", minimum=0, maximum=1e6)
            if "clip" in node:
                clip = node["clip"]
                require(isinstance(clip, dict) and clip.get("type") in {"rect", "circle", "path"},
                        "motion_clip", "Unsupported clip", label)
                _object(clip, label + ".clip", {"type", "fillRule"} | _SHAPES_2D[clip["type"]])
                _path_geometry(clip, label + ".clip")
                require(clip.get("fillRule", "nonzero") in {"nonzero", "evenodd"}, "motion_clip", "Unknown fill rule", label)
            if kind in {"rect", "circle", "path"}:
                _path_geometry(node, label)
            if kind == "text":
                require(node.get("align", "left") in {"left", "center", "right", "start", "end"}, "motion_text", "Unknown text alignment", label)
                require(node.get("baseline", "alphabetic") in {"top", "hanging", "middle", "alphabetic", "ideographic", "bottom"},
                        "motion_text", "Unknown baseline", label)
                if "maxWidth" in node:
                    number(node["maxWidth"], label + ".maxWidth", minimum=.001, maximum=1e6)
        else:
            for field in {"position", "rotation", "scale"} & set(node):
                _vector(node[field], 3, label + "." + field)
            require(all(v > 1e-9 for v in node.get("scale", [1, 1, 1])), "motion_geometry", "3D scale must be positive", label)
            if kind != "group":
                material = _object(node.get("material"), label + ".material", {"color", "unlit", "side"})
                _color(material.get("color"), label + ".material.color")
                require(isinstance(material.get("unlit", False), bool), "motion_material", "unlit must be boolean", label)
                require(material.get("side", "front") in {"front", "double"}, "motion_material", "side must be front or double", label)
            else:
                require("material" not in node, "motion_material", "Group has no material", label)
            if kind in {"box", "plane"}:
                _vector(node.get("size"), 3 if kind == "box" else 2, label + ".size", minimum=.0001)
            for field in {"radius", "tube", "depth"} & set(node):
                number(node[field], label + "." + field, minimum=.0001, maximum=1e5)
            for field in {"rings", "segments", "curve_segments"} & set(node):
                value = integer(node[field], label + "." + field, minimum=3 if field != "curve_segments" else 1)
                require(value <= 96, "motion_budget", "Geometry subdivision exceeds 96", label)
            if kind in {"sphere", "torus"}:
                number(node.get("radius"), label + ".radius", minimum=.0001, maximum=1e5)
            if kind == "torus":
                number(node.get("tube"), label + ".tube", minimum=.0001, maximum=1e5)
            if kind == "text3d":
                number(node.get("depth"), label + ".depth", minimum=.0001, maximum=1e5)
        if kind in {"text", "text3d"}:
            require(isinstance(node.get("text"), str) and 1 <= len(node["text"]) <= 2000,
                    "motion_text", "Expected 1–2000 text characters", label)
            number(node.get("font_size"), label + ".font_size", minimum=.001, maximum=1e5)
            font = font_index.get(node.get("font_id"))
            expected = "font" if kind == "text" else "three-typeface"
            require(font is not None and font["format"] == expected, "motion_font", "Missing font or mismatched format", label)
            require("\n" not in node["text"] and "\r" not in node["text"], "motion_text",
                    "Use independent text nodes for multiple lines", label)
            verify_glyphs(font, node["text"], label)
        for i, child in enumerate(children):
            visit(child, label + f".children[{i}]", depth + 1)

    for index, node in enumerate(nodes):
        visit(node, f"scene.nodes[{index}]")
    if mode == "3d":
        camera = _object(result.get("camera"), "scene.camera", {"position", "target", "fov", "near", "far"})
        _vector(camera.get("position"), 3, "scene.camera.position")
        _vector(camera.get("target"), 3, "scene.camera.target")
        require(camera["position"] != camera["target"], "motion_camera", "Camera cannot look at its own position", "scene.camera")
        number(camera.setdefault("fov", 50), "scene.camera.fov", minimum=1, maximum=170)
        number(camera.setdefault("near", .1), "scene.camera.near", minimum=.00001, maximum=1e6)
        number(camera.setdefault("far", 1000), "scene.camera.far", minimum=camera["near"] + .00001, maximum=1e9)
        lights = result.setdefault("lights", [])
        require(isinstance(lights, list) and len(lights) <= 32, "motion_lights", "Expected up to 32 lights", "scene.lights")
        for light in lights:
            _object(light, "light", {"type", "color", "intensity", "direction", "position"})
            require(light.get("type") in {"ambient", "directional", "point"}, "motion_light", "Unknown light type", "light")
            _color(light.get("color"), "light.color")
            number(light.get("intensity"), "light.intensity", minimum=0, maximum=100)
            if light["type"] == "directional":
                _vector(light.get("direction"), 3, "light.direction")
                require(any(light["direction"]), "motion_light", "Light direction cannot be zero", "light")
                require("position" not in light, "motion_field", "Directional light takes direction, not position", "light")
            elif light["type"] == "point":
                _vector(light.get("position"), 3, "light.position")
                require("direction" not in light, "motion_field", "Point light takes position, not direction", "light")
            else:
                require("position" not in light and "direction" not in light, "motion_field", "Ambient light has no transform", "light")
    else:
        require("camera" not in result and "lights" not in result, "motion_field", "2D scenes have no 3D camera or lights", "scene")
    groups = result.setdefault("groups", {})
    require(isinstance(groups, dict) and len(groups) <= 100, "motion_groups", "Expected up to 100 animation groups", "scene.groups")
    for group_id, group in groups.items():
        _identifier(group_id, "group.id")
        _object(group, "group", {"start", "end", "rate", "keys"})
        start = number(group.get("start"), "group.start", minimum=0, maximum=duration)
        end = number(group.get("end"), "group.end", minimum=0, maximum=duration)
        require(end > start, "motion_group", "Group end must exceed start", group_id)
        number(group.setdefault("rate", 1), "group.rate", minimum=.25, maximum=2.5)
        _keys(group.get("keys"), "group.keys", end - start, minimum=0, maximum=1, default_ease="linear")
    tracks = result.setdefault("tracks", [])
    require(isinstance(tracks, list) and len(tracks) <= 500, "motion_tracks", "Expected up to 500 tracks", "scene.tracks")
    bound = set()
    for track in tracks:
        _object(track, "track", {"target", "property", "group", "keys"})
        target, prop = track.get("target"), track.get("property")
        require(isinstance(target, str) and isinstance(prop, str), "motion_track", "Track needs target and property", "track")
        require((target, prop) not in bound, "motion_track", "Two tracks cannot control the same property", "track")
        bound.add((target, prop))
        if target == "camera":
            require(mode == "3d" and prop in {"position", "target", "fov"}, "motion_track", "Unsupported camera track", "track")
            dimensions = 1 if prop == "fov" else 3
        else:
            require(target in node_index, "motion_track", "Unknown target ID", "track")
            node = node_index[target]
            if mode == "2d":
                allowed = {"x", "y", "rotation", "scaleX", "scaleY", "opacity"}
                allowed |= (_SHAPES_2D[node["type"]] & {"width", "height", "radius", "cornerRadius", "font_size", "maxWidth"})
                require(prop in allowed, "motion_track", "Property is not animatable on this node type", "track")
                dimensions = 1
            else:
                require(prop in {"position", "rotation", "scale"}, "motion_track", "3D geometry and material must remain explicit; transform tracks supported", "track")
                dimensions = 3
        if "group" in track:
            require(track["group"] in groups, "motion_group", "Unknown track group", "track")
        minimum = 0 if prop in {"opacity", "width", "height", "radius", "cornerRadius"} else 1 if prop == "fov" else .001 if prop in {"font_size", "maxWidth"} else -1e6
        maximum = 1 if prop == "opacity" else 170 if prop == "fov" else 1e6
        _keys(track.get("keys"), "track.keys", duration, dimensions=dimensions, minimum=minimum, maximum=maximum)
        if mode == "3d" and prop == "scale":
            require(all(v > 0 for key in track["keys"] for v in key["value"]),
                    "motion_geometry", "Animated 3D scales must stay positive", "track")
    total_keys = sum(len(track["keys"]) for track in tracks) + sum(len(group["keys"]) for group in groups.values())
    require(total_keys <= 10000, "motion_budget", "Limit: 10000 animation keys", "scene")
    return result


def _vendor_fingerprint() -> dict:
    manifest = _VENDOR / "provenance.json"
    require(file_sha256(manifest) == _VENDOR_MANIFEST_SHA256, "motion_vendor",
            "Pinned vendor inventory changed", str(manifest))
    inventory = json.loads(manifest.read_text(encoding="utf8"))
    require(inventory["commit"] == UPSTREAM_COMMIT and inventory["license"] == "MIT",
            "motion_vendor", "Only the frozen MIT revision is permitted", str(manifest))
    for item in inventory["files"]:
        require(file_sha256(_VENDOR / item["path"]) == item["sha256"], "motion_vendor",
                "Vendored bytes differ from the pinned revision", item["path"])
    adapter_files = [Path(__file__).resolve(), *_ADAPTER.glob("*.mjs"), _ADAPTER / "package.json", _ADAPTER / "package-lock.json"]
    adapter = {str(path.relative_to(_ROOT)): file_sha256(path) for path in sorted(adapter_files)}
    return {"upstream_repository": UPSTREAM_REPOSITORY, "upstream_commit": UPSTREAM_COMMIT, "license": "MIT",
            "vendor_manifest_sha256": _VENDOR_MANIFEST_SHA256, "adapter_version": VERSION,
            "adapter_files": adapter, "adapter_sha256": digest(adapter)}


def _node(payload: dict, *, timeout: float = 600) -> dict | list:
    node = shutil.which("node") or os.environ.get("CODEX_PRIMARY_RUNTIME_NODE")
    require(bool(node), "motion_runtime", "Node.js is unavailable", "node")
    expected = {"three": "0.180.0", "@napi-rs/canvas": "0.1.100"}
    for package, version in expected.items():
        path = _ADAPTER / "node_modules" / package / "package.json"
        require(path.is_file(), "motion_dependency", f"Run npm ci --ignore-scripts in {_ADAPTER}", package)
        installed = json.loads(path.read_text(encoding="utf8"))
        require(installed.get("version") == version, "motion_dependency", f"Expected {package} {version}", package)
    try:
        completed = subprocess.run([str(node), str(_ADAPTER / "bridge.mjs")],
                                   input=json.dumps(payload, allow_nan=False), text=True, capture_output=True,
                                   timeout=timeout, check=False, cwd=_ROOT)
    except subprocess.TimeoutExpired as exc:
        raise ValidationError("motion_timeout", "Motion renderer exceeded its explicit timeout") from exc
    require(completed.returncode == 0, "motion_runtime", completed.stderr[-6000:] or "Renderer failed", "node")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValidationError("motion_runtime", "Renderer returned invalid JSON") from exc


def _runtime_scene(scene: dict) -> dict:
    result = clone(scene)
    result["fps_value"] = float(Fraction(result["fps"]))
    return result


def probe() -> dict:
    """Execute tiny 2D and 3D pixel proofs; availability is not aesthetic approval."""
    report = {"schema_version": "motionlab-probe/1", "available": False, "version": VERSION}
    try:
        report["provenance"] = _vendor_fingerprint()
        report.update(_node({"command": "probe"}, timeout=30))
        report["available"] = all(item["available"] for item in report["backends"].values())
        report["ffmpeg"] = shutil.which("ffmpeg")
        report["limitations"] = ["CPU 3D uses opaque Lambert-shaded meshes; no shadows, reflections, PBR or WebGL.",
                                 "Pixel probes establish execution, not visual quality or approval."]
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        report["error"] = str(exc)
    return report


def evaluate(scene: dict, time_s: float) -> dict:
    """Evaluate independent node/group clocks from absolute scene time."""
    scene = validate_scene(scene)
    number(time_s, "time_s", minimum=0, maximum=scene["duration_s"])
    provenance = _vendor_fingerprint()
    result = _node({"command": "evaluate", "scene": _runtime_scene(scene), "time_s": time_s})
    return {"schema_version": "motionlab-state/1", "scene_id": scene["id"], "scene_sha256": digest(scene),
            "clock": "scene_seconds", "provenance": provenance, **result}


def sonic_candidates(scene: dict, *, rate: int = 60, density: float = .5) -> dict:
    """Derive candidate instants/intensities from motion; never bind a sound asset."""
    scene = validate_scene(scene)
    integer(rate, "rate", minimum=10)
    require(rate <= 240 and rate * scene["duration_s"] <= 100000, "motion_budget", "Telemetry sample budget exceeded", "rate")
    number(density, "density", minimum=0, maximum=1)
    provenance = _vendor_fingerprint()
    result = _node({"command": "sonic", "scene": _runtime_scene(scene), "options": {"rate": rate, "density": density}})
    result.update({"scene_id": scene["id"], "scene_sha256": digest(scene), "clock": "scene_seconds",
                   "fps": scene["fps"], "frame_count": scene["frame_count"], "duration_s": scene["duration_s"], "provenance": provenance})
    for evidence in result["evidence"]:
        evidence["scene_sha256"] = result["scene_sha256"]
    return result


def render(scene: dict, output: str | Path, *, samples: int = 1, shutter_angle: float = 210,
           shutter_profile: str = "cosine", preview: bool = False, preview_background: str = "#000000",
           timeout: float = 600) -> dict:
    """Render a fresh artifact directory, retaining every straight-alpha PNG.

    An .mp4 output explicitly requests an opaque preview. Otherwise `output` is
    a new directory; preview=True additionally encodes preview.mp4. The preview
    background is declared separately and never changes the RGBA layer.
    """
    scene = validate_scene(scene)
    integer(samples, "samples", minimum=1)
    require(samples <= 64, "motion_samples", "At most 64 temporal samples", "samples")
    number(shutter_angle, "shutter_angle", minimum=0, maximum=360)
    require(shutter_profile in {"cosine", "box"}, "motion_shutter", "Unknown shutter profile", "shutter_profile")
    _color(preview_background, "preview_background")
    number(timeout, "timeout", minimum=1, maximum=86400)
    fingerprint = _vendor_fingerprint()
    destination = Path(output).expanduser().resolve()
    if destination.suffix.lower() == ".mp4":
        preview_path = destination
        frames_dir = destination.with_name(destination.stem + ".frames")
        receipt_path = destination.with_name(destination.stem + ".receipt.json")
        scene_path = destination.with_name(destination.stem + ".scene.json")
        manifest_path = destination.with_name(destination.stem + ".frames.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        require(not destination.exists(), "motion_output_exists", "Output directory must be new", str(destination))
        destination.mkdir(parents=True, exist_ok=False)
        preview_path = destination / "preview.mp4" if preview else None
        frames_dir, receipt_path, scene_path, manifest_path = (destination / name for name in
                                                              ("frames", "receipt.json", "scene.json", "frames.json"))
    for path in [frames_dir, receipt_path, scene_path, manifest_path, *([preview_path] if preview_path else [])]:
        require(not path.exists(), "motion_output_exists", "Refusing to overwrite an existing artifact", str(path))
    if preview_path:
        require(scene["width"] % 2 == 0 and scene["height"] % 2 == 0, "motion_preview",
                "H.264 4:2:0 preview requires even dimensions; render PNGs for odd rasters", "scene")
        require(shutil.which("ffmpeg") is not None, "motion_dependency", "ffmpeg is required for MP4 preview", "ffmpeg")
    frames_dir.mkdir(parents=False, exist_ok=False)
    scene_path.write_text(json.dumps(scene, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    options = {"samples": samples, "shutter_angle": shutter_angle, "shutter_profile": shutter_profile}
    execution = _node({"command": "render", "scene": _runtime_scene(scene), "frames_dir": str(frames_dir), "options": options}, timeout=timeout)
    frames = execution["frames"]
    require(len(frames) == scene["frame_count"], "motion_frame_count", "Renderer produced the wrong number of frames", "frames")
    from PIL import Image
    minimum_alpha, maximum_alpha = 255, 0
    for index, frame in enumerate(frames):
        require(frame["index"] == index and Path(frame["path"]).resolve().parent == frames_dir,
                "motion_frame_manifest", "Frame order or path changed", "frames")
        require(file_sha256(frame["path"]) == frame["sha256"], "motion_frame_hash", "Rendered PNG changed", frame["path"])
        with Image.open(frame["path"]) as image:
            require(image.mode == "RGBA" and image.size == (scene["width"], scene["height"]),
                    "motion_frame_format", "Expected exact RGBA raster", frame["path"])
            lo, hi = image.getchannel("A").getextrema()
            minimum_alpha, maximum_alpha = min(minimum_alpha, lo), max(maximum_alpha, hi)
    manifest = {"schema_version": "motionlab-frames/1", "scene_sha256": digest(scene), "fps": scene["fps"],
                "frame_count": scene["frame_count"], "width": scene["width"], "height": scene["height"],
                "alpha": "straight", "color_space": "sRGB", "frames": frames}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
    preview_report = None
    if preview_path:
        background = scene["background"] or preview_background
        command = [shutil.which("ffmpeg"), "-v", "error", "-nostdin", "-n", "-framerate", scene["fps"],
                   "-i", str(frames_dir / "%08d.png"), "-f", "lavfi", "-i",
                   f"color=c={background.replace('#', '0x')}:s={scene['width']}x{scene['height']}:r={scene['fps']}",
                   "-filter_complex", "[1:v][0:v]overlay=shortest=1:format=auto,format=yuv420p[v]", "-map", "[v]",
                   "-frames:v", str(scene["frame_count"]), "-an", "-c:v", "libx264", "-crf", "18", "-movflags", "+faststart", str(preview_path)]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        require(completed.returncode == 0, "motion_preview", completed.stderr[-4000:] or "Preview encoding failed", str(preview_path))
        preview_report = {"path": str(preview_path), "sha256": file_sha256(preview_path), "alpha": "opaque",
                          "flatten_background": background, "audio": "none", "role": "preview_only"}
    receipt = {"schema_version": "motionlab-render/1", "status": "rendered", "version": VERSION,
               "backend_version": VERSION, "upstream_commit": UPSTREAM_COMMIT, "scene_id": scene["id"],
               "scene_sha256": digest(scene), "scene_path": str(scene_path), "scene_file_sha256": file_sha256(scene_path),
               "backend": execution["backend"], "provenance": fingerprint, "frames_dir": str(frames_dir),
               "frame_manifest": str(manifest_path), "frame_manifest_sha256": file_sha256(manifest_path),
               "frames": frames, "fps": scene["fps"], "frame_count": scene["frame_count"],
               "width": scene["width"], "height": scene["height"], "duration_s": scene["duration_s"],
               "clock": "scene_seconds", "retimed": False, "alpha": "straight", "color_space": "sRGB",
               "opaque": minimum_alpha == 255, "alpha_range": [minimum_alpha, maximum_alpha],
               "scene_background": scene["background"], "motion_blur": {**options, "cut_aware": True,
                   "integration": execution["temporal_integration"]}, "preview": preview_report,
               "path": str(preview_path) if preview_path else str(manifest_path),
               "sha256": preview_report["sha256"] if preview_report else file_sha256(manifest_path),
               "review": {"technical": "pngs_decoded_hashed", "motion_perceptual": "unverified", "audio": "absent", "user_approved": False},
               "limitations": ["Authored scene; no automatic prompt interpretation, source tracking or semantic sound selection.",
                               "3D backend: opaque Lambert meshes, six-plane clipping and z-buffer; no shadows/reflections/PBR.",
                               "CPU raster has temporal supersampling but no spatial supersampling; small edges may alias."]}
    receipt["receipt_path"] = str(receipt_path)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return receipt


__all__ = ["VERSION", "UPSTREAM_COMMIT", "probe", "validate_scene", "evaluate", "render", "sonic_candidates"]
