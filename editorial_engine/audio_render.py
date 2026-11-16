"""Execute preselected SFX cues against a validated native video timeline.

This module makes no editorial selections. The caller must validate its plan
before passing cues. Source and rendered video clocks are checked frame by
frame. The rendered image stream is copied; original audio and SFX are mixed
in an explicit PCM clock before delivery encoding. Technical checks do not
establish perceived synchronization, intelligibility, or aesthetic approval.
"""

from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import numpy as np

from audiovisual.semantic_audio import spot_sfx, verify_asset


HEADROOM_DB = -6.0
LIMITER = {"limit": 0.89125094, "attack_ms": 5, "release_ms": 50,
           "automatic_level": False, "latency_compensated": True}
DUCKING = {"threshold": 0.0316227766, "ratio": 8, "attack_ms": 5,
           "release_ms": 120, "knee": 2.82843, "detection": "rms",
           "makeup": 1, "source": "original_audio_mix"}


class AudioRenderError(ValueError):
    """A controlled validation, decoding, or FFmpeg execution failure."""


def _whole(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise AudioRenderError(f"{label} must be an integer >= {minimum}.")
    return value


def _fraction(value: Any, label: str) -> Fraction:
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError) as error:
        raise AudioRenderError(f"Invalid {label}: {value!r}.") from error
    return result


def _round(value: Fraction) -> int:
    quotient, remainder = divmod(value.numerator, value.denominator)
    return quotient + int(remainder * 2 >= value.denominator)


def _hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise AudioRenderError(f"Required executable is unavailable: {name}.")
    return executable


def _run(arguments: list[str]) -> bytes:
    try:
        result = subprocess.run(arguments, capture_output=True, check=True, timeout=300)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace")[-2000:].strip()
        raise AudioRenderError(f"Audio render command failed: {detail}") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AudioRenderError(f"Audio render command could not complete: {error}") from error
    return result.stdout


def _probe(path: Path) -> dict[str, Any]:
    output = _run([
        _tool("ffprobe"), "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,sample_rate,channels,time_base,start_pts,start_time,duration_ts,duration,avg_frame_rate,width,height:format=duration,start_time",
        "-of", "json", str(path),
    ])
    try:
        return json.loads(output)
    except (ValueError, UnicodeError) as error:
        raise AudioRenderError("FFprobe returned invalid metadata.") from error


def _frames(path: Path, selector: str) -> list[dict[str, Any]]:
    output = _run([
        _tool("ffprobe"), "-v", "error", "-select_streams", selector, "-show_frames",
        "-show_entries", "frame=best_effort_timestamp,pkt_duration,duration,nb_samples",
        "-of", "json", str(path),
    ])
    try:
        return json.loads(output).get("frames", [])
    except (ValueError, UnicodeError) as error:
        raise AudioRenderError("FFprobe returned invalid frame timestamps.") from error


def _video_clock(path: Path, probe: dict[str, Any]) -> dict[str, Any]:
    stream = next((row for row in probe.get("streams", []) if row.get("codec_type") == "video"), None)
    if stream is None:
        raise AudioRenderError(f"No video stream: {path.name}.")
    time_base = _fraction(stream.get("time_base"), "video time_base")
    if time_base <= 0:
        raise AudioRenderError("Video time_base must be positive.")
    frames = _frames(path, "v:0")
    if not frames:
        raise AudioRenderError("Video has no decodable frames.")
    try:
        timestamps = [int(frame["best_effort_timestamp"]) * time_base for frame in frames]
    except (KeyError, ValueError, TypeError) as error:
        raise AudioRenderError("Every video frame needs a valid presentation timestamp.") from error
    if any(later <= earlier for earlier, later in zip(timestamps, timestamps[1:])):
        raise AudioRenderError("Video frame timestamps are not strictly increasing.")
    fps = _fraction(stream.get("avg_frame_rate"), "video frame rate")
    if fps <= 0:
        raise AudioRenderError("Video average frame rate is unavailable.")
    last_duration = frames[-1].get("duration", frames[-1].get("pkt_duration"))
    if last_duration is None or int(last_duration) <= 0:
        # A missing final duration is safe only when a CFR cadence is evidenced.
        if len(timestamps) < 2 or any(b - a != 1 / fps for a, b in zip(timestamps, timestamps[1:])):
            raise AudioRenderError("Cannot establish the last video frame duration.")
        last_duration_s = 1 / fps
        last_duration_source = "verified_constant_frame_rate"
    else:
        last_duration_s = int(last_duration) * time_base
        last_duration_source = "decoded_frame_metadata"
    duration = timestamps[-1] + last_duration_s - timestamps[0]
    signature = hashlib.sha256(json.dumps([str(value) for value in timestamps], separators=(",", ":")).encode()).hexdigest()
    return {
        "timestamps": timestamps, "origin": timestamps[0], "duration": duration,
        "summary": {
            "frame_count": len(frames), "average_fps": str(fps), "time_base": str(time_base),
            "start_seconds": str(timestamps[0]), "duration_seconds": str(duration),
            "last_frame_duration_seconds": str(last_duration_s),
            "last_frame_duration_source": last_duration_source, "timestamps_sha256": signature,
            "width": stream.get("width"), "height": stream.get("height"), "codec": stream.get("codec_name"),
        },
    }


def _same_clock(left: dict[str, Any], right: dict[str, Any], label: str) -> None:
    if left["timestamps"] != right["timestamps"] or left["duration"] != right["duration"]:
        raise AudioRenderError(f"{label}: frame presentation times or durations differ; retiming needs an explicit edit map.")


def _audio_clock(path: Path, probe: dict[str, Any]) -> dict[str, Any] | None:
    stream = next((row for row in probe.get("streams", []) if row.get("codec_type") == "audio"), None)
    if stream is None:
        return None
    rate = _whole(int(stream.get("sample_rate", 0)), "original audio sample_rate", 1)
    time_base = _fraction(stream.get("time_base"), "audio time_base")
    if time_base <= 0:
        raise AudioRenderError("Audio time_base must be positive.")
    frames = _frames(path, "a:0")
    if not frames:
        raise AudioRenderError("Original audio stream has no decodable samples.")
    previous_end = None
    total_samples = 0
    origin = None
    for frame in frames:
        try:
            timestamp = int(frame["best_effort_timestamp"]) * time_base
            count = _whole(frame["nb_samples"], "decoded audio frame samples", 1)
        except (KeyError, TypeError, ValueError) as error:
            raise AudioRenderError("Original audio needs timed, decodable sample frames.") from error
        if previous_end is not None and abs(timestamp - previous_end) > Fraction(1, rate):
            raise AudioRenderError("Original audio has timestamp gaps or overlaps; no silent flattening is performed.")
        if origin is None:
            origin = timestamp
        previous_end = timestamp + Fraction(count, rate)
        total_samples += count
    return {"sample_rate": rate, "origin": origin, "sample_count": total_samples,
            "channels": stream.get("channels"), "codec": stream.get("codec_name")}


def _video_packets(path: Path) -> list[str]:
    data = json.loads(_run([
        _tool("ffprobe"), "-v", "error", "-select_streams", "v:0", "-show_packets",
        "-show_data_hash", "sha256", "-show_entries", "packet=data_hash", "-of", "json", str(path),
    ]))
    hashes = [packet.get("data_hash") for packet in data.get("packets", [])]
    if not hashes or any(not isinstance(value, str) or not value.startswith("SHA256:") for value in hashes):
        raise AudioRenderError("Could not fingerprint the rendered video packets.")
    return hashes


def _pcm_measure(path: Path, rate: int) -> dict[str, Any]:
    raw = _run([
        _tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-vn", "-ac", "2", "-ar", str(rate),
        "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1",
    ])
    if not raw or len(raw) % 8:
        raise AudioRenderError("Mixed audio did not decode to complete stereo PCM samples.")
    samples = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    if not np.isfinite(samples).all():
        raise AudioRenderError("Mixed audio contains nonfinite samples.")
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return {"sample_rate": rate, "channels": 2, "sample_count": len(samples),
            "pcm_sha256": hashlib.sha256(raw).hexdigest(), "sample_peak": peak,
            "sample_peak_dbfs": 20 * math.log10(peak) if peak else None,
            "rms_dbfs": 20 * math.log10(rms) if rms else None,
            "loudness_lufs_measured": False, "true_peak_measured": False}


def mix_sfx(source_video: str | Path, rendered_video: str | Path, output_path: str | Path,
            cues: list[dict[str, Any]], *, sample_rate: int = 48000) -> dict[str, Any]:
    """Mix only supplied cues; caller is responsible for prior editorial validation.

    Cue fields: id, indexed asset, target_sample; optional trim_in/trim_out,
    source_attack_sample, gain_db (finite and <= 0), intended_offset_samples,
    negative_start_policy, require_reviewed_anchor (default True). Source trim
    fields use the asset's PCM rate. Targets use ``sample_rate``. Tails must fit
    the video; trim_out is required to shorten a cue that would overrun it.

    MP4 delivery uses AAC; MOV/MKV use PCM. Sample-exact spotting is verified in
    the pre-encode PCM clock. AAC padding is measured separately, never hidden.
    """
    rate = _whole(sample_rate, "sample_rate", 1)
    if not isinstance(cues, list):
        raise AudioRenderError("cues must be a list already selected by a validated plan.")
    source = Path(source_video).resolve()
    rendered = Path(rendered_video).resolve()
    destination = Path(output_path).resolve()
    if not source.is_file() or not rendered.is_file():
        raise AudioRenderError("Source and rendered videos must exist.")
    if destination.suffix.lower() not in {".mp4", ".mov", ".mkv"}:
        raise AudioRenderError("Audio delivery supports MP4, MOV, or MKV output.")
    protected = [source, rendered]
    for cue in cues:
        if not isinstance(cue, dict) or not isinstance(cue.get("asset"), dict):
            raise AudioRenderError("Every cue must contain an indexed asset object.")
        protected.append(verify_asset(cue["asset"]).resolve())
    for path in protected:
        if destination == path or (destination.exists() and os.path.samefile(destination, path)):
            raise AudioRenderError("Output must not overwrite any video or audio input.")
    source_hash, rendered_hash = _hash(source), _hash(rendered)
    source_probe, rendered_probe = _probe(source), _probe(rendered)
    source_clock = _video_clock(source, source_probe)
    rendered_clock = _video_clock(rendered, rendered_probe)
    _same_clock(source_clock, rendered_clock, "Source/render clock mismatch")
    original = _audio_clock(source, source_probe)
    exact_samples = source_clock["duration"] * rate
    total_samples = _round(exact_samples)
    if total_samples <= 0:
        raise AudioRenderError("Video duration has no audio samples at the requested rate.")
    if source_clock["origin"] < 0:
        raise AudioRenderError("Negative video origin requires an explicit upstream clock normalization.")
    selections = []
    identifiers = set()
    for cue in cues:
        identifier = cue.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers:
            raise AudioRenderError("Cue IDs must be nonempty and unique.")
        identifiers.add(identifier)
        gain = cue.get("gain_db", 0)
        if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not math.isfinite(gain) or not -120 <= gain <= 0:
            raise AudioRenderError("Cue gain_db must be finite and between -120 and 0 dB.")
        reviewed = cue.get("require_reviewed_anchor", True)
        if type(reviewed) is not bool:
            raise AudioRenderError("require_reviewed_anchor must be boolean.")
        override = cue.get("source_attack_sample")
        anchor = cue["asset"].get("anchor", {})
        # Repeating an already reviewed marker does not create a new marker.
        if override == anchor.get("sample") and anchor.get("status") == "reviewed":
            override = None
        spot = spot_sfx(
            cue["asset"], target_sample=cue.get("target_sample"), timeline_sample_rate=rate,
            trim_in=cue.get("trim_in", 0), trim_out=cue.get("trim_out"), source_attack_sample=override,
            intended_offset_samples=cue.get("intended_offset_samples", 0),
            negative_start_policy=cue.get("negative_start_policy", "reject"),
            require_reviewed_anchor=reviewed,
        )
        sfx = spot["sfx"]
        if spot["actual_attack_sample"] >= total_samples:
            raise AudioRenderError(f"Cue {identifier}: attack is outside the video.")
        tail_end = sfx["timeline_start_sample"] + sfx["trim_out"] - sfx["trim_in"]
        if tail_end > total_samples:
            raise AudioRenderError(f"Cue {identifier}: audio tail exceeds video duration; provide trim_out explicitly.")
        selections.append({"id": identifier, "gain_db": float(gain), "spot": spot})
    packet_hashes = _video_packets(rendered)
    offset_exact = (original["origin"] - source_clock["origin"]) * rate if original else Fraction(0)
    offset_samples = _round(offset_exact)
    common = f"aformat=sample_fmts=fltp:sample_rates={rate}:channel_layouts=stereo"
    finish = f"apad=whole_len={total_samples},atrim=end_sample={total_samples}"
    filters = []
    if original:
        original_chain = f"[0:a:0]aresample={rate},{common},asetpts=PTS-STARTPTS"
        if offset_samples < 0:
            original_chain += f",atrim=start_sample={-offset_samples},asetpts=PTS-STARTPTS"
        elif offset_samples > 0:
            original_chain += f",adelay={offset_samples}S:all=1"
        original_chain += f",{finish}[original]"
    else:
        original_chain = f"anullsrc=r={rate}:cl=stereo,{finish}[original]"
    filters.append(original_chain)
    for position, entry in enumerate(selections, 1):
        filters.append(
            f"[{position}:a:0]{entry['spot']['audio_filter']},{common},"
            f"volume={entry['gain_db']:.12g}dB,{finish}[sfx{position}]"
        )
    duck_enabled = bool(original and selections)
    if selections:
        labels = "".join(f"[sfx{position}]" for position in range(1, len(selections) + 1))
        filters.append(f"{labels}amix=inputs={len(selections)}:duration=longest:dropout_transition=0:normalize=0[sfxbus]")
        if duck_enabled:
            filters.append("[original]asplit=2[originalmix][controller]")
            filters.append(
                "[sfxbus][controller]sidechaincompress=threshold=0.0316227766:ratio=8:"
                "attack=5:release=120:knee=2.82843:detection=rms:makeup=1:mix=1[ducked]"
            )
            mix_inputs = "[originalmix][ducked]"
        else:
            mix_inputs = "[original][sfxbus]"
        filters.append(f"{mix_inputs}amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[combined]")
        mixed_label = "combined"
    else:
        mixed_label = "original"
    filters.append(
        f"[{mixed_label}]volume={HEADROOM_DB}dB,alimiter=limit=0.89125094:attack=5:release=50:"
        f"level=false:latency=true,{finish}[mix]"
    )
    filter_graph = ";".join(filters)
    codec = "aac" if destination.suffix.lower() == ".mp4" else "pcm_s24le"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="editorial-audio-", dir=destination.parent) as temporary:
        work = Path(temporary)
        mixed_pcm = work / "mix.wav"
        encoded = work / ("delivery" + destination.suffix.lower())
        command = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(source)]
        for cue in cues:
            command += ["-i", str(Path(cue["asset"]["path"]).resolve())]
        command += ["-filter_complex", filter_graph, "-map", "[mix]", "-vn", "-sn", "-dn",
                    "-ar", str(rate), "-ac", "2", "-c:a", "pcm_f32le", str(mixed_pcm)]
        _run(command)
        pcm_metrics = _pcm_measure(mixed_pcm, rate)
        if pcm_metrics["sample_count"] != total_samples:
            raise AudioRenderError("PCM mix duration does not match the planned sample count.")
        if pcm_metrics["sample_peak"] > LIMITER["limit"] + 1e-5:
            raise AudioRenderError("PCM sample peak exceeds the configured limiter ceiling.")
        mux = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y", "-copyts",
               "-i", str(rendered), "-i", str(mixed_pcm), "-map", "0:v:0", "-map", "1:a:0",
               "-map_metadata", "0", "-map_chapters", "-1", "-c:v", "copy", "-c:a", codec,
               "-ar", str(rate), "-ac", "2", "-avoid_negative_ts", "disabled"]
        if source_clock["origin"]:
            origin = source_clock["origin"]
            mux += ["-af", f"asetpts=PTS+({origin.numerator}/{origin.denominator})/TB"]
        if codec == "aac":
            mux += ["-b:a", "192k"]
        if destination.suffix.lower() in {".mp4", ".mov"}:
            mux += ["-movflags", "+faststart"]
        mux.append(str(encoded))
        _run(mux)
        final_probe = _probe(encoded)
        final_clock = _video_clock(encoded, final_probe)
        _same_clock(rendered_clock, final_clock, "Encoded output clock mismatch")
        if _video_packets(encoded) != packet_hashes:
            raise AudioRenderError("Output video packets differ despite stream-copy mode.")
        final_audio = _audio_clock(encoded, final_probe)
        if final_audio is None or abs(final_audio["origin"] - source_clock["origin"]) > Fraction(1, rate):
            raise AudioRenderError("Encoded audio start does not match the video clock.")
        final_pcm = _pcm_measure(encoded, rate)
        if codec != "aac" and final_pcm["sample_count"] != total_samples:
            raise AudioRenderError("Lossless output changed the audio sample count.")
        if final_pcm["sample_peak"] > 1.0 + 1e-5:
            raise AudioRenderError("Encoded audio exceeds full-scale sample peaks; lower cue gains before delivery.")
        _run([_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-i", str(encoded),
              "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"])
        if _hash(source) != source_hash or _hash(rendered) != rendered_hash:
            raise AudioRenderError("Video inputs changed during audio rendering.")
        for cue in cues:
            verify_asset(cue["asset"])
        output_hash = _hash(encoded)
        os.replace(encoded, destination)
    return {
        "schema_version": "1.0", "status": "rendered", "output_path": str(destination),
        "output_sha256": output_hash,
        "source_video": {"path": str(source), "sha256": source_hash, **source_clock["summary"]},
        "rendered_video": {"path": str(rendered), "sha256": rendered_hash, **rendered_clock["summary"]},
        "timeline": {"sample_rate": rate, "sample_count": total_samples,
                     "exact_duration_samples": str(exact_samples),
                     "duration_quantization_error_samples": str(Fraction(total_samples) - exact_samples)},
        "original_audio": {
            "included": original is not None,
            "sample_rate": original["sample_rate"] if original else None,
            "channels": original["channels"] if original else None,
            "offset_exact_samples": str(offset_exact), "offset_samples": offset_samples,
            "offset_quantization_error_samples": str(Fraction(offset_samples) - offset_exact),
            "voice_isolated": False,
        },
        "cues": selections, "selection_performed": False,
        "editorial_plan_validation": "caller_responsibility",
        "headroom_db": HEADROOM_DB, "limiter": dict(LIMITER),
        "ducking": {"enabled": duck_enabled, **DUCKING,
                    "limitation": "The controller is the original mix, which may contain music; it is not isolated speech."},
        "filter_graph": filter_graph,
        "pcm_mix": pcm_metrics,
        "delivery_audio": {"codec": codec, **final_pcm,
                           "padding_samples_after_decode": final_pcm["sample_count"] - total_samples,
                           "sample_exact_claim": "preencode_pcm_clock_only" if codec == "aac" else "lossless_pcm_clock"},
        "technical_checks": {"source_render_timeline_match": True, "output_timeline_match": True,
                             "video_packets_identical": True, "output_decodes": True,
                             "indexed_asset_hashes_verified": True, "pcm_sample_count_matches": True,
                             "sample_peak_within_limiter_ceiling": True,
                             "limiter_ceiling_check_stage": "preencode_pcm",
                             "encoded_sample_peaks_below_full_scale": True},
        "perceptual_review_performed": False, "speech_intelligibility": "not_assessed",
        "sfx_synchronization_listened": False,
    }
