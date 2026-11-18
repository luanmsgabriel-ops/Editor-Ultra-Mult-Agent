"""Verified 2D measured-motion proof, using the existing geometric renderer.

This adapter does not synthesize gestures, segment moving people, retime audio,
or import reference photography. All file paths are resolved by EngineAdapter;
no paths, manifests, executable instructions or URLs come from the caller.
"""
from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path
from typing import Literal

import cv2
from pydantic import BaseModel, ConfigDict, Field, model_validator

from editorial_engine.contracts import file_sha256, require
from visual_fidelity.motion_binding import bind_timeline_motion, validate_time_map
from visual_fidelity.motion_profile import profile_digest
from visual_fidelity.motion_observation import probe_clock
from visual_fidelity.geometric_video import render as render_geometric


class TimePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    output_time: float = Field(ge=0, allow_inf_nan=False)
    source_time: float = Field(ge=0, allow_inf_nan=False)


class MotionApplicationSpecification(BaseModel):
    """Explicit mapping of one observed element to a new 2D RGBA still layer."""
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    schema_name: Literal["editor-ultra-measured-motion-application/1"] = Field(
        default="editor-ultra-measured-motion-application/1", alias="schema")
    measurement_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    base_asset_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    overlay_asset_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    matte_asset_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    element_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    channels: list[Literal["position", "scale", "angle"]] = Field(min_length=1, max_length=3)
    frame_count: int = Field(strict=True, ge=2, le=300)
    base_start_frame: int = Field(default=0, strict=True, ge=0, le=3600)
    pivot_px: list[float] = Field(min_length=2, max_length=2)
    base_scale: float = Field(gt=0, le=32, allow_inf_nan=False)
    spatial_scale: float | None = Field(default=None, gt=0, le=32, allow_inf_nan=False)
    spatial_offset_px: list[float] = Field(default_factory=lambda: [0., 0.], min_length=2, max_length=2)
    time_map: list[TimePoint] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def validate_mapping(self):
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("Motion channels must not repeat")
        for name in ("pivot_px", "spatial_offset_px"):
            if any(not isinstance(v, (int, float)) or isinstance(v, bool)
                   or not math.isfinite(v) or abs(v) > 16384 for v in getattr(self, name)):
                raise ValueError(name + " must contain two finite bounded coordinates")
        validate_time_map([p.model_dump() for p in self.time_map])
        if len({self.base_asset_id, self.overlay_asset_id, self.matte_asset_id}) != 3:
            raise ValueError("Base, overlay and matte must be distinct verified assets")
        return self


def verify_base_clock(video: Path, *, base_start_frame: int, frame_count: int):
    clock = probe_clock(video)
    require(clock["clock_kind"] == "cfr" and clock["fps"] and
            clock["container_rotation"] == 0 and clock["width"] % 2 == 0 and clock["height"] % 2 == 0,
            "motion_target_clock", "Use even-sized, unrotated CFR video for this 2D proof")
    require(base_start_frame + frame_count <= clock["frames"], "motion_target_range",
            "Target video does not cover the requested frames; never pad with copies")
    require(0 < clock["width"] <= 1920 and 0 < clock["height"] <= 1080 and
            clock["width"] * clock["height"] * frame_count <= 180_000_000,
            "motion_render_budget", "Measured-motion preview exceeds the bounded CPU render budget")
    rate = Fraction(clock["fps"])
    require(0 < rate <= 60, "motion_target_rate", "Motion preview FPS must be within 1..60")
    return clock


def prepare_timeline(spec: MotionApplicationSpecification, profile: dict, *,
                     base: Path, overlay: Path, matte: Path):
    """Prepare a fully specified motion timeline before starting any encoder."""
    clock = verify_base_clock(base, base_start_frame=spec.base_start_frame,
                              frame_count=spec.frame_count)
    sample = cv2.imread(str(overlay), cv2.IMREAD_UNCHANGED)
    mask = cv2.imread(str(matte), cv2.IMREAD_GRAYSCALE)
    require(sample is not None and mask is not None and sample.shape[:2] == mask.shape and
            bool((mask > 0).any()), "motion_matte",
            "The nonempty grayscale matte must match the overlay image raster")
    require(max(sample.shape[:2]) <= 4096, "motion_overlay_size", "Overlay raster exceeds 4096 pixels")
    size = (clock["width"], clock["height"])
    frames = [{
        "frame": i, "shot": "measured-motion-preview",
        "base": {"source": "base", "frame": spec.base_start_frame + i},
        "foreground": {"source": "overlay", "matte": str(matte)},
        "mask": {"kind": "empty"},
    } for i in range(spec.frame_count)]
    timeline = {
        "width": size[0], "height": size[1], "fps": clock["fps"], "frames": spec.frame_count,
        "assets": {
            "base": {"path": str(base), "kind": "video", "origin": "verified_project_asset"},
            "overlay": {"path": str(overlay), "kind": "image", "origin": "verified_project_asset"},
        },
        "asset_plan": {"slots": [{
            "id": "overlay", "evidence": "Measured reference motion: " + profile_digest(profile),
            "role": "2d_motion_proof", "status": "ready", "asset_ids": ["overlay"],
            "interval": [0, spec.frame_count], "semantic_review": "pending",
        }]},
        "frame_bindings": frames,
    }
    binding = {
        "target": "foreground", "interval": [0, spec.frame_count],
        "element_id": spec.element_id, "channels": spec.channels,
        "pivot_px": spec.pivot_px, "base_scale": spec.base_scale,
        "time_map": [point.model_dump() for point in spec.time_map],
    }
    if spec.spatial_scale is not None:
        binding["spatial_scale"] = spec.spatial_scale
        binding["spatial_offset_px"] = spec.spatial_offset_px
    else:
        require(size == (profile["source"]["width"], profile["source"]["height"]) and
                spec.spatial_offset_px == [0, 0], "motion_spatial_mapping",
                "Different output geometry requires an explicit spatial_scale and offset")
    # Preflight each output frame and reject holes/cuts/time-map ambiguity.
    result = bind_timeline_motion(timeline, profile, [binding])
    return result, clock


def render_preview(timeline: dict, directory: Path):
    """Return a byte-bound consumption receipt; failure never implies application."""
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = directory / "measured-timeline.json"
    movie = directory / "measured-preview.mp4"
    manifest.write_text(json.dumps(timeline, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
                        encoding="utf-8")
    report = render_geometric(manifest, movie)
    consumed = report.get("element_motion", {}).get("bindings", [])
    require(len(consumed) == 1 and consumed[0]["target"] == "foreground" and
            consumed[0]["frame_count"] == timeline["frames"] and
            consumed[0]["frames"] == list(range(timeline["frames"])),
            "motion_not_consumed", "The renderer did not consume the measured binding on every output frame")
    require(report["render_sha256"] == file_sha256(movie), "motion_output_hash",
            "Rendered preview bytes differ from the motion use receipt")
    return {"video": movie, "manifest": manifest, "sidecar": movie.with_suffix(".json"),
            "report": report, "consumption": consumed[0],
            "status": "rendered_unreviewed",
            "limitations": ["2D similarity only; no original gestures, 3D camera or occlusion inference",
                            "Single still overlay with a user-supplied matte; no automatic person replacement",
                            "Technical preview has no audio; continuous visual review remains pending"]}
