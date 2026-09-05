# Consensus: the briefing

Everything you need to hold in your head to present the project: the problem, the solution, how it works, the technology, the MCP layer, what is novel, what is honest, and the answers to the questions you will get.

## The problem, in the words judges will recognise

Every developer now runs an AI coding agent. Claude Code, Cursor, Windsurf, Copilot. They are fast, and they work alone. On a team, that creates two failures that did not exist a year ago.

**Design conflicts that git cannot see.** Agent A rebuilds the session model around signed refresh tokens. Agent B, in another directory, adds a login endpoint that creates a server-side session. Neither touches the other's files. There is no merge conflict. CI is green. Days later in code review someone finds two incompatible designs, and one of them gets thrown away. Every tool we have works on files and diffs. The conflict was never in the files. It was in what the two plans assumed.

**Every agent starts from zero.** Agent C re-reads the auth module that Agent A already understood. Agent D tries the JWT-in-localStorage approach that Agent B abandoned yesterday. Decisions made in a chat thread never reach the next agent. Tokens burn, time passes, and nothing one agent learns is available to the next.

The one-liner: agents coordinate with nobody, and the tools that coordinate humans do not understand agents.

## The solution

Consensus is a coordination layer that sits between the agents and the repository. It does three things.

1. **Declare before you write.** Before writing code, an agent tells Consensus its plan in plain language. Consensus compares it with every other plan in flight on the team and answers in about a second: proceed, proceed with context, or wait.
2. **Shared memory.** Agents ask what the team knows before reading the codebase, and record what they learn as they work. Discoveries, decisions, dead ends, and rulings.
3. **Human rulings that compound.** When two plans genuinely conflict, a person decides once. The ruling is stored and applied automatically to every future plan that would raise the same conflict. Nobody is asked twice.

It never reads, writes, executes or merges code. It reads plans, keeps memory, and opens pull requests.

## How it works, step by step

When an agent declares a plan, this happens:

1. **One model call extracts a stance.** Claude reads the plan and returns a fixed JSON shape: the concepts the plan touches, named in ordinary domain vocabulary such as "session model" or "login endpoint", and its position on four axes where integration failures usually hide: error handling, authentication check, data access, and API shape. If the plan says nothing about an axis, that axis is null. The model is instructed never to guess. This is the only model call in the whole path.
2. **The plan is embedded** as a vector and stored.
3. **Candidates are retrieved.** The ten most similar open plans by other agents in the project, and the five most relevant memory entries, from PostgreSQL with pgvector.
4. **Comparison is deterministic.** No model. Two plans overlap if they share a concept after normalisation, or if their vectors are close. They clash if they overlap and both took a position on the same axis and the positions disagree. Positions are compared with negation-aware token overlap: "sessions stored server-side" and "stateless signed tokens, not server-side" contradict; "reset tokens in Redis with 15 minute TTL" and "password-reset tokens stored in redis, expire after fifteen minutes" agree.
5. **Severity.** Overlap plus disagreement is a hard clash. Overlap without disagreement is soft. Memory hits alone are context. Nothing is clear.
6. **Prior-ruling check.** Before escalating a hard clash to a human, Consensus searches memory for a ruling on the same concept and axis. If one exists, the clash is auto-resolved and the agent proceeds with the ruling attached.
7. **Persist and publish.** The plan and any clashes are stored, events go out over WebSocket, and the verdict returns. Every verdict is logged with its full inputs so any clash can be explained afterwards.

Steps 3 to 7 run under a per-project lock so two agents declaring at the same instant cannot both be told to proceed.

When the verdict is wait, the agent parks on a long poll. A human opens the clash on the board, sees both plans and both positions, and rules: A proceeds, B proceeds, or both with a note. The waiting agent is released within milliseconds with the ruling, and the ruling is written to memory.

When the agent finishes, it files a handoff: what changed, what it deliberately left alone, assumptions, uncertainties. Consensus stores it and opens the pull request with all of that in the description, including any rulings made along the way.

## The MCP part

The Model Context Protocol is how agents call tools. Consensus is an MCP server over HTTP, so any MCP-capable agent connects with one URL and one header:

```
claude mcp add --transport http consensus https://host/mcp --header "Authorization: Bearer csk_..."
```

The agent then has six tools: `query_memory`, `declare_intent`, `check_verdict`, `write_memory`, `file_handoff`, `report_usage`. The server's instructions tell the agent when to use each, so the workflow runs without the developer changing how they work.

The bearer token is a personal API key minted on the developer's profile. The server derives identity from it: which user, which organisation, which project by default. Everything the agent does is attributed to that developer. An agent cannot claim to be someone else, and one developer cannot take over another's agent name. The human-to-agent link is cryptographic, not a text field.

## Technology

| Layer | Choice | Why |
|---|---|---|
| Service | Python 3.11, FastAPI, Uvicorn | Async, typed, OpenAPI for free |
| Database | PostgreSQL 16 with pgvector | Relational data and vector search in one place |
| Cache and events | Redis | Per-project locks, pub/sub fan-out to WebSocket clients |
| Stance extraction | Claude Opus 5 via the Anthropic SDK, structured JSON output, low effort | One call per plan, schema-enforced, nulls preserved |
| Embeddings | OpenAI text-embedding-3-small behind a small interface; offline hashing provider for demos and tests | Swappable, and the system runs with no keys |
| Agent protocol | MCP Python SDK, streamable HTTP | Works with every major coding agent |
| Auth | GitHub OAuth, email magic links, JWT sessions, per-user API keys | No passwords; identity flows to agents |
| Integrations | GitHub REST (PRs, comments, webhook), Notion API | Off the critical path, never block a verdict |
| Tests | 24 automated tests over a real server, plus live end-to-end scripts | The golden scenario is a real test |

## What is novel

1. **Intent-level conflict detection.** Everything else that coordinates code works on files, diffs, or locks. Consensus compares what plans mean: concepts and positions. It catches conflicts across files that never touch.
2. **Exactly one model call, then determinism.** Using a second model call to judge whether two plans conflict would be slow, expensive, and unexplainable. Consensus extracts once and compares with arithmetic. Same inputs, same verdict, every input logged.
3. **Nulls as a first-class signal.** A plan that does not mention error handling cannot clash on error handling. Refusing to guess is what keeps false alarms low enough that agents keep declaring.
4. **Rulings that compound.** Human arbitration is the expensive resource. Each decision is captured as memory and applied automatically, so the number of interruptions falls as the team's rule set grows.
5. **Identity travels to the agent.** MCP tokens tied to people, so the board is trustworthy and arbitration rights follow ownership.
6. **Tokens saved, measured.** Memory reads are compared against the team's own reported codebase reads, so the savings are a real number on the board, not a claim.

## Where it fits

It is not a code editor, a CI system, an orchestrator, or a task manager. It sits alongside all of them. GitHub stays the place where code is reviewed and merged; Consensus makes sure what arrives there was coordinated. It is for teams of two to a few dozen developers who have adopted agents and are feeling the seams.

## What is honest to say about its state

- Working and verified: the verdict loop, memory, arbitration, compounding rulings, organisations and roles, per-user keys, MCP auth, GitHub OAuth and pull requests, the live event stream. Real Claude Opus extraction has been tested on plan pairs and behaves correctly.
- Not yet exercised: OpenAI embeddings (no key configured; offline provider in use), Notion (no token), a real webhook from GitHub (needs a public URL; simulated locally), email delivery for magic links.
- Known limits: a verdict takes two to three seconds on Opus, mostly the model call. The comparison is heuristic and tuned on a small set of plan pairs; it will need tuning on real team vocabulary. Rulings are matched on concept and axis, so a ruling about sessions does not leak onto payments, but two teams using very different words for the same thing will need the synonym map extended.
- Not built: pricing enforcement, encryption at rest for stored OAuth tokens, rate limiting.

## Questions you will get

**What if the agent ignores the verdict?** It can, but the plan, the verdict and the clash are all on the board and in the log. An ignored wait is visible to the team, not silent.

**How is this different from file locking or branch protection?** Those work on files. The conflict we catch is not in the files. Two plans in unrelated directories that disagree about where sessions live never produce a merge conflict.

**Why not just let a model compare the plans?** Cost, latency, and explainability. One extraction per plan, then arithmetic, means the same inputs always give the same answer and we can show exactly why a clash fired.

**Does it slow developers down?** The agent declares in a second or two. The developer only hears from Consensus when two plans genuinely collide, and each ruling makes the next collision automatic.

**Does it see our code?** No. It sees plan text and what the agent chooses to write to memory. It never reads or writes files.

**Which agents?** Any MCP client over HTTP: Claude Code, Cursor, Windsurf, and others.

**What about false positives?** Three defences: null axes are skipped, comparison is negation-aware with a wording tolerance, and every clash is explainable from its logged inputs so the threshold can be tuned with evidence.

**Can we self-host?** Yes. One Python service, Postgres with pgvector, Redis. Docker Compose for local, the same image for production.

## The pitch in sixty seconds

Every developer here runs an AI coding agent, and the agents do not know about each other. The result is design conflicts that git cannot see and knowledge that never travels between agents. Consensus is the layer where agents check in before they write code. One model call extracts what a plan touches and the positions it takes; a deterministic comparison finds plans that disagree, even in files that never touch. When two plans genuinely conflict, a human decides once, and that ruling applies automatically from then on. Agents share what they learn, so nobody re-reads the codebase or repeats a dead end. It connects to any coding agent over MCP with one URL and one key, opens the pull request when work is done, and never touches a line of code.
