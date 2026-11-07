#!/usr/bin/env python3
"""Run full default pure-CPU regression for ainerzero.V9.P166 review with complete artifacts lstat audit."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

# Reset signal handlers to default
signal.signal(signal.SIGINT, signal.SIG_DFL)
signal.signal(signal.SIGTERM, signal.SIG_DFL)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REVIEW_DIR = REPO_ROOT / "reports" / "V9-S2-W2" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


def snapshot_artifacts_lstat(root: Path) -> dict[str, list[int]]:
    snap: dict[str, list[int]] = {}
    art_dir = root / "artifacts"
    if not art_dir.exists():
        return snap
    # Walk every directory and file
    for dirpath, dirnames, filenames in os.walk(art_dir):
        rel_dir = os.path.relpath(dirpath, root)
        try:
            st = os.lstat(dirpath)
            snap[rel_dir] = [st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino]
        except OSError:
            pass
        for f in filenames:
            full_path = os.path.join(dirpath, f)
            rel_file = os.path.relpath(full_path, root)
            try:
                st = os.lstat(full_path)
                snap[rel_file] = [st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino]
            except OSError:
                pass
    return snap


def main() -> int:
    print(f"=== Starting full pure-CPU regression for P166 review from {REPO_ROOT} ===")
    t0 = time.time()
    before_snap = snapshot_artifacts_lstat(REPO_ROOT)
    print(f"Captured {len(before_snap)} artifact entries with lstat (mtime, ctime, size, ino) before test run.")

    pytest_bin = REPO_ROOT / ".venv" / "bin" / "python"
    log_file = REVIEW_DIR / "pytest_full.log"

    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), PYTHONDONTWRITEBYTECODE="1")
    cmd = [str(pytest_bin), "-m", "pytest", "-v"]
    print(f"Executing: {' '.join(cmd)}")

    with open(log_file, "w", encoding="utf-8") as lf:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:  # type: ignore
            sys.stdout.write(line)
            lf.write(line)
        proc.wait()

    ret = proc.returncode
    t1 = time.time()
    print(f"\nPytest exited with code {ret} in {t1 - t0:.2f}s.")

    after_snap = snapshot_artifacts_lstat(REPO_ROOT)
    print(f"Captured {len(after_snap)} artifact entries after test run.")

    diffs: dict[str, str] = {}
    all_keys = set(before_snap.keys()) | set(after_snap.keys())
    for k in sorted(all_keys):
        if k not in before_snap:
            diffs[k] = "ADDED"
        elif k not in after_snap:
            diffs[k] = "DELETED"
        elif before_snap[k] != after_snap[k]:
            b_m, b_c, b_s, b_i = before_snap[k]
            a_m, a_c, a_s, a_i = after_snap[k]
            diffs[k] = f"MODIFIED (mtime: {b_m}->{a_m}, ctime: {b_c}->{a_c}, size: {b_s}->{a_s}, ino: {b_i}->{a_i})"

    comparison = {
        "total_entries_before": len(before_snap),
        "total_entries_after": len(after_snap),
        "diff_count": len(diffs),
        "diffs": diffs,
        "elapsed_seconds": round(t1 - t0, 2),
        "pytest_returncode": ret,
        "checked_fields": ["mtime_ns", "ctime_ns", "size", "ino"],
    }

    comp_file = REVIEW_DIR / "stat_comparison.json"
    with open(comp_file, "w", encoding="utf-8") as cf:
        json.dump(comparison, cf, indent=2, ensure_ascii=False)
    print(f"Artifacts comparison saved to {comp_file}. Diffs found: {len(diffs)}")

    return ret


if __name__ == "__main__":
    sys.exit(main())
