"""Authenticated MCP Apps bridge to the real, local Editor Ultra engines.

The host directs the edit. This server admits files, prepares evidence, executes
validated plans and returns actual artifacts. It never calls a video generator.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from functools import wraps
import json
import mimetypes
import os
from pathlib import Path
import shutil
import threading
from typing import Any, Literal
from urllib.parse import urlsplit
import uuid

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, ImageContent, ResourceLink, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.routing import Route

from . import __version__
from .auth import OwnerAuthGuard, OwnerOAuthProvider
from .catalog import Catalog
from .engine import EngineAdapter
from .jobs import JobQueue
from .media import MAX_FILE_BYTES, PreviewSigner, download_attachment


UI_URI = "ui://editor-ultra/studio-v1.html"
ID = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$"


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    download_url: str = Field(max_length=12000)
    file_id: str = Field(min_length=1, max_length=300)
    mime_type: str = Field(default="", max_length=150)
    file_name: str = Field(default="", max_length=240)


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
            raise ValueError("O projeto mudou. Atualize o painel antes de repetir a ação.")

    def execute(job):
        with lock:
            project_id = job["project_id"]
            revision(project_id, job["expected_revision"])
            kind = job["kind"]
            if job["operation"] == "prepare":
                return engine.prepare(project_id, kind, expected_revision=job["expected_revision"])
            if job["operation"] == "direction":
                return engine.apply_direction(project_id, kind, job["direction"], expected_revision=job["expected_revision"])
            if job["operation"] == "render":
                return engine.render(project_id, kind, expected_revision=job["expected_revision"])
            raise ValueError("Operação indisponível.")

    queue = JobQueue(root, execute)

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
        return value

    def space_for(size=0):
        limit = int(os.environ.get("EDITOR_ULTRA_MAX_STORAGE_MB", "850")) * 1024 * 1024
        used = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
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

    def import_received(project_id, role, path, filename, mime_type, shot_id, expected):
        queue.assert_idle(project_id)
        with lock:
            queue.assert_idle(project_id)
            revision(project_id, expected)
            space_for(path.stat().st_size)
            return engine.import_local_file(project_id, role, path, filename, mime_type,
                                            shot_id=shot_id, expected_revision=expected)

    hostname = urlsplit(base).netloc
    server = FastMCP(
        "Editor Ultra", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
        instructions=("Editor Ultra: use editor_open para abrir o painel. A geração de vídeo é apenas exportação "
                      "de prompts; o usuário produz clipes fora e os devolve. prepare cria análise/pedido real; "
                      "a direção criativa deve ser autorada no host, depois importada com editor_apply_direction. "
                      "Execute editor_render somente após um plano atual válido. Consulte editor_get_project "
                      "para trabalhos e pendências. Não chame um pedido ou teste técnico de clonagem pronta, "
                      "nem registre aprovação do usuário sem confirmação explícita do arquivo atual. "
                      "Arquivos devem ser enviados por file params; caminhos locais ou blob: não são anexos."),
        auth_server_provider=owner, auth=owner.auth_settings(),
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[hostname] + (["localhost:*", "127.0.0.1:*", "testserver"] if allow_loopback else []),
            allowed_origins=[base, "https://chatgpt.com", "https://chat.openai.com"]),
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    write = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
    admitted = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)

    @server.resource(UI_URI, name="Editor Ultra", mime_type="text/html;profile=mcp-app", meta={
        "ui": {"prefersBorder": True, "csp": {"connectDomains": [], "resourceDomains": [base]}},
        "openai/ui": {"availableDisplayModes": ["inline", "fullscreen"]},
        "openai/widgetDescription": "Painel privado de clonagem de edição, aprovação, prompts e renderização do Editor Ultra.",
    })
    def studio() -> str:
        return Path(__file__).with_name("ui.html").read_text(encoding="utf-8")

    @server.tool(name="editor_open", title="Abrir Editor Ultra", annotations=read,
                 meta={"ui": {"resourceUri": UI_URI}, "openai/outputTemplate": UI_URI})
    @offload
    def editor_open(project_id: str | None = None) -> CallToolResult:
        """Abre o painel nativo e projetos privados, sem iniciar render nem aprovar arquivos."""
        return result({"project": snapshot(project_id) if project_id else None,
                       "projects": engine.list_projects(), "catalog_status": catalog.status()}, "Editor Ultra aberto.")

    @server.tool(annotations=read)
    @offload
    def editor_list_templates() -> CallToolResult:
        """Lista templates do acervo privado com amostras reais e limitações; a demonstração não comprova execução."""
        return result(catalog.list_templates(), "Catálogo privado consultado.")

    @server.tool(annotations=read)
    @offload
    def editor_get_template(template_id: str) -> CallToolResult:
        """Lê requisitos e contratos verificados de um template antes de dirigir sua aplicação."""
        return result(catalog.detail(template_id))

    @server.tool(annotations=read)
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

    @server.tool(annotations=write)
    @offload
    def editor_save_project(state: dict[str, Any], project_id: str | None = None,
                            expected_revision: int | None = None) -> CallToolResult:
        """Salva escolhas do painel. Aprovações e recibos enviados no JSON nunca criam aprovação no servidor."""
        if project_id:
            queue.assert_idle(project_id)
        with lock:
            if project_id:
                if expected_revision is None:
                    raise ValueError("A revisão atual é obrigatória.")
                queue.assert_idle(project_id)
                revision(project_id, expected_revision)
            return result(engine.save_project(project_id, state, expected_revision))

    @server.tool(annotations=admitted, meta={"openai/fileParams": ["file"]})
    @serial_upload
    async def editor_import_file(project_id: str, role: str, file: Attachment,
                                 expected_revision: int, shot_id: str | None = None) -> CallToolResult:
        """Transfere anexo real do ChatGPT, verifica mídia e registra referência/bruto/identidade/prévia; não gera vídeo."""
        available = await asyncio.to_thread(upload_preflight, project_id, expected_revision)
        downloaded = await download_attachment(file.download_url, root / "incoming", max_bytes=available)
        try:
            value = await asyncio.to_thread(import_received, project_id, role, downloaded,
                                            file.file_name or "anexo", file.mime_type or mimetypes.guess_type(file.file_name)[0] or "application/octet-stream",
                                            shot_id, expected_revision)
            return result(value, "Arquivo recebido e verificado no motor.")
        finally:
            downloaded.unlink(missing_ok=True)

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
            job = queue.enqueue(project_id, operation, arguments, request_id)
            return result(job, "Trabalho registrado. Consulte o projeto para acompanhar a execução e o resultado.")

    @server.tool(annotations=write)
    @offload
    def editor_prepare(project_id: str, kind: Literal["clone", "edit", "prompts"],
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

    async def preview(request: Request):
        try:
            path = signer.resolve(request.path_params["path"], request.query_params.get("expires", ""),
                                  request.query_params.get("signature", ""))
        except (ValueError, OSError):
            return JSONResponse({"error": "preview_link_expired_or_invalid"}, status_code=403)
        return FileResponse(path, media_type=signer.mime(path), headers={
            "Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"})

    async def health(request):
        return JSONResponse({"service": "editor-ultra", "version": __version__, "status": "ok",
                             "video_generation": "prompt_export_only", "ffmpeg": bool(shutil.which("ffmpeg"))})

    async def home(request):
        return HTMLResponse("<!doctype html><html lang='pt-BR'><meta charset='utf-8'><title>Editor Ultra</title>"
                            "<body><h1>Editor Ultra</h1><p>Motor privado para a interface do ChatGPT.</p>"
                            "<p>Adicione este serviço como um MCP personalizado com autenticação OAuth.</p>"
                            "<p>Endpoint: <code>/mcp</code></p><p>A geração de vídeo usa prompts e clipes devolvidos pelo usuário.</p></body></html>",
                            headers={"Content-Security-Policy": "default-src 'none'; style-src 'self'", "Cache-Control": "no-store"})

    app = server.streamable_http_app()
    app.routes.extend(owner.routes())
    app.routes.extend([Route("/healthz", health), Route("/", home), Route("/media/{path:path}", preview),
                       Route("/catalog/install", catalog_install, methods=["POST"]),
                       Route("/uploads/{project_id}/{role}", direct_upload, methods=["POST"])])
    app.add_middleware(OwnerAuthGuard, provider=owner)
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application):
        queue.start()
        try:
            async with original_lifespan(application):
                yield
        finally:
            queue.close()

    app.router.lifespan_context = lifespan
    app.state.editor_engine = engine
    app.state.editor_catalog = catalog
    app.state.editor_queue = queue
    app.state.editor_mcp = server
    app.state.editor_owner = owner
    return app


def main():
    import uvicorn
    app = create_app(allow_loopback=os.environ.get("EDITOR_ULTRA_ALLOW_LOOPBACK") == "1")
    # Access logs can contain signed file URLs or authorization codes; keep them off.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), access_log=False)


if __name__ == "__main__":
    main()
