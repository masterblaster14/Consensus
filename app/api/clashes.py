"""GET /api/projects/{id}/clashes and POST /api/clashes/{id}/resolve (arbitration)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import CommittingRoute
from app.api.deps import get_project, optional_principal, require_access_to_project_id
from app.core import arbitration
from app.core import verdict as verdict_core
from app.core.auth import Principal
from app.db.models import Clash, Project
from app.db.session import get_db
from app.schemas import CheckVerdictResult, ClashOut, MemoryEntryOut, ResolveClashRequest

router = APIRouter(prefix="/api", tags=["clashes"], route_class=CommittingRoute)


@router.get("/projects/{project_id}/clashes", response_model=list[ClashOut])
async def list_clashes(
    project: Project = Depends(get_project),
    status: str | None = Query(default=None, description="open | resolved | auto_resolved; omit for all"),
    severity: str | None = Query(default=None, description="hard | soft"),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[ClashOut]:
    stmt = select(Clash).where(Clash.project_id == project.id).order_by(Clash.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Clash.status == status)
    if severity:
        stmt = stmt.where(Clash.severity == severity)
    rows = (await db.execute(stmt)).unique().scalars().all()
    return [ClashOut.from_clash(c) for c in rows]


async def _load_clash(clash_id: uuid.UUID, principal: Principal | None, db: AsyncSession) -> Clash:
    clash = await db.get(Clash, clash_id)
    if clash is None:
        raise HTTPException(status_code=404, detail="clash not found")
    await require_access_to_project_id(db, principal, clash.project_id)
    return clash


@router.get("/clashes/{clash_id}", response_model=ClashOut)
async def get_clash(clash_id: uuid.UUID, principal: Principal | None = Depends(optional_principal), db: AsyncSession = Depends(get_db)) -> ClashOut:
    return ClashOut.from_clash(await _load_clash(clash_id, principal, db))


@router.get("/clashes/{clash_id}/verdict", response_model=CheckVerdictResult)
async def clash_verdict(clash_id: uuid.UUID, wait_seconds: int = Query(default=0, ge=0, le=600), principal: Principal | None = Depends(optional_principal), db: AsyncSession = Depends(get_db)) -> CheckVerdictResult:
    """REST mirror of the check_verdict MCP tool (long-polls when wait_seconds > 0)."""
    await _load_clash(clash_id, principal, db)
    try:
        return await verdict_core.check_verdict(clash_id, wait_seconds=wait_seconds)
    except verdict_core.ClashNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


class ResolveResponse(ClashOut):
    ruling: MemoryEntryOut | None = None


@router.post("/clashes/{clash_id}/resolve", response_model=ResolveResponse)
async def resolve_clash(clash_id: uuid.UUID, body: ResolveClashRequest, principal: Principal | None = Depends(optional_principal), db: AsyncSession = Depends(get_db)) -> ResolveResponse:
    """Arbitration. `a_proceeds` = the earlier claim (claim_a) proceeds; `b_proceeds` = the newer claim
    (claim_b, the one that received `wait`) proceeds. Writes a ruling to memory and releases the waiter.

    Who may resolve: an org admin, or a member who owns one of the two agents involved."""
    clash = await _load_clash(clash_id, principal, db)
    resolved_by = body.resolved_by
    if principal is not None:
        project = await db.get(Project, clash.project_id)
        owns_agent = principal.user_id in {clash.claim_a.agent.user_id, clash.claim_b.agent.user_id}
        if not (principal.is_admin(project.org_id) or owns_agent):
            raise HTTPException(status_code=403, detail="only an admin or the owner of an involved agent can resolve this clash")
        resolved_by = principal.email if body.resolved_by in ("", "human") else body.resolved_by
    db.expunge(clash)
    try:
        clash_out, ruling = await arbitration.resolve_clash(
            clash_id, resolution=body.resolution, note=body.note, resolved_by=resolved_by
        )
    except verdict_core.ClashNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except arbitration.ClashAlreadyResolved as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ResolveResponse(**clash_out.model_dump(), ruling=ruling)
