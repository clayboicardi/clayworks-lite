#!/usr/bin/env python3
"""Hook script: check for due alerts and print them.

Runs from a UserPromptSubmit hook. The plugin install registers it for you
(plugin/hooks/hooks.json). For the install.sh / install.ps1 path, add this to
~/.claude/settings.json:

    {
      "hooks": {
        "UserPromptSubmit": [{
          "hooks": [{
            "type": "command",
            "command": "bash ~/.claude/skills/clayworks-lite-nudge/scripts/run-python.sh ~/.claude/skills/clayworks-lite-nudge/scripts/check_alerts.py",
            "timeout": 10
          }]
        }]
      }
    }

Prints due + unacknowledged alerts as plain text. Claude Code adds plain
UserPromptSubmit stdout to Claude's context (it wraps it itself), so the model
sees the alerts alongside the user's next prompt. Prints nothing when no
alert is due.
"""

import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True  # keep __pycache__ out of the skill dir
from nudge_db import open_db  # noqa: E402

ACK_SCRIPT = Path(__file__).resolve().parent / "ack_alert.py"
LAUNCHER = Path(__file__).resolve().parent / "run-python.sh"


def check_alerts() -> list[tuple[int, str, str]]:
    """Return (id, due_at, message) tuples for unacknowledged due alerts."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open_db() as conn:
        cursor = conn.execute(
            """
            SELECT id, due_at, message
            FROM alerts
            WHERE due_at <= ? AND acknowledged = 0
            ORDER BY due_at
            """,
            (now,),
        )
        return cursor.fetchall()


def main() -> None:
    try:
        alerts = check_alerts()
    except Exception as exc:  # noqa: BLE001 -- report, don't dump a traceback
        # One short stderr line: Claude Code shows it in a non-blocking
        # "hook error" notice, and the prompt still goes through.
        print(f"clayworks-lite-nudge: could not read alerts DB: {exc}", file=sys.stderr)
        sys.exit(1)
    if alerts:
        print("ALERTS DUE:")
        for alert_id, due_at, message in alerts:
            print(f"  [{alert_id}] {due_at}: {message}")
        # Route the dismiss command through the bundled launcher: on Windows
        # machines with only `python` or `py -3`, a bare `python3` fails and
        # the alert would repeat on every prompt.
        print(f'(Dismiss with: bash "{LAUNCHER.as_posix()}" "{ACK_SCRIPT.as_posix()}" <id>)')


if __name__ == "__main__":
    main()
