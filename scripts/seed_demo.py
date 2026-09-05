"""Seed the golden demo scenario. Idempotent. Works with all integrations disabled.

    python -m scripts.seed_demo            # seed
    python -m scripts.seed_demo --reset    # wipe the demo project first

Creates: one organisation ("Consensus Demo") with an admin user, one project
(fixed UUID so the frontend can hardcode it), three agents with developer names,
two tasks, a handful of memory entries and codebase_read token events so the
counters are not zero on stage. Prints the admin's API key for connecting agents.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import uuid

os.environ.setdefault("ENABLE_GITHUB", "false")
os.environ.setdefault("ENABLE_NOTION", "false")

from sqlalchemy import delete, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core.auth import API_KEY_PREFIX, sha256  # noqa: E402
from app.core.providers import get_providers  # noqa: E402
from app.db.models import (  # noqa: E402
    Agent,
    ApiKey,
    Claim,
    Clash,
    Membership,
    MemoryEntry,
    Organization,
    Project,
    Task,
    TokenEvent,
    User,
    VerdictLog,
)
from app.db.session import dispose_engine, session_scope  # noqa: E402

DEMO_ORG_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")
DEMO_ORG_NAME = "Consensus Demo"
DEMO_ADMIN_EMAIL = os.environ.get("DEMO_ADMIN_EMAIL", "demo@example.com")
DEMO_ADMIN_NAME = "Demo Admin"
DEMO_PROJECT_ID = uuid.UUID("00000000-0000-4000-8000-00000000c0de")
DEMO_PROJECT_NAME = "Consensus Demo"
DEMO_REPO = os.environ.get("DEMO_REPO_FULL_NAME") or None
DEMO_USERS = [("priya@example.com", "Priya"), ("marcus@example.com", "Marcus"), ("lena@example.com", "Lena")]


def demo_api_key() -> str:
    """Deterministic per SECRET_KEY so the same key works across re-seeds (dev only)."""
    return API_KEY_PREFIX + "demo_" + sha256("demo-key:" + get_settings().secret_key)[:32]

AGENTS = [
    ("Agent A", "Priya"),
    ("Agent B", "Marcus"),
    ("Agent C", "Lena"),
]

TASKS = [
    ("ENG-1201", "Move sessions to refresh tokens"),
    ("ENG-1207", "Add POST /login endpoint"),
]

MEMORY = [
    ("Agent C", "discovery", "Auth middleware lives in app/middleware/auth.py and runs before every route; it reads the session cookie and attaches request.user.", ["authentication", "session model"]),
    ("Agent C", "discovery", "Sessions are currently rows in the sessions table keyed by a random 32-byte id; expiry is enforced by a nightly job.", ["session model", "database schema"]),
    ("Agent C", "decision", "We decided that all auth failures return HTTP 401 with a JSON body {error: 'unauthenticated'}; never redirect from the API.", ["authentication", "error handling"]),
    ("Agent A", "dead_end", "Tried storing the session in a JWT inside localStorage; abandoned because the SPA needs HttpOnly cookies for CSRF safety.", ["session model", "auth token"]),
    ("Agent C", "discovery", "The users table has no email uniqueness constraint; duplicates exist in production. Do not rely on email as an identifier.", ["user model", "database schema"]),
    ("Agent B", "discovery", "Rate limiting is applied in the nginx layer, not in the app; per-route limits require an nginx config change.", ["rate limiting"]),
]

CODEBASE_READS = [("Agent A", 18500), ("Agent B", 22100), ("Agent C", 16400), ("Agent A", 20300)]


async def reset() -> None:
    async with session_scope() as db:
        for model in (VerdictLog, Clash, TokenEvent, MemoryEntry, Claim, Task, Agent):
            await db.execute(delete(model).where(model.project_id == DEMO_PROJECT_ID))
        await db.execute(delete(ApiKey).where(ApiKey.project_id == DEMO_PROJECT_ID))
        await db.execute(delete(Project).where(Project.id == DEMO_PROJECT_ID))
    print("reset demo project")


async def seed() -> None:
    providers = get_providers()
    async with session_scope() as db:
        # organisation + admin (the creator is the admin)
        admin = (await db.execute(select(User).where(User.email == DEMO_ADMIN_EMAIL))).scalar_one_or_none()
        if admin is None:
            admin = User(email=DEMO_ADMIN_EMAIL, name=DEMO_ADMIN_NAME)
            db.add(admin)
            await db.flush()
        org = await db.get(Organization, DEMO_ORG_ID)
        if org is None:
            org = Organization(id=DEMO_ORG_ID, name=DEMO_ORG_NAME, slug="consensus-demo", created_by=admin.id, auto_join_domain="example.com")
            db.add(org)
            await db.flush()
            print(f"created organisation {org.id}")
        users: dict[str, User] = {DEMO_ADMIN_NAME: admin}
        for email, name in DEMO_USERS:
            u = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if u is None:
                u = User(email=email, name=name)
                db.add(u)
                await db.flush()
            users[name] = u
        for u, role in [(admin, "admin")] + [(users[n], "member") for _, n in DEMO_USERS]:
            m = (await db.execute(select(Membership).where(Membership.org_id == org.id, Membership.user_id == u.id))).scalar_one_or_none()
            if m is None:
                db.add(Membership(org_id=org.id, user_id=u.id, role=role))
        await db.flush()

        project = await db.get(Project, DEMO_PROJECT_ID)
        if project is None:
            project = Project(id=DEMO_PROJECT_ID, org_id=org.id, name=DEMO_PROJECT_NAME, repo_full_name=DEMO_REPO)
            db.add(project)
            await db.flush()
            print(f"created project {project.id}")
        else:
            project.org_id = org.id
            if DEMO_REPO and project.repo_full_name != DEMO_REPO:
                project.repo_full_name = DEMO_REPO

        # admin API key bound to the demo project
        key_raw = demo_api_key()
        key = (await db.execute(select(ApiKey).where(ApiKey.key_hash == sha256(key_raw)))).scalar_one_or_none()
        if key is None:
            db.add(ApiKey(user_id=admin.id, org_id=org.id, project_id=project.id, name="demo", key_hash=sha256(key_raw), prefix=key_raw[:12]))

        agents: dict[str, Agent] = {}
        for name, dev in AGENTS:
            a = (await db.execute(select(Agent).where(Agent.project_id == project.id, Agent.name == name))).scalar_one_or_none()
            if a is None:
                a = Agent(project_id=project.id, name=name, developer_name=dev, user_id=users[dev].id)
                db.add(a)
                await db.flush()
            agents[name] = a

        for ref, title in TASKS:
            t = (await db.execute(select(Task).where(Task.project_id == project.id, Task.external_ref == ref))).scalar_one_or_none()
            if t is None:
                db.add(Task(project_id=project.id, external_ref=ref, title=title))

        existing = {
            row.content
            for row in (await db.execute(select(MemoryEntry).where(MemoryEntry.project_id == project.id))).scalars().all()
        }
        new_entries = [m for m in MEMORY if m[1] != "ruling" and m[2] not in existing]
        if new_entries:
            vectors = await providers.embeddings.embed_many([m[2] for m in new_entries])
            for (agent_name, type_, content, concepts), vec in zip(new_entries, vectors):
                db.add(
                    MemoryEntry(
                        project_id=project.id,
                        type=type_,
                        content=content,
                        concepts=concepts,
                        embedding=vec,
                        source_agent_id=agents[agent_name].id,
                    )
                )
        print(f"memory entries added: {len(new_entries)}")

        have_reads = (
            await db.execute(select(TokenEvent.id).where(TokenEvent.project_id == project.id, TokenEvent.kind == "codebase_read"))
        ).first()
        if not have_reads:
            for agent_name, tokens in CODEBASE_READS:
                db.add(TokenEvent(project_id=project.id, agent_id=agents[agent_name].id, kind="codebase_read", tokens=tokens))
            print(f"codebase_read events added: {len(CODEBASE_READS)}")

    print(f"demo project ready: {DEMO_PROJECT_ID}")
    print(f"demo org: {DEMO_ORG_ID}  admin: {DEMO_ADMIN_EMAIL} (sign in via POST /api/auth/dev-login when DEV_AUTH=true)")
    print("agents:", ", ".join(f"{n} ({d})" for n, d in AGENTS))
    print(f"admin API key (MCP bearer token): {demo_api_key()}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete the demo project first")
    args = parser.parse_args()
    try:
        if args.reset:
            await reset()
        await seed()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
