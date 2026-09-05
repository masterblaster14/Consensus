"""End-to-end smoke test against a RUNNING server, the way a real agent would use it.

    python -m scripts.smoke_e2e                       # uses the seeded demo key
    python -m scripts.smoke_e2e --url http://host:8000 --key csk_...

Walks the golden scenario over MCP (declare -> memory -> clash -> ruling -> auto-resolve),
prints every verdict, and exits non-zero if anything is off. Also reports which providers
the server is using so you know whether the LLM path was actually exercised.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid

import httpx
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

PLAN_A = "Replace the session model with a refresh-token flow. Sessions move from server-side store to signed tokens."
PLAN_B = "Add a POST /login endpoint that creates a server-side session and returns the session id."
UNRELATED = "Add a CSV export button to the reports page that downloads the current table."
DISCOVERIES = [
    "Login is handled by app.auth.login which validates the password and creates a session row.",
    "The auth middleware reads the session cookie on every request and attaches the current user.",
]

OK, BAD = "\x1b[32mOK\x1b[0m", "\x1b[31mFAIL\x1b[0m"
failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    print(f"  [{OK if cond else BAD}] {label}" + (f"  ({detail})" if detail else ""))
    if not cond:
        failures.append(label)


class Agent:
    def __init__(self, url: str, key: str) -> None:
        self.url, self.key = url, key

    async def call(self, name: str, **args) -> dict:
        async with httpx2.AsyncClient(timeout=httpx2.Timeout(300.0), headers={"Authorization": f"Bearer {self.key}"}) as http:
            async with streamable_http_client(self.url, http_client=http) as (read, write, *_):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    res = await s.call_tool(name, args, read_timeout_seconds=300)
        if res.is_error:
            raise RuntimeError(res.content[0].text if res.content else "tool error")
        sc = res.structured_content
        if sc is not None:
            return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
        return json.loads(res.content[0].text)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("CONSENSUS_URL", "http://localhost:8000"))
    ap.add_argument("--key", default=os.environ.get("CONSENSUS_API_KEY"))
    ap.add_argument("--project", default=None, help="project id; default = the key's bound project")
    args = ap.parse_args()

    if not args.key:
        from scripts.seed_demo import demo_api_key

        args.key = demo_api_key()
        print(f"using seeded demo key {args.key[:14]}…")

    base = args.url.rstrip("/")
    rest = httpx.AsyncClient(base_url=base, timeout=60.0, headers={"Authorization": f"Bearer {args.key}"})
    agent = Agent(f"{base}/mcp", args.key)
    tag = uuid.uuid4().hex[:6]
    a_name, b_name = f"Smoke A {tag}", f"Smoke B {tag}"

    print("\n1. Server")
    h = (await rest.get("/health")).json()
    check(h.get("status") == "ok", "health", json.dumps(h))
    me = await rest.get("/api/auth/me")
    check(me.status_code == 200, "API key is valid", me.json()["user"]["email"] if me.status_code == 200 else me.text)
    provs = (await rest.get("/api/auth/providers")).json()
    print(f"     sign-in providers: {provs}")

    if args.project:
        pid = args.project
    else:
        # A fresh project per run so earlier smoke runs cannot produce clashes or rulings.
        org_id = me.json()["memberships"][0]["org_id"]
        r = await rest.post(f"/api/orgs/{org_id}/projects", json={"name": f"Smoke {tag}"})
        check(r.status_code == 201, "created a fresh project for this run", r.text[:100] if r.status_code != 201 else r.json()["id"])
        pid = r.json()["id"]

    print("\n2. Agent A declares on the project")
    t = time.perf_counter()
    a = await agent.call("declare_intent", agent_name=a_name, plan_text=PLAN_A, branch=f"smoke/{tag}-a", project_id=pid)
    # On an empty project this is "proceed"; on the seeded demo project, memory about auth
    # already exists, so "proceed_with_context" is the correct answer.
    expected = ("proceed",) if not args.project else ("proceed", "proceed_with_context")
    check(a["verdict"] in expected, f"verdict = {a['verdict']}", f"{a['duration_ms']} ms; context entries: {len(a['context'])}")
    check(a["clash"] is None, "no clash on a fresh plan")
    stance = (await rest.get(f"/api/claims/{a['claim_id']}")).json()["stance"]
    print(f"     concepts: {stance['concepts']}")
    print(f"     data_access: {stance['data_access']!r}  auth_check: {stance['auth_check']!r}  api_shape: {stance['api_shape']!r}")
    check(bool(stance["concepts"]), "stance has concepts")
    check(stance["error_handling"] is None, "unaddressed axis (error_handling) is null, not guessed")

    print("\n3. Agent A writes memory, Agent B reads it")
    for d in DISCOVERIES:
        w = await agent.call("write_memory", agent_name=a_name, type="discovery", content=d, project_id=pid)
    dup = await agent.call("write_memory", agent_name=a_name, type="discovery", content=DISCOVERIES[0], project_id=pid)
    check(dup["deduplicated"] is True, "near-duplicate memory is linked, not stored twice")
    q = await agent.call("query_memory", question="how does login work", agent_name=b_name, project_id=pid)
    check(len(q["entries"]) >= 2, f"query_memory returned {len(q['entries'])} entries", f"top: {q['entries'][0]['content'][:60]}…" if q["entries"] else "")

    print("\n4. Agent B declares the conflicting plan")
    t = time.perf_counter()
    b = await agent.call("declare_intent", agent_name=b_name, plan_text=PLAN_B, branch=f"smoke/{tag}-b", project_id=pid)
    check(b["verdict"] == "wait", f"verdict = {b['verdict']}", f"{b['duration_ms']} ms")
    if b["clash"]:
        c = b["clash"]
        check(c["with_agent"] == a_name, f"clash names {c['with_agent']}")
        check(any("session" in x.lower() for x in c["shared_concepts"]), f"shared concepts {c['shared_concepts']}")
        print(f"     axis={c['axis']}  yours={c['your_position']!r}  theirs={c['their_position']!r}")
    else:
        check(False, "clash payload present")

    print("\n5. An unrelated plan is not blocked")
    u = await agent.call("declare_intent", agent_name=f"Smoke C {tag}", plan_text=UNRELATED, project_id=pid)
    check(u["verdict"] != "wait", f"verdict = {u['verdict']}")

    if b.get("clash_id"):
        print("\n6. Human resolves; the waiting agent is released")
        waiter = asyncio.create_task(agent.call("check_verdict", clash_id=b["clash_id"], wait_seconds=30))
        await asyncio.sleep(1.0)
        note = f"Refresh tokens win ({tag})."
        r = await rest.post(f"/api/clashes/{b['clash_id']}/resolve", json={"resolution": "a_proceeds", "note": note})
        check(r.status_code == 200, "resolve endpoint", r.text[:120] if r.status_code != 200 else "")
        t = time.perf_counter()
        out = await asyncio.wait_for(waiter, timeout=20)
        check(out["status"] == "resolved" and out["ruling"] and note in out["ruling"]["content"], "pending check_verdict returned with the ruling", f"{int((time.perf_counter()-t)*1000)} ms after resolve")

        print("\n7. Same plan again: the ruling short-circuits")
        b2 = await agent.call("declare_intent", agent_name=b_name, plan_text=PLAN_B, project_id=pid)
        check(b2["verdict"] == "proceed_with_context", f"verdict = {b2['verdict']}")
        check(b2.get("ruling") is not None and note in b2["ruling"]["content"], "ruling attached to the response")
        open_ = (await rest.get(f"/api/projects/{pid}/clashes", params={"status": "open"})).json()
        check(not any(x["claim_b_id"] == b2["claim_id"] for x in open_), "no new open clash created")

        print("\n8. Handoff")
        hoff = await agent.call("file_handoff", claim_id=b2["claim_id"], changed=["app/api/login.py"], untouched=["session middleware"], assumptions=["bcrypt stays"], uncertainties=["login rate limit"])
        check("entry_id" in hoff, "handoff stored", f"pr_url={hoff.get('pr_url')}")
        st = (await rest.get(f"/api/claims/{b2['claim_id']}")).json()["status"]
        check(st == "in_review", f"claim status = {st}")

    print("\n9. Board")
    counters = (await rest.get(f"/api/projects/{pid}/counters")).json()
    print(f"     counters: {counters}")
    verdicts = (await rest.get(f"/api/projects/{pid}/verdicts", params={"limit": 3})).json()
    check(len(verdicts) >= 3, "verdict log records inputs", f"latest: {verdicts[0]['verdict']}, {len(verdicts[0]['detail']['candidates'])} candidates compared")

    await rest.aclose()
    print()
    if failures:
        print(f"{BAD}: {len(failures)} check(s) failed: {failures}")
        return 1
    print(f"{OK}: all checks passed against {base}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
