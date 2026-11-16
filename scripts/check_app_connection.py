#!/usr/bin/env python3
"""Exercise the private MCP endpoint, without printing credentials or registering a ChatGPT plugin.

Usage:
  EDITOR_ULTRA_OWNER_KEY=... python scripts/check_app_connection.py https://...up.railway.app
  python scripts/check_app_connection.py https://...up.railway.app --key-stdin < private-key-file

For a longer integration check, import ``authorize_owner`` and use the returned
``OwnerConnection`` as a context manager. It revokes the test grant on exit.
Nothing here calls a generator or marks an edit approved.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import hashlib
import json
import os
import secrets
import sys
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx


CALLBACK = "https://chatgpt.com/connector/oauth/editor_ultra_connection_check"


class _ConsentForm(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "input" and values.get("type") == "hidden" and values.get("name") in {"request", "csrf"}:
            self.fields[str(values["name"])] = str(values.get("value") or "")


def _ok(response: Any, stage: str, expected: int = 200) -> Any:
    if response.status_code != expected:
        # A response may contain an auth code or credential. Never include its
        # body, request form or full redirect URL in a raised/logged exception.
        raise RuntimeError(f"{stage}: HTTP {response.status_code}, expected {expected}")
    return response


def _same_endpoint(url: str, base: str, path: str) -> bool:
    candidate, origin = urlsplit(url), urlsplit(base)
    return (
        candidate.scheme == origin.scheme
        and candidate.netloc == origin.netloc
        and candidate.path == path
        and candidate.username is None
        and candidate.password is None
        and not candidate.fragment
    )


@dataclass(repr=False)
class OwnerConnection:
    """A temporary protocol-test grant. Access credentials are intentionally absent from repr."""

    base_url: str
    client_id: str
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    client: Any = field(repr=False)
    owns_client: bool = field(default=True, repr=False)
    _request_id: int = field(default=0, repr=False)
    _revoked: bool = field(default=False, repr=False)

    def __repr__(self) -> str:
        return f"OwnerConnection(base_url={self.base_url!r}, authenticated={not self._revoked})"

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self.access_token,
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._request_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": self._request_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = _ok(self.client.post(self.base_url + "/mcp", json=payload, headers=self.headers), "MCP request")
        result = response.json()
        if "error" in result:
            raise RuntimeError("MCP returned a protocol error")
        return result["result"]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.rpc("tools/call", {"name": name, "arguments": arguments})

    def revoke(self) -> None:
        if self._revoked:
            return
        response = self.client.post(self.base_url + "/revoke", data={
            "client_id": self.client_id, "token": self.refresh_token, "token_type_hint": "refresh_token",
        })
        _ok(response, "Revoke test grant")
        self._revoked = True
        self.access_token = self.refresh_token = ""

    def close(self) -> None:
        try:
            self.revoke()
        finally:
            if self.owns_client:
                self.client.close()

    def __enter__(self) -> "OwnerConnection":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False


def authorize_owner(base_url: str, owner_key: str, *, client: Any = None) -> OwnerConnection:
    """Perform DCR + owner-consent + PKCE against this server only; do not visit the callback.

    ``client`` is injectable for tests. Normally an httpx.Client with normal TLS
    verification is created. The caller must close/revoke the returned grant.
    """
    base = base_url.rstrip("/")
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"https", "http"}
        or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"})
        or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path
    ):
        raise ValueError("Use the service HTTPS origin, without /mcp or credentials")
    if not 32 <= len(owner_key) <= 512:
        raise ValueError("A private owner key is required")
    owns_client = client is None
    client = client or httpx.Client(timeout=45, follow_redirects=False)
    connection = None
    try:
        metadata = _ok(client.get(base + "/.well-known/oauth-authorization-server"), "OAuth discovery").json()
        for name, path in (("registration_endpoint", "/register"), ("authorization_endpoint", "/authorize"), ("token_endpoint", "/token")):
            if not _same_endpoint(metadata.get(name, ""), base, path):
                raise RuntimeError("Unexpected OAuth endpoint in discovery")
        issuer = metadata["issuer"]
        if "S256" not in metadata.get("code_challenge_methods_supported", []):
            raise RuntimeError("Server does not advertise PKCE S256")
        registration = _ok(client.post(base + "/register", json={
            "client_name": "Editor Ultra connection check",
            "redirect_uris": [CALLBACK], "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "scope": "editor:read editor:write",
        }), "Register test client", 201).json()
        client_id = registration["client_id"]
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(32)
        authorization = _ok(client.get(base + "/authorize", params={
            "client_id": client_id, "response_type": "code", "redirect_uri": CALLBACK,
            "resource": base + "/mcp", "scope": "editor:read editor:write",
            "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        }, follow_redirects=False), "Start authorization", 302)
        consent_url = authorization.headers["location"]
        if not _same_endpoint(consent_url, base, "/owner/authorize"):
            raise RuntimeError("Unexpected consent endpoint")
        form = _ConsentForm()
        form.feed(_ok(client.get(consent_url), "Read consent form").text)
        if set(form.fields) != {"request", "csrf"}:
            raise RuntimeError("Consent form did not contain security fields")
        form.fields.update({"owner_key": owner_key, "confirm": "yes"})
        consent = _ok(client.post(base + "/owner/authorize", data=form.fields,
                                 headers={"Origin": base}, follow_redirects=False), "Authorize owner", 303)
        callback = urlsplit(consent.headers["location"])
        expected_callback = urlsplit(CALLBACK)
        if (callback.scheme, callback.netloc, callback.path, callback.fragment) != (expected_callback.scheme, expected_callback.netloc, expected_callback.path, ""):
            raise RuntimeError("Authorization callback mismatch")
        fields = parse_qs(callback.query)
        if fields.get("state") != [state] or fields.get("iss") != [issuer] or len(fields.get("code", [])) != 1:
            raise RuntimeError("Authorization state or issuer mismatch")
        tokens = _ok(client.post(base + "/token", data={
            "grant_type": "authorization_code", "client_id": client_id,
            "code": fields["code"][0], "code_verifier": verifier,
            "redirect_uri": CALLBACK, "resource": base + "/mcp",
        }), "Exchange code").json()
        connection = OwnerConnection(base, client_id, tokens["access_token"], tokens["refresh_token"], client, owns_client)
        connection.rpc("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "editor-ultra-connection-check", "version": "1.0.0"},
        })
        return connection
    except BaseException:
        if connection is not None:
            connection.close()
        elif owns_client:
            client.close()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="HTTPS origin of the private Editor Ultra service")
    parser.add_argument("--key-stdin", action="store_true", help="Read the private owner key from standard input")
    args = parser.parse_args()
    key = sys.stdin.read(513).strip() if args.key_stdin else os.environ.get("EDITOR_ULTRA_OWNER_KEY", "")
    with authorize_owner(args.base_url, key) as session:
        tools = session.rpc("tools/list")
        resources = session.rpc("resources/list")
        print(json.dumps({
            "endpoint": session.base_url + "/mcp", "oauth_pkce": "passed",
            "tools": [tool["name"] for tool in tools.get("tools", [])],
            "resources": [resource["uri"] for resource in resources.get("resources", [])],
            "chatgpt_plugin_installed": False,
        }, ensure_ascii=False, indent=2))
    print("Test grant revoked.")


if __name__ == "__main__":
    main()
