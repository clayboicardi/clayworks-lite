# Clayworks LITE — Hook Scaffolding Examples

Minimal, annotated examples for the eight Claude Code hook events I reach for most. Claude Code documents many more (permission, compaction, worktree, model-switch, file-watch, and task events among them); see the [hooks reference](https://code.claude.com/docs/en/hooks) for the full list. Use these as starting points: copy into `~/.claude/hooks/` (renamed to fit your purpose) and reference them in `~/.claude/settings.json`.

## What hooks are

Hooks are shell commands that Claude Code runs at specific lifecycle events. They can:

- **Observe** — log activity, capture telemetry, surface alerts
- **Inject** — add text to Claude's context (plain stdout on UserPromptSubmit and SessionStart; JSON `additionalContext` on most other events)
- **Guard** — block tool calls before they happen (`exit 2` on PreToolUse)
- **Cleanup** — release resources at session end

Each hook receives a JSON payload on stdin describing the event. The exit code and stdout decide what happens next:

- **Exit 0** — success. On UserPromptSubmit and SessionStart, plain-text stdout reaches Claude's context; Claude Code wraps it itself (as a system reminder that names the hook), so print plain text and don't hand-wrap it in `<system-reminder>` tags. On most other events, plain stdout only goes to the debug log.
- **Exit 2** — the only exit code that blocks. What it blocks depends on the event: PreToolUse blocks the tool call, UserPromptSubmit rejects the prompt, Stop makes Claude keep working. Stderr carries the reason.
- **Any other non-zero exit** — a non-blocking error. Claude Code shows a hook-error notice and carries on. `exit 1` does **not** block anything.
- **Stdout that starts with `{`** — Claude Code parses it as [JSON output](https://code.claude.com/docs/en/hooks#json-output). If it doesn't parse, Claude Code drops it and reports a hook error, so don't print JSON-looking text by accident.
- **Size** — plain stdout and `additionalContext` cap at 10,000 characters; Claude Code saves anything longer to a file and passes only a preview.

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

The `hooks` array per event allows multiple handlers, and every matching handler runs **in parallel**, not in the order you list them. Don't write two hooks that depend on each other's output. `timeout` is in seconds; Claude Code cancels the hook if it runs longer. Set it explicitly and keep it small. The defaults vary by event (30s for UserPromptSubmit, 600s for most command hooks), and SessionEnd shares a 1.5-second budget unless you raise it.

Claude Code watches `settings.json` and applies hook edits to a running session, so you don't need a restart. Run `/hooks` to confirm what Claude Code loaded and where each hook came from.

## Files in this directory

| File | Hook event | Purpose |
|---|---|---|
| `userpromptsubmit.sh` | UserPromptSubmit | Fires on every prompt the user sends. Common: inject reminders, freshness gates, context. |
| `pretooluse.sh` | PreToolUse | Fires before a matching tool call. Common: guards (`exit 2`), sandboxing, audit logging. |
| `posttooluse.sh` | PostToolUse | Fires after a tool call succeeds. Common: log timing, add context for Claude. |
| `sessionstart.sh` | SessionStart | Fires on startup, resume, `/clear`, compaction, and fork (`source` says which). Common: load primer files, surface unfinished work. |
| `sessionend.sh` | SessionEnd | Fires when a session ends (`reason` says why). Common: persist state, write a summary line. Tight time budget. |
| `stop.sh` | Stop | Fires each time Claude finishes a response, not at session exit. Common: end-of-turn cleanup, observability grading. |
| `subagentstart.sh` | SubagentStart | Fires when Claude spawns a subagent. Common: track parallel work, inject subagent context. |
| `subagentstop.sh` | SubagentStop | Fires when a subagent finishes. Common: log what it reported. |

## How these pair with the LITE skills

- **`userpromptsubmit.sh` ↔ `clayworks-lite-nudge`** — the Nudge skill ships a working consumer of UserPromptSubmit. Its `scripts/check_alerts.py` is exactly the kind of command this hook event exists to run, and the plugin install registers it for you (see `plugin/hooks/hooks.json`). The example here is the broader contract; the skill is the concrete implementation.
- **`stop.sh`, `sessionend.sh`, `sessionstart.sh` ↔ `clayworks-lite-heartbeat-concept`** — the heartbeat-concept skill describes the cadence pattern (observe + reflect + update on a schedule). These three hook examples are the starting points for implementing the per-turn, end-of-session, and session-open beats respectively. The skill explains the *pattern*; the examples are the *primitives*.
- **`pretooluse.sh`, `posttooluse.sh`, `subagentstart.sh`, `subagentstop.sh`** — no LITE skill consumes these directly. They're observability and audit primitives you can wire into your own beats (e.g., a stop.sh-driven heartbeat could read the PostToolUse log to grade per-turn behavior) or use standalone for sandboxing and telemetry.

## Pattern conventions used

- All examples start with `#!/usr/bin/env bash` + `set -u` for safety
- I use `set -u` (error on undefined variables) but **not** `set -e` (exit on any error). Hooks must keep running even when a single branch fails — `set -e` would turn a `mkdir -p` permission warning into a session-affecting hook failure. Errors go to stderr; the hook moves on.
- All examples are **silent unless something fires** — no constant chatter to logs
- JSON parsing uses `python3 -c "import json, sys; ..."` (no `jq` dependency). On Windows, where `python3` is often missing, swap in `python` or `py -3`, or route through the Nudge skill's `run-python.sh` launcher.
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
