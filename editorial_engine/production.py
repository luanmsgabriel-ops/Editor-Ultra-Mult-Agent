"""Explicit production requests, typed artifacts and resumable Python adapters.

JSON selects an adapter already registered by the host; it never supplies an
import, shell command or executable project. Manual requests are useful exports,
not claims that this process called an image, video or voice provider. Technical
verification remains separate from perceptual review and user approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import marshal
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable

from PIL import Image, ImageFont

from .contracts import (ValidationError, clone, digest, integer, mapping, nonempty,
                        number, require, sequence, sha256)
from .workflows import WorkflowLedger, ExecutionUnknown, artifact_evidence
from .video_generation_policy import execution_policy


REQUEST_SCHEMA = "production-request/1"
RESULT_SCHEMA = "production-result/1"
EXECUTION_SCHEMA = "production-execution/1"
OUTPUT_KINDS = {"image", "video", "audio", "motion_layer", "transcript", "pose",
                "mattes", "planar_tracking"}
INPUT_KINDS = OUTPUT_KINDS | {"json", "file", "font"}
PREPARATION_KINDS = {"transcript", "pose", "mattes", "planar_tracking"}
MANUAL_OPERATIONS = {"chat_image", "external_video", "voice", "music", "sfx",
                     "transcript", "pose", "mattes", "planar_tracking", "manual_asset", "procedural"}
# These authored operations describe local rendering/processing, not temporal
# synthesis through a video model. Other video callbacks need a host-registered
# execution_kind; request JSON cannot grant that capability.
LOCAL_VIDEO_OPERATIONS = {"motion_recipe", "planar_portal", "template", "procedural"}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def _id(value, label):
    require(isinstance(value, str) and bool(_ID.fullmatch(value)), "production_id",
            "Use an identifier without paths or whitespace", label)
    return value


def _fields(value, required, optional=(), label="object"):
    mapping(value, label)
    require(set(required) <= set(value) <= set(required) | set(optional),
            "production_fields", "Missing or unknown fields", label)
    return value


def _seal(value, field):
    value = clone(value)
    value[field] = digest({key: item for key, item in value.items() if key != field})
    return value


def _sealed(value, field):
    sha256(value.get(field), field)
    require(value[field] == digest({key: item for key, item in value.items() if key != field}),
            "production_digest", "The sealed record changed", field)


def _absolute(value, label):
    path = Path(nonempty(value, label))
    require(path.is_absolute(), "production_path", "Use an absolute local path", label)
    return path.resolve()


def _rate(value):
    require(isinstance(value, str), "production_clock", "FPS must be a rational string")
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValidationError("production_clock", "Invalid rational FPS") from error
    require(0 < rate <= 240, "production_clock", "FPS must be positive and at most 240")
    return rate


def _write_once(path, value):
    """Resume identical exports; never overwrite another request or result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(json.loads(path.read_text(encoding="utf-8")) == value,
                "production_output_exists", "Existing record differs; use a new revision/output directory", str(path))
        return
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _file(path, expected=None):
    try:
        return artifact_evidence(path, expected)
    except (OSError, ValueError) as error:
        raise ValidationError("production_file", str(error), str(path)) from error


def production_request(request_id, operation, *, prompt, output_kind, inputs=None,
                       parameters=None, adapter_id=None, source_binding=None,
                       context=None, unresolved=None, constraints=None, revision=1):
    """Author one immutable need. Input paths/hashes must be supplied explicitly.

    ``context`` can bind a project revision, need ID or plan hash. Missing authoring
    decisions belong in ``unresolved``; choosing a provider is not required to
    export a manual request. This function does not probe files or run a model.
    """
    value = {"schema": REQUEST_SCHEMA, "id": request_id, "revision": revision,
             "operation": operation, "prompt": prompt, "output_kind": output_kind,
             "adapter_id": adapter_id, "inputs": [] if inputs is None else inputs,
             "parameters": {} if parameters is None else parameters,
             "source_binding": source_binding, "context": {} if context is None else context,
             "unresolved": [] if unresolved is None else unresolved,
             "constraints": {} if constraints is None else constraints}
    return validate_request(_seal(value, "request_sha256"))


def validate_request(request, *, verify_files=False):
    data = clone(mapping(request, "request"))
    _fields(data, {"schema", "id", "revision", "operation", "prompt", "output_kind",
                  "adapter_id", "inputs", "parameters", "source_binding", "context",
                  "unresolved", "constraints", "request_sha256"}, label="request")
    require(data["schema"] == REQUEST_SCHEMA, "production_schema", "Expected production-request/1")
    _sealed(data, "request_sha256")
    _id(data["id"], "request.id")
    _id(data["operation"], "operation")
    integer(data["revision"], "revision", minimum=1)
    nonempty(data["prompt"], "prompt")
    require(isinstance(data["output_kind"], str) and data["output_kind"] in OUTPUT_KINDS,
            "production_kind", "Unsupported output kind")
    if data["adapter_id"] is not None:
        _id(data["adapter_id"], "adapter_id")
    mapping(data["parameters"], "parameters")
    mapping(data["context"], "context")
    for item in sequence(data["unresolved"], "unresolved"):
        nonempty(item, "unresolved entry")
    seen = set()
    for item in sequence(data["inputs"], "inputs"):
        _fields(item, {"id", "kind", "path", "sha256"}, {"role"}, "input")
        _id(item["id"], "input.id")
        require(item["id"] not in seen, "production_input", "Duplicate input id")
        seen.add(item["id"])
        require(isinstance(item["kind"], str) and item["kind"] in INPUT_KINDS,
                "production_kind", "Unsupported input kind")
        _absolute(item["path"], "input.path")
        sha256(item["sha256"], "input.sha256")
        if "role" in item:
            nonempty(item["role"], "input.role")
        if verify_files:
            _file(item["path"], item["sha256"])
            if item["kind"] in {"image", "video", "audio"}:
                _media(item["path"], item["kind"], decode=False)
            elif item["kind"] == "font":
                try:
                    ImageFont.truetype(item["path"], 16)
                except (OSError, ValueError) as error:
                    raise ValidationError("production_font", "Font file cannot be loaded") from error
            elif item["kind"] == "json":
                clone(json.loads(Path(item["path"]).read_text(encoding="utf-8")))
            elif item["kind"] == "motion_layer":
                from .motion_assets import load_layer
                load_layer(item["path"], verify_files=True)
    constraints = _fields(data["constraints"], set(), {"width", "height", "fps", "frame_count",
        "duration_s", "duration_tolerance_s", "alpha", "require_transparency", "full_coverage"}, "constraints")
    for name in ("width", "height", "frame_count"):
        if name in constraints:
            integer(constraints[name], "constraints." + name, minimum=1)
    if "fps" in constraints:
        _rate(constraints["fps"])
    for name in ("duration_s", "duration_tolerance_s"):
        if name in constraints:
            number(constraints[name], "constraints." + name, minimum=0)
    if "duration_s" in constraints:
        require(constraints["duration_s"] > 0, "production_duration", "Duration must be positive")
    if "alpha" in constraints:
        require(isinstance(constraints["alpha"], str) and constraints["alpha"] in {"straight", "opaque"},
                "production_alpha", "Unknown alpha contract")
    for name in ("require_transparency", "full_coverage"):
        if name in constraints:
            require(type(constraints[name]) is bool, "production_type", name + " must be boolean")
    binding = data["source_binding"]
    if binding is not None:
        _fields(binding, {"input_id", "source_sha256", "fps", "frame_count"},
                {"start_frame", "end_frame"}, "source_binding")
        source = _input(data, binding["input_id"])
        require(source["kind"] == "video" and source["sha256"] == binding["source_sha256"],
                "production_source", "Source binding must identify a declared video input")
        _rate(binding["fps"])
        count = integer(binding["frame_count"], "source_binding.frame_count", minimum=1)
        first = integer(binding.get("start_frame", 0), "source_binding.start_frame")
        last = integer(binding.get("end_frame", count), "source_binding.end_frame", minimum=1)
        require(first < last <= count, "production_source", "Invalid source-bound interval")
        if verify_files:
            from visual_fidelity.reference_cadence import video_clock
            rate, measured = video_clock(Path(source["path"]))
            require(rate == _rate(binding["fps"]) and measured == count,
                    "production_source", "Declared binding differs from the real source clock")
    require(data["output_kind"] not in PREPARATION_KINDS or binding is not None,
            "production_source", "Preparation results require the current source binding")
    if data["operation"] == "template":
        require(data["output_kind"] in {"video", "motion_layer"}, "production_kind",
                "Template production needs an actual video or motion layer")
    return data


def _input(request, identifier):
    value = next((item for item in request["inputs"] if item["id"] == identifier), None)
    require(value is not None, "production_input", "Unknown input id", str(identifier))
    return value


@dataclass(frozen=True)
class Adapter:
    id: str
    executor: Callable | None
    operations: tuple[str, ...]
    output_kinds: tuple[str, ...]
    version: str = "1"
    simulated: bool = False
    execution_kind: str | None = None

    def descriptor(self):
        code = getattr(self.executor, "__code__", None)
        if code is None and self.executor is not None:
            code = getattr(getattr(self.executor, "__call__", None), "__code__", None)
        value = {"id": self.id, "version": self.version, "operations": list(self.operations),
                 "output_kinds": list(self.output_kinds), "simulated": self.simulated,
                 "callback_code_sha256": hashlib.sha256(marshal.dumps(code)).hexdigest() if code else None}
        # Preserve identities of existing non-video ledger jobs when the host
        # has not added a new execution declaration.
        if self.execution_kind is not None:
            value["execution_kind"] = self.execution_kind
        return value


class AdapterRegistry:
    """Host-owned callables; data cannot import or register another callable."""

    def __init__(self):
        self._adapters = {}

    def register(self, adapter_id, executor, *, operations, output_kinds,
                 version="1", simulated=False, execution_kind=None):
        _id(adapter_id, "adapter_id")
        require(callable(executor), "production_adapter", "Register a Python callable")
        nonempty(version, "adapter.version")
        require(type(simulated) is bool, "production_adapter", "simulated must be boolean")
        require(execution_kind is None or execution_kind == "local_processing", "production_adapter",
                "A host adapter may explicitly declare local_processing; video synthesis is prompt export only")
        require(adapter_id not in self._adapters, "production_adapter", "Adapter id is already registered")
        require(isinstance(operations, (list, tuple)) and operations and isinstance(output_kinds, (list, tuple))
                and output_kinds and all(isinstance(kind, str) for kind in output_kinds),
                "production_adapter", "Declare lists of operations and output kinds")
        for name in operations:
            _id(name, "adapter.operation")
        require(set(output_kinds) <= OUTPUT_KINDS, "production_adapter", "Unknown adapter output kind")
        adapter = Adapter(adapter_id, executor, tuple(operations), tuple(output_kinds), version, simulated, execution_kind)
        self._adapters[adapter_id] = adapter
        return adapter

    def get(self, adapter_id):
        return self._adapters.get(adapter_id)

    def describe(self):
        return [self._adapters[key].descriptor() for key in sorted(self._adapters)]


def _adapter(request, executor, registry):
    adapter = registry.get(request["adapter_id"]) if registry and request["adapter_id"] else None
    if executor is not None:
        require(adapter is None or adapter.executor is executor, "production_adapter",
                "Do not override a registered adapter with another callable")
        if adapter is None:
            require(callable(executor), "production_adapter", "Executor must be a Python callable")
            adapter = Adapter(request["adapter_id"] or "explicit-python", executor,
                              (request["operation"],), (request["output_kind"],))
    if adapter is not None:
        require(request["operation"] in adapter.operations and request["output_kind"] in adapter.output_kinds,
                "production_adapter", "Registered adapter is incompatible with the request")
    return adapter


def _run(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValidationError("production_media", "Media verification unavailable or timed out") from error
    require(result.returncode == 0, "production_media", "Media could not be verified: " + result.stderr[-1600:])
    return result.stdout


def _media(path, kind, *, decode=True):
    if kind == "image":
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                image.load()
                alpha = (image.convert("RGBA").getchannel("A").getextrema()
                         if "A" in image.getbands() or "transparency" in image.info else None)
                return {"width": image.width, "height": image.height, "format": image.format,
                        "alpha": "straight" if alpha is not None else "opaque",
                        "alpha_extrema": list(alpha) if alpha is not None else None,
                        "check": "image_decoded"}
        except (OSError, ValueError) as error:
            raise ValidationError("production_media", "Image cannot be decoded") from error
    require(shutil.which("ffprobe"), "production_media", "FFprobe is required for media verification")
    args = ["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe"]
    if decode:
        args.append("-count_frames")
    payload = json.loads(_run([*args, "-show_streams", "-show_format", "-of", "json", str(path)]))
    if kind == "video":
        formats = set(payload.get("format", {}).get("format_name", "").split(","))
        require(not formats & {"image2", "image2pipe", "png_pipe", "jpeg_pipe", "webp_pipe", "hls", "dash", "concat"},
                "production_media", "Supply self-contained temporal video, not a still or playlist")
    stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == kind
                   and (kind != "video" or not item.get("disposition", {}).get("attached_pic"))), None)
    require(stream is not None, "production_media", "Artifact does not contain the requested media stream")
    duration = stream.get("duration") or payload.get("format", {}).get("duration")
    require(duration not in (None, "N/A"), "production_media", "Media duration is unknown")
    duration = number(float(duration), "media.duration_s", minimum=0)
    require(duration > 0, "production_media", "Media duration is empty")
    if decode:
        require(shutil.which("ffmpeg"), "production_media", "FFmpeg is required to decode the result")
        _run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-protocol_whitelist", "file,pipe",
              "-i", str(path), "-map", "0:" + str(stream["index"]), "-f", "null", "-"])
    result = {"duration_s": duration, "codec": stream.get("codec_name"),
              "check": "stream_and_decode" if decode else "stream_probe",
              "audio_present": any(item.get("codec_type") == "audio" for item in payload.get("streams", []))}
    if kind == "video":
        result.update(width=integer(stream.get("width"), "media.width", minimum=1),
                      height=integer(stream.get("height"), "media.height", minimum=1),
                      fps=str(_rate(stream.get("avg_frame_rate") if stream.get("avg_frame_rate") not in (None, "0/0")
                                    else stream.get("r_frame_rate"))),
                      frame_count=int(stream.get("nb_read_frames") or stream.get("nb_frames") or 0),
                      alpha=("opaque" if stream.get("pix_fmt") in {
                          "yuv420p", "yuv422p", "yuv444p", "yuv420p10le", "yuv422p10le", "yuv444p10le",
                          "yuvj420p", "yuvj422p", "yuvj444p", "rgb24", "bgr24", "nv12", "gray"}
                          else "not_certified"))
        require(not decode or result["frame_count"] > 0, "production_media", "No decoded video frames")
    else:
        result.update(sample_rate=int(stream["sample_rate"]), channels=int(stream["channels"]))
    return result


def _constraints(actual, request):
    constraints = request["constraints"]
    for name in ("width", "height", "frame_count", "alpha"):
        if name in constraints:
            require(actual.get(name) == constraints[name], "production_contract",
                    "Artifact differs from requested " + name)
    if "fps" in constraints:
        require(actual.get("fps") is not None and _rate(actual["fps"]) == _rate(constraints["fps"]),
                "production_contract", "Artifact differs from requested FPS")
    if "duration_s" in constraints:
        require(actual.get("duration_s") is not None and
                abs(actual["duration_s"] - constraints["duration_s"]) <= constraints.get("duration_tolerance_s", 1e-6),
                "production_contract", "Artifact differs from requested duration; no trim or retime was applied")
    if constraints.get("require_transparency"):
        extrema = actual.get("alpha_extrema")
        require(extrema is not None and extrema[0] < 255 and extrema[1] > 0,
                "production_alpha", "Real visible transparent pixels are required")
    if constraints.get("full_coverage"):
        require(actual.get("full_coverage") is True, "production_coverage", "Result lacks full source coverage")


def _prepare_artifact(path, kind, request):
    raw = clone(json.loads(Path(path).read_text(encoding="utf-8")))
    binding = request["source_binding"]
    require(raw.get("source_sha256") == binding["source_sha256"] and raw.get("clock", "source") == "source",
            "production_source", "Preparation artifact refers to another source or clock")
    count, rate = binding["frame_count"], _rate(binding["fps"])
    files = []
    actual = {"check": "source_bound_data", "fps": str(rate), "frame_count": count,
              "duration_s": float(count / rate), "full_coverage": True}
    if kind == "transcript":
        previous = 0
        segments = sequence(raw.get("segments"), "segments")
        for segment in segments:
            mapping(segment, "segment")
            start = number(segment.get("start"), "segment.start", minimum=0)
            end = number(segment.get("end"), "segment.end", maximum=float(count / rate))
            require(previous <= start < end, "production_transcript", "Segments must be ordered and nonoverlapping")
            nonempty(segment.get("text"), "segment.text")
            previous = end
        actual.update(segment_count=len(segments), audio_listened=False, full_coverage=False,
                      coverage_note="Timestamps are source-bound; completeness of speech recognition was not assessed")
        return actual, files
    require(Fraction(str(raw.get("fps"))) == rate, "production_source", "Preparation FPS differs from source")
    if kind == "pose":
        frames = mapping(raw.get("frames"), "pose.frames")
        require(set(frames) == {str(index) for index in range(count)}, "production_coverage",
                "Pose must represent every source frame, including empty detections")
        for people in frames.values():
            for person in sequence(people, "pose frame"):
                mapping(person, "pose person")
        actual["measurement_semantics"] = "producer_attested; detection accuracy not assessed"
    elif kind == "planar_tracking":
        from .contracts import provenance
        from visual_fidelity.video_anchor import quad
        require(raw.get("frame_count") == count, "production_source", "Track frame count differs from source")
        provenance(raw.get("provenance"), "tracking.provenance")
        quads = mapping(raw.get("quads"), "quads")
        for index, points in quads.items():
            require(index.isdigit() and str(int(index)) == index and 0 <= int(index) < count,
                    "production_tracking", "Track index is outside the source")
            quad(points)
        first, last = binding.get("start_frame", 0), binding.get("end_frame", count)
        actual.update(observed_frames=sorted(map(int, quads)),
                      full_coverage=all(str(i) in quads for i in range(first, last)))
    elif kind == "mattes":
        require(raw.get("frames") == count, "production_source", "Matte count differs from source")
        resolution = sequence(raw.get("resolution"), "matte.resolution")
        require(len(resolution) == 2, "production_media", "Matte raster is required")
        for value in resolution:
            integer(value, "matte raster", minimum=1)
        source = _media(_input(request, binding["input_id"])["path"], "video", decode=False)
        require(abs(resolution[0] / resolution[1] - source["width"] / source["height"]) <= 1 / min(resolution),
                "production_media", "Mask aspect ratio differs from the current source")
        for index in range(count):
            frame = Path(path).parent / f"{index:06d}.png"
            evidence = _file(frame)
            with Image.open(frame) as image:
                require(image.format == "PNG" and image.mode in {"L", "I", "I;16"} and
                        image.size == tuple(resolution), "production_media", "Mask must be a grayscale PNG at its declared raster")
                image.load()
            files.append(evidence)
        actual.update(width=resolution[0], height=resolution[1])
    return actual, files


def _inspect_artifact(path, kind, request):
    evidence = _file(path)
    files = [evidence]
    if kind in {"image", "video", "audio"}:
        actual = _media(evidence["path"], kind)
    elif kind == "motion_layer":
        from .motion_assets import load_layer
        layer = load_layer(evidence["path"], verify_files=True)
        actual = {key: layer[key] for key in ("width", "height", "fps", "frame_count", "alpha")}
        actual.update(check="rgba_sequence_decoded", duration_s=float(layer["frame_count"] / _rate(layer["fps"])))
        extrema = [255, 0]
        for frame in layer["frames"]:
            files.append(_file(frame["path"], frame["sha256"]))
            with Image.open(frame["path"]) as image:
                image.load()
                low, high = image.getchannel("A").getextrema()
                extrema = [min(extrema[0], low), max(extrema[1], high)]
            if "glyph_ids_path" in frame:
                files.append(_file(frame["glyph_ids_path"], frame["glyph_ids_sha256"]))
        actual["alpha_extrema"] = extrema
        if request["source_binding"] is not None:
            expected = request["source_binding"]
            observed = layer.get("source_binding") or {}
            require(observed.get("source_sha256") == expected["source_sha256"] and
                    observed.get("frame_count") == expected["frame_count"] and
                    observed.get("start_frame") == expected.get("start_frame", 0) and
                    _rate(observed.get("fps")) == _rate(expected["fps"]),
                    "production_source", "Motion layer does not retain its requested source binding")
    else:
        actual, others = _prepare_artifact(evidence["path"], kind, request)
        files.extend(others)
    _constraints(actual, request)
    _file(evidence["path"], evidence["sha256"])
    return evidence, actual, sorted(files, key=lambda item: item["path"])


def _provenance(value):
    value = clone(mapping(value, "provenance"))
    nonempty(value.get("actor"), "provenance.actor")
    nonempty(value.get("method"), "provenance.method")
    require(type(value.get("simulated")) is bool, "production_provenance",
            "Explicitly declare whether the provider/result is simulated")
    if "producer_receipt" in value:
        evidence = _fields(value["producer_receipt"], {"path", "sha256"}, {"size"}, "producer_receipt")
        _absolute(evidence["path"], "producer_receipt.path")
        sha256(evidence["sha256"], "producer_receipt.sha256")
    return value


def _template_spec(request):
    from .templates import validate_library
    params = request["parameters"]
    library_input = _input(request, params.get("library_input", "library"))
    require(library_input["kind"] == "json", "production_template", "Template library must be a declared JSON input")
    _file(library_input["path"], library_input["sha256"])
    root = _absolute(params.get("root", str(Path(library_input["path"]).parent)), "template.root")
    library = validate_library(json.loads(Path(library_input["path"]).read_text(encoding="utf-8")), root=root, verify_files=True)
    template = next((item for item in library["templates"] if item["id"] == params.get("template_id")), None)
    require(template is not None and template["state"]["adaptation"] != "reference_only", "production_template",
            "Select a reusable authoring template")
    supplied = mapping(params.get("params", {}), "template.params")
    inputs = {}
    for slot, input_id in mapping(params.get("inputs", {}), "template.inputs").items():
        source = _input(request, input_id)
        require(slot in template["inputs"] and source["kind"] == template["inputs"][slot]["kind"],
                "production_template", "Template input slot/media kind differs")
        inputs[slot] = {key: source[key] for key in ("path", "sha256")}
    package = next(item for item in library["packages"] if item["id"] == template["package_id"])
    preview_paths = {preview["path"] for item in library["templates"] if item["package_id"] == package["id"]
                     for preview in item["previews"]}
    previews = {item["sha256"] for item in package["files"] if item["path"] in preview_paths}
    return library, root, template, supplied, inputs, previews


def _verify_instance(request, descriptor):
    from visual_fidelity.reference_bundle import inventory
    _fields(descriptor, {"path", "sha256"}, {"size"}, "template_instance")
    evidence = _file(descriptor["path"], descriptor["sha256"])
    value = clone(json.loads(Path(evidence["path"]).read_text(encoding="utf-8")))
    require(value.get("schema") == "motion-template-instance/1", "production_template", "Expected template instance receipt")
    _sealed(value, "receipt_sha256")
    library, _, template, supplied, inputs, previews = _template_spec(request)
    expected = {name: supplied[name] if name in supplied else spec["default"]
                for name, spec in template["parameters"].items() if name in supplied or "default" in spec}
    require(value.get("library_sha256") == digest(library) and value.get("template_sha256") == digest(template)
            and value.get("template_id") == template["id"] and value.get("parameters") == expected
            and value.get("inputs") == inputs and value.get("entrypoint") == "project/" + template["entrypoint"],
            "production_template", "Instance belongs to another library, template, parameters or inputs")
    base = Path(evidence["path"]).parent
    require(Path(value.get("receipt_path", "")).resolve() == Path(evidence["path"]), "production_template", "Instance receipt moved")
    actual = sorted(inventory(base / "project", excludes=()), key=lambda item: item["path"])
    expected_files = sorted([{key: item[key] for key in ("path", "sha256", "size")} for item in value["files"]],
                            key=lambda item: item["path"])
    require(actual == expected_files, "production_template", "Instantiated project files changed")
    return evidence, value, previews


def _instantiate(request, root):
    from .templates import instantiate_template
    destination = root / "instance"
    receipt_path = destination / "instance.json"
    if not receipt_path.exists():
        library, base, template, params, inputs, _ = _template_spec(request)
        instantiate_template(library, template["id"], destination, root=base, params=params, inputs=inputs)
    evidence = _file(receipt_path)
    _, value, _ = _verify_instance(request, evidence)
    return value, evidence


def import_result(request, artifact_path, *, kind=None, provenance, output_dir=None,
                  expected_sha256=None, template_instance=None):
    """Import real output, without attesting how an external provider used inputs.

    For mattes pass ``alpha.json``; for motion pass ``motion-layer.json``. A
    template result also needs the path/hash of its actual instance receipt.
    An identical saved import is reusable; another result needs a new location.
    """
    data = validate_request(request, verify_files=True)
    require(not data["unresolved"], "production_unresolved", "Resolve authoring requirements before importing a result")
    kind = data["output_kind"] if kind is None else kind
    require(kind == data["output_kind"], "production_kind", "Result kind differs from the request")
    origin = _provenance(provenance)
    original = _file(artifact_path, expected_sha256)
    artifact, actual, files = _inspect_artifact(original["path"], kind, data)
    require(artifact == original, "production_file", "Artifact changed during import")
    if "producer_receipt" in origin:
        producer = origin["producer_receipt"]
        evidence = _file(producer["path"], producer["sha256"])
        require("size" not in producer or producer["size"] == evidence["size"], "production_file", "Producer receipt size changed")
        if evidence not in files:
            files.append(evidence)
            files.sort(key=lambda item: item["path"])
    protected = {Path(item["path"]).resolve() for item in data["inputs"]}
    require(not any(Path(item["path"]).resolve() in protected or
                    any(Path(item["path"]).samefile(source) for source in protected) for item in files),
            "production_source", "Produced output must be separate from request inputs")
    instance_evidence = None
    if data["operation"] == "template":
        require(template_instance is not None, "production_template", "Template output needs its instantiated project receipt")
        instance_evidence, _, previews = _verify_instance(data, template_instance)
        project_root = Path(instance_evidence["path"]).parent / "project"
        require(not any(Path(item["path"]).is_relative_to(project_root) for item in files),
                "production_template", "Output must be separate from the instantiated project and its previews")
        require(artifact["sha256"] not in previews, "production_preview", "A provided preview is not a produced variant")
    else:
        require(template_instance is None, "production_template", "Only template production binds an instance receipt")
    validate_request(data, verify_files=True)
    value = {"schema": RESULT_SCHEMA, "request_id": data["id"], "request_revision": data["revision"],
             "request_sha256": data["request_sha256"], "operation": data["operation"], "kind": kind,
             "status": "simulated_result" if origin["simulated"] else "produced_unreviewed",
             "artifact": artifact, "files": files, "technical": actual,
             "source_binding": data["source_binding"], "context": data["context"], "inputs": data["inputs"],
             "provenance": origin, "template_instance": instance_evidence,
             "input_use": "request_bound; actual provider use not independently attested",
             "verification": {"file_bytes": "verified", "media_or_data": "verified", "semantics": "unverified",
                              "continuous_motion": "unverified", "audio_listened": False, "user_approval": "pending"}}
    value = _seal(value, "result_sha256")
    if output_dir is not None:
        root = Path(output_dir).resolve()
        _export_request(data, root)
        _write_once(root / "result.json", value)
    return value


def validate_result(result, request, *, verify_files=True):
    data = validate_request(request, verify_files=verify_files)
    value = clone(mapping(result, "result"))
    require(value.get("schema") == RESULT_SCHEMA, "production_schema", "Expected production-result/1")
    _sealed(value, "result_sha256")
    require(value.get("request_sha256") == data["request_sha256"] and value.get("request_id") == data["id"]
            and value.get("request_revision") == data["revision"] and value.get("operation") == data["operation"]
            and value.get("kind") == data["output_kind"] and value.get("context") == data["context"]
            and value.get("inputs") == data["inputs"] and value.get("source_binding") == data["source_binding"],
            "production_stale", "Result is not bound to the current request and inputs")
    origin = _provenance(value.get("provenance"))
    require(value.get("status") == ("simulated_result" if origin["simulated"] else "produced_unreviewed"),
            "production_status", "Imported output does not imply editorial approval")
    require(value.get("verification") == {"file_bytes": "verified", "media_or_data": "verified", "semantics": "unverified",
            "continuous_motion": "unverified", "audio_listened": False, "user_approval": "pending"},
            "production_review", "Keep technical verification separate from perceptual review")
    for item in sequence(value.get("files"), "files"):
        _fields(item, {"path", "sha256", "size"}, label="result file")
        _absolute(item["path"], "result file.path")
        sha256(item["sha256"], "result file.sha256")
        integer(item["size"], "result file.size", minimum=1)
    require(value.get("artifact") in value["files"], "production_file", "Primary artifact is absent from its file inventory")
    _constraints(mapping(value.get("technical"), "technical"), data)
    if verify_files:
        regenerated = import_result(data, value["artifact"]["path"], kind=value["kind"], provenance=origin,
                                    expected_sha256=value["artifact"]["sha256"], template_instance=value.get("template_instance"))
        require(regenerated == value, "production_stale", "Artifact, nested resource or receipt changed since import")
    return value


def _export_request(request, root):
    if request["operation"] == "template":
        # Check destination before writing request.json: exporting a task must
        # not add even one file to an immutable source package.
        source = _input(request, request["parameters"].get("library_input", "library"))
        library = json.loads(Path(source["path"]).read_text(encoding="utf-8"))
        base = _absolute(request["parameters"].get("root", str(Path(source["path"]).parent)), "template.root")
        for package in library.get("packages", []):
            require(not root.is_relative_to((base / package["root"]).resolve()), "production_source",
                    "Task output cannot be inside an immutable template package")
    _write_once(root / "request.json", request)
    text_path = root / "REQUEST.md"
    text = "# Production request: " + request["id"] + "\n\n"
    text += "Operation: " + request["operation"] + "\n\nExpected result: " + request["output_kind"] + "\n\n"
    text += "## Authored instructions\n\n" + request["prompt"] + "\n\n"
    text += "## Inputs, parameters and constraints\n\n```json\n" + json.dumps(
        {key: request[key] for key in ("inputs", "parameters", "constraints", "source_binding", "unresolved", "context")},
        ensure_ascii=False, indent=2, allow_nan=False) + "\n```\n\n"
    text += ("This is an exported task. No ChatGPT, video or voice service was called by exporting it. "
             "Return the real artifact, its SHA-256, actor/method and explicit simulated true/false. "
             "Import against request_sha256 " + request["request_sha256"] + ". "
             "Technical import does not approve meaning, identity, motion or sound.\n")
    if text_path.exists():
        require(text_path.read_text(encoding="utf-8") == text, "production_output_exists", "Manual export changed")
    else:
        with text_path.open("x", encoding="utf-8") as stream:
            stream.write(text)


def _execution(request, root, status, *, adapter=None, result=None, result_path=None,
               ledger=None, issues=None, instance=None, reused=False, executor_report=None, actual_cost=None):
    return _seal({"schema": EXECUTION_SCHEMA, "request_id": request["id"], "request_sha256": request["request_sha256"],
                  "status": status, "output_dir": str(root), "request_path": str(root / "request.json"),
                  "manual_instructions": str(root / "REQUEST.md"), "adapter": adapter,
                  "result": result, "result_path": result_path, "ledger": ledger, "issues": issues or [],
                  "template_instance": instance, "reused": reused,
                  "executor_report": executor_report, "actual_cost": actual_cost,
                  "user_approval": "pending"}, "execution_sha256")


def _previous_execution(root):
    if (root / "latest.json").exists():
        pointer = json.loads((root / "latest.json").read_text(encoding="utf-8"))
        selected = _file(pointer["path"], pointer["sha256"])
        require(Path(selected["path"]).parent == root, "production_path", "Execution pointer must stay in its task directory")
        previous = json.loads(Path(selected["path"]).read_text(encoding="utf-8"))
        require(previous["execution_sha256"] == pointer["execution_sha256"], "production_digest", "Execution pointer changed")
    elif (root / "execution.json").exists():
        previous = json.loads((root / "execution.json").read_text(encoding="utf-8"))
    else:
        return None
    _sealed(previous, "execution_sha256")
    return previous


def _job_report(job, captured):
    report = captured.get("executor_report")
    if report is None:
        source_root = Path(job["specification"]["source_files"]["production_request"]["path"]).parent
        previous = _previous_execution(source_root)
        if previous and previous.get("ledger") and previous["ledger"]["key"] == job["key"]:
            report = previous.get("executor_report")
    return _file(report["path"], report["sha256"]) if report else None


def _motion(request, root):
    from .motion import render_recipe
    params = request["parameters"]
    allowed = {"backend", "recipe", "font_input", "font_license", "samples", "shutter_angle", "asset_id", "description"}
    require(set(params) <= allowed and {"backend", "recipe"} <= set(params), "production_motion",
            "Bundled motion takes a declarative recipe and tracked font; use a registered adapter for other options")
    require(params["backend"] in {"motionlab", "motngrfx"}, "production_motion",
            "The bundled recipe adapter supports Motion Lab and MOTNGRFX; register other project runtimes explicitly")
    recipe = mapping(params["recipe"], "recipe")
    require(request["output_kind"] in {"video", "motion_layer"}, "production_motion", "Motion produces video or motion_layer")
    require(params["backend"] != "motngrfx" or request["output_kind"] == "motion_layer", "production_motion",
            "MOTNGRFX produces a PNG layer; use an explicit encoder adapter to create a standalone video")
    if request["output_kind"] == "video":
        require(recipe.get("background") is not None, "production_motion", "Author the background for an opaque video; no preview background is inferred")
    kwargs = {name: params[name] for name in ("font_license", "samples", "shutter_angle", "asset_id", "description") if name in params}
    if "font_input" in params:
        font = _input(request, params["font_input"])
        require(font["kind"] == "font", "production_motion", "font_input must identify a tracked font")
        kwargs["font"] = font["path"]
    tracked = {(str(Path(item["path"]).resolve()), item["sha256"]) for item in request["inputs"]}
    for font in recipe.get("fonts", []):
        require((str(Path(font["path"]).resolve()), font["sha256"]) in tracked, "production_motion",
                "Every font embedded in a recipe must also be a hashed request input")
    receipt = render_recipe(params["backend"], clone(recipe), root / "motion", **kwargs)
    if request["output_kind"] == "motion_layer":
        require(receipt.get("contextual_asset"), "production_motion", "Producer did not expose a real alpha sequence")
        path = receipt["contextual_asset"]["manifest_path"]
    else:
        require(request["output_kind"] == "video", "production_motion", "Motion recipe produces video or motion_layer")
        path = receipt["producer"].get("path")
        require(path, "production_motion", "Producer did not return a real video path")
    return {"artifact_path": str(path), "artifact_sha256": _file(path)["sha256"], "actual_cost": 0,
            "provenance": {"actor": "editorial_engine.motion.render_recipe", "method": "Executed the explicit local declarative recipe",
                           "simulated": False, "backend": params["backend"], "producer_receipt": _file(root / "motion" / "run.json")}}


def _planar_portal(request, root):
    """Render a declared portal only when all nested media are tracked inputs."""
    from visual_fidelity.planar_portal import render as render_portal
    params = _fields(request["parameters"], {"manifest_input"}, label="planar_portal.parameters")
    require(request["output_kind"] == "video", "production_portal", "Bundled planar_portal produces a silent video")
    manifest_input = _input(request, params["manifest_input"])
    require(manifest_input["kind"] == "json", "production_portal", "manifest_input must identify a declared JSON input")
    _file(manifest_input["path"], manifest_input["sha256"])
    manifest_path = Path(manifest_input["path"]).resolve()
    manifest = mapping(json.loads(manifest_path.read_text(encoding="utf-8")), "portal manifest")
    require(manifest.get("schema") == "planar-portal/1", "production_portal", "Expected planar-portal/1")
    tracked = {(str(Path(item["path"]).resolve()), item["sha256"]) for item in request["inputs"]}
    sources = [mapping(manifest.get(name), "portal." + name) for name in ("base", "insert")]
    if manifest.get("occlusion") is not None:
        sources.append(mapping(mapping(manifest["occlusion"], "portal.occlusion").get("source"), "portal.occlusion.source"))
    for source in sources:
        require(source.get("kind") in {"image", "video", "sequence"}, "production_portal", "Unknown portal source kind")
        files = sequence(source.get("files"), "portal source files") if source["kind"] == "sequence" else [source]
        require(bool(files), "production_portal", "Portal sources cannot be empty")
        for item in files:
            mapping(item, "portal source file")
            path = (manifest_path.parent / nonempty(item.get("path"), "portal source path")).resolve()
            expected = sha256(item.get("sha256"), "portal source sha256")
            require((str(path), expected) in tracked, "production_portal_input",
                    "Every portal base, insert, occlusion and sequence file must also be a hashed request input", str(path))
    output = root / "portal.mp4"
    receipt = render_portal(manifest_path, output)
    return {"artifact_path": str(output), "artifact_sha256": receipt["output_sha256"], "actual_cost": 0,
            "provenance": {"actor": "visual_fidelity.planar_portal.render",
                "method": "Rendered independent hashed sources through authored four-corner geometry on an explicit frame clock",
                "simulated": False, "mapping": receipt["mapping"], "audio": "not_rendered",
                "producer_receipt": _file(output.with_suffix(".mp4.json"))}}


def execute_request(request, output_dir, *, executor=None, registry=None, ledger=None,
                    estimated_cost=0, retry_failed=False):
    """Export, stage or execute explicitly; unknown executions are never retried.

    A callable receives one context object: request, output_dir, job_key and
    template_instance. Return artifact_path, artifact_sha256, actual_cost and
    provenance {actor, method, simulated}; or a known failed result and cost.
    With a ledger, its durable job owns retries and cost reservations.
    """
    data = validate_request(request, verify_files=True)
    require(ledger is None or isinstance(ledger, WorkflowLedger), "production_ledger", "Use the existing WorkflowLedger")
    root = Path(output_dir).resolve()
    _export_request(data, root)
    external_video = data["operation"] == "external_video"
    # A supplied callable, adapter ID or request flag cannot enable video model
    # execution. Keep the external task portable and let the user return media.
    adapter = None if external_video else _adapter(data, executor, registry)
    builtin_motion = data["operation"] == "motion_recipe" and adapter is None and data["adapter_id"] in (None, "bundled.motion")
    builtin_portal = data["operation"] == "planar_portal" and adapter is None and data["adapter_id"] in (None, "bundled.planar_portal")
    builtin = builtin_motion or builtin_portal
    descriptor = adapter.descriptor() if adapter else ({"id": "bundled.motion", "version": "1", "simulated": False,
        "implementation_sha256": _file(__file__)["sha256"],
        "motion_sha256": _file(Path(__file__).with_name("motion.py"))["sha256"]} if builtin_motion else None)
    if builtin_portal:
        from visual_fidelity import planar_portal, geometric_replay, subject_alignment
        descriptor = {"id": "bundled.planar_portal", "version": planar_portal.VERSION, "simulated": False,
            "implementation_sha256": _file(__file__)["sha256"],
            "portal_sha256": _file(planar_portal.__file__)["sha256"],
            "geometry_sha256": _file(geometric_replay.__file__)["sha256"],
            "subject_alignment_sha256": _file(subject_alignment.__file__)["sha256"]}
    previous_path = root / "execution.json"
    previous = _previous_execution(root)
    if previous:
        require(previous["request_sha256"] == data["request_sha256"], "production_stale", "Output belongs to another request")
        if builtin_portal and previous["status"] == "succeeded":
            require(previous["adapter"] == descriptor, "production_stale",
                    "Portal implementation changed; keep this result and render a new execution directory")
        if previous["ledger"] is not None:
            require(ledger is not None, "production_ledger", "Resume a ledger-managed job with its ledger")
            old_job = ledger.get_job(previous["ledger"]["key"])
            require(old_job is not None, "production_ledger", "The supplied ledger does not own this execution")
            if old_job["status"] in {"unknown", "running"}:
                # Reconfiguring/removing a callback cannot bypass an unresolved
                # job. Reconciliation belongs to the existing ledger attempt.
                return _execution(data, root, old_job["status"], adapter=previous["adapter"],
                    ledger={key: old_job.get(key) for key in ("key", "status", "attempt", "cost", "error")},
                    issues=[old_job["error"]] if old_job.get("error") else [],
                    executor_report=_job_report(old_job, {}), reused=True)
            if old_job["status"] == "succeeded":
                result_path = old_job["artifact"]["path"]
                result = validate_result(json.loads(Path(result_path).read_text(encoding="utf-8")), data)
                return _execution(data, root, "succeeded", adapter=previous["adapter"], result=result, result_path=result_path,
                    ledger={key: old_job.get(key) for key in ("key", "status", "attempt", "cost", "error")},
                    executor_report=_job_report(old_job, {}), actual_cost=old_job["cost"]["actual"], reused=True)
            if old_job["status"] == "failed" and not retry_failed:
                return _execution(data, root, "failed", adapter=previous["adapter"],
                    ledger={key: old_job.get(key) for key in ("key", "status", "attempt", "cost", "error")},
                    issues=[old_job["error"]] if old_job.get("error") else [],
                    executor_report=_job_report(old_job, {}), actual_cost=old_job["cost"]["actual"], reused=True)
    if external_video and ledger is not None:
        pending = ledger.unresolved_production_jobs(data["request_sha256"])
        require(len(pending) <= 1, "production_ledger",
                "Reconcile all historical pending jobs for this video request before exporting a new state: "
                + ", ".join(job["key"] for job in pending))
        if pending:
            old_job = pending[0]
            value = _execution(data, root, old_job["status"],
                adapter=old_job["specification"].get("plan", {}).get("adapter"),
                ledger={key: old_job.get(key) for key in ("key", "status", "attempt", "cost", "error")},
                issues=[old_job["error"]] if old_job.get("error") else [],
                executor_report=_job_report(old_job, {}), reused=True)
            if previous is None:
                _write_once(previous_path, value)
            return value
    if data["unresolved"]:
        return _execution(data, root, "blocked", adapter=descriptor, issues=data["unresolved"])
    # A local successful import can satisfy a manual task. An unresolved ledger
    # remains under ledger control; an artifact alone does not settle its cost.
    if ledger is None and (root / "result.json").exists():
        result = validate_result(json.loads((root / "result.json").read_text(encoding="utf-8")), data)
        return _execution(data, root, "succeeded", adapter=descriptor, result=result,
                          result_path=str(root / "result.json"), reused=True)
    if ledger is None and previous and previous["status"] in {"unknown", "running", "failed"}:
        if previous["status"] != "failed" or not retry_failed:
            return _seal({**previous, "reused": True}, "execution_sha256")
    if external_video:
        policy = execution_policy()
        _write_once(root / "VIDEO-GENERATION-POLICY.json", policy)
        value = _execution(data, root, "awaiting_external_generation", reused=previous is not None,
                           issues=[{"code": "video_generation_prompt_only",
                                    "message": "Video generation exports prompts and settings. Generate in the tool you choose and import the returned video."}])
        value = _seal({**value, "execution_policy": policy}, "execution_sha256")
        if previous is None:
            _write_once(previous_path, value)
        return value
    if data["output_kind"] == "video" and adapter is not None:
        require(data["operation"] in LOCAL_VIDEO_OPERATIONS or adapter.execution_kind == "local_processing",
                "video_generation_prompt_only",
                "Video synthesis exports prompts only. An unfamiliar video callback requires host-registered local_processing metadata.")
    instance, instance_evidence = (None, None)
    if data["operation"] == "template":
        instance, instance_evidence = _instantiate(data, root)
    if not builtin and adapter is None:
        status = "instantiated_not_rendered" if instance else ("awaiting_adapter" if data["adapter_id"] else "awaiting_external")
        value = _execution(data, root, status, instance=instance_evidence, reused=previous is not None)
        # Pending exports are not executed jobs and may resume with a configured callback.
        if previous is None:
            _write_once(previous_path, value)
        return value

    captured = {}

    def run_callback(_graph, job_key):
        captured["key"] = job_key
        attempt = ledger.get_job(job_key, verify_artifact=False)["attempt"] if ledger is not None else 1
        if ledger is None and previous and retry_failed:
            attempt = 1 + len(list(root.glob("attempt-*")))
        work = root / f"attempt-{attempt:03d}"
        require(not work.exists(), "production_output_exists", "Execution attempt directory already exists")
        work.mkdir()
        context = {"request": clone(data), "output_dir": str(work), "job_key": job_key,
                   "template_instance": clone(instance), "template_instance_file": clone(instance_evidence),
                   "cost_limit": estimated_cost, "cost_unit": ledger.budget()["unit"] if ledger else None}
        if builtin:
            try:
                outcome = _planar_portal(data, work) if builtin_portal else _motion(data, work)
            except (ValueError, OSError, RuntimeError, KeyError, TypeError, ImportError, subprocess.SubprocessError) as error:
                outcome = {"status": "failed", "actual_cost": 0, "error": "local_adapter_failed:" + str(error)}
        else:
            outcome = adapter.executor(context)
        require(isinstance(outcome, dict), "production_executor", "Executor must return an object")
        _write_once(work / "executor-report.json", clone(outcome))
        captured["executor_report"] = _file(work / "executor-report.json")
        if outcome.get("status") not in (None, "succeeded", "failed"):
            return outcome  # Ledger retains running/unknown and its reservation.
        if "actual_cost" not in outcome:
            return outcome  # Unknown cost cannot be silently replaced by zero.
        if outcome.get("status") == "failed":
            return outcome
        try:
            provenance = _provenance(outcome.get("provenance"))
            require(not (adapter and adapter.simulated) or provenance["simulated"], "production_provenance",
                    "A simulated adapter must label its result as simulated")
            require(outcome.get("artifact_sha256"), "production_file", "Executor must return its output hash")
            artifact_path = _absolute(outcome.get("artifact_path"), "executor.artifact_path")
            require(artifact_path.is_relative_to(work), "production_output", "Callback output must be inside its new attempt directory")
            result = import_result(data, artifact_path, provenance={**provenance, "execution_adapter": descriptor,
                                   "execution_scope": "explicit_python_callback"}, expected_sha256=outcome["artifact_sha256"],
                                   template_instance=instance_evidence)
            require(all(Path(item["path"]).is_relative_to(work) for item in result["files"]),
                    "production_output", "All callback output resources must be inside its new attempt directory")
            _write_once(work / "result.json", result)
            captured["result"] = result
            return {"artifact_path": str(work / "result.json"), "artifact_sha256": _file(work / "result.json")["sha256"],
                    "actual_cost": outcome["actual_cost"]}
        except (ValueError, OSError, KeyError, TypeError) as error:
            return {"status": "failed", "actual_cost": outcome["actual_cost"], "error": "result_invalid:" + str(error)}

    if ledger is not None:
        require(isinstance(ledger, WorkflowLedger), "production_ledger", "Use the existing WorkflowLedger")
        recipe = {"id": "production-adapter", "version": "1", "spatial_mode": "none",
                  "workflow": {"produce": {"class_type": "ExplicitPythonAdapter", "inputs": {"request_sha256": data["request_sha256"]}}}}
        source_paths = {"production_request": root / "request.json", **{"input:" + item["id"]: item["path"] for item in data["inputs"]}}
        # Instance bytes are validated separately. Its receipt contains output
        # paths; adding that derived file to job identity would duplicate the
        # same provider request merely because the export directory changed.
        try:
            job = ledger.run(plan={"request": data, "adapter": descriptor}, source_paths=source_paths,
                recipe=recipe, params={}, availability={"nodes": {"ExplicitPythonAdapter": True}},
                executor=run_callback, estimated_cost=estimated_cost, retry_failed=retry_failed)
        except ExecutionUnknown:
            job = ledger.get_job(captured["key"])
        summary = {key: job.get(key) for key in ("key", "status", "attempt", "cost", "error", "reused")}
        report = _job_report(job, captured)
        if job["status"] == "succeeded":
            result_path = job["artifact"]["path"]
            result = validate_result(json.loads(Path(result_path).read_text(encoding="utf-8")), data)
            value = _execution(data, root, "succeeded", adapter=descriptor, result=result, result_path=result_path,
                               ledger=summary, instance=instance_evidence, reused=job.get("reused", False),
                               executor_report=report, actual_cost=job["cost"]["actual"])
        else:
            value = _execution(data, root, job["status"], adapter=descriptor, ledger=summary,
                               issues=[job.get("error")] if job.get("error") else [], instance=instance_evidence,
                               reused=job.get("reused", False), executor_report=report)
    else:
        try:
            outcome = run_callback({}, data["request_sha256"])
            number(outcome.get("actual_cost"), "actual_cost", minimum=0)
            if outcome.get("status") == "failed" and "actual_cost" in outcome:
                value = _execution(data, root, "failed", adapter=descriptor, issues=[str(outcome.get("error", "executor_failed"))],
                                   executor_report=captured.get("executor_report"), actual_cost=outcome["actual_cost"])
            elif outcome.get("status") in (None, "succeeded") and "actual_cost" in outcome and "result" in captured:
                result = captured["result"]
                _write_once(root / "result.json", result)
                value = _execution(data, root, "succeeded", adapter=descriptor, result=result, result_path=str(root / "result.json"),
                                   instance=instance_evidence, executor_report=captured.get("executor_report"), actual_cost=outcome["actual_cost"])
            else:
                value = _execution(data, root, "unknown", adapter=descriptor, issues=["Execution or actual cost is not terminal/known"],
                                   executor_report=captured.get("executor_report"))
        except Exception as error:
            value = _execution(data, root, "unknown", adapter=descriptor, issues=["executor_exception:" + str(error)],
                               executor_report=captured.get("executor_report"))
    # Revision of execution state is append-only; execution.json is the initial
    # state, and latest.json is only a pointer to a sealed event file.
    event = root / ("execution-" + value["execution_sha256"] + ".json")
    _write_once(event, value)
    if not previous_path.exists():
        _write_once(previous_path, value)
    _write_latest(root, event, value)
    return value


def _write_latest(root, event, value):
    # The immutable event is authoritative. Replacing this small pointer never
    # discards the initial pending state or an earlier execution receipt.
    pointer = {"path": str(event), "sha256": _file(event)["sha256"], "execution_sha256": value["execution_sha256"]}
    temporary = root / ".latest.tmp"
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(pointer, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    temporary.replace(root / "latest.json")


def queue_status(requests, results=(), *, verify_files=True):
    """Describe authored needs without selecting providers or executing work."""
    supplied = {item["request_sha256"]: item for item in results}
    rows, ids = [], set()
    for request in requests:
        data = validate_request(request, verify_files=verify_files)
        require(data["id"] not in ids, "production_id", "A queue needs one current revision per request id")
        ids.add(data["id"])
        result = supplied.get(data["request_sha256"])
        if result is not None:
            result = validate_result(result, data, verify_files=verify_files)
            status = result["status"]
        else:
            status = "blocked" if data["unresolved"] else "awaiting_production"
        rows.append({"request_id": data["id"], "request_sha256": data["request_sha256"],
                     "operation": data["operation"], "output_kind": data["output_kind"], "status": status,
                     "unresolved": data["unresolved"], "result_sha256": result["result_sha256"] if result else None})
    return {"schema": "production-queue/1", "needs": rows, "execution_performed": False}
