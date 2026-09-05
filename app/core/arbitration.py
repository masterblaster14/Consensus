"""Human arbitration of a clash: update the row, write a ruling, release the waiter."""
from __future__ import annotations

import logging
import uuid

from app.core.providers import get_providers
from app.core.rulings import ruling_content
from app.core.verdict import ClashNotFound
from app.db.models import Clash, MemoryEntry
from app.db.session import session_scope
from app.events.bus import get_bus
from app.schemas import ClashOut, ContextItem, MemoryEntryOut

log = logging.getLogger(__name__)


class ClashAlreadyResolved(ValueError):
    pass


async def resolve_clash(
    clash_id: uuid.UUID, *, resolution: str, note: str, resolved_by: str
) -> tuple[ClashOut, MemoryEntryOut]:
    """1. update the clash  2. write a `ruling` memory entry  3. publish clash.resolved."""
    providers = get_providers()

    async with session_scope() as db:
        clash = await db.get(Clash, clash_id)
        if clash is None:
            raise ClashNotFound(f"clash {clash_id} not found")
        if clash.status == "resolved":
            raise ClashAlreadyResolved(f"clash {clash_id} is already resolved")

        clash.status = "resolved"
        clash.resolution = resolution
        clash.resolution_note = note
        clash.resolved_by = resolved_by

        content = ruling_content(
            resolution, note, clash.axis, list(clash.shared_concepts), clash.claim_a.intent_text, clash.claim_b.intent_text
        )
        embedding = await providers.embeddings.embed(content)
        entry = MemoryEntry(
            project_id=clash.project_id,
            type="ruling",
            content=content,
            concepts=list(clash.shared_concepts),
            axis=clash.axis,
            embedding=embedding,
            source_agent=None,
            related_claim_id=clash.claim_b_id,
        )
        db.add(entry)
        await db.flush()

        clash_out = ClashOut.from_clash(clash)
        entry_out = MemoryEntryOut.from_entry(entry)
        pid = clash.project_id
        pr_number = clash.claim_a.pr_number or clash.claim_b.pr_number

    bus = get_bus()
    ruling_item = ContextItem(type="ruling", content=entry_out.content, source=resolved_by, entry_id=entry_out.id)
    await bus.publish(pid, "memory.written", {"entry": entry_out.model_dump(mode="json")})
    await bus.publish(
        pid,
        "clash.resolved",
        {"clash": clash_out.model_dump(mode="json"), "auto": False, "ruling": ruling_item.model_dump(mode="json")},
    )

    # Mirror outward, without blocking.
    try:
        from app.integrations.github import comment_on_pr_background
        from app.integrations.notion import push_entry_background

        push_entry_background(entry_out)
        if pr_number:
            comment_on_pr_background(pid, pr_number, clash_out)
    except Exception:  # pragma: no cover
        log.exception("integration scheduling failed after resolve")

    return clash_out, entry_out
