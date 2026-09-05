"""Shared FastAPI dependencies: authentication and project access."""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.auth import AuthError, Forbidden, Principal, current_principal, principal_from_bearer
from app.db.models import Organization, Project
from app.db.session import get_db


def _bearer_from(request: Request | WebSocket) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # WebSocket clients cannot set headers from a browser; allow ?token=
    token = request.query_params.get("token")
    return token.strip() if token else None


async def optional_principal(request: Request, db: AsyncSession = Depends(get_db)) -> Principal | None:
    token = _bearer_from(request)
    if not token:
        current_principal.set(None)
        return None
    try:
        p = await principal_from_bearer(db, token)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    current_principal.set(p)
    return p


async def require_principal(p: Principal | None = Depends(optional_principal)) -> Principal:
    if p is None:
        raise HTTPException(status_code=401, detail="authentication required", headers={"WWW-Authenticate": "Bearer"})
    return p


async def get_project(
    project_id: uuid.UUID,
    principal: Principal | None = Depends(optional_principal),
    db: AsyncSession = Depends(get_db),
) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"project {project_id} not found")
    settings = get_settings()
    if principal is None:
        if settings.mcp_auth_required:
            raise HTTPException(status_code=401, detail="authentication required", headers={"WWW-Authenticate": "Bearer"})
        return project
    if project.org_id is None:
        if settings.dev_auth:
            return project
        raise HTTPException(status_code=403, detail="project has no organisation")
    if not principal.is_member(project.org_id):
        raise HTTPException(status_code=403, detail="not a member of this project's organisation")
    return project


async def require_access_to_project_id(db: AsyncSession, principal: Principal | None, project_id: uuid.UUID) -> Project:
    """Same rules as get_project, for routes addressed by claim/clash id."""
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    settings = get_settings()
    if principal is None:
        if settings.mcp_auth_required:
            raise HTTPException(status_code=401, detail="authentication required", headers={"WWW-Authenticate": "Bearer"})
        return project
    if project.org_id is None:
        if settings.dev_auth:
            return project
        raise HTTPException(status_code=403, detail="project has no organisation")
    if not principal.is_member(project.org_id):
        raise HTTPException(status_code=403, detail="not a member of this project's organisation")
    return project


async def get_org(
    org_id: uuid.UUID,
    principal: Principal = Depends(require_principal),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="organisation not found")
    if not principal.is_member(org.id):
        raise HTTPException(status_code=403, detail="not a member of this organisation")
    return org


async def get_org_as_admin(
    org: Organization = Depends(get_org), principal: Principal = Depends(require_principal)
) -> Organization:
    if not principal.is_admin(org.id):
        raise HTTPException(status_code=403, detail="admin role required")
    return org


def http_from_auth_error(e: Exception) -> HTTPException:
    if isinstance(e, AuthError):
        return HTTPException(status_code=401, detail=str(e))
    if isinstance(e, Forbidden):
        return HTTPException(status_code=403, detail=str(e))
    return HTTPException(status_code=500, detail=str(e))
