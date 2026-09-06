# Demo script

A presenter's script for a ten-minute demo on the hosted product at
https://consensus-production-aed6.up.railway.app with two laptops. Nothing is
pre-made: the organisation, the team, the members, the keys and the agents are all
created in front of the audience. Each step says what to do, what the audience sees,
and the one sentence to say.

Roles: **Presenter** (laptop 1, projected) and **Teammate** (laptop 2, own GitHub
account, own Claude Code). Both have done the rehearsal in `demo-runbook.md`.

## The story in one line

"Every developer here runs an AI coding agent. The agents do not know about each
other. Consensus is the layer where they check in before they write code, so
conflicts are caught before the code exists and nothing learned is learned twice."

## Steps

### 1. Create the organisation (1 minute)

Presenter opens the site, clicks **Sign in with GitHub**, lands on onboarding, picks
**Create an organisation**, names it. Then **Create team**, names the team, and picks
the repository from the list. (The list is there because GitHub was connected during
rehearsal; if it is not, type `owner/repository`.)

Say: "One organisation per company, one team per repository. Attaching the
repository also registered the merge webhook on it. That is the last piece of setup."

### 2. Invite the teammate (30 seconds)

Presenter: sidebar **Manage members**, **Invite member**, copy the link. Send it to the
Teammate in whatever chat you have open. Teammate opens it on laptop 2, signs in with
GitHub, clicks accept, and is in the same team.

Say: "A link. No secrets, no IDs. Everyone in the organisation sees every team."

### 3. Connect the agents (1 minute)

Both: sidebar **Settings**, **Create key**, name it, and the page shows the key once
together with the exact command. Paste the command into a terminal:

```
claude mcp add --transport http consensus https://consensus-production-aed6.up.railway.app/mcp --header "Authorization: Bearer csk_..."
```

Presenter, in Claude Code, types `/mcp`. The audience sees `consensus` connected
with its eight tools.

Say: "One URL, one header. Everything this agent does is attributed to me; it cannot
pretend to be someone else. It is on the MCP Registry and the Claude Code plugin
marketplace, so a new developer is two commands away."

### 4. The first agent declares and writes memory (1.5 minutes)

Presenter, in Claude Code, in the repository:

> Before you do anything, ask Consensus what the team knows about how login works.

The agent calls `query_memory`. The answer is empty because the organisation is a
minute old. Then:

> Declare this plan to Consensus as Agent A on branch demo/refresh-tokens: replace
> the session model with a refresh-token flow, moving sessions from the server-side
> store to signed tokens. Then write two memory entries: a discovery that login
> currently stores sessions server-side keyed by a cookie, and a decision that
> sessions are moving to signed refresh tokens.

On the dashboard: Agent A appears, the plan appears with the verdict **proceed** and
the stance extracted from it (session model, authentication position), and Memory
gains two entries. Click the plan to show the extracted positions.

Say: "Before writing code the agent states its intent in plain language. One model
call extracts what it touches and the positions it takes. Nothing overlaps, so it
proceeds. And what it learned is now team memory."

### 5. The second agent collides (2 minutes)

Teammate, in their Claude Code:

> Ask Consensus what the team knows about login, then declare this plan as Agent B on
> branch demo/login-endpoint: add a POST /login endpoint that creates a server-side
> session and returns the session id.

Two things to point at. First, the query hit: Agent B got Agent A's discovery and the
tokens-saved counter moved. Second, the verdict is **wait**. On the projected
dashboard a conflict appears within a second, with both plans side by side and the two
positions: signed tokens against server-side sessions. Agent B's status is
**blocked**; Agent B's Claude Code is sitting in `check_verdict`.

Say: "Different files. Different directories. Git would merge these without a word.
Consensus caught it because it compares what the plans mean, not which files they
touch. Agent B is now waiting on a human."

Pause here and let people read the conflict card.

### 6. A human rules once (1.5 minutes)

Presenter: **Conflicts**, open the card, choose Agent A proceeds, type a note such as
"Refresh tokens win. Login must issue a signed token, not a server-side session."
Submit.

Three things happen at once: the conflict is resolved on the dashboard, the
Teammate's waiting call returns with the ruling in the terminal, and a ruling entry
appears in Memory.

Teammate then declares the same plan a second time, word for word. The verdict is
**proceed with context**, the ruling is attached, and no new conflict opens.

Say: "That is the difference between a nag and a system. I was asked once. Every
agent from now on gets my answer without asking me."

### 7. Handoff opens the pull request (1.5 minutes)

Presenter, in Claude Code:

> Make the change on branch demo/refresh-tokens, commit and push it, then file a
> handoff to Consensus: changed the session module and auth middleware, left the login
> endpoint and user model untouched, assumed the refresh token lives in an HttpOnly
> cookie, unsure about the rotation interval.

The plan moves to **in review** and a pull request opens on the repository. Open it.
The description has the intent, what changed, what was left alone, the assumptions,
the uncertainties, and your ruling with the note. Merge it. Within a few seconds the
plan leaves the board and Agent A is idle.

Say: "The review starts with everything the reviewer needs, including the decision
that was made along the way. When it merges, the plan retires on its own."

### 8. The guardrail (optional, 1 minute)

If time allows, on laptop 2 with the plugin installed instead of the bare server, ask
Claude Code to edit a file without declaring. The hook refuses with "declare your plan
before editing code". Then declare, and the edit goes through.

Say: "With the plugin, the agent cannot skip the check-in even if it wants to."

### 9. Close (30 seconds)

**Teams** page: counters up, one conflict caught, memory grown by two discoveries, a
ruling and a handoff, one pull request merged.

Say: "It never read or wrote code. It read plans, kept memory, asked a human once, and
opened a pull request. That is the whole surface."

## Questions you will get

**What if the agent ignores the verdict?** With the plugin it cannot edit until the
verdict allows it. Without the plugin it can, but the plan and verdict are on the
dashboard and in the log, so an ignored wait is visible to the team, not silent.

**How do you avoid false alarms?** One model call extracts positions; an axis the plan
does not mention is left empty, never guessed. The comparison itself is deterministic
with every input logged, so any conflict can be explained from its verdict log, which
is on the plan's page.

**Does it see our code?** No. Plans, not files. It cannot execute, edit, or merge
anything; the pull request is opened from a branch the agent pushed itself.

**Which agents?** Anything that speaks MCP over HTTP: Claude Code, Cursor, Windsurf.

**Where is it hosted?** Railway, with Postgres and Redis. The backend serves the web
app, the REST API, the WebSocket and the MCP endpoint from one origin.

## Fallbacks

- **GitHub or the venue network is slow.** Switch to the rehearsal organisation from
  the sidebar switcher. It already has the team, the members, the keys and memory.
- **You would rather not type into Claude Code live.** From the repository folder,
  with the key in `CONSENSUS_API_KEY`, this drives steps 4 to 7 against the hosted
  instance while the dashboard updates:

  ```
  set CONSENSUS_URL=https://consensus-production-aed6.up.railway.app
  set CONSENSUS_API_KEY=csk_...
  .venv\Scripts\python -m scripts.smoke_e2e
  ```

- **The pull request does not open.** It needs a pushed branch on the attached
  repository. Show the pull request from the rehearsal instead.
