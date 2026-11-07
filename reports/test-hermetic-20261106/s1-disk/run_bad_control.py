#!/usr/bin/env python3
"""Hermetic Bad Control Experiment for S1 disk_probe injection (ainerzero.V9.A20).

This script:
1. Creates an isolated temporary copy of the test files in /tmp.
2. Runs the S1 test files under simulated 24.9 GiB host disk space:
   (a) WITH the fixture (_hermetic_s1_disk_probe in conftest.py) -> all pass (0 failed).
   (b) WITHOUT the fixture (reverting conftest.py) -> S1 tests turn RED (failed with disk_free_limit).
3. Verifies that explicit injection of low disk_probe (< 50 GiB) continues to refuse.
4. Verifies byte-for-byte SHA256 restoration of all modified files.
5. Saves structured outputs to bad_control_summary.json.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REPORT_DIR = REPO_ROOT / "reports" / "test-hermetic-20261106" / "s1-disk"
CONFTEST_PATH = REPO_ROOT / "tests" / "v9" / "experiments" / "conftest.py"

S1_AFFECTED_FILES = [
    "tests/v9/experiments/test_s1_approval.py",
    "tests/v9/experiments/test_s1_final_eval.py",
    "tests/v9/experiments/test_s1_prereg.py",
    "tests/v9/experiments/test_s1_r12_ordering.py",
    "tests/v9/experiments/test_s1_r14_registration.py",
    "tests/v9/experiments/test_s1_r15_registration.py",
    "tests/v9/experiments/test_s1_r6_deadline.py",
    "tests/v9/experiments/test_s1_r6_entry_guards.py",
    "tests/v9/experiments/test_s1_r6_ledger_anchor.py",
    "tests/v9/experiments/test_s1_r8_completion.py",
    "tests/v9/experiments/test_s1_r8_d_budget.py",
    "tests/v9/experiments/test_s1_r9_shared_experiment.py",
    "tests/v9/experiments/test_s1_storage_layout.py",
    "tests/v9/experiments/test_s1_timing_sequence.py",
    "tests/v9/experiments/test_s1_train_gates.py",
]

def sha256_of_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    print("=== S1 Disk Hermeticity: Bad Control Experiment ===")
    initial_sha = sha256_of_file(CONFTEST_PATH)
    print(f"Initial conftest.py SHA256: {initial_sha}")

    sandbox_dir = Path("/tmp/ainerzero_s1_disk_bad_control")
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    sandbox_dir.mkdir(parents=True, exist_ok=True)

    sandbox_conftest = sandbox_dir / "conftest.py"
    shutil.copy2(CONFTEST_PATH, sandbox_conftest)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src'}:{REPO_ROOT}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    python_bin = str(REPO_ROOT / ".venv" / "bin" / "python")

    # Hook code to simulate host disk having 24.9 GiB free (below 50.0 GiB limit)
    sim_disk_code = (
        "import sys, psutil; "
        "from types import SimpleNamespace; "
        "psutil.disk_usage = lambda p: SimpleNamespace(total=1000*2**30, used=975.1*2**30, free=24.9*2**30, percent=97.5);"
    )

    results = {}

    # Case 1: With hermetic fixture under 24.9 GiB host disk
    print("\n--- Running Case 1: WITH hermetic fixture under simulated 24.9 GiB host disk ---")
    cmd1 = [
        python_bin, "-c",
        f"{sim_disk_code} import pytest; sys.exit(pytest.main({json.dumps(S1_AFFECTED_FILES)} + ['-q']))"
    ]
    p1 = subprocess.run(cmd1, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
    print(f"Case 1 returncode: {p1.returncode}")
    print(f"Case 1 summary: {p1.stdout.strip().splitlines()[-1] if p1.stdout.strip() else ''}")
    results["with_fixture"] = {
        "exit_code": p1.returncode,
        "summary": p1.stdout.strip().splitlines()[-1] if p1.stdout.strip() else "",
        "status": "PASS" if p1.returncode == 0 else "FAIL"
    }

    # Case 2: Bad control: remove the fixture under 24.9 GiB host disk
    print("\n--- Running Case 2: WITHOUT hermetic fixture (Bad Control) under simulated 24.9 GiB host disk ---")
    conftest_content = CONFTEST_PATH.read_text(encoding="utf-8")
    fixture_marker = "@pytest.fixture(autouse=True)\ndef _hermetic_s1_disk_probe"
    assert fixture_marker in conftest_content, "Fixture not found in conftest.py"
    
    parts = conftest_content.split(fixture_marker)
    fixture_body, rest = parts[1].split("\n@pytest.fixture\ndef synthetic_dataset", 1)
    reverted_conftest = parts[0] + "@pytest.fixture\ndef synthetic_dataset" + rest

    CONFTEST_PATH.write_text(reverted_conftest, encoding="utf-8")
    reverted_sha = sha256_of_file(CONFTEST_PATH)
    print(f"Reverted conftest.py SHA256: {reverted_sha}")

    try:
        cmd2 = [
            python_bin, "-c",
            f"{sim_disk_code} import pytest; sys.exit(pytest.main({json.dumps(S1_AFFECTED_FILES)} + ['-q']))"
        ]
        p2 = subprocess.run(cmd2, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
        print(f"Case 2 returncode: {p2.returncode}")
        last_line = p2.stdout.strip().splitlines()[-1] if p2.stdout.strip() else ""
        print(f"Case 2 summary: {last_line}")
        
        failed_count = 0
        failed_tests = []
        for line in p2.stdout.splitlines():
            if line.startswith("FAILED "):
                failed_count += 1
                failed_tests.append(line)
        
        print(f"Case 2 detected failed tests: {failed_count}")
        results["without_fixture_bad_control"] = {
            "exit_code": p2.returncode,
            "summary": last_line,
            "failed_count": failed_count,
            "failed_tests_sample": failed_tests[:5],
            "status": "RED (CONFIRMED)" if p2.returncode != 0 and failed_count >= 38 else "UNEXPECTED"
        }
    finally:
        shutil.copy2(sandbox_conftest, CONFTEST_PATH)
        restored_sha = sha256_of_file(CONFTEST_PATH)
        print(f"\nRestored conftest.py SHA256: {restored_sha}")
        assert restored_sha == initial_sha, f"SHA mismatch! {restored_sha} != {initial_sha}"
        print("Restoration verified: 100% byte-for-byte identical.")

    # Case 3: Explicit rejection test with injected probes
    print("\n--- Running Case 3: Explicit low disk_probe injection (< 50 GiB) ---")
    case3_script = (
        "import sys\n"
        "from ainerzero.v9.experiments.s1 import resource_gate, spec\n"
        "limits = dict(spec.RESOURCE_LIMITS)\n"
        "try:\n"
        "    resource_gate.assert_start(limits, probes={'disk_probe': lambda: 10.0 * resource_gate.GIB})\n"
        "    sys.exit(1)\n"
        "except resource_gate.ResourceGateRefused as exc:\n"
        "    assert any('disk_free_limit' in r for r in exc.reasons)\n"
        "    print('assert_start refused:', exc.reasons)\n"
        "guard = resource_gate.RuntimeGuard(limits, probes={'disk_probe': lambda: 10.0 * resource_gate.GIB})\n"
        "try:\n"
        "    guard.sample(force=True)\n"
        "    sys.exit(1)\n"
        "except resource_gate.ResourceGateRefused as exc:\n"
        "    assert any('disk_free_limit' in r for r in exc.reasons)\n"
        "    print('RuntimeGuard refused:', exc.reasons)\n"
        "sys.exit(0)\n"
    )
    p3 = subprocess.run([python_bin, "-c", case3_script], cwd=str(REPO_ROOT), env=env, capture_output=True, text=True)
    print(f"Case 3 returncode: {p3.returncode}")
    print(p3.stdout.strip())
    results["explicit_rejection"] = {
        "exit_code": p3.returncode,
        "stdout": p3.stdout.strip(),
        "status": "PASS" if p3.returncode == 0 else "FAIL"
    }

    results["restoration_verification"] = {
        "initial_sha256": initial_sha,
        "restored_sha256": restored_sha,
        "match": initial_sha == restored_sha
    }

    out_file = REPORT_DIR / "bad_control_summary.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved bad control summary to {out_file}")

if __name__ == "__main__":
    main()
