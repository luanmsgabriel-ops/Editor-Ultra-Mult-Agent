"""Bounded source-clock temporal QA for reference versus rendered reconstruction.

Separate from reference_cadence.py, which handles reference cuts and beat timing.
This records observed per-frame 2D changes and flow gaps, never approval or
restored object motion.
"""
from __future__ import annotations
from fractions import Fraction
from pathlib import Path
import csv
import hashlib
import json
import subprocess
import cv2
import numpy as np
from .reference_fidelity import _clock

MAX_WINDOWS = 6
MAX_WINDOW_FRAMES = 240
MAX_TOTAL_FRAMES = 720
RASTER = (160, 90)

def _sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def _decode(path, clock):
    width, height = RASTER
    command = ["ffmpeg", "-nostdin", "-v", "error", "-threads", "2", "-i", str(path),
               "-map", "0:v:0", "-vf", f"scale={width}:{height}:flags=area,format=gray",
               "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    try:
        data = subprocess.run(command, capture_output=True, timeout=150, check=True).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise ValueError("Video cannot be decoded on its original clock") from exc
    if len(data) != clock["frame_count"] * width * height:
        raise ValueError("Decoded frame count differs from source clock")
    return np.frombuffer(data, dtype=np.uint8).reshape(clock["frame_count"], height, width)

def validate_windows(ranges, count):
    if not isinstance(ranges, list) or not 1 <= len(ranges) <= MAX_WINDOWS:
        raise ValueError("Select one to six review windows")
    previous, total, checked = 0, 0, []
    for span in ranges:
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise ValueError("Review window requires [start_frame,end_frame)")
        first, last = span
        if (type(first) is not int or type(last) is not int or first < previous
                or last - first < 3 or last - first > MAX_WINDOW_FRAMES or last > count):
            raise ValueError("Windows must be ordered, disjoint and 3 to 240 frames")
        previous, total = last, total + last - first
        checked.append([first, last])
    if total > MAX_TOTAL_FRAMES:
        raise ValueError("Review exceeds 720 source frames")
    return checked

def window_around_seconds(clock, center_s, length_frames=90):
    if (type(center_s) not in (float, int) or not np.isfinite(center_s)
            or type(length_frames) is not int or length_frames < 3 or length_frames > MAX_WINDOW_FRAMES):
        raise ValueError("Invalid source time or window size")
    count, fps = clock["frame_count"], Fraction(clock["fps"])
    if count < 3 or center_s < 0 or Fraction(str(center_s)) * fps >= count:
        raise ValueError("Selected playback time lies outside the reference")
    length = min(count, length_frames)
    position = int(Fraction(str(center_s)) * fps)
    first = max(0, min(count - length, position - length // 2))
    return [[first, first + length]]

def measure_reference_cadence_gap(reference, reconstruction, output, *, ranges):
    reference, reconstruction, output = Path(reference), Path(reconstruction), Path(output)
    if not reference.is_file() or not reconstruction.is_file():
        raise ValueError("Reference and reconstruction files are required")
    clock = _clock(reference)
    if _clock(reconstruction) != clock:
        raise ValueError("Reference and clone clocks/raster differ; no implicit alignment")
    windows = validate_windows(ranges, clock["frame_count"])
    ref_frames, clone_frames = _decode(reference, clock), _decode(reconstruction, clock)
    fps, rows = Fraction(clock["fps"]), []
    for window_number, (first, last) in enumerate(windows):
        for frame in range(first + 1, last):
            a, prev_a = ref_frames[frame], ref_frames[frame - 1]
            b, prev_b = clone_frames[frame], clone_frames[frame - 1]
            ref_change = float(np.abs(a.astype(np.int16) - prev_a.astype(np.int16)).mean()) / 255
            clone_change = float(np.abs(b.astype(np.int16) - prev_b.astype(np.int16)).mean()) / 255
            flow_a = cv2.calcOpticalFlowFarneback(prev_a, a, None, .5, 2, 13, 2, 5, 1.1, 0)
            flow_b = cv2.calcOpticalFlowFarneback(prev_b, b, None, .5, 2, 13, 2, 5, 1.1, 0)
            speed_a = float(np.linalg.norm(flow_a, axis=2).mean())
            speed_b = float(np.linalg.norm(flow_b, axis=2).mean())
            rows.append({"window": window_number, "frame": frame,
                         "time_s": round(float(frame / fps), 6),
                         "reference_change": round(ref_change, 6),
                         "candidate_change": round(clone_change, 6),
                         "change_gap": round(abs(ref_change - clone_change), 6),
                         "reference_flow_smallpx_per_frame": round(speed_a, 6),
                         "candidate_flow_smallpx_per_frame": round(speed_b, 6),
                         "flow_gap_smallpx_per_frame": round(abs(speed_a - speed_b), 6),
                         "luma_gap": round(float(abs(a.mean() - b.mean()) / 255), 6)})
    if not rows:
        raise ValueError("No frames were available for within-window comparison")
    result = {"schema": "editor-ultra-reference-temporal-qa/1",
              "status": "diagnostic_not_approved",
              "source": {"sha256": _sha(reference)},
              "reconstruction": {"sha256": _sha(reconstruction)},
              "clock": clock, "windows": windows,
              "analysis_raster": list(RASTER), "alignment": "exact_same_frame_no_retime",
              "metrics": {"mean_change_gap": round(float(np.mean([r["change_gap"] for r in rows])), 6),
                          "mean_flow_gap_smallpx_per_frame": round(float(np.mean([r["flow_gap_smallpx_per_frame"] for r in rows])), 6),
                          "max_change_gap": max(r["change_gap"] for r in rows),
                          "max_flow_gap_smallpx_per_frame": max(r["flow_gap_smallpx_per_frame"] for r in rows)},
              "largest_change_gaps": sorted(rows, key=lambda row: row["change_gap"], reverse=True)[:10],
              "largest_flow_gaps": sorted(rows, key=lambda row: row["flow_gap_smallpx_per_frame"], reverse=True)[:10],
              "sample_count": len(rows),
              "limitations": ["Downscaled 2D optical flow is not per-object tracking, true velocity or camera pose",
                              "Brightness changes and scene cuts affect the metrics",
                              "No aesthetic approval or motion-blur proof"],
              "user_approved": False, "perceptual_review": "pending"}
    if output.exists():
        raise ValueError("Use a new evidence directory")
    output.mkdir(parents=True)
    csv_file = output / "temporal_frames.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result["csv"] = {"name": csv_file.name, "sha256": _sha(csv_file)}
    (output / "temporal_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
