"""GET /api/projects/{id}/memory?type=&q="""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import CommittingRoute
from app.api.deps import get_project
from app.core import memory as memory_core
from app.db.models import MemoryEntry, Project
from app.db.session import get_db
from app.schemas import MemoryEntryOut, QueryMemoryResult, WriteMemoryRequest, WriteMemoryResult

router = APIRouter(prefix="/api", tags=["memory"], route_class=CommittingRoute)


@router.get("/projects/{project_id}/memory", response_model=list[MemoryEntryOut])
async def list_memory(
    project: Project = Depends(get_project),
    type: str | None = Query(default=None, description="discovery | decision | dead_end | ruling | handoff"),
    q: str | None = Query(default=None, description="semantic query; when set, results are ranked by similarity"),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[MemoryEntryOut]:
    if q:
        from app.core import retrieval
        from app.core.providers import get_providers

        embedding = await get_providers().embeddings.embed(q)
        hits = await retrieval.similar_memory(db, project.id, embedding, limit=limit, types=[type] if type else None)
        return [MemoryEntryOut.from_entry(h.entry) for h in hits]

    stmt = select(MemoryEntry).where(MemoryEntry.project_id == project.id).order_by(MemoryEntry.created_at.desc()).limit(limit)
    if type:
        stmt = stmt.where(MemoryEntry.type == type)
    rows = (await db.execute(stmt)).unique().scalars().all()
    return [MemoryEntryOut.from_entry(e) for e in rows]


@router.post("/projects/{project_id}/memory", response_model=WriteMemoryResult, status_code=201)
async def write_memory_via_rest(body: WriteMemoryRequest, project: Project = Depends(get_project)) -> WriteMemoryResult:
    """REST mirror of the write_memory MCP tool."""
    return await memory_core.write_memory(
        agent_name=body.agent_name, type=body.type, content=body.content, concepts=body.concepts, project_id=project.id
    )


@router.get("/projects/{project_id}/memory/query", response_model=QueryMemoryResult)
async def query_memory_via_rest(
    project: Project = Depends(get_project),
    question: str = Query(...),
    limit: int = Query(default=5, ge=1, le=25),
    agent_name: str | None = Query(default=None),
) -> QueryMemoryResult:
    """REST mirror of the query_memory MCP tool (records a memory_read token event)."""
    return await memory_core.query_memory(question=question, limit=limit, project_id=project.id, agent_name=agent_name)
