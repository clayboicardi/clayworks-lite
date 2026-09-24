# LITE in action: worked examples

This directory ships **two complete LITE configurations**, ready to adapt. They show what the kit looks like assembled, not just as parts.

Both examples assume the script install (`./install.sh` or `.\install.ps1` from the repo root), which puts the skills in `~/.claude/skills/`. Examples here are *configurations*, the artifacts a user lands in `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, and `~/.claude/hooks/` after they decide what they want.

If you installed LITE as a plugin instead, the plugin already registers the Nudge hook. Skip the `minimal/` example and drop the UserPromptSubmit block from `full/settings.json`, or every due alert shows up twice.

## [`minimal/`](minimal/) — smallest viable config

The minimum to make LITE actually *do* something.

- [`settings.json`](minimal/settings.json) — one hook: UserPromptSubmit fires the Nudge skill's `check_alerts.py` on every prompt, so time-based reminders actually fire when due. A small launcher (`run-python.sh`) finds `python3`, `python`, or `py -3`, so the same command works on macOS, Linux, and Windows.

That's it. Drop the `hooks` block into your `~/.claude/settings.json` (merging with any existing hooks) and the Nudge skill goes from "registers alerts" to "alerts also surface at due time."

**Adopt this when:** you want one tangible win from LITE without committing to the broader heartbeat pattern.

## [`full/`](full/) — heartbeat-pattern setup

Demonstrates the LITE skills + hook examples composed into a working heartbeat-style operator setup.

- [`settings.json`](full/settings.json) — three hooks wired: UserPromptSubmit (Nudge), SessionStart (primer surface + git-state warning), Stop (per-turn log + commented dream-style 24h trigger).
- [`hooks/sessionstart.sh`](full/hooks/sessionstart.sh) — customized from the LITE example. Reads a primer file at `~/agent/session-primer.md` (configurable), warns about uncommitted git state.
- [`hooks/stop.sh`](full/hooks/stop.sh) — customized from the LITE example. Logs every turn-end timestamp.
- [`CLAUDE.md`](full/CLAUDE.md) — `CLAUDE.md.clayworks-template` with the `<YOUR ...>` placeholders filled for a fictional operator "Sam". Real-shaped, immediately adoptable.

**Adopt this when:** you've felt LITE's minimum-viable Nudge config land and you want the heartbeat pattern wired in.

## Adoption pattern (both)

1. **Copy** the parts you want from `examples/<flavor>/` into the equivalent paths under `~/.claude/`.
2. **Merge** `settings.json` if you already have one. The LITE settings live inside `hooks.*` arrays you append to, not replace.
3. **Customize** the CLAUDE.md (placeholders, project paths, your preferences). Don't ship someone else's persona as your own.
4. **Check it loaded.** Claude Code watches `settings.json` and applies hook changes to a running session, so you don't need to restart it. Run `/hooks` to confirm the entries and where each one came from.
5. **Verify** with `./install.sh --verify` from the LITE repo and an actual time-based natural-language prompt (e.g. *"stop me at 5pm to wrap up"*).

## What these examples are NOT

- **Not a substitute for reading the skills' SKILL.md docs.** The skills explain the *why*; these examples show *what an assembled outcome looks like*.
- **Not exhaustive.** LITE's hook scaffolding covers eight events; the `full/` example wires 3. The 5 unwired ones (`PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`, `SessionEnd`) live in `hooks/examples/`, where I document each one so you can compose it in as your setup matures.
- **Not "Sam's actual config"** — there is no Sam. The persona's placeholder values are illustrative shape, nothing more.
