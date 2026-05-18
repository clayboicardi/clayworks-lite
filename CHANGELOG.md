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

### Pending for v1.0.0
- Multi-memory routing decision-tree skill.
- Heartbeat framework concept doc.

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
