"""Author-driven shot timing and ratio-specific composition, without generation.

The author supplies actions and their intervals. This module chooses only among
declared duration candidates, exposes missing decisions and performs arithmetic.
It never invents an action, emotion, camera move, crop, performance or provider
capability. A planned result is neither a video nor audiovisual approval.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import re

from ..contracts import (clone, digest, integer, interval, mapping, nonempty,
                         number, provenance, require, sequence, sha256, strings,
                         verify_file)
from .contracts import PLAN_SCHEMA, STRATEGIES

DESIGN_SCHEMA = "video-shot-design/1"
RESULT_SCHEMA = "video-shot-design-plan/1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_RATIO = re.compile(r"[1-9][0-9]*:[1-9][0-9]*\Z")


def _identifier(value, path):
    nonempty(value, path)
    require(bool(_ID.fullmatch(value)) and ".." not in value, "shot_identifier", "Use a portable identifier", path)
    return value


def _time(value, path):
    number(value, path, minimum=0)
    return Fraction(str(value))


def _optional_texts(value, keys, path):
    for key in keys:
        if key in value:
            require(isinstance(value[key], str), "shot_text", "Use an authored string", path + "." + key)


def _index(items, path):
    indexed = {}
    for item in sequence(items, path):
        mapping(item, path)
        key = _identifier(item.get("id"), path + ".id")
        require(key not in indexed, "shot_duplicate", "Duplicate identifier", path + "." + key)
        indexed[key] = item
    return indexed


def _zone(value, path):
    require(isinstance(value, list) and len(value) == 4, "shot_zone", "Use normalized [left, top, right, bottom]", path)
    for coordinate in value:
        number(coordinate, path, minimum=0, maximum=1)
    require(value[0] < value[2] and value[1] < value[3], "shot_zone", "Zone needs positive area", path)


def validate_design(design):
    """Validate structure; missing editorial decisions remain questions.

    Timing uses finite JSON numbers and half-open intervals in the retained
    content clock. Empty semantic strings are allowed here, then reported by
    plan_shots rather than replaced by invented direction.
    """
    data = clone(mapping(design, "design"))
    require(data.get("schema") == DESIGN_SCHEMA, "shot_schema", "Expected " + DESIGN_SCHEMA)
    _identifier(data.get("id"), "design.id")
    integer(data.get("revision"), "design.revision", minimum=1)
    provenance(data.get("author"), "design.author", kinds={"human", "model"})
    ratios = strings(data.get("aspect_ratios", []), "design.aspect_ratios")
    require(all(_RATIO.fullmatch(r) for r in ratios), "shot_ratio", "Use positive width:height ratios")
    if "duration_candidates_s" in data:
        candidates = sequence(data["duration_candidates_s"], "duration_candidates_s")
        for value in candidates:
            require(_time(value, "duration_candidates_s") > 0, "shot_duration", "Duration candidates must be positive")
        require(len(candidates) == len(set(candidates)), "shot_duration", "Duplicate duration candidates")
    if "target_duration_s" in data:
        require(_time(data["target_duration_s"], "target_duration_s") > 0, "shot_duration", "Target must be positive")
    locations = _index(data.get("locations", []), "locations")
    for key, location in locations.items():
        _optional_texts(location, ["description"], "locations." + key)
    shots = _index(data.get("shots", []), "shots")
    for key, shot in shots.items():
        path = "shots." + key
        _optional_texts(shot, ["purpose", "subject", "performance", "lighting", "opening_state", "closing_state"], path)
        location_ids = strings(shot.get("location_ids", []), path + ".location_ids")
        require(set(location_ids) <= set(locations), "shot_location", "Shot refers to an unknown location", path)
        for name in ("use_duration_s", "generated_duration_s"):
            if name in shot:
                require(_time(shot[name], path + "." + name) > 0, "shot_duration", "Duration must be positive", path)
        if "excess_policy" in shot:
            require(shot["excess_policy"] == "tail_handle", "shot_excess", "Only explicitly assigned tail_handle is supported", path)
        handles = mapping(shot.get("handles", {}), path + ".handles")
        for name in ("in_s", "out_s"):
            if name in handles:
                _time(handles[name], path + ".handles." + name)
        _optional_texts(handles, ["in_direction", "out_direction"], path + ".handles")
        camera = mapping(shot.get("camera", {}), path + ".camera")
        _optional_texts(camera, ["purpose", "movement"], path + ".camera")
        for action_id, action in _index(shot.get("actions", []), path + ".actions").items():
            interval(action, path + ".actions." + action_id)
            _optional_texts(action, ["description"], path + ".actions." + action_id)
        for ratio, composition in mapping(shot.get("compositions", {}), path + ".compositions").items():
            require(bool(_RATIO.fullmatch(ratio)), "shot_ratio", "Composition needs a width:height key", path)
            mapping(composition, path + ".compositions." + ratio)
            _optional_texts(composition, ["framing", "rationale"], path + ".compositions." + ratio)
            for name in ("subject_zone", "gesture_zone"):
                if name in composition:
                    _zone(composition[name], path + ".compositions." + ratio + "." + name)
        if "environment_transition" in shot:
            transition = mapping(shot["environment_transition"], path + ".environment_transition")
            require(transition.get("mode") == "continuous", "shot_environments", "Several environments in one shot require an explicit continuous transition", path)
            _optional_texts(transition, ["description", "camera_path"], path + ".environment_transition")
            if "start_s" in transition or "end_s" in transition:
                interval(transition, path + ".environment_transition")
        for voice_id, voice in _index(shot.get("voice", []), path + ".voice").items():
            vp = path + ".voice." + voice_id
            interval(voice, vp)
            _optional_texts(voice, ["text"], vp)
            require(voice.get("timing_basis") in {"estimated", "measured"}, "shot_voice_basis", "Declare estimated or measured voice timing", vp)
            provenance(voice.get("provenance"), vp + ".provenance", kinds={"human", "model"})
            if voice["timing_basis"] == "measured":
                source = mapping(voice.get("source"), vp + ".source")
                nonempty(source.get("path"), vp + ".source.path")
                require(Path(source["path"]).is_absolute(), "absolute_path", "Measured voice needs an absolute source path", vp)
                sha256(source.get("sha256"), vp + ".source.sha256")
                interval(source, vp + ".source")
                require(_time(source["end_s"], vp) - _time(source["start_s"], vp) ==
                        _time(voice["end_s"], vp) - _time(voice["start_s"], vp),
                        "shot_voice_retime", "Voice source and authored window must have equal duration; retime is not inferred", vp)
            else:
                require("source" not in voice, "shot_voice_basis", "An estimated window must not claim measured source timing", vp)
    joins = _index(data.get("joins", []), "joins")
    expected = set(zip(shots, list(shots)[1:]))
    seen = set()
    for key, join in joins.items():
        path = "joins." + key
        pair = (join.get("from"), join.get("to"))
        require(pair in expected and pair not in seen, "shot_join_pair", "Join must connect consecutive shots once", path)
        seen.add(pair)
        _optional_texts(join, ["kind", "rationale", "outgoing", "incoming"], path)
        if "overlap_s" in join:
            _time(join["overlap_s"], path + ".overlap_s")
        if "execution" in join:
            require(join["execution"] in {"generation", "post", "hybrid"}, "shot_join_execution", "Use generation, post or hybrid", path)
        if "strategy" in join:
            require(join["strategy"] in STRATEGIES, "shot_join_strategy", "Unknown continuity strategy", path)
    return data


def _prompt(shot, result, ratio, locations):
    composition = shot.get("compositions", {}).get(ratio, {})
    lines = ["SHOT " + shot["id"], "Output aspect ratio: " + ratio]
    if result["generated_duration_s"] is not None:
        lines.append("Generated duration (set the tool duration field): " + str(result["generated_duration_s"]) + " s")
        lines.append("Editorial use inside the generated clip: " + str(result["use"]))
    for field in ("purpose", "subject", "performance", "lighting", "opening_state", "closing_state"):
        if shot.get(field):
            lines.append(field.replace("_", " ").capitalize() + ": " + shot[field])
    for location_id in shot.get("location_ids", []):
        lines.append("Environment " + location_id + ": " + locations[location_id].get("description", ""))
    for name in ("purpose", "movement"):
        if shot.get("camera", {}).get(name):
            lines.append("Camera " + name + ": " + shot["camera"][name])
    for name in ("framing", "rationale"):
        if composition.get(name):
            lines.append("Composition " + name + ": " + composition[name])
    for name in ("subject_zone", "gesture_zone"):
        if name in composition:
            lines.append(name.replace("_", " ").capitalize() + " (normalized left,top,right,bottom): " + str(composition[name]))
    offset = Fraction(str(result["handles"].get("in_s", 0)))
    if offset and shot.get("handles", {}).get("in_direction"):
        lines.append("Lead-in direction: " + shot["handles"]["in_direction"])
    for action in shot.get("actions", []):
        start, end = Fraction(str(action["start_s"])) + offset, Fraction(str(action["end_s"])) + offset
        lines.append(f"Authored action {float(start):g}–{float(end):g} s: " + action.get("description", ""))
    transition = shot.get("environment_transition")
    if transition:
        window = ""
        if "start_s" in transition:
            start = Fraction(str(transition["start_s"])) + offset
            end = Fraction(str(transition["end_s"])) + offset
            window = f" {float(start):g}–{float(end):g} s"
        lines.append("Continuous environment transition" + window + ": " + transition.get("description", ""))
        lines.append("Continuous camera path: " + transition.get("camera_path", ""))
    for voice in shot.get("voice", []):
        start, end = Fraction(str(voice["start_s"])) + offset, Fraction(str(voice["end_s"])) + offset
        lines.append(f"Literal voice {float(start):g}–{float(end):g} s ({voice['timing_basis']} timing): " + voice.get("text", ""))
    if result["handles"].get("effective_out_s", 0) and shot.get("handles", {}).get("out_direction"):
        lines.append("Tail direction: " + shot["handles"]["out_direction"])
    lines.append("Timing is authored direction; verify the actual returned motion and audio. Text does not apply tool settings.")
    return "\n".join(lines)


def _seam_notes(shot_id, joins):
    lines = []
    for join in joins:
        if shot_id not in (join["from"], join["to"]):
            continue
        side = "outgoing" if join["from"] == shot_id else "incoming"
        lines.append("Editorial " + side + " join: " + join.get("kind", "") +
                     "; execution=" + join.get("execution", "unresolved") +
                     "; overlap_s=" + str(join.get("overlap_s", "unresolved")))
        if join.get(side):
            lines.append("Authored " + side + " state: " + join[side])
        if join.get("execution") == "post":
            lines.append("This transition belongs to postproduction; generate the authored shot without duplicating its transition effect.")
    return lines


def shot_prompt(design_plan, shot_id, ratio, *, include_voice=True):
    """Format the authored fields after generation mapping has been validated.

    Omitting structured voice prevents duplicate dialogue or generated speech
    when the parent assigns audio to post. Visual prose is preserved verbatim;
    this function does not infer whether prose accidentally requests speech.
    It does not call the generation validator or execute any provider.
    """
    require(type(include_voice) is bool, "type", "include_voice must be boolean")
    result = mapping(design_plan, "design_plan")
    require(result.get("schema") == RESULT_SCHEMA, "shot_result_schema", "Expected " + RESULT_SCHEMA)
    require(result.get("plan_sha256") == digest({k: v for k, v in result.items() if k != "plan_sha256"}),
            "shot_result_changed", "Shot plan changed after planning")
    design = validate_design(result.get("design"))
    require(result.get("design_sha256") == digest(design), "shot_result_changed", "Authored design changed")
    require(ratio in design.get("aspect_ratios", []), "shot_mapping_ratio", "Ratio lacks an authored design")
    authored = next((s for s in design.get("shots", []) if s["id"] == shot_id), None)
    planned = next((s for s in result.get("shots", []) if s["id"] == shot_id), None)
    require(authored is not None and planned is not None, "shot_prompt_id", "Unknown authored shot")
    require(ratio in authored.get("compositions", {}), "shot_mapping_ratio", "Ratio lacks an authored composition")
    if not include_voice:
        authored = {**authored, "voice": []}
    locations = {p["id"]: p for p in design.get("locations", [])}
    prompt = _prompt(authored, planned, ratio, locations)
    notes = _seam_notes(shot_id, design.get("joins", []))
    return prompt + ("\n" + "\n".join(notes) if notes else "")


def plan_shots(design, *, profile=None, verify_files=False):
    """Plan one generated clip per authored shot, without synthesis or retiming.

    A dated capability profile is a declaration, never a live capability check.
    A profile range needs explicit duration candidates: this planner does not
    invent the generator's duration increments. Missing semantics produce
    questions; malformed contracts raise ValidationError.
    """
    require(type(verify_files) is bool, "type", "verify_files must be boolean")
    data = validate_design(design)
    from .prompts import validate_profile
    capabilities = validate_profile(profile) if profile is not None else None
    issues, questions = [], []

    def issue(code, message, path, *, question=None, blocking=True):
        record = {"code": code, "message": message, "path": path, "blocking": blocking}
        issues.append(record)
        if question:
            questions.append({"id": path, "question": question, "required_for_direction": blocking})

    def text_needed(value, key, path):
        if not value.get(key, "").strip():
            issue("shot_authoring_needed", "Missing authored " + key, path + "." + key,
                  question="Qual é a direção de " + key + " para " + path + "?")

    ratios = data.get("aspect_ratios", [])
    if not ratios:
        issue("shot_ratio_needed", "Choose the output formats", "aspect_ratios", question="Quais proporções devem receber composição própria?")
    candidates = data.get("duration_candidates_s")
    candidate_origin = "authored_candidates" if candidates is not None else "profile_durations"
    if candidates is None and capabilities is not None:
        candidates = capabilities.get("durations_s")
    if not candidates:
        candidates = []
        issue("duration_candidates_needed", "Supply duration candidates or a profile with discrete durations", "duration_candidates_s",
              question="Quais durações este modelo e modo aceitam, por exemplo 4, 6, 8 ou 10 segundos?")
    durations = sorted(Fraction(str(d)) for d in candidates)
    if capabilities is None:
        issue("shot_profile_pending", "Neutral duration candidates are not provider capabilities", "profile", blocking=False)
    else:
        if capabilities["verification"]["status"] != "verified":
            issue("shot_profile_unverified", "The supplied profile remains unverified", "profile.verification", blocking=False)
        for ratio in ratios:
            if ratio not in capabilities["aspect_ratios"]:
                issue("shot_ratio_unsupported", "Profile does not declare this ratio", "aspect_ratios." + ratio)

        def supported(duration):
            if "durations_s" in capabilities:
                return duration in {Fraction(str(d)) for d in capabilities["durations_s"]}
            bounds = capabilities["duration_range_s"]
            return Fraction(str(bounds["min"])) <= duration <= Fraction(str(bounds["max"]))

        for duration in durations:
            if not supported(duration):
                issue("shot_duration_unsupported", "Authored candidate is absent from the capability declaration", "duration_candidates_s")
        durations = [d for d in durations if supported(d)]
    locations = {p["id"]: p for p in data.get("locations", [])}
    for identifier, location in locations.items():
        text_needed(location, "description", "locations." + identifier)
    planned = []
    if not data.get("shots"):
        issue("shots_needed", "Author the shots before scheduling", "shots", question="Quais ações e ambientes compõem os planos?")
    for shot in data.get("shots", []):
        path = "shots." + shot["id"]
        for field in ("purpose", "subject", "performance", "lighting"):
            text_needed(shot, field, path)
        for field in ("purpose", "movement"):
            text_needed(shot.get("camera", {}), field, path + ".camera")
        if not shot.get("location_ids"):
            issue("shot_location_needed", "Declare the environment", path + ".location_ids", question="Em qual ambiente este plano ocorre?")
        transition = shot.get("environment_transition")
        if len(shot.get("location_ids", [])) > 1 and not transition:
            issue("shot_environment_split", "Multiple environments need separate shots or an explicitly authored continuous transition", path + ".location_ids",
                  question="Separe os ambientes em planos ou descreva uma passagem contínua sem corte.")
        if transition:
            for field in ("description", "camera_path"):
                text_needed(transition, field, path + ".environment_transition")
            if "start_s" not in transition:
                issue("shot_transition_interval", "Continuous environment change needs an authored interval", path + ".environment_transition",
                      question="Em qual intervalo ocorre a passagem contínua entre os ambientes?")
        for ratio in ratios:
            composition = shot.get("compositions", {}).get(ratio, {})
            for field in ("framing", "rationale"):
                text_needed(composition, field, path + ".compositions." + ratio)
            for field in ("subject_zone", "gesture_zone"):
                if field not in composition:
                    issue("shot_composition_needed", "Author the subject and gesture zones separately for this ratio", path + ".compositions." + ratio + "." + field,
                          question="Qual área do quadro " + ratio + " precisa conter " + field + "?")
        actions = shot.get("actions", [])
        if not actions:
            issue("shot_actions_needed", "Action intervals are required; durations are not inferred from action count", path + ".actions",
                  question="Quais ações ocorrem e quanto tempo cada intervalo precisa ocupar?")
        for action in actions:
            text_needed(action, "description", path + ".actions." + action["id"])
        voices = []
        for voice in shot.get("voice", []):
            text_needed(voice, "text", path + ".voice." + voice["id"])
            record = clone(voice)
            record["verification"] = "authored_estimate" if voice["timing_basis"] == "estimated" else "attributed_measurement_not_remeasured"
            if voice["timing_basis"] == "measured" and verify_files:
                from ..production import _media
                source = voice["source"]
                verify_file(source["path"], source["sha256"], "voice source")
                actual = _media(source["path"], "audio", decode=False)
                require(source["end_s"] <= actual["duration_s"] + 1e-6, "shot_voice_coverage", "Measured audio does not cover the selected interval", path)
                verify_file(source["path"], source["sha256"], "voice source")
                record.update(verification="source_bytes_and_audio_duration_verified", source_duration_s=actual["duration_s"])
            voices.append(record)
        requirements = [Fraction(str(a["end_s"])) for a in actions + shot.get("voice", [])]
        if transition and "end_s" in transition:
            requirements.append(Fraction(str(transition["end_s"])))
        needed = max(requirements, default=Fraction())
        use = Fraction(str(shot["use_duration_s"])) if "use_duration_s" in shot else None
        if use is None:
            issue("shot_use_needed", "Declare the retained shot duration", path + ".use_duration_s",
                  question="Qual duração útil deve ser mantida para este plano?")
        elif needed > use:
            issue("shot_content_trimmed", "Retained duration would cut an authored action, transition or voice window", path + ".use_duration_s")
        cursor = Fraction()
        for action in sorted(actions, key=lambda a: (a["start_s"], a["end_s"])):
            start, end = Fraction(str(action["start_s"])), Fraction(str(action["end_s"]))
            if start > cursor:
                issue("shot_action_gap", "Describe the visual action or intentional pause in the uncovered interval", path + ".actions",
                      question="O que acontece visualmente no intervalo ainda sem direção?")
            cursor = max(cursor, end)
        if use is not None and actions and cursor < use:
            issue("shot_action_gap", "Author the final action or intentional hold; no freeze is inserted", path + ".actions",
                  question="Como o plano se sustenta até o final de sua faixa útil?")
        handles = clone(shot.get("handles", {}))
        for field in ("in_s", "out_s"):
            if field not in handles:
                issue("shot_handles_needed", "Declare handles explicitly, including zero", path + ".handles." + field,
                      question="Quantos segundos de margem " + field + " este plano precisa?")
        head, tail = Fraction(str(handles.get("in_s", 0))), Fraction(str(handles.get("out_s", 0)))
        minimum = head + use + tail if use is not None else None
        selected = None
        if "generated_duration_s" in shot:
            selected = Fraction(str(shot["generated_duration_s"]))
            if selected not in durations:
                issue("shot_duration_unsupported", "Explicit generated duration is absent from the declared candidates", path + ".generated_duration_s")
            if minimum is not None and selected < minimum:
                issue("shot_duration_short", "Explicit generated duration cannot hold content and handles", path + ".generated_duration_s")
        elif minimum is not None:
            selected = next((d for d in durations if d >= minimum), None)
            if selected is None and durations:
                issue("shot_duration_unavailable", "No declared duration fits; revise or split the authored shot", path + ".use_duration_s",
                      question="Dividir este plano ou escolher um modo que aceite a duração necessária?")
        surplus = max(Fraction(), selected - minimum) if selected is not None and minimum is not None else Fraction()
        effective_tail = tail
        if surplus:
            if shot.get("excess_policy") != "tail_handle":
                issue("shot_excess_unassigned", "Generation has unused seconds; explicitly assign them before execution", path + ".excess_policy",
                      question="Atribuir os segundos excedentes à margem final e descrever a atuação dessa margem?")
            else:
                effective_tail += surplus
        if head > 0:
            text_needed(handles, "in_direction", path + ".handles")
        if effective_tail > 0:
            text_needed(handles, "out_direction", path + ".handles")
        result = {"id": shot["id"], "location_ids": clone(shot.get("location_ids", [])),
                  "required_content_s": float(needed), "use_duration_s": float(use) if use is not None else None,
                  "minimum_generation_s": float(minimum) if minimum is not None else None,
                  "generated_duration_s": float(selected) if selected is not None else None,
                  "selection": "explicit_authored_duration" if "generated_duration_s" in shot else "shortest_declared_duration_that_fits",
                  "use": {"start_s": float(head), "end_s": float(head + use)} if use is not None else None,
                  "handles": {**handles, "effective_out_s": float(effective_tail)},
                  "surplus_s": float(surplus), "surplus_assignment": shot.get("excess_policy") if surplus else "none",
                  "voice": voices, "compositions": clone(shot.get("compositions", {})),
                  "prompts": {}}
        result["prompts"] = {ratio: _prompt(shot, result, ratio, locations) for ratio in ratios}
        planned.append(result)
    joins = data.get("joins", [])
    by_pair = {(j["from"], j["to"]): j for j in joins}
    by_id = {s["id"]: s for s in planned}
    overlap_by_id = {s["id"]: Fraction() for s in planned}
    joins_valid = True
    for left, right in zip(planned, planned[1:]):
        join = by_pair.get((left["id"], right["id"]))
        if join is None:
            issue("shot_join_needed", "Every consecutive pair needs an explicit cut or transition", "joins." + left["id"] + "." + right["id"],
                  question="Qual corte ou transição liga estes dois planos e qual a sobreposição?")
            joins_valid = False
            continue
        path = "joins." + join["id"]
        for field in ("kind", "rationale"):
            text_needed(join, field, path)
        if "overlap_s" not in join or "execution" not in join:
            issue("shot_join_timing", "Declare overlap and execution explicitly", path,
                  question="Qual é a sobreposição e onde a transição será executada?")
            joins_valid = False
            continue
        overlap = Fraction(str(join["overlap_s"]))
        if overlap and (join["execution"] not in {"post", "hybrid"} or join.get("kind") == "cut"):
            issue("shot_join_overlap", "An overlap requires an explicit post/hybrid transition, not a hard cut", path)
            joins_valid = False
        for shot in (left, right):
            overlap_by_id[shot["id"]] += overlap
            if shot["use_duration_s"] is not None and overlap >= Fraction(str(shot["use_duration_s"])):
                issue("shot_join_overlap", "Overlap cannot consume an entire shot", path)
                joins_valid = False
    for identifier, total in overlap_by_id.items():
        use = by_id[identifier]["use_duration_s"]
        if use is not None and total > Fraction(str(use)):
            issue("shot_overlap_collision", "Incoming and outgoing overlaps collide", "shots." + identifier)
            joins_valid = False
    # Preserve authored seam instructions in each prompt without turning a
    # postproduction transition into a duplicate generated effect.
    for shot in planned:
        seam_lines = _seam_notes(shot["id"], joins)
        if seam_lines:
            shot["prompts"] = {ratio: prompt + "\n" + "\n".join(seam_lines)
                               for ratio, prompt in shot["prompts"].items()}
    timing = None
    if planned and joins_valid and all(s["use_duration_s"] is not None for s in planned):
        cursor, timeline, used = Fraction(), [], Fraction()
        for index, shot in enumerate(planned):
            if index:
                cursor -= Fraction(str(by_pair[(planned[index - 1]["id"], shot["id"])]["overlap_s"]))
            duration = Fraction(str(shot["use_duration_s"]))
            timeline.append({"shot_id": shot["id"], "start_s": float(cursor), "end_s": float(cursor + duration)})
            cursor += duration
            used += duration
        timing = {"used_duration_s": float(used), "overlap_duration_s": float(used - cursor), "final_duration_s": float(cursor),
                  "exact_final_s": str(cursor), "timeline": timeline, "clock": "planned_seconds", "frame_conform": "pending_returned_media",
                  "generated_duration_s": float(sum(Fraction(str(s["generated_duration_s"])) for s in planned))
                  if all(s["generated_duration_s"] is not None for s in planned) else None}
        if "target_duration_s" in data and cursor != Fraction(str(data["target_duration_s"])):
            issue("shot_target_mismatch", "Final duration differs from the authored target; no trim, freeze or retime was applied", "target_duration_s")
    blocked = any(i["blocking"] for i in issues)
    result = {"schema": RESULT_SCHEMA, "id": data["id"], "revision": data["revision"], "design_sha256": digest(data),
              "design": data, "status": "blocked" if blocked else "planned", "questions": questions, "issues": issues,
              "aspect_ratios": clone(ratios), "duration_candidates_s": [float(d) for d in durations], "candidate_origin": candidate_origin,
              "profile": capabilities, "profile_sha256": digest(capabilities) if capabilities else None,
              "shots": planned, "joins": clone(joins), "timing": timing,
              "verification": {"method": "authored_intervals_and_exact_arithmetic", "voice_files_checked": verify_files,
                  "capabilities_live_checked": False, "media_generated": False, "motion_reviewed": False,
                  "audio_listened": False, "automatic_crop": False, "automatic_retime": False, "user_approval": "unverified"}}
    result["plan_sha256"] = digest(result)
    return result


def validate_generation_mapping(design_plan, generation_plan, clip_to_shot):
    """Bind a sealed design to one generation clip per shot and one output ratio.

    Checks duration/use/ratio and overlaps; this does not certify that generated
    prompt prose preserves all semantic direction. Use the authored prompt
    blocks as context and review that prose separately.
    """
    result = mapping(design_plan, "design_plan")
    require(result.get("schema") == RESULT_SCHEMA, "shot_result_schema", "Expected " + RESULT_SCHEMA)
    require(result.get("plan_sha256") == digest({k: v for k, v in result.items() if k != "plan_sha256"}),
            "shot_result_changed", "Shot plan changed after planning")
    rebuilt = plan_shots(result["design"], profile=result.get("profile"), verify_files=result["verification"]["voice_files_checked"])
    require(rebuilt["plan_sha256"] == result["plan_sha256"], "shot_result_changed", "Shot plan differs from its authored inputs")
    require(result["status"] == "planned", "shot_plan_blocked", "Resolve authored shot requirements before accepting generation mapping")
    # The full generation validator calls this binding check. Do not call it
    # back: validate the fields needed here and leave the full graph to it.
    generated = clone(mapping(generation_plan, "generation_plan"))
    require(generated.get("schema") == PLAN_SCHEMA, "generation_schema", "Expected " + PLAN_SCHEMA)
    brief = mapping(generated.get("brief"), "generation_plan.brief")
    nonempty(brief.get("aspect_ratio"), "generation_plan.brief.aspect_ratio")
    _index(generated.get("clips"), "generation_plan.clips")
    for clip in generated["clips"]:
        require(_time(clip.get("duration_s"), "clip.duration_s") > 0, "shot_mapping_duration", "Clip duration must be positive")
        interval(clip.get("use"), "clip.use", duration_s=clip["duration_s"])
    _index(generated.get("joins"), "generation_plan.joins")
    binding = mapping(clip_to_shot, "clip_to_shot")
    shots = {s["id"]: s for s in result["shots"]}
    clip_ids = [c["id"] for c in generated["clips"]]
    require(set(binding) == set(clip_ids) and list(binding.get(k) for k in clip_ids) == list(shots),
            "shot_mapping", "Map every generated clip to one authored shot in the same order")
    require(generated["brief"]["aspect_ratio"] in result["aspect_ratios"], "shot_mapping_ratio", "Generation ratio lacks an authored composition")
    for clip in generated["clips"]:
        shot = shots[binding[clip["id"]]]
        require(Fraction(str(clip["duration_s"])) == Fraction(str(shot["generated_duration_s"])),
                "shot_mapping_duration", "Generated duration changed from shot design", clip["id"])
        require(all(Fraction(str(clip["use"][k])) == Fraction(str(shot["use"][k])) for k in ("start_s", "end_s")),
                "shot_mapping_use", "Useful range changed from shot design", clip["id"])
    joins = {(j["from"], j["to"]): j for j in result["joins"]}
    expected_pairs = set(zip(clip_ids, clip_ids[1:]))
    seen_pairs = set()
    for join in generated["joins"]:
        pair = (join.get("from"), join.get("to"))
        require(pair in expected_pairs and pair not in seen_pairs, "shot_mapping_overlap",
                "Map consecutive generation joins exactly once")
        seen_pairs.add(pair)
        _time(join.get("overlap_s"), "join.overlap_s")
        authored = joins[(binding[join["from"]], binding[join["to"]])]
        require(Fraction(str(join["overlap_s"])) == Fraction(str(authored["overlap_s"])),
                "shot_mapping_overlap", "Join overlap changed from shot design", join["id"])
    require(seen_pairs == expected_pairs, "shot_mapping_overlap", "Generation mapping omitted an authored join")
    return {"schema": "video-shot-generation-binding/1", "design_plan_sha256": result["plan_sha256"],
            "generation_plan_sha256": digest(generated), "clip_to_shot": clone(binding),
            "aspect_ratio": generated["brief"]["aspect_ratio"], "timing_bound": True,
            "semantic_prompt_review": "pending", "media_generated": False, "user_approval": "unverified"}
