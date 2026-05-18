# Clayworks LITE — design rationale

Why each of the LITE components is shaped the way it is. The SKILL.md files and main README cover **what** the kit does; this directory covers **why** specific design choices were made and what was rejected along the way.

Read these when:

- You're customizing a LITE component and want to know whether your change crosses the line into "fights the design" territory.
- You're evaluating LITE against alternatives and want to see whether the trade-offs we accepted match the trade-offs you'd make.
- You're considering contributing a change to the design (vs. just an addition) — read the relevant rationale first; the reasoning may already address what you'd propose.

## Files

- [`why-claude-md-structure-matters.md`](why-claude-md-structure-matters.md) — Why the CLAUDE.md template orders sections the way it does (identity → memory routing → behavioral rules → project context) and why ordering matters more than content.
- [`memory-routing-rationale.md`](memory-routing-rationale.md) — Why three memory layers (Engram + native MEMORY.md + Honcho), why a routing skill is needed at all, what alternatives were rejected.
- [`heartbeat-design.md`](heartbeat-design.md) — Design choices behind the heartbeat pattern (cadenced observe + reflect + update). Why three steps not five, why bounded time budget, what cadence to pick.
- [`installer-design.md`](installer-design.md) — Why backup-then-install + SHA-256 hash-diff, why reject symlinks, why pure ASCII, why no auto-edit of `settings.json`.
- [`upgrade-philosophy.md`](upgrade-philosophy.md) — What LITE intentionally doesn't ship and the principles separating "free baseline" from "paid bundle." How to predict whether a given feature falls on the LITE side or the bundle side.

## What this directory is NOT

- **Not user-facing onboarding** — that's the README + the SKILL.md docs. Start there.
- **Not exhaustive design history** — each doc covers the one or two non-obvious choices that matter for the design's coherence. Implementation details live in the source files, not here.
- **Not stable forever** — as LITE evolves, some of these rationales will be revised or made obsolete. The historical "why we did it this way at v1" stays useful even after that.
