"""Isolate a warm/cool emitter using decoded, aligned on/off BGR frames."""
import numpy as np

def measure_emitter(on, off, roi, side, color, *, gain=17):
    """Measure signed chromatic gain (not an aesthetic or reference-equivalence score)."""
    if (not isinstance(on,np.ndarray) or not isinstance(off,np.ndarray) or on.dtype != np.uint8
        or off.dtype != np.uint8 or on.shape != off.shape or on.ndim != 3 or on.shape[2]!=3):
        raise ValueError("aligned 8-bit BGR frames required")
    if color not in {"warm","cool"} or side not in {"left","right"} or type(gain) is not int or not 1<=gain<=255:
        raise ValueError("invalid color/side/gain")
    x0,y0,x1,y1=roi
    h,w=on.shape[:2]
    if (not all(type(v) is int for v in roi) or
        not 0<=x0<x1<=w or not 0<=y0<y1<=h or not x0<w/2<x1):
        raise ValueError("ROI must include valid pixels on both sides")
    d=on[y0:y1,x0:x1].astype(np.int16)-off[y0:y1,x0:x1].astype(np.int16)
    b,g,r=d.transpose((2,0,1))
    signal=np.minimum(r-b,r-g) if color=="warm" else np.minimum(b-r,g-r)
    yy,xx=np.where(signal>=gain)
    strength=signal[yy,xx].astype(np.int64); x=xx+x0
    target=(x<w/2) if side=="left" else (x>=w/2)
    count=int(len(xx))
    energy=int(strength.sum())
    observed_centroid=float(np.average(x,weights=strength)) if energy else None
    channel_span=np.max(d,axis=2)-np.min(d,axis=2)
    return {"strong_px":count,"target_px":int(target.sum()),"opposite_px":count-int(target.sum()),
            "positive_chromatic_energy":energy,"target_energy_fraction":float(strength[target].sum()/energy) if energy else None,
            "centroid_x_px":observed_centroid,"roi_peak_channel_difference":int(channel_span.max())}


def analyze_thermal_pair(active_path, control_path, spec):
    """Check two prescribed pulses and surrounding controls. Not aesthetic QA.

    The operator supplies the predeclared frame windows and establishes that
    only the emitter was disabled in the control render.
    """
    from .effect_witness import frame_set, sha
    from .effect_phase_review import presentation_clock

    keys = {"active_sha256", "control_sha256", "roi", "gain", "min_area",
            "min_side_fraction", "max_control_px", "warm", "cool", "controls"}
    if not isinstance(spec, dict) or set(spec) != keys:
        raise ValueError("invalid thermal phase contract")
    active, control = sha(active_path), sha(control_path)
    if (active, control) != (spec["active_sha256"], spec["control_sha256"]) or active == control:
        raise ValueError("thermal pair does not match distinct bound bytes")
    phases = [spec[k] for k in ("controls", "warm", "cool")]
    if any(not isinstance(p, list) or not 2 <= len(p) <= 32
           or any(type(f) is not int or f < 0 for f in p)
           or sorted(set(p)) != p for p in phases):
        raise ValueError("invalid ordered thermal windows")
    negatives, warm, cool = phases
    if (warm[-1] >= cool[0] or negatives[0] >= warm[0] or negatives[-1] <= cool[-1]
            or set(negatives) & (set(warm) | set(cool))):
        raise ValueError("warm must precede cool with disjoint surrounding controls")
    if (type(spec["min_area"]) is not int or spec["min_area"] < 1
            or type(spec["max_control_px"]) is not int or not 0 <= spec["max_control_px"] < spec["min_area"]
            or type(spec["min_side_fraction"]) not in (int, float)
            or not 0.5 < spec["min_side_fraction"] <= 1):
        raise ValueError("invalid thermal floors")
    dimensions, timeline = presentation_clock(active_path)
    if presentation_clock(control_path) != (dimensions, timeline):
        raise ValueError("thermal sources are not presentation aligned")
    frames = sorted(set(negatives + warm + cool))
    if frames[-1] >= len(timeline):
        raise ValueError("thermal window extends beyond the video")
    on, off = frame_set(active_path, frames), frame_set(control_path, frames)
    if (sha(active_path), sha(control_path)) != (active, control):
        raise ValueError("thermal source changed during decoding")
    pairs = {"warm": ("right", warm), "cool": ("left", cool)}
    results, problems = {}, []
    for color, (side, window) in pairs.items():
        values = {f: measure_emitter(on[f], off[f], spec["roi"], side, color, gain=spec["gain"])
                  for f in frames}
        qualified = [f for f in window if values[f]["target_px"] >= spec["min_area"]
                     and values[f]["target_energy_fraction"] >= spec["min_side_fraction"]]
        if not any(b == a + 1 for a,b in zip(qualified, qualified[1:])):
            problems.append(f"{color}: no two consecutive qualified frames")
        controls = {f: values[f]["strong_px"] for f in negatives}
        if any(px > spec["max_control_px"] for px in controls.values()):
            problems.append(f"{color}: chromatic residue in negative control")
        results[color] = {"side": side, "window": {f: values[f] for f in window},
                          "qualified_frames": qualified, "controls": controls}
    return {"schema": "ultra-thermal-diagnostic/1", "active_sha256": active,
            "control_sha256": control, "results": results, "problems": problems,
            "status": "changes_required" if problems else "thermal_direction_witnessed",
            "aesthetic_approved": False, "review_eligibility_evaluated": False}
