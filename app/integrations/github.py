"""GitHub integration: open PRs, comment clashes, sync open PRs, handle merge webhook.

Behind ENABLE_GITHUB. The token comes from the project's organisation (an admin's
GitHub OAuth token, connected via POST /api/orgs/{id}/integrations/github/connect),
falling back to the GITHUB_TOKEN env var. Every entry point swallows and logs its
own errors so the declare flow never depends on GitHub being up.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.schemas import ClaimOut, ClashOut

log = logging.getLogger(__name__)

API = "https://api.github.com"


@dataclass
class PullRequest:
    number: int
    url: str


def _client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=API,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "consensus-coordinator",
        },
        timeout=15.0,
    )


@dataclass
class Creds:
    repo: str | None
    token: str | None

    @property
    def ok(self) -> bool:
        return bool(self.repo and self.token)


async def _creds_for_project(project_id: uuid.UUID) -> Creds:
    """Repo + token for a project: the org's connected GitHub token, else GITHUB_TOKEN."""
    from app.db.models import Organization, Project
    from app.db.session import session_scope

    settings = get_settings()
    if not settings.enable_github:
        return Creds(None, None)
    async with session_scope() as db:
        project = await db.get(Project, project_id)
        if project is None:
            return Creds(None, None)
        token = None
        if project.org_id:
            org = await db.get(Organization, project.org_id)
            token = org.github_token if org else None
        return Creds(project.repo_full_name, token or settings.github_token)


async def _default_branch(client: httpx.AsyncClient, repo: str) -> str:
    r = await client.get(f"/repos/{repo}")
    r.raise_for_status()
    return r.json().get("default_branch", "main")


# -- PR body ---------------------------------------------------------------------


def build_pr_body(claim: ClaimOut, handoff: dict, clashes: list[ClashOut]) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {i}" for i in items) if items else "- (none)"

    lines = [
        "## Intent",
        claim.intent_text,
        "",
        f"_Declared by {claim.agent_name or 'unknown agent'}"
        + (f" ({claim.developer_name})" if claim.developer_name else "")
        + (f" for {claim.task_ref}" if claim.task_ref else "")
        + "._",
        "",
        "## Changed",
        bullets(handoff.get("changed", [])),
        "",
        "## Untouched",
        bullets(handoff.get("untouched", [])),
        "",
        "## Assumptions",
        bullets(handoff.get("assumptions", [])),
        "",
        "## Uncertainties",
        bullets(handoff.get("uncertainties", [])),
        "",
        "## Clashes",
    ]
    if not clashes:
        lines.append("- none detected")
    for c in clashes:
        other = c.agent_a if c.claim_b_id == claim.id else c.agent_b
        status = c.status
        res = f" -> **{c.resolution}**" if c.resolution else ""
        note = f": {c.resolution_note}" if c.resolution_note else ""
        lines.append(
            f"- **{c.severity}** on `{c.axis}` with {other or 'another agent'} "
            f"(shared: {', '.join(c.shared_concepts) or '-'}) [{status}]{res}{note}"
        )
    lines += ["", "---", "_Opened by Consensus. Claim `" + str(claim.id) + "`._"]
    return "\n".join(lines)


async def open_pull_request(
    project_id: uuid.UUID, claim: ClaimOut, handoff: dict, clashes: list[ClashOut]
) -> PullRequest | None:
    creds = await _creds_for_project(project_id)
    if not creds.ok or not claim.branch:
        log.info("open_pull_request skipped (repo=%s token=%s branch=%s)", creds.repo, bool(creds.token), claim.branch)
        return None
    repo = creds.repo
    title = (claim.stance.summary or claim.intent_text).strip().splitlines()[0][:120]
    body = build_pr_body(claim, handoff, clashes)
    async with _client(creds.token) as client:
        base = await _default_branch(client, repo)
        # reuse an existing PR for this branch if one is open
        owner = repo.split("/")[0]
        existing = await client.get(f"/repos/{repo}/pulls", params={"head": f"{owner}:{claim.branch}", "state": "open"})
        if existing.status_code == 200 and existing.json():
            pr = existing.json()[0]
            await client.patch(f"/repos/{repo}/pulls/{pr['number']}", json={"body": body})
            return PullRequest(number=pr["number"], url=pr["html_url"])
        r = await client.post(f"/repos/{repo}/pulls", json={"title": title, "head": claim.branch, "base": base, "body": body})
        r.raise_for_status()
        pr = r.json()
        return PullRequest(number=pr["number"], url=pr["html_url"])


async def comment_on_pr(project_id: uuid.UUID, pr_number: int, clash: ClashOut) -> None:
    creds = await _creds_for_project(project_id)
    if not creds.ok:
        return
    repo = creds.repo
    body = (
        f"**Consensus clash ({clash.severity}) on `{clash.axis}`** between {clash.agent_a} and {clash.agent_b}\n\n"
        f"- Shared concepts: {', '.join(clash.shared_concepts) or '-'}\n"
        f"- {clash.agent_a}: {clash.position_a or '-'}\n"
        f"- {clash.agent_b}: {clash.position_b or '-'}\n"
        f"- Status: {clash.status}"
        + (f" -> {clash.resolution}" if clash.resolution else "")
        + (f"\n- Note: {clash.resolution_note}" if clash.resolution_note else "")
    )
    async with _client(creds.token) as client:
        r = await client.post(f"/repos/{repo}/issues/{pr_number}/comments", json={"body": body})
        r.raise_for_status()


def comment_on_pr_background(project_id: uuid.UUID, pr_number: int, clash: ClashOut) -> None:
    async def _run() -> None:
        try:
            await comment_on_pr(project_id, pr_number, clash)
        except Exception:
            log.exception("comment_on_pr failed")

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:  # no loop
        pass


async def sync_open_prs(project_id: uuid.UUID) -> int:
    """Create claims for open PRs not already tracked so unconnected agents appear on the board.
    Returns the number of claims created."""
    from app.core.providers import get_providers
    from app.core.verdict import resolve_agent
    from app.db.models import Claim, Project
    from app.db.session import session_scope

    creds = await _creds_for_project(project_id)
    if not creds.ok:
        return 0
    repo = creds.repo
    async with _client(creds.token) as client:
        r = await client.get(f"/repos/{repo}/pulls", params={"state": "open", "per_page": 50})
        r.raise_for_status()
        prs = r.json()

    created = 0
    providers = get_providers()
    for pr in prs:
        from sqlalchemy import select

        async with session_scope() as db:
            tracked = (
                await db.execute(
                    select(Claim.id).where(Claim.project_id == project_id, Claim.pr_number == pr["number"])
                )
            ).first()
            if tracked:
                continue
            login = (pr.get("user") or {}).get("login") or "github"
            agent = await resolve_agent(db, project_id, f"github:{login}", login, bind_owner=False)
            text = f"{pr['title']}\n\n{pr.get('body') or ''}".strip()
            stance = await providers.stance.extract(text)
            embedding = await providers.embeddings.embed(text)
            db.add(
                Claim(
                    project_id=project_id,
                    agent=agent,
                    task=None,
                    intent_text=text,
                    stance=stance.to_dict(),
                    concepts=list(stance.concepts),
                    embedding=embedding,
                    branch=(pr.get("head") or {}).get("ref"),
                    pr_number=pr["number"],
                    status="in_review",
                )
            )
            created += 1
    return created


# -- webhook registration -----------------------------------------------------------


@dataclass
class WebhookStatus:
    registered: bool
    hook_id: int | None = None
    url: str | None = None
    reason: str | None = None


def webhook_url() -> str | None:
    """Where GitHub should deliver: PUBLIC_URL, else FRONTEND_URL when it is not a local address."""
    settings = get_settings()
    base = (settings.public_url or settings.frontend_url or "").rstrip("/")
    if not base or "localhost" in base or "127.0.0.1" in base:
        return None
    return f"{base}/api/webhooks/github"


async def ensure_webhook(project_id: uuid.UUID) -> WebhookStatus:
    """Register the pull_request webhook on the project's repository, or update the one already
    pointing at this server. Each project gets its own secret. Idempotent. Never raises: the
    outcome comes back as a status the UI can show ("connect GitHub first", "needs admin")."""
    from app.core.auth import new_opaque_token
    from app.db.models import Project
    from app.db.session import session_scope

    settings = get_settings()
    if not settings.enable_github:
        return WebhookStatus(False, reason="GitHub integration is disabled (ENABLE_GITHUB)")
    creds = await _creds_for_project(project_id)
    if not creds.repo:
        return WebhookStatus(False, reason="project has no repository")
    if not creds.token:
        return WebhookStatus(False, reason="no GitHub token: an organisation admin must connect GitHub first")
    url = webhook_url()
    if url is None:
        return WebhookStatus(False, reason="backend has no public URL (set PUBLIC_URL); register the webhook by hand")
    try:
        async with session_scope() as db:
            project = await db.get(Project, project_id)
            if project is None:
                return WebhookStatus(False, reason="project not found")
            if not project.webhook_secret:
                project.webhook_secret = new_opaque_token(32)
            secret = project.webhook_secret
        config = {"url": url, "content_type": "json", "secret": secret, "insecure_ssl": "0"}
        async with _client(creds.token) as client:
            r = await client.get(f"/repos/{creds.repo}/hooks", params={"per_page": 100})
            if r.status_code in (403, 404):
                return WebhookStatus(
                    False, url=url,
                    reason=f"GitHub refused ({r.status_code}): the connected account needs admin rights on {creds.repo} to manage webhooks",
                )
            r.raise_for_status()
            existing = next((h for h in r.json() if (h.get("config") or {}).get("url") == url), None)
            if existing:
                r = await client.patch(
                    f"/repos/{creds.repo}/hooks/{existing['id']}",
                    json={"active": True, "events": ["pull_request"], "config": config},
                )
            else:
                r = await client.post(
                    f"/repos/{creds.repo}/hooks",
                    json={"name": "web", "active": True, "events": ["pull_request"], "config": config},
                )
            r.raise_for_status()
            hook_id = int(r.json()["id"])
        async with session_scope() as db:
            project = await db.get(Project, project_id)
            if project is not None:
                project.webhook_id = hook_id
        log.info("webhook %s registered on %s for project %s", hook_id, creds.repo, project_id)
        return WebhookStatus(True, hook_id=hook_id, url=url)
    except Exception as e:
        log.exception("webhook registration failed for project %s", project_id)
        return WebhookStatus(False, url=url, reason=f"{type(e).__name__}: {e}")


async def ensure_webhooks_for_org(org_id: uuid.UUID) -> dict[str, WebhookStatus]:
    """After an admin connects GitHub: register hooks for every live project with a repository."""
    from sqlalchemy import select

    from app.db.models import Project
    from app.db.session import session_scope

    async with session_scope() as db:
        ids = (
            await db.execute(
                select(Project.id).where(Project.org_id == org_id, Project.repo_full_name.is_not(None), Project.archived_at.is_(None))
            )
        ).scalars().all()
    return {str(pid): await ensure_webhook(pid) for pid in ids}


async def webhook_secrets_for_repo(repo_full_name: str) -> list[str]:
    from sqlalchemy import select

    from app.db.models import Project
    from app.db.session import session_scope

    if not repo_full_name:
        return []
    async with session_scope() as db:
        rows = (
            await db.execute(
                select(Project.webhook_secret).where(Project.repo_full_name == repo_full_name, Project.webhook_secret.is_not(None))
            )
        ).scalars().all()
    return [s for s in rows if s]


# -- webhook -----------------------------------------------------------------------


def verify_signature(secret: str | None, body: bytes, signature_header: str | None) -> bool:
    if not secret:
        return True  # no secret configured: accept (dev)
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[len("sha256="):])


async def handle_pull_request_closed(repo_full_name: str, pr_number: int, merged: bool) -> list[uuid.UUID]:
    """Retire every claim tracking this PR. Returns retired claim ids."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db.models import Claim, Project
    from app.db.session import session_scope
    from app.events.bus import get_bus

    retired: list[tuple[uuid.UUID, uuid.UUID]] = []
    async with session_scope() as db:
        projects = (
            await db.execute(select(Project.id).where(Project.repo_full_name == repo_full_name))
        ).scalars().all()
        if not projects:
            return []
        claims = (
            await db.execute(select(Claim).where(Claim.project_id.in_(projects), Claim.pr_number == pr_number))
        ).unique().scalars().all()
        for c in claims:
            c.status = "retired"
            c.resolved_at = datetime.now(timezone.utc)
            retired.append((c.project_id, c.id))
    for pid, cid in retired:
        await get_bus().publish(pid, "claim.retired", {"claim_id": str(cid), "pr_number": pr_number, "merged": merged})
    return [cid for _, cid in retired]
