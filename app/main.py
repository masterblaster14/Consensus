"""FastAPI application: lifespan, router mounting, MCP mount."""
from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, board, claims, clashes, devpages, keys, memory, orgs, projects, stream, webhooks
from app.config import get_settings
from app.db.session import CommittingRoute, dispose_engine, get_engine
from app.events.bus import get_bus
from app.mcp.auth import MCPAuthMiddleware
from app.mcp.server import build_mcp_app, mcp_server
from starlette.routing import Route

log = logging.getLogger("consensus")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bus = get_bus()
    await bus.start()
    # The MCP streamable-HTTP transport needs its session manager running for
    # the lifetime of the process. Mounting a sub-app does not run its lifespan,
    # so we drive it from here.
    async with mcp_server.session_manager.run():
        log.info("consensus ready (github=%s notion=%s)", settings.github_enabled, settings.notion_enabled)
        try:
            yield
        finally:
            await bus.stop()
            await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Consensus",
        version="0.1.0",
        description="Coordination service for AI coding agents.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/", tags=["ops"], include_in_schema=False)
    async def root() -> dict:
        return {
            "service": "consensus",
            "health": "/health",
            "api_docs": "/docs",
            "board": "/board?token=<api key or session token>&project=<project id>",
            "mcp": "/mcp  (POST, Authorization: Bearer <api key>)",
            "websocket": "/ws/projects/{project_id}?token=<token>",
        }

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        db_ok = redis_ok = False
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # pragma: no cover
            log.exception("health: database check failed")
        try:
            redis_ok = bool(await get_bus().redis.ping())
        except Exception:  # pragma: no cover
            log.exception("health: redis check failed")
        return {"status": "ok" if (db_ok and redis_ok) else "degraded", "database": db_ok, "redis": redis_ok}

    app.include_router(auth.router)
    app.include_router(orgs.router)
    app.include_router(keys.router)
    app.include_router(projects.router)
    app.include_router(claims.router)
    app.include_router(memory.router)
    app.include_router(clashes.router)
    app.include_router(webhooks.router)
    app.include_router(stream.router)
    app.include_router(devpages.router)
    app.include_router(board.router)

    # Agent-facing MCP endpoint: POST/GET/DELETE http://host:port/mcp
    # The transport route is added directly (not mounted) so /mcp needs no trailing-slash redirect.
    for route in build_mcp_app().routes:
        if isinstance(route, Route) and route.path == "/mcp":
            route = Route(route.path, endpoint=MCPAuthMiddleware(route.endpoint), methods=route.methods)
        app.router.routes.append(route)
    return app


app = create_app()
