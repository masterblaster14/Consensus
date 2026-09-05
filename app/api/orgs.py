"""Organisations: create (creator becomes admin), members, invites, projects, integrations."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import CommittingRoute
from app.api.deps import get_org, get_org_as_admin, require_principal
from app.config import get_settings
from app.core import memory as memory_core
from app.core.auth import Principal, new_opaque_token, slugify
from app.core.mailer import invite_message, send_email
from app.db.models import Agent, Claim, Clash, Invite, MemoryEntry, Membership, Organization, Project, User
from app.db.session import get_db
from app.mcp.auth import invalidate_token_cache
from app.schemas import (
    InviteCreate,
    InviteOut,
    MemberUpdate,
    MembershipOut,
    NotionConnect,
    OrgCreate,
    OrgOut,
    OrgSummaryOut,
    OrgUpdate,
    ProjectCreateInOrg,
    ProjectOut,
)

router = APIRouter(prefix="/api", tags=["organisations"], route_class=CommittingRoute)


def _org_out(org: Organization, role: str | None) -> OrgOut:
    return OrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        auto_join_domain=org.auto_join_domain,
        created_at=org.created_at,
        role=role,
        integrations={
            "github": {"connected": bool(org.github_token), "connected_by": str(org.github_connected_by) if org.github_connected_by else None},
            "notion": {"connected": bool(org.notion_token), "tasks_db_id": org.notion_tasks_db_id},
        },
    )


def _invite_url(token: str) -> str:
    return f"{get_settings().frontend_url.rstrip('/')}/invite/{token}"


def _membership_out(org: Organization, m: Membership) -> MembershipOut:
    return MembershipOut(
        org_id=m.org_id, org_name=org.name, org_slug=org.slug, role=m.role, status=m.status,
        user_id=m.user_id, user_email=m.user.email, user_name=m.user.name, user_avatar_url=m.user.avatar_url,
    )


async def _other_active_admins(db: AsyncSession, org_id: uuid.UUID, except_user_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(Membership).where(
                    Membership.org_id == org_id,
                    Membership.role == "admin",
                    Membership.status == "active",
                    Membership.user_id != except_user_id,
                )
            )
        ).scalar_one()
    )


# -- orgs -------------------------------------------------------------------------------


@router.get("/orgs", response_model=list[OrgOut])
async def list_my_orgs(principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> list[OrgOut]:
    ms = (await db.execute(select(Membership).where(Membership.user_id == principal.user_id))).scalars().all()
    return [_org_out(m.org, m.role) for m in sorted(ms, key=lambda m: m.org.name.lower())]


@router.post("/orgs", response_model=OrgOut, status_code=201)
async def create_org(body: OrgCreate, principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> OrgOut:
    """The first person who creates an organisation becomes its admin."""
    base = slugify(body.slug or body.name)
    slug = base
    n = 2
    while (await db.execute(select(Organization.id).where(Organization.slug == slug))).first():
        slug = f"{base}-{n}"
        n += 1
    org = Organization(name=body.name.strip(), slug=slug, auto_join_domain=(body.auto_join_domain or "").lower() or None, created_by=principal.user_id)
    db.add(org)
    await db.flush()
    db.add(Membership(org_id=org.id, user_id=principal.user_id, role="admin"))
    await db.flush()
    return _org_out(org, "admin")


@router.get("/orgs/{org_id}", response_model=OrgOut)
async def get_org_route(org: Organization = Depends(get_org), principal: Principal = Depends(require_principal)) -> OrgOut:
    return _org_out(org, "admin" if principal.is_admin(org.id) else "member")


@router.patch("/orgs/{org_id}", response_model=OrgOut)
async def update_org(body: OrgUpdate, org: Organization = Depends(get_org_as_admin), db: AsyncSession = Depends(get_db)) -> OrgOut:
    if body.name is not None:
        org.name = body.name.strip()
    if body.auto_join_domain is not None:
        org.auto_join_domain = body.auto_join_domain.strip().lower() or None
    await db.flush()
    return _org_out(org, "admin")


# -- members -----------------------------------------------------------------------------


@router.get("/orgs/{org_id}/members", response_model=list[MembershipOut])
async def list_members(org: Organization = Depends(get_org), db: AsyncSession = Depends(get_db)) -> list[MembershipOut]:
    ms = (await db.execute(select(Membership).where(Membership.org_id == org.id))).scalars().all()
    return [_membership_out(org, m) for m in sorted(ms, key=lambda m: (m.role != "admin", m.user.name.lower()))]


@router.patch("/orgs/{org_id}/members/{user_id}", response_model=MembershipOut)
async def update_member(user_id: uuid.UUID, body: MemberUpdate, org: Organization = Depends(get_org_as_admin), principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> MembershipOut:
    """Change a member's role and/or status. `restricted` keeps read access but blocks declarations,
    memory writes, handoffs, arbitration and admin actions. The last active admin is protected."""
    if body.role is None and body.status is None:
        raise HTTPException(status_code=400, detail="send role and/or status")
    m = (await db.execute(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="member not found")
    loses_admin = m.is_active_admin and ((body.role is not None and body.role != "admin") or (body.status is not None and body.status != "active"))
    if loses_admin and await _other_active_admins(db, org.id, m.user_id) == 0:
        raise HTTPException(status_code=409, detail="an organisation needs at least one active admin")
    if body.role is not None:
        m.role = body.role
    if body.status is not None:
        m.status = body.status
    await db.flush()
    invalidate_token_cache()  # MCP calls re-resolve the principal immediately
    return _membership_out(org, m)


@router.delete("/orgs/{org_id}/members/{user_id}", status_code=204)
async def remove_member(user_id: uuid.UUID, org: Organization = Depends(get_org), principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> None:
    """Admins can remove anyone; a member can remove themselves (leave)."""
    if user_id != principal.user_id and not principal.is_admin(org.id):
        raise HTTPException(status_code=403, detail="admin role required")
    m = (await db.execute(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user_id))).scalar_one_or_none()
    if m is None:
        raise HTTPException(status_code=404, detail="member not found")
    if m.is_active_admin and await _other_active_admins(db, org.id, m.user_id) == 0:
        raise HTTPException(status_code=409, detail="the last admin cannot leave; promote someone first")
    await db.delete(m)
    invalidate_token_cache()


# -- invites ---------------------------------------------------------------------------------


@router.post("/orgs/{org_id}/invites", response_model=InviteOut, status_code=201)
async def create_invite(body: InviteCreate, org: Organization = Depends(get_org_as_admin), principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> InviteOut:
    """Returns the invite link. Email is optional: with it the link only works for that address."""
    inv = Invite(
        org_id=org.id,
        email=(body.email or "").strip().lower() or None,
        role=body.role,
        token=new_opaque_token(24),
        created_by=principal.user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=get_settings().invite_ttl_days),
    )
    db.add(inv)
    await db.flush()
    url = _invite_url(inv.token)
    email_sent: bool | None = None
    if inv.email:
        subject, text, html = invite_message(org.name, url, principal.name or principal.email, inv.role)
        email_sent = await send_email(inv.email, subject, text, html)
    return InviteOut(id=inv.id, org_id=org.id, org_name=org.name, email=inv.email, role=inv.role, token=inv.token, url=url, expires_at=inv.expires_at, email_sent=email_sent)


@router.get("/orgs/{org_id}/invites", response_model=list[InviteOut])
async def list_invites(org: Organization = Depends(get_org_as_admin), db: AsyncSession = Depends(get_db)) -> list[InviteOut]:
    rows = (await db.execute(select(Invite).where(Invite.org_id == org.id, Invite.accepted_at.is_(None)).order_by(Invite.created_at.desc()))).scalars().all()
    return [InviteOut(id=i.id, org_id=i.org_id, org_name=org.name, email=i.email, role=i.role, token=i.token, url=_invite_url(i.token), expires_at=i.expires_at) for i in rows]


@router.delete("/orgs/{org_id}/invites/{invite_id}", status_code=204)
async def revoke_invite(invite_id: uuid.UUID, org: Organization = Depends(get_org_as_admin), db: AsyncSession = Depends(get_db)) -> None:
    inv = await db.get(Invite, invite_id)
    if inv is None or inv.org_id != org.id:
        raise HTTPException(status_code=404, detail="invite not found")
    await db.delete(inv)


@router.get("/invites/{token}", response_model=InviteOut)
async def preview_invite(token: str, db: AsyncSession = Depends(get_db)) -> InviteOut:
    """Public: what the invite page shows before the user signs in."""
    inv = (await db.execute(select(Invite).where(Invite.token == token))).scalar_one_or_none()
    if inv is None or inv.accepted_at is not None or inv.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="invite is invalid, used or expired")
    return InviteOut(id=inv.id, org_id=inv.org_id, org_name=inv.org.name, email=inv.email, role=inv.role, expires_at=inv.expires_at)


@router.post("/invites/{token}/accept", response_model=OrgOut)
async def accept_invite(token: str, principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> OrgOut:
    inv = (await db.execute(select(Invite).where(Invite.token == token))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if inv is None or inv.accepted_at is not None or inv.expires_at < now:
        raise HTTPException(status_code=404, detail="invite is invalid, used or expired")
    if inv.email and inv.email != principal.email.lower():
        raise HTTPException(status_code=403, detail=f"this invite is for {inv.email}")
    m = (await db.execute(select(Membership).where(Membership.org_id == inv.org_id, Membership.user_id == principal.user_id))).scalar_one_or_none()
    if m is None:
        db.add(Membership(org_id=inv.org_id, user_id=principal.user_id, role=inv.role))
        role = inv.role
    else:
        role = m.role
    inv.accepted_at = now
    inv.accepted_by = principal.user_id
    await db.flush()
    return _org_out(inv.org, role)


# -- projects in an org ---------------------------------------------------------------------


@router.get("/orgs/{org_id}/projects", response_model=list[ProjectOut])
async def list_org_projects(
    org: Organization = Depends(get_org), include_archived: bool = Query(default=False), db: AsyncSession = Depends(get_db)
) -> list[ProjectOut]:
    stmt = select(Project).where(Project.org_id == org.id).order_by(Project.created_at)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    rows = (await db.execute(stmt)).scalars().all()
    return [ProjectOut.model_validate(p) for p in rows]


async def _org_project(db: AsyncSession, org: Organization, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.org_id != org.id:
        raise HTTPException(status_code=404, detail="project not found in this organisation")
    return project


@router.delete("/orgs/{org_id}/projects/{project_id}", status_code=204)
async def archive_org_project(project_id: uuid.UUID, org: Organization = Depends(get_org_as_admin), db: AsyncSession = Depends(get_db)) -> None:
    """Soft delete (admin). Same as DELETE /api/projects/{id}: hidden from lists, rejects writes, history kept."""
    project = await _org_project(db, org, project_id)
    if project.archived_at is None:
        project.archived_at = datetime.now(timezone.utc)
        await db.flush()


@router.post("/orgs/{org_id}/projects/{project_id}/restore", response_model=ProjectOut)
async def restore_org_project(project_id: uuid.UUID, org: Organization = Depends(get_org_as_admin), db: AsyncSession = Depends(get_db)) -> ProjectOut:
    project = await _org_project(db, org, project_id)
    project.archived_at = None
    await db.flush()
    return ProjectOut.model_validate(project)


@router.get("/orgs/{org_id}/summary", response_model=OrgSummaryOut)
async def org_summary(org: Organization = Depends(get_org), db: AsyncSession = Depends(get_db)) -> OrgSummaryOut:
    """Admin dashboard tiles in one call. Archived projects and their agents are excluded."""
    live = select(Project.id).where(Project.org_id == org.id, Project.archived_at.is_(None))
    pids = list((await db.execute(live)).scalars().all())

    async def count(stmt) -> int:
        return int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())

    repositories = await count(live.where(Project.repo_full_name.is_not(None)))
    members = await count(select(Membership.id).where(Membership.org_id == org.id))
    if not pids:
        return OrgSummaryOut(projects=0, repositories=repositories, members=members, agents=0, active_agents=0, open_claims=0, open_clashes=0, memory_count=0, tokens_saved=0)
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    return OrgSummaryOut(
        projects=len(pids),
        repositories=repositories,
        members=members,
        agents=await count(select(Agent.id).where(Agent.project_id.in_(pids))),
        active_agents=await count(select(Agent.id).where(Agent.project_id.in_(pids), Agent.last_seen >= since)),
        open_claims=await count(select(Claim.id).where(Claim.project_id.in_(pids), Claim.status == "open")),
        open_clashes=await count(select(Clash.id).where(Clash.project_id.in_(pids), Clash.status == "open")),
        memory_count=await count(select(MemoryEntry.id).where(MemoryEntry.project_id.in_(pids))),
        tokens_saved=sum([await memory_core.tokens_saved(db, pid) for pid in pids]),
    )


@router.post("/orgs/{org_id}/projects", response_model=ProjectOut, status_code=201)
async def create_org_project(body: ProjectCreateInOrg, org: Organization = Depends(get_org), db: AsyncSession = Depends(get_db)) -> ProjectOut:
    project = Project(org_id=org.id, name=body.name.strip(), repo_full_name=(body.repo_full_name or "").strip() or None)
    db.add(project)
    await db.flush()
    return ProjectOut.model_validate(project)


# -- integrations (admin) ----------------------------------------------------------------------


@router.post("/orgs/{org_id}/integrations/github/connect", response_model=OrgOut)
async def connect_github(org: Organization = Depends(get_org_as_admin), principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> OrgOut:
    """Use the calling admin's GitHub OAuth token (repo scope) for this org's PRs and comments."""
    user = await db.get(User, principal.user_id)
    if user is None or not user.github_access_token:
        raise HTTPException(status_code=409, detail="sign in with GitHub first; no GitHub token on your account")
    org.github_token = user.github_access_token
    org.github_connected_by = user.id
    await db.flush()
    return _org_out(org, "admin")


@router.delete("/orgs/{org_id}/integrations/github", response_model=OrgOut)
async def disconnect_github(org: Organization = Depends(get_org_as_admin), db: AsyncSession = Depends(get_db)) -> OrgOut:
    org.github_token = None
    org.github_connected_by = None
    await db.flush()
    return _org_out(org, "admin")


@router.get("/orgs/{org_id}/integrations/github/repos")
async def list_github_repos(org: Organization = Depends(get_org), principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> list[dict]:
    """Repos the connected GitHub token can see, for the 'create project' picker."""
    import httpx

    token = org.github_token
    if not token:
        user = await db.get(User, principal.user_id)
        token = user.github_access_token if user else None
    if not token:
        raise HTTPException(status_code=409, detail="no GitHub token available")
    async with httpx.AsyncClient(timeout=15.0, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}) as client:
        r = await client.get("https://api.github.com/user/repos", params={"per_page": 100, "sort": "updated", "affiliation": "owner,collaborator,organization_member"})
        r.raise_for_status()
    return [{"full_name": x["full_name"], "private": x["private"], "default_branch": x.get("default_branch")} for x in r.json()]


@router.put("/orgs/{org_id}/integrations/notion", response_model=OrgOut)
async def connect_notion(body: NotionConnect, org: Organization = Depends(get_org_as_admin), db: AsyncSession = Depends(get_db)) -> OrgOut:
    """Notion internal integrations have no OAuth: the admin pastes the token and the tasks database id."""
    org.notion_token = body.notion_token.strip()
    org.notion_tasks_db_id = body.notion_tasks_db_id.strip()
    await db.flush()
    return _org_out(org, "admin")


@router.delete("/orgs/{org_id}/integrations/notion", response_model=OrgOut)
async def disconnect_notion(org: Organization = Depends(get_org_as_admin), db: AsyncSession = Depends(get_db)) -> OrgOut:
    org.notion_token = None
    org.notion_tasks_db_id = None
    await db.flush()
    return _org_out(org, "admin")
