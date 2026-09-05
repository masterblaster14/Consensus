# Consensus Backend — Build Handoff

Hand this file to Claude Code as the spec. Build in the phase order given. Do not skip ahead.

---

## 1. What you are building

A coordination service for AI coding agents. Multiple developers each run their own agent on the same repository. Before an agent writes code, it declares its plan to this service. The service compares that plan against every other open plan and against a shared memory of what the team already knows, then returns one of three verdicts: proceed, proceed with context, or wait.

The single hardest requirement: **detect that two plans conflict even when they share no files.** An agent rebuilding the session model and an agent adding a login endpoint are in different files and still break each other. Catching that is the product.

## 2. Non-goals — do not build these

- No code editor, file tree, diff viewer or terminal
- No code execution or sandbox
- No CI, no automated merging
- No agent orchestration. We do not assign work to agents or run them.
- The service **never writes code**. It reads GitHub, comments on GitHub, and opens pull requests. Nothing else.

If a task seems to require any of the above, stop and flag it rather than building it.

## 3. Stack

- Python 3.11+, FastAPI, Uvicorn
- SQLAlchemy 2.0 async with asyncpg
- PostgreSQL 16 with the `pgvector` extension
- Redis for pub/sub and short-lived locks
- MCP Python SDK, HTTP transport, for the agent-facing tools
- Anthropic API for stance extraction (structured output via tool use)
- An embedding provider behind a small interface. Default to OpenAI `text-embedding-3-small`, 1536 dimensions. Keep it swappable — do not scatter provider calls through the codebase.
- `httpx` for GitHub and Notion
- Docker Compose for Postgres and Redis in local dev

## 4. Directory structure

```
consensus/
  app/
    main.py                 FastAPI app, lifespan, router mounting
    config.py               Settings from env, pydantic-settings
    db/
      session.py            async engine, session factory
      models.py             SQLAlchemy models
      migrations/           alembic
    mcp/
      server.py             MCP server, HTTP transport
      tools.py              the four agent-facing tools
    core/
      stance.py             plan text -> stance JSON (the one LLM call)
      embeddings.py         provider interface + default impl
      retrieval.py          vector search over claims and memory
      clash.py              deterministic comparison + severity
      verdict.py            orchestrates the declare flow end to end
      rulings.py            prior-ruling lookup and application
    api/
      claims.py             GET endpoints for the dashboard
      memory.py
      clashes.py            includes the arbitration resolve endpoint
      stream.py             WebSocket
      webhooks.py           GitHub webhook receiver
    integrations/
      github.py
      notion.py
    events/
      bus.py                publish to Redis, fan out to WS clients
  scripts/
    seed_demo.py            loads the demo scenario
  tests/
docker-compose.yml
.env.example
```

## 5. Database schema

Enable pgvector first: `CREATE EXTENSION IF NOT EXISTS vector;`

```sql
CREATE TABLE projects (
  id            UUID PRIMARY KEY,
  name          TEXT NOT NULL,
  repo_full_name TEXT,             -- "owner/repo"
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE agents (
  id             UUID PRIMARY KEY,
  project_id     UUID REFERENCES projects(id),
  name           TEXT NOT NULL,     -- "Agent A"
  developer_name TEXT NOT NULL,     -- "Priya"
  last_seen      TIMESTAMPTZ
);

CREATE TABLE tasks (
  id              UUID PRIMARY KEY,
  project_id      UUID REFERENCES projects(id),
  external_ref    TEXT,             -- "ENG-1234"
  notion_page_id  TEXT,
  title           TEXT NOT NULL
);

CREATE TABLE claims (
  id           UUID PRIMARY KEY,
  project_id   UUID REFERENCES projects(id),
  agent_id     UUID REFERENCES agents(id),
  task_id      UUID REFERENCES tasks(id) NULL,
  intent_text  TEXT NOT NULL,
  stance       JSONB NOT NULL,
  concepts     TEXT[] NOT NULL DEFAULT '{}',
  embedding    VECTOR(1536),
  branch       TEXT,
  pr_number    INTEGER NULL,
  status       TEXT NOT NULL DEFAULT 'open',   -- open | in_review | retired
  created_at   TIMESTAMPTZ DEFAULT now(),
  resolved_at  TIMESTAMPTZ NULL
);
CREATE INDEX ON claims USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX ON claims (project_id, status);

CREATE TABLE memory_entries (
  id               UUID PRIMARY KEY,
  project_id       UUID REFERENCES projects(id),
  type             TEXT NOT NULL,  -- discovery | decision | dead_end | ruling | handoff
  content          TEXT NOT NULL,
  concepts         TEXT[] NOT NULL DEFAULT '{}',
  axis             TEXT NULL,      -- set on rulings only
  embedding        VECTOR(1536),
  source_agent_id  UUID REFERENCES agents(id) NULL,
  related_claim_id UUID REFERENCES claims(id) NULL,
  created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON memory_entries USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX ON memory_entries (project_id, type);

CREATE TABLE clashes (
  id              UUID PRIMARY KEY,
  project_id      UUID REFERENCES projects(id),
  claim_a_id      UUID REFERENCES claims(id),
  claim_b_id      UUID REFERENCES claims(id),
  axis            TEXT NOT NULL,
  shared_concepts TEXT[] NOT NULL,
  severity        TEXT NOT NULL,   -- hard | soft
  status          TEXT NOT NULL DEFAULT 'open',  -- open | resolved | auto_resolved
  resolution      TEXT NULL,       -- a_proceeds | b_proceeds | both_with_note
  resolution_note TEXT NULL,
  resolved_by     TEXT NULL,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE token_events (
  id          UUID PRIMARY KEY,
  project_id  UUID REFERENCES projects(id),
  agent_id    UUID REFERENCES agents(id),
  kind        TEXT NOT NULL,    -- codebase_read | memory_read
  tokens      INTEGER NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
);
```

`token_events` is what powers the "tokens saved" counter. Agents report their own usage; we do not measure it ourselves.

## 6. The four MCP tools

These are the only things an agent can do. Signatures are fixed — the demo depends on them.

### `declare_intent`
```
Input:  agent_name, developer_name, plan_text, task_ref?, branch?
Output: {
  claim_id,
  verdict: "proceed" | "proceed_with_context" | "wait",
  context: [ {type, content, source} ],
  clash: { with_agent, their_intent, axis, your_position, their_position } | null,
  clash_id: uuid | null
}
```
On `wait`, the agent should poll `check_verdict(clash_id)` or hold on a long poll of up to 120 seconds.

### `query_memory`
```
Input:  question, limit=5
Output: { entries: [ {type, content, source_agent, created_at} ], tokens_used }
```
Vector search only. No LLM call. Records a `memory_read` token event.

### `write_memory`
```
Input:  agent_name, type, content, concepts?
Output: { entry_id, deduplicated: bool }
```
Before insert, run a similarity check. If an existing entry is above 0.92 cosine similarity, link instead of duplicating and return `deduplicated: true`.

### `file_handoff`
```
Input:  claim_id, changed, untouched, assumptions, uncertainties
Output: { entry_id, pr_url | null }
```
Stores a `handoff` memory entry, moves the claim to `in_review`, and opens the GitHub pull request.

## 7. The declare flow — implement exactly this order

This is the core algorithm. Everything else is plumbing.

```
1. Resolve or create the agent row.

2. STANCE EXTRACTION  (core/stance.py)
   One Anthropic call, structured output, this exact schema:
   {
     concepts: string[],          # e.g. ["session model", "auth token refresh"]
     error_handling: string|null,
     auth_check:     string|null,
     data_access:    string|null,
     api_shape:      string|null,
     summary:        string
   }
   Axes the plan does not touch MUST come back null. Do not let the
   model guess. Null means "not addressed" and is skipped in comparison.

3. EMBED the plan text.

4. RETRIEVE  (core/retrieval.py)  — run both in parallel
   a) top 10 claims where status='open' AND project matches AND agent differs
   b) top 5 memory_entries in the same project
   Cosine similarity, pgvector.

5. COMPARE each candidate claim  (core/clash.py)  — deterministic, no LLM
   concept_overlap = (
       set(new.concepts) ∩ set(other.concepts) is non-empty
       OR cosine(new.embedding, other.embedding) > 0.82
   )
   divergent_axes = [
       axis for axis in FOUR_AXES
       if new.stance[axis] is not None
       and other.stance[axis] is not None
       and normalize(new.stance[axis]) != normalize(other.stance[axis])
   ]

6. SEVERITY
   concept_overlap and divergent_axes  -> hard
   concept_overlap and not divergent   -> soft
   no overlap, memory hits present     -> context
   nothing                             -> clear

7. PRIOR RULING SHORT-CIRCUIT  (core/rulings.py)
   Before escalating any hard clash, search memory_entries where
   type='ruling' for a matching concept + axis. If one exists,
   return proceed_with_context carrying that ruling, mark the clash
   auto_resolved, and DO NOT escalate to a human.
   This is what makes human decisions compound. Do not skip it.

8. PERSIST the claim (status='open') and any clash rows.

9. PUBLISH to the event bus: claim.created, and clash.opened if any.

10. RETURN the verdict.
```

Normalisation in step 5 means lowercase, trim, and collapse obvious synonyms via a small hardcoded map. Do not use an LLM for this comparison. Determinism here is what keeps false positives down and is the thing we defend in the pitch.

Concurrency: take a Redis lock on `project_id` for the duration of steps 4 through 8, so two simultaneous declarations cannot both pass.

## 8. REST and WebSocket

```
GET  /api/projects/{id}/claims?status=open
GET  /api/projects/{id}/memory?type=&q=
GET  /api/projects/{id}/clashes?status=open
GET  /api/projects/{id}/agents
GET  /api/projects/{id}/counters       -> {tokens_saved, clashes_caught, memory_count}
POST /api/clashes/{id}/resolve         -> {resolution, note, resolved_by}
POST /api/webhooks/github
WS   /ws/projects/{id}                 -> every event, JSON frames
```

`POST /api/clashes/{id}/resolve` is the arbitration endpoint. It must:
1. Update the clash row
2. Write a `ruling` memory entry carrying the note, the shared concepts and the axis
3. Publish `clash.resolved` so the waiting agent is released

`tokens_saved` is computed as: for each `memory_read` event, the average `codebase_read` size for that project minus the memory read cost. Keep the formula in one function so it is easy to explain.

WebSocket event types: `claim.created`, `claim.retired`, `clash.opened`, `clash.resolved`, `memory.written`, `memory.read`, `handoff.filed`, `pr.opened`.

## 9. Integrations

**GitHub** (`integrations/github.py`)
- `open_pull_request(claim, handoff, clashes)` — body assembled from the claim's intent, the handoff fields, and any clashes with their resolutions. Opens from `claim.branch`.
- `comment_on_pr(pr_number, clash)` — posts a clash as a PR comment.
- `sync_open_prs(project)` — polls open PRs and creates claims for any not already tracked, so unconnected agents still appear on the board.
- Webhook on `pull_request.closed` -> set claim to `retired`, publish `claim.retired`.

**Notion** (`integrations/notion.py`)
- `sync_tasks(project)` — reads a Notion database, upserts `tasks`.
- `push_entry(entry)` — mirrors any `decision`, `dead_end` or `ruling` out as a Notion page linking back to the claim and PR.

Both integrations must be behind a feature flag and must not block the declare flow. If GitHub is down, declaring still works.

## 10. Environment

```
DATABASE_URL=postgresql+asyncpg://consensus:consensus@localhost:5432/consensus
REDIS_URL=redis://localhost:6379
ANTHROPIC_API_KEY=
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=
GITHUB_TOKEN=
GITHUB_WEBHOOK_SECRET=
NOTION_TOKEN=
NOTION_TASKS_DB_ID=
ENABLE_GITHUB=true
ENABLE_NOTION=true
CONCEPT_SIMILARITY_THRESHOLD=0.82
DEDUP_SIMILARITY_THRESHOLD=0.92
```

## 11. Build order

Do these in sequence. Each phase must pass its check before moving on.

**Phase 0 — skeleton**
Docker Compose with Postgres and Redis. FastAPI app boots. Alembic migration creates all tables and the vector extension. `GET /health` returns 200.

**Phase 1 — the core loop. This is the whole product.**
`declare_intent` end to end: stance extraction, embedding, retrieval, comparison, severity, persist, return verdict. MCP server exposing the tool.
*Check: the golden test in section 12 passes.*

**Phase 2 — memory**
`query_memory` and `write_memory`, dedup, token events, the counters endpoint.
*Check: writing four entries then querying returns them ranked sensibly, and the counters move.*

**Phase 3 — arbitration**
Clash rows, the resolve endpoint, ruling written to memory, the prior-ruling short circuit in step 7.
*Check: resolve a clash, then declare the same conflicting plan again. It must return `proceed_with_context` carrying the ruling, and must not create a new open clash.*

**Phase 4 — handoff and GitHub**
`file_handoff`, PR body assembly, PR creation, merge webhook retiring the claim.
*Check: a handoff produces a PR whose body contains the original intent, the changed and untouched lists, and the clash resolution.*

**Phase 5 — live and Notion**
WebSocket stream with all event types, Redis fan-out, `sync_open_prs`, Notion task sync and entry mirroring.
*Check: two browser tabs both receive every event within a second.*

## 12. Golden acceptance test

Write this as a real test in `tests/`. It is the demo, and it is what the whole design exists to pass.

```
Given an empty project
When Agent A declares:
  "Replace the session model with a refresh-token flow.
   Sessions move from server-side store to signed tokens."
Then the verdict is "proceed"

When Agent A writes 4 discovery entries about how auth works

When Agent B queries memory with "how does login work"
Then it receives those entries, and a memory_read token event is recorded

When Agent B declares:
  "Add a POST /login endpoint that creates a server-side session
   and returns the session id."
Then the verdict is "wait"
And the clash names Agent A
And the shared concepts include the session model
And NO FILE PATHS WERE COMPARED AT ANY POINT

When a human resolves the clash with "a_proceeds" and a note
Then a ruling memory entry exists carrying that note
And Agent B's pending call returns with the ruling

When Agent B declares the same plan a second time
Then the verdict is "proceed_with_context", not "wait"
And no new open clash is created
```

The last two blocks are the ones people forget. They prove human decisions compound, which is the difference between a nag and a system.

## 13. Seed script

`scripts/seed_demo.py` must set up the golden scenario in one command: a project, three agents with developer names, two tasks, and enough memory entries that the panel does not start empty on stage. It must be idempotent and it must be runnable with all integrations disabled, so the demo does not depend on the network.

## 14. Notes for whoever builds this

- Stance extraction is the only place an LLM appears in the declare path. If you find yourself adding a second model call to compare two plans, stop. That is the design being violated, and it is what makes the system slow and imprecise.
- Nulls in the stance matter more than values. A plan that does not mention error handling must not get a guessed position, or everything will look like it conflicts with everything.
- Every verdict path must be fast enough that declaring feels free. If declaring is slow, agents skip it, and the product stops working.
- Log every verdict with its inputs. During the hackathon you will need to explain why a specific clash fired, and reconstructing it from memory is painful.
