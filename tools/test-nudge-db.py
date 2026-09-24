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

    # 1. Plugin cache: two older versions each hold a DB; the new version merges
    #    both. Each version kept its own store, so the identical row in each is
    #    two reminders the user created, and both must survive. A corrupt file
    #    in nudge-import/ is set aside with a diagnostic, never fatal.
    root = td / "cfg"
    cache = root / "plugins" / "cache" / "clayworks-lite" / "clayworks-lite"
    mkdb(cache / "1.0.0/skills/clayworks-lite-nudge/scripts/alerts.db", [A, B])
    mkdb(cache / "1.0.1/skills/clayworks-lite-nudge/scripts/alerts.db", [A, C])
    (cache / "1.1.0/skills").mkdir(parents=True)
    shutil.copytree(SRC, cache / "1.1.0/skills/clayworks-lite-nudge")
    new_scripts = cache / "1.1.0/skills/clayworks-lite-nudge/scripts"
    imp = root / "clayworks-lite/nudge/nudge-import"
    imp.mkdir(parents=True)
    (imp / "broken.db").write_bytes(b"not a sqlite file" * 10)
    out, err = run(new_scripts, "--list", home=home)
    db = root / "clayworks-lite/nudge/alerts.db"
    assert len(rows(db)) == 4, rows(db)
    assert (cache / "1.0.0/skills/clayworks-lite-nudge/scripts/alerts.db.merged").exists()
    assert (cache / "1.0.1/skills/clayworks-lite-nudge/scripts/alerts.db.merged").exists()
    assert (imp / "broken.db.unmergeable").exists() and not (imp / "broken.db").exists()
    assert "couldn't import legacy alerts" in err and "broken.db" in err, err
    _, err2 = run(new_scripts, "--list", home=home)
    assert len(rows(db)) == 4, "rerun duplicated rows"
    assert err2 == "", f"set-aside file was retried: {err2}"
    print("1 plugin-cache merge keeps distinct rows; corrupt store set aside: ok")

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

    # 7. An old plugin process recreates its alerts.db after I merged it; the new
    #    file restarts ids at 1. The different row 1 must still come across.
    old = cache / "1.0.1/skills/clayworks-lite-nudge/scripts/alerts.db"
    D = ("2026-01-04 09:00", "made-after-migration", "2026-01-01 08:00:00", 0)
    mkdb(old, [D])                                      # same path, fresh ids
    run(new_scripts, "--list", home=home)
    assert (D[0], D[1], 0) in rows(db) and len(rows(db)) == 5, rows(db)
    print("7 recreated legacy store merged despite reused ids: ok")

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
print("ALL OK")
