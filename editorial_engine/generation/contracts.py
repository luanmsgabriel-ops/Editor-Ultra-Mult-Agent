"""A provider-independent audiovisual plan with explicit, bilateral joins.

Validation proves structure, arithmetic, dependencies and (optionally) bytes.
It cannot prove that an action is plausible, a voice matches or a cut works.
No generator-specific limits or aesthetic quotas belong in this contract.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import re

from ..contracts import (clone, digest, index_by_id, integer, mapping, nonempty,
                         number, provenance, require, sequence, sha256, strings,
                         verify_file)

PLAN_SCHEMA = "video-generation-plan/1"
ROLES = {"start_frame", "end_frame", "identity_image", "scene_image",
         "motion_video", "voice_audio", "previous_video"}
ROLE_KINDS = {"start_frame": "image", "end_frame": "image", "identity_image": "image",
              "scene_image": "image", "motion_video": "video", "voice_audio": "audio",
              "previous_video": "video"}
STRATEGIES = {"planned_frame", "observed_frame", "native_extension", "prompt_only", "post_only"}
EVIDENCE_SCOPES = {"sampled_frames", "continuous_video", "audio_listened", "transcript",
                   "document", "human_note"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")


def _fraction(value, path="time"):
    number(value, path, minimum=0)
    return Fraction(str(value))


def _identifier(value, path):
    nonempty(value, path)
    require(bool(_ID.fullmatch(value)) and ".." not in value, "identifier",
            "Use a short identifier containing letters, numbers, underscores, dots or hyphens", path)
    return value


def _index(items, path):
    result = index_by_id(items, path)
    for key in result:
        _identifier(key, path + ".id")
    return result


def _fields(item, names, path):
    for name in names:
        nonempty(item.get(name), path + "." + name)


def _refs(values, known, path, *, nonempty_required=False):
    result = strings(values, path, allow_empty=not nonempty_required)
    for value in result:
        require(value in known, "unknown_reference", f"Unknown identifier {value}", path)
    return result


def _range(item, duration, path):
    item = mapping(item, path)
    start = _fraction(item.get("start_s"), path + ".start_s")
    end = _fraction(item.get("end_s"), path + ".end_s")
    require(end > start, "empty_interval", "Use a nonempty half-open interval", path)
    require(end <= duration, "outside_clip", "Interval exceeds the generated clip", path)
    return start, end


def _state(state, path):
    state = mapping(state, path)
    _fields(state, ("description", "motion", "camera", "audio"), path)
    return state


def _file(item, path, verify):
    name = nonempty(item.get("path"), path + ".path")
    require(Path(name).is_absolute(), "absolute_path", "Use an absolute local file path", path)
    sha256(item.get("sha256"), path + ".sha256")
    if verify:
        verify_file(name, item["sha256"], path)


def _timing(data):
    """Arithmetic only; validate_plan calls this after validating the fields."""
    total_generated = sum((Fraction(str(c["duration_s"])) for c in data["clips"]), Fraction())
    total_used = sum((Fraction(str(c["use"]["end_s"])) - Fraction(str(c["use"]["start_s"]))
                      for c in data["clips"]), Fraction())
    by_destination = {j["to"]: j for j in data["joins"]}
    overlap = sum((Fraction(str(j["overlap_s"])) for j in data["joins"]), Fraction())
    timeline, cursor = [], Fraction()
    for clip in data["clips"]:
        incoming = by_destination.get(clip["id"])
        cursor -= Fraction(str(incoming["overlap_s"])) if incoming else 0
        length = Fraction(str(clip["use"]["end_s"])) - Fraction(str(clip["use"]["start_s"]))
        timeline.append({"clip_id": clip["id"], "start_s": float(cursor), "end_s": float(cursor + length),
                         "use": clone(clip["use"])})
        cursor += length
    target = Fraction(str(data["brief"]["target_duration_s"]))
    return {"generated_duration_s": float(total_generated), "used_duration_s": float(total_used),
            "overlap_duration_s": float(overlap), "final_duration_s": float(total_used - overlap),
            "target_duration_s": float(target), "exact_final_s": str(total_used - overlap),
            "exact_target_s": str(target), "timeline": timeline,
            "clock": "planned_seconds", "frame_conform": "pending_returned_media"}


def validate_plan(data, *, verify_files=False):
    """Check an authored plan. Missing media may remain declared as needed.

    verify_files checks references and all ready assets, not creative quality.
    Unfulfilled needs are export issues rather than fabricated resources.
    """
    data = clone(mapping(data, "plan"))
    require(data.get("schema") == PLAN_SCHEMA, "generation_schema", "Unsupported video generation plan")
    _identifier(data.get("id"), "id")
    integer(data.get("revision"), "revision", minimum=1)
    provenance(data.get("author"), "author", kinds={"human", "model"})
    brief = mapping(data.get("brief"), "brief")
    require(brief.get("mode") in {"original", "reference_clone", "adaptation", "fill_gaps"},
            "generation_mode", "Unsupported creation mode", "brief.mode")
    _fields(brief, ("objective", "audience", "aspect_ratio", "instruction_language", "dialogue_language"), "brief")
    require(bool(re.fullmatch(r"[1-9][0-9]*:[1-9][0-9]*", brief["aspect_ratio"])),
            "aspect_ratio", "Use a positive width:height ratio", "brief.aspect_ratio")
    require(_fraction(brief.get("target_duration_s"), "brief.target_duration_s") > 0,
            "duration", "Target duration must be positive")
    if "audio_execution" in brief:
        require(brief["audio_execution"] in {"generation", "post", "none"}, "audio_execution",
                "Declare generation, post or none for the audio route", "brief.audio_execution")
    if "require_generated_audio" in brief:
        require(type(brief["require_generated_audio"]) is bool, "audio_requirement",
                "Generated audio requirement must be a boolean", "brief.require_generated_audio")
    require(not (brief.get("audio_execution") in {"post", "none"} and brief.get("require_generated_audio") is True),
            "audio_conflict", "Generated audio cannot be required when audio is assigned to post or disabled")
    bible = mapping(data.get("bible"), "bible")
    nonempty(bible.get("visual_style"), "bible.visual_style")
    strings(bible.get("invariants"), "bible.invariants")
    characters = _index(bible.get("characters"), "bible.characters")
    locations = _index(bible.get("locations"), "bible.locations")
    props = _index(bible.get("props"), "bible.props")
    for key, character in characters.items():
        _fields(character, ("identity", "wardrobe", "voice"), f"characters.{key}")
        strings(character.get("invariants"), f"characters.{key}.invariants")
    for items, name in ((locations, "locations"), (props, "props")):
        for key, item in items.items():
            nonempty(item.get("description"), f"{name}.{key}.description")
    references = _index(data.get("references"), "references")
    evidence = _index(data.get("evidence"), "evidence")
    assets = _index(data.get("assets"), "assets")
    for key, reference in references.items():
        path = "references." + key
        require(reference.get("kind") in {"video", "image", "audio", "document"},
                "reference_kind", "Unsupported source kind", path)
        nonempty(reference.get("role"), path + ".role")
        _file(reference, path, verify_files)
        if "duration_s" in reference:
            require(_fraction(reference["duration_s"], path + ".duration_s") > 0,
                    "duration", "Source duration must be positive", path)
    for key, item in evidence.items():
        path = "evidence." + key
        source_id = nonempty(item.get("source_id"), path + ".source_id")
        require(source_id in references, "evidence_source", "Evidence needs an existing source", path)
        reference = references[source_id]
        require(item.get("source_sha256") == reference["sha256"], "evidence_hash",
                "Evidence is bound to other source bytes", path)
        nonempty(item.get("observation"), path + ".observation")
        require(item.get("scope") in EVIDENCE_SCOPES, "evidence_scope", "Declare the actual observation scope", path)
        if reference["kind"] in {"video", "audio"} or "interval" in item:
            duration = Fraction(str(reference.get("duration_s", item.get("interval", {}).get("end_s", 0))))
            _range(item.get("interval"), duration, path + ".interval")
    for key, asset in assets.items():
        path = "assets." + key
        require(asset.get("kind") in {"image", "video", "audio", "motion"}, "asset_kind", "Unsupported asset kind", path)
        nonempty(asset.get("purpose"), path + ".purpose")
        require(asset.get("route") in {"reuse", "chat_image", "external_video", "procedural", "user"},
                "asset_route", "Unsupported asset production route", path)
        require(asset.get("status") in {"needed", "ready"}, "asset_status", "Declare needed or ready", path)
        _refs(asset.get("evidence_ids"), evidence, path + ".evidence_ids",
              nonempty_required=brief["mode"] != "original")
        _refs(asset.get("reference_ids"), references, path + ".reference_ids")
        if asset["status"] == "ready":
            _file(asset, path, verify_files)
        else:
            require("path" not in asset and "sha256" not in asset, "unready_file",
                    "Missing assets must not claim file paths or hashes", path)
            if asset["route"] in {"chat_image", "external_video"}:
                nonempty(asset.get("prompt"), path + ".prompt")
        require(asset["route"] != "chat_image" or asset["kind"] == "image", "static_image",
                "Chat image generation produces still images", path)
    clips = _index(data.get("clips"), "clips")
    require(bool(clips), "no_clips", "Provide at least one clip")
    ordered = list(clips)
    for position, (key, clip) in enumerate(clips.items()):
        path = "clips." + key
        nonempty(clip.get("purpose"), path + ".purpose")
        duration = _fraction(clip.get("duration_s"), path + ".duration_s")
        require(duration > 0, "duration", "Clip duration must be positive", path)
        used_start, used_end = _range(clip.get("use"), duration, path + ".use")
        _refs(clip.get("character_ids"), characters, path + ".character_ids")
        _refs(clip.get("location_ids"), locations, path + ".location_ids")
        _refs(clip.get("prop_ids"), props, path + ".prop_ids")
        _refs(clip.get("evidence_ids"), evidence, path + ".evidence_ids",
              nonempty_required=brief["mode"] != "original")
        strings(clip.get("constraints"), path + ".constraints")
        shots = _index(clip.get("shots"), path + ".shots")
        require(bool(shots), "no_shots", "Each clip needs directed shots", path)
        cursor = Fraction()
        for shot_id, shot in shots.items():
            sp = path + ".shots." + shot_id
            start, end = _range(shot, duration, sp)
            require(start == cursor, "shot_coverage", "Shots must be ordered, without gaps or overlap", sp)
            cursor = end
            _fields(shot, ("intent", "action", "composition", "camera", "performance", "lighting"), sp)
        require(cursor == duration, "shot_coverage", "Shot coverage must reach the clip end", path)
        for i, item in enumerate(sequence(clip.get("dialogue"), path + ".dialogue")):
            dp = f"{path}.dialogue[{i}]"
            mapping(item, dp)
            speech_start, speech_end = _range(item, duration, dp)
            require(used_start <= speech_start and speech_end <= used_end, "speech_trimmed",
                    "The used range must retain the entire authored line; revise the dialogue explicitly before cutting it", dp)
            require(brief.get("audio_execution") != "none", "silent_dialogue",
                    "A silent clip cannot request spoken dialogue", dp)
            require(item.get("speaker_id") in clip["character_ids"], "dialogue_speaker",
                    "Every speaking character must belong to this clip", dp)
            _fields(item, ("text", "delivery"), dp)
            require(item.get("mode") in {"on_camera", "off_screen"}, "dialogue_mode",
                    "Declare on_camera or off_screen speech", dp)
        audio = mapping(clip.get("audio"), path + ".audio")
        _fields(audio, ("voice_direction", "ambience", "music", "sfx"), path + ".audio")
        conditioned = []
        for i, item in enumerate(sequence(clip.get("conditioning"), path + ".conditioning")):
            cp = f"{path}.conditioning[{i}]"
            mapping(item, cp)
            role, asset_id = item.get("role"), item.get("asset_id")
            require(role in ROLES, "conditioning_role", "Unsupported conditioning role", cp)
            require(asset_id in assets, "conditioning_asset", "Missing conditioning asset", cp)
            require(assets[asset_id]["kind"] == ROLE_KINDS[role], "conditioning_kind",
                    "Conditioning role and media kind disagree", cp)
            require((role, asset_id) not in conditioned, "duplicate_conditioning", "Duplicate binding", cp)
            conditioned.append((role, asset_id))
        for role in ("start_frame", "end_frame", "previous_video"):
            require(sum(item[0] == role for item in conditioned) <= 1, "ambiguous_conditioning",
                    "Use one " + role + " per clip", path)
        for post_id, post in _index(clip.get("post"), path + ".post").items():
            pp = path + ".post." + post_id
            require(post.get("kind") in {"text", "logo", "sfx", "motion"}, "post_kind", "Unknown post operation", pp)
            nonempty(post.get("brief"), pp + ".brief")
            post_start, post_end = _range(post, duration, pp)
            require(used_start <= post_start and post_end <= used_end, "post_trimmed",
                    "The used range must retain each authored post event; revise the event explicitly before cutting it", pp)
            if "trigger" in post:
                nonempty(post["trigger"], pp + ".trigger")
            if "asset_id" in post:
                require(post["asset_id"] in assets, "post_asset", "Unknown post asset", pp)
        if position == 0:
            _state(clip.get("initial_state"), path + ".initial_state")
        else:
            require("initial_state" not in clip, "duplicate_boundary", "Incoming join owns the clip opening state", path)
        if position == len(ordered) - 1:
            _state(clip.get("final_state"), path + ".final_state")
        else:
            require("final_state" not in clip, "duplicate_boundary", "Outgoing join owns the clip closing state", path)
    joins = _index(data.get("joins"), "joins")
    expected = list(zip(ordered, ordered[1:]))
    require(len(joins) == len(expected), "join_count", "Every consecutive clip pair needs exactly one join")
    pairs = set()
    overlaps = {key: Fraction() for key in ordered}
    for key, join in joins.items():
        path = "joins." + key
        pair = (join.get("from"), join.get("to"))
        require(pair in expected and pair not in pairs, "join_pair", "Join must uniquely connect consecutive clips", path)
        pairs.add(pair)
        _fields(join, ("kind", "rationale"), path)
        require(join.get("execution") in {"generation", "post", "hybrid"}, "join_execution", "Unknown join execution", path)
        require(join.get("strategy") in STRATEGIES, "join_strategy", "Unknown join strategy", path)
        overlap = _fraction(join.get("overlap_s"), path + ".overlap_s")
        require(overlap == 0 or join["execution"] in {"post", "hybrid"}, "generated_overlap",
                "Timeline overlap needs an explicit post operation", path)
        require(join["strategy"] != "post_only" or join["execution"] == "post", "join_execution",
                "post_only is executed during editing", path)
        _state(join.get("outgoing"), path + ".outgoing")
        _state(join.get("incoming"), path + ".incoming")
        strings(join.get("match"), path + ".match")
        for clip_id in pair:
            clip = clips[clip_id]
            length = Fraction(str(clip["use"]["end_s"])) - Fraction(str(clip["use"]["start_s"]))
            require(overlap < length, "join_overlap", "An overlap cannot consume an entire clip", path)
            overlaps[clip_id] += overlap
        if join["strategy"] == "planned_frame":
            asset_id = join.get("handoff_asset_id")
            require(asset_id in assets and assets[asset_id]["kind"] == "image", "handoff_asset",
                    "A planned shared boundary needs one image asset", path)
            for clip_id, role in ((pair[0], "end_frame"), (pair[1], "start_frame")):
                explicit = [c["asset_id"] for c in clips[clip_id]["conditioning"] if c["role"] == role]
                require(not explicit or explicit == [asset_id], "conflicting_handoff",
                        "Both sides must condition on the same shared image", path)
        else:
            require("handoff_asset_id" not in join, "unexpected_handoff",
                    "Only planned_frame uses a planned handoff asset", path)
        if join["strategy"] in {"observed_frame", "native_extension"}:
            forbidden = {"start_frame", "previous_video"}
            require(not any(c["role"] in forbidden for c in clips[pair[1]]["conditioning"]),
                    "conflicting_return", "Returned media binding is owned by the incoming join", path)
    for key, total in overlaps.items():
        clip = clips[key]
        length = Fraction(str(clip["use"]["end_s"])) - Fraction(str(clip["use"]["start_s"]))
        require(total <= length, "overlap_collision", "Incoming and outgoing overlaps collide in " + key)
    timing = _timing(data)
    require(timing["exact_final_s"] == timing["exact_target_s"], "duration_mismatch",
            f"Planned edit is {timing['final_duration_s']:g}s; target is {timing['target_duration_s']:g}s. "
            "Account for explicit trims and overlapping joins.")
    return data


def assembly_timing(plan):
    """Return the planned editing clock, not probed media timing."""
    return _timing(validate_plan(plan))


def effective_states(plan, clip_id):
    """Opening/closing come from one shared join object per pair."""
    clip = next((c for c in plan["clips"] if c["id"] == clip_id), None)
    require(clip is not None, "unknown_clip", "Unknown clip " + str(clip_id))
    incoming = next((j for j in plan["joins"] if j["to"] == clip_id), None)
    outgoing = next((j for j in plan["joins"] if j["from"] == clip_id), None)
    return (clone(incoming["incoming"] if incoming else clip["initial_state"]),
            clone(outgoing["outgoing"] if outgoing else clip["final_state"]))


def clip_fingerprint(plan, clip_id):
    """Identify the instructions/resources that can affect one generated clip.

    Changing another independent clip or the numeric project revision does not
    invalidate this digest. Global style/identity and adjacent joins do.
    Returned parent bytes additionally belong to the prompt export fingerprint.
    """
    plan = validate_plan(plan)
    clip = next((c for c in plan["clips"] if c["id"] == clip_id), None)
    require(clip is not None, "unknown_clip", "Unknown clip " + str(clip_id))
    joins = [j for j in plan["joins"] if clip_id in {j["from"], j["to"]}]
    asset_ids = {c["asset_id"] for c in clip["conditioning"]}
    asset_ids.update(p["asset_id"] for p in clip["post"] if "asset_id" in p)
    asset_ids.update(j["handoff_asset_id"] for j in joins if "handoff_asset_id" in j)
    assets = [a for a in plan["assets"] if a["id"] in asset_ids]
    evidence_ids = set(clip["evidence_ids"])
    evidence_ids.update(e for a in assets for e in a["evidence_ids"])
    evidence = [e for e in plan["evidence"] if e["id"] in evidence_ids]
    source_ids = {e["source_id"] for e in evidence}
    source_ids.update(r for a in assets for r in a["reference_ids"])
    references = [r for r in plan["references"] if r["id"] in source_ids]
    return digest({"schema": PLAN_SCHEMA, "brief": plan["brief"], "bible": plan["bible"],
                   "clip": clip, "joins": joins, "assets": assets, "evidence": evidence,
                   "references": references})


def revise_plan(previous, revised):
    """Accept a full authored revision and enumerate invalidated dependents.

    This never rewrites another clip, fabricates approval or erases reviews.
    The caller stores the prior plan and receipts alongside this change report.
    """
    previous, revised = validate_plan(previous), validate_plan(revised)
    require(revised["id"] == previous["id"], "project_identity", "A revision must retain the project id")
    require(revised["revision"] == previous["revision"] + 1, "revision_sequence",
            "Increase revision by exactly one")
    old_ids = {c["id"] for c in previous["clips"]}
    new_ids = {c["id"] for c in revised["clips"]}
    changed = {key for key in new_ids if key not in old_ids or
               clip_fingerprint(previous, key) != clip_fingerprint(revised, key)}
    affected = set(changed)
    # A returned-frame/native-extension chain depends on its parent's actual
    # result, even if the child's written directions did not change.
    while True:
        expanded = affected | {j["to"] for j in revised["joins"]
                               if j["from"] in affected and j["strategy"] in {"observed_frame", "native_extension"}}
        if expanded == affected:
            break
        affected = expanded
    return {"schema": "video-generation-revision/1", "previous_plan_sha256": digest(previous),
            "plan_sha256": digest(revised), "plan": revised,
            "changed_clips": sorted(changed), "invalidated_clips": sorted(affected),
            "removed_clips": sorted(old_ids - new_ids), "unchanged_clips": sorted(new_ids - affected),
            "review_status": "pending_for_changed_media", "automatic_approval": False}
