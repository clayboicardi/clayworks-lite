#!/usr/bin/env python3
"""Shared helpers for the Nudge scripts: where the alerts DB lives, the
one-time migration from the old location, and the schema.

The DB lives OUTSIDE the skill directory so it survives plugin updates (the
plugin cache directory changes on every version) and so both install paths
(plugin marketplace and install.sh / install.ps1) share one alert store.

Resolution order:
    1. $CLAYWORKS_NUDGE_DB, if set (full path to the .db file)
    2. $CLAUDE_CONFIG_DIR/clayworks-lite/nudge/alerts.db, if CLAUDE_CONFIG_DIR is set
    3. ~/.claude/clayworks-lite/nudge/alerts.db

Versions before 1.1.0 kept alerts.db next to these scripts. On first run, if
the new DB doesn't exist yet and a legacy alerts.db sits next to the scripts,
the scripts move it to the new location.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
LEGACY_DB_PATH = SCRIPTS_DIR / "alerts.db"
ENV_OVERRIDE = "CLAYWORKS_NUDGE_DB"

SCHEMA = """
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        due_at TEXT NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        acknowledged INTEGER NOT NULL DEFAULT 0
    )
"""


def resolve_db_path() -> Path:
    """Return the alerts DB path (see module docstring for the order)."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return Path(override).expanduser()
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    base = Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"
    return base / "clayworks-lite" / "nudge" / "alerts.db"


def _migrate_legacy(db_path: Path) -> None:
    """Move a pre-1.1.0 alerts.db from the scripts dir, once, if safe."""
    if db_path.exists() or not LEGACY_DB_PATH.is_file():
        return
    try:
        if LEGACY_DB_PATH.resolve() == db_path.resolve():
            return
        shutil.move(str(LEGACY_DB_PATH), str(db_path))
    except OSError:
        # Best-effort: a read-only plugin cache or a locked file just means
        # the user starts with a fresh DB. The legacy file stays untouched.
        pass


def init_db() -> Path:
    """Create the DB dir + table if needed, migrate legacy data, tighten perms."""
    db_path = resolve_db_path()
    # mode applies only to directories this call creates (and respects umask).
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _migrate_legacy(db_path)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(SCHEMA)
    finally:
        conn.close()
    # Best-effort: alert content can be sensitive (e.g. "standup at 9:30 about
    # acquisition negotiation"). Tighten so it isn't world-readable on shared
    # multi-user systems. No-op semantics on Windows.
    try:
        db_path.chmod(0o600)
    except OSError:
        pass
    return db_path


@contextmanager
def open_db() -> Iterator[sqlite3.Connection]:
    """Yield a connection to the initialized DB; commit on success, always close."""
    conn = sqlite3.connect(init_db())
    try:
        with conn:
            yield conn
    finally:
        conn.close()
