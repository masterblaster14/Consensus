"""Backend queue from docs/backend-pending.md: activity feed, enriched agents, project archive,
member restriction, org summary, manual tasks, presentation fields, mail and token encryption."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import crypto
from app.db.session import session_scope
from tests.conftest import ToolError, client_for, login

PLAN_A = "Replace the session model with a refresh-token flow. Sessions move from server-side store to signed tokens."
PLAN_B = "Add a POST /login endpoint that creates a server-side session and returns the session id."


# -- 1. activity feed -----------------------------------------------------------------------------


async def test_activity_feed_persists_every_event(api, mcp, project):
    pid = project["id"]
    await mcp.call("write_memory", agent_name="Agent A", type="discovery", content="Sessions live in Redis.", project_id=pid)
    await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, project_id=pid)
    d = await mcp.call("declare_intent", agent_name="Agent B", plan_text=PLAN_B, project_id=pid)
    assert d["verdict"] == "wait"

    feed = (await api.get(f"/api/projects/{pid}/activity")).json()
    types = [e["type"] for e in feed]
    assert types[0] == "clash.opened" or types[0] == "claim.created"  # newest first
    assert set(types) >= {"memory.written", "claim.created", "clash.opened"}
    assert all(e["project_id"] == pid and e["ts"] and e["id"] for e in feed)
    opened = next(e for e in feed if e["type"] == "clash.opened")
    assert opened["data"]["clash"]["id"] == d["clash_id"]

    only = (await api.get(f"/api/projects/{pid}/activity", params={"type": "memory.written,claim.created"})).json()
    assert {e["type"] for e in only} == {"memory.written", "claim.created"}

    # paging: `before` = ts of the last frame you have excludes everything at or after it
    older = (await api.get(f"/api/projects/{pid}/activity", params={"before": feed[0]["ts"], "limit": 100})).json()
    assert feed[0]["id"] not in {e["id"] for e in older} and len(older) == len(feed) - 1


# -- 2. agents carry their current work -------------------------------------------------------------


async def test_agents_carry_status_and_current_claim(api, mcp, project):
    pid = project["id"]
    d = await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, branch="feature/tokens", task_ref="ENG-1", project_id=pid)

    def agent(name):
        return next(a for a in agents if a["name"] == name)

    agents = (await api.get(f"/api/projects/{pid}/agents")).json()
    a = agent("Agent A")
    assert a["status"] == "working" and a["open_claims"] == 1
    assert a["current_claim"]["id"] == d["claim_id"]
    assert a["current_claim"]["branch"] == "feature/tokens" and a["current_claim"]["task_ref"] == "ENG-1"

    await mcp.call("file_handoff", claim_id=d["claim_id"], changed=["app/auth.py"], untouched=[], assumptions=[], uncertainties=[])
    agents = (await api.get(f"/api/projects/{pid}/agents")).json()
    a = agent("Agent A")
    assert a["status"] == "reviewing" and a["open_claims"] == 0 and a["current_claim"]["status"] == "in_review"

    await mcp.call("query_memory", question="anything", agent_name="Agent Z", project_id=pid)
    agents = (await api.get(f"/api/projects/{pid}/agents")).json()
    z = agent("Agent Z")
    assert z["status"] == "idle" and z["current_claim"] is None and z["open_claims"] == 0


# -- 3. archive a project ---------------------------------------------------------------------------


async def test_archive_project_hides_it_and_blocks_writes(anon, server, api, org, project, mcp):
    pid = project["id"]
    marcus = await login(anon, "marcus@example.com", "Marcus")
    cm = await client_for(server, marcus["token"])
    inv = (await api.post(f"/api/orgs/{org['id']}/invites", json={})).json()
    await cm.post(f"/api/invites/{inv['token']}/accept")
    assert (await cm.delete(f"/api/projects/{pid}")).status_code == 403  # members cannot archive

    assert (await api.delete(f"/api/orgs/{org['id']}/projects/{pid}")).status_code == 204
    assert pid not in [p["id"] for p in (await api.get("/api/projects")).json()]
    assert pid not in [p["id"] for p in (await api.get(f"/api/orgs/{org['id']}/projects")).json()]
    assert pid in [p["id"] for p in (await api.get("/api/projects", params={"include_archived": "true"})).json()]
    assert (await api.get(f"/api/projects/{pid}")).json()["archived_at"]
    assert (await api.get(f"/api/projects/{pid}/claims")).status_code == 200  # reads keep working

    with pytest.raises(ToolError, match="archived"):
        await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, project_id=pid)
    assert (await api.post(f"/api/projects/{pid}/tasks", json={"title": "x"})).status_code == 403

    r = await api.post(f"/api/projects/{pid}/restore")
    assert r.status_code == 200 and r.json()["archived_at"] is None
    d = await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, project_id=pid)
    assert d["verdict"] == "proceed"
    await cm.aclose()


# -- 4. restricted members are read-only ------------------------------------------------------------


async def test_restricted_member_is_read_only(anon, server, admin, org, project, mcp_factory):
    ca, pid = admin["client"], project["id"]
    marcus = await login(anon, "marcus@example.com", "Marcus")
    cm = await client_for(server, marcus["token"])
    inv = (await ca.post(f"/api/orgs/{org['id']}/invites", json={})).json()
    await cm.post(f"/api/invites/{inv['token']}/accept")
    key = (await cm.post("/api/me/api-keys", json={"org_id": org["id"], "project_id": pid})).json()["key"]
    bot = mcp_factory(key)
    d = await bot.call("declare_intent", agent_name="Marcus bot", plan_text="Add a health endpoint that returns 200.", project_id=pid)
    assert d["verdict"] == "proceed"

    marcus_id = marcus["me"]["user"]["id"]
    r = await ca.patch(f"/api/orgs/{org['id']}/members/{marcus_id}", json={"status": "restricted"})
    assert r.status_code == 200 and r.json()["status"] == "restricted" and r.json()["role"] == "member"
    me = (await cm.get("/api/auth/me")).json()
    assert me["memberships"][0]["status"] == "restricted"

    # reads still work, over REST and MCP
    assert (await cm.get(f"/api/projects/{pid}/claims")).status_code == 200
    assert (await bot.call("query_memory", question="health", project_id=pid))["entries"] == []
    # writes are refused everywhere
    with pytest.raises(ToolError, match="restricted"):
        await bot.call("declare_intent", agent_name="Marcus bot", plan_text="Add a metrics endpoint.", project_id=pid)
    with pytest.raises(ToolError, match="restricted"):
        await bot.call("write_memory", agent_name="Marcus bot", type="discovery", content="x", project_id=pid)
    with pytest.raises(ToolError, match="restricted"):
        await bot.call("report_usage", agent_name="Marcus bot", tokens=10, project_id=pid)
    with pytest.raises(ToolError, match="restricted"):
        await bot.call("file_handoff", claim_id=d["claim_id"], changed=["x"], untouched=[], assumptions=[], uncertainties=[])
    r = await cm.post(f"/api/projects/{pid}/memory", json={"agent_name": "Marcus bot", "type": "discovery", "content": "y"})
    assert r.status_code == 403
    assert (await cm.post(f"/api/projects/{pid}/tasks", json={"title": "x"})).status_code == 403

    # the last active admin cannot be restricted or demoted; an empty patch is rejected
    admin_id = admin["me"]["user"]["id"]
    assert (await ca.patch(f"/api/orgs/{org['id']}/members/{admin_id}", json={"status": "restricted"})).status_code == 409
    assert (await ca.patch(f"/api/orgs/{org['id']}/members/{admin_id}", json={})).status_code == 400

    # a restricted admin has no admin powers until reinstated
    await ca.patch(f"/api/orgs/{org['id']}/members/{marcus_id}", json={"role": "admin"})
    assert (await cm.post(f"/api/orgs/{org['id']}/invites", json={})).status_code == 403
    await ca.patch(f"/api/orgs/{org['id']}/members/{marcus_id}", json={"status": "active"})
    assert (await cm.post(f"/api/orgs/{org['id']}/invites", json={})).status_code == 201
    d2 = await bot.call("declare_intent", agent_name="Marcus bot", plan_text="Add a metrics endpoint.", project_id=pid)
    assert d2["verdict"] in ("proceed", "proceed_with_context")
    await cm.aclose()


# -- 5. org summary ---------------------------------------------------------------------------------


async def test_org_summary(api, org, project, mcp):
    pid = project["id"]
    await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, project_id=pid)
    await mcp.call("declare_intent", agent_name="Agent B", plan_text=PLAN_B, project_id=pid)
    p2 = (await api.post(f"/api/orgs/{org['id']}/projects", json={"name": "Widgets", "repo_full_name": "acme/widgets"})).json()

    s = (await api.get(f"/api/orgs/{org['id']}/summary")).json()
    assert s == {
        "projects": 2, "repositories": 1, "members": 1, "agents": 2, "active_agents": 2,
        "open_claims": 2, "open_clashes": 1, "memory_count": 0, "tokens_saved": 0,
    }
    await api.delete(f"/api/orgs/{org['id']}/projects/{p2['id']}")
    s = (await api.get(f"/api/orgs/{org['id']}/summary")).json()
    assert s["projects"] == 1 and s["repositories"] == 0


# -- 7. manual tasks --------------------------------------------------------------------------------


async def test_tasks_crud(api, project, mcp):
    pid = project["id"]
    r = await api.post(f"/api/projects/{pid}/tasks", json={"title": "Ship login", "external_ref": "ENG-7"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "open" and t["assignee_agent"] is None and t["external_ref"] == "ENG-7"
    assert (await api.post(f"/api/projects/{pid}/tasks", json={"title": "dup", "external_ref": "ENG-7"})).status_code == 409

    # declaring against the same task_ref reuses the task instead of creating a second one
    await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, task_ref="ENG-7", project_id=pid)
    assert len((await api.get(f"/api/projects/{pid}/tasks")).json()) == 1

    r = await api.patch(f"/api/projects/{pid}/tasks/{t['id']}", json={"status": "in_progress", "assignee_agent": "Agent A"})
    assert r.status_code == 200 and r.json()["status"] == "in_progress" and r.json()["assignee_agent"] == "Agent A"
    assert (await api.patch(f"/api/projects/{pid}/tasks/{t['id']}", json={"status": "bogus"})).status_code == 422
    assert (await api.patch(f"/api/projects/{pid}/tasks/{t['id']}", json={"assignee_agent": "Nobody"})).status_code == 404
    r = await api.patch(f"/api/projects/{pid}/tasks/{t['id']}", json={"assignee_agent": ""})
    assert r.json()["assignee_agent"] is None and r.json()["assignee_agent_id"] is None

    assert [x["id"] for x in (await api.get(f"/api/projects/{pid}/tasks", params={"status": "in_progress"})).json()] == [t["id"]]
    assert (await api.get(f"/api/projects/{pid}/tasks", params={"status": "done"})).json() == []

    # deleting a task a claim referenced keeps the claim
    assert (await api.delete(f"/api/projects/{pid}/tasks/{t['id']}")).status_code == 204
    assert (await api.get(f"/api/projects/{pid}/tasks")).json() == []
    claims = (await api.get(f"/api/projects/{pid}/claims")).json()
    assert len(claims) == 1 and claims[0]["task_id"] is None


# -- 8 + 9. presentation fields ---------------------------------------------------------------------


async def test_clash_and_memory_presentation_fields(api, mcp, project):
    pid = project["id"]
    await mcp.call("declare_intent", agent_name="Agent A", plan_text=PLAN_A, project_id=pid)
    d = await mcp.call("declare_intent", agent_name="Agent B", plan_text=PLAN_B, project_id=pid)
    assert d["verdict"] == "wait"
    c = (await api.get(f"/api/clashes/{d['clash_id']}")).json()
    assert c["severity_label"] == "high"
    assert c["title"].lower().startswith(c["axis"].replace("_", " ")) and "conflict on" in c["title"]
    assert "Agent A" in c["explanation"] and "Agent B" in c["explanation"] and c["explanation"].endswith(".")
    listed = (await api.get(f"/api/projects/{pid}/clashes")).json()
    assert listed[0]["title"] == c["title"]

    w = await mcp.call("write_memory", agent_name="Agent A", type="decision", content="All auth failures return 401. Never redirect from the API.", concepts=["auth failures", "API errors"], project_id=pid)
    w2 = await mcp.call("write_memory", agent_name="Agent A", type="discovery", content="Sessions are stored in Redis with a 24h TTL. Cookies are HTTP-only.", project_id=pid)
    entries = {e["id"]: e for e in (await api.get(f"/api/projects/{pid}/memory")).json()}
    assert entries[w["entry_id"]]["title"] == "Auth failures, API errors"
    assert entries[w2["entry_id"]]["title"] == "Sessions are stored in Redis with a 24h TTL."


# -- B. mail delivery state and encryption at rest ------------------------------------------------


async def test_magic_link_and_invite_report_delivery_state(anon, api, org):
    r = (await anon.post("/api/auth/magic-link", json={"email": "someone@example.com"})).json()
    assert r["ok"] is True and r["sent"] is False and "dev_link" in r  # no SMTP configured in tests
    assert (await anon.get("/api/auth/providers")).json()["magic_link"] is True  # dev mode keeps it offered
    inv = (await api.post(f"/api/orgs/{org['id']}/invites", json={"email": "new@example.com"})).json()
    assert inv["email_sent"] is False and inv["url"]
    open_inv = (await api.post(f"/api/orgs/{org['id']}/invites", json={})).json()
    assert open_inv["email_sent"] is None


async def test_integration_tokens_are_encrypted_at_rest(api, org):
    r = await api.put(f"/api/orgs/{org['id']}/integrations/notion", json={"notion_token": "secret_abc123", "notion_tasks_db_id": "db-1"})
    assert r.status_code == 200 and r.json()["integrations"]["notion"]["connected"] is True
    async with session_scope() as db:
        stored = (await db.execute(text("SELECT notion_token FROM organizations WHERE id = :id"), {"id": org["id"]})).scalar_one()
    assert stored.startswith(crypto.PREFIX) and "secret_abc123" not in stored
    assert crypto.decrypt(stored) == "secret_abc123"
    assert crypto.decrypt("legacy-plaintext") == "legacy-plaintext"  # rows written before encryption still read
    assert crypto.encrypt(crypto.encrypt("x")) == crypto.encrypt("x") or crypto.decrypt(crypto.encrypt(crypto.encrypt("x"))) == "x"
