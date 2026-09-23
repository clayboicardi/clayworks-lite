#!/usr/bin/env python3
"""Acknowledge (dismiss) an alert so it no longer fires.

Usage:
    python3 ack_alert.py <alert_id>

Exits 1 if the alert isn't found or the ID isn't a number.
"""

import sys

sys.dont_write_bytecode = True  # keep __pycache__ out of the skill dir
from nudge_db import open_db  # noqa: E402


def ack_alert(alert_id: int) -> bool:
    """Mark the alert as acknowledged. Returns True if the row existed."""
    with open_db() as conn:
        cursor = conn.execute(
            "UPDATE alerts SET acknowledged = 1 WHERE id = ?",
            (alert_id,),
        )
        return cursor.rowcount > 0


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: ack_alert.py <alert_id>")
        sys.exit(1)

    try:
        alert_id = int(sys.argv[1])
    except ValueError:
        print(f"Not an alert ID: {sys.argv[1]!r}")
        sys.exit(1)

    if ack_alert(alert_id):
        print(f"Alert {alert_id} acknowledged")
    else:
        print(f"Alert {alert_id} not found")
        sys.exit(1)


if __name__ == "__main__":
    main()
