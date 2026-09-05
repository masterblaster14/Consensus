"""Projects, agents, counters, and REST mirrors of the agent tools (for dashboards / smoke tests)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import CommittingRoute
from app.api.deps import get_project, http_from_auth_error, optional_principal, require_principal
from app.config import get_settings
from app.core import memory as memory_core
from app.core import verdict as verdict_core
from app.core.auth import AuthError, Forbidden, Principal
from app.db.models import Agent, Project, Task
from app.db.session import get_db
from app.schemas import (
    AgentOut,
    CountersOut,
    DeclareRequest,
    DeclareResult,
    ProjectCreate,
    ProjectOut,
    TaskOut,
    TokenEventCreate,
)

router = APIRouter(prefix="/api", tags=["projects"], route_class=CommittingRoute)


@router.get("/projects", response_model=list[ProjectOut])
async def list_projects(principal: Principal | None = Depends(optional_principal), db: AsyncSession = Depends(get_db)) -> list[ProjectOut]:
    """Projects in the caller's organisations. Unauthenticated: only allowed when MCP_AUTH_REQUIRED=false."""
    settings = get_settings()
    if principal is None:
        if settings.mcp_auth_required:
            raise HTTPException(status_code=401, detail="authentication required", headers={"WWW-Authenticate": "Bearer"})
        rows = (await db.execute(select(Project).order_by(Project.created_at))).scalars().all()
    elif principal.org_ids:
        rows = (await db.execute(select(Project).where(Project.org_id.in_(principal.org_ids)).order_by(Project.created_at))).scalars().all()
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


@router.get("/projects/{project_id}/agents", response_model=list[AgentOut])
async def list_agents(project: Project = Depends(get_project), db: AsyncSession = Depends(get_db)) -> list[AgentOut]:
    rows = (await db.execute(select(Agent).where(Agent.project_id == project.id).order_by(Agent.name))).scalars().all()
    return [AgentOut.model_validate(a) for a in rows]


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(project: Project = Depends(get_project), db: AsyncSession = Depends(get_db)) -> list[TaskOut]:
    rows = (await db.execute(select(Task).where(Task.project_id == project.id).order_by(Task.title))).scalars().all()
    return [TaskOut.model_validate(t) for t in rows]


@router.get("/projects/{project_id}/counters", response_model=CountersOut)
async def get_counters(project: Project = Depends(get_project), db: AsyncSession = Depends(get_db)) -> CountersOut:
    return await memory_core.counters(db, project.id)


@router.post("/projects/{project_id}/token-events", status_code=201)
async def create_token_event(body: TokenEventCreate, project: Project = Depends(get_project)) -> dict:
    event_id = await memory_core.record_token_event(
        agent_name=body.agent_name, kind=body.kind, tokens=body.tokens, project_id=project.id
    )
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
