# How Consensus works

## The problem it solves

Five developers, five AI coding agents, one repository. Each agent works fast and alone. Agent A rebuilds the session model around signed refresh tokens. Agent B, in a completely different directory, adds a login endpoint that creates a server-side session. Neither touches the other's files. Git sees no conflict. Code review, days later, finds two incompatible designs.

File-based tools cannot catch this, because the conflict is not in the files. It is in what the two plans *assume*.

Consensus catches it at the moment the plan is declared, before any code exists.

## The loop

Every agent connected to Consensus follows the same four-step loop. The agent does this on its own; the developer just codes.

```
query_memory  →  declare_intent  →  (work)  →  write_memory  →  file_handoff
```

1. **Ask memory first.** Before reading the codebase the agent asks what the team already knows. Answers come from a shared, searchable memory of discoveries, decisions, dead ends and rulings.
2. **Declare the plan.** The agent states, in plain language, what it intends to change and how. Consensus returns a verdict.
3. **Record what was learned.** As it works, the agent writes reusable facts back into memory.
4. **File a handoff.** When done, it records what changed, what was left alone, assumptions and uncertainties, and Consensus turns that into the pull request.

## What happens when a plan is declared

This is the heart of the system. It runs in well under a second and involves exactly **one** language-model call.

### Step 1 – Extract the stance

The plan text goes through one structured model call that extracts a *stance*:

```json
{
  "concepts": ["session model", "refresh token flow", "auth token"],
  "error_handling": null,
  "auth_check": "validate signed token per request",
  "data_access": "sessions are stateless signed tokens",
  "api_shape": null,
  "summary": "Move sessions from a server-side store to signed refresh tokens."
}
```

Two rules make this work:

- **Concepts are domain nouns, never file paths.** "session model", "login endpoint", "payment webhook". This is what lets two plans in unrelated files be compared at all.
- **An axis the plan does not address is null.** The model is instructed not to guess. If a plan says nothing about error handling, `error_handling` is null and that axis is simply skipped. Guessed positions would make everything look like it conflicts with everything.

### Step 2 – Find the candidates

The plan is embedded as a vector. Consensus retrieves, in parallel, the ten most similar *open* plans by other agents in the same project, and the five most relevant memory entries.

### Step 3 – Compare, deterministically

Each candidate plan is compared to the new one **without any model call**. Two questions are asked:

**Do they overlap?** Yes if they share a concept (after normalisation: case, plurals, hyphenation, a small synonym map, and ignoring generic words like "model" or "endpoint" so that "session model" matches "server-side session" but not "user model"), or if the two plans' embeddings are closer than a threshold.

**Do they disagree?** For each of the four axes (error handling, auth check, data access, API shape), if *both* plans took a position and the positions do not agree after normalisation, that axis is divergent.

The comparison is pure string and vector arithmetic. The same two plans always produce the same answer, and every input to it is logged so any clash can be explained afterwards.

### Step 4 – Decide the severity

| Overlap | Divergent axis | Severity | Verdict |
|---|---|---|---|
| yes | yes | **hard** | **wait** |
| yes | no | soft | proceed with context |
| no | – | context (memory hits exist) | proceed with context |
| no | – | clear | proceed |

### Step 5 – Check for a prior ruling

Before escalating a hard clash to a human, Consensus searches memory for a **ruling** on the same concept and axis. If one exists, the clash is marked auto-resolved, the ruling is attached to the response, and the verdict is *proceed with context*. Nobody is asked the same question twice.

### Step 6 – Persist, publish, return

The plan is stored as an open claim. Any clashes are stored. Events go out over the live stream so every dashboard updates within the second. The verdict is returned to the agent.

Steps 2 to 6 run under a per-project lock, so two agents declaring at the same instant cannot both be told to proceed.

## What "wait" looks like to the agent

```json
{
  "verdict": "wait",
  "clash": {
    "with_agent": "Agent A",
    "their_intent": "Replace the session model with a refresh-token flow…",
    "axis": "data_access",
    "your_position": "sessions stored server-side",
    "their_position": "sessions are stateless signed tokens",
    "shared_concepts": ["session model"]
  },
  "clash_id": "…"
}
```

The agent knows exactly who it conflicts with and on what. It holds, polling for the ruling, or keeps the call open for up to two minutes.

## Arbitration

A human (an admin, or the owner of one of the two agents) opens the clash on the board, sees both plans and both positions, and rules: A proceeds, B proceeds, or both with a note.

Three things happen atomically:

1. The clash is resolved and the waiting agent is released with the ruling.
2. A **ruling** entry is written to shared memory carrying the note, the shared concepts and the axis.
3. If either plan has a pull request, the ruling is posted as a comment there.

Because rulings live in memory and are checked in Step 5, every human decision permanently reduces future interruptions. This is the difference between a nag and a system.

## Shared memory

Memory is a vector-searchable store of short, reusable facts, each tagged with a type:

| Type | Written by | Example |
|---|---|---|
| discovery | agents | "Auth middleware runs before every route and attaches request.user." |
| decision | agents or humans | "All auth failures return 401 with a JSON body; never redirect." |
| dead_end | agents | "JWT in localStorage was abandoned: the SPA needs HttpOnly cookies." |
| ruling | arbitration | "Ruling on data_access for session model: the first plan proceeds…" |
| handoff | file_handoff | What changed, what was untouched, assumptions, uncertainties. |

Writes are deduplicated: if a near-identical entry already exists, the new one is linked to it instead of stored again. Reads are vector search only, with no model call, so they are fast and cheap.

Every memory read is compared against the average size of a direct codebase read reported by the team's agents. The difference is the **tokens saved** counter on the dashboard.

## What Consensus deliberately does not do

- It does not read, write or execute code.
- It does not merge, run CI, or assign work to agents.
- It does not use a second model call to compare plans. Determinism is what keeps false positives low.
- It does not compare file paths. Ever.

## Live board

Every event, whether a plan declared, a clash opened or resolved, memory written or read, a handoff filed, or a PR opened, is pushed over a WebSocket to every open dashboard in the project within a second. The board is the same for everyone on the team; what differs per person is a "needs you" strip of clashes blocking their agents or waiting on their ruling.
