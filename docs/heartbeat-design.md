# Heartbeat pattern — design rationale

The `clayworks-lite-heartbeat-concept` skill describes a three-step loop (observe → reflect → update) at one or more cadences. This doc explains why three steps and not five, why a bounded time budget, and what cadence to pick for what work.

## The core observation

AI agents (and their users) suffer the same problem: **what was "current" gets less current with time, and nobody notices until it breaks**. The CLAUDE.md you wrote two months ago contradicts the workflow you've evolved into. The "open threads" list you maintained until last month is now lying. The decisions you made and forgot the rationale for are now mystery code.

A heartbeat is the discipline of *deliberately re-anchoring on a schedule* rather than hoping the right memory surfaces when needed.

## Why three steps, not five

The skill is structured as **observe → reflect → update**. Three. Why not five (read, summarize, evaluate, decide, write)?

Because three is the minimum that still preserves the loop:

- **Observe alone** (just read recent state) is logging-without-comprehension.
- **Reflect alone** (just synthesize) dies with the conversation that thought it.
- **Update alone** (just write to a file) is drift-blind state churn.

Five steps would split "reflect" into multiple stages (summarize → evaluate → decide). In practice, when humans do this kind of work, those stages compress; trying to separate them adds ceremony without adding signal. The skill calls it out as one step explicitly so the ceremony doesn't appear.

## Why bounded time budget

The heartbeat skill recommends "20 minutes thinking + 5 minutes writing, hard cap" as an example (reframed during the audit from a prescription to an author-specific example). Why bound it at all?

**Because unbounded reflection becomes the work, not the support for the work.** A 40-minute heartbeat that produces a great reflection is worse than a 5-minute heartbeat that produces a mediocre one *every day for a year*. Cadence beats intensity for this specific discipline. The "if you can't say it in 5 minutes of writing, your reflection is the wrong shape" line is the test for this — long writing means you're trying to capture too much, which usually means you didn't reflect enough to know what the *salient* thing is.

The exact budget is per-user. The principle (bound it) is universal.

## Why the specific cadences

The skill names six cadences (per-prompt, per-turn, end-of-session, daily, weekly, monthly). Each maps to a specific scale of state-rate-of-change:

| Cadence | Rate of change observed | Typical artifact |
|---|---|---|
| Per-prompt | Sub-second context shifts | `UserPromptSubmit` hook injection (Nudge, freshness gate) |
| Per-turn | Single-turn deltas | `Stop` hook (per-turn observability) |
| End-of-session | Session-scope changes | `SessionEnd` hook + summary write-back |
| Daily | Day-scope changes | Cron / Task Scheduler (outside CC's hook lifecycle) |
| Weekly | Pattern recognition window | Manual or scheduled |
| Monthly | Identity-level shift detection | Manual; rare cadence |

**Picking the wrong cadence is the most common heartbeat failure mode.** A daily beat for something that changes weekly produces noise. A weekly beat for something that changes hourly produces stale signal. The skill explicitly calls this out in the anti-patterns section ("beating on the wrong axis").

The decision: **match the cadence to the rate-of-change of the thing being observed**, not to your meeting schedule or your habits. If your project changes weekly, a daily review is theater. If your CLAUDE.md changes monthly, a daily review is just reading.

## Why "concept only, not implementation" for LITE

LITE ships the *pattern*, not a heartbeat system. The full production implementation (three-tier observability stack, daily-cycle templates, trust ledger schema, drift signaling) lives in the paid Clayworks bundle.

This split was a deliberate scope choice:

- The **pattern** is reusable across implementations. Documenting it in LITE gives users the shape they can build to.
- The **implementation** is *months of hardening* on a specific shape (specific telemetry schemas, specific log paths, specific anomaly thresholds). Shipping the implementation generically would either (a) leak the author's specific operational choices into a public artifact, or (b) require generalization work that hasn't been done.

The "you can build all of this yourself from the pattern above" line in the SKILL.md is the honest framing. The pattern is the contribution; the implementation is paid because the implementation is real work that has been done and is being commercialized.

## Alternatives considered

**Single cadence (just daily).** Considered. The audit's Phase 5 specifically asked whether the skill over-articulated cadences. Decision: keep all six because users land at different scales — a freelancer doing one project might never need monthly; an operator running an org might need all six. Naming all six means users can pick; pruning to one forces a guess.

**Implement heartbeat in LITE (vs. concept only).** Considered. Rejected for the scope reasons above + because a generic heartbeat implementation is much bigger than LITE's "minimal" surface allows. A `STATE.md.example` template ships (closes the "concept ≠ implementation" gap with the minimum-viable artifact); anything beyond is paid-bundle territory.

**No heartbeat skill at all (just docs in README).** Considered. Rejected because the skill needs to *auto-trigger* on relevant user mentions ("how do I track my agent's state over time?", "what's a good reflection cadence?") — a README section doesn't fire as a skill does. The frontmatter description is half the value.

**Use a different framing word (cycle, loop, beat, rhythm).** "Heartbeat" was chosen because it carries the *involuntary, persistent, alive* connotation that the discipline aims for. "Cycle" felt mechanical. "Loop" felt programmatic. "Rhythm" felt aesthetic. "Heartbeat" is somatic — the right register for a discipline meant to keep the agent (and user) alive across time.

## Trade-offs accepted

- **"Heartbeat" as terminology may not generalize.** Some users will find it overwrought. Accepted: the alternative terms have their own problems; "heartbeat" + the explicit anti-patterns section + the "minimum-viable heartbeat" starter mitigates the over-clinical feel.
- **The pattern lives in a SKILL.md without an executable component.** Users who copy LITE expecting "a tool" get docs. Accepted: the docs ARE the tool for the concept layer. Production implementation in the paid bundle.
- **The six cadences could collapse to fewer.** The audit considered this. The skill's `Cadences` section names all six even though most users will use 2-3. Verbosity accepted to give the full map.

## When this design would be wrong

- **You don't have multi-session work that needs continuity.** If every Claude session is a one-shot interaction, there's no drift to fight; the heartbeat is overhead. The skill should never fire; users who don't need it should ignore the skill description.
- **You work in deeply collaborative environments.** Heartbeat is single-operator discipline. Teams need different mechanisms (standups, retros, etc.) — closer to traditional engineering practice than to agent telemetry.
- **The "20 minutes thinking" feels precious to you.** That's a signal the wider pattern probably isn't for you either. Try a 5-minute version once; if even that feels like ceremony, this isn't the discipline.

## What this doc is NOT

- **Not the SKILL.md** — `skills/clayworks-lite-heartbeat-concept/SKILL.md` carries the cadences + anti-patterns + composition notes. This doc explains why the pattern has its specific shape.
- **Not implementation guidance** — see the SKILL.md "Minimum-viable heartbeat" section + `templates/STATE.md.example` for the start-today shape. The paid Clayworks bundle has the production version.
