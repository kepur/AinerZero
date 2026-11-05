#!/usr/bin/env python3
"""Master verification runner for V9-T55 (T54 DA3 real-run review)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"

SCRIPTS = [
    ("Step 1: SHA256SUMS.txt Verification", HERE / "check_sha256sums.py"),
    ("Step 2: Registration Chain Verification", HERE / "verify_registration_chain.py"),
    ("Step 3: Central Ledger Verification", HERE / "verify_ledger.py"),
    ("Step 4: Run Integrity & Supervision Verification", HERE / "verify_run_integrity.py"),
    ("Step 5 & 6: Independent Negative Controls & CPU Parity Recalculation", HERE / "recalculate_adverse_and_parity.py"),
    ("Step 7: Adversarial Mutation Tests", HERE / "adversarial_test.py"),
]


def main():
    print("==================================================")
    print("  AINERZERO V9-T55: T54 INDEPENDENT REVIEW SUITE  ")
    print("==================================================")

    all_passed = True
    for title, script_path in SCRIPTS:
        print(f"\n--- Running: {title} ---")
        res = subprocess.run([PYTHON, str(script_path)], capture_output=True, text=True)
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
