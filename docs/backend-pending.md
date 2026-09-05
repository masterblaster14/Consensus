# Backend: pending changes

The single queue of backend work. Section A came from reviewing the merged frontend (`frontend/` on the `Frontend` branch) against the REST and WebSocket contract in [backend-reference.md](backend-reference.md). Section B carries the operational gaps from [qa.md](qa.md). Section C lists frontend assumptions that need **no** backend change, only a different frontend approach.

**Status on 2026-09-06:** everything in A except the team-secret decision (item 6) is built, migrated (`alembic upgrade head` → `0003_frontend_queue`) and covered by `tests/test_queue.py`. In B, email delivery, encryption at rest and background PR sync are built; metering and webhook registration remain.

## A. Needed by the frontend

### 1. Persisted activity feed — done
- `events` table written by the event bus on every publish; `GET /api/projects/{id}/activity?limit=&before=<ts>&type=a,b` returns frames in the WebSocket shape (`id, type, project_id, ts, data`), newest first. Page by passing the last frame's `ts` as `before`.
- Frontend: load this on mount, then apply live WebSocket frames on top.

### 2. Agents enriched with current work — done
- `AgentOut` now carries `status` (`working` = has an open claim, `reviewing` = newest non-retired claim is in review, `idle`), `open_claims`, and `current_claim` (`id, intent_text, status, branch, task_ref, pr_number, created_at`).
- Frontend: "progress %" and "role" still have no data source. Use `current_claim.intent_text` as the task line and `branch` as the branch chip.

### 3. Delete or archive a project — done
- `DELETE /api/projects/{id}` and `DELETE /api/orgs/{org_id}/projects/{id}` (admin) set `archived_at`. Archived projects drop out of every list unless `?include_archived=true`, reject declarations and writes with 403, and keep serving reads so history stays visible. `POST .../restore` undoes it. `ProjectOut.archived_at` says which state a project is in.

### 4. Restrict a member — done
- `Membership.status` = `active | restricted`. `PATCH /api/orgs/{id}/members/{user_id}` takes `{role?, status?}` (at least one). A restricted principal, over REST or an API key, gets 403 on `declare_intent`, `write_memory`, `file_handoff`, `report_usage`, task edits, clash resolution and every admin route, and keeps all reads including `query_memory`. A restricted admin has no admin powers until reinstated. The last **active** admin cannot be restricted, demoted or removed (409). `MembershipOut.status` and `/api/auth/me` memberships carry the status.

### 5. Org summary — done
- `GET /api/orgs/{id}/summary` → `{projects, repositories, members, agents, active_agents, open_claims, open_clashes, memory_count, tokens_saved}`. `active_agents` = seen in the last 24 hours. Archived projects are excluded.

### 6. Team-level access — decision still needed
- **Frontend assumes:** after joining an organisation via invite link, a person also enters a **Team ID + Team Secret** to get into a team, and admins generate those credentials per team.
- **Backend has:** organisation membership only. Every project in an org is visible to every member. No per-project secret, no per-project membership.
- **Options:**
  - (a) **Recommended:** drop the team secret. Joining the org via the invite link is the whole flow. Zero backend work; the frontend removes the Join Team screen and the secret display on Add Team.
  - (b) Project-scoped invites: `POST /api/orgs/{id}/projects/{pid}/invites`, a `project_members` table, and visibility limited to project members plus org admins. Medium effort and touches every project-scoped query and the MCP key resolution.
- **Until decided:** the frontend builds (a).

### 7. Manual tasks — done
- `POST /api/projects/{id}/tasks {title, external_ref?, status?}` (409 on a duplicate `external_ref`), `PATCH /api/projects/{id}/tasks/{task_id} {title?, external_ref?, status?, assignee_agent?}` (`assignee_agent` is an agent name; `""` clears), `DELETE .../tasks/{task_id}` (claims keep their history, the link is cleared). `GET .../tasks?status=` filters. `TaskOut` gained `status` (`open | in_progress | done`), `assignee_agent_id`, `assignee_agent`, `created_at`. A declared `task_ref` still auto-creates the task when it does not exist.
- Not done on purpose: no automatic status changes from declarations or handoffs. Add if the team wants it.

### 8. Clash presentation fields — done
- `ClashOut` gained `title` ("Auth check conflict on session model, login"), `explanation` (one sentence built from both agents' positions), `severity_label` (`hard` → high, `soft` → medium, `context` → low).

### 9. Memory entry title — done
- `MemoryEntryOut.title`: the concepts joined, else the first sentence of the content, capped at 80 characters.

### 10. Clash resolution by the signed-in user — already worked
- `resolved_by` may be `""` or `"human"`; the backend substitutes the caller's email.

### 11. Claim lifecycle — done
- `withdraw_claim` (MCP) / `POST /api/claims/{id}/withdraw` retires a plan and auto-resolves any clash it was part of, releasing the waiting agent with the reason as its ruling. `get_status` / `GET /api/projects/{id}/status` shows an agent's live claims and clashes. Open claims older than `CLAIM_TTL_HOURS` with no PR are expired hourly by the scheduler.

### 12. Demo resilience — done
- Stance extraction falls back to the keyword extractor when the model call fails; `STANCE_MODEL` defaults to `claude-sonnet-5` for latency; `DATABASE_URL` accepts the `postgres://` form hosted providers hand out.

## B. Operational gaps (carried from qa.md)

- **Email delivery — done.** `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` / `SMTP_STARTTLS` in `.env`. Magic links and emailed invites go out through it; responses carry `sent` / `email_sent` so the UI can say "check your inbox" or "copy this link". Without `SMTP_HOST` the link is logged, and `/api/auth/providers` only offers magic links when SMTP is configured or `DEV_AUTH=true`.
- **Encryption at rest — done.** GitHub OAuth tokens and Notion tokens are Fernet-encrypted (`app/db/crypto.py`, `TOKEN_ENCRYPTION_KEY`, comma-separate keys to rotate). Rows written before this build are read as plaintext and rewritten by `python -m scripts.encrypt_tokens`.
- **Background PR sync — done.** `PR_SYNC_INTERVAL_SECONDS` (default 300, 0 disables) runs `sync_open_prs` over every live project with a repository from the app lifespan.
- **Deployment — packaged.** Dockerfile, entrypoint that migrates on boot, `render.yaml` blueprint, compose `full` profile, CI workflow. Steps and the safety settings are in [deploy.md](deploy.md). Hosting it is the remaining manual step.
- **Register the real GitHub webhook** URL and secret once deployed. Deployment step, not code.
- **Metering and billing.** Pricing tiers on the landing page are not enforced anywhere. Product decision first.
- **Unexercised with real keys:** OpenAI embeddings, Notion, live stance extraction in the current environment, SMTP against a real server.

## C. Frontend assumptions that need no backend change

- **Sign-in comes first.** The mock creates an organisation from a name and org name with no account. The backend requires a signed-in user (`/api/auth/*`) before `POST /api/orgs`; the frontend adds a sign-in step.
- **Invite link format.** Use the `url` returned by `POST /api/orgs/{id}/invites` (`FRONTEND_URL/invite/{token}`), not the mock's `https://consensus.ai/join?org=&token=`.
- **Add member by name and email.** Maps to creating an invite for that email (now also emailed when SMTP is configured). Users are created when they sign in and accept.
- **Shift team domain.** Maps to the org-level `auto_join_domain` via `PATCH /api/orgs/{id}`. No per-team domain.
- **Conflict resolution options.** `a_proceeds`, `b_proceeds`, `both_with_note` with a note, not free-text architecture choices.
- **"Agent velocity 87%" and per-agent "progress %"** have no data source. Use `counters.tokens_saved` and `counters.clashes_caught` instead.
- **WebSocket auth** uses `?token=` because browsers cannot set headers.
- **CORS** already allows `localhost:5173`; in dev the Vite proxy makes calls same-origin anyway.

## Frontend client additions

`frontend/src/lib/api.ts` on the `Frontend` branch predates this work. Add:

```ts
projectApi.activity  = (id, f: {limit?: number; before?: string; type?: string} = {}) => get<StreamFrame[]>(`/api/projects/${id}/activity${q(f)}`)
projectApi.archive   = (id) => del<void>(`/api/projects/${id}`)
projectApi.restore   = (id) => post<Project>(`/api/projects/${id}/restore`)
projectApi.createTask = (id, b: {title: string; external_ref?: string; status?: TaskStatus}) => post<Task>(`/api/projects/${id}/tasks`, b)
projectApi.updateTask = (id, taskId, b: {title?: string; external_ref?: string; status?: TaskStatus; assignee_agent?: string}) => patch<Task>(`/api/projects/${id}/tasks/${taskId}`, b)
projectApi.deleteTask = (id, taskId) => del<void>(`/api/projects/${id}/tasks/${taskId}`)
orgApi.summary       = (orgId) => get<OrgSummary>(`/api/orgs/${orgId}/summary`)
orgApi.updateMember  = (orgId, userId, b: {role?: Role; status?: 'active' | 'restricted'}) => patch<Membership>(`/api/orgs/${orgId}/members/${userId}`, b)
orgApi.archiveProject = (orgId, pid) => del<void>(`/api/orgs/${orgId}/projects/${pid}`)
```

and extend the types: `Agent` gains `status`, `open_claims`, `current_claim`; `Task` gains `status`, `assignee_agent_id`, `assignee_agent`, `created_at`; `Clash` gains `title`, `explanation`, `severity_label`; `MemoryEntry` gains `title`; `Project` gains `archived_at`; `Membership` gains `status`; `Invite` gains `email_sent`.
