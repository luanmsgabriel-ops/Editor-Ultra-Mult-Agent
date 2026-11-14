"""Recriar os 38 cortes em cor nativa, importar o letreiro e queimar as legendas."""
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
FPS = 24
FRAMES = 700
COLOR = ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv"]
ENCODE = ["-c:v", "libx264", "-threads", "3", "-preset", "fast", "-crf", "17", "-bf", "0",
          "-pix_fmt", "yuv420p", "-video_track_timescale", "24000", *COLOR]


def run(*args, cwd=None):
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
                    *map(str, args)], cwd=cwd, check=True)


def shot(index, row, sources, stage, workdir):
    length = row["end"] - row["start"]
    is_stage = row["stage_composite"]
    source = stage if is_stage else sources / f"{row['id']}.mp4"
    vf = ["setpts=PTS-STARTPTS", "setsar=1"]
    if not is_stage:
        vf.append("zscale=matrixin=170m:transferin=iec61966-2-1:primariesin=709:rangein=limited:"
                  "matrix=709:transfer=709:primaries=709:range=limited")
    vf += ["scale=1080:1920:flags=lanczos:in_color_matrix=bt709:out_color_matrix=bt709", "format=yuv420p"]
    if index == 0:
        vf.append("fade=t=in:s=0:n=3")
    if is_stage:
        vf.append(f"fade=t=out:s={length-8}:n=7")
    name = f"shot-{index:02d}.mp4"
    run("-threads", 2, "-ss", f"{(0 if is_stage else row['in'])/FPS:.9f}",
        "-i", source, "-map", "0:v:0", "-an", "-filter_threads", 2, "-vf", ",".join(vf),
        "-frames:v", length, *ENCODE, name, cwd=workdir)
    actual = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                      "-show_entries", "stream=nb_frames", "-of", "csv=p=0", str(workdir/name)])
    if int(actual) != length:
        raise ValueError(f"{source} gerou {int(actual)} quadros, esperado {length}.")
    return f"file '{name}'\nduration {length/FPS:.9f}\n"


def render(sources, stage, output):
    data = json.loads((ROOT/"Timeline.json").read_text())
    shots = data["shots"]
    if shots[0]["start"] != 0 or shots[-1]["end"] != FRAMES:
        raise ValueError("A timeline precisa cobrir 700 quadros.")
    if any(a["end"] != b["start"] for a, b in zip(shots, shots[1:])):
        raise ValueError("Plano de corte com lacuna ou sobreposição.")
    with TemporaryDirectory(prefix="oniria-clean-") as temp:
        workdir = Path(temp)
        with ThreadPoolExecutor(max_workers=2) as executor:
            items = list(executor.map(lambda spec: shot(*spec, sources, stage, workdir), enumerate(shots)))
        (workdir/"montagem.txt").write_text("".join(items))
        (workdir/"Locucao.ass").write_bytes((ROOT/"Locucao.ass").read_bytes())
        run("-f", "concat", "-safe", 1, "-i", "montagem.txt", "-c", "copy",
            "-bsf:v", "setts=pts=N*1000:dts=N*1000:duration=1000", "-video_track_timescale", "24000",
            "montagem.mp4", cwd=workdir)
        run("-i", "montagem.mp4", "-an", "-filter_threads", 3, "-vf", "ass=Locucao.ass",
            "-frames:v", FRAMES, *ENCODE, "-movflags", "+faststart", output.resolve(), cwd=workdir)


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    render(options.sources.resolve(), options.stage.resolve(), options.output)
