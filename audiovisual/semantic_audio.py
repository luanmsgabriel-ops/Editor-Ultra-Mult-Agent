"""Auditable SFX retrieval and spotting, with optional local CLAP inference.

Indexing metadata never pretends to be semantic search. CLAP is loaded only on
request, from an already populated local Hugging Face cache; this module does
not install dependencies, download weights, or call a paid API. A supplied
encoder is an explicit integration boundary, not evidence of CLAP validation.

All source sample positions are relative to decoded PCM sample zero, not to
container PTS. Spotting resamples BEFORE trimming; the returned ``sfx`` uses the
single sample clock expected by ``extensions.editor_policy.validate_plan``.
An amplitude peak is an inferred candidate, never an approved perceptual apex.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Protocol

import numpy as np


SCHEMA_VERSION = 1
DEFAULT_MODEL = "laion/clap-htsat-fused"


class SemanticAudioUnavailable(RuntimeError):
    """A semantic dependency or an actual embedding index is unavailable."""


class CatalogIntegrityError(ValueError):
    """Catalog contents no longer identify the bytes that were indexed."""


class AudioEncoder(Protocol):
    model_id: str
    checkpoint: str
    sample_rate: int

    def encode_audio(self, audio: np.ndarray, sample_rate: int) -> Any: ...

    def encode_text(self, text: str) -> Any: ...


def _int(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name}: expected integer >= {minimum}.")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}: expected nonempty text.")
    return value


def _ratio(value: Any, name: str, *, positive: bool = False) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, (int, str, Fraction)):
        raise ValueError(f"{name}: use integer, Fraction, or rational string.")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError(f"{name}: invalid rational value.") from error
    if result < 0 or (positive and result == 0):
        raise ValueError(f"{name}: rational value out of range.")
    return result


def _nearest_sample(value: Fraction) -> int:
    """Round exact rational samples to nearest; ties go towards +infinity."""
    quotient, remainder = divmod(value.numerator, value.denominator)
    return quotient + int(2 * remainder >= value.denominator)


def _digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _program(name: str) -> str:
    result = shutil.which(name)
    if result is None:
        raise SemanticAudioUnavailable(f"{name} is unavailable; audio was not decoded.")
    return result


def _run(command: list[str]) -> bytes:
    try:
        result = subprocess.run(command, check=True, capture_output=True, timeout=300)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace")[-1500:]
        raise ValueError(f"Audio command failed: {detail.strip()}") from error
    except subprocess.TimeoutExpired as error:
        raise SemanticAudioUnavailable("Audio command timed out; indexing is incomplete.") from error
    return result.stdout


def probe_backend() -> dict[str, Any]:
    """Report presence only. No model imports, loading, downloads, or inference."""
    modules = {}
    for name in ("torch", "transformers"):
        try:
            modules[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            modules[name] = False
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "clap": {
            "model_id": DEFAULT_MODEL,
            "dependency_modules": modules,
            "dependencies_present": all(modules.values()),
            "weights_verified": False,
            "inference_executed": False,
            "automatic_download": False,
            "status": "not_verified" if all(modules.values()) else "unavailable",
        },
        "api_calls": 0,
        "model_cost": "not_measured",
    }


class ClapEncoder:
    """Lazy Transformers CLAP adapter. It only reads already cached weights."""

    sample_rate = 48000
    backend = "transformers_clap_local"

    def __init__(self, model_id: str = DEFAULT_MODEL, checkpoint: str = "main", *, device: str = "cpu"):
        self.model_id = _text(model_id, "model_id")
        self.checkpoint = _text(checkpoint, "checkpoint")
        self.requested_checkpoint = self.checkpoint
        self.device = _text(device, "device")
        self._model = self._processor = self._torch = None

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import ClapModel, ClapProcessor
        except (ImportError, OSError, RuntimeError) as error:
            raise SemanticAudioUnavailable(
                "CLAP requires working torch and transformers installations; no keyword fallback was used."
            ) from error
        try:
            processor = ClapProcessor.from_pretrained(
                self.model_id, revision=self.requested_checkpoint,
                local_files_only=True, trust_remote_code=False,
            )
            model = ClapModel.from_pretrained(
                self.model_id, revision=self.requested_checkpoint,
                local_files_only=True, trust_remote_code=False,
            ).to(self.device)
            model.eval()
        except (OSError, RuntimeError, ValueError, ImportError) as error:
            raise SemanticAudioUnavailable(
                "CLAP local weights or runtime are unavailable. Populate the cache separately; "
                "this operation neither downloads weights nor substitutes text matching."
            ) from error
        resolved = getattr(model.config, "_commit_hash", None)
        if resolved:
            self.checkpoint = str(resolved)
        self._torch, self._processor, self._model = torch, processor, model

    def _features(self, inputs: Any, method: str) -> np.ndarray:
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self._torch.inference_mode():
            features = getattr(self._model, method)(**inputs)
        if not hasattr(features, "detach"):
            raise SemanticAudioUnavailable("The installed CLAP API did not return tensor features.")
        values = features.detach().cpu().numpy()
        if values.ndim != 2 or values.shape[0] != 1:
            raise ValueError("CLAP must return exactly one embedding for each request.")
        return values[0]

    def encode_audio(self, audio: np.ndarray, sample_rate: int) -> np.ndarray:
        if sample_rate != self.sample_rate:
            raise ValueError("CLAP input must be explicitly resampled to 48000 Hz before encoding.")
        signal = np.asarray(audio, dtype=np.float32)
        if signal.ndim != 1 or signal.size == 0 or not np.isfinite(signal).all():
            raise ValueError("CLAP expects a finite, nonempty mono waveform.")
        self._load()
        inputs = self._processor(audios=signal, sampling_rate=sample_rate, return_tensors="pt")
        return self._features(inputs, "get_audio_features")

    def encode_text(self, text: str) -> np.ndarray:
        self._load()
        inputs = self._processor(text=[_text(text, "query")], return_tensors="pt", padding=True)
        return self._features(inputs, "get_text_features")


def _identity(encoder: AudioEncoder) -> tuple[str, str]:
    return _text(encoder.model_id, "encoder.model_id"), _text(encoder.checkpoint, "encoder.checkpoint")


def _vector(value: Any, name: str, dimension: int | None = None) -> np.ndarray:
    try:
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{name}: invalid embedding.") from error
    if result.ndim != 1 or result.size == 0 or not np.isfinite(result).all():
        raise ValueError(f"{name}: embedding must be a finite, nonempty one-dimensional vector.")
    if dimension is not None and result.size != dimension:
        raise ValueError(f"{name}: dimension {result.size} does not match {dimension}.")
    maximum = float(np.max(np.abs(result)))
    if maximum == 0:
        raise ValueError(f"{name}: zero embeddings cannot be compared by cosine similarity.")
    # Scaling before the norm avoids overflow for large but finite input values.
    scaled = result / maximum
    return scaled / np.linalg.norm(scaled)


def _decode(path: Path, sample_rate: int, channels: int) -> np.ndarray:
    payload = _run([
        _program("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-vn", "-ac", str(channels), "-ar", str(sample_rate),
        "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1",
    ])
    if not payload or len(payload) % (4 * channels):
        raise ValueError("Audio decoding produced empty or incomplete PCM frames.")
    audio = np.frombuffer(payload, dtype="<f4").reshape(-1, channels)
    if not np.isfinite(audio).all():
        raise ValueError("Decoded audio contains nonfinite samples.")
    return audio


def _probe_audio(path: Path) -> tuple[dict[str, Any], np.ndarray]:
    payload = _run([
        _program("ffprobe"), "-v", "error", "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate,channels,start_time,time_base,duration_ts:format=duration",
        "-of", "json", str(path),
    ])
    details = json.loads(payload)
    streams = details.get("streams", [])
    if not streams:
        raise ValueError(f"No audio stream in {path.name}.")
    stream = streams[0]
    rate = _int(int(stream.get("sample_rate", 0)), "sample_rate", 1)
    channels = _int(int(stream.get("channels", 0)), "channels", 1)
    audio = _decode(path, rate, channels)
    duration = Fraction(len(audio), rate)
    return {
        "sample_rate": rate,
        "channels": channels,
        "sample_count": len(audio),
        "duration_seconds": str(duration),
        "duration_ms": _nearest_sample(duration * 1000),
        "clock": "decoded_pcm_sample_zero",
        "source_stream_start_time": stream.get("start_time"),
        "source_stream_time_base": stream.get("time_base"),
        "source_stream_duration_ts": stream.get("duration_ts"),
        "container_duration_seconds": details.get("format", {}).get("duration"),
    }, audio


def verify_asset(asset: dict[str, Any]) -> Path:
    """Verify bytes before retrieval or spotting; never silently use stale assets."""
    path = Path(_text(asset.get("path"), "asset.path"))
    expected = _text(asset.get("sha256"), "asset.sha256")
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise CatalogIntegrityError("Invalid SHA-256 in audio catalog.")
    if not path.is_file():
        raise CatalogIntegrityError(f"Indexed audio is missing: {path}.")
    if _digest(path) != expected:
        raise CatalogIntegrityError(f"Indexed audio bytes changed: {asset.get('id', path.name)}.")
    if "size_bytes" in asset and path.stat().st_size != asset["size_bytes"]:
        raise CatalogIntegrityError("Indexed audio file size changed.")
    return path


def _anchor(spec: dict[str, Any], audio: np.ndarray) -> dict[str, Any]:
    supplied = spec.get("anchor")
    if supplied is not None:
        if not isinstance(supplied, dict):
            raise ValueError("anchor must be an object with a source PCM sample.")
        sample = _int(supplied.get("sample"), "anchor.sample")
        if sample >= len(audio):
            raise ValueError("anchor.sample is outside decoded audio.")
        status = supplied.get("status", "inferred")
        if status not in {"inferred", "reviewed"}:
            raise ValueError("anchor.status must be inferred or reviewed.")
        return {
            "sample": sample,
            "kind": _text(supplied.get("kind", "provided_candidate"), "anchor.kind"),
            "status": status,
            "method": "supplied_metadata",
            "review_note": supplied.get("review_note"),
            "reviewed_by": supplied.get("reviewed_by"),
            "perceptual_apex_verified": status == "reviewed" and supplied.get("perceptual_apex_verified") is True,
        }
    envelope = np.max(np.abs(audio), axis=1)
    peak = float(np.max(envelope))
    if peak <= 1e-8:
        return {"sample": None, "kind": "none", "status": "unavailable", "method": "silence",
                "perceptual_apex_verified": False}
    active = np.flatnonzero(envelope >= max(peak * 0.02, 1e-7))
    return {
        "sample": int(np.argmax(envelope)),
        "kind": "amplitude_peak_candidate",
        "status": "inferred",
        "method": "maximum_absolute_channel_amplitude",
        "activity_start_sample": int(active[0]),
        "activity_end_sample_exclusive": int(active[-1]) + 1,
        "perceptual_apex_verified": False,
        "note": "Energy landmarks are candidates; onset, amplitude peak and perceptual apex are not interchangeable.",
    }


def index_audio_assets(asset_specs: Any, *, encoder: AudioEncoder | None = None) -> dict[str, Any]:
    """Build a byte-bound index from explicit local assets; no recursive discovery.

    Each spec needs ``id`` and ``path`` (``local_file`` is also accepted for the
    existing ElevenLabs staging manifest). A path alone uses its stem as ID.
    With no encoder this produces metadata only, explicitly unavailable for
    semantic retrieval. Injected encoders must declare model_id/checkpoint.
    """
    specs = asset_specs.get("assets") if isinstance(asset_specs, dict) else asset_specs
    if not isinstance(specs, (list, tuple)) or not specs:
        raise ValueError("Provide a nonempty explicit list of audio assets.")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    model: dict[str, Any] | None = None
    for raw in specs:
        spec = {"id": Path(raw).stem, "path": str(raw)} if isinstance(raw, (str, Path)) else raw
        if not isinstance(spec, dict):
            raise ValueError("Audio asset specs must be objects or local paths.")
        identifier = _text(spec.get("id"), "asset.id")
        if identifier in seen:
            raise ValueError(f"Duplicate audio asset ID: {identifier}.")
        seen.add(identifier)
        path = Path(_text(spec.get("path", spec.get("local_file")), "asset.path")).resolve()
        if not path.is_file():
            raise ValueError(f"Audio asset does not exist: {path}.")
        digest = _digest(path)
        if spec.get("sha256") is not None and spec["sha256"] != digest:
            raise CatalogIntegrityError(f"Supplied hash does not match audio: {identifier}.")
        metadata, audio = _probe_audio(path)
        review_status = spec.get("review_status", "pending")
        if review_status not in {"pending", "reviewed", "approved", "rejected"}:
            raise ValueError("Unknown audio review_status.")
        row = {
            "id": identifier, "path": str(path), "sha256": digest,
            "size_bytes": path.stat().st_size,
            "kind": _text(spec.get("kind", spec.get("family", "unknown")), "asset.kind"),
            "review_status": review_status, "metadata": metadata,
            "anchor": _anchor(spec, audio), "embedding": None,
        }
        # Keep provenance without inferring editorial rights from file access.
        for key in ("source", "license_status", "uses", "tags", "root_id", "drive_file_id", "provider_generation_id"):
            if key in spec:
                row[key] = spec[key]
        if encoder is not None:
            rate = _int(getattr(encoder, "sample_rate", metadata["sample_rate"]), "encoder.sample_rate", 1)
            mono = audio.mean(axis=1) if rate == metadata["sample_rate"] else _decode(path, rate, 1)[:, 0]
            values = _vector(encoder.encode_audio(mono, rate), "audio embedding")
            model_id, checkpoint = _identity(encoder)  # Loading may resolve a revision to an exact commit.
            identity = {"model_id": model_id, "checkpoint": checkpoint, "dimension": int(values.size)}
            if model is None:
                model = identity
            elif identity != model:
                raise ValueError("Encoder model identity or dimension changed while indexing.")
            row["embedding"] = {**identity, "values": values.tolist(), "input_sample_rate": rate}
        if _digest(path) != digest:
            raise CatalogIntegrityError(f"Audio changed during indexing: {identifier}.")
        rows.append(row)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ready" if model else "metadata_only",
        "semantic_search": "available" if model else "unavailable",
        "unavailable_reason": None if model else "No embeddings were requested or computed.",
        "embedding_model": model,
        "embedding_backend": getattr(encoder, "backend", "injected_encoder") if encoder else None,
        "clap_inference_executed": isinstance(encoder, ClapEncoder) and encoder._model is not None,
        "injected_encoder": encoder is not None and not isinstance(encoder, ClapEncoder),
        "perceptual_review_performed": False,
        "assets": rows,
    }


def _validate_index(index: dict[str, Any], *, embeddings: bool) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not isinstance(index, dict) or index.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported semantic audio index schema.")
    assets = index.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("Audio index contains no assets.")
    if any(not isinstance(asset, dict) for asset in assets):
        raise ValueError("Audio index assets must be objects.")
    model = index.get("embedding_model")
    if embeddings and (not isinstance(model, dict) or any(not asset.get("embedding") for asset in assets)):
        raise SemanticAudioUnavailable("Audio index has no complete embeddings; keyword fallback is disabled.")
    if model is not None:
        if not isinstance(model, dict):
            raise ValueError("embedding_model must be an object or null.")
        _text(model.get("model_id"), "embedding_model.model_id")
        _text(model.get("checkpoint"), "embedding_model.checkpoint")
        _int(model.get("dimension"), "embedding_model.dimension", 1)
    seen: set[str] = set()
    for asset in assets:
        identifier = _text(asset.get("id"), "asset.id")
        if identifier in seen:
            raise ValueError("Duplicate IDs in audio index.")
        seen.add(identifier)
        verify_asset(asset)
        if embeddings:
            embedded = asset["embedding"]
            if not isinstance(embedded, dict):
                raise ValueError(f"Embedding for {identifier} must be an object.")
            if any(embedded.get(key) != model[key] for key in ("model_id", "checkpoint", "dimension")):
                raise ValueError(f"Embedding model mismatch for {identifier}.")
            _vector(embedded.get("values"), identifier, model["dimension"])
    return assets, model


def search(index: dict[str, Any], *, query: str | None = None, query_embedding: Any = None,
           encoder: AudioEncoder | None = None, model_id: str | None = None,
           checkpoint: str | None = None, top_k: int = 5,
           kinds: list[str] | None = None) -> dict[str, Any]:
    """Cosine retrieval with strict embedding provenance and current-byte checks.

    A precomputed query may be a vector plus model_id/checkpoint or an object
    with those fields and ``values``. Text requires an encoder; omitted means
    local-only ClapEncoder using the index's exact recorded checkpoint.
    """
    _int(top_k, "top_k", 1)
    if (query is None) == (query_embedding is None):
        raise ValueError("Provide exactly one of query or query_embedding.")
    assets, model = _validate_index(index, embeddings=True)
    if kinds is not None and (not isinstance(kinds, list) or any(not isinstance(kind, str) or not kind for kind in kinds)):
        raise ValueError("kinds must be a list of nonempty strings.")
    if query is not None:
        _text(query, "query")
        if model_id is not None and model_id != model["model_id"]:
            raise ValueError("Requested query model does not match the index.")
        if checkpoint is not None and checkpoint != model["checkpoint"]:
            raise ValueError("Requested query checkpoint does not match the index.")
        encoder = encoder or ClapEncoder(model["model_id"], model["checkpoint"])
        raw = encoder.encode_text(query)
        query_model, query_checkpoint = _identity(encoder)
    else:
        if encoder is not None:
            raise ValueError("An encoder is not used with a precomputed query embedding.")
        if isinstance(query_embedding, dict):
            query_model = query_embedding.get("model_id")
            query_checkpoint = query_embedding.get("checkpoint")
            if model_id is not None and model_id != query_model:
                raise ValueError("Conflicting query model IDs.")
            if checkpoint is not None and checkpoint != query_checkpoint:
                raise ValueError("Conflicting query checkpoints.")
            raw = query_embedding.get("values")
        else:
            raw, query_model, query_checkpoint = query_embedding, model_id, checkpoint
    if (query_model, query_checkpoint) != (model["model_id"], model["checkpoint"]):
        raise ValueError("Query and catalog embeddings must use the same model and checkpoint.")
    vector = _vector(raw, "query embedding", model["dimension"])
    matches = []
    excluded = []
    for asset in assets:
        reason = "review_rejected" if asset.get("review_status") == "rejected" else None
        if kinds is not None and asset.get("kind") not in kinds:
            reason = "kind_filter"
        if reason:
            excluded.append({"id": asset["id"], "reason": reason})
            continue
        candidate = _vector(asset["embedding"]["values"], asset["id"], model["dimension"])
        score = float(np.clip(np.dot(vector, candidate), -1.0, 1.0))
        matches.append({
            "id": asset["id"], "path": asset["path"], "sha256": asset["sha256"],
            "score": score, "kind": asset.get("kind"),
            "review_status": asset.get("review_status", "pending"),
            "anchor_status": asset.get("anchor", {}).get("status", "unavailable"),
        })
    matches.sort(key=lambda item: (-item["score"], item["id"]))
    return {
        "status": "ok", "method": "embedding_cosine", "embedding_model": model,
        "matches": matches[:top_k], "excluded": excluded,
        "semantic_fallback": False, "editorial_decision": "not_performed",
        "note": "Similarity retrieves candidates; it does not establish editorial fitness or publication rights.",
    }


def spot_sfx(asset: dict[str, Any], *, target_sample: int, timeline_sample_rate: int,
             trim_in: int = 0, trim_out: int | None = None,
             source_attack_sample: int | None = None, intended_offset_samples: int = 0,
             negative_start_policy: str = "reject", require_reviewed_anchor: bool = False) -> dict[str, Any]:
    """Place an SFX attack in exact sample clocks, with explicit resample rounding.

    trim_in/trim_out/attack are in SOURCE PCM samples; target and intended offset
    are in TIMELINE samples. Render in the documented order: resample, trim,
    reset PTS, then delay. ``trim_start`` explicitly drops pre-roll before zero.
    It does not shift the attack away from its target.
    """
    path = verify_asset(asset)
    if asset.get("review_status") == "rejected":
        raise ValueError("An explicitly rejected audio asset cannot be spotted.")
    target = _int(target_sample, "target_sample")
    rate = _int(timeline_sample_rate, "timeline_sample_rate", 1)
    if type(intended_offset_samples) is not int:
        raise ValueError("intended_offset_samples must be an integer.")
    if target + intended_offset_samples < 0:
        raise ValueError("The intended attack cannot occur before timeline zero.")
    if negative_start_policy not in {"reject", "trim_start"}:
        raise ValueError("negative_start_policy must be reject or trim_start.")
    metadata = asset.get("metadata", {})
    source_rate = _int(metadata.get("sample_rate"), "source sample_rate", 1)
    source_count = _int(metadata.get("sample_count"), "source sample_count", 1)
    start_trim = _int(trim_in, "trim_in")
    end_trim = source_count if trim_out is None else _int(trim_out, "trim_out", 1)
    if not 0 <= start_trim < end_trim <= source_count:
        raise ValueError("Source trim must be a nonempty interval within decoded audio.")
    anchor = asset.get("anchor", {})
    overridden = source_attack_sample is not None
    attack = source_attack_sample if overridden else anchor.get("sample")
    if attack is None:
        raise SemanticAudioUnavailable("No usable source anchor: supply a reviewed attack sample.")
    attack = _int(attack, "source_attack_sample")
    if not start_trim <= attack < end_trim:
        raise ValueError("Source attack must lie inside the retained half-open trim interval.")
    anchor_status = "inferred" if overridden else anchor.get("status", "inferred")
    if require_reviewed_anchor and anchor_status != "reviewed":
        raise ValueError("This operation requires an explicitly reviewed source anchor.")
    scale = Fraction(rate, source_rate)
    exact = {"trim_in": start_trim * scale, "trim_out": end_trim * scale, "source_attack_sample": attack * scale}
    normalized = {key: _nearest_sample(value) for key, value in exact.items()}
    if not normalized["trim_in"] <= normalized["source_attack_sample"] < normalized["trim_out"]:
        raise ValueError("Resampling collapses the retained audio or moves the anchor outside the trim.")
    nominal_start = target + intended_offset_samples - (normalized["source_attack_sample"] - normalized["trim_in"])
    dropped = 0
    if nominal_start < 0:
        if negative_start_policy == "reject":
            raise ValueError("SFX starts before zero; use an explicit trim_start policy to discard pre-roll.")
        dropped = -nominal_start
    effective_trim = normalized["trim_in"] + dropped
    if effective_trim > normalized["source_attack_sample"] or effective_trim >= normalized["trim_out"]:
        raise ValueError("Dropping pre-roll would remove the source attack.")
    position = max(0, nominal_start)
    actual_attack = position + normalized["source_attack_sample"] - effective_trim
    if actual_attack != target + intended_offset_samples:
        raise AssertionError("Internal sample-clock alignment error.")
    sfx = {
        "asset_id": asset["id"], "path": str(path), "sha256": asset["sha256"],
        "sample_rate": rate, "trim_in": effective_trim, "trim_out": normalized["trim_out"],
        "source_attack_sample": normalized["source_attack_sample"],
        "timeline_start_sample": position, "intended_offset_samples": intended_offset_samples,
    }
    return {
        "asset_id": asset["id"], "target_sample": target, "sample_rate": rate,
        "source_clock": {"sample_rate": source_rate, "trim_in": start_trim, "trim_out": end_trim,
                         "source_attack_sample": attack, "origin": "decoded_pcm_sample_zero"},
        "resampled_clock": {**normalized, "sample_rate": rate, "effective_trim_in": effective_trim},
        "quantization": {
            key: {"exact_samples": str(exact[key]), "rounded_samples": normalized[key],
                  "error_samples": str(Fraction(normalized[key]) - exact[key])}
            for key in exact
        },
        "sfx": sfx,
        "anchor_status": anchor_status,
        "anchor_kind": "provided_candidate" if overridden else anchor.get("kind", "unknown"),
        "negative_start_policy": negative_start_policy,
        "discarded_preroll_samples": dropped,
        "actual_attack_sample": actual_attack,
        "alignment_error_samples": 0,
        "alignment_basis": "planned_resampled_anchor",
        "rendered_anchor_verified": False,
        "render_order": ["resample_to_timeline_rate", "trim_in_resampled_samples", "reset_pts", "delay_in_timeline_samples"],
        "audio_filter": (
            f"aresample={rate},atrim=start_sample={effective_trim}:end_sample={normalized['trim_out']},"
            f"asetpts=PTS-STARTPTS,adelay={position}S:all=1"
        ),
        "perceptual_review_performed": False,
    }


def make_editor_cue(spot: dict[str, Any], *, label: str, frame: int, fps: Any,
                    kind: str = "effect", tolerance_frames: Any = "1/2") -> dict[str, Any]:
    """Adapt a spot to editor_policy's common-clock cue contract."""
    name = _text(label, "label")
    target_frame = _int(frame, "frame")
    frame_rate = _ratio(fps, "fps", positive=True)
    tolerance = _ratio(tolerance_frames, "tolerance_frames")
    rate = _int(spot.get("sample_rate"), "sample_rate", 1)
    sample = _int(spot.get("target_sample"), "target_sample")
    if kind not in {"cut", "gesture", "effect", "speech", "title"}:
        raise ValueError("Cue kind is incompatible with editor_policy.")
    deviation = abs(Fraction(sample, rate) * frame_rate - target_frame)
    if deviation > tolerance:
        raise ValueError("Target audio sample does not match the requested cue frame within tolerance.")
    sfx = spot.get("sfx", {})
    if sfx.get("sample_rate") != rate:
        raise ValueError("SFX and cue must share the normalized timeline sample clock.")
    verify_asset(sfx)
    start_trim = _int(sfx.get("trim_in"), "sfx.trim_in")
    end_trim = _int(sfx.get("trim_out"), "sfx.trim_out", 1)
    attack = _int(sfx.get("source_attack_sample"), "sfx.source_attack_sample")
    _int(sfx.get("timeline_start_sample"), "sfx.timeline_start_sample")
    if not start_trim <= attack < end_trim:
        raise ValueError("SFX attack is outside its normalized trim interval.")
    if sfx["timeline_start_sample"] + sfx["source_attack_sample"] - sfx["trim_in"] != sample + sfx["intended_offset_samples"]:
        raise ValueError("SFX spot no longer aligns with its target sample.")
    return {
        "label": name, "kind": kind, "frame": target_frame, "sample_rate": rate,
        "audio_sample": sample, "tolerance_frames": str(tolerance), "sfx": dict(sfx),
        "source_clock": dict(spot["source_clock"]),
        "anchor_status": spot["anchor_status"], "perceptual_review_performed": False,
    }


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("probe", help="Inspect dependency presence without loading CLAP.")
    indexing = commands.add_parser("index", help="Index explicit files; --semantic uses already cached CLAP.")
    indexing.add_argument("files", nargs="*", type=Path)
    indexing.add_argument("--catalog", type=Path)
    indexing.add_argument("--output", type=Path, required=True)
    indexing.add_argument("--semantic", action="store_true")
    indexing.add_argument("--model-id", default=DEFAULT_MODEL)
    indexing.add_argument("--checkpoint", default="main")
    retrieval = commands.add_parser("search", help="Retrieve actual embeddings; no keyword fallback.")
    retrieval.add_argument("index", type=Path)
    queries = retrieval.add_mutually_exclusive_group(required=True)
    queries.add_argument("--query")
    queries.add_argument("--query-embedding", type=Path)
    retrieval.add_argument("--model-id")
    retrieval.add_argument("--checkpoint")
    retrieval.add_argument("--top-k", type=int, default=5)
    retrieval.add_argument("--kind", action="append")
    spotting = commands.add_parser("spot", help="Place an SFX in explicit source and timeline clocks.")
    spotting.add_argument("index", type=Path)
    spotting.add_argument("--asset", required=True)
    spotting.add_argument("--target-sample", type=int, required=True)
    spotting.add_argument("--timeline-sample-rate", type=int, required=True)
    spotting.add_argument("--trim-in", type=int, default=0)
    spotting.add_argument("--trim-out", type=int)
    spotting.add_argument("--source-attack-sample", type=int)
    spotting.add_argument("--intended-offset-samples", type=int, default=0)
    spotting.add_argument("--negative-start-policy", choices=("reject", "trim_start"), default="reject")
    spotting.add_argument("--require-reviewed-anchor", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "probe":
            result = probe_backend()
        elif args.command == "index":
            if bool(args.files) == bool(args.catalog):
                raise ValueError("Provide files or --catalog, exclusively.")
            specs = _read(args.catalog) if args.catalog else args.files
            encoder = ClapEncoder(args.model_id, args.checkpoint) if args.semantic else None
            result = index_audio_assets(specs, encoder=encoder)
            output = args.output.resolve()
            if output in {Path(asset["path"]) for asset in result["assets"]} or (args.catalog and output == args.catalog.resolve()):
                raise ValueError("Index output must not overwrite original audio or input catalog.")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            result = {"status": result["status"], "semantic_search": result["semantic_search"],
                      "assets": len(result["assets"]), "output": str(output),
                      "clap_inference_executed": result["clap_inference_executed"]}
        elif args.command == "search":
            result = search(_read(args.index), query=args.query,
                            query_embedding=_read(args.query_embedding) if args.query_embedding else None,
                            model_id=args.model_id, checkpoint=args.checkpoint,
                            top_k=args.top_k, kinds=args.kind)
        else:
            assets, _ = _validate_index(_read(args.index), embeddings=False)
            selected = next((asset for asset in assets if asset["id"] == args.asset), None)
            if selected is None:
                raise ValueError("Unknown audio asset ID.")
            result = spot_sfx(selected, target_sample=args.target_sample, timeline_sample_rate=args.timeline_sample_rate,
                              trim_in=args.trim_in, trim_out=args.trim_out, source_attack_sample=args.source_attack_sample,
                              intended_offset_samples=args.intended_offset_samples, negative_start_policy=args.negative_start_policy,
                              require_reviewed_anchor=args.require_reviewed_anchor)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except SemanticAudioUnavailable as error:
        print(json.dumps({"status": "unavailable", "reason": str(error), "semantic_fallback": False}))
        return 3
    except (ValueError, TypeError, KeyError, OSError) as error:
        print(json.dumps({"status": "error", "reason": str(error), "semantic_fallback": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
