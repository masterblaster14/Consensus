"""WS /ws/projects/{id}  -> every event for the project as JSON frames.

Frame shape:
    {"id": "...", "type": "clash.opened", "project_id": "...", "ts": "...", "data": {...}}

The first frame after connect is {"type": "hello", ...} carrying a snapshot of
counters so a dashboard can paint immediately. Clients may send "ping" and
receive {"type": "pong"}.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import _bearer_from
from app.config import get_settings
from app.core import memory as memory_core
from app.core.auth import AuthError, principal_from_bearer
from app.db.models import Project
from app.db.session import session_scope
from app.events.bus import dumps, get_bus

log = logging.getLogger(__name__)
router = APIRouter(tags=["stream"])


@router.websocket("/ws/projects/{project_id}")
async def project_stream(websocket: WebSocket, project_id: uuid.UUID) -> None:
    settings = get_settings()
    async with session_scope() as db:
        project = await db.get(Project, project_id)
        if project is None:
            await websocket.close(code=4004, reason="project not found")
            return
        # Auth: Authorization header or ?token= (JWT or API key). Browsers cannot set headers on WS.
        token = _bearer_from(websocket)
        if token:
            try:
                principal = await principal_from_bearer(db, token)
            except AuthError:
                await websocket.close(code=4001, reason="invalid token")
                return
            if project.org_id is not None and not principal.is_member(project.org_id):
                await websocket.close(code=4003, reason="not a member")
                return
            if project.org_id is None and not settings.dev_auth:
                await websocket.close(code=4003, reason="project has no organisation")
                return
        elif settings.mcp_auth_required:
            await websocket.close(code=4001, reason="authentication required")
            return
        snapshot = (await memory_core.counters(db, project_id)).model_dump()

    await websocket.accept()
    bus = get_bus()
    q = bus.subscribe(project_id)
    hello = bus.make_frame(project_id, "hello", {"counters": snapshot})
    hello["type"] = "hello"
    await websocket.send_text(dumps(hello))

    async def _pump_events() -> None:
        while True:
            payload = await q.get()
            await websocket.send_text(payload)

    async def _read_client() -> None:
        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() == "ping":
                await websocket.send_text(dumps(bus.make_frame(project_id, "pong", {})))

    pump = asyncio.create_task(_pump_events())
    reader = asyncio.create_task(_read_client())
    try:
        done, pending = await asyncio.wait({pump, reader}, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                log.debug("websocket task ended: %r", exc)
    finally:
        for t in (pump, reader):
            t.cancel()
            with contextlib.suppress(BaseException):
                await t
        bus.unsubscribe(project_id, q)
