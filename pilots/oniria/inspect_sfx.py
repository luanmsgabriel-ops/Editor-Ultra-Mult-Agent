"""Meça duração decodificada, pico RMS e envelope acústico dos candidatos."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import numpy as np

RATE = 48_000

def read(path, af=None):
    filters = ["-af", af] if af else []
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
                                   *filters, "-f", "f32le", "-ar", str(RATE), "-ac", "2", "-"])
    return np.frombuffer(raw, dtype=np.float32).reshape((-1, 2))

def envelope(sound, window=0.02):
    step = round(window * RATE)
    starts = np.arange(0, len(sound), step)
    power = np.add.reduceat((sound.astype(np.float64)**2).mean(axis=1), starts)
    counts = np.diff([*starts, len(sound)])
    return (starts + counts/2)/RATE, np.sqrt(power/counts)

def stats(path):
    sound = read(path)
    ts, powers = envelope(sound)
    peak = int(np.argmax(powers))
    edge = np.where(powers > powers[peak]*10**(-24/20))[0]
    if not edge.size:
        edge = [peak]
    return {
        "id": path.stem, "duration_s": len(sound)/RATE,
        "sha256": sha256(path.read_bytes()).hexdigest(),
        "apex_s": float(ts[peak]), "first_signal_s": float(ts[edge[0]]),
        "last_signal_s": float(ts[edge[-1]]),
        "peaks": [[round(float(ts[k]),2), round(float(powers[k]/powers[peak]),2)]
                  for k in sorted(np.argpartition(-powers, 7)[:7])],
    }

if __name__ == "__main__":
    root = Path("/tmp/editor-ultra-media")
    names = {r["id"]: r for p in root.glob("catalog-*.json") for r in json.loads(p.read_text())}
    local_files = sorted((root/"files").glob("*.mp3"))
    with ThreadPoolExecutor(4) as ex:
        all_stats = list(ex.map(stats,local_files))
    for s in all_stats:
        s.update({key: names[s["id"]][key] for key in ("name", "root_id", "license_status", "url")})
        print(s["name"], round(s["duration_s"],3), s["first_signal_s"], s["apex_s"], s["last_signal_s"], s["peaks"])
    Path(__file__).with_name("Analise-Candidatos.json").write_text(json.dumps(all_stats,ensure_ascii=False,indent=2)+"\n")
