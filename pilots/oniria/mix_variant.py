"""Componha a faixa SFX da revisão A/B em amostras de PCM, sem alterar a base."""
from argparse import ArgumentParser
from pathlib import Path
import json
import subprocess

import numpy as np

from .inspect_sfx import envelope, read, RATE

FRAMES = 700
FPS = 24
LENGTH = FRAMES * RATE // FPS


def sample(second):
    return round(second * RATE)


def rms(arr):
    return float(np.sqrt(np.mean(arr.astype(np.float64) ** 2)))


def db(value):
    return 20 * np.log10(max(1e-12, value))


def wav(path, pcm):
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "f32le",
                    "-ar", str(RATE), "-ac", "2", "-i", "pipe:0", "-c:a", "pcm_s24le", str(path)],
                   input=np.asarray(pcm, dtype="<f4").tobytes(), check=True)


def effect(cue, base, path):
    source = read(path, cue["filter"])
    lo, hi = (sample(s) for s in cue["source_range_s"])
    selected = source[lo:hi].copy()
    if len(selected) != hi-lo:
        raise ValueError(f"Corte fora do arquivo de áudio: {path}")
    times, env = envelope(selected, window=.01)
    if cue["anchor_type"] == "max_rms_10ms":
        apex = int(np.argmax(env))
    else:
        apex = int(np.argmax(np.diff(env, prepend=0)))
    anchor_on_effect = sample(times[apex])
    anchor_on_timeline = cue["sequence_frame"] * (RATE//FPS)
    start = anchor_on_timeline - anchor_on_effect
    end = start + len(selected)
    if start < 0 or end > LENGTH:
        raise ValueError("O efeito excede a tradução válida da timeline.")
    in_fade, out_fade = (sample(s) for s in cue["fade_s"])
    selected[:in_fade] *= np.linspace(0, 1, in_fade, dtype=np.float32)[:, None]
    selected[-out_fade:] *= np.linspace(1, 0, out_fade, dtype=np.float32)[:, None]
    gain = rms(base[start:end]) * 10**(cue["target_rms_vs_bed_db"]/20) / rms(selected)
    placed = selected * gain
    result = cue | {
        "sequence_s": anchor_on_timeline / RATE, "sequence_anchor_sample": anchor_on_timeline,
        "source_anchor_s": (lo + anchor_on_effect) / RATE,
        "rendered_in_s": start / RATE, "rendered_out_s": end / RATE,
        "gain_db_after_filter": round(float(db(gain)),3),
        "rms_vs_bed_db": round(float(db(rms(placed)/rms(base[start:end]))),3),
    }
    return start, end, placed, result


def main():
    p = ArgumentParser(description=__doc__)
    p.add_argument("--base", type=Path, required=True)
    p.add_argument("--cues", type=Path, required=True)
    p.add_argument("--assets", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    base = read(args.base)
    if len(base) != LENGTH:
        raise ValueError(f"Esperava {LENGTH} amostras e recebi {len(base)}.")
    data = json.loads(args.cues.read_text())
    stem = np.zeros_like(base)
    detail = []
    for cue in data["cues"]:
        if cue["root_id"] not in data["allowed_roots"] or cue["source"] != "drive":
            raise ValueError(f"Asset fora das pastas autorizadas: {cue['id']}")
        start, end, placed, result = effect(cue, base, args.assets/f"{cue['id']}.mp3")
        if start < sample(24.75) and end > sample(21.1):
            raise ValueError("Efeito colide com a janela protegida de locução.")
        stem[start:end] += placed
        detail.append(result)
    master = base + stem
    peak = float(np.max(np.abs(master)))
    if peak > .86:
        raise ValueError(f"Pico de {db(peak):.2f} dBFS acima da folga desejada.")
    wav(args.out/"Mix-Variante.wav", master)
    wav(args.out/"Stem-SFX.wav", stem)
    records = data | {
        "mode": "preview",
        "baseline": "Mix original do Oníria — PYTI instrumental e locução. Mantido para comparar os efeitos.",
        "rate": RATE, "sample_count": LENGTH, "peak_dbfs": round(float(db(peak)),3),
        "global_rms_delta_db": round(float(db(rms(master)/rms(base))),4),
        "cues": detail,
    }
    (args.out/"Cues-Realizados.json").write_text(json.dumps(records,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    main()
