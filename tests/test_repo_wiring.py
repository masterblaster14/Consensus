"""Attaching a repository to a project, automatic merge-webhook registration, and same-origin frontend serving."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import httpx

from app.db.models import Project
from app.db.session import session_scope
from tests.conftest import client_for, login


async def test_patch_project_repo_and_manual_webhook_endpoint(anon, server, api, org, project):
    pid = project["id"]
    marcus = await login(anon, "marcus@example.com", "Marcus")
    cm = await client_for(server, marcus["token"])
    inv = (await api.post(f"/api/orgs/{org['id']}/invites", json={})).json()
    await cm.post(f"/api/invites/{inv['token']}/accept")
    assert (await cm.patch(f"/api/projects/{pid}", json={"name": "x"})).status_code == 403  # members cannot

    r = await api.patch(f"/api/projects/{pid}", json={"name": "Renamed", "repo_full_name": "acme/widgets"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Renamed" and body["repo_full_name"] == "acme/widgets"
    assert body["webhook"]["registered"] is False and "disabled" in body["webhook"]["reason"]  # ENABLE_GITHUB=false in tests

    got = (await api.get(f"/api/projects/{pid}")).json()
    assert got["repo_full_name"] == "acme/widgets" and got["webhook"] is None  # status only on writes

    r = await api.post(f"/api/projects/{pid}/integrations/github/webhook")
    assert r.status_code == 200 and r.json()["registered"] is False

    r = await api.patch(f"/api/projects/{pid}", json={"repo_full_name": ""})
    assert r.json()["repo_full_name"] is None and r.json()["webhook"] is None

    # creating a project with a repo reports the webhook outcome too
    r = await api.post(f"/api/orgs/{org['id']}/projects", json={"name": "With repo", "repo_full_name": "acme/api"})
    assert r.status_code == 201 and r.json()["webhook"]["registered"] is False

    await api.delete(f"/api/projects/{pid}")
    assert (await api.patch(f"/api/projects/{pid}", json={"name": "y"})).status_code == 403  # archived
    await cm.aclose()


async def test_ensure_webhook_registers_updates_and_secures_deliveries(api, mcp, project, monkeypatch):
    from app.integrations import github as gh

    pid = uuid.UUID(project["id"])
    live = gh.get_settings().model_copy(update={"enable_github": True, "github_token": "tok", "public_url": "https://consensus.example.com"})
    monkeypatch.setattr(gh, "get_settings", lambda: live)

    hooks: list[dict] = []

    def fake_github(req: httpx.Request) -> httpx.Response:
        p, m = req.url.path, req.method
        if p.startswith("/repos/noaccess/"):
            return httpx.Response(404, json={"message": "Not Found"})
        if m == "GET" and p == "/repos/acme/widgets/hooks":
            return httpx.Response(200, json=hooks)
        if m == "POST" and p == "/repos/acme/widgets/hooks":
            h = {"id": 42, "config": json.loads(req.content)["config"]}
            hooks.append(h)
            return httpx.Response(201, json=h)
        if m == "PATCH" and p == "/repos/acme/widgets/hooks/42":
            hooks[0]["config"] = json.loads(req.content)["config"]
            return httpx.Response(200, json=hooks[0])
        return httpx.Response(500, json={"message": f"unexpected {m} {p}"})

    monkeypatch.setattr(gh, "_client", lambda token: httpx.AsyncClient(base_url=gh.API, transport=httpx.MockTransport(fake_github)))

    async with session_scope() as db:
        (await db.get(Project, pid)).repo_full_name = "acme/widgets"

    s1 = await gh.ensure_webhook(pid)
    assert s1.registered and s1.hook_id == 42 and s1.url == "https://consensus.example.com/api/webhooks/github"
    assert hooks[0]["config"]["url"] == s1.url and hooks[0]["config"]["secret"]
    secret = hooks[0]["config"]["secret"]

    s2 = await gh.ensure_webhook(pid)  # second run updates, never duplicates, keeps the secret
    assert s2.registered and s2.hook_id == 42 and len(hooks) == 1 and hooks[0]["config"]["secret"] == secret

    async with session_scope() as db:
        p = await db.get(Project, pid)
        assert p.webhook_id == 42 and p.webhook_secret == secret

    # a delivery signed with the project's own secret retires the claim; an unsigned one is refused
    a = await mcp.call("declare_intent", agent_name="Agent A", plan_text="Add a logout endpoint that deletes the session.", branch="feat/logout", project_id=str(pid))
    async with session_scope() as db:
        from app.db.models import Claim

        (await db.get(Claim, uuid.UUID(a["claim_id"]))).pr_number = 7
    payload = json.dumps({"action": "closed", "pull_request": {"number": 7, "merged": True}, "repository": {"full_name": "acme/widgets"}}).encode()
    assert (await api.post("/api/webhooks/github", content=payload, headers={"X-GitHub-Event": "pull_request", "content-type": "application/json"})).status_code == 401
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    r = await api.post("/api/webhooks/github", content=payload, headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig, "content-type": "application/json"})
    assert r.status_code == 200 and r.json()["retired_claims"] == [a["claim_id"]]

    # a repository the token cannot administer is reported, not raised
    async with session_scope() as db:
        (await db.get(Project, pid)).repo_full_name = "noaccess/private"
    s3 = await gh.ensure_webhook(pid)
    assert not s3.registered and "admin rights" in s3.reason

    # no public URL: explains what to set instead of guessing
    monkeypatch.setattr(gh, "get_settings", lambda: live.model_copy(update={"public_url": None, "frontend_url": "http://localhost:5173"}))
    assert "PUBLIC_URL" in (await gh.ensure_webhook(pid)).reason


async def test_frontend_build_is_served_from_the_same_origin(tmp_path, monkeypatch):
    from app import main as main_mod

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>SPA</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    real_settings = main_mod.get_settings()
    monkeypatch.setattr(main_mod, "get_settings", lambda: real_settings.model_copy(update={"frontend_dist": str(dist)}))

    app = main_mod.create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/")).text == "<html>SPA</html>"
        assert (await c.get("/app/dashboard")).text == "<html>SPA</html>"  # client-side route on refresh
        assert (await c.get("/invite/abc")).text == "<html>SPA</html>"  # dev placeholder page gives way to the app
        assert (await c.get("/assets/app.js")).text == "console.log(1)"
        assert (await c.get("/api/auth/providers")).status_code == 200  # API untouched
        assert (await c.get("/docs")).status_code == 200
        spec = (await c.get("/openapi.json")).json()
        assert spec["components"]["securitySchemes"]["bearerAuth"]["scheme"] == "bearer" and spec["security"] == [{"bearerAuth": []}]
        assert (await c.get("/../etc/passwd")).text == "<html>SPA</html>"  # no path escape

    # without a build, the placeholder pages and the JSON root are what you get
    monkeypatch.setattr(main_mod, "get_settings", lambda: real_settings.model_copy(update={"frontend_dist": str(tmp_path / "nowhere")}))
    app = main_mod.create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/")).json()["service"] == "consensus"
        assert "token" in (await c.get("/invite/abc")).text.lower()
