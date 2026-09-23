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

Versions before 1.1.0 kept alerts.db next to the scripts. On first run, if the
new DB doesn't exist yet, I look for a legacy alerts.db in three places: next
to these scripts, in older versions of this plugin in the plugin cache (a
plugin update runs from a new version dir and leaves the old one behind), and
in the script-install skill dir. I move the most recently modified one to the
new location.
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


SKILL_NAME = "clayworks-lite-nudge"
# Files install.sh / install.ps1 always put in the install root.
_SCRIPT_INSTALL_MARKERS = ("CLAUDE.md.clayworks-template", "settings.example.json")


def _install_root() -> Path | None:
    """The Claude config dir these scripts were installed into, if recognizable.

    Script install: <root>/skills/clayworks-lite-nudge/scripts, where <root>
    holds the installer's template files. Plugin install:
    <root>/plugins/cache/<marketplace>/<plugin>/<version>/skills/clayworks-lite-nudge/scripts.
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
    if any((above / marker).is_file() for marker in _SCRIPT_INSTALL_MARKERS):
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


def _legacy_candidates() -> list[Path]:
    """Pre-1.1.0 alerts.db locations worth migrating, existing ones only."""
    found = [LEGACY_DB_PATH]
    # Plugin cache (<cache>/<marketplace>/<plugin>/<version>/skills/<skill>):
    # sibling version dirs of this plugin.
    ups = SCRIPTS_DIR.parent.parents
    if len(ups) >= 5 and ups[4].name == "cache":
        plugin_dir = ups[2]
        found += plugin_dir.glob(f"*/skills/{SKILL_NAME}/scripts/alerts.db")
    # Script install under the same root (or the default config dir).
    for root in {_install_root() or _config_root(), _config_root()}:
        found.append(root / "skills" / SKILL_NAME / "scripts" / "alerts.db")
    unique: dict[str, Path] = {}
    for path in found:
        try:
            if path.is_file():
                unique.setdefault(str(path.resolve()), path)
        except OSError:
            continue
    return list(unique.values())


def _migrate_legacy(db_path: Path) -> None:
    """Move the newest pre-1.1.0 alerts.db to db_path, once, if safe."""
    if db_path.exists():
        return
    candidates = _legacy_candidates()
    if not candidates:
        return
    try:
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        if newest.resolve() == db_path.resolve():
            return
        shutil.move(str(newest), str(db_path))
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
