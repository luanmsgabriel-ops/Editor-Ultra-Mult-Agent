#!/usr/bin/env python3
"""Propor ataques por banda e gerar uma curva de energia RMS da mídia local."""
import argparse
import csv
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np


SAMPLE_RATE = 48000
CHANNELS = 2
HOP = 240
FFT_SIZE = 1024
RMS_WINDOW = 19200
RMS_HOP = 2400
BANDS = (("grave", 35, 180), ("medio", 180, 2000), ("agudo", 2000, 10000))


def audio_origin(path, stream):
    """Return an informational source time. The main clock starts at sample 0."""
    stream_id = f"a:{stream}"
    args = ["ffprobe", "-v", "error", "-select_streams", stream_id,
            "-show_entries", "stream=start_time:format=start_time",
            "-of", "json", str(path)]
    metadata = json.loads(subprocess.check_output(args))
    sources = metadata.get("streams", [])
    if not sources:
        raise ValueError(f"Faixa de áudio {stream_id} não encontrada.")
    args = ["ffprobe", "-v", "error", "-select_streams", stream_id,
            "-read_intervals", "%+#32", "-show_frames",
            "-show_entries", "frame=best_effort_timestamp_time",
            "-of", "json", str(path)]
    frames = json.loads(subprocess.check_output(args)).get("frames", [])
    first_pts = next((f["best_effort_timestamp_time"] for f in frames
                      if "best_effort_timestamp_time" in f), None)
    return {"primeiro_frame_audio_pts_s": first_pts,
            "inicio_stream_s": sources[0].get("start_time"),
            "inicio_container_s": metadata.get("format", {}).get("start_time")}


def padded_windows(audio, centers, window):
    half = window // 2
    indexes = centers[:, None] + np.arange(-half, half)
    valid = (indexes >= 0) & (indexes < len(audio))
    return np.where(valid[..., None], audio[indexes.clip(0, len(audio) - 1)], 0)


def batches(centers, size=128):
    return (centers[i:i + size] for i in range(0, len(centers), size))


def band_flux(audio, centers):
    """Positive log spectral flux in each band. Window time uses its centre."""
    freq = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
    selections = [(freq >= low) & (freq < high) for _, low, high in BANDS]
    window = np.hanning(FFT_SIZE)
    previous = np.zeros(len(freq))
    flux = []
    for group in batches(centers):
        block = padded_windows(audio, group, FFT_SIZE) * window[None, :, None]
        spectrum = np.fft.rfft(block, axis=1) / (window.sum() / 2)
        # Taking the channel maximum prevents opposite-phase stereo from cancelling.
        log_magnitude = np.log1p(1000 * abs(spectrum).max(axis=2))
        rises = np.maximum(0, np.diff(log_magnitude, axis=0,
                                      prepend=previous[None, :]))
        flux.append(np.column_stack([rises[:, selection].mean(axis=1)
                                     for selection in selections]))
        previous = log_magnitude[-1]
    return np.concatenate(flux, axis=0)


def select_peaks(values, separation):
    median = np.median(values)
    deviation = np.median(abs(values - median))
    threshold = max(median + 4 * deviation, 0.02)
    left = np.r_[-np.inf, values[:-1]]
    right = np.r_[values[1:], -np.inf]
    peaks = np.flatnonzero((values >= threshold) & (values > left) & (values >= right))
    claimed = np.zeros(len(values), dtype=bool)
    selected = []
    for peak in peaks[np.argsort(-values[peaks], kind="stable")]:
        if not claimed[peak]:
            selected.append(peak)
            claimed[max(0, peak - separation + 1):peak + separation] = True
    return sorted(selected)


def write_attacks(output, audio, min_separation):
    centers = np.arange(0, len(audio), HOP)
    flux = band_flux(audio, centers)
    events = []
    for col, (band, _, _) in enumerate(BANDS):
        events.extend((int(centers[i]), band, float(flux[i, col]))
                      for i in select_peaks(flux[:, col], min_separation))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["amostra_candidata", "tempo_relativo_s", "banda", "fluxo_log_positivo"])
        for sample, band, strength in sorted(events):
            writer.writerow([sample, f"{sample / SAMPLE_RATE:.6f}", band, f"{strength:.6f}"])


def write_rms(output, audio):
    centers = np.arange(0, len(audio), RMS_HOP)
    # RMS windows are reused for overlap by prefix sums, processing one channel
    # at a time to avoid holding an array of all overlapping samples.
    left = (centers - RMS_WINDOW // 2).clip(0, len(audio))
    right = (centers + RMS_WINDOW // 2).clip(0, len(audio))
    channel_power = np.zeros(len(centers))
    for col in range(CHANNELS):
        prefix = np.empty(len(audio) + 1)
        prefix[0] = 0
        # 12-second chunks keep the working allocation modest.
        for start in range(0, len(audio), SAMPLE_RATE * 12):
            end = min(len(audio), start + SAMPLE_RATE * 12)
            square = np.square(audio[start:end, col], dtype=np.float64)
            prefix[start + 1:end + 1] = np.cumsum(square) + prefix[start]
        channel_power += (prefix[right] - prefix[left]) / (right - left)
    rms_db = 10 * np.log10(np.maximum(channel_power / CHANNELS, 1e-12))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["amostra_centro", "tempo_relativo_s", "rms_dbfs"])
        for sample, level in zip(centers, rms_db):
            writer.writerow([int(sample), f"{sample / SAMPLE_RATE:.6f}", f"{level:.4f}"])


def analyze(path, output, stream, min_separation_ms):
    timing = audio_origin(path, stream)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="spotting-") as directory:
        pcm = Path(directory) / "audio.pcm"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y",
                        "-i", str(path), "-map", f"0:a:{stream}",
                        "-vn", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE),
                        "-c:a", "pcm_f32le", "-f", "f32le", str(pcm)], check=True)
        samples = pcm.stat().st_size // (4 * CHANNELS)
        if not samples:
            raise ValueError("A faixa selecionada foi decodificada sem amostras.")
        audio = np.memmap(pcm, mode="r", dtype="<f4", shape=(samples, CHANNELS))
        write_attacks(output / "ataques.csv", audio,
                      max(1, round(min_separation_ms * SAMPLE_RATE / (1000 * HOP))))
        write_rms(output / "curva-rms.csv", audio)
        del audio
    metadata = {
        "arquivo": str(path), "faixa_audio": stream, "taxa_hz": SAMPLE_RATE,
        "canais_analisados": CHANNELS, "amostras_por_canal": samples,
        "tempo_relativo": "Zero no início do PCM decodificado; somar offset de edição separadamente.",
        "tempos_da_fonte_informativos": timing,
        "limites_relogio": "Verificar PTS e continuidade se houver gaps, edit lists, VFR ou offset A/V.",
        "janela_fft_amostras": FFT_SIZE, "passo_fft_amostras": HOP,
        "centro_janela": True, "passo_grid_fft_ms": 1000 * HOP / SAMPLE_RATE,
        "janela_fft_ms": 1000 * FFT_SIZE / SAMPLE_RATE,
        "bandas_hz": {name: [low, high] for name, low, high in BANDS},
        "janela_rms_amostras": RMS_WINDOW, "passo_rms_amostras": RMS_HOP,
        "separacao_minima_por_banda_ms": min_separation_ms,
        "nota": "Picos de fluxo são candidatos de transiente, não batidas, compassos ou pontos aprovados. "
                "O passo do grid não é garantia de precisão perceptual. RMS não é LUFS.",
    }
    (output / "metadados.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("midia", type=Path)
    parser.add_argument("--saida", required=True, type=Path)
    parser.add_argument("--faixa", type=int, default=0, help="Índice da faixa de áudio, a partir de zero.")
    parser.add_argument("--separacao-ms", type=float, default=65)
    args = parser.parse_args()
    if args.faixa < 0 or args.separacao_ms <= 0:
        parser.error("Faixa deve ser não negativa e separação deve ser positiva.")
    try:
        analyze(args.midia, args.saida, args.faixa, args.separacao_ms)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Falha: {error}\n")


if __name__ == "__main__":
    main()
