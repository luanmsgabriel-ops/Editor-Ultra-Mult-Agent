"""Protocol tests exercise the actual SDK handlers and durable owner provider."""

import asyncio
import base64
import hashlib
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.provider import TokenError
from starlette.applications import Starlette
from starlette.testclient import TestClient

from editor_ultra_app.auth import OwnerAuthGuard, OwnerOAuthProvider


BASE = "https://editor.example"
KEY = "test-owner-key-for-protocol-tests-only-0123456789"
REDIRECT = "https://chatgpt.com/connector/oauth/test_callback_1234"
VERIFIER = "V" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def app_client(tmp_path):
    provider = OwnerOAuthProvider(tmp_path, BASE, KEY)
    settings = provider.auth_settings()
    app = Starlette(routes=create_auth_routes(
        provider, settings.issuer_url,
        client_registration_options=settings.client_registration_options,
        revocation_options=settings.revocation_options,
    ) + provider.routes())
    app.add_middleware(OwnerAuthGuard, provider=provider)
    with TestClient(app, base_url=BASE) as client:
        yield provider, client


def register(client, redirect=REDIRECT):
    response = client.post("/register", json={
        "redirect_uris": [redirect], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
        "client_name": "ChatGPT", "scope": "editor:read editor:write",
    })
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


def pending(client, client_id, **overrides):
    params = {
        "response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT,
        "code_challenge": CHALLENGE, "code_challenge_method": "S256",
        "scope": "editor:read editor:write", "state": "kept-state",
        "resource": BASE + "/mcp",
    }
    params.update(overrides)
    response = client.get("/authorize", params=params, follow_redirects=False)
    assert response.status_code == 302
    return response.headers["location"]


def consent(client, location, **overrides):
    page = client.get(location)
    assert page.status_code == 200, page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    nonce = parse_qs(urlsplit(location).query)["request"][0]
    fields = {"request": nonce, "csrf": csrf, "owner_key": KEY, "confirm": "yes"}
    fields.update(overrides)
    return client.post("/owner/authorize", data=fields, headers={"origin": BASE}, follow_redirects=False)


def code(client, client_id):
    response = consent(client, pending(client, client_id))
    assert response.status_code == 303, response.text
    params = parse_qs(urlsplit(response.headers["location"]).query)
    assert params["state"] == ["kept-state"]
    assert params["iss"] == [BASE + "/"]
    return params["code"][0]


def exchange(client, client_id, auth_code, **overrides):
    fields = {
        "grant_type": "authorization_code", "client_id": client_id,
        "code": auth_code, "code_verifier": VERIFIER,
        "redirect_uri": REDIRECT, "resource": BASE + "/mcp",
    }
    fields.update(overrides)
    return client.post("/token", data=fields)


def refresh(client, client_id, token, **overrides):
    fields = {"grant_type": "refresh_token", "client_id": client_id,
              "refresh_token": token, "resource": BASE + "/mcp"}
    fields.update(overrides)
    return client.post("/token", data=fields)


def test_real_sdk_pkce_consent_and_persistent_tokens(app_client, tmp_path):
    provider, client = app_client
    client_id = register(client)
    auth_code = code(client, client_id)
    assert exchange(client, client_id, auth_code, code_verifier="wrong").status_code == 400
    issued = exchange(client, client_id, auth_code)
    assert issued.status_code == 200, issued.text
    credentials = issued.json()
    assert exchange(client, client_id, auth_code).status_code == 400
    token = run(provider.load_access_token(credentials["access_token"]))
    assert token.resource == BASE + "/mcp" and token.subject == "owner"
    restarted = OwnerOAuthProvider(tmp_path, BASE, KEY)
    assert run(restarted.load_access_token(credentials["access_token"])) is not None
    stored = provider.db_path.read_bytes()
    assert KEY.encode() not in stored
    assert credentials["access_token"].encode() not in stored
    assert credentials["refresh_token"].encode() not in stored
    assert auth_code.encode() not in stored


@pytest.mark.parametrize("redirect", [
    "https://evil.example/callback", "https://chatgpt.com.evil.example/connector_platform_oauth_redirect",
    "https://chatgpt.com/other", "https://chatgpt.com/connector/oauth/test_callback_1234?next=https://evil.example",
    "http://chatgpt.com/connector_platform_oauth_redirect", "http://127.0.0.1:1234/callback",
    "https://chatgpt.com:444/connector_platform_oauth_redirect", "https://user@chatgpt.com/connector_platform_oauth_redirect",
])
def test_registration_rejects_untrusted_redirect(app_client, redirect):
    _, client = app_client
    response = client.post("/register", json={"redirect_uris": [redirect], "token_endpoint_auth_method": "none"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_resource_checks_at_authorize_and_token(app_client):
    _, client = app_client
    client_id = register(client)
    refused = pending(client, client_id, resource="https://other.example/mcp")
    assert parse_qs(urlsplit(refused).query)["error"] == ["invalid_request"]
    auth_code = code(client, client_id)
    assert exchange(client, client_id, auth_code, resource="https://other.example/mcp").status_code == 400
    assert exchange(client, client_id, auth_code, resource="").status_code == 400
    assert exchange(client, client_id, auth_code).status_code == 200


def test_owner_key_explicit_consent_and_csrf_are_required(app_client):
    _, client = app_client
    client_id = register(client)
    location = pending(client, client_id)
    response = consent(client, location, owner_key="incorrect-owner-key-" * 3)
    assert response.status_code == 403 and "location" not in response.headers
    assert consent(client, location, confirm="").status_code == 403
    page = client.get(location)
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    nonce = parse_qs(urlsplit(location).query)["request"][0]
    fields = {"request": nonce, "csrf": csrf, "owner_key": KEY, "confirm": "yes"}
    assert client.post("/owner/authorize", data=fields, headers={"origin": "https://evil.example"}).status_code == 403
    client.cookies.clear()
    assert client.post("/owner/authorize", data=fields, headers={"origin": BASE}).status_code == 403
    assert consent(client, location).status_code == 303
    assert client.get(location).status_code == 410


def test_native_consent_form_preserves_origin_without_leaking_callback_referrer(app_client):
    _, client = app_client
    client_id = register(client)
    location = pending(client, client_id)
    page = client.get(location)
    # Native form POSTs send Origin:null under no-referrer (Fetch Standard).
    # TestClient does not implement browser referrer policy, so check the
    # served policy as well as the HTTP exchange instead of only forcing Origin.
    assert page.headers["referrer-policy"] == "same-origin"
    assert "form-action 'self' https://chatgpt.com;" in page.headers["content-security-policy"]
    assert '<form method="post" action="/owner/authorize">' in page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    nonce = parse_qs(urlsplit(location).query)["request"][0]
    response = client.post("/owner/authorize", data={
        "request": nonce, "csrf": csrf, "owner_key": KEY, "confirm": "yes",
    }, headers={"origin": BASE, "sec-fetch-site": "same-origin"}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["referrer-policy"] == "no-referrer"
    assert urlsplit(response.headers["location"]).netloc == "chatgpt.com"
    auth_code = parse_qs(urlsplit(response.headers["location"]).query)["code"][0]
    assert exchange(client, client_id, auth_code).status_code == 200


@pytest.mark.parametrize("redirect", [
    REDIRECT, "https://chat.openai.com/connector_platform_oauth_redirect",
])
def test_consent_form_csp_allows_only_its_registered_callback_origin(app_client, redirect):
    _, client = app_client
    client_id = register(client, redirect=redirect)
    location = pending(client, client_id, redirect_uri=redirect)
    # Extra GET parameters must not alter the persisted callback or CSP.
    page = client.get(location + "&redirect_uri=https://evil.example/callback")
    directives = {parts[0]: parts[1:] for item in page.headers["content-security-policy"].split(";")
                  if (parts := item.strip().split())}
    callback = urlsplit(redirect)
    assert directives["form-action"] == ["'self'", f"{callback.scheme}://{callback.netloc}"]
    assert directives["default-src"] == ["'none'"]
    assert directives["base-uri"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert '<form method="post" action="/owner/authorize">' in page.text


@pytest.mark.parametrize("headers", [
    {"origin": "null", "sec-fetch-site": "same-origin"},
    {"origin": "https://evil.example", "sec-fetch-site": "same-origin"},
    {"origin": BASE, "sec-fetch-site": "cross-site"},
])
def test_native_consent_still_rejects_untrusted_origins_with_valid_csrf(app_client, headers):
    _, client = app_client
    client_id = register(client)
    location = pending(client, client_id)
    page = client.get(location)
    fields = {
        "request": parse_qs(urlsplit(location).query)["request"][0],
        "csrf": re.search(r'name="csrf" value="([^"]+)"', page.text).group(1),
        "owner_key": KEY, "confirm": "yes",
    }
    response = client.post("/owner/authorize", data=fields, headers=headers, follow_redirects=False)
    assert response.status_code == 403
    assert "Origem do pedido não autorizada." in response.text
    assert "location" not in response.headers
    assert response.headers["referrer-policy"] == "no-referrer"


def test_expired_consent_and_authorization_code_fail(app_client):
    provider, client = app_client
    client_id = register(client)
    location = pending(client, client_id)
    with provider._db() as db:
        db.execute("UPDATE pending SET expires=0")
    assert client.get(location).status_code == 410
    auth_code = code(client, client_id)
    with provider._db() as db:
        db.execute("UPDATE codes SET expires=0")
    assert exchange(client, client_id, auth_code).status_code == 400


def test_cross_client_and_scope_escalation_fail(app_client):
    provider, client = app_client
    first, second = register(client), register(client)
    auth_code = code(client, first)
    assert exchange(client, second, auth_code).status_code == 400
    initial = exchange(client, first, auth_code).json()
    assert refresh(client, second, initial["refresh_token"]).status_code == 400
    assert refresh(client, first, initial["refresh_token"], scope="editor:admin").status_code == 400
    assert run(provider.load_access_token(initial["access_token"])) is not None


def test_refresh_rotation_replay_revocation_and_key_rotation(app_client, tmp_path):
    provider, client = app_client
    client_id = register(client)
    initial = exchange(client, client_id, code(client, client_id)).json()
    renewed = refresh(client, client_id, initial["refresh_token"])
    assert renewed.status_code == 200
    current = renewed.json()
    assert run(provider.load_access_token(initial["access_token"])) is None
    assert run(provider.load_access_token(current["access_token"])) is not None
    assert refresh(client, client_id, initial["refresh_token"]).status_code == 400
    assert run(provider.load_access_token(current["access_token"])) is None
    next_credentials = exchange(client, client_id, code(client, client_id)).json()
    rotated = OwnerOAuthProvider(tmp_path, BASE, "a-new-random-owner-key-" * 3)
    assert run(rotated.load_access_token(next_credentials["access_token"])) is None


def test_code_exchange_is_atomic_across_workers(app_client):
    provider, client = app_client
    client_id = register(client)
    auth_code = code(client, client_id)
    client_info = run(provider.get_client(client_id))
    grant = run(provider.load_authorization_code(client_info, auth_code))

    def attempt(_):
        try:
            return run(provider.exchange_authorization_code(client_info, grant))
        except TokenError:
            return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(4)))
    assert len([result for result in results if result]) == 1


def test_login_body_cap_and_attempt_cap(app_client):
    _, client = app_client
    response = client.post("/owner/authorize", content=b"x" * 20000, headers={"content-type": "application/x-www-form-urlencoded"})
    assert response.status_code == 413
    client_id = register(client)
    location = pending(client, client_id)
    for _ in range(5):
        assert consent(client, location, owner_key="wrong" * 10).status_code == 403
    assert client.get(location).status_code == 410


def test_startup_fail_closed_without_key_or_https(tmp_path):
    with pytest.raises(ValueError):
        OwnerOAuthProvider(tmp_path, BASE, "")
    with pytest.raises(ValueError):
        OwnerOAuthProvider(tmp_path, "http://editor.example", KEY)
    with pytest.raises(ValueError):
        OwnerOAuthProvider(tmp_path, "https://editor.example/mcp", KEY)
    provider = OwnerOAuthProvider(tmp_path, "http://127.0.0.1:8000", KEY, allow_loopback=True)
    assert provider._redirect_allowed("http://127.0.0.1:8080/callback")


def test_fastmcp_discovery_and_authenticated_transport(tmp_path):
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings

    provider = OwnerOAuthProvider(tmp_path, BASE, KEY)
    mcp = FastMCP(
        "auth-integration-test", auth_server_provider=provider, auth=provider.auth_settings(),
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["editor.example"], allowed_origins=[BASE],
        ),
    )

    @mcp.tool()
    def owner_only() -> str:
        return "authorized"

    app = mcp.streamable_http_app()
    app.routes.extend(provider.routes())
    app.add_middleware(OwnerAuthGuard, provider=provider)
    with TestClient(app, base_url=BASE) as client:
        challenge = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert challenge.status_code == 401
        metadata_url = re.search(r'resource_metadata="([^"]+)"', challenge.headers["www-authenticate"]).group(1)
        resource = client.get(metadata_url).json()
        assert resource["resource"] == BASE + "/mcp"
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        assert metadata["issuer"] == resource["authorization_servers"][0] == BASE + "/"
        assert metadata["code_challenge_methods_supported"] == ["S256"]
        assert "none" in metadata["token_endpoint_auth_methods_supported"]
        client_id = register(client)
        issued = exchange(client, client_id, code(client, client_id)).json()
        response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "owner_only", "arguments": {}}}, headers={
            "Authorization": "Bearer " + issued["access_token"],
            "Accept": "application/json, text/event-stream",
        })
        assert response.status_code == 200, response.text
        assert response.json()["result"]["content"][0]["text"] == "authorized"
        from scripts.check_app_connection import authorize_owner
        with authorize_owner(BASE, KEY, client=client) as connection:
            private_token = connection.access_token
            assert private_token not in repr(connection)
            assert connection.call_tool("owner_only", {})["content"][0]["text"] == "authorized"
        assert run(provider.load_access_token(private_token)) is None
