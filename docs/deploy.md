# Deploying Consensus

The backend is one container. It needs PostgreSQL with the pgvector extension and Redis. Everything else is environment variables. The frontend ships inside the same container: the Dockerfile builds `frontend/` when the branch being deployed has one and the app serves it from `/` on the same origin, so there is no second service and no CORS. Until the frontend lands, the backend's own `/board` page and `/docs` work against the hosted instance.

## Before anything else

Three settings decide whether a public instance is safe:

| Variable | Value on a public host | Why |
|---|---|---|
| `DEV_AUTH` | `false` | With it on, `POST /api/auth/dev-login` issues a session for any email you type. |
| `SECRET_KEY` | long random string | Signs sessions and, unless `TOKEN_ENCRYPTION_KEY` is set, derives the key that encrypts stored GitHub and Notion tokens. |
| `MCP_AUTH_REQUIRED` | `true` | Otherwise anonymous MCP calls land on the first project. |

Generate the two keys:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"                       # SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # TOKEN_ENCRYPTION_KEY
```

## Option A: Render (blueprint, about five minutes)

`render.yaml` at the repo root declares the web service, a Postgres database and a Key Value store.

1. Render dashboard, **Blueprints**, **New Blueprint Instance**, pick this repository.
2. It prompts for the `sync: false` variables: the Anthropic and OpenAI keys, `TOKEN_ENCRYPTION_KEY`, `FRONTEND_URL` (your frontend's origin, or the backend's own URL until the frontend exists), `CORS_ORIGINS` (same origin list), and the GitHub OAuth values if you have them. Leave GitHub blank to start; magic links and dev login are not available without SMTP, so create the first admin via the seed (below) or connect GitHub.
3. Deploy. The entrypoint runs `alembic upgrade head` on every boot, so the schema is always current.
4. Enable pgvector on the database once: open the database's **Shell** (or `psql` with the external URL) and run `CREATE EXTENSION IF NOT EXISTS vector;`. The first migration does this too, but only if the role is allowed to; running it by hand removes the doubt.

`DATABASE_URL` from Render is `postgres://…`; the app rewrites that to the asyncpg dialect itself.

## Option B: Railway (step by step)

`railway.json` tells Railway to build the Dockerfile and health-check `/health`. The app reads `PORT` from Railway.

0. **Install Railway's GitHub app for the repository** first: https://github.com/apps/railway-app/installations/new, pick the account, "Only select repositories", select the repo. Without this Railway can build from the repo once but never sees pushes, so nothing auto-deploys.
1. **New project from GitHub.** Railway dashboard, **New Project**, **Deploy from GitHub repo**, pick `masterblaster14/Consensus`, branch `main`. It will start a build straight away; that first deploy fails on the health check because there is no database yet. That is expected.
2. **Add Postgres with pgvector.** In the project canvas, **Create**, **Database**, **PostgreSQL**. Once it is up, open its **Data** tab (or connect with `psql` using the `DATABASE_PUBLIC_URL` variable) and run `CREATE EXTENSION IF NOT EXISTS vector;`. If that errors because the image lacks pgvector, delete it and instead **Create**, **Template**, search **pgvector** and deploy that template; it exposes the same `DATABASE_URL` variable.
3. **Add Redis.** **Create**, **Database**, **Redis**.
4. **Wire the app to them.** Open the app service, **Variables**, **Add Reference** twice: `DATABASE_URL` from the Postgres service and `REDIS_URL` from the Redis service. Railway inserts `${{Postgres.DATABASE_URL}}` style references; leave them as they are. The app rewrites `postgres://` to the asyncpg dialect itself.
5. **Set the rest of the variables** on the app service (**Raw Editor** is fastest):

   ```
   DEV_AUTH=false
   MCP_AUTH_REQUIRED=true
   SECRET_KEY=<output of the first command above>
   TOKEN_ENCRYPTION_KEY=<output of the second command above>
   STANCE_PROVIDER=anthropic
   ANTHROPIC_API_KEY=<key>
   EMBEDDING_PROVIDER=openai
   OPENAI_API_KEY=<key>
   FRONTEND_URL=https://<app domain>            # step 6; the backend's own URL until the frontend is hosted
   CORS_ORIGINS=https://<app domain>            # add the frontend origin when it exists
   PUBLIC_URL=https://<app domain>              # webhook target the backend registers on repositories
   SEED_DEMO=true                               # first boot only; flip to false afterwards
   LOG_LEVEL=INFO
   ```

   No OpenAI key? Set `EMBEDDING_PROVIDER=hashing`; clash detection then relies on concept names alone, which is fine for the demo scenario and weaker for free-form plans.
6. **Public domain.** App service, **Settings**, **Networking**, **Generate Domain** (port 8000). Put that URL into `FRONTEND_URL` and `CORS_ORIGINS`, then **Deploy**.
7. **Check it.** `https://<app domain>/health` should return `{"status":"ok","database":true,"redis":true}`. Open **Deploy Logs**: with `SEED_DEMO=true` the seed prints the demo organisation, project and an **admin API key**. Copy that key, then set `SEED_DEMO=false` so later boots skip the seed.
8. **Connect an agent** with that key (step 3 of the post-deploy checklist below), and register the GitHub webhook and OAuth app against the new domain (steps 4 and 5).

Railway redeploys on every push to `main`. Migrations run inside the container on each boot, so schema changes ship with the code.

## Option C: Fly.io or any Docker host

```bash
docker build -t consensus .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host:5432/db \
  -e REDIS_URL=redis://host:6379 \
  -e SECRET_KEY=... -e DEV_AUTH=false \
  -e ANTHROPIC_API_KEY=... -e OPENAI_API_KEY=... -e EMBEDDING_PROVIDER=openai \
  consensus
```

Fly: `fly launch` reads the Dockerfile; attach `fly postgres` (run `CREATE EXTENSION vector` on it) and an Upstash Redis, then `fly secrets set` the rest.

## Option D: everything in Docker Compose (self-hosted or a VM)

```bash
docker compose --profile full up -d --build
```

Brings up Postgres, Redis and the app on port 8000, reading `.env` for keys. This is also the quickest way to check a build locally before pushing.

## After the first deploy

1. **Health**: `GET https://<host>/health` returns `{"status":"ok","database":true,"redis":true}`.
2. **First admin and demo data**: either set `SEED_DEMO=true` for one boot (creates the demo organisation, project, agents and memory, and prints an admin API key in the logs), or sign in with GitHub and create the organisation from `/docs`.
3. **Connect an agent**: create an API key (`POST /api/me/api-keys` or the frontend's settings page) and add the MCP server to Claude Code:
   ```bash
   claude mcp add --transport http consensus https://<host>/mcp --header "Authorization: Bearer csk_..."
   ```
   or install the plugin (`claude plugin marketplace add masterblaster14/Consensus && claude plugin install consensus@consensus`), which also adds the edit guardrail.
4. **GitHub sign-in**: register an OAuth app with callback `https://<host>/api/auth/github/callback`, set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`. Sign in with the account that will administer the organisation and call the org's GitHub connect endpoint once.
5. **Repositories**: create a project and pick a repo (or `PATCH /api/projects/{id}` with `repo_full_name`). The merge webhook is registered on the repository automatically with its own secret, as long as `PUBLIC_URL` is set and the connected account has admin rights on the repo. The response says whether it worked. Nothing to configure in GitHub by hand.
6. **Email**: set the `SMTP_*` variables so magic links and invites are delivered. Without them the providers endpoint hides magic-link sign-in.

## What runs in the background

- PR sync every `PR_SYNC_INTERVAL_SECONDS` (default 300) over every live project with a repository.
- Stale-claim expiry hourly: open claims older than `CLAIM_TTL_HOURS` (default 72) with no handoff and no PR are retired, and any clash they were blocking is released.

Both are inside the web process, so a single instance is enough. Running more than one instance is fine for requests (events fan out through Redis), but set `PR_SYNC_INTERVAL_SECONDS=0` and `CLAIM_TTL_HOURS=0` on all but one of them to avoid duplicate passes.

## Sizing

Postgres with pgvector on the smallest tier is fine for a team; the vector indexes are IVFFlat with 100 lists and every query is scoped to one project. Redis holds pub/sub and short-lived locks only. The app is a single async process; one small instance handles many agents because the only slow step is the stance model call, and that runs concurrently.
