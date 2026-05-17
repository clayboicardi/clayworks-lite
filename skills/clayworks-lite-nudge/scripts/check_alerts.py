#!/usr/bin/env python3
"""Hook script: check for due alerts and print them.

Intended to be invoked from a UserPromptSubmit hook in ~/.claude/settings.json:

    {
      "hooks": {
        "UserPromptSubmit": [{
          "hooks": [{
            "type": "command",
            "command": "python ~/.claude/skills/clayworks-lite-nudge/scripts/check_alerts.py",
            "timeout": 5
          }]
        }]
      }
    }

Prints due+unacknowledged alerts. Claude Code surfaces the printed text
as a system-reminder so the model sees it on the user's next prompt.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "alerts.db"
ACK_SCRIPT = Path(__file__).parent / "ack_alert.py"


def init_db() -> None:
    """Create the alerts table if it doesn't exist (idempotent)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                due_at TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                acknowledged INTEGER NOT NULL DEFAULT 0
            )
        """)


def check_alerts() -> list[tuple[int, str, str]]:
    """Return (id, due_at, message) tuples for unacknowledged due alerts."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with sqlite3.connect(DB_PATH) as conn:
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
    init_db()
    alerts = check_alerts()
    if alerts:
        print("ALERTS DUE:")
        for alert_id, due_at, message in alerts:
            print(f"  [{alert_id}] {due_at}: {message}")
        print(f"(Dismiss with: python {ACK_SCRIPT} <id>)")


if __name__ == "__main__":
    main()
