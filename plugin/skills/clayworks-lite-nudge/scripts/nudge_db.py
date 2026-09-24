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
    - an alerts.db next to these scripts (renamed *.merged after)
    - the script-install skill dir under the same root; left in place, since
      a retained 1.0.x install may still use it
I don't scan old plugin-cache versions: 1.0.x Nudge never worked from a
plugin install (its commands pointed at ~/.claude/skills/...), so no 1.0.x
plugin cache holds reminders.
A store that is corrupt or isn't a Nudge DB gets a one-line diagnostic on
stderr; when I own the file I rename it *.unmergeable (never over an earlier
one) so the data stays on disk and I stop retrying.
"""

from __future__ import annotations

import os
import sqlite3
import stat
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


_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_link(path: Path) -> bool:
    """True for a symlink, and on Windows for any reparse point (an NTFS
    junction too, which Path.is_symlink() doesn't report)."""
    try:
        if path.is_symlink():
            return True
        isjunction = getattr(os.path, "isjunction", None)      # Python 3.12+
        if isjunction is not None and isjunction(path):
            return True
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
        return bool(attrs & _FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def _linked_component(path: Path, stop: Path) -> Path | None:
    """The first linked path from `path` up to (not including) `stop`, if any.

    For a path outside `stop` (an import dir next to a CLAYWORKS_NUDGE_DB you
    chose), I check only the file and its folder: the folders above are your
    layout, and some are links by design (macOS /tmp and /var are).
    """
    inside = stop in path.parents
    candidates = [path, *path.parents] if inside else [path, path.parent]
    for candidate in candidates:
        if candidate == stop or candidate in stop.parents:
            return None
        if _is_link(candidate):
            return candidate
    return None


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
    found.append((root / "skills" / SKILL_NAME / "scripts" / "alerts.db", False))
    unique: dict[str, tuple[Path, bool]] = {}
    for path, rename in found:
        try:
            if not path.is_file() or path.resolve() == db_path.resolve():
                continue
        except OSError:
            continue
        # A linked store (or a linked folder on the way to it) could point at
        # an unrelated database outside the Claude folder; I never import from
        # one, and I say so once on stderr.
        linked = _linked_component(path, root) or next(
            (s for s in (path.with_name(path.name + side) for side in SIDECARS) if _is_link(s)),
            None)
        if linked is not None:
            print(f"clayworks-lite-nudge: I skipped legacy alerts at {path} because {linked} "
                  f"is a symlink or junction; I only import from real files inside your "
                  f"Claude folder.", file=sys.stderr)
            continue
        unique.setdefault(str(path.resolve()), (path, rename))
    return list(unique.values())


# Errors that prove the file itself will never merge: it isn't a SQLite DB,
# its pages are corrupt, or it isn't a Nudge store. Everything else (I/O,
# permissions, a read-only rollback) can clear on its own, so I retry it.
_PERMANENT_MARKERS = (
    "file is not a database",
    "malformed",
    "no such table",
    "no such column",
    "no alerts table",
)


def _classify(exc: sqlite3.Error) -> str:
    """How to treat a failed legacy read.

    "wait": a lock or busy error that clears on its own; retry silently.
    "permanent": proof the file can't ever merge (see _PERMANENT_MARKERS);
        I set it aside.
    "retry": anything else, such as a disk I/O error, a permissions problem,
        or a read-only rollback. It may be persistent, so I say so on stderr,
        but I keep the file where it is and retry, since nothing proves the
        data is bad.
    """
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        return "wait"
    if any(marker in text for marker in _PERMANENT_MARKERS):
        return "permanent"
    return "retry"


def _report_retry(src: Path, reason: str) -> None:
    print(f"clayworks-lite-nudge: I couldn't open legacy alerts at {src} ({reason}); "
          f"I'll try again next time. Check that file's permissions if this repeats.",
          file=sys.stderr)


SIDECARS = ("-journal", "-wal", "-shm")


def _rename_aside(src: Path, suffix: str) -> Path:
    """Rename src to src<suffix>, or src<suffix>.1, .2, ... if that name is taken,
    and carry its SQLite sidecars (-journal, -wal, -shm) to the matching name.

    POSIX rename silently replaces an existing file, so I never reuse a name:
    an earlier set-aside or merged copy stays intact. Moving the sidecars keeps
    a set-aside store recoverable: SQLite looks for `<name>-journal` next to
    the database it opens.
    """
    def taken(candidate: Path) -> bool:
        return candidate.exists() or any(
            candidate.with_name(candidate.name + side).exists() for side in SIDECARS)

    target = src.with_name(src.name + suffix)
    n = 1
    while taken(target):
        target = src.with_name(f"{src.name}{suffix}.{n}")
        n += 1
    src.rename(target)
    for side in SIDECARS:
        sidecar = src.with_name(src.name + side)
        if sidecar.exists():
            sidecar.rename(target.with_name(target.name + side))
    return target


def _set_aside(src: Path, rename: bool, reason: str) -> None:
    """Report a store I can't ever merge, and stop retrying it when I own it."""
    if rename:
        try:
            target = _rename_aside(src, ".unmergeable")
            print(f"clayworks-lite-nudge: I couldn't import legacy alerts from {src} ({reason}); "
                  f"I renamed it to {target.name} so the data stays on disk.",
                  file=sys.stderr)
            return
        except OSError:
            pass
    print(f"clayworks-lite-nudge: I couldn't import legacy alerts from {src} ({reason}).",
          file=sys.stderr)


def _open_source(src: Path, exclusive: bool) -> tuple[sqlite3.Connection, list[tuple]]:
    """Open a legacy store and read every alert row; the caller closes it.

    Errors raised here come from the source file, so the caller can blame it
    safely; nothing here touches the stable DB. I open the source read-write
    (I only ever SELECT from it) because a store that crashed mid-write has a
    hot rollback journal, and SQLite must write to the file to roll that
    transaction back before it can read the committed alerts.

    exclusive=True (for a store I'll rename once merged) holds an EXCLUSIVE
    lock from this read until the caller closes the connection, so an old
    1.0.x process can't commit a row between my read and the rename and
    strand it in the renamed file.
    """
    # timeout=0: a store another process has locked must not stall the hook
    # (it has a short timeout of its own); I just retry it on the next prompt.
    src_conn = sqlite3.connect(str(src), timeout=0, isolation_level=None)
    try:
        if exclusive:
            src_conn.execute("BEGIN EXCLUSIVE")
        has_table = src_conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alerts'"
        ).fetchone()
        if not has_table:
            raise sqlite3.DatabaseError("no alerts table")
        rows = src_conn.execute(
            "SELECT id, due_at, message, created_at, acknowledged FROM alerts ORDER BY id"
        ).fetchall()
    except BaseException:
        src_conn.close()
        raise
    return src_conn, rows


def _merge_rows(conn: sqlite3.Connection, source: str, src_rows: list[tuple]) -> None:
    """Copy not-yet-merged rows into the stable DB, and carry acknowledgments.

    I recognize a row I've already copied by (row id, content), whatever path
    it came from: the installers relocate a store I merged earlier (say, when
    you switch from the plugin back to a script install), and a path-based
    identity would import every row a second time. Two genuinely separate
    stores would need the same row id AND the same due time, message, and
    creation second to collide, which in practice means a copy of one store.
    """
    done = {(sid, fp): dest for sid, fp, dest in conn.execute(
        "SELECT src_id, fingerprint, dest_id FROM merged_rows")}
    with conn:
        for sid, due_at, message, created_at, acknowledged in src_rows:
            fingerprint = f"{due_at}\x1f{message}\x1f{created_at}"
            key = (sid, fingerprint)
            if key in done:
                # Already copied. Carry a later acknowledgment across; I never
                # un-acknowledge a copy.
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


def _merge_legacy(conn: sqlite3.Connection, db_path: Path) -> None:
    """Copy every not-yet-merged row from each legacy store into the open DB.

    I read the source and write the stable DB in separate steps, so a failure
    writing the stable DB (disk full, read-only) never gets blamed on the
    source: the source stays put and I retry next run.
    """
    stop = False
    for src, rename in _legacy_sources(db_path):
        if stop:
            break
        source = str(src.resolve())
        try:
            src_conn, src_rows = _open_source(src, exclusive=rename)
        except sqlite3.Error as exc:
            kind = _classify(exc)
            if kind == "retry":
                _report_retry(src, str(exc))
            elif kind == "permanent":
                _set_aside(src, rename, str(exc))
            continue                     # "wait" and "retry" try again next run
        renamed = False
        try:
            try:
                _merge_rows(conn, source, src_rows)
            except sqlite3.Error as exc:
                print(f"clayworks-lite-nudge: I couldn't write legacy alerts from {src} into "
                      f"{db_path} ({exc}); I left the legacy file in place and I'll retry "
                      f"next time.", file=sys.stderr)
                if _classify(exc) == "wait":
                    # Another process holds the stable DB. Waiting again for
                    # each remaining store could run past the hook's timeout,
                    # so I stop and let the next prompt finish the merge.
                    stop = True
                continue
            # On POSIX I rename while I still hold the EXCLUSIVE lock, so no
            # writer can slip a row in between my read and the rename.
            # Windows won't rename an open file, so there I rename after
            # closing (below); a writer that still has it open makes that
            # rename fail, and the ledger picks up its new rows next run.
            if rename and os.name != "nt":
                try:
                    _rename_aside(src, ".merged")
                    renamed = True
                except OSError:
                    pass
        finally:
            src_conn.close()
        if rename and not renamed and os.name == "nt":
            try:
                _rename_aside(src, ".merged")
            except OSError:
                pass                     # still open elsewhere: the ledger covers reruns


def _refuse_linked_default(db_path: Path) -> None:
    """Refuse a symlinked default DB path before I touch it.

    The installers check this for a script install, but a plugin install runs
    these scripts with no installer preflight. A link at the default
    location (the nudge/ folder, alerts.db, or a SQLite sidecar) would have me
    chmod and write reminders into whatever it points at. A CLAYWORKS_NUDGE_DB
    you set yourself is your layout to choose, so I only guard the default.
    """
    if os.environ.get(ENV_OVERRIDE, "").strip():
        return
    candidates = [db_path.parent.parent, db_path.parent, db_path]
    candidates += [db_path.with_name(db_path.name + side) for side in SIDECARS]
    for candidate in candidates:
        if _is_link(candidate):
            raise OSError(f"I won't use {candidate}: it's a symlink or junction, and it could point "
                          f"outside your Claude folder. Replace it with a real file or folder.")


def init_db() -> Path:
    """Create the DB dir + table if needed, merge legacy stores, tighten perms."""
    db_path = resolve_db_path()
    _refuse_linked_default(db_path)
    # mode applies only to directories this call creates (and respects umask).
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Alert content can be sensitive (e.g. "standup at 9:30 about acquisition
    # negotiation"), so the file is owner-only BEFORE any row lands in it: I
    # create a new DB as 0600 myself, and strip group/other access from an
    # existing one first. The
    # directory may be shared (a CLAYWORKS_NUDGE_DB you chose). No-op
    # semantics on Windows.
    try:
        fd = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    except FileExistsError:
        pass
    except OSError:
        pass                             # sqlite3.connect below reports real problems
    try:
        # Strip group/other bits only; I never add a permission, so a DB you
        # deliberately made read-only stays read-only.
        db_path.chmod(stat.S_IMODE(db_path.stat().st_mode) & 0o700)
    except OSError:
        pass
    # A short busy timeout: if another process is writing the stable DB, the
    # merge waits at most a second (once, see _merge_legacy) so the hook still
    # has time to read and show your alerts.
    conn = sqlite3.connect(db_path, timeout=1)
    try:
        with conn:
            conn.execute(SCHEMA)
            conn.execute(LEDGER_SCHEMA)
        _merge_legacy(conn, db_path)
    finally:
        conn.close()
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
