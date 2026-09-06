# Consensus web app

The product's frontend: the public site, sign-in, onboarding, and the per-team dashboard. Every screen runs on the backend's REST API and WebSocket; nothing on screen is mock data.

## Run it

The backend serves this app from the same origin whenever a build exists at `frontend/dist` (the Dockerfile builds it on deploy). For local work:

```bash
# backend, from the repo root (see docs/getting-started.md)
docker compose up -d && .venv/Scripts/python -m uvicorn app.main:app --port 8000

# frontend, from this directory
npm install
npm run dev        # http://localhost:5173, proxies /api and /ws to :8000
npm run build      # tsc -b && vite build -> dist/, which the backend then serves at :8000
npm run lint
```

With `DEV_AUTH=true` on the backend, the sign-in page offers a development sign-in that accepts any email. On the hosted instance only the configured providers appear (GitHub today; email links once SMTP is set).

## Layout

```
src/
  App.tsx                 router: /app/* is the dashboard behind RequireAuth, everything else is public
  lib/api.ts              typed client for every backend endpoint the screens use (paths and shapes mirror app/schemas.py)
  lib/session.tsx         who is signed in, current organisation, its teams and members, all write operations
  lib/project.tsx         live data for the selected team: REST load + WebSocket updates, arbitration, memory writes
  lib/theme.tsx, icons.tsx
  landing/LandingApp.tsx  marketing page, sign in / sign up, /auth/callback, /auth/magic, /invite/:token, onboarding
  dashboard/DashboardApp.tsx  the dashboard shell and every page
  theme.css, index.css, landing/landing.css, dashboard/dashboard.css
```

## How it maps to the backend

| Screen | Backend |
|---|---|
| Sign in with GitHub | `GET /api/auth/github/start` then the callback lands on `/auth/callback#token=` |
| Development sign-in / email link | `POST /api/auth/dev-login`, `POST /api/auth/magic-link` + `/auth/magic?token=` |
| Session | `GET /api/auth/me`; the JWT lives in `localStorage` under `consensus.token` |
| Create / join organisation | `POST /api/orgs`, `GET /api/invites/{token}`, `POST /api/invites/{token}/accept` |
| Teams | projects: `GET/POST /api/orgs/{id}/projects`, `PATCH /api/projects/{id}`, archive via `DELETE` |
| Members, invites, restriction, roles | `GET /api/orgs/{id}/members`, `PATCH .../members/{user_id}`, `POST .../invites` |
| Overview, agents, claims, conflicts, memory, tasks, activity | `GET /api/projects/{id}/...` loaded together, then `/ws/projects/{id}` keeps them current |
| Rule on a conflict | `POST /api/clashes/{id}/resolve`; the ruling comes back and is written to memory |
| Add to memory, withdraw a claim | `POST /api/projects/{id}/memory`, `POST /api/claims/{id}/withdraw` |
| API keys | `GET/POST/DELETE /api/me/api-keys`; the key and MCP URL are shown once |
| Integrations | GitHub connect / disconnect / repos, Notion connect, per-team sync and webhook registration |

Vocabulary: the UI says organisation and team; the backend says org and project. Every member of an organisation sees every team in it. There is no team-level secret.

## Roles

| | Member | Admin |
|---|---|---|
| See every team, agent, claim, conflict, memory entry | yes | yes |
| Rule on conflicts | yes, for conflicts involving their own agents | yes, all |
| Create keys, write memory, manage tasks | yes | yes |
| Create, rename, archive teams; attach repositories | | yes |
| Invite, remove, restrict members; change roles | | yes |
| Connect GitHub and Notion | | yes |

A restricted member keeps every read and loses every write; the arbitration form and the memory form say so instead of failing.

## Agent status

`working` = has an open claim. `reviewing` = newest claim is in review. `blocked` = its open claim is the waiting side of an open conflict. `idle` = nothing open. The first three come from the backend; `blocked` is derived on the client from open conflicts.
