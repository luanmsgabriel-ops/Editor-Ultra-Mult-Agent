"""Persistent intake and execution bridges for Clone's eleven entry routes.

The project owns dependencies and versions, not creative judgments. Every
executed stage calls an existing, file-verifying engine. Missing direction or
media becomes a work item; registering a request never counts as producing it.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from .contracts import (ValidationError, clone, digest, file_sha256, mapping,
                        nonempty, require, sequence, verify_file)

SPEC_SCHEMA = "clone-project-spec/1"
PROJECT_SCHEMA = "clone-project/1"
ROUTES = {
    "edit": {"input_roles": ["footage"], "engine": "contextual", "label": "Editar um vídeo"},
    "montage": {"input_roles": ["footage"], "engine": "assembly", "label": "Montar vários vídeos"},
    "style_transfer": {"input_roles": ["footage", "reference"], "engine": "contextual", "label": "Aplicar a linguagem de uma referência"},
    "reconstruct": {"input_roles": ["footage", "reference"], "engine": "assembly", "label": "Recompor a referência com novas filmagens"},
    "reference_generate": {"input_roles": ["reference"], "engine": "generation", "label": "Gerar novos personagens e cenas com referência"},
    "original": {"input_roles": [], "engine": "generation", "label": "Criar sem referência"},
    "media_story": {"input_roles": [], "engine": "generation", "label": "Criar a partir de imagens, roteiro ou áudio"},
    "fill_gaps": {"input_roles": [], "engine": "generation", "label": "Produzir os trechos ou recursos que faltam"},
    "template": {"input_roles": ["template_library"], "engine": "production", "label": "Personalizar e renderizar um template"},
    "returned_clips": {"input_roles": [], "engine": "generation", "label": "Receber e montar clipes externos"},
    "revision": {"input_roles": [], "engine": "revision", "label": "Retomar e corrigir uma versão"},
}
INPUT_ROLES = {"footage", "reference", "image", "audio", "script", "resource", "template_library"}


def _id(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value)
            and value not in {".", ".."}, "project_id", "Use a simple, path-safe identifier")
    return value


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _seal(state):
    state.pop("project_sha256", None)
    state["project_sha256"] = digest(state)
    return state


def _spec(spec):
    data = clone(mapping(spec, "spec"))
    require(data.get("schema") == SPEC_SCHEMA, "project_schema", "Unsupported project specification")
    _id(data.get("id"))
    require(data.get("intent") in ROUTES, "project_intent", "Select an explicit entry route")
    nonempty(data.get("brief"), "spec.brief")
    seen = set()
    for item in sequence(data.setdefault("inputs", []), "spec.inputs"):
        identifier = _id(item.get("id"))
        require(identifier not in seen, "duplicate_input", "Input ID repeated")
        seen.add(identifier)
        require(item.get("role") in INPUT_ROLES, "input_role", "Declare the purpose of each input")
        require(item.get("media_type") in {"video", "image", "audio", "json", "text"},
                "media_type", "Declare video, image, audio, json or text")
        item.setdefault("status", "ready" if item.get("path") else "needed")
        require(item["status"] in {"ready", "needed"}, "input_status", "Declare ready or needed")
        if item["status"] == "ready":
            path = Path(nonempty(item.get("path"), "input.path"))
            require(path.is_absolute(), "absolute_path", "Input paths must be absolute")
            actual = file_sha256(path)
            require(item.get("sha256", actual) == actual, "input_changed", "Input differs from its declared hash")
            item.update(path=str(path.resolve()), sha256=actual)
        else:
            require("path" not in item and "sha256" not in item, "unready_input", "Needed inputs cannot claim files")
    for name in ("generation_answers", "preferences", "settings"):
        mapping(data.setdefault(name, {}), "spec." + name)
    sequence(data.setdefault("requirements", []), "spec.requirements")
    return data


def load_project(directory):
    root = Path(directory).resolve()
    state = _read(root / "project.json")
    require(state.get("schema") == PROJECT_SCHEMA, "project_schema", "Unsupported stored project")
    require(state.get("project_sha256") == digest({k: v for k, v in state.items() if k != "project_sha256"}),
            "project_hash", "Project state was changed outside a revision")
    require(state.get("root") == str(root), "project_location", "Restore or relocate with an explicit import, not a path rewrite")
    snapshot = root / "revisions" / f"{state['revision']:06d}.json"
    require(snapshot.is_file() and _read(snapshot) == state, "project_snapshot", "Current revision is missing or changed")
    return state


@contextmanager
def _lock(root):
    import fcntl
    path = Path(root) / ".project.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(descriptor)
        raise ValidationError("project_busy", "Another project update is active; retry after it completes") from error
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _commit(state, action, detail=None, *, initial=False):
    root = Path(state["root"])
    with _lock(root):
        expected = state.get("project_sha256")
        if not initial:
            require(load_project(root)["project_sha256"] == expected, "project_conflict",
                    "Project changed during this action; preserve its output and retry from current state")
        state = clone(state)
        state["parent_sha256"] = None if initial else expected
        snapshots = [int(path.stem) for path in (root / "revisions").glob("*.json") if path.stem.isdigit()]
        state["revision"] = max([state["revision"], *snapshots], default=0) + 1
        state["updated_at"] = _now()
        state["history"].append({"revision": state["revision"], "action": action,
                                 "at": state["updated_at"], "detail": detail or {}})
        _refresh(state)
        _seal(state)
        _write(root / "revisions" / f"{state['revision']:06d}.json", state)
        temporary = root / (".next-" + uuid.uuid4().hex + ".json")
        _write(temporary, state)
        os.replace(temporary, root / "project.json")
    return state


def create_project(directory, spec):
    spec = _spec(spec)
    root = Path(directory).resolve()
    state = {"schema": PROJECT_SCHEMA, "root": str(root), "spec": spec, "revision": 0,
             "artifacts": {}, "history": [], "review_attempts": 0,
             "max_review_retries": spec["settings"].get("max_review_retries", 2)}
    require(type(state["max_review_retries"]) is int and state["max_review_retries"] >= 0,
            "retry_limit", "max_review_retries must be a nonnegative integer")
    root.mkdir(parents=True, exist_ok=False)
    return _commit(state, "create", initial=True)


def update_project(directory, spec, *, reason):
    state, spec = load_project(directory), _spec(spec)
    nonempty(reason, "reason")
    require(spec["id"] == state["spec"]["id"], "project_identity", "Keep the project ID when revising")
    state["spec"] = spec
    return _commit(state, "update_spec", {"reason": reason})


def _input(state, identifier):
    matches = [item for item in state["spec"]["inputs"] if item["id"] == identifier]
    require(len(matches) == 1, "input_missing", "Input is not declared: " + str(identifier))
    item = matches[0]
    require(item["status"] == "ready", "input_needed", "Supply the missing input: " + identifier)
    verify_file(item["path"], item["sha256"], "inputs." + identifier)
    return item


def _token(state, key):
    if key in {"brief", "generation_answers", "preferences", "settings", "requirements", "intent"}:
        return digest(state["spec"][key])
    category, _, identifier = key.partition(":")
    if category == "input":
        for item in state["spec"]["inputs"]:
            if item["id"] == identifier and item["status"] == "ready":
                return digest(item)
    elif category == "artifact":
        record = state["artifacts"].get(identifier)
        if record and record["status"] == "current":
            return record["sha256"]
    elif category == "clip":
        record = state["artifacts"].get("generation_plan")
        if record and record["status"] == "current":
            from .generation.contracts import clip_fingerprint
            try:
                return clip_fingerprint(_read(record["path"]), identifier)
            except (ValueError, KeyError, OSError):
                return None
    return None


def _dependencies(state, *keys):
    result = {key: _token(state, key) for key in keys}
    require(all(result.values()), "dependency_missing", "A required project dependency is absent or stale")
    return result


def _file_refs(data):
    """Collect hashes actually present in receipts, without inventing paths."""
    found, inspected = {}, set()
    def walk(item):
        if isinstance(item, dict):
            # receipt_sha256/request_sha256 often seal canonical JSON, not file
            # bytes. Only known byte-hash pairs may become archived resources.
            pairs = [("path", "sha256"), ("artifact_path", "artifact_sha256"),
                     ("pcm_path", "pcm_sha256"), ("glyph_ids_path", "glyph_ids_sha256")]
            for p, h in pairs:
                if isinstance(item.get(p), str) and isinstance(item.get(h), str) and Path(item[p]).is_absolute():
                    found[item[p]] = item[h]
                    if p == "artifact_path" and Path(item[p]).suffix.lower() == ".json" and item[p] not in inspected:
                        inspected.add(item[p])
                        verify_file(item[p], item[h], "technical receipt")
                        walk(_read(item[p]))
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)
    walk(data)
    return [{"path": path, "sha256": checksum} for path, checksum in sorted(found.items())]


def _refresh(state):
    # Never resurrect a stale artifact just because an older hash reappears.
    changed = True
    while changed:
        changed = False
        for record in state["artifacts"].values():
            if record["status"] != "current":
                continue
            reasons = [key for key, value in record["dependencies"].items() if _token(state, key) != value]
            if reasons:
                record.update(status="stale", invalidated_by=reasons)
                changed = True


def _checked_state(directory):
    state = load_project(directory)
    _refresh(state)
    for item in state["spec"]["inputs"]:
        if item["status"] == "ready":
            verify_file(item["path"], item["sha256"], "inputs." + item["id"])
    return state


def _artifact(state, key):
    record = state["artifacts"].get(key)
    require(record and record["status"] == "current", "artifact_needed", "Current artifact required: " + key)
    verify_file(record["path"], record["sha256"], key)
    for item in record.get("files", []):
        verify_file(item["path"], item["sha256"], key + ".files")
    return _read(record["path"])


def _workspace(state, action):
    root = Path(state["root"]) / "work" / f"{state['revision'] + 1:06d}-{action}-{uuid.uuid4().hex[:10]}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def _record(state, key, data, dependencies, *, kind=None, directory=None):
    workspace = directory or _workspace(state, "record")
    path = workspace / (key.replace(":", "-") + ".json")
    _write(path, data)
    state["artifacts"][key] = {"kind": kind or key.split(":")[0], "path": str(path),
        "sha256": file_sha256(path), "dependencies": clone(dependencies), "status": "current",
        "created_in_revision": state["revision"] + 1, "files": _file_refs(data)}
    _refresh(state)
    return data


def _freeze_artifact(state, key, memo=None, visiting=None):
    """Snapshot an artifact DAG before reusing live stage names for finishing."""
    memo, visiting = ({} if memo is None else memo), (set() if visiting is None else visiting)
    if key in memo:
        return memo[key]
    require(key not in visiting, "dependency_cycle", "Project artifact dependencies contain a cycle")
    visiting.add(key)
    _artifact(state, key)
    record = clone(state["artifacts"][key])
    dependencies = {}
    for dependency, checksum in record["dependencies"].items():
        if dependency.startswith("artifact:"):
            frozen = _freeze_artifact(state, dependency[len("artifact:"):], memo, visiting)
            dependencies["artifact:" + frozen] = checksum
        else:
            dependencies[dependency] = checksum
    record["dependencies"] = dependencies
    frozen = "snapshot:" + digest({"path": record["path"], "dependencies": dependencies})
    record["kind"] = "snapshot"
    state["artifacts"][frozen] = record
    memo[key] = frozen
    visiting.remove(key)
    return frozen


def artifact(directory, key):
    """Read a current artifact, checking its dependencies and actual file bytes."""
    return _artifact(_checked_state(directory), key)


def prepare_input(directory, input_id, *, resources=None, sample_every_s=1.0):
    """Prepare actual footage or a reference; resources may come from production."""
    from .perception import prepare_analysis
    state = _checked_state(directory)
    source = _input(state, input_id)
    require(source["media_type"] == "video", "video_required", "Technical video preparation requires a video input")
    resources = clone(resources or {})
    require(set(resources) <= {"transcript", "pose", "mattes", "protection", "projection", "assets"},
            "preparation_resource", "Unknown preparation resource")
    workspace = _workspace(state, "prepare")
    analysis = prepare_analysis(source["path"], workspace / "analysis", sample_every_s=sample_every_s, **resources)
    dependencies = _dependencies(state, "input:" + input_id)
    _record(state, "analysis:" + input_id, analysis, dependencies, directory=workspace)
    catalog = _read(workspace / "analysis" / "catalog.json")
    _record(state, "catalog:" + input_id, catalog, dependencies, directory=workspace)
    return _commit(state, "prepare", {"input_id": input_id})


def prepare_render(directory, *, resources=None, sample_every_s=1.0):
    """Feed the assembled film into the existing contextual finishing engine."""
    from .perception import prepare_analysis
    state = _checked_state(directory)
    rendered = _artifact(state, "render")
    # A finishing render must not depend on the mutable name of its own output.
    frozen = _freeze_artifact(state, "render")
    _record(state, "render_base", rendered, _dependencies(state, "artifact:" + frozen))
    workspace = _workspace(state, "prepare-render")
    analysis = prepare_analysis(rendered["path"], workspace / "analysis",
                                sample_every_s=sample_every_s, **(resources or {}))
    dependencies = _dependencies(state, "artifact:render_base")
    _record(state, "analysis:film", analysis, dependencies, directory=workspace)
    _record(state, "catalog:film", _read(workspace / "analysis" / "catalog.json"), dependencies, directory=workspace)
    return _commit(state, "prepare_render")


def describe_reference(directory, input_id, observations, *, author, adaptation=None):
    from .reference_direction import build_dossier, validate_adaptation
    state = _checked_state(directory)
    require(_input(state, input_id)["role"] == "reference", "reference_role", "Input must explicitly be a reference")
    analysis = _artifact(state, "analysis:" + input_id)
    dossier = build_dossier(analysis, observations, dossier_id=input_id, author=author, verify_files=True)
    _record(state, "dossier:" + input_id, dossier, _dependencies(state, "artifact:analysis:" + input_id))
    if adaptation is not None:
        contract = validate_adaptation(adaptation, dossier, verify_files=True)
        _record(state, "adaptation:" + input_id, contract,
                _dependencies(state, "artifact:dossier:" + input_id, "brief"))
    return _commit(state, "reference", {"input_id": input_id})


def adapt_reference(directory, input_id, contract):
    from .reference_direction import validate_adaptation
    state = _checked_state(directory)
    dossier = _artifact(state, "dossier:" + input_id)
    contract = validate_adaptation(contract, dossier, verify_files=True)
    _record(state, "adaptation:" + input_id, contract,
            _dependencies(state, "artifact:dossier:" + input_id, "brief"))
    return _commit(state, "adapt_reference", {"input_id": input_id})


def _reference(state, reference_id):
    if reference_id is None:
        return None, None, {}
    dossier = _artifact(state, "dossier:" + reference_id)
    adaptation = _artifact(state, "adaptation:" + reference_id)
    return dossier, adaptation, _dependencies(state, "artifact:dossier:" + reference_id,
                                               "artifact:adaptation:" + reference_id)


def request_direction(directory, *, kind, input_id=None, reference_id=None,
                      assets=None, include_images=True, max_frames=24,
                      template_input_id=None, template_root=None, template_ids=None):
    state = _checked_state(directory)
    require(kind in {"edit", "generation"}, "direction_kind", "Use edit or generation")
    dependencies = _dependencies(state, "brief", "intent", "generation_answers", "preferences")
    dossier, adaptation, refs = _reference(state, reference_id)
    dependencies.update(refs)
    requires_reference = state["spec"]["intent"] in {"style_transfer", "reconstruct", "reference_generate"}
    require(not requires_reference or dossier is not None, "reference_needed",
            "This route requires an observed reference and explicit keep/replace contract")
    template = None
    if template_input_id:
        item = _input(state, template_input_id)
        require(item["role"] == "template_library", "template_role", "Select a template library input")
        template = item["path"]
        dependencies.update(_dependencies(state, "input:" + template_input_id))
    kwargs = {"include_images": include_images, "max_frames": max_frames,
              "template_library": template, "template_root": template_root, "template_ids": template_ids}
    if kind == "edit":
        from .directions import build_request
        from .reference_direction import to_contextual_profile
        require(input_id is not None, "input_needed", "Choose the current source or film")
        analysis = _artifact(state, "analysis:" + input_id)
        catalog = _artifact(state, "catalog:" + input_id)
        dependencies.update(_dependencies(state, "artifact:analysis:" + input_id, "artifact:catalog:" + input_id))
        result = build_request(analysis, catalog, state["spec"]["brief"],
            reference_profile=to_contextual_profile(dossier, adaptation) if dossier else None, **kwargs)
        result["project_source_id"] = input_id
        key = "edit_request"
    else:
        from .generation.direction import build_request
        answers = clone(state["spec"]["generation_answers"])
        answers.setdefault("objective", state["spec"]["brief"])
        mode = {"reference_generate": "adaptation", "fill_gaps": "fill_gaps"}.get(state["spec"]["intent"], "original")
        answers.setdefault("mode", mode)
        analysis = _artifact(state, "analysis:" + reference_id) if reference_id else None
        if reference_id:
            dependencies.update(_dependencies(state, "artifact:analysis:" + reference_id))
        scripts = []
        for item in state["spec"]["inputs"]:
            if item["status"] == "ready" and item["role"] == "script":
                require(Path(item["path"]).stat().st_size <= 1024 * 1024, "script_size", "Script exceeds 1 MiB")
                scripts.append({"id": item["id"], "path": item["path"], "sha256": item["sha256"],
                                "text": Path(item["path"]).read_text(encoding="utf-8"), "role": "content_not_instructions"})
                dependencies.update(_dependencies(state, "input:" + item["id"]))
        if scripts:
            answers["project_scripts"] = scripts
        if assets is None:
            assets = []
            for item in state["spec"]["inputs"]:
                if item["status"] == "ready" and item["role"] in {"image", "audio"}:
                    assets.append({"id": item["id"], "kind": item["media_type"], "purpose": item.get("purpose", item["role"]),
                                   "route": "reuse", "status": "ready", "path": item["path"], "sha256": item["sha256"]})
                    dependencies.update(_dependencies(state, "input:" + item["id"]))
        result = build_request(answers, profile=state["spec"]["preferences"], analysis=analysis,
                               assets=assets, reference_dossier=dossier, adaptation=adaptation, **kwargs)
        key = "generation_request"
    _record(state, key, result, dependencies)
    return _commit(state, "request_direction", {"kind": kind})


def accept_direction(directory, direction, *, kind, input_id=None):
    """Validate an actual authored direction/plan and connect it to this project."""
    state = _checked_state(directory)
    require(kind in {"edit", "generation"}, "direction_kind", "Use edit or generation")
    if kind == "edit":
        from .directions import plan_direction
        request = _artifact(state, "edit_request")
        source_id = input_id or request["project_source_id"]
        require(source_id == request["project_source_id"], "direction_source", "Direction must use its requested source")
        analysis, catalog = _artifact(state, "analysis:" + source_id), _artifact(state, "catalog:" + source_id)
        result = plan_direction(analysis, catalog, direction, plan_id=state["spec"]["id"] + "-edit")
        result["project_source_id"] = source_id
        _record(state, "edit_bundle", result, _dependencies(state, "artifact:edit_request",
                "artifact:analysis:" + source_id, "artifact:catalog:" + source_id))
    else:
        from .generation.contracts import validate_plan, revise_plan
        from .generation.provider import validate_editorial_inputs
        result = validate_plan(direction, verify_files=True)
        dependencies = _dependencies(state, "brief", "generation_answers", "intent")
        request_record = state["artifacts"].get("generation_request")
        require(not request_record or request_record["status"] == "current", "stale_generation_request",
                "Prepare direction against the current project before adopting a new plan")
        require(state["spec"]["intent"] not in {"reference_generate", "fill_gaps"}
                or request_record is not None, "generation_request_needed",
                "Reference and gap-filling routes need a current direction request bound to their context")
        declared = state["spec"]["generation_answers"]
        declared = {**declared.get("brief", {}), **{k: v for k, v in declared.items() if k != "brief"}}
        validate_editorial_inputs(result, declared)
        for key in ("mode", "objective", "audience", "aspect_ratio", "target_duration_s",
                    "instruction_language", "dialogue_language", "audio_execution", "require_generated_audio"):
            if key in declared:
                require(result["brief"].get(key) == declared[key], "brief_changed",
                        "The imported plan changed an explicit project answer: " + key)
        for item in state["spec"]["inputs"]:
            if item["status"] == "ready" and item["role"] in {"reference", "image", "audio", "script"}:
                dependencies.update(_dependencies(state, "input:" + item["id"]))
        if request_record and request_record["status"] == "current":
            request = _artifact(state, "generation_request")
            validate_editorial_inputs(result, request["briefing"]["resolved"])
            require(all(result["brief"].get(key) == value for key, value in request["brief"].items()),
                    "brief_changed", "Directed plan changed the resolved brief; revise the project first")
            dependencies.update(_dependencies(state, "artifact:generation_request"))
        prior = state["artifacts"].get("generation_plan")
        if prior:
            verify_file(prior["path"], prior["sha256"], "previous generation plan")
            previous = _read(prior["path"])
            revision = revise_plan(previous, result)
            _record(state, "generation_revision", revision, {})
            for identifier in revision["invalidated_clips"] + revision["removed_clips"]:
                record = state["artifacts"].get("return:" + identifier)
                if record:
                    record.update(status="stale", invalidated_by=["generation_revision"])
        _record(state, "generation_plan", result, dependencies)
    return _commit(state, "accept_direction", {"kind": kind})


def direct_project(directory, *, kind, endpoint, model, api_key_env=None, transport=None):
    """Call only an explicitly configured director; authentication stays outside JSON."""
    state = _checked_state(directory)
    if kind == "generation":
        from .generation.provider import call_provider
        result = call_provider(_artifact(state, "generation_request"), endpoint=endpoint,
                               model=model, api_key_env=api_key_env, transport=transport)
    else:
        from .directions import call_provider
        require(kind == "edit" and transport is None, "direction_kind", "Use edit or generation; edit uses its configured transport")
        result = call_provider(_artifact(state, "edit_request"), endpoint=endpoint, model=model, api_key_env=api_key_env)
    # Compare-and-swap before accepting a potentially slow network result.
    require(load_project(directory)["project_sha256"] == state["project_sha256"], "project_conflict", "Project changed while directing")
    return accept_direction(directory, result, kind=kind)


def export_prompts(directory, *, profile=None, ready=False):
    from .generation.prompts import compile_pack, render_markdown
    state = _checked_state(directory)
    plan = _artifact(state, "generation_plan")
    dependencies = _dependencies(state, "artifact:generation_plan")
    returns = {}
    for key, record in state["artifacts"].items():
        if key.startswith("return:") and record["status"] == "current":
            returns[key[7:]] = _artifact(state, key)
            dependencies.update(_dependencies(state, "artifact:" + key))
    pack = compile_pack(plan, profile=profile, returns=returns, ready=ready)
    workspace = _workspace(state, "prompts")
    (workspace / "prompts.md").write_text(render_markdown(pack), encoding="utf-8")
    for index, clip in enumerate(pack["clips"], 1):
        _id(clip["clip_id"])
        (workspace / f"{index:02d}-{clip['clip_id']}.txt").write_text(clip["prompt"] + "\n", encoding="utf-8")
    pack["project_exports"] = [{"path": str(p), "sha256": file_sha256(p)} for p in sorted(workspace.iterdir())]
    _record(state, "prompt_pack", pack, dependencies, directory=workspace)
    return _commit(state, "export_prompts", {"status": pack["status"]})


def receive_clip(directory, clip_id, video, *, selected_frame=None, observation=None):
    from .generation.ingest import import_clip
    state = _checked_state(directory)
    plan = _artifact(state, "generation_plan")
    pack_record = state["artifacts"].get("prompt_pack")
    exported = None
    if pack_record and pack_record["status"] == "current":
        pack = _artifact(state, "prompt_pack")
        exported = next((c for c in pack["clips"] if c["clip_id"] == clip_id), None)
    workspace = _workspace(state, "receive")
    result = import_clip(plan, clip_id, video, workspace / "return", selected_frame=selected_frame,
                         observation=observation, exported_clip=exported)
    dependencies = _dependencies(state, "clip:" + clip_id)
    # A returned-frame chain also depends on the bytes used at its preceding join.
    for join in plan["joins"]:
        if join["to"] == clip_id and join["strategy"] in {"observed_frame", "native_extension"}:
            dependencies.update(_dependencies(state, "artifact:return:" + join["from"]))
    _record(state, "return:" + clip_id, result, dependencies, directory=workspace)
    return _commit(state, "receive_clip", {"clip_id": clip_id})


def queue_production(directory, request):
    from .production import validate_request
    state = _checked_state(directory)
    request = validate_request(request, verify_files=True)
    identifier = _id(request["id"] if "id" in request else request["request_id"])
    dependencies = _dependencies(state, "brief", "requirements")
    for item in request.get("inputs", []):
        for source in state["spec"]["inputs"]:
            if source.get("path") == item.get("path"):
                dependencies.update(_dependencies(state, "input:" + source["id"]))
    _record(state, "production:" + identifier, request, dependencies)
    return _commit(state, "queue_production", {"request_id": identifier})


def produce(directory, request_id, *, executor=None, registry=None, estimated_cost=0):
    from .production import execute_request
    from .workflows import WorkflowLedger
    state = _checked_state(directory)
    request = _artifact(state, "production:" + request_id)
    ledger = WorkflowLedger(Path(state["root"]) / "jobs.sqlite",
                            budget_limit=state["spec"]["settings"].get("production_budget"),
                            unit=state["spec"]["settings"].get("budget_unit", "credits"))
    workspace = _workspace(state, "produce")
    result = execute_request(request, workspace / "output", executor=executor, registry=registry,
                             ledger=ledger, estimated_cost=estimated_cost)
    dependencies = _dependencies(state, "artifact:production:" + request_id)
    _record(state, "execution:" + request_id, result, dependencies, directory=workspace)
    if result.get("result") is not None:
        _record(state, "result:" + request_id, result["result"], dependencies, directory=workspace)
    return _commit(state, "produce", {"request_id": request_id, "status": result["status"]})


def receive_production(directory, request_id, path, *, provenance, kind=None, expected_sha256=None, template_instance=None):
    from .production import import_result
    state = _checked_state(directory)
    request = _artifact(state, "production:" + request_id)
    if request["operation"] == "template" and template_instance is None:
        execution = _artifact(state, "execution:" + request_id)
        instance = execution.get("template_instance")
        require(instance is not None, "template_instance_needed", "Instantiate the requested template before importing its render")
        template_instance = clone(instance)
    workspace = _workspace(state, "receive-resource")
    result = import_result(request, path, kind=kind, provenance=provenance,
                           output_dir=workspace / "import", expected_sha256=expected_sha256, template_instance=template_instance)
    _record(state, "result:" + request_id, result,
            _dependencies(state, "artifact:production:" + request_id), directory=workspace)
    return _commit(state, "receive_production", {"request_id": request_id})


def adopt_production(directory, request_id, *, input_id, role, purpose):
    """Use a rendered template/voice/image as a concrete project input."""
    from .production import validate_result
    state = _checked_state(directory)
    request, result = _artifact(state, "production:" + request_id), _artifact(state, "result:" + request_id)
    result = validate_result(result, request, verify_files=True)
    require(result["status"] != "simulated_result", "simulated_resource", "Simulated output cannot become production input")
    require(role in INPUT_ROLES, "input_role", "Declare the role of the produced input")
    nonempty(purpose, "purpose")
    kind = result["kind"]
    require((role not in {"footage", "reference"} or kind == "video")
            and (role != "image" or kind == "image") and (role != "audio" or kind == "audio"),
            "input_kind", "A result cannot change media type when adopted")
    require(role != "template_library", "input_kind", "A rendered template is media, not a new template library")
    identifier = _id(input_id)
    require(not any(i["id"] == identifier for i in state["spec"]["inputs"]),
            "duplicate_input", "Use a new input ID; replacing an existing source requires update")
    media_type = kind if kind in {"image", "video", "audio"} else "json"
    item = {"id": identifier, "role": role, "media_type": media_type, "status": "ready",
            "path": result["artifact"]["path"], "sha256": result["artifact"]["sha256"], "purpose": purpose,
            "production": {"request_id": request_id, "request_sha256": request["request_sha256"],
                           "result_sha256": result["result_sha256"]}}
    state["spec"]["inputs"].append(item)
    return _commit(state, "adopt_production", {"request_id": request_id, "input_id": identifier})


def queue_missing_assets(directory):
    from .production import production_request
    state = _checked_state(directory)
    plan = _artifact(state, "generation_plan")
    for item in plan["assets"]:
        if item["status"] != "needed":
            continue
        identifier = _id("asset-" + item["id"])
        operation = {"reuse": "manual_asset", "user": "manual_asset"}.get(item["route"], item["route"])
        kind = "motion_layer" if item["kind"] == "motion" else item["kind"]
        request = production_request(identifier, operation, prompt=item.get("prompt") or item["purpose"],
            output_kind=kind, context={"project_id": state["spec"]["id"], "asset_id": item["id"],
                                       "asset_need_sha256": digest(item), "generation_plan_id": plan["id"]})
        prior = state["artifacts"].get("production:" + identifier)
        if prior:
            verify_file(prior["path"], prior["sha256"], "previous production request")
            previous = _read(prior["path"])
            equivalent = lambda value: {k: v for k, v in value.items() if k not in {"revision", "request_sha256"}}
            if prior["status"] == "current" and equivalent(previous) == equivalent(request):
                continue
            request = production_request(identifier, operation, prompt=item.get("prompt") or item["purpose"],
                output_kind=kind, context=request["context"], revision=previous["revision"] + 1)
        # Binding to the asset need is separate from the whole plan revision: a
        # received image can be adopted without invalidating its own provenance.
        _record(state, "production:" + identifier, request, _dependencies(state, "brief", "requirements"))
    return _commit(state, "queue_missing_assets")


def fulfill_asset(directory, asset_id, request_id):
    from .production import validate_result
    state = _checked_state(directory)
    request, result = _artifact(state, "production:" + request_id), _artifact(state, "result:" + request_id)
    result = validate_result(result, request, verify_files=True)
    require(result["status"] != "simulated_result", "simulated_resource", "A simulated provider result cannot satisfy a production asset")
    plan = _artifact(state, "generation_plan")
    matches = [item for item in plan["assets"] if item["id"] == asset_id]
    require(len(matches) == 1 and matches[0]["status"] == "needed", "asset_needed", "Choose an existing needed asset")
    need = matches[0]
    context = request.get("context", {})
    require(context.get("asset_id") == asset_id and context.get("asset_need_sha256") == digest(need),
            "asset_request_changed", "The production request must identify this exact asset need")
    expected_kind = "motion_layer" if need["kind"] == "motion" else need["kind"]
    require(result["kind"] == expected_kind, "asset_kind", "Production output cannot change the needed media type")
    need.update(status="ready", path=result["artifact"]["path"], sha256=result["artifact"]["sha256"],
                production_result_sha256=result["result_sha256"])
    plan["revision"] += 1
    state = accept_direction(directory, plan, kind="generation")
    state["artifacts"]["generation_plan"]["dependencies"].update(_dependencies(state, "artifact:result:" + request_id))
    return _commit(state, "fulfill_asset", {"asset_id": asset_id, "request_id": request_id})


def prepare_with_results(directory, input_id, bindings, *, asset_requests=None, sample_every_s=1.0):
    from .production import validate_result
    state = _checked_state(directory)
    resources, dependencies, inventory = {}, {}, []
    expected = {"transcript": "transcript", "pose": "pose", "mattes": "mattes", "projection": "planar_tracking"}
    for name, request_id in mapping(bindings, "bindings").items():
        require(name in expected, "resource_kind", "Use transcript, pose, mattes or projection bindings")
        request, result = _artifact(state, "production:" + request_id), _artifact(state, "result:" + request_id)
        result = validate_result(result, request, verify_files=True)
        require(result["kind"] == expected[name] and result["status"] != "simulated_result",
                "resource_kind", "Preparation needs a real result of the requested type")
        require(result.get("source_binding", {}).get("source_sha256") == _input(state, input_id)["sha256"],
                "resource_source", "Preparation output belongs to another source")
        path = Path(result["artifact"]["path"])
        resources[name] = str(path.parent if name == "mattes" else path)
        dependencies.update(_dependencies(state, "artifact:result:" + request_id))
    for request_id in asset_requests or []:
        request, result = _artifact(state, "production:" + request_id), _artifact(state, "result:" + request_id)
        result = validate_result(result, request, verify_files=True)
        require(result["kind"] in {"image", "motion_layer"} and result["status"] != "simulated_result",
                "resource_kind", "Use image or motion_layer here; audio must have an explicitly indexed/reviewed sound anchor")
        inventory.append({"id": request_id, "kind": "image" if result["kind"] == "image" else "motion",
                          "path": result["artifact"]["path"], "description": request["prompt"],
                          "provenance": result["provenance"]})
        dependencies.update(_dependencies(state, "artifact:result:" + request_id))
    if inventory:
        resources["assets"] = {"assets": inventory}
    state = prepare_input(directory, input_id, resources=resources, sample_every_s=sample_every_s)
    for key in ("analysis:" + input_id, "catalog:" + input_id):
        state["artifacts"][key]["dependencies"].update(dependencies)
    return _commit(state, "prepare_with_results", {"input_id": input_id})


def plan_assembly(directory, plan=None, *, fps=None, width=None, height=None,
                  fit="reject", fps_policy="reject", audio="source", missing_audio="silence", transitions=None,
                  reference_id=None):
    from .assembly import from_generation, validate_assembly
    state = _checked_state(directory)
    dependencies = _dependencies(state, "brief", "intent")
    if state["spec"]["intent"] == "reconstruct":
        references = [i["id"] for i in state["spec"]["inputs"] if i["role"] == "reference" and i["status"] == "ready"]
        reference_id = reference_id or (references[0] if len(references) == 1 else None)
        require(reference_id is not None, "reference_needed", "Reconstruction requires an explicitly selected reference")
    if reference_id:
        dossier, adaptation, reference_dependencies = _reference(state, reference_id)
        from .reference_direction import to_contextual_profile
        _record(state, "assembly_reference", to_contextual_profile(dossier, adaptation), reference_dependencies)
        dependencies.update(_dependencies(state, "artifact:assembly_reference"))
    if plan is None:
        generated = _artifact(state, "generation_plan")
        returns = {clip["id"]: _artifact(state, "return:" + clip["id"]) for clip in generated["clips"]}
        plan = from_generation(generated, returns, fps=fps, width=width, height=height, fit=fit,
            fps_policy=fps_policy, audio=audio, missing_audio=missing_audio, transitions=transitions)
        dependencies.update(_dependencies(state, "artifact:generation_plan",
                            *("artifact:return:" + key for key in returns)))
    else:
        for source in plan.get("sources", []):
            for item in state["spec"]["inputs"]:
                if source.get("path") == item.get("path"):
                    dependencies.update(_dependencies(state, "input:" + item["id"]))
    validate_assembly(plan, verify_files=True)
    _record(state, "assembly_plan", plan, dependencies)
    return _commit(state, "plan_assembly")


def _start_review(state, plan, rendered):
    from .review import new_review, continue_review
    prior_record = state["artifacts"].get("review")
    if prior_record:
        verify_file(prior_record["path"], prior_record["sha256"], "previous review")
        previous = _read(prior_record["path"])
        consume = previous["status"] in {"needs_revision", "exhausted"}
        review = continue_review(previous, plan, rendered, reason="New render requires its own coverage", consume_retry=consume)
    else:
        review = new_review(plan, rendered, max_retries=state["max_review_retries"])
    state["review_attempts"] = review["retry_count"]
    _record(state, "review", review, _dependencies(state, "artifact:render", "artifact:review_plan"))


def render_project(directory, *, kind, font=None, script_font=None, style=None):
    state = _checked_state(directory)
    workspace = _workspace(state, "render")
    if kind == "assembly":
        from .assembly import render_assembly
        result = render_assembly(_artifact(state, "assembly_plan"), workspace / "assembly")
        review_plan = result["review_plan"]
        dependencies = _dependencies(state, "artifact:assembly_plan")
    else:
        from .native import render_bundle
        require(kind == "edit", "render_kind", "Use assembly or edit")
        bundle = _artifact(state, "edit_bundle")
        result = render_bundle(bundle, workspace / "render.mp4", font=font, script_font=script_font, style=style)
        review_plan = bundle["plan"]
        dependencies = _dependencies(state, "artifact:edit_bundle")
        if bundle.get("project_source_id") == "film":
            base = _artifact(state, "render_base")
            result["pending_post"] = clone(base.get("pending_post", []))
            result["finished_from_sha256"] = base["sha256"]
            dependencies.update(_dependencies(state, "artifact:render_base"))
    _record(state, "review_plan", review_plan, dependencies, directory=workspace)
    _record(state, "render", result, dependencies, directory=workspace)
    _start_review(state, review_plan, result)
    return _commit(state, "render", {"kind": kind, "render_sha256": result["sha256"]})


def review_project(directory, report):
    from .review import add_review
    state = _checked_state(directory)
    plan, rendered, previous = (_artifact(state, name) for name in ("review_plan", "render", "review"))
    review = add_review(previous, plan, rendered, report)
    _post_resolved_ids(report, rendered, strict=True)
    _record(state, "review", review, _dependencies(state, "artifact:render", "artifact:review_plan"))
    return _commit(state, "review", {"status": review["status"], "can_finalize": review["can_finalize"]})


def patch_edit(directory, patch):
    from .planner import apply_patch
    state = _checked_state(directory)
    bundle, review = _artifact(state, "edit_bundle"), _artifact(state, "review")
    result = apply_patch(bundle["plan"], patch, bundle["analysis"], bundle["catalog"], review)
    bundle["plan"] = result["plan"]
    _record(state, "edit_bundle", bundle, state["artifacts"]["edit_bundle"]["dependencies"])
    # Stale review remains a first-class budget record; it is not a passed gate.
    _record(state, "review", result["review"], _dependencies(state, "artifact:edit_bundle"))
    state["review_attempts"] = result["review"]["retry_count"]
    return _commit(state, "patch_edit")


def import_finished_video(directory, video, *, provenance):
    """Receive a real external finishing pass without silently retiming it."""
    from fractions import Fraction
    import subprocess
    from .contracts import provenance as check_provenance
    from .assembly import _read_media
    state = _checked_state(directory)
    base = _artifact(state, "render")
    check_provenance(provenance, "external_finish.provenance")
    path = Path(video).resolve()
    workspace = _workspace(state, "external-finish")
    destination = workspace / "finished.mp4"
    with path.open("rb") as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target)
    checksum = file_sha256(destination)
    actual, base_actual = _read_media(destination), _read_media(Path(base["path"]))
    require(actual["clock"] == "cfr" and actual["frame_count"] == base["frame_count"]
            and Fraction(actual["fps"]) == Fraction(base["fps"])
            and abs(Fraction(actual["duration"]) - Fraction(base_actual["duration"])) <= Fraction(actual["time_base"]),
            "finish_clock", "External finishing must preserve the planned film clock; revise assembly for timing changes")
    require((actual["width"], actual["height"]) == (base_actual["width"], base_actual["height"]),
            "finish_raster", "Revise the output format explicitly before changing the finishing raster")
    require(not base_actual["audio"] or actual["audio"], "finish_audio", "Finishing cannot silently remove the original audio")
    if actual["audio_clock"]:
        require(abs(Fraction(actual["audio_clock"]["origin"])) <= Fraction(1, 48000),
                "finish_audio_clock", "Finishing audio must start with the film clock")
        clock = actual["audio_clock"]
        audio_duration = Fraction(clock["sample_count"], clock["sample_rate"])
        video_duration = Fraction(actual["duration"])
        require(video_duration - Fraction(1, clock["sample_rate"]) <= audio_duration
                <= video_duration + Fraction(1024, clock["sample_rate"]),
                "finish_audio_coverage", "Finishing audio must cover the film, allowing at most one AAC frame of encoded padding")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-protocol_whitelist", "file,pipe", "-i", str(destination),
                    "-f", "null", "-"], check=True, capture_output=True)
    # Snapshot the assembly/edit binding before replacing the current output.
    frozen = _freeze_artifact(state, "render")
    _record(state, "external_finish_base", base, _dependencies(state, "artifact:" + frozen))
    verify_file(str(destination), checksum, "finished output after measurement")
    verify_file(base["path"], base["sha256"], "base output after measurement")
    plan = {"schema_version": "1.0", "kind": "external-finish-review-binding/1",
            "plan_id": state["spec"]["id"] + "-external-finish", "version": state["revision"] + 1,
            "decisions": [{"id": "external-finish", "provenance": clone(provenance)}],
            "validation": {"executable": True, "meaning": "Existing video fully decoded; not an engine-executed finishing recipe"},
            "base_render_sha256": base["sha256"], "external_render_sha256": checksum}
    plan["plan_sha256"] = digest(plan)
    rendered = {"path": str(destination), "sha256": checksum, "plan_sha256": plan["plan_sha256"],
                "duration_s": actual["duration_s"], "fps": actual["fps"], "frame_count": actual["frame_count"],
                "clock": "output", "actual": actual, "provenance": clone(provenance),
                "finished_from_sha256": base["sha256"], "pending_post": clone(base.get("pending_post", [])),
                "technical_checks": {"full_decode": "pass", "frame_clock": "pass"},
                "perceptual_review": "unverified", "user_approval": "pending", "engine_executed_finish": False}
    dependencies = _dependencies(state, "artifact:external_finish_base")
    _record(state, "review_plan", plan, dependencies, directory=workspace)
    _record(state, "render", rendered, dependencies, directory=workspace)
    _start_review(state, plan, rendered)
    return _commit(state, "import_finished_video")


def pending_post_items(rendered):
    """Stable identities survive finishing; a matching review must resolve them."""
    return [{"id": digest(item), "label": item.get("id", "post"), "requirement": clone(item)}
            for item in rendered.get("pending_post", [])]


def _unresolved_post(rendered, review):
    required = {item["id"] for item in pending_post_items(rendered)}
    if not required:
        return []
    resolved = set()
    for report in review.get("reports", []):
        resolved.update(_post_resolved_ids(report, rendered))
    return sorted(required - resolved)


def _post_resolved_ids(report, rendered, *, strict=False):
    """Only an explicit, continuous final-film review can close pending post."""
    from .review import _covered
    try:
        resolutions = sequence(report.get("post_resolutions", []), "post_resolutions")
        if not resolutions:
            return set()
        require(rendered.get("finished_from_sha256") and rendered["finished_from_sha256"] != rendered["sha256"],
                "post_not_executed", "An unchanged assembly cannot resolve its own pending post")
        require(report.get("render_sha256") == rendered["sha256"]
                and report.get("plan_sha256") == rendered["plan_sha256"], "stale_post_review", "Review the current finishing pass")
        require(report.get("reviewer", {}).get("kind") in {"human", "model", "user"},
                "post_review_scope", "Post completion needs attributed perceptual review")
        for dimension in ("motion", "audio", "editorial"):
            check = report.get("checks", {}).get(dimension, {})
            require(check.get("status") == "pass" and check.get("mode") == "continuous"
                    and _covered(check.get("coverage", []), rendered["duration_s"])[0],
                    "post_review_scope", "Post completion requires this report to cover motion, audio and editorial continuously")
        required = {item["id"] for item in pending_post_items(rendered)}
        resolved = set()
        for item in resolutions:
            mapping(item, "post_resolution")
            require(set(item) == {"id", "status", "notes"} and item["id"] in required and item["id"] not in resolved,
                    "post_resolution", "Use one known post ID, explicit resolved status and notes")
            require(item["status"] == "resolved", "post_resolution", "Pending or failed work cannot be resolved")
            nonempty(item["notes"], "post_resolution.notes")
            resolved.add(item["id"])
        return resolved
    except ValidationError:
        if strict:
            raise
        return set()


def project_status(directory):
    state = _checked_state(directory)
    records, spec = state["artifacts"], state["spec"]
    def has(key):
        return key in records and records[key]["status"] == "current"
    def usable_result(identifier):
        return has("result:" + identifier) and _artifact(state, "result:" + identifier)["status"] != "simulated_result"
    items = []
    def need(code, action, detail, **extra):
        items.append({"code": code, "action": action, "detail": detail, **extra})
    available_roles = {i["role"] for i in spec["inputs"] if i["status"] == "ready"}
    for role in ROUTES[spec["intent"]]["input_roles"]:
        if role not in available_roles:
            need("missing_input", "update", "Forneça a entrada necessária: " + role, role=role)
    for item in spec["inputs"]:
        if item["status"] == "needed":
            need("missing_input", "update", "Forneça " + item["id"], input_id=item["id"])
    if spec["intent"] == "media_story" and not available_roles & {"image", "audio", "script"}:
        need("missing_story_media", "update", "Inclua imagens, áudio ou roteiro para esta entrada")
    for requirement in spec["requirements"]:
        identifier = _id(requirement.get("id"))
        if not usable_result(identifier):
            need("missing_resource", "produce" if has("production:" + identifier) else "queue",
                 requirement.get("description", "Produza o recurso solicitado"), request_id=identifier)
    production = []
    for key in records:
        if key.startswith("production:") and has(key):
            identifier = key.split(":", 1)[1]
            execution = _artifact(state, "execution:" + identifier) if has("execution:" + identifier) else None
            production.append({"request_id": identifier, "status": "received" if usable_result(identifier)
                               else "simulated_not_usable" if has("result:" + identifier)
                               else execution["status"] if execution else "queued"})
            if not usable_result(identifier):
                need("production_pending", "receive-resource" if execution else "produce",
                     "Produção pendente: " + identifier, request_id=identifier)
    if has("generation_plan"):
        for asset in _artifact(state, "generation_plan")["assets"]:
            if asset["status"] == "needed":
                need("missing_asset", "queue-assets", asset["purpose"], asset_id=asset["id"], route=asset["route"])
    if has("render"):
        rendered = _artifact(state, "render")
        review = _artifact(state, "review") if has("review") else {}
        unresolved = _unresolved_post(rendered, review)
        if unresolved:
            need("pending_post", "prepare-film", "Conclua e revise a pós-produção no filme montado",
                 post_ids=unresolved, requirements=pending_post_items(rendered))
        if not review.get("can_finalize"):
            need("review_needed", "review", "Revise movimento, áudio e edição no arquivo atual, além da verificação técnica",
                 review_status=review.get("status", "missing"))
        state_name = "ready_delivery" if not items else "needs_revision" if review.get("status") in {"needs_revision", "exhausted"} else "awaiting_review"
    elif has("assembly_plan"):
        need("render_ready", "render --kind assembly", "Execute a montagem planejada")
        state_name = "ready_render"
    elif has("edit_bundle"):
        bundle = _artifact(state, "edit_bundle")
        executable = bundle["plan"].get("validation", {}).get("executable", False)
        need("render_ready" if executable else "plan_blocked", "render --kind edit" if executable else "plan",
             "Renderize as operações selecionadas" if executable else "Resolva as dependências ou propostas do plano")
        state_name = "ready_render" if executable else "blocked"
    elif has("generation_plan"):
        plan = _artifact(state, "generation_plan")
        missing = [c["id"] for c in plan["clips"] if not has("return:" + c["id"])]
        if not has("prompt_pack"):
            need("prompt_export", "export", "Exporte os prompts e as dependências para a ferramenta escolhida")
        if missing:
            need("missing_clips", "receive", "Importe os clipes realmente produzidos", clip_ids=missing)
        else:
            need("assembly_ready", "assemble", "Planeje a montagem dos retornos verificados")
        state_name = "awaiting_media" if missing else "ready_assembly"
    else:
        for item in spec["inputs"]:
            if item["status"] == "ready" and item["media_type"] == "video" and item["role"] in {"reference", "footage"}:
                if not has("analysis:" + item["id"]):
                    need("preparation_needed", "prepare", "Extraia evidências atuais de " + item["id"], input_id=item["id"])
                if item["role"] == "reference" and not has("adaptation:" + item["id"]):
                    need("reference_direction", "reference", "Descreva a referência e defina manter/substituir", input_id=item["id"])
        engine = ROUTES[spec["intent"]]["engine"]
        request_key = "edit_request" if engine == "contextual" else "generation_request"
        if engine in {"generation", "contextual"}:
            if has(request_key):
                request = _artifact(state, request_key)
                if request.get("briefing", {}).get("ready_for_direction") is False:
                    need("brief_needed", "update", "Complete as decisões essenciais do briefing",
                         questions=request["briefing"]["next_questions"])
                else:
                    need("direction_needed", "direct or plan", "Conclua a direção a partir das evidências exportadas")
            else:
                need("direction_request", "request", "Prepare a solicitação de direção")
        elif engine == "assembly":
            need("assembly_plan_needed", "assemble --plan", "Defina os trechos, ordem, cortes, formato e áudio da montagem")
        elif engine == "production":
            need("template_request", "queue", "Selecione template, conteúdo e adaptador de renderização")
        else:
            need("base_project_needed", "fork", "Retome o projeto existente para preservar planos, retornos e revisões")
        state_name = "awaiting_direction"
    return {"schema": "clone-project-status/1", "project_id": spec["id"], "revision": state["revision"],
            "intent": spec["intent"], "route": ROUTES[spec["intent"]], "status": state_name,
            "work_items": items, "production": production,
            "artifacts": {key: {"status": value["status"], "path": value["path"],
                                 "invalidated_by": value.get("invalidated_by", [])} for key, value in records.items()},
            "review_attempts": state["review_attempts"], "max_review_retries": state["max_review_retries"],
            "ready_for_final_delivery": state_name == "ready_delivery"}


def advance_project(directory):
    """Resume repeatable local preparation. Direction and production stay explicit."""
    state = _checked_state(directory)
    for item in state["spec"]["inputs"]:
        if item["status"] == "ready" and item["role"] in {"footage", "reference"} and item["media_type"] == "video":
            record = state["artifacts"].get("analysis:" + item["id"])
            if not record or record["status"] != "current":
                state = prepare_input(directory, item["id"])
    engine = ROUTES[state["spec"]["intent"]]["engine"]
    reference_ids = [i["id"] for i in state["spec"]["inputs"] if i["role"] == "reference" and i["status"] == "ready"]
    if len(reference_ids) > 1:
        return project_status(directory)  # Selection is an authored decision.
    reference_id = reference_ids[0] if reference_ids else None
    if reference_id and state["artifacts"].get("adaptation:" + reference_id, {}).get("status") != "current":
        return project_status(directory)
    key = "edit_request" if engine == "contextual" else "generation_request"
    if engine in {"contextual", "generation"} and state["artifacts"].get(key, {}).get("status") != "current":
        footage = [i["id"] for i in state["spec"]["inputs"] if i["role"] == "footage" and i["status"] == "ready"]
        if engine == "generation" or len(footage) == 1:
            request_direction(directory, kind="edit" if engine == "contextual" else "generation",
                              input_id=footage[0] if engine == "contextual" else None, reference_id=reference_id)
    return project_status(directory)


def fork_project(directory, parent_directory, *, project_id=None):
    """Create a revision branch; original artifacts remain read-only dependencies."""
    parent = _checked_state(parent_directory)
    spec = clone(parent["spec"])
    if project_id:
        spec["id"] = _id(project_id)
    spec["entry_route"] = "revision"
    state = create_project(directory, spec)
    state["artifacts"] = clone(parent["artifacts"])
    state["review_attempts"] = parent["review_attempts"]
    state["max_review_retries"] = parent["max_review_retries"]
    state["parent_project"] = {"root": parent["root"], "project_sha256": parent["project_sha256"],
                               "revision": parent["revision"]}
    return _commit(state, "fork", {"parent_project_sha256": parent["project_sha256"]})


def _history_files(state):
    expected, result = state["project_sha256"], []
    for entry in reversed(state["history"]):
        path = Path(state["root"]) / "revisions" / f"{entry['revision']:06d}.json"
        snapshot = _read(path)
        actual = digest({k: v for k, v in snapshot.items() if k != "project_sha256"})
        require(actual == expected == snapshot.get("project_sha256"), "project_history",
                "A previous immutable project revision changed")
        result.append({"path": str(path), "sha256": file_sha256(path)})
        expected = snapshot["parent_sha256"]
    require(expected is None, "project_history", "Project history is incomplete")
    return result


def deliver_project(directory, output_dir, *, kind="final", include_dependencies=True):
    """Copy verified deliverables and their audit trail to a new immutable package."""
    require(kind in {"final", "preview", "prompts"}, "delivery_kind", "Use final, preview or prompts")
    state = _checked_state(directory)
    status = project_status(directory)
    if kind == "final":
        require(status["ready_for_final_delivery"], "delivery_blocked", "Final delivery requires completed post and current full-film review")
    key = "prompt_pack" if kind == "prompts" else "render"
    primary = _artifact(state, key)
    output = Path(output_dir).resolve()
    require(not output.exists(), "delivery_exists", "Use a new delivery directory")
    # Complete the checks before creating the package, then verify every copy.
    files = {}
    for item in _history_files(state):
        files[item["path"]] = item["sha256"]
    for record in state["artifacts"].values():
        if record["status"] == "current":
            verify_file(record["path"], record["sha256"], "delivery manifest")
            files[record["path"]] = record["sha256"]
            if include_dependencies:
                for item in record.get("files", []):
                    files[item["path"]] = item["sha256"]
    if include_dependencies:
        for item in state["spec"]["inputs"]:
            if item["status"] == "ready":
                files[item["path"]] = item["sha256"]
    for path, checksum in files.items():
        verify_file(path, checksum, "delivery dependency")
    output.mkdir(parents=True)
    copied, path_map = {}, []
    for path, checksum in sorted(files.items()):
        suffix = Path(path).suffix.lower()
        relative = "dependencies/" + checksum + suffix
        target = output / relative
        if relative not in copied:
            target.parent.mkdir(exist_ok=True)
            with Path(path).open("rb") as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination)
            verify_file(str(target), checksum, "delivered copy")
            copied[relative] = checksum
        path_map.append({"original_path": path, "package_path": relative, "sha256": checksum})
    if kind != "prompts":
        target = output / ("final.mp4" if kind == "final" else "preview.mp4")
        shutil.copyfile(primary["path"], target)
        verify_file(str(target), primary["sha256"], "delivered video")
        copied[target.name] = primary["sha256"]
    else:
        from .generation.prompts import render_markdown
        target = output / "prompts.md"
        target.write_text(render_markdown(primary), encoding="utf-8")
        copied[target.name] = file_sha256(target)
    _write(output / "project-snapshot.json", state)
    _write(output / "path-map.json", path_map)
    copied["project-snapshot.json"] = file_sha256(output / "project-snapshot.json")
    copied["path-map.json"] = file_sha256(output / "path-map.json")
    receipt = {"schema": "clone-delivery/1", "kind": kind, "project_sha256": state["project_sha256"],
               "project_revision": state["revision"], "output_dir": str(output),
               "files": [{"path": str(output / p), "sha256": h} for p, h in sorted(copied.items())],
               "dependencies_included": include_dependencies, "path_map": "path-map.json",
               "execution_note": "Manifests retain original hashes and paths; path-map locates archived copies without rewriting evidence.",
               "user_approval": _artifact(state, "review")["user_approval"] if key == "render" else "not_applicable",
               "perceptual_review": "passed" if kind == "final" else "not_claimed"}
    receipt["delivery_sha256"] = digest(receipt)
    _write(output / "delivery.json", receipt)
    _record(state, "delivery", receipt, _dependencies(state, "artifact:" + key,
            *(["artifact:review"] if key == "render" else [])))
    return _commit(state, "deliver", {"kind": kind, "path": str(output)})
