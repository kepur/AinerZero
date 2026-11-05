#!/usr/bin/env python3
"""Master verification runner for V9-T53 (E18 independent review)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON_EXE = sys.executable

SCRIPTS = [
    ("Step 1: Leaf Diff Analysis", HERE / "leaf_diff.py", PYTHON_EXE),
    ("Step 2: Independent Ledger Recalculation", HERE / "recalculate_ledger.py", PYTHON_EXE),
    ("Step 3 & 4: Numerical & Verbatim Verification", HERE / "verify_consistency.py", PYTHON_EXE),
    ("Step 5: Author check_e18.py Execution", HERE / "run_author_check_e18.py", "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"),
    ("Step 6: Adversarial Mutation Tests", HERE / "adversarial_test.py", PYTHON_EXE),
]


def main():
    print("==================================================")
    print("  AINERZERO V9-T53: E18 INDEPENDENT REVIEW SUITE  ")
    print("==================================================")

    all_passed = True
    for title, script_path, py in SCRIPTS:
        print(f"\n--- Running: {title} ---")
        res = subprocess.run([py, str(script_path)], capture_output=True, text=True)
        print(res.stdout)
        if res.stderr:
            print("STDERR:", res.stderr)
        if res.returncode != 0:
            print(f"FAILED: {title} (exit {res.returncode})")
            all_passed = False
        else:
            print(f"PASSED: {title}")

    print("\n==================================================")
    if all_passed:
        print("OVERALL VERDICT: ALL VERIFICATION CHECKS PASSED")
    else:
        print("OVERALL VERDICT: SOME CHECKS FAILED")
    print("==================================================")
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
