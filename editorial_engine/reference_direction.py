"""Attributed reference observations and explicit keep/replace decisions.

These contracts carry authored interpretation into either editorial direction
or video generation. They never inspect meaning, infer a replacement, copy a
reference's private assets, or turn a style description into an executable
effect. File verification proves identities, not that an observation is true.
"""

from __future__ import annotations

from pathlib import Path
import re

from .contracts import (clone, digest, index_by_id, integer, mapping, nonempty,
                        number, overlaps, provenance, require, sequence,
                        sha256, source_reference, strings, validate_analysis,
                        verify_file)

DOSSIER_SCHEMA = "reference-direction-dossier/1"
ADAPTATION_SCHEMA = "reference-adaptation/1"
ASPECTS = {"narrative", "composition", "camera", "rhythm", "transition",
           "identity", "wardrobe", "location", "prop", "lighting", "color",
           "typography", "motion", "audio", "voice"}
SCOPES = {"sampled_frames", "continuous_video", "audio_listened", "transcript",
          "human_note"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")


def _identifier(value, label):
    nonempty(value, label)
    require(bool(_ID.fullmatch(value)) and ".." not in value, "reference_id",
            "Use a portable identifier", label)
    return value


def _file(record, label, verify):
    nonempty(record.get("path"), label + ".path")
    require(Path(record["path"]).is_absolute(), "absolute_path", "Use an absolute local path", label)
    sha256(record.get("sha256"), label + ".sha256")
    if verify:
        verify_file(record["path"], record["sha256"], label)


def verified_analysis(analysis, *, verify_files=True):
    """Also check sample/transcript artifacts, beyond the common contract."""
    data = validate_analysis(analysis, verify_files=verify_files)
    for source in data["sources"]:
        _file(source, "analysis.source." + source["id"], verify_files)
    for item in data["evidence"]:
        for name in ("artifact", "transcript_artifact"):
            if name in item:
                _file(mapping(item[name], name), "analysis.evidence." + item["id"] + "." + name, verify_files)
    return data


def _observations(items, analysis):
    observations = clone(sequence(items, "observations"))
    indexed = index_by_id(observations, "observations")
    require(bool(indexed), "reference_observations", "Provide actual attributed observations")
    sources = index_by_id(analysis["sources"], "sources")
    evidence = index_by_id(analysis["evidence"], "evidence")
    for key, observation in indexed.items():
        label = "observations." + key
        _identifier(key, label + ".id")
        require(isinstance(observation.get("aspect"), str) and observation["aspect"] in ASPECTS,
                "reference_aspect", "Unknown observed aspect", label)
        nonempty(observation.get("description"), label + ".description")
        source_reference(observation, sources, label)
        provenance(observation.get("provenance"), label + ".provenance", kinds={"human", "model"})
        number(observation.get("confidence"), label + ".confidence", minimum=0, maximum=1)
        require(isinstance(observation.get("scope"), str) and observation["scope"] in SCOPES,
                "reference_scope", "Declare the actual observation scope", label)
        refs = strings(observation.get("evidence_ids"), label + ".evidence_ids", allow_empty=False)
        for identifier in refs:
            require(identifier in evidence, "unknown_evidence", "Unknown supporting evidence", label)
            item = evidence[identifier]
            require(item["source_id"] == observation["source_id"] and
                    overlaps(item["interval"], observation["interval"]), "reference_evidence_scope",
                    "Evidence must belong to the observed source and overlap its interval", label)
        kinds = {evidence[r]["kind"] for r in refs}
        if observation["scope"] in {"sampled_frames", "continuous_video"}:
            require("visual" in kinds, "reference_scope", "Visual observations need visual evidence", label)
        if observation["scope"] == "audio_listened":
            require("audio" in kinds, "reference_scope", "A transcript is not an audio-listening observation", label)
        if observation["scope"] == "transcript":
            require("transcript" in kinds, "reference_scope", "Transcript observations need transcript evidence", label)
    return observations


def build_dossier(analysis, observations, *, dossier_id, author, revision=1, verify_files=True):
    data = {"schema": DOSSIER_SCHEMA, "id": dossier_id, "revision": revision,
            "author": clone(author), "analysis": verified_analysis(analysis, verify_files=verify_files),
            "observations": clone(observations),
            "review_scope": {"interpretation": "attributed_observations", "automatic_perception": False,
                             "user_approval": "unverified"}}
    data["analysis_sha256"] = digest(data["analysis"])
    data["dossier_sha256"] = digest(data)
    return validate_dossier(data, verify_files=verify_files)


def validate_dossier(dossier, *, verify_files=True):
    data = clone(mapping(dossier, "dossier"))
    require(data.get("schema") == DOSSIER_SCHEMA, "reference_schema", "Unsupported reference dossier")
    _identifier(data.get("id"), "dossier.id")
    integer(data.get("revision"), "dossier.revision", minimum=1)
    provenance(data.get("author"), "dossier.author", kinds={"human", "model"})
    analysis = verified_analysis(data.get("analysis"), verify_files=verify_files)
    require(data.get("analysis_sha256") == digest(analysis), "reference_analysis_changed", "Dossier analysis changed")
    _observations(data.get("observations"), analysis)
    require(data.get("review_scope") == {"interpretation": "attributed_observations", "automatic_perception": False,
                                         "user_approval": "unverified"}, "reference_attestation",
            "A dossier cannot certify automatic perception or user approval")
    require(data.get("dossier_sha256") == digest({k: v for k, v in data.items() if k != "dossier_sha256"}),
            "reference_digest", "Dossier changed after authoring")
    return data


def validate_adaptation(contract, dossier, *, verify_files=True):
    dossier = validate_dossier(dossier, verify_files=verify_files)
    data = clone(mapping(contract, "adaptation"))
    require(data.get("schema") == ADAPTATION_SCHEMA, "adaptation_schema", "Unsupported reference adaptation")
    _identifier(data.get("id"), "adaptation.id")
    integer(data.get("revision"), "adaptation.revision", minimum=1)
    provenance(data.get("author"), "adaptation.author", kinds={"human", "model"})
    require(data.get("dossier_sha256") == dossier["dossier_sha256"], "stale_adaptation",
            "Adaptation decisions belong to another dossier revision")
    references = index_by_id(data.get("replacement_references", []), "replacement_references")
    for key, item in references.items():
        _identifier(key, "replacement_references.id")
        require(isinstance(item.get("kind"), str) and item["kind"] in {"image", "video", "audio", "document"},
                "reference_kind", "Unknown replacement reference kind")
        nonempty(item.get("role"), "replacement_references.role")
        _file(item, "replacement_references." + key, verify_files)
        if "duration_s" in item:
            number(item["duration_s"], "replacement_references.duration_s", minimum=0.000001)
    observations = {o["id"]: o for o in dossier["observations"]}
    decisions = sequence(data.get("decisions"), "decisions")
    addressed = set()
    for i, decision in enumerate(decisions):
        label = f"decisions[{i}]"
        mapping(decision, label)
        key = nonempty(decision.get("observation_id"), label + ".observation_id")
        require(key in observations and key not in addressed, "adaptation_observation",
                "Each observation requires one unique, explicit decision", label)
        addressed.add(key)
        require(isinstance(decision.get("action"), str) and decision["action"] in {"keep", "replace"},
                "adaptation_action", "Choose keep or replace", label)
        nonempty(decision.get("rationale"), label + ".rationale")
        if decision["action"] == "replace":
            nonempty(decision.get("target"), label + ".target")
        else:
            require("target" not in decision, "adaptation_target", "A keep decision must not silently replace its observation", label)
        for reference in strings(decision.get("reference_ids", []), label + ".reference_ids"):
            require(reference in references, "adaptation_reference", "Unknown replacement reference", label)
    require(addressed == set(observations), "adaptation_incomplete",
            "Decide keep or replace for every observed aspect; missing decisions are not inferred")
    expected = digest({k: v for k, v in data.items() if k != "adaptation_sha256"})
    if "adaptation_sha256" in data:
        require(data["adaptation_sha256"] == expected, "adaptation_digest", "Adaptation changed after validation")
    data["adaptation_sha256"] = expected
    return data


def _portable(prefix, value):
    return prefix + "-" + digest(value)[:20]


def analysis_context(analysis, *, verify_files=True):
    """Project technical/attributed input text, without creating new perception."""
    data = verified_analysis(analysis, verify_files=verify_files)
    references, evidence = [], []
    source_ids = {}
    for source in data["sources"]:
        identifier = _portable("ref", source["id"])
        source_ids[source["id"]] = identifier
        references.append({"id": identifier, "kind": source.get("kind", "video"),
                           "path": source["path"], "sha256": source["sha256"],
                           "role": "Source from supplied editorial analysis", "duration_s": source["duration_s"],
                           "analysis_source_id": source["id"]})
    for item in data["evidence"]:
        scope = "transcript" if item["kind"] == "transcript" else "human_note"
        evidence.append({"id": _portable("input", item["id"]), "source_id": source_ids[item["source_id"]],
                         "source_sha256": item["source_sha256"], "observation": item["observation"],
                         "scope": scope, "interval": clone(item["interval"]),
                         "provenance": clone(item["provenance"]), "origin_evidence_id": item["id"],
                         "interpretation": "supplied_attributed_note_not_new_inspection"})
    return {"references": references, "evidence": evidence}


def _project(dossier, contract, verify_files):
    dossier = validate_dossier(dossier, verify_files=verify_files)
    contract = validate_adaptation(contract, dossier, verify_files=verify_files)
    observations = {o["id"]: o for o in dossier["observations"]}
    decisions = [{**clone(d), "observation": clone(observations[d["observation_id"]])} for d in contract["decisions"]]
    return dossier, contract, decisions


def to_contextual_profile(dossier, contract, *, verify_files=True):
    dossier, contract, decisions = _project(dossier, contract, verify_files)
    result = {"schema": "reference-contextual-profile/1", "id": contract["id"],
              "dossier_sha256": dossier["dossier_sha256"], "adaptation_sha256": contract["adaptation_sha256"],
              "keep": [d for d in decisions if d["action"] == "keep"],
              "replace": [d for d in decisions if d["action"] == "replace"],
              "replacement_references": clone(contract.get("replacement_references", [])),
              "review_scope": clone(dossier["review_scope"]),
              "execution": "authoring_context_only; no effect IDs, source assets or runtime capabilities are inferred"}
    result["profile_sha256"] = digest(result)
    return result


def generation_context(dossier, contract, *, verify_files=True):
    dossier, contract, decisions = _project(dossier, contract, verify_files)
    context = analysis_context(dossier["analysis"], verify_files=verify_files)
    source_ids = {r["analysis_source_id"]: r["id"] for r in context["references"]}
    context["evidence"] = [{"id": _portable("observed", o["id"]), "source_id": source_ids[o["source_id"]],
                            "source_sha256": o["source_sha256"], "observation": o["description"],
                            "scope": o["scope"], "interval": clone(o["interval"]),
                            "provenance": clone(o["provenance"]), "origin_observation_id": o["id"]}
                           for o in dossier["observations"]]
    replacements = clone(contract.get("replacement_references", []))
    existing_ids = {r["id"] for r in context["references"]}
    require(not existing_ids & {r["id"] for r in replacements}, "reference_collision", "Replacement reference IDs collide with source IDs")
    context["references"].extend(replacements)
    context.update(schema="reference-generation-context/1", dossier_sha256=dossier["dossier_sha256"],
                   adaptation_sha256=contract["adaptation_sha256"], decisions=decisions,
                   review_scope=clone(dossier["review_scope"]),
                   execution="direction_context_only; replacement media and semantic compliance still need production and review")
    context["context_sha256"] = digest(context)
    return context
