"""Rewrite legacy plaintext GitHub / Notion tokens as encrypted values.

Safe to run repeatedly: already-encrypted rows are left alone. Needed once
after upgrading to the build that introduced app/db/crypto.py, and again after
adding a new key to TOKEN_ENCRYPTION_KEY if you want old rows re-encrypted
with it.

    python -m scripts.encrypt_tokens
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select, text
from sqlalchemy.orm.attributes import flag_modified

from app.db import crypto
from app.db.models import Organization, User
from app.db.session import dispose_engine, session_scope


async def main() -> None:
    rewritten = 0
    async with session_scope() as db:
        raw_users = (await db.execute(text("SELECT id, github_access_token FROM users WHERE github_access_token IS NOT NULL"))).all()
        for user_id, stored in raw_users:
            if not crypto.is_encrypted(stored):
                user = await db.get(User, user_id)
                if user is not None:
                    flag_modified(user, "github_access_token")
                    rewritten += 1
        raw_orgs = (await db.execute(text("SELECT id, github_token, notion_token FROM organizations"))).all()
        for org_id, gh, notion in raw_orgs:
            org = await db.get(Organization, org_id)
            if org is None:
                continue
            if gh and not crypto.is_encrypted(gh):
                flag_modified(org, "github_token")
                rewritten += 1
            if notion and not crypto.is_encrypted(notion):
                flag_modified(org, "notion_token")
                rewritten += 1
        _ = select  # keep import for readers extending this script
    await dispose_engine()
    print(f"rewrote {rewritten} token value(s)")


if __name__ == "__main__":
    asyncio.run(main())
