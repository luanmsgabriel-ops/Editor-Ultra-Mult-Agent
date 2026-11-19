"""Private effect library and revision-bound Studio editing commands."""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import shutil
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from editorial_engine.contracts import clone, digest, file_sha256, require
from editorial_engine.effect_edit import EFFECTS, compatible_ranges, inspect_video, render_demo, render_edit
from visual_fidelity.effect_library import index, read, register, words, write
from visual_fidelity.motion_profile import evaluate_element, profile_digest, validate_profile

Id = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$")]
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=64)]
Version = Annotated[str, Field(pattern=r"^(0|[1-9]\d{0,3})(\.(0|[1-9]\d{0,3})){2}$")]
Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False, strict=True)]
Scalar = Annotated[float, Field(allow_inf_nan=False, strict=True, ge=-1e5, le=1e5)]
FrameNumber = Annotated[int, Field(ge=0, le=3600, strict=True)]
ColorChannel = Annotated[int, Field(ge=0, le=255, strict=True)]
FrameRange = tuple[FrameNumber, FrameNumber]
Point = tuple[Unit, Unit]
Vec3 = tuple[Scalar, Scalar, Scalar]


class CommandModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Analyze(CommandModel):
    action: Literal["analyze"]
    role: Literal["ref", "footage"]
    asset_id: Id
    source_url: Annotated[str, Field(max_length=1500)] | None = None


class Publish(CommandModel):
    action: Literal["publish"]
    recipe_id: Slug
    version: Version
    effect: Literal["flash", "type", "world"]
    title: Annotated[str, Field(min_length=2, max_length=100)]
    description: Annotated[str, Field(min_length=8, max_length=500)]
    tags: Annotated[list[Annotated[str, Field(min_length=2, max_length=40)]], Field(max_length=12)] = []
    reference_range: FrameRange
    duration_seconds: Annotated[float, Field(ge=.1, le=12, allow_inf_nan=False)] = 1.5
    intensity: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] = .9
    curve: Annotated[list[Point], Field(min_length=2, max_length=24)] | None = None
    color: tuple[ColorChannel, ColorChannel, ColorChannel] | None = None
    motion_measurement_id: Id | None = None
    motion_element_id: Id | None = None
    confirmed: Literal[True]

    @model_validator(mode="after")
    def validate_curve(self):
        if self.curve and (self.curve[0][0] != 0 or self.curve[-1][0] != 1
                           or any(a[0] >= b[0] for a, b in zip(self.curve, self.curve[1:]))):
            raise ValueError("A curva precisa cobrir de 0 a 1 com tempos estritamente crescentes.")
        if bool(self.motion_measurement_id) != bool(self.motion_element_id):
            raise ValueError("Informe a medição e o elemento de movimento juntos.")
        if self.motion_measurement_id and self.effect == "flash":
            raise ValueError("O flash usa envelope de intensidade. Escolha motion apenas para legenda ou cartão.")
        return self


class Opportunity(CommandModel):
    range: FrameRange
    intent: Annotated[str, Field(min_length=3, max_length=300)]
    effects: Annotated[list[Literal["flash", "type", "world"]], Field(max_length=3)] = []


class Suggest(CommandModel):
    action: Literal["suggest"]
    query: Annotated[str, Field(max_length=160)] = ""
    opportunities: Annotated[list[Opportunity], Field(max_length=24)] = []


class Calibration(CommandModel):
    intrinsics: tuple[Vec3, Vec3, Vec3]
    world_points: Annotated[list[Vec3], Field(min_length=8, max_length=96)]
    image_points: Annotated[list[Point], Field(min_length=8, max_length=96)]


class Selection(CommandModel):
    action: Literal["select"]
    recipe_id: Slug
    version: Version
    range: FrameRange
    text: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    anchor: Point | None = None
    scale: Annotated[float, Field(ge=.10, le=.45, allow_inf_nan=False)] | None = None
    calibration: Calibration | None = None
    occlusion: Annotated[list[Point], Field(min_length=3, max_length=20)] | None = None
    replace: bool = False


class Remove(CommandModel):
    action: Literal["remove"]
    application_id: Id


class Render(CommandModel):
    action: Literal["render"]
    preview: bool = True
    application_id: Id | None = None


class Review(CommandModel):
    action: Literal["review"]
    asset_id: Id
    decision: Literal["approved", "rejected"]
    confirmed: Literal[True]
    notes: Annotated[str, Field(max_length=2000)] = ""


EffectCommand = Annotated[Analyze | Publish | Suggest | Selection | Remove | Render | Review,
                          Field(discriminator="action")]


def _library(adapter):
    return adapter.data_dir / "effect-library"


def _read_package(path):
    card = read(path / "effect.json")
    for name, sha in card["sha256"].items():
        file = path / name
        require(file.resolve().is_relative_to(path.resolve()) and file.is_file() and file_sha256(file) == sha,
                "effect_package", "O pacote do efeito diverge dos arquivos catalogados.")
    return card, read(path / "recipe.json")


def _library_row(card, directory):
    return {**{name: card[name] for name in ("id", "version", "title", "description", "tags")},
            "effect": card["recipe"]["effect"], "anchor": card["recipe"]["anchor"],
            "default_seconds": card["recipe"]["duration_seconds"], "demo": {"path": str(directory / "demo.mp4")},
            "demo_kind": "synthetic", "package_sha256": digest(card)}


def library(adapter, query="", *, latest=True):
    root = _library(adapter)
    # Only this workflow's versioned recipes share the Studio's executable catalog.
    rows = [_library_row(card, root / card["path"]) for card in index(root)["effects"]
            if card["recipe"]["engine"] == "editor-ultra-effect-edit/1" and card["status"] == "pronto"]
    tokens = words(query)

    def score(row):
        return len(tokens & words(row["title"] + " " + " ".join(row["tags"]))) * 3 + len(tokens & words(row["description"]))

    if latest:
        rows = sorted(rows, key=lambda row: tuple(map(int, row["version"].split("."))), reverse=True)
        by_id = {}
        for item in rows:
            by_id.setdefault(item["id"], item)
        rows = list(by_id.values())
    return sorted((row for row in rows if not tokens or score(row)),
                  key=lambda row: (-score(row), row["id"]))[:80]


def _recipe(adapter, recipe_id, version):
    root = _library(adapter)
    matches = [root / family / recipe_id / version for family in ("motion", "transicao")]
    matches = [path for path in matches if (path / "effect.json").is_file()]
    require(len(matches) == 1, "effect_recipe", "Esta versão do efeito não está no catálogo.")
    path = matches[0]
    card, recipe = _read_package(path)
    require(card["recipe"]["engine"] == "editor-ultra-effect-edit/1" and card["status"] == "pronto",
            "effect_recipe", "Este pacote não declara um efeito executável para a timeline.")
    return _library_row(card, path), recipe


def _current(adapter, record, state, role):
    analysis = state.get(role)
    require(analysis is not None and analysis["asset_id"] in current_assets(record, role),
            "effect_analysis", "Analise o arquivo atual antes de prosseguir.")
    source = adapter.resolve_asset(record["project_id"], analysis["asset_id"])
    path = adapter.resolve_asset(record["project_id"], analysis["analysis_asset_id"])
    report = read(path)
    require(report["source_sha256"] == record["files"][analysis["asset_id"]]["sha256"],
            "effect_analysis", "A análise foi feita a partir de outros bytes.")
    return source, report


def current_assets(record, role):
    return {item["id"] for item in record["state"]["assets"].get(role, [])}


def snapshot(record):
    workflow = clone(record.get("effect_workflow", {}))
    for role in ("ref", "footage"):
        if role in workflow:
            workflow[role]["current"] = workflow[role]["asset_id"] in current_assets(record, role)
    edit = workflow.get("render")
    if edit:
        edit["current"] = bool(workflow.get("footage", {}).get("current")) and edit["selection"] == digest(workflow.get("selections", []))
    if workflow.get("review"):
        workflow["review"]["current"] = bool(edit and edit["current"] and workflow["review"]["asset_id"] == edit["asset_id"])
    return workflow


def _range(value, count):
    first, end = value
    require(0 <= first < end <= count, "effect_range", "Informe um intervalo [início, fim exclusivo] da faixa de quadros.")
    return [first, end]


def _source_url(value):
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError()
    except ValueError as exc:
        raise ValueError("Informe o link HTTP(S) da página pública da referência.") from exc
    return value


def _analyze(adapter, record, state, command, directory):
    role, asset_id = command.role, command.asset_id
    require(asset_id in current_assets(record, role), "effect_asset", "Escolha um vídeo selecionado com o papel informado.")
    item = record["files"][asset_id]
    require(item["type"].startswith("video/") and item.get("duration", 0) <= 180,
            "effect_asset", "Escolha um vídeo de até 180 segundos.")
    path = adapter.resolve_asset(record["project_id"], asset_id)
    source_url = _source_url(command.source_url or (record["state"]["sourceLink"] if role == "ref" else None))
    old = state.get(role, {})
    if old.get("asset_id") == asset_id and old.get("source_url") == source_url:
        _current(adapter, record, state, role)
        return
    directory.mkdir()
    report = inspect_video(path, directory)
    summary = {"asset_id": asset_id, "source_url": source_url, "frames": report["clock"]["frames"],
               "fps": report["clock"]["fps"], "clock_kind": report["clock"]["clock_kind"],
               "shots": report["shots"][:80], "shot_count": len(report["shots"]), "events": report["events"][:100],
               "audio": report["audio"]}
    for key, filename in (("analysis", "analysis.json"), ("poster", "takes.jpg"), ("proxy", "inspection.mp4")):
        media = adapter._register_internal(record, directory / filename, role="effect_evidence")
        summary[f"{key}_asset_id"] = media["id"]
        summary[key] = {"path": media["path"]}
    state[role] = summary
    if role == "footage":
        for field in ("suggestions", "selections", "render", "review"):
            state.pop(field, None)


def _measured_motion(adapter, record, analysis, command, frames):
    measurement = next((item for item in record.get("motion_measurements", [])
                        if item["id"] == command.motion_measurement_id), None)
    require(measurement and measurement["source"]["sha256"] == analysis["source_sha256"],
            "effect_motion", "Selecione uma medição deste projeto, vinculada à referência atual.")
    for dependency in (measurement["source"], *measurement.get("masks", [])):
        adapter.resolve_asset(record["project_id"], dependency["asset_id"])
    path = adapter.resolve_asset(record["project_id"], measurement["artifacts"]["profile"]["asset_id"])
    profile = read(path)
    validate_profile(profile)
    require(profile_digest(profile) == measurement["profile_sha256"],
            "effect_motion", "O perfil difere do que foi medido no projeto.")
    first, end = frames
    require(2 <= end - first <= 300, "effect_motion", "Use de 2 a 300 quadros para aprender movimento.")
    clock = analysis["clock"]
    ticks = clock["frame_pts"][first:end]
    tick = Fraction(clock["time_base"])
    samples = [evaluate_element(profile, command.motion_element_id, float((pts - clock["first_pts"]) * tick))
               for pts in ticks]
    require(all(all(sample[key] is not None for key in ("position_px", "scale", "angle_deg_unwrapped")) for sample in samples),
            "effect_motion", "A medição precisa cobrir posição, escala e ângulo em cada quadro do intervalo.")
    base = samples[0]
    motion = []
    for pts, sample in zip(ticks, samples):
        x, y = [(a - b) / clock["width"] for a, b in zip(sample["position_px"], base["position_px"])]
        scale = sample["scale"] / base["scale"]
        angle = sample["angle_deg_unwrapped"] - base["angle_deg_unwrapped"]
        require(max(abs(x), abs(y)) <= .75 and .35 <= scale <= 2.5,
                "effect_motion", "A curva excede o deslocamento ou escala suportados pelo efeito.")
        motion.append([(pts - ticks[0]) / (ticks[-1] - ticks[0]), x, y, scale, angle])
    return motion, {"profile_sha256": measurement["profile_sha256"], "element_id": command.motion_element_id}


def _publish(adapter, record, state, command, directory):
    _, analysis = _current(adapter, record, state, "ref")
    frames = _range(command.reference_range, analysis["clock"]["frames"])
    artifact = {key: getattr(command, key) for key in ("effect", "intensity", "curve", "duration_seconds", "color")
                if getattr(command, key) is not None}
    motion_source = None
    if command.motion_measurement_id:
        artifact["motion"], motion_source = _measured_motion(adapter, record, analysis, command, frames)
    kind = EFFECTS[command.effect]
    other_kinds = {"motion", "transicao"} - {kind["family"]}
    require(not any((_library(adapter) / family / command.recipe_id).exists() for family in other_kinds),
            "effect_identity", "Use um novo ID para um efeito de outra família.")
    card = {"kind": kind["family"], "id": command.recipe_id, "version": command.version, "status": "pronto",
            "title": command.title, "description": command.description, "tags": command.tags,
            "source": {"type": "assisted_recreation",
                       "details": "Receita autorada e confirmada com base no intervalo registrado.",
                       "reference_sha256": analysis["source_sha256"], "frames": frames,
                       "fps": float(Fraction(analysis["clock"]["fps"])), "url": state["ref"].get("source_url"),
                       "motion": motion_source},
            "files": ["recipe.json", "demo.mp4"], "recipe": {"engine": "editor-ultra-effect-edit/1",
                       "entry": "recipe.json", "anchor": kind["anchor"], "effect": command.effect,
                       "duration_seconds": command.duration_seconds}}
    directory.mkdir()
    write(directory / "recipe.json", artifact)
    write(directory / "effect.json", card)
    target = _library(adapter) / kind["family"] / command.recipe_id / command.version
    if target.is_dir():
        stored, saved = _read_package(target)
        require(digest(saved) == digest(artifact) and {key: stored[key] for key in card} == card,
                "effect_version", "A versão já existe com conteúdo diferente. Incremente a versão.")
    else:
        render_demo(artifact, directory / "demo.mp4")
        target = register(directory / "effect.json", _library(adapter))
    row = _library_row(read(target / "effect.json"), target)
    current = state.setdefault("published", [])
    if not any(item["package_sha256"] == row["package_sha256"] for item in current):
        current.append(row)


def _suggest(adapter, record, state, command):
    _, report = _current(adapter, record, state, "footage")
    clock = report["clock"]
    tick = Fraction(clock["time_base"])
    times = [float((pts - clock["first_pts"]) * tick) for pts in clock["frame_pts"]]
    times.append(times[-1] + float(1 / Fraction(clock["fps"])))
    for item in command.opportunities:
        _range(item.range, clock["frames"])
    recipes = library(adapter, command.query)
    suggestions = {}
    for recipe in recipes:
        for shot, frames, reason, center in compatible_ranges(report, recipe["effect"], recipe["default_seconds"]):
            cover = frames if center is not None else shot["range"]
            choices = [(frames, None)]
            if command.opportunities:
                choices = []
                for opportunity in command.opportunities:
                    if opportunity.effects and recipe["effect"] not in opportunity.effects:
                        continue
                    start, end = max(cover[0], opportunity.range[0]), min(cover[1], opportunity.range[1])
                    if center is None:
                        end = min(end, start + frames[1] - frames[0])
                    if end - start >= EFFECTS[recipe["effect"]]["min_frames"] and (center is None or start < center < end):
                        choices.append(([start, end], opportunity.intent))
            for effect_range, intent in choices:
                entry = {"recipe": recipe, "take": shot["id"], "range": effect_range, "reason": reason,
                         "time_s": [times[number] for number in effect_range],
                         "source_sha256": report["source_sha256"], "cut_frame": center,
                         "readiness": "tracking_required" if recipe["anchor"] == "world" else "candidate"}
                if intent:
                    entry["intent"] = intent
                suggestions.setdefault((shot["id"], tuple(effect_range)), []).append({**entry, "id": digest(entry)[:20]})
    state["suggestions"] = [entry for rows in suggestions.values() for entry in rows[:3]][:60]


def _select(adapter, record, state, command):
    _, report = _current(adapter, record, state, "footage")
    row, recipe = _recipe(adapter, command.recipe_id, command.version)
    frames = _range(command.range, report["clock"]["frames"])
    first, end = frames
    effect = row["effect"]
    require(end - first >= EFFECTS[effect]["min_frames"], "effect_range", "O intervalo é curto para este efeito.")
    shots = report["shots"]
    if effect == "flash":
        crossings = [shot["range"][0] for shot in shots if first < shot["range"][0] < end]
        require(len(crossings) == 1, "effect_cut", "O flash precisa cruzar exatamente um candidato a corte.")
    else:
        require(any(a <= first and end <= b for a, b in (shot["range"] for shot in shots)),
                "effect_cut", "Selecione o efeito dentro de uma tomada contínua.")
        require(bool(command.text), "effect_text", "Escreva o texto para a legenda ou cartão.")
    spatial = command.anchor or command.scale or command.calibration or command.occlusion
    require(not spatial or effect == "world", "effect_anchor", "Âncora, calibração e máscara são específicas do efeito 3D.")
    if effect == "world":
        require(end - first <= 300, "effect_range", "Limite o tracking a 300 quadros por aplicação.")
    params = command.model_dump(mode="json", include={"text", "anchor", "scale", "calibration", "occlusion"}, exclude_none=True)
    application = {**recipe, **params, "range": frames, "recipe_id": row["id"], "version": row["version"],
                   "title": row["title"], "package_sha256": row["package_sha256"]}
    application["id"] = digest(application)[:20]
    selected = state.setdefault("selections", [])
    if any(item["id"] == application["id"] for item in selected):
        return
    existing = [item for item in selected if max(first, item["range"][0]) < min(end, item["range"][1])]
    require(not existing or command.replace, "effect_overlap", "Já existe uma aplicação neste intervalo. Confirme a substituição.")
    require(len(selected) - len(existing) < 24, "effect_limit", "Limite de 24 aplicações no mesmo vídeo.")
    state["selections"] = sorted([item for item in selected if item not in existing] + [application],
                                 key=lambda item: item["range"])


def _render(adapter, record, state, command, directory):
    source, report = _current(adapter, record, state, "footage")
    require(all(record["files"][reference]["sha256"] != report["source_sha256"]
                for reference in current_assets(record, "ref")),
            "effect_independent", "Use um bruto diferente da referência para aplicar os efeitos.")
    selection = state.get("selections", [])
    effects = [item for item in selection if command.application_id in (None, item["id"])]
    require(effects and (command.preview or command.application_id is None),
            "effect_selection", "Escolha efeitos atuais antes de renderizar. A seleção individual é para prévia.")
    for item in effects:
        row, _ = _recipe(adapter, item["recipe_id"], item["version"])
        require(item["package_sha256"] == row["package_sha256"], "effect_recipe", "A versão do pacote foi alterada.")
    directory.mkdir()
    output, receipt = render_edit(source, report, effects, directory, preview=command.preview)
    media = adapter._register_internal(record, output, role="effect_render")
    report_file = adapter._register_internal(record, directory / "render.json", role="effect_evidence")
    state["render"] = {"asset_id": media["id"], "media": {"path": media["path"]},
                       "receipt": {"path": report_file["path"]}, "receipt_asset_id": report_file["id"],
                       "sha256": receipt["render_sha256"], "source_range": receipt["source_range"],
                       "kind": receipt["render_kind"], "selection": digest(selection)}
    state["render_history"] = [*state.get("render_history", []), clone(state["render"])][-15:]
    state.pop("review", None)


def _review(adapter, record, state, command):
    current = snapshot(record).get("render")
    require(current and current["current"] and current["asset_id"] == command.asset_id,
            "effect_review", "Revise o arquivo da execução atual.")
    require(command.decision != "approved" or current["kind"] == "full",
            "effect_review", "Gere o vídeo completo antes da aprovação final.")
    adapter.resolve_asset(record["project_id"], command.asset_id)
    state["review"] = {"decision": command.decision, "asset_id": current["asset_id"], "sha256": current["sha256"],
                       "notes": command.notes, "at": datetime.now(timezone.utc).isoformat()}
    for item in state.get("render_history", []):
        if item["asset_id"] == current["asset_id"]:
            item["review"] = clone(state["review"])


def execute(adapter, project_id, command, expected_revision):
    with adapter._lock(project_id):
        record = adapter._load(project_id)
        adapter._expect(record, expected_revision)
        state = record.setdefault("effect_workflow", {})
        directory = adapter._directory(project_id) / ("effects-" + uuid4().hex)
        try:
            match command:
                case Analyze():
                    _analyze(adapter, record, state, command, directory)
                case Publish():
                    _publish(adapter, record, state, command, directory)
                case Suggest():
                    _suggest(adapter, record, state, command)
                case Selection():
                    _select(adapter, record, state, command)
                case Remove():
                    _current(adapter, record, state, "footage")
                    selected = state.get("selections", [])
                    require(any(item["id"] == command.application_id for item in selected),
                            "effect_selection", "Aplicação indisponível.")
                    state["selections"] = [item for item in selected if item["id"] != command.application_id]
                case Render():
                    _render(adapter, record, state, command, directory)
                case Review():
                    _review(adapter, record, state, command)
            adapter._write(record, "Biblioteca de efeitos: " + command.action)
        except BaseException:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        if isinstance(command, Publish):
            shutil.rmtree(directory, ignore_errors=True)
        return adapter._snapshot(record)
