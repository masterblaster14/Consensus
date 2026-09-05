"""Bearer auth for the MCP endpoint.

Agents send `Authorization: Bearer csk_...` (a per-user API key from
POST /api/me/api-keys). The resolved Principal is placed in a contextvar for
the duration of the request so the tools know who is calling, which org they
belong to, and which project the key defaults to.

With MCP_AUTH_REQUIRED=false an unauthenticated call is allowed through with no
principal (pre-auth behaviour, dev only).
"""
from __future__ import annotations

import json
import logging

import time

from app.config import get_settings
from app.core.auth import AuthError, Principal, current_principal, principal_from_bearer, sha256
from app.db.session import session_scope

log = logging.getLogger(__name__)

# The MCP session manager runs tool calls in its own task group, so a contextvar set
# here does not reach the tool. The middleware therefore only gates the request; each
# tool re-binds the principal from its request headers via `bind_principal`, using
# this short-lived cache so the DB is not hit twice per call.
_CACHE_TTL = 30.0
_cache: dict[str, tuple[float, Principal]] = {}


async def resolve_token(token: str) -> Principal:
    key = sha256(token)
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    async with session_scope() as db:
        principal = await principal_from_bearer(db, token)
    _cache[key] = (now + _CACHE_TTL, principal)
    if len(_cache) > 5000:
        for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
    return principal


def invalidate_token_cache() -> None:
    _cache.clear()


def _token_from_headers(headers) -> str | None:
    if not headers:
        return None
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    return auth[7:].strip() if auth.lower().startswith("bearer ") else None


async def bind_principal(ctx) -> Principal | None:
    """Call at the top of every tool. Sets `current_principal` for this task."""
    token = _token_from_headers(getattr(ctx, "headers", None))
    principal = await resolve_token(token) if token else None
    if principal is None and get_settings().mcp_auth_required:
        raise AuthError("authentication required: send Authorization: Bearer <api key>")
    current_principal.set(principal)
    return principal


class MCPAuthMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None

        principal = None
        if token:
            try:
                principal = await resolve_token(token)
            except AuthError as e:
                await _reject(send, 401, str(e))
                return
            except Exception:
                log.exception("mcp auth failed")
                await _reject(send, 500, "authentication error")
                return
        elif get_settings().mcp_auth_required:
            await _reject(send, 401, "authentication required: send Authorization: Bearer <api key>")
            return

        reset = current_principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(reset)


async def _reject(send, status: int, message: str) -> None:
    body = json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": message}}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="consensus"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
