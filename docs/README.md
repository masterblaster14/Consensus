# Consensus docs (website copy)

Markdown pages intended for the landing site. Each file is self-contained and can be rendered as its own page.

| Page | File | Purpose |
|---|---|---|
| Getting started / How to use | [getting-started.md](getting-started.md) | Step-by-step from sign-up to first ruling; the "how to use" section for the landing page |
| How it works | [how-it-works.md](how-it-works.md) | The mechanism: stance extraction, deterministic comparison, verdicts, rulings, memory |
| Features | [features.md](features.md) | Feature list grouped by theme, landing-page ready |
| Pricing | [pricing.md](pricing.md) | Proposed tiers and limits. **Numbers are a proposal; limits are not enforced by the backend yet.** |
| Backend reference | [backend-reference.md](backend-reference.md) | Developer reference: setup, layout, verdict internals, MCP tools, REST/WS contracts, auth, integrations |

The top-level [README](../README.md) describes the product; the developer-facing reference is [backend-reference.md](backend-reference.md).

Notes for whoever builds the pages:

- Everything described in Getting started, How it works and Features exists in the backend today, with one nuance: "open PRs that were never declared still appear on the board" is an on-demand sync (`POST /api/projects/{id}/integrations/github/sync`), not a background poll, so the frontend should expose a sync button or call it on board load.
- Pricing tiers (seat caps, declaration caps, history retention, SSO, audit export, trials) are copy only. Nothing in the backend meters or enforces them.
- Replace `https://<your-consensus-host>` in code samples with the real hostname.
