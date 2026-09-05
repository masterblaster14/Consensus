"""file_handoff: store a handoff memory entry, move the claim to in_review, open the PR."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.config import get_settings
from app.core.auth import check_write, current_principal
from app.core.memory import write_memory
from app.db.models import Claim, Clash, Project
from app.db.session import session_scope
from app.events.bus import get_bus
from app.schemas import ClaimOut, ClashOut, FileHandoffResult

log = logging.getLogger(__name__)


class ClaimNotFound(LookupError):
    pass


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [line.strip() for line in v.splitlines() if line.strip()]
    return [str(x).strip() for x in v if str(x).strip()]


def handoff_text(changed: list[str], untouched: list[str], assumptions: list[str], uncertainties: list[str]) -> str:
    def block(title: str, items: list[str]) -> str:
        body = "\n".join(f"- {i}" for i in items) if items else "- (none)"
        return f"{title}:\n{body}"

    return "\n\n".join(
        [
            block("Changed", changed),
            block("Untouched", untouched),
            block("Assumptions", assumptions),
            block("Uncertainties", uncertainties),
        ]
    )


async def file_handoff(
    *,
    claim_id: uuid.UUID,
    changed,
    untouched,
    assumptions,
    uncertainties,
) -> FileHandoffResult:
    settings = get_settings()
    changed, untouched = _as_list(changed), _as_list(untouched)
    assumptions, uncertainties = _as_list(assumptions), _as_list(uncertainties)

    async with session_scope() as db:
        claim = await db.get(Claim, claim_id)
        if claim is None:
            raise ClaimNotFound(f"claim {claim_id} not found")
        project = await db.get(Project, claim.project_id)
        if project is not None:
            check_write(current_principal.get(), project)
        claim.status = "in_review"
        claim.resolved_at = datetime.now(timezone.utc)
        claim_out = ClaimOut.from_claim(claim)
        agent_name = claim.agent.name
        pid = claim.project_id
        clashes = (
            await db.execute(
                select(Clash).where(or_(Clash.claim_a_id == claim.id, Clash.claim_b_id == claim.id))
            )
        ).unique().scalars().all()
        clash_outs = [ClashOut.from_clash(c) for c in clashes]

    content = f"Handoff for: {claim_out.intent_text}\n\n" + handoff_text(changed, untouched, assumptions, uncertainties)
    written = await write_memory(
        agent_name=agent_name,
        type="handoff",
        content=content,
        concepts=claim_out.concepts,
        project_id=pid,
        related_claim_id=claim_id,
    )

    payload = {
        "claim": claim_out.model_dump(mode="json"),
        "entry_id": str(written.entry_id),
        "changed": changed,
        "untouched": untouched,
        "assumptions": assumptions,
        "uncertainties": uncertainties,
    }
    await get_bus().publish(pid, "handoff.filed", payload)

    pr_url: str | None = None
    pr_number: int | None = None
    if settings.enable_github and claim_out.branch:
        try:
            from app.integrations.github import open_pull_request

            pr = await open_pull_request(
                pid,
                claim_out,
                {"changed": changed, "untouched": untouched, "assumptions": assumptions, "uncertainties": uncertainties},
                clash_outs,
            )
            if pr is not None:
                pr_url, pr_number = pr.url, pr.number
                async with session_scope() as db:
                    c = await db.get(Claim, claim_id)
                    if c is not None:
                        c.pr_number = pr_number
                await get_bus().publish(pid, "pr.opened", {"claim_id": str(claim_id), "pr_url": pr_url, "pr_number": pr_number})
        except Exception:
            log.exception("opening pull request failed; handoff still recorded")
    elif not claim_out.branch:
        log.info("handoff for claim %s has no branch; skipping PR", claim_id)

    return FileHandoffResult(entry_id=written.entry_id, pr_url=pr_url, pr_number=pr_number)
