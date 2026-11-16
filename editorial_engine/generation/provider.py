"""One explicitly configured direction call for the generation-plan schema.

This calls a text/multimodal director, never a video or image generator. Its
result remains authored direction, not proof of perception or provider fidelity.
An injected transport is always labelled simulated, so unit tests cannot become
evidence that a real model was contacted. There is no heuristic fallback.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

from ..contracts import (clone, digest, integer, mapping, nonempty, overlaps,
                         require, sequence, sha256, verify_file)
from .contracts import validate_plan

_REQUEST_MAX = 20 * 1024 * 1024
_RESPONSE_MAX = 4 * 1024 * 1024


def request_payload(request):
    """Validate the prepared envelope and its actual image/file bindings."""
    request = clone(mapping(request, "request"))
    require(request.get("schema") == "video-generation-director-request/1", "generation_request",
            "Use the generation director request schema, not the contextual editing schema")
    body = mapping(request.get("body"), "request.body")
    require(request.get("request_sha256") == digest(body), "request_hash", "Direction request changed")
    messages = sequence(body.get("messages"), "request.body.messages")
    require(len(messages) == 2 and messages[0].get("role") == "system" and messages[1].get("role") == "user",
            "request_messages", "Expected the prepared director and project messages")
    content = messages[1].get("content")
    images = []
    if isinstance(content, str):
        text = content
    else:
        parts = sequence(content, "request.content")
        require(bool(parts) and parts[0].get("type") == "text", "request_context", "Project JSON must precede the images")
        text = parts[0].get("text")
        for part in parts[1:]:
            mapping(part, "request.content[]")
            require(part.get("type") in {"text", "image_url"}, "request_content", "Unsupported director content type")
            if part["type"] == "image_url":
                images.append(mapping(part.get("image_url"), "image_url").get("url"))
    payload = mapping(json.loads(text), "request.payload")
    require(payload.get("brief") == request.get("brief") and
            payload.get("review_scope") == request.get("review_scope") and
            payload.get("briefing") == request.get("briefing") and
            payload.get("response_contract") == request.get("response_contract"), "request_context",
            "Envelope and hashed project context disagree")
    require(request.get("analysis_sha256") == (digest(payload["analysis"]) if payload.get("analysis") is not None else None)
            and request.get("assets_sha256") == digest(payload.get("assets")), "request_context",
            "Analysis or asset fingerprints disagree with the hashed context")
    reference = payload.get("reference_context")
    templates = payload.get("template_library")
    require(request.get("reference_context_sha256") == (digest(reference) if reference is not None else None)
            and request.get("template_library_sha256") == (templates["library_sha256"] if templates is not None else None),
            "request_context", "Reference or template fingerprints disagree with the hashed context")
    require(payload.get("briefing", {}).get("ready_for_direction") is True, "brief_incomplete",
            "Resolve essential briefing questions before calling the director")
    limits = mapping(payload.get("request_limits"), "request_limits")
    maximum = integer(limits.get("max_request_bytes"), "request_limits.max_request_bytes", minimum=1)
    require(maximum <= _REQUEST_MAX, "request_size", "Request byte budget exceeds the supported bound")
    require(len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")) <= maximum,
            "request_size", "Direction request exceeds its declared budget")
    files = sequence(payload.get("file_manifest"), "file_manifest")
    for item in files:
        mapping(item, "file_manifest[]")
        nonempty(item.get("path"), "file_manifest.path")
        require(Path(item["path"]).is_absolute(), "absolute_path", "Input files need absolute paths")
        sha256(item.get("sha256"), "file_manifest.sha256")
        verify_file(item["path"], item["sha256"], "director input")
    manifest = sequence(payload.get("image_manifest"), "image_manifest")
    frame_budget = integer(limits.get("max_frames"), "request_limits.max_frames", minimum=1)
    image_budget = integer(limits.get("max_image_bytes"), "request_limits.max_image_bytes", minimum=1)
    require(frame_budget <= 96 and image_budget <= 4 * 1024 * 1024, "image_budget", "Invalid image budget")
    require(len(manifest) == len(images) <= frame_budget, "image_manifest", "Supplied images and manifest/budget disagree")
    allowed = {(f["path"], f["sha256"]) for f in files}
    for record, url in zip(manifest, images):
        require((record.get("path"), record.get("sha256")) in allowed, "image_manifest", "Image is outside the verified file manifest")
        prefix = "data:" + record["mime_type"] + ";base64,"
        require(isinstance(url, str) and url.startswith(prefix), "image_manifest", "Image MIME and prepared bytes disagree")
        try:
            raw = base64.b64decode(url[len(prefix):], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid embedded image encoding") from exc
        require(len(raw) == record["bytes"] <= image_budget and raw == Path(record["path"]).read_bytes(),
                "image_manifest", "Embedded image bytes do not match the verified local image")
    require(payload["review_scope"].get("image_ids") == [r["id"] for r in manifest],
            "image_scope", "Review scope must enumerate exactly the supplied images")
    require(payload["review_scope"].get("continuous_motion_review") is False and
            payload["review_scope"].get("listened_audio") is False and
            payload["review_scope"].get("semantic_inference_executed") is False,
            "request_attestation", "Preparing image samples cannot certify playback, listening or inference")
    return payload


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _transport(*, endpoint, body, headers, timeout_s, max_response_bytes):
    outgoing = urllib.request.Request(endpoint, json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                                      headers, method="POST")
    try:
        # The caller authorized this exact endpoint, not forwarding image data
        # or credentials to a redirect target selected by a server.
        with urllib.request.build_opener(_NoRedirect()).open(outgoing, timeout=timeout_s) as response:
            raw = response.read(max_response_bytes + 1)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Configured generation director failed; no fallback plan was created") from exc
    require(len(raw) <= max_response_bytes, "response_size", "Director response exceeds the byte budget")
    return json.loads(raw)


def validate_editorial_inputs(plan, editorial_inputs):
    """Keep explicit clip limits and literal speech on any authored plan.

    Callers validate the generation-plan schema separately. This shared check
    reads no files, performs no perception and does not mutate either argument.
    A missing field adds no constraint. It returns the same plan object so both
    manual imports and provider responses can use the same invariants.
    """
    mapping(plan, "plan")
    inputs = mapping(editorial_inputs, "editorial_inputs")
    if "clip_count" in inputs:
        require(len(plan["clips"]) == inputs["clip_count"], "clip_count_changed",
                "Authored plan changed the requested clip count")
    if "clip_duration_s" in inputs:
        require(all(c["duration_s"] == inputs["clip_duration_s"] for c in plan["clips"]),
                "clip_duration_changed", "Authored plan changed the requested generated clip duration")
    if isinstance(inputs.get("dialogue_text"), str):
        spoken = " ".join(d["text"] for c in plan["clips"] for d in c["dialogue"])
        require(spoken == inputs["dialogue_text"], "literal_dialogue_changed",
                "Authored plan changed the supplied literal dialogue")
    return plan


def _response_plan(response, payload, model, simulated):
    response = clone(mapping(response, "provider_response"))
    choices = sequence(response.get("choices"), "provider_response.choices")
    require(len(choices) == 1, "response_choice", "The director must return exactly one plan")
    message = mapping(choices[0].get("message"), "provider_response.message")
    require(not message.get("tool_calls") and not message.get("function_call"), "response_action",
            "A generation director returns plan data, not tool execution requests")
    text = nonempty(message.get("content"), "provider_response.content")
    plan = mapping(json.loads(text), "provider_plan")
    plan["author"] = {"kind": "model", "actor": model,
                      "method": "Injected transport fixture; no model inference" if simulated else
                                "Configured generation direction endpoint; supplied still samples and attributed context"}
    require("provider_receipt" not in plan, "response_attestation", "The transport, not the model, records provider execution")
    plan = validate_plan(plan)
    for field, value in payload["brief"].items():
        require(plan["brief"].get(field) == value, "brief_changed", "Director changed a resolved briefing value", "brief." + field)
    validate_editorial_inputs(plan, payload["editorial_inputs"])
    allowed = {(f["path"], f["sha256"]) for f in payload["file_manifest"]}
    for item in plan["references"] + [a for a in plan["assets"] if a["status"] == "ready"]:
        require((item["path"], item["sha256"]) in allowed, "unprovided_file",
                "Director invented or substituted a ready file outside the prepared inputs", item["id"])
        kinds = {f.get("kind") for f in payload["file_manifest"] if (f["path"], f["sha256"]) == (item["path"], item["sha256"])}
        require(None in kinds or item["kind"] in kinds, "provided_file_kind", "Director changed the declared input media kind", item["id"])
    known_context = payload["authoring_context"]
    known_references = {r["id"]: r for r in known_context["references"]}
    references = {r["id"]: r for r in plan["references"]}
    for key, reference in references.items():
        if key in known_references:
            expected = known_references[key]
            for field in ("path", "sha256", "kind", "duration_s"):
                if field in expected:
                    require(reference.get(field) == expected[field], "provided_reference_changed", "Reference facts changed", key)
    known_evidence = {e["id"]: e for e in known_context["evidence"]}
    for item in plan["evidence"]:
        if item["id"] in known_evidence:
            expected = known_evidence[item["id"]]
            for field in ("source_id", "source_sha256", "observation", "scope", "interval"):
                require(item.get(field) == expected.get(field), "attributed_evidence_changed",
                        "Preserve the supplied observation, source and declared scope", item["id"])
            item["provenance"] = clone(expected["provenance"])
            continue
        require(item["scope"] == "sampled_frames", "unobserved_scope",
                "New model observations may describe only supplied still samples; preserve prior attributed evidence verbatim")
        reference = references[item["source_id"]]
        samples = []
        for sample in payload["image_manifest"]:
            if sample.get("source_sha256") == reference["sha256"]:
                if "interval" not in item or overlaps(sample["interval"], item["interval"]):
                    samples.append(sample["id"])
            elif sample["sha256"] == reference["sha256"] and reference["kind"] == "image":
                samples.append(sample["id"])
        require(bool(samples), "unseen_source", "New visual observation has no supplied image from this source/interval", item["id"])
        item["provenance"] = clone(plan["author"])
        item["supplied_image_ids"] = samples
    return validate_plan(plan, verify_files=True)


def call_provider(request, *, endpoint, model, api_key_env=None, timeout_s=45,
                  transport=None, max_response_bytes=_RESPONSE_MAX):
    """Return a validated plan at the root, with an execution receipt.

    ``transport`` is a test seam: callable(**endpoint, body, headers, timeout_s,
    max_response_bytes) -> compatible JSON response. Supplying it always records
    transport_kind=injected_simulation and model_inference_executed=False.
    This function neither saves files nor calls any image/video generator.
    """
    payload = request_payload(request)
    nonempty(model, "model")
    nonempty(endpoint, "endpoint")
    parsed = urllib.parse.urlsplit(endpoint)
    require(parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}),
            "endpoint", "Use HTTPS or a local HTTP director endpoint")
    require(bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment,
            "endpoint", "Endpoint must not contain embedded credentials or a fragment")
    require(type(timeout_s) in {int, float} and 0 < timeout_s <= 60, "timeout", "Timeout must be at most 60 seconds")
    integer(max_response_bytes, "max_response_bytes", minimum=1)
    require(max_response_bytes <= _RESPONSE_MAX, "response_size", "Response budget cannot exceed 4 MiB")
    headers = {"Content-Type": "application/json"}
    if api_key_env is not None:
        require(isinstance(api_key_env, str) and api_key_env.isidentifier(), "credential_env", "Invalid credential environment name")
        credential = os.environ.get(api_key_env)
        require(bool(credential), "credential_missing", "Configured credential is absent")
        headers["Authorization"] = "Bearer " + credential
    body = {**clone(request["body"]), "model": model}
    require(len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")) <= payload["request_limits"]["max_request_bytes"],
            "request_size", "Request with model identifier exceeds its byte budget")
    simulated = transport is not None
    response = (transport or _transport)(endpoint=endpoint, body=body, headers=headers,
                                         timeout_s=timeout_s, max_response_bytes=max_response_bytes)
    require(len(json.dumps(response, ensure_ascii=False, allow_nan=False).encode("utf-8")) <= max_response_bytes,
            "response_size", "Director response exceeds the byte budget")
    # Re-check all source bytes after the call before accepting its result.
    request_payload(request)
    plan = _response_plan(response, payload, model, simulated)
    plan["provider_receipt"] = {"schema": "video-generation-direction-receipt/1",
                                "request_sha256": request["request_sha256"], "response_sha256": digest(response),
                                "plan_sha256": digest(plan), "model": model,
                                "analysis_sha256": request.get("analysis_sha256"),
                                "reference_context_sha256": request.get("reference_context_sha256"),
                                "template_library_sha256": request.get("template_library_sha256"),
                                "input_manifest_sha256": digest(payload["file_manifest"]),
                                "endpoint_sha256": digest(endpoint), "transport_kind": "injected_simulation" if simulated else "configured_http",
                                "model_inference_executed": not simulated, "media_generation_executed": False,
                                "review_scope": clone(payload["review_scope"]),
                                "supplied_image_ids": [i["id"] for i in payload["image_manifest"]],
                                "provider_input_use": "unverified", "continuous_playback": "not_supplied",
                                "audio_listening": "not_supplied", "perceptual_quality": "unverified", "user_approval": "unverified"}
    plan["provider_receipt"]["receipt_sha256"] = digest(plan["provider_receipt"])
    return plan
