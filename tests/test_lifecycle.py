"""Claim lifecycle (withdraw, expiry, status), stance fallback, hosted-Postgres URLs."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.core import claims as claims_core
from app.db.models import Claim
from app.db.session import session_scope
from tests.conftest import client_for, login

PLAN_A = "Replace the session model with a refresh-token flow. Sessions move from server-side store to signed tokens."
PLAN_B = "Add a POST /login endpoint that creates a server-side session and returns the session id."


async def test_withdraw_releases_the_waiting_agent(anon, server, api, org, project, mcp):
    pid = project["id"]
    a = await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, project_id=pid)
    b = await mcp.call("declare_intent", agent_name="Agent B", plan_text=PLAN_B, project_id=pid)
    assert b["verdict"] == "wait"

    # a member who does not own the agent cannot withdraw it
    marcus = await login(anon, "marcus@example.com", "Marcus")
    cm = await client_for(server, marcus["token"])
    inv = (await api.post(f"/api/orgs/{org['id']}/invites", json={})).json()
    await cm.post(f"/api/invites/{inv['token']}/accept")
    assert (await cm.post(f"/api/claims/{a['claim_id']}/withdraw", json={})).status_code == 403

    # Agent B long-polls; Agent A withdraws; B is released with the reason as its ruling
    poll = asyncio.create_task(api.get(f"/api/clashes/{b['clash_id']}/verdict", params={"wait_seconds": 20}))
    await asyncio.sleep(0.5)
    w = await mcp.call("withdraw_claim", claim_id=a["claim_id"], reason="Switching to the login work instead")
    assert w["status"] == "retired" and w["released_clashes"] == [b["clash_id"]]
    r = (await poll).json()
    assert r["status"] == "auto_resolved" and r["verdict"] == "proceed_with_context" and r["resolution"] == "b_proceeds"
    assert "Switching" in r["ruling"]["content"] and r["resolved_by"] == "withdrawn:Agent A"

    assert (await api.get(f"/api/claims/{a['claim_id']}")).json()["status"] == "retired"
    types = [e["type"] for e in (await api.get(f"/api/projects/{pid}/activity")).json()]
    assert "claim.retired" in types and "clash.resolved" in types
    # idempotent
    assert (await mcp.call("withdraw_claim", claim_id=a["claim_id"]))["released_clashes"] == []
    # B's agent is no longer blocked: a fresh declaration of the same plan proceeds
    again = await mcp.call("declare_intent", agent_name="Agent C", plan_text=PLAN_B, project_id=pid)
    assert again["verdict"] in ("proceed", "proceed_with_context")
    await cm.aclose()


async def test_stale_claims_expire_and_release_clashes(api, mcp, project):
    pid = project["id"]
    a = await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, project_id=pid)
    b = await mcp.call("declare_intent", agent_name="Agent B", plan_text=PLAN_B, project_id=pid)
    assert b["verdict"] == "wait"

    old = datetime.now(timezone.utc) - timedelta(hours=100)
    async with session_scope() as db:
        await db.execute(update(Claim).where(Claim.id == uuid.UUID(a["claim_id"])).values(created_at=old))

    assert await claims_core.expire_stale_claims(0) == []  # disabled
    retired = await claims_core.expire_stale_claims(72)
    assert [str(x) for x in retired] == [a["claim_id"]]
    v = (await api.get(f"/api/clashes/{b['clash_id']}/verdict")).json()
    assert v["status"] == "auto_resolved" and v["resolution"] == "b_proceeds" and "expired" in v["ruling"]["content"]

    # a claim with a PR is never expired, however old
    async with session_scope() as db:
        await db.execute(update(Claim).where(Claim.id == uuid.UUID(b["claim_id"])).values(created_at=old, pr_number=7))
    assert await claims_core.expire_stale_claims(72) == []
    assert (await api.get(f"/api/claims/{b['claim_id']}")).json()["status"] == "open"


async def test_get_status(api, mcp, project):
    pid = project["id"]
    await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, branch="feature/tokens", project_id=pid)
    b = await mcp.call("declare_intent", agent_name="Agent B", plan_text=PLAN_B, project_id=pid)

    s = await mcp.call("get_status", project_id=pid)  # the key's owner owns both agents
    assert s["agents"] == ["Agent A", "Agent B"]
    assert {c["agent_name"] for c in s["claims"]} == {"Agent A", "Agent B"}
    assert [x["id"] for x in s["waiting_on"]] == [b["clash_id"]]
    assert [x["id"] for x in s["blocking"]] == [b["clash_id"]]

    sb = await mcp.call("get_status", agent_name="Agent B", project_id=pid)
    assert sb["agents"] == ["Agent B"] and sb["blocking"] == [] and len(sb["waiting_on"]) == 1
    assert sb["claims"][0]["status"] == "open"

    r = await api.get(f"/api/projects/{pid}/status", params={"agent": "Agent A"})
    assert r.status_code == 200 and r.json()["waiting_on"] == [] and r.json()["claims"][0]["branch"] == "feature/tokens"
    assert (await api.get(f"/api/projects/{pid}/status", params={"agent": "Nobody"})).json()["claims"] == []


async def test_stance_falls_back_when_the_model_call_fails():
    from app.core.stance import AnthropicStanceExtractor

    ex = AnthropicStanceExtractor(api_key="sk-not-a-key")

    async def boom(_plan: str):
        raise RuntimeError("api down")

    ex._extract = boom  # type: ignore[method-assign]
    st = await ex.extract(PLAN_A)
    assert "session model" in st.concepts and ex.fallbacks == 1


def test_database_url_accepts_hosted_postgres_forms():
    from app.config import Settings

    for given in ("postgres://u:p@h/db", "postgresql://u:p@h/db", "postgresql+asyncpg://u:p@h/db"):
        assert Settings(database_url=given).database_url == "postgresql+asyncpg://u:p@h/db"
