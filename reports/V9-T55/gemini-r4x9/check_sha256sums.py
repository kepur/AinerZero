#!/usr/bin/env python3
"""Verification of SHA256SUMS.txt in V9-T54 and V9-T28/registration."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LOG_FILE = HERE / "logs" / "sha256sums.log"

DIRS_TO_CHECK = [
    REPO / "reports" / "V9-T54",
    REPO / "reports" / "V9-T28" / "registration",
]


def main():
    log = []
    log.append("=== Checking SHA256SUMS.txt Integrity ===")
    all_ok = True

    for d in DIRS_TO_CHECK:
        log.append(f"\nChecking directory: {d}")
        cmd = ["shasum", "-a", "256", "-c", "SHA256SUMS.txt"]
        res = subprocess.run(cmd, cwd=d, capture_output=True, text=True)
        log.append(f"Command: {' '.join(cmd)} in {d}")
        log.append(res.stdout)
        if res.stderr:
            log.append("STDERR: " + res.stderr)
        if res.returncode != 0:
            log.append(f"FAILED in {d} (exit code {res.returncode})")
            all_ok = False
        else:
            log.append(f"PASSED in {d}")

    out_str = "\n".join(log)
    print(out_str)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(out_str + "\n", encoding="utf-8")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
