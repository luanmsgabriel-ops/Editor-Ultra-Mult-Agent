"""Proof-grounded scene router: routing != executing, no implicit paid generation."""
from __future__ import annotations
from fractions import Fraction
from .contracts import clone, digest

ROUTING_SCHEMA = "editor-ultra-scene-routing/1"
PLAN_SCHEMA = "editor-ultra-scene-route-plan/1"
BACKENDS = {
    "motion_graphic_2d": "motionlab",
    "measured_motion_2d": "motion_kit",
    "native_composite": "native",
    "typography_3d": "motngrfx",
    "environment_3d": "openkatana_blender",
    "temporal_occlusion": "external_masking",
    "synchronized_sfx": "native_audio",
    "new_actor_performance": "external_generation",
}
NEEDS = frozenset([*BACKENDS, "preserve"])


def probe_capabilities(required):
    """Only local read-only probes; no video model POST, installation or render."""
    required = set(required)
    probes = {
        "motionlab": {"available": False, "evidence": "not_checked"},
        "motion_kit": {"available": True, "evidence": "binding_code_available_not_executed"},
        "native": {"available": False, "evidence": "not_checked"},
        "native_audio": {"available": False, "evidence": "not_checked"},
        "motngrfx": {"available": False, "evidence": "not_checked"},
        "openkatana_blender": {"available": False, "evidence": "not_checked"},
        "external_masking": {"available": False, "evidence": "requires_verified_temporal_matte"},
        "external_generation": {"available": False, "evidence": "external_user_authorization_required"},
    }
    if "motion_graphic_2d" in required:
        try:
            from .motionlab import probe
            value = probe()
            probes["motionlab"] = {"available": value.get("available") is True,
                                   "evidence": "motionlab_pixel_probe" if value.get("available") else "motionlab_probe_blocked"}
        except (ImportError, OSError, RuntimeError, ValueError):
            probes["motionlab"]["evidence"] = "motionlab_probe_error"
    if required & {"native_composite", "synchronized_sfx"}:
        try:
            from .native import probe_native_backend
            value = probe_native_backend()
            probes["native"] = {"available": value.get("visual_available") is True,
                                "evidence": "native_ffmpeg_probe"}
            probes["native_audio"] = {"available": value.get("audio_available") is True,
                                      "evidence": "native_audio_filter_probe"}
        except (ImportError, OSError, RuntimeError, ValueError):
            probes["native"]["evidence"] = "native_probe_error"
    if "typography_3d" in required:
        try:
            from .motngrfx import probe_motngrfx
            value = probe_motngrfx()
            probes["motngrfx"] = {"available": value.get("available") is True,
                                  "evidence": "motngrfx_dependency_probe"}
        except (ImportError, OSError, RuntimeError, ValueError):
            probes["motngrfx"]["evidence"] = "motngrfx_probe_error"
    if "environment_3d" in required:
        try:
            from .openkatana import probe_openkatana
            value = probe_openkatana(check_browser=False)
            probes["openkatana_blender"] = {
                "available": value.get("capabilities", {}).get("blender") == "ready",
                "evidence": "openkatana_blender_probe"}
        except (ImportError, OSError, RuntimeError, ValueError):
            probes["openkatana_blender"]["evidence"] = "openkatana_probe_error"
    return probes


def validate_choices(manifest, spec):
    if (not isinstance(spec, dict) or set(spec) != {"schema", "scenes"}
            or spec["schema"] != ROUTING_SCHEMA):
        raise ValueError("Expected editor-ultra-scene-routing/1")
    declared = spec["scenes"]
    if not isinstance(declared, list) or len(declared) != len(manifest["scenes"]):
        raise ValueError("All reference scenes require authored routing")
    by_id = {}
    for row in declared:
        if (not isinstance(row, dict) or set(row) - {"scene_id", "needs", "recipe"}
                or not {"scene_id", "needs"} <= set(row)):
            raise ValueError("Scene route requires scene_id and needs")
        ident, needs = row["scene_id"], row["needs"]
        if (not isinstance(ident, str) or ident in by_id or not isinstance(needs, list)
                or not 1 <= len(needs) <= 8 or len(set(needs)) != len(needs)
                or set(needs) - NEEDS):
            raise ValueError("Invalid scene route or capabilities")
        if "preserve" in needs and len(needs) != 1:
            raise ValueError("Preserve cannot silently coexist with effects")
        if "recipe" in row and "motion_graphic_2d" not in needs:
            raise ValueError("Recipe belongs only to local motion_graphic_2d")
        by_id[ident] = row
    if set(by_id) != {s["id"] for s in manifest["scenes"]}:
        raise ValueError("Scene route IDs must match reference inventory exactly")
    return by_id


def validate_local_recipe(recipe, scene, fps):
    """Authorial recipe must fit the scene without retiming, fonts or hidden resources."""
    from .motionlab import validate_scene
    checked = validate_scene(recipe)
    if (checked.get("mode") != "2d"
            or checked["frame_count"] != scene["end_frame"] - scene["start_frame"]
            or checked["frame_count"] > 120
            or Fraction(checked["fps"]) != Fraction(fps)
            or Fraction(checked["fps"]) > 60
            or checked["width"] * checked["height"] > 1280 * 720
            or checked.get("background") is not None or checked.get("fonts")):
        raise ValueError("Local motion needs an exact-clock, no-font transparent 2D recipe <=120 frames")
    return checked


def route_scenes(manifest, spec, *, readiness, measured_scene_ids=()):
    directives = validate_choices(manifest, spec)
    if not isinstance(readiness, dict) or set(readiness) - set(BACKENDS.values()):
        raise ValueError("Only known server-side readiness probes are accepted")
    measured = set(measured_scene_ids)
    if measured - set(directives):
        raise ValueError("Unknown measured scene ID")
    result = []
    for scene in manifest["scenes"]:
        d = directives[scene["id"]]
        operations = []
        for need in d["needs"]:
            if need == "preserve":
                operations.append({"need": need, "backend": None, "status": "authored_preservation",
                                   "execution": "not_executed", "evidence": "explicit_directive"})
                continue
            backend = BACKENDS[need]
            p = readiness.get(backend, {"available": False, "evidence": "not_probed"})
            status = "awaiting_authored_resources" if p.get("available") is True else "backend_unavailable"
            if need == "new_actor_performance":
                status = "external_generation_requires_user_authorization"
            elif need == "temporal_occlusion":
                status = "awaiting_temporal_mask_evidence"
            elif need == "measured_motion_2d":
                status = "measurement_not_applied" if scene["id"] in measured else "awaiting_valid_tracking"
            elif need == "motion_graphic_2d" and p.get("available") is True and "recipe" in d:
                validate_local_recipe(d["recipe"], scene, manifest["fps"])
                status = "ready_local_production"
            operations.append({"need": need, "backend": backend, "status": status,
                               "execution": "not_executed",
                               "evidence": str(p.get("evidence", "not_probed"))[:100]})
        entry = {"scene_id": scene["id"],
                 "frame_range": [scene["start_frame"], scene["end_frame"]],
                 "operations": operations,
                 "quality_gate": "pending",
                 "status": "ready_local_step" if any(x["status"] == "ready_local_production" for x in operations)
                           else "pending_evidence_or_direction"}
        if "recipe" in d:
            entry.update(motion_recipe=clone(d["recipe"]),
                         motion_recipe_sha256=digest(d["recipe"]))
        result.append(entry)
    return {
        "schema": PLAN_SCHEMA, "source_sha256": manifest["source_sha256"],
        "scene_manifest_sha256": digest(manifest), "choices_sha256": digest(spec),
        "fps": manifest["fps"], "frame_count": manifest["frame_count"],
        "scenes": result, "readiness": {
            key: {"available": v.get("available") is True,
                  "evidence": str(v.get("evidence", "unknown"))[:100]}
            for key, v in readiness.items()},
        "status": "planned_not_executed", "user_approved": False,
        "limitations": ["Probes are not executed renders",
                        "Only explicit bounded Motion Lab 2D may run locally from this router",
                        "No paid VIDEOAPI generation, actor swap or automatic visual approval"],
    }
