# Clayworks LITE — Hook Scaffolding Examples

Minimal, annotated examples for each Claude Code hook event. Use these as starting points; copy into `~/.claude/hooks/` (renamed to fit your purpose) and reference them in `~/.claude/settings.json`.

## What hooks are

Hooks are shell commands that Claude Code invokes at specific lifecycle events. They can:

- **Observe** — log activity, capture telemetry, surface alerts
- **Inject** — print text that Claude sees as a system-reminder on the next prompt
- **Guard** — block tool calls before they happen (via exit code on PreToolUse)
- **Cleanup** — release resources at session end

Each hook receives a JSON payload on stdin describing the event. Print to stdout to inject text into the session. Exit non-zero to signal failure (some hooks treat this as a block; others just log it).

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

The `hooks` array per event allows multiple hooks; they all run on each fire. `timeout` is in seconds — Claude Code kills the hook if it exceeds this. Default to 5; bump only if the hook genuinely needs longer.

## Files in this directory

| File | Hook event | Purpose |
|---|---|---|
| `userpromptsubmit.sh` | UserPromptSubmit | Fires on every prompt the user sends. Common: inject reminders, freshness gates, context. |
| `pretooluse.sh` | PreToolUse | Fires before any tool call. Common: guards, sandboxing, audit logging. |
| `posttooluse.sh` | PostToolUse | Fires after a tool returns. Common: log results, surface anomalies. |
| `sessionstart.sh` | SessionStart | Fires when a session begins. Common: load primer files, surface unfinished work. |
| `sessionend.sh` | SessionEnd | Fires when a session terminates. Common: persist state, write summary. |
| `stop.sh` | Stop | Fires when Claude completes its turn. Common: end-of-turn cleanup, observability grading. |
| `subagentstart.sh` | SubagentStart | Fires when a subagent (Agent tool) is dispatched. Common: track parallel work. |
| `subagentstop.sh` | SubagentStop | Fires when a subagent completes. Common: collect results, log timing. |

## How these pair with the LITE skills

- **`userpromptsubmit.sh` ↔ `clayworks-lite-nudge`** — the Nudge skill ships a working consumer of UserPromptSubmit. Its `scripts/check_alerts.py` is exactly the kind of command this hook event was designed to run. The example here is the broader contract; the skill is the concrete implementation.
- **`stop.sh`, `sessionend.sh`, `sessionstart.sh` ↔ `clayworks-lite-heartbeat-concept`** — the heartbeat-concept skill describes the cadence pattern (observe + reflect + update on a schedule). These three hook examples are the starting points for implementing the per-turn, end-of-session, and session-open beats respectively. The skill explains the *pattern*; the examples are the *primitives*.
- **`pretooluse.sh`, `posttooluse.sh`, `subagentstart.sh`, `subagentstop.sh`** — no LITE skill currently consumes these directly. They're observability and audit primitives you can wire into your own beats (e.g., a stop.sh-driven heartbeat could read the PostToolUse log to grade per-turn behavior) or use standalone for sandboxing and telemetry.

## Pattern conventions used

- All examples start with `#!/usr/bin/env bash` + `set -u` for safety
- All examples are **silent unless something fires** — no constant chatter to logs
- JSON parsing uses `python3 -c "import json, sys; ..."` (no `jq` dependency)
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
