"""Measure shots and render versioned effects on the current video's clock."""

from __future__ import annotations

from contextlib import contextmanager
from fractions import Fraction
import json
import math
from pathlib import Path
import subprocess
import tempfile
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from editorial_engine.contracts import digest, file_sha256
from visual_fidelity.anchor_camera import project
from visual_fidelity.effect_library import analyze_reference
from visual_fidelity.motion_observation import probe_clock
from visual_fidelity.planar_portal import render_portal_frame
from visual_fidelity.studio_matte import StudioMatte
from visual_fidelity.world_tracking import solve_world_track

EFFECTS = {
    "flash": {"label": "Flash de transição", "family": "transicao", "anchor": "cut", "min_frames": 3},
    "type": {"label": "Legenda cinética", "family": "motion", "anchor": "screen", "min_frames": 6},
    "world": {"label": "Cartão flutuante 3D", "family": "motion", "anchor": "world", "min_frames": 8},
}
AZURE = (58, 214, 245)
MAX_FRAMES = 3600


def _run(args):
    result = subprocess.run(args, capture_output=True, timeout=240)
    if result.returncode:
        raise ValueError("FFmpeg não conseguiu processar a mídia selecionada.")
    return result.stdout


@contextmanager
def video(path, first=0):
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened() or first and not capture.set(cv2.CAP_PROP_POS_FRAMES, first):
            raise ValueError("Não foi possível decodificar a tomada.")
        yield capture
    finally:
        capture.release()


def read_frame(capture):
    ok, frame = capture.read()
    if not ok:
        raise ValueError("A mídia terminou antes do quadro declarado.")
    return frame


def inspect_video(path, directory):
    clock = probe_clock(path)
    width, height = (clock[key] for key in ("width", "height"))
    if (not clock["fps"] or clock["frames"] > MAX_FRAMES or width * height > 1920 * 1080
            or width < 64 or height < 64 or clock["container_rotation"]):
        raise ValueError("Use um vídeo sem rotação de contêiner, de até 3.600 quadros e 1080p.")
    measured = analyze_reference(path)
    if measured["frames"] != clock["frames"]:
        raise ValueError("A quantidade de quadros decodificados diverge do relógio da fonte.")
    count = clock["frames"]
    cuts = sorted({row["frame"] for row in measured["candidates"] if row["candidate"] == "mudanca_forte"})
    boundaries = [0, *cuts, count]
    shots = [{"id": f"take-{i + 1}", "range": [first, end], "status": "candidate_boundary"}
             for i, (first, end) in enumerate(zip(boundaries, boundaries[1:])) if first < end]
    events = [{"id": f"event-{i + 1}", **value} for i, value in enumerate(measured["candidates"])]
    audio = _audio_attacks(path)
    tiles = []
    sample_frames = {(shot["range"][0] + shot["range"][1] - 1) // 2: shot for shot in shots}
    with video(path) as capture:
        for number in range(max(sample_frames) + 1):
            if not capture.grab():
                raise ValueError("O relógio não corresponde à decodificação.")
            shot = sample_frames.get(number)
            if shot is None:
                continue
            ok, frame = capture.retrieve()
            if not ok:
                raise ValueError("Não foi possível ler um quadro da amostra.")
            gray = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY)
            gradients = cv2.Canny(gray, 65, 140) > 0
            shot["lower_edge_density"] = round(float(np.mean(gradients[57:82, 20:140])), 4)
            shot["detail_density"] = round(float(np.mean(gradients[14:76, 15:145])), 4)
            if len(tiles) < 12:
                tile = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                tile.thumbnail((244, 136))
                tiles.append((shot, tile))
    sheet = Image.new("RGB", (744, math.ceil(len(tiles) / 3) * 164), (18, 23, 30))
    draw = ImageDraw.Draw(sheet)
    for i, (shot, tile) in enumerate(tiles):
        x, y = i % 3 * 248, i // 3 * 164
        sheet.paste(tile, (x + (244 - tile.width) // 2, y))
        draw.text((x + 8, y + 140), f"{shot['id']}  {shot['range'][0]}–{shot['range'][1] - 1}", fill="white")
    sheet.save(directory / "takes.jpg", quality=87)
    _run(["ffmpeg", "-nostdin", "-v", "error", "-threads", "2", "-i", str(path),
          "-map", "0:v:0", "-an", "-vf", r"scale=-2:trunc(min(480\,ih)/2)*2",
          "-fps_mode", "passthrough", "-c:v", "libx264", "-threads", "2", "-preset", "fast",
          "-crf", "31", "-movflags", "+faststart", str(directory / "inspection.mp4")])
    report = {"schema": "editor-ultra-shot-analysis/1", "source_sha256": file_sha256(path),
              "clock": clock, "shots": shots, "events": events, "audio": audio,
              "limitations": ["Cortes e flashes são candidatos técnicos.", "Amostras de quadros não certificam semântica ou camadas ocultas."]}
    (directory / "analysis.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return report


def _audio_attacks(path):
    track = _run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                  "stream=index", "-of", "csv=p=0", str(path)])
    if not track.strip():
        return {"present": False, "attack_candidates_s": []}
    pcm = _run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-t", "180",
                "-ac", "1", "-ar", "12000", "-f", "f32le", "pipe:1"])
    samples = np.frombuffer(pcm, dtype="<f4")
    window = 240
    windows = samples[:len(samples) // window * window].reshape(-1, window)
    rms = np.sqrt(np.mean(windows ** 2, axis=1))
    change = np.maximum(0, np.diff(rms))
    # Dynamic baseline. These timestamps are peaks in mono activity, not beats or effect IDs.
    peaks = []
    if len(change) > 2:
        threshold = max(.015, float(np.quantile(change, .96)))
        peaks = [i for i in range(1, len(change) - 1)
                 if change[i] >= threshold and change[i] > change[i - 1] and change[i] >= change[i + 1]]
        peaks = sorted(sorted(peaks, key=lambda i: change[i], reverse=True)[:80])
    return {"present": True, "window_ms": 20,
            "attack_candidates_s": [round((i + 1) * .02, 3) for i in peaks]}


def compatible_ranges(report, effect, default):
    """Return choices whose geometric prerequisites can be investigated on this source."""
    count = report["clock"]["frames"]
    length = max(EFFECTS[effect]["min_frames"], round(default * float(Fraction(report["clock"]["fps"]))))
    for i, shot in enumerate(report["shots"]):
        start, end = shot["range"]
        if effect == "flash":
            if i and min(start, count - start) >= 2:
                half = min(max(2, length // 2), start - report["shots"][i - 1]["range"][0], end - start)
                if half >= 2:
                    yield shot, [start - half, start + half], "Realça a mudança visual candidata.", start
            continue
        length_needed = EFFECTS[effect]["min_frames"]
        if end - start < length_needed:
            continue
        if effect == "world" and shot.get("detail_density", 0) < .035:
            continue
        reason = ("O trecho tem detalhes úteis para tentar medir a câmera."
                  if effect == "world" else "A legenda usa contraste próprio e cabe numa tomada contínua.")
        yield shot, [start, min(end, start + min(length, 300))], reason, None


def _font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def _card(text, width, height, color):
    art = Image.new("RGBA", (width, height))
    draw = ImageDraw.Draw(art)
    border = max(2, width // 95)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=height // 5,
                           fill=(18, 24, 35, 246), outline=(*color, 255), width=border)
    font = _font(max(10, height // 3))
    lines = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if line and draw.textlength(candidate, font=font) > width * .86:
            lines.append(line)
            line = word
        else:
            line = candidate
    lines.append(line)
    if len(lines) > 2 or any(draw.textlength(line, font=font) > width * .88 for line in lines):
        raise ValueError("O texto excede o espaço legível desta receita. Encurte ou aumente a escala.")
    draw.multiline_text((width / 2, height / 2), "\n".join(lines), font=font,
                        fill="white", anchor="mm", align="center", spacing=3, stroke_width=0)
    return np.asarray(art)


def _motion(effect, offset):
    samples = effect.get("motion")
    if not samples:
        return 0., 0., 1., 0.
    first, end = effect["range"]
    phase = offset / max(1, end - first - 1)
    ticks = [sample[0] for sample in samples]
    return tuple(float(np.interp(phase, ticks, [row[i] for row in samples])) for i in range(1, 5))


def _world_layer(art, track, frame, canvas, opacity, motion=(0., 0., 1., 0.)):
    camera = {**track["cameras"][frame], "size": canvas}
    horizontal, vertical, forward = np.asarray(track["axes"])
    center = np.asarray(track["center"])
    dx, dy, zoom, rotation = motion
    center = center + track["card_width"] * (dx * horizontal + dy * vertical)
    angle = math.radians(rotation)
    horizontal, vertical = (math.cos(angle) * horizontal - math.sin(angle) * vertical,
                            math.sin(angle) * horizontal + math.cos(angle) * vertical)
    h = track["card_width"] * zoom / 2
    v = h * art.shape[0] / art.shape[1]
    front = [center - horizontal*h - vertical*v, center + horizontal*h - vertical*v,
             center + horizontal*h + vertical*v, center - horizontal*h + vertical*v]
    quad = project(front, camera)
    back = project(np.asarray(front) + forward*h*.26, camera)
    if quad is None or back is None or not np.isfinite([quad, back]).all():
        raise ValueError("O elemento 3D saiu do campo renderizável.")
    if not np.all((quad >= -.10) & (quad <= 1.1)):
        raise ValueError("A âncora escolhida recorta o elemento 3D durante o trecho.")
    if not 0 <= opacity <= 1:
        raise ValueError("A opacidade do elemento 3D deve ficar entre 0 e 1.")
    if opacity == 0:
        return render_portal_frame(art, quad, canvas, mapping="projective", opacity=0)
    face = render_portal_frame(art, quad, canvas, mapping="projective")
    # Sample the swept alpha silhouette from face to back. Its variation along
    # a ray gives wall coverage, including the inside edges of holes.
    front_px, back_px = np.asarray([quad, back]) * canvas - .5
    corners = np.concatenate([front_px, back_px])
    lower = np.maximum(np.floor(corners.min(axis=0)).astype(int) - 1, 0)
    upper = np.minimum(np.ceil(corners.max(axis=0)).astype(int) + 2, canvas)
    if np.all(upper > lower):
        x0, y0 = lower
        x1, y1 = upper
        target = face[y0:y1, x0:x1]
        texture_h, texture_w = art.shape[:2]
        uv = np.float32([[0, 0], [texture_w, 0], [texture_w, texture_h], [0, texture_h]]) - .5
        minimum = target[:, :, 3].copy()
        maximum = minimum.copy()
        travel = np.linalg.norm(back_px - front_px, axis=1).max()
        steps = min(128, max(1, math.ceil(travel)))
        for step in range(1, steps + 1):
            depth = (step / steps) * h * .26
            section = project(np.asarray(front) + forward * depth, camera)
            points = (section * canvas - .5 - lower).astype(np.float32)
            warp = cv2.getPerspectiveTransform(uv, points)
            coverage = cv2.warpPerspective(art[:, :, 3], warp, (int(x1 - x0), int(y1 - y0)))
            np.minimum(minimum, coverage, out=minimum)
            np.maximum(maximum, coverage, out=maximum)
        sides = np.empty_like(target)
        sides[:, :, :3] = (66, 75, 103)
        sides[:, :, 3] = np.rint((maximum - minimum) * (235 / 255)).astype(np.uint8)
        target[:] = np.asarray(Image.alpha_composite(Image.fromarray(sides), Image.fromarray(target)))
        target[target[:, :, 3] == 0] = 0
    face[:, :, 3] = np.rint(face[:, :, 3] * opacity).astype(np.uint8)
    return face


def _seed(frame, polygon):
    height, width = frame.shape[:2]
    mask = np.zeros((height, width), np.uint8)
    points = np.rint(np.asarray(polygon) * [width - 1, height - 1]).astype(np.int32)
    cv2.fillPoly(mask, [points], 1)
    kernel = np.ones((5, 5), dtype=np.uint8)
    inner = cv2.erode(mask, kernel)
    outer = cv2.dilate(mask, kernel)
    trimap = np.full_like(mask, cv2.GC_BGD)
    trimap[outer > 0] = cv2.GC_PR_BGD
    trimap[mask > 0] = cv2.GC_PR_FGD
    trimap[inner > 0] = cv2.GC_FGD
    if not np.any(inner) or not np.any(outer == 0):
        raise ValueError("O contorno de oclusão precisa distinguir sujeito e fundo.")
    return trimap


def _prepare_track(path, effect, canvas):
    first, end = effect["range"]
    width, height = canvas
    size = (min(640, width), max(64, round(min(640, width) * height / width)))
    if size[1] > 640:
        size = (max(64, round(size[0] * 640 / size[1])), 640)
    polygon = effect.get("occlusion")
    with video(path, first) as capture:
        grays = [cv2.cvtColor(cv2.resize(read_frame(capture), size), cv2.COLOR_BGR2GRAY) for _ in range(end - first)]
    excluded = None
    if polygon:
        excluded = _seed(np.zeros((size[1], size[0], 3), np.uint8), polygon) > 0
        excluded = cv2.dilate(excluded.astype(np.uint8), np.ones((9, 9), np.uint8))
    calibration = effect.get("calibration")
    scale = np.diag([size[0] / width, size[1] / height, 1])
    if calibration:
        calibration = {**calibration, "intrinsics": (scale @ np.asarray(calibration["intrinsics"])).tolist()}
    track = solve_world_track(grays, calibration=calibration, anchor=effect.get("anchor"),
                              size_fraction=effect.get("scale", .24), exclude=excluded)
    track["raster"] = list(canvas)
    for camera in track["cameras"]:
        camera["K"] = (np.linalg.inv(scale) @ np.asarray(camera["K"])).tolist()
    track["reprojection_raster"] = list(size)
    return track


def _cached_track(path, effect, canvas, source_sha256, directory):
    key = {"schema": "editor-ultra-world-track-cache/1", "source_sha256": source_sha256,
           "raster": list(canvas), "binding": {name: effect.get(name) for name in
                                               ("range", "anchor", "scale", "calibration", "occlusion")}}
    directory.mkdir(mode=0o700, exist_ok=True)
    cached = directory / (digest(key) + ".json")
    if cached.is_file() and not cached.is_symlink():
        try:
            record = json.loads(cached.read_text(encoding="utf-8"))
            if record["binding"] == key and digest(record["track"]) == record["track_sha256"]:
                return {**record["track"], "cache_hit": True}
        except (OSError, ValueError, TypeError, KeyError):
            pass
    track = _prepare_track(path, effect, canvas)
    record = {"binding": key, "track": track, "track_sha256": digest(track)}
    temporary = directory / (".track-" + uuid4().hex)
    try:
        temporary.write_text(json.dumps(record, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(cached)
    finally:
        temporary.unlink(missing_ok=True)
    return {**track, "cache_hit": False}


def _activity(offset, length, curve):
    phase = offset / max(1, length - 1)
    if curve:
        return float(np.interp(phase, [row[0] for row in curve], [row[1] for row in curve]))
    return min(1., (offset + 1) * 5 / length, (length - offset) * 5 / length)


def _apply(frame, effect, offset, art, track=None, matte=None):
    first, end = effect["range"]
    mode = effect["effect"]
    phase = _activity(offset, end - first, effect.get("curve"))
    height, width = frame.shape[:2]
    if mode == "flash":
        strength = phase * effect["intensity"]
        return cv2.addWeighted(frame, 1 - strength, np.full_like(frame, 255), strength, 0), 0
    if mode == "world":
        layer = _world_layer(art, track, offset, (width, height), phase * effect["intensity"], _motion(effect, offset))
    else:
        x = (width - art.shape[1]) // 2
        y = min(height - art.shape[0], round(height * .78 + (1 - phase) * height * .055))
        layer = np.zeros((height, width, 4), np.uint8)
        layer[y:y + art.shape[0], x:x + art.shape[1]] = art
        if effect.get("motion"):
            dx, dy, zoom, angle = _motion(effect, offset)
            center = (width / 2, y + art.shape[0] / 2)
            affine = cv2.getRotationMatrix2D(center, angle, zoom)
            affine[:, 2] += np.asarray([dx, dy]) * art.shape[1]
            alpha = layer[:, :, 3:4].astype(np.float32) / 255
            premultiplied = layer.astype(np.float32)
            premultiplied[:, :, :3] *= alpha
            warped = cv2.warpAffine(premultiplied, affine, (width, height))
            warped_alpha = warped[:, :, 3:4] / 255
            warped[:, :, :3] = np.divide(warped[:, :, :3], warped_alpha,
                                         out=np.zeros_like(warped[:, :, :3]), where=warped_alpha > 0)
            layer = np.rint(np.clip(warped, 0, 255)).astype(np.uint8)
        layer[:, :, 3] = np.rint(layer[:, :, 3] * phase * effect["intensity"]).astype(np.uint8)
    alpha = layer[:, :, 3].astype(np.float32) / 255
    occluded = 0
    if matte is not None:
        occluded = int(np.count_nonzero((alpha > .2) & (matte > 127)))
        alpha *= 1 - matte.astype(np.float32) / 255
    result = frame * (1 - alpha[:, :, None]) + layer[:, :, 2::-1] * alpha[:, :, None]
    return np.rint(result).astype(np.uint8), occluded


@contextmanager
def _encoder(output, canvas, fps, *, source=None, start=0.0, duration=None, audio=False):
    width, height = canvas
    args = ["ffmpeg", "-nostdin", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-video_size", f"{width}x{height}", "-framerate", str(fps), "-i", "pipe:0"]
    if audio:
        args += ["-ss", f"{start:.9f}", "-i", str(source), "-map", "0:v:0", "-map", "1:a:0",
                 "-t", f"{duration:.9f}", "-c:a", "aac"]
    args += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-threads", "2",
             "-preset", "fast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=log)
        try:
            yield proc.stdin
            proc.stdin.close()
            if proc.wait(timeout=45):
                raise ValueError("FFmpeg não conseguiu codificar a saída.")
        except BaseException:
            proc.kill()
            proc.wait()
            output.unlink(missing_ok=True)
            raise
        finally:
            proc.stdin.close()


def _art(effect, canvas):
    width, height = canvas
    if effect["effect"] == "flash":
        return None
    if effect["effect"] == "world":
        size = (360, 140)
    else:
        size = (round(width * .85), max(24, round(height * .13)))
    return _card(effect["text"], *size, tuple(effect.get("color", AZURE)))


def render_demo(effect, output):
    width, height, count = 480, 270, 32
    fps = Fraction(16)
    canvas = (width, height)
    effect = {**effect, "range": [0, count], "text": "Prévia do efeito"}
    art = _art(effect, canvas)
    track = {"center": [0, 0, 5], "axes": np.eye(3).tolist(), "card_width": 2.,
             "cameras": [{"K": [[420, 0, width / 2], [0, 420, height / 2], [0, 0, 1]],
                          "R": np.eye(3).tolist(), "t": [(i - count / 2) * .04, 0., 0.]}
                         for i in range(count)]}
    with _encoder(output, canvas, fps) as stream:
        for frame_index in range(count):
            frame = np.zeros((height, width, 3), np.uint8)
            frame[:] = (28, 23, 19)
            for x in range(-32 + frame_index, width, 44):
                cv2.line(frame, (x, 0), (x, height), (68, 65, 59), 1)
            for y in range(0, height, 44):
                cv2.line(frame, (0, y), (width, y), (68, 65, 59), 1)
            result, _ = _apply(frame, effect, frame_index, art, track)
            stream.write(result.tobytes())


def render_edit(path, report, effects, directory, *, preview=False):
    clock = report["clock"]
    if clock["clock_kind"] != "cfr":
        raise ValueError("A análise conserva os PTS de vídeo VFR. Para renderizar, envie uma versão CFR.")
    width, height, count = (clock[key] for key in ("width", "height", "frames"))
    fps = Fraction(clock["fps"])
    canvas = (width, height)
    effects = sorted(effects, key=lambda item: item["range"])
    if not effects or any(a["range"][1] > b["range"][0] for a, b in zip(effects, effects[1:])):
        raise ValueError("Selecione trechos atuais sem sobreposição.")
    first, end = (effects[0]["range"][0], effects[-1]["range"][1]) if preview else (0, count)
    if preview:
        first = max(0, first - round(float(fps / 2)))
        end = min(count, end + round(float(fps / 2)))
    if first < 0 or end > count:
        raise ValueError("A edição excede os quadros da fonte.")
    tracks = {effect["id"]: _cached_track(path, effect, canvas, report["source_sha256"],
                                         directory.parent / "effect-tracks")
              for effect in effects if effect["effect"] == "world"}
    arts = {effect["id"]: _art(effect, canvas) for effect in effects}
    applied = {effect["id"]: {"source_frames": [], "occlusion_pixels": [], "changed_pixels": []}
               for effect in effects}
    audio = bool(_run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                       "stream=index", "-of", "csv=p=0", str(path)]).strip())
    output = directory / ("preview.mp4" if preview else "edit.mp4")
    duration = float((end - first) / fps)
    active = iter(effects)
    effect = next(active)
    matte = None
    with video(path, first) as capture, _encoder(output, canvas, fps, source=path, start=float(first / fps),
                                                duration=duration, audio=audio) as stream:
        for number in range(first, end):
            frame = read_frame(capture)
            if effect and number >= effect["range"][1]:
                effect = next(active, None)
                matte = None
            if effect and effect["range"][0] <= number < effect["range"][1]:
                key = effect["id"]
                offset = number - effect["range"][0]
                mask = None
                if effect.get("occlusion"):
                    if offset == 0:
                        matte = StudioMatte()
                    mask = matte.process(frame, _seed(frame, effect["occlusion"]) if offset == 0 else None)
                result, pixels = _apply(frame, effect, offset, arts[key], tracks.get(key), mask)
                applied[key]["source_frames"].append(number)
                applied[key]["occlusion_pixels"].append(pixels)
                applied[key]["changed_pixels"].append(int(np.count_nonzero(np.any(result != frame, axis=2))))
                frame = result
            stream.write(frame.tobytes())
    if probe_clock(output)["frames"] != end - first:
        raise ValueError("O render codificado diverge do intervalo solicitado.")
    if any(not any(item["changed_pixels"]) for item in applied.values()):
        raise ValueError("Pelo menos um efeito não ficou visível no intervalo. Revise a âncora, a máscara ou a intensidade.")
    receipt = {"schema": "editor-ultra-effect-edit/1", "source_sha256": report["source_sha256"],
               "render_sha256": file_sha256(output), "source_range": [first, end],
               "fps": str(fps), "audio_source_present": audio, "render_kind": "preview" if preview else "full",
               "applications": effects, "coverage": applied, "spatial": tracks}
    (directory / "render.json").write_text(json.dumps(receipt, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return output, receipt
