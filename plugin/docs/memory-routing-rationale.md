# Memory routing: design rationale

The `clayworks-lite-memory-routing` skill ships a four-question decision tree across three layers (Engram, native CC `MEMORY.md`, Honcho). This doc explains why three layers, why a routing decision is needed at all, and what was rejected.

## The core observation

Memory in an AI agent isn't one thing. The literature treats it as one, but in practice there are at least three distinct *kinds* of memory an operator needs, each with different access patterns:

| Kind | Access pattern | Examples |
|---|---|---|
| **Project-scoped facts** | Auto-load when working on this project | Build commands, file conventions, recent decisions |
| **Cross-project procedural** | Exact keyword search across all work | Tool configs, architecture patterns, bug-fix recipes |
| **User-modeling** | Continuous representation refinement | Working style, preferences, identity facts |

Putting all three in one store works *badly*: project-scoped facts pollute global search; cross-project procedures don't auto-load when relevant; user-model preferences get re-stated every session because there's no continuous representation.

LITE's routing skill treats this as a real distinction and provides a decision tree.

## Why three layers, not one

**One-layer alternative (Engram only).** Save everything to Engram. Namespace via topic keys: `project-x/build`, `user-profile/style`, `decisions/...`. Workable. Loses auto-load (Engram doesn't auto-load on session start by default; you have to `mem_search`). Loses Honcho's dialectical refinement of user model over time. Acceptable for users who only want one tool; LITE supports this in the "If you only have one layer" section of the skill.

**One-layer alternative (native MEMORY.md only).** Project-scoped only. Works for project work but breaks the moment you want a fact from one project to surface in another. Forces re-entry of cross-project knowledge every time you change projects. Recommended *against* in the skill, but supported as a degraded mode.

**One-layer alternative (Honcho only).** Unusual. Honcho's strength is user modeling; using it for project facts or procedural knowledge fights its grain. Skill marks this as the least-recommended fallback.

**Why the three-layer model:** each layer is *better* at one kind of memory than the others. Forcing one to do all three's job is worse than picking the right one per fact.

## Why a routing decision skill (not just docs)

Users could read the layer descriptions and decide for themselves where to save each fact. Why ship a skill that auto-fires on save-events?

**Because the decision happens at write time, not read time, and write-time is when humans are tired.** A user who's just hit a "this took me 3 hours to figure out" insight is going to save it to wherever is in their muscle memory. Without active routing, that's wherever they used last. With the skill, the decision tree fires automatically and the user gets a quick "where does this belong?" prompt that takes 5 seconds to answer.

The cost is one extra micro-decision per save. The benefit is layers stay coherent over time. The author has run this discipline for many months on his personal setup; the layers stay clean. Without the discipline, they drift.

## The four-question tree, briefly

1. **Is this about WHO the user is?** → Honcho
2. **Is this scoped to one project?** → native `MEMORY.md` in that project's dir
3. **Is this cross-project / procedural / searchable?** → Engram
4. **None of the above?** → Engram (default; broadest retrieval, lowest mis-filing risk)

Each question is binary, terminating, and answers from the user's natural language without forcing them to think in storage-layer abstractions. Question 1 asks about content type, not layer type. Question 4 ensures the tree terminates even on edge cases.

## Alternatives considered

**Auto-classify with an LLM.** Could send the fact to a classifier model and route automatically. Rejected because (a) adds a network/compute hop on every save, (b) classifiers are wrong ~10% of the time and wrong classifications produce permanent mis-filings, (c) the human's intuition about what kind of fact they just had is usually better than a classifier's read.

**Single decision question instead of four.** "Where does this belong?" with three buttons. Rejected because the choice isn't memorable without the decision tree. Users who haven't internalized the layers will guess. The four-question tree IS the user's mental model formation.

**More than four questions.** Tempting (project subdirectories, urgency, age, etc.). Rejected because past four questions, users stop running the tree at all.

**Different layer set (e.g. add a "todo" layer).** Considered. Todos are a different artifact (they have a state machine, pending → done, that memory doesn't). LITE's Nudge skill handles time-based reminders; a longer-form "what I have to do" layer would be a separate concern. Out of scope for v1; not ruled out for future.

## The "your user-modeling layer of choice" framing

Honcho is named in the skill, but the skill explicitly says (line 57):

> Honcho is one user-modeling layer; not the only one. If you use a different system (a hand-maintained `USER.md`, a separate vector store, a custom service), the routing principles still apply. Honcho's slot in the decision tree is just "your user-modeling layer of choice."

This is intentional plugin-agnosticism. The routing principles are about *kinds* of memory, not specific products. Users who have built or adopted other user-modeling layers can slot them in. Users with no user-modeling layer at all get a graceful degradation path (fall back to Engram with `user-profile/...` topic keys).

The framing was a deliberate design choice during the audit. Earlier drafts named Honcho more authoritatively; the audit-time read was that this overcommitted to a specific vendor when the principle is broader.

## Trade-offs accepted

- **Cognitive overhead.** Four-question tree per save. Faster than re-deriving the answer each time, slower than no decision. Net positive over many months; net negative if you only have a few dozen memory entries total.
- **Layer drift even with discipline.** Some facts straddle categories (a project-specific build command that turns out to apply across projects months later). The skill's quarterly-maintenance note exists because no decision tree is perfect.
- **Plugin proliferation.** Three layers means three plugins to install (well, two; native MEMORY.md is built-in). User reaction: "why so many?" Reality: one binary memory and one no-tool-needed-MEMORY-md is the minimum for the distinction to matter.

## When this design would be wrong

- **You only save 5-10 things per week.** The decision tree's overhead isn't worth it. Save everything to one place; you'll remember where it is.
- **You don't want a user-modeling layer.** Skip Honcho. The routing skill explicitly supports this. Fall through to Engram with `user-profile/...` namespace.
- **You work alone on one project for years.** Native MEMORY.md alone is fine. The cross-project advantage of Engram only matters if you actually have cross-project work.

## What this doc is NOT

- **Not the SKILL.md** — `skills/clayworks-lite-memory-routing/SKILL.md` carries the decision tree itself + 11 worked examples. This doc explains why the tree has the shape it does.
- **Not a comparison of memory plugins** — Engram, Honcho, and native MEMORY.md are mentioned because they're what LITE ships with. Other memory plugins exist; their slot-in-the-tree depends on their access patterns, not their feature lists.
