# Questions and answers

Grouped by what a judge, a customer, or an engineer is likely to ask. Answers are written to be said out loud.

## What it is

**In one sentence, what is Consensus?**
A coordination layer for teams whose developers each run an AI coding agent on the same codebase. Agents declare what they plan to do before they write code, Consensus catches plans that conflict, keeps a shared memory, and turns human decisions into rules that apply automatically.

**Who is it for?**
Software teams of two to a few dozen developers who have adopted agents like Claude Code, Cursor or Windsurf and are feeling the seams: work that collides in review, agents that re-learn the same things, decisions that live in someone's head.

**What problem does it solve that I do not already have a tool for?**
Two. First, design conflicts that never become merge conflicts: two agents in different files making incompatible assumptions. Git, CI, branch protection and code review all work on files and diffs, and this conflict is not in the files. Second, knowledge that does not travel: every agent starts from zero, re-reads the codebase, and repeats dead ends, because nothing one agent learns reaches the next.

**Is it a code editor, an agent, or a CI tool?**
None of those. It does not write, run, or merge code, and it does not run agents. It sits beside your existing tools. Your agent stays your agent; your pull requests stay on GitHub.

**What does it actually touch?**
Plan text that agents send it, memory entries agents write, and, if you connect GitHub, pull requests and PR comments. It never reads a source file.

## How it is used, day to day

**What changes for a developer?**
One-time setup: sign in, create an API key, add one line to your coding agent's config. After that, nothing. The agent talks to Consensus on its own. You hear from Consensus only when your agent's plan collides with someone else's, and then you make a one-click decision.

**Walk me through a normal morning.**
You open your agent and describe the task. Before reading code, the agent asks Consensus what the team knows about that area and gets back a handful of relevant facts. It declares its plan and gets proceed. It works. As it learns things worth keeping, it writes them to shared memory. When done, it files a handoff and a pull request appears with the plan, the changes, and the assumptions in the description. You reviewed nothing extra and typed nothing extra.

**And when there is a conflict?**
Your agent gets wait, with the other agent's name, their plan, and exactly which position disagrees. On the board you, the other developer, or an admin see both plans side by side and pick who proceeds, or say both can with a note. Your agent is released immediately with that ruling. The next time any agent raises the same conflict, the ruling applies automatically.

**Who sees what?**
Everyone on the project sees the same board: open plans, clashes, memory, counters. What differs per person is a strip of clashes that are blocking their agents or waiting on their ruling. Nothing is hidden, so nobody is surprised.

**Who can resolve a clash?**
An organisation admin, or a developer whose own agent is one of the two involved. Everyone else can see it.

**What if my agent ignores a wait?**
It can. Consensus is advisory to the agent but visible to the team: the plan, the verdict and the clash are on the board and in the log. An ignored wait is not silent, and the pull request that follows still carries the clash.

**Does the developer have to write plans?**
No. The agent writes the plan from the task the developer gave it, in the same words it would use to explain what it is about to do. Consensus reads that.

**What about developers who do not use agents?**
They still benefit: the board shows what agents are doing, and rulings and memory are readable by people. A developer can declare a plan through the API or the dashboard if they want their own work coordinated too.

**How do I get my team on it?**
Create an organisation, add a project per repository, send invite links or set an auto-join email domain. Each developer creates a key and adds the one line. Ten minutes for a team.

## How it works

**How do you detect a conflict without looking at files?**
One model call turns each plan into a stance: the concepts it touches, in ordinary domain words like "session model", and its positions on four axes: error handling, authentication, data access, API shape. Then a deterministic comparison: two plans overlap if they share a concept or are semantically close; they clash if they overlap and take different positions on the same axis.

**Why four axes?**
They are where integration failures actually hide. Two pieces of code that agree on those four things generally fit together; two that disagree on any one of them generally do not. The set is small on purpose so extraction is reliable and comparison is explainable.

**Why not just ask a model whether two plans conflict?**
Cost, latency and explainability. A comparison call per candidate pair would be slow and expensive, and its answer would be an opinion. We extract once and compare with arithmetic: same inputs, same verdict, every input logged, and we can show exactly why a clash fired.

**How do you keep false positives down?**
Three ways. An axis a plan does not mention is null and skipped, never guessed, so plans cannot clash on things they did not say. Comparison is negation-aware and tolerant of wording, so "sessions in Redis with a 15 minute TTL" and "session tokens stored in redis, expire after fifteen minutes" agree. And every clash is explainable from its logged inputs, so thresholds are tuned with evidence rather than feel.

**What is a soft clash?**
Two plans overlap on a concept but do not disagree on any axis. Nobody is blocked; the agent proceeds with the other plan as context. It appears on the board for awareness.

**How do rulings compound?**
A ruling is stored with the concept and the axis it settled. Before any hard clash is escalated to a human, Consensus checks for a ruling on that concept and axis. If one exists, the clash is auto-resolved and the agent proceeds with the ruling attached. Interruptions fall as the team's rule set grows.

**Can a ruling about sessions leak onto payments?**
No. Rulings match on concept and axis, so a data-access ruling about the session model applies only to plans that touch the session model.

**What is shared memory?**
A searchable store of short, reusable facts with a type: discovery, decision, dead end, ruling, handoff. Agents query it by meaning, not keyword. Near-duplicates are linked rather than stored twice.

**What does "tokens saved" mean?**
Agents report how many tokens they spend when they read the codebase directly. Each memory read is compared against that average, and the difference is added up. It is measured from the team's own reports, not estimated.

**How fast is a verdict?**
About two to three seconds with Claude Opus, almost all of it the single model call; the rest is milliseconds. A lighter model brings it near one second.

**What happens when two agents declare at the same instant?**
Declarations for a project are serialised behind a lock, so the second one sees the first. They cannot both be told to proceed.

## The MCP layer

**What is MCP and why use it?**
The Model Context Protocol is the standard way coding agents call external tools. Making Consensus an MCP server means every major agent connects the same way: one URL, one header. No plugins per editor.

**What tools does the agent get?**
Six: query memory, declare intent, check verdict, write memory, file handoff, report usage. The server ships instructions telling the agent when to use each, so the workflow runs without the developer prompting for it.

**How does Consensus know which developer an agent belongs to?**
The agent authenticates with a personal API key the developer created. Identity, organisation and default project all come from that key. An agent cannot claim to be someone else, and one developer cannot take over another developer's agent name.

**Which agents work?**
Claude Code, Cursor, Windsurf, and anything else that speaks MCP over HTTP.

## Technology

**What is the stack?**
Python and FastAPI; PostgreSQL with the pgvector extension for all state and vector search; Redis for locks and event fan-out; Claude for stance extraction with structured output; embeddings behind a swappable interface; the MCP Python SDK; GitHub OAuth and REST; JWT sessions and per-user API keys.

**Why Postgres with pgvector instead of a vector database?**
One store for relational data and vectors, transactional, and nothing extra to operate. The volumes here are thousands of plans and memory entries per project, well within pgvector.

**Which model, and can we change it?**
Claude Opus 5 by default, chosen for extraction quality. It is one setting. Sonnet is faster and cheaper and works with the same prompt. Embeddings default to OpenAI and can be swapped; there is an offline provider for demos and tests.

**Does it run without API keys?**
Yes. Offline mode uses a rule-based extractor and hashed embeddings. It is enough for demos and the test suite; real teams should use a model.

**How is it tested?**
Twenty-four automated tests run against a real server, real Postgres and Redis, driving the agent tools over MCP; the golden scenario from the specification is a real test. Separate scripts exercise the real model, a real GitHub repository, and the live event stream.

**Can we self-host?**
Yes. One Python service plus Postgres and Redis. Docker Compose for local, the same image for production.

**How does it scale?**
The service is stateless; Redis pub/sub lets any number of instances share one event stream. The heavy step is the model call, which is one per declaration and parallelises trivially. Postgres holds the rest.

## Security and data

**Does it see our code?**
No. It sees plan text, memory entries agents choose to write, and pull request metadata. Source files never leave your machines.

**Where is our data?**
In your Postgres if you self-host. Plan text and memory are the sensitive parts; treat the database as you would any internal system of record.

**How is access controlled?**
Organisations own projects. You see a project only if you are a member of its organisation. Admins manage members and integrations; members build and can arbitrate clashes involving their own agents.

**What about GitHub permissions?**
Consensus uses the connecting admin's OAuth token with repository scope to open pull requests and comment. It never pushes code. Revoke the token and it stops.

## Business

**How is it priced?**
Per developer seat, because that is what scales with value: one agent per developer. A free tier for one repository and a small team, then a per-seat monthly price with unlimited declarations, then business and enterprise tiers with SSO, audit export and support. The specific numbers are a proposal at this stage.

**Who is the buyer?**
The engineering lead or platform team that owns developer productivity. It lands bottom-up: one team turns it on, sees the first caught clash, and the rest follow.

**What is the competition?**
Nothing does intent-level conflict detection. Adjacent tools are code review assistants, which act after the code exists; file locking and branch protection, which act on files; and agent orchestration platforms, which run agents for you. Consensus sits beside all of them and does the one thing they cannot: catch a conflict in plans before there is a diff.

**Why now?**
Because the number of agents per team just went from zero to one per developer, and the tools that coordinate humans were never built to see what agents intend.

**What is the roadmap?**
Near term: metering and billing, encryption of stored integration tokens, email delivery, background PR sync. Then richer axes learned from real team vocabulary, per-repository synonym maps, and analytics on which rulings save the most interruptions. Longer term: coordination across repositories in the same organisation.

## Limitations, stated plainly

**What does it not do yet?**
Embeddings and Notion have not been exercised with real keys in this build; the offline embedding provider is in use. Real GitHub merge webhooks need a public URL. Magic links need an email provider. Pricing limits are not enforced. Stored OAuth tokens are not encrypted at rest.

**Where will it be wrong?**
The comparison is heuristic, tuned on a small set of plan pairs. Teams with unusual vocabulary will see some false clashes until the synonym map is extended, and a plan written vaguely produces a vague stance. Both are visible and tunable because every verdict is logged with its inputs.

**Does it slow developers down?**
A declaration costs a second or two of agent time, not developer time. The developer is interrupted only for a genuine conflict, and each ruling makes the next one automatic.
