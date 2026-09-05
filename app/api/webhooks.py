"""POST /api/webhooks/github"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.db.session import CommittingRoute
from app.config import get_settings
from app.integrations.github import handle_pull_request_closed, verify_signature

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"], route_class=CommittingRoute)


@router.post("/github")
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(default=None),
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    body = await request.body()
    if not verify_signature(get_settings().github_webhook_secret, body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json")

    if x_github_event == "ping":
        return {"ok": True, "event": "ping"}

    if x_github_event == "pull_request" and payload.get("action") == "closed":
        pr = payload.get("pull_request") or {}
        repo = (payload.get("repository") or {}).get("full_name") or ""
        retired = await handle_pull_request_closed(repo, int(pr.get("number", 0)), bool(pr.get("merged")))
        return {"ok": True, "event": "pull_request.closed", "retired_claims": [str(c) for c in retired]}

    return {"ok": True, "event": x_github_event, "ignored": True}
