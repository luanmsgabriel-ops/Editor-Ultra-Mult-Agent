"""Bounded file admission and short-lived, file-scoped preview URLs."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import mimetypes
import os
from pathlib import Path
import re
import socket
import time
from urllib.parse import urlsplit
import uuid

import httpx


MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_UPLOAD_SECONDS = 300


def allowed_file_url(url: str):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if (parts.scheme != "https" or parts.username or parts.password or parts.port not in (None, 443)
            or parts.fragment or len(url) > 12000):
        raise ValueError("Use o link HTTPS temporário do arquivo anexado ao ChatGPT.")
    allowed = (host == "files.oaiusercontent.com" or host.endswith(".oaiusercontent.com")
               or (host.endswith(".blob.core.windows.net") and host.startswith(("oaisdmntpr", "oaisdsorpr")))
               or bool(re.fullmatch(r"oaisdmntpr[\w-]*\.s3(?:[.-][\w-]+)?\.amazonaws\.com", host)))
    if not allowed:
        raise ValueError("Este domínio não é uma origem de anexos autorizada. Anexe o arquivo ao ChatGPT.")
    return host


async def download_attachment(url: str, directory: Path, max_bytes: int = MAX_FILE_BYTES):
    """No arbitrary links, redirects, proxy credentials or local-network reads."""
    import asyncio

    host = allowed_file_url(url)
    addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, 0, socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("A origem do anexo não resolve para um endereço público.")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid.uuid4().hex + ".upload")
    count = 0
    try:
        async with asyncio.timeout(MAX_UPLOAD_SECONDS):
            async with httpx.AsyncClient(follow_redirects=False, trust_env=False, timeout=45) as client:
                async with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
                    if response.status_code != 200:
                        raise ValueError("O link do anexo expirou ou não está disponível. Solicite um novo link.")
                    if int(response.headers.get("content-length", "0")) > max_bytes:
                        raise ValueError("O arquivo ultrapassa o limite de 512 MiB por envio.")
                    with path.open("xb") as output:
                        os.chmod(path, 0o600)
                        async for block in response.aiter_bytes(1024 * 1024):
                            count += len(block)
                            if count > max_bytes:
                                raise ValueError("O arquivo ultrapassa o limite de envio.")
                            output.write(block)
        if count == 0:
            raise ValueError("O arquivo está vazio.")
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class PreviewSigner:
    def __init__(self, root: Path, base_url: str, key: str):
        self.root = root.resolve()
        self.base_url = base_url.rstrip("/")
        self.key = hashlib.sha256(("editor-ultra-preview-v1:" + key).encode()).digest()

    def _signature(self, relative: str, expires: int):
        return hmac.new(self.key, f"{relative}\n{expires}".encode(), hashlib.sha256).hexdigest()

    def url(self, path: Path, ttl: int = 1800):
        from urllib.parse import quote
        actual = path.resolve(strict=True)
        if not actual.is_relative_to(self.root) or not actual.is_file():
            raise ValueError("Prévia fora do acervo privado.")
        relative = actual.relative_to(self.root).as_posix()
        expires = int(time.time()) + min(ttl, 3600)
        return f"{self.base_url}/media/{quote(relative, safe='/')}?expires={expires}&signature={self._signature(relative, expires)}"

    def resolve(self, relative: str, expires: str, signature: str):
        if not re.fullmatch(r"[0-9]{1,12}", expires) or not re.fullmatch(r"[0-9a-f]{64}", signature):
            raise ValueError("Link inválido.")
        until = int(expires)
        if until < int(time.time()) or until > int(time.time()) + 3605:
            raise ValueError("Link expirado. Atualize o projeto para receber outra prévia.")
        if not hmac.compare_digest(signature, self._signature(relative, until)):
            raise ValueError("Link inválido.")
        actual = (self.root / relative).resolve(strict=True)
        if not actual.is_relative_to(self.root) or not actual.is_file():
            raise ValueError("Prévia indisponível.")
        # Never expose auth/job databases or configuration even if called internally by mistake.
        if actual.suffix.lower() not in {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp", ".wav", ".mp3", ".json", ".txt", ".md", ".zip"}:
            raise ValueError("Tipo de arquivo indisponível para prévia.")
        return actual

    @staticmethod
    def mime(path: Path):
        return mimetypes.guess_type(path.name)[0] or "application/octet-stream"
