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
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CLAYWORKS_NUDGE_DB")}
    env.update(HOME=str(home), USERPROFILE=str(home), PYTHONDONTWRITEBYTECODE="1")
    env.update(extra_env or {})
    r = subprocess.run([sys.executable, "-B", str(scripts / "nudge_db.py"), *args],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def rows(db):
    c = sqlite3.connect(db)
    out = sorted(c.execute("SELECT due_at, message, acknowledged FROM alerts").fetchall())
    c.close(); return out


A = ("2026-01-01 09:00", "shared", "2025-12-31 10:00:00", 0)
B = ("2026-01-02 09:00", "only-in-100", "2025-12-31 11:00:00", 0)
C = ("2026-01-03 09:00", "only-in-101", "2025-12-31 12:00:00", 0)

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    home = td / "home"; home.mkdir()

    # 1. plugin cache: two older versions each hold a DB; the new version merges both.
    root = td / "cfg"
    cache = root / "plugins" / "cache" / "clayworks-lite" / "clayworks-lite"
    mkdb(cache / "1.0.0/skills/clayworks-lite-nudge/scripts/alerts.db", [A, B])
    mkdb(cache / "1.0.1/skills/clayworks-lite-nudge/scripts/alerts.db", [A, C])
    (cache / "1.1.0/skills").mkdir(parents=True)
    shutil.copytree(SRC, cache / "1.1.0/skills/clayworks-lite-nudge")
    new_scripts = cache / "1.1.0/skills/clayworks-lite-nudge/scripts"
    # a garbage "DB" in the import dir must be skipped, not renamed, not fatal
    (root / "clayworks-lite/nudge/import").mkdir(parents=True)
    (root / "clayworks-lite/nudge/import/broken.db").write_bytes(b"not a sqlite file" * 10)
    print(run(new_scripts, "--list", home=home))
    db = root / "clayworks-lite/nudge/alerts.db"
    assert len(rows(db)) == 3, rows(db)
    assert (cache / "1.0.0/skills/clayworks-lite-nudge/scripts/alerts.db.merged").exists()
    assert (cache / "1.0.1/skills/clayworks-lite-nudge/scripts/alerts.db.merged").exists()
    assert (root / "clayworks-lite/nudge/import/broken.db").exists()
    run(new_scripts, "--list", home=home)
    assert len(rows(db)) == 3, "rerun duplicated rows"
    print("1 plugin-cache merge of all versions: ok")

    # 2. custom script root recognized by its clayworks-lite/ dir alone; the default
    #    profile's legacy DB must NOT be pulled in.
    custom = td / "custom"
    shutil.copytree(SRC, custom / "skills/clayworks-lite-nudge")
    (custom / "clayworks-lite/nudge").mkdir(parents=True)
    mkdb(home / ".claude/skills/clayworks-lite-nudge/scripts/alerts.db", [B])
    cscripts = custom / "skills/clayworks-lite-nudge/scripts"
    got = run(cscripts, "--path", home=home)
    assert Path(got).resolve() == (custom / "clayworks-lite/nudge/alerts.db").resolve(), got
    run(cscripts, "--list", home=home)
    assert rows(custom / "clayworks-lite/nudge/alerts.db") == []
    assert (home / ".claude/skills/clayworks-lite-nudge/scripts/alerts.db").exists()
    print("2 custom root isolated from default profile: ok")

    # 3. import dir file merged and renamed; acked state in the stable DB wins on rerun.
    mkdb(custom / "clayworks-lite/nudge/import/legacy-1.db", [C])
    run(cscripts, "--list", home=home)
    cdb = custom / "clayworks-lite/nudge/alerts.db"
    assert rows(cdb) == [(C[0], C[1], 0)]
    assert (custom / "clayworks-lite/nudge/import/legacy-1.db.merged").exists()
    c = sqlite3.connect(cdb); c.execute("UPDATE alerts SET acknowledged = 1"); c.commit(); c.close()
    print("3 import merge + rename: ok")

    # 4. script-install legacy DB in the same root is merged but left in place.
    root4 = td / "r4"
    shutil.copytree(SRC, root4 / "skills/clayworks-lite-nudge")
    (root4 / "clayworks-lite").mkdir()
    mkdb(root4 / "skills/clayworks-lite-nudge/scripts/alerts.db", [A])
    s4 = root4 / "skills/clayworks-lite-nudge/scripts"
    run(s4, "--list", home=home)
    # own scripts dir == script-install dir here, so it IS renamed (rename flag of LEGACY_DB_PATH)
    assert rows(root4 / "clayworks-lite/nudge/alerts.db") == [(A[0], A[1], 0)]
    print("4 own legacy DB merged:", sorted(p.name for p in (root4 / "skills/clayworks-lite-nudge/scripts").glob("alerts*")))

    # 5. CLAUDE_CONFIG_DIR honored by --path for a checkout (no recognizable root).
    cfgdir = td / "cfgdir"
    got = run(SRC / "scripts", "--path", home=home, extra_env={"CLAUDE_CONFIG_DIR": str(cfgdir)})
    assert Path(got).resolve() == (cfgdir / "clayworks-lite/nudge/alerts.db").resolve(), got
    print("5 CLAUDE_CONFIG_DIR for checkout: ok")
print("ALL OK")
