# Consensus

Consensus is a coordination layer for teams whose developers each run their own AI coding agent on the same codebase. Before an agent writes a line of code, it tells Consensus what it intends to do. Consensus compares that plan with every other plan currently in flight on the team, and with everything the team has already learned, and answers in a second: go ahead, go ahead but read this first, or wait, a human needs to decide.

It catches the conflicts that version control cannot see, keeps a shared memory so agents stop rediscovering the same things, and turns every human decision into a rule that applies automatically from then on.

## The problem

AI coding agents are fast and they work alone. Put five developers with five agents on one repository and each agent optimises for its own task with no idea what the others are doing. The failures this produces are rarely merge conflicts. They are design conflicts: one agent rebuilds the session model around signed tokens while another, in an entirely different part of the codebase, adds a login endpoint that assumes sessions live in the database. Neither touches the other's files. Git is happy. Code review, days later, finds two incompatible designs and someone throws a week of work away.

The second cost is quieter. Every agent starts from zero. It re-reads the codebase, re-learns how authentication works, re-tries the approach a colleague abandoned last Tuesday. Tokens burn, time passes, and nothing that one agent learns reaches the next.

Consensus exists to fix both.

## What it does

Every connected agent follows a short loop, on its own, without the developer having to do anything differently.

**It asks before it reads.** Before touching the codebase, the agent queries the team's shared memory: how does login work, what did we decide about error responses, what has already been tried and abandoned. It gets back short, relevant facts written by other agents and by people. Reading five of those is far cheaper than re-reading the code, and Consensus keeps a running count of the tokens saved.

**It declares before it writes.** The agent states its plan in plain language. Consensus returns one of three verdicts:

- *Proceed.* Nothing overlaps. Go.
- *Proceed with context.* Go, but the attached memory entries or an earlier ruling are relevant. Read them first.
- *Wait.* Another agent's open plan conflicts with this one. The response names the other agent, quotes their plan, and shows exactly which position disagrees. The agent holds until a human rules.

**It records what it learns.** Discoveries, decisions and dead ends go back into shared memory as the agent works, so the next agent starts further along.

**It hands off cleanly.** When the change is ready, the agent files a handoff: what changed, what it deliberately left alone, what it assumed, what it is unsure about. Consensus stores it and opens the pull request with all of that in the description.

## How it catches what diffs miss

Consensus never looks at file paths. It looks at what a plan means.

Each declared plan goes through a single language-model call that extracts its *stance*: the concepts it touches, named in ordinary domain vocabulary such as "session model" or "login endpoint", and the position it takes on four axes that cause most integration failures: how errors are handled, how requests are authenticated, where data lives, and what the API contract looks like. An axis the plan does not address is left empty. Nothing is guessed.

Comparison is then entirely deterministic. Two plans overlap when they share a concept or are semantically close. They clash when they overlap and take different positions on the same axis. The same two plans always produce the same answer, every input is logged, and any clash can be explained after the fact. There is no second model call deciding whether two plans conflict, which is what keeps false alarms rare enough that agents keep declaring.

## People stay in charge

When two plans genuinely conflict, a person decides. The clash appears on the team's board with both plans side by side and the exact point of disagreement. An admin, or the developer whose agent is involved, picks who proceeds or explains how both can, adds a short note, and the waiting agent is released with that ruling in hand.

The ruling is then written into shared memory. If any agent later declares a plan that would raise the same conflict on the same concept, Consensus applies the ruling itself and lets the agent proceed with the ruling as context. No one is asked the same question twice. Over time the team's judgement accumulates into a set of rules that the agents follow without being told.

## One board for the team

Every project has a single live board that every member sees the same way: open plans, clashes, shared memory, and counters for clashes caught and tokens saved. Events arrive within a second of happening. What differs per person is emphasis, not content: a strip at the top shows the clashes blocking your own agents or waiting on your ruling.

## Identity, teams and access

People sign in with GitHub or an email link. The first person to create an organisation becomes its admin; others join through invite links or automatically by verified email domain. Each organisation holds one project per repository.

Each developer mints a personal API key and gives it to their coding agent. Everything the agent does is attributed to that developer. An agent cannot claim to be someone else, and no one can take over another developer's agent. Consensus speaks the Model Context Protocol over HTTP, so it works with Claude Code, Cursor, Windsurf and any other agent that supports MCP, with one URL and one header and no plugins.

## Integrations

**GitHub.** An admin who signed in with GitHub connects their organisation in one click. Handoffs open pull requests whose descriptions carry the intent, the changes, the assumptions and any clash rulings. Rulings are posted as comments on related pull requests. Merged pull requests retire their plans from the board, and open pull requests that were never declared can be pulled onto the board so nothing is invisible.

**Notion.** Tasks sync in so plans can reference tickets. Decisions, dead ends and rulings are mirrored out as pages that link back to the plan and the pull request.

Both integrations are deliberately off the critical path. If GitHub or Notion is unavailable, declaring a plan still takes a second.

## What Consensus does not do

It does not read, write, execute or merge code. It does not run your CI. It does not assign work to agents or run them. It reads plans, comments on GitHub, and opens pull requests. That is the entire extent of what it touches.

## Who it is for

Teams of two to a few dozen developers who have adopted AI coding agents and are starting to feel the seams: work that collides in review, agents that re-learn the same things, and decisions that live in someone's head instead of somewhere an agent can find them. It fits alongside existing tools rather than replacing any of them.

## Getting started

The short version:

1. Sign in and create an organisation. You are its admin.
2. Add a project and point it at a repository.
3. Invite your team with a link, or set an auto-join email domain.
4. Each developer creates an API key and adds Consensus to their coding agent as an MCP server.
5. Work as usual. Watch the board.

The full walkthrough, with the exact commands for connecting an agent, is in [docs/getting-started.md](docs/getting-started.md).

## Running it yourself

Consensus is one Python service with PostgreSQL (with the pgvector extension) and Redis behind it. Docker Compose brings up the databases; the service runs anywhere Python 3.11 runs. It uses Claude for stance extraction and OpenAI for embeddings by default, both behind a small interface you can swap, and it has an offline mode that needs no API keys at all for demos and tests.

Setup, configuration, the API contract for building a dashboard, and the internals of the verdict algorithm are all in [docs/backend-reference.md](docs/backend-reference.md).

## Documentation

- [Getting started](docs/getting-started.md): from sign-up to first ruling
- [How it works](docs/how-it-works.md): the mechanism in detail
- [Features](docs/features.md)
- [Pricing](docs/pricing.md): proposed tiers
- [Pitch briefing](docs/pitch.md): problem to solution, technology, novelty, and the questions you will get
- [Demo script](docs/demo-script.md): what to show and say in a ten-minute demo
- [Demo runbook](docs/demo-runbook.md): run it and show every integration working, no frontend needed
- [Backend reference](docs/backend-reference.md): running the service, REST and WebSocket API, MCP tools
- [Original build specification](consensus-backend-build-handoff-v9.md)
