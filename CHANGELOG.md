# Changelog

All notable changes to Clayworks LITE are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `clayworks-lite-nudge` skill — SQLite-backed reminder system that surfaces time-based pings via a UserPromptSubmit hook. Includes `add_alert.py`, `ack_alert.py`, `check_alerts.py`, and a SKILL.md with hook-wiring instructions.
- `templates/CLAUDE.md.clayworks-template` — anonymized CLAUDE.md starter. Preserves the structural philosophy (identity → memory routing → behavioral rules → project context) with `<YOUR ...>` placeholders for the parts a user fills in. Includes inline comments explaining WHY each section matters.

### Pending for v1.0.0
- Multi-memory routing decision-tree skill.
- Hook scaffolding examples (one `.sh` per CC hook event).
- Heartbeat framework concept doc.
- `install.sh` / `install.ps1` installers.

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
