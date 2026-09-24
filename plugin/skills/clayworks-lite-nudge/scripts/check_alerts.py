#!/usr/bin/env python3
"""Hook script: check for due alerts and print them.

I run this from a UserPromptSubmit hook. With the plugin install I register it
for you (plugin/hooks/hooks.json). For the install.sh / install.ps1 path, I add
this to ~/.claude/settings.json:

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

I print due + unacknowledged alerts as plain text. I rely on Claude Code adding
plain UserPromptSubmit stdout to Claude's context (and wrapping it itself), so
the model sees the alerts alongside the user's next prompt. I print nothing
when no alert is due.
"""

import shlex
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True  # I keep __pycache__ out of the skill dir
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
    except Exception as exc:  # noqa: BLE001 -- I report instead of dumping a traceback
        # I print one short stderr line: Claude Code shows it in a non-blocking
        # "hook error" notice, and I still let the prompt go through.
        print(f"clayworks-lite-nudge: I could not read the alerts DB: {exc}", file=sys.stderr)
        sys.exit(1)
    if alerts:
        print("ALERTS DUE:")
        for alert_id, due_at, message in alerts:
            print(f"  [{alert_id}] {due_at}: {message}")
        # I route the dismiss command through the bundled launcher: on Windows
        # machines with only `python` or `py -3`, a bare `python3` fails and I'd
        # repeat the alert on every prompt.
        # shlex.quote: Claude may run this line, so I make sure an install path
        # with quotes, `$`, or backticks can't break out of the arguments.
        launcher = shlex.quote(LAUNCHER.as_posix())
        ack = shlex.quote(ACK_SCRIPT.as_posix())
        print(f"(Dismiss with: bash {launcher} {ack} <id>)")


if __name__ == "__main__":
    main()
