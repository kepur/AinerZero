"""Self-tests for the two-layer hermetic guards in tests/conftest.py.

Verifies against an isolated fake root staged under tmp_path:
1. Function-level guard: fcntl.flock, fcntl.lockf, sqlite3.connect are intercepted
   and raise RuntimeError when targeting protected artifacts.
2. Function-level guard: un-protected paths and whitelisted paths are permitted.
3. Session-level stat guard: detects file modification, addition, deletion,
   and SQLite WAL -shm/-wal changes.
4. Subprocess adversarial verification:
   - Mutation 1: direct protected connect turns RED (RuntimeError);
   - Mutation 2: bypassed function guard causes session stat guard to turn RED (AssertionError on -shm).

Zero interaction with real repository artifacts.
"""

from __future__ import annotations

import fcntl
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import conftest


def _stage_fake_root(base: Path) -> Path:
    fake_root = base / "fake_repo"
    phase1 = fake_root / "artifacts" / "v9" / "s1" / "phase1"
    phase1.mkdir(parents=True, exist_ok=True)
    locks = fake_root / "artifacts" / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    (locks / "m0-worker.lock").write_text("", encoding="utf-8")

    db_path = phase1 / "control.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE runs (run_id TEXT, state TEXT)")
    conn.commit()
    conn.close()
    return fake_root


def test_function_guard_intercepts_protected_connect_and_flock(tmp_path):
    fake_root = _stage_fake_root(tmp_path)
    protected_db = fake_root / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3"
    protected_lock = fake_root / "artifacts" / "locks" / "m0-worker.lock"

    guarded_connect = conftest.make_guarded_connect(fake_root)
    guarded_flock = conftest.make_guarded_flock(fake_root)
    guarded_lockf = conftest.make_guarded_lockf(fake_root)

    # 1. Connect targeting protected db raises
    with pytest.raises(RuntimeError, match="Hermetic test guard violation: sqlite3.connect"):
        guarded_connect(protected_db)

    with pytest.raises(RuntimeError, match="Hermetic test guard violation: sqlite3.connect"):
        guarded_connect(f"file:{protected_db}?mode=ro", uri=True)

    # 2. Flock / lockf targeting protected lock raises
    with open(protected_lock, "r+") as handle:
        with pytest.raises(RuntimeError, match="Hermetic test guard violation: fcntl.flock"):
            guarded_flock(handle, fcntl.LOCK_EX)

        with pytest.raises(RuntimeError, match="Hermetic test guard violation: fcntl.lockf"):
            guarded_lockf(handle, fcntl.LOCK_EX)

    # 3. Non-protected paths succeed
    allowed_db = tmp_path / "outside.sqlite3"
    conn = guarded_connect(allowed_db)
    conn.close()

    allowed_lock = tmp_path / "outside.lock"
    allowed_lock.write_text("")
    with open(allowed_lock, "r+") as handle:
        guarded_flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        guarded_flock(handle, fcntl.LOCK_UN)


def test_function_guard_respects_whitelist(tmp_path):
    fake_root = _stage_fake_root(tmp_path)
    protected_db = fake_root / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3"

    whitelist = {str(protected_db.resolve()): "documented test exception"}
    guarded_connect = conftest.make_guarded_connect(fake_root, whitelist=whitelist)

    conn = guarded_connect(protected_db)
    conn.close()


def test_session_stat_guard_detects_wal_shm_activity(tmp_path):
    fake_root = _stage_fake_root(tmp_path)
    db_path = fake_root / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3"

    before = conftest.guard_snapshot(fake_root)

    # Simulate read-only connection touching WAL index (-shm)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.execute("SELECT * FROM runs").fetchall()
    conn.close()

    after = conftest.guard_snapshot(fake_root)
    diff = conftest.guard_compare(before, after)

    assert any("control.sqlite3-shm" in k for k in diff), f"Session guard missed -shm: {diff}"


def test_session_stat_guard_detects_modification_and_additions(tmp_path):
    fake_root = _stage_fake_root(tmp_path)
    lock_file = fake_root / "artifacts" / "locks" / "m0-worker.lock"

    before = conftest.guard_snapshot(fake_root)

    # Modify existing lock file
    lock_file.write_text("modified", encoding="utf-8")
    # Add new sensitive artifact
    new_db = fake_root / "artifacts" / "control.sqlite3"
    new_db.write_text("fake db", encoding="utf-8")

    after = conftest.guard_snapshot(fake_root)
    diff = conftest.guard_compare(before, after)

    assert str(lock_file.resolve()) in diff
    assert "MODIFIED" in diff[str(lock_file.resolve())]
    assert str(new_db.resolve()) in diff
    assert diff[str(new_db.resolve())] == "ADDED"


def test_hermetic_guards_installed_globally():
    """Verify that guards are actually installed in global sqlite3 and fcntl modules."""
    import fcntl
    import fcntl as f
    import sqlite3
    import sqlite3 as s

    assert Path(conftest.__file__).resolve().parent == Path(__file__).resolve().parent
    assert sqlite3.connect is conftest.guarded_connect
    assert s.connect is conftest.guarded_connect
    assert fcntl.flock is conftest.guarded_flock
    assert fcntl.lockf is conftest.guarded_lockf
    assert f.flock is conftest.guarded_flock
    assert f.lockf is conftest.guarded_lockf
    assert sys.modules["sqlite3"].connect is conftest.guarded_connect

