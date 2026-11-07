#!/usr/bin/env python3
"""Adversarial mutation verification for hermetic test guards.

Executes mutations entirely on an isolated fake root under a temporary directory:
- Mutation 1: test calling sqlite3.connect on protected artifacts -> intercepted by
  function-level guard (RED: RuntimeError).
- Mutation 2: function-level guard bypassed -> session-level stat guard detects
  control.sqlite3-shm index update and fails session teardown (RED: AssertionError).

Completely decoupled from real repository artifacts; zero bytes written to real artifacts.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[2]


def run_mutation_tests(out_log: Path | None = None) -> int:
    log_lines = []

    def log(msg: str) -> None:
        print(msg)
        log_lines.append(msg)

    log("=== HERMETIC GUARD ADVERSARIAL MUTATION VERIFICATION (FAKE ROOT) ===")

    with tempfile.TemporaryDirectory(prefix="hermetic-mutation-") as tmpdir:
        fake_root = Path(tmpdir) / "fake_repo"
        phase1 = fake_root / "artifacts" / "v9" / "s1" / "phase1"
        phase1.mkdir(parents=True, exist_ok=True)
        locks = fake_root / "artifacts" / "locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / "m0-worker.lock").write_text("", encoding="utf-8")

        # Initialise WAL SQLite ledger
        db_path = phase1 / "control.sqlite3"
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE runs (run_id TEXT, state TEXT)")
        conn.commit()
        conn.close()

        # Write test and conftest targeting fake_root
        tests_dir = fake_root / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)

        conftest_code = f"""
import fcntl, glob, os, sqlite3, sys
from pathlib import Path
from urllib.parse import urlparse
import pytest

sys.dont_write_bytecode = True
FAKE_ROOT = Path({repr(str(fake_root))}).resolve()
HERMETIC_SENSITIVE_PATTERNS = [
    "artifacts/locks/**",
    "artifacts/locks",
    "artifacts/control.sqlite3*",
    "artifacts/v9/**/control.sqlite3*",
    "artifacts/v9/s1/**/*.sqlite3*",
    "artifacts/v9/e1/**",
]

def guard_resolve_path(target):
    if target is None: return None
    if isinstance(target, int):
        try:
            buf = b" " * 1024
            res_buf = fcntl.fcntl(target, 50, buf)
            raw = res_buf.split(b"\\x00", 1)[0].decode("utf-8", "replace")
            if raw: return os.path.realpath(raw)
        except OSError: pass
        return None
    if hasattr(target, "fileno"):
        try: return guard_resolve_path(target.fileno())
        except Exception: return None
    target_str = str(target)
    if not target_str or target_str == ":memory:": return None
    if target_str.startswith("file:"): target_str = urlparse(target_str).path
    try: return os.path.realpath(target_str)
    except Exception: return None

def check_hermetic_access(target, op_name, root=FAKE_ROOT):
    resolved = guard_resolve_path(target)
    if not resolved: return
    art_dir = os.path.realpath(root / "artifacts")
    if resolved == art_dir or resolved.startswith(art_dir + os.sep):
        raise RuntimeError(f"Hermetic test guard violation: {{op_name}} called on protected artifact: {{resolved}}")

_orig_connect = sqlite3.connect
def guarded_connect(database, *args, **kwargs):
    check_hermetic_access(database, "sqlite3.connect")
    return _orig_connect(database, *args, **kwargs)

sqlite3.connect = guarded_connect

def guard_snapshot(root=FAKE_ROOT):
    snapshot = {{}}
    for pattern in HERMETIC_SENSITIVE_PATTERNS:
        full_pattern = str(root / pattern)
        for p in glob.glob(full_pattern, recursive=True):
            try:
                st = os.stat(p)
                snapshot[os.path.realpath(p)] = (st.st_mtime_ns, st.st_size, st.st_ino)
            except OSError: pass
    return snapshot

def guard_compare(before, after):
    diffs = {{}}
    all_keys = set(before.keys()) | set(after.keys())
    for k in sorted(all_keys):
        if k not in before: diffs[k] = "ADDED"
        elif k not in after: diffs[k] = "DELETED"
        elif before[k] != after[k]: diffs[k] = "MODIFIED"
    return diffs

def pytest_sessionstart(session):
    session._hermetic_stat_before = guard_snapshot()

@pytest.fixture(scope="session", autouse=True)
def hermetic_artifacts_guard(request):
    yield
    before = getattr(request.session, "_hermetic_stat_before", {{}})
    after = guard_snapshot()
    diff = guard_compare(before, after)
    assert not diff, f"Hermetic session guard violation: real artifacts modified during test session:\\n{{diff}}"

def pytest_sessionfinish(session, exitstatus):
    before = getattr(session, "_hermetic_stat_before", {{}})
    after = guard_snapshot()
    diff = guard_compare(before, after)
    if diff:
        session.exitstatus = 1
"""
        (tests_dir / "conftest.py").write_text(conftest_code, encoding="utf-8")

        test_code = f"""
import sqlite3
from pathlib import Path

def test_touch_protected_db():
    db = Path({repr(str(db_path))})
    conn = sqlite3.connect(f"file:{{db}}?mode=ro", uri=True)
    try:
        conn.execute("SELECT * FROM runs").fetchall()
    finally:
        conn.close()
"""
        (tests_dir / "test_target.py").write_text(test_code, encoding="utf-8")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(REAL_ROOT / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        pytest_bin = str(REAL_ROOT / ".venv" / "bin" / "pytest")

        # --- Mutation 1: Function-level guard active -> test should FAIL with RuntimeError
        log("\n--- Mutation 1: Running test against protected database with function-level guard active ---")
        run1 = subprocess.run(
            [pytest_bin, str(tests_dir), "-v", "-p", "no:cacheprovider"],
            cwd=str(fake_root), env=env, capture_output=True, text=True
        )
        log(f"Mutation 1 exit code: {run1.returncode} (Expected: non-zero)")
        out1 = run1.stdout + run1.stderr
        assert run1.returncode != 0, f"Mutation 1 unexpectedly passed:\n{out1}"
        assert "Hermetic test guard violation: sqlite3.connect called on protected artifact" in out1
        log("Mutation 1 VERIFIED: caught by function-level guard (RED)")

        # --- Mutation 2: Function-level guard bypassed -> session stat guard should catch -shm change
        log("\n--- Mutation 2: Bypassing function-level guard; testing session-level stat guard ---")
        conftest_bypassed = conftest_code.replace("check_hermetic_access(database, \"sqlite3.connect\")", "# bypassed")
        (tests_dir / "conftest.py").write_text(conftest_bypassed, encoding="utf-8")

        run2 = subprocess.run(
            [pytest_bin, str(tests_dir), "-v", "-p", "no:cacheprovider"],
            cwd=str(fake_root), env=env, capture_output=True, text=True
        )
        log(f"Mutation 2 exit code: {run2.returncode} (Expected: non-zero)")
        out2 = run2.stdout + run2.stderr
        assert run2.returncode != 0, f"Mutation 2 unexpectedly passed:\n{out2}"
        assert "Hermetic session guard violation: real artifacts modified during test session" in out2
        assert "control.sqlite3-shm" in out2
        log("Mutation 2 VERIFIED: caught by session-level stat guard (RED on -shm)")

    log("\nAll mutations verified against isolated fake root. Real repository artifacts were untouched.")

    if out_log is not None:
        out_log.parent.mkdir(parents=True, exist_ok=True)
        out_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        log(f"Logged mutation results to {out_log}")

    return 0


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REAL_ROOT / "reports/test-hermetic-20261106/r2/mutation_log.txt"
    sys.exit(run_mutation_tests(out))
