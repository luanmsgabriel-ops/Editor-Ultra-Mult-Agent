"""Reconstruct the three-card cascade and compare it against the reference."""

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np

from . import providers


HERE = Path(__file__).resolve().parent
STUDIO = (232, 228, 231)
CARD_IDS = {"card_a", "card_b", "card_c"}


def read_template(path):
    rig = json.loads(path.read_text(encoding="utf-8"))
    if rig["schema_version"] != 1 or rig["fps"] != 30 or rig["canvas"] != [720, 1280]:
        raise ValueError("Este piloto espera o esquema 1 em 720 × 1280 a 30 fps.")
    start, end = rig["source_range"]
    settled = rig["settled_frame"]
    ids = [layer["id"] for layer in rig["layers"]]
    if len(ids) != 3 or set(ids) != CARD_IDS:
        raise ValueError("O template precisa dos três cards.")
    if not 0 <= start <= settled < end or end - start > 180:
        raise ValueError("Faixa de referência inválida para o piloto.")
    if len({layer["z"] for layer in rig["layers"]}) != len(ids):
        raise ValueError("A ordem de composição precisa ser única.")
    for layer in rig["layers"]:
        raw = np.asarray(layer["keys"], dtype=float)
        if (
            raw.ndim != 2 or raw.shape[1] != 5 or raw.shape[0] < 2
            or not np.isfinite(raw).all() or np.any(raw[:, 3] <= 0)
            or np.any(np.diff(raw[:, 0]) <= 0) or np.any(raw[:, 0] % 1)
            or raw[0, 0] < start or raw[-1, 0] >= end
        ):
            raise ValueError(f"Chaves inválidas para {layer['id']}.")
    rig["layers"].sort(key=lambda layer: layer["z"])
    return rig


def pose(layer, frame):
    keys = np.asarray(layer["keys"])
    if frame < keys[0, 0]:
        return None
    return np.array([np.interp(frame, keys[:, 0], keys[:, i]) for i in range(1, 5)])


def transform(center, angle, scale, left):
    radians = np.deg2rad(angle)
    a, b = np.cos(radians) * scale, np.sin(radians) * scale
    linear = np.array([[a, -b], [b, a]])
    return np.column_stack((linear, np.array(center) - linear @ left))


def placed(layer, frame):
    dx, dy, scale, angle = pose(layer, frame)
    return transform(
        np.array(layer["center"]) + [dx, dy], layer["angle"] + angle,
        scale, np.asarray(layer["size"]) / 2,
    )


def round_alpha(width, height, radius):
    yy, xx = np.mgrid[:height, :width]
    qx = abs(xx + .5 - width / 2) - (width / 2 - radius)
    qy = abs(yy + .5 - height / 2) - (height / 2 - radius)
    distance = np.hypot(qx.clip(0), qy.clip(0)) + np.minimum(np.maximum(qx, qy), 0) - radius
    return np.clip(.5 - distance, 0, 1).astype(np.float32)


def contain_card(image, dimensions):
    width, height = dimensions
    hi, wi = image.shape[:2]
    ratio = max(width / wi, height / hi)
    size = (max(width, round(wi * ratio)), max(height, round(hi * ratio)))
    scaled = cv2.resize(image, size, interpolation=cv2.INTER_AREA if ratio < 1 else cv2.INTER_CUBIC)
    x, y = (scaled.shape[1] - width) // 2, (scaled.shape[0] - height) // 2
    return scaled[y:y + height, x:x + width]


def paint_card(pixels, layer, *, from_reference):
    width, height = layer["size"]
    pixels = pixels.astype(np.float32) / 255
    if not from_reference:
        inner = np.zeros((height, width), dtype=np.float32)
        inner[3:-3, 3:-3] = round_alpha(width - 6, height - 6, layer["radius"] - 3)
        pixels = pixels * inner[..., None] + np.array([.96, .96, .98]) * (1 - inner[..., None])
    opacity = round_alpha(width, height, layer["radius"])
    return np.dstack((pixels * opacity[..., None], opacity)).astype(np.float32)


def extract_card(settled, layer, settled_frame):
    width, height = layer["size"]
    extract = cv2.warpAffine(
        settled, placed(layer, settled_frame), (width, height),
        flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
    )
    if layer["id"] == "card_c":
        # The front card occludes the upper-left of C in the settled reference.
        # Restore the flat blue surface from the clear half of that same card.
        for y in range(8, min(94, height)):
            limit = max(0, 52 - y // 4)
            extract[y, :limit] = extract[y, 78:113].mean(axis=0).round().astype(np.uint8)
    return paint_card(extract, layer, from_reference=True)


def composite(canvas, premultiplied, opacity=1):
    alpha = premultiplied[..., 3:4] * opacity
    canvas[:] = premultiplied[..., :3] * opacity + canvas * (1 - alpha)


def card_opacity(layer, frame):
    return min(1, max(0, (frame - layer["keys"][0][0] + .2) / 1.4))


def draw(rig, cards, frame, background, foreground=None):
    width, height = rig["canvas"]
    canvas = background.astype(np.float32) / 255
    if foreground is not None:
        rgba = foreground.astype(np.float32) / 255
        rgba[..., :3] *= rgba[..., 3:4]
        composite(canvas, rgba)
    for layer in rig["layers"]:
        if pose(layer, frame) is None:
            continue
        alpha = card_opacity(layer, frame)
        card = cv2.warpAffine(cards[layer["id"]], placed(layer, frame), (width, height))
        composite(canvas, card, alpha)
    return np.round(np.clip(canvas, 0, 1) * 255).astype(np.uint8)


def measures(rig, reference_frames):
    start, _ = rig["source_range"]
    still = rig["settled_frame"]
    gray = [cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) for frame in reference_frames]
    output = {}
    for layer in rig["layers"]:
        basis = np.vstack((placed(layer, still), [0, 0, 1]))
        inverse = np.linalg.inv(basis)
        width, height = layer["size"]
        left, top, right, bottom = layer["patch"]
        patch = np.float32([[left * width, top * height], [right * width, top * height],
                            [right * width, bottom * height], [left * width, bottom * height]])
        polygon = cv2.transform(patch[None, :, :], basis[:2])[0]
        expected = {
            frame - start: placed(layer, frame) @ inverse
            for frame in range(layer["measure_from"], rig["source_range"][1] - 3)
        }
        steps = providers.observe(gray[still - start], gray, polygon, expected, start)
        pivot = np.r_[layer["center"], 1]
        centers, angles, scales = [], [], []
        for observed in steps:
            matrix = observed["matrix"]
            model = expected[observed["frame"] - start]
            centers.append(float(np.linalg.norm(matrix @ pivot - model @ pivot)))
            angles.append(float(abs(np.degrees(
                np.arctan2(matrix[1, 0], matrix[0, 0]) - np.arctan2(model[1, 0], model[0, 0])
            ))))
            scales.append(float(abs(np.linalg.norm(matrix[:, 0]) - np.linalg.norm(model[:, 0]))))
        peak = max(layer["keys"], key=lambda key: key[3])
        observed_set = {step["frame"] for step in steps}
        output[layer["id"]] = {
            "visible_from_frame": {"card_a": 93, "card_b": 101, "card_c": 105}[layer["id"]],
            "scale_peak_frame": peak[0],
            "scale_overshoot_percent": round((peak[3] - 1) * 100, 2),
            "flow_observed_frames": len(steps),
            "flow_expected_frames": len(expected),
            "flow_frames_rejected": [n + start for n in expected if n + start not in observed_set],
            "median_center_error_px": round(float(np.median(centers)), 2) if centers else None,
            "p95_center_error_px": round(float(np.percentile(centers, 95)), 2) if centers else None,
            "median_rotation_error_deg": round(float(np.median(angles)), 2) if angles else None,
            "median_scale_error_percent": round(float(np.median(scales) * 100), 2) if scales else None,
        }
    return output


def encode(path, frames, size):
    width, height = size
    with tempfile.NamedTemporaryFile() as raw:
        for frame in frames:
            raw.write(frame.tobytes())
        raw.flush()
        command = [
            "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}", "-r", "30", "-i", raw.name, "-an", "-c:v", "libx264",
            "-vf", "scale=out_color_matrix=bt709,format=yuv420p", "-crf", "17", "-threads", "4",
            "-color_primaries", "bt709", "-colorspace", "bt709", "-color_trc", "bt709",
            "-movflags", "+faststart", str(path),
        ]
        subprocess.run(command, check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], check=True)


def comparison(reference, still, variant):
    labels = ("REFERENCIA", "RECONSTRUCAO", "IMAGENS TROCADAS")
    panels = (reference, still, variant)
    for frames in zip(*panels):
        row = []
        for label, frame in zip(labels, frames):
            panel = np.full((682, 360, 3), (33, 28, 39), dtype=np.uint8)
            panel[42:] = cv2.resize(frame, (360, 640), interpolation=cv2.INTER_AREA)
            cv2.putText(panel, label, (17, 27), cv2.FONT_HERSHEY_SIMPLEX, .55, (241, 235, 246), 1, cv2.LINE_AA)
            row.append(panel)
        yield np.concatenate(row, axis=1)


def export_hyperframes(directory, rig, cards):
    """Build a seekable HyperFrames scene from the same per-frame transforms."""
    directory.mkdir(parents=True, exist_ok=True)
    start, end = rig["source_range"]
    layers = []
    for layer in rig["layers"]:
        asset = layer["id"] + ".png"
        rgba = cards[layer["id"]].copy()
        rgba[..., :3] = rgba[..., :3] / np.maximum(rgba[..., 3:4], 1e-8)
        rgba = np.uint8(np.round(np.clip(rgba, 0, 1) * 255))
        if not cv2.imwrite(str(directory / asset), rgba):
            raise OSError(f"Não consegui exportar {asset}.")
        frames = []
        for frame in range(start, end):
            if pose(layer, frame) is None:
                frames.append(None)
                continue
            matrix = placed(layer, frame)
            frames.append({
                "matrix": np.round(matrix.T.ravel(), 8).tolist(),
                "alpha": card_opacity(layer, frame),
            })
        layers.append({"id": layer["id"], "image": asset, "frames": frames})
    scene = (HERE / "hyperframes.html").read_text(encoding="utf-8")
    scene = scene.replace("__DURATION__", str((end - start) / rig["fps"]))
    scene = scene.replace("__TRACK_DATA__", json.dumps({"frameCount": end - start, "layers": layers}))
    (directory / "index.html").write_text(scene, encoding="utf-8")


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def run(args):
    rig = read_template(args.template)
    if args.motionclone_render and not (args.motionclone and args.hyperframes):
        raise ValueError("A comparação do MotionClone exige o projeto editável e o HyperFrames.")
    motionclone = providers.motionclone_project(args.motionclone) if args.motionclone else {"status": "aguardando_export_editavel"}
    cotracker = providers.comparison_tracks(args.cotracker) if args.cotracker else {"status": "comparador_de_pesquisa_opcional"}
    if Fraction(providers.video_rate(args.reference)) != rig["fps"]:
        raise ValueError("Prepare a referência em 30 fps antes de comparar o intervalo.")
    start, end = rig["source_range"]
    size = tuple(rig["canvas"])
    source = providers.video_frames(args.reference, start, end, *size)
    baseline = source[rig["settled_frame"] - start]
    original = {layer["id"]: extract_card(baseline, layer, rig["settled_frame"]) for layer in rig["layers"]}
    replacements = dict(zip(sorted(CARD_IDS), args.cards, strict=True))
    alternate = {
        layer["id"]: paint_card(
            contain_card(providers.image(replacements[layer["id"]]), layer["size"]), layer, from_reference=False,
        ) for layer in rig["layers"]
    }
    args.out.mkdir(parents=True, exist_ok=True)
    backdrop = np.full((size[1], size[0], 3), STUDIO, dtype=np.uint8)
    if args.background:
        rate = Fraction(providers.video_rate(args.background))
        indices = [int((Fraction(args.background_start) + Fraction(n, rig["fps"])) * rate)
                   for n in range(end - start)]
        decoded = providers.video_frames(args.background, indices[0], indices[-1] + 1, *size)
        backgrounds = [decoded[index - indices[0]] for index in indices]
    else:
        backgrounds = [backdrop] * (end - start)
    same, changed = [], []
    for index, frame in enumerate(range(start, end)):
        foreground = (
            providers.foreground_frame(args.foreground, index + 1, size) if args.foreground else None
        )
        same.append(draw(rig, original, frame, backdrop))
        changed.append(draw(rig, alternate, frame, backgrounds[index], foreground))
    encode(args.out / "referencia.mp4", source, size)
    encode(args.out / "reconstrucao.mp4", same, size)
    encode(args.out / "imagens-trocadas.mp4", changed, size)
    encode(args.out / "comparacao.mp4", comparison(source, same, changed), (1080, 682))
    export_hyperframes(args.out / "hyperframes", rig, alternate)
    report = {
        "source": {"sha256": sha256(args.reference), "frames": [start, end], "fps": rig["fps"], "canvas": size},
        "frames_rendered": len(changed),
        "trajectory_order": ["card_a", "card_b", "card_c"],
        "z_order_back_to_front": [layer["id"] for layer in rig["layers"]],
        "template_sha256": sha256(args.template),
        "reference_tracking": measures(rig, source),
        "tracks_shared_by_both_renders": True,
        "adapters": {
            "opencv": {"version": cv2.__version__, "status": "executado"},
            "sam2": {"status": "recorte_externo_usado" if args.foreground else "recorte_dispensavel_neste_plano"},
            "motionclone": motionclone,
            "cotracker": cotracker,
        },
        "notes": [
            "Quadros iniciais dos cards foram conferidos visualmente. A medição usa o trecho com textura suficiente.",
            "O render compara o movimento dos cards. Fundo, pessoa, tipografia e efeitos de transição da referência ficam fora do recorte técnico.",
        ],
    }
    if args.motionclone_render:
        report["adapters"]["motionclone"]["comparacao"] = providers.hyperframes_report(
            args.hyperframes, args.out / "referencia.mp4", args.motionclone_render,
        )
    if args.hyperframes:
        report["adapters"]["hyperframes"] = providers.hyperframes_report(
            args.hyperframes, args.out / "referencia.mp4", args.out / "reconstrucao.mp4",
        )
    else:
        report["adapters"]["hyperframes"] = {"status": "cli_opcional"}
    shutil.copyfile(args.template, args.out / "motion.json")
    (args.out / "relatorio.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--cards", nargs=3, type=Path, required=True, metavar=("A", "B", "C"))
    parser.add_argument("--background", type=Path)
    parser.add_argument("--background-start", default="0")
    parser.add_argument("--foreground", type=Path)
    parser.add_argument("--hyperframes", type=Path)
    parser.add_argument("--motionclone", type=Path)
    parser.add_argument("--motionclone-render", type=Path)
    parser.add_argument("--cotracker", type=Path)
    parser.add_argument("--template", type=Path, default=HERE / "motion.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
    print(args.out / "comparacao.mp4")


if __name__ == "__main__":
    main()
