---
name: consensus-workflow
description: How to work on a repository coordinated by Consensus. Use at the start of any coding task when the consensus MCP server is connected, and whenever a Consensus tool returns a verdict, a clash, or a ruling.
---

# Working with Consensus

Consensus coordinates every AI coding agent on this repository. Other agents are
working right now; some of their plans may conflict with yours. Consensus catches
that before code exists, and remembers what the team has already learned.

## The loop

1. **Ask memory first.** `query_memory(question)` before reading the codebase. It
   returns discoveries, decisions, dead ends and rulings from every agent on the
   project. Reading three memory entries is cheaper than re-reading ten files.
2. **Declare before editing.** `declare_intent(agent_name, plan_text, branch, task_ref)`
   with a plain-language plan: what you will change and how. Two or three sentences
   that name the parts of the system you touch and the positions you take (how you
   handle errors, auth, data access, API shape).
3. **Obey the verdict.**
   - `proceed`: go ahead.
   - `proceed_with_context`: read every item in `context` (and `ruling` if present)
     first. They are decisions and discoveries that bear on your plan. Then go ahead.
   - `wait`: a hard clash with another agent's open plan. Do not edit code. Call
     `check_verdict(clash_id, wait_seconds=120)` until a human rules, then follow
     the ruling. If you are abandoning the plan, call `withdraw_claim(claim_id)`.
4. **Record what you learn.** `write_memory(type, content, concepts)` for every
   discovery about how the code works, every decision you make, and every dead end
   you hit. One to three sentences, specific and reusable.
5. **Hand off when done.** `file_handoff(claim_id, changed, untouched, assumptions,
   uncertainties)`. This moves your claim to review and opens the pull request.

`get_status()` shows your open claims and any clash waiting on you.

## The guardrail

This plugin installs a hook that refuses `Edit` and `Write` until the session has
a declaration whose verdict allows work. If you see "Consensus: declare your plan
before editing code", do step 2. If you see "waiting on a human ruling", do step 3.

## Writing a good plan

Say what changes and what position you take, not which files. Consensus compares
meaning, not paths.

Good: "Replace the session model with a refresh-token flow. Sessions move from the
server-side store to signed tokens. Auth failures return 401 JSON."

Weak: "Update auth.py and middleware.py."

## Configuration

`CONSENSUS_URL` (default `http://localhost:8000/mcp`) and `CONSENSUS_API_KEY`
(a `csk_` key from the Consensus settings page) must be set in the environment
before starting Claude Code. `CONSENSUS_ENFORCE=0` disables the guardrail.
