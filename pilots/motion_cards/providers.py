"""Interchange adapters for motion measurement, masks and editable projects."""

import json
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np


def image(path, *, alpha=False):
    flags = cv2.IMREAD_UNCHANGED if alpha else cv2.IMREAD_COLOR
    pixels = cv2.imread(str(path), flags)
    if pixels is None:
        raise ValueError(f"Imagem indisponível: {path}")
    if alpha and (pixels.ndim != 3 or pixels.shape[2] != 4):
        raise ValueError(f"A camada só é válida com transparência RGBA: {path}")
    return pixels


def video_frames(path, start, end, width, height):
    """Read exact zero-based frames. The caller verifies input frame rate."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-map", "0:v:0", "-vf", f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS,scale={width}:{height}",
         "-an", "-fps_mode", "passthrough", "-pix_fmt", "bgr24", "-threads", "1", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    pixels = np.frombuffer(result.stdout, dtype=np.uint8)
    expected = (end - start) * width * height * 3
    if pixels.size != expected:
        raise ValueError(f"O vídeo precisa conter os quadros [{start}, {end}).")
    return pixels.reshape(end - start, height, width, 3)


def video_rate(path):
    data = subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=avg_frame_rate", "-of", "json", str(path)], text=True,
    )
    streams = json.loads(data)["streams"]
    if not streams:
        raise ValueError(f"Vídeo indisponível: {path}")
    return streams[0]["avg_frame_rate"]


def hyperframes_report(cli, ref, reconstruction, *, ranges=None):
    """Run the pinned CLI on local paths. Preserve reports on low scores."""
    commands = {
        "cuts": ["measure", "cuts", str(ref)],
        "diff": ["diff", str(ref), str(reconstruction), "--json"],
    }
    reports = {}
    for name, args in commands.items():
        if name == "diff":
            args += ["--out", str(Path(reconstruction).parent / ("hyperframes-diff-" + Path(reconstruction).stem))]
        if name == "diff" and ranges:
            args += ["--range", ranges]
        result = subprocess.run(
            [str(cli), *args], text=True, capture_output=True, check=False,
            env={**os.environ, "HYPERFRAMES_NO_TELEMETRY": "1"},
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"HyperFrames não devolveu JSON em {name}: {result.stderr.strip() or result.stdout.strip()}"
            ) from error
        reports[name] = {"exit_code": result.returncode, "result": payload}
    return reports


def motionclone_project(directory):
    """Record an already exported editable project supplied by the editor."""
    root = Path(directory).resolve()
    package = root / "package.json"
    entries = sorted(root.glob("*.html"))
    if not root.is_dir() or not entries or not package.is_file():
        raise ValueError("Indique a pasta extraída do projeto editável do MotionClone.")
    manifest = json.loads(package.read_text(encoding="utf-8"))
    packages = {**manifest.get("dependencies", {}), **manifest.get("devDependencies", {})}
    if not any("hyperframes" in name for name in packages):
        raise ValueError("O projeto editável precisa declarar HyperFrames.")
    return {
        "status": "projeto_recebido",
        "timing_manifest": (root / "project.json").is_file(),
        "scene_scripts": sorted(str(entry.relative_to(root)) for entry in root.rglob("scene-*.js")),
        "entries": [entry.name for entry in entries],
        "packages": {key: value for key, value in packages.items() if "hyperframes" in key},
    }


def foreground_frame(directory, frame, size):
    mask = image(Path(directory) / f"{frame:06}.png", alpha=True)
    width, height = size
    if mask.shape[:2] != (height, width):
        raise ValueError("O recorte precisa ter o mesmo enquadramento e resolução do piloto.")
    return mask


def comparison_tracks(path):
    """Read a research export in CoTracker's pred_tracks/pred_visibility format."""
    with np.load(path, allow_pickle=False) as saved:
        tracks = np.asarray(saved["pred_tracks"])
        visibility = np.asarray(saved["pred_visibility"])
    if tracks.ndim == 4 and tracks.shape[0] == 1:
        tracks = tracks[0]
    if visibility.ndim == 3 and visibility.shape[0] == 1:
        visibility = visibility[0]
    if tracks.ndim != 3 or tracks.shape[-1] != 2 or visibility.shape != tracks.shape[:2]:
        raise ValueError("CoTracker espera coordenadas [T,N,2] e visibilidade [T,N].")
    usable = visibility.astype(bool) & np.isfinite(tracks).all(axis=-1)
    return {
        "status": "comparacao_nao_comercial",
        "frames": int(tracks.shape[0]),
        "points": int(tracks.shape[1]),
        "visible_per_frame": usable.sum(axis=1).tolist(),
    }


def observe(reference, frames, source_points, transforms, first_frame):
    """Measure card transforms with pyramidal optical flow and RANSAC."""
    featured = np.zeros(reference.shape, dtype=np.uint8)
    cv2.fillConvexPoly(featured, np.int32(source_points), 255)
    points = cv2.goodFeaturesToTrack(
        reference, 90, .01, 3, mask=featured, blockSize=3,
    )
    if points is None or len(points) < 5:
        raise ValueError("Textura insuficiente no card de referência.")
    params = {"winSize": (23, 23), "maxLevel": 2,
              "criteria": (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 32, .02)}
    observations = []
    for index, frame in enumerate(frames):
        expected = transforms.get(index)
        if expected is None:
            continue
        initial = cv2.transform(points, expected.astype(np.float32))
        targets, found, _ = cv2.calcOpticalFlowPyrLK(
            reference, frame, points, initial, flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **params,
        )
        if targets is None:
            continue
        reverted, returned, _ = cv2.calcOpticalFlowPyrLK(
            frame, reference, targets, points.copy(), flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **params,
        )
        if reverted is None:
            continue
        good = (found.reshape(-1) != 0) & (returned.reshape(-1) != 0)
        good &= np.linalg.norm((points - reverted)[:, 0], axis=1) < 1.6
        if good.sum() < 5:
            continue
        matrix, inliers = cv2.estimateAffinePartial2D(
            points[good, 0], targets[good, 0], method=cv2.RANSAC, ransacReprojThreshold=2.1,
        )
        if matrix is None or inliers.sum() < 5:
            continue
        observations.append({
            "frame": index + first_frame, "matrix": matrix, "inliers": int(inliers.sum()),
        })
    return observations
