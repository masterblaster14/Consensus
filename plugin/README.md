# Consensus plugin for Claude Code

One install gives an agent everything it needs to work on a Consensus-coordinated
repository:

- the **Consensus MCP server** (`declare_intent`, `check_verdict`, `query_memory`,
  `write_memory`, `file_handoff`, `withdraw_claim`, `get_status`, `report_usage`)
- a **guardrail hook** that refuses `Edit` / `Write` until the plan has been declared
  and the verdict allows work (and while a clash is waiting on a human)
- a **workflow skill** the agent loads at the start of a task

## Install

```bash
export CONSENSUS_URL="https://<your-consensus-host>/mcp"
export CONSENSUS_API_KEY="csk_..."        # Settings -> API keys in Consensus

claude plugin marketplace add masterblaster14/Consensus
claude plugin install consensus@consensus
```

Restart Claude Code. `/mcp` should list `consensus` as connected.

## Try it

Ask the agent to add a logout endpoint. It will query memory, declare the plan, get a
verdict, and only then edit. Ask a second agent (another terminal, another key) to
change the session model. One of them gets `wait`, and the clash appears on the board
for a human to rule.

## Options

| Variable | Effect |
|---|---|
| `CONSENSUS_ENFORCE=0` | Turn the guardrail off |
| `CONSENSUS_ALLOW_PATHS=docs/,README` | Path prefixes that never need a declaration |
| `CONSENSUS_STATE_DIR` | Where per-session state is kept (default `~/.consensus/sessions`) |

The hook is `hooks/require_declaration.py`. It keeps one small JSON file per Claude
Code session and makes no network calls.
