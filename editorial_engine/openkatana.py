"""Pinned OpenKatana analysis and real local rendering adapters.

The Node renderer runs the upstream Canvas engine, with an explicitly declared
Canvas implementation. It is not Chromium pixel parity or a WebGL fallback.
Sources, clocks, generated PNGs and runtime limitations remain in each receipt.
"""

from __future__ import annotations

from fractions import Fraction
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from .contracts import ValidationError, clone, file_sha256, require


UPSTREAM_COMMIT = "b9282bf0740a7df5b5a8862b5e289ef4cd642641"
VENDOR_MANIFEST_SHA256 = "32e45b972e17b21ff37b3f90e1e52a6505200aafa3ca007c253aa9a4f6183599"
VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "openkatana"
PACKAGE = "_editor_ultra_openkatana"
REPORT_SCHEMA = "editor-ultra-openkatana/1"
CLOCK_SCHEMA = "openkatana-clockmap/1"


def _run(arguments, *, timeout_s=300, input=None):
    try:
        return subprocess.run([str(v) for v in arguments], input=input, capture_output=True,
                              check=True, timeout=timeout_s).stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace")[-2000:]
        raise ValidationError("openkatana_process", detail or "Local process failed") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidationError("openkatana_process", str(error)) from error


def _verify_vendor():
    path = VENDOR / "VENDOR-MANIFEST.json"
    require(path.is_file() and file_sha256(path) == VENDOR_MANIFEST_SHA256,
            "openkatana_vendor", "Pinned vendor manifest is absent or changed")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    require(manifest["commit"] == UPSTREAM_COMMIT, "openkatana_vendor", "Unexpected upstream revision")
    for entry in manifest["files"]:
        candidate = (VENDOR / entry["path"]).resolve()
        require(candidate.is_relative_to(VENDOR.resolve()) and candidate.is_file()
                and file_sha256(candidate) == entry["sha256"],
                "openkatana_vendor", "Vendored implementation bytes changed", entry["path"])
    return manifest


def _module(name):
    _verify_vendor()
    if PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            PACKAGE, VENDOR / "openkatana" / "__init__.py",
            submodule_search_locations=[str(VENDOR / "openkatana")],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = module
        spec.loader.exec_module(module)
    return importlib.import_module(PACKAGE + "." + name)


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _output(path):
    path = Path(path).resolve()
    require(not path.exists(), "output_exists", "Choose a new OpenKatana output directory", str(path))
    path.mkdir(parents=True)
    return path


def _file(path):
    path = Path(path).resolve()
    require(path.is_file(), "file_missing", "Input file is missing", str(path))
    return {"path": str(path), "sha256": file_sha256(path), "bytes": path.stat().st_size}


def _unchanged(files):
    for item in files:
        require(file_sha256(item["path"]) == item["sha256"], "source_changed",
                "Input changed during execution", item["path"])


def _base(operation, *, trusted_code=False):
    return {"schema": REPORT_SCHEMA, "operation": operation,
            "upstream": {"repository": "https://github.com/rk0neki/OpenKatana",
                         "commit": UPSTREAM_COMMIT, "version": "0.1.3", "license": "Apache-2.0",
                         "vendor_manifest_sha256": VENDOR_MANIFEST_SHA256},
            "external_model_executed": None if trusted_code else False,
            "external_api_called": None if trusted_code else False,
            "credits_used": None if trusted_code else 0,
            "external_activity": "not_observed_trusted_code" if trusted_code else "adapter_local_only",
            "perceptual_review": "not_performed", "user_approval": "pending"}


def _save_report(output, report):
    path = output / "adapter-receipt.json"
    _json(path, report)
    return {**report, "receipt": _file(path)}


def _probe_media(path):
    return json.loads(_run(["ffprobe", "-v", "error", "-count_frames", "-show_streams", "-show_format",
                            "-of", "json", path]))


def _node():
    return os.environ.get("EDITOR_ULTRA_NODE") or shutil.which("node")


def _canvas_package():
    configured = os.environ.get("EDITOR_ULTRA_OPENKATANA_CANVAS_MODULE")
    choices = [Path(configured)] if configured else [
        VENDOR / "adapter-node" / "node_modules" / "@napi-rs" / "canvas",
        Path(__file__).parent / "backends" / "motionlab" / "node_modules" / "@napi-rs" / "canvas",
    ]
    for path in choices:
        if (path / "package.json").is_file():
            metadata = json.loads((path / "package.json").read_text())
            require(metadata.get("name") == "@napi-rs/canvas" and metadata.get("version") == "0.1.100",
                    "canvas_version", "Install the locked @napi-rs/canvas 0.1.100 runtime")
            return path.resolve()
    raise ValidationError("canvas_missing",
        "Run npm ci --ignore-scripts --prefix vendor/openkatana/adapter-node, or configure EDITOR_ULTRA_OPENKATANA_CANVAS_MODULE")


def _node_probe():
    if not _node():
        return {"status": "blocked", "reason": "Node.js is not installed"}
    script = """const c=require(process.argv[1]);const x=c.createCanvas(2,2).getContext('2d');
x.fillStyle='red';x.fillRect(0,0,2,2);
if(x.getImageData(0,0,1,1).data[0]!==255)throw Error('Canvas pixel probe failed');
process.stdout.write(JSON.stringify({status:'ready',runtime:'node-canvas',node:process.version,
canvas:require(process.argv[1]+'/package.json').version,canvas_module:process.argv[1],pixel_probe:true}));"""
    try:
        return json.loads(_run([_node(), "-e", script, _canvas_package()], timeout_s=20))
    except (ValidationError, ValueError) as error:
        return {"status": "blocked", "reason": str(error)}


def _browser_probe():
    try:
        runtime = _module("render")
        with runtime.playwright()() as play:
            browser = play.chromium.launch(executable_path=runtime.chrome_path(), headless=True,
                args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
            try:
                page = browser.new_page()
                checks = page.evaluate("""() => ({canvas:!!document.createElement('canvas').getContext('2d'),
webgl:!!document.createElement('canvas').getContext('webgl2')})""")
            finally:
                browser.close()
        return {"status": "ready" if checks["canvas"] else "blocked",
                "canvas": checks["canvas"], "webgl": checks["webgl"], "runtime": "chromium"}
    except Exception as error:
        detail = str(error)
        return {"status": "blocked", "canvas": False, "webgl": False,
                "reason": ("Runtime denied Chromium IPC/socket initialization"
                           if "Operation not permitted" in detail else type(error).__name__ + ": " + detail[:300])}


def _blender_probe():
    try:
        configured = os.environ.get("OPENKATANA_BLENDER")
        executable = Path(configured) if configured else Path(_module("blender_bridge").executable())
        require(executable.is_file() and os.access(executable, os.X_OK), "blender_executable",
                "Configured Blender must be an installed executable")
        version = _run([executable, "--version"], timeout_s=20).decode(errors="replace").splitlines()[0]
        require(version.startswith("Blender "), "blender_executable", "Executable did not identify itself as Blender")
        return {"status": "ready", "path": str(executable.resolve()), "version": version}
    except (ValueError, OSError, IndexError) as error:
        return {"status": "blocked", "reason": str(error)}


def probe_openkatana(*, check_browser=True):
    """Probe installed local execution; never install or download a dependency."""
    try:
        manifest = _verify_vendor()
    except ValidationError as error:
        return {**_base("probe"), "status": "blocked", "reason": str(error), "capabilities": {}}
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    imports = {}
    for name in ("numpy", "PIL", "cv2"):
        try:
            imports[name] = importlib.import_module(name).__version__
        except ImportError:
            imports[name] = None
    node = _node_probe()
    blender = _blender_probe()
    browser = _browser_probe() if check_browser else {"status": "unknown", "canvas": False, "webgl": False}
    codecs = set()
    if not missing:
        text = _run(["ffmpeg", "-hide_banner", "-encoders"], timeout_s=15).decode(errors="replace")
        codecs = {line.split()[1] for line in text.splitlines() if len(line.split()) >= 2}
    def status(ready):
        return "ready" if ready else "blocked"
    basic = not missing and all(imports.values())
    capabilities = {
        "reference_analysis": status(basic), "audio_analysis": status(not missing and imports["numpy"]),
        "timeline_node_canvas": status(basic and node["status"] == "ready" and "libx264" in codecs),
        "timeline_chromium": status(basic and browser["canvas"] and "libx264" in codecs),
        "scene_webgl": status(basic and browser["webgl"] and "libx264" in codecs),
        "blender": status(basic and blender["status"] == "ready" and "libx264" in codecs),
    }
    return {**_base("probe"), "status": "ready" if any(v == "ready" for v in capabilities.values()) else "blocked",
            "capabilities": capabilities, "node_canvas": node, "chromium": browser, "blender": blender,
            "missing_tools": missing, "python_modules": imports, "vendor_files": len(manifest["files"]),
            "limits": ["Readiness is not render approval.", "No automatic switch between 2D, WebGL and Blender."]}


def _clean_measurements(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _clean_measurements(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_clean_measurements(item) for item in value]
    return value


def analyze_reference(source, output_dir, *, start_s=0, duration_s=30,
                      measures=("cuts", "cadence", "look", "textures", "transitions")):
    """Run upstream pixel measurements; report the 60-fps analysis clock separately."""
    original = _file(source)
    require(0 <= float(start_s) and 0 < float(duration_s) <= 120, "analysis_window", "Reference window must be 0..120 seconds")
    output = _output(output_dir)
    result = _module("reference_measure").measure(Path(original["path"]), output, float(start_s),
                                                  float(duration_s), list(measures))
    _unchanged([original])
    files = [_file(p) for p in output.iterdir() if p.is_file()]
    report = {**_base("analyze_reference"), "source": original, "results": _clean_measurements(result),
              "artifacts": files, "clockmap": {"clock": "analysis", "fps": "60", "source_offset_s": str(start_s),
                  "source_time_formula": "source_offset_s + analysis_frame / 60",
                  "source_probe": _probe_media(original["path"])},
              "limits": ["Estimates require visual review; source frames below 60 fps are repeated.",
                         "Resampling does not recover missing source motion or identify exact fonts.",
                         "Unavailable numerical estimates are null in this receipt; raw upstream files are retained."]}
    return _save_report(output, report)


def analyze_audio(source, output_dir, *, start_s=0, duration_s=None, fps=None, beats_per_bar=4):
    """Execute local spectral/onset/beat analysis, without a model or service."""
    original = _file(source)
    require(0 <= float(start_s) and (duration_s is None or 1 <= float(duration_s) <= 1800),
            "analysis_window", "Audio window must have 1..1800 seconds")
    require(type(beats_per_bar) is int and 2 <= beats_per_bar <= 12, "beats_per_bar", "Use 2..12 beats per bar")
    output = _output(output_dir)
    module = _module("audio_analysis")
    result, curves = module.analyze(Path(original["path"]), float(start_s),
                                    None if duration_s is None else float(duration_s),
                                    None if fps is None else float(Fraction(str(fps))), beats_per_bar)
    module.timeline_image(result, curves, output / "audio-analysis.png")
    _json(output / "audio-analysis.json", _clean_measurements(result))
    _unchanged([original])
    return _save_report(output, {**_base("analyze_audio"), "source": original,
        "results": _clean_measurements(result), "artifacts": [_file(p) for p in output.iterdir() if p.is_file()],
        "clockmap": {"clock": "analysis_seconds", "source_offset_s": str(start_s),
                     "source_time_formula": "source_offset_s + analysis_seconds",
                     "output_fps": None if fps is None else str(Fraction(str(fps)))},
        "limits": ["Constant-tempo beat-grid estimate, not verified musical structure.",
                   "Tempo octave and downbeat ambiguities remain in results; listening has not been performed."]})


def _sampling(timeline):
    return [{"f0": shot["f0"], "f1": shot["f1"], "clip": shot.get("clip"),
             "src": shot.get("src", 0), "srcf": shot.get("srcf"),
             "speed": shot.get("speed", 1), "speed1": shot.get("speed1", shot.get("speed", 1)),
             "loop": shot.get("loop", "clamp"), "loop_explicit": "loop" in shot,
             "blend": shot.get("blend"), "transition": shot.get("transition"),
             "fx": clone(shot.get("fx", {})), "layers": clone(shot.get("layers", [])),
             "special": clone(shot.get("special"))} for shot in timeline["shots"]]


def _global_sampling(timeline):
    return {key: clone(timeline.get(key, default)) for key, default in
            (("post", {}), ("overlays", []), ("specials", []))}


def _rational_rate(value):
    # Canonical upstream JSON stores rates as numbers. Recover a bounded
    # rational representation; a supplied clockmap remains the encoder authority.
    return str(Fraction(str(value)).limit_denominator(1_000_000))


def make_clockmap(timeline, sources):
    """Describe explicit canonical shot sampling; sources must explain every clip."""
    return {"schema": CLOCK_SCHEMA, "fps": _rational_rate(timeline["canvas"]["fps"]),
            "frame_count": timeline["canvas"]["frames"], "clips": clone(sources), "shots": _sampling(timeline),
            "global_sampling": _global_sampling(timeline),
            "sampling": "Upstream frame-midpoint sampling; frame-trace records actual source choices.",
            "temporal_effects": "May sample neighboring source frames when explicitly selected in the timeline."}


def _validate_clockmap(clockmap, timeline):
    require(isinstance(clockmap, dict) and clockmap.get("schema") == CLOCK_SCHEMA,
            "clockmap_required", "Supply an explicit OpenKatana clockmap")
    require(abs(float(Fraction(clockmap["fps"])) - timeline["canvas"]["fps"]) < 1e-7
            and clockmap["frame_count"] == timeline["canvas"]["frames"],
            "clockmap_output", "Clockmap differs from the output timeline")
    require(clockmap.get("shots") == _sampling(timeline), "clockmap_sampling", "Clockmap differs from shot sampling")
    require(clockmap.get("global_sampling") == _global_sampling(timeline), "clockmap_sampling",
            "Clockmap differs from overlays, specials or global effects")
    require(set(clockmap.get("clips", {})) == set(timeline["clips"]), "clockmap_clips", "Every clip needs a source binding")
    files = []
    for key, clip in timeline["clips"].items():
        entry = clockmap["clips"][key]
        require(entry.get("frame_count") == clip["n"] and abs(float(Fraction(entry["fps"])) - clip["fps"]) < 1e-7,
                "clockmap_clip", "Clip clock differs from its binding", key)
        require(type(entry.get("origin_frame")) is int and entry["origin_frame"] >= 0,
                "clockmap_origin", "A source frame origin is required", key)
        if entry.get("kind") == "source":
            file = _file(entry["path"])
            require(file["sha256"] == entry.get("sha256"), "clockmap_source", "Source bytes changed", key)
            from visual_fidelity.reference_cadence import video_clock
            actual_fps, actual_count = video_clock(Path(file["path"]))
            require(actual_fps == Fraction(entry["fps"])
                    and entry["origin_frame"] + clip["n"] <= actual_count,
                    "clockmap_source", "Source frame clock does not cover this clip; conform explicitly", key)
            files.append(file)
        else:
            require(entry.get("kind") == "authored_sequence" and isinstance(entry.get("provenance"), str)
                    and bool(entry["provenance"].strip()), "clockmap_source",
                    "A clip needs a hashed source or explicit authored-sequence provenance", key)
    return files


def _verify_source_pixels(project, timeline, clockmap):
    """A video hash alone cannot attest that its claimed PNG proxies came from it."""
    from PIL import Image
    checks = []
    resolve = _module("contracts").local_path
    for key, clip in timeline["clips"].items():
        binding = clockmap["clips"][key]
        if binding["kind"] == "authored_sequence":
            checks.append({"clip": key, "status": "declared_authored_sequence", "source_pixels_verified": False})
            continue
        start, count = binding["origin_frame"], clip["n"]
        with tempfile.TemporaryDirectory(prefix="openkatana-source-check-") as temporary:
            temporary = Path(temporary)
            _run(["ffmpeg", "-nostdin", "-v", "error", "-i", binding["path"], "-map", "0:v:0", "-an",
                  "-vf", f"select=between(n\\,{start}\\,{start+count-1}),setpts=PTS-STARTPTS",
                  "-fps_mode", "passthrough", "-start_number", "0", temporary / "%05d.png"], timeout_s=600)
            require(len(list(temporary.glob("*.png"))) == count, "source_binding_frames",
                    "Source decoding does not cover the declared PNG sequence", key)
            for index in range(count):
                proxy = resolve(project, str(Path(clip["frames_dir"]) / (clip.get("pattern", "%05d.png") % index)))
                with Image.open(temporary / f"{index:05d}.png") as expected, Image.open(proxy) as actual:
                    require(expected.size == actual.size == (clip["w"], clip["h"])
                            and expected.convert("RGBA").tobytes() == actual.convert("RGBA").tobytes(),
                            "source_binding_pixels", "PNG pixels differ from the declared source and origin", f"{key}/{index}")
        checks.append({"clip": key, "status": "verified", "source_pixels_verified": True,
                       "method": "FFmpeg exact frame decode and RGBA byte comparison", "frames_compared": count,
                       "source_sha256": binding["sha256"], "origin_frame": start})
    return checks


def _sample_bounds(timeline, clockmap):
    """Audit every base/blend sample, transition handle, panel, map and overlay.

    Temporal stacks use a conservative superset: all output frames for that shot.
    Their output-boundary clamp must be acknowledged separately in the clockmap.
    """
    fps, total = timeline["canvas"]["fps"], timeline["canvas"]["frames"]
    temporal_names = {"local_echo", "local_frame_blend", "local_posterize_time", "local_time_displacement"}
    repetitions, checked = {}, 0

    def wrapped(index, count, mode):
        if mode == "loop":
            return index % count
        if mode == "pingpong" and count > 1:
            value = index % (2 * (count - 1))
            return value if value < count else 2 * (count - 1) - value
        return min(count - 1, max(0, index))

    def observe(clip_id, index, mode, where, frame):
        nonlocal checked
        checked += 1
        count = timeline["clips"][clip_id]["n"]
        if not 0 <= index < count:
            require(mode in {"clamp", "loop", "pingpong"}, "source_sample_bounds",
                    "Source is exhausted; declare an intentional loop/clamp or supply source handles",
                    f"{where}: output {frame}, source {index}, available 0..{count-1}")
            key = where + ":" + mode
            entry = repetitions.setdefault(key, {"owner": where, "clip": clip_id, "mode": mode,
                                                  "out_of_range_samples": 0, "first_output_frame": frame,
                                                  "last_output_frame": frame})
            entry["out_of_range_samples"] += 1
            entry["last_output_frame"] = frame
        return wrapped(index, count, mode)

    def effects(shot):
        result = [(name, {} if value is True else value) for name, value in
                  {**timeline.get("post", {}), **shot.get("fx", {})}.items() if value is not False]
        result += [(layer["type"], layer) for layer in shot.get("layers", [])]
        return result

    def inspect(shot, frame, where, *, panel=False):
        if "special" in shot:
            for index, child in enumerate(shot["special"].get("panels", [])):
                inspect({**child, "f0": shot["f0"], "f1": shot["f1"]}, frame, f"{where}.panels[{index}]", panel=True)
            return
        clip_id = shot["clip"]
        clip = timeline["clips"][clip_id]
        elapsed = (frame + .5) / fps - shot["f0"] / fps
        duration = shot["f1"] / fps - shot["f0"] / fps
        speed0, speed1 = shot.get("speed", 1), shot.get("speed1", shot.get("speed", 1))
        speed = speed0 + (speed1 - speed0) * elapsed / duration
        start = shot["srcf"] / clip["fps"] + 1e-7 if shot.get("srcf") is not None else shot.get("src", 0)
        position = (start + speed0 * elapsed + (speed1 - speed0) * elapsed * elapsed / (2 * duration)) * clip["fps"]
        fx = dict(effects(shot))
        stutter = fx.get("stutter")
        if stutter is not None and stutter is not False:
            raw = math.floor(start * clip["fps"]) + ((frame - shot["f0"]) % stutter.get("n", 3)) * stutter.get("step", 1)
        else:
            raw = math.floor(position)
        chosen = observe(clip_id, raw, shot.get("loop"), where, frame)
        blending = 0 < abs(speed) < 1 and shot.get("blend") is not False and (abs(speed) >= .3 or shot.get("blend") is True)
        if stutter in (None, False) and blending:
            low = math.floor(position - .5)
            if not (speed > 0 and low < math.floor(start * clip["fps"])):
                observe(clip_id, low, shot.get("loop"), where + ".blend", frame)
                if position - .5 - low:
                    observe(clip_id, low + 1, shot.get("loop"), where + ".blend", frame)
        if panel:
            return
        trail = fx.get("trail")
        if isinstance(trail, dict):
            for distance in range(1, trail.get("n", 3) + 1):
                observe(clip_id, chosen - distance * trail.get("step", 2), shot.get("loop"), where + ".trail", frame)
        for name, options in effects(shot):
            if isinstance(options, dict) and name.startswith("local_") and "clip" in options:
                t = elapsed - options.get("at", 0)
                if t >= 0:
                    other = options["clip"]
                    raw = math.floor((options.get("src", 0) + options.get("speed", 1) * t) * timeline["clips"][other]["fps"] + 1e-6)
                    observe(other, raw, options.get("loop"), where + "." + name, frame)

    windows = [[shot["f0"], shot["f1"]] for shot in timeline["shots"]]
    transition_module = _module("transitions")
    for index, shot in enumerate(timeline["shots"]):
        if shot.get("transition"):
            low, high = transition_module.frame_window(shot["transition"], shot["f0"], fps)
            for owner in (index - 1, index):
                windows[owner][0] = max(0, min(windows[owner][0], low))
                windows[owner][1] = min(total, max(windows[owner][1], high))
    temporal_owners = []
    for index, shot in enumerate(timeline["shots"]):
        if any(name in temporal_names for name, _ in effects(shot)):
            boundary = clockmap.get("temporal_output_boundary", {})
            require(boundary.get("mode") == "clamp" and bool(str(boundary.get("reason", "")).strip()),
                    "clockmap_temporal_boundary", "Temporal effects need an explicit output-clamp acknowledgement and reason")
            windows[index] = [0, total]
            temporal_owners.append(index)
        for frame in range(*windows[index]):
            inspect(shot, frame, f"shots[{index}]")
    for index, special in enumerate(timeline.get("specials", [])):
        for frame in range(special["f0"], special["f1"]):
            inspect({"f0": special["f0"], "f1": special["f1"], "special": special}, frame, f"specials[{index}]")
    for index, overlay in enumerate(timeline.get("overlays", [])):
        if overlay["type"] != "clip":
            continue
        clip = timeline["clips"][overlay["clip"]]
        start = overlay["srcf"] / clip["fps"] + 1e-7 if overlay.get("srcf") is not None else overlay.get("src", 0)
        for frame in range(overlay["f0"], overlay["f1"]):
            elapsed = (frame - overlay["f0"] + .5) / fps
            if overlay.get("fps"):
                elapsed = (math.floor(elapsed * overlay["fps"]) + .5) / overlay["fps"]
            raw = math.floor((start + overlay.get("speed", 1) * elapsed) * clip["fps"])
            observe(overlay["clip"], raw, overlay.get("loop"), f"overlays[{index}]", frame)
    return {"status": "verified", "samples_checked": checked, "explicit_repetitions": list(repetitions.values()),
            "conservative_temporal_shots": temporal_owners,
            "scope": "All base and blend samples, transition handles, collage panels, source trails, maps and overlays; temporal stacks check every output frame."}


NODE_RENDERER = r"""
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm');
const request=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const C=require(request.canvas_module);
const root=fs.realpathSync(request.project),web=fs.realpathSync(request.web);
function local(url){
  if(!url.startsWith('/project/'))throw Error('Only project-local reads are allowed');
  const p=fs.realpathSync(path.resolve(root,decodeURIComponent(url.slice(9))));
  if(p!==root&&!p.startsWith(root+path.sep))throw Error('Project path escapes its root');
  return p;
}
globalThis.window=globalThis;
globalThis.Path2D=C.Path2D;globalThis.ImageData=C.ImageData;globalThis.DOMMatrix=C.DOMMatrix;
globalThis.fetch=async url=>{const p=local(String(url)),bytes=fs.readFileSync(p);
  return {ok:true,status:200,json:async()=>JSON.parse(bytes.toString('utf8')),blob:async()=>new Blob([bytes])};};
globalThis.createImageBitmap=async blob=>{const img=await C.loadImage(Buffer.from(await blob.arrayBuffer()));
  img.close=()=>{};return img;};
const output=C.createCanvas(2,2);
globalThis.document={addEventListener:(type,listener)=>{
  if(type!=='securitypolicyviolation')throw Error('DOM events are unavailable');
  // There is no browser CSP in this runtime. Project hooks are prohibited by
  // the Python adapter, and fetch above accepts only confined local files.
},createElement:type=>{if(type!=='canvas')throw Error('Unsupported DOM element: '+type);
  return C.createCanvas(2,2);},getElementById:id=>{if(id!=='output')throw Error('Unknown canvas');return output;},
  fonts:{add:()=>{},ready:Promise.resolve()}};
globalThis.FontFace=class{constructor(family,src,options){this.family=family;this.src=src;this.options=options;}
  async load(){const url=JSON.parse(this.src.slice(4,-1));
    if(!C.GlobalFonts.registerFromPath(local(url),this.family))throw Error('Font registration failed');
    return this;}};
const html=fs.readFileSync(path.join(web,'render.html'),'utf8');
for(const match of html.matchAll(/src="\/app\/([^"]+)"/g)){
  const script=path.resolve(web,match[1]);
  if(!script.startsWith(web+path.sep))throw Error('Script path escapes vendor root');
  vm.runInThisContext(fs.readFileSync(script,'utf8'),{filename:script});
}
(async()=>{
  await OpenKatana.boot(request.timeline);
  const trace=[];
  fs.mkdirSync(request.frames,{recursive:false});
  for(let f=0;f<request.timeline.canvas.frames;f++){
    const value=await OpenKatana.render(f);
    fs.writeFileSync(path.join(request.frames,String(f).padStart(5,'0')+'.png'),Buffer.from(value.png,'base64'));
    trace.push({frame:f,...value.sample,...(value.transition?{transition:value.transition}:{}),
                ...(value.face?{face:value.face}:{})});
  }
  fs.writeFileSync(request.trace,JSON.stringify(trace,null,2));
  process.stdout.write(JSON.stringify({frames:trace.length,node:process.version,
    canvas:require(path.join(request.canvas_module,'package.json')).version,
    canvas_module:request.canvas_module,runtime:'node-canvas'}));
})().catch(error=>{process.stderr.write(String(error.stack||error));process.exitCode=1;});
"""


def _input_manifest(timeline, project):
    paths = set()
    for clip in timeline["clips"].values():
        paths.update(str(Path(clip["frames_dir"]) / (clip.get("pattern", "%05d.png") % i)) for i in range(clip["n"]))
        if clip.get("mask_dir"):
            paths.update(str(Path(clip["mask_dir"]) / f"{i:05d}.png") for i in range(clip["n"]))
        if clip.get("faces"):
            paths.add(clip["faces"])
    paths.update(font["url"] for font in timeline.get("fonts", []))
    paths.update(timeline.get("assets", {}).get("stickers", []))
    paths.update(_module("audio").source_paths(timeline.get("audio")))
    resolve = _module("contracts").local_path
    return [_file(resolve(project, path)) for path in sorted(paths)]


def _artifact(output, render_dir, operation, *, clockmap, runtime, inputs, upstream=None, alpha="opaque",
              source_bindings=None, sampling_audit=None, trusted_code=False):
    from PIL import Image
    movie = render_dir / "video.mp4"
    media = _probe_media(movie)
    stream = next(s for s in media["streams"] if s["codec_type"] == "video")
    count, width, height = int(stream["nb_read_frames"]), int(stream["width"]), int(stream["height"])
    fps = str(Fraction(stream["r_frame_rate"]))
    require(count == clockmap["frame_count"] and Fraction(fps) == Fraction(clockmap["fps"]),
            "render_clock", "Encoded output differs from its explicit clockmap")
    sequence = []
    for index in range(count):
        path = render_dir / "frames" / f"{index:05d}.png"
        with Image.open(path) as frame:
            require(frame.size == (width, height), "frame_dimensions", "Rendered sequence dimensions changed")
            if alpha == "straight":
                require("A" in frame.getbands(), "alpha_missing", "Declared alpha sequence lacks an alpha channel")
        sequence.append({"index": index, **_file(path)})
    _run(["ffmpeg", "-nostdin", "-v", "error", "-i", movie, "-f", "null", "-"])
    _unchanged(inputs)
    report = {**_base(operation, trusted_code=trusted_code), "status": "rendered", "path": str(movie), "sha256": file_sha256(movie),
              "fps": fps, "frame_count": count, "width": width, "height": height, "alpha": alpha,
              "frames": sequence,
              "clock": "output", "clockmap": clone(clockmap), "runtime": runtime, "inputs": inputs,
              "sequence": {"directory": str(render_dir / "frames"), "pattern": "%05d.png",
                           "alpha_mode": alpha, "frames": sequence},
              "video_alpha_mode": "opaque", "upstream_receipt": upstream,
              "source_bindings": source_bindings, "sampling_audit": sampling_audit,
              "technical_checks": {"decode": "pass", "clock": "pass", "input_hashes": "pass", "frame_hashes": "pass"},
              "limits": ["Technical checks are not aesthetic or listening approval.",
                         "Node Canvas output is not asserted to match Chromium pixels.",
                         "Authored 3D does not imply camera solve or integration into existing footage."]}
    return _save_report(output, report)


def render_timeline(project_dir, timeline, output_dir, *, clockmap=None, renderer="node-canvas", timeout_s=600):
    """Execute a canonical timeline. Explicit renderer; never switch on failure."""
    project = Path(project_dir).resolve()
    require(project.is_dir(), "project_missing", "Project directory is missing")
    raw = json.loads(Path(timeline).read_text()) if isinstance(timeline, (str, Path)) else clone(timeline)
    if "timeline" in raw:
        require(clockmap is None, "clockmap_duplicate", "Pass the clockmap in one place")
        clockmap, raw = raw.get("clockmap"), raw["timeline"]
    require(not raw.get("hooks"), "trusted_code", "Timeline hooks are not enabled in this adapter")
    require(not raw.get("audio", {}).get("cues"), "audio_cues", "Supply explicit indexed audio tracks instead of procedural cues")
    canonical = _module("contracts").validate(raw, project)
    sources = _validate_clockmap(clockmap, canonical)
    sampling_audit = _sample_bounds(canonical, clockmap)
    inputs = sources + _input_manifest(canonical, project)
    source_bindings = _verify_source_pixels(project, canonical, clockmap)
    require(renderer in {"node-canvas", "chromium"}, "renderer", "Choose node-canvas or chromium explicitly")
    readiness = _node_probe() if renderer == "node-canvas" else _browser_probe()
    require(readiness["status"] == "ready", "openkatana_runtime", readiness.get("reason", "Requested renderer is unavailable"))
    output = _output(output_dir)
    _json(output / "timeline.json", canonical)
    _json(output / "clockmap.json", clockmap)
    render_dir = output / "render"
    runtime_module = _module("render")
    if renderer == "node-canvas":
        render_dir.mkdir()
        request = {"project": str(project), "web": str(VENDOR / "openkatana" / "web"),
                   "canvas_module": str(_canvas_package()),
                   "timeline": canonical, "frames": str(render_dir / "frames"),
                   "trace": str(render_dir / "frame-trace.json")}
        _json(output / "node-request.json", request)
        runtime = json.loads(_run([_node(), "-e", NODE_RENDERER, output / "node-request.json"], timeout_s=timeout_s))
        audio = canonical.get("audio")
        mixed, soundtrack = None, None
        audio_report = None
        if audio and audio.get("mode") == "mix":
            mixed = render_dir / "audio.wav"
            audio_report = _module("audio").mix(audio, project, mixed,
                                                 canonical["canvas"]["frames"] / canonical["canvas"]["fps"])
        elif audio and audio.get("mode") == "copy":
            soundtrack = _module("contracts").local_path(project, audio["src"])
        runtime_module.encode(render_dir / "frames", {**canonical["canvas"], "fps": clockmap["fps"]}, render_dir / "video.mp4",
                              soundtrack=soundtrack, mixed=mixed)
        upstream = {"engine": "unmodified pinned OpenKatana Canvas JavaScript",
                    "audio_mix": audio_report, "visual_review": "not_performed"}
    else:
        with tempfile.NamedTemporaryFile(prefix="editor-ultra-", suffix=".json", dir=project, delete=False) as handle:
            path = Path(handle.name)
        try:
            _json(path, canonical)
            upstream = runtime_module.render(path, render_dir)
        finally:
            path.unlink(missing_ok=True)
        runtime = {"runtime": "chromium", "upstream_native_renderer": True}
    _json(render_dir / "input-manifest.json", inputs)
    return _artifact(output, render_dir, "render_timeline", clockmap=clockmap, runtime=runtime, inputs=inputs,
                     upstream=upstream, source_bindings=source_bindings, sampling_audit=sampling_audit)


def preview_effect(source, output_dir, *, effect, params=None, start_frame=0, frame_count=None,
                   start_s=None, duration_s=None, renderer="node-canvas", spatial_mode="screen",
                   include_audio=False, timeout_s=300):
    """Render one real effect on an exact CFR source interval; retain all PNGs."""
    from visual_fidelity.reference_cadence import video_clock
    require(spatial_mode == "screen", "spatial_mode", "An effect preview is screen composition, not planar/3D anchoring")
    original = _file(source)
    source = Path(original["path"])
    fps, available = video_clock(source)
    if start_s is not None:
        require(start_frame == 0, "preview_clock", "Specify start_s or start_frame")
        position = Fraction(str(start_s)) * fps
        require(abs(position - round(position)) < Fraction(1, 10**7),
                "preview_clock", "start_s must align exactly to a source frame")
        start_frame = round(position)
    if duration_s is not None:
        require(frame_count is None, "preview_clock", "Specify duration_s or frame_count")
        length = Fraction(str(duration_s)) * fps
        require(abs(length - round(length)) < Fraction(1, 10**7),
                "preview_clock", "duration_s must span whole source frames")
        frame_count = round(length)
    count = available - start_frame if frame_count is None else frame_count
    require(type(start_frame) is int and type(count) is int and 0 <= start_frame < available
            and 1 <= count <= 3600 and start_frame + count <= available,
            "preview_interval", "Preview needs an existing exact source frame interval of at most 3600 frames")
    metadata = _probe_media(source)
    video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
    require(video.get("color_transfer") not in {"smpte2084", "arib-std-b67"}
            and not any(abs(float(item.get("rotation", 0))) % 360 for item in video.get("side_data_list", []))
            and video.get("sample_aspect_ratio", "1:1") in {"1:1", "N/A"},
            "source_conform", "HDR, rotated or nonsquare-pixel media require explicit conformance")
    output = _output(output_dir)
    project = output / "project"
    project.mkdir()
    frames = project / "source"
    frames.mkdir()
    _run(["ffmpeg", "-nostdin", "-v", "error", "-i", source, "-map", "0:v:0", "-an",
          "-vf", f"select=between(n\\,{start_frame}\\,{start_frame+count-1}),setpts=PTS-STARTPTS",
          "-fps_mode", "passthrough", "-start_number", "0", frames / "%05d.png"], timeout_s=timeout_s)
    require(len(list(frames.glob("*.png"))) == count, "source_frames", "Extraction did not preserve selected source frames")
    timeline = {"canvas": {"w": video["width"], "h": video["height"], "fps": float(fps), "frames": count},
                "clips": {"source": {"frames_dir": "source", "n": count, "fps": float(fps),
                                      "w": video["width"], "h": video["height"], "pattern": "%05d.png"}},
                "shots": [{"f0": 0, "f1": count, "clip": "source", "speed": 1, "fx": {effect: params or {}}}]}
    if include_audio and any(s["codec_type"] == "audio" for s in metadata["streams"]):
        _run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(float(start_frame / fps)), "-i", source,
              "-t", str(float(count / fps)), "-vn", "-c:a", "pcm_s24le", project / "source-audio.wav"])
        timeline["audio"] = {"mode": "mix", "tracks": [{"src": "source-audio.wav", "duration": float(count / fps)}]}
    clockmap = make_clockmap(timeline, {"source": {"kind": "source", **original, "fps": str(fps),
                                                    "frame_count": count, "origin_frame": start_frame}})
    clockmap["fps"] = str(fps)
    rendered = render_timeline(project, timeline, output / "execution", clockmap=clockmap,
                               renderer=renderer, timeout_s=timeout_s)
    _unchanged([original])
    report = {**rendered, **_base("preview_effect"), "effect": effect, "params": clone(params or {}),
              "source": original, "audio_included": bool(timeline.get("audio")), "spatial_mode": "screen"}
    report.pop("receipt", None)
    return _save_report(output, report)


def render_scene3d(project_dir, scene, output_dir, *, trusted_script=False):
    """Use upstream WebGL only; no silent replacement with a flat scene."""
    ready = _browser_probe()
    require(ready["webgl"], "webgl_unavailable", ready.get("reason", "WebGL is unavailable"))
    project = Path(project_dir).resolve()
    raw = json.loads(Path(scene).read_text()) if isinstance(scene, (str, Path)) else clone(scene)
    require(not raw.get("authoring") or trusted_script is True, "trusted_code", "Authored JS needs explicit trusted_script=True")
    module = _module("scene3d")
    canonical = module.validate(raw, project)
    inputs = [_file(project / rel) for rel in module.input_manifest(canonical, project)]
    output = _output(output_dir)
    _json(output / "scene.json", canonical)
    with tempfile.NamedTemporaryFile(prefix="editor-ultra-scene-", suffix=".json", dir=project, delete=False) as handle:
        path = Path(handle.name)
    try:
        _json(path, canonical)
        receipt = module.render_scene(path, output / "render", trusted_script=trusted_script)
    finally:
        path.unlink(missing_ok=True)
    clockmap = {"schema": CLOCK_SCHEMA, "fps": str(canonical["canvas"]["fps"]),
                "frame_count": canonical["canvas"]["frames"], "clock": "authored_scene",
                "camera_solve_on_footage": False}
    return _artifact(output, output / "render", "render_scene3d", clockmap=clockmap,
                     runtime={"runtime": "chromium-webgl"}, inputs=inputs, upstream=receipt,
                     alpha="straight" if canonical["canvas"].get("transparent") else "opaque",
                     trusted_code=bool(canonical.get("authoring")))


def render_blender(source, output_dir, *, engine="BLENDER_EEVEE", start=None, end=None, trusted_script=False):
    """A distinct installed Blender route, with source/dependency hashes and PNGs."""
    original = _file(source)
    require(Path(source).suffix.lower() != ".py" or trusted_script is True, "trusted_code",
            "Blender scripts require explicit trusted_script=True")
    readiness = _blender_probe()
    require(readiness["status"] == "ready", "blender_unavailable", readiness.get("reason", "Blender is unavailable"))
    output = _output(output_dir)
    receipt = _module("blender_bridge").render_blender(source, output / "render", engine, start, end, trusted_script)
    dependencies = []
    for path, before in receipt.get("dependencies", {}).items():
        current = _file(path)
        require(current["sha256"] == before, "source_changed", "Blender dependency differs from its pre-render hash", path)
        dependencies.append(current)
    inputs = [original] + dependencies
    clockmap = {"schema": CLOCK_SCHEMA, "clock": "authored_scene", "fps": _rational_rate(receipt["fps"]),
                "frame_count": receipt["frames"], "source_frame_start": receipt["source_frame_start"],
                "source_frame_end": receipt["source_frame_end"], "camera_solve_on_footage": False}
    return _artifact(output, output / "render", "render_blender", clockmap=clockmap,
                     runtime={"runtime": "blender", "version": receipt.get("blender"), "engine": engine},
                     inputs=inputs, upstream=receipt, alpha="straight", trusted_code=Path(source).suffix.lower() == ".py")
