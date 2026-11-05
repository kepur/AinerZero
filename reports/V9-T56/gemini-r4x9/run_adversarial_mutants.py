#!/usr/bin/env python3
"""Adversarial mutant verification script for ainerzero.V9.T56.

Proves that:
1. Mutant 1 (SHA check removed in da3_calibration_runner.py):
   Fails test_runner_registered_sha_mismatch_refused_via_proposal_flag because proposal SHA mismatch
   is no longer rejected with PreflightError / exit code 2.
2. Mutant 2 (missing/null model allowed in da3_controlled.py):
   Fails test_is_da3_ledger_run_missing_model_refuses because missing model does not raise BenchmarkRefusalError.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
MUTANTS_DIR = REPO_ROOT / "reports" / "V9-T56" / "gemini-r4x9" / "mutants"
LOGS_DIR = REPO_ROOT / "reports" / "V9-T56" / "gemini-r4x9" / "logs"

VENV_PYTEST = REPO_ROOT / ".venv" / "bin" / "pytest"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"


def verify_import_path(mutant_src: Path, module_name: str) -> None:
    code = f"import sys, {module_name}; print({module_name}.__file__)"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{mutant_src}:{env.get('PYTHONPATH', '')}"
    res = subprocess.run([str(VENV_PYTHON), "-c", code], env=env, capture_output=True, text=True, check=True)
    imported_file = res.stdout.strip()
    print(f"Verified import of {module_name}: {imported_file}")
    assert str(mutant_src) in imported_file, f"Expected {mutant_src} in {imported_file}"


def run_mutant_test(
    mutant_name: str,
    mutant_src: Path,
    module_to_check: str,
    test_node: str,
    log_name: str,
) -> bool:
    verify_import_path(mutant_src, module_to_check)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{mutant_src}:{env.get('PYTHONPATH', '')}"

    log_path = LOGS_DIR / log_name
    print(f"=== Testing {mutant_name} against {test_node} ===")
    res = subprocess.run(
        [str(VENV_PYTEST), "-v", test_node],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    output = f"Return Code: {res.returncode}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}\n"
    log_path.write_text(output, encoding="utf-8")
    print(f"Result for {mutant_name}: returncode={res.returncode}")
    if res.returncode == 1:
        print(f"PASS: Mutant turned RED as required (returncode=1, test failed on mutant). Log: {log_path}")
        return True
    else:
        print(f"FAIL: Mutant did not produce test failure (returncode={res.returncode}). Log: {log_path}")
        return False


def main() -> int:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    m1_src = MUTANTS_DIR / "mutant_1_no_sha_check" / "src"
    m2_src = MUTANTS_DIR / "mutant_2_missing_model_allowed" / "src"

    m1_ok = run_mutant_test(
        "Mutant 1 (no SHA check)",
        m1_src,
        "ainerzero.v9.teachers.da3_calibration_runner",
        "tests/test_da3_t56_features.py::test_runner_registered_sha_mismatch_refused_via_proposal_flag",
        "mutant_1_test.log",
    )

    m2_ok = run_mutant_test(
        "Mutant 2 (missing model allowed)",
        m2_src,
        "ainerzero.v9.teachers.da3_controlled",
        "tests/test_da3_t56_features.py::test_is_da3_ledger_run_missing_model_refuses",
        "mutant_2_test.log",
    )

    if m1_ok and m2_ok:
        print("\nALL MUTANT ADVERSARIAL CONTROLS PASSED (BOTH MUTANTS TURNED RED / EXIT CODE 1).")
        return 0
    else:
        print("\nSOME MUTANT CONTROLS FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
