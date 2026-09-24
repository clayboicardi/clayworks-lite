"""Scenario tests for the Nudge DB resolver and legacy merge: python3 -B tools/test-nudge-db.py."""
import os, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "plugin" / "skills" / "clayworks-lite-nudge"
SCHEMA = ("CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, due_at TEXT NOT NULL, "
          "message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, "
          "acknowledged INTEGER NOT NULL DEFAULT 0)")


def mkdb(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute(SCHEMA)
    c.executemany("INSERT INTO alerts (due_at, message, created_at, acknowledged) VALUES (?,?,?,?)", rows)
    c.commit(); c.close()


def run(scripts, *args, home, extra_env=None):
    """Run nudge_db.py; return (stdout, stderr). Fails the test on a non-zero exit."""
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CLAYWORKS_NUDGE_DB")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONDONTWRITEBYTECODE="1")
    env.update(extra_env or {})
    r = subprocess.run([sys.executable, "-B", str(scripts / "nudge_db.py"), *args],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip(), r.stderr.strip()


def rows(db):
    c = sqlite3.connect(db)
    out = sorted(c.execute("SELECT due_at, message, acknowledged FROM alerts").fetchall())
    c.close(); return out


def same(a, b):
    return Path(a).resolve() == Path(b).resolve()


A = ("2026-01-01 09:00", "shared", "2025-12-31 10:00:00", 0)
B = ("2026-01-02 09:00", "only-in-100", "2025-12-31 11:00:00", 0)
C = ("2026-01-03 09:00", "only-in-101", "2025-12-31 12:00:00", 0)

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    home = td / "home"; home.mkdir()

    # 1. Plugin install: two stores the installers handed over in nudge-import/
    #    both merge. The same text created at different times is two reminders,
    #    and both survive. A corrupt import is set aside with a
    #    diagnostic, and a second corrupt one never overwrites the first. Old
    #    plugin-cache versions are NOT scanned (1.0.x Nudge never ran there).
    root = td / "cfg"
    cache = root / "plugins" / "cache" / "clayworks-lite" / "clayworks-lite"
    old_cache_db = cache / "1.0.1/skills/clayworks-lite-nudge/scripts/alerts.db"
    mkdb(old_cache_db, [B])
    (cache / "1.1.0/skills").mkdir(parents=True)
    shutil.copytree(SRC, cache / "1.1.0/skills/clayworks-lite-nudge")
    new_scripts = cache / "1.1.0/skills/clayworks-lite-nudge/scripts"
    imp = root / "clayworks-lite/nudge/nudge-import"
    mkdb(imp / "legacy-a.db", [A, B])
    A2 = (A[0], A[1], "2025-12-31 10:05:00", 0)          # same text, created later
    mkdb(imp / "legacy-b.db", [A2, C])
    (imp / "broken.db").write_bytes(b"not a sqlite file" * 10)
    out, err = run(new_scripts, "--list", home=home)
    db = root / "clayworks-lite/nudge/alerts.db"
    assert len(rows(db)) == 4, rows(db)
    assert (imp / "legacy-a.db.merged").exists() and (imp / "legacy-b.db.merged").exists()
    assert old_cache_db.exists() and not old_cache_db.with_name("alerts.db.merged").exists()
    assert (imp / "broken.db.unmergeable").exists() and not (imp / "broken.db").exists()
    assert "couldn't import legacy alerts" in err and "broken.db" in err, err
    _, err2 = run(new_scripts, "--list", home=home)
    assert len(rows(db)) == 4, "rerun duplicated rows"
    assert err2 == "", f"set-aside file was retried: {err2}"
    (imp / "broken.db").write_bytes(b"still not sqlite" * 10)
    run(new_scripts, "--list", home=home)
    assert (imp / "broken.db.unmergeable").read_bytes().startswith(b"not a sqlite file")
    assert (imp / "broken.db.unmergeable.1").read_bytes().startswith(b"still not sqlite")
    print("1 import merge keeps distinct rows; cache not scanned; set-asides never overwritten: ok")

    # 2. Custom script root recognized by its clayworks-lite/ dir alone; the
    #    default profile's legacy DB must NOT be pulled in.
    custom = td / "custom"
    shutil.copytree(SRC, custom / "skills/clayworks-lite-nudge")
    (custom / "clayworks-lite/nudge").mkdir(parents=True)
    mkdb(home / ".claude/skills/clayworks-lite-nudge/scripts/alerts.db", [B])
    cscripts = custom / "skills/clayworks-lite-nudge/scripts"
    got, _ = run(cscripts, "--path", home=home)
    assert same(got, custom / "clayworks-lite/nudge/alerts.db"), got
    run(cscripts, "--list", home=home)
    assert rows(custom / "clayworks-lite/nudge/alerts.db") == []
    assert (home / ".claude/skills/clayworks-lite-nudge/scripts/alerts.db").exists()
    print("2 custom root isolated from default profile: ok")

    # 3. nudge-import file merged and renamed; acked state in the stable DB stays.
    mkdb(custom / "clayworks-lite/nudge/nudge-import/legacy-1.db", [C])
    run(cscripts, "--list", home=home)
    cdb = custom / "clayworks-lite/nudge/alerts.db"
    assert rows(cdb) == [(C[0], C[1], 0)]
    assert (custom / "clayworks-lite/nudge/nudge-import/legacy-1.db.merged").exists()
    c = sqlite3.connect(cdb); c.execute("UPDATE alerts SET acknowledged = 1"); c.commit(); c.close()
    run(cscripts, "--list", home=home)
    assert rows(cdb) == [(C[0], C[1], 1)]
    print("3 nudge-import merge + rename: ok")

    # 4. A retained script-install store (not renamed) merges once; the ledger
    #    stops a rerun from copying it again.
    root4 = td / "r4"
    c4 = root4 / "plugins/cache/clayworks-lite/clayworks-lite/1.1.0/skills"
    c4.mkdir(parents=True)
    shutil.copytree(SRC, c4 / "clayworks-lite-nudge")
    mkdb(root4 / "skills/clayworks-lite-nudge/scripts/alerts.db", [A])
    s4 = c4 / "clayworks-lite-nudge/scripts"
    run(s4, "--list", home=home)
    run(s4, "--list", home=home)
    assert rows(root4 / "clayworks-lite/nudge/alerts.db") == [(A[0], A[1], 0)]
    assert (root4 / "skills/clayworks-lite-nudge/scripts/alerts.db").exists()
    print("4 retained store merged once, left in place: ok")

    # 5. CLAUDE_CONFIG_DIR honored by --path for a checkout (no recognizable root).
    cfgdir = td / "cfgdir"
    got, _ = run(SRC / "scripts", "--path", home=home, extra_env={"CLAUDE_CONFIG_DIR": str(cfgdir)})
    assert same(got, cfgdir / "clayworks-lite/nudge/alerts.db"), got
    print("5 CLAUDE_CONFIG_DIR for checkout: ok")

    # 6. Override DB elsewhere: the installers' fallback nudge-import under the
    #    root still gets merged into the override store.
    root6 = td / "r6"
    shutil.copytree(SRC, root6 / "skills/clayworks-lite-nudge")
    mkdb(root6 / "clayworks-lite/nudge/nudge-import/legacy-2.db", [B])
    override = td / "elsewhere/alerts.db"
    run(root6 / "skills/clayworks-lite-nudge/scripts", "--list", home=home,
        extra_env={"CLAYWORKS_NUDGE_DB": str(override)})
    assert rows(override) == [(B[0], B[1], 0)]
    print("6 fallback nudge-import merged into an override DB: ok")

    # 7. An old 1.0.x process recreates alerts.db next to the scripts after I
    #    merged and renamed it; the new file restarts ids at 1. The different
    #    row 1 must still come across, and the second rename must not replace
    #    the first .merged copy.
    root7 = td / "r7"
    shutil.copytree(SRC, root7 / "skills/clayworks-lite-nudge")
    (root7 / "clayworks-lite/nudge").mkdir(parents=True)
    s7 = root7 / "skills/clayworks-lite-nudge/scripts"
    mkdb(s7 / "alerts.db", [A])
    run(s7, "--list", home=home)
    D = ("2026-01-04 09:00", "made-after-migration", "2026-01-01 08:00:00", 0)
    mkdb(s7 / "alerts.db", [D])                         # same path, fresh ids
    run(s7, "--list", home=home)
    db7 = root7 / "clayworks-lite/nudge/alerts.db"
    assert rows(db7) == sorted([(A[0], A[1], 0), (D[0], D[1], 0)]), rows(db7)
    assert (s7 / "alerts.db.merged").exists() and (s7 / "alerts.db.merged.1").exists()
    print("7 recreated legacy store merged despite reused ids; renames never overwrite: ok")

    # 8. A stable DB I can't write (read-only) must not get the source set
    #    aside; once the DB is writable again the rows come across.
    root8 = td / "r8"
    shutil.copytree(SRC, root8 / "skills/clayworks-lite-nudge")
    s8 = root8 / "skills/clayworks-lite-nudge/scripts"
    (root8 / "clayworks-lite/nudge").mkdir(parents=True)
    run(s8, "--list", home=home)                        # create the stable DB
    db8 = root8 / "clayworks-lite/nudge/alerts.db"
    src8 = root8 / "clayworks-lite/nudge/nudge-import/legacy-9.db"
    mkdb(src8, [C])
    os.chmod(db8, 0o444)
    try:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CLAYWORKS_NUDGE_DB")}
        env.update(HOME=str(home), USERPROFILE=str(home))
        r = subprocess.run([sys.executable, "-B", str(s8 / "nudge_db.py"), "--list"],
                           capture_output=True, text=True, env=env)
        assert src8.exists(), "source was moved even though the write failed"
        assert not src8.with_name(src8.name + ".unmergeable").exists()
        assert "couldn't write legacy alerts" in r.stderr, r.stderr
    finally:
        os.chmod(db8, 0o644)
    run(s8, "--list", home=home)
    assert rows(db8) == [(C[0], C[1], 0)] and src8.with_name(src8.name + ".merged").exists()
    print("8 read-only destination retries without blaming the source: ok")

    # 9. An acknowledgment made later in a retained legacy store (root4 from
    #    scenario 4, never renamed) reaches the copy I fire from.
    legacy4 = root4 / "skills/clayworks-lite-nudge/scripts/alerts.db"
    c = sqlite3.connect(legacy4); c.execute("UPDATE alerts SET acknowledged = 1"); c.commit(); c.close()
    run(s4, "--list", home=home)
    assert rows(root4 / "clayworks-lite/nudge/alerts.db") == [(A[0], A[1], 1)]
    print("9 legacy acknowledgment carried to the stable copy: ok")

    # 10. The dismiss hint shell-quotes its paths: an install root holding `$(...)`
    #     and backticks must come back as exactly the launcher + script arguments.
    import shlex
    root10 = td / "odd $(echo INJECTED) `x` root"
    shutil.copytree(SRC, root10 / "skills/clayworks-lite-nudge")
    (root10 / "clayworks-lite/nudge").mkdir(parents=True)
    s10 = root10 / "skills/clayworks-lite-nudge/scripts"
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CLAYWORKS_NUDGE_DB")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable, "-B", str(s10 / "add_alert.py"), "+0m", "quote check"],
                   capture_output=True, text=True, env=env, check=True)
    out = subprocess.run([sys.executable, "-B", str(s10 / "check_alerts.py")],
                         capture_output=True, text=True, env=env, check=True).stdout
    hint = next(line for line in out.splitlines() if "Dismiss with:" in line)
    cmd = hint.split("Dismiss with: ", 1)[1].rsplit(" <id>)", 1)[0]
    argv = shlex.split(cmd)
    assert argv[0] == "bash" and len(argv) == 3, argv
    assert Path(argv[1]).name == "run-python.sh" and Path(argv[2]).name == "ack_alert.py", argv
    assert "INJECTED" in argv[1] and "$(" in argv[1], argv   # stayed literal inside one argument
    print("10 dismiss hint quoted safely: ok")

    # 11. A legacy store that crashed mid-write carries a hot rollback journal.
    #     SQLite has to roll it back before reading, so the merge must recover
    #     the committed alerts, not set the store aside.
    root11 = td / "r11"
    shutil.copytree(SRC, root11 / "skills/clayworks-lite-nudge")
    imp11 = root11 / "clayworks-lite/nudge/nudge-import"
    hot = imp11 / "legacy-hot.db"
    mkdb(hot, [A])
    crash = (
        "import os, sqlite3, sys\n"
        "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
        "c.execute('PRAGMA journal_mode=DELETE'); c.execute('PRAGMA cache_size=1')\n"
        "c.execute('BEGIN')\n"
        "for i in range(3000):\n"
        "    c.execute('INSERT INTO alerts (due_at, message) VALUES (?, ?)', ('2026-02-01 09:00', 'x' * 200))\n"
        "os._exit(0)\n"                                  # die mid-transaction, journal left behind
    )
    subprocess.run([sys.executable, "-c", crash, str(hot)], check=True)
    assert hot.with_name(hot.name + "-journal").exists(), "test setup: no hot journal"
    _, err11 = run(root11 / "skills/clayworks-lite-nudge/scripts", "--list", home=home)
    assert rows(root11 / "clayworks-lite/nudge/alerts.db") == [(A[0], A[1], 0)], err11
    assert not (imp11 / "legacy-hot.db.unmergeable").exists(), err11
    print("11 hot rollback journal recovered before merge: ok")

    # 12. A legacy store another process holds an exclusive lock on must not
    #     stall the hook (it has a short timeout); I skip it quietly and merge
    #     it on a later run once the lock is gone.
    import time
    root12 = td / "r12"
    shutil.copytree(SRC, root12 / "skills/clayworks-lite-nudge")
    locked = root12 / "clayworks-lite/nudge/nudge-import/legacy-locked.db"
    mkdb(locked, [B])
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sqlite3, sys, time\n"
         "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
         "c.execute('BEGIN EXCLUSIVE'); print('locked', flush=True); time.sleep(30)\n",
         str(locked)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "locked"
        s12 = root12 / "skills/clayworks-lite-nudge/scripts"
        t0 = time.monotonic()
        _, err12 = run(s12, "--list", home=home)
        elapsed = time.monotonic() - t0
        assert elapsed < 3, f"hook stalled {elapsed:.1f}s on a locked store"
        assert locked.exists() and err12 == "", err12       # quiet skip, not set aside
    finally:
        holder.kill(); holder.wait()
    run(s12, "--list", home=home)
    assert rows(root12 / "clayworks-lite/nudge/alerts.db") == [(B[0], B[1], 0)]
    print(f"12 locked store skipped in {elapsed:.1f}s, merged after release: ok")
    # 13. A store I merged in place (a retained script install) that an installer
    #     later relocates into nudge-import/ must not import its rows twice: I
    #     recognize rows by id and content, not by the path they came from.
    root13 = td / "r13"
    c13 = root13 / "plugins/cache/clayworks-lite/clayworks-lite/1.1.0/skills"
    c13.mkdir(parents=True)
    shutil.copytree(SRC, c13 / "clayworks-lite-nudge")
    s13 = c13 / "clayworks-lite-nudge/scripts"
    legacy13 = root13 / "skills/clayworks-lite-nudge/scripts/alerts.db"
    mkdb(legacy13, [A, B])
    run(s13, "--list", home=home)                        # merged in place, left there
    imp13 = root13 / "clayworks-lite/nudge/nudge-import"
    imp13.mkdir(parents=True, exist_ok=True)
    shutil.move(str(legacy13), str(imp13 / "legacy-20260101-000000-1.db"))   # installer relocates it
    run(s13, "--list", home=home)
    assert len(rows(root13 / "clayworks-lite/nudge/alerts.db")) == 2, rows(root13 / "clayworks-lite/nudge/alerts.db")
    print("13 relocated store not imported twice: ok")
    # 14. Another process holds a write lock on the stable DB while two stores
    #     wait to merge: I wait about a second once, stop, and let the next
    #     prompt finish, so the hook stays well under its 10-second timeout.
    root14 = td / "r14"
    shutil.copytree(SRC, root14 / "skills/clayworks-lite-nudge")
    s14 = root14 / "skills/clayworks-lite-nudge/scripts"
    (root14 / "clayworks-lite/nudge").mkdir(parents=True)
    run(s14, "--list", home=home)                         # create the stable DB
    stable14 = root14 / "clayworks-lite/nudge/alerts.db"
    imp14 = root14 / "clayworks-lite/nudge/nudge-import"
    mkdb(imp14 / "one.db", [B]); mkdb(imp14 / "two.db", [C])
    writer = subprocess.Popen(
        [sys.executable, "-c",
         "import sqlite3, sys, time\n"
         "c = sqlite3.connect(sys.argv[1], isolation_level=None)\n"
         "c.execute('BEGIN IMMEDIATE'); print('locked', flush=True); time.sleep(30)\n",
         str(stable14)],
        stdout=subprocess.PIPE, text=True)
    try:
        assert writer.stdout is not None and writer.stdout.readline().strip() == "locked"
        t0 = time.monotonic()
        _, err14 = run(s14, "--list", home=home)
        took = time.monotonic() - t0
        assert took < 4, f"hook took {took:.1f}s behind a locked stable DB"
        assert "couldn't write legacy alerts" in err14, err14
    finally:
        writer.kill(); writer.wait()
    run(s14, "--list", home=home)
    assert len(rows(stable14)) == 2, rows(stable14)
    print(f"14 locked stable DB: one short wait ({took:.1f}s), merged next run: ok")

    # 15. A plugin install runs with no installer preflight, so the runtime itself
    #     must refuse a symlinked default alerts.db instead of chmod-ing and
    #     writing through it. (Needs symlink rights; skipped where the OS denies them.)
    root15 = td / "r15"
    c15 = root15 / "plugins/cache/clayworks-lite/clayworks-lite/1.1.0/skills"
    c15.mkdir(parents=True)
    shutil.copytree(SRC, c15 / "clayworks-lite-nudge")
    (root15 / "clayworks-lite/nudge").mkdir(parents=True)
    outside = td / "outside.db"
    outside.write_bytes(b"not yours")
    try:
        os.symlink(outside, root15 / "clayworks-lite/nudge/alerts.db")
    except (OSError, NotImplementedError):
        print("15 linked default DB refused: skipped (no symlink rights here)")
    else:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CLAYWORKS_NUDGE_DB")}
        env.update(HOME=str(home), USERPROFILE=str(home), PYTHONDONTWRITEBYTECODE="1")
        r15 = subprocess.run([sys.executable, "-B", str(c15 / "clayworks-lite-nudge/scripts/nudge_db.py"), "--list"],
                             capture_output=True, text=True, env=env)
        assert r15.returncode != 0 and "symlink" in r15.stderr, (r15.returncode, r15.stderr)
        assert outside.read_bytes() == b"not yours"
        print("15 linked default DB refused, target untouched: ok")
print("ALL OK")
