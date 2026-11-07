#!/usr/bin/env python3
"""Run bad control (坏对照) mutations for AinerZero V9.A22.

Runs in an isolated temporary sandbox:
Copies src, tests, pyproject.toml.
Verifies that:
- imports resolve to the sandbox copy;
- A22-M1: fixture assert改成恒真 -> test_session_fixture_assertion_fails_on_tampered_artifacts turns RED;
- A22-M2: sessionfinish 不置 exitstatus -> test_sessionfinish_sets_exitstatus_on_tampered_artifacts turns RED;
- A22-M3: 子进程不注入守卫 -> test_subprocess_sqlite_connect_intercepted_by_sitecustomize turns RED;
- Every mutation restores 100% byte-for-byte with verified SHA256.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
SANDBOX = Path("/tmp/ainerzero_a22_bad_control")
A22_REPORT_DIR = REPO_ROOT / "reports" / "test-hermetic-20261106" / "A22"


def setup_sandbox() -> None:
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    SANDBOX.mkdir(parents=True)

    print(f"Setting up isolated sandbox at {SANDBOX}...")
    shutil.copytree(REPO_ROOT / "src", SANDBOX / "src")
    shutil.copytree(REPO_ROOT / "tests", SANDBOX / "tests")
    shutil.copy2(REPO_ROOT / "pyproject.toml", SANDBOX / "pyproject.toml")

    # Verify that imports resolve to the sandbox
    verify_cmd = [
        str(PYTHON_BIN),
        "-c",
        f"import sys; sys.path.insert(0, '{SANDBOX / 'src'}'); import ainerzero; assert str(ainerzero.__file__).startswith('{SANDBOX}'), 'Did not resolve to sandbox!'",
    ]
    res = subprocess.run(verify_cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Import resolution check failed: {res.stderr}"
    print("[OK] Imports resolve strictly to sandbox copy.")


def run_pytest(test_target: str) -> tuple[int, str, str]:
    cmd = [
        str(PYTHON_BIN),
        "-m",
        "pytest",
        test_target,
        "-v",
        "--tb=short",
    ]
    env = {
        "PATH": f"{PYTHON_BIN.parent}:/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": f"{SANDBOX / 'src'}",
    }
    p = subprocess.run(cmd, cwd=SANDBOX, env=env, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def main() -> int:
    setup_sandbox()

    conftest_path = SANDBOX / "tests" / "conftest.py"
    orig_bytes = conftest_path.read_bytes()
    orig_sha = hashlib.sha256(orig_bytes).hexdigest()
    print(f"Original conftest.py SHA256: {orig_sha}")

    # Baseline check
    rc, out, err = run_pytest("tests/test_hermetic_guards.py")
    assert rc == 0, f"Baseline tests failed in sandbox:\n{out}\n{err}"
    print("[OK] Baseline: all 8 hermetic guard tests passed.")

    mutation_results = []
    log_lines = []

    # -------------------------------------------------------------------------
    # Mutation A22-M1: fixture assert 改成恒真
    # -------------------------------------------------------------------------
    m1_target = "assert not diff, ("
    m1_repl = "assert True, ("
    assert m1_target in orig_bytes.decode("utf-8"), "m1_target not found in conftest.py"
    m1_code = orig_bytes.decode("utf-8").replace(m1_target, m1_repl, 1)
    conftest_path.write_text(m1_code, encoding="utf-8")

    rc_m1, out_m1, err_m1 = run_pytest(
        "tests/test_hermetic_guards.py::test_session_fixture_assertion_fails_on_tampered_artifacts"
    )
    print(f"A22-M1 returncode: {rc_m1} (expected != 0)")
    assert rc_m1 != 0, "A22-M1 failed to turn RED!"
    assert "FAILED" in out_m1 and "DID NOT RAISE" in out_m1 and "AssertionError" in out_m1

    conftest_path.write_bytes(orig_bytes)
    restored_sha_m1 = hashlib.sha256(conftest_path.read_bytes()).hexdigest()
    assert restored_sha_m1 == orig_sha, "SHA mismatch after restoring M1!"

    mutation_results.append({
        "mutation": "A22-M1",
        "name": "fixture_assert_constant_true",
        "description": "assert_session_stat_clean / fixture assertion changed to 'assert True'",
        "target_test": "tests/test_hermetic_guards.py::test_session_fixture_assertion_fails_on_tampered_artifacts",
        "returncode": rc_m1,
        "turned_red": True,
        "restored_sha_match": True,
        "snippet": [l for l in out_m1.splitlines() if "FAILED" in l or "Failed:" in l][:3],
    })
    log_lines.append(f"=== A22-M1 ===\n{out_m1}\n")

    # -------------------------------------------------------------------------
    # Mutation A22-M2: sessionfinish 不置 exitstatus
    # -------------------------------------------------------------------------
    m2_target = "session.exitstatus = 1"
    m2_repl = "# session.exitstatus = 1 (MUTATION A22-M2: do not set exitstatus)"
    assert m2_target in orig_bytes.decode("utf-8"), "m2_target not found in conftest.py"
    m2_code = orig_bytes.decode("utf-8").replace(m2_target, m2_repl, 1)
    conftest_path.write_text(m2_code, encoding="utf-8")

    rc_m2, out_m2, err_m2 = run_pytest(
        "tests/test_hermetic_guards.py::test_sessionfinish_sets_exitstatus_on_tampered_artifacts"
    )
    print(f"A22-M2 returncode: {rc_m2} (expected != 0)")
    assert rc_m2 != 0, "A22-M2 failed to turn RED!"
    assert "FAILED" in out_m2 and "assert 0 == 1" in out_m2

    conftest_path.write_bytes(orig_bytes)
    restored_sha_m2 = hashlib.sha256(conftest_path.read_bytes()).hexdigest()
    assert restored_sha_m2 == orig_sha, "SHA mismatch after restoring M2!"

    mutation_results.append({
        "mutation": "A22-M2",
        "name": "sessionfinish_no_exitstatus",
        "description": "apply_sessionfinish_exitstatus does not set session.exitstatus = 1",
        "target_test": "tests/test_hermetic_guards.py::test_sessionfinish_sets_exitstatus_on_tampered_artifacts",
        "returncode": rc_m2,
        "turned_red": True,
        "restored_sha_match": True,
        "snippet": [l for l in out_m2.splitlines() if "FAILED" in l or "assert" in l][:3],
    })
    log_lines.append(f"=== A22-M2 ===\n{out_m2}\n")

    # -------------------------------------------------------------------------
    # Mutation A22-M3: 子进程不注入守卫
    # -------------------------------------------------------------------------
    # We mutate conftest.py so it no longer sets PYTHONPATH with _HERMETIC_SITE_DIR
    m3_target = '    os.environ["PYTHONPATH"] = os.pathsep.join([_HERMETIC_SITE_DIR] + _pp_entries)'
    m3_repl = '    pass  # MUTATION A22-M3: bypass sitecustomize injection'
    assert m3_target in orig_bytes.decode("utf-8"), "m3_target not found in conftest.py"
    m3_code = orig_bytes.decode("utf-8").replace(m3_target, m3_repl, 1)
    conftest_path.write_text(m3_code, encoding="utf-8")

    rc_m3, out_m3, err_m3 = run_pytest(
        "tests/test_hermetic_guards.py::test_subprocess_sqlite_connect_intercepted_by_sitecustomize"
    )
    print(f"A22-M3 returncode: {rc_m3} (expected != 0)")
    assert rc_m3 != 0, "A22-M3 failed to turn RED!"
    assert "FAILED" in out_m3

    conftest_path.write_bytes(orig_bytes)
    restored_sha_m3 = hashlib.sha256(conftest_path.read_bytes()).hexdigest()
    assert restored_sha_m3 == orig_sha, "SHA mismatch after restoring M3!"

    mutation_results.append({
        "mutation": "A22-M3",
        "name": "child_subprocess_no_guard_injection",
        "description": "conftest.py does not inject _HERMETIC_SITE_DIR into child PYTHONPATH",
        "target_test": "tests/test_hermetic_guards.py::test_subprocess_sqlite_connect_intercepted_by_sitecustomize",
        "returncode": rc_m3,
        "turned_red": True,
        "restored_sha_match": True,
        "snippet": [l for l in out_m3.splitlines() if "FAILED" in l or "assert" in l][:3],
    })
    log_lines.append(f"=== A22-M3 ===\n{out_m3}\n")

    # Final baseline check
    rc_final, out_final, _ = run_pytest("tests/test_hermetic_guards.py")
    assert rc_final == 0, f"Final baseline check failed: {out_final}"
    assert hashlib.sha256(conftest_path.read_bytes()).hexdigest() == orig_sha

    print("[SUCCESS] All 3 mutations turned RED and restored 100% byte-for-byte!")

    summary_file = A22_REPORT_DIR / "mutations.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(mutation_results, f, indent=2)

    log_file = A22_REPORT_DIR / "mutations.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    return 0


if __name__ == "__main__":
    sys.exit(main())
