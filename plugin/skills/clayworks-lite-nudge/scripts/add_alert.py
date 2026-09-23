#!/usr/bin/env python3
"""Add a new alert to the Nudge SQLite store.

Usage:
    python3 add_alert.py <time> <message>

Time formats:
    HH:MM             -- Today at that time (24-hour)
    YYYY-MM-DD HH:MM  -- Specific datetime
    +Nm               -- N minutes from now (e.g., +30m)
    +Nh               -- N hours from now (e.g., +2h)

The database lives at ~/.claude/clayworks-lite/nudge/alerts.db (override with
the CLAYWORKS_NUDGE_DB environment variable). See nudge_db.py.
"""

import sys
from datetime import datetime, timedelta

sys.dont_write_bytecode = True  # keep __pycache__ out of the skill dir
from nudge_db import open_db  # noqa: E402


def parse_time(time_str: str) -> str:
    """Parse a time string into ISO-formatted 'YYYY-MM-DD HH:MM'.

    Accepts: HH:MM (today), YYYY-MM-DD HH:MM, +Nm, +Nh
    """
    now = datetime.now()

    if time_str.startswith("+"):
        try:
            amount = int(time_str[1:-1])
        except ValueError:
            raise ValueError(f"Invalid time format: {time_str!r}. Expected +30m or +2h")
        unit = time_str[-1]
        if unit == "m":
            target = now + timedelta(minutes=amount)
        elif unit == "h":
            target = now + timedelta(hours=amount)
        else:
            raise ValueError(f"Unknown unit: {unit!r}. Use 'm' (minutes) or 'h' (hours)")
        return target.strftime("%Y-%m-%d %H:%M")

    if len(time_str) == 5 and ":" in time_str:
        # HH:MM format -- assume today
        return f"{now.strftime('%Y-%m-%d')} {time_str}"

    # Assume already a full datetime
    return time_str


def add_alert(due_at: str, message: str) -> int:
    """Insert the alert and return its row ID."""
    with open_db() as conn:
        cursor = conn.execute(
            "INSERT INTO alerts (due_at, message) VALUES (?, ?)",
            (due_at, message),
        )
        return int(cursor.lastrowid or 0)


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: add_alert.py <time> <message>")
        print("  Time formats: HH:MM, YYYY-MM-DD HH:MM, +30m, +2h")
        sys.exit(1)

    time_str = sys.argv[1]
    message = " ".join(sys.argv[2:])

    due_at = parse_time(time_str)
    alert_id = add_alert(due_at, message)
    print(f"Alert {alert_id} set for {due_at}: {message}")


if __name__ == "__main__":
    main()
