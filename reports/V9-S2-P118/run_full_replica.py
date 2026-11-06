#!/usr/bin/env python3
"""Run full default pure-CPU pytest regression entirely in an isolated replica tree for P118.

- Asserts zero temporary stashing or modifying in real working tree.
- Copies src, tests, configs, contracts, docs, examples, scripts, pyproject.toml into an isolated replica.
- Collects test inventory and executes full default pure-CPU pytest with SIG_DFL.
- Records output to pytest_full.log.
- Verifies real repository artifacts/ stat remains untouched (0 diffs).
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

REAL_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = REAL_ROOT / "reports/V9-S2-P118"


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
        elif list(before[k]) != list(after[k]):
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
    print("=== STARTING FULL REGRESSION IN ISOLATED REPLICA (P118) ===")
    venv_pytest = REAL_ROOT / ".venv" / "bin" / "pytest"
    assert venv_pytest.exists(), f"Virtualenv pytest not found at {venv_pytest}"

    # 1. Snapshot BEFORE replica test on real artifacts
    print("\n[Step 1] Recording pre-test stat of real artifacts/ ...")
    t0 = time.time()
    stat_before = snapshot_artifacts(REAL_ROOT)
    t1 = time.time()
    print(f"Recorded {len(stat_before)} real artifact entries in {t1 - t0:.2f}s.")
    (REPORT_DIR / "artifacts_stat_before.json").write_text(
        json.dumps(stat_before, indent=2, sort_keys=True), encoding="utf-8"
    )

    with tempfile.TemporaryDirectory(prefix="p118-full-replica-") as tmpdir:
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
        (REPORT_DIR / "nodes_after.txt").write_text(collect_res.stdout, encoding="utf-8")
        print("Wrote nodes_after.txt.")

        # Run full pure-CPU suite in replica with SIG_DFL
        print("\n[Step 4] Running full default pure-CPU pytest suite in replica (SIG_DFL) ...")
        pytest_log_path = REPORT_DIR / "pytest_full.log"

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
    (REPORT_DIR / "artifacts_stat_after.json").write_text(
        json.dumps(stat_after, indent=2, sort_keys=True), encoding="utf-8"
    )

    diffs_replica = compare_snapshots(stat_before, stat_after)
    print(f"Replica run real artifacts diff count: {len(diffs_replica)}")
    (REPORT_DIR / "stat_comparison.json").write_text(
        json.dumps({
            "total_before": len(stat_before),
            "total_after": len(stat_after),
            "differences_count": len(diffs_replica),
            "differences": diffs_replica,
        }, indent=2),
        encoding="utf-8"
    )
    assert len(diffs_replica) == 0, f"Real artifacts modified during replica test! Diffs:\n{diffs_replica}"
    print("ZERO real artifact differences confirmed!")


if __name__ == "__main__":
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    main()
