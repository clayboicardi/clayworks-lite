# Upgrade philosophy — LITE vs. paid bundle

LITE intentionally doesn't ship features that exist in the paid Clayworks bundle. This isn't gatekeeping; it's scoping. This doc explains the principles separating the two and how to predict which side a given feature falls on.

## The line, in one sentence

**LITE ships the patterns and minimum competent baselines. The paid bundle ships the production-hardened implementations of those patterns.**

A pattern is: the heartbeat-concept skill (a written description of the observe/reflect/update loop + cadences + anti-patterns + minimum-viable single-file artifact). A production implementation of that pattern is: the three-tier observability stack with telemetry schemas, trust-ledger aggregation, drift-signaling routes, daily-cycle templates that have been tuned against months of real use. The pattern is the contribution; the implementation is the work.

The same line applies to most paid-bundle features.

## Why the split exists

Three reasons, in order of importance:

1. **The implementations have months of hardening behind them.** Generalizing a heartbeat implementation that was built for one operator's workflow, then making it portable across configurations, is real work. Shipping it free would either skip the generalization (giving users a kit shaped wrong for them) or do the work without compensation. Neither is sustainable.

2. **The free baseline has to be useful on its own.** If LITE is just "marketing for the bundle," users notice and bounce. LITE has to deliver enough value to justify a download even from users who never buy. The 7-component baseline (CLAUDE.md template, three skills, hook examples, settings example, examples/ composites, README + installers) is calibrated against this.

3. **The line has to be predictable.** Users evaluating LITE need to be able to look at it and know what's there vs. what's gated. The "What's NOT in LITE" section of the README enumerates the bundle's specific features explicitly; this doc explains *why* each one is on that side of the line.

## How to predict which side a feature falls on

For any operator-system feature, ask three questions:

**Question 1: Is it a pattern or an implementation?**

- **Pattern** (the *shape* of how to do something) → LITE.
- **Implementation** (the *working code* that does it for you) → bundle.

Examples:
- Heartbeat-concept skill: pattern. LITE.
- Trust-ledger schema with append-only JSON capped at 60 entries, per-tier summary aggregation, SPC-style streak analysis: implementation. Bundle.

**Question 2: Does it require user-specific setup that LITE can't generically provide?**

- **No** (works the same for every operator) → LITE.
- **Yes** (needs Telegram bot tokens, specific filesystem layouts, specific cron, specific notification routing) → bundle.

Examples:
- Memory-routing decision tree: works for every operator with any subset of the three layers. LITE.
- CC↔CC inter-session communication system with filesystem messaging + Telegram routing + auto-spawn handoffs: requires Telegram credentials, specific filesystem paths, specific notification routing. Bundle.

**Question 3: Is the kit's "minimum competent baseline" promise undermined without it?**

- **Yes** (LITE would feel gimped) → LITE (add it).
- **No** (LITE works without; users who want it can level up) → bundle.

Examples:
- A CLAUDE.md template: yes, LITE feels gimped without a starter shape. LITE.
- A 15-30 page "Operating Claude Code at production quality" written guide: no, LITE works without the deep operator-manual. Bundle.

The three questions don't always agree. When they conflict, **Question 1 is the deciding question** — pattern vs. implementation is the load-bearing distinction.

## Worked examples — applying the framework

**Settings.example.json** (composed working `settings.json` showing hooks composition). Q1: pattern (the *shape* of hook composition). Q2: no user-specific setup. Q3: LITE feels gimped without it (audit finding — 5 separate LITE files reference settings.json without showing assembly). → **LITE.** Shipped.

**Upper observability layers** (Layer 2 rubric-graded outcome evaluation + Layer 3 structural-validity checking, on top of the Layer 1 liveness pattern the free heartbeat-concept documents). Q1: implementation. Q2: Layer 2 needs an LLM and specific telemetry paths; Layer 3 needs a config-walker with specific check thresholds. Q3: LITE doesn't need them for the minimum competent baseline; the heartbeat-concept skill is Layer 1 and describes the pattern. → **Bundle.**

**Plugin baseline doc** (curated list of plugins with rationale per plugin). Q1: pattern, debatable — it's curation-as-content. Q2: no setup, just docs. Q3: LITE doesn't need it for minimum baseline; the README's "Acknowledgments" credits 4-5 specific plugins and the LITE template names 2 (Engram, Honcho; Octo was dropped after its 2026 retirement). → **Bundle for the full 20-plugin operator baseline (plus optional add-ons) with rationale.**

**Worked CLAUDE.md examples** (template with placeholders filled). Q1: pattern (the *shape* of an assembled CLAUDE.md). Q2: no user-specific setup. Q3: LITE feels notably less competent without a "what does this look like assembled?" reference. → **LITE.** Shipped in `examples/full/CLAUDE.md`.

**Telegram notification integration** (proactive pings + remote control of CC instance from phone). Q1: implementation. Q2: requires Telegram bot credentials, specific allowlist files, specific notification routing. Q3: not needed for minimum competent baseline. → **Bundle.**

**Hook scaffolding examples** (one `.sh` per CC hook event). Q1: pattern (the shape of a hook script). Q2: no setup. Q3: LITE definitely feels gimped without these — users would have to write hooks from scratch. → **LITE.** Shipped.

**Inbox watcher pattern** (drop a markdown file in a folder; agent picks it up on next session start). Q1: implementation (specific filesystem path, specific hook integration). Q2: yes user-specific setup. Q3: not needed for baseline. → **Bundle.**

## The "What's NOT in LITE" section — discipline

The README's "What's NOT in LITE" section is the single most-important honesty surface in the entire repo. It names what's in the bundle so users can see exactly what they'd be buying. The discipline:

- **Every paid-bundle feature should be in that list, by name, with one sentence of description.**
- **No vague language** ("advanced features", "production-grade tooling") — concrete names only.
- **No overselling.** If a bundle feature is debatable on the LITE/bundle line, lean toward including it in LITE.
- **No artificial scarcity.** Features go on the LITE side based on the three-question framework, not on revenue optimization.

The audit caught one bundle item that was over-specifically named in the heartbeat SKILL.md (the upper observability layers, trust ledger schema, drift signaling, and daily-cycle templates). The audit's verdict: that level of specificity worked because it was paired with "you can build all of this yourself from the pattern above." The honest tease is honest because it invites the reader to do the work themselves. Withholding the names while charging for them is the dishonest version.

## When you'd revisit the line

Several conditions would shift items across the line:

- **A pattern crystallizes into a generic-enough implementation to ship in LITE.** E.g., if the dream-skill consolidation pattern develops a configuration-agnostic shape, it could move from bundle to LITE. Hasn't happened yet at v1.
- **A bundle feature has been adopted by competitors generically.** If "CC↔CC inter-session communication" becomes a standard pattern others ship as plugins, the bundle's version becomes "our hardened variant" rather than "the only option" — possibly moving LITE-side as a thin wrapper.
- **Marketing pressure to add value to LITE.** Resist. The three-question framework is the discipline; ad-hoc additions break the predictability.

## What this doc is NOT

- **Not pricing strategy** — the bundle's pricing is in the README. This doc is about feature placement, not revenue.
- **Not a roadmap** — items currently in the bundle won't all stay there forever, but this doc doesn't predict moves.
- **Not exhaustive** — the framework covers the typical case. Edge features get evaluated case-by-case with the three questions as the guide.
