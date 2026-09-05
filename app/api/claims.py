"""GET /api/projects/{id}/claims"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import CommittingRoute
from app.api.deps import get_project, http_from_auth_error, optional_principal, require_access_to_project_id
from app.core import claims as claims_core
from app.core import handoff as handoff_core
from app.core.auth import AuthError, Forbidden, Principal
from app.db.models import Claim, Project
from app.db.session import get_db
from app.schemas import ClaimOut, FileHandoffResult, WithdrawRequest, WithdrawResult

router = APIRouter(prefix="/api", tags=["claims"], route_class=CommittingRoute)


@router.get("/projects/{project_id}/claims", response_model=list[ClaimOut])
async def list_claims(
    project: Project = Depends(get_project),
    status: str | None = Query(default=None, description="open | in_review | retired; omit for all"),
    agent: str | None = Query(default=None, description="filter by agent name"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[ClaimOut]:
    stmt = select(Claim).where(Claim.project_id == project.id).order_by(Claim.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Claim.status == status)
    rows = (await db.execute(stmt)).unique().scalars().all()
    if agent:
        rows = [c for c in rows if c.agent and c.agent.name == agent]
    return [ClaimOut.from_claim(c) for c in rows]


@router.get("/claims/{claim_id}", response_model=ClaimOut)
async def get_claim(claim_id: uuid.UUID, principal: Principal | None = Depends(optional_principal), db: AsyncSession = Depends(get_db)) -> ClaimOut:
    claim = await db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    await require_access_to_project_id(db, principal, claim.project_id)
    return ClaimOut.from_claim(claim)


@router.post("/claims/{claim_id}/withdraw", response_model=WithdrawResult)
async def withdraw_via_rest(claim_id: uuid.UUID, body: WithdrawRequest, principal: Principal | None = Depends(optional_principal), db: AsyncSession = Depends(get_db)) -> WithdrawResult:
    """REST mirror of the withdraw_claim MCP tool. Owner of the agent or an org admin. Idempotent."""
    try:
        return await claims_core.withdraw_claim(claim_id, reason=body.reason)
    except claims_core.ClaimNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (AuthError, Forbidden) as e:
        raise http_from_auth_error(e)


@router.post("/claims/{claim_id}/handoff", response_model=FileHandoffResult)
async def handoff_via_rest(claim_id: uuid.UUID, body: dict, principal: Principal | None = Depends(optional_principal), db: AsyncSession = Depends(get_db)) -> FileHandoffResult:
    """REST mirror of the file_handoff MCP tool."""
    claim = await db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    await require_access_to_project_id(db, principal, claim.project_id)
    db.expunge(claim)
    try:
        return await handoff_core.file_handoff(
            claim_id=claim_id,
            changed=body.get("changed", []),
            untouched=body.get("untouched", []),
            assumptions=body.get("assumptions", []),
            uncertainties=body.get("uncertainties", []),
        )
    except handoff_core.ClaimNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (AuthError, Forbidden) as e:
        raise http_from_auth_error(e)
