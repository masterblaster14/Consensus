# Backend: pending changes

The single queue of backend work. Section A comes from reviewing the merged frontend (`frontend/`) against the REST and WebSocket contract in [backend-reference.md](backend-reference.md). Section B carries the operational gaps already listed in [qa.md](qa.md) so nothing is tracked in two places. Section C lists frontend assumptions that need **no** backend change, only a different frontend approach, so nobody files them as backend work.

Ordering inside A is by how much frontend work each one unblocks.

## A. Needed by the frontend

### 1. Persisted activity feed
- **Add:** `events` table written from the event bus on every publish; `GET /api/projects/{id}/activity?limit=&before=` returning the same envelope as the WebSocket frames (`id, type, ts, data`), newest first.
- **Why:** the dashboard's "Recent activity" panel, the Activity page and the agent detail timeline all show a history. WebSocket events are not persisted today, so every page load starts empty until something happens.
- **Size:** small. One table, one insert in `app/events/bus.py`, one route.

### 2. Agents enriched with current work
- **Add:** on `AgentOut` (or via `?include=current`): `status` (`working` if the agent has an open claim, `reviewing` if its newest claim is `in_review`, else `idle`), `current_claim` (`id, intent_text, branch, task_ref, status, created_at`), `open_claims`.
- **Why:** the Agents page and the "Agents at work" rows show status, task and branch per agent. Every screen that lists agents would otherwise join claims client-side.
- **Size:** small. `AgentOut` gains optional fields; one query in `app/api/projects.py`.

### 3. Delete or archive a project
- **Add:** `DELETE /api/orgs/{org_id}/projects/{project_id}` (admin only) as a soft delete (`archived_at`); archived projects drop out of every list and reject new declarations.
- **Why:** the admin console has a "Delete Teams" page and there is no endpoint for it.
- **Size:** small. Migration adds one column; list queries filter on it.

### 4. Restrict a member
- **Add:** `Membership.status` = `active | restricted`; `PATCH /api/orgs/{id}/members/{user_id}` accepts `{status}` alongside `{role}`; a restricted principal (JWT or API key) gets 403 on `declare_intent`, `write_memory`, `file_handoff`, clash resolution and org admin routes, and keeps read access.
- **Why:** the admin console has a "Restrict Members" toggle. The backend only knows role and removal.
- **Size:** small to medium. Migration, one check in `app/api/deps.py` / `app/mcp/auth.py`, last-admin protection must ignore restricted admins.

### 5. Org summary
- **Add:** `GET /api/orgs/{id}/summary` → `{projects, members, repositories, active_agents, open_clashes, open_claims}`.
- **Why:** the admin dashboard's four tiles. Without it the frontend calls projects, members and each project's counters separately.
- **Size:** small.

### 6. Team-level access (decision needed)
- **Frontend assumes:** after joining an organisation via invite link, a person also enters a **Team ID + Team Secret** to get into a team, and admins generate those credentials per team.
- **Backend has:** organisation membership only. Every project in an org is visible to every member. No per-project secret, no per-project membership.
- **Options:**
  - (a) **Recommended:** drop the team secret. Joining the org via the invite link is the whole flow. Zero backend work; the frontend removes the Join Team screen and the secret display on Add Team.
  - (b) Project-scoped invites: `POST /api/orgs/{id}/projects/{pid}/invites`, a `project_members` table, and visibility limited to project members plus org admins. Medium effort and touches every project-scoped query and the MCP key resolution.
- **Until decided:** the frontend builds (a).

### 7. Manual tasks
- **Add:** `POST /api/projects/{id}/tasks {title, external_ref?}`, `PATCH /api/projects/{id}/tasks/{task_id} {title?, status?, assignee_agent?}`, and `status` + `assignee` on `TaskOut`.
- **Why:** the dashboard has a "New task" button and a Tasks page with a count. Tasks are currently only created by Notion sync and have no status.
- **Size:** small.

### 8. Clash presentation fields (optional)
- **Add:** on `ClashOut`: `title` (e.g. "Session model: server-side store vs signed tokens", built from `axis` and `shared_concepts`), `explanation` (one deterministic sentence from the two positions), `severity_label` (`hard` → high, `soft` → medium, `context` → low).
- **Why:** the Conflicts page shows a headline and a plain-English explanation. The frontend can template these; a backend field keeps the wording identical to the PR comment the backend already writes.
- **Size:** small.

### 9. Memory entry title (optional)
- **Add:** `title` on `MemoryEntryOut` (concept list or first sentence).
- **Why:** the Shared Memory cards show a title over the content. Frontend can derive it; listed here only so the choice is deliberate.

### 10. Clash resolution by the signed-in user
- **Already works:** `resolved_by` may be sent as `""` or `"human"` and the backend substitutes the caller's email. No change; documented here so the frontend does not build a "who are you" field.

## B. Operational gaps (carried from qa.md)

- **Email delivery for magic links.** Non-GitHub sign-in on the frontend depends on it; dev mode returns the link in the response.
- **Encryption at rest** for stored GitHub OAuth and Notion tokens.
- **Background PR sync** scheduler (the endpoint exists; nothing calls it periodically).
- **Register the real GitHub webhook** URL and secret once deployed.
- **Metering and billing.** Pricing tiers on the landing page are not enforced anywhere.
- **Unexercised with real keys:** OpenAI embeddings, Notion, live stance extraction in the current environment.

## C. Frontend assumptions that need no backend change

- **Sign-in comes first.** The mock creates an organisation from a name and org name with no account. The backend requires a signed-in user (`/api/auth/*`) before `POST /api/orgs`; the frontend adds a sign-in step.
- **Invite link format.** Use the `url` returned by `POST /api/orgs/{id}/invites` (`FRONTEND_URL/invite/{token}`), not the mock's `https://consensus.ai/join?org=&token=`.
- **Add member by name and email.** Maps to creating an invite for that email. Users are created when they sign in and accept; there is no direct user creation.
- **Shift team domain.** Maps to the org-level `auto_join_domain` via `PATCH /api/orgs/{id}`. No per-team domain.
- **Conflict resolution options.** `a_proceeds`, `b_proceeds`, `both_with_note` with a note, not free-text architecture choices.
- **"Agent velocity 87%" and per-agent "progress %"** have no data source. Use `counters.tokens_saved` and `counters.clashes_caught` instead.
- **WebSocket auth** uses `?token=` because browsers cannot set headers.
- **CORS** already allows `localhost:5173`; in dev the Vite proxy makes calls same-origin anyway.
