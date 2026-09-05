# Deploying Consensus

The backend is one container. It needs PostgreSQL with the pgvector extension and Redis. Everything else is environment variables. The frontend is a separate static build and can come later; until then the backend's own `/board` page and `/docs` work against the hosted instance.

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

## Option B: Railway

1. New project from the GitHub repo. Railway detects the Dockerfile.
2. Add **PostgreSQL** (choose the pgvector template, or run `CREATE EXTENSION vector` on a plain one) and **Redis** from the service catalog. Railway injects `DATABASE_URL` and `REDIS_URL` into the app service when you reference them.
3. Set the variables from the table above plus the API keys and `FRONTEND_URL` / `CORS_ORIGINS`.
4. Generate a public domain for the app service.

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
4. **GitHub webhook**: in the repository's settings add a webhook for `https://<host>/api/webhooks/github`, content type JSON, secret = `GITHUB_WEBHOOK_SECRET`, event **Pull requests**. Merged PRs then retire their claims.
5. **GitHub sign-in**: register an OAuth app with callback `https://<host>/api/auth/github/callback`, set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.
6. **Email**: set the `SMTP_*` variables so magic links and invites are delivered. Without them the providers endpoint hides magic-link sign-in.

## What runs in the background

- PR sync every `PR_SYNC_INTERVAL_SECONDS` (default 300) over every live project with a repository.
- Stale-claim expiry hourly: open claims older than `CLAIM_TTL_HOURS` (default 72) with no handoff and no PR are retired, and any clash they were blocking is released.

Both are inside the web process, so a single instance is enough. Running more than one instance is fine for requests (events fan out through Redis), but set `PR_SYNC_INTERVAL_SECONDS=0` and `CLAIM_TTL_HOURS=0` on all but one of them to avoid duplicate passes.

## Sizing

Postgres with pgvector on the smallest tier is fine for a team; the vector indexes are IVFFlat with 100 lists and every query is scoped to one project. Redis holds pub/sub and short-lived locks only. The app is a single async process; one small instance handles many agents because the only slow step is the stance model call, and that runs concurrently.
