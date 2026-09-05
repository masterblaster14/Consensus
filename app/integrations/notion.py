"""Notion integration: sync tasks from a database, mirror memory entries out as pages.

Behind ENABLE_NOTION. Credentials come from the project's organisation (an admin
pastes an internal-integration token and the tasks database id via
PUT /api/orgs/{id}/integrations/notion), falling back to NOTION_TOKEN /
NOTION_TASKS_DB_ID env vars. Never blocks the declare flow.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.schemas import MemoryEntryOut

log = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


@dataclass
class Creds:
    token: str | None
    tasks_db_id: str | None

    @property
    def ok(self) -> bool:
        return bool(self.token and self.tasks_db_id)


async def _creds_for_project(project_id: uuid.UUID) -> Creds:
    from app.db.models import Organization, Project
    from app.db.session import session_scope

    settings = get_settings()
    if not settings.enable_notion:
        return Creds(None, None)
    async with session_scope() as db:
        project = await db.get(Project, project_id)
        org = await db.get(Organization, project.org_id) if project and project.org_id else None
    token = (org.notion_token if org else None) or settings.notion_token
    db_id = (org.notion_tasks_db_id if org else None) or settings.notion_tasks_db_id
    return Creds(token, db_id)


def _client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=API,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        timeout=15.0,
    )


def _plain(rich: list[dict] | None) -> str:
    return "".join(part.get("plain_text", "") for part in (rich or []))


def _page_title(page: dict) -> str:
    for prop in (page.get("properties") or {}).values():
        if prop.get("type") == "title":
            return _plain(prop.get("title"))
    return "(untitled)"


def _page_ref(page: dict) -> str | None:
    """Look for a text/rich_text property that looks like an external ref (e.g. 'ENG-1234')."""
    for name, prop in (page.get("properties") or {}).items():
        if prop.get("type") == "rich_text" and name.lower() in {"ref", "id", "ticket", "key", "external ref", "external_ref"}:
            v = _plain(prop.get("rich_text"))
            if v:
                return v
        if prop.get("type") == "unique_id":
            uid = prop.get("unique_id") or {}
            if uid.get("number") is not None:
                prefix = uid.get("prefix")
                return f"{prefix}-{uid['number']}" if prefix else str(uid["number"])
    return None


async def sync_tasks(project_id: uuid.UUID) -> int:
    """Read the configured Notion database, upsert `tasks`. Returns rows upserted."""
    from sqlalchemy import select

    from app.db.models import Task
    from app.db.session import session_scope

    creds = await _creds_for_project(project_id)
    if not creds.ok:
        return 0

    pages: list[dict] = []
    async with _client(creds.token) as client:
        cursor: str | None = None
        while True:
            payload: dict = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            r = await client.post(f"/databases/{creds.tasks_db_id}/query", json=payload)
            r.raise_for_status()
            data = r.json()
            pages.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

    upserted = 0
    async with session_scope() as db:
        for page in pages:
            page_id = page["id"]
            title = _page_title(page)
            ref = _page_ref(page)
            task = (
                await db.execute(select(Task).where(Task.project_id == project_id, Task.notion_page_id == page_id))
            ).scalar_one_or_none()
            if task is None and ref:
                task = (
                    await db.execute(select(Task).where(Task.project_id == project_id, Task.external_ref == ref))
                ).scalar_one_or_none()
            if task is None:
                db.add(Task(project_id=project_id, notion_page_id=page_id, external_ref=ref, title=title))
            else:
                task.title = title
                task.notion_page_id = page_id
                if ref:
                    task.external_ref = ref
            upserted += 1
    return upserted


async def push_entry(entry: MemoryEntryOut) -> str | None:
    """Mirror a decision / dead_end / ruling as a Notion page in the tasks database's parent.
    Returns the created page id."""
    if entry.type not in ("decision", "dead_end", "ruling"):
        return None
    creds = await _creds_for_project(entry.project_id)
    if not creds.ok:
        return None

    links: list[str] = []
    if entry.related_claim_id:
        links.append(f"claim {entry.related_claim_id}")
        pr_url = await _pr_url_for_claim(entry.related_claim_id)
        if pr_url:
            links.append(pr_url)

    title = f"[{entry.type}] {entry.content[:80]}"
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": entry.content[:1900]}}]},
        }
    ]
    if entry.concepts:
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": "Concepts: " + ", ".join(entry.concepts)}}]},
            }
        )
    if links:
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": "Links: " + " | ".join(links)}}]},
            }
        )
    async with _client(creds.token) as client:
        # Find the title property name of the database so the page is valid.
        r = await client.get(f"/databases/{creds.tasks_db_id}")
        r.raise_for_status()
        props = r.json().get("properties", {})
        title_prop = next((n for n, p in props.items() if p.get("type") == "title"), "Name")
        r = await client.post(
            "/pages",
            json={
                "parent": {"database_id": creds.tasks_db_id},
                "properties": {title_prop: {"title": [{"type": "text", "text": {"content": title}}]}},
                "children": children,
            },
        )
        r.raise_for_status()
        return r.json().get("id")


async def _pr_url_for_claim(claim_id: uuid.UUID) -> str | None:
    from app.db.models import Claim, Project
    from app.db.session import session_scope

    async with session_scope() as db:
        claim = await db.get(Claim, claim_id)
        if claim is None or claim.pr_number is None:
            return None
        project = await db.get(Project, claim.project_id)
        if project is None or not project.repo_full_name:
            return None
        return f"https://github.com/{project.repo_full_name}/pull/{claim.pr_number}"


def push_entry_background(entry: MemoryEntryOut) -> None:
    if not get_settings().enable_notion:
        return

    async def _run() -> None:
        try:
            await push_entry(entry)
        except Exception:
            log.exception("notion push_entry failed")

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass
