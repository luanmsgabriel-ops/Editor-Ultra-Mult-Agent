"""Compile authored direction into portable, independently usable clip prompts.

This module formats supplied creative decisions. It neither translates their
meaning nor calls a generator. Capability profiles are dated declarations;
``ready`` means the declared export prerequisites passed, not that a provider
accepted the request or that the eventual video is visually approved.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from fractions import Fraction
import json
from pathlib import Path
import re
import subprocess

from ..contracts import (ValidationError, clone, digest, integer, mapping,
                         nonempty, number, require, sequence, strings, verify_file)
from .contracts import (ROLES, assembly_timing, clip_fingerprint, effective_states,
                        validate_plan)

PROFILE_SCHEMA = "video-generation-capabilities/1"
PACK_SCHEMA = "video-prompt-pack/1"


def validate_profile(profile: dict) -> dict:
    """Validate a declaration without contacting its source or assuming freshness."""
    data = clone(mapping(profile, "profile"))
    require(data.get("schema") == PROFILE_SCHEMA, "profile_schema", "Unsupported capability profile")
    for key in ("id", "tool", "model", "mode", "interface"):
        nonempty(data.get(key), "profile." + key)
    verification = mapping(data.get("verification"), "profile.verification")
    require(verification.get("status") in {"verified", "unverified"}, "profile_verification",
            "Declare verified or unverified", "profile.verification.status")
    for field in ("source", "checked_at"):
        require(isinstance(verification.get(field), str), "profile_verification",
                "Use a string; an unverified profile may leave it empty", "profile.verification." + field)
    if verification["status"] == "verified":
        nonempty(verification["source"], "profile.verification.source")
        nonempty(verification["checked_at"], "profile.verification.checked_at")
    if verification["checked_at"]:
        try:
            date.fromisoformat(verification["checked_at"])
        except ValueError as exc:
            raise ValidationError("profile_date", "Use an ISO date YYYY-MM-DD", "profile.verification.checked_at") from exc
        require(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", verification["checked_at"])),
                "profile_date", "Use an ISO date YYYY-MM-DD", "profile.verification.checked_at")
    require(("durations_s" in data) != ("duration_range_s" in data), "profile_duration",
            "Declare either durations_s or duration_range_s, not both", "profile")
    if "durations_s" in data:
        durations = sequence(data["durations_s"], "profile.durations_s")
        require(bool(durations), "profile_duration", "Declare at least one duration", "profile.durations_s")
        for value in durations:
            require(number(value, "profile.durations_s", minimum=0) > 0,
                    "profile_duration", "Durations must be positive")
        require(len(set(durations)) == len(durations), "profile_duration", "Duplicate durations")
    else:
        bounds = mapping(data["duration_range_s"], "profile.duration_range_s")
        low = number(bounds.get("min"), "profile.duration_range_s.min", minimum=0)
        high = number(bounds.get("max"), "profile.duration_range_s.max", minimum=0)
        require(0 < low <= high, "profile_duration", "Use a positive, ordered duration range")
    ratios = strings(data.get("aspect_ratios"), "profile.aspect_ratios", allow_empty=False)
    require(all(re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", ratio) for ratio in ratios),
            "profile_ratio", "Use width:height ratios", "profile.aspect_ratios")
    require("max_prompt_chars" in data, "profile_prompt_limit", "Declare a character limit or null")
    if data["max_prompt_chars"] is not None:
        integer(data["max_prompt_chars"], "profile.max_prompt_chars", minimum=1)
    inputs = mapping(data.get("inputs"), "profile.inputs")
    for role, capability in inputs.items():
        require(role in ROLES, "profile_role", "Unknown input role " + role, "profile.inputs")
        cp = "profile.inputs." + role
        mapping(capability, cp)
        require(type(capability.get("supported")) is bool, "profile_support",
                "Input support must be an explicit boolean", cp)
        count = integer(capability.get("max_count"), cp + ".max_count")
        require((capability["supported"] and count > 0) or (not capability["supported"] and count == 0),
                "profile_count", "Supported roles need a positive count; unsupported roles need zero", cp)
        require(isinstance(capability.get("field"), str), "profile_field", "Declare the interface field", cp)
        if capability["supported"]:
            nonempty(capability["field"], cp + ".field")
    outputs = mapping(data.get("outputs"), "profile.outputs")
    for key in ("audio", "speech"):
        require(type(outputs.get(key)) is bool, "profile_output", "Declare explicit output booleans", "profile.outputs." + key)
    require(not outputs["speech"] or outputs["audio"], "profile_output", "Speech output requires audio output")
    require("multi_shot" in data and (data["multi_shot"] is None or type(data["multi_shot"]) is bool),
            "profile_multi_shot", "Declare multi_shot true, false or null")
    if "extension_output" in data:
        require(data["extension_output"] in {"appended_clip", "full_sequence", "unknown"},
                "extension_output", "Declare appended_clip, full_sequence or unknown")
    return data


def _issue(code, message, path="", *, blocking=True):
    return {"code": code, "message": message, "path": path, "blocking": blocking}


def _file_issue(item, path):
    try:
        require(Path(item["path"]).is_absolute(), "absolute_path", "Expected an absolute local path", path)
        verify_file(item["path"], item["sha256"], path)
    except (ValueError, OSError) as exc:
        return _issue("file_unverified", str(exc), path)
    return None


def _media_issue(item, path):
    """Probe the declared media kind, not its semantics or perceptual quality."""
    try:
        if item["kind"] == "image":
            from PIL import Image
            with Image.open(item["path"]) as image:
                image.verify()
            with Image.open(item["path"]) as image:
                image.load()
                require(image.width > 0 and image.height > 0, "image_dimensions", "Image has no pixels", path)
        elif item["kind"] in {"video", "audio"}:
            result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
                                     "-of", "json", item["path"]], capture_output=True, text=True,
                                    check=True, timeout=20)
            streams = json.loads(result.stdout).get("streams", [])
            require(any(s.get("codec_type") == item["kind"] for s in streams),
                    "media_stream", "The declared media stream is absent", path)
    except (ValueError, OSError, ImportError, subprocess.SubprocessError) as exc:
        return _issue("media_unverified", "Media format verification failed: " + str(exc), path)
    return None


def _language_issues(brief):
    review = brief.get("language_review")
    if not isinstance(review, dict):
        return [_issue("language_review_missing", "Review the authored direction and literal dialogue in the requested languages; the compiler does not translate.", "brief.language_review")]
    valid = all(isinstance(review.get(key), str) and review[key].strip() for key in ("actor", "method"))
    valid = valid and all(review.get(key) == brief[key] for key in ("instruction_language", "dialogue_language"))
    if not valid:
        return [_issue("language_review_mismatch", "Language review must identify actor/method and match both requested languages.", "brief.language_review")]
    return []


def _return_map(returns):
    if returns is None:
        return {}
    if isinstance(returns, dict) and returns.get("schema") == "video-generation-result/1":
        returns = [returns]
    if isinstance(returns, list):
        result = {}
        for receipt in returns:
            mapping(receipt, "returns")
            key = nonempty(receipt.get("clip_id"), "returns.clip_id")
            require(key not in result, "duplicate_return", "Only one current receipt per clip", key)
            result[key] = receipt
        return result
    result = mapping(returns, "returns")
    for key, value in result.items():
        mapping(value, "returns." + key)
        require(value.get("clip_id") == key, "return_identity", "Return map key and clip_id disagree", key)
    return result


def _validate_return(receipt, plan, clip_id):
    # Lazy import keeps neutral drafting independent of media-probe tooling.
    from .ingest import validate_receipt
    return validate_receipt(receipt, plan, clip_id=clip_id, verify_files=True)


def _returns_checked(raw, plan):
    """Check current bytes, scoped revisions and the supplied parent-result chain."""
    valid, failures = {}, {}
    known = {c["id"] for c in plan["clips"]}
    for key, receipt in raw.items():
        require(key in known, "unknown_return", "Receipt belongs to an unknown clip", "returns." + key)
        try:
            valid[key] = _validate_return(receipt, plan, key)
        except (ValueError, OSError) as exc:
            failures[key] = _issue("return_invalid", str(exc), "returns." + key)
    incoming = {j["to"]: j for j in plan["joins"] if j["strategy"] in {"observed_frame", "native_extension"}}
    for clip in plan["clips"]:
        key = clip["id"]
        if key not in valid or key not in incoming:
            continue
        parent = incoming[key]["from"]
        dependency = next((d for d in valid[key].get("dependencies", []) if d.get("clip_id") == parent), None)
        matches = parent in valid and dependency is not None
        if matches:
            selected = valid[parent].get("selected_frame") if incoming[key]["strategy"] == "observed_frame" else None
            expected = _dependency(valid[parent], selected)
            matches = all(dependency.get(field) == value for field, value in expected.items())
            if incoming[key]["strategy"] == "observed_frame":
                matches = matches and isinstance(selected, dict) and dependency.get("selected_frame") == selected
        if not matches:
            failures[key] = _issue("return_dependency_stale", "This returned clip is not bound to the current parent receipt. Reimport with the actual exported instructions and dependencies.", "returns." + key)
            del valid[key]
    return valid, failures


def _asset_attachment(asset, role, issues, origin):
    result = {"role": role, "asset_id": asset["id"], "origin": origin, "status": "needed", "field": None}
    if asset["status"] != "ready":
        issues.append(_issue("asset_needed", "Produce or supply asset " + asset["id"] + " before using this input.", "assets." + asset["id"]))
        return result
    problem = _file_issue(asset, "assets." + asset["id"]) or _media_issue(asset, "assets." + asset["id"])
    if problem:
        issues.append(problem)
        result["status"] = "unavailable"
    else:
        result.update(status="ready", path=asset["path"], sha256=asset["sha256"])
    return result


def _dependency(receipt, selected=None):
    result = {"kind": "returned_clip", "clip_id": receipt["clip_id"],
              "clip_fingerprint": receipt["clip_fingerprint"], "receipt_sha256": receipt["receipt_sha256"],
              "path": receipt["path"], "sha256": receipt["sha256"]}
    if selected:
        result["selected_frame_sha256"] = selected["sha256"]
        result["selected_frame"] = clone(selected)
    return result


def _returned_input(join, plan, valid_returns, invalid_returns, issues, profile):
    parent = join["from"]
    role = "start_frame" if join["strategy"] == "observed_frame" else "previous_video"
    attachment = {"role": role, "source_clip_id": parent, "origin": "join:" + join["id"], "status": "needed", "field": None}
    if parent in invalid_returns:
        issues.append(clone(invalid_returns[parent]))
        return attachment, None, None
    if parent not in valid_returns:
        issues.append(_issue("return_needed", "Import the actual returned video for " + parent + " before preparing this dependent clip.", "joins." + join["id"]))
        return attachment, None, None
    receipt = valid_returns[parent]
    parent_clip = next(c for c in plan["clips"] if c["id"] == parent)
    usable = receipt.get("usable", {})
    if usable.get("status") != "usable" or usable.get("covers_planned_use") is not True:
        issues.append(_issue("returned_use_unresolved", "The returned clip does not have a usable, conformed planned range. Revise the plan or conform explicitly before exporting a dependent generation.", "returns." + parent + ".usable"))
    if join["strategy"] == "observed_frame":
        selected = receipt.get("selected_frame")
        observation = receipt.get("observation")
        boundary = receipt.get("boundary", {})
        if not isinstance(selected, dict):
            issues.append(_issue("frame_selection_needed", "Select and review an actual returned frame; no last frame is selected automatically.", "returns." + parent))
            return attachment, _dependency(receipt), None
        if boundary.get("status") != "observed" or boundary.get("matches_planned_use") is not True:
            issues.append(_issue("boundary_unresolved", "The selected frame must end at the planned used boundary and have a reviewed motion window. Revise the use range explicitly when selecting an earlier frame.", "returns." + parent + ".boundary"))
        if not isinstance(observation, dict) or observation.get("scope") not in {"boundary_window", "continuous_video"}:
            issues.append(_issue("motion_observation_needed", "A still-frame observation cannot establish motion continuity. Record a boundary-window or continuous-video observation.", "returns." + parent + ".observation"))
        decision = observation.get("continuity_decision") if isinstance(observation, dict) else None
        if not isinstance(decision, dict) or decision.get("status") != "accept" or not all(
                isinstance(decision.get(field), str) and decision[field].strip() for field in ("actor", "reason")):
            issues.append(_issue("continuity_not_accepted", "A director must explicitly accept the observed boundary for this transition. Viewing a window alone is not a decision to use it; this is separate from user approval.", "returns." + parent + ".observation.continuity_decision"))
        # Ingest verifies this relationship at frame-clock precision. Check the
        # declared boundary again rather than inferring a silent trim.
        recommended = selected.get("recommended_use_end_s")
        if not isinstance(recommended, (int, float)) or abs(recommended - parent_clip["use"]["end_s"]) > 1e-7:
            issues.append(_issue("selected_frame_use_mismatch", "The selected frame's end differs from the planned use.end_s; make a new explicit plan revision.", "returns." + parent + ".selected_frame"))
        attachment.update(status="ready", path=selected["path"], sha256=selected["sha256"],
                          receipt_sha256=receipt["receipt_sha256"], frame_index=selected["index"], pts_s=selected["pts_s"])
        return attachment, _dependency(receipt, selected), clone(observation)
    output = profile.get("extension_output") if profile else None
    if output != "appended_clip":
        message = ("This profile returns a full extended sequence. An explicit assembly adapter is needed before treating it as a new independent clip."
                   if output == "full_sequence" else "Declare whether native extension returns an appended clip or a full sequence; their durations and assembly differ.")
        issues.append(_issue("extension_output_unresolved", message, "profile.extension_output"))
    actual = receipt["actual"]["duration_s"]
    if abs(actual - parent_clip["use"]["end_s"]) > 1e-7:
        issues.append(_issue("extension_boundary_mismatch", "Native extension would use the end of the returned source, which differs from the planned used end. Supply an explicitly revised source/plan.", "returns." + parent))
    attachment.update(status="ready", path=receipt["path"], sha256=receipt["sha256"], receipt_sha256=receipt["receipt_sha256"])
    return attachment, _dependency(receipt), None


def _profile_issues(profile, clip, brief, attachments):
    issues = []
    if profile is None:
        return [_issue("profile_needed", "Choose a tool/model/mode/interface profile before marking this export ready. The neutral prompt remains usable as a draft.", "profile")]
    if profile["verification"]["status"] != "verified":
        issues.append(_issue("profile_unverified", "The capability profile is declared unverified; record a source and checked date for the selected interface.", "profile.verification"))
    duration = Fraction(str(clip["duration_s"]))
    if "durations_s" in profile:
        supported = duration in {Fraction(str(d)) for d in profile["durations_s"]}
    else:
        bounds = profile["duration_range_s"]
        supported = Fraction(str(bounds["min"])) <= duration <= Fraction(str(bounds["max"]))
    if not supported:
        issues.append(_issue("duration_unsupported", "The declared profile does not support this clip's generated duration.", "clips." + clip["id"] + ".duration_s"))
    if brief["aspect_ratio"] not in profile["aspect_ratios"]:
        issues.append(_issue("aspect_ratio_unsupported", "The declared profile does not support this aspect ratio.", "brief.aspect_ratio"))
    if len(clip["shots"]) > 1 and profile["multi_shot"] is not True:
        issues.append(_issue("multi_shot_unsupported", "Multiple directed shots require an explicit multi_shot capability; do not silently merge them.", "clips." + clip["id"] + ".shots"))
    counts = Counter(a["role"] for a in attachments)
    for role, count in counts.items():
        capability = profile["inputs"].get(role)
        if capability is None:
            issues.append(_issue("input_capability_unknown", "No capability declaration exists for " + role + ".", "profile.inputs." + role))
        elif capability["supported"] is not True:
            issues.append(_issue("input_unsupported", "The declared interface does not accept " + role + ".", "profile.inputs." + role))
        elif count > capability["max_count"]:
            issues.append(_issue("input_count_exceeded", "Required " + role + " inputs exceed the declared count.", "profile.inputs." + role))
        for attachment in attachments:
            if attachment["role"] == role and capability and capability["supported"]:
                attachment["field"] = capability["field"]
    audio_execution = brief.get("audio_execution", "generation")
    if audio_execution == "generation" and clip["dialogue"]:
        if not profile["outputs"]["speech"]:
            issues.append(_issue("speech_unsupported", "This clip requests generated dialogue but the profile does not declare speech output.", "profile.outputs.speech"))
    if (audio_execution == "generation" or brief.get("require_generated_audio") is True) and not profile["outputs"]["audio"]:
        issues.append(_issue("audio_unsupported", "This export directs generated audio, but the profile does not declare audio output. Choose postproduction explicitly for a silent generator.", "profile.outputs.audio"))
    if profile["max_prompt_chars"] is None:
        issues.append(_issue("prompt_limit_unstated", "No character limit is stated in this profile; provider acceptance has not been tested.", "profile.max_prompt_chars", blocking=False))
    return issues


def _format_state(state, include_audio=True):
    return json.dumps({k: v for k, v in state.items() if include_audio or k != "audio"}, ensure_ascii=False, sort_keys=True)


def _prompt(plan, clip, incoming, outgoing, observed):
    """Use neutral field labels and preserve every authored semantic value."""
    brief, bible = plan["brief"], plan["bible"]
    audio_execution = brief.get("audio_execution", "generation")
    opening, closing = effective_states(plan, clip["id"])
    lines = ["CLIP " + clip["id"], "PURPOSE: " + clip["purpose"],
             "VISUAL STYLE: " + bible["visual_style"]]
    for invariant in bible["invariants"]:
        lines.append("CONTINUITY INVARIANT: " + invariant)
    for character in bible["characters"]:
        if character["id"] in clip["character_ids"]:
            visible_character = {k: v for k, v in character.items() if k != "voice" or audio_execution == "generation"}
            lines.append("CHARACTER " + character["id"] + ": " + json.dumps(visible_character, ensure_ascii=False, sort_keys=True))
    for key, ids in (("locations", "location_ids"), ("props", "prop_ids")):
        for item in bible[key]:
            if item["id"] in clip[ids]:
                lines.append(key.upper() + " " + item["id"] + ": " + item["description"])
    lines.append("INTENDED OPENING STATE: " + _format_state(opening, audio_execution == "generation"))
    if observed:
        visible_observation = {k: v for k, v in observed.items() if k != "audio" or audio_execution == "generation"}
        lines.append("RETURNED SOURCE OBSERVATION (attributed review, not an automatic match guarantee): " + json.dumps(visible_observation, ensure_ascii=False, sort_keys=True))
    for shot in clip["shots"]:
        lines.append(f"SHOT {shot['id']} [{shot['start_s']:g}, {shot['end_s']:g}) s — approximate direction timing")
        for key in ("intent", "action", "composition", "camera", "performance", "lighting"):
            lines.append(key.upper() + ": " + shot[key])
    if audio_execution == "generation":
        for dialogue in clip["dialogue"]:
            lines.append(f"DIALOGUE {dialogue['speaker_id']} [{dialogue['start_s']:g}, {dialogue['end_s']:g}) s; {dialogue['mode']}; delivery: {dialogue['delivery']}")
            lines.append(dialogue["text"])
        for key in ("voice_direction", "ambience", "music", "sfx"):
            lines.append("AUDIO " + key.upper() + ": " + clip["audio"][key])
    elif audio_execution == "post":
        lines.append("AUDIO WORKFLOW: approved dialogue and sound will be assembled separately; do not invent or rewrite speech.")
    lines.append("INTENDED CLOSING STATE: " + _format_state(closing, audio_execution == "generation"))
    for label, join in (("INCOMING", incoming), ("OUTGOING", outgoing)):
        if join and join["execution"] in {"generation", "hybrid"}:
            lines.append(label + " JOIN: " + join["kind"] + "; reason: " + join["rationale"])
            lines.append(label + " MATCH REQUIREMENTS: " + json.dumps(join["match"], ensure_ascii=False))
    for constraint in clip["constraints"]:
        lines.append("CONSTRAINT: " + constraint)
    if clip["post"]:
        lines.append("POSTPRODUCTION: separately specified overlays, exact typography, logos and timed effects are added after generation.")
    return "\n".join(lines)


def compile_pack(plan: dict, *, profile=None, returns=None, ready=False) -> dict:
    """Build drafts or check readiness per clip, without submitting anything.

    Missing prerequisites are reported on the affected clip. This allows the
    first clip to be ready while the next awaits its actual returned frame.
    Structurally invalid plans/profiles raise ValidationError. Neither a ready
    label nor a hash is a semantic, audiovisual or provider acceptance review.
    """
    require(type(ready) is bool, "type", "ready must be boolean")
    plan = validate_plan(plan)
    profile = validate_profile(profile) if profile is not None else None
    assets = {a["id"]: a for a in plan["assets"]}
    incoming_by_id = {j["to"]: j for j in plan["joins"]}
    outgoing_by_id = {j["from"]: j for j in plan["joins"]}
    valid_returns, invalid_returns = _returns_checked(_return_map(returns), plan)
    shared_issues = _language_issues(plan["brief"])
    for reference in plan["references"]:
        problem = _file_issue(reference, "references." + reference["id"])
        if problem:
            shared_issues.append(problem)
    compiled = []
    for clip in plan["clips"]:
        key = clip["id"]
        incoming, outgoing = incoming_by_id.get(key), outgoing_by_id.get(key)
        issues, attachments, dependencies = clone(shared_issues), [], []
        bindings = [(c["role"], c["asset_id"], "conditioning") for c in clip["conditioning"]]
        for join, role in ((incoming, "start_frame"), (outgoing, "end_frame")):
            if join and join["strategy"] == "planned_frame":
                asset_id = join["handoff_asset_id"]
                if not any(r == role and a == asset_id for r, a, _ in bindings):
                    bindings.append((role, asset_id, "join:" + join["id"]))
                boundary_ok = (clip["use"]["start_s"] == 0 if role == "start_frame" else clip["use"]["end_s"] == clip["duration_s"])
                if not boundary_ok:
                    issues.append(_issue("conditioned_frame_trimmed", "The planned edit discards the conditioned boundary frame. Revise the useful range or the continuity strategy explicitly.", "clips." + key + ".use"))
        for role, asset_id, origin in bindings:
            attachments.append(_asset_attachment(assets[asset_id], role, issues, origin))
        observed = None
        if incoming and incoming["strategy"] in {"observed_frame", "native_extension"}:
            attachment, dependency, observed = _returned_input(incoming, plan, valid_returns, invalid_returns, issues, profile)
            attachments.append(attachment)
            if dependency:
                dependencies.append(dependency)
            if incoming["strategy"] == "observed_frame" and clip["use"]["start_s"] != 0:
                issues.append(_issue("conditioned_frame_trimmed", "The used range discards the observed start frame. Revise the plan explicitly.", "clips." + key + ".use"))
        for join in (incoming, outgoing):
            if join and join["strategy"] == "prompt_only":
                issues.append(_issue("text_only_continuity", "Continuity at " + join["id"] + " is requested in text only and is not enforced by a shared image or returned video.", "joins." + join["id"], blocking=False))
        postproduction = clone(clip["post"])
        post_assets, post_asset_ids = [], set()
        for post in clip["post"]:
            if "asset_id" in post and post["asset_id"] not in post_asset_ids:
                asset = assets[post["asset_id"]]
                post_issues = []
                resource = _asset_attachment(asset, "postproduction", post_issues, "post:" + post["id"])
                for field in ("role", "field", "origin"):
                    resource.pop(field)
                resource.update(kind=asset["kind"], purpose=asset["purpose"], route=asset["route"])
                post_assets.append(resource)
                post_asset_ids.add(asset["id"])
                for problem in post_issues:
                    if problem["code"] == "asset_needed":
                        problem.update(code="post_asset_needed", blocking=False)
                    issues.append(problem)
        if outgoing and outgoing["execution"] in {"post", "hybrid"}:
            postproduction.append({"kind": "transition", "join": clone(outgoing)})
        if plan["brief"].get("audio_execution", "generation") == "post":
            postproduction.append({"kind": "audio", "dialogue": clone(clip["dialogue"]), "direction": clone(clip["audio"])})
            if any(d["mode"] == "on_camera" for d in clip["dialogue"]):
                issues.append(_issue("lip_sync_unresolved", "On-camera speech with separately assembled audio needs an explicitly supported lip-sync workflow. A voice identity reference alone does not resolve timing.", "clips." + key + ".dialogue"))
        issues.extend(_profile_issues(profile, clip, plan["brief"], attachments))
        prompt = _prompt(plan, clip, incoming, outgoing, observed)
        if profile and profile["max_prompt_chars"] is not None and len(prompt) > profile["max_prompt_chars"]:
            issues.append(_issue("prompt_too_long", f"Prompt has {len(prompt)} characters; declared limit is {profile['max_prompt_chars']}. Rewrite explicitly; no text was truncated.", "clips." + key + ".prompt"))
        status = "draft" if not ready else ("blocked" if any(i["blocking"] for i in issues) else "ready")
        result = {"clip_id": key, "clip_fingerprint": clip_fingerprint(plan, key), "status": status,
                  "prompt": prompt, "prompt_chars": len(prompt),
                  "settings": {"duration_s": clip["duration_s"], "aspect_ratio": plan["brief"]["aspect_ratio"],
                               "audio_execution": plan["brief"].get("audio_execution", "generation"),
                               "extension_output": profile.get("extension_output") if profile else None,
                               "tool": profile["tool"] if profile else None, "model": profile["model"] if profile else None,
                               "mode": profile["mode"] if profile else None, "interface": profile["interface"] if profile else None},
                  "attachments": attachments, "postproduction": postproduction, "post_assets": post_assets,
                  "dependencies": dependencies,
                  "profile_sha256": digest(profile) if profile else None, "issues": issues,
                  "language": {"requested_direction": plan["brief"]["instruction_language"],
                               "requested_dialogue": plan["brief"]["dialogue_language"],
                               "review": clone(plan["brief"].get("language_review")), "translated": False},
                  "validation_scope": "declared_contracts_and_current_file_bytes; not provider acceptance or audiovisual approval"}
        result["export_sha256"] = digest(result)
        compiled.append(result)
    statuses = {c["status"] for c in compiled}
    status = "draft" if not ready else ("ready" if statuses == {"ready"} else ("partially_ready" if "ready" in statuses else "blocked"))
    assembly = assembly_timing(plan)
    assembly.update(joins=clone(plan["joins"]), audiovisual_review="pending_returned_media", automatic_approval=False)
    return {"schema": PACK_SCHEMA, "plan_id": plan["id"], "plan_revision": plan["revision"],
            "plan_sha256": digest(plan), "status": status, "profile": profile,
            "capabilities_live_checked": False, "translation_performed": False, "generation_performed": False,
            "semantic_analysis_performed": False, "clips": compiled, "assembly": assembly,
            "asset_requests": [clone(a) for a in plan["assets"] if a["status"] == "needed"],
            "review_note": "Technical export readiness is distinct from provider input use, rendered continuity, audio review and user approval."}


def _code_block(text, language=""):
    longest = max((len(m.group()) for m in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return fence + language + "\n" + text + "\n" + fence


def render_markdown(pack: dict) -> str:
    """Render complete manual-copy instructions, with settings and inputs apart."""
    mapping(pack, "pack")
    require(pack.get("schema") == PACK_SCHEMA, "pack_schema", "Unsupported prompt pack")
    parts = ["# Video prompt pack", "", f"Project: {pack['plan_id']} · revision {pack['plan_revision']} · status **{pack['status']}**", "",
             "Each clip prompt is independent. Set duration/aspect and attach the listed files in the selected interface. Nothing was submitted or generated by this export.", "",
             pack["review_note"], "", "## Capability declaration", ""]
    if pack["profile"]:
        profile = pack["profile"]
        parts.append(f"{profile['tool']} / {profile['model']} / {profile['mode']} / {profile['interface']}")
        parts.append(f"Declared status: {profile['verification']['status']}; source: {profile['verification']['source'] or 'unspecified'}; checked: {profile['verification']['checked_at'] or 'unspecified'}. No live check was performed.")
    else:
        parts.append("Tool undecided. Prompts are neutral drafts; select a capability profile before ready export.")
    for clip in pack["clips"]:
        parts.extend(["", f"## {clip['clip_id']} — {clip['status']}", "", "### Prompt", "", _code_block(clip["prompt"]), "",
                      "### Settings", "", _code_block(json.dumps(clip["settings"], ensure_ascii=False, indent=2), "json"), "",
                      "### Attachments", "", _code_block(json.dumps(clip["attachments"], ensure_ascii=False, indent=2), "json"), "",
                      "### Postproduction", "", _code_block(json.dumps(clip["postproduction"], ensure_ascii=False, indent=2), "json"), "",
                      "### Postproduction assets", "", _code_block(json.dumps(clip["post_assets"], ensure_ascii=False, indent=2), "json"), "",
                      "### Checks and unresolved requirements", ""])
        if clip["issues"]:
            parts.extend("- " + ("BLOCKER" if item["blocking"] else "NOTE") + " " + item["code"] + ": " + item["message"].replace("\n", " ") for item in clip["issues"])
        else:
            parts.append("Declared technical export prerequisites passed. Review the generated result separately.")
        parts.extend(["", "Export identity: `" + clip["export_sha256"] + "`."])
    parts.extend(["", "## Planned assembly", "", _code_block(json.dumps(pack["assembly"], ensure_ascii=False, indent=2), "json"), "",
                  "## Assets still to produce or supply", "", _code_block(json.dumps(pack["asset_requests"], ensure_ascii=False, indent=2), "json"), ""])
    return "\n".join(parts)
