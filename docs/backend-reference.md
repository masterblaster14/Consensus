# Backend reference

Everything a developer needs to run, extend, or integrate with the Consensus service: setup, layout, the verdict algorithm, the agent tools, the REST and WebSocket contracts, auth and organisations, integrations, and counters. For what Consensus is and why, see the [README](../README.md); for website copy see the other pages in this folder.

## Run it

```bash
docker compose up -d                      # Postgres 16 + pgvector, Redis
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (Windows) or .venv/bin/pip
cp .env.example .env                      # fill in keys, or leave empty for offline mode
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m scripts.seed_demo # idempotent; --reset to wipe the demo project
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

- REST + OpenAPI: `http://localhost:8000/docs`
- MCP (streamable HTTP, for agents): `http://localhost:8000/mcp`
- WebSocket: `ws://localhost:8000/ws/projects/{project_id}`
- Health: `GET /health` → `{"status":"ok","database":true,"redis":true}`

Demo project id (fixed by the seed): `00000000-0000-4000-8000-00000000c0de`.

### Offline mode

With no API keys the service falls back to deterministic offline providers (`STANCE_PROVIDER=keyword`, `EMBEDDING_PROVIDER=hashing`), so the demo and the test suite run with no network. For real use set `ANTHROPIC_API_KEY` (stance extraction, one call per declare) and `OPENAI_API_KEY` (embeddings). Both are swappable behind [app/core/stance.py](../app/core/stance.py) and [app/core/embeddings.py](../app/core/embeddings.py).

### Tests

```bash
.venv/Scripts/python -m pytest -q
```

Runs against the `consensus_test` database and Redis db 1 from Docker Compose, boots a real uvicorn server in the test loop, and drives the MCP tools over HTTP. [tests/test_golden.py](../tests/test_golden.py) is the golden acceptance test from section 12 of the spec.

Against a **running** server (real model, real repo):

```bash
.venv/Scripts/python -m scripts.smoke_e2e      # golden scenario over MCP with the seeded key; fresh project per run
.venv/Scripts/python -m scripts.try_stance     # real stance extraction + comparison on sample plan pairs
.venv/Scripts/python -m scripts.github_e2e     # OAuth-connected org, branches, PR from a handoff, merge webhook (needs DEV_SESSION_TOKEN in .env)
```

Placeholder pages (`/auth/callback`, `/auth/magic`, `/invite/{token}`) let you complete sign-in and invites before the frontend exists; set `FRONTEND_URL` to this server to use them, or to the real frontend to bypass them.

## Layout

```
app/
  main.py                FastAPI app, lifespan, CORS, MCP route
  config.py              settings (pydantic-settings, .env)
  schemas.py             pydantic contracts shared by MCP tools, REST and WS
  db/models.py           SQLAlchemy models   db/migrations/  alembic
  mcp/server.py tools.py MCP server + the agent tools
  core/
    stance.py            plan text -> stance JSON (the one LLM call; + offline keyword extractor)
    embeddings.py        provider interface (OpenAI, offline hashing)
    text.py              deterministic normalisation, synonym map, concept matching
    retrieval.py         pgvector cosine search over claims and memory
    clash.py             deterministic comparison + severity
    rulings.py           prior-ruling lookup
    verdict.py           the declare flow (steps 1-10) + check_verdict long-poll
    memory.py            query/write memory, dedup, token events, counters
    arbitration.py       resolve a clash -> ruling -> release waiter
    handoff.py           file_handoff -> memory entry, in_review, PR
    auth.py              JWTs, API keys, principals, membership checks
  api/                   REST routers (auth, orgs, keys, projects, claims, memory, clashes, webhooks) + WebSocket stream
  mcp/auth.py            bearer auth for the MCP endpoint
  integrations/          github.py, notion.py (feature-flagged, never block declare)
  events/bus.py          Redis pub/sub -> WebSocket fan-out
scripts/seed_demo.py     the demo scenario, idempotent, offline-capable
```

## How a verdict is produced

1. Resolve agent. 2. One Anthropic call extracts `{concepts, error_handling, auth_check, data_access, api_shape, summary}`; axes the plan does not address come back `null` and are skipped. 3. Embed the plan. 4. Retrieve top 10 open claims by other agents and top 5 memory entries (pgvector cosine). 5. Compare deterministically: concept overlap = shared concept names (normalised, non-generic token match) **or** cosine > `CONCEPT_SIMILARITY_THRESHOLD`; divergent axes = both non-null and not agreeing after normalisation (negation-aware; `AXIS_MATCH_OVERLAP` tolerance for wording). 6. Severity: hard / soft / context / clear. 7. A hard clash whose concept + axis already has a `ruling` in memory is auto-resolved and returned as `proceed_with_context`; no human is asked twice. 8. Persist claim + clash rows. 9. Publish events. 10. Return.

Steps 4-8 hold a Redis lock per project. Every verdict is logged with its inputs in `verdict_logs` (`GET /api/projects/{id}/verdicts`) so any clash can be explained after the fact.

Verdict mapping: hard clash without ruling → `wait`; hard clash with ruling, soft clash, or memory hits → `proceed_with_context`; nothing → `proceed`.

## Users, organisations, and how an agent gets connected

**Tenancy.** Organisation → Projects (one per repo) → Members. Whoever creates an organisation becomes its admin. A user sees a project iff they are a member of its organisation. Two roles:

| | admin | member |
|---|---|---|
| see the board, run agents, write memory | yes | yes |
| arbitrate a clash | any | only clashes involving one of their own agents |
| invite / remove members, change roles | yes | no |
| connect GitHub / Notion for the org | yes | no |

**Sign-in.** GitHub OAuth (primary; needs `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`, callback `http://<api>/api/auth/github/callback`) or an email magic link (no email provider is wired yet: the link is logged, and returned in the response when `DEV_AUTH=true`). `POST /api/auth/dev-login` exists only with `DEV_AUTH=true`. `GET /api/auth/providers` tells the frontend which buttons to show. Every REST call then carries `Authorization: Bearer <jwt>`; the WebSocket takes `?token=<jwt>` because browsers cannot set headers on it.

**Joining an org.** Admins mint invite links (`POST /api/orgs/{id}/invites`, optionally pinned to an email and carrying a role). The invitee signs in and calls `POST /api/invites/{token}/accept`. Alternatively an org sets `auto_join_domain` (e.g. `acme.com`) and anyone who signs in with a verified email on that domain becomes a member automatically.

**The human ↔ agent link.** This is the part that makes the board trustworthy:

1. The developer signs in on the dashboard and creates an API key on their profile page (`POST /api/me/api-keys`, optionally bound to a default project). The key is shown once and looks like `csk_…`.
2. They register Consensus as an MCP server in their coding agent with that key as a bearer header, e.g. for Claude Code:

   ```bash
   claude mcp add --transport http consensus http://localhost:8000/mcp --header "Authorization: Bearer csk_..."
   ```

   Cursor / Windsurf / other MCP clients take the same URL + header in their MCP config.
3. From then on the agent calls `declare_intent`, `query_memory`, `write_memory`, `file_handoff` itself. The server derives the developer's identity and organisation from the key: `developer_name` comes from the account (an agent cannot claim to be someone else), agents are owned by the user who first used their name in a project, and the key's project is the default so agents need not pass `project_id`.
4. The dashboard is one shared board per project for the whole team. What differs per user is emphasis: "clashes waiting on you" (blocking your agent, or ones you may arbitrate) and a "my agents" filter. Nothing is hidden per user.

Unauthenticated MCP / REST calls are rejected (401) unless `MCP_AUTH_REQUIRED=false`, which restores the pre-auth single-tenant behaviour for local experiments.

**Integration credentials are per organisation.** GitHub: an admin who signed in with GitHub calls `POST /api/orgs/{id}/integrations/github/connect`, which attaches their OAuth token (scope includes `repo`) to the org; `GET /api/orgs/{id}/integrations/github/repos` lists repos for the "create project" picker. Notion internal integrations have no OAuth, so an admin pastes the token and tasks database id via `PUT /api/orgs/{id}/integrations/notion`. `GITHUB_TOKEN` / `NOTION_TOKEN` env vars remain a server-wide fallback.

### Auth & org endpoints

```
GET  /api/auth/providers                    {github, magic_link, dev_login}
GET  /api/auth/github/start?redirect_to=    {url}  -> browser goes there; callback redirects to FRONTEND_URL/auth/callback#token=<jwt>&next=
POST /api/auth/magic-link                   {email, name?} -> link emailed (dev: dev_link/dev_token in response)
POST /api/auth/magic-link/verify            {token} -> {token: <jwt>, me}
POST /api/auth/dev-login                    {email, name?} -> {token, me}     (DEV_AUTH=true only)
GET  /api/auth/me                           {user, memberships[{org_id, org_name, org_slug, role}]}

GET  /api/orgs                              my orgs (with my role + integration status)
POST /api/orgs                              {name, slug?, auto_join_domain?} -> OrgOut (creator = admin)
GET  /api/orgs/{id}   PATCH /api/orgs/{id}  {name?, auto_join_domain?}          (admin)
GET  /api/orgs/{id}/members                 [MembershipOut]
PATCH /api/orgs/{id}/members/{user_id}      {role}                              (admin; last admin protected)
DELETE /api/orgs/{id}/members/{user_id}     admin removes anyone; a member removes themselves
POST /api/orgs/{id}/invites                 {email?, role?} -> {token, url, ...}  (admin)
GET  /api/orgs/{id}/invites  DELETE /api/orgs/{id}/invites/{invite_id}
GET  /api/invites/{token}                   public preview {org_name, role, email}
POST /api/invites/{token}/accept            -> OrgOut (signed-in user joins)
GET  /api/orgs/{id}/projects  POST /api/orgs/{id}/projects {name, repo_full_name?}
POST /api/orgs/{id}/integrations/github/connect   DELETE .../github   GET .../github/repos
PUT  /api/orgs/{id}/integrations/notion {notion_token, notion_tasks_db_id}   DELETE .../notion

GET  /api/me/api-keys                       [ApiKeyOut]  (prefix only)
POST /api/me/api-keys                       {name?, org_id?, project_id?} -> {key (once), mcp_url, ...}
DELETE /api/me/api-keys/{key_id}            revoke
```

Seeded demo: org `Consensus Demo`, admin `demo@example.com` (dev-login), members Priya / Marcus / Lena, and an admin API key printed by the seed script.

## Agent tools (MCP at `/mcp`)

| Tool | Input | Output |
|---|---|---|
| `declare_intent` | `agent_name, developer_name, plan_text, task_ref?, branch?, wait_seconds?=0, project_id?` | `{claim_id, verdict, context[], clash, clash_id, ruling, severity, project_id, agent_id, duration_ms}` |
| `check_verdict` | `clash_id, wait_seconds?=0` (long-poll up to 120s) | `{clash_id, status, verdict, resolution, resolution_note, resolved_by, ruling}` |
| `query_memory` | `question, limit?=5, agent_name?, project_id?` | `{entries[{type, content, source_agent, created_at, entry_id, similarity}], tokens_used}` |
| `write_memory` | `agent_name, type, content, concepts?, project_id?` | `{entry_id, deduplicated}` |
| `file_handoff` | `claim_id, changed[], untouched[], assumptions[], uncertainties[]` | `{entry_id, pr_url, pr_number}` |
| `report_usage` | `agent_name, tokens, kind?=codebase_read, project_id?` | `{event_id, kind, tokens}` |

Agents authenticate with `Authorization: Bearer csk_…` (an API key from `POST /api/me/api-keys`). `project_id` is optional: the key's bound project is used, else the caller's only project. `developer_name` is ignored when authenticated and taken from the account. `check_verdict` and `report_usage` are additions the spec's flow relies on (the `wait` verdict tells agents to poll `check_verdict`; `codebase_read` events power the tokens-saved counter).

## REST API (for the dashboard)

All JSON. CORS is enabled for `CORS_ORIGINS` (default: localhost:3000 and :5173). Every route requires `Authorization: Bearer <jwt or api key>` and is scoped to the caller's organisations; `GET /api/projects` lists only projects the caller can see.

```
GET  /api/projects                              [ProjectOut]
POST /api/projects                              {name, repo_full_name?, id?} -> ProjectOut
GET  /api/projects/{id}                         ProjectOut
GET  /api/projects/{id}/agents                  [AgentOut]
GET  /api/projects/{id}/tasks                   [TaskOut]
GET  /api/projects/{id}/claims?status=&agent=   [ClaimOut]      status: open|in_review|retired
GET  /api/claims/{claim_id}                     ClaimOut
GET  /api/projects/{id}/memory?type=&q=         [MemoryEntryOut] q = semantic search
GET  /api/projects/{id}/clashes?status=&severity= [ClashOut]    status: open|resolved|auto_resolved
GET  /api/clashes/{clash_id}                    ClashOut
GET  /api/clashes/{clash_id}/verdict?wait_seconds=  CheckVerdictResult (long-poll)
POST /api/clashes/{clash_id}/resolve            {resolution, note, resolved_by} -> ClashOut + ruling
GET  /api/projects/{id}/counters                {tokens_saved, clashes_caught, memory_count, open_claims, open_clashes, agents}
GET  /api/projects/{id}/verdicts?limit=         verdict log with inputs (why did this clash fire?)
POST /api/projects/{id}/token-events            {agent_name, kind, tokens}
POST /api/webhooks/github                       GitHub webhook (pull_request.closed -> claim retired)

REST mirrors of the agent tools (same shapes as the MCP outputs):
POST /api/projects/{id}/declare                 DeclareRequest -> DeclareResult
GET  /api/projects/{id}/memory/query?question=  QueryMemoryResult
POST /api/projects/{id}/memory                  WriteMemoryRequest -> WriteMemoryResult
POST /api/claims/{claim_id}/handoff             {changed[], untouched[], assumptions[], uncertainties[]} -> FileHandoffResult
POST /api/projects/{id}/integrations/github/sync    sync_open_prs
POST /api/projects/{id}/integrations/notion/sync    sync_tasks
```

Resolution semantics: `a_proceeds` = the earlier claim (`claim_a`) proceeds; `b_proceeds` = the newer claim (`claim_b`, the one that received `wait`) proceeds; `both_with_note`.

`ClashOut` carries denormalised fields the board needs: `agent_a`, `agent_b`, `intent_a`, `intent_b`, `position_a`, `position_b`, `axis`, `shared_concepts`, `severity`, `status`, `resolution`, `resolution_note`, `resolved_by`. `ClaimOut` carries `agent_name`, `developer_name`, `task_ref`, `stance`, `concepts`, `branch`, `pr_number`, `status`.

Full schemas: `GET /openapi.json` or [app/schemas.py](../app/schemas.py).

## WebSocket `/ws/projects/{id}`

Every frame:

```json
{"id": "uuid", "type": "clash.opened", "project_id": "…", "ts": "2026-09-05T12:00:00+00:00", "data": {…}}
```

First frame is `{"type":"hello","data":{"counters":{…}}}`. Send `"ping"` to get `{"type":"pong"}`.

| type | data |
|---|---|
| `claim.created` | `{claim: ClaimOut, verdict}` |
| `claim.retired` | `{claim_id, pr_number, merged}` |
| `clash.opened` | `{clash: ClashOut}` |
| `clash.resolved` | `{clash: ClashOut, auto: bool, ruling: ContextItem}` (`auto=true` when a prior ruling short-circuited) |
| `memory.written` | `{entry: MemoryEntryOut}` |
| `memory.read` | `{agent, question, hits, tokens_used}` |
| `handoff.filed` | `{claim: ClaimOut, entry_id, changed, untouched, assumptions, uncertainties}` |
| `pr.opened` | `{claim_id, pr_url, pr_number}` |

Events are not persisted; on reconnect, re-fetch claims / clashes / memory / counters and resume the stream.

## Integrations

- **GitHub** (`ENABLE_GITHUB`; token from the org's connected admin or `GITHUB_TOKEN`; project needs `repo_full_name`): `file_handoff` opens (or updates) a PR from `claim.branch` with the intent, changed/untouched lists, assumptions, uncertainties and clash resolutions. Resolving a clash comments on the related PR. `sync_open_prs` creates `in_review` claims for untracked PRs. Webhook `pull_request.closed` retires the claim (HMAC verified with `GITHUB_WEBHOOK_SECRET`).
- **Notion** (`ENABLE_NOTION`; token + tasks database id from the org settings or `NOTION_TOKEN` / `NOTION_TASKS_DB_ID`): `sync_tasks` upserts tasks from the database; `decision`, `dead_end` and `ruling` entries are mirrored as pages.

Both are fire-and-forget from the declare / resolve / handoff paths; a failure is logged and never changes a verdict.

## Counters

`tokens_saved` = Σ over `memory_read` events of `max(0, avg(codebase_read tokens in project) − memory_read tokens)`. One function: `app/core/memory.py::tokens_saved`.
