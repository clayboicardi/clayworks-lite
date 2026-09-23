#!/usr/bin/env python3
"""Shared helpers for the Nudge scripts: where the alerts DB lives, the
one-time migration from the old location, and the schema.

The DB lives OUTSIDE the skill directory so it survives plugin updates (the
plugin cache directory changes on every version) and so both install paths
(plugin marketplace and install.sh / install.ps1) share one alert store.

Resolution order:
    1. $CLAYWORKS_NUDGE_DB, if set (full path to the .db file)
    2. <install root>/clayworks-lite/nudge/alerts.db, where the install root
       is the Claude config dir these scripts were installed into: the
       `--claude-dir` of a script install, or the dir above `plugins/` for a
       plugin install
    3. $CLAUDE_CONFIG_DIR/clayworks-lite/nudge/alerts.db, if CLAUDE_CONFIG_DIR is set
    4. ~/.claude/clayworks-lite/nudge/alerts.db

Versions before 1.1.0 kept alerts.db next to the scripts. Every time I open
the DB, I merge in any legacy store I can find and skip rows already present,
so a merge is safe to repeat and a failed read just retries on the next run:
    - files the installers dropped into <DB dir>/import/ (renamed *.merged after)
    - an alerts.db next to these scripts or in an older version of this
      plugin in the plugin cache (a plugin update runs from a new version dir
      and leaves the old one behind); renamed *.merged after
    - the script-install skill dir under the same root; left in place, since
      a retained 1.0.x install may still use it
"""

from __future__ import annotations

import os
import sqlite3
import sys
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


SKILL_NAME = "clayworks-lite-nudge"
# Durable state install.sh / install.ps1 always leave in the install root: the
# DB home (the primary marker) and, as a fallback, the starter templates.
_SCRIPT_INSTALL_MARKERS = ("clayworks-lite", "CLAUDE.md.clayworks-template", "settings.example.json")


def _install_root() -> Path | None:
    """The Claude config dir these scripts were installed into, if recognizable.

    Script install: <root>/skills/clayworks-lite-nudge/scripts, where <root>
    holds the installer's `clayworks-lite/` dir (or its templates). Plugin
    install: <root>/plugins/cache/<marketplace>/<plugin>/<version>/skills/clayworks-lite-nudge/scripts.
    Anything else (a repo checkout, `--plugin-dir`, the marketplace clone)
    returns None so the caller falls back to CLAUDE_CONFIG_DIR / ~/.claude.
    """
    skill_dir = SCRIPTS_DIR.parent
    if skill_dir.name != SKILL_NAME or skill_dir.parent.name != "skills":
        return None
    above = skill_dir.parent.parent
    ups = above.parents
    if len(ups) >= 5 and ups[2].name == "cache" and ups[3].name == "plugins":
        return ups[4]
    if any((above / marker).exists() for marker in _SCRIPT_INSTALL_MARKERS):
        return above
    return None


def _config_root() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"


def resolve_db_path() -> Path:
    """Return the alerts DB path (see module docstring for the order)."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override:
        return Path(override).expanduser()
    base = _install_root() or _config_root()
    return base / "clayworks-lite" / "nudge" / "alerts.db"


def _legacy_sources(db_path: Path) -> list[tuple[Path, bool]]:
    """(path, rename_after_merge) for every legacy store that exists.

    I only look inside the active root, never another profile's config dir.
    """
    found: list[tuple[Path, bool]] = []
    import_dir = db_path.parent / "import"
    if import_dir.is_dir():
        found += [(p, True) for p in sorted(import_dir.glob("*.db"))]
    found.append((LEGACY_DB_PATH, True))
    # Plugin cache (<cache>/<marketplace>/<plugin>/<version>/skills/<skill>):
    # sibling version dirs of this plugin.
    ups = SCRIPTS_DIR.parent.parents
    if len(ups) >= 5 and ups[4].name == "cache":
        found += [(p, True) for p in ups[2].glob(f"*/skills/{SKILL_NAME}/scripts/alerts.db")]
    root = _install_root() or _config_root()
    found.append((root / "skills" / SKILL_NAME / "scripts" / "alerts.db", False))
    unique: dict[str, tuple[Path, bool]] = {}
    for path, rename in found:
        try:
            if path.is_file() and path.resolve() != db_path.resolve():
                unique.setdefault(str(path.resolve()), (path, rename))
        except OSError:
            continue
    return list(unique.values())


def _merge_legacy(conn: sqlite3.Connection, db_path: Path) -> None:
    """Merge rows from every legacy store into the open DB, skipping duplicates."""
    for src, rename in _legacy_sources(db_path):
        try:
            conn.execute("ATTACH DATABASE ? AS legacy", (str(src),))
        except sqlite3.Error:
            continue                     # locked or unreadable: retry next run
        merged = False
        try:
            has_table = conn.execute(
                "SELECT 1 FROM legacy.sqlite_master WHERE type = 'table' AND name = 'alerts'"
            ).fetchone()
            if has_table:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO main.alerts (due_at, message, created_at, acknowledged)
                        SELECT l.due_at, l.message, l.created_at, l.acknowledged
                        FROM legacy.alerts AS l
                        WHERE NOT EXISTS (
                            SELECT 1 FROM main.alerts AS m
                            WHERE m.due_at = l.due_at AND m.message = l.message
                              AND m.created_at = l.created_at)
                        """
                    )
                merged = True
        except sqlite3.Error:
            pass                         # not a Nudge DB, or mid-write: retry next run
        finally:
            try:
                conn.execute("DETACH DATABASE legacy")
            except sqlite3.Error:
                pass
        if merged and rename:
            try:
                src.replace(src.with_name(src.name + ".merged"))
            except OSError:
                pass                     # read-only cache: the duplicate check covers reruns


def init_db() -> Path:
    """Create the DB dir + table if needed, merge legacy stores, tighten perms."""
    db_path = resolve_db_path()
    # mode applies only to directories this call creates (and respects umask).
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(SCHEMA)
        _merge_legacy(conn, db_path)
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


def main(argv: list[str]) -> int:
    """`--path` prints the resolved DB path; `--list` prints pending alerts."""
    if argv[1:] == ["--path"]:
        print(resolve_db_path())
        return 0
    if argv[1:] == ["--list"]:
        with open_db() as conn:
            rows = conn.execute(
                "SELECT id, due_at, message FROM alerts WHERE acknowledged = 0 ORDER BY due_at"
            ).fetchall()
        for alert_id, due_at, message in rows:
            print(f"[{alert_id}] {due_at}: {message}")
        if not rows:
            print("No pending nudges.")
        return 0
    print("usage: nudge_db.py --path | --list", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    sys.exit(main(sys.argv))
