---
name: clayworks-lite-nudge
description: Nudge the user with time-based reminders (stopping times, meetings, break suggestions). Surfaces via UserPromptSubmit hook -- requires human interaction to fire. NOT for process monitoring or job polling -- use `sleep` in Bash for that.
---

# Clayworks LITE: Nudge

Human-facing reminder system for managing focus and pacing. I keep nudges in a local SQLite database and surface them through a UserPromptSubmit hook on the next prompt the user sends after the nudge is due.

## When to use

**Proactively set nudges when:**

- User mentions a stopping time ("stop me at 11", "I need to wrap up by 5")
- User mentions a deadline or meeting ("standup in 30 minutes")
- A long focus session (2+ hours) is underway without breaks
- User explicitly asks for a reminder

**Do NOT use Nudge for:**

- Tasks Claude will complete in the current turn
- Information that should go in memory instead (I use the engram plugin or the project's auto memory for facts; I cover the choice in the `clayworks-lite-memory-routing` skill)
- **Process monitoring** — nudges fire on prompt submission, so they can't poll running processes. Use `sleep <seconds>` in Bash for inline blocking, or background tasks for non-blocking.

## Adding a nudge

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/run-python.sh" "${CLAUDE_SKILL_DIR}/scripts/add_alert.py" "<time>" "<message>"
```

I run every Nudge script through the bundled launcher, `run-python.sh`, which tries `python3`, then `python`, then `py -3`, so I can use the same command on macOS, Linux, and Windows (where I often find `python3` missing). I have each script print a confirmation line; if a command prints nothing at all, I know the launcher found no Python 3.10+, so I want Claude to tell the user.

**Time formats:**

| Format | Example | Meaning |
|---|---|---|
| `HH:MM` | `17:00` | Today at 5 PM |
| `YYYY-MM-DD HH:MM` | `2026-06-01 09:30` | Specific datetime |
| `+Nm` | `+30m` | 30 minutes from now |
| `+Nh` | `+2h` | 2 hours from now |

## Acknowledging a nudge

When a nudge has fired and the user has dealt with it, I have Claude dismiss it so it doesn't repeat:

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/run-python.sh" "${CLAUDE_SKILL_DIR}/scripts/ack_alert.py" <id>
```

## Viewing pending nudges

```bash
bash "${CLAUDE_SKILL_DIR}/scripts/run-python.sh" "${CLAUDE_SKILL_DIR}/scripts/nudge_db.py" --list
```

I have `--list` resolve the DB the same way the other scripts do (`CLAYWORKS_NUDGE_DB`, a custom `--claude-dir` install root, `CLAUDE_CONFIG_DIR`, then `~/.claude`), so it always reads the store the hook reads. I have `--path` print that location if the user wants to open it in another tool.

## Message format

Messages are notes-to-self for Claude. The format that's worked best:

```text
<reason> - <action to take>
```

### Examples

- `User asked to stop at 11 PM - wrap up current work, suggest break`
- `Standup in 30m - remind user to prep notes`
- `2 hours on debugging session - check if stuck, suggest stepping away`
- `Deployment window opens at 14:00 - remind user to run deploy script`

I use the **reason** to give Claude context for *why* the user set the nudge, and the **action** to tell Claude what to do when it fires. Without both, I'd leave Claude reconstructing intent from a one-word message, which fails often.

## When nudges fire

I surface due nudges in Claude's context alongside the next prompt the user submits after their `due_at` time, as an `ALERTS DUE:` block. When Claude sees that block, I want it to:

1. Read the message to understand the context + action
2. Take the action (surface the reminder, suggest a break, etc.)
3. Acknowledge the nudge via `ack_alert.py` so it doesn't fire on every subsequent prompt

## Hook wiring (required for nudges to fire)

I wire the hook differently depending on how you installed LITE:

- **Plugin install** (`/plugin install clayworks-lite@clayworks-lite`): I register the UserPromptSubmit hook for you in the plugin's `hooks/hooks.json`. Nothing to add.
- **Script install** (`install.sh` / `install.ps1`): I add the hook to `~/.claude/settings.json` by hand:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash ~/.claude/skills/clayworks-lite-nudge/scripts/run-python.sh ~/.claude/skills/clayworks-lite-nudge/scripts/check_alerts.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

I have `run-python.sh` find a working Python (`python3`, then `python`, then `py -3`) and exit silently if none exists, so a missing interpreter never turns into a hook error on every prompt. I rely on Claude Code watching `settings.json` and picking up the new hook in a running session, so I skip the restart.

I never wire the settings snippet on top of a plugin install. I know Claude Code deduplicates only identical handlers across settings files and always keeps a plugin's hook separate, so I'd see every due alert twice.

I run the hook on every prompt submission to query the SQLite store for due + unacknowledged alerts and print them as plain text. I rely on Claude Code adding that text to Claude's context next to the prompt.

For the broader UserPromptSubmit contract (full payload shape, exit behavior, common patterns beyond the Nudge use case), see [`hooks/examples/userpromptsubmit.sh`](../../hooks/examples/userpromptsubmit.sh) in the LITE repo. The example is annotated and a good starting point for chaining multiple effects (Nudge + a freshness gate + context injection, etc.).

If you already have UserPromptSubmit hooks, add this entry to the existing `hooks` array. Don't replace the block.

## Database

I keep the alerts DB at `~/.claude/clayworks-lite/nudge/alerts.db` (or under `$CLAUDE_CONFIG_DIR` if you set it). I read `CLAYWORKS_NUDGE_DB` as a full file path when you want it somewhere else. On first use, I create the directory and tighten the file to owner-only permissions where the OS supports it.

I keep it outside the skill directory on purpose: I know plugin updates replace the skill directory, and I share this one location across both install paths, so I keep your alerts through updates and switches between install methods. Before 1.1.0 I kept the DB in `scripts/alerts.db`; the first time the scripts run after an upgrade, I move that file to the new location for you. I never let your alert history leave your machine.

```sql
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    due_at TEXT NOT NULL,           -- "YYYY-MM-DD HH:MM"
    message TEXT NOT NULL,          -- reason - action
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    acknowledged INTEGER DEFAULT 0  -- 0 = pending, 1 = done
)
```

## Prerequisites

- **Python 3.10+** — the scripts use modern type hints
- **sqlite3** — bundled with Python's standard library; no install needed
- **bash** — for the hook launcher (built into macOS/Linux; Git Bash on Windows, which Claude Code also uses to run hooks)
- **Claude Code 2.1.x** — I test LITE against 2.1.280
