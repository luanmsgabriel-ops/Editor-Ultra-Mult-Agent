"""Typed bridge from current project Motion Kit receipt to the native renderer.

Browser JSON specifies IDs, frame map and physical mapping parameters only;
it never injects a motion profile, filesystem path, shell command or network URL.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from editorial_engine.contracts import ValidationError, require
from editorial_engine import project as project_engine
from visual_fidelity.motion_binding import validate_binding, validate_time_map
from visual_fidelity.motion_profile import profile_digest


class NativeTimePoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    output_time: float = Field(ge=0, le=600, allow_inf_nan=False)
    source_time: float = Field(ge=0, le=120, allow_inf_nan=False)


class NativeMeasuredMotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_name: Literal["editor-ultra-native-measured-motion/1"] = Field(
        default="editor-ultra-native-measured-motion/1", alias="schema")
    measurement_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    # The planner uses native decision identifiers such as decision:shield-layer.
    decision_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
    element_id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
    channels: list[Literal["position", "scale", "angle"]] = Field(min_length=1, max_length=3)
    pivot_px: list[float] = Field(min_length=2, max_length=2)
    base_scale: float = Field(gt=0, le=32, allow_inf_nan=False)
    spatial_scale: float | None = Field(default=None, gt=0, le=32, allow_inf_nan=False)
    spatial_offset_px: list[float] = Field(default_factory=lambda: [0.0, 0.0], min_length=2, max_length=2)
    time_map: list[NativeTimePoint] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def check_numeric(self):
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("Motion channels must not repeat")
        for name in ("pivot_px", "spatial_offset_px"):
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or abs(v) > 16384 for v in getattr(self, name)):
                raise ValueError(name + " must contain two finite bounded output coordinates")
        validate_time_map([x.model_dump() for x in self.time_map])
        return self


def bind_native_motion(adapter, record, stage, request):
    """Resolve verified stored measured curves and check target authoring."""
    measurements = [entry for entry in record.get("motion_measurements", [])
                    if entry["id"] == request.measurement_id]
    require(len(measurements) == 1, "native_motion_measurement",
            "Select one measured current profile belonging to this project")
    measurement = measurements[0]
    require(adapter._motion_public(record, measurement)["current"]
            and measurement.get("scope") == "evidence_not_applied",
            "native_motion_stale", "Measure the current reference after all project revisions")
    source = record["files"].get(measurement["source"]["asset_id"])
    require(source is not None and source["sha256"] == measurement["source"]["sha256"]
            and source["role"] in {"ref", "footage"},
            "native_motion_source", "Motion trajectory must originate in verified reference or new footage")
    profile_asset = measurement["artifacts"]["profile"]
    profile_path = adapter.resolve_asset(record["project_id"], profile_asset["asset_id"])
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    require(profile_digest(profile) == measurement["profile_sha256"],
            "native_motion_profile", "Motion profile changed since its measurement receipt")
    bound = profile.get("application_binding", {})
    require(bound.get("measurement_id") == measurement["id"]
            and bound.get("source", {}).get("sha256") == source["sha256"]
            and bound.get("specification_sha256") == measurement["specification_sha256"],
            "native_motion_provenance", "Curves do not belong to the selected verified measurement")
    bundle = project_engine.artifact(stage["directory"], "edit_bundle")
    decisions = [decision for decision in bundle["plan"]["decisions"]
                 if decision["id"] == request.decision_id]
    require(len(decisions) == 1 and decisions[0].get("operation")
            and decisions[0]["operation"]["operation"] in {"overlay", "motion_layer"},
            "native_motion_decision", "Select a compiled native screen overlay or motion layer decision")
    operation = decisions[0]["operation"]
    require(operation["renderer"] == "native" and operation["params"].get("animation", "hold") == "hold"
            and operation["anchor"]["space"] == "screen",
            "native_motion_scope", "Measured native placement requires a screen/hold visual decision")
    binding = {
        "schema": "element-motion-binding/1", "stage": "masked_canvas",
        "profile": profile, "profile_sha256": measurement["profile_sha256"],
        "element_id": request.element_id,
        "channels": request.channels, "pivot_px": request.pivot_px,
        "base_scale": request.base_scale,
        "time_map": [row.model_dump() for row in request.time_map],
    }
    if request.spatial_scale is not None:
        binding["spatial_scale"] = request.spatial_scale
        binding["spatial_offset_px"] = request.spatial_offset_px
    else:
        require(request.spatial_offset_px == [0, 0],
                "native_motion_spatial_map", "Offset requires an explicit uniform spatial_scale")
    validate_binding(binding)
    summary = {"schema": "editor-ultra-native-motion-application/1",
               "measurement_id": measurement["id"],
               "measurement_profile_sha256": measurement["profile_sha256"],
               "measured_source_sha256": source["sha256"],
               "decision_id": request.decision_id, "element_id": request.element_id,
               "channels": request.channels, "status": "bound_not_rendered",
               "user_approved": False, "perceptual_review": "pending"}
    return {request.decision_id: binding}, summary
