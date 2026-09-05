"""Phase 6: users, organisations, invites, roles, API keys, MCP auth, arbitration permissions."""
from __future__ import annotations

import uuid

import pytest
import websockets

from tests.conftest import ToolError, client_for, login

PLAN_A = "Replace the session model with a refresh-token flow. Sessions move from server-side store to signed tokens."
PLAN_B = "Add a POST /login endpoint that creates a server-side session and returns the session id."


async def test_creator_becomes_admin_and_orgs_are_isolated(anon, server):
    priya = await login(anon, "priya@acme.com", "Priya")
    c1 = await client_for(server, priya["token"])
    r = await c1.post("/api/orgs", json={"name": "Acme"})
    assert r.status_code == 201 and r.json()["role"] == "admin" and r.json()["slug"] == "acme"
    org = r.json()

    me = (await c1.get("/api/auth/me")).json()
    assert me["memberships"][0]["role"] == "admin" and me["memberships"][0]["org_id"] == org["id"]

    # another user creating an org with the same name gets a distinct slug and is admin of their own
    zed = await login(anon, "zed@other.com", "Zed")
    c2 = await client_for(server, zed["token"])
    r = await c2.post("/api/orgs", json={"name": "Acme"})
    assert r.status_code == 201 and r.json()["slug"] == "acme-2"

    # Zed cannot see Priya's org, members, or projects
    assert (await c2.get(f"/api/orgs/{org['id']}")).status_code == 403
    assert (await c2.get(f"/api/orgs/{org['id']}/members")).status_code == 403
    p = (await c1.post(f"/api/orgs/{org['id']}/projects", json={"name": "Widgets"})).json()
    assert (await c2.get(f"/api/projects/{p['id']}")).status_code == 403
    assert (await c2.get(f"/api/projects/{p['id']}/claims")).status_code == 403
    assert [x["id"] for x in (await c2.get("/api/projects")).json()] == []
    assert [x["id"] for x in (await c1.get("/api/projects")).json()] == [p["id"]]

    # unauthenticated is 401 everywhere that matters
    assert (await anon.get("/api/projects")).status_code == 401
    assert (await anon.get(f"/api/projects/{p['id']}/counters")).status_code == 401
    assert (await anon.get("/api/auth/me")).status_code == 401
    await c1.aclose()
    await c2.aclose()


async def test_invites_roles_and_membership(anon, server, admin, org):
    ca = admin["client"]
    # members cannot create invites; admins can
    marcus = await login(anon, "marcus@example.com", "Marcus")
    cm = await client_for(server, marcus["token"])
    assert (await cm.post(f"/api/orgs/{org['id']}/invites", json={})).status_code == 403

    inv = (await ca.post(f"/api/orgs/{org['id']}/invites", json={"email": "marcus@example.com", "role": "member"})).json()
    assert inv["url"].endswith(f"/invite/{inv['token']}")

    # public preview, then accept by the right person only
    preview = (await anon.get(f"/api/invites/{inv['token']}")).json()
    assert preview["org_name"] == "Acme" and preview["role"] == "member" and preview.get("token") is None
    lena = await login(anon, "lena@example.com", "Lena")
    cl = await client_for(server, lena["token"])
    assert (await cl.post(f"/api/invites/{inv['token']}/accept")).status_code == 403
    r = await cm.post(f"/api/invites/{inv['token']}/accept")
    assert r.status_code == 200 and r.json()["role"] == "member"
    assert (await cm.post(f"/api/invites/{inv['token']}/accept")).status_code == 404  # single use

    members = (await ca.get(f"/api/orgs/{org['id']}/members")).json()
    assert [(m["user_name"], m["role"]) for m in members] == [("Priya", "admin"), ("Marcus", "member")]

    # open invite (no email) works for anyone; admin role can be granted via invite
    open_inv = (await ca.post(f"/api/orgs/{org['id']}/invites", json={"role": "admin"})).json()
    assert (await cl.post(f"/api/invites/{open_inv['token']}/accept")).json()["role"] == "admin"

    # role changes; the last admin is protected
    marcus_id = marcus["me"]["user"]["id"]
    r = await ca.patch(f"/api/orgs/{org['id']}/members/{marcus_id}", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert (await cm.patch(f"/api/orgs/{org['id']}/members/{admin['me']['user']['id']}", json={"role": "member"})).status_code == 200
    lena_id = lena["me"]["user"]["id"]
    assert (await cm.patch(f"/api/orgs/{org['id']}/members/{lena_id}", json={"role": "member"})).status_code == 200
    assert (await cm.patch(f"/api/orgs/{org['id']}/members/{marcus_id}", json={"role": "member"})).status_code == 409
    assert (await cm.delete(f"/api/orgs/{org['id']}/members/{marcus_id}")).status_code == 409
    # a member can leave; an admin can remove others
    assert (await cl.delete(f"/api/orgs/{org['id']}/members/{lena_id}")).status_code == 204
    assert (await cl.get(f"/api/orgs/{org['id']}")).status_code == 403
    for c in (cm, cl):
        await c.aclose()


async def test_auto_join_by_email_domain(anon, server, admin):
    r = await admin["client"].post("/api/orgs", json={"name": "Globex", "auto_join_domain": "globex.com"})
    org = r.json()
    joined = await login(anon, "new.hire@globex.com", "New Hire")
    assert [m["org_id"] for m in joined["me"]["memberships"]] == [org["id"]]
    assert joined["me"]["memberships"][0]["role"] == "member"
    outsider = await login(anon, "someone@else.com", "Someone")
    assert outsider["me"]["memberships"] == []


async def test_magic_link_dev_flow(anon):
    r = await anon.post("/api/auth/magic-link", json={"email": "ada@example.com", "name": "Ada"})
    assert r.status_code == 200 and "dev_token" in r.json()
    token = r.json()["dev_token"]
    r = await anon.post("/api/auth/magic-link/verify", json={"token": token})
    assert r.status_code == 200 and r.json()["me"]["user"]["name"] == "Ada"
    assert (await anon.post("/api/auth/magic-link/verify", json={"token": token})).status_code == 400  # single use
    providers = (await anon.get("/api/auth/providers")).json()
    assert providers["magic_link"] is True and providers["dev_login"] is True and isinstance(providers["github"], bool)


async def test_api_keys_and_mcp_auth(anon, server, admin, org, project, mcp_factory):
    ca = admin["client"]
    # no key -> 401 at the transport
    with pytest.raises(Exception):
        await mcp_factory(None).list_tools()
    with pytest.raises(Exception):
        await mcp_factory("csk_not_a_real_key").list_tools()

    created = (await ca.post("/api/me/api-keys", json={"name": "laptop", "project_id": project["id"]})).json()
    assert created["key"].startswith("csk_") and created["mcp_url"].endswith("/mcp")
    listed = (await ca.get("/api/me/api-keys")).json()
    assert [k["name"] for k in listed] == ["laptop"] and "key" not in listed[0]

    tools = await mcp_factory(created["key"]).list_tools()
    assert "declare_intent" in tools

    # the key's project is the default; developer_name comes from the account, not the agent
    res = await mcp_factory(created["key"]).call("declare_intent", agent_name="Agent A", developer_name="Spoofed", plan_text=PLAN_A)
    assert res["project_id"] == project["id"] and res["verdict"] == "proceed"
    claim = (await ca.get(f"/api/claims/{res['claim_id']}")).json()
    assert claim["developer_name"] == "Priya"
    agents = (await ca.get(f"/api/projects/{project['id']}/agents")).json()
    assert agents[0]["user_id"] == admin["me"]["user"]["id"]

    # revoked key stops working
    await ca.delete(f"/api/me/api-keys/{created['id']}")
    from app.mcp.auth import invalidate_token_cache

    invalidate_token_cache()
    with pytest.raises(Exception):
        await mcp_factory(created["key"]).list_tools()


async def test_agent_ownership_and_arbitration_permissions(anon, server, admin, org, project, mcp_factory):
    ca = admin["client"]
    # add two members
    for email, name in [("marcus@example.com", "Marcus"), ("lena@example.com", "Lena")]:
        inv = (await ca.post(f"/api/orgs/{org['id']}/invites", json={"email": email})).json()
        u = await login(anon, email, name)
        c = await client_for(server, u["token"])
        assert (await c.post(f"/api/invites/{inv['token']}/accept")).status_code == 200
        await c.aclose()
    marcus = await login(anon, "marcus@example.com", "Marcus")
    lena = await login(anon, "lena@example.com", "Lena")
    cm, cl = await client_for(server, marcus["token"]), await client_for(server, lena["token"])
    key_m = (await cm.post("/api/me/api-keys", json={"name": "m", "project_id": project["id"]})).json()["key"]
    key_l = (await cl.post("/api/me/api-keys", json={"name": "l", "project_id": project["id"]})).json()["key"]
    key_a = (await ca.post("/api/me/api-keys", json={"name": "a", "project_id": project["id"]})).json()["key"]

    a = await mcp_factory(key_a).call("declare_intent", agent_name="Agent A", plan_text=PLAN_A)
    b = await mcp_factory(key_m).call("declare_intent", agent_name="Agent B", plan_text=PLAN_B)
    assert b["verdict"] == "wait"
    assert b["clash"]["with_agent"] == "Agent A"

    # Lena cannot hijack Marcus's agent name
    with pytest.raises(ToolError, match="belongs to another user"):
        await mcp_factory(key_l).call("declare_intent", agent_name="Agent B", plan_text="Add CSV export.")

    # Lena (member, not involved) cannot arbitrate; Marcus (owner of Agent B) can; admin can too.
    body = {"resolution": "a_proceeds", "note": "tokens win"}
    assert (await cl.post(f"/api/clashes/{b['clash_id']}/resolve", json=body)).status_code == 403
    r = await cm.post(f"/api/clashes/{b['clash_id']}/resolve", json=body)
    assert r.status_code == 200 and r.json()["resolved_by"] == "marcus@example.com"
    assert (await ca.post(f"/api/clashes/{b['clash_id']}/resolve", json=body)).status_code == 409  # already resolved

    # Lena can still read the board (she's a member)
    assert (await cl.get(f"/api/projects/{project['id']}/clashes")).status_code == 200

    # WebSocket: no token -> rejected; member token -> hello frame
    ws_base = server.replace("http://", "ws://") + f"/ws/projects/{project['id']}"
    with pytest.raises(Exception):
        async with websockets.connect(ws_base) as ws:
            await ws.recv()
    async with websockets.connect(ws_base + f"?token={lena['token']}") as ws:
        assert '"hello"' in await ws.recv()
    async with websockets.connect(ws_base + f"?token={key_l}") as ws:  # API keys work on WS too
        assert '"hello"' in await ws.recv()
    for c in (cm, cl):
        await c.aclose()


async def test_key_without_project_needs_disambiguation(anon, server, admin, org, mcp_factory):
    ca = admin["client"]
    p1 = (await ca.post(f"/api/orgs/{org['id']}/projects", json={"name": "One"})).json()
    key = (await ca.post("/api/me/api-keys", json={"name": "k"})).json()["key"]
    # one project: it is the default
    res = await mcp_factory(key).call("declare_intent", agent_name="Agent A", plan_text="Add CSV export.")
    assert res["project_id"] == p1["id"]
    # two projects: must pass project_id
    p2 = (await ca.post(f"/api/orgs/{org['id']}/projects", json={"name": "Two"})).json()
    with pytest.raises(ToolError, match="pass project_id"):
        await mcp_factory(key).call("declare_intent", agent_name="Agent A", plan_text="Add PDF export.")
    res = await mcp_factory(key).call("declare_intent", agent_name="Agent A", plan_text="Add PDF export.", project_id=p2["id"])
    assert res["project_id"] == p2["id"]
    # a project in someone else's org is forbidden even when named explicitly
    with pytest.raises(ToolError):
        await mcp_factory(key).call("declare_intent", agent_name="Agent A", plan_text="x", project_id=str(uuid.uuid4()))
