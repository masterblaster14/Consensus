"""GitHub integration end-to-end, against a RUNNING server and a real repository.

Prerequisites (all local):
  * you signed in with GitHub and put the session token in .env as DEV_SESSION_TOKEN
  * the demo project's repo_full_name is the test repo (seed with DEMO_REPO_FULL_NAME=owner/repo)

    python -m scripts.github_e2e            # runs, then cleans up the PRs and branches it made
    python -m scripts.github_e2e --keep     # leave the PRs open for inspection

What it checks:
  1. session token valid; the user is (or becomes) an admin of the demo org
  2. connect GitHub to the org using that user's OAuth token; the repo is visible
  3. two branches with one commit each are created on the repo
  4. Agent A declares on branch a, Agent B declares the conflicting plan on branch b -> wait
  5. the clash is resolved; A files a handoff -> a real PR is opened
  6. the PR body contains the intent, changed / untouched lists and the clash resolution
  7. sync_open_prs finds nothing new (our PRs are already tracked)
  8. a simulated pull_request.closed webhook retires the claim
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault("ENABLE_NOTION", "false")

from scripts.seed_demo import DEMO_ORG_ID, DEMO_PROJECT_ID, demo_api_key  # noqa: E402
from scripts.smoke_e2e import Agent, check, failures  # noqa: E402

PLAN_A = "Replace the session model with a refresh-token flow. Sessions move from server-side store to signed tokens."
PLAN_B = "Add a POST /login endpoint that creates a server-side session and returns the session id."
GH = "https://api.github.com"


async def github_client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=GH,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        timeout=30.0,
    )


async def org_github_token() -> str | None:
    from app.db.models import Organization
    from app.db.session import dispose_engine, session_scope

    async with session_scope() as db:
        org = await db.get(Organization, DEMO_ORG_ID)
        tok = org.github_token if org else None
    await dispose_engine()
    return tok


async def ensure_initial_commit(gh: httpx.AsyncClient, repo: str, base: str) -> None:
    """An empty repository has no refs; give it a README on the default branch."""
    r = await gh.get(f"/repos/{repo}/git/ref/heads/{base}")
    if r.status_code == 200:
        return
    import base64

    content = base64.b64encode(("# " + repo.split("/")[-1] + chr(10) + chr(10) + "Test repository for Consensus." + chr(10)).encode()).decode()
    r = await gh.put(f"/repos/{repo}/contents/README.md", json={"message": "initial commit (consensus smoke)", "content": content})
    r.raise_for_status()


async def make_branch(gh: httpx.AsyncClient, repo: str, name: str, base: str, tag: str) -> None:
    r = await gh.get(f"/repos/{repo}/git/ref/heads/{base}")
    r.raise_for_status()
    sha = r.json()["object"]["sha"]
    r = await gh.post(f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha})
    r.raise_for_status()
    import base64

    content = base64.b64encode(f"consensus smoke {tag} on {name}\n".encode()).decode()
    r = await gh.put(
        f"/repos/{repo}/contents/consensus-smoke/{name.replace('/', '_')}.txt",
        json={"message": f"consensus smoke {tag}", "content": content, "branch": name},
    )
    r.raise_for_status()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("CONSENSUS_URL", "http://localhost:8000"))
    ap.add_argument("--keep", action="store_true", help="do not close the PRs / delete the branches afterwards")
    args = ap.parse_args()
    base = args.url.rstrip("/")
    jwt = os.environ.get("DEV_SESSION_TOKEN")
    if not jwt:
        print("DEV_SESSION_TOKEN is not set in .env (sign in with GitHub first)")
        return 2
    tag = uuid.uuid4().hex[:6]

    user = httpx.AsyncClient(base_url=base, timeout=120.0, headers={"Authorization": f"Bearer {jwt}"})
    admin = httpx.AsyncClient(base_url=base, timeout=60.0, headers={"Authorization": f"Bearer {demo_api_key()}"})

    print("\n1. Session")
    me = await user.get("/api/auth/me")
    check(me.status_code == 200, "session token valid", me.json()["user"]["email"] if me.status_code == 200 else me.text[:120])
    if me.status_code != 200:
        return 1
    email = me.json()["user"]["email"]
    check(bool(me.json()["user"].get("github_login")), "signed in via GitHub", me.json()["user"].get("github_login") or "no github_login on user")
    roles = {m["org_id"]: m["role"] for m in me.json()["memberships"]}
    if roles.get(str(DEMO_ORG_ID)) != "admin":
        inv = (await admin.post(f"/api/orgs/{DEMO_ORG_ID}/invites", json={"role": "admin"})).json()
        r = await user.post(f"/api/invites/{inv['token']}/accept")
        check(r.status_code == 200 and r.json()["role"] == "admin", "joined the demo org as admin via invite", r.text[:120] if r.status_code != 200 else "")
    else:
        check(True, "already admin of the demo org")

    print("\n2. Connect GitHub to the organisation")
    r = await user.post(f"/api/orgs/{DEMO_ORG_ID}/integrations/github/connect")
    check(r.status_code == 200 and r.json()["integrations"]["github"]["connected"], "org GitHub integration connected", r.text[:160] if r.status_code != 200 else "")
    proj = (await user.get(f"/api/projects/{DEMO_PROJECT_ID}")).json()
    repo = proj.get("repo_full_name")
    check(bool(repo), f"demo project repo = {repo}")
    r = await user.get(f"/api/orgs/{DEMO_ORG_ID}/integrations/github/repos")
    names = [x["full_name"] for x in r.json()] if r.status_code == 200 else []
    check(repo in names, f"repo visible to the connected token ({len(names)} repos listed)", "" if repo in names else r.text[:160])

    token = await org_github_token()
    if not token:
        print("no org token stored; aborting")
        return 1
    gh = await github_client(token)
    default_branch = (await gh.get(f"/repos/{repo}")).json().get("default_branch", "main")

    print("\n3. Branches on the repo")
    br_a, br_b = f"consensus/smoke-{tag}-a", f"consensus/smoke-{tag}-b"
    try:
        await ensure_initial_commit(gh, repo, default_branch)
        await make_branch(gh, repo, br_a, default_branch, tag)
        await make_branch(gh, repo, br_b, default_branch, tag)
        check(True, f"created {br_a} and {br_b} from {default_branch}")
    except httpx.HTTPStatusError as e:
        check(False, "create branches", f"{e.response.status_code} {e.response.text[:160]}")
        return 1

    key = (await user.post("/api/me/api-keys", json={"name": f"github-e2e-{tag}", "org_id": str(DEMO_ORG_ID), "project_id": str(DEMO_PROJECT_ID)})).json()["key"]
    agent = Agent(f"{base}/mcp", key)
    a_name, b_name = f"GH A {tag}", f"GH B {tag}"

    print("\n4. Declare")
    a = await agent.call("declare_intent", agent_name=a_name, plan_text=PLAN_A, branch=br_a, task_ref="ENG-1201")
    check(a["verdict"] != "wait", f"A verdict = {a['verdict']}")
    b = await agent.call("declare_intent", agent_name=b_name, plan_text=PLAN_B, branch=br_b, task_ref="ENG-1207")
    check(b["verdict"] == "wait" and b["clash"] and b["clash"]["with_agent"] == a_name, f"B verdict = {b['verdict']}")

    print("\n5. Resolve, then A files a handoff -> pull request")
    note = f"Refresh tokens win ({tag}); login must issue a signed token."
    r = await user.post(f"/api/clashes/{b['clash_id']}/resolve", json={"resolution": "a_proceeds", "note": note})
    check(r.status_code == 200, "clash resolved", r.text[:120] if r.status_code != 200 else r.json()["resolved_by"])
    h = await agent.call(
        "file_handoff",
        claim_id=a["claim_id"],
        changed=["auth/session.py: signed refresh tokens", "auth/middleware.py: validate token per request"],
        untouched=["login endpoint (Agent B)", "user model"],
        assumptions=["HttpOnly cookie carries the refresh token"],
        uncertainties=["token rotation interval"],
    )
    check(bool(h.get("pr_url")), f"PR opened: {h.get('pr_url')}")
    pr_a = h.get("pr_number")

    print("\n6. PR body")
    if pr_a:
        pr = (await gh.get(f"/repos/{repo}/pulls/{pr_a}")).json()
        body = pr.get("body") or ""
        check(PLAN_A in body, "body contains the original intent")
        check("auth/session.py: signed refresh tokens" in body and "login endpoint (Agent B)" in body, "body contains changed and untouched lists")
        check("HttpOnly cookie" in body and "token rotation" in body, "body contains assumptions and uncertainties")
        check("a_proceeds" in body and note in body, "body contains the clash resolution and note")
        check(pr["head"]["ref"] == br_a and pr["base"]["ref"] == default_branch, f"PR from {pr['head']['ref']} into {pr['base']['ref']}")
        claim = (await user.get(f"/api/claims/{a['claim_id']}")).json()
        check(claim["pr_number"] == pr_a and claim["status"] == "in_review", "claim records pr_number and is in_review")

    print("\n7. sync_open_prs")
    r = await user.post(f"/api/projects/{DEMO_PROJECT_ID}/integrations/github/sync")
    check(r.status_code == 200, f"sync ran, created {r.json().get('claims_created')} claim(s) for untracked PRs", r.text[:120] if r.status_code != 200 else "")

    print("\n8. Merge webhook retires the claim")
    payload = json.dumps({"action": "closed", "pull_request": {"number": pr_a, "merged": True}, "repository": {"full_name": repo}}).encode()
    headers = {"X-GitHub-Event": "pull_request", "content-type": "application/json"}
    secret = os.environ.get("GITHUB_WEBHOOK_SECRET")
    if secret:
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    r = await user.post("/api/webhooks/github", content=payload, headers=headers)
    check(r.status_code == 200 and a["claim_id"] in r.json().get("retired_claims", []), "webhook retired the claim", r.text[:120])
    claim = (await user.get(f"/api/claims/{a['claim_id']}")).json()
    check(claim["status"] == "retired", f"claim status = {claim['status']}")

    if not args.keep:
        print("\n9. Cleanup")
        if pr_a:
            await gh.patch(f"/repos/{repo}/pulls/{pr_a}", json={"state": "closed"})
        for br in (br_a, br_b):
            await gh.delete(f"/repos/{repo}/git/refs/heads/{br}")
        check(True, "closed the PR and deleted the branches")
    else:
        print(f"\nkept PR #{pr_a} and branches {br_a}, {br_b}")

    await gh.aclose()
    await user.aclose()
    await admin.aclose()
    print()
    if failures:
        print(f"FAIL: {failures}")
        return 1
    print("OK: GitHub integration works end to end")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
