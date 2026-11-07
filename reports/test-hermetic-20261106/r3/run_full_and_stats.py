#!/usr/bin/env python3
"""Run full pure-CPU pytest regression with SIG_DFL, surrounded by real artifacts/ stat audit."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REAL_ROOT = Path(__file__).resolve().parents[3]
R3_DIR = REAL_ROOT / "reports/test-hermetic-20261106/r3"


def snapshot_artifacts(root: Path = REAL_ROOT) -> dict[str, tuple[int, int, int]]:
    art_dir = root / "artifacts"
    snap = {}
    if not art_dir.exists():
        return snap
    for dirpath, dirnames, filenames in os.walk(art_dir):
        for name in dirnames + filenames:
            p = os.path.join(dirpath, name)
            try:
                st = os.stat(p)
                snap[os.path.realpath(p)] = (st.st_mtime_ns, st.st_size, st.st_ino)
            except OSError:
                pass
    return snap


def compare_snapshots(before: dict, after: dict) -> dict[str, str]:
    diffs = {}
    all_keys = set(before.keys()) | set(after.keys())
    for k in sorted(all_keys):
        if k not in before:
            diffs[k] = "ADDED"
        elif k not in after:
            diffs[k] = "DELETED"
        elif before[k] != after[k]:
            b_m, b_s, b_i = before[k]
            a_m, a_s, a_i = after[k]
            details = []
            if b_m != a_m:
                details.append(f"mtime_ns: {b_m} -> {a_m}")
            if b_s != a_s:
                details.append(f"size: {b_s} -> {a_s}")
            if b_i != a_i:
                details.append(f"inode: {b_i} -> {a_i}")
            diffs[k] = "MODIFIED (" + ", ".join(details) + ")"
    return diffs


def main():
    print("=== STARTING FULL REGRESSION & STAT AUDIT (R3) ===")
    venv_pytest = REAL_ROOT / ".venv" / "bin" / "pytest"
    assert venv_pytest.exists(), f"Virtualenv pytest not found at {venv_pytest}"

    # 1. Snapshot BEFORE full test
    print("\n[Step 1] Recording pre-full-test stat of real artifacts/ ...")
    t0 = time.time()
    stat_before = snapshot_artifacts(REAL_ROOT)
    t1 = time.time()
    print(f"Recorded {len(stat_before)} artifact entries in {t1 - t0:.2f}s.")
    (R3_DIR / "artifacts_stat_before.json").write_text(
        json.dumps(stat_before, indent=2, sort_keys=True), encoding="utf-8"
    )

    # 2. Collect node list
    print("\n[Step 2] Collecting test inventory (pytest --collect-only -q) ...")
    collect_res = subprocess.run(
        [str(venv_pytest), "--collect-only", "-q"],
        cwd=str(REAL_ROOT),
        capture_output=True,
        text=True,
    )
    (R3_DIR / "nodes_after.txt").write_text(collect_res.stdout, encoding="utf-8")
    print("Wrote nodes_after.txt.")

    # 3. Run full pure-CPU suite with SIG_DFL
    print("\n[Step 3] Running full default pure-CPU pytest suite (SIG_DFL) ...")
    pytest_log_path = R3_DIR / "pytest_full.log"

    def preexec_fn():
        # Restore default SIGINT handling
        signal.signal(signal.SIGINT, signal.SIG_DFL)

    t_start = time.time()
    proc = subprocess.Popen(
        [str(venv_pytest)],
        cwd=str(REAL_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        preexec_fn=preexec_fn,
    )

    log_lines = []
    for line in iter(proc.stdout.readline, ""):
        sys.stdout.write(line)
        sys.stdout.flush()
        log_lines.append(line)
    proc.stdout.close()
    proc.wait()
    t_end = time.time()
    duration = t_end - t_start

    full_output = "".join(log_lines)
    pytest_log_path.write_text(full_output, encoding="utf-8")
    print(f"\nPytest exited with return code: {proc.returncode} in {duration:.2f}s")

        assert proc.returncode == 0, f"Full pytest suite failed! (return code {proc.returncode})"

    # 4. Snapshot AFTER full test
    print("\n[Step 4] Recording post-full-test stat of real artifacts/ ...")
    stat_after = snapshot_artifacts(REAL_ROOT)
    (R3_DIR / "artifacts_stat_after.json").write_text(
        json.dumps(stat_after, indent=2, sort_keys=True), encoding="utf-8"
    )

    diffs_full = compare_snapshots(stat_before, stat_after)
    print(f"Full suite artifacts diff count: {len(diffs_full)}")
    assert len(diffs_full) == 0, f"Real artifacts modified during full test! Diffs:\n{diffs_full}"

    # 5. Run mutation verification
    print("\n[Step 5] Running adversarial mutations in isolated replica ...")
    mut_py = R3_DIR / "run_mutations.py"
    mut_proc = subprocess.run(
        [sys.executable, str(mut_py),
         "--out-log", str(R3_DIR / "mutation_log.txt"),
         "--json-out", str(R3_DIR / "mutation_summary.json")],
        cwd=str(REAL_ROOT),
        capture_output=True,
        text=True,
    )
    print(mut_proc.stdout)
    if mut_proc.stderr:
        print("Mutation STDERR:\n", mut_proc.stderr)
    assert mut_proc.returncode == 0, f"Mutation verification failed with code {mut_proc.returncode}"

    # 6. Overall stat comparison
    print("\n[Step 6] Final end-to-end stat verification ...")
    stat_final = snapshot_artifacts(REAL_ROOT)
    diffs_total = compare_snapshots(stat_before, stat_final)
    shm_wal_diffs = {k: v for k, v in diffs_total.items() if "-shm" in k or "-wal" in k}

    stat_summary = {
        "total_entries": len(stat_final),
        "diff_count": len(diffs_total),
        "shm_wal_diff_count": len(shm_wal_diffs),
        "diffs": diffs_total,
    }
    (R3_DIR / "stat_comparison.json").write_text(
        json.dumps(stat_summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"End-to-end real artifacts diff count: {len(diffs_total)}")
    assert len(diffs_total) == 0, f"Real artifacts modified overall! Diffs:\n{diffs_total}"

    print("\n=== FULL REGRESSION AND STAT AUDIT COMPLETED SUCCESSFULLY ===")


if __name__ == "__main__":
    main()
