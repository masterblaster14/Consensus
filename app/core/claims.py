"""Claim lifecycle beyond declare and handoff: withdraw, expiry, status.

A claim is "open" from declare_intent until file_handoff (in_review) or a merged
PR (retired). Two more exits exist so abandoned plans do not block other agents
forever:

  withdraw_claim       the agent (or an admin) gives the plan up explicitly
  expire_stale_claims  the scheduler retires open claims older than CLAIM_TTL_HOURS
                       that have no PR

Both release any open clash the claim was part of: the other side's claim
proceeds, the clash is marked auto_resolved with a note, and clash.resolved is
published so a waiting check_verdict returns immediately.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Forbidden, check_write, current_principal, require_project_access
from app.core.verdict import resolve_project
from app.db.models import Agent, Claim, Clash, Project
from app.db.session import session_scope
from app.events.bus import get_bus
from app.schemas import ClaimBrief, ClashOut, ContextItem, StatusClaim, StatusOut, WithdrawResult

log = logging.getLogger(__name__)


class ClaimNotFound(LookupError):
    pass


async def _retire(db: AsyncSession, claim: Claim, *, note: str, resolved_by: str) -> list[Clash]:
    """Mark the claim retired and close every open clash it is part of. The other claim proceeds."""
    claim.status = "retired"
    claim.resolved_at = datetime.now(timezone.utc)
    clashes = (
        await db.execute(
            select(Clash).where(Clash.status == "open", or_(Clash.claim_a_id == claim.id, Clash.claim_b_id == claim.id))
        )
    ).unique().scalars().all()
    for cl in clashes:
        cl.status = "auto_resolved"
        cl.resolution = "b_proceeds" if cl.claim_a_id == claim.id else "a_proceeds"
        cl.resolution_note = note
        cl.resolved_by = resolved_by
    return list(clashes)


async def _publish_retired(pid: uuid.UUID, claim_id: uuid.UUID, clashes: list[ClashOut], why: str) -> None:
    bus = get_bus()
    await bus.publish(pid, "claim.retired", {"claim_id": str(claim_id), "pr_number": None, "merged": False, "reason": why})
    for co in clashes:
        ruling = ContextItem(type="ruling", content=co.resolution_note or why, source=co.resolved_by)
        await bus.publish(
            pid, "clash.resolved", {"clash": co.model_dump(mode="json"), "auto": True, "ruling": ruling.model_dump(mode="json")}
        )


async def withdraw_claim(claim_id: uuid.UUID, *, reason: str | None = None) -> WithdrawResult:
    """Idempotent. Only the agent's owner or an org admin may withdraw."""
    principal = current_principal.get()
    async with session_scope() as db:
        claim = await db.get(Claim, claim_id)
        if claim is None:
            raise ClaimNotFound(f"claim {claim_id} not found")
        project = await require_project_access(db, principal, claim.project_id)
        check_write(principal, project)
        owner = claim.agent.user_id if claim.agent else None
        if principal is not None and owner not in (None, principal.user_id) and not principal.is_admin(project.org_id):
            raise Forbidden("only the agent's owner or an organisation admin can withdraw this claim")
        if claim.status == "retired":
            return WithdrawResult(claim_id=claim.id, status="retired", released_clashes=[])
        agent_name = claim.agent.name if claim.agent else "the agent"
        note = (reason or "").strip() or f"{agent_name} withdrew its plan"
        released = await _retire(db, claim, note=note, resolved_by=f"withdrawn:{agent_name}")
        outs = [ClashOut.from_clash(c) for c in released]
        pid = claim.project_id
    await _publish_retired(pid, claim_id, outs, "withdrawn")
    log.info("claim %s withdrawn by %s; released %d clash(es)", claim_id, agent_name, len(outs))
    return WithdrawResult(claim_id=claim_id, status="retired", released_clashes=[o.id for o in outs])


async def expire_stale_claims(ttl_hours: int, *, now: datetime | None = None) -> list[uuid.UUID]:
    """Retire open claims older than ttl_hours that never reached a PR. 0 disables. Returns retired ids."""
    if ttl_hours <= 0:
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=ttl_hours)
    to_publish: list[tuple[uuid.UUID, uuid.UUID, list[ClashOut], str]] = []
    async with session_scope() as db:
        stale = (
            await db.execute(
                select(Claim).where(Claim.status == "open", Claim.pr_number.is_(None), Claim.created_at < cutoff)
            )
        ).unique().scalars().all()
        for claim in stale:
            agent_name = claim.agent.name if claim.agent else "an agent"
            note = f"{agent_name}'s plan expired after {ttl_hours} hours without a handoff"
            released = await _retire(db, claim, note=note, resolved_by="system:expired")
            to_publish.append((claim.project_id, claim.id, [ClashOut.from_clash(c) for c in released], note))
    for pid, cid, outs, _ in to_publish:
        await _publish_retired(pid, cid, outs, "expired")
    if to_publish:
        log.info("expired %d stale claim(s)", len(to_publish))
    return [cid for _, cid, _, _ in to_publish]


async def status(*, agent_name: str | None = None, project_id: uuid.UUID | str | None = None) -> StatusOut:
    """Where an agent stands: its live claims, clashes waiting on a ruling for it, clashes where
    another agent waits on it. Default scope: every agent owned by the calling account."""
    principal = current_principal.get()
    async with session_scope() as db:
        project = await resolve_project(db, project_id)
        q = select(Agent).where(Agent.project_id == project.id)
        if agent_name:
            q = q.where(Agent.name == agent_name)
        elif principal is not None:
            q = q.where(Agent.user_id == principal.user_id)
        agents = (await db.execute(q.order_by(Agent.name))).scalars().all()
        ids = {a.id for a in agents}
        names = {a.id: a.name for a in agents}
        claims = (
            await db.execute(
                select(Claim)
                .where(Claim.project_id == project.id, Claim.agent_id.in_(ids), Claim.status != "retired")
                .order_by(Claim.created_at.desc())
            )
        ).unique().scalars().all() if ids else []
        mine = {c.id for c in claims}
        clashes = (
            await db.execute(select(Clash).where(Clash.project_id == project.id, Clash.status == "open"))
        ).unique().scalars().all() if mine else []
        return StatusOut(
            project_id=project.id,
            agents=[a.name for a in agents],
            claims=[StatusClaim(**ClaimBrief.from_claim(c).model_dump(), agent_name=names.get(c.agent_id)) for c in claims],
            waiting_on=[ClashOut.from_clash(cl) for cl in clashes if cl.claim_b_id in mine],
            blocking=[ClashOut.from_clash(cl) for cl in clashes if cl.claim_a_id in mine],
        )
