"""Effect manifests describe executable capabilities, never infer their presence."""

from __future__ import annotations

from .contracts import (SCHEMA_VERSION, clone, index_by_id, mapping, nonempty,
                        number, require, sequence, strings)

ANCHOR_REQUIREMENTS = {"hand": "hand_tracking", "body": "body_tracking",
                       "planar": "planar_tracking", "world": "camera_solve"}
PARAMETER_TYPES = {"number", "integer", "string", "boolean", "array", "object"}


def validate_catalog(catalog: dict) -> dict:
    data = clone(mapping(catalog, "catalog"))
    require(data.get("schema_version") == SCHEMA_VERSION, "schema_version", "Unsupported catalog version")
    effects = index_by_id(data.get("effects"), "effects")
    for effect_id, effect in effects.items():
        path = f"effects.{effect_id}"
        require(effect_id != "preserve", "reserved_id", "preserve is a built-in editorial decision", path)
        nonempty(effect.get("version"), path + ".version")
        require(effect.get("status") in ("ready", "draft"), "effect_status", "Expected ready or draft", path)
        strings(effect.get("functions"), path + ".functions", allow_empty=False)
        require(effect.get("modality") in ("visual", "audio", "av"), "modality", "Unsupported effect modality", path)
        renderer = mapping(effect.get("renderer"), path + ".renderer")
        nonempty(renderer.get("name"), path + ".renderer.name")
        nonempty(renderer.get("operation"), path + ".renderer.operation")
        requirements = strings(effect.get("requirements", []), path + ".requirements")
        anchors = strings(effect.get("anchors"), path + ".anchors", allow_empty=False)
        require(set(anchors) <= {"screen", "none", *ANCHOR_REQUIREMENTS}, "anchor_space", "Unsupported anchor space", path)
        bindings = mapping(effect.get("binding_requirements", {}), path + ".binding_requirements")
        for key, value in bindings.items():
            nonempty(key, path + ".binding_requirements")
            nonempty(value, path + ".binding_requirements." + key)
        parameters = mapping(effect.get("parameters", {}), path + ".parameters")
        for key, raw in parameters.items():
            spec = mapping(raw, path + ".parameters." + key)
            require(isinstance(spec.get("type"), str) and spec["type"] in PARAMETER_TYPES, "parameter_type", "Unsupported parameter type", path + ".parameters." + key)
            require(type(spec.get("required", False)) is bool, "type", "required must be boolean", path)
            if "minimum" in spec:
                number(spec["minimum"], path + ".parameters." + key + ".minimum")
            if "maximum" in spec:
                number(spec["maximum"], path + ".parameters." + key + ".maximum")
            if "minimum" in spec and "maximum" in spec:
                require(spec["minimum"] <= spec["maximum"], "parameter_range", "Invalid parameter bounds", path)
            if "enum" in spec:
                require(bool(sequence(spec["enum"], path + ".parameters." + key + ".enum")), "empty", "Enum must not be empty", path)
        strings(effect.get("occupied_channels"), path + ".occupied_channels", allow_empty=False)
        for key in ("conflicts", "fallbacks"):
            refs = strings(effect.get(key, []), path + "." + key)
            for ref in refs:
                require(ref in effects or (key == "fallbacks" and ref == "preserve"), "unknown_effect", f"Unknown {key} effect {ref}", path)
                require(ref != effect_id, "self_reference", "Effect cannot reference itself", path)
        # Requiring a renderer attestation is automatic in the planner; a
        # manifest cannot evade it by omitting it from requirements.
    return data


def validate_parameters(params: dict, effect: dict) -> None:
    values = mapping(params, "proposal.params")
    specs = effect.get("parameters", {})
    require(set(values) <= set(specs), "unknown_parameter", "Proposal includes undeclared parameters", "proposal.params")
    for key, spec in specs.items():
        if key not in values:
            require(not spec.get("required", False), "missing_parameter", f"Missing parameter {key}", "proposal.params")
            continue
        value = values[key]
        kind = spec["type"]
        valid_type = {
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "array": isinstance(value, list),
            "object": isinstance(value, dict),
        }[kind]
        require(valid_type, "parameter_type", f"Parameter {key} must be {kind}", "proposal.params." + key)
        if kind in {"number", "integer"}:
            number(value, "proposal.params." + key, minimum=spec.get("minimum"), maximum=spec.get("maximum"))
        if "enum" in spec:
            require(value in spec["enum"], "parameter_enum", f"Unsupported value for {key}", "proposal.params." + key)
