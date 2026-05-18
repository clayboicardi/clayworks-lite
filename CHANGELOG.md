# Changelog

All notable changes to Clayworks LITE are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `clayworks-lite-nudge` skill — SQLite-backed reminder system that surfaces time-based pings via a UserPromptSubmit hook. Includes `add_alert.py`, `ack_alert.py`, `check_alerts.py`, and a SKILL.md with hook-wiring instructions.
- `templates/CLAUDE.md.clayworks-template` — anonymized CLAUDE.md starter. Preserves the structural philosophy (identity → memory routing → behavioral rules → project context) with `<YOUR ...>` placeholders for the parts a user fills in. Includes inline comments explaining WHY each section matters.
- `hooks/examples/` — minimal annotated examples for 8 Claude Code hook events: UserPromptSubmit, PreToolUse, PostToolUse, SessionStart, SessionEnd, Stop, SubagentStart, SubagentStop. Each example shows the JSON payload shape, common use cases, exit-code behavior, and registration syntax for `settings.json`. README in the dir explains the broader hook contract conventions.
- `install.sh` and `install.ps1` — cross-platform installers (bash for macOS/Linux/Git Bash, PowerShell 7+ for Windows). Backup-then-install model: anything that would be overwritten is first copied to `~/.claude/.clayworks-lite-backup/<timestamp>/`. SHA-256 hash-diff on each item makes re-runs idempotent — unchanged files skip, modified files back up then reinstall fresh source. Supports `--dry-run` / `-DryRun` and a `--claude-dir` / `-ClaudeDir` override for testing. Tolerant of missing optional pieces (memory-routing and heartbeat-concept skills install only when present in the repo).
- `.gitattributes` — locks `*.sh` to LF and `*.ps1` to CRLF so cross-platform clones don't break the bash shebang on macOS/Linux when cloned from Windows.
- `clayworks-lite-memory-routing` skill — routing decision tree across Engram (cross-model structured/procedural), native Claude Code `MEMORY.md` (project-scoped), and Honcho (user modeling). Frontmatter description covers the common trigger phrasings ("remember this", "save this", preference statements, project conventions) so the skill auto-triggers when a destination decision is in play. Body explains each layer's strengths, walks a four-question decision tree, includes 11 concrete fact-to-layer examples, and explains how to operate degraded (one-layer-only) installations. Skill is documentation only — no executable component; the underlying memory systems handle storage.
- `clayworks-lite-heartbeat-concept` skill — reference for the heartbeat pattern (cadenced observe + reflect + update loop that keeps an agent's state coherent over time). Anonymized to describe the pattern abstractly; production implementation lives in the paid bundle. Covers six cadences (per-prompt, per-turn, end-of-session, daily, weekly, monthly), six anti-patterns, a minimum-viable single-file heartbeat anyone can start today, and explicit composition notes with the other LITE skills (Nudge fires the cadence; memory-routing decides where consolidated state goes; heartbeat-concept defines what each beat actually does).

### Fixed
- `hooks/examples/sessionstart.sh` (primer-file freshness check) and `hooks/examples/stop.sh` (24h-gated trigger example, commented) used `date -r "$FILE" +%s` to read file mtime. This works on GNU `date` (Linux) but silently fails on BSD `date` (macOS) — BSD's `-r` treats the argument as epoch seconds, not a file path. Replaced with `python3 -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$FILE"` for portability. Existing users who copied the examples should update their local copies; the installer doesn't touch user-customized hook files.
- README: replaced internal-phase-naming reference ("Phase V observability stack") with a generic description ("three-tier observability stack") that doesn't leak private terminology.
- Hook examples + Nudge SKILL.md + Nudge Python script docstrings: normalized `python -c` / `python <script>.py` invocations to `python3` consistently. Modern macOS (12.3+) removed `/usr/bin/python`, so the unqualified `python` form silently failed on a default macOS install (hooks don't block on stderr, so the user got no signal). README Prerequisites now notes that the scripts invoke `python3` by name.
- `.gitattributes`: added an explicit `*.clayworks-template text eol=lf` rule. The CLAUDE.md template uses the `.clayworks-template` extension, which doesn't match the existing `*.md eol=lf` rule. Without the new rule, Windows clones got CRLF line endings on the template, which then propagated into a user's `CLAUDE.md` when they followed the install instructions.
- `install.ps1` + README: corrected PowerShell version claim from "PowerShell 7+" to "PowerShell 5.1+". The installer uses no PS7-only features (no `??`, `?:`, `&&`/`||`, or `ForEach-Object -Parallel`); true floor is PS 5.1, the universal Windows 10 baseline. Added `#Requires -Version 5.1` directive to `install.ps1` so older PowerShell versions get a clean rejection instead of obscure parse errors. The earlier claim was a false adoption barrier for users on Windows 10 corporate machines that haven't upgraded to PS 7.
- README factual cleanup: added missing `git` to Prerequisites (the install snippet's first line is `git clone`); fixed JAMZ link from the old `clayboicardi/Gramophone` URL to the current `clayboicardi/JAMZ` (GitHub still redirects, but the URL is fragile against future re-takes of the old name); added upstream Gramophone link to the JAMZ acknowledgment for clearer fork attribution; struck `[DATE TBD]` from the footer (the CHANGELOG carries the canonical release date); `templates/CLAUDE.md.clayworks-template`: replaced a broken private-repo link (`github.com/clayboicardi/clayworks`, returns 404 for non-collaborators) with a "checkout link forthcoming at clayboicardi.com" line that doesn't dead-end.

### Changed
- Cross-reference web added between LITE skills and hook examples. The three LITE skills + the 8 hook examples are designed to compose, but the SKILL.md files didn't point at the specific hook examples they pair with (and vice versa). Resolved:
  - `clayworks-lite-heartbeat-concept` SKILL.md: each cadence section (per-prompt, per-turn, end-of-session, daily) now names the specific LITE hook example that serves as its starting-point contract.
  - `clayworks-lite-nudge` SKILL.md: hook-wiring section now points at `hooks/examples/userpromptsubmit.sh` as the broader contract reference for chaining multiple effects.
  - `hooks/examples/README.md`: added a "How these pair with the LITE skills" section explicitly mapping each hook event to the LITE skill that consumes (or could consume) it.
  - `clayworks-lite-memory-routing` SKILL.md: unchanged — no hook relationship by design (user-action-triggered, not hook-triggered).
- `.gitignore`: removed `.last-dream` and `.dream-pending` entries. These are markers for a private off-session memory-consolidation system that doesn't ship in LITE; their presence in `.gitignore` was leakage of private-system terminology into the public repo.

## [0.1.0] — 2026-05-17

### Added
- Initial repo scaffold (public repository, MIT license).
- README describing what Clayworks LITE is, who it's for, what's in it, what's not.
- LICENSE (MIT).
- CONTRIBUTING.md (contribution guidelines).
- Issue templates (bug report, enhancement).
- CODEOWNERS.

### Pending for v1.0.0
- CLAUDE.md starter template (anonymized).
- Multi-memory routing decision-tree skill.
- Hook scaffolding examples (one `.sh` per CC hook event).
- Heartbeat framework concept doc.
- `install.sh` / `install.ps1` installers.
