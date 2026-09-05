# Running the backend and demonstrating it

This is the operator's guide: how to bring Consensus up on a laptop and show every integration working, with no frontend required. Everything below uses the built-in pages the backend serves and the scripts in `scripts/`.

## 1. Start it

From the `consensus` folder, in one terminal:

```bash
docker compose up -d
.venv\Scripts\python -m alembic upgrade head
set DEMO_REPO_FULL_NAME=masterblaster14/test_repo
.venv\Scripts\python -m scripts.seed_demo --reset
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

On macOS or Linux use `.venv/bin/python` and `export` instead of `set`. First-time setup (once): `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`, then `copy .env.example .env` and fill in `ANTHROPIC_API_KEY`, `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.

The seed prints two things you need: the demo project id and the admin API key (`csk_demo_…`). Copy the key.

Check it is up: open http://localhost:8000/health and you should see `"status":"ok"` with database and redis both true.

## 2. Open the board

http://localhost:8000/board?token=csk_demo_…&project=00000000-0000-4000-8000-00000000c0de

Paste the seeded key in place of `csk_demo_…`. The header shows a green "live" dot when the WebSocket is connected. Leave this window visible for the whole demo; everything else happens in a second terminal and shows up here within a second.

The board is a placeholder for the real dashboard, but it uses only the public REST and WebSocket API, so what it shows is exactly what the frontend will get.

## 3. The core demo (two minutes)

In a second terminal:

```bash
.venv\Scripts\python -m scripts.smoke_e2e --project 00000000-0000-4000-8000-00000000c0de
```

Watch the board while it runs. In order:

1. **Agent A declares** a plan to move sessions to signed refresh tokens. The verdict is *proceed*. An open plan appears with its concepts extracted by Claude (session model, refresh token, auth subsystem).
2. **Agent A writes memory**, two discoveries about how login works. A third near-duplicate is linked, not stored. Both show in Shared memory.
3. **Agent B queries memory** with "how does login work" and gets the entries. The tokens-saved counter moves.
4. **Agent B declares** a login endpoint that creates a server-side session. The verdict is *wait*. A hard clash appears: two agents, two plans in different files, opposite positions on where sessions live. Point at the two positions on the clash card: "sessions are stateless signed tokens" against "sessions stored server-side".
5. **An unrelated plan** (CSV export) is declared and is not blocked.
6. **A human resolves** the clash: Agent A proceeds, with a note. The script does this through the API; you can do it yourself instead by clicking a button on the clash card. The waiting agent is released within milliseconds and receives the ruling. A `ruling` entry appears in memory.
7. **Agent B declares the same plan again.** Verdict is *proceed with context*, the ruling is attached, and no new open clash is created. This is the moment to make: the human was asked once, and never again.
8. **Agent B files a handoff.** It appears in memory and the plan moves to in review.

The terminal prints a check for each step. Because the demo project accumulates plans and rulings across runs, run the seed with `--reset` between demos, or leave out `--project` and the script will create a fresh project for itself.

## 4. Show the stance extraction on its own

```bash
.venv\Scripts\python -m scripts.try_stance
```

Five plan pairs go through the real model and the deterministic comparison, and the output shows the extracted stance for each plan, the shared concepts, the divergent axis, and the severity. Use the third pair to make the point that a 404-versus-200 disagreement across two unrelated files is caught with no file paths involved, and the fifth to show that the same position in different words is not a clash.

## 5. Show GitHub end to end

Prerequisite: sign in with GitHub once and put the session token in `.env` as `DEV_SESSION_TOKEN`. To sign in, open http://localhost:8000/api/auth/github/start, visit the `url` it returns, authorise, and copy the token from the page you land on.

```bash
.venv\Scripts\python -m scripts.github_e2e --keep
```

It connects your GitHub account to the demo organisation, creates two branches on `masterblaster14/test_repo`, runs the clash and the ruling, and files a handoff that opens a real pull request. Open the printed PR link and show the description: the original intent, changed and untouched lists, assumptions, uncertainties, and the clash ruling with the note. The script then simulates the merge webhook and the plan is retired from the board. Without `--keep` it closes the PR and deletes the branches at the end.

## 6. Show the API surface

- http://localhost:8000/docs is the interactive OpenAPI page. Every endpoint the dashboard will use is there and can be called from the page with the API key as a bearer token (click Authorize).
- The MCP endpoint agents talk to is http://localhost:8000/mcp. To show a real agent connected, add it to Claude Code:

  ```bash
  claude mcp add --transport http consensus http://localhost:8000/mcp --header "Authorization: Bearer csk_demo_…"
  ```

  then in Claude Code ask it to "declare that you plan to add a logout endpoint that deletes the server-side session" and watch the board.

## 7. Sign-in and organisations without a frontend

- http://localhost:8000/api/auth/providers shows which sign-in methods are configured.
- Magic link: `POST /api/auth/magic-link` with `{"email": "..."}` returns the link directly while `DEV_AUTH=true`; open it and the page signs you in.
- Invites: create one from `/docs` under organisations, open the returned URL, paste a session token, and click Accept.

## What is and is not connected

| Verified working | Notes |
|---|---|
| Verdict loop, memory, rulings, arbitration | Automated tests plus live runs |
| Claude Opus stance extraction | Real model; five plan pairs correct |
| Sign-in, organisations, invites, roles, API keys | Automated tests |
| GitHub: OAuth, org connect, PR from handoff, merge webhook | Verified on the test repository |
| Live board over WebSocket | The `/board` page |

| Not yet exercised | Why |
|---|---|
| OpenAI embeddings | No key configured; the offline hashing provider is in use |
| Notion | No integration token configured |
| Real merge webhook from GitHub | GitHub cannot reach localhost; simulated locally. Register the webhook URL and `GITHUB_WEBHOOK_SECRET` once deployed |
| Email delivery for magic links | No provider wired; links are returned in dev mode |
