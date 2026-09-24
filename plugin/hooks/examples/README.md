# Clayworks LITE — Hook Scaffolding Examples

Minimal, annotated examples for the eight Claude Code hook events I reach for most. I know Claude Code documents many more (permission, compaction, worktree, model-switch, file-watch, and task events among them); I point to the [hooks reference](https://code.claude.com/docs/en/hooks) for the full list. I use these as starting points: I copy one into `~/.claude/hooks/` (renamed to fit my purpose) and reference it in `~/.claude/settings.json`.

## What hooks are

I think of hooks as shell commands that Claude Code runs at specific lifecycle events. I use them to:

- **Observe** — log activity, capture telemetry, surface alerts
- **Inject** — add text to Claude's context (plain stdout on UserPromptSubmit and SessionStart; JSON `additionalContext` on most other events)
- **Guard** — block tool calls before they happen (`exit 2` on PreToolUse)
- **Cleanup** — release resources at session end

I rely on Claude Code sending each hook a JSON payload on stdin that describes the event. I control what happens next with the exit code and stdout:

- **Exit 0** — success. On UserPromptSubmit and SessionStart, I get plain-text stdout into Claude's context; I rely on Claude Code wrapping it itself (as a system reminder that names the hook), so I print plain text and never hand-wrap it in `<system-reminder>` tags. On most other events, I know plain stdout only goes to the debug log.
- **Exit 2** — the only exit code that blocks. I get a different block per event: on PreToolUse I block the tool call, on UserPromptSubmit I reject the prompt, and on Stop I make Claude keep working. I put the reason on stderr.
- **Any other non-zero exit** — a non-blocking error. I see Claude Code show a hook-error notice and carry on. I block **nothing** with `exit 1`.
- **Stdout that starts with `{`** — I rely on Claude Code parsing it as [JSON output](https://code.claude.com/docs/en/hooks#json-output). If it doesn't parse, I know Claude Code drops it and reports a hook error, so I never print JSON-looking text by accident.
- **Size** — I work within the 10,000-character cap on plain stdout and `additionalContext`; I know Claude Code saves anything longer to a file and passes only a preview.

## Registering a hook in settings.json

Edit `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/hooks/your-hook.sh",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

I can list multiple handlers in the `hooks` array per event, and I rely on Claude Code running every matching handler **in parallel**, not in the order I list them. I never write two hooks that depend on each other's output. I give `timeout` in seconds; I rely on Claude Code cancelling the hook if it runs longer. I set it explicitly and keep it small. I know the defaults vary by event (30s for UserPromptSubmit, 600s for most command hooks), and that SessionEnd shares a 1.5-second budget unless I raise it.

I rely on Claude Code watching `settings.json` and applying hook edits to a running session, so I skip the restart. I run `/hooks` to confirm what Claude Code loaded and where each hook came from.

## Files in this directory

| File | Hook event | Purpose |
|---|---|---|
| `userpromptsubmit.sh` | UserPromptSubmit | I wire it to fire on every prompt the user sends. Common: reminder injection, freshness gates, context. |
| `pretooluse.sh` | PreToolUse | I wire it to fire before a matching tool call. Common: guards (`exit 2`), sandboxing, audit logging. |
| `posttooluse.sh` | PostToolUse | I wire it to fire after a tool call succeeds. Common: timing logs, added context for Claude. |
| `sessionstart.sh` | SessionStart | I wire it to fire on startup, resume, `/clear`, compaction, and fork (I read `source` to tell which). Common: primer files, unfinished-work reminders. |
| `sessionend.sh` | SessionEnd | I wire it to fire when a session ends (I read `reason` to learn why). Common: state persistence, a summary line. Tight time budget. |
| `stop.sh` | Stop | I wire it to fire each time Claude finishes a response, not at session exit. Common: end-of-turn cleanup, observability grading. |
| `subagentstart.sh` | SubagentStart | I wire it to fire when Claude spawns a subagent. Common: parallel-work tracking, subagent context injection. |
| `subagentstop.sh` | SubagentStop | I wire it to fire when a subagent finishes. Common: a log of what it reported. |

## How these pair with the LITE skills

- **`userpromptsubmit.sh` ↔ `clayworks-lite-nudge`** — I ship a working consumer of UserPromptSubmit in the Nudge skill. I wrote its `scripts/check_alerts.py` as exactly the kind of command this hook event exists to run, and I register it for you in the plugin install (see `plugin/hooks/hooks.json`). I use the example here for the broader contract and the skill for the concrete implementation.
- **`stop.sh`, `sessionend.sh`, `sessionstart.sh` ↔ `clayworks-lite-heartbeat-concept`** — the heartbeat-concept skill describes the cadence pattern (observe + reflect + update on a schedule). These three hook examples are the starting points for implementing the per-turn, end-of-session, and session-open beats respectively. The skill explains the *pattern*; the examples are the *primitives*.
- **`pretooluse.sh`, `posttooluse.sh`, `subagentstart.sh`, `subagentstop.sh`** — I don't consume these directly from any LITE skill. I offer them as observability and audit primitives you can wire into your own beats (e.g., I could have a stop.sh-driven heartbeat read the PostToolUse log to grade per-turn behavior) or use standalone for sandboxing and telemetry.

## Pattern conventions used

- All examples start with `#!/usr/bin/env bash` + `set -u` for safety
- I use `set -u` (error on undefined variables) but **not** `set -e` (exit on any error). I need hooks to keep running even when a single branch fails — with `set -e` I'd turn a `mkdir -p` permission warning into a session-affecting hook failure. I send errors to stderr and let the hook move on.
- All examples are **silent unless something fires** — no constant chatter to logs
- I parse JSON with `python3 -c "import json, sys; ..."` (no `jq` dependency). On Windows, where I often find `python3` missing, I fall back to the Nudge skill's bundled launcher: I replace `python3 -c "..."` with `bash /path/to/run-python.sh -c "..."`, and I let it try `python3`, then `python`, then `py -3`. If it finds no Python, I have it print nothing, so the example sees empty fields instead of crashing.
- I strip control characters from payload string fields before they reach a log file, so a crafted payload can't forge log lines
- Log files default to `~/agent/logs/` (override with env var if you prefer elsewhere)
- Errors go to stderr; stdout is reserved for content Claude should see

## How to evolve from these

These are deliberately MINIMAL. The Clayworks paid bundle ships production-hardened versions with:

- Prompt-injection defenses
- Log rotation
- Multi-platform path handling
- Graceful degradation on missing dependencies
- Cross-session coordination (CC↔CC comms)

If your hook is taking on responsibility (e.g., a freshness gate that injects external content), invest in those defenses. If it's just a logger, the minimal pattern is fine forever.
