---
name: clayworks-lite-heartbeat-concept
description: Reference for the heartbeat pattern — a cadenced loop of observe + reflect + update that keeps an agent's state coherent across sessions. Use when the user asks about agent self-observation, daily/weekly cycles, reflection cadences, the "heartbeat" pattern, drift detection, or how to make Claude Code reflect on its own state between sessions. Concept reference only — production implementation ships in the paid Clayworks bundle; this doc is enough to roll your own.
---

# Clayworks LITE — Heartbeat framework (concept)

A **heartbeat** is a structured, cadenced loop that keeps an agent's state coherent over time. Without it, what was "current" two weeks ago feels like "current" now — and drift accumulates silently until something breaks.

This document explains the *pattern*. The full production implementation — telemetry schema, trust ledger, three-tier observability, daily-cycle templates — ships in the paid Clayworks bundle. **You do not need that to start.** A minimum-viable heartbeat takes one file and three lines of discipline.

---

## What a heartbeat is (the pattern)

Every heartbeat — regardless of cadence or sophistication — does three things on a repeating schedule:

1. **Observe state.** Read context: current work, recent activity, system health, open threads. The agent (and the user) anchor on what *is*, not what they remember to be the case.
2. **Reflect.** Synthesize the observation: what's working, what's drifting, what needs attention. This is the step that produces signal — without it, observation is just logging.
3. **Update.** Write back to durable state. Logs, summary files, telemetry, a `NOW.md`-style anchor. The reflection escapes the conversation and survives the next compaction.

Skip any of the three and the pattern degrades:

- **Observation without reflection** → telemetry noise nobody reads
- **Reflection without update** → it dies with the session that thought it
- **Update without observation** → drift-blind state churn

---

## Why you'd want one

If you use Claude Code (or any agent) for real work over weeks, you've hit these:

- **Memory degrades silently.** The agent's last understanding of "current state" is whatever it last saw — which may be days stale, contradicted by recent work, or based on a decision that's since been reversed.
- **Drift compounds.** Small misalignments between *what you said you'd do* and *what you actually did* become large ones if nothing surfaces them.
- **Decision rationale evaporates.** Six weeks from now, "we picked X" is in git history but the *why* — the rejected alternatives, the constraint that drove the choice — is gone.
- **The agent grows stale identity.** Preferences you stated months ago either still apply (and shouldn't be re-asked) or have evolved (and shouldn't still be in force). Without periodic review, both failure modes feed on each other.

A heartbeat addresses all four. It's the discipline of *deliberate re-anchoring* on a schedule, instead of hoping the right memory surfaces when needed.

---

## Cadences

Different problems need different beats. Use what fits the work:

### Per-prompt (lightest)

- Auto-recall from memory layer (e.g., engram, user-modeling layer) injected at prompt-submit time
- Freshness gates that detect stale recall and re-fetch
- Triggered hooks that surface time-due reminders (the `clayworks-lite-nudge` skill is one example)

**LITE scaffolding:** `hooks/examples/userpromptsubmit.sh` is the contract reference for this cadence — payload shape, common patterns, exit behavior. The Nudge skill ships a working consumer of that contract.

**Good for:** keeping context fresh without per-prompt overhead the user feels.

### Per-turn (Stop hook)

- Observability grading: did this turn meet expectations? What scored low?
- Drift checks: did the agent honor explicit rules from CLAUDE.md / memory?
- Structural integrity checks: do referenced files still exist? Have hooks been parsing cleanly?

**LITE scaffolding:** `hooks/examples/stop.sh` is the contract reference — payload shape, the gated 24h trigger pattern, and how to spawn background work without blocking CC's exit.

**Good for:** catching regressions and silent failures before they accumulate.

### End-of-session

- Summarize what happened in the session: goal, discoveries, accomplished, next steps, relevant files
- Persist the summary to memory so the next session inherits context cleanly
- Optional: write a hand-off doc if context-window saturation is approaching

**LITE scaffolding:** `hooks/examples/sessionend.sh` is the contract reference for the evening tail. Pair with `hooks/examples/sessionstart.sh` for the session-open counterpart that surfaces unfinished threads at the next session's open — the closest CC-native approximation of a morning beat.

**Good for:** clean session boundaries. Single highest-impact cadence if you only have time for one.

### Daily

- **Morning beat:** read recent state, surface unfinished threads, set the day's focus
- **Evening beat:** consolidate the day, prune stale items, write back updated state, surface anything that needs human decision before tomorrow

**LITE scaffolding:** Daily beats run outside CC's hook lifecycle — schedule via cron (macOS/Linux) or Task Scheduler (Windows). For session-coupled approximations (fire on session open/close instead of fixed clock time), see `hooks/examples/sessionstart.sh` and `hooks/examples/sessionend.sh`. Weekly and monthly beats are also out-of-CC; same scheduler options apply.

**Good for:** turning the agent into something between a journal and an operations runner. The daily pair is where most users feel the biggest leverage.

### Weekly

- Review patterns across the week: what recurred? What surprised you? What changed in priorities?
- Promote recurring behaviors into rules (e.g., "I keep correcting Claude on X — write it into CLAUDE.md")
- Prune stale entries from memory, agent identity files, project NOW lists

**Good for:** pattern recognition and rule promotion. Stops CLAUDE.md drift.

### Monthly

- Identity-level review: working style, role, preferences, north-star priorities
- Update user-modeling layer (Honcho or equivalent) with what's actually true now
- Sunset behaviors that no longer match the work

**Good for:** preventing the agent's "model of you" from going stale as your life evolves.

---

## Minimum-viable heartbeat

You don't need three tiers, a trust ledger, or telemetry to start. Begin with:

**One file:** `~/agent/STATE.md` (or wherever you keep "what's current"). Plain markdown.

**One discipline:** at the end of each working session, run a three-step prompt:

1. Read `~/agent/STATE.md`
2. Describe what changed in this session vs. what's in the file
3. Write the updated file with today's date and the new state

That's it. Three lines, one file, no plugins. The pattern works.

When the discipline holds: add a morning beat (read STATE.md → set focus for the day) before opening any project. Then a weekly beat (review past 7 days of STATE.md history → prune + promote rules). Each addition compounds.

---

## Anti-patterns

What NOT to make a heartbeat do:

- **Observation without reflection.** A heartbeat that just appends raw logs and never synthesizes is telemetry, not heartbeat. Useful, but a different artifact.
- **Reflection without update.** If the reflection only lives in the conversation, it dies with the session. The "update" step is what makes it survive.
- **Heartbeat racing the work.** A daily beat that takes 40 minutes defeats the purpose. Bound the beat: 20 minutes for thinking + 5 minutes for writing, hard cap. If you can't say it in 5 minutes of writing, your reflection is the wrong shape.
- **Heartbeat without thresholds.** "Score: 7/10" means nothing without a baseline. Track means + standard deviations so you can distinguish normal variance from real drift.
- **Heartbeat replacing actual work.** If you spend more time observing the agent than working with it, you've built a self-watching machine, not an operator. The beat exists to *enable* the work, not to *replace* it.
- **Beating on the wrong axis.** A daily beat for something that changes weekly produces noise. A weekly beat for something that changes hourly produces stale signal. Match cadence to the rate-of-change of the thing being observed.

---

## Production implementation — paid bundle

LITE ships this concept doc; the full production heartbeat system is in the paid **Clayworks** bundle:

- **Three-tier observability stack** — per-prompt outcomes grading (lightweight, sampled), end-of-session structural integrity check (catches reference rot, hook parse errors, log staleness), end-of-session memory consolidation candidate (proposes new memory entries for explicit human approval).
- **Daily-cycle templates** — full prompts for morning briefing, evening consolidation, weekly review, monthly identity review. Each is a structured prompt with the right read-context + the right reflection questions + the right write-back format.
- **Trust ledger schema** — append-only JSON with caps, per-tier summary aggregation, designed for SPC-style streak analysis if you want it.
- **Drift signaling** — per-tier P0/P1/P2 findings routed to notification channels (Telegram, system tray) with frequency throttling so you only see real signal.
- **Heartbeat-aware skills** — composes with the rest of the paid bundle (CC↔CC comms surfaces inter-session disagreements, inbox watcher catches dropped artifacts, freshness gate injects fresh CC docs when relevant).

You can build all of this yourself from the pattern above. The bundle ships *one* version of it that's been hardened over months of daily use.

---

## When to invoke this skill

Trigger conditions:

- User mentions "heartbeat", "cadence", "reflection cycle", "morning beat", "evening consolidation", "weekly review"
- User asks how to make CC reflect on its own state between sessions
- User asks about drift detection, self-observation, or agent telemetry patterns
- User asks how to start a daily / weekly review discipline with their agent
- User describes a problem this pattern would solve ("Claude keeps forgetting decisions from last week", "I never know what state things are in", "my CLAUDE.md is full of rules nobody honors anymore")
- User asks what's in the paid bundle vs. what's in LITE around observability

---

## Related

- **`clayworks-lite-nudge`** — provides the cadence-trigger mechanism (time-based pings via UserPromptSubmit hook). A morning beat scheduled via Nudge fires reliably without depending on the user remembering.
- **`clayworks-lite-memory-routing`** — the heartbeat's "update" step has to write *somewhere*. Routing decides which memory layer absorbs each piece of consolidated state.

The three LITE skills compose: routing answers *where state goes*, Nudge answers *when the beat fires*, heartbeat-concept answers *what the beat does*.
