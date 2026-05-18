# Clayworks LITE

> The Claude Code operator scaffolding I built for my own work, now open-sourced.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Claude Code 2.1.x](https://img.shields.io/badge/Claude%20Code-2.1.x-blue)](https://docs.claude.com/en/docs/claude-code)
[![Status: v1](https://img.shields.io/badge/status-v1-green)](https://github.com/clayboicardi/clayworks-lite)
[![No telemetry](https://img.shields.io/badge/telemetry-none-brightgreen)](#no-telemetry)

---

## What this is

Claude Code is small at install. Out of the box you get a model that can read your code, edit files, and run commands. That's the engine. It is not yet a production system.

The production version of Claude Code — the one that remembers across sessions, surfaces fresh docs when you ask about libraries, structures your CLAUDE.md so the model actually behaves consistently, and includes the hook scaffolding to extend any of it — takes weeks of configuration work to assemble from scratch.

I did that work for my own operator system. This LITE kit is the minimum competent baseline distilled out of it: enough to feel the difference, free under MIT, no commitment.

The full production stack lives in **Clayworks** — the paid bundle, launching alongside this kit. See the "Upgrade path" section below.

---

## What it solves

If you've used Claude Code seriously for more than a few sessions, you've hit these:

- **Memory amnesia.** Every session starts at zero. Decisions you made yesterday don't surface today.
- **CLAUDE.md drift.** The file grows organically until it's incoherent, contradicting itself, or stuffed with rules the model ignores.
- **Library doc staleness.** The model writes code against APIs that no longer exist because its training data is older than the library's current version.
- **No structure for repeatable workflows.** Every nontrivial task gets re-explained from scratch.
- **No notification path.** Long-running operations finish silently while you're in another window.

LITE addresses the first three directly and gives you the structural scaffolding for the rest. The paid bundle goes the full distance.

---

## Who it's for

**Yes, for you:** You're using Claude Code for real work. You've already hit the friction above. You're comfortable in a shell and have opinions about your tooling. You want a sharper edge, not a wizard.

**Probably not for you:** You're just starting with Claude Code and want the simplest possible experience. Use CC stock for a few weeks first; come back when you feel the gaps.

**Definitely not for you:** You're looking for a no-code "AI assistant builder" or a low-effort productivity app. Clayworks is operator scaffolding for technical users.

---

## What's in LITE

Seven components. Each is opinionated and minimal.

### 1. CLAUDE.md starter template

[`templates/CLAUDE.md.clayworks-template`](templates/CLAUDE.md.clayworks-template) — an anonymized version of the `CLAUDE.md` I run in production, with structure preserved and contents replaced by example rules. Drop it in, customize per-section, ship.

The structure encodes a specific philosophy: identity rules first, behavioral rules second, tool routing third, project-specific context last. Section ordering matters — the model reads top-to-bottom and weights early rules more heavily. The template's section ordering is the lesson.

### 2. Multi-memory routing decision tree

[`skills/clayworks-lite-memory-routing/SKILL.md`](skills/clayworks-lite-memory-routing/SKILL.md) — a standalone skill that helps you decide which memory layer to use for a given fact:

- **Engram** for procedural decisions, conventions, cross-model retrievability
- **Honcho** (or your user-modeling layer of choice) for *who you are* — preferences, style, role
- **Native `~/.claude/projects/<project>/memory/MEMORY.md`** for project-specific facts

If you don't have all three, the skill still works — it'll route everything to whichever layer you have. The point is that "where does this belong?" is a decision, not a hunch.

### 3. Nudge install pattern

[`skills/clayworks-lite-nudge/`](skills/clayworks-lite-nudge/SKILL.md) — a SQLite-backed reminder system that surfaces time-based pings via a UserPromptSubmit hook. Use cases:

- "Stop me at 5pm" — model gets the nudge when due
- "Remind me about the standup at 9:55" — surfaces at submit time
- "Wrap up debugging if you're still on it in 30 minutes"

Three small Python scripts (`add_alert.py`, `ack_alert.py`, `check_alerts.py`) plus the skill that drives them. Not flashy, genuinely useful.

### 4. Hook scaffolding examples

[`hooks/examples/`](hooks/examples/README.md) — a minimal `.sh` example for each Claude Code hook event (UserPromptSubmit, Stop, PreToolUse, SessionStart, SessionEnd, etc.). Each one is annotated with the event's contract, the JSON payload shape, and one common pattern. You'll modify these heavily; they exist so you don't start from a blank file.

### 5. Heartbeat framework concept doc

[`skills/clayworks-lite-heartbeat-concept/SKILL.md`](skills/clayworks-lite-heartbeat-concept/SKILL.md) — a written explanation of the heartbeat pattern I use to keep my agent reflecting on its own state and surfacing decisions on a regular cadence. **Concept only, not implementation** — the full heartbeat system ships in the paid bundle because the generic refactoring is real work I haven't finished. The concept doc is enough to roll your own if you want.

### 6. Worked examples

[`examples/`](examples/) — two complete LITE configurations (minimal + full) ready to adapt. Shows what the kit looks like assembled instead of as parts: `settings.json` for two adoption levels, customized hook scripts, and a sample CLAUDE.md based on the template. See [`examples/README.md`](examples/README.md) for the adoption pattern.

### 7. This README + install scripts

The walkthrough you're reading + a Bash/PowerShell installer that drops the right files into the right places without clobbering anything.

---

## What's NOT in LITE

LITE is honest about what it isn't. The following live in the paid **Clayworks** bundle, not here:

- **Annotated production CLAUDE.md** — every rule with rationale, not just structure
- **CC↔CC inter-session communication system** — when you run two CC sessions in parallel, they coordinate via filesystem messaging + Telegram routing
- **Full three-tier observability stack** — three layers of self-evaluation (per-prompt outcomes, end-of-session structure check, end-of-session memory consolidation candidate)
- **Multi-AI bridges** — wired Gemini CLI + local Ollama integrations with logging, sandboxing, and fallback handling
- **CC docs freshness gate** — a UserPromptSubmit hook that detects Claude Code-related questions and injects fresh local mirror context so the model doesn't fall back to stale training-data recall
- **Inbox watcher pattern** — drop a markdown file in a folder, the agent picks it up on next session start
- **Multi-node sync docs** — running CC across a primary machine + secondary machines with consistent state
- **Morning briefing / evening consolidation / weekly review / reflection beat templates** — structured daily-cycle prompts that turn CC into something between a journal and an operations runner
- **Telegram integration** — proactive notifications + remote control over your CC instance from your phone
- **Settings.example.json + per-key rationale** — the env vars, hooks, permissions, plugin set, and marketplaces I run in production
- **Plugin baseline doc (full 23-plugin operator stack, rationale per plugin)** — LITE names a few plugins in passing (Engram, Honcho, Octo); the paid doc covers all 23 with the why for each addition
- **Operating Claude Code at production quality** — a 15-30 page written guide covering the operator discipline that holds the system together
- **Install guide + troubleshooting field guide**

If your reaction to the LITE contents is *"I want the rest of this"* — that's the bundle.

---

## Prerequisites

- **Claude Code 2.1.x or newer** — earlier versions are missing hook events LITE depends on
- **A shell** — Bash on macOS/Linux, PowerShell 5.1+ or Git Bash on Windows
- **Git** — for cloning the repo (`git clone https://...`)
- **A `~/.claude/` directory** — created by Claude Code on first run; if you've never run CC, install it first
- **(Optional) Python 3.10+** — required only for the Nudge skill and for the hook examples that parse JSON payloads. The scripts invoke `python3` by name; if your system only provides `python`, symlink or alias as needed.
- **(Optional) [Engram plugin](https://github.com/Gentleman-Programming/engram)** — if you want the multi-memory routing skill to actually route to a memory layer rather than just describing what it would route to. Engram is free and installs in CC via:

  ```text
  /plugin marketplace add Gentleman-Programming/engram
  /plugin install engram@engram
  ```

LITE itself is shell scripts + markdown. No build, no compile, no Docker.

---

## Install

Before running, glance at `install.sh` (or `install.ps1`) to satisfy yourself there's nothing surprising in it. The installer is ~600 lines and does what the comments say — `--dry-run` to see exactly what would change without writing anything.

```bash
# Clone the repo somewhere out of the way
git clone https://github.com/clayboicardi/clayworks-lite.git ~/clayworks-lite

# Run the installer
cd ~/clayworks-lite
./install.sh        # macOS / Linux / Git Bash
# OR
.\install.ps1       # Windows PowerShell 5.1+ (pwsh or powershell.exe)
```

The installer:

1. **Backs up** anything it's about to overwrite to `~/.claude/.clayworks-lite-backup/<timestamp>/`
2. Copies the LITE skills into `~/.claude/skills/`
3. Copies the hook scaffolding examples into `~/.claude/hooks/examples/` (NOT into the live hooks dir — you opt-in by referencing them in `settings.json`)
4. Copies the CLAUDE.md template to `~/.claude/CLAUDE.md.clayworks-template` (NOT `CLAUDE.md` — your existing file is sacred)
5. Copies a `settings.example.json` to `~/.claude/settings.example.json` (NOT `settings.json` — same reason) showing the LITE-recommended hook composition
6. Prints a summary of what changed and what to do next

The installer is idempotent. Re-running it picks up new versions without re-clobbering your edits, as long as you've moved files out of the `clayworks-lite/` source dir (e.g., your customized `CLAUDE.md` lives at `~/.claude/CLAUDE.md`, not in the source).

### Updating LITE

To pick up a new release, pull and re-run the installer:

```bash
cd ~/clayworks-lite && git pull && ./install.sh
```

The hash-diff logic means unchanged files skip; only new or modified items get backed up + reinstalled. Your customized `~/.claude/CLAUDE.md` and live `~/.claude/hooks/` files are never touched.

### Verifying the install

Sanity-check that the install is healthy:

```bash
./install.sh --verify        # macOS / Linux / Git Bash
# OR
.\install.ps1 -Verify        # Windows PowerShell 5.1+
```

Checks: skills present + frontmatter parses, hook examples present + shebangs intact, `python3` + `sqlite3` available (required for the Nudge skill), CLAUDE.md template + `settings.example.json` present and well-formed, best-effort `claude` CLI version detection. Exits 0 on all-pass, 1 on any failure, with per-check detail.

### Uninstalling LITE

To remove what LITE installed:

```bash
./install.sh --uninstall     # macOS / Linux / Git Bash
# OR
.\install.ps1 -Uninstall     # Windows PowerShell 5.1+
```

The uninstaller removes only files that match what LITE shipped (compared by SHA-256 hash). Any file you've customized is left in place — your edits aren't silently lost. Your live `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, and `~/.claude/hooks/` directory are never touched. The backup folder (`~/.claude/.clayworks-lite-backup/`) is preserved; remove it manually if you want a clean slate.

If you wired Nudge or other LITE hooks into `~/.claude/settings.json`, you'll need to remove those entries yourself — the uninstaller doesn't edit your settings file.

### No telemetry

LITE is shell scripts + markdown + three Python scripts. No analytics, no phone-home, no usage tracking. The installer touches only paths under `~/.claude/` (configurable via `--claude-dir`). The Nudge SQLite database stays on your machine and is gitignored.

### Verify the install

```bash
# Restart Claude Code (close all sessions, start a new one)
# Then in a new session:
ls ~/.claude/skills/clayworks-lite-*/
```

You should see three skill directories: `clayworks-lite-nudge`, `clayworks-lite-memory-routing`, `clayworks-lite-heartbeat-concept`. The `clayworks-lite-` prefix is intentional — it keeps these distinguishable from your own skills.

The installer also dropped a starter `CLAUDE.md` template at `~/.claude/CLAUDE.md.clayworks-template`. To adopt it as your live `CLAUDE.md`, back up any existing one first and copy:

```bash
cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.bak 2>/dev/null || true
cp ~/.claude/CLAUDE.md.clayworks-template ~/.claude/CLAUDE.md
# Then edit ~/.claude/CLAUDE.md and replace <YOUR ...> placeholders
```

In your next CC session, try the Nudge skill in plain English — it auto-triggers on time references; no slash command needed:

> stop me at 5pm to wrap up

Claude picks up the trigger, runs the Nudge skill, and stores the alert in a local SQLite store. That confirms the skill is loaded.

### Make the Nudge skill actually fire (one extra step)

The skill *registers* alerts; for them to actually *fire* at the due time, the included `check_alerts.py` needs to run on each prompt submission. Wire it once in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/skills/clayworks-lite-nudge/scripts/check_alerts.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

If you already have `UserPromptSubmit` hooks, append this command to the existing `hooks` array — don't replace the block. See [`skills/clayworks-lite-nudge/SKILL.md`](skills/clayworks-lite-nudge/SKILL.md) for the full Nudge surface (time formats, message format, dismissal, schema).

---

## Upgrade path to the paid bundle

If LITE delivers on its promise — you feel the structural difference, you want the rest — the paid Clayworks bundle is the next step.

**What you get:**

- All of the items listed in "What's NOT in LITE" above
- The 15-30 page "Operating Claude Code at production quality" written guide
- Install guide + troubleshooting field guide
- Annotated production CLAUDE.md (every rule with the why)
- Curated plugin baseline doc for the full 23-plugin operator stack
- Update access for v1.x patches

**Pricing:**

- **Early adopter (first 30 days):** $49
- **Standard:** $79
- Optional sprint-tier service offerings (install acceleration $499 / full custom setup $1,500) and monthly retainer ($399/mo) for teams that want the bundle deployed to their environment rather than self-installing.

Checkout link forthcoming on launch — watch this repo or the [Clayworks landing page](https://clayboicardi.com) (coming soon) for the buy URL.

---

## License

LITE ships under the **MIT License**. You can use it commercially, modify it, redistribute it, sublicense it. The only requirement is preserving the copyright notice.

The MIT choice is deliberate: this is operator scaffolding, not a moat. If LITE is useful for your work, take it.

---

## Who built this

I'm **[@clayboicardi](https://github.com/clayboicardi)** on GitHub. I'm a technical operator who learned most of my stack autodidactically over the last several years. I've built:

- **[HarmonoidWidget](https://github.com/clayboicardi/HarmonoidWidget)** — Android home-screen widget for the Harmonoid music player (Kotlin, MediaSession integration)
- **[JAMZ](https://github.com/clayboicardi/JAMZ)** — Fork of the [Gramophone](https://github.com/FoedusProgramme/Gramophone) Android music player with custom branding + UI changes (Kotlin, Material Design)
- The internal operator system this kit and the paid bundle distill from — built over several years of daily Claude Code use

I run this stack every day on my own machine. It's not a thought experiment. It's the system I actually use.

For service inquiries (sprint installs, custom setups, team retainers), open a GitHub issue here. A dedicated intake form on the Clayworks landing page is coming soon.

---

## Design rationale

[`docs/`](docs/) carries the **why** behind LITE's design choices. The SKILL.md files and main README cover what the kit does; `docs/` covers why specific decisions were made and what was rejected:

- [`docs/why-claude-md-structure-matters.md`](docs/why-claude-md-structure-matters.md) — section ordering as load-bearing design
- [`docs/memory-routing-rationale.md`](docs/memory-routing-rationale.md) — why three layers, why a routing skill
- [`docs/heartbeat-design.md`](docs/heartbeat-design.md) — pattern vs. implementation, why bounded time budgets, why these cadences
- [`docs/installer-design.md`](docs/installer-design.md) — backup-then-install, hash-diff, symlink rejection, no-auto-edit-of-settings.json
- [`docs/upgrade-philosophy.md`](docs/upgrade-philosophy.md) — the principles separating LITE from the paid bundle

Skim if you're evaluating LITE against alternatives, customizing a component and want to know if your change crosses the design grain, or considering contributing a change to the design rather than just an addition.

## Contributing

Issues and pull requests welcome. Specifically appreciated:

- **Bug reports** — `install.sh` / `install.ps1` failures on specific OS/shell combinations
- **Hook scaffolding additions** — minimal examples for hook events I haven't covered
- **Memory-routing decision-tree refinements** — edge cases where the skill's logic could be sharper
- **Documentation improvements** — typos, clarifications, ambiguities

Not specifically appreciated:

- "Add my favorite plugin to the baseline" — the LITE baseline is intentionally small (6 plugins); the paid bundle covers the larger curated set
- "Make this work with [non-CC tool]" — Clayworks LITE is specifically for Claude Code, not generic agent infra

Issues: [github.com/clayboicardi/clayworks-lite/issues](https://github.com/clayboicardi/clayworks-lite/issues)

---

## Acknowledgments

The pattern of organizing CC operations around persistent memory, structured hooks, and multi-AI orchestration didn't emerge in isolation. Tools and people whose work informed mine:

- **[Anthropic](https://anthropic.com)** — Claude Code itself, plus the [superpowers](https://github.com/anthropics/claude-plugins-official) skill collection (in `claude-plugins-official`) that anchors a lot of LITE's structural assumptions
- **[Plastic Labs](https://plasticlabs.ai)** — Honcho, the user-modeling layer that taught me to separate "facts about the project" from "facts about the user"
- **[nyldn / claude-octopus](https://github.com/nyldn/claude-octopus)** — Octo multi-AI orchestration plugin; the bundle's multi-AI routing pattern compounds with it nicely
- **[Gentleman-Programming / engram](https://github.com/Gentleman-Programming/engram)** — Engram persistent memory plugin
- **The awesome-claude-code curators** — [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code), [rohitg00/awesome-claude-code-toolkit](https://github.com/rohitg00/awesome-claude-code-toolkit), [ComposioHQ/awesome-claude-plugins](https://github.com/ComposioHQ/awesome-claude-plugins) — whose maintained lists mapped the CC plugin/skill ecosystem and made it possible to see what's table-stakes vs. what's distinctive
- The other operator-setup-publishers in the CC ecosystem whose published rigs informed what LITE intentionally does and doesn't ship
- The Claude Code community on Discord and GitHub for the steady flow of patterns, edge cases, and pushback that sharpens this kind of work

---

*Clayworks LITE v1. The paid bundle launches alongside.*
