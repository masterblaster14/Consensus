"""Periodic background work, started from the app lifespan.

  PR sync       every PR_SYNC_INTERVAL_SECONDS, each live project with a repository has
                `sync_open_prs` run so pull requests that were never declared still appear
                on the board. 0 disables; never starts when GitHub is disabled.
  Claim expiry  hourly, open claims older than CLAIM_TTL_HOURS with no PR are retired and
                the clashes they were blocking are released. 0 disables.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Project
from app.db.session import session_scope

log = logging.getLogger(__name__)


async def sync_all_projects() -> dict[str, int]:
    """One pass over every live project with a repo. Returns {project_id: claims_created}."""
    from app.integrations.github import sync_open_prs

    async with session_scope() as db:
        ids = (
            await db.execute(
                select(Project.id).where(Project.repo_full_name.is_not(None), Project.archived_at.is_(None))
            )
        ).scalars().all()
    out: dict[str, int] = {}
    for pid in ids:
        try:
            out[str(pid)] = await sync_open_prs(pid)
        except Exception:
            log.exception("pr sync failed for project %s", pid)
    return out


async def pr_sync_loop(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            created = await sync_all_projects()
            total = sum(created.values())
            if total:
                log.info("pr sync created %d claim(s) across %d project(s)", total, len(created))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("pr sync pass failed")


EXPIRY_CHECK_SECONDS = 3600


async def claim_expiry_loop(ttl_hours: int) -> None:
    from app.core.claims import expire_stale_claims

    while True:
        await asyncio.sleep(EXPIRY_CHECK_SECONDS)
        try:
            await expire_stale_claims(ttl_hours)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("claim expiry pass failed")


def start_background_tasks() -> list[asyncio.Task[None]]:
    s = get_settings()
    tasks: list[asyncio.Task[None]] = []
    if s.enable_github and s.pr_sync_interval_seconds > 0:
        tasks.append(asyncio.create_task(pr_sync_loop(s.pr_sync_interval_seconds), name="pr-sync"))
        log.info("pr sync every %ss", s.pr_sync_interval_seconds)
    if s.claim_ttl_hours > 0:
        tasks.append(asyncio.create_task(claim_expiry_loop(s.claim_ttl_hours), name="claim-expiry"))
        log.info("stale claims expire after %sh", s.claim_ttl_hours)
    return tasks


async def stop_background_tasks(tasks: list[asyncio.Task[None]]) -> None:
    for t in tasks:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await t
