"""Sign-in: GitHub OAuth (primary), email magic link (fallback), dev login (local only).

Flow for the frontend:
  GitHub:     GET /api/auth/github/start -> {url}; send the browser there. GitHub calls back
              GET /api/auth/github/callback which redirects to FRONTEND_URL/auth/callback#token=<jwt>
  Magic link: POST /api/auth/magic-link {email} -> link is emailed (logged in dev);
              the link points at FRONTEND_URL/auth/magic?token=..., the page then calls
              POST /api/auth/magic-link/verify {token} -> {token: <jwt>, user}
  Then:       Authorization: Bearer <jwt> on every request; GET /api/auth/me
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import CommittingRoute
from app.api.deps import require_principal
from app.config import get_settings
from app.core.auth import (
    Principal,
    get_or_create_user,
    issue_jwt,
    memberships_for,
    new_opaque_token,
    sha256,
)
from app.db.models import MagicLink, User
from app.db.session import get_db
from app.events.bus import get_bus
from app.schemas import MeOut, MembershipOut, TokenOut, UserOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"], route_class=CommittingRoute)

GITHUB_AUTHORIZE = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_API = "https://api.github.com"
_STATE_TTL = 600


async def _me(db: AsyncSession, user: User) -> MeOut:
    ms = await memberships_for(db, user.id)
    return MeOut(
        user=UserOut.model_validate(user),
        memberships=[
            MembershipOut(org_id=m.org_id, org_name=m.org.name, org_slug=m.org.slug, role=m.role, user_id=m.user_id, user_email=user.email, user_name=user.name)
            for m in ms
        ],
    )


# -- GitHub OAuth ----------------------------------------------------------------------


@router.get("/github/start")
async def github_start(redirect_to: str | None = Query(default=None, description="frontend path to return to")) -> dict:
    settings = get_settings()
    if not settings.github_client_id:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured (GITHUB_CLIENT_ID)")
    state = new_opaque_token(24)
    await get_bus().redis.set(f"consensus:oauth:{state}", redirect_to or "/", ex=_STATE_TTL)
    params = httpx.QueryParams(
        {"client_id": settings.github_client_id, "scope": settings.github_oauth_scopes, "state": state, "allow_signup": "true"}
    )
    return {"url": f"{GITHUB_AUTHORIZE}?{params}", "state": state}


@router.get("/github/callback")
async def github_callback(code: str, state: str, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    redis = get_bus().redis
    redirect_to = await redis.get(f"consensus:oauth:{state}")
    if redirect_to is None:
        raise HTTPException(status_code=400, detail="invalid or expired oauth state")
    await redis.delete(f"consensus:oauth:{state}")

    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            GITHUB_TOKEN,
            headers={"Accept": "application/json"},
            data={"client_id": settings.github_client_id, "client_secret": settings.github_client_secret, "code": code},
        )
        r.raise_for_status()
        access_token = r.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail=f"github token exchange failed: {r.json()}")
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        gh_user = (await client.get(f"{GITHUB_API}/user", headers=headers)).json()
        emails = (await client.get(f"{GITHUB_API}/user/emails", headers=headers)).json()

    primary = next((e for e in emails if isinstance(e, dict) and e.get("primary") and e.get("verified")), None)
    email = (primary or {}).get("email") or gh_user.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="GitHub account has no verified email")

    # match by github id first, then by email
    user = (await db.execute(select(User).where(User.github_id == gh_user["id"]))).scalar_one_or_none()
    if user is None:
        user = await get_or_create_user(db, email=email, name=gh_user.get("name") or gh_user.get("login"), avatar_url=gh_user.get("avatar_url"))
    else:
        user.last_login_at = datetime.now(timezone.utc)
    user.github_id = gh_user["id"]
    user.github_login = gh_user.get("login")
    user.github_access_token = access_token
    if gh_user.get("avatar_url"):
        user.avatar_url = gh_user["avatar_url"]
    await db.flush()

    token = issue_jwt(user)
    dest = f"{settings.frontend_url.rstrip('/')}/auth/callback#token={token}&next={redirect_to}"
    return RedirectResponse(dest, status_code=302)


# -- Magic link -----------------------------------------------------------------------


class MagicLinkRequest(BaseModel):
    email: EmailStr
    name: str | None = None


class MagicLinkVerify(BaseModel):
    token: str


@router.post("/magic-link")
async def magic_link_request(body: MagicLinkRequest, db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    raw = new_opaque_token(32)
    db.add(
        MagicLink(
            email=str(body.email).lower(),
            token_hash=sha256(raw),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.magic_link_ttl_minutes),
        )
    )
    link = f"{settings.frontend_url.rstrip('/')}/auth/magic?token={raw}"
    if body.name:
        await get_bus().redis.set(f"consensus:magic-name:{sha256(raw)}", body.name, ex=settings.magic_link_ttl_minutes * 60)
    # No email provider is wired yet: the link is logged. Plug an email sender in here.
    log.info("magic link for %s: %s", body.email, link)
    out: dict = {"ok": True, "expires_in_minutes": settings.magic_link_ttl_minutes}
    if settings.dev_auth:
        out["dev_link"] = link
        out["dev_token"] = raw
    return out


@router.post("/magic-link/verify", response_model=TokenOut)
async def magic_link_verify(body: MagicLinkVerify, db: AsyncSession = Depends(get_db)) -> TokenOut:
    h = sha256(body.token)
    ml = (await db.execute(select(MagicLink).where(MagicLink.token_hash == h))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if ml is None or ml.used_at is not None or ml.expires_at < now:
        raise HTTPException(status_code=400, detail="invalid, used or expired link")
    ml.used_at = now
    name = await get_bus().redis.get(f"consensus:magic-name:{h}")
    user = await get_or_create_user(db, email=ml.email, name=name)
    return TokenOut(token=issue_jwt(user), me=await _me(db, user))


# -- Dev login (DEV_AUTH=true only) ---------------------------------------------------------


class DevLogin(BaseModel):
    email: EmailStr
    name: str | None = None


@router.post("/dev-login", response_model=TokenOut)
async def dev_login(body: DevLogin, db: AsyncSession = Depends(get_db)) -> TokenOut:
    if not get_settings().dev_auth:
        raise HTTPException(status_code=404, detail="not found")
    user = await get_or_create_user(db, email=str(body.email), name=body.name)
    return TokenOut(token=issue_jwt(user), me=await _me(db, user))


# -- Me -----------------------------------------------------------------------------------


@router.get("/me", response_model=MeOut)
async def me(principal: Principal = Depends(require_principal), db: AsyncSession = Depends(get_db)) -> MeOut:
    user = await db.get(User, principal.user_id)
    assert user is not None
    return await _me(db, user)


@router.get("/providers")
async def providers() -> dict:
    """Which sign-in methods the frontend should offer."""
    s = get_settings()
    return {"github": bool(s.github_client_id), "magic_link": True, "dev_login": s.dev_auth}
