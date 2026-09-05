"""Prior-ruling lookup and application.

When a human resolves a hard clash we write a `ruling` memory entry carrying
the note, the shared concepts and the axis. Before escalating a new hard
clash we look for a ruling on the same concept + axis. If one exists, the
agent proceeds with that ruling as context and no human is asked again.
This is what makes human decisions compound.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import concepts_match
from app.db.models import MemoryEntry


@dataclass
class RulingMatch:
    entry: MemoryEntry
    matched_concepts: list[str]


async def find_ruling(
    db: AsyncSession,
    project_id: uuid.UUID,
    axis: str,
    concepts: list[str],
) -> RulingMatch | None:
    """Most recent ruling on `axis` whose concepts overlap `concepts`."""
    if not concepts:
        return None
    stmt = (
        select(MemoryEntry)
        .where(MemoryEntry.project_id == project_id, MemoryEntry.type == "ruling", MemoryEntry.axis == axis)
        .order_by(MemoryEntry.created_at.desc())
        .limit(50)
    )
    rulings = (await db.execute(stmt)).unique().scalars().all()
    for r in rulings:
        matched = [c for c in concepts if any(concepts_match(c, rc) for rc in r.concepts)]
        if matched:
            return RulingMatch(entry=r, matched_concepts=matched)
    return None


def ruling_content(resolution: str, note: str, axis: str, shared: list[str], a_intent: str, b_intent: str) -> str:
    who = {
        "a_proceeds": "the first plan proceeds",
        "b_proceeds": "the second plan proceeds",
        "both_with_note": "both proceed with the note below",
    }.get(resolution, resolution)
    return (
        f"Ruling on {axis} for {', '.join(shared) or 'unspecified concepts'}: {who}. "
        f"Note: {note.strip()} "
        f"(Plan A: {a_intent.strip()[:200]} | Plan B: {b_intent.strip()[:200]})"
    )
