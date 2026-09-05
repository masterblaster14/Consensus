"""POST /api/webhooks/github"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.db.session import CommittingRoute
from app.config import get_settings
from app.integrations.github import handle_pull_request_closed, verify_signature, webhook_secrets_for_repo

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"], route_class=CommittingRoute)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json")
    repo = (payload.get("repository") or {}).get("full_name") or ""
    # Hooks the backend registered itself carry a per-project secret; a hand-registered hook
    # uses GITHUB_WEBHOOK_SECRET. Either is accepted. With no secret anywhere (dev), deliveries pass.
    secrets = [s for s in (get_settings().github_webhook_secret,) if s] + await webhook_secrets_for_repo(repo)
    if secrets and not any(verify_signature(s, body, x_hub_signature_256) for s in secrets):
        raise HTTPException(status_code=401, detail="bad signature")

    if x_github_event == "ping":
        return {"ok": True, "event": "ping"}

    if x_github_event == "pull_request" and payload.get("action") == "closed":
        pr = payload.get("pull_request") or {}
        repo = (payload.get("repository") or {}).get("full_name") or ""
        retired = await handle_pull_request_closed(repo, int(pr.get("number", 0)), bool(pr.get("merged")))
        return {"ok": True, "event": "pull_request.closed", "retired_claims": [str(c) for c in retired]}

    return {"ok": True, "event": x_github_event, "ignored": True}
