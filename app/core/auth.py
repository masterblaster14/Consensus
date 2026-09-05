"""Authentication and authorisation primitives.

Two credentials exist:
  * Session JWT  - issued after GitHub OAuth / magic link / dev-login; used by the
                   frontend on REST (Authorization: Bearer <jwt>) and WS (?token=).
  * API key      - `csk_...`, minted per user (+ org, optional default project);
                   presented by agents to the MCP endpoint. Also accepted on REST/WS.

Both resolve to a `Principal`. Authorisation is membership-based: a user can see
a project iff they are a member of the project's organisation. Admins manage
members, integrations and can arbitrate any clash; members can arbitrate clashes
involving one of their own agents.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import ApiKey, Membership, Organization, Project, User

API_KEY_PREFIX = "csk_"


class AuthError(Exception):
    """401"""


class Forbidden(Exception):
    """403"""


@dataclass
class Principal:
    user_id: uuid.UUID
    email: str
    name: str
    via: str  # "jwt" | "api_key"
    org_ids: list[uuid.UUID] = field(default_factory=list)
    admin_org_ids: list[uuid.UUID] = field(default_factory=list)
    api_key_id: uuid.UUID | None = None
    key_org_id: uuid.UUID | None = None
    key_project_id: uuid.UUID | None = None

    def is_member(self, org_id: uuid.UUID | None) -> bool:
        return org_id is not None and org_id in self.org_ids

    def is_admin(self, org_id: uuid.UUID | None) -> bool:
        return org_id is not None and org_id in self.admin_org_ids


# Set by the MCP auth middleware for the duration of a tool call.
current_principal: ContextVar[Principal | None] = ContextVar("current_principal", default=None)


# -- hashing / tokens -----------------------------------------------------------


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_api_key() -> tuple[str, str, str]:
    """(plaintext, hash, display prefix)"""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, sha256(raw), raw[:12]


def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def issue_jwt(user: User) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_ttl_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise AuthError(f"invalid session token: {e}") from e


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "org"


def email_domain(email: str) -> str:
    return email.lower().rsplit("@", 1)[-1]


# -- users ------------------------------------------------------------------------


async def get_or_create_user(db: AsyncSession, *, email: str, name: str | None = None, avatar_url: str | None = None) -> User:
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(email=email, name=(name or email.split("@")[0]).strip(), avatar_url=avatar_url)
        db.add(user)
        await db.flush()
    else:
        if name and not user.name:
            user.name = name
        if avatar_url and not user.avatar_url:
            user.avatar_url = avatar_url
    user.last_login_at = datetime.now(timezone.utc)
    await auto_join_by_domain(db, user)
    return user


async def auto_join_by_domain(db: AsyncSession, user: User) -> list[Organization]:
    """Orgs whose auto_join_domain matches the user's email domain get the user as a member."""
    domain = email_domain(user.email)
    orgs = (await db.execute(select(Organization).where(Organization.auto_join_domain == domain))).scalars().all()
    joined: list[Organization] = []
    for org in orgs:
        existing = (
            await db.execute(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
        ).scalar_one_or_none()
        if existing is None:
            db.add(Membership(org_id=org.id, user_id=user.id, role="member"))
            joined.append(org)
    if joined:
        await db.flush()
    return joined


async def memberships_for(db: AsyncSession, user_id: uuid.UUID) -> list[Membership]:
    return list((await db.execute(select(Membership).where(Membership.user_id == user_id))).scalars().all())


async def principal_for_user(db: AsyncSession, user: User, via: str) -> Principal:
    ms = await memberships_for(db, user.id)
    return Principal(
        user_id=user.id,
        email=user.email,
        name=user.name,
        via=via,
        org_ids=[m.org_id for m in ms],
        admin_org_ids=[m.org_id for m in ms if m.role == "admin"],
    )


# -- credential resolution ----------------------------------------------------------


async def principal_from_bearer(db: AsyncSession, token: str) -> Principal:
    token = token.strip()
    if token.startswith(API_KEY_PREFIX):
        return await principal_from_api_key(db, token)
    claims = decode_jwt(token)
    user = await db.get(User, uuid.UUID(claims["sub"]))
    if user is None:
        raise AuthError("user no longer exists")
    return await principal_for_user(db, user, via="jwt")


async def principal_from_api_key(db: AsyncSession, raw: str) -> Principal:
    key = (await db.execute(select(ApiKey).where(ApiKey.key_hash == sha256(raw)))).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        raise AuthError("invalid or revoked API key")
    key.last_used_at = datetime.now(timezone.utc)
    p = await principal_for_user(db, key.user, via="api_key")
    if key.org_id not in p.org_ids:
        raise AuthError("API key's organisation no longer includes this user")
    p.api_key_id = key.id
    p.key_org_id = key.org_id
    p.key_project_id = key.project_id
    return p


# -- authorisation helpers ------------------------------------------------------------


async def require_project_access(db: AsyncSession, principal: Principal | None, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise LookupError(f"project {project_id} not found")
    if principal is None:
        if get_settings().mcp_auth_required:
            raise AuthError("authentication required")
        return project
    if project.org_id is None:
        # Legacy / unowned project: only reachable in dev mode.
        if get_settings().dev_auth:
            return project
        raise Forbidden("project has no organisation")
    if not principal.is_member(project.org_id):
        raise Forbidden("not a member of this project's organisation")
    return project


async def default_project_for(db: AsyncSession, principal: Principal | None) -> Project:
    """Where MCP tools land when no project_id is given."""
    settings = get_settings()
    if principal is not None:
        if principal.key_project_id:
            return await require_project_access(db, principal, principal.key_project_id)
        org_ids = [principal.key_org_id] if principal.key_org_id else principal.org_ids
        projects = (
            await db.execute(select(Project).where(Project.org_id.in_(org_ids)).order_by(Project.created_at))
        ).scalars().all() if org_ids else []
        if len(projects) == 1:
            return projects[0]
        if settings.default_project_id:
            return await require_project_access(db, principal, uuid.UUID(settings.default_project_id))
        if not projects:
            raise LookupError("no projects in your organisation yet; create one first")
        raise LookupError("several projects are visible; pass project_id (or bind the API key to a project)")
    if settings.mcp_auth_required:
        raise AuthError("authentication required")
    if settings.default_project_id:
        p = await db.get(Project, uuid.UUID(settings.default_project_id))
        if p is not None:
            return p
    p = (await db.execute(select(Project).order_by(Project.created_at).limit(1))).scalar_one_or_none()
    if p is None:
        raise LookupError("no projects exist; create one or run scripts/seed_demo.py")
    return p
