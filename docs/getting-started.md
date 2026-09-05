# Getting started with Consensus

Consensus is a coordination layer for teams whose developers each run their own AI coding agent on the same repository. Before an agent writes code, it tells Consensus what it plans to do. Consensus checks that plan against every other open plan on the team and against what the team already knows, then answers in under a second: **proceed**, **proceed with context**, or **wait**.

You do not change how you code. Your agent does the talking. You only hear from Consensus when two plans are about to collide.

---

## 1. Create your account

Sign in with **GitHub** (recommended, one click) or with an **email magic link**. No passwords.

Signing in with GitHub also lets Consensus open pull requests and comment on them for your organisation later, so the person who will administer the team should use GitHub.

## 2. Create an organisation

An organisation is your team. The person who creates it becomes its **admin**.

Pick a name. Optionally set an **auto-join domain** such as `acme.com`: anyone who later signs in with a verified `@acme.com` email joins automatically as a member, with no invite needed.

## 3. Add a project

A project is one repository. Give it a name and, if you connected GitHub, pick the repo from the list. Everything Consensus tracks (plans, clashes, shared memory) lives inside a project, and the whole team sees the same board for it.

## 4. Invite your teammates

From the organisation's **Members** page, create an invite link. You can:

- pin it to a specific email address, so only that person can use it
- choose the role it grants: **member** (the default) or **admin**
- leave it open, so anyone with the link can join

Send the link however you like. The invitee signs in, lands on the invite page, and clicks **Join**.

| | Admin | Member |
|---|---|---|
| See the board, run agents, write to shared memory | ✓ | ✓ |
| Arbitrate a clash | any clash | clashes involving their own agents |
| Invite and remove members, change roles | ✓ | |
| Connect GitHub and Notion for the organisation | ✓ | |

## 5. Connect your coding agent

This is the step that links *you* to *your agent*.

1. Open your **profile → API keys** and create a key. Optionally bind it to a project so your agent never has to say which project it means. The key is shown once and looks like `csk_…`.
2. Register Consensus as an MCP server in your coding agent, passing the key as a bearer token.

**Claude Code**

```bash
claude mcp add --transport http consensus https://<your-consensus-host>/mcp \
  --header "Authorization: Bearer csk_..."
```

**Cursor, Windsurf, and other MCP clients** take the same URL and header in their MCP settings:

```json
{
  "mcpServers": {
    "consensus": {
      "url": "https://<your-consensus-host>/mcp",
      "headers": { "Authorization": "Bearer csk_..." }
    }
  }
}
```

That is the whole setup. Because the key belongs to you, everything your agent does is attributed to you. An agent cannot claim to be a different developer, and nobody else's agent can take over your agent's name.

## 6. Work as usual

Your agent now has six tools and the instructions to use them. A typical session looks like this:

1. **`query_memory`** – before reading the codebase, the agent asks what the team already knows: "how does login work?" It gets back discoveries, decisions, dead ends and past rulings, ranked by relevance. Reading five memory entries is cheaper than re-reading the codebase, and Consensus keeps a running count of the tokens that saves.
2. **`declare_intent`** – before writing code, the agent states its plan in plain language. Consensus replies with one of three verdicts:
   - **proceed** – nothing overlaps; go.
   - **proceed with context** – go, but read the attached memory entries or ruling first.
   - **wait** – another agent's open plan conflicts with yours. The response names the other agent, their plan, and exactly which position differs. The agent parks until a human rules.
3. **`write_memory`** – whenever the agent learns something reusable, it records it: a discovery about how the code works, a decision, or a dead end. Near-duplicates are linked rather than stored twice.
4. **`file_handoff`** – when the change is ready, the agent files a handoff: what changed, what it deliberately left alone, its assumptions and its open questions. Consensus stores it, marks the plan as in review, and (with GitHub connected) opens the pull request with all of that in the description.

## 7. Resolve a clash

When a verdict is **wait**, the clash appears on the project board and in the **needs you** strip of anyone who can arbitrate it. Open it and you see both plans side by side, the shared concept, and the two positions on the axis where they diverge. Choose:

- **A proceeds** – the earlier plan wins
- **B proceeds** – the newer plan wins
- **Both, with a note** – they can coexist; explain how

Add a short note. The moment you resolve it:

- the waiting agent is released and receives your ruling
- the ruling is written to shared memory
- if either plan has a pull request, the ruling is posted there as a comment

**Rulings compound.** If any agent later declares a plan that would raise the same clash on the same concept and axis, Consensus applies your ruling automatically and answers *proceed with context* instead of asking a human again.

## 8. Optional integrations

**GitHub** – an admin who signed in with GitHub clicks **Connect** on the organisation's Integrations page. From then on, handoffs open pull requests, rulings are posted as PR comments, merged PRs retire their plans from the board, and open PRs that were not declared through Consensus still appear on the board so nothing is invisible.

**Notion** – paste an internal integration token and the id of your tasks database. Consensus syncs tasks in (so plans can reference tickets) and mirrors decisions, dead ends and rulings out as pages that link back to the plan and PR.

Neither integration is ever on the critical path. If GitHub or Notion is down, declaring still takes under a second.

---

## Frequently asked

**Does Consensus read or write my code?**
No. It reads plans, not files. It never executes code, never edits files, and never merges. The only things it touches in GitHub are pull requests and their comments.

**How does it detect conflicts if it does not look at files?**
It compares what plans *mean*: the concepts they touch and the positions they take on error handling, authentication, data access and API shape. Two plans in different files that disagree about where sessions live are still a clash. See [How it works](how-it-works.md).

**What if my agent ignores the verdict?**
Consensus is advisory to the agent but visible to the team. Every plan, verdict and clash is on the board and in the log, so an ignored *wait* is not silent.

**Can I run it without an LLM key?**
Yes. In offline mode a deterministic extractor stands in for the language model. It is good enough for demos and tests; for real teams, connect a model key for better concept extraction.

**Where do I run it?**
Self-host with Docker Compose (Postgres with pgvector, Redis, one Python service) or use the hosted version. Both expose the same API.
