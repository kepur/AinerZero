#!/usr/bin/env python3
"""Adversarial mutant verification script for ainerzero.V9.T56 (r2).

Proves that:
1. Mutant 1 (restores `from ainerzero...` import in da3_calibration_runner.py):
   Fails `test_real_venv_t6_runner_script_execution_without_pythonpath` because running in .venv-t6
   without PYTHONPATH fails with ModuleNotFoundError: No module named 'ainerzero' (exit code 1).
2. Mutant 2 (removes proposal SHA256 check against REGISTERED.json in da3_calibration_runner.py):
   Fails `test_real_venv_t6_runner_script_execution_without_pythonpath` because `--proposal` pointing
   to pre-E18 proposal is NOT rejected by preflight (exit code 0 instead of 2).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
R2_DIR = REPO_ROOT / "reports" / "V9-T56" / "gemini-r4x9" / "r2"
MUTANTS_DIR = R2_DIR / "mutants"
LOGS_DIR = R2_DIR / "logs"

VENV_PYTEST = REPO_ROOT / ".venv" / "bin" / "pytest"
TEST_TARGET = "tests/test_da3_t56_features.py::test_real_venv_t6_runner_script_execution_without_pythonpath"


def run_mutant_test(
    mutant_name: str,
    mutant_script: Path,
    log_name: str,
) -> bool:
    env = os.environ.copy()
    env["DA3_RUNNER_SCRIPT"] = str(mutant_script.resolve())

    log_path = LOGS_DIR / log_name
    print(f"=== Testing {mutant_name} against {TEST_TARGET} ===")
    res = subprocess.run(
        [str(VENV_PYTEST), "-v", TEST_TARGET],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    output = f"Return Code: {res.returncode}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}\n"
    log_path.write_text(output, encoding="utf-8")
    print(f"Result for {mutant_name}: returncode={res.returncode}")
    if res.returncode == 1:
        print(f"PASS: Mutant turned RED as required (returncode=1). Log: {log_path}")
        return True
    else:
        print(f"FAIL: Mutant did not turn RED (returncode={res.returncode}). Log: {log_path}")
        return False


def main() -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    m1_script = (
        MUTANTS_DIR
        / "mutant_1_from_ainerzero_import"
        / "src"
        / "ainerzero"
        / "v9"
        / "teachers"
        / "da3_calibration_runner.py"
    )
    m2_script = (
        MUTANTS_DIR
        / "mutant_2_no_sha_check"
        / "src"
        / "ainerzero"
        / "v9"
        / "teachers"
        / "da3_calibration_runner.py"
    )

    m1_ok = run_mutant_test(
        "Mutant 1 (restored `from ainerzero...` import)",
        m1_script,
        "mutant_1_import_failure.log",
    )

    m2_ok = run_mutant_test(
        "Mutant 2 (removed registration SHA check)",
        m2_script,
        "mutant_2_sha_failure.log",
    )

    if m1_ok and m2_ok:
        print("\nALL R2 MUTANT ADVERSARIAL CONTROLS PASSED (BOTH MUTANTS TURNED RED / EXIT CODE 1).")
        return 0
    else:
        print("\nSOME R2 MUTANT CONTROLS FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
