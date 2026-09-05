"""Test harness.

Runs against the real Postgres (consensus_test database) and Redis from
docker-compose, with the offline stance/embedding providers so no network or
API keys are needed. A real uvicorn server is started inside the test event
loop so REST, WebSocket and MCP-over-HTTP are all exercised end to end.

Auth: DEV_AUTH=true so tests sign in via POST /api/auth/dev-login. Every test
gets an admin user ("priya"), an organisation, a project and an API key; the
`api` client carries the admin's JWT and the `mcp` client carries the API key.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid

import httpx
import pytest
import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://consensus:consensus@localhost:5432/consensus_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ["STANCE_PROVIDER"] = "keyword"
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ["ENABLE_GITHUB"] = "false"
os.environ["ENABLE_NOTION"] = "false"
os.environ["DEFAULT_PROJECT_ID"] = ""
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["DEV_AUTH"] = "true"
os.environ["MCP_AUTH_REQUIRED"] = "true"
os.environ["SECRET_KEY"] = "test-secret-that-is-at-least-32-bytes-long!!"

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import models  # noqa: E402
from app.db.session import dispose_engine, get_engine  # noqa: E402

get_settings.cache_clear()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture(scope="session")
async def schema():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(models.Base.metadata.drop_all)
        await conn.run_sync(models.Base.metadata.create_all)
    yield
    await dispose_engine()


@pytest_asyncio.fixture(scope="session")
async def server(schema):
    """Real uvicorn server running in this event loop."""
    import uvicorn

    from app.main import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    for _ in range(100):
        if srv.started:
            break
        await asyncio.sleep(0.05)
    assert srv.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    await task


@pytest_asyncio.fixture
async def clean_db(schema):
    from app.mcp.auth import invalidate_token_cache

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE verdict_logs, token_events, clashes, memory_entries, claims, tasks, agents, "
                "api_keys, invites, memberships, magic_links, projects, organizations, users CASCADE"
            )
        )
    invalidate_token_cache()
    yield


@pytest_asyncio.fixture
async def anon(server, clean_db):
    """Unauthenticated client."""
    async with httpx.AsyncClient(base_url=server, timeout=30.0) as client:
        yield client


async def login(anon: httpx.AsyncClient, email: str, name: str) -> dict:
    r = await anon.post("/api/auth/dev-login", json={"email": email, "name": name})
    assert r.status_code == 200, r.text
    return r.json()


async def client_for(server: str, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=server, timeout=30.0, headers={"Authorization": f"Bearer {token}"})


@pytest_asyncio.fixture
async def admin(anon, server):
    """Admin user: {token, me, client}"""
    data = await login(anon, "priya@example.com", "Priya")
    client = await client_for(server, data["token"])
    yield {"token": data["token"], "me": data["me"], "client": client}
    await client.aclose()


@pytest_asyncio.fixture
async def org(admin) -> dict:
    r = await admin["client"].post("/api/orgs", json={"name": "Acme"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def api(admin, org):
    """Authenticated (admin) REST client."""
    yield admin["client"]


@pytest_asyncio.fixture
async def project(api, org) -> dict:
    r = await api.post(f"/api/orgs/{org['id']}/projects", json={"name": "Golden"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def api_key(api, org, project) -> str:
    r = await api.post("/api/me/api-keys", json={"name": "test", "org_id": org["id"], "project_id": project["id"]})
    assert r.status_code == 201, r.text
    return r.json()["key"]


class MCP:
    """Thin MCP client over streamable HTTP for calling the agent tools in tests."""

    def __init__(self, url: str, token: str | None) -> None:
        self.url = url
        self.token = token

    def _http(self, timeout: float = 300.0):
        import httpx2

        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx2.AsyncClient(timeout=httpx2.Timeout(timeout), headers=headers)

    async def call(self, name: str, **arguments) -> dict:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with self._http() as http:
            async with streamable_http_client(self.url, http_client=http) as (read, write, *_):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, arguments, read_timeout_seconds=300)
        # raise outside the context managers so the error is not wrapped in an ExceptionGroup
        if result.is_error:
            raise ToolError(result.content[0].text if result.content else "tool error")
        if result.structured_content is not None:
            sc = result.structured_content
            return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
        return json.loads(result.content[0].text)

    async def list_tools(self) -> list[str]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with self._http(30.0) as http:
            async with streamable_http_client(self.url, http_client=http) as (read, write, *_):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return [t.name for t in tools.tools]


class ToolError(Exception):
    pass


@pytest.fixture
def mcp(server, api_key) -> MCP:
    return MCP(f"{server}/mcp", api_key)


@pytest.fixture
def mcp_factory(server):
    def make(token: str | None) -> MCP:
        return MCP(f"{server}/mcp", token)

    return make
