# Consensus

Coordination for teams whose developers each run an AI coding agent on the same codebase.

Before an agent writes code, it declares its plan. Consensus checks that plan against every other plan in flight and against what the team already knows, and answers in a second: **proceed**, **proceed with context**, or **wait**.

## Why

AI coding agents are fast and they work alone. On a team that produces two problems git cannot see:

- **Design conflicts in files that never touch.** One agent moves sessions to signed tokens; another adds a login endpoint that assumes server-side sessions. No merge conflict. Two incompatible designs discovered days later in review.
- **Every agent starts from zero.** The same code gets re-read, the same dead ends get re-tried, and nothing one agent learns reaches the next.

## What it does

- **Declare before writing.** Plans are compared on what they mean, not which files they touch. Conflicts are caught before the code exists.
- **Shared memory.** Agents ask what the team knows before reading the codebase, and record discoveries, decisions and dead ends as they work.
- **Human rulings that compound.** When two plans genuinely conflict, a person decides once. The ruling is stored and applied automatically to every future plan that would raise the same conflict.
- **Clean handoffs.** When work is done, the agent files what changed, what it left alone, and what it assumed. That becomes the pull request.

Consensus never reads, writes, executes or merges code.

## How it works

1. One language-model call extracts a plan's *stance*: the concepts it touches and its positions on error handling, authentication, data access and API shape. Unaddressed axes stay empty; nothing is guessed.
2. The nearest open plans and memory entries are retrieved by vector search.
3. Plans are compared deterministically. Shared concept plus disagreeing positions is a clash. Same inputs, same answer, every input logged.
4. A hard clash is checked against prior rulings before any human is asked.

Full detail: [How it works](docs/how-it-works.md).

## Connecting an agent

Consensus is an MCP server. Each developer creates a personal API key and adds one line to their coding agent:

```
claude mcp add --transport http consensus https://<host>/mcp --header "Authorization: Bearer csk_..."
```

Works with Claude Code, Cursor, Windsurf and any other MCP client. Everything the agent does is attributed to the developer who owns the key.

## Teams and integrations

- Sign in with GitHub or an email link. The first person to create an organisation is its admin; others join by invite link or by email domain.
- One shared live board per repository.
- GitHub: handoffs open pull requests, rulings become PR comments, merged PRs retire their plans.
- Notion: tasks sync in, decisions and rulings mirror out.

## Running it

Python 3.11, PostgreSQL with pgvector, Redis. Docker Compose for the databases. Offline mode needs no API keys.

```
docker compose up -d
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m scripts.seed_demo
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Setup details, configuration and the full API: [Backend reference](docs/backend-reference.md).

## Documentation

- [Getting started](docs/getting-started.md)
- [How it works](docs/how-it-works.md)
- [Features](docs/features.md)
- [Pitch briefing](docs/pitch.md)
- [Demo script](docs/demo-script.md) and [demo runbook](docs/demo-runbook.md)
- [Backend reference](docs/backend-reference.md)
- [Pricing](docs/pricing.md)
