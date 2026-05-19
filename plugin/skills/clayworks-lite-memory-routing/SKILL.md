---
name: clayworks-lite-memory-routing
description: Pick the right memory layer when saving a fact across Engram (cross-model structured/procedural), native Claude Code MEMORY.md (project-scoped), or Honcho (user modeling). Use when the user says "remember/save/store this", states a preference or identity fact, describes a project convention or build command, or when Claude is about to write to memory and the destination isn't obvious. This skill is a routing decision tree, not a memory implementation. The underlying plugins handle storage.
---

# Clayworks LITE: Multi-memory routing

You have up to three memory layers. Each is good at different things. Picking the right one isn't a hunch. It's a decision that follows from what the fact IS.

The point is the *decision*, not the *destination*. Even if you only have one layer installed, deciding deliberately keeps that layer's contents coherent.

## The three layers

### Engram: cross-model structured memory

**Install** (free, runs locally):

```text
/plugin marketplace add Gentleman-Programming/engram
/plugin install engram@engram
```

**Use for:**

- Architecture decisions (with the *why*, not just the *what*)
- Project conventions (naming, structure, tooling choices)
- Bug fixes worth surfacing later (include the root cause)
- Recurring procedures (build commands, deploy steps, recovery playbooks)
- Anything that needs exact keyword search
- Anything that should be reachable from non-Claude tools (Gemini CLI, Codex, etc.)

**Key trait:** topic-keyed, searchable, cross-model accessible. Survives compaction and session boundaries. Save with `mem_save`; retrieve with `mem_search`.

### Native Claude Code memory (`MEMORY.md`)

**Install:** built into Claude Code. No plugin needed.

**Path:** `~/.claude/projects/<project-name>/memory/MEMORY.md`

**Use for:**

- Project-specific facts that live with the codebase
- Build commands and quirks specific to one project
- Recent decisions affecting current work in that project
- Anything the auto-loader should surface at session start for the matching project

**Key trait:** auto-loaded into context on session start when CC is invoked from inside that project directory. Free. No plugin needed. Plain markdown — edit directly with your favorite editor.

### Honcho: user modeling

**Install** (cloud-hosted; $100 free credits then ~$2–3/mo at typical usage):

```text
/plugin marketplace add plastic-labs/claude-honcho
/plugin install honcho@honcho
```

**Use for:**

- WHO the user is: role, occupation, identity facts
- Working-style preferences (terse vs. verbose, push-back tolerance, formatting taste)
- Long-term behavioral traits and patterns
- Anything that should color *how* Claude talks to the user, not just *what facts* it knows

**Key trait:** dialectical model that builds a persistent representation of the user across sessions. Auto-loaded as a profile at session start. Save with `create_conclusion`.

**Alternative:** Honcho is one user-modeling layer; not the only one. If you use a different system (a hand-maintained `USER.md`, a separate vector store, a custom service), the routing principles still apply. Honcho's slot in the decision tree is just "your user-modeling layer of choice."

---

## Routing decision tree

Ask these questions in order. Stop at the first YES.

**1. Is this a fact about WHO the user is: their role, working style, preferences, or behavioral patterns?**
→ **Honcho.** (If Honcho isn't installed, fall through to Engram and tag with `user-profile/...`.)

**2. Is this fact specific to one project: a build command, file convention, or recent decision affecting only that codebase?**
→ **Native `MEMORY.md`** in that project's memory directory.

**3. Is this a cross-project decision, a tool config, a procedure, a bug-fix root cause, or something that should be searchable from multiple AI tools?**
→ **Engram.**

**4. None of the above clearly fit?**
→ **Engram.** Broadest retrieval, lowest risk of misfiling. Add a clear topic key so it stays discoverable.

---

## Examples

| Fact | Layer | Why |
|---|---|---|
| "User is a backend engineer at a fintech startup" | Honcho | WHO they are |
| "User prefers terse responses, no closing pleasantries" | Honcho | Working style |
| "User won't approve destructive operations without a written backup confirmation" | Honcho | Behavioral guardrail |
| "Project X builds with `./gradlew :app:assembleDebug` using JDK 21" | `MEMORY.md` (Project X) | Project-specific build command |
| "Project X uses `applicationId com.foo.app.debug` for debug builds" | `MEMORY.md` (Project X) | Project-specific config |
| "Use the Bash tool (not PowerShell) for cross-platform scripts" | Engram | Tool convention across projects |
| "Bug: API X's bulk endpoint silently drops fields > 1KB" | Engram | Reusable discovery, cross-project |
| "Pattern: backup-then-install + SHA-256 hash-diff for idempotent installers" | Engram | Cross-project architecture pattern |
| "DocuSeal free tier doesn't support conditional logic" | Engram | Cross-project tool limitation |
| "User is allergic to peanuts" | Honcho | Identity fact, persistent across sessions |
| "Standup is at 09:30 daily" | Probably neither: this is a recurring event; use a calendar or the Nudge skill instead | Memory is for facts, not schedules |

---

## If you only have one layer

The skill works degraded. Use what's available:

- **Engram only.** Save everything there. Namespace topic keys so categories stay separate: `user-profile/role`, `user-profile/style`, `project-x/build`, `decisions/architecture/idempotent-installers`.
- **Native `MEMORY.md` only.** Save everything in the active project's `MEMORY.md`. Add a `## User Profile` section near the top for WHO-the-user-is facts so they load with the file.
- **Honcho only.** Unusual configuration, but workable. Save preferences and identity facts there; rely on conversation context (re-stated each session) for procedural and project facts. Engram is recommended in this case.

---

## What this skill is NOT

- **Not a memory implementation.** Engram, native CC memory, and Honcho are separate plugins/systems. This skill just helps pick the right one.
- **Not a substitute for the underlying plugin docs.** `mem_save` syntax, `create_conclusion` parameters, and native MEMORY.md formatting are documented in their respective sources. Read those when you're actually saving.
- **Not opinionated about which layers you install.** Install all three, install one, install something else entirely. The routing principles transfer. Destinations change; the decision doesn't.

---

## When to invoke this skill

Trigger conditions:

- User mentions saving: *"save this for later"*, *"remember that X"*, *"store this preference"*
- User states a preference, working style, or identity fact (even casually)
- User describes a project convention, build command, or recent project-specific decision
- User describes a cross-project pattern, architecture decision, or bug-fix root cause
- Claude is about to call `mem_save`, write to `MEMORY.md`, or call `create_conclusion` and the destination isn't obvious
- User asks "where should this go?" or "what memory system is this?"

When in doubt: invoke and run through the decision tree once. The 30 seconds it costs now beats the friction of finding a fact in the wrong layer later, or worse, saving it three times across all three layers and then maintaining the divergence.

---

## Maintenance note

The three layers drift apart over time if you don't actively maintain them:

- **Engram** accumulates entries that should have been MEMORY.md (project-scoped facts saved globally) or vice versa
- **Honcho** accumulates conclusions that contradict each other as preferences evolve
- **MEMORY.md** drifts when project conventions change but old entries don't get pruned

Quarterly: skim each layer. Re-route entries that are in the wrong place. Delete entries that no longer reflect reality. The decision tree is most valuable on day one of a new fact, but periodically *re-running* the decision on existing facts catches the drift.
