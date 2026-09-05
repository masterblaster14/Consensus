# Consensus frontend

One Vite + React + TypeScript app that combines the two earlier branches:

- the marketing site, onboarding, admin console and "My Teams" (was `Frontend`)
- the per-team agent dashboard (was `frontend_pari`)

Everything on screen today renders **mock data held in React state**. No screen calls the backend yet. The typed client in `src/lib/api.ts` maps every backend endpoint the screens need, so wiring a screen means replacing its local state with a call from that file.

## Run it

```bash
# backend (from the repo root) — see docs/getting-started.md
docker compose up -d && uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build
npm run lint
```

In dev, `vite.config.ts` proxies `/api` and `/ws` to `localhost:8000`, so the app uses relative URLs and needs no CORS setup. For a deployed build set `VITE_API_URL` (see `.env.example`).

## Layout

```
src/
  App.tsx                  router: /app/* -> dashboard, everything else -> landing
  main.tsx, index.css      entry + global reset only
  landing/
    LandingApp.tsx         marketing site, onboarding, join-team, admin console, My Teams
    landing.css
  dashboard/
    DashboardApp.tsx       agent dashboard (sidebar shell + pages)
    dashboard.css
  lib/api.ts               typed backend client + WebSocket helper (not used by the UI yet)
  assets/hero.png
```

### Routes

| Path | Screen | File |
|---|---|---|
| `/` | Landing page (hero, how it works, features, pricing, getting started) | landing |
| `/` + internal state | Onboarding: create org / join org, join team, admin console pages, My Teams | landing |
| `/app/dashboard` | Dashboard overview (`?team=<id>` is passed but not read yet) | dashboard |
| `/app/agents`, `/app/agents/:agentId` | Agents list and agent detail | dashboard |
| `/app/conflicts` | Conflicts list + arbitration | dashboard |
| `/app/memory` | Shared memory | dashboard |
| `/app/activity` | Activity timeline | dashboard |
| `/app/claims`, `/app/tasks`, `/app/team`, `/app/integrations`, `/app/settings` | Placeholders | dashboard |

The landing app does not use URL routes for its internal views (onboarding, admin pages, My Teams). They live in `appState` / `adminPage` / `empPage` inside `LandingApp`. Because of that, leaving to `/app` and coming back resets the landing app to the marketing page. That goes away once sign-in state comes from the stored token rather than component state; converting those views to real routes is on the list below.

### How the two apps are kept apart

- Each half imports its own stylesheet. Two class names existed in both (`primary-button`, `stat-card`); the dashboard's copies are renamed `dash-primary-button` / `dash-stat-card`. The dashboard's `footer` rule is scoped to `.app-shell footer`.
- Both share `--orange`, `--white`, `--black` from `landing.css`. Dashboard-only variables (`--navy`, `--paper`, `--line`, `--muted`, ...) live in `dashboard.css`.
- Keep new dashboard styles under `.app-shell` and new landing styles under `.page-root` or `.topnav` so they never leak into each other.

### Vocabulary: UI vs backend

| UI says | Backend has | Notes |
|---|---|---|
| Organisation | `Org` (`/api/orgs`) | creator = admin |
| Team | `Project` (`/api/orgs/{id}/projects`, `/api/projects/{id}`) | a project may carry `repo_full_name` |
| Member | `Membership` (org-level, role `admin` or `member`) | no team-level membership today |
| Team ID + Team Secret | nothing | see docs/backend-pending.md item 6 |
| Invite link | `POST /api/orgs/{id}/invites` returns `url` (`FRONTEND_URL/invite/{token}`) | preview `GET /api/invites/{token}`, accept `POST /api/invites/{token}/accept` |
| Agent | `Agent` | name, developer_name, last_seen only |
| Claim | `Claim` | one per `declare_intent` |
| Conflict | `Clash` | severity `hard` / `soft` / `context` |
| Ruling / Shared memory | `MemoryEntry` types `ruling`, `decision`, `discovery`, `dead_end`, `handoff` | |

## What is built (all mock)

**Landing** (`src/landing`)
- Marketing page: hero, how it works, features, pricing cards, getting started, responsive top nav with mobile menu.
- Onboarding: choose create / join, create organisation form, join organisation via pasted invite link.
- Join team: Team ID + Secret form with error state and "skip".
- Admin console: dashboard tiles (teams, members, repositories, active agents), teams list, members list, user dropdown with nested "manage teams" / "manage members" menus.
- Admin pages: add team (generates id + secret, copy buttons), delete team (confirm), shift team domain, manage members (invite banner + table), add member, restrict member (toggle), delete member.
- Employee: My Teams grid; "Open Dashboard" goes to `/app/dashboard?team=<id>`.

**Dashboard** (`src/dashboard`)
- Shell: sidebar with counts, workspace switcher, top bar with search, theme toggle, notifications popover, "Back to site".
- Dashboard: four stat tiles, agents-at-work list with status filter and search, needs-attention conflict card, recent activity, shared-memory teaser.
- Agents: cards with progress; agent detail with plan, activity, claims, related conflicts.
- Conflicts: side-by-side plans, explanation, severity, arbitration radio + save ruling, resolved state.
- Shared memory: typed entries, "just saved" highlight after a ruling.
- Activity: full timeline.
- Placeholders: claims, tasks, team, integrations, settings.

## What is left to build

Ordered so that a demo against the real backend becomes possible as early as possible.

1. **Sign-in and session.** Screen with the providers from `authApi.providers()`: GitHub (`githubStart` then read `#token=` on `/auth/callback`), magic link (`magicLink` then `magicVerify` on `/auth/magic`), and dev-login when the backend reports it. Store the JWT with `auth.set`, load `authApi.me()`, redirect to onboarding if the user has no memberships. Sign-out clears the token. Add `/auth/callback`, `/auth/magic`, `/invite/:token` routes (the backend's dev pages at `app/api/devpages.py` are the reference for what each must do).
2. **Create organisation → real.** `orgApi.create({name})` after sign-in. Drop the "Your Name" field (name comes from the account).
3. **Join organisation → real.** Parse the token from the pasted link or from `/invite/:token`, show `inviteApi.preview`, call `inviteApi.accept`. Replace the mock `https://consensus.ai/join?...` format with the backend's `url`.
4. **Teams = projects.** Admin add team → `orgApi.createProject(orgId, {name, repo_full_name?})` with a repo picker from `orgApi.github.repos` when GitHub is connected. My Teams → `projectApi.list()`. Team ID + Secret has no backend equivalent; see backend-pending item 6 and, until that is decided, hide the secret UI.
5. **Members → real.** List `orgApi.members`; add member → `orgApi.createInvite({email, role})` and show the link; delete → `orgApi.removeMember`; role change → `orgApi.setRole`. "Restrict" needs backend-pending item 4. "Shift domain" → `orgApi.update(orgId, {auto_join_domain})` at org level (there is no per-team domain).
6. **API key page (Settings).** This is how an agent gets connected and the product does nothing without it: `keyApi.create({project_id})` shows the `csk_` key once plus `mcp_url` and the `claude mcp add ...` command from docs/backend-reference.md; `keyApi.list` / `keyApi.revoke` for management.
7. **Dashboard data layer.** Replace `DemoProvider` with a project context: pick the project from `?team=` or the workspace switcher (`projectApi.list`), load `counters`, `agents`, `claims`, `clashes`, `memory` in parallel, then `openProjectStream` and apply `claim.created`, `clash.opened`, `clash.resolved`, `memory.written`, `handoff.filed`, `pr.opened` to state. On reconnect, re-fetch.
8. **Agents page → real.** Derive status from claims (`open` → Working, `in_review` → Reviewing, none → Idle); task / branch from the newest claim; "role" and "progress %" have no data, drop them or wait for backend-pending item 2.
9. **Conflicts → real.** Headline from `axis` + `shared_concepts`, cards from `intent_a/b` and `position_a/b`, severity `hard` → HIGH, `soft` → MEDIUM. Arbitration options become `a_proceeds` / `b_proceeds` / `both_with_note` plus a note field; submit with `clashApi.resolve`. Resolved state shows `resolution_note`, `resolved_by`, and the returned `ruling`. Add a "waiting on you" filter (clashes where the newer claim belongs to my agent).
10. **Shared memory → real.** `projectApi.memory({type, q})`; the search box drives `q` (semantic). Entries have no title: show `concepts` as the heading and `content` as body. Add a "write memory" form for humans (`POST /api/projects/{id}/memory`).
11. **Activity → real.** Until backend-pending item 1 lands, build the timeline from claims, clashes, and memory timestamps and append live WS events.
12. **Claims page.** Table from `projectApi.claims({status, agent})`: agent, developer, intent, concepts, branch, PR number, status; detail drawer with the stance axes. This is the page that explains "why did this clash fire" together with `projectApi.verdicts`.
13. **Tasks page.** `projectApi.tasks` (Notion-synced) with a sync button. "New task" needs backend-pending item 7.
14. **Team page.** Org members and which agents belong to each (agent `user_id` → member).
15. **Integrations page.** GitHub connect / disconnect / repo list, Notion token + database id form, per-project sync buttons.
16. **Settings page.** Org name and auto-join domain, project repo, API keys (item 6), theme.
17. **Notifications.** Bell shows open clashes and recent `clash.opened` events; "needs your attention" card uses the same list.
18. **Routing cleanup.** Turn the landing app's internal views into routes (`/onboarding`, `/join`, `/admin/...`, `/teams`) so refresh and back button work and state survives visiting `/app`.
19. **Polish.** Error and loading states, empty states with a "connect your first agent" call to action, mobile layout for the dashboard sidebar.

Backend changes that the above depends on are queued in `docs/backend-pending.md`.
