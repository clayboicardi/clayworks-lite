# Security Policy

## Supported versions

The latest tagged release on `main` is supported. Older releases receive no patches.

## Reporting a vulnerability

If you find a security issue in Clayworks LITE — installer behavior, hook examples that enable exploitation, vulnerabilities in the bundled Python scripts — please **do not** open a public GitHub issue.

Instead, use one of:

- **GitHub's private vulnerability reporting:** [github.com/clayboicardi/clayworks-lite/security/advisories/new](https://github.com/clayboicardi/clayworks-lite/security/advisories/new)
- **Email:** [clayhaworth1@gmail.com](mailto:clayhaworth1@gmail.com) — subject `[clayworks-lite security]`

Expected response: acknowledgement within 7 days, fix-or-disclosure-plan within 30 days. If the issue requires coordination with the upstream plugins LITE references (Engram, Honcho, Octo), I'll loop in their maintainers.

## Threat model

LITE installs into `~/.claude/` — a directory that may contain Claude Code conversation history, project paths, and (depending on your CC setup) credentials in plain-text settings or `.env` references. Anything that compromises `~/.claude/` is in scope.

**In scope:**

- Supply-chain tampering — malicious modifications to the source tree that the installer would then write into `~/.claude/`
- Hook examples that, when copied verbatim into a user's `~/.claude/hooks/`, enable arbitrary code execution (e.g. `git status` in an untrusted cwd, `eval`-style processing of user input)
- Python scripts in `skills/clayworks-lite-nudge/scripts/` — SQL injection, argv handling, path traversal
- Local prompt-injection vectors via hook stdout that gets surfaced to Claude as system-reminder context
- Installer behavior that escapes the configured `~/.claude/` root (or `--claude-dir` override)

**Out of scope:**

- The Claude Code platform itself (report to Anthropic)
- Third-party plugins LITE mentions (Engram → Gentleman-Programming/engram; Honcho → plastic-labs/claude-honcho; Octo → nyldn/claude-octopus)
- Network-level concerns — LITE has no network calls in any shipped runtime component
- User error — running with `--claude-dir=/etc` is a self-inflicted wound, not a vulnerability

## Hardening shipped in v1.0.0

- Installer refuses to proceed if the source tree contains symlinks/junctions (supply-chain hardening — see `install.sh`'s `reject_symlinks_in_source` + `install.ps1`'s `Test-NoSymlinksInSource`)
- `install.sh` uses `cp -RP` (no-dereference) and `path_hash()` excludes symlinks for TOCTOU robustness
- `hooks/examples/sessionstart.sh` neutralizes `core.fsmonitor` / `core.hooksPath` when running `git status` in user-controlled cwd (CVE-2022-39253 family)
- Hook examples include SECURITY comments calling out the prompt-injection channel (primer file) and pinned-script-path foot-gun (background-job pattern)
- Backup-before-overwrite model on every install — your existing files are always recoverable from `~/.claude/.clayworks-lite-backup/<timestamp>/`

## Known non-issues

- `~/.claude/.clayworks-lite-backup/` accumulates over many installs. Safe to delete manually; not a vulnerability.
- The Nudge SQLite database (`alerts.db`) is gitignored and stays local.
- LITE does not telemeter, phone home, or make any network calls in shipped scripts.
