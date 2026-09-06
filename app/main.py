"""FastAPI application: lifespan, router mounting, MCP mount."""
from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import auth, board, claims, clashes, devpages, keys, memory, orgs, projects, stream, webhooks
from app.config import get_settings
from app.db.session import CommittingRoute, dispose_engine, get_engine
from app.events.bus import get_bus
from app.mcp.auth import MCPAuthMiddleware
from app.mcp.server import build_mcp_app, mcp_server
from app.core.scheduler import start_background_tasks, stop_background_tasks
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
        background = start_background_tasks()
        log.info("consensus ready (github=%s notion=%s)", settings.github_enabled, settings.notion_enabled)
        try:
            yield
        finally:
            await stop_background_tasks(background)
            await bus.stop()
            await dispose_engine()


def frontend_dir() -> Path | None:
    """The built frontend, when the deployment carries one (Dockerfile builds frontend/ if present)."""
    p = Path(get_settings().frontend_dist).expanduser()
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    return p if (p / "index.html").is_file() else None


def create_app() -> FastAPI:
    settings = get_settings()
    frontend = frontend_dir()
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
    async def root() -> dict:  # replaced by the SPA when a frontend build is present
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
    if frontend is None:
        app.include_router(devpages.router)  # placeholder pages until the real frontend is built in
    app.include_router(board.router)

    # Agent-facing MCP endpoint: POST/GET/DELETE http://host:port/mcp
    # The transport route is added directly (not mounted) so /mcp needs no trailing-slash redirect.
    for route in build_mcp_app().routes:
        if isinstance(route, Route) and route.path == "/mcp":
            route = Route(route.path, endpoint=MCPAuthMiddleware(route.endpoint), methods=route.methods)
        app.router.routes.append(route)

    # Every route takes `Authorization: Bearer <session JWT or csk_ API key>` through its own
    # dependency, which FastAPI cannot see. Declare the scheme so /docs shows an Authorize button
    # and sends the header; runtime authentication is unchanged.
    def openapi_with_bearer() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
        schema.setdefault("components", {}).setdefault("securitySchemes", {})["bearerAuth"] = {
            "type": "http",
            "scheme": "bearer",
            "description": "Session token from sign-in (GitHub / magic link / dev login) or a csk_ API key.",
        }
        schema["security"] = [{"bearerAuth": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = openapi_with_bearer  # type: ignore[method-assign]

    if frontend is not None:
        # Same-origin frontend: hashed assets as static files, every other unknown path -> index.html
        # so client-side routes (/app/dashboard, /invite/<token>, /auth/callback) work on refresh.
        # API, MCP, WebSocket, docs and board routes are registered above and take precedence.
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]
        if (frontend / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")
        index = frontend / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            candidate = (frontend / path).resolve() if path else index
            if path and candidate.is_file() and str(candidate).startswith(str(frontend.resolve())):
                return FileResponse(candidate)
            # The shell must never be cached: it names hashed assets that change on every deploy,
            # and a stale copy would point browsers at files that no longer exist.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})

        log.info("serving frontend from %s", frontend)
    return app


app = create_app()
