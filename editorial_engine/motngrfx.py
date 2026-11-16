"""Portable, attributed MOTNGRFX motion and strict footage composition.

This CPU renderer uses actual extruded glyph contours, a perspective camera and
a depth buffer. It does not infer a camera/subject track from footage. Masks and
source clocks are supplied, checked resources. See docs/motngrfx-adapter.md.
"""
from __future__ import annotations

from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unicodedata
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from vendor.motngrfx import portable
from .contracts import (clone, digest, file_sha256, integer, mapping, nonempty,
                        number, require, sha256, verify_file, ValidationError)

SCHEMA = "motngrfx-motion/1"
SEQUENCE_SCHEMA = "motion-sequence/1"
VERSION = "1.0.0"
UPSTREAM_COMMIT = "8c0ddc816616a95f55bddc606eecea3fd5ba5ef1"
MODULES = ("rotate", "hinge_unfold")


def implementation_fingerprint() -> dict:
    root = Path(__file__).resolve().parents[1]
    names = ["editorial_engine/motngrfx.py", "vendor/motngrfx/portable.py",
             "vendor/motngrfx/UPSTREAM.json", "visual_fidelity/type_layout.py"]
    return {name: file_sha256(root / name) for name in names if (root / name).is_file()}


def probe_backend() -> dict:
    """Dependency readiness only; never a render or a model-inference claim."""
    missing = [name for name in ("numpy", "PIL", "cv2", "fontTools")
               if importlib.util.find_spec(name) is None]
    return {"backend": "motngrfx-portable", "version": VERSION,
            "available": not missing, "missing_modules": missing,
            "modules": list(MODULES), "device": "cpu",
            "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"),
            "upstream_commit": UPSTREAM_COMMIT, "model_inference": False,
            "render_tested": False, "implementation": implementation_fingerprint()}


def probe_motngrfx() -> dict:
    """Named alias for the motion CLI; never imports torch or model runtimes."""
    return probe_backend()


def preflight_comfyui(endpoint: str, *, required_nodes: list[str],
                      model_files: list[dict], timeout: float = 5.0) -> dict:
    """Read-only opt-in endpoint/model check. Does not submit/download anything.

    Nodes must be named by the caller's actual workflow. Model files are local
    receipts {path, sha256}; an empty/unknown set cannot prove full readiness.
    """
    require(endpoint.startswith(("http://", "https://")), "comfy_endpoint", "Supply an explicit HTTP(S) endpoint")
    require(bool(required_nodes), "comfy_nodes", "List the nodes required by the actual workflow")
    results = {"endpoint": endpoint.rstrip("/"), "executed": False,
               "downloaded": False, "ready": False, "missing_nodes": [], "models": []}
    for item in model_files:
        verify_file(item["path"], item["sha256"], "ComfyUI model")
        results["models"].append({"path": str(Path(item["path"]).resolve()), "sha256": item["sha256"]})
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/object_info", timeout=timeout) as response:
            body = response.read(16*1024*1024 + 1)
        require(len(body) <= 16*1024*1024, "comfy_response", "ComfyUI response too large")
        nodes = json.loads(body)
        require(isinstance(nodes, dict), "comfy_response", "Expected ComfyUI object_info")
        results["missing_nodes"] = sorted(set(required_nodes) - set(nodes))
        results["nodes_and_local_files_present"] = bool(model_files) and not results["missing_nodes"]
        results["models_verified_locally_only"] = True
        results["remote_model_access_unverified"] = True
    except (OSError, ValueError) as error:
        results["error"] = str(error)
    # Even matching local files do not establish that a remote server can see
    # them or execute a graph. Keep this distinct from an executable capability.
    results["executable_capability"] = False
    return results


def _rate(value, label="fps") -> Fraction:
    require(isinstance(value, str), "motion_clock", "FPS must be a rational string", label)
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValidationError("motion_clock", "Invalid FPS rational", label) from error
    require(0 < rate <= 240, "motion_clock", "FPS outside supported range", label)
    return rate


def _vector(value, length, label, *, lo=None, hi=None):
    require(isinstance(value, list) and len(value) == length, "motion_vector", f"Expected {length} numbers", label)
    return [number(x, label, minimum=lo, maximum=hi) for x in value]


def validate_spec(spec: dict) -> dict:
    """Normalize explicit parameters; no prompt/keyword/seed-based choice."""
    d = clone(mapping(spec, "spec"))
    allowed = {"schema", "text", "fps", "frame_count", "width", "height", "font_size",
               "extrusion_px", "center", "color", "side_color", "light", "ambient",
               "camera_distance_px", "focal_length_px", "animation", "read_window",
               "min_face_cosine", "supersampling"}
    require(not (set(d)-allowed), "motion_parameter", "Unknown motion parameters: " + ", ".join(sorted(set(d)-allowed)))
    require(d.get("schema") == SCHEMA, "motion_schema", f"Expected {SCHEMA}")
    text = nonempty(d.get("text"), "text")
    require(len(text) <= 64 and "\n" not in text and "\r" not in text,
            "motion_text", "Use one explicit line, at most 64 characters")
    require(unicodedata.normalize("NFC", text) == text and
            not any(unicodedata.combining(c) or unicodedata.bidirectional(c) in {"R", "AL"} for c in text),
            "motion_shaping", "This per-glyph route supports NFC text without joining scripts; supply complete lettering elsewhere")
    r = _rate(d.get("fps"))
    d["fps"] = f"{r.numerator}/{r.denominator}"
    for key in ("frame_count", "width", "height", "font_size"):
        integer(d.get(key), key, minimum=1)
    require(d["frame_count"] <= 18000 and max(d["width"], d["height"]) <= 4096 and d["font_size"] <= 1024,
            "motion_scope", "Motion sequence exceeds supported dimensions/duration")
    d.setdefault("extrusion_px", 12.0)
    number(d["extrusion_px"], "extrusion_px", minimum=0.5, maximum=512)
    d.setdefault("center", [0.5, 0.5])
    _vector(d["center"], 2, "center", lo=0, hi=1)
    for key, default in (("color", [246, 227, 181]), ("side_color", [104, 53, 27])):
        d.setdefault(key, default)
        require(isinstance(d[key], list) and len(d[key]) == 3 and all(type(c) is int and 0 <= c <= 255 for c in d[key]),
                "motion_color", "Colors must be three RGB bytes", key)
    d.setdefault("light", [-0.4, 0.7, 1.0])
    _vector(d["light"], 3, "light")
    require(np.linalg.norm(d["light"]) > 0, "motion_light", "Light direction cannot be zero")
    d.setdefault("ambient", 0.35)
    number(d["ambient"], "ambient", minimum=0, maximum=1)
    d.setdefault("camera_distance_px", float(max(d["width"], d["height"])*2))
    d.setdefault("focal_length_px", d["camera_distance_px"])
    for key in ("camera_distance_px", "focal_length_px"):
        number(d[key], key, minimum=10, maximum=100000)
    d.setdefault("min_face_cosine", 0.1)
    number(d["min_face_cosine"], "min_face_cosine", minimum=0, maximum=1)
    d.setdefault("supersampling", 1)
    require(type(d["supersampling"]) is int and d["supersampling"] in {1, 2}, "motion_samples", "Supersampling must be 1 or 2")
    a = mapping(d.get("animation"), "animation")
    require(not (set(a)-{"module", "keyframes", "easing", "hinge_frames", "stagger_frames"}),
            "motion_animation", "Unknown animation parameters")
    require(a.get("module") in MODULES, "motion_module", "Choose a supported explicit module")
    a.setdefault("easing", "smooth")
    require(a["easing"] in {"linear", "smooth", "arrive", "exit", "camera"}, "motion_easing", "Unsupported easing")
    keys = a.get("keyframes")
    require(isinstance(keys, list) and bool(keys), "motion_keys", "Supply explicit keyframes")
    previous = -1
    for i, key in enumerate(keys):
        mapping(key, f"keyframes.{i}")
        require(not (set(key)-{"frame", "rotation_deg", "scale", "offset_px"}), "motion_key", "Unknown keyframe parameters")
        integer(key.get("frame"), "frame")
        require(previous < key["frame"] < d["frame_count"], "motion_key_order", "Keyframes must be strictly increasing inside the sequence")
        previous = key["frame"]
        _vector(key.get("rotation_deg"), 3, "rotation_deg", lo=-3600, hi=3600)
        key.setdefault("scale", 1.0)
        number(key["scale"], "scale", minimum=0.01, maximum=10)
        key.setdefault("offset_px", [0, 0, 0])
        _vector(key["offset_px"], 3, "offset_px", lo=-100000, hi=100000)
    require(keys[0]["frame"] == 0 and (len(keys) == 1 or keys[-1]["frame"] == d["frame_count"]-1),
            "motion_key_coverage", "First key must be frame 0; moving keys must cover the last frame")
    if a["module"] == "hinge_unfold":
        a.setdefault("hinge_frames", max(1, d["frame_count"]//2))
        integer(a["hinge_frames"], "hinge_frames", minimum=1)
        require(a["hinge_frames"] < d["frame_count"], "hinge_window", "The hinge must leave a reading interval")
        a.setdefault("stagger_frames", 1.0)
        number(a["stagger_frames"], "stagger_frames", minimum=0, maximum=30)
    else:
        require("hinge_frames" not in a and "stagger_frames" not in a, "motion_parameter", "Hinge parameters require hinge_unfold")
    d.setdefault("read_window", {"start_frame": a.get("hinge_frames", 0), "end_frame": d["frame_count"]})
    rw = mapping(d["read_window"], "read_window")
    require(set(rw) == {"start_frame", "end_frame"}, "motion_read_window", "Reading interval requires start_frame/end_frame")
    integer(rw["start_frame"], "read_window.start_frame")
    integer(rw["end_frame"], "read_window.end_frame", minimum=1)
    require(0 <= rw["start_frame"] < rw["end_frame"] <= d["frame_count"], "motion_read_window", "Invalid reading interval")
    return d


def _glyphs(spec, font_path):
    from fontTools.ttLib import TTFont
    from visual_fidelity.type_layout import glyph_metrics
    font = ImageFont.truetype(str(font_path), spec["font_size"])
    with TTFont(str(font_path), lazy=True) as face:
        cmap = face.getBestCmap() or {}
        require(all(ord(c) in cmap for c in spec["text"] if not c.isspace()),
                "font_coverage", "Chosen font lacks one or more requested characters")
    metrics, width = glyph_metrics(spec["text"], font)
    whole = font.getbbox(spec["text"], anchor="ls")
    mid_y = (whole[1]+whole[3])/2
    glyphs = []
    for item in metrics:
        if item["char"].isspace():
            continue
        x0, y0, x1, y1 = font.getbbox(item["char"], anchor="ls")
        pad = 2
        mask = Image.new("L", (x1-x0+2*pad, y1-y0+2*pad))
        ImageDraw.Draw(mask).text((pad-x0, pad-y0), item["char"], font=font, fill=255, anchor="ls", features=["-liga"])
        alpha = np.asarray(mask, np.uint8)
        require(bool(np.any(alpha)), "empty_glyph", "Requested glyph has no visible outline")
        origin = np.array([item["origin"] + x0-pad-width/2, mid_y-y0+pad])
        contours, _ = cv2.findContours((alpha >= 128).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        contours = [cv2.approxPolyDP(c, 0.35, True)[:, 0, :].astype(float) for c in contours if len(c) >= 3]
        glyphs.append({"id": len(glyphs)+1, "char": item["char"], "mask": alpha,
                       "origin": origin, "contours": contours,
                       "pivot": np.array([item["center"]-width/2, mid_y, 0.0])})
    require(bool(glyphs), "empty_type", "Text has no drawable glyphs")
    return glyphs


def _key_at(spec, frame):
    keys = spec["animation"]["keyframes"]
    if len(keys) == 1:
        return keys[0]
    right = next((i for i, k in enumerate(keys) if k["frame"] >= frame), len(keys)-1)
    if right == 0:
        return keys[0]
    a, b = keys[right-1], keys[right]
    u = portable.ease(spec["animation"]["easing"], (frame-a["frame"])/(b["frame"]-a["frame"]))
    result = {}
    for key in ("rotation_deg", "offset_px"):
        result[key] = np.array(a[key])*(1-u) + np.array(b[key])*u
    result["scale"] = math.exp(math.log(a["scale"])*(1-u)+math.log(b["scale"])*u)
    return result


def _triangle(canvas, zbuf, ids, xy, z, color, glyph_id, texture=None, uv=None):
    h, w = zbuf.shape
    lo = np.maximum(np.floor(xy.min(0)).astype(int), 0)
    hi = np.minimum(np.ceil(xy.max(0)).astype(int), [w-1, h-1])
    if np.any(lo > hi):
        return
    yy, xx = np.mgrid[lo[1]:hi[1]+1, lo[0]:hi[0]+1]
    x, y = xx+0.5, yy+0.5
    a, b, c = xy
    den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
    if abs(den) < 1e-9:
        return
    wa = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/den
    wb = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/den
    wc = 1-wa-wb
    inside = (wa >= -1e-7) & (wb >= -1e-7) & (wc >= -1e-7)
    invz = wa/z[0]+wb/z[1]+wc/z[2]
    depth = 1/np.maximum(invz, 1e-12)
    region_z = zbuf[lo[1]:hi[1]+1, lo[0]:hi[0]+1]
    keep = inside & (depth < region_z-1e-5)
    alpha = np.ones_like(depth, dtype=np.float32)
    if texture is not None:
        tx = (wa*uv[0, 0]/z[0]+wb*uv[1, 0]/z[1]+wc*uv[2, 0]/z[2])*depth
        ty = (wa*uv[0, 1]/z[0]+wb*uv[1, 1]/z[1]+wc*uv[2, 1]/z[2])*depth
        alpha = cv2.remap(texture, tx.astype(np.float32), ty.astype(np.float32), cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT).astype(np.float32)/255
        keep &= alpha > 1/255
    region = canvas[lo[1]:hi[1]+1, lo[0]:hi[0]+1]
    region[keep, :3] = color
    region[keep, 3] = alpha[keep]
    region_z[keep] = depth[keep]
    ids[lo[1]:hi[1]+1, lo[0]:hi[0]+1][keep] = glyph_id


def _frame(spec, glyphs, frame):
    ss = spec["supersampling"]
    w, h = spec["width"]*ss, spec["height"]*ss
    canvas = np.zeros((h, w, 4), np.float32)
    zbuf = np.full((h, w), np.inf)
    ids = np.zeros((h, w), np.uint16)
    k = _key_at(spec, frame)
    rot = portable.rotation(*np.deg2rad(k["rotation_deg"]))
    offset = np.asarray(k["offset_px"])
    light = np.array(spec["light"], float)
    light /= np.linalg.norm(light)
    center = (spec["center"][0]*w, spec["center"][1]*h)
    reading = spec["read_window"]["start_frame"] <= frame < spec["read_window"]["end_frame"]
    face_angles = []
    for gi, glyph in enumerate(glyphs):
        gr = np.eye(3)
        lift = 0.0
        if spec["animation"]["module"] == "hinge_unfold":
            a = spec["animation"]
            angle, lift = portable.hinge_state(frame/a["hinge_frames"], gi, len(glyphs), spec["font_size"],
                                               float(a["stagger_frames"])/float(Fraction(spec["fps"])))
            gr = portable.rotation(0, angle, 0)
        normal = rot @ gr @ np.array([0, 0, 1.0])
        face_angles.append(float(normal[2]))
        if reading:
            require(normal[2] >= spec["min_face_cosine"], "type_edge_on", "A glyph face cannot meet the requested reading angle", str(frame))
        def transform(points):
            p = np.asarray(points, float)
            p = (p-glyph["pivot"]) @ gr.T + glyph["pivot"] + np.array([0, 0, lift])
            return (p*k["scale"]) @ rot.T + offset
        def project(points):
            try:
                return portable.project(points, spec["camera_distance_px"], spec["focal_length_px"]*ss, center)
            except ValueError as error:
                raise ValidationError("type_near_plane", str(error), str(frame)) from error
        texture = glyph["mask"]
        th, tw = texture.shape
        ox, oy = glyph["origin"]
        depth = spec["extrusion_px"]
        uv = np.array([[0, 0], [tw-1, 0], [tw-1, th-1], [0, th-1]], float)
        for zside, facing in ((-depth/2, -1), (depth/2, 1)):
            vertices = transform([[ox, oy, zside], [ox+tw-1, oy, zside],
                                  [ox+tw-1, oy-th+1, zside], [ox, oy-th+1, zside]])
            xy, z = project(vertices)
            require(np.all(xy >= 0) and np.all(xy < [w, h]), "type_outside_picture", "Glyph geometry would be clipped; revise placement/scale", str(frame))
            n = normal*facing
            intensity = spec["ambient"]+(1-spec["ambient"])*max(float(n@light), 0.0)
            color = np.asarray(spec["color"], float)/255*intensity
            for indices in ([0, 1, 2], [0, 2, 3]):
                _triangle(canvas, zbuf, ids, xy[indices], z[indices], color, glyph["id"], texture, uv[indices])
        for contour in glyph["contours"]:
            for ai, bi in zip(contour, np.roll(contour, -1, axis=0)):
                a = np.array([ox+ai[0], oy-ai[1], -depth/2])
                b = np.array([ox+bi[0], oy-bi[1], -depth/2])
                edge = b-a
                n = np.array([edge[1], -edge[0], 0.0])
                n /= max(np.linalg.norm(n), 1e-9)
                n = rot @ gr @ n
                vertices = transform([a, b, b+[0, 0, depth], a+[0, 0, depth]])
                xy, z = project(vertices)
                intensity = spec["ambient"]+(1-spec["ambient"])*max(float(n@light), 0.0)
                color = np.asarray(spec["side_color"], float)/255*intensity
                for indices in ([0, 1, 2], [0, 2, 3]):
                    _triangle(canvas, zbuf, ids, xy[indices], z[indices], color, glyph["id"])
    if ss > 1:
        alpha = cv2.resize(canvas[..., 3], (spec["width"], spec["height"]), interpolation=cv2.INTER_AREA)
        pm = cv2.resize(canvas[..., :3]*canvas[..., 3:4], (spec["width"], spec["height"]), interpolation=cv2.INTER_AREA)
        rgb = np.divide(pm, alpha[..., None], out=np.zeros_like(pm), where=alpha[..., None] > 1e-9)
        canvas = np.dstack([rgb, alpha])
        ids = cv2.resize(ids, (spec["width"], spec["height"]), interpolation=cv2.INTER_NEAREST)
    rgba = np.round(np.clip(canvas, 0, 1)*255).astype(np.uint8)
    rgba[rgba[..., 3] == 0, :3] = 0
    require(int((rgba[..., 3] > 0).sum()) >= 4, "empty_motion_frame", "Requested motion is invisible", str(frame))
    missing = [g["id"] for g in glyphs if not np.any((ids == g["id"]) & (rgba[..., 3] > 0))]
    require(not (reading and missing), "hidden_glyph", "A glyph is wholly hidden during the reading interval", str(frame))
    return rgba, ids, {"frame": frame, "reading": reading, "min_face_cosine": min(face_angles),
                       "visible_glyphs": len(glyphs)-len(missing), "alpha_pixels": int((rgba[..., 3] > 0).sum())}


def render_sequence(spec: dict, output_dir: str | Path, *, font_path: str | Path,
                    font_license: str) -> dict:
    """Render immutable PNG RGBA frames and per-glyph IDs. Returns saved manifest."""
    d = validate_spec(spec)
    font_path, target = Path(font_path).resolve(), Path(output_dir).resolve()
    require(font_path.is_file(), "font_missing", "Supply the chosen font file")
    nonempty(font_license, "font_license")
    require(not target.exists(), "output_exists", "Use a new directory; motion exports are immutable")
    target.parent.mkdir(parents=True, exist_ok=True)
    font_hash = file_sha256(font_path)
    implementation = implementation_fingerprint()
    glyphs = _glyphs(d, font_path)
    stage = Path(tempfile.mkdtemp(prefix=".motngrfx-", dir=target.parent))
    try:
        frames, metrics = [], []
        for index in range(d["frame_count"]):
            rgba, ids, measure = _frame(d, glyphs, index)
            name, id_name = f"{index:06d}.png", f"glyphs-{index:06d}.png"
            Image.fromarray(rgba).save(stage/name)
            Image.fromarray(ids).save(stage/id_name)
            frames.append({"index": index, "path": str(target/name), "sha256": file_sha256(stage/name),
                           "glyph_ids_path": str(target/id_name), "glyph_ids_sha256": file_sha256(stage/id_name)})
            metrics.append(measure)
        verify_file(str(font_path), font_hash, "font changed during render")
        require(implementation == implementation_fingerprint(), "backend_changed", "Implementation changed during the render")
        manifest = {"schema": SEQUENCE_SCHEMA, "backend": "motngrfx-portable", "backend_version": VERSION,
                    "upstream_commit": UPSTREAM_COMMIT, "fps": d["fps"], "frame_count": d["frame_count"],
                    "width": d["width"], "height": d["height"], "alpha": "straight", "color_space": "sRGB",
                    "geometry": "raster-contour extrusion with front/back caps, side walls and depth buffer",
                    "coordinate_space": "synthetic camera; no footage camera solve", "spec": d, "spec_sha256": digest(d),
                    "font": {"path": str(font_path), "sha256": font_hash, "license_attestation": font_license,
                             "license_verified_by_backend": False, "redistributed": False},
                    "glyphs": [{"id": g["id"], "char": g["char"]} for g in glyphs],
                    "implementation": implementation, "frames": frames,
                    "metrics": metrics, "technical_render": "passed", "perceptual_review": "unverified",
                    "user_approved": False, "model_inference": False, "fallbacks": []}
        manifest["manifest_sha256"] = digest(manifest)
        (stage/"manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        stage.rename(target)
        return manifest
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def validate_manifest(manifest: dict | str | Path, *, verify_files=True) -> dict:
    if isinstance(manifest, (str, Path)):
        manifest = json.loads(Path(manifest).read_text(encoding="utf-8"))
    m = clone(mapping(manifest, "manifest"))
    require(m.get("schema") == SEQUENCE_SCHEMA and m.get("alpha") == "straight", "motion_manifest", "Expected a straight-alpha motion sequence")
    _rate(m.get("fps"))
    for key in ("frame_count", "width", "height"):
        integer(m.get(key), key, minimum=1)
    if "manifest_sha256" in m:
        body = {k: v for k, v in m.items() if k != "manifest_sha256"}
        require(digest(body) == m["manifest_sha256"], "motion_manifest_hash", "Motion manifest changed")
    frames = m.get("frames")
    require(isinstance(frames, list) and len(frames) == m["frame_count"], "motion_coverage", "A frame is required at every source index")
    for index, frame in enumerate(frames):
        require(type(frame.get("index")) is int and frame["index"] == index, "motion_coverage", "Frame order or coverage changed")
        sha256(frame.get("sha256"), "frame.sha256")
        if verify_files:
            verify_file(frame["path"], frame["sha256"], f"motion frame {index}")
            with Image.open(frame["path"]) as image:
                require(image.mode == "RGBA" and image.size == (m["width"], m["height"]), "motion_frame_format", "Frame must be RGBA at declared dimensions")
            if "glyph_ids_path" in frame:
                verify_file(frame["glyph_ids_path"], frame["glyph_ids_sha256"], f"glyph IDs {index}")
    return m


def composite_frame(source_rgb, layer_rgba, *, mode="front", matte=None,
                    min_visible=0.70, min_occluded=0.0, glyph_ids=None,
                    min_glyph_visible=0.50):
    """Compose in linear light; fail coverage/occlusion, never reorder/drop type."""
    src, layer = np.asarray(source_rgb), np.asarray(layer_rgba)
    require(src.dtype == np.uint8 and src.ndim == 3 and src.shape[2] == 3 and
            layer.dtype == np.uint8 and layer.shape == (*src.shape[:2], 4),
            "motion_raster", "Expected same-size RGB and straight RGBA uint8 rasters")
    require(mode in {"front", "behind"}, "motion_order", "Explicit front or behind order required")
    for key, value in (("min_visible", min_visible), ("min_occluded", min_occluded), ("min_glyph_visible", min_glyph_visible)):
        number(value, key, minimum=0, maximum=1)
    a = layer[..., 3].astype(np.float64)/255
    require(float(a.sum()) > 1e-9, "empty_motion_frame", "Requested layer is empty")
    if mode == "behind":
        require(matte is not None, "matte_missing", "Behind type requires a verified subject matte")
        o = np.asarray(matte)
        require(o.shape == src.shape[:2] and np.issubdtype(o.dtype, np.number), "matte_dimensions", "Matte must match source pixels")
        o = o.astype(float)/(255 if o.dtype == np.uint8 else 1)
        require(np.all(np.isfinite(o)) and np.all((0 <= o) & (o <= 1)), "matte_range", "Matte values must be finite alpha in [0,1] or uint8")
    else:
        require(min_occluded == 0, "motion_order", "Front composition cannot satisfy a required occlusion")
        o = np.zeros_like(a)
    if glyph_ids is not None:
        require(np.asarray(glyph_ids).shape == a.shape, "glyph_ids", "Glyph IDs must match the raster")
        require(np.issubdtype(np.asarray(glyph_ids).dtype, np.integer) and np.any(np.asarray(glyph_ids) > 0),
                "glyph_ids", "Glyph IDs must identify visible letters")
    require(min_glyph_visible == 0 or glyph_ids is not None, "glyph_evidence_missing",
            "A per-glyph visibility floor requires the original glyph ID pass")
    metrics = portable.visibility(a, o, glyph_ids)
    require(metrics["visible"]+1e-9 >= min_visible, "type_legibility", "Word coverage cannot meet the explicit visibility floor")
    require(metrics["occluded"]+1e-9 >= min_occluded, "occlusion_missing", "Requested behind interaction is not present in the supplied matte")
    require(all(x["visible"]+1e-9 >= min_glyph_visible for x in metrics["glyph_visible"]),
            "glyph_legibility", "A glyph cannot meet the explicit visibility floor")
    effective = a*(1-o)
    def linear(x):
        v = x.astype(float)/255
        return np.where(v <= 0.04045, v/12.92, ((v+0.055)/1.055)**2.4)
    mixed = linear(src)*(1-effective[..., None]) + linear(layer[..., :3])*effective[..., None]
    srgb = np.where(mixed <= 0.0031308, 12.92*mixed, 1.055*np.maximum(mixed, 0)**(1/2.4)-0.055)
    result = np.round(np.clip(srgb, 0, 1)*255).astype(np.uint8)
    result[effective == 0] = src[effective == 0]
    return result, {**metrics, "mode": mode, "order_changed": False, "effect_dropped": False,
                    "effective_pixels": int((effective > 0).sum()), "legibility_kind": "alpha coverage; perceptual legibility unverified"}


def probe_video(path: str | Path) -> dict:
    require(shutil.which("ffprobe"), "media_backend", "FFprobe is required")
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-show_frames",
               "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,time_base:frame=best_effort_timestamp_time", "-of", "json", str(path)]
    p = subprocess.run(command, capture_output=True, text=True, check=True)
    info = json.loads(p.stdout)
    require(len(info.get("streams", [])) == 1 and bool(info.get("frames")), "video_probe", "No decoded video frames")
    stream, frames = info["streams"][0], info["frames"]
    rate = _rate(stream["avg_frame_rate"])
    pts = [Fraction(x["best_effort_timestamp_time"]) for x in frames]
    tolerance = max(float(Fraction(stream.get("time_base", "1/1000000")))*1.1, 2e-6)
    require(all(abs(float((b-a)-1/rate)) <= tolerance for a, b in zip(pts, pts[1:])),
            "video_vfr", "This adapter requires a measured CFR source; no silent frame duplication")
    return {"fps": f"{rate.numerator}/{rate.denominator}", "frame_count": len(pts),
            "width": stream["width"], "height": stream["height"], "pts_start_s": float(pts[0]), "cfr": True}


def _matte_manifest(matte, source_sha, clock):
    if isinstance(matte, (str, Path)):
        matte = json.loads(Path(matte).read_text(encoding="utf-8"))
    m = clone(mapping(matte, "matte"))
    require(m.get("source_sha256") == source_sha, "matte_source", "Matte belongs to a different source")
    require(m.get("clock") == "source", "matte_clock", "Matte must explicitly use the source clock")
    for key in ("frame_count", "width", "height"):
        require(m.get(key) == clock[key], "matte_clock", "Matte dimensions/coverage do not match source", key)
    require(_rate(m.get("fps")) == _rate(clock["fps"]), "matte_clock", "Matte FPS differs from source")
    frames = m.get("frames")
    require(isinstance(frames, list) and len(frames) == clock["frame_count"], "matte_coverage", "Every source frame requires a matte")
    for index, frame in enumerate(frames):
        require(frame.get("index") == index, "matte_coverage", "Matte indices are missing or reordered")
        verify_file(frame["path"], frame["sha256"], f"matte {index}")
        with Image.open(frame["path"]) as image:
            require(image.mode == "L" and image.size == (clock["width"], clock["height"]), "matte_dimensions", "Use grayscale mattes in exact source dimensions")
    return m


def _decode(path, width, height):
    process = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-f", "rawvideo",
                                "-pix_fmt", "rgb24", "-vsync", "0", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = width*height*3
    try:
        while True:
            raw = process.stdout.read(size)
            if not raw:
                break
            require(len(raw) == size, "video_decode", "Incomplete decoded frame")
            yield np.frombuffer(raw, np.uint8).reshape(height, width, 3).copy()
        require(process.wait() == 0, "video_decode", "FFmpeg decoding failed")
    finally:
        if process.poll() is None:
            # FFmpeg traps SIGTERM and may try to flush a full pipe. A consumer
            # that rejected a frame has intentionally stopped reading it.
            process.kill()
            process.wait(timeout=5)
        process.stdout.close()


def _load_layer(frame):
    layer = np.asarray(Image.open(frame["path"]).convert("RGBA"))
    ids = np.asarray(Image.open(frame["glyph_ids_path"])) if "glyph_ids_path" in frame else None
    return layer, ids


def verify_render(source_path: str | Path, output_path: str | Path, manifest: dict | str | Path,
                  *, mode="front", matte=None, cut_frames=(), min_visible=0.70,
                  min_occluded=0.0, min_glyph_visible=0.50, pixel_tolerance=0) -> dict:
    """Decode every frame and compare with required composition and source clock.

    Lossless RGB/FFV1 outputs can use tolerance zero. This check proves frame
    identity/order, source preservation and matte order, not subjective quality.
    """
    m = validate_manifest(manifest)
    source_hash = file_sha256(source_path)
    implementation = implementation_fingerprint()
    clock, rendered = probe_video(source_path), probe_video(output_path)
    require(all(clock[k] == rendered[k] == m[k] for k in ("fps", "frame_count", "width", "height")),
            "render_clock", "Rendered source clock/dimensions differ")
    require(abs(clock["pts_start_s"]-rendered["pts_start_s"]) <= 1e-6,
            "render_pts", "Rendered PTS origin differs from source")
    integer(pixel_tolerance, "pixel_tolerance")
    require(pixel_tolerance <= 10, "pixel_tolerance", "Use a lossless proof or a bounded pixel tolerance")
    masks = _matte_manifest(matte, source_hash, clock) if mode == "behind" else None
    cuts = sorted(set(cut_frames))
    require(all(type(x) is int and 0 < x < clock["frame_count"] for x in cuts), "cut_frame", "Cuts must be frame indices inside source")
    src_frames = _decode(source_path, clock["width"], clock["height"])
    dst_frames = _decode(output_path, clock["width"], clock["height"])
    measurements = []
    source_jumps, output_jumps = {}, {}
    previous_s = previous_o = None
    max_error = 0
    try:
        for index, (src, out) in enumerate(zip(src_frames, dst_frames)):
            layer, ids = _load_layer(m["frames"][index])
            mask = np.asarray(Image.open(masks["frames"][index]["path"])) if masks else None
            expected, metric = composite_frame(src, layer, mode=mode, matte=mask, glyph_ids=ids,
                                               min_visible=min_visible, min_occluded=min_occluded,
                                               min_glyph_visible=min_glyph_visible)
            error = int(np.abs(expected.astype(int)-out.astype(int)).max())
            max_error = max(max_error, error)
            require(error <= pixel_tolerance, "render_mismatch", "Rendered pixels fail source/occlusion composition; possible cut/frame/order error", str(index))
            if index in cuts:
                source_jumps[index] = float(np.abs(src.astype(float)-previous_s).mean())
                output_jumps[index] = float(np.abs(out.astype(float)-previous_o).mean())
            previous_s, previous_o = src, out
            measurements.append({"frame": index, **metric})
    finally:
        src_frames.close()
        dst_frames.close()
    require(len(measurements) == clock["frame_count"], "render_frames", "Decoded frame coverage differs")
    require(implementation == implementation_fingerprint(), "backend_changed", "Implementation changed during review")
    verify_file(str(source_path), source_hash, "source changed during review")
    return {"schema": "motngrfx-render-review/1", "technical_status": "passed", "source_sha256": source_hash,
            "render_sha256": file_sha256(output_path), "sequence_sha256": digest(m), "source_clock": clock,
            "all_frames_compared": len(measurements), "pixel_error_max": max_error, "pixel_tolerance": pixel_tolerance,
            "cut_frames": cuts, "cut_frame_identity_verified": True, "source_cut_jumps": source_jumps,
            "render_cut_jumps": output_jumps, "occlusion": measurements, "mode": mode,
            "perceptual_motion": "unverified", "audio_listened": "unverified", "user_approved": False,
            "fallbacks": []}


def render_on_video(source_path: str | Path, output_path: str | Path, manifest: dict | str | Path,
                    *, mode="front", matte=None, cut_frames=(), min_visible=0.70,
                    min_occluded=0.0, min_glyph_visible=0.50) -> dict:
    """Render a full source-clock sequence; keep source audio, validate all pixels."""
    source_path, output_path = Path(source_path).resolve(), Path(output_path).resolve()
    require(source_path.is_file() and output_path != source_path and not output_path.exists(),
            "output_exists", "Source/existing artifacts are immutable; choose a new output")
    require(not output_path.with_suffix(output_path.suffix+".review.json").exists(),
            "output_exists", "An existing review must not be overwritten")
    require(output_path.suffix.lower() in {".mkv", ".mp4"}, "render_container", "Use MKV (FFV1) or MP4 (lossless RGB H.264)")
    require(shutil.which("ffmpeg"), "media_backend", "FFmpeg is required")
    m = validate_manifest(manifest)
    source_hash = file_sha256(source_path)
    clock = probe_video(source_path)
    implementation = implementation_fingerprint()
    require(abs(clock["pts_start_s"]) <= 1e-6, "source_pts",
            "This adapter requires source PTS starting at zero; normalize with an explicit clock mapping first")
    require(all(clock[k] == m[k] for k in ("fps", "frame_count", "width", "height")), "sequence_clock", "Sequence must match the complete source clock and raster")
    masks = _matte_manifest(matte, source_hash, clock) if mode == "behind" else None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".motngrfx-video-", dir=output_path.parent))
    encoded = temporary/output_path.name
    codec = ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0"] if output_path.suffix.lower() == ".mkv" else ["-c:v", "libx264rgb", "-crf", "0", "-preset", "veryfast", "-pix_fmt", "rgb24"]
    cmd = ["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{clock['width']}x{clock['height']}",
           "-r", clock["fps"], "-i", "pipe:0", "-i", str(source_path), "-map", "0:v:0", "-map", "1:a?",
           *codec, "-c:a", "copy", "-fps_mode", "passthrough", str(encoded)]
    process = None
    try:
        with (temporary/"ffmpeg.log").open("wb") as errors:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
            decoded = _decode(source_path, clock["width"], clock["height"])
            seen = 0
            try:
                for index, src in enumerate(decoded):
                    layer, ids = _load_layer(m["frames"][index])
                    mask = np.asarray(Image.open(masks["frames"][index]["path"])) if masks else None
                    out, _ = composite_frame(src, layer, mode=mode, matte=mask, glyph_ids=ids,
                                             min_visible=min_visible, min_occluded=min_occluded,
                                             min_glyph_visible=min_glyph_visible)
                    process.stdin.write(out.tobytes())
                    seen += 1
            finally:
                decoded.close()
            process.stdin.close()
            require(process.wait() == 0, "video_encode", (temporary/"ffmpeg.log").read_text(errors="replace")[-2000:])
        require(seen == clock["frame_count"], "source_frames", "Source decoded frame count changed")
        verify_file(str(source_path), source_hash, "source changed during render")
        require(implementation == implementation_fingerprint(), "backend_changed", "Implementation changed during composition")
        report = verify_render(source_path, encoded, m, mode=mode, matte=masks, cut_frames=cut_frames,
                               min_visible=min_visible, min_occluded=min_occluded,
                               min_glyph_visible=min_glyph_visible, pixel_tolerance=0)
        encoded.rename(output_path)
        report["render_path"] = str(output_path)
        report["source_path"] = str(source_path)
        report["audio_policy"] = "original audio streams copied; listening unverified"
        report["implementation"] = implementation
        report["report_sha256"] = digest(report)
        output_path.with_suffix(output_path.suffix+".review.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
        return report
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        shutil.rmtree(temporary, ignore_errors=True)
