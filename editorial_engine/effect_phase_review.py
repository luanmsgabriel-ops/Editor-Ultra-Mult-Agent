"""Operator-invoked phase diagnostics on independently prepared A/B renders.

This is not a hosted verifier identity and does not grant review eligibility.
A caller supplies the predeclared measurement windows and known file hashes
outside the render recipe. The purpose is to reject weak or missing results.
"""
from pathlib import Path
import argparse
import json
import math
import subprocess

from fractions import Fraction

from .effect_witness import contrast_witness, frame_set, refraction_motion_witness, sha


def presentation_clock(path):
    command = ["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=width,height,time_base:frame=best_effort_timestamp",
               "-of", "json", str(Path(path).resolve())]
    try:
        probe = json.loads(subprocess.check_output(command, timeout=30))
        stream, = probe["streams"]
        time_base = Fraction(stream["time_base"])
        pts = tuple(int(frame["best_effort_timestamp"])*time_base for frame in probe["frames"])
        if not 0 < len(pts) <= 3600 or time_base <= 0 or any(a >= b for a,b in zip(pts, pts[1:])):
            raise ValueError("invalid bounded presentation clock")
        return (stream["width"], stream["height"]), pts
    except (KeyError, subprocess.SubprocessError) as error:
        raise ValueError("could not verify the video presentation clock") from error


def analyze_pair(effect_path, control_path, contract):
    if not isinstance(contract, dict) or set(contract) != {"schema", "active_sha256", "control_sha256", "phases"}:
        raise ValueError("expected an exact operator phase contract")
    if contract["schema"] != "ultra-phase-pair/1":
        raise ValueError("unsupported phase contract")
    active = sha(effect_path)
    control = sha(control_path)
    if active != contract["active_sha256"] or control != contract["control_sha256"] or active == control:
        raise ValueError("active and distinct zero-strength control must match bound bytes")
    phases = contract["phases"]
    if not isinstance(phases, dict) or not 1 <= len(phases) <= 16:
        raise ValueError("one to sixteen uniquely named phases are required")
    for name, phase in phases.items():
        if (not isinstance(name, str) or not name or not isinstance(phase, dict)
                or set(phase) != {"frame", "roi", "min_tracks", "min_median_px", "luma_delta_floor"}
                or type(phase["frame"]) is not int or type(phase["min_median_px"]) not in (int, float)
                or not math.isfinite(phase["min_median_px"]) or not 0 < phase["min_median_px"] <= 32):
            raise ValueError("invalid optical phase or acceptance floor")
    frames = sorted({phase["frame"] for phase in phases.values()})
    dimensions, clock = presentation_clock(effect_path)
    if presentation_clock(control_path) != (dimensions, clock):
        raise ValueError("compare only an aligned raster and presentation clock")
    on, off = frame_set(effect_path, frames), frame_set(control_path, frames)
    # Reject changed files after decoding; these files are local QA inputs.
    if sha(effect_path) != active or sha(control_path) != control:
        raise ValueError("input bytes changed while decoding")
    results = {}
    for name, spec in phases.items():
        frame = spec["frame"]
        movement = refraction_motion_witness(on[frame], off[frame], spec["roi"],
            min_tracks=spec["min_tracks"], luma_delta_floor=spec["luma_delta_floor"],
            controls_provenance="operator-declared zero-strength control; recipe equivalence checked separately")
        observed = movement["median_displacement_px"]
        status = "blocked_insufficient_texture" if observed is None else (
            "meets_optical_floor" if observed >= spec["min_median_px"] else "below_optical_floor")
        results[name] = {"frame": frame, "status": status, "min_median_px": spec["min_median_px"],
            "movement": movement, "contrast": contrast_witness(on[frame], off[frame], spec["roi"], threshold=6)}
    return {"schema": "ultra-phase-diagnostics/1", "active_sha256": active, "control_sha256": control,
        "phases": results, "frames_aligned": len(clock),
        "status": "optical_floor_witnessed" if all(r["status"] == "meets_optical_floor" for r in results.values())
                  else "changes_required",
        "aesthetic_approved": False, "review_eligibility_evaluated": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("active", "control", "contract"):
        parser.add_argument("--"+name, required=True, type=Path)
    parsed = parser.parse_args(argv)
    from .effect_gate import load_unique
    result = analyze_pair(parsed.active, parsed.control, load_unique(parsed.contract))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "optical_floor_witnessed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
