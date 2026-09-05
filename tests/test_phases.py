"""Phase checks from spec section 11 that the golden test does not already cover."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid

import pytest
import websockets
from sqlalchemy import select

from app.db.models import Claim, MemoryEntry
from app.db.session import session_scope
from app.integrations.github import build_pr_body
from app.schemas import ClaimOut, ClashOut

PLAN_A = "Replace the session model with a refresh-token flow. Sessions move from server-side store to signed tokens."
PLAN_B = "Add a POST /login endpoint that creates a server-side session and returns the session id."


# -- Phase 2: memory ---------------------------------------------------------------------------


async def test_memory_ranking_dedup_and_counters(api, mcp, project):
    pid = project["id"]
    entries = [
        ("discovery", "Login validates the password and creates a session row in the sessions table."),
        ("discovery", "Rate limiting is applied in nginx, not in the application."),
        ("decision", "All auth failures return 401 with a JSON body."),
        ("dead_end", "Storing the session in localStorage was abandoned because of CSRF."),
    ]
    for type_, content in entries:
        w = await mcp.call("write_memory", agent_name="Agent C", type=type_, content=content, project_id=pid)
        assert w["deduplicated"] is False

    # Near-duplicate is linked, not inserted.
    dup = await mcp.call(
        "write_memory",
        agent_name="Agent A",
        type="discovery",
        content="Login validates the password and creates a session row in the sessions table",
        concepts=["login endpoint"],
        project_id=pid,
    )
    assert dup["deduplicated"] is True
    r = await api.get(f"/api/projects/{pid}/memory")
    assert len(r.json()) == 4
    linked = next(e for e in r.json() if e["id"] == dup["entry_id"])
    assert "login endpoint" in linked["concepts"]

    # Query ranks the login discovery first for a login question.
    q = await mcp.call("query_memory", question="how does login work", agent_name="Agent B", project_id=pid)
    assert q["entries"][0]["content"].startswith("Login validates")
    assert q["entries"][0]["similarity"] >= q["entries"][-1]["similarity"]

    # Counters: no codebase_read baseline yet -> tokens_saved is 0
    c0 = (await api.get(f"/api/projects/{pid}/counters")).json()
    assert c0["memory_count"] == 4 and c0["tokens_saved"] == 0

    # Agents report codebase reads; the memory read now counts as savings.
    await mcp.call("report_usage", agent_name="Agent A", tokens=20000, kind="codebase_read", project_id=pid)
    r = await api.post(f"/api/projects/{pid}/token-events", json={"agent_name": "Agent B", "kind": "codebase_read", "tokens": 10000})
    assert r.status_code == 201
    c1 = (await api.get(f"/api/projects/{pid}/counters")).json()
    assert c1["tokens_saved"] == 15000 - q["tokens_used"]

    # Filtering by type works.
    r = await api.get(f"/api/projects/{pid}/memory", params={"type": "decision"})
    assert [e["type"] for e in r.json()] == ["decision"]
    r = await api.get(f"/api/projects/{pid}/memory", params={"q": "nginx rate limits"})
    assert r.json()[0]["content"].startswith("Rate limiting")


# -- Phase 4: handoff and GitHub ------------------------------------------------------------------


async def test_handoff_moves_claim_and_pr_body_has_everything(api, mcp, project):
    pid = project["id"]
    a = await mcp.call("declare_intent", agent_name="Agent A", developer_name="Priya", plan_text=PLAN_A, branch="feat/refresh-tokens", project_id=pid)
    b = await mcp.call("declare_intent", agent_name="Agent B", developer_name="Marcus", plan_text=PLAN_B, branch="feat/login", project_id=pid)
    assert b["verdict"] == "wait"
    await api.post(f"/api/clashes/{b['clash_id']}/resolve", json={"resolution": "b_proceeds", "note": "Login ships first; A rebases.", "resolved_by": "lead"})

    h = await mcp.call(
        "file_handoff",
        claim_id=b["claim_id"],
        changed=["app/api/login.py: new POST /login", "tests/test_login.py"],
        untouched=["session middleware"],
        assumptions=["password hashing stays bcrypt"],
        uncertainties=["rate limit for login attempts"],
    )
    assert h["pr_url"] is None  # GitHub disabled in tests: handoff still succeeds

    r = await api.get(f"/api/claims/{b['claim_id']}")
    assert r.json()["status"] == "in_review"
    r = await api.get(f"/api/projects/{pid}/claims", params={"status": "open"})
    assert [c["agent_name"] for c in r.json()] == ["Agent A"]

    r = await api.get(f"/api/projects/{pid}/memory", params={"type": "handoff"})
    assert len(r.json()) == 1 and "session middleware" in r.json()[0]["content"]

    # PR body assembly (pure function; what open_pull_request would send).
    async with session_scope() as db:
        claim = await db.get(Claim, uuid.UUID(b["claim_id"]))
        claim_out = ClaimOut.from_claim(claim)
    clash = ClashOut(**(await api.get(f"/api/clashes/{b['clash_id']}")).json())
    body = build_pr_body(
        claim_out,
        {"changed": ["app/api/login.py: new POST /login"], "untouched": ["session middleware"], "assumptions": ["bcrypt"], "uncertainties": ["rate limit"]},
        [clash],
    )
    assert PLAN_B in body
    assert "app/api/login.py: new POST /login" in body and "session middleware" in body
    assert "b_proceeds" in body and "Login ships first; A rebases." in body
    assert "Agent A" in body


async def test_merge_webhook_retires_claim(api, mcp, project):
    pid = project["id"]
    r = await api.post("/api/projects", json={"name": "Repo project", "repo_full_name": "acme/widgets"})
    repo_pid = r.json()["id"]
    a = await mcp.call("declare_intent", agent_name="Agent A", developer_name="Priya", plan_text=PLAN_A, branch="feat/x", project_id=repo_pid)
    async with session_scope() as db:
        claim = await db.get(Claim, uuid.UUID(a["claim_id"]))
        claim.pr_number = 42

    payload = json.dumps(
        {"action": "closed", "pull_request": {"number": 42, "merged": True}, "repository": {"full_name": "acme/widgets"}}
    ).encode()
    r = await api.post("/api/webhooks/github", content=payload, headers={"X-GitHub-Event": "pull_request", "content-type": "application/json"})
    assert r.status_code == 200 and r.json()["retired_claims"] == [a["claim_id"]]
    r = await api.get(f"/api/claims/{a['claim_id']}")
    assert r.json()["status"] == "retired"

    # ping is acknowledged; other events ignored
    r = await api.post("/api/webhooks/github", content=b"{}", headers={"X-GitHub-Event": "ping"})
    assert r.json()["event"] == "ping"


def test_webhook_signature_check():
    from app.integrations.github import verify_signature

    body = b'{"x":1}'
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_signature("secret", body, sig)
    assert not verify_signature("secret", body, "sha256=deadbeef")
    assert not verify_signature("secret", body, None)
    assert verify_signature(None, body, None)  # no secret configured


# -- Phase 5: live stream ----------------------------------------------------------------------------


async def test_two_websocket_clients_receive_every_event_within_a_second(api, mcp, project, server, admin):
    pid = project["id"]
    ws_url = server.replace("http://", "ws://") + f"/ws/projects/{pid}?token={admin['token']}"

    async with websockets.connect(ws_url) as ws1, websockets.connect(ws_url) as ws2:
        hello1, hello2 = json.loads(await ws1.recv()), json.loads(await ws2.recv())
        assert hello1["type"] == "hello" and "counters" in hello1["data"]
        assert hello2["type"] == "hello"

        async def collect(ws, n: int) -> list[dict]:
            out = []
            for _ in range(n):
                out.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0)))
            return out

        # claim.created (A)
        await mcp.call("declare_intent", agent_name="Agent A", developer_name="Priya", plan_text=PLAN_A, project_id=pid)
        # memory.written
        await mcp.call("write_memory", agent_name="Agent A", type="discovery", content="Sessions live in the sessions table.", project_id=pid)
        # memory.read
        await mcp.call("query_memory", question="sessions", agent_name="Agent B", project_id=pid)
        # claim.created (B) + clash.opened
        b = await mcp.call("declare_intent", agent_name="Agent B", developer_name="Marcus", plan_text=PLAN_B, project_id=pid)
        # memory.written (ruling) + clash.resolved
        await api.post(f"/api/clashes/{b['clash_id']}/resolve", json={"resolution": "a_proceeds", "note": "tokens win", "resolved_by": "lead"})
        # handoff.filed + memory.written (handoff entry)
        await mcp.call("file_handoff", claim_id=b["claim_id"], changed=["x"], untouched=[], assumptions=[], uncertainties=[])

        expected = [
            "claim.created",
            "memory.written",
            "memory.read",
            "claim.created",
            "clash.opened",
            "memory.written",
            "clash.resolved",
            "memory.written",
            "handoff.filed",
        ]
        got1, got2 = await asyncio.gather(collect(ws1, len(expected)), collect(ws2, len(expected)))
        assert [f["type"] for f in got1] == expected
        assert [f["type"] for f in got2] == expected
        assert all(f["project_id"] == pid for f in got1)
        assert got1[4]["data"]["clash"]["severity"] == "hard"

        await ws1.send("ping")
        assert json.loads(await asyncio.wait_for(ws1.recv(), timeout=1.0))["type"] == "pong"

    # unknown project is rejected
    with pytest.raises(Exception):
        async with websockets.connect(server.replace("http://", "ws://") + f"/ws/projects/{uuid.uuid4()}?token={admin['token']}") as ws:
            await ws.recv()


# -- Concurrency: two simultaneous declarations cannot both pass ----------------------------------------


async def test_simultaneous_declarations_serialise(api, mcp, project):
    pid = project["id"]
    a, b = await asyncio.gather(
        mcp.call("declare_intent", agent_name="Agent A", developer_name="Priya", plan_text=PLAN_A, project_id=pid),
        mcp.call("declare_intent", agent_name="Agent B", developer_name="Marcus", plan_text=PLAN_B, project_id=pid),
    )
    verdicts = sorted([a["verdict"], b["verdict"]])
    assert verdicts == ["proceed", "wait"], (a, b)
    r = await api.get(f"/api/projects/{pid}/clashes", params={"status": "open"})
    assert len(r.json()) == 1


# -- MCP surface ---------------------------------------------------------------------------------------


async def test_mcp_exposes_the_agent_tools(mcp, server):
    names = await mcp.list_tools()
    assert {"declare_intent", "query_memory", "write_memory", "file_handoff", "check_verdict", "report_usage"} <= set(names)


async def test_declare_without_project_uses_first_project(api, mcp, project):
    # Only one project exists (the fixture's) so an agent that passes no project_id lands on it.
    res = await mcp.call("declare_intent", agent_name="Agent Z", developer_name="Zed", plan_text="Add CSV export of reports.")
    assert res["project_id"] == project["id"]
    assert res["verdict"] == "proceed"
