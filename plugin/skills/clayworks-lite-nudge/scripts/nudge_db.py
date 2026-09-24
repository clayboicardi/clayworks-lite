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
the DB, I merge in any legacy store I can find. A `merged_rows` ledger records
each (source, row id) I've copied, so a merge is safe to repeat, two distinct
reminders never collapse into one, and a store I can't read yet (locked) just
waits for the next run. Sources:
    - files the installers dropped into a `nudge-import/` dir, either next to
      the DB or, when the DB override points inside the skill folder, under
      <root>/clayworks-lite/nudge/ (renamed *.merged after)
    - an alerts.db next to these scripts or in an older version of this
      plugin in the plugin cache (a plugin update runs from a new version dir
      and leaves the old one behind); renamed *.merged after
    - the script-install skill dir under the same root; left in place, since
      a retained 1.0.x install may still use it
A store that is corrupt or isn't a Nudge DB gets a one-line diagnostic on
stderr; when I own the file I rename it *.unmergeable so the data stays on
disk and I stop retrying.
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

# One row per legacy row I've copied. The key includes the row's content, not
# just its id: an old plugin process can recreate its alerts.db after I merged
# it, and the new file restarts ids at 1. dest_id points at the copy in
# `alerts`, so an acknowledgment made later in a retained legacy store still
# reaches the copy I fire from.
LEDGER_SCHEMA = """
    CREATE TABLE IF NOT EXISTS merged_rows (
        source TEXT NOT NULL,
        src_id INTEGER NOT NULL,
        fingerprint TEXT NOT NULL,
        dest_id INTEGER,
        PRIMARY KEY (source, src_id, fingerprint)
    )
"""
IMPORT_DIR_NAME = "nudge-import"


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
    root = _install_root() or _config_root()
    found: list[tuple[Path, bool]] = []
    for import_dir in (db_path.parent / IMPORT_DIR_NAME,
                       root / "clayworks-lite" / "nudge" / IMPORT_DIR_NAME):
        if import_dir.is_dir():
            found += [(p, True) for p in sorted(import_dir.glob("*.db"))]
    found.append((LEGACY_DB_PATH, True))
    # Plugin cache (<cache>/<marketplace>/<plugin>/<version>/skills/<skill>):
    # sibling version dirs of this plugin.
    ups = SCRIPTS_DIR.parent.parents
    if len(ups) >= 5 and ups[4].name == "cache":
        found += [(p, True) for p in ups[2].glob(f"*/skills/{SKILL_NAME}/scripts/alerts.db")]
    found.append((root / "skills" / SKILL_NAME / "scripts" / "alerts.db", False))
    unique: dict[str, tuple[Path, bool]] = {}
    for path, rename in found:
        try:
            if path.is_file() and path.resolve() != db_path.resolve():
                unique.setdefault(str(path.resolve()), (path, rename))
        except OSError:
            continue
    return list(unique.values())


def _classify(exc: sqlite3.Error) -> str:
    """How to treat a failed legacy read.

    "wait": a lock or busy error that clears on its own; retry silently.
    "retry": SQLite couldn't open the file (permissions, I/O). It may be
        persistent, so I say so on stderr, but I keep the file where it is
        and retry, since fixing the permissions is enough to recover.
    "permanent": corruption or a non-Nudge DB; set it aside.
    """
    text = str(exc).lower()
    if isinstance(exc, sqlite3.OperationalError):
        if "locked" in text or "busy" in text:
            return "wait"
        if "unable to open" in text:
            return "retry"
    return "permanent"


def _report_retry(src: Path, reason: str) -> None:
    print(f"clayworks-lite-nudge: I couldn't open legacy alerts at {src} ({reason}); "
          f"I'll try again next time. Check that file's permissions if this repeats.",
          file=sys.stderr)


def _set_aside(src: Path, rename: bool, reason: str) -> None:
    """Report a store I can't ever merge, and stop retrying it when I own it."""
    if rename:
        try:
            src.replace(src.with_name(src.name + ".unmergeable"))
            print(f"clayworks-lite-nudge: I couldn't import legacy alerts from {src} ({reason}); "
                  f"I renamed it to {src.name}.unmergeable so the data stays on disk.",
                  file=sys.stderr)
            return
        except OSError:
            pass
    print(f"clayworks-lite-nudge: I couldn't import legacy alerts from {src} ({reason}).",
          file=sys.stderr)


def _read_source(src: Path) -> list[tuple]:
    """Every alert row in a legacy store, read through its own read-only connection.

    Errors raised here come from the source file, so the caller can blame it
    safely; nothing here touches the stable DB.
    """
    src_conn = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)
    try:
        has_table = src_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alerts'"
        ).fetchone()
        if not has_table:
            raise sqlite3.DatabaseError("no alerts table")
        return src_conn.execute(
            "SELECT id, due_at, message, created_at, acknowledged FROM alerts ORDER BY id"
        ).fetchall()
    finally:
        src_conn.close()             # closed before any rename (Windows locks open files)


def _merge_legacy(conn: sqlite3.Connection, db_path: Path) -> None:
    """Copy every not-yet-merged row from each legacy store into the open DB.

    I read the source and write the stable DB in separate steps, so a failure
    writing the stable DB (disk full, read-only) never gets blamed on the
    source: the source stays put and I retry next run.
    """
    for src, rename in _legacy_sources(db_path):
        source = str(src.resolve())
        try:
            src_rows = _read_source(src)
        except sqlite3.Error as exc:
            kind = _classify(exc)
            if kind == "retry":
                _report_retry(src, str(exc))
            elif kind == "permanent":
                _set_aside(src, rename, str(exc))
            continue                     # "wait" and "retry" try again next run
        try:
            done = {(sid, fp): dest for sid, fp, dest in conn.execute(
                "SELECT src_id, fingerprint, dest_id FROM merged_rows WHERE source = ?",
                (source,))}
            with conn:
                for sid, due_at, message, created_at, acknowledged in src_rows:
                    fingerprint = f"{due_at}\x1f{message}\x1f{created_at}"
                    key = (sid, fingerprint)
                    if key in done:
                        # Already copied. Carry a later acknowledgment across;
                        # I never un-acknowledge a copy.
                        if acknowledged and done[key] is not None:
                            conn.execute(
                                "UPDATE alerts SET acknowledged = 1 "
                                "WHERE id = ? AND acknowledged = 0", (done[key],))
                        continue
                    cur = conn.execute(
                        "INSERT INTO alerts (due_at, message, created_at, acknowledged) "
                        "VALUES (?, ?, ?, ?)",
                        (due_at, message, created_at, acknowledged),
                    )
                    conn.execute(
                        "INSERT INTO merged_rows (source, src_id, fingerprint, dest_id) "
                        "VALUES (?, ?, ?, ?)",
                        (source, sid, fingerprint, cur.lastrowid),
                    )
        except sqlite3.Error as exc:
            print(f"clayworks-lite-nudge: I couldn't write legacy alerts from {src} into "
                  f"{db_path} ({exc}); I left the legacy file in place and I'll retry next time.",
                  file=sys.stderr)
            continue
        if rename:
            try:
                src.replace(src.with_name(src.name + ".merged"))
            except OSError:
                pass                     # read-only cache: the ledger covers reruns


def init_db() -> Path:
    """Create the DB dir + table if needed, merge legacy stores, tighten perms."""
    db_path = resolve_db_path()
    # mode applies only to directories this call creates (and respects umask).
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(SCHEMA)
            conn.execute(LEDGER_SCHEMA)
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
