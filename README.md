<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/clayworks-banner-dark.webp" type="image/webp">
  <source media="(prefers-color-scheme: dark)" srcset="docs/clayworks-banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/clayworks-banner-light.webp" type="image/webp">
  <img src="docs/clayworks-banner-light.png" alt="Clayworks">
</picture>

# Clayworks LITE

> The Claude Code operator scaffolding I built without writing the code. Open-sourced for anyone else doing the same.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Claude Code 2.1.x](https://img.shields.io/badge/Claude%20Code-2.1.x-blue)](https://docs.claude.com/en/docs/claude-code)
[![Release: v1.0.1](https://img.shields.io/badge/release-v1.0.1-green)](https://github.com/clayboicardi/clayworks-lite/releases/tag/v1.0.1)
[![No telemetry](https://img.shields.io/badge/telemetry-none-brightgreen)](#no-telemetry)

---

## What this is

Claude Code is a model that can read files, edit files, and run commands on your machine. It's the engine. Out of the box, it's not yet a production system.

The production version is the one that remembers across sessions, keeps its instructions consistent, surfaces fresh docs when you ask about libraries it doesn't know, and has the scaffolding to extend any of it. It takes weeks of configuration work to assemble.

I did that work for myself, without a coding background. Six months before launching this I didn't know what GitHub was. The system is what let me ship real work anyway. LITE is the minimum competent baseline distilled out of it: enough to feel the difference, free under MIT, no commitment.

The full production stack lives in the paid **Clayworks bundle**, launching alongside this kit. See the "Upgrade path" section below.

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

**For you:** You want to build real things with Claude Code. You don't have to know how to code. Clayworks is built so you can use what you don't fully understand and stay in control of the work. Trust the system.

Most of what LITE installs is shell scripts and config files. Some commands will look unfamiliar at first. That's expected. The system is designed to compensate for what you don't know yet, while you stay in the driver's seat.

**Not for you:** You want a wizard that decides everything for you. You want a "no-code AI assistant" you barely interact with. Clayworks is for people who want to build, not delegate.

---

## What's in LITE

Seven components. Each is opinionated and minimal.

### 1. CLAUDE.md starter template

[`plugin/templates/CLAUDE.md.clayworks-template`](plugin/templates/CLAUDE.md.clayworks-template) — an anonymized version of the `CLAUDE.md` I run in production, with structure preserved and contents replaced by example rules. Drop it in, customize per-section, ship.

The structure encodes a specific philosophy: identity rules first, behavioral rules second, tool routing third, project-specific context last. Section ordering matters. The model reads top-to-bottom and weights early rules more heavily. The template's section ordering is the lesson.

### 2. Multi-memory routing decision tree

[`plugin/skills/clayworks-lite-memory-routing/SKILL.md`](plugin/skills/clayworks-lite-memory-routing/SKILL.md) — a standalone skill that helps you decide which memory layer to use for a given fact:

- **Engram** for procedural decisions, conventions, cross-model retrievability
- **Honcho** (or your user-modeling layer of choice) for *who you are* — preferences, style, role
- **Native `~/.claude/projects/<project>/memory/MEMORY.md`** for project-specific facts

If you don't have all three, the skill still works. It'll route everything to whichever layer you have. The point is that "where does this belong?" is a decision, not a hunch.

### 3. Nudge install pattern

[`plugin/skills/clayworks-lite-nudge/`](plugin/skills/clayworks-lite-nudge/SKILL.md) — a SQLite-backed reminder system that surfaces time-based pings via a UserPromptSubmit hook. Use cases:

- "Stop me at 5pm" — model gets the nudge when due
- "Remind me about the standup at 9:55" — surfaces at submit time
- "Wrap up debugging if you're still on it in 30 minutes"

Three small Python scripts (`add_alert.py`, `ack_alert.py`, `check_alerts.py`) plus the skill that drives them. Not flashy, genuinely useful.

### 4. Hook scaffolding examples

[`plugin/hooks/examples/`](plugin/hooks/examples/README.md) — a minimal `.sh` example for each Claude Code hook event (UserPromptSubmit, Stop, PreToolUse, SessionStart, SessionEnd, etc.). Each one is annotated with the event's contract, the JSON payload shape, and one common pattern. You'll modify these heavily; they exist so you don't start from a blank file.

### 5. Heartbeat framework concept doc

[`plugin/skills/clayworks-lite-heartbeat-concept/SKILL.md`](plugin/skills/clayworks-lite-heartbeat-concept/SKILL.md) — a written explanation of the heartbeat pattern I use to keep my agent reflecting on its own state and surfacing decisions on a regular cadence. **Concept only, not implementation** — the full heartbeat system ships in the paid bundle because the generic refactoring is real work I haven't finished. The concept doc is enough to roll your own if you want.

### 6. Worked examples

[`plugin/examples/`](plugin/examples/) — two complete LITE configurations (minimal + full) ready to adapt. Shows what the kit looks like assembled instead of as parts: `settings.json` for two adoption levels, customized hook scripts, and a sample CLAUDE.md based on the template. See [`plugin/examples/README.md`](plugin/examples/README.md) for the adoption pattern.

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

If your reaction to the LITE contents is *"I want the rest of this"*, that's the bundle.

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

**Before you start:** some of what's below will look unfamiliar if you don't have a coding background. That's expected. You don't need to read every line of every script before running it. Claude Code itself can summarize anything you're unsure about: paste the script into your CC session and ask "what does this do?" If anything reads as surprising or doesn't match what the section says it does, don't run it. Trust the system to walk you through what you're seeing.

**On billing:** Clayworks runs on your existing Claude Pro or Max plan. Pro and Max share their usage limits across claude.ai and Claude Code. No API key needed unless you explicitly set one. If you don't have a Pro or Max subscription yet, get one before installing.

LITE ships **two install paths**. Pick one based on preference. Don't run both, or the skills end up duplicated on disk. Option A is the simpler path if anything below feels foreign; you can always switch to Option B later.

### Option A: Claude Code plugin marketplace (in-CC, no clone)

Inside any Claude Code session:

```text
/plugin marketplace add clayboicardi/clayworks-lite
/plugin install clayworks-lite@clayworks-lite
```

CC clones the kit to `~/.claude/plugins/marketplaces/clayworks-lite/`. The three LITE skills auto-activate. Hook scaffolding examples, the CLAUDE.md template, `settings.example.json`, worked configurations (`examples/`), and design rationale (`docs/`) all ship to disk at that path — present for you (and Claude in a session) to reference, copy, and customize when you decide to. Templates aren't auto-deployed to standard `~/.claude/` paths under this option; you copy them yourself when ready.

### Option B: Git clone + install script (deployed to `~/.claude/`)

Before running, paste `install.sh` (or `install.ps1`) into a Claude Code session and ask it to summarize what the script does. If anything reads as surprising or doesn't match the description below, don't run it. The installer is ~600 lines and does what the comments say. `--dry-run` shows exactly what would change without writing anything.

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
3. Copies the hook scaffolding examples into `~/.claude/hooks/examples/` (NOT into the live hooks dir; you opt-in by referencing them in `settings.json`)
4. Copies the CLAUDE.md template to `~/.claude/CLAUDE.md.clayworks-template` (NOT `CLAUDE.md`; your existing file is sacred)
5. Copies a `settings.example.json` to `~/.claude/settings.example.json` (NOT `settings.json`; same reason) showing the LITE-recommended hook composition
6. Prints a summary of what changed and what to do next

The installer is idempotent. Re-running it picks up new versions without re-clobbering your edits, as long as you've moved files out of the `clayworks-lite/` source dir (e.g., your customized `CLAUDE.md` lives at `~/.claude/CLAUDE.md`, not in the source).

### Which option should I pick?

| If you want... | Pick |
|---|---|
| Quickest start; let CC manage updates; skills auto-active immediately | **Option A** (plugin marketplace) |
| Templates + hook examples deployed to standard `~/.claude/` paths (`~/.claude/CLAUDE.md.clayworks-template`, `~/.claude/hooks/examples/`, etc.) | **Option B** (clone + script) |
| Full uninstall via `--uninstall` flag + automatic backup of any file LITE would overwrite | **Option B** |
| Don't want any LITE files outside `~/.claude/plugins/` | **Option A** |
| Auditing the install before running (read every script first) | **Option B** (the source is local; for **A**, audit at `~/.claude/plugins/marketplaces/clayworks-lite/` after install) |

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

The uninstaller removes only files that match what LITE shipped (compared by SHA-256 hash). Any file you've customized is left in place. Your edits aren't silently lost. Your live `~/.claude/CLAUDE.md`, `~/.claude/settings.json`, and `~/.claude/hooks/` directory are never touched. The backup folder (`~/.claude/.clayworks-lite-backup/`) is preserved; remove it manually if you want a clean slate.

If you wired Nudge or other LITE hooks into `~/.claude/settings.json`, you'll need to remove those entries yourself. The uninstaller doesn't edit your settings file.

### No telemetry

LITE is shell scripts + markdown + three Python scripts. No analytics, no phone-home, no usage tracking. The installer touches only paths under `~/.claude/` (configurable via `--claude-dir`). The Nudge SQLite database stays on your machine and is gitignored.

### Verify the install

```bash
# Restart Claude Code (close all sessions, start a new one)
# Then in a new session:
ls ~/.claude/skills/clayworks-lite-*/
```

You should see three skill directories: `clayworks-lite-nudge`, `clayworks-lite-memory-routing`, `clayworks-lite-heartbeat-concept`. The `clayworks-lite-` prefix is intentional. It keeps these distinguishable from your own skills.

The installer also dropped a starter `CLAUDE.md` template at `~/.claude/CLAUDE.md.clayworks-template`. To adopt it as your live `CLAUDE.md`, back up any existing one first and copy:

```bash
cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.bak 2>/dev/null || true
cp ~/.claude/CLAUDE.md.clayworks-template ~/.claude/CLAUDE.md
# Then edit ~/.claude/CLAUDE.md and replace <YOUR ...> placeholders
```

In your next CC session, try the Nudge skill in plain English. It auto-triggers on time references; no slash command needed:

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

If you already have `UserPromptSubmit` hooks, append this command to the existing `hooks` array. Don't replace the block. See [`plugin/skills/clayworks-lite-nudge/SKILL.md`](plugin/skills/clayworks-lite-nudge/SKILL.md) for the full Nudge surface (time formats, message format, dismissal, schema).

---

## Upgrade path to the paid bundle

If LITE gets you most of the way and you want the rest of the system without spending weeks figuring out the configuration yourself, the paid Clayworks bundle is the next step.

For context: a Claude power-user workshop runs around $800. An AI workflow consultant charges $150 an hour. An AI agency engagement to set up an equivalent CC operator system starts around $5,000, and hiring a developer to build one from scratch runs into tens of thousands of dollars.

The bundle is a one-time purchase of the hardened configuration I run myself, with the rationale documented inline so you know why every choice was made.

**What the bundle adds:**

- All of the items listed in "What's NOT in LITE" above
- The 15-30 page "Operating Claude Code at production quality" written guide
- Install + troubleshooting field guide
- Annotated production CLAUDE.md with every rule's rationale
- Curated plugin baseline doc for the full 23-plugin operator stack
- Update access for v1.x patches

**Pricing:**

- **Early adopter (first 30 days):** $49
- **Standard:** $79
- Optional sprint-tier service offerings: install acceleration ($499) or full custom setup ($1,500) for people who want the bundle deployed by me rather than self-installing.
- Monthly retainer ($399/mo) for ongoing operator support, advisory, and configuration updates.

Checkout link forthcoming on launch. Watch this repo or [clayboicardi.com](https://clayboicardi.com) for the buy URL.

---

## License

LITE ships under the **MIT License**. You can use it commercially, modify it, redistribute it, sublicense it. The only requirement is preserving the copyright notice.

The MIT choice is deliberate: this is operator scaffolding, not a moat. If LITE is useful for your work, take it.

---

## Who built this

I'm **[@clayboicardi](https://github.com/clayboicardi)** on GitHub. I'm not a developer. Six months before launching Clayworks LITE, I didn't know what GitHub was. The system you're looking at is what let me ship real work anyway.

What I've shipped using this pattern:

- **[HarmonoidWidget](https://github.com/clayboicardi/HarmonoidWidget)** — Android home-screen widget for the Harmonoid music player (Kotlin / MediaSession)
- **[JAMZ](https://github.com/clayboicardi/JAMZ)** — Fork of the [Gramophone](https://github.com/FoedusProgramme/Gramophone) Android music player with custom branding + UI changes (Kotlin / Material Design)
- The internal operator system this kit and the paid bundle distill from, built over months of daily Claude Code use

I run this stack every day on my own machine. It's not a thought experiment. It's the system I actually use to do work I would otherwise have to pay a developer thousands of dollars for.

For service inquiries (sprint installs, custom setups, team retainers), open a GitHub issue here. A dedicated intake form is coming soon at [clayboicardi.com](https://clayboicardi.com).

---

## Design rationale

[`plugin/docs/`](plugin/docs/) carries the **why** behind LITE's design choices. The SKILL.md files and main README cover what the kit does; `plugin/docs/` covers why specific decisions were made and what was rejected:

- [`plugin/docs/why-claude-md-structure-matters.md`](plugin/docs/why-claude-md-structure-matters.md) — section ordering as load-bearing design
- [`plugin/docs/memory-routing-rationale.md`](plugin/docs/memory-routing-rationale.md) — why three layers, why a routing skill
- [`plugin/docs/heartbeat-design.md`](plugin/docs/heartbeat-design.md) — pattern vs. implementation, why bounded time budgets, why these cadences
- [`plugin/docs/installer-design.md`](plugin/docs/installer-design.md) — backup-then-install, hash-diff, symlink rejection, no-auto-edit-of-settings.json
- [`plugin/docs/upgrade-philosophy.md`](plugin/docs/upgrade-philosophy.md) — the principles separating LITE from the paid bundle

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
- **[nyldn / claude-octopus](https://github.com/nyldn/claude-octopus)** — Octo's multi-AI orchestration shaped the bundle's early routing pattern; since retired from my stack in favor of a homegrown multi-provider fan-out (multi-ask), but the influence stands
- **[Gentleman-Programming / engram](https://github.com/Gentleman-Programming/engram)** — Engram persistent memory plugin
- **The awesome-claude-code curators** — [hesreallyhim/awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code), [rohitg00/awesome-claude-code-toolkit](https://github.com/rohitg00/awesome-claude-code-toolkit), [ComposioHQ/awesome-claude-plugins](https://github.com/ComposioHQ/awesome-claude-plugins) — whose maintained lists mapped the CC plugin/skill ecosystem and made it possible to see what's table-stakes vs. what's distinctive
- The other operator-setup-publishers in the CC ecosystem whose published rigs informed what LITE intentionally does and doesn't ship
- The Claude Code community on Discord and GitHub for the steady flow of patterns, edge cases, and pushback that sharpens this kind of work

---

*Clayworks LITE v1. The paid bundle launches alongside.*
