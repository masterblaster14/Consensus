"""Shared memory: query, write (with dedup), token events and counters."""
from __future__ import annotations

import logging
import math
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import retrieval
from app.core.auth import check_write, current_principal
from app.core.providers import get_providers
from app.core.text import normalize_concept
from app.core.verdict import resolve_agent, resolve_project
from app.db.models import Agent, Claim, Clash, MemoryEntry, TokenEvent
from app.db.session import session_scope
from app.events.bus import get_bus
from app.schemas import CountersOut, MemoryEntryOut, QueryMemoryEntry, QueryMemoryResult, WriteMemoryResult

log = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token). Only used for memory_read accounting."""
    return max(1, math.ceil(len(text) / 4))


async def query_memory(
    *,
    question: str,
    limit: int = 5,
    project_id: uuid.UUID | str | None = None,
    agent_name: str | None = None,
    types: list[str] | None = None,
) -> QueryMemoryResult:
    """Vector search only. No LLM call. Records a memory_read token event."""
    providers = get_providers()
    embedding = await providers.embeddings.embed(question)

    async with session_scope() as db:
        project = await resolve_project(db, project_id)
        hits = await retrieval.similar_memory(db, project.id, embedding, limit=limit, types=types)
        entries = [
            QueryMemoryEntry(
                type=h.entry.type,
                content=h.entry.content,
                source_agent=h.entry.source_agent.name if h.entry.source_agent else None,
                created_at=h.entry.created_at,
                entry_id=h.entry.id,
                similarity=round(h.similarity, 4),
            )
            for h in hits
        ]
        tokens_used = sum(estimate_tokens(e.content) for e in entries) + estimate_tokens(question)

        # token events need an agent row; anonymous reads go to the caller's account agent or "system"
        principal = current_principal.get()
        name = agent_name or (f"{principal.name}'s agent" if principal else "system")
        agent = await resolve_agent(db, project.id, name, None if principal else "system")
        agent_id = agent.id
        db.add(TokenEvent(project_id=project.id, agent_id=agent_id, kind="memory_read", tokens=tokens_used))
        pid = project.id

    await get_bus().publish(
        pid,
        "memory.read",
        {"agent": agent_name, "question": question, "hits": len(entries), "tokens_used": tokens_used},
    )
    return QueryMemoryResult(entries=entries, tokens_used=tokens_used)


async def write_memory(
    *,
    agent_name: str,
    type: str,
    content: str,
    concepts: list[str] | None = None,
    project_id: uuid.UUID | str | None = None,
    related_claim_id: uuid.UUID | None = None,
    axis: str | None = None,
    developer_name: str | None = None,
) -> WriteMemoryResult:
    """Insert unless a near-duplicate (cosine >= DEDUP threshold) already exists."""
    settings = get_settings()
    providers = get_providers()
    embedding = await providers.embeddings.embed(content)
    concepts = _clean_concepts(concepts or [])

    async with session_scope() as db:
        project = await resolve_project(db, project_id)
        check_write(current_principal.get(), project)
        agent = await resolve_agent(db, project.id, agent_name, developer_name)

        hits = await retrieval.similar_memory(db, project.id, embedding, limit=1, types=[type])
        if hits and hits[0].similarity >= settings.dedup_similarity_threshold:
            existing = hits[0].entry
            # link instead of duplicating: merge concepts / claim link onto the existing row
            merged = list(existing.concepts or [])
            for c in concepts:
                if normalize_concept(c) not in {normalize_concept(m) for m in merged}:
                    merged.append(c)
            existing.concepts = merged
            if related_claim_id and not existing.related_claim_id:
                existing.related_claim_id = related_claim_id
            log.info("write_memory deduplicated onto %s (sim=%.3f)", existing.id, hits[0].similarity)
            return WriteMemoryResult(entry_id=existing.id, deduplicated=True)

        entry = MemoryEntry(
            project_id=project.id,
            type=type,
            content=content.strip(),
            concepts=concepts,
            axis=axis,
            embedding=embedding,
            source_agent=agent,
            related_claim_id=related_claim_id,
        )
        db.add(entry)
        await db.flush()
        out = MemoryEntryOut.from_entry(entry)
        pid = project.id

    await get_bus().publish(pid, "memory.written", {"entry": out.model_dump(mode="json")})
    _mirror_to_notion(out)
    return WriteMemoryResult(entry_id=out.id, deduplicated=False)


def _clean_concepts(concepts: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for c in concepts:
        c = str(c).strip()
        if not c:
            continue
        key = normalize_concept(c)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _mirror_to_notion(entry: MemoryEntryOut) -> None:
    """Fire-and-forget; never blocks or fails the write."""
    if entry.type not in ("decision", "dead_end", "ruling"):
        return
    try:
        from app.integrations.notion import push_entry_background

        push_entry_background(entry)
    except Exception:  # pragma: no cover
        log.exception("notion mirror scheduling failed")


async def record_token_event(
    *, agent_name: str, kind: str, tokens: int, project_id: uuid.UUID | str | None = None
) -> uuid.UUID:
    async with session_scope() as db:
        project = await resolve_project(db, project_id)
        check_write(current_principal.get(), project)
        agent = await resolve_agent(db, project.id, agent_name, None)
        ev = TokenEvent(project_id=project.id, agent_id=agent.id, kind=kind, tokens=tokens)
        db.add(ev)
        await db.flush()
        return ev.id


# -- counters ----------------------------------------------------------------------


async def tokens_saved(db: AsyncSession, project_id: uuid.UUID) -> int:
    """For each memory_read event: (average codebase_read size for the project) - (that read's cost),
    floored at zero, summed. One function so it is easy to explain on stage."""
    avg_codebase = (
        await db.execute(
            select(func.avg(TokenEvent.tokens)).where(
                TokenEvent.project_id == project_id, TokenEvent.kind == "codebase_read"
            )
        )
    ).scalar_one()
    if avg_codebase is None:
        return 0
    avg_codebase = float(avg_codebase)
    reads = (
        await db.execute(
            select(TokenEvent.tokens).where(TokenEvent.project_id == project_id, TokenEvent.kind == "memory_read")
        )
    ).scalars().all()
    return int(sum(max(0.0, avg_codebase - r) for r in reads))


async def counters(db: AsyncSession, project_id: uuid.UUID) -> CountersOut:
    saved = await tokens_saved(db, project_id)
    clashes_caught = (
        await db.execute(select(func.count()).select_from(Clash).where(Clash.project_id == project_id))
    ).scalar_one()
    open_clashes = (
        await db.execute(
            select(func.count()).select_from(Clash).where(Clash.project_id == project_id, Clash.status == "open")
        )
    ).scalar_one()
    memory_count = (
        await db.execute(select(func.count()).select_from(MemoryEntry).where(MemoryEntry.project_id == project_id))
    ).scalar_one()
    open_claims = (
        await db.execute(
            select(func.count()).select_from(Claim).where(Claim.project_id == project_id, Claim.status == "open")
        )
    ).scalar_one()
    agents = (
        await db.execute(select(func.count()).select_from(Agent).where(Agent.project_id == project_id))
    ).scalar_one()
    return CountersOut(
        tokens_saved=saved,
        clashes_caught=int(clashes_caught),
        memory_count=int(memory_count),
        open_claims=int(open_claims),
        open_clashes=int(open_clashes),
        agents=int(agents),
    )
