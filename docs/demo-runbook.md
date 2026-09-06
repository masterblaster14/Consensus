# Demo runbook

The operator's guide for the hosted product: what to prepare, how to rehearse, what
to show for the MCP server and the marketplace listings, and how to recover. The
presenter's script is `demo-script.md`.

Hosted instance: https://consensus-production-aed6.up.railway.app. It runs the
backend, the web app, the API, the WebSocket and the MCP endpoint from one origin.
Sign-in is GitHub. Stance extraction uses the real Anthropic model.

## 1. The day before: rehearse the whole thing once

Do the script end to end with the teammate who will be on laptop 2. Use a repository
one of you administers (webhook registration needs admin rights on it) and that both
of you can push to. Name the organisation something like "Rehearsal".

What the rehearsal buys you:

- Both GitHub accounts authorise the OAuth app once. On stage GitHub redirects back
  with no consent screen.
- The rehearsal organisation stays as the fallback. If anything is slow on stage,
  switch to it from the sidebar switcher; it already has the team, the members, the
  keys, memory and a merged pull request.
- Each of you has `consensus` in Claude Code already. On stage, creating a new key and
  re-running `claude mcp add` replaces the header; that is the whole reconnect.

Check that the pull request step works in rehearsal: the agent must push its branch
to the attached repository before `file_handoff`, and the merge must retire the plan
on the dashboard within a few seconds. If merging does not retire it, the webhook was
not registered: open the team's Integrations page and click register.

## 2. On the day, before the audience arrives

1. Open https://consensus-production-aed6.up.railway.app/health on the projector
   laptop. You want `"status":"ok"` with database and redis both true.
2. Both laptops: signed out of the site, Claude Code open in the repository folder,
   a terminal beside the browser. The dashboard updates within a second of every
   command, and that is the demo, so keep them side by side.
3. Have the three prompts from the script in a text file to paste.
4. Have the rehearsal pull request open in a background tab.
5. Decide the organisation name for the stage run. It must differ from the rehearsal
   one because slugs are unique.

## 3. Showing the MCP server itself

Three things prove the integration is real rather than a page that looks like one:

- **`/mcp` inside Claude Code** lists `consensus` as connected with eight tools:
  `declare_intent`, `check_verdict`, `query_memory`, `write_memory`, `file_handoff`,
  `withdraw_claim`, `get_status`, `report_usage`.
- **The endpoint is public and authenticated.** `POST /mcp` without a key returns
  401. With a key, Claude Code's tool calls are what you see moving on the dashboard.
- **The API page.** https://consensus-production-aed6.up.railway.app/docs is the
  interactive OpenAPI page; every endpoint the dashboard uses is there and can be
  called with a key as the bearer token (click Authorize).

## 4. Showing the marketplace listings

**MCP Registry.** The server is published as `io.github.masterblaster14/consensus`.
The listing, with the hosted URL and the header it needs, is at:

```
https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.masterblaster14/consensus
```

Any client that reads the registry can find it by name.

**Claude Code plugin marketplace.** The repository is itself a marketplace, and the
plugin bundles the MCP server, the guardrail hook and the workflow skill:

```
set CONSENSUS_API_KEY=csk_...
claude plugin marketplace add masterblaster14/Consensus
claude plugin install consensus@consensus
```

After a restart `/plugin` shows it installed and `/mcp` shows the server. Install it
on laptop 2 before the demo if you want step 8 of the script, where the hook refuses
an edit until the plan is declared.

## 5. Recovering

| Problem | Do this |
|---|---|
| GitHub sign-in hangs | Retry once; then use the rehearsal organisation, already signed in on the other laptop |
| Verdict is `proceed` where the script expects `wait` | A ruling from an earlier run in the same organisation applies; that is correct behaviour. Use a fresh organisation, or change one plan's position |
| Agent B does not wake after the ruling | Its `check_verdict` timed out; ask it to call `check_verdict` again with the clash id |
| Pull request did not open | The branch was not pushed to the attached repository. Push it and ask the agent to file the handoff again, or show the rehearsal pull request |
| Merge did not retire the plan | The webhook was not registered: Team, Integrations, register it. Retire the already-merged plan with Withdraw on its page; the next merge retires on its own |
| Dashboard shows the footer dot grey | The WebSocket dropped; it reconnects on its own, and a page reload reloads everything from the API |

## 6. Resetting

There is no delete for organisations. Between runs, create a new organisation with a
new name; old ones stay in the switcher and cost nothing. Archive a team from
**Manage teams** if you want it out of the way.

## 7. Running it locally instead

Everything above also runs on a laptop with Docker: see `getting-started.md`. The
web app is served at http://localhost:8000 once `frontend/dist` is built, the sign-in
page offers a development sign-in when `DEV_AUTH=true`, and GitHub cannot reach a
laptop for the merge webhook, so the local scripts simulate it. The hosted instance
is the one to demo.
