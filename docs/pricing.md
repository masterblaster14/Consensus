# Pricing

> **Proposal.** The tiers, limits and prices below are a starting point for the landing page, not a decision. Everything is priced per developer seat because that is what scales with the value delivered (one agent per developer). Adjust before publishing.

Simple, per-seat pricing. Every plan includes the full conflict-detection engine; the tiers differ in team size, history, and integrations.

| | **Free** | **Team** | **Business** | **Enterprise** |
|---|---|---|---|---|
| Price | $0 | **$20** / developer / month | **$45** / developer / month | Custom |
| Best for | Trying it on one repo | Small teams shipping with agents | Multiple teams and repos | Regulated or large organisations |
| Organisations | 1 | 1 | Unlimited | Unlimited |
| Projects (repositories) | 1 | 5 | Unlimited | Unlimited |
| Developer seats | up to 3 | up to 25 | Unlimited | Unlimited |
| Plan declarations | 500 / month | Unlimited | Unlimited | Unlimited |
| Shared memory | 1,000 entries | Unlimited | Unlimited | Unlimited |
| Verdict and clash history | 7 days | 90 days | 1 year | Unlimited |
| Live board | ✓ | ✓ | ✓ | ✓ |
| Human arbitration and compounding rulings | ✓ | ✓ | ✓ | ✓ |
| GitHub integration (PRs, comments, merge sync) | ✓ | ✓ | ✓ | ✓ |
| Notion integration | | ✓ | ✓ | ✓ |
| Auto-join by email domain | | ✓ | ✓ | ✓ |
| Bring your own model keys | | ✓ | ✓ | ✓ |
| SSO / SAML | | | ✓ | ✓ |
| Audit log export | | | ✓ | ✓ |
| Self-hosted option | ✓ (community) | | ✓ | ✓ |
| Support | Community | Email | Priority email | Dedicated, SLA |

Annual billing: two months free.

## What counts as a seat?

A seat is one developer who signs in and connects an agent. Viewers who only watch the board do not use a seat. Agents are not seats: one developer can run several agents under one key.

## What counts as a declaration?

One call to `declare_intent`. Memory reads and writes, handoffs and rulings are unlimited on every plan. Only the Free tier caps declarations.

## Model usage

Consensus makes exactly one language-model call per declaration and none for memory reads or comparisons. On hosted plans this is included. Teams that bring their own keys pay their provider directly; typical cost is a fraction of a cent per declaration.

## Self-hosting

The community edition is open for self-hosting on the Free tier terms. Business and Enterprise include a supported self-hosted deployment with the same features as hosted.

## Questions

**Can I try Team before paying?**
Yes. Every new organisation starts with a 14-day Team trial. If you do nothing, it drops to Free.

**What happens if we go over the Free limits?**
Declarations beyond the monthly cap return *proceed* with a notice instead of a full verdict, so nothing breaks. Upgrade to restore full detection.

**Do you store our code?**
No. Consensus stores plan text, extracted stances, memory entries and handoff notes. It never reads or stores source files.

**How do I cancel?**
From the organisation's billing page, at any time. Your data stays readable on the Free tier.
