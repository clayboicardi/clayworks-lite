---
name: clayworks-lite-nudge
description: Nudge the user with time-based reminders (stopping times, meetings, break suggestions). Surfaces via UserPromptSubmit hook -- requires human interaction to fire. NOT for process monitoring or job polling -- use `sleep` in Bash for that.
---

# Clayworks LITE — Nudge

Human-facing reminder system for managing focus and pacing. Nudges are stored in a local SQLite database and surface via a UserPromptSubmit hook on the next prompt the user sends after the nudge is due.

## When to use

**Proactively set nudges when:**
- User mentions a stopping time ("stop me at 11", "I need to wrap up by 5")
- User mentions a deadline or meeting ("standup in 30 minutes")
- A long focus session (2+ hours) is underway without breaks
- User explicitly asks for a reminder

**Do NOT use Nudge for:**
- Tasks Claude will complete in the current turn
- Information that should go in memory instead (use the engram plugin or `~/.claude/projects/<project>/memory/MEMORY.md` for facts)
- **Process monitoring** — nudges fire on prompt submission, so they can't poll running processes. Use `sleep <seconds>` in Bash for inline blocking, or background tasks for non-blocking.

## Adding a nudge

```bash
python ~/.claude/skills/clayworks-lite-nudge/scripts/add_alert.py "<time>" "<message>"
```

**Time formats:**

| Format | Example | Meaning |
|---|---|---|
| `HH:MM` | `17:00` | Today at 5 PM |
| `YYYY-MM-DD HH:MM` | `2026-06-01 09:30` | Specific datetime |
| `+Nm` | `+30m` | 30 minutes from now |
| `+Nh` | `+2h` | 2 hours from now |

## Acknowledging a nudge

When a nudge has fired and been addressed, dismiss it so it doesn't repeat:

```bash
python ~/.claude/skills/clayworks-lite-nudge/scripts/ack_alert.py <id>
```

## Viewing pending nudges

```bash
sqlite3 ~/.claude/skills/clayworks-lite-nudge/scripts/alerts.db \
  "SELECT id, due_at, message FROM alerts WHERE acknowledged = 0 ORDER BY due_at"
```

## Message format

Messages are notes-to-self for Claude. The format that's worked best:

```
<reason> - <action to take>
```

### Examples

- `User asked to stop at 11 PM - wrap up current work, suggest break`
- `Standup in 30m - remind user to prep notes`
- `2 hours on debugging session - check if stuck, suggest stepping away`
- `Deployment window opens at 14:00 - remind user to run deploy script`

The **reason** gives Claude context for *why* the nudge was set; the **action** tells Claude what to do when it fires. Without both, Claude has to reconstruct intent from a one-word message, which fails often.

## When nudges fire

Due nudges appear in a system-reminder on the next prompt submission after their `due_at` time has passed. When Claude sees an alert in the system-reminder:

1. Read the message to understand the context + action
2. Take the action (surface the reminder, suggest a break, etc.)
3. Acknowledge the nudge via `ack_alert.py` so it doesn't fire on every subsequent prompt

## Hook wiring (required for nudges to fire)

This skill ships the SQL store and the helper scripts. For nudges to *fire*, you need a UserPromptSubmit hook configured in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python ~/.claude/skills/clayworks-lite-nudge/scripts/check_alerts.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The hook runs on every prompt submission, queries the SQLite for due+unacknowledged alerts, and prints them. Claude Code surfaces the printed text as a system-reminder.

If you already have UserPromptSubmit hooks, add this entry to the existing `hooks` array — don't replace the block.

## Database schema

```sql
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    due_at TEXT NOT NULL,           -- "YYYY-MM-DD HH:MM"
    message TEXT NOT NULL,          -- reason - action
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    acknowledged INTEGER DEFAULT 0  -- 0 = pending, 1 = done
)
```

The DB file (`alerts.db`) is created in the `scripts/` directory on first use. It's gitignored — your personal alert history never leaves your machine.

## Prerequisites

- **Python 3.10+** — the scripts use modern type hints
- **sqlite3** — bundled with Python's standard library; no install needed
- **Claude Code** with UserPromptSubmit hook support (any 2.x version)
