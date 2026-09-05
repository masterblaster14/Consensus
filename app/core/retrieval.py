"""Vector search over claims and memory (pgvector, cosine)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Claim, MemoryEntry


@dataclass
class ScoredClaim:
    claim: Claim
    similarity: float


@dataclass
class ScoredMemory:
    entry: MemoryEntry
    similarity: float


async def similar_open_claims(
    db: AsyncSession,
    project_id: uuid.UUID,
    embedding: list[float],
    exclude_agent_id: uuid.UUID,
    limit: int = 10,
) -> list[ScoredClaim]:
    """Top-N open claims in the project by another agent, nearest first."""
    distance = Claim.embedding.cosine_distance(embedding)
    stmt = (
        select(Claim, distance.label("distance"))
        .where(Claim.project_id == project_id, Claim.status == "open", Claim.agent_id != exclude_agent_id)
        .where(Claim.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).unique().all()
    return [ScoredClaim(claim=c, similarity=1.0 - float(d)) for c, d in rows]


async def similar_memory(
    db: AsyncSession,
    project_id: uuid.UUID,
    embedding: list[float],
    limit: int = 5,
    types: list[str] | None = None,
) -> list[ScoredMemory]:
    distance = MemoryEntry.embedding.cosine_distance(embedding)
    stmt = (
        select(MemoryEntry, distance.label("distance"))
        .where(MemoryEntry.project_id == project_id, MemoryEntry.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    if types:
        stmt = stmt.where(MemoryEntry.type.in_(types))
    rows = (await db.execute(stmt)).unique().all()
    return [ScoredMemory(entry=e, similarity=1.0 - float(d)) for e, d in rows]
