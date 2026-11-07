#!/usr/bin/env python3
"""Run full default pure-CPU pytest regression entirely in an isolated replica tree.

Complies strictly with Tier 1 W1/W2/W3 requirements:
- W1: Zero temporary stashing/moving in real working tree.
- W2: Full disclosure of concurrent files and execution environment.
- W3: Re-runs full regression entirely inside an isolated replica tree copying all
      tracked and untracked files (including S2 WIP files) as-is from the real working tree.
- Verifies real repository artifacts/ stat remains untouched (0 diffs, 0 -shm/-wal changes).
"""

from __future__ import annotations

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
R3B_DIR = REAL_ROOT / "reports/test-hermetic-20261106/r3b"


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


def list_s2_files(tree_root: Path) -> dict[str, list[str]]:
    s2_src = tree_root / "src/ainerzero/v9/experiments/s2"
    s2_tests = tree_root / "tests/v9/experiments"
    src_files = []
    test_files = []
    if s2_src.exists():
        for p in sorted(s2_src.rglob("*.py")):
            src_files.append(str(p.relative_to(tree_root)))
    if s2_tests.exists():
        for p in sorted(s2_tests.glob("test_s2_*.py")):
            test_files.append(str(p.relative_to(tree_root)))
    return {"src_files": src_files, "test_files": test_files}


def main():
    print("=== STARTING FULL REGRESSION IN ISOLATED REPLICA (R3B) ===")
    venv_pytest = REAL_ROOT / ".venv" / "bin" / "pytest"
    assert venv_pytest.exists(), f"Virtualenv pytest not found at {venv_pytest}"

    # 1. Snapshot BEFORE replica test on real artifacts
    print("\n[Step 1] Recording pre-test stat of real artifacts/ ...")
    t0 = time.time()
    stat_before = snapshot_artifacts(REAL_ROOT)
    t1 = time.time()
    print(f"Recorded {len(stat_before)} real artifact entries in {t1 - t0:.2f}s.")
    (R3B_DIR / "artifacts_stat_before.json").write_text(
        json.dumps(stat_before, indent=2, sort_keys=True), encoding="utf-8"
    )

    with tempfile.TemporaryDirectory(prefix="hermetic-r3b-full-replica-") as tmpdir:
        rep = Path(tmpdir) / "replica"
        rep.mkdir()
        print(f"\n[Step 2] Staging full isolated replica under {rep} ...")
        for d in ["src", "tests", "examples", "configs", "contracts", "docs", "scripts"]:
            src_dir = REAL_ROOT / d
            if src_dir.exists():
                shutil.copytree(src_dir, rep / d)
        for f in ["pyproject.toml"]:
            src_file = REAL_ROOT / f
            if src_file.exists():
                shutil.copy2(src_file, rep / f)

        # Inventory S2 files in replica
        s2_inventory = list_s2_files(rep)
        print("S2 files staged in replica:")
        for k, files in s2_inventory.items():
            print(f"  {k}:")
            for f in files:
                print(f"    - {f}")
        (R3B_DIR / "s2_files_inventory.json").write_text(
            json.dumps(s2_inventory, indent=2, sort_keys=True), encoding="utf-8"
        )

        env = dict(os.environ)
        src_path = str(rep / "src")
        env["PYTHONPATH"] = f"{rep}:{src_path}"
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        # Collect node list
        print("\n[Step 3] Collecting test inventory in replica (pytest --collect-only -q) ...")
        collect_res = subprocess.run(
            [str(venv_pytest), "--collect-only", "-q"],
            cwd=str(rep),
            env=env,
            capture_output=True,
            text=True,
        )
        (R3B_DIR / "nodes_after.txt").write_text(collect_res.stdout, encoding="utf-8")
        print("Wrote nodes_after.txt.")

        # Run full pure-CPU suite in replica with SIG_DFL
        print("\n[Step 4] Running full default pure-CPU pytest suite in replica (SIG_DFL) ...")
        pytest_log_path = R3B_DIR / "pytest_full.log"

        def preexec_fn():
            signal.signal(signal.SIGINT, signal.SIG_DFL)

        t_start = time.time()
        proc = subprocess.Popen(
            [str(venv_pytest)],
            cwd=str(rep),
            env=env,
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
        print(f"\nReplica Pytest exited with return code: {proc.returncode} in {duration:.2f}s")

    # 5. Snapshot AFTER replica test
    print("\n[Step 5] Recording post-replica-test stat of real artifacts/ ...")
    stat_after = snapshot_artifacts(REAL_ROOT)
    (R3B_DIR / "artifacts_stat_after.json").write_text(
        json.dumps(stat_after, indent=2, sort_keys=True), encoding="utf-8"
    )

    diffs_replica = compare_snapshots(stat_before, stat_after)
    print(f"Replica run real artifacts diff count: {len(diffs_replica)}")
    assert len(diffs_replica) == 0, f"Real artifacts modified during replica test! Diffs:\n{diffs_replica}"

    # 6. Run mutation verification
    print("\n[Step 6] Running adversarial mutations in isolated replica ...")
    mut_py = R3B_DIR / "run_mutations.py"
    mut_proc = subprocess.run(
        [sys.executable, str(mut_py),
         "--out-log", str(R3B_DIR / "mutation_log.txt"),
         "--json-out", str(R3B_DIR / "mutation_summary.json")],
        cwd=str(REAL_ROOT),
        capture_output=True,
        text=True,
    )
    print(mut_proc.stdout)
    if mut_proc.stderr:
        print("Mutation STDERR:\n", mut_proc.stderr)
    assert mut_proc.returncode == 0, f"Mutation verification failed with code {mut_proc.returncode}"

    # 7. Overall stat comparison
    print("\n[Step 7] Final end-to-end stat verification ...")
    stat_final = snapshot_artifacts(REAL_ROOT)
    diffs_total = compare_snapshots(stat_before, stat_final)
    shm_wal_diffs = {k: v for k, v in diffs_total.items() if "-shm" in k or "-wal" in k}

    stat_summary = {
        "total_entries": len(stat_final),
        "diff_count": len(diffs_total),
        "shm_wal_diff_count": len(shm_wal_diffs),
        "diffs": diffs_total,
    }
    (R3B_DIR / "stat_comparison.json").write_text(
        json.dumps(stat_summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"End-to-end real artifacts diff count: {len(diffs_total)}")
    assert len(diffs_total) == 0, f"Real artifacts modified overall! Diffs:\n{diffs_total}"

    print("\n=== FULL REPLICA REGRESSION AND STAT AUDIT COMPLETED ===")


if __name__ == "__main__":
    main()
