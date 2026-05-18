---
name: Bug report
about: install.sh / install.ps1 failures, broken hooks, unexpected behavior
title: "[bug] "
labels: bug
assignees: clayboicardi

---

## What happened

<!-- One or two sentences describing what went wrong. -->

## What you expected

<!-- One sentence describing what you thought would happen. -->

## How to reproduce

<!-- Commands you ran, in order. -->

## Environment

- **OS:** <!-- macOS / Linux / Windows + version -->
- **Shell:** <!-- bash / zsh / pwsh + version -->
- **Python (if relevant):** <!-- output of `python3 --version` AND `python --version` (note if `python` is missing) -->
- **Claude Code version:** <!-- output of `claude --version` -->
- **Clayworks LITE version / commit:** <!-- output of `git log -1 --oneline` from your clone, or release tag -->

## Quick diagnostics (please try first)

- [ ] I ran `./install.sh --dry-run` (or `.\install.ps1 -DryRun`) and the output matches what I expected
- [ ] I checked `~/.claude/.clayworks-lite-backup/<timestamp>/` to see what (if anything) the installer overwrote
- [ ] I restarted Claude Code (closed all sessions, opened a fresh one) after install

## Logs / output

<!-- Paste relevant error output here, in code fences. Redact anything sensitive. -->

```text
(paste here)
```

## Anything else

<!-- Extra context, screenshots, or guesses. -->
