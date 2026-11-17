"""Bounded exact-frame video comparison. Evidence, never automatic approval."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np

MAX_FRAMES = 16
MAX_PIXELS = 1920 * 1080
MAX_SOURCE_FRAMES = 3600


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _clock(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_frames,avg_frame_rate",
         "-of", "json", str(path)], capture_output=True, timeout=30, check=True)
    streams = json.loads(result.stdout).get("streams", [])
    if len(streams) != 1:
        raise ValueError("Expected one video stream")
    s = streams[0]
    try:
        fps = Fraction(s["avg_frame_rate"])
        count = int(s["nb_frames"])
        width, height = int(s["width"]), int(s["height"])
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        raise ValueError("Video must declare rational FPS and frame count") from exc
    if fps <= 0 or count <= 0 or count > MAX_SOURCE_FRAMES or width * height > MAX_PIXELS:
        raise ValueError("Video clock or raster exceeds bounded comparison limits")
    return {"width": width, "height": height, "fps": str(fps), "frame_count": count}


def _read_frames(path: Path, indices: list[int]) -> list[np.ndarray]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("Unable to open source video")
    out = []
    try:
        for n in indices:
            if not cap.set(cv2.CAP_PROP_POS_FRAMES, n):
                raise ValueError(f"Cannot seek to frame {n}")
            ok, frame = cap.read()
            if not ok or frame is None:
                raise ValueError(f"Frame {n} cannot be decoded")
            out.append(frame)
    finally:
        cap.release()
    return out


def _edge_f1(reference: np.ndarray, candidate: np.ndarray) -> float:
    a = cv2.Canny(reference, 80, 160) > 0
    b = cv2.Canny(candidate, 80, 160) > 0
    if not (a.any() or b.any()):
        return 1.0
    if not a.any() or not b.any():
        return 0.0
    kernel = np.ones((3, 3), np.uint8)
    matched_a = cv2.dilate(b.astype("uint8"), kernel).astype(bool)
    matched_b = cv2.dilate(a.astype("uint8"), kernel).astype(bool)
    recall = float((a & matched_a).sum()) / float(a.sum())
    precision = float((b & matched_b).sum()) / float(b.sum())
    return float(2 * precision * recall / (precision + recall)) if precision + recall else 0.0


def _ssim(reference: np.ndarray, candidate: np.ndarray) -> float:
    x = reference.astype("float32") / 255.0
    y = candidate.astype("float32") / 255.0
    mx, my = cv2.GaussianBlur(x, (11, 11), 1.5), cv2.GaussianBlur(y, (11, 11), 1.5)
    xx = cv2.GaussianBlur(x*x, (11, 11), 1.5) - mx*mx
    yy = cv2.GaussianBlur(y*y, (11, 11), 1.5) - my*my
    xy = cv2.GaussianBlur(x*y, (11, 11), 1.5) - mx*my
    c1, c2 = 0.01**2, 0.03**2
    value = ((2*mx*my+c1)*(2*xy+c2)) / ((mx*mx+my*my+c1)*(xx+yy+c2))
    return float(np.mean(value))


def _row(frame_index: int, ref: np.ndarray, clone: np.ndarray, fps: Fraction) -> dict:
    delta = cv2.absdiff(ref, clone)
    gray_a, gray_b = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), cv2.cvtColor(clone, cv2.COLOR_BGR2GRAY)
    return {"frame": frame_index, "time_s": round(float(frame_index/fps), 6),
            "mae_rgb": round(float(np.mean(delta)) / 255.0, 6),
            "ssim_luma": round(_ssim(gray_a, gray_b), 6),
            "edge_f1_1px": round(_edge_f1(gray_a, gray_b), 6)}


def audit_pair(reference: Path, reconstruction: Path, output: Path, frames: list[int]) -> dict:
    """Never retime, crop or resize either input. Require one verified source clock."""
    reference, reconstruction, output = Path(reference), Path(reconstruction), Path(output)
    if not reference.is_file() or not reconstruction.is_file():
        raise ValueError("Reference and reconstruction must exist")
    if (not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES
            or any(type(frame) is not int for frame in frames)
            or frames != sorted(set(frames))):
        raise ValueError("Require 1 to 16 unique ascending integer frame indices")
    clock = _clock(reference)
    if _clock(reconstruction) != clock:
        raise ValueError("FPS, frame count and raster must match; no implicit retime or resize")
    if frames[0] < 0 or frames[-1] >= clock["frame_count"]:
        raise ValueError("Requested frame is outside the original source")
    originals, copies = _read_frames(reference, frames), _read_frames(reconstruction, frames)
    rows = [_row(n, a, b, Fraction(clock["fps"])) for n, a, b in zip(frames, originals, copies)]
    width = 340
    height = max(1, round(width * clock["height"] / clock["width"]))
    sheet = np.full(((height + 34) * len(rows), width * 3, 3), 18, dtype=np.uint8)
    for i, (n, a, b, details) in enumerate(zip(frames, originals, copies, rows)):
        y = i * (height + 34)
        for j, img in enumerate((a, b, cv2.absdiff(a, b))):
            thumb = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
            sheet[y+34:y+34+height, j*width:(j+1)*width] = thumb
        label = f'FRAME {n} | {details["time_s"]:0.3f}s'
        for j, title in enumerate(("ORIGINAL", "RECONSTRUCAO", "DIFERENCA")):
            cv2.putText(sheet, f"{title}   {label}", (j*width+6, y+23),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (225, 225, 225), 1, cv2.LINE_AA)
    output.mkdir(parents=True, exist_ok=False)
    image_path = output / "aligned_contact_sheet.jpg"
    if not cv2.imwrite(str(image_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88]):
        raise ValueError("Unable to write contact sheet")
    report = {"schema": "editor-ultra-reference-comparison/1",
              "status": "diagnostic_only_not_approved",
              "source": {"sha256": _sha256(reference)},
              "reconstruction": {"sha256": _sha256(reconstruction)},
              "clock": clock, "frame_alignment": "exact_same_index_no_retime",
              "metrics_are_not_a_fidelity_grade": True,
              "perceptual_review": "pending", "user_approval": False,
              "samples": rows,
              "diagnostics": {"mae_rgb_mean": round(float(np.mean([r["mae_rgb"] for r in rows])), 6),
                              "ssim_luma_mean": round(float(np.mean([r["ssim_luma"] for r in rows])), 6),
                              "edge_f1_mean": round(float(np.mean([r["edge_f1_1px"] for r in rows])), 6)},
              "evidence": {"contact_sheet": image_path.name, "sha256": _sha256(image_path)}}
    (output / "comparison_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
