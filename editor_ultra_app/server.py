"""Authenticated MCP Apps bridge to the real, local Editor Ultra engines.

The host directs the edit. This server admits files, prepares evidence, executes
validated plans and returns actual artifacts. It never calls a video generator.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from functools import wraps
from html import escape
import json
import logging
import mimetypes
import os
import re
from pathlib import Path
import shutil
import threading
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
import uuid

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ImageContent, ResourceLink, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import ClientDisconnect, Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from editorial_engine.contracts import ValidationError

from . import __version__
from .auth import OwnerAuthGuard, OwnerOAuthProvider
from .catalog import Catalog
from .clone_resources import CloneResources, ImageNeed, MAX_RESOURCE_BYTES
from .motion_apply import MotionApplicationSpecification
from .engine import EngineAdapter, MotionMeasurementSpecification, MOTION_LIMITS, stored_bytes
from .jobs import JobQueue
from .media import MAX_FILE_BYTES, PreviewSigner, download_attachment
from .upload_tickets import TICKET_TTL_SECONDS, UploadBinding, UploadTicketError, UploadTicketStore
from .videoapi import BASE_URL as VIDEOAPI_BASE, VideoAPIClient, VideoAPIJobs, VideoAPIError, build_payload
from .videoapi_import import download_completed_video, verified_origin


UI_URI = "ui://editor-ultra/studio-v9.html"
UI_ALIASES = tuple(f"ui://editor-ultra/studio-v{version}.html" for version in (1, 2, 3, 4, 5, 6, 7, 8))
BRAND_MARK_PATH = "/brand/e-mark-v1.png"
ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$"
UPLOAD_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
UPLOAD_LOG = logging.getLogger("editor_ultra.upload")
UPLOAD_VALIDATION_ERRORS = {
    "revision_conflict": (409, "O projeto foi atualizado. Confira o recebimento antes de retomar o envio."),
    "invalid_media": (422, "O motor não conseguiu verificar o conteúdo deste arquivo. Reanexe o vídeo original ou exporte uma nova cópia."),
    "media_duration": (422, "O arquivo precisa ter duração maior que zero e de até 10 minutos."),
    "video_stream": (422, "Este arquivo contém mais de uma faixa de vídeo. Exporte uma cópia com uma única faixa de vídeo."),
    "image_size": (422, "A imagem ultrapassa o limite de 40 milhões de pixels. Reduza suas dimensões antes de enviar."),
    "asset_type": (422, "O formato do arquivo não corresponde ao tipo de material selecionado."),
    "asset_file": (422, "O motor não conseguiu validar o arquivo recebido. Reanexe o original."),
}
UPLOAD_UNCERTAIN_TICKET_CODES = {
    "upload_in_progress", "upload_already_received", "upload_claim_lost", "upload_receipt_missing",
}
UPLOAD_REJECTED_TICKET_CODES = {
    "revision_conflict", "upload_identifier", "upload_destination", "upload_revision", "upload_filename",
    "upload_mime", "upload_size", "upload_rate_limit", "upload_id_conflict", "upload_ledger_full",
    "upload_pending_limit", "upload_ticket_invalid_or_expired", "upload_content_type", "upload_content_length",
    "upload_ticket_required", "upload_request", "upload_storage_limit", "upload_shot_missing", "upload_incomplete",
}


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    download_url: str = Field(max_length=12000)
    file_id: str = Field(min_length=1, max_length=300)
    mime_type: str = Field(default="", max_length=150)
    file_name: str = Field(default="", max_length=240)


class UIUploadRequest(BaseModel):
    """Private command payload inside the established save tool's state object."""
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["ref", "clone", "footage", "identity", "narration", "logo", "result", "shot", "clone_resource"]
    file_name: str = Field(min_length=1, max_length=240)
    mime_type: str = Field(min_length=3, max_length=150)
    size_bytes: int = Field(ge=1, le=MAX_FILE_BYTES)
    upload_id: str = Field(min_length=36, max_length=36)
    shot_id: str | None = Field(default=None, min_length=1, max_length=96, pattern=ID)


class UIUploadCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ui_action: Literal["begin_upload"]
    upload_request: UIUploadRequest


class UIVideoAPIGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=96)
    kind: Literal["video", "image"]
    prompt: str = Field(min_length=1, max_length=5000)
    aspect_ratio: Literal["9:16", "16:9"]
    duration_seconds: Literal[5, 10, 20, 30] | None = None
    reference_asset_ids: list[str] = Field(default_factory=list, max_length=3)


class UIVideoAPICommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ui_action: Literal["videoapi_generate"]
    generation_request: UIVideoAPIGeneration


def offload(function):
    """Keep the HTTP event loop responsive while a file-bound tool is running."""
    @wraps(function)
    async def invoke(*args, **kwargs):
        return await asyncio.to_thread(function, *args, **kwargs)
    return invoke


def create_app(*, data_dir: Path | None = None, base_url: str | None = None,
               owner_key: str | None = None, allow_loopback: bool = False):
    root = (data_dir or Path(os.environ.get("EDITOR_ULTRA_DATA_DIR", "/data/editor-ultra"))).resolve()
    base = (base_url or os.environ.get("EDITOR_ULTRA_BASE_URL", "")).rstrip("/")
    key = owner_key or os.environ.get("EDITOR_ULTRA_OWNER_KEY", "")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    owner = OwnerOAuthProvider(root, base, key, allow_loopback=allow_loopback)
    tickets = UploadTicketStore(root)
    signer = PreviewSigner(root, base, key)
    catalog = Catalog(root, signer)
    engine = EngineAdapter(root)
    engine.template_library = catalog.library_path()
    lock = threading.RLock()
    upload_lock = asyncio.Semaphore(1)

    def serial_upload(function):
        @wraps(function)
        async def invoke(*args, **kwargs):
            async with upload_lock:
                return await function(*args, **kwargs)
        return invoke

    def revision(project_id, expected):
        actual = engine.get_project(project_id)["revision"]
        if actual != expected:
            raise UploadTicketError("revision_conflict", "O projeto mudou. Atualize o painel antes de repetir a ação.", 409)

    def execute(job):
        with lock:
            project_id = job["project_id"]
            revision(project_id, job["expected_revision"])
            kind = job["kind"]
            if job["operation"] == "prepare":
                if job.get("reconstruction"):
                    space_for(160 * 1024 * 1024)
                return engine.prepare(project_id, kind, expected_revision=job["expected_revision"],
                                      reconstruction=job.get("reconstruction"))
            if job["operation"] == "direction":
                return engine.apply_direction(project_id, kind, job["direction"], expected_revision=job["expected_revision"])
            if job["operation"] == "render":
                return engine.render(project_id, kind, expected_revision=job["expected_revision"])
            if job["operation"] == "queue_bundled_motion":
                return engine.queue_bundled_motion(project_id, job["recipe"],
                                                    expected_revision=job["expected_revision"])
            if job["operation"] == "execute_bundled_motion":
                space_for(16 * 1024 * 1024)
                return engine.execute_bundled_motion(project_id,
                                                      expected_revision=job["expected_revision"])
            if job["operation"] == "route_scenes":
                return engine.route_reference_scenes(project_id, job["choices"],
                                                     expected_revision=job["expected_revision"])
            if job["operation"] == "execute_scene_motion":
                space_for(96 * 1024 * 1024)
                return engine.execute_local_scene_motion(project_id, job["scene_id"],
                                                         expected_revision=job["expected_revision"])
            if job["operation"] == "audit_scene_batch":
                space_for(12 * 1024 * 1024)
                return engine.audit_scene_batch(project_id, job["scene_ids"],
                                                expected_revision=job["expected_revision"])
            if job["operation"] == "compare_temporal":
                space_for(4 * 1024 * 1024)
                return engine.compare_temporal(project_id, center_s=job["center_s"],
                                               expected_revision=job["expected_revision"])
            if job["operation"] == "measure_motion":
                space_for(MOTION_LIMITS["max_artifact_bytes"])
                return engine.measure_motion(project_id,job["asset_id"],job["specification"],
                                             expected_revision=job["expected_revision"])
            if job["operation"] == "apply_motion":
                space_for(96 * 1024 * 1024)
                return engine.apply_measured_motion(project_id, job["specification"],
                                                    expected_revision=job["expected_revision"])
            if job["operation"] == "videoapi_import":
                return import_completed_generation(project_id, job["videoapi_job_id"],
                                                   job.get("shot_id"), job["expected_revision"])
            raise ValueError("Operação indisponível.")

    queue = JobQueue(root, execute)
    videoapi_client = VideoAPIClient()
    videoapi_jobs = VideoAPIJobs(root, videoapi_client)

    def import_completed_generation(project_id, job_id, shot_id, expected_revision):
        """Import an existing completed VIDEOAPI video; never create paid jobs."""
        receipt = videoapi_jobs.get(project_id, job_id)
        if not receipt or receipt["status"] != "done" or receipt["kind"] != "video":
            raise VideoAPIError("import_state", "Selecione uma geração de vídeo concluída deste projeto.")
        current = engine.get_project(project_id)
        existing = next((a for a in current["assets"]
                         if a.get("hostFileId") == "videoapi:" + job_id), None)
        if existing:
            engine.resolve_asset(project_id, existing["asset_id"])
            return {**current, "status": "videoapi_imported", "asset_id": existing["asset_id"],
                    "asset": existing, "idempotent": True}
        target = "shot" if shot_id else "footage"
        if current["state"]["mode"] == "generate":
            if not shot_id or not any(s["id"] == shot_id for s in current["state"]["shots"]):
                raise VideoAPIError("import_shot_required",
                                    "Selecione uma tomada existente para receber o vídeo concluído.")
        elif shot_id:
            raise VideoAPIError("import_mode", "Tomadas recebem vídeo apenas no modo de geração.")
        source_url = receipt.get("download_url") or receipt.get("url")
        if not source_url:
            receipt = videoapi_jobs.recover_media(project_id, job_id)
            source_url = receipt.get("download_url") or receipt.get("url")
        # Check the provider-controlled URL and exact host before any outbound call.
        origin = verified_origin(source_url)
        hostname = urlsplit(origin).hostname
        maximum = space_for()
        incoming = download_completed_video(origin, root / "incoming", max_bytes=maximum)
        try:
            imported = engine.import_local_file(
                project_id, target, incoming,
                "VIDEOAPI-" + job_id + ".mp4", "video/mp4",
                shot_id=shot_id, expected_revision=expected_revision,
                host_file_id="videoapi:" + job_id,
                provenance={"schema": "videoapi-import/1", "provider": "VIDEOAPI",
                            "job_id": job_id, "provider_id": receipt["provider_id"],
                            "original_request_id": receipt["request_id"],
                            "media_host": hostname, "target_role": target})
            return {**imported, "status": "videoapi_imported", "idempotent": imported.get("idempotent", False)}
        finally:
            incoming.unlink(missing_ok=True)

    def public(value):
        """Keep engine paths internal; expose only scoped expiring media URLs."""
        if isinstance(value, list):
            return [public(v) for v in value]
        if not isinstance(value, dict):
            return value
        output = {}
        for name, item in value.items():
            if name == "path" and isinstance(item, str) and item.startswith("/"):
                candidate = Path(item)
                if candidate.is_file() and candidate.resolve().is_relative_to(root):
                    output["url"] = signer.url(candidate)
                continue
            output[name] = public(item)
        return output

    def result(value, message="Operação concluída."):
        return CallToolResult(content=[TextContent(type="text", text=message)], structuredContent=public(value))

    def snapshot(project_id):
        value = engine.get_project(project_id)
        value["jobs"] = queue.list(project_id)
        value["videoapi_jobs"] = videoapi_jobs.list(project_id)
        value["videoapi_enabled"] = videoapi_client.enabled
        return value

    def space_for(size=0):
        limit = int(os.environ.get("EDITOR_ULTRA_MAX_STORAGE_MB", "850")) * 1024 * 1024
        used = stored_bytes(root)
        if size < 0 or used + size > limit:
            raise ValueError("O armazenamento privado está cheio. Arquive arquivos antes de um novo envio.")
        if shutil.disk_usage(root).free < size + 64 * 1024 * 1024:
            raise ValueError("Espaço livre insuficiente para receber o arquivo com segurança.")
        return max(0, min(MAX_FILE_BYTES, (limit - used - 64 * 1024 * 1024) // 2,
                          (shutil.disk_usage(root).free - 64 * 1024 * 1024) // 2))

    def upload_preflight(project_id, expected, size=0):
        queue.assert_idle(project_id)
        with lock:
            queue.assert_idle(project_id)
            revision(project_id, expected)
            return space_for(size)

    def import_received(project_id, role, path, filename, mime_type, shot_id, expected, host_file_id=None):
        queue.assert_idle(project_id)
        with lock:
            queue.assert_idle(project_id)
            revision(project_id, expected)
            space_for(path.stat().st_size)
            return engine.import_local_file(project_id, role, path, filename, mime_type,
                                            shot_id=shot_id, expected_revision=expected,
                                            host_file_id=host_file_id)

    def upload_receipt(binding, asset_id=None):
        """Recover identity from the engine and return today's state, never a cached snapshot."""
        value = snapshot(binding.project_id)
        asset = next((item for item in value["assets"]
                      if item.get("hostFileId") == binding.host_file_id and item["role"] == binding.role
                      and item.get("shot_id") == binding.shot_id), None)
        if asset is None:
            return None
        if (asset["size"] != binding.size_bytes or asset["name"] != binding.file_name
                or (asset_id is not None and asset["id"] != asset_id)):
            raise UploadTicketError("upload_id_conflict", "Este identificador pertence a outro arquivo recebido.", 409)
        engine.resolve_asset(binding.project_id, asset["id"])
        return {**value, "asset_id": asset["id"], "asset": {k: v for k, v in asset.items() if k != "path"},
                "idempotent": True}

    def preflight_ticket(binding):
        available = upload_preflight(binding.project_id, binding.expected_revision, binding.size_bytes * 2)
        if binding.size_bytes > available:
            raise UploadTicketError("upload_storage_limit", "Espaço privado insuficiente para este arquivo.", 413)
        if binding.role == "shot":
            state = engine.get_project(binding.project_id)["state"]
            if not any(shot["id"] == binding.shot_id for shot in state["shots"]):
                raise UploadTicketError("upload_shot_missing", "Selecione uma tomada existente no projeto.", 409)

    def commit_ticket(claim, path):
        with lock:
            tickets.assert_claim(claim)
            binding = claim.binding
            value = upload_receipt(binding)
            if value is None:
                value = import_received(binding.project_id, binding.role, path, binding.file_name,
                                        binding.engine_mime, binding.shot_id, binding.expected_revision,
                                        host_file_id=binding.host_file_id)
            tickets.complete(claim, value["asset_id"])
            return value

    def begin_ticket(binding):
        """Shared ticket path; neither entry point saves UI choices or revisions."""
        with lock:
            tickets.check_binding(binding)
            received = upload_receipt(binding)
            if received is not None:
                tickets.recover(binding, received["asset_id"])
                return result(received, "Arquivo já recebido. Estado atual recuperado sem repetir o envio.")
            preflight_ticket(binding)
            token, expires = tickets.issue(binding)
        return CallToolResult(
            content=[TextContent(type="text", text="Envio autorizado para o arquivo selecionado no painel.")],
            structuredContent={"status": "authorized", "project_id": binding.project_id,
                               "upload_id": binding.upload_id, "revision": binding.expected_revision,
                               "expires_at": expires},
            _meta={"editor": {"upload": {"upload_id": binding.upload_id,
                                       "url": base + "/upload-tickets/" + binding.upload_id,
                                       "method": "POST", "headers": {"Authorization": "Upload " + token,
                                                                     "Content-Type": binding.mime_type},
                                       "expires_at": expires, "max_bytes": binding.size_bytes}}},
        )

    hostname = urlsplit(base).netloc
    server = FastMCP(
        "Editor Ultra", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
        instructions=("Editor Ultra: use editor_open para abrir o painel. O fluxo padrão de direção exporta prompts; "
                      "a VIDEOAPI é opção adicional, explícita e cobrada, acionada somente por editor_videoapi_generate. "
                      "Use editor_import_videoapi_result para importar um clipe VIDEOAPI já concluído; essa ação só faz GET, sem nova geração paga. "
                      "Sem aprovação automática e sem substituir preparação/render do motor. prepare cria análise/pedido real; "
                      "a direção criativa deve ser autorada no host, depois importada com editor_apply_direction. "
                      "Execute editor_render somente após um plano atual válido. Consulte editor_get_project "
                      "para trabalhos e pendências. "
                      "Use editor_measure_motion com asset_id e janelas/ROIs explícitas para medir movimento; "
                      "o resultado é evidência por elemento, ainda sem aplicar motion ou aprovar render. "
                      "Não chame um pedido ou teste técnico de clonagem pronta, "
                      "nem registre aprovação do usuário sem confirmação explícita do arquivo atual. "
                      "Anexos do chat usam file params; o painel autoriza envio direto por editor_save_project "
                      "com state.ui_action='begin_upload' e upload_request, sem salvar escolhas nesse comando. "
                      "Caminhos locais ou blob: não são anexos."),
        auth_server_provider=owner, auth=owner.auth_settings(),
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[hostname] + (["localhost:*", "127.0.0.1:*", "testserver"] if allow_loopback else []),
            allowed_origins=[base, "https://chatgpt.com", "https://chat.openai.com"]),
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    admitted = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
    widget = {"openai/widgetAccessible": True}

    studio_metadata = {
        "ui": {"prefersBorder": True, "csp": {"connectDomains": [base], "resourceDomains": [base, VIDEOAPI_BASE]}},
        "openai/ui": {"availableDisplayModes": ["inline", "fullscreen"], "preferredDisplayMode": "fullscreen"},
        "openai/widgetDescription": "Painel privado de clonagem de edição, aprovação, prompts e renderização do Editor Ultra.",
    }

    @server.resource(UI_URI, name="Editor Ultra", mime_type="text/html;profile=mcp-app", meta=studio_metadata)
    def studio() -> str:
        html = Path(__file__).with_name("ui.html").read_text(encoding="utf-8")
        return html.replace("__EDITOR_ULTRA_LOGO_URL__", escape(base + BRAND_MARK_PATH, quote=True))

    for legacy_uri in UI_ALIASES:
        server.resource(legacy_uri, name="Editor Ultra (compatibilidade)",
                        mime_type="text/html;profile=mcp-app", meta=studio_metadata)(studio)

    @server.tool(name="editor_open", title="Editor Ultra", annotations=read,
                 meta={**widget, "ui": {"resourceUri": UI_URI}, "openai/outputTemplate": UI_URI,
                       "openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]}})
    @offload
    def editor_open(project_id: str | None = None) -> CallToolResult:
        """Abre o painel nativo e projetos privados, sem iniciar render nem aprovar arquivos."""
        return result({"project": snapshot(project_id) if project_id else None,
                       "projects": engine.list_projects(), "catalog_status": catalog.status(),
                       "videoapi_enabled": videoapi_client.enabled,
                       "upload_capabilities": {"direct": True, "origin": base, "max_bytes": MAX_FILE_BYTES,
                                               "ticket_ttl_seconds": TICKET_TTL_SECONDS}}, "Editor Ultra aberto.")

    @server.tool(annotations=read, meta=widget)
    @offload
    def editor_list_templates() -> CallToolResult:
        """Lista templates do acervo privado com amostras reais e limitações; a demonstração não comprova execução."""
        return result(catalog.list_templates(), "Catálogo privado consultado.")

    @server.tool(annotations=read)
    @offload
    def editor_get_template(template_id: str) -> CallToolResult:
        """Lê requisitos e contratos verificados de um template antes de dirigir sua aplicação."""
        return result(catalog.detail(template_id))

    @server.tool(annotations=read, meta=widget)
    @offload
    def editor_get_project(project_id: str) -> CallToolResult:
        """Retoma escolhas, prévias atuais, revisões, pendências e resultado dos trabalhos reais."""
        return result(snapshot(project_id))

    @server.tool(annotations=read)
    @offload
    def editor_get_asset(project_id: str, asset_id: str) -> CallToolResult:
        """Abre uma evidência ou mídia por ID do projeto. Imagens pequenas retornam os pixels reais para inspeção no host."""
        path = engine.resolve_asset(project_id, asset_id)
        mime = signer.mime(path)
        url = signer.url(path)
        content = [ResourceLink(type="resource_link", uri=url, name=path.name, mimeType=mime)]
        if mime.startswith("image/") and path.stat().st_size < 4 * 1024 * 1024:
            content.append(ImageContent(type="image", data=base64.b64encode(path.read_bytes()).decode(), mimeType=mime))
        return CallToolResult(content=content, structuredContent={"project_id": project_id, "asset_id": asset_id,
                                                                 "url": url, "mime_type": mime, "size": path.stat().st_size})

    @server.tool(annotations=read)
    @offload
    def editor_get_result(project_id: str, stage: Literal["clone", "edit", "assembly", "generation"] = "edit") -> CallToolResult:
        """Obtém artefatos reais da etapa atual; mantém revisão técnica e confirmação do usuário separadas."""
        return result(engine.get_result(project_id, stage))

    @server.tool(annotations=write, meta=widget)
    @offload
    def editor_save_project(state: dict[str, Any], project_id: str | None = None,
                            expected_revision: int | None = None) -> CallToolResult:
        """Salva escolhas do painel; aprovações e recibos no JSON não criam aprovação.

        O comando state.ui_action='begin_upload', com upload_request estrito,
        apenas autoriza o envio direto e não salva escolhas ou revisões.
        """
        if state.get("ui_action") == "videoapi_account":
            if set(state) != {"ui_action"}:
                raise ValueError("Comando de consulta VIDEOAPI inválido.")
            return result({"videoapi_account": videoapi_client.account()}, "Saldo VIDEOAPI consultado.")
        if state.get("ui_action") == "videoapi_refresh":
            if set(state) != {"ui_action", "job_id"} or not isinstance(state.get("job_id"), str):
                raise ValueError("Pedido de recuperação VIDEOAPI inválido.")
            if not project_id or expected_revision is None:
                raise ValueError("Projeto e revisão são obrigatórios para recuperar mídia.")
            revision(project_id, expected_revision)
            return result({"videoapi_job": videoapi_jobs.recover_media(project_id, state["job_id"])},
                          "Resultado recuperado da VIDEOAPI sem criar outra geração.")
        if state.get("ui_action") == "videoapi_generate" or "generation_request" in state:
            command = UIVideoAPICommand.model_validate(state)
            if not project_id or expected_revision is None:
                raise ValueError("Projeto e revisão são obrigatórios para gerar.")
            revision(project_id, expected_revision)
            return submit_videoapi_generation(project_id, **command.generation_request.model_dump())
        if "ui_action" in state or "upload_request" in state:
            command = UIUploadCommand.model_validate(state)
            if not project_id or expected_revision is None:
                raise ValueError("O projeto existente e sua revisão são obrigatórios para autorizar o envio.")
            return begin_ticket(UploadBinding(project_id=project_id, expected_revision=expected_revision,
                                              **command.upload_request.model_dump()))
        if project_id:
            queue.assert_idle(project_id)
        with lock:
            if project_id:
                if expected_revision is None:
                    raise ValueError("A revisão atual é obrigatória.")
                queue.assert_idle(project_id)
                revision(project_id, expected_revision)
            return result(engine.save_project(project_id, state, expected_revision))

    @server.tool(annotations=admitted, meta={**widget, "openai/fileParams": ["file"]})
    @serial_upload
    async def editor_import_file(project_id: str, role: str, file: Attachment,
                                 expected_revision: int, shot_id: str | None = None) -> CallToolResult:
        """Transfere anexo real do ChatGPT, verifica mídia e registra referência/bruto/identidade/prévia; não gera vídeo."""
        available = await asyncio.to_thread(upload_preflight, project_id, expected_revision)
        if role == "clone_resource":
            available = min(available, MAX_RESOURCE_BYTES)
        downloaded = await download_attachment(file.download_url, root / "incoming", max_bytes=available)
        try:
            value = await asyncio.to_thread(import_received, project_id, role, downloaded,
                                            file.file_name or "anexo", file.mime_type or mimetypes.guess_type(file.file_name)[0] or "application/octet-stream",
                                            shot_id, expected_revision, host_file_id=file.file_id)
            return result(value, "Arquivo recebido e verificado no motor.")
        finally:
            downloaded.unlink(missing_ok=True)

    @server.tool(annotations=write, meta={**widget, "ui": {"visibility": ["app"]}})
    @offload
    def editor_begin_upload(
        project_id: Annotated[str, Field(min_length=1, max_length=96, pattern=ID)],
        role: Literal["ref", "clone", "footage", "identity", "narration", "logo", "result", "shot", "clone_resource"],
        expected_revision: Annotated[int, Field(strict=True, ge=0)],
        file_name: Annotated[str, Field(min_length=1, max_length=240)],
        mime_type: Annotated[str, Field(min_length=3, max_length=150)],
        size_bytes: Annotated[int, Field(strict=True, ge=1, le=MAX_FILE_BYTES)],
        upload_id: Annotated[str, Field(min_length=36, max_length=36)],
        shot_id: str | None = None,
    ) -> CallToolResult:
        """Autoriza um único arquivo selecionado no painel; o segredo fica apenas na metadata da interface.

        Não altera escolhas nem aprovações. Em resultado incerto, consulte o projeto
        por hostFileId direct:upload_id antes de pedir uma nova autorização.
        """
        binding = UploadBinding(upload_id, project_id, role, expected_revision,
                                file_name, mime_type, size_bytes, shot_id)
        return begin_ticket(binding)

    def enqueue(project_id, operation, kind, expected_revision, request_id, **extra):
        arguments = {"kind": kind, "expected_revision": expected_revision, **extra}
        existing = queue.existing_request(project_id, operation, arguments, request_id)
        if existing:
            return result(existing, "Este pedido já foi registrado. Resultado recuperado sem repetir a execução.")
        with lock:
            existing = queue.existing_request(project_id, operation, arguments, request_id)
            if existing:
                return result(existing, "Este pedido já foi registrado. Resultado recuperado sem repetir a execução.")
            revision(project_id, expected_revision)
            if operation=="measure_motion":
                space_for(MOTION_LIMITS["max_artifact_bytes"])
            if operation=="videoapi_import":
                space_for()
            if operation=="apply_motion":
                space_for(96 * 1024 * 1024)
            job = queue.enqueue(project_id, operation, arguments, request_id)
            return result(job, "Trabalho registrado. Consulte o projeto para acompanhar a execução e o resultado.")

    @server.tool(annotations=read, meta=widget)
    @offload
    def editor_videoapi_account() -> CallToolResult:
        """Consulta saldo e preços da VIDEOAPI sem expor a chave nem realizar uma geração."""
        return result({"videoapi_account": videoapi_client.account()}, "Saldo e custos de geração consultados.")

    def submit_videoapi_generation(project_id: str, request_id: str, kind: str, prompt: str,
                                   aspect_ratio: str, duration_seconds: int | None,
                                   reference_asset_ids: list[str] | None = None) -> CallToolResult:
        """Single secure implementation shared by new tools and the legacy UI-compatible command."""
        engine.get_project(project_id)
        images = []
        for asset_id in reference_asset_ids or []:
            path = engine.resolve_asset(project_id, asset_id)
            mime = signer.mime(path)
            if mime not in {"image/png", "image/jpeg", "image/webp"}:
                raise VideoAPIError("reference_type", "Selecione uma imagem PNG, JPEG ou WebP do projeto.")
            if path.stat().st_size > 3_000_000:
                raise VideoAPIError("reference_size", "Imagem de referência muito grande. Use arquivo menor que 3 MB.")
            filename = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)[:80] or "referencia.png"
            images.append({"mime_type": mime, "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                           "filename": filename})
        payload = build_payload(kind, prompt, aspect_ratio, duration_seconds, images)
        job = videoapi_jobs.submit(project_id, request_id, kind, payload)
        return result({"videoapi_job": job}, "Pedido VIDEOAPI registrado. Acompanhe o status no projeto.")

    @server.tool(annotations=write, meta=widget)
    @offload
    def editor_videoapi_generate(
        project_id: Annotated[str, Field(min_length=1, max_length=96, pattern=ID)],
        request_id: Annotated[str, Field(min_length=1, max_length=96)],
        kind: Literal["video", "image"],
        prompt: Annotated[str, Field(min_length=1, max_length=5000)],
        aspect_ratio: Literal["9:16", "16:9"] = "9:16",
        duration_seconds: Literal[5, 10, 20, 30] | None = None,
        reference_asset_ids: Annotated[list[str], Field(max_length=3)] | None = None,
    ) -> CallToolResult:
        """Paid generation with explicit user authorization, persistent ID and secure server-side key."""
        return submit_videoapi_generation(project_id, request_id, kind, prompt, aspect_ratio,
                                          duration_seconds, reference_asset_ids)

    @server.tool(annotations=write, meta=widget)
    @offload
    def editor_import_videoapi_result(
        project_id: Annotated[str, Field(min_length=1, max_length=96, pattern=ID)],
        videoapi_job_id: Annotated[str, Field(min_length=36, max_length=36)],
        expected_revision: int, request_id: str,
        shot_id: str | None = None,
    ) -> CallToolResult:
        """Importa vídeo concluído do ledger VIDEOAPI para a montagem do projeto.

        Não gera outro vídeo, não cobra créditos nem aceita URL externa. Use
        shot_id no modo generate; caso contrário entra como footage.
        Arquivos importados passam por validação de vídeo e SHA-256 reais.
        """
        return enqueue(project_id, "videoapi_import", "generation_result", expected_revision,
                       request_id, videoapi_job_id=videoapi_job_id, shot_id=shot_id)

    @server.tool(annotations=write, meta=widget)
    @offload
    def editor_prepare(project_id: str, kind: Literal["clone", "edit", "prompts", "assembly"],
                       expected_revision: int, request_id: str) -> CallToolResult:
        """Executa preparação real de evidências e pedido de direção. Não inventa plano, clonagem, render ou aprovação."""
        return enqueue(project_id, "prepare", kind, expected_revision, request_id)

    @server.tool(annotations=write)
    @offload
    def editor_apply_direction(project_id: str, kind: Literal["clone", "edit", "generation", "assembly"],
                               direction: dict[str, Any], expected_revision: int, request_id: str) -> CallToolResult:
        """Importa direção autorada no host no contrato retornado por prepare. Use asset:ID para recursos; sem comandos ou URLs."""
        return enqueue(project_id, "direction", kind, expected_revision, request_id, direction=direction)

    @server.tool(annotations=write)
    @offload
    def editor_render(project_id: str, kind: Literal["clone", "edit", "assembly"],
                      expected_revision: int, request_id: str) -> CallToolResult:
        """Executa o plano atual no motor local e devolve um MP4 real. Não aprova o resultado nem chama geradores."""
        return enqueue(project_id, "render", kind, expected_revision, request_id)

    @server.tool(annotations=write)
    @offload
    def editor_measure_motion(project_id: str, asset_id: str,
                              specification: MotionMeasurementSpecification,
                              expected_revision: int, request_id: str) -> CallToolResult:
        """Mede posição, escala e rotação em janelas/ROIs declaradas de um vídeo do projeto.

        Até quatro elementos, 300 frames por janela e 600 element-frames por job,
        sujeitos ao cache de 128 MiB; fonte até 120 s, 3600 frames e Full HD.
        Máscara somente por mask_asset_id de imagem deste projeto. Devolve IDs
        de observações, perfil, QA e CSV. Não aplica a curva nem aprova o vídeo.
        """
        return enqueue(project_id,"measure_motion","motion",expected_revision,request_id,
                       asset_id=asset_id,
                       specification=specification.model_dump(by_alias=True,exclude_none=True))

    @server.tool(annotations=write, meta=widget)
    @offload
    def editor_record_review(project_id: str, kind: Literal["clone", "final"],
                             decision: Literal["approved", "rejected"], confirmation: bool,
                             asset_id: str, checks: dict[str, Any], notes: str,
                             expected_revision: int) -> CallToolResult:
        """Registra decisão explícita do usuário sobre o arquivo atual; outra revisão ou outros bytes invalidam aprovação."""
        queue.assert_idle(project_id)
        with lock:
            queue.assert_idle(project_id)
            revision(project_id, expected_revision)
            return result(engine.record_review(project_id, kind, decision, confirmation,
                                               asset_id=asset_id, checks=checks, notes=notes,
                                               expected_revision=expected_revision))

    async def authenticate_request(request: Request):
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer "):
            return None
        return await owner.load_access_token(header[7:])

    @serial_upload
    async def catalog_install(request: Request):
        token = await authenticate_request(request)
        if token is None or "editor:write" not in token.scopes:
            return JSONResponse({"error": "authentication_required"}, status_code=401)
        incoming = root / "incoming"
        incoming.mkdir(exist_ok=True)
        temporary = incoming / (uuid.uuid4().hex + ".zip")
        total = 0
        try:
            size = int(request.headers.get("content-length", "0"))
            available = await asyncio.to_thread(space_for, size * 2)
            with temporary.open("xb") as target:
                async with asyncio.timeout(300):
                    async for block in request.stream():
                        total += len(block)
                        if total > min(200 * 1024 * 1024, available):
                            raise ValueError("Pacote excede 200 MiB.")
                        target.write(block)
            def install_catalog():
                with lock:
                    receipt = catalog.install(temporary)
                    engine.template_library = catalog.library_path()
                    return receipt
            receipt = await asyncio.to_thread(install_catalog)
            return JSONResponse(receipt)
        except (ValueError, OSError, TimeoutError) as exc:
            return JSONResponse({"error": str(exc)[:300]}, status_code=400)
        finally:
            temporary.unlink(missing_ok=True)

    @serial_upload
    async def direct_upload(request: Request):
        """Authenticated binary route for first-party upload clients and integration checks."""
        token = await authenticate_request(request)
        if token is None or "editor:write" not in token.scopes:
            return JSONResponse({"error": "authentication_required"}, status_code=401)
        project_id = request.path_params["project_id"]
        role = request.path_params["role"]
        try:
            expected = int(request.headers.get("x-editor-revision", "-1"))
            size = int(request.headers.get("content-length", "0"))
            available = await asyncio.to_thread(upload_preflight, project_id, expected, size * 2)
            if role == "clone_resource":
                available = min(available, MAX_RESOURCE_BYTES)
        except (ValueError, OSError) as exc:
            return JSONResponse({"error": str(exc)[:300]}, status_code=409)
        incoming = root / "incoming"
        incoming.mkdir(exist_ok=True)
        temporary = incoming / (uuid.uuid4().hex + ".upload")
        count = 0
        try:
            async with asyncio.timeout(300):
                with temporary.open("xb") as target:
                    async for block in request.stream():
                        count += len(block)
                        if count > available:
                            raise ValueError("Arquivo excede 512 MiB.")
                        target.write(block)
            value = await asyncio.to_thread(import_received, project_id, role, temporary,
                                            request.query_params.get("filename", "anexo"),
                                            request.headers.get("content-type", "application/octet-stream"),
                                            request.query_params.get("shot_id"), expected)
            return JSONResponse(public(value))
        except (ValueError, OSError, TimeoutError) as exc:
            return JSONResponse({"error": str(exc)[:500]}, status_code=400)
        finally:
            temporary.unlink(missing_ok=True)

    async def ticket_upload(request: Request):
        """CORS is scoped to this capability route; no cookies or OAuth grant are used."""
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=UPLOAD_HEADERS)
        claim, temporary, acquired = None, None, False
        phase = "authorization"

        def rejected(code, message, status, *, uncertain):
            # Do not log headers, file names, bodies, paths, or exception text.
            # Untrusted route values must be canonical UUIDs before logging.
            upload_id = request.path_params.get("upload_id", "")
            try:
                if str(uuid.UUID(upload_id)) != upload_id:
                    upload_id = "unavailable"
            except (ValueError, AttributeError, TypeError):
                upload_id = "unavailable"
            UPLOAD_LOG.warning("upload_rejected code=%s status=%s phase=%s upload_id=%s",
                               code, status, phase, upload_id)
            return JSONResponse({"error": message, "code": code, "uncertain": uncertain},
                                status_code=status, headers=UPLOAD_HEADERS)

        try:
            header = request.headers.get("authorization", "")
            if not header.startswith("Upload "):
                raise UploadTicketError("upload_ticket_required", "Autorize este envio pelo painel conectado.", 401)
            if request.query_params or request.headers.get("content-encoding", "identity") != "identity":
                raise UploadTicketError("upload_request", "Envie apenas os bytes originais do arquivo autorizado.")
            phase = "claim"
            claim = await asyncio.to_thread(tickets.claim, request.path_params["upload_id"], header[7:],
                                           request.headers.get("content-type", ""),
                                           request.headers.get("content-length"))
            if claim.completed:
                phase = "receipt"
                value = await asyncio.to_thread(upload_receipt, claim.binding, claim.asset_id)
                if value is None:
                    raise UploadTicketError("upload_receipt_missing", "Confira o arquivo no projeto antes de repetir.", 409)
                return JSONResponse(public(value), headers=UPLOAD_HEADERS)
            # Bound both the wait for the one transfer slot and the incoming
            # stream. Claiming precedes this wait so duplicate POSTs fail at once.
            async with asyncio.timeout(300):
                phase = "waiting"
                await upload_lock.acquire()
                acquired = True
                phase = "preflight"
                await asyncio.to_thread(preflight_ticket, claim.binding)
                incoming = root / "incoming"
                incoming.mkdir(exist_ok=True, mode=0o700)
                temporary = incoming / ("direct-" + uuid.uuid4().hex + ".upload")
                count = 0
                phase = "receive"
                with temporary.open("xb") as target:
                    temporary.chmod(0o600)
                    async for block in request.stream():
                        count += len(block)
                        if count > claim.binding.size_bytes:
                            raise UploadTicketError("upload_content_length", "O arquivo excede o tamanho autorizado.", 413)
                        await asyncio.to_thread(target.write, block)
                if count != claim.binding.size_bytes:
                    raise UploadTicketError("upload_incomplete", "O arquivo chegou incompleto. Confira e tente novamente.")
            # Do not unlink a file or release its claim while a cancelled HTTP
            # waiter leaves an engine commit running in its worker thread.
            phase = "commit"
            commit = asyncio.create_task(asyncio.to_thread(commit_ticket, claim, temporary))
            try:
                value = await asyncio.shield(commit)
            except asyncio.CancelledError:
                await commit
                raise
            phase = "response"
            return JSONResponse(public(value), headers=UPLOAD_HEADERS)
        except UploadTicketError as exc:
            if exc.code in UPLOAD_REJECTED_TICKET_CODES | UPLOAD_UNCERTAIN_TICKET_CODES:
                return rejected(exc.code, str(exc), exc.status,
                                uncertain=exc.code in UPLOAD_UNCERTAIN_TICKET_CODES)
            return rejected("upload_uncertain", "Confira o recebimento no projeto antes de repetir.",
                            500, uncertain=True)
        except ValidationError as exc:
            code = exc.issues[0].get("code") if exc.issues else None
            if code in UPLOAD_VALIDATION_ERRORS:
                status, message = UPLOAD_VALIDATION_ERRORS[code]
                return rejected(code, message, status, uncertain=False)
            return rejected("upload_uncertain", "Confira o recebimento no projeto antes de repetir.",
                            500, uncertain=True)
        except (TimeoutError, ClientDisconnect):
            return rejected("upload_interrupted", "O envio foi interrompido. Confira o recebimento antes de repetir.",
                            409, uncertain=True)
        except (ValueError, OSError):
            # A failure can occur after the engine has already committed the file.
            # Never turn an unclassified exception into a definitive rejection.
            return rejected("upload_uncertain", "O motor não confirmou o envio. Confira o recebimento antes de repetir.",
                            409, uncertain=True)
        except Exception:
            return rejected("upload_uncertain", "Confira o recebimento no projeto antes de repetir.",
                            500, uncertain=True)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if acquired:
                upload_lock.release()
            if claim is not None and not claim.completed:
                await asyncio.to_thread(tickets.fail, claim)

    async def preview(request: Request):
        try:
            path = signer.resolve(request.path_params["path"], request.query_params.get("expires", ""),
                                  request.query_params.get("signature", ""))
        except (ValueError, OSError):
            return JSONResponse({"error": "preview_link_expired_or_invalid"}, status_code=403)
        return FileResponse(path, media_type=signer.mime(path), headers={
            "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"})

    async def brand_mark(request):
        # Only this packaged brand asset is public; project media keeps signed URLs.
        return FileResponse(Path(__file__).with_name("brand") / "e-mark-v1.png", media_type="image/png",
                            headers={"Cache-Control": "public, max-age=31536000, immutable",
                                     "X-Content-Type-Options": "nosniff"})

    async def health(request):
        return JSONResponse({"service": "editor-ultra", "version": __version__, "status": "ok",
                             "video_generation": "prompt_export_only + optional_videoapi", "ffmpeg": bool(shutil.which("ffmpeg"))})

    async def home(request):
        return HTMLResponse("<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Editor Ultra</title>"
                            "<body><h1>Editor Ultra</h1><p>Motor privado para a interface do ChatGPT.</p>"
                            "<p>Adicione este serviço como um MCP personalizado com autenticação OAuth.</p>"
                            "<p>Endpoint: <code>/mcp</code></p><p>A geração de vídeo usa prompts e clipes devolvidos pelo usuário.</p></body></html>",
                            headers={"Content-Security-Policy": "default-src 'none'; style-src 'self'", "Cache-Control": "no-store"})

    app = server.streamable_http_app()
    app.routes.extend(owner.routes())
    app.routes.extend([Route("/healthz", health), Route("/", home), Route(BRAND_MARK_PATH, brand_mark),
                       Route("/media/{path:path}", preview),
                       Route("/catalog/install", catalog_install, methods=["POST"]),
                       Route("/upload-tickets/{upload_id}", ticket_upload, methods=["POST", "OPTIONS"]),
                       Route("/uploads/{project_id}/{role}", direct_upload, methods=["POST"])])
    app.add_middleware(OwnerAuthGuard, provider=owner)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        queue.start()
        videoapi_jobs.start()
        try:
            async with original_lifespan(application):
                yield
        finally:
            videoapi_jobs.close()
            queue.close()

    app.router.lifespan_context = lifespan
    app.state.editor_engine = engine
    app.state.editor_catalog = catalog
    app.state.editor_queue = queue
    app.state.editor_videoapi_jobs = videoapi_jobs
    app.state.editor_mcp = server
    app.state.editor_owner = owner
    app.state.editor_upload_tickets = tickets
    return app


def main():
    import uvicorn
    app = create_app(allow_loopback=os.environ.get("EDITOR_ULTRA_ALLOW_LOOPBACK") == "1")
    # Access logs can contain signed file URLs or authorization codes; keep them off.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), access_log=False)


if __name__ == "__main__":
    main()

