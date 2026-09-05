"""Projects, agents, tasks, activity, counters, and REST mirrors of the agent tools (for dashboards / smoke tests)."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import CommittingRoute
from app.api.deps import get_project, http_from_auth_error, optional_principal, require_principal
from app.config import get_settings
from app.core import memory as memory_core
from app.core import verdict as verdict_core
from app.core.auth import AuthError, Forbidden, Principal, check_write
from app.db.models import Agent, Claim, Event, Project, Task
from app.db.session import get_db
from app.schemas import (
    AgentOut,
    CountersOut,
    DeclareRequest,
    DeclareResult,
    EventFrame,
    ProjectCreate,
    ProjectOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TokenEventCreate,
)

router = APIRouter(prefix="/api", tags=["projects"], route_class=CommittingRoute)


def _check_write_http(principal: Principal | None, project: Project) -> None:
    """403 for restricted members and archived projects (see app.core.auth.check_write)."""
    try:
        check_write(principal, project)
    except Forbidden as e:
        raise HTTPException(status_code=403, detail=str(e))


async def _require_project_admin(project: Project, principal: Principal) -> None:
    if project.org_id is None:
        if get_settings().dev_auth:
            return
        raise HTTPException(status_code=403, detail="project has no organisation")
    if not principal.is_admin(project.org_id):
        raise HTTPException(status_code=403, detail="admin role required")


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(
    include_archived: bool = Query(default=False),
    principal: Principal | None = Depends(optional_principal),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectOut]:
    """Projects in the caller's organisations. Archived ones are hidden unless include_archived=true.
    Unauthenticated: only allowed when MCP_AUTH_REQUIRED=false."""
    settings = get_settings()
    stmt = select(Project).order_by(Project.created_at)
    if not include_archived:
        stmt = stmt.where(Project.archived_at.is_(None))
    if principal is None:
        if settings.mcp_auth_required:
            raise HTTPException(status_code=401, detail="authentication required", headers={"WWW-Authenticate": "Bearer"})
        rows = (await db.execute(stmt)).scalars().all()
    elif principal.org_ids:
        rows = (await db.execute(stmt.where(Project.org_id.in_(principal.org_ids)))).scalars().all()
    else:
        rows = []
    return [ProjectOut.model_validate(p) for p in rows]


@router.post("/projects", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> ProjectOut:
    """Create a project in one of the caller's organisations (org_id optional when they belong to exactly one)."""
    org_id = body.org_id
    if org_id is None:
        if len(principal.org_ids) != 1:
            raise HTTPException(status_code=400, detail="org_id is required")
        org_id = principal.org_ids[0]
    if not principal.is_member(org_id):
        raise HTTPException(status_code=403, detail="not a member of that organisation")
    project = Project(org_id=org_id, name=body.name, repo_full_name=body.repo_full_name)
    if body.id:
        project.id = body.id
    db.add(project)
    await db.flush()
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}", response_model=ProjectOut)
async def get_project_route(project: Project = Depends(get_project)) -> ProjectOut:
    return ProjectOut.model_validate(project)


@router.delete("/projects/{project_id}", status_code=204)
async def archive_project(
    project: Project = Depends(get_project), principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)
) -> None:
    """Soft delete (admin): the project disappears from lists and rejects declarations and writes.
    Reads keep working so history stays visible. Undo with POST /api/projects/{id}/restore."""
    await _require_project_admin(project, principal)
    if project.archived_at is None:
        project.archived_at = datetime.now(timezone.utc)
        await db.flush()


@router.post("/projects/{project_id}/restore", response_model=ProjectOut)
async def restore_project(
    project: Project = Depends(get_project), principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)
) -> ProjectOut:
    await _require_project_admin(project, principal)
    project.archived_at = None
    await db.flush()
    return ProjectOut.model_validate(project)


@router.get("/projects/{project_id}/agents", response_model=list[AgentOut])
async def list_agents(project: Project = Depends(get_project), db: AsyncSession = Depends(get_db)) -> list[AgentOut]:
    """Agents with their current work: status (working / reviewing / idle), open claim count and the
    newest non-retired claim, all derived from the claims table."""
    rows = (await db.execute(select(Agent).where(Agent.project_id == project.id).order_by(Agent.name))).scalars().all()
    claims = (
        await db.execute(
            select(Claim)
            .where(Claim.project_id == project.id, Claim.status != "retired")
            .order_by(Claim.created_at.desc())
        )
    ).unique().scalars().all()
    by_agent: dict[uuid.UUID, list[Claim]] = defaultdict(list)
    for c in claims:
        by_agent[c.agent_id].append(c)
    return [AgentOut.from_agent(a, by_agent.get(a.id)) for a in rows]


# -- tasks ---------------------------------------------------------------------------------------


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    project: Project = Depends(get_project),
    status: str | None = Query(default=None, description="open | in_progress | done; omit for all"),
    db: AsyncSession = Depends(get_db),
) -> list[TaskOut]:
    stmt = select(Task).where(Task.project_id == project.id).order_by(Task.created_at.desc().nulls_last(), Task.title)
    if status:
        stmt = stmt.where(Task.status == status)
    rows = (await db.execute(stmt)).unique().scalars().all()
    return [TaskOut.from_task(t) for t in rows]


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    body: TaskCreate,
    project: Project = Depends(get_project),
    principal: Principal | None = Depends(optional_principal),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    """Manual task (Notion sync and declared task_refs also create tasks). external_ref is what agents
    pass as task_ref in declare_intent; it must be unique within the project."""
    _check_write_http(principal, project)
    ref = (body.external_ref or "").strip() or None
    if ref:
        dup = (await db.execute(select(Task.id).where(Task.project_id == project.id, Task.external_ref == ref))).first()
        if dup:
            raise HTTPException(status_code=409, detail=f"a task with external_ref {ref!r} already exists")
    t = Task(project_id=project.id, title=body.title.strip(), external_ref=ref, status=body.status, assignee=None)
    db.add(t)
    await db.flush()
    return TaskOut.from_task(t)


async def _load_task(db: AsyncSession, project: Project, task_id: uuid.UUID) -> Task:
    t = await db.get(Task, task_id)
    if t is None or t.project_id != project.id:
        raise HTTPException(status_code=404, detail="task not found")
    return t


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    project: Project = Depends(get_project),
    principal: Principal | None = Depends(optional_principal),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    _check_write_http(principal, project)
    t = await _load_task(db, project, task_id)
    if body.title is not None:
        t.title = body.title.strip()
    if body.external_ref is not None:
        t.external_ref = body.external_ref.strip() or None
    if body.status is not None:
        t.status = body.status
    if body.assignee_agent is not None:
        name = body.assignee_agent.strip()
        if not name:
            t.assignee = None
            t.assignee_agent_id = None
        else:
            agent = (
                await db.execute(select(Agent).where(Agent.project_id == project.id, Agent.name == name))
            ).scalar_one_or_none()
            if agent is None:
                raise HTTPException(status_code=404, detail=f"no agent named {name!r} in this project")
            t.assignee = agent
            t.assignee_agent_id = agent.id
    await db.flush()
    return TaskOut.from_task(t)


@router.delete("/projects/{project_id}/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: uuid.UUID,
    project: Project = Depends(get_project),
    principal: Principal | None = Depends(optional_principal),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Claims that referenced the task keep their history; only the link is cleared."""
    _check_write_http(principal, project)
    t = await _load_task(db, project, task_id)
    await db.execute(update(Claim).where(Claim.task_id == t.id).values(task_id=None))
    await db.delete(t)


# -- activity ------------------------------------------------------------------------------------


@router.get("/projects/{project_id}/activity", response_model=list[EventFrame])
async def list_activity(
    project: Project = Depends(get_project),
    limit: int = Query(default=50, ge=1, le=500),
    before: datetime | None = Query(default=None, description="cursor: only events with ts older than this ISO timestamp"),
    type: str | None = Query(default=None, description="comma-separated event types, e.g. clash.opened,clash.resolved"),
    db: AsyncSession = Depends(get_db),
) -> list[EventFrame]:
    """Persisted event frames (same shape as the WebSocket stream), newest first. Page with `before`
    set to the `ts` of the last frame you have."""
    stmt = select(Event).where(Event.project_id == project.id).order_by(Event.created_at.desc(), Event.id).limit(limit)
    if before is not None:
        stmt = stmt.where(Event.created_at < before)
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        if types:
            stmt = stmt.where(Event.type.in_(types))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        EventFrame(
            id=str(e.id),
            type=e.type,
            project_id=str(e.project_id),
            ts=e.created_at.isoformat() if e.created_at else "",
            data=e.data or {},
        )
        for e in rows
    ]


@router.get("/projects/{project_id}/counters", response_model=CountersOut)
async def get_counters(project: Project = Depends(get_project), db: AsyncSession = Depends(get_db)) -> CountersOut:
    return await memory_core.counters(db, project.id)


@router.post("/projects/{project_id}/token-events", status_code=201)
async def create_token_event(body: TokenEventCreate, project: Project = Depends(get_project)) -> dict:
    try:
        event_id = await memory_core.record_token_event(
            agent_name=body.agent_name, kind=body.kind, tokens=body.tokens, project_id=project.id
        )
    except (AuthError, Forbidden) as e:
        raise http_from_auth_error(e)
    return {"event_id": str(event_id)}


@router.post("/projects/{project_id}/declare", response_model=DeclareResult)
async def declare_via_rest(body: DeclareRequest, project: Project = Depends(get_project)) -> DeclareResult:
    """REST mirror of the declare_intent MCP tool (handy for dashboards and smoke tests)."""
    try:
        return await verdict_core.declare_intent(
            agent_name=body.agent_name,
            developer_name=body.developer_name,
            plan_text=body.plan_text,
            task_ref=body.task_ref,
            branch=body.branch,
            project_id=project.id,
            wait_seconds=body.wait_seconds,
        )
    except verdict_core.ProjectNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (AuthError, Forbidden) as e:
        raise http_from_auth_error(e)


@router.post("/projects/{project_id}/integrations/github/sync")
async def github_sync(project: Project = Depends(get_project)) -> dict:
    from app.integrations.github import sync_open_prs

    created = await sync_open_prs(project.id)
    return {"claims_created": created}


@router.post("/projects/{project_id}/integrations/notion/sync")
async def notion_sync(project: Project = Depends(get_project)) -> dict:
    from app.integrations.notion import sync_tasks

    upserted = await sync_tasks(project.id)
    return {"tasks_upserted": upserted}


@router.get("/projects/{project_id}/verdicts")
async def list_verdicts(
    project: Project = Depends(get_project), limit: int = 50, db: AsyncSession = Depends(get_db)
) -> list[dict]:
    """Verdict log with inputs, newest first. For explaining why a clash fired."""
    from app.db.models import VerdictLog

    rows = (
        await db.execute(
            select(VerdictLog).where(VerdictLog.project_id == project.id).order_by(VerdictLog.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": str(v.id),
            "claim_id": str(v.claim_id) if v.claim_id else None,
            "verdict": v.verdict,
            "duration_ms": v.duration_ms,
            "detail": v.detail,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in rows
    ]
