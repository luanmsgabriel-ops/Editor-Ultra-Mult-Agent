"""Reference-analysis-only motion reconstruction. No asset decoder in this route."""
from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from PIL import Image, ImageColor, ImageDraw, __version__ as pillow_version

SCHEMA = "editor-ultra-effects-only/1"
RECEIPT = "editor-ultra-effects-only-receipt/1"
ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
COLOR = re.compile(r"#[0-9a-fA-F]{6}\Z")


class EffectsError(ValueError):
    pass


def check(test, problem):
    if not test:
        raise EffectsError(problem)


def shape(value, keys, label):
    check(type(value) is dict and set(value) == set(keys.split()), "Invalid fields: " + label)


def number(value, lo, hi, label):
    check(type(value) is int and lo <= value <= hi, "Out of bounds: " + label)


def color(value):
    check(type(value) is str and COLOR.fullmatch(value), "Expected opaque #RRGGBB color")


def validate(m):
    shape(m, "schema canvas reference audio effects", "manifest")
    check(m["schema"] == SCHEMA, "Unknown schema")
    c, r = m["canvas"], m["reference"]
    shape(c, "width height fps duration_frames background", "canvas")
    w, h, fps, n = c["width"], c["height"], c["fps"], c["duration_frames"]
    number(w, 32, 1920, "width")
    number(h, 32, 1920, "height")
    number(fps, 1, 120, "fps")
    number(n, 1, 1800, "duration_frames")
    check(w * h * n <= 300_000_000, "Frame budget exceeded")
    color(c["background"])
    shape(r, "sha256 usage", "reference")
    check(r["usage"] == "analysis_only" and type(r["sha256"]) is str
          and SHA.fullmatch(r["sha256"]), "Reference must be analysis-only digest")
    shape(m["audio"], "mode provenance", "audio")
    check(m["audio"] == {"mode": "silent", "provenance": "none"}, "Audio not supported; output must be silent")
    effects = m["effects"]
    check(type(effects) is list and 0 < len(effects) <= 64, "Expected 1–64 effects")
    seen = set()
    for e in effects:
        shape(e, "id kind start_frame end_frame z provenance params", "effect")
        name, kind = e["id"], e["kind"]
        check(type(name) is str and ID.fullmatch(name) and name not in seen, "Invalid or duplicate effect ID")
        seen.add(name)
        check(e["provenance"] == "authored_primitive", "Unapproved effect source: " + name)
        check(kind in ("caption", "panel", "pulse"), "Unsupported effect: " + name)
        number(e["start_frame"], 0, n - 1, "start_frame")
        number(e["end_frame"], e["start_frame"] + 1, n, "end_frame")
        number(e["z"], -1024, 1024, "z")
        p = e["params"]
        if kind == "caption":
            shape(p, "x y color text", name)
            number(p["x"], 0, w - 1, "x")
            number(p["y"], 0, h - 1, "y")
            check(type(p["text"]) is str and 0 < len(p["text"]) <= 160
                  and all(32 <= ord(ch) <= 126 or 160 <= ord(ch) <= 255 for ch in p["text"]),
                  "Caption contains unsupported glyphs")
        else:
            extra = " x_end y_end" if kind == "panel" else ""
            shape(p, "x y width height color" + extra, name)
            number(p["width"], 1, w, "width")
            number(p["height"], 1, h, "height")
            number(p["x"], 0, w-p["width"], "x")
            number(p["y"], 0, h-p["height"], "y")
            if kind == "panel":
                number(p["x_end"], 0, w-p["width"], "x_end")
                number(p["y_end"], 0, h-p["height"], "y_end")
        color(p["color"])
    return m


def load(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            check(k not in result, "Duplicate JSON key: " + k)
            result[k] = v
        return result
    data = Path(path).read_bytes()
    check(len(data) <= 256_000, "Manifest is too large")
    return validate(json.loads(data, object_pairs_hook=unique))


def render_frames(manifest):
    """Rebuild each frame independently; no mutable state crosses a frame boundary."""
    m = validate(manifest)
    c = m["canvas"]
    layers = sorted(m["effects"], key=lambda e: (e["z"], e["id"]))
    for frame in range(c["duration_frames"]):
        im = Image.new("RGB", (c["width"], c["height"]), c["background"])
        d = ImageDraw.Draw(im)
        for e in layers:
            begin, end = e["start_frame"], e["end_frame"]
            if not begin <= frame < end:
                continue
            p, kind = e["params"], e["kind"]
            x, y, color_hex = p["x"], p["y"], p["color"]
            if kind == "caption":
                d.text((x, y), p["text"], fill=color_hex)
                continue
            t, span = frame-begin, max(1, end-begin-1)
            if kind == "panel":
                # Integer smoothstep. Exact endpoints and repeated cross-run output.
                step, den = t*t*(3*span-2*t), span**3
                x += (p["x_end"]-x)*step//den
                y += (p["y_end"]-y)*step//den
            if kind == "pulse":
                alpha = 255 if end-begin == 1 else 255*(span-abs(2*t-span))//span
                source = ImageColor.getrgb(color_hex)
                box = (x, y, x+p["width"], y+p["height"])
                fill = Image.new("RGB", (p["width"], p["height"]), source)
                im.paste(Image.blend(im.crop(box), fill, alpha/255), (x,y))
            else:
                d.rectangle((x, y, x+p["width"]-1, y+p["height"]-1), fill=color_hex)
        yield im.tobytes()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_aux(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_frames",
         "-show_entries", "stream=codec_type,codec_name,pix_fmt,time_base,width,height:frame=pts",
         "-of", "json", str(path)], check=True, capture_output=True)
    return json.loads(result.stdout)


def verify(path, c, expected):
    p = read_aux(path)
    s = p["streams"]
    check(len(s) == 1 and s[0]["codec_type"] == "video" and s[0]["codec_name"] == "ffv1"
          and s[0]["pix_fmt"] == "bgr0"
          and (s[0]["width"], s[0]["height"]) == (c["width"], c["height"]),
          "Invalid master: unexpected streams, codec or dimensions")
    base = Fraction(s[0]["time_base"])
    frames = [int(x["pts"]) for x in p["frames"]]
    n, fps = c["duration_frames"], c["fps"]
    check(len(frames) == n and all(abs(i/Fraction(fps)-pts*base) <= base/2
                                  for i, pts in enumerate(frames))
          and (not frames or frames[0] == 0), "Invalid presentation timestamps")
    with subprocess.Popen(
        ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(path),
         "-map", "0:v", "-fps_mode", "passthrough", "-pix_fmt", "rgb24",
         "-f", "rawvideo", "-threads", "1", "-"], stdout=subprocess.PIPE,
    ) as proc:
        size = c["width"]*c["height"]*3
        for i, digest in enumerate(expected):
            b = proc.stdout.read(size)
            if len(b) != size or sha(b) != digest:
                proc.kill()
                raise EffectsError("Lossless decode mismatch at frame " + str(i))
        if proc.stdout.read(1):
            proc.kill()
            raise EffectsError("Unexpected extra frame bytes")
        check(proc.wait() == 0, "Strict video decode failed")
    return {"time_base": str(base), "pts": frames, "frame_sha256": expected}


def render(manifest, output_dir):
    m = validate(manifest)
    c = m["canvas"]
    out = Path(output_dir)
    check(not out.exists() or (out.is_dir() and not any(out.iterdir())), "Use a new or empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".effects-only-", dir=out) as tmp:
        tmp = Path(tmp)
        master = tmp/"effects.mkv"
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-n", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-video_size", f'{c["width"]}x{c["height"]}', "-framerate", str(c["fps"]), "-i", "-",
               "-an", "-map_metadata", "-1", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0",
               "-threads", "1", "-fflags", "+bitexact", "-flags:v", "+bitexact", str(master)]
        expected = []
        with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
            try:
                for b in render_frames(m):
                    expected.append(sha(b))
                    proc.stdin.write(b)
                proc.stdin.close()
                check(proc.wait() == 0, "FFmpeg encoding failed")
            except BaseException:
                if proc.poll() is None:
                    proc.kill()
                raise
        timeline = verify(master, c, expected)
        portable = json.dumps(m, ensure_ascii=False, sort_keys=True, indent=2).encode()
        (tmp/"manifest.json").write_bytes(portable)
        r = {"schema": RECEIPT, "master_sha256": sha_file(master),
             "manifest_sha256": sha(portable), "pillow_version": pillow_version,
             "audio": m["audio"], "timeline": timeline,
             "draw_order": [e["id"] for e in sorted(m["effects"], key=lambda e: (e["z"], e["id"]))]}
        (tmp/"receipt.json").write_text(json.dumps(r, sort_keys=True, indent=2), encoding="utf-8")
        for name in ("effects.mkv", "manifest.json", "receipt.json"):
            (tmp/name).replace(out/name)
    return r


def check_revision(previous, current, start, end, region=None):
    """Reference separate exports; fail if any unauthorized frame/timing/audio changes."""
    def open_and_verify(p):
        p = Path(p)
        r = json.loads((p/"receipt.json").read_text(encoding="utf-8"))
        m = load(p/"manifest.json")
        check(r["schema"] == RECEIPT and sha_file(p/"manifest.json") == r["manifest_sha256"]
              and sha_file(p/"effects.mkv") == r["master_sha256"], "Mismatched revision files")
        expected = [sha(x) for x in render_frames(m)]
        timeline = verify(p/"effects.mkv", m["canvas"], expected)
        check(timeline == r["timeline"] and m["audio"] == r["audio"], "Mismatched revision receipt")
        return m, timeline
    left, a = open_and_verify(previous)
    right, b = open_and_verify(current)
    check(left["canvas"] == right["canvas"] and left["audio"] == right["audio"]
          and left["reference"] == right["reference"], "Revision changed canvas, audio or reference")
    check(a["pts"] == b["pts"] and a["time_base"] == b["time_base"], "Revision changed the presentation clock")
    n = left["canvas"]["duration_frames"]
    number(start, 0, n-1, "authorized start")
    number(end, start+1, n, "authorized end")
    changed = [i for i,(x,y) in enumerate(zip(a["frame_sha256"], b["frame_sha256"], strict=True)) if x != y]
    check(all(start <= i < end for i in changed), "Unauthorized frame change")
    if region is not None:
        check(len(region) == 4, "Authorized region needs four coordinates")
        x0, y0, x1, y1 = region
        w, h = left["canvas"]["width"], left["canvas"]["height"]
        number(x0, 0, w-1, "left")
        number(y0, 0, h-1, "top")
        number(x1, x0+1, w, "right")
        number(y1, y0+1, h, "bottom")
        for i, (a, b) in enumerate(zip(render_frames(left), render_frames(right), strict=True)):
            if i not in changed:
                continue
            for row in range(h):
                l, r = row*w*3, (row+1)*w*3
                if y0 <= row < y1:
                    check(a[l:l+x0*3] == b[l:l+x0*3] and a[l+x1*3:r] == b[l+x1*3:r],
                          "Unauthorized pixel change at frame " + str(i))
                else:
                    check(a[l:r] == b[l:r], "Unauthorized pixel change at frame " + str(i))
    return {"changed_frames": changed, "unchanged_outside_window": True,
            "authorized_window": [start, end], "verified_region": list(region) if region else None,
            "exact_pts": True, "unchanged_audio": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--out")
    parser.add_argument("--compare", nargs=2, metavar=("PREVIOUS", "CURRENT"))
    parser.add_argument("--window", nargs=2, type=int, metavar=("START", "END"))
    parser.add_argument("--region", nargs=4, type=int, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    args = parser.parse_args(argv)
    try:
        if args.compare and args.window and not args.manifest and not args.out:
            print(json.dumps(check_revision(*args.compare, *args.window, region=args.region)))
        elif args.manifest and args.out and not args.compare and not args.window and not args.region:
            render(load(args.manifest), args.out)
        else:
            parser.error("pass MANIFEST --out DIR, or --compare PREVIOUS CURRENT --window START END")
    except (EffectsError, OSError, subprocess.SubprocessError, ValueError) as e:
        parser.exit(2, f"effects-only: {e}\n")


if __name__ == "__main__":
    main()
