"""Per-user API keys (MCP tokens). The plaintext is returned once, on creation."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import CommittingRoute
from app.api.deps import require_principal
from app.core.auth import Principal, new_api_key
from app.db.models import ApiKey, Project
from app.db.session import get_db
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(prefix="/api/me/api-keys", tags=["api-keys"], route_class=CommittingRoute)


def _mcp_url(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/mcp"


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> list[ApiKeyOut]:
    rows = (await db.execute(select(ApiKey).where(ApiKey.user_id == principal.user_id).order_by(ApiKey.created_at.desc()))).scalars().all()
    return [ApiKeyOut.model_validate(k) for k in rows]


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_key(body: ApiKeyCreate, request: Request, principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> ApiKeyCreated:
    org_id = body.org_id
    if org_id is None:
        if len(principal.org_ids) == 1:
            org_id = principal.org_ids[0]
        else:
            raise HTTPException(status_code=400, detail="org_id is required when you belong to several organisations")
    if not principal.is_member(org_id):
        raise HTTPException(status_code=403, detail="not a member of that organisation")
    if body.project_id is not None:
        project = await db.get(Project, body.project_id)
        if project is None or project.org_id != org_id:
            raise HTTPException(status_code=400, detail="project does not belong to that organisation")

    raw, key_hash, prefix = new_api_key()
    key = ApiKey(user_id=principal.user_id, org_id=org_id, project_id=body.project_id, name=body.name, key_hash=key_hash, prefix=prefix)
    db.add(key)
    await db.flush()
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=raw, mcp_url=_mcp_url(request))


@router.delete("/{key_id}", status_code=204)
async def revoke_key(key_id: uuid.UUID, principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> None:
    key = await db.get(ApiKey, key_id)
    if key is None or key.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="key not found")
    key.revoked_at = datetime.now(timezone.utc)
