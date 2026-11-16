"""Map authored-motion sound candidates to the real source audio clock."""

from fractions import Fraction
from pathlib import Path

from .contracts import clone, file_sha256, integer, mapping, number, require, sequence, sha256
from .motion_assets import frame_rate


def map_sonic_candidates(candidates: dict, source: str | Path, *, source_first_frame: int,
                         source_last_frame: int | None = None, asset_start_frame: int = 0) -> dict:
    """Map timing only. This never picks an SFX or marks an attack as listened."""
    from visual_fidelity.reference_cadence import video_clock
    data = clone(mapping(candidates, "sonic_candidates"))
    require(data.get("schema_version") == "motionlab-sonic/1" and data.get("clock") == "scene_seconds",
            "sonic_schema", "Expected Motion Lab scene-clock candidates")
    sha256(data.get("scene_sha256"), "scene_sha256")
    source = Path(source).resolve()
    source_hash = file_sha256(source)
    fps, count = video_clock(source)
    require(frame_rate(data.get("fps")) == fps, "sonic_clock", "Motion and source FPS differ; explicit retiming is required")
    motion_count = integer(data.get("frame_count"), "motion frame_count", minimum=1)
    integer(source_first_frame, "source_first_frame")
    integer(asset_start_frame, "asset_start_frame")
    last = count if source_last_frame is None else integer(source_last_frame, "source_last_frame", minimum=1)
    require(0 <= source_first_frame < last <= count, "sonic_interval", "Placement must stay inside the source")
    require(asset_start_frame + last - source_first_frame <= motion_count, "sonic_coverage", "Motion does not cover this placement")
    start_t = Fraction(source_first_frame, 1) / fps
    end_t = Fraction(last, 1) / fps
    offset = Fraction(source_first_frame - asset_start_frame, 1) / fps
    mapped, outside, ids = [], [], set()
    for event in sequence(data.get("candidates"), "candidates"):
        mapping(event, "sonic candidate")
        identifier = event.get("id")
        require(isinstance(identifier, str) and bool(identifier) and identifier not in ids,
                "sonic_id", "Sound candidate identifiers must be unique")
        ids.add(identifier)
        seconds = number(event.get("time_s"), "time_s", minimum=0)
        require(Fraction(str(seconds)) < Fraction(motion_count, 1) / fps,
                "sonic_range", "Candidate starts outside the authored scene")
        instant = Fraction(str(seconds)) + offset
        if not start_t <= instant < end_t:
            outside.append({"id": identifier, "reason": "outside selected motion excerpt"})
            continue
        exact_sample = instant * 48000
        target_sample = (exact_sample.numerator * 2 + exact_sample.denominator) // (2 * exact_sample.denominator)
        require(start_t <= Fraction(target_sample, 48000) < end_t, "sonic_quantization",
                "Rounded sound target falls outside the selected interval; revise its timing")
        mapped.append({"id": identifier, "source_sha256": source_hash, "clock": "source",
                       "source_time_s": float(instant), "target_sample": target_sample, "sample_rate": 48000,
                       "rounding_error_samples": float(Fraction(target_sample) - exact_sample),
                       "motion_candidate": event, "sound_asset": None,
                       "selection_status": "requires_editorial_choice_and_reviewed_attack"})
    require(file_sha256(source) == source_hash, "sonic_source_changed", "Source changed during timing analysis")
    return {"schema": "motion-sonic-map/1", "source_path": str(source), "source_sha256": source_hash,
            "source_fps": str(fps), "source_frame_count": count, "scene_sha256": data["scene_sha256"],
            "placement": {"source_first_frame": source_first_frame, "source_last_frame": last,
                          "asset_start_frame": asset_start_frame, "retime": False},
            "candidates": mapped, "excluded": outside, "audio_listened": False, "sfx_selected": False}
