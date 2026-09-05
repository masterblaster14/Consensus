# Features

## Conflict detection that reads intent, not files

**Semantic clash detection.** Two agents in different files, editing different modules, can still break each other. Consensus extracts each plan's *stance* (the concepts it touches and its positions on error handling, authentication, data access and API shape) and finds conflicts that no diff or file lock could see.

**Three-way verdicts.** Every declared plan gets one of three answers in under a second: *proceed*, *proceed with context*, or *wait*. The agent knows exactly what to do next.

**Precise clash reports.** A *wait* names the other agent, quotes their plan, and shows the exact axis and the two positions that disagree. No guessing what went wrong.

**Deterministic comparison.** One language-model call per plan, then pure arithmetic. The same two plans always produce the same verdict, and every input is logged so any clash can be explained after the fact.

**Null means null.** Plans are never assigned positions they did not take. A plan that says nothing about error handling cannot clash on error handling. This is what keeps false positives low enough that agents keep declaring.

## Human arbitration that compounds

**One-click rulings.** See both plans side by side, choose who proceeds (or both, with a note), done. The waiting agent is released instantly with your decision.

**Rulings become memory.** Every decision is stored with the concept and axis it settles. When any agent later raises the same conflict, Consensus applies the ruling automatically. You are never asked the same question twice.

**Right person, right clash.** Admins can rule on anything. Members rule on clashes involving their own agents. Everyone sees everything.

## Shared team memory

**Ask before you read.** Agents query memory before touching the codebase and get discoveries, decisions, dead ends and rulings ranked by relevance. Reading five entries beats re-reading five thousand lines.

**Write once, link duplicates.** Near-identical entries are linked, not duplicated, so memory stays clean as it grows.

**Tokens-saved counter.** Consensus measures what each memory read replaced and shows the running total on the board. The savings are real and visible.

**Structured handoffs.** When work is ready, the agent records what changed, what it deliberately left alone, its assumptions and its open questions. That becomes the PR description and a permanent memory entry.

## A board the whole team shares

**One board per repository.** Open plans, clashes, memory and counters, identical for every member. Nothing is hidden, so nobody is surprised.

**Live in under a second.** Every event streams to every open dashboard: plans declared, clashes opened and resolved, memory written, handoffs filed, PRs opened.

**"Needs you" strip.** Each person sees the clashes blocking their agents and the ones waiting on their ruling, on top of the shared board.

**Explainable history.** Every verdict is logged with the stance, the candidates, the similarity scores and the comparison result. Click any clash and see why it fired.

## Built for how teams already work

**Any MCP-capable agent.** Claude Code, Cursor, Windsurf and anything else that speaks MCP over HTTP. One URL, one header, no plugins.

**Identity travels with the key.** Each developer mints their own API key. Everything their agent does is attributed to them; agents cannot impersonate other developers, and one developer cannot hijack another's agent.

**Organisations, projects, roles.** Create an organisation, add a project per repo, invite by link or let people auto-join by email domain. Admins manage; members build.

**Sign in your way.** GitHub OAuth in one click, or an email magic link. No passwords to manage.

## Integrations that stay out of the critical path

**GitHub.** Handoffs open pull requests with the intent, changes, assumptions and clash rulings in the description. Rulings are posted as PR comments. Merged PRs retire their plans. Open PRs that were never declared still appear on the board.

**Notion.** Tasks sync in so plans can reference tickets. Decisions, dead ends and rulings mirror out as pages linking back to the plan and PR.

**Never blocking.** Both integrations are fire-and-forget. If GitHub or Notion is down, declaring still takes under a second.

## Deploy anywhere

**Self-host in minutes.** One Python service, Postgres with pgvector, Redis. Docker Compose for local; the same image for production.

**Bring your own models.** Anthropic for stance extraction and OpenAI for embeddings by default, both behind a small interface you can swap. An offline mode runs with no keys at all.

**Open API.** Everything the dashboard does is available over REST and WebSocket with a published OpenAPI schema.

**It never writes code.** Consensus reads plans, comments on GitHub and opens pull requests. It does not execute, edit or merge anything.
