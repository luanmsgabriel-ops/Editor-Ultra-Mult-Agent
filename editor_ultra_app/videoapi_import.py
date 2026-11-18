"""Download an already-paid VIDEOAPI result safely into the private project.

No POST is performed. The job URL is owned by the provider ledger, never
accepted from the browser; redirects must remain in an operator-owned exact
HTTPS hostname allowlist, and DNS is pinned to verified public addresses.
"""
from __future__ import annotations

import http.client
import ipaddress
import os
from pathlib import Path
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from .videoapi import VideoAPIError, safe_media_url

MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
DEFAULT_HOSTS = frozenset({"videoapi-wheat.vercel.app", "www.videoapi.com.br"})
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_REDIRECTS = {301, 302, 303, 307, 308}


def approved_hosts():
    """Additional CDN domains are explicitly configured in the SERVER environment."""
    extra = os.environ.get("EDITOR_ULTRA_VIDEOAPI_MEDIA_HOSTS", "")
    names = {name.strip().lower().rstrip(".") for name in extra.split(",") if name.strip()}
    if any(not _HOST_RE.fullmatch(name) or ".." in name or "*" in name for name in names):
        raise VideoAPIError("media_hosts_config", "A lista privada de domínios da VIDEOAPI é inválida.")
    return DEFAULT_HOSTS | names


def verified_origin(value, hosts=None):
    link = safe_media_url(value)
    if link is None:
        raise VideoAPIError("media_url", "O resultado não contém um link HTTPS válido para importação.")
    p = urlsplit(link)
    host = (p.hostname or "").lower().rstrip(".")
    if p.fragment or host not in (hosts if hosts is not None else approved_hosts()):
        raise VideoAPIError("media_host",
                            "O domínio da mídia VIDEOAPI não está autorizado para importação no servidor. "
                            "Configure o domínio exato em EDITOR_ULTRA_VIDEOAPI_MEDIA_HOSTS ou faça upload manual.")
    return link


def _pinned_get(link):
    """Pin the verified public IP while keeping TLS certificate validation and SNI."""
    parts = urlsplit(link)
    host = parts.hostname
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise VideoAPIError("media_dns", "O domínio da mídia não resolve exclusivamente para endereços públicos.")
    address = addresses[0][4][0]
    connection = http.client.HTTPSConnection(host, timeout=45, context=ssl.create_default_context())

    def dial(_endpoint, timeout=45, source_address=None):
        return socket.create_connection((address, 443), timeout, source_address=source_address)

    connection._create_connection = dial
    path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
    try:
        connection.request("GET", path, headers={
            "Accept": "video/mp4,application/octet-stream,*/*",
            "Accept-Encoding": "identity",
            "User-Agent": "EditorUltra-VerifiedMediaImport/1",
            "Host": host,
        })
        return connection, connection.getresponse()
    except BaseException:
        connection.close()
        raise


def download_completed_video(value, destination_dir, *, max_bytes=MAX_DOWNLOAD_BYTES,
                             hosts=None, fetch=None):
    """Bounded streaming, no automatic paid generation, no arbitrary URL fetch.

    A testing fetch callback is injected by trusted Python code, never via MCP.
    A returned path is temporary; the caller must use the media admission gate.
    """
    if type(max_bytes) is not int or not 0 < max_bytes <= MAX_DOWNLOAD_BYTES:
        raise VideoAPIError("media_budget", "Limite de download inválido.")
    allowed = approved_hosts() if hosts is None else frozenset(hosts)
    url = verified_origin(value, allowed)
    directory = Path(destination_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = directory / (uuid4().hex + ".videoapi-upload")
    try:
        for redirects in range(4):
            url = verified_origin(url, allowed)
            try:
                connection, response = (fetch or _pinned_get)(url)
            except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException):
                raise VideoAPIError("media_download",
                                    "Não foi possível acessar o arquivo gerado. Recupere o link concluído ou envie o MP4 manualmente.") from None
            try:
                if response.status in _REDIRECTS:
                    location = response.getheader("Location")
                    if redirects >= 3 or not location:
                        raise VideoAPIError("media_redirect", "Redirecionamentos da mídia excederam o limite seguro.")
                    url = verified_origin(urljoin(url, location), allowed)
                    continue
                if response.status != 200:
                    raise VideoAPIError("media_http",
                                        "O download concluído não está disponível (HTTP " + str(response.status) +
                                        "). Recupere o link ou envie o MP4 manualmente.",
                                        response.status)
                raw_size = response.getheader("Content-Length")
                if raw_size is not None:
                    try:
                        declared_size = int(raw_size)
                    except ValueError:
                        raise VideoAPIError("media_length", "O provedor informou tamanho inválido.") from None
                    if declared_size > max_bytes or declared_size < 0:
                        raise VideoAPIError("media_budget", "O arquivo ultrapassa o limite de importação.")
                media_type = str(response.getheader("Content-Type") or "").split(";", 1)[0].lower()
                if media_type and media_type not in {
                    "video/mp4", "application/octet-stream", "application/mp4",
                    "binary/octet-stream", "video/quicktime",
                }:
                    raise VideoAPIError("media_type", "O provedor não entregou um arquivo de vídeo.")
                with temporary.open("xb") as output:
                    os.chmod(temporary, 0o600)
                    size = 0
                    while True:
                        chunk = response.read(min(1024 * 1024, max_bytes - size + 1))
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise VideoAPIError("media_budget", "O download ultrapassou o limite de armazenamento.")
                        output.write(chunk)
                if not size:
                    raise VideoAPIError("media_empty", "O vídeo gerado está vazio.")
                return temporary
            finally:
                connection.close()
        raise VideoAPIError("media_redirect", "O link da mídia não pôde ser validado.")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
