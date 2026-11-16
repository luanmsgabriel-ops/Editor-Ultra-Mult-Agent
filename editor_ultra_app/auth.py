"""Single-owner OAuth 2.1 authorization for the private Editor Ultra MCP app.

The MCP SDK owns protocol parsing, client authentication and PKCE validation.
This provider owns the explicit owner consent, durable grants and single-use
exchanges. Install ``OwnerAuthGuard`` on the resulting ASGI app as well: the
SDK's token handler currently accepts, but does not validate, ``resource``.

There is deliberately no anonymous owner setup and no password in a URL. Set a
random EDITOR_ULTRA_OWNER_KEY of at least 32 characters outside the repository.
Changing that key revokes existing grants on the next service start.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.auth.routes import build_metadata
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route


SCOPES = ["editor:read", "editor:write"]
OWNER_SUBJECT = "owner"
ACCESS_TTL = 3600
REFRESH_TTL = 30 * 86400
CONSENT_TTL = 600
CODE_TTL = 120
MAX_AUTH_BODY = 16384
MAX_CLIENTS = 128
MAX_PENDING = 128
MAX_TOKENS = 4096
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,160}$")
_CALLBACK = re.compile(r"^/connector/oauth/[A-Za-z0-9_-]{8,160}$")
_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class _Transaction:
    """Explicit context manager also supports the SDK's frozen error dataclasses."""

    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row

    def __enter__(self) -> sqlite3.Connection:
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            self.db.rollback() if exc_type else self.db.commit()
        finally:
            self.db.close()
        return False


class OwnerOAuthProvider:
    """Persistent provider for one private owner, not a multi-user identity service."""

    def __init__(
        self,
        data_dir: Path,
        base_url: str,
        owner_key: str,
        allow_loopback: bool = False,
    ) -> None:
        if not isinstance(owner_key, str) or not 32 <= len(owner_key) <= 512:
            raise ValueError("EDITOR_ULTRA_OWNER_KEY must contain 32–512 characters")
        parsed = urlsplit(base_url)
        loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or (parsed.scheme != "https" and not (allow_loopback and loopback and parsed.scheme == "http"))
        ):
            raise ValueError("OAuth base URL must be a canonical HTTPS origin")
        self.base_url = base_url.rstrip("/")
        # The SDK serializes origin-only AnyHttpUrl issuers with a trailing slash.
        self.issuer_url = str(AnyHttpUrl(self.base_url))
        self.resource_url = self.base_url + "/mcp"
        self.allow_loopback = allow_loopback
        self._key_hash = _hash(owner_key)
        self._cookie_name = "eu-owner-csrf" if parsed.scheme == "http" else "__Secure-eu-owner-csrf"
        self._secure_cookie = parsed.scheme == "https"
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = root / "auth.sqlite3"
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS clients (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL,
                    authorized REAL
                );
                CREATE TABLE IF NOT EXISTS pending (
                    digest TEXT PRIMARY KEY, client_id TEXT NOT NULL, payload TEXT NOT NULL,
                    expires REAL NOT NULL, csrf_digest TEXT, attempts INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS codes (
                    digest TEXT PRIMARY KEY, client_id TEXT NOT NULL, payload TEXT NOT NULL,
                    expires REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    digest TEXT PRIMARY KEY, kind TEXT NOT NULL, client_id TEXT NOT NULL,
                    family TEXT NOT NULL, scopes TEXT NOT NULL, resource TEXT NOT NULL,
                    subject TEXT NOT NULL, expires INTEGER NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS tokens_family ON tokens(family);
                CREATE TABLE IF NOT EXISTS rate_limits (
                    key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL
                );
            """)
            fingerprint = _hash(self._key_hash + "\n" + self.base_url)
            previous = db.execute("SELECT value FROM settings WHERE key='owner'").fetchone()
            if previous and previous[0] != fingerprint:
                for table in ("pending", "codes", "tokens"):
                    db.execute(f"DELETE FROM {table}")
            db.execute("INSERT OR REPLACE INTO settings VALUES ('owner', ?)", (fingerprint,))
        self.db_path.chmod(0o600)

    def _db(self) -> _Transaction:
        return _Transaction(self.db_path)

    def _cleanup(self, db: sqlite3.Connection) -> None:
        now = time.time()
        for table in ("pending", "codes", "tokens", "rate_limits"):
            db.execute(f"DELETE FROM {table} WHERE expires < ?", (now,))
        db.execute("DELETE FROM clients WHERE authorized IS NULL AND created < ?", (now - 86400,))

    def rate_allowed(self, key: str, limit: int, seconds: int) -> bool:
        """Bounded persistent fixed-window limiter; keys contain no raw IP addresses."""
        now = time.time()
        with self._db() as db:
            db.execute("DELETE FROM rate_limits WHERE expires < ?", (now,))
            row = db.execute("SELECT count,expires FROM rate_limits WHERE key=?", (key,)).fetchone()
            if row and row["count"] >= limit:
                return False
            if row:
                db.execute("UPDATE rate_limits SET count=count+1 WHERE key=?", (key,))
            else:
                # The guard also applies global limits, so clients cannot grow this table without bound.
                if db.execute("SELECT COUNT(*) FROM rate_limits").fetchone()[0] >= 2048:
                    return False
                db.execute("INSERT INTO rate_limits VALUES (?,?,?)", (key, 1, now + seconds))
            return True

    def auth_settings(self) -> AuthSettings:
        return AuthSettings(
            issuer_url=self.issuer_url,
            resource_server_url=self.resource_url,
            required_scopes=SCOPES,
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=SCOPES, default_scopes=SCOPES,
            ),
            revocation_options=RevocationOptions(enabled=True),
        )

    def authorization_metadata(self) -> dict[str, Any]:
        settings = self.auth_settings()
        metadata = build_metadata(
            settings.issuer_url, None, settings.client_registration_options,
            settings.revocation_options,
        ).model_dump(mode="json", exclude_none=True)
        methods = ["none", "client_secret_post", "client_secret_basic"]
        metadata["token_endpoint_auth_methods_supported"] = methods
        metadata["revocation_endpoint_auth_methods_supported"] = methods
        # Do not advertise RFC 9207 support: SDK error redirects do not carry iss.
        return metadata

    def _redirect_allowed(self, value: str) -> bool:
        url = urlsplit(value)
        if url.username or url.password or url.fragment or url.query:
            return False
        try:
            port = url.port
        except ValueError:
            return False
        if (
            self.allow_loopback
            and url.scheme == "http"
            and url.hostname in {"127.0.0.1", "localhost", "::1"}
            and url.path == "/callback"
        ):
            return True
        return bool(
            url.scheme == "https"
            and url.hostname in {"chatgpt.com", "chat.openai.com"}
            and port in {None, 443}
            and (url.path == "/connector_platform_oauth_redirect" or _CALLBACK.fullmatch(url.path))
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if not isinstance(client_id, str) or len(client_id) > 256:
            return None
        with self._db() as db:
            row = db.execute("SELECT payload FROM clients WHERE id=?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row[0]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        redirects = client_info.redirect_uris or []
        serialized = client_info.model_dump_json()
        if (
            not client_info.client_id
            or len(client_info.client_id) > 256
            or not 1 <= len(redirects) <= 8
            or any(not self._redirect_allowed(str(uri)) for uri in redirects)
        ):
            raise RegistrationError("invalid_redirect_uri", "Only the configured ChatGPT OAuth callbacks are allowed")
        if (
            len(serialized.encode()) > MAX_AUTH_BODY
            or client_info.token_endpoint_auth_method not in {"none", "client_secret_post", "client_secret_basic"}
            or set(client_info.grant_types) != {"authorization_code", "refresh_token"}
            or client_info.response_types != ["code"]
            or not set((client_info.scope or "").split()).issubset(SCOPES)
        ):
            raise RegistrationError("invalid_client_metadata", "Unsupported OAuth client metadata")
        with self._db() as db:
            self._cleanup(db)
            if db.execute("SELECT COUNT(*) FROM clients").fetchone()[0] >= MAX_CLIENTS:
                raise RegistrationError("invalid_client_metadata", "Registration capacity reached")
            try:
                db.execute("INSERT INTO clients VALUES (?,?,?,NULL)", (client_info.client_id, serialized, time.time()))
            except sqlite3.IntegrityError as exc:
                raise RegistrationError("invalid_client_metadata", "Client already registered") from exc

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        registered = await self.get_client(client.client_id or "")
        if (
            not registered
            or params.redirect_uri not in (registered.redirect_uris or [])
            or not self._redirect_allowed(str(params.redirect_uri))
        ):
            raise AuthorizeError("unauthorized_client", "Client or callback not allowed")
        if params.resource != self.resource_url:
            raise AuthorizeError("invalid_request", "The resource must identify this MCP server")
        scopes = params.scopes if params.scopes is not None else SCOPES
        if not scopes or not set(scopes).issubset(SCOPES):
            raise AuthorizeError("invalid_scope", "Unsupported Editor Ultra scope")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge):
            raise AuthorizeError("invalid_request", "A SHA-256 PKCE challenge is required")
        if params.state is not None and len(params.state) > 2048:
            raise AuthorizeError("invalid_request", "State is too long")
        nonce = secrets.token_urlsafe(32)
        payload = params.model_dump(mode="json")
        payload["scopes"] = scopes
        with self._db() as db:
            self._cleanup(db)
            if db.execute("SELECT COUNT(*) FROM pending").fetchone()[0] >= MAX_PENDING:
                raise AuthorizeError("temporarily_unavailable", "Too many pending requests")
            db.execute(
                "INSERT INTO pending(digest,client_id,payload,expires) VALUES (?,?,?,?)",
                (_hash(nonce), client.client_id, _json(payload), time.time() + CONSENT_TTL),
            )
        return self.base_url + "/owner/authorize?" + urlencode({"request": nonce})

    def routes(self) -> list[Route]:
        return [Route("/owner/authorize", self.owner_authorize, methods=["GET", "POST"])]

    @staticmethod
    def _message(message: str, status: int = 400) -> HTMLResponse:
        return HTMLResponse(
            "<!doctype html><html lang=pt-BR><meta charset=utf-8>"
            "<title>Editor Ultra</title><h1>Conexão do Editor Ultra</h1><p>"
            + html.escape(message) + "</p></html>", status_code=status, headers=_HEADERS,
        )

    async def owner_authorize(self, request: Request) -> Response:
        if request.method == "GET":
            nonce = request.query_params.get("request", "")
            if not _SAFE_TOKEN.fullmatch(nonce):
                return self._message("Pedido de conexão inválido.")
            csrf = secrets.token_urlsafe(32)
            with self._db() as db:
                row = db.execute("SELECT * FROM pending WHERE digest=?", (_hash(nonce),)).fetchone()
                if not row or row["expires"] < time.time() or row["attempts"] >= 5:
                    return self._message("Este pedido expirou. Reinicie a conexão no ChatGPT.", 410)
                db.execute("UPDATE pending SET csrf_digest=? WHERE digest=?", (_hash(csrf), _hash(nonce)))
                client = db.execute("SELECT payload FROM clients WHERE id=?", (row["client_id"],)).fetchone()
            client_name = json.loads(client[0]).get("client_name") or "ChatGPT" if client else "ChatGPT"
            response = HTMLResponse(
                "<!doctype html><html lang=pt-BR><meta charset=utf-8>"
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                "<title>Conectar Editor Ultra</title><style>"
                "body{font:16px system-ui,sans-serif;background:#f7f7f5;color:#1e2424;margin:0;padding:32px 20px}"
                "main{max-width:460px;margin:8vh auto;background:white;padding:28px;border:1px solid #ddd;border-radius:18px}"
                "h1{font-size:26px}label,input,button{display:block}input[type=password]{box-sizing:border-box;width:100%;"
                "padding:12px;margin:10px 0 18px;border:1px solid #999;border-radius:8px;font:inherit}"
                "button{padding:12px 18px;background:#155c50;color:white;border:0;border-radius:8px;font:inherit;margin-top:20px}"
                "label.confirm{display:flex;gap:10px}p{line-height:1.55}.small{font-size:13px;color:#536060}"
                "</style><main><p class=small>EDITOR ULTRA · CONEXÃO PRIVADA</p><h1>Conectar ao ChatGPT</h1>"
                "<p>Autorize <strong>" + html.escape(str(client_name)[:120]) + "</strong> a consultar seus projetos, "
                "receber arquivos, preparar edições e executar os renders solicitados.</p>"
                '<form method="post" action="/owner/authorize">'
                '<input type="hidden" name="request" value="' + html.escape(nonce, quote=True) + '">'
                '<input type="hidden" name="csrf" value="' + html.escape(csrf, quote=True) + '">'
                '<label for="owner-key">Chave privada do proprietário</label>'
                '<input id="owner-key" name="owner_key" type="password" required minlength="32" maxlength="512" '
                'autocomplete="current-password">'
                '<label class="confirm"><input type="checkbox" name="confirm" value="yes" required>'
                '<span>Autorizo esta conexão ao meu Editor Ultra.</span></label>'
                '<button type="submit">Autorizar conexão</button></form>'
                '<p class=small>A chave é usada somente nesta página de autorização. Ela não é enviada ao ChatGPT.</p>'
                "</main></html>", headers=_HEADERS,
            )
            response.set_cookie(
                self._cookie_name, csrf, max_age=CONSENT_TTL, path="/owner/authorize",
                secure=self._secure_cookie, httponly=True, samesite="strict",
            )
            return response

        if request.headers.get("origin") not in {None, self.base_url} or request.headers.get("sec-fetch-site") == "cross-site":
            return self._message("Origem do pedido não autorizada.", 403)
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
            return self._message("Formato de pedido inválido.", 415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_AUTH_BODY:
                return self._message("Pedido excede o limite.", 413)
        try:
            fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=8)
        except (ValueError, UnicodeDecodeError):
            return self._message("Pedido inválido.")
        if any(len(value) != 1 for value in fields.values()):
            return self._message("Campos duplicados não são aceitos.")
        get = lambda key: fields.get(key, [""])[0]
        nonce, csrf, key = get("request"), get("csrf"), get("owner_key")
        if not _SAFE_TOKEN.fullmatch(nonce) or not _SAFE_TOKEN.fullmatch(csrf):
            return self._message("Pedido de conexão inválido.", 403)
        cookie = request.cookies.get(self._cookie_name, "")
        if not hmac.compare_digest(_hash(cookie), _hash(csrf)):
            return self._message("Confirmação de segurança inválida. Reinicie a conexão.", 403)
        with self._db() as db:
            row = db.execute("SELECT * FROM pending WHERE digest=?", (_hash(nonce),)).fetchone()
            if not row or row["expires"] < time.time() or row["attempts"] >= 5:
                return self._message("Este pedido expirou. Reinicie a conexão no ChatGPT.", 410)
            if not row["csrf_digest"] or not hmac.compare_digest(row["csrf_digest"], _hash(csrf)):
                return self._message("Confirmação de segurança inválida.", 403)
            if not 32 <= len(key) <= 512 or not hmac.compare_digest(_hash(key), self._key_hash) or get("confirm") != "yes":
                db.execute("UPDATE pending SET attempts=attempts+1 WHERE digest=?", (_hash(nonce),))
                return self._message("Chave ou confirmação inválida. Volte e tente novamente.", 403)
            params = AuthorizationParams.model_validate_json(row["payload"])
            code = secrets.token_urlsafe(32)
            grant = AuthorizationCode(
                code=code, client_id=row["client_id"], scopes=params.scopes or SCOPES,
                expires_at=time.time() + CODE_TTL, code_challenge=params.code_challenge,
                redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=self.resource_url, subject=OWNER_SUBJECT,
            )
            db.execute(
                "INSERT INTO codes VALUES (?,?,?,?)",
                (_hash(code), grant.client_id, grant.model_dump_json(exclude={"code"}), grant.expires_at),
            )
            db.execute("DELETE FROM pending WHERE digest=?", (_hash(nonce),))
            db.execute("UPDATE clients SET authorized=? WHERE id=?", (time.time(), grant.client_id))
        query: dict[str, str] = {"code": code, "iss": self.issuer_url}
        if params.state is not None:
            query["state"] = params.state
        response = RedirectResponse(str(params.redirect_uri) + "?" + urlencode(query), status_code=303, headers=_HEADERS)
        response.delete_cookie(self._cookie_name, path="/owner/authorize", secure=self._secure_cookie, httponly=True, samesite="strict")
        return response

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        if not _SAFE_TOKEN.fullmatch(authorization_code):
            return None
        with self._db() as db:
            row = db.execute("SELECT * FROM codes WHERE digest=? AND client_id=?", (_hash(authorization_code), client.client_id)).fetchone()
        if not row or row["expires"] <= time.time():
            return None
        return AuthorizationCode(code=authorization_code, **json.loads(row["payload"]))

    def _issue_tokens(self, db: sqlite3.Connection, client_id: str, scopes: list[str], family: str | None = None) -> OAuthToken:
        self._cleanup(db)
        if db.execute("SELECT COUNT(*) FROM tokens").fetchone()[0] > MAX_TOKENS - 2:
            raise TokenError("invalid_grant", "Token capacity reached; revoke unused connections")
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        family = family or secrets.token_urlsafe(24)
        now = int(time.time())
        for value, kind, ttl in ((access, "access", ACCESS_TTL), (refresh, "refresh", REFRESH_TTL)):
            db.execute(
                "INSERT INTO tokens(digest,kind,client_id,family,scopes,resource,subject,expires) VALUES (?,?,?,?,?,?,?,?)",
                (_hash(value), kind, client_id, family, _json(scopes), self.resource_url, OWNER_SUBJECT, now + ttl),
            )
        return OAuthToken(access_token=access, refresh_token=refresh, expires_in=ACCESS_TTL, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        with self._db() as db:
            row = db.execute("SELECT * FROM codes WHERE digest=? AND client_id=?", (_hash(authorization_code.code), client.client_id)).fetchone()
            if not row or row["expires"] <= time.time():
                raise TokenError("invalid_grant", "Authorization code is expired or already used")
            grant = json.loads(row["payload"])
            if grant["resource"] != self.resource_url or grant["subject"] != OWNER_SUBJECT:
                raise TokenError("invalid_grant", "Invalid authorization audience")
            db.execute("DELETE FROM codes WHERE digest=?", (_hash(authorization_code.code),))
            return self._issue_tokens(db, row["client_id"], grant["scopes"])

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        if not _SAFE_TOKEN.fullmatch(refresh_token):
            return None
        with self._db() as db:
            row = db.execute("SELECT * FROM tokens WHERE digest=? AND kind='refresh' AND client_id=?", (_hash(refresh_token), client.client_id)).fetchone()
            if not row or row["expires"] <= time.time() or row["resource"] != self.resource_url:
                return None
            if row["revoked"]:
                # Reuse of a rotated refresh credential revokes the whole grant family.
                db.execute("UPDATE tokens SET revoked=1 WHERE family=?", (row["family"],))
                return None
        return RefreshToken(token=refresh_token, client_id=row["client_id"], scopes=json.loads(row["scopes"]), expires_at=row["expires"], subject=OWNER_SUBJECT)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        with self._db() as db:
            row = db.execute("SELECT * FROM tokens WHERE digest=? AND kind='refresh' AND client_id=?", (_hash(refresh_token.token), client.client_id)).fetchone()
            if not row or row["expires"] <= time.time() or row["revoked"] or row["resource"] != self.resource_url:
                raise TokenError("invalid_grant", "Refresh token expired or already used")
            if not scopes or not set(scopes).issubset(json.loads(row["scopes"])):
                raise TokenError("invalid_scope", "Refresh cannot increase permissions")
            db.execute("UPDATE tokens SET revoked=1 WHERE family=?", (row["family"],))
            return self._issue_tokens(db, row["client_id"], scopes, family=row["family"])

    async def load_access_token(self, token: str) -> AccessToken | None:
        if not _SAFE_TOKEN.fullmatch(token):
            return None
        with self._db() as db:
            row = db.execute("SELECT * FROM tokens WHERE digest=? AND kind='access'", (_hash(token),)).fetchone()
        if not row or row["revoked"] or row["expires"] <= time.time() or row["resource"] != self.resource_url or row["subject"] != OWNER_SUBJECT:
            return None
        return AccessToken(token=token, client_id=row["client_id"], scopes=json.loads(row["scopes"]), expires_at=row["expires"], resource=self.resource_url, subject=OWNER_SUBJECT, claims={"iss": self.issuer_url})

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self._db() as db:
            row = db.execute("SELECT family FROM tokens WHERE digest=?", (_hash(token.token),)).fetchone()
            if row:
                db.execute("UPDATE tokens SET revoked=1 WHERE family=?", (row["family"],))


class OwnerAuthGuard:
    """Required outer ASGI middleware: OAuth audience, body caps and public limits."""

    PATHS = {"/authorize", "/token", "/register", "/revoke", "/owner/authorize"}

    def __init__(self, app: Any, provider: OwnerOAuthProvider) -> None:
        self.app, self.provider = app, provider

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and scope.get("path") == "/.well-known/oauth-authorization-server":
            headers = {**_HEADERS, "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS"}
            if scope["method"] == "OPTIONS":
                return await Response(status_code=204, headers=headers)(scope, receive, send)
            if scope["method"] == "GET":
                return await JSONResponse(self.provider.authorization_metadata(), headers=headers)(scope, receive, send)
        if scope["type"] != "http" or scope.get("path") not in self.PATHS:
            return await self.app(scope, receive, send)
        path, method = scope["path"], scope["method"]
        if method == "OPTIONS":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if len(scope.get("query_string", b"")) > 8192:
            return await JSONResponse({"error": "invalid_request"}, 413, headers=_HEADERS)(scope, receive, send)
        limit, period = (64, 86400) if path == "/register" else (300, 300)
        if not self.provider.rate_allowed("global:" + path, limit, period):
            return await JSONResponse({"error": "temporarily_unavailable"}, 429, headers={**_HEADERS, "Retry-After": "300"})(scope, receive, send)
        address = (scope.get("client") or ("unknown",))[0]
        per_limit, per_period = ((8, 3600) if path == "/register" else (10, 300) if path == "/owner/authorize" and method == "POST" else (60, 60))
        if not self.provider.rate_allowed("ip:" + path + ":" + method + ":" + _hash(str(address)), per_limit, per_period):
            return await JSONResponse({"error": "temporarily_unavailable"}, 429, headers={**_HEADERS, "Retry-After": "300"})(scope, receive, send)
        body = bytearray()
        if method == "POST":
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_AUTH_BODY:
                    return await JSONResponse({"error": "invalid_request"}, 413, headers=_HEADERS)(scope, receive, send)
                if not message.get("more_body", False):
                    break
        if path == "/token" and method == "POST":
            try:
                if headers.get("content-type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
                    raise ValueError("invalid token format")
                fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
                if any(len(v) != 1 for v in fields.values()) or fields.get("resource") != [self.provider.resource_url]:
                    raise ValueError("invalid token audience")
            except (ValueError, UnicodeDecodeError):
                return await JSONResponse({"error": "invalid_request", "error_description": "A single matching MCP resource is required"}, 400, headers=_HEADERS)(scope, receive, send)
        if path == "/revoke" and method == "POST":
            try:
                if headers.get("content-type", "").split(";")[0].strip() != "application/x-www-form-urlencoded":
                    raise ValueError("invalid revocation format")
                fields = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=20)
                if any(len(v) != 1 for v in fields.values()):
                    raise ValueError("duplicate fields")
                # MCP SDK 1.29 marks this optional value as required in the
                # revocation form. An empty value preserves its client-auth
                # checks while allowing standard public-client revocation.
                if "client_secret" not in fields:
                    body.extend(b"&client_secret=")
            except (ValueError, UnicodeDecodeError):
                return await JSONResponse({"error": "invalid_request"}, 400, headers=_HEADERS)(scope, receive, send)
        sent = False

        async def replay() -> dict[str, Any]:
            nonlocal sent
            if method == "POST" and not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
