"""The golden acceptance test (spec section 12). This is the demo.

Runs through the agent-facing MCP tools and the arbitration REST endpoint,
exactly the way the demo does.
"""
from __future__ import annotations

import asyncio
import re

import pytest
from sqlalchemy import select

from app.db.models import Clash, MemoryEntry, TokenEvent, VerdictLog
from app.db.session import session_scope

AGENT_A_PLAN = (
    "Replace the session model with a refresh-token flow. "
    "Sessions move from server-side store to signed tokens."
)
AGENT_B_PLAN = "Add a POST /login endpoint that creates a server-side session and returns the session id."

DISCOVERIES = [
    "Login is handled by app.auth.login which validates the password and creates a session row.",
    "Sessions are stored in the sessions table keyed by a random id and expire after 14 days.",
    "The auth middleware reads the session cookie on every request and attaches the current user.",
    "Logout deletes the session row; there is no token revocation list because tokens are not used.",
]

PATH_RE = re.compile(r"(^|\s)[\w.-]*/[\w./-]+|\.py\b|\.ts\b|\.js\b")


@pytest.mark.asyncio(loop_scope="session")
async def test_golden_scenario(api, mcp, project):
    pid = project["id"]

    # -- Agent A declares on an empty project -> proceed ----------------------------------
    a = await mcp.call(
        "declare_intent",
        agent_name="Agent A",
        developer_name="Priya",
        plan_text=AGENT_A_PLAN,
        project_id=pid,
    )
    assert a["verdict"] == "proceed", a
    assert a["clash"] is None and a["clash_id"] is None

    # -- Agent A writes 4 discovery entries about how auth works --------------------------------
    for content in DISCOVERIES:
        w = await mcp.call("write_memory", agent_name="Agent A", type="discovery", content=content, project_id=pid)
        assert w["deduplicated"] is False

    # -- Agent B queries memory -> receives entries; a memory_read token event is recorded -----
    q = await mcp.call("query_memory", question="how does login work", agent_name="Agent B", project_id=pid)
    assert len(q["entries"]) == 4
    assert all(e["type"] == "discovery" and e["source_agent"] == "Agent A" for e in q["entries"])
    assert q["tokens_used"] > 0
    async with session_scope() as db:
        reads = (await db.execute(select(TokenEvent).where(TokenEvent.kind == "memory_read"))).scalars().all()
    assert len(reads) == 1 and reads[0].tokens == q["tokens_used"]

    # -- Agent B declares the conflicting plan -> wait --------------------------------------
    b = await mcp.call(
        "declare_intent",
        agent_name="Agent B",
        developer_name="Marcus",
        plan_text=AGENT_B_PLAN,
        project_id=pid,
    )
    assert b["verdict"] == "wait", b
    assert b["clash"] is not None and b["clash_id"] is not None
    assert b["clash"]["with_agent"] == "Agent A"
    assert b["clash"]["their_intent"] == AGENT_A_PLAN
    assert any("session" in c.lower() for c in b["clash"]["shared_concepts"]), b["clash"]
    assert b["clash"]["your_position"] and b["clash"]["their_position"]
    assert b["clash"]["your_position"] != b["clash"]["their_position"]

    # The memory Agent A wrote came back as context even though the verdict is wait.
    assert len(b["context"]) >= 1

    # -- NO FILE PATHS WERE COMPARED AT ANY POINT ----------------------------------------------
    # The verdict log records every input to the comparison. None of it is a file path:
    # only concepts, embeddings similarity and the four stance axes.
    async with session_scope() as db:
        logs = (await db.execute(select(VerdictLog).order_by(VerdictLog.created_at))).scalars().all()
    assert [l.verdict for l in logs] == ["proceed", "wait"]
    detail = logs[-1].detail
    assert detail["candidates"], "comparison ran against Agent A's claim"
    for cand in detail["candidates"]:
        cmp = cand["comparison"]
        assert set(cmp) == {"concept_overlap", "shared_concepts", "similarity", "divergent_axes", "severity"}
        assert cmp["severity"] == "hard"
        for concept in cmp["shared_concepts"]:
            assert not PATH_RE.search(concept), concept
        for div in cmp["divergent_axes"]:
            assert div["axis"] in {"error_handling", "auth_check", "data_access", "api_shape"}
    for concept in detail["stance"]["concepts"]:
        assert not PATH_RE.search(concept), concept

    # One open hard clash on the board.
    r = await api.get(f"/api/projects/{pid}/clashes", params={"status": "open"})
    open_clashes = r.json()
    assert len(open_clashes) == 1
    assert open_clashes[0]["id"] == b["clash_id"]
    assert open_clashes[0]["severity"] == "hard"
    assert {open_clashes[0]["agent_a"], open_clashes[0]["agent_b"]} == {"Agent A", "Agent B"}

    # -- Agent B holds on a long poll; a human resolves the clash -------------------------------
    pending = asyncio.create_task(mcp.call("check_verdict", clash_id=b["clash_id"], wait_seconds=60))
    await asyncio.sleep(1.0)  # make sure the poll is parked before the ruling lands
    assert not pending.done()

    note = "Refresh tokens win. Login must issue a signed token, not a server-side session."
    r = await api.post(
        f"/api/clashes/{b['clash_id']}/resolve",
        json={"resolution": "a_proceeds", "note": note, "resolved_by": "priya@example.com"},
    )
    assert r.status_code == 200, r.text
    resolved = r.json()
    assert resolved["status"] == "resolved" and resolved["resolution"] == "a_proceeds"
    assert resolved["ruling"]["type"] == "ruling" and note in resolved["ruling"]["content"]

    # A ruling memory entry exists carrying the note, the shared concepts and the axis.
    async with session_scope() as db:
        rulings = (await db.execute(select(MemoryEntry).where(MemoryEntry.type == "ruling"))).scalars().all()
    assert len(rulings) == 1
    assert note in rulings[0].content
    assert rulings[0].axis == open_clashes[0]["axis"]
    assert set(rulings[0].concepts) == set(open_clashes[0]["shared_concepts"])

    # Agent B's pending call returns with the ruling.
    outcome = await asyncio.wait_for(pending, timeout=15)
    assert outcome["status"] == "resolved"
    assert outcome["verdict"] == "proceed_with_context"
    assert outcome["ruling"] is not None and note in outcome["ruling"]["content"]

    # -- Agent B declares the same plan again -> proceed_with_context, no new open clash ---------
    b2 = await mcp.call(
        "declare_intent",
        agent_name="Agent B",
        developer_name="Marcus",
        plan_text=AGENT_B_PLAN,
        project_id=pid,
    )
    assert b2["verdict"] == "proceed_with_context", b2
    assert b2["ruling"] is not None and note in b2["ruling"]["content"]
    assert any(c["type"] == "ruling" and note in c["content"] for c in b2["context"])

    r = await api.get(f"/api/projects/{pid}/clashes", params={"status": "open"})
    assert r.json() == [], "the ruling must short-circuit; no human should be asked twice"
    async with session_scope() as db:
        clashes = (await db.execute(select(Clash).order_by(Clash.created_at))).scalars().all()
    assert [c.status for c in clashes] == ["resolved", "auto_resolved"]
    assert clashes[1].resolved_by == f"ruling:{rulings[0].id}"

    # Counters moved.
    r = await api.get(f"/api/projects/{pid}/counters")
    counters = r.json()
    assert counters["clashes_caught"] == 2
    assert counters["memory_count"] == 5  # 4 discoveries + 1 ruling
    assert counters["open_clashes"] == 0
