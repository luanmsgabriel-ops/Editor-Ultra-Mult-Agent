"""Validate and reconcile explicit editorial proposals against measured evidence.

The calling human/model supplies observations, intent and suitability scores.
This module makes no semantic claims of its own: it enforces feasibility,
compares declared proposals and records why alternatives were not selected.
"""

from __future__ import annotations

from .catalog import ANCHOR_REQUIREMENTS, validate_catalog, validate_parameters
from .contracts import (EPSILON, SCHEMA_VERSION, ValidationError, clone, contains,
                        digest, index_by_id, integer, interval, mapping, nonempty,
                        number, overlaps, provenance, require, sequence,
                        sha256, source_reference, strings, validate_analysis)

SCORE_KEYS = ("intent_fit", "visual_fit", "style_fit", "timing_fit")
DEFAULT_POLICY = {
    "weights": {"intent_fit": 0.35, "visual_fit": 0.25, "style_fit": 0.20, "timing_fit": 0.20},
    "minimum_score": 0.50,
    "opportunity_bonus": 0.04,
    "repetition_penalty": 0.08,
    "max_effect_repetitions": 4,
    "max_visual_layers": 3,
    "max_audio_layers": 3,
}


def _policy(value: dict | None) -> dict:
    result = clone(DEFAULT_POLICY)
    supplied = mapping({} if value is None else value, "policy")
    require(set(supplied) <= set(result), "policy", "Unknown policy setting", "policy")
    result.update(clone(supplied))
    weights = mapping(result["weights"], "policy.weights")
    require(set(weights) == set(SCORE_KEYS), "policy", "Weights must name every score dimension", "policy.weights")
    for key in SCORE_KEYS:
        number(weights[key], "policy.weights." + key, minimum=0)
    require(sum(weights.values()) > 0, "policy", "At least one weight must be positive", "policy.weights")
    for key in ("minimum_score", "opportunity_bonus", "repetition_penalty"):
        number(result[key], "policy." + key, minimum=0, maximum=1)
    for key in ("max_effect_repetitions", "max_visual_layers", "max_audio_layers"):
        integer(result[key], "policy." + key, minimum=1)
    return result


def _capability_matches(capability: dict, candidate: dict, name: str) -> bool:
    return (capability["name"] == name and capability["status"] == "verified"
            and capability["source_id"] == candidate["source_id"]
            and capability["source_sha256"] == candidate["source_sha256"]
            and capability["clock"] == candidate["clock"]
            and contains(capability["interval"], candidate["interval"]))


def _region(candidate: dict) -> list[float]:
    region = candidate.get("region", [0.0, 0.0, 1.0, 1.0])
    require(isinstance(region, list) and len(region) == 4, "region", "Region must be [x, y, width, height]", "proposal.region")
    for coordinate in region:
        number(coordinate, "proposal.region", minimum=0, maximum=1)
    x, y, width, height = region
    require(width > 0 and height > 0 and x + width <= 1 + EPSILON and y + height <= 1 + EPSILON,
            "region", "Region must be nonempty and inside the normalized frame", "proposal.region")
    return region


def _validate_candidate(candidate: dict, sources: dict, evidence: dict,
                        events: dict, capabilities: dict, effects: dict) -> dict:
    proposal_id = nonempty(candidate.get("id"), "proposal.id")
    event_id = nonempty(candidate.get("event_id"), f"proposals.{proposal_id}.event_id")
    require(event_id in events, "unknown_event", f"Unknown event {event_id}", proposal_id)
    event = events[event_id]
    source_reference(candidate, sources, proposal_id)
    require(candidate["source_id"] == event["source_id"], "event_source_mismatch", "Proposal and event have different sources", proposal_id)
    require(contains(event["interval"], candidate["interval"]), "outside_event", "Proposal exceeds its event", proposal_id)
    nonempty(candidate.get("why"), proposal_id + ".why")
    evidence_ids = strings(candidate.get("evidence_ids"), proposal_id + ".evidence_ids", allow_empty=False)
    for evidence_id in evidence_ids:
        require(evidence_id in evidence, "unknown_evidence", f"Unknown evidence {evidence_id}", proposal_id)
        require(evidence_id in event["evidence_ids"], "unbound_evidence", "Evidence was not declared for this event", proposal_id)
        require(overlaps(evidence[evidence_id]["interval"], candidate["interval"]), "evidence_time_mismatch", "Evidence does not support this time interval", proposal_id)
    scores = mapping(candidate.get("scores"), proposal_id + ".scores")
    require(set(scores) == set(SCORE_KEYS), "score_dimensions", "Scores must name every declared dimension", proposal_id)
    for key in SCORE_KEYS:
        number(scores[key], proposal_id + ".scores." + key, minimum=0, maximum=1)
    provenance(candidate.get("score_provenance"), proposal_id + ".score_provenance", kinds={"human", "model"})
    effect_id = nonempty(candidate.get("effect_id"), proposal_id + ".effect_id")
    addresses = strings(candidate.get("addresses", []), proposal_id + ".addresses")
    opportunities = index_by_id(event.get("opportunities", []), "opportunities")
    require(set(addresses) <= set(opportunities), "unknown_opportunity", "Proposal cites an unknown opportunity", proposal_id)
    if effect_id == "preserve":
        require(candidate["interval"] == event["interval"], "preserve_interval", "Preservation must cover the entire event", proposal_id)
        require(not addresses, "preserve_opportunity", "Preservation does not fulfill an effect opportunity", proposal_id)
        require(not candidate.get("params") and not candidate.get("bindings"), "preserve_parameters", "Preservation cannot contain render parameters", proposal_id)
        return {"proposal": candidate, "effect": None, "capability_ids": [], "region": _region(candidate)}
    require(effect_id in effects, "unknown_effect", f"Unknown effect {effect_id}", proposal_id)
    effect = effects[effect_id]
    require(effect["status"] == "ready", "effect_not_ready", "Draft effects are not executable", proposal_id)
    for opportunity_id in addresses:
        require(opportunities[opportunity_id]["function"] in effect["functions"], "opportunity_function_mismatch",
                "Effect cannot fulfill the cited editorial function", proposal_id)
    validate_parameters(candidate.get("params", {}), effect)
    anchor = mapping(candidate.get("anchor"), proposal_id + ".anchor")
    space = anchor.get("space")
    require(space in effect["anchors"], "anchor_space", "Anchor space is not supported by this effect", proposal_id)
    bindings = mapping(candidate.get("bindings", {}), proposal_id + ".bindings")
    binding_requirements = effect.get("binding_requirements", {})
    require(set(bindings) == set(binding_requirements), "binding_schema", "Bindings must exactly match the manifest", proposal_id)
    used = set()
    required_names = set(effect.get("requirements", []))
    renderer = effect["renderer"]
    required_names.add(f"renderer:{renderer['name']}:{renderer['operation']}")
    if space in ANCHOR_REQUIREMENTS:
        capability_id = anchor.get("capability_id")
        require(isinstance(capability_id, str) and capability_id in capabilities, "unknown_anchor", "Spatial anchor requires a known capability ID", proposal_id)
        name = ANCHOR_REQUIREMENTS[space]
        require(_capability_matches(capabilities[capability_id], candidate, name), "anchor_unverified",
                "Anchor tracking/camera is not verified over the full interval", proposal_id)
        used.add(capability_id)
        required_names.add(name)
    elif anchor.get("capability_id") is not None:
        raise ValidationError("anchor_binding", "Screen/none anchors cannot claim spatial tracking", proposal_id)
    for binding_name, capability_name in binding_requirements.items():
        capability_id = bindings[binding_name]
        require(isinstance(capability_id, str) and capability_id in capabilities, "unknown_binding", "Binding requires a known capability ID", proposal_id)
        require(_capability_matches(capabilities[capability_id], candidate, capability_name), "binding_unverified",
                f"Binding {binding_name} is not verified over the full interval", proposal_id)
        used.add(capability_id)
        required_names.add(capability_name)
    for name in sorted(required_names):
        matches = sorted(capability_id for capability_id, cap in capabilities.items()
                         if _capability_matches(cap, candidate, name))
        require(bool(matches), "missing_capability", f"Required capability {name} is unavailable or unverified for this interval", proposal_id)
        if not any(capabilities[capability_id]["name"] == name for capability_id in used):
            used.add(matches[0])
    return {"proposal": candidate, "effect": effect, "capability_ids": sorted(used), "region": _region(candidate)}


def _score(item: dict, policy: dict, repetitions: dict[str, int]) -> dict:
    proposal = item["proposal"]
    weights = policy["weights"]
    editorial = sum(proposal["scores"][key] * weights[key] for key in SCORE_KEYS) / sum(weights.values())
    # This is an explicit scheduling preference, not an inferred quality metric.
    coverage_bonus = policy["opportunity_bonus"] * min(2, len(proposal.get("addresses", [])))
    penalty = policy["repetition_penalty"] * repetitions.get(proposal["effect_id"], 0)
    return {"editorial": round(editorial, 8), "opportunity_bonus": round(coverage_bonus, 8),
            "repetition_penalty": round(penalty, 8), "total": round(editorial + coverage_bonus - penalty, 8)}


def _spatial_overlap(left: list[float], right: list[float]) -> bool:
    return (min(left[0] + left[2], right[0] + right[2]) > max(left[0], right[0]) + EPSILON
            and min(left[1] + left[3], right[1] + right[3]) > max(left[1], right[1]) + EPSILON)


def _conflict(item: dict, selected: list[dict], policy: dict) -> tuple[str, list[str]] | None:
    candidate, effect = item["proposal"], item["effect"]
    temporal = [other for other in selected if other["proposal"]["source_id"] == candidate["source_id"]
                and overlaps(other["proposal"]["interval"], candidate["interval"])]
    for other in temporal:
        existing, other_effect = other["proposal"], other["effect"]
        if effect is None or other_effect is None:
            if effect is not None or other_effect is not None:
                return "preservation_conflict", [existing["id"]]
            continue
        if (existing["effect_id"] in effect.get("conflicts", []) or
                candidate["effect_id"] in other_effect.get("conflicts", [])):
            return "declared_effect_conflict", [existing["id"]]
        common = set(effect["occupied_channels"]) & set(other_effect["occupied_channels"])
        if common and (effect["modality"] in {"audio", "av"} or other_effect["modality"] in {"audio", "av"}
                       or _spatial_overlap(item["region"], other["region"])):
            return "occupied_channel", [existing["id"]]
    if effect is not None:
        for family, modalities in (("visual", {"visual", "av"}), ("audio", {"audio", "av"})):
            if effect["modality"] not in modalities:
                continue
            related = [other for other in temporal if other["effect"] and other["effect"]["modality"] in modalities]
            points = {candidate["interval"]["start_s"], candidate["interval"]["end_s"]}
            for other in related:
                points.add(max(candidate["interval"]["start_s"], other["proposal"]["interval"]["start_s"]))
                points.add(min(candidate["interval"]["end_s"], other["proposal"]["interval"]["end_s"]))
            ordered = sorted(points)
            for start, end in zip(ordered, ordered[1:]):
                middle = (start + end) / 2
                active = [other for other in related if other["proposal"]["interval"]["start_s"] <= middle < other["proposal"]["interval"]["end_s"]]
                if len(active) + 1 > policy[f"max_{family}_layers"]:
                    return f"{family}_layer_limit", [other["proposal"]["id"] for other in active]
    return None


def _decision(item: dict, score: dict, version: int) -> dict:
    proposal, effect = item["proposal"], item["effect"]
    operation = None
    if effect is not None:
        operation = {
            "renderer": effect["renderer"]["name"], "operation": effect["renderer"]["operation"],
            "effect_version": effect["version"], "params": clone(proposal.get("params", {})),
            "anchor": clone(proposal["anchor"]), "bindings": clone(proposal.get("bindings", {})),
            "source_id": proposal["source_id"], "source_sha256": proposal["source_sha256"],
            "clock": "source", "interval": clone(proposal["interval"]),
        }
    return {
        "id": "decision:" + proposal["id"], "revision": version,
        "event_id": proposal["event_id"], "effect_id": proposal["effect_id"],
        "source_id": proposal["source_id"], "source_sha256": proposal["source_sha256"],
        "clock": "source", "interval": clone(proposal["interval"]),
        "why": proposal["why"], "evidence_ids": clone(proposal["evidence_ids"]),
        "proposal": clone(proposal), "score": score, "score_kind": "declared_editorial_scores_with_explicit_policy",
        "capability_ids": item["capability_ids"], "manifest_snapshot": clone(effect), "operation": operation,
    }


def _seal(plan: dict) -> dict:
    plan.pop("plan_sha256", None)
    plan["plan_sha256"] = digest(plan)
    return plan


def assert_plan_digest(plan: dict) -> None:
    mapping(plan, "plan")
    unsigned = {key: value for key, value in plan.items() if key != "plan_sha256"}
    require(plan.get("plan_sha256") == digest(unsigned), "plan_hash_mismatch", "Plan content changed without a new revision")


def build_plan(analysis: dict, catalog: dict, proposals: dict, *, plan_id: str = "editorial-plan",
               version: int = 1, policy: dict | None = None, verify_files: bool = False) -> dict:
    data = validate_analysis(analysis, verify_files=verify_files)
    manifest = validate_catalog(catalog)
    candidate_input = clone(mapping(proposals, "proposals"))
    require(candidate_input.get("schema_version") == SCHEMA_VERSION, "schema_version", "Unsupported proposals version")
    candidates = index_by_id(candidate_input.get("candidates"), "proposals.candidates")
    nonempty(plan_id, "plan_id")
    integer(version, "version", minimum=1)
    settings = _policy(policy)
    sources = index_by_id(data["sources"], "sources")
    evidence = index_by_id(data["evidence"], "evidence")
    events = index_by_id(data["events"], "events")
    capabilities = index_by_id(data.get("capabilities", []), "capabilities")
    effects = index_by_id(manifest["effects"], "effects")
    valid, preserved, discarded = [], [], []
    for proposal_id, candidate in sorted(candidates.items()):
        try:
            checked = _validate_candidate(candidate, sources, evidence, events, capabilities, effects)
            (preserved if checked["effect"] is None else valid).append(checked)
        except ValidationError as exc:
            discarded.append({"proposal_id": proposal_id, "event_id": candidate.get("event_id"),
                              "effect_id": candidate.get("effect_id"), "stage": "eligibility", "issues": exc.issues})
    selected, decisions, repetitions = [], [], {}
    while valid:
        valid.sort(key=lambda item: (-_score(item, settings, repetitions)["total"], item["proposal"]["id"]))
        item = valid.pop(0)
        candidate = item["proposal"]
        score = _score(item, settings, repetitions)
        issue, blockers = None, []
        # High bonuses must never rescue unsuitable or infeasible effects.
        if score["editorial"] < settings["minimum_score"]:
            issue = "below_editorial_threshold"
        elif repetitions.get(candidate["effect_id"], 0) >= settings["max_effect_repetitions"]:
            issue = "repetition_limit"
        else:
            conflict = _conflict(item, selected, settings)
            if conflict:
                issue, blockers = conflict
        if issue:
            discarded.append({"proposal_id": candidate["id"], "event_id": candidate["event_id"],
                              "effect_id": candidate["effect_id"], "stage": "selection", "score": score,
                              "issues": [{"code": issue, "message": issue.replace("_", " "), "path": candidate["id"]}],
                              "blocked_by": blockers})
            continue
        selected.append(item)
        decisions.append(_decision(item, score, version))
        repetitions[candidate["effect_id"]] = repetitions.get(candidate["effect_id"], 0) + 1

    # Preserve is an explicit, reasoned fallback for an event with no selected
    # intervention. It never wins merely because doing nothing has low cost.
    preserved.sort(key=lambda item: (-_score(item, settings, {})["total"], item["proposal"]["id"]))
    for item in preserved:
        candidate = item["proposal"]
        if any(other["event_id"] == candidate["event_id"] for other in decisions):
            code = "preserve_not_needed"
        elif _conflict(item, selected, settings):
            code = "preservation_conflict"
        else:
            selected.append(item)
            decisions.append(_decision(item, _score(item, settings, {}), version))
            continue
        discarded.append({"proposal_id": candidate["id"], "event_id": candidate["event_id"], "effect_id": "preserve",
                          "stage": "selection", "issues": [{"code": code, "message": code.replace("_", " "), "path": candidate["id"]}]})

    decisions.sort(key=lambda item: (item["source_id"], item["interval"]["start_s"], item["id"]))
    discarded.sort(key=lambda item: item["proposal_id"])
    missed, planned = [], []
    for event_id, event in events.items():
        event_decisions = [decision for decision in decisions if decision["event_id"] == event_id]
        for opportunity in event.get("opportunities", []):
            addressing = [decision["id"] for decision in event_decisions if opportunity["id"] in decision["proposal"].get("addresses", [])]
            record = {"event_id": event_id, "opportunity_id": opportunity["id"], "function": opportunity["function"], "why": opportunity["why"]}
            if addressing:
                planned.append({**record, "status": "planned_not_render_verified", "decision_ids": addressing})
            else:
                missed.append({**record, "status": "unaddressed", "reason": "preserved_with_reason" if any(d["effect_id"] == "preserve" for d in event_decisions) else "no_eligible_selected_proposal"})
    unresolved = sorted(set(events) - {decision["event_id"] for decision in decisions})
    return _seal({
        "schema_version": SCHEMA_VERSION, "plan_id": plan_id, "version": version,
        "analysis_sha256": digest(data), "catalog_sha256": digest(manifest),
        "proposals_sha256": digest(candidate_input), "input_proposals": candidate_input,
        "policy_snapshot": settings, "decisions": decisions, "discarded": discarded,
        "planned_opportunities": planned, "missed_opportunities": missed, "unresolved_events": unresolved,
        "history": [],
        "validation": {"schema_valid": True, "file_integrity_verified": verify_files,
                       "executable": bool(decisions) and not unresolved and verify_files,
                       "capability_basis": "upstream_verification_attestations_and_report_hashes",
                       "perceptual_validation": "not_performed", "approved_by_user": False},
    })


def validate_plan(plan: dict, analysis: dict, catalog: dict, *, verify_files: bool = False) -> dict:
    assert_plan_digest(plan)
    require(plan.get("analysis_sha256") == digest(analysis), "analysis_changed", "Analysis changed since this plan")
    require(plan.get("catalog_sha256") == digest(catalog), "catalog_changed", "Catalog changed since this plan")
    rebuilt = build_plan(analysis, catalog, plan["input_proposals"], plan_id=plan["plan_id"],
                         version=plan["version"], policy=plan["policy_snapshot"], verify_files=verify_files)
    require(set(plan) == set(rebuilt), "plan_schema", "Plan contains missing or undeclared fields")
    excluded = {"plan_sha256", "validation", "history"}
    for key in set(rebuilt) - excluded:
        require(plan.get(key) == rebuilt[key], "plan_replay_mismatch", f"Plan field {key} cannot be reproduced", key)
    require(plan["validation"].get("schema_valid") is True, "plan_validation", "Invalid plan validation record")
    require(type(plan["validation"].get("file_integrity_verified")) is bool, "plan_validation", "Missing file verification state")
    expected_executable = bool(plan["decisions"]) and not plan["unresolved_events"] and plan["validation"]["file_integrity_verified"]
    require(plan["validation"].get("executable") is expected_executable, "plan_validation", "Executable state does not match recorded verification")
    expected_validation = clone(rebuilt["validation"])
    expected_validation["file_integrity_verified"] = plan["validation"]["file_integrity_verified"]
    expected_validation["executable"] = expected_executable
    require(plan["validation"] == expected_validation, "plan_validation", "Planning cannot claim perceptual review or user approval")
    history = sequence(plan.get("history", []), "history")
    previous_version = None
    for entry in history:
        mapping(entry, "history.entry")
        sha256(entry.get("base_plan_sha256"), "history.base_plan_sha256")
        nonempty(entry.get("reason"), "history.reason")
        integer(entry.get("base_version"), "history.base_version", minimum=1)
        require(entry["base_version"] < plan["version"], "history_version", "History cannot point to a future revision")
        require(previous_version is None or entry["base_version"] == previous_version + 1,
                "history_version", "Patch history revisions must be consecutive")
        previous_version = entry["base_version"]
        strings(entry.get("changed_decision_ids"), "history.changed_decision_ids", allow_empty=False)
        if entry.get("render_sha256") is not None:
            sha256(entry["render_sha256"], "history.render_sha256")
    require(not history or previous_version == plan["version"] - 1,
            "history_version", "History must end at the immediately preceding revision")
    return {"valid": True, "plan_sha256": plan["plan_sha256"], "files_verified": verify_files,
            "executable_now": bool(plan["decisions"]) and not plan["unresolved_events"] and verify_files,
            "perceptual_validation": "not_performed"}


def apply_patch(plan: dict, patch: dict, analysis: dict, catalog: dict, review: dict | None = None) -> dict:
    """Apply a scoped proposal replacement to one version, invalidating old QA."""
    validate_plan(plan, analysis, catalog, verify_files=plan["validation"]["file_integrity_verified"])
    change = clone(mapping(patch, "patch"))
    require(change.get("base_plan_sha256") == plan["plan_sha256"] and change.get("base_version") == plan["version"],
            "stale_patch", "Patch refers to a different plan revision")
    nonempty(change.get("reason"), "patch.reason")
    updates = sequence(change.get("updates"), "patch.updates")
    require(bool(updates), "empty_patch", "Patch needs at least one localized update")
    if review is not None:
        require(review.get("plan_sha256") == plan["plan_sha256"], "stale_review", "Review belongs to another plan")
        require(review.get("retry_count", 0) < review.get("max_retries", 0), "retry_limit", "Review repair budget is exhausted")
    decisions = {decision["id"]: decision for decision in plan["decisions"]}
    replacements, changed_ids = {}, set()
    for update in updates:
        mapping(update, "patch.update")
        decision_id = update.get("decision_id")
        require(decision_id in decisions, "unknown_decision", "Patch refers to an unknown decision")
        require(decision_id not in changed_ids, "duplicate_patch", "Decision is updated more than once")
        original = decisions[decision_id]
        require(update.get("expected_revision") == original["revision"], "stale_patch", "Decision revision changed")
        proposal = mapping(update.get("proposal"), "patch.proposal")
        require(proposal.get("id") == original["proposal"]["id"] and proposal.get("event_id") == original["event_id"],
                "patch_scope", "Patch must retain the proposal and event identity")
        replacements[proposal["id"]] = proposal
        changed_ids.add(decision_id)
    candidate_input = clone(plan["input_proposals"])
    candidate_input["candidates"] = [replacements.get(candidate["id"], candidate) for candidate in candidate_input["candidates"]]
    updated = build_plan(analysis, catalog, candidate_input, plan_id=plan["plan_id"], version=plan["version"] + 1,
                         policy=plan["policy_snapshot"], verify_files=plan["validation"]["file_integrity_verified"])
    rejected_ids = {item["proposal_id"] for item in updated["discarded"] if item["stage"] == "eligibility"}
    require(not rejected_ids.intersection(replacements), "invalid_patch", "A replacement failed evidence/capability validation")
    selected_ids = {decision["proposal"]["id"] for decision in updated["decisions"]}
    require(set(replacements) <= selected_ids, "invalid_patch_selection",
            "A replacement was not selected; repair its conflicts or submit a separately scoped plan")
    old = {decision["id"]: decision["proposal"] for decision in plan["decisions"] if decision["id"] not in changed_ids}
    new = {decision["id"]: decision["proposal"] for decision in updated["decisions"] if decision["id"] not in changed_ids}
    require(old == new, "nonlocal_patch", "Patch would alter an unlisted decision; include every affected decision in the revision")
    updated["history"] = clone(plan.get("history", [])) + [{
        "base_plan_sha256": plan["plan_sha256"], "base_version": plan["version"],
        "reason": change["reason"], "changed_decision_ids": sorted(changed_ids),
        "render_sha256": review.get("render_sha256") if review else None,
    }]
    _seal(updated)
    revised_review = None
    if review is not None:
        from .review import invalidate_review
        revised_review = invalidate_review(review, updated["plan_sha256"], reason="plan_changed_by_localized_patch", consume_retry=True)
    return {"plan": updated, "review": revised_review}
