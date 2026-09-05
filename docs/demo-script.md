# Demo script

A presenter's script for a ten-minute demo with the backend and your frontend running separately. Each step says what to do, what the audience sees, and the one sentence to say. If your frontend does not yet show something, the fallback is the backend's built-in page at `/board` or the API page at `/docs`; both use the same API your frontend does.

## Before the audience arrives

Backend, terminal 1 (leave running):

```
docker compose up -d
.venv\Scripts\python -m alembic upgrade head
set DEMO_REPO_FULL_NAME=masterblaster14/test_repo
.venv\Scripts\python -m scripts.seed_demo --reset
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Frontend, terminal 2: start it, pointed at `http://localhost:8000`. Make sure `CORS_ORIGINS` in the backend `.env` includes the frontend's origin.

Then:

1. Sign in on the frontend. Use GitHub if the OAuth app is configured, otherwise the dev login with `demo@example.com`. You should land in the organisation "Consensus Demo" with the project "Consensus Demo" already there, three agents (Priya, Marcus, Lena), two tasks, six memory entries, and counters that are not zero.
2. Create an API key from your profile page, or use the seeded one the seed script printed. Have it in a text file ready to paste.
3. Open a third terminal in the `consensus` folder for the agent commands. Test one command end to end before people arrive.
4. Open the pull request from the earlier GitHub run in a background tab, or plan to create one live in step 7.
5. Keep the browser and the terminal side by side. The board updates within a second of each command, and that is the demo.

If anything is stale, `seed_demo --reset` wipes and rebuilds the demo project in a few seconds.

## The story in one line

"Every developer here runs an AI coding agent. The agents do not know about each other. Consensus is the layer where they check in before they write code, so conflicts are caught before the code exists and nothing learned is learned twice."

## Steps

### 1. The empty board (30 seconds)

Show the project board: open plans, clashes, shared memory, counters.

Say: "One board per repository. The whole team sees the same thing. Six things the team already knows are in memory: how auth works, a decision about error responses, a dead end someone hit."

### 2. Connect an agent (1 minute)

In the terminal, add Consensus to Claude Code with the API key:

```
claude mcp add --transport http consensus http://localhost:8000/mcp --header "Authorization: Bearer csk_..."
```

Say: "Each developer mints a key and gives it to their agent. One URL, one header. From now on the agent talks to Consensus on its own. Everything it does is attributed to me; it cannot pretend to be someone else."

If you would rather not use Claude Code live, every remaining step can be driven by the smoke script instead; see the fallback at the end.

### 3. The agent asks before it reads (1 minute)

In Claude Code, type: "Before you do anything, ask Consensus what the team knows about how login works."

The agent calls `query_memory`. On the board, the tokens-saved counter moves and the live event feed shows the read.

Say: "The agent read five sentences instead of the whole auth module. Consensus counts what that saved."

### 4. Agent A declares (1 minute)

In Claude Code: "Declare this plan to Consensus: replace the session model with a refresh-token flow, moving sessions from the server-side store to signed tokens. Use agent name Agent A."

The board shows a new open plan with its concepts (session model, refresh token, auth subsystem) and the verdict: proceed.

Say: "Before writing code, the agent states its intent in plain language. One model call extracts what it touches and the positions it takes. Nothing overlaps, so it proceeds."

### 5. Agent B collides (2 minutes)

This is the centre of the demo. In a second Claude Code session, or the same one with a different agent name: "Declare this plan as Agent B: add a POST /login endpoint that creates a server-side session and returns the session id."

The verdict is wait. A hard clash appears on the board with both plans side by side and the two positions: "sessions are stateless signed tokens" against "sessions stored server-side".

Say: "Different files. Different directories. Git would merge these without a word. Consensus caught it because it compares what the plans mean, not which files they touch. Agent B is now waiting."

Pause here. Let people read the clash card.

### 6. A human rules, and the ruling compounds (2 minutes)

On the board, click the resolve button on the clash: Agent A proceeds. Type a note such as "Refresh tokens win. Login must issue a signed token, not a server-side session."

Three things happen at once: the clash is resolved, Agent B's waiting call returns with the ruling, and a ruling entry appears in shared memory.

Now declare Agent B's plan a second time, word for word. The verdict is proceed with context, the ruling is attached, and no new clash is opened.

Say: "That is the difference between a nag and a system. I was asked once. Every agent from now on gets my answer without asking me."

### 7. Handoff opens the pull request (1 minute)

In Claude Code as Agent A: "File a handoff to Consensus for that plan: changed the session module and auth middleware, left the login endpoint and user model untouched, assumed the refresh token lives in an HttpOnly cookie, unsure about the rotation interval." The plan needs a branch that exists on the repo; if you did not set one when declaring, show the pull request from the earlier GitHub run instead.

The plan moves to in review and a pull request opens on GitHub. Open it. The description has the intent, what changed, what was left alone, the assumptions, the uncertainties, and the ruling with your note.

Say: "The review starts with everything the reviewer needs, including the decision that was made along the way. When it merges, the plan leaves the board on its own."

### 8. Close (30 seconds)

Back to the board: counters up, one clash caught, memory grown by the discoveries, the ruling and the handoff.

Say: "It never read or wrote code. It read plans, kept memory, asked a human once, and opened a pull request. That is the whole surface."

## Questions you will get

**What if the agent ignores the verdict?** It can, but the plan and verdict are on the board and in the log, so an ignored wait is visible to the team, not silent.

**How do you avoid false alarms?** One model call extracts positions; an axis the plan does not mention is left empty, never guessed. The comparison itself is deterministic string and vector arithmetic with every input logged, so any clash can be explained.

**Does it see our code?** No. Plans, not files. It cannot execute, edit, or merge anything.

**Which agents?** Anything that speaks MCP over HTTP: Claude Code, Cursor, Windsurf.

## Fallback: drive it from the script instead of Claude Code

If you would rather not type into Claude Code on stage, this runs steps 3 to 7 automatically while the board updates:

```
.venv\Scripts\python -m scripts.smoke_e2e --project 00000000-0000-4000-8000-00000000c0de
```

To do the GitHub pull request live (needs your GitHub session token in `.env` as `DEV_SESSION_TOKEN`):

```
.venv\Scripts\python -m scripts.github_e2e --keep
```

And if you want to show the model's extraction on its own, with five plan pairs and the reason each is or is not a clash:

```
.venv\Scripts\python -m scripts.try_stance
```

## Reset between demos

```
.venv\Scripts\python -m scripts.seed_demo --reset
```

Without this, the ruling from the previous run makes Agent B skip the wait in step 5. That is correct behaviour, but it spoils the reveal.
