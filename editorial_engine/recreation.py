"""Plan independent performer recreation without inventing media or perception.

The author supplies temporal requirements. This module checks their consequences:
a new performance needs a new video from frame zero, and geometry is measured on
that video. Hashes and lineage declarations catch known reuse; neither identifies
a person, detects motion semantics, nor proves that a provider used no hidden input.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import re

from .contracts import (ValidationError, clone, digest, index_by_id, integer,
                        mapping, nonempty, provenance, require, sequence, sha256,
                        strings, verify_file)
from .production import production_request


SPEC_SCHEMA = "independent-recreation-spec/1"
PLAN_SCHEMA = "independent-recreation/1"
ROLES = ("base_video", "transformed_image_or_video", "tracking",
         "subject_alignment", "occlusion", "composition")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
_KINDS = {"base_video": {"video"}, "tracking": {"planar_tracking", "pose"},
          "subject_alignment": {"json"}, "occlusion": {"mattes"},
          "composition": {"video"}}
_DEPENDENCIES = {"base_video": [], "transformed_image_or_video": [],
                 "tracking": ["base_video"],
                 "subject_alignment": ["base_video", "transformed_image_or_video", "tracking"],
                 "occlusion": ["base_video", "tracking"],
                 "composition": ["base_video", "transformed_image_or_video", "tracking",
                                 "subject_alignment", "occlusion"]}


def _dependencies(spec, role):
    if role == "transformed_image_or_video" and spec["transformation"]["motion"] == "temporal_performance":
        return ["base_video"]
    return list(_DEPENDENCIES[role])


def _id(value, path):
    nonempty(value, path)
    require(bool(_IDENTIFIER.fullmatch(value)) and ".." not in value,
            "recreation_id", "Use a short identifier without paths or whitespace", path)
    return value


def _rate(value, path):
    nonempty(value, path)
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as error:
        raise ValidationError("recreation_clock", "Use a rational FPS string", path) from error
    require(0 < result <= 240, "recreation_clock", "FPS must be positive and at most 240", path)
    return result


def _range(value, count, path):
    item = mapping(value, path)
    first = integer(item.get("start_frame"), path + ".start_frame")
    last = integer(item.get("end_frame"), path + ".end_frame", minimum=1)
    require(first < last <= count, "recreation_interval",
            "Use a nonempty half-open interval within the planned clock", path)
    return first, last


def _file(item, path, verify):
    name = nonempty(item.get("path"), path + ".path")
    require(Path(name).is_absolute(), "recreation_path", "Use an absolute local file path", path)
    sha256(item.get("sha256"), path + ".sha256")
    if verify:
        verify_file(name, item["sha256"], path)


def _spec(raw, verify_files):
    data = clone(mapping(raw, "spec"))
    require(data.get("schema") == SPEC_SCHEMA, "recreation_schema", "Expected " + SPEC_SCHEMA)
    _id(data.get("id"), "spec.id")
    integer(data.get("revision"), "spec.revision", minimum=1)
    provenance(data.get("author"), "spec.author", kinds={"human", "model"})
    clock = mapping(data.get("clock"), "spec.clock")
    _rate(clock.get("fps"), "spec.clock.fps")
    for key in ("width", "height", "frame_count"):
        integer(clock.get(key), "spec.clock." + key, minimum=1)
    ref = mapping(data.get("reference"), "spec.reference")
    _id(ref.get("id"), "spec.reference.id")
    sha256(ref.get("sha256"), "spec.reference.sha256")
    _id(ref.get("character_id"), "spec.reference.character_id")
    if "path" in ref:
        _file(ref, "spec.reference", verify_files)
    derived = data.setdefault("known_reference_derivative_sha256s", [])
    for index, value in enumerate(strings(derived, "spec.known_reference_derivative_sha256s")):
        sha256(value, f"spec.known_reference_derivative_sha256s[{index}]")
    identity_refs = index_by_id(data.setdefault("identity_references", []), "spec.identity_references")
    for key, item in identity_refs.items():
        _id(key, "identity_reference.id")
        require(item.get("kind") == "image", "recreation_identity", "Identity references must be images")
        _file(item, "identity_references." + key, verify_files)
        require(item["sha256"] not in {ref["sha256"], *derived}, "recreation_reference_pixels",
                "A replacement identity reference cannot reuse known reference bytes", key)
    target = data.setdefault("target_character", None)
    if target is not None:
        mapping(target, "spec.target_character")
        _id(target.get("id"), "spec.target_character.id")
        require(target["id"] != ref["character_id"], "recreation_same_character",
                "The replacement needs its own declared character identity")
        if target.get("identity") is not None:
            nonempty(target["identity"], "spec.target_character.identity")
        for reference_id in strings(target.setdefault("reference_ids", []), "target_character.reference_ids"):
            require(reference_id in identity_refs, "recreation_identity_reference",
                    "Identity reference is not supplied", reference_id)
    performance = index_by_id(data.setdefault("performance", []), "spec.performance")
    for key, item in performance.items():
        _id(key, "performance.id")
        nonempty(item.get("description"), "performance.description")
        require(item.get("scope") in {"continuous_video", "sampled_frames", "human_note", "user_instruction"},
                "recreation_scope", "Declare the actual scope of the authored temporal requirement", key)
        _range(item, clock["frame_count"], "performance." + key)
        strings(item.setdefault("evidence_ids", []), "performance.evidence_ids")
    transform = mapping(data.get("transformation"), "spec.transformation")
    require(transform.get("motion") in {"static_overlay", "temporal_performance", "unknown"},
            "recreation_motion", "Declare static_overlay, temporal_performance or unknown")
    nonempty(transform.get("description"), "spec.transformation.description")
    intervals = sequence(transform.get("intervals"), "spec.transformation.intervals")
    require(bool(intervals), "recreation_interval", "Declare when the transformed subject is visible")
    previous = 0
    for index, interval in enumerate(intervals):
        first, last = _range(interval, clock["frame_count"], f"transformation.intervals[{index}]")
        require(first >= previous, "recreation_interval", "Visible intervals must be ordered and disjoint")
        previous = last
    if "alignment" in data:
        mapping(data["alignment"], "spec.alignment")
    return data


def _coverage(asset, intervals, clock, path):
    require(_rate(asset.get("fps"), path + ".fps") == _rate(clock["fps"], "clock.fps"),
            "recreation_clock", "Conform FPS explicitly before binding media", path)
    count = integer(asset.get("frame_count"), path + ".frame_count", minimum=1)
    covered = sequence(asset.get("coverage"), path + ".coverage")
    require(bool(covered), "recreation_coverage", "Declare actual media coverage", path)
    spans, previous = [], 0
    for index, part in enumerate(covered):
        first, last = _range(part, clock["frame_count"], f"{path}.coverage[{index}]")
        source_first = integer(part.get("source_start_frame"), path + ".source_start_frame")
        require(source_first + last - first <= count, "recreation_coverage",
                "Coverage exceeds available source frames", path)
        require(first >= previous, "recreation_coverage", "Coverage must be ordered and disjoint", path)
        previous = last
        spans.append((first, last))
    for wanted in intervals:
        cursor = wanted["start_frame"]
        for first, last in spans:
            if last <= cursor:
                continue
            if first > cursor:
                break
            cursor = max(cursor, last)
            if cursor >= wanted["end_frame"]:
                break
        require(cursor >= wanted["end_frame"], "recreation_coverage",
                "Media must cover every required frame, including the opening at frame zero", path)


def _origin(asset, spec, path):
    origin = provenance(asset.get("provenance"), path + ".provenance")
    require(origin.get("simulated", False) is False, "recreation_simulated",
            "A simulated result cannot satisfy an actual recreation resource", path)
    require(origin.get("origin") in {"independent_generation", "new_recording", "independent_asset", "new_composite"},
            "recreation_reference_pixels", "Declare independently produced source material", path)
    require(origin.get("reference_pixels_used") is False, "recreation_reference_pixels",
            "Reference photography must not be present in replacement media", path)
    ancestors = strings(origin.get("ancestor_sha256s"), path + ".provenance.ancestor_sha256s")
    for value in ancestors:
        sha256(value, path + ".provenance.ancestor_sha256s")
    forbidden = {spec["reference"]["sha256"], *spec["known_reference_derivative_sha256s"]}
    require(not forbidden.intersection({asset["sha256"], *ancestors}), "recreation_reference_pixels",
            "Known reference bytes or descendants cannot serve as replacement media", path)


def _media(asset, verify_files, clock):
    if not verify_files:
        return
    if asset["kind"] == "video":
        from .generation.ingest import _probe
        measured = _probe(Path(asset["path"]))
        require(measured["clock"] == "cfr" and measured["frame_count"] == asset["frame_count"]
                and Fraction(measured["fps"]) == Fraction(asset["fps"]),
                "recreation_media_clock", "Declared video clock differs from decoded media", asset["id"])
        if asset["role"] in {"base_video", "composition"}:
            require(measured["width"] == clock["width"] and measured["height"] == clock["height"],
                    "recreation_raster", "Conform the base/output raster explicitly before adoption", asset["id"])
    elif asset["kind"] == "image":
        from PIL import Image
        try:
            with Image.open(asset["path"]) as image:
                image.verify()
        except (OSError, ValueError) as error:
            raise ValidationError("recreation_image", "Image could not be decoded", asset["id"]) from error


def _assets(raw, spec, verify_files):
    assets = clone(sequence(raw, "assets"))
    indexed = index_by_id(assets, "assets")
    by_role = {}
    full = [{"start_frame": 0, "end_frame": spec["clock"]["frame_count"]}]
    for key, asset in indexed.items():
        _id(key, "assets.id")
        role = asset.get("role")
        require(isinstance(role, str) and role in ROLES and role not in by_role, "recreation_role",
                "Supply at most one actual resource for each recreation role", key)
        require(asset.get("status", "ready") == "ready", "recreation_asset_status",
                "Omit missing resources; the plan keeps their needs open", key)
        if role == "transformed_image_or_video":
            motion = spec["transformation"]["motion"]
            require(motion != "unknown", "recreation_motion", "Choose the transformed content's motion before adoption")
            allowed = {"video"} if motion == "temporal_performance" else {"image", "video"}
        else:
            allowed = _KINDS[role]
        require(isinstance(asset.get("kind"), str) and asset["kind"] in allowed, "recreation_media_kind",
                "This role requires " + "/".join(sorted(allowed)), key)
        _file(asset, "assets." + key, verify_files)
        by_role[role] = asset
        if role in {"base_video", "transformed_image_or_video", "composition"}:
            target = spec["target_character"]
            require(target is not None and bool(target.get("identity")), "recreation_identity_needed",
                    "Choose the new character before accepting its media", key)
            require(asset.get("character_id") == target["id"], "recreation_character",
                    "Media must name the planned replacement character", key)
            _origin(asset, spec, "assets." + key)
            if asset["kind"] == "video":
                temporal = role != "transformed_image_or_video" or spec["transformation"]["motion"] == "temporal_performance"
                allowed_performance = {"temporal_video"} if temporal else {"temporal_video", "animated_still"}
                require(asset.get("performance_kind") in allowed_performance, "recreation_still_performance",
                        "An animated still satisfies only an explicitly selected static overlay", key)
                required = spec["transformation"]["intervals"] if role == "transformed_image_or_video" else full
                _coverage(asset, required, spec["clock"], "assets." + key)
        _media(asset, verify_files, spec["clock"])
    base = by_role.get("base_video")
    if spec["transformation"]["motion"] == "temporal_performance" and "transformed_image_or_video" in by_role:
        transformed = by_role["transformed_image_or_video"]
        require(base is not None and transformed.get("performance_source_sha256") == base["sha256"],
                "recreation_performance_source", "Bind transformed motion to the actual new base performance")
    for role in ("tracking", "subject_alignment", "occlusion"):
        if role not in by_role:
            continue
        asset = by_role[role]
        require(base is not None, "recreation_base_needed", "Measure geometry on the actual new base video", role)
        binding = mapping(asset.get("source_binding"), role + ".source_binding")
        require(binding.get("asset_id") == base["id"] and binding.get("source_sha256") == base["sha256"]
                and binding.get("frame_count") == base["frame_count"]
                and binding.get("fps") == base["fps"], "recreation_reanchor",
                "Tracking, alignment and mattes must bind to the current new performance video", role)
        require(asset.get("reanchored") is True, "recreation_reanchor",
                "Declare geometry newly measured or reanchored on the replacement footage", role)
        _coverage(asset, full, spec["clock"], role)
        if role in {"subject_alignment", "occlusion"}:
            tracking = by_role.get("tracking")
            require(tracking is not None and asset.get("tracking_sha256") == tracking["sha256"],
                    "recreation_tracking_needed", "Bind to the current replacement tracking", role)
        if role == "subject_alignment":
            transformed = by_role.get("transformed_image_or_video")
            require(transformed is not None and asset.get("transformed_sha256") == transformed["sha256"],
                    "recreation_alignment_source", "Alignment must identify the transformed media it fits", role)
    if "composition" in by_role:
        output = by_role["composition"]
        expected = {by_role[role]["sha256"] for role in _DEPENDENCIES["composition"] if role in by_role}
        require(all(role in by_role for role in _DEPENDENCIES["composition"]),
                "recreation_composition_dependencies", "Composition requires all actual replacement layers")
        supplied = strings(output.get("dependency_sha256s"), "composition.dependency_sha256s")
        require(set(supplied) == expected, "recreation_composition_dependencies",
                "Composition dependency hashes must match every current layer")
    return assets, by_role


def _instructions(spec, role):
    target = spec["target_character"]
    identity = target.get("identity") if target else None
    clock = spec["clock"]
    duration = float(Fraction(clock["frame_count"], 1) / Fraction(clock["fps"]))
    actions = "; ".join(f"frames [{item['start_frame']}, {item['end_frame']}): {item['description']}"
                        for item in spec["performance"])
    if role == "base_video":
        return (f"Produce an independent, clean performance video of {identity or '[replacement identity still needed]'}. "
                f"Deliver {duration:g} seconds, {clock['frame_count']} frames at {clock['fps']} fps, "
                f"{clock['width']}x{clock['height']}. The new performer is present from frame zero. "
                f"Performance direction: {actions or '[temporal direction still needed]'}. "
                "Use actual temporal hand, head and body performance. An animated photograph does not satisfy this need. "
                "Use the reference only as attributed editing/action direction; do not reuse its photographed person, "
                "background frames or recovered hidden regions. Keep the base clean for later transformation, tracking and occlusion. "
                "Export the prompt for the selected tool; the prompt itself does not configure or call a provider.")
    if role == "transformed_image_or_video":
        return (f"Create the transformed appearance of the same replacement character ({identity or '[identity needed]'}): "
                f"{spec['transformation']['description']}. Declared motion: {spec['transformation']['motion']}. "
                "Match the intended head, shoulders, torso, framing and viewpoint. Produce temporal video when the content "
                "changes pose, expression or view independently; static artwork is only an explicitly selected overlay. "
                "Do not recover the original performer's photographic pixels. Final fit is measured against the new base.")
    if role == "tracking":
        return ("Measure the new base video across its full clock: hands and effect triggers, head/neck, shoulders and torso, "
                "plus the portal or other effect anchors. Reanchor on the actual new footage. Reference geometry provides "
                "direction or timing, never measured coordinates for another person. Record confidence and occluded/unsolved intervals.")
    if role == "subject_alignment":
        return ("Fit the transformed head, shoulders and torso to the newly tracked performer, with uniform scale and "
                "translation unless an explicitly justified warp is needed. Preserve aspect ratio. Measure the scale/pivot "
                "on corresponding anatomy, apply the authored setback and validate several frames. Layer setback is an "
                "image-plane placement adjustment, not a recovered 3D camera distance. Export the fit report and its source hashes.")
    if role == "occlusion":
        return ("Prepare new foreground/hand mattes from the new base video on the same viewport and clock. "
                "Validate the front/behind order throughout movement. Keep gaps and low-confidence regions explicit.")
    return ("Compose the independent base, transformed content, new tracking, subject alignment and new occlusion "
            "across the full timeline from frame zero. Preserve effect cadence while reanchoring to the new performer. "
            "Audio remains a separately authored choice. Deliver a preview and continuous visual review; technical "
            "checks do not establish identity, natural motion, aesthetic acceptance or user approval.")


def build_plan(spec, assets=None, *, verify_files=False):
    """Build a reviewable, provider-neutral dependency plan from authored needs.

    Missing identity, movement decisions or media remain blocking issues. Present
    resources must satisfy their assigned role; they cannot silently fall back to
    reference photography or a still. No perception, generation or render occurs.
    """
    require(type(verify_files) is bool, "type", "verify_files must be boolean")
    spec = _spec(spec, verify_files)
    assets, by_role = _assets([] if assets is None else assets, spec, verify_files)
    issues = []
    target = spec["target_character"]
    if target is None or not target.get("identity"):
        issues.append({"code": "target_identity_needed", "message": "Choose or describe the replacement character.",
                       "roles": ["base_video", "transformed_image_or_video"], "blocking": True})
    if not spec["performance"]:
        issues.append({"code": "performance_direction_needed", "message": "Author the required hand, head and body performance.",
                       "roles": ["base_video"], "blocking": True})
    if spec["transformation"]["motion"] == "unknown":
        issues.append({"code": "transformation_motion_needed", "message": "Choose static artwork or temporal transformed performance.",
                       "roles": ["transformed_image_or_video"], "blocking": True})
    if any(item["scope"] == "sampled_frames" for item in spec["performance"]):
        issues.append({"code": "motion_observation_incomplete", "message": "Frame samples describe authored needs; they do not prove continuous motion.",
                       "roles": ["base_video"], "blocking": False})
    steps = []
    for role in ROLES:
        needs = _dependencies(spec, role)
        blocked = [dependency for dependency in needs if dependency not in by_role]
        blocked.extend(issue["code"] for issue in issues if issue["blocking"] and role in issue["roles"])
        media = by_role.get(role)
        kinds = (["video"] if spec["transformation"]["motion"] == "temporal_performance"
                 else ["image", "video"] if spec["transformation"]["motion"] == "static_overlay" else [])
        if role != "transformed_image_or_video":
            kinds = sorted(_KINDS[role])
        steps.append({"id": role, "status": "supplied_unreviewed" if media else "needed",
                      "acceptable_kinds": kinds, "dependencies": list(needs), "blocked_by": blocked,
                      "asset_id": media["id"] if media else None,
                      "required_intervals": clone(spec["transformation"]["intervals"] if role == "transformed_image_or_video"
                                                  else [{"start_frame": 0, "end_frame": spec["clock"]["frame_count"]}]),
                      "instructions": _instructions(spec, role)})
    data = {"schema": PLAN_SCHEMA, "id": spec["id"], "revision": spec["revision"],
            "spec": spec, "spec_sha256": digest(spec), "assets": assets, "steps": steps,
            "issues": issues, "verification": {"automatic_semantic_detection": False,
                "identity_verified": False, "source_independence": "declared_lineage_only",
                "continuous_visual_review": "pending", "user_approval": "pending",
                "provider_called": False, "rendered_by_this_module": False}}
    data["plan_sha256"] = digest(data)
    return data


def validate_plan(plan, *, verify_files=False):
    """Recompute all derived readiness and dependencies; attestations stay claims."""
    data = clone(mapping(plan, "plan"))
    require(data.get("schema") == PLAN_SCHEMA, "recreation_schema", "Expected " + PLAN_SCHEMA)
    expected = build_plan(data.get("spec"), data.get("assets"), verify_files=verify_files)
    require(data == expected, "recreation_plan_changed", "Rebuild the plan after changing its inputs or derived fields")
    return data


def production_requests(plan, *, verify_files=False):
    """Return genuine production-request/1 records, without fabricated bindings.

    Geometry requests appear after the real base exists. Alignment is a local JSON
    task in ``steps`` because production's output contract does not include JSON.
    All tasks, including these temporarily unexportable ones, remain in the plan.
    """
    plan = validate_plan(plan, verify_files=verify_files)
    spec = plan["spec"]
    assets = {asset["role"]: asset for asset in plan["assets"]}
    identity = {item["id"]: item for item in spec["identity_references"]}
    requests = []
    clock = spec["clock"]
    constraints = {key: clock[key] for key in ("width", "height", "fps", "frame_count")}
    for step in plan["steps"]:
        role = step["id"]
        if step["status"] != "needed" or role == "subject_alignment":
            continue
        if role == "transformed_image_or_video" and spec["transformation"]["motion"] == "unknown":
            continue
        if role in {"tracking", "occlusion"} and "base_video" not in assets:
            continue
        input_assets = [assets[dependency] for dependency in step["dependencies"] if dependency in assets]
        if role in {"base_video", "transformed_image_or_video"} and spec["target_character"]:
            input_assets += [identity[key] for key in spec["target_character"]["reference_ids"]]
        inputs = [{key: item[key] for key in ("id", "kind", "path", "sha256")} for item in input_assets]
        # A source reference is deliberately absent from pixel-bearing inputs.
        source_binding = None
        output_kind, operation = "video", "external_video"
        task_constraints = clone(constraints)
        if role == "transformed_image_or_video" and spec["transformation"]["motion"] == "static_overlay":
            output_kind, operation = "image", "chat_image"
            task_constraints = {key: clock[key] for key in ("width", "height")}
        elif role in {"tracking", "occlusion"}:
            output_kind = operation = "planar_tracking" if role == "tracking" else "mattes"
            task_constraints["full_coverage"] = True
            base = assets["base_video"]
            source_binding = {"input_id": base["id"], "source_sha256": base["sha256"],
                              "fps": base["fps"], "frame_count": base["frame_count"]}
        elif role == "composition":
            operation = "manual_asset"
        requests.append(production_request(
            spec["id"][:50] + "-" + digest(spec["id"])[:8] + "-" + role,
            operation, prompt=step["instructions"], output_kind=output_kind,
            inputs=inputs, source_binding=source_binding, constraints=task_constraints,
            parameters={"role": role, "required_intervals": step["required_intervals"],
                        "alignment_direction": clone(spec.get("alignment", {}))},
            context={"recreation_plan_sha256": plan["plan_sha256"], "recreation_role": role,
                     "target_character": clone(spec["target_character"]), "reference_sha256": spec["reference"]["sha256"],
                     "reference_use": "direction_only", "identity_verified": False},
            unresolved=list(step["blocked_by"]), revision=spec["revision"]))
    return requests


def generation_context(plan, *, verify_files=False):
    """Small attributed context for the existing generation director/compiler."""
    data = validate_plan(plan, verify_files=verify_files)
    return {"schema": "independent-recreation-context/1", "plan_sha256": data["plan_sha256"],
            "target_character": clone(data["spec"]["target_character"]),
            "clock": clone(data["spec"]["clock"]), "performance": clone(data["spec"]["performance"]),
            "steps": clone(data["steps"]), "issues": clone(data["issues"]),
            "reference_use": "direction_only", "base_video_from_frame_zero": True,
            "new_footage_requires_new_tracking": True, "verification": clone(data["verification"])}


def validate_generation_assets(plan, generation_plan, *, verify_files=False):
    """Validate the optional generation extension, without recursive validation.

    The surrounding generation validator checks its own schema. This extension
    names its stage, so a prompt producing the base never conditions on that same
    missing result. Dependencies may still be needed in a draft. Actual adoption
    remains subject to this module's temporal, lineage and binding checks.
    """
    recreation = validate_plan(plan, verify_files=verify_files)
    generated = clone(mapping(generation_plan, "generation_plan"))
    extension = mapping(generated.get("recreation"), "generation_plan.recreation")
    require(extension.get("plan") == recreation, "recreation_generation_plan",
            "Bind the exact current recreation plan, including its assets and gaps")
    stage = extension.get("stage")
    require(stage in {"base_video", "transformed_image_or_video", "composition"},
            "recreation_generation_stage", "Declare which independent recreation stage these clips produce")
    target = recreation["spec"]["target_character"]
    target_id = target["id"] if target is not None else None
    require(extension.get("character_id") == target_id, "recreation_character",
            "Generation stage and recreation target identities disagree")
    if target and target.get("identity"):
        bible = mapping(generated.get("bible"), "bible")
        characters = index_by_id(bible.get("characters"), "bible.characters")
        require(target_id in characters and characters[target_id].get("identity") == target["identity"],
                "recreation_character", "Preserve the exact replacement identity declaration in the generation bible")
        source_character = recreation["spec"]["reference"]["character_id"]
        for clip in sequence(generated.get("clips"), "clips"):
            names = strings(clip.get("character_ids"), "clip.character_ids")
            require(target_id in names and source_character not in names, "recreation_character",
                    "Every recreation clip must perform with the replacement character")
    if stage == "base_video":
        duration = Fraction(recreation["spec"]["clock"]["frame_count"], 1) / Fraction(recreation["spec"]["clock"]["fps"])
        brief = mapping(generated.get("brief"), "brief")
        require(Fraction(str(brief.get("target_duration_s"))) == duration, "recreation_coverage",
                "The base generation must cover the complete planned timeline from frame zero")
    mapped = {}
    known = {asset["role"]: asset for asset in recreation["assets"]}
    steps = {step["id"]: step for step in recreation["steps"]}
    forbidden = {recreation["spec"]["reference"]["sha256"],
                 *recreation["spec"]["known_reference_derivative_sha256s"]}
    for asset in sequence(generated.get("assets"), "assets"):
        if asset.get("kind") in {"video", "image"} and asset.get("status") == "ready":
            require(asset.get("sha256") not in forbidden, "recreation_reference_pixels",
                    "Reference photography cannot be a generation media input", asset.get("id", ""))
        role = asset.get("recreation_role")
        if role is None:
            continue
        require(role in {"base_video", "transformed_image_or_video"} and role not in mapped,
                "recreation_generation_role", "Map each independent source layer once")
        require(asset["kind"] in steps[role]["acceptable_kinds"], "recreation_media_kind",
                "Generation asset does not satisfy the required independent media kind", asset["id"])
        if asset["status"] == "ready":
            require(role in known and asset["sha256"] == known[role]["sha256"]
                    and asset["path"] == known[role]["path"], "recreation_generation_media",
                    "Ready generation media must first be adopted with independent recreation provenance", asset["id"])
        else:
            require(asset["route"] != "reuse", "recreation_reference_pixels",
                    "Missing independent media cannot be fulfilled by reference reuse", asset["id"])
        mapped[role] = asset
    required = {role for role in _dependencies(recreation["spec"], stage)
                if role in {"base_video", "transformed_image_or_video"}}
    require(required <= set(mapped), "recreation_generation_mapping",
            "Explicitly map the independent source media required by this stage")
    for clip in sequence(generated.get("clips"), "clips"):
        for condition in sequence(clip.get("conditioning"), "clip.conditioning"):
            require(not (stage in mapped and condition.get("asset_id") == mapped[stage]["id"]
                         and mapped[stage]["status"] == "needed"), "recreation_generation_cycle",
                    "A stage cannot condition on its own missing output")
    return generated
