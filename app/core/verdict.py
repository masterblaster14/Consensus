"""The declare flow, end to end. Spec section 7, in exactly that order.

 1. resolve/create agent
 2. stance extraction            (core/stance.py, the only LLM call)
 3. embed the plan text
 4. retrieve candidates           (core/retrieval.py, in parallel)
 5. compare each candidate        (core/clash.py, deterministic)
 6. severity
 7. prior-ruling short circuit    (core/rulings.py)
 8. persist claim + clash rows
 9. publish events
10. return verdict

Steps 4-8 run under a Redis lock on the project so two simultaneous
declarations cannot both pass each other.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core import retrieval
from app.core.auth import Forbidden, Principal, current_principal, default_project_for, require_project_access
from app.core.clash import Comparison, compare, overall_severity
from app.core.providers import get_providers
from app.core.rulings import RulingMatch, find_ruling
from app.core.stance import Stance
from app.db.models import Agent, Claim, Clash, MemoryEntry, Project, Task, VerdictLog
from app.db.session import session_scope
from app.events.bus import get_bus
from app.schemas import (
    CheckVerdictResult,
    ClaimOut,
    ClashOut,
    ClashSummary,
    ContextItem,
    DeclareResult,
)

log = logging.getLogger(__name__)


class ProjectNotFound(LookupError):
    pass


class ClashNotFound(LookupError):
    pass


# -- helpers -------------------------------------------------------------------


async def resolve_project(
    db: AsyncSession, project_id: uuid.UUID | str | None, principal: Principal | None = None
) -> Project:
    """Explicit id (membership-checked), else the caller's default project.

    The principal defaults to the request-scoped one set by the REST auth dependency
    or the MCP auth middleware.
    """
    if principal is None:
        principal = current_principal.get()
    try:
        if project_id:
            return await require_project_access(db, principal, uuid.UUID(str(project_id)))
        return await default_project_for(db, principal)
    except LookupError as e:
        raise ProjectNotFound(str(e)) from e


async def resolve_agent(
    db: AsyncSession,
    project_id: uuid.UUID,
    agent_name: str,
    developer_name: str | None,
    principal: Principal | None = None,
    bind_owner: bool = True,
) -> Agent:
    """Find or create the agent row. An authenticated caller owns the agent: its
    developer_name comes from the account, and it cannot take over another user's agent.
    bind_owner=False creates/updates the row without attributing it to the caller
    (used when mirroring external PRs)."""
    if principal is None and bind_owner:
        principal = current_principal.get()
    if not bind_owner:
        principal = None
    agent = (
        await db.execute(select(Agent).where(Agent.project_id == project_id, Agent.name == agent_name))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if principal is not None:
        developer_name = principal.name or developer_name
    if agent is None:
        agent = Agent(
            project_id=project_id,
            name=agent_name,
            developer_name=developer_name or agent_name,
            user_id=principal.user_id if principal else None,
            last_seen=now,
        )
        db.add(agent)
        await db.flush()
    else:
        if principal is not None:
            if agent.user_id is None:
                agent.user_id = principal.user_id
            elif agent.user_id != principal.user_id and not principal.is_admin((await db.get(Project, project_id)).org_id):
                raise Forbidden(f"agent '{agent_name}' belongs to another user in this project")
        agent.last_seen = now
        if developer_name and agent.developer_name != developer_name:
            agent.developer_name = developer_name
    return agent


async def resolve_task(db: AsyncSession, project_id: uuid.UUID, task_ref: str | None) -> Task | None:
    if not task_ref:
        return None
    task = (
        await db.execute(select(Task).where(Task.project_id == project_id, Task.external_ref == task_ref))
    ).scalar_one_or_none()
    if task is None:
        task = Task(project_id=project_id, external_ref=task_ref, title=task_ref)
        db.add(task)
        await db.flush()
    return task


def _context_item(entry: MemoryEntry, similarity: float | None = None) -> ContextItem:
    return ContextItem(
        type=entry.type,
        content=entry.content,
        source=entry.source_agent.name if entry.source_agent else None,
        entry_id=entry.id,
        similarity=round(similarity, 4) if similarity is not None else None,
    )


@dataclass
class _Candidate:
    claim: Claim
    comparison: Comparison
    ruling: RulingMatch | None = None


# -- the flow ------------------------------------------------------------------


async def declare_intent(
    *,
    agent_name: str,
    developer_name: str | None,
    plan_text: str,
    task_ref: str | None = None,
    branch: str | None = None,
    project_id: uuid.UUID | str | None = None,
    wait_seconds: int = 0,
) -> DeclareResult:
    started = time.perf_counter()
    settings = get_settings()
    providers = get_providers()
    bus = get_bus()

    # 1. agent (own short transaction so the LLM call is not inside a DB txn)
    async with session_scope() as db:
        project = await resolve_project(db, project_id)
        agent = await resolve_agent(db, project.id, agent_name, developer_name)
        task = await resolve_task(db, project.id, task_ref)
        pid, agent_id, task_id = project.id, agent.id, (task.id if task else None)

    # 2 + 3. stance extraction and embedding are independent: run them together
    stance, embedding = await asyncio.gather(providers.stance.extract(plan_text), providers.embeddings.embed(plan_text))

    lock = bus.redis.lock(f"consensus:lock:project:{pid}", timeout=60, blocking_timeout=60)
    async with lock:
        async with session_scope() as db:
            # 4. retrieve, both in parallel (separate sessions: asyncpg forbids concurrent use of one connection)
            candidates_task = asyncio.create_task(_retrieve_claims(pid, embedding, agent_id))
            memory_task = asyncio.create_task(_retrieve_memory(pid, embedding))
            scored_claims, scored_memory = await asyncio.gather(candidates_task, memory_task)

            # 5. compare, deterministically
            candidates: list[_Candidate] = []
            for sc in scored_claims:
                other = Stance.from_dict(sc.claim.stance or {})
                cmp = compare(stance, other, sc.similarity)
                if cmp.severity in ("hard", "soft"):
                    candidates.append(_Candidate(claim=sc.claim, comparison=cmp))

            # 6. severity
            severity = overall_severity([c.comparison for c in candidates], memory_hits=len(scored_memory))

            # 7. prior-ruling short circuit
            for cand in candidates:
                if cand.comparison.severity != "hard":
                    continue
                primary = cand.comparison.primary
                assert primary is not None
                cand.ruling = await find_ruling(db, pid, primary.axis, cand.comparison.shared_concepts)

            unruled_hard = [c for c in candidates if c.comparison.severity == "hard" and c.ruling is None]
            ruled_hard = [c for c in candidates if c.comparison.severity == "hard" and c.ruling is not None]

            if unruled_hard:
                verdict = "wait"
            elif candidates or scored_memory:
                verdict = "proceed_with_context"
            else:
                verdict = "proceed"

            # 8. persist claim + clash rows
            agent_row = await db.get(Agent, agent_id)
            task_row = await db.get(Task, task_id) if task_id else None
            claim = Claim(
                project_id=pid,
                agent=agent_row,
                task=task_row,
                intent_text=plan_text.strip(),
                stance=stance.to_dict(),
                concepts=list(stance.concepts),
                embedding=embedding,
                branch=branch,
                status="open",
            )
            db.add(claim)
            await db.flush()

            clash_rows: list[tuple[Clash, _Candidate]] = []
            for cand in candidates:
                cmp = cand.comparison
                if cmp.severity == "hard":
                    axis = cmp.primary.axis  # type: ignore[union-attr]
                    if cand.ruling is not None:
                        row = Clash(
                            project_id=pid,
                            claim_a=cand.claim,
                            claim_b=claim,
                            axis=axis,
                            shared_concepts=cmp.shared_concepts,
                            severity="hard",
                            status="auto_resolved",
                            resolution=None,
                            resolution_note=cand.ruling.entry.content,
                            resolved_by=f"ruling:{cand.ruling.entry.id}",
                        )
                    else:
                        row = Clash(
                            project_id=pid,
                            claim_a=cand.claim,
                            claim_b=claim,
                            axis=axis,
                            shared_concepts=cmp.shared_concepts,
                            severity="hard",
                            status="open",
                        )
                else:
                    row = Clash(
                        project_id=pid,
                        claim_a=cand.claim,
                        claim_b=claim,
                        axis="concept",
                        shared_concepts=cmp.shared_concepts,
                        severity="soft",
                        status="auto_resolved",
                        resolution="both_with_note",
                        resolution_note="Soft clash: overlapping concepts, no divergent stance axis.",
                        resolved_by="system",
                    )
                db.add(row)
                clash_rows.append((row, cand))
            await db.flush()

            # Build the response while the rows are still attached.
            context: list[ContextItem] = [_context_item(m.entry, m.similarity) for m in scored_memory]
            ruling_item: ContextItem | None = None
            for cand in ruled_hard:
                item = _context_item(cand.ruling.entry)  # type: ignore[union-attr]
                if ruling_item is None:
                    ruling_item = item
                if all(ci.entry_id != item.entry_id for ci in context):
                    context.insert(0, item)

            primary_row: Clash | None = None
            primary_cand: _Candidate | None = None
            for row, cand in clash_rows:
                if row.severity == "hard" and row.status == "open":
                    primary_row, primary_cand = row, cand
                    break
            if primary_row is None:
                for row, cand in clash_rows:
                    if row.severity == "hard":
                        primary_row, primary_cand = row, cand
                        break
            if primary_row is None and clash_rows:
                primary_row, primary_cand = clash_rows[0]

            clash_summary: ClashSummary | None = None
            if primary_row is not None and primary_cand is not None:
                div = primary_cand.comparison.primary
                clash_summary = ClashSummary(
                    with_agent=primary_cand.claim.agent.name,
                    their_intent=primary_cand.claim.intent_text,
                    axis=primary_row.axis,
                    your_position=div.ours if div else None,
                    their_position=div.theirs if div else None,
                    shared_concepts=list(primary_row.shared_concepts),
                    severity=primary_row.severity,
                )

            duration_ms = int((time.perf_counter() - started) * 1000)
            db.add(
                VerdictLog(
                    project_id=pid,
                    claim_id=claim.id,
                    verdict=verdict,
                    duration_ms=duration_ms,
                    detail={
                        "agent": agent_name,
                        "plan_text": plan_text,
                        "stance": stance.to_dict(),
                        "severity": severity,
                        "candidates": [
                            {
                                "claim_id": str(sc.claim.id),
                                "agent": sc.claim.agent.name,
                                "similarity": round(sc.similarity, 4),
                                "comparison": compare(stance, Stance.from_dict(sc.claim.stance or {}), sc.similarity).to_dict(),
                            }
                            for sc in scored_claims
                        ],
                        "memory_hits": [
                            {"entry_id": str(m.entry.id), "type": m.entry.type, "similarity": round(m.similarity, 4)}
                            for m in scored_memory
                        ],
                        "rulings_applied": [str(c.ruling.entry.id) for c in ruled_hard],  # type: ignore[union-attr]
                        "clashes": [
                            {"clash_id": str(r.id), "severity": r.severity, "status": r.status, "axis": r.axis}
                            for r, _ in clash_rows
                        ],
                        "thresholds": {
                            "concept_similarity": settings.concept_similarity_threshold,
                            "axis_match_overlap": settings.axis_match_overlap,
                        },
                    },
                )
            )

            claim_out = ClaimOut.from_claim(claim)
            clash_outs = [ClashOut.from_clash(r) for r, _ in clash_rows]
            result = DeclareResult(
                claim_id=claim.id,
                verdict=verdict,
                context=context,
                clash=clash_summary,
                clash_id=primary_row.id if primary_row is not None else None,
                ruling=ruling_item,
                severity=severity,
                project_id=pid,
                agent_id=agent_id,
                duration_ms=duration_ms,
            )
        # session committed here, lock still held until we leave the `async with lock`

    # 9. publish
    await bus.publish(pid, "claim.created", {"claim": claim_out.model_dump(mode="json"), "verdict": verdict})
    for co in clash_outs:
        if co.status == "open":
            await bus.publish(pid, "clash.opened", {"clash": co.model_dump(mode="json")})
        elif co.severity == "hard":
            await bus.publish(
                pid,
                "clash.resolved",
                {"clash": co.model_dump(mode="json"), "auto": True, "ruling": ruling_item.model_dump(mode="json") if ruling_item else None},
            )

    log.info(
        "verdict=%s agent=%s severity=%s clash=%s duration_ms=%d",
        verdict,
        agent_name,
        severity,
        result.clash_id,
        duration_ms,
    )

    # Optional long poll: hold the call open until the clash is resolved.
    if verdict == "wait" and wait_seconds > 0 and result.clash_id is not None:
        outcome = await check_verdict(result.clash_id, wait_seconds=min(wait_seconds, settings.max_wait_seconds))
        if outcome.status != "open":
            result.verdict = outcome.verdict
            if outcome.ruling is not None:
                result.ruling = outcome.ruling
                result.context.insert(0, outcome.ruling)

    # 10.
    return result


async def _retrieve_claims(pid: uuid.UUID, embedding: list[float], agent_id: uuid.UUID) -> list[retrieval.ScoredClaim]:
    async with session_scope() as db:
        return await retrieval.similar_open_claims(db, pid, embedding, exclude_agent_id=agent_id, limit=10)


async def _retrieve_memory(pid: uuid.UUID, embedding: list[float]) -> list[retrieval.ScoredMemory]:
    async with session_scope() as db:
        return await retrieval.similar_memory(db, pid, embedding, limit=5)


# -- check_verdict -----------------------------------------------------------------


async def _clash_outcome(clash_id: uuid.UUID) -> CheckVerdictResult:
    async with session_scope() as db:
        clash = await db.get(Clash, clash_id)
        if clash is None:
            raise ClashNotFound(f"clash {clash_id} not found")
        ruling: ContextItem | None = None
        if clash.status != "open":
            entry = (
                await db.execute(
                    select(MemoryEntry)
                    .where(MemoryEntry.type == "ruling", MemoryEntry.related_claim_id == clash.claim_b_id, MemoryEntry.axis == clash.axis)
                    .order_by(MemoryEntry.created_at.desc())
                    .limit(1)
                )
            ).unique().scalar_one_or_none()
            if entry is None and clash.resolved_by and clash.resolved_by.startswith("ruling:"):
                entry = await db.get(MemoryEntry, uuid.UUID(clash.resolved_by.split(":", 1)[1]))
            if entry is not None:
                ruling = _context_item(entry)
            elif clash.resolution_note:
                ruling = ContextItem(type="ruling", content=clash.resolution_note, source=clash.resolved_by)
        verdict = "wait" if clash.status == "open" else "proceed_with_context"
        return CheckVerdictResult(
            clash_id=clash.id,
            status=clash.status,
            verdict=verdict,
            resolution=clash.resolution,
            resolution_note=clash.resolution_note,
            resolved_by=clash.resolved_by,
            ruling=ruling,
        )


async def check_verdict(clash_id: uuid.UUID, wait_seconds: int = 0) -> CheckVerdictResult:
    """Return the clash outcome, optionally long-polling until it is resolved."""
    outcome = await _clash_outcome(clash_id)
    if outcome.status != "open" or wait_seconds <= 0:
        return outcome

    bus = get_bus()
    async with session_scope() as db:
        clash = await db.get(Clash, clash_id)
        pid = clash.project_id  # type: ignore[union-attr]

    def _is_ours(frame: dict) -> bool:
        return frame.get("type") == "clash.resolved" and str(frame.get("data", {}).get("clash", {}).get("id")) == str(clash_id)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    q = bus.subscribe(pid)
    try:
        # Re-check the DB right after subscribing so a resolve landing between the
        # first read and the subscription cannot be missed.
        outcome = await _clash_outcome(clash_id)
        if outcome.status != "open":
            return outcome
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return await _clash_outcome(clash_id)
            try:
                payload = await asyncio.wait_for(q.get(), timeout=min(remaining, 2.0))
            except asyncio.TimeoutError:
                outcome = await _clash_outcome(clash_id)  # periodic DB fallback
                if outcome.status != "open":
                    return outcome
                continue
            if _is_ours(json.loads(payload)):
                return await _clash_outcome(clash_id)
    finally:
        bus.unsubscribe(pid, q)
