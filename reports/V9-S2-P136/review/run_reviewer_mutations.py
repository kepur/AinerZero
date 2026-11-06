#!/usr/bin/env python3
"""Reviewer Adversarial Mutations Runner for V9.P136.

Performs independent adversarial mutations in an isolated sandbox:
1. REV-M1: Omit rmtree in finally (replica temp directory not cleaned up)
   Target: test_replica_directory_cleaned_up -> MUST FAIL (RED / KILLED)
2. REV-M2: Directly open real DB without replica copy
   Target: test_independent_zero_modification -> MUST FAIL (RED / KILLED)
3. REV-M3: Omit copying WAL file during snapshot preparation
   Target: test_independent_wal_visibility -> MUST FAIL (RED / KILLED)

Each mutation is verified to be KILLED (RED), restored, and byte-verified via SHA256.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REAL_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P136" / "review"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
TEST_SCRIPT = REPORT_DIR / "test_independent_zero_modification_and_wal.py"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def setup_sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)

    shutil.copytree(REAL_ROOT / "src", sandbox / "src", symlinks=True)
    shutil.copytree(REAL_ROOT / "tests", sandbox / "tests", symlinks=True)
    shutil.copy2(REAL_ROOT / "pyproject.toml", sandbox / "pyproject.toml")
    shutil.copy2(TEST_SCRIPT, sandbox / "test_independent_review.py")

    return sandbox


def run_test_in_sandbox(sandbox: Path, test_func_name: str) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-c",
        f"import sys; from test_independent_review import {test_func_name}; res = {test_func_name}(); print(res)",
    ]

    res = subprocess.run(
        cmd,
        cwd=str(sandbox),
        env=env,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout + "\n" + res.stderr


def main() -> int:
    print("=== Reviewer Adversarial Mutation Test Suite ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="rev_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Isolated sandbox setup at: {sandbox}")

        worker_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "worker.py"
        orig_worker_content = worker_file.read_text(encoding="utf-8")
        orig_worker_sha = hashlib.sha256(orig_worker_content.encode("utf-8")).hexdigest()

        # Pre-check baseline: all 3 review tests must PASS in clean sandbox
        for tname in [
            "test_independent_zero_modification",
            "test_independent_wal_visibility",
            "test_replica_directory_cleaned_up",
        ]:
            ret_clean, out_clean = run_test_in_sandbox(sandbox, tname)
            if ret_clean != 0:
                print(f"[FAIL] Baseline clean test {tname} failed:\n{out_clean}")
                return 1
            print(f"[PASS] Clean baseline passed for {tname}")

        # -------------------------------------------------------------------------
        # Mutation 1: REV-M1 (副本未清理：finally 中缺少 rmtree)
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation REV-M1: Omit rmtree (leaked replica directory) ---")
        m1_target = "shutil.rmtree(tmp_dir, ignore_errors=True)"
        m1_replacement = "# Intentionally commented out rmtree cleanup\n        pass"
        assert m1_target in orig_worker_content, f"m1_target not found in worker.py"
        worker_file.write_text(orig_worker_content.replace(m1_target, m1_replacement, 1), encoding="utf-8")

        ret_m1, out_m1 = run_test_in_sandbox(sandbox, "test_replica_directory_cleaned_up")
        is_red_m1 = ret_m1 != 0
        print(f"REV-M1 Result: returncode={ret_m1}, is_red={is_red_m1}")
        log_lines.append(f"=== REV-M1 Output ===\nReturnCode: {ret_m1}\n{out_m1}\n")

        # Restore
        worker_file.write_text(orig_worker_content, encoding="utf-8")
        restored_sha_m1 = sha256_file(worker_file)
        assert restored_sha_m1 == orig_worker_sha, "Worker SHA mismatch after REV-M1 restore!"

        results.append({
            "id": "REV-M1",
            "name": "replica_directory_not_cleaned",
            "description": "Omit shutil.rmtree in finally block of ledger_read_snapshot",
            "target_test": "test_replica_directory_cleaned_up",
            "returncode": ret_m1,
            "status": "KILLED" if is_red_m1 else "SURVIVED",
            "is_red": is_red_m1,
            "restored_sha256": restored_sha_m1,
        })

        # -------------------------------------------------------------------------
        # Mutation 2: REV-M2 (直接只读打开实盘主库，不走隔离副本)
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation REV-M2: Direct open of real DB without copy ---")
        m2_target = """    try:
        shutil.copy2(p, temp_db)
        if wal_path.is_file():
            shutil.copy2(wal_path, temp_wal)
        if shm_path.is_file():
            shutil.copy2(shm_path, temp_shm)

        store = RunStore(temp_db)
        try:
            yield store
        finally:
            store.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)"""
        m2_replacement = """    store = RunStore(p)
    try:
        yield store
    finally:
        store.close()"""
        assert m2_target in orig_worker_content, "m2_target not found in worker.py"
        worker_file.write_text(orig_worker_content.replace(m2_target, m2_replacement, 1), encoding="utf-8")

        ret_m2, out_m2 = run_test_in_sandbox(sandbox, "test_independent_zero_modification")
        is_red_m2 = ret_m2 != 0
        print(f"REV-M2 Result: returncode={ret_m2}, is_red={is_red_m2}")
        log_lines.append(f"=== REV-M2 Output ===\nReturnCode: {ret_m2}\n{out_m2}\n")

        # Restore
        worker_file.write_text(orig_worker_content, encoding="utf-8")
        restored_sha_m2 = sha256_file(worker_file)
        assert restored_sha_m2 == orig_worker_sha, "Worker SHA mismatch after REV-M2 restore!"

        results.append({
            "id": "REV-M2",
            "name": "direct_open_without_copy",
            "description": "Directly open real ledger path with RunStore without copying to tempdir",
            "target_test": "test_independent_zero_modification",
            "returncode": ret_m2,
            "status": "KILLED" if is_red_m2 else "SURVIVED",
            "is_red": is_red_m2,
            "restored_sha256": restored_sha_m2,
        })

        # -------------------------------------------------------------------------
        # Mutation 3: REV-M3 (快照时漏掉 WAL 文件)
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation REV-M3: Omit copying WAL file during snapshot ---")
        m3_target = """        if wal_path.is_file():
            shutil.copy2(wal_path, temp_wal)"""
        m3_replacement = """        # Intentionally skipped copying WAL
        pass"""
        assert m3_target in orig_worker_content, "m3_target not found in worker.py"
        worker_file.write_text(orig_worker_content.replace(m3_target, m3_replacement, 1), encoding="utf-8")

        ret_m3, out_m3 = run_test_in_sandbox(sandbox, "test_independent_wal_visibility")
        is_red_m3 = ret_m3 != 0
        print(f"REV-M3 Result: returncode={ret_m3}, is_red={is_red_m3}")
        log_lines.append(f"=== REV-M3 Output ===\nReturnCode: {ret_m3}\n{out_m3}\n")

        # Restore
        worker_file.write_text(orig_worker_content, encoding="utf-8")
        restored_sha_m3 = sha256_file(worker_file)
        assert restored_sha_m3 == orig_worker_sha, "Worker SHA mismatch after REV-M3 restore!"

        results.append({
            "id": "REV-M3",
            "name": "omit_wal_copy",
            "description": "Skip copying WAL file during snapshot creation",
            "target_test": "test_independent_wal_visibility",
            "returncode": ret_m3,
            "status": "KILLED" if is_red_m3 else "SURVIVED",
            "is_red": is_red_m3,
            "restored_sha256": restored_sha_m3,
        })

    # Summary
    summary_file = REPORT_DIR / "reviewer_mutation_summary.json"
    summary_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved reviewer mutation summary to {summary_file}")

    log_file = REPORT_DIR / "reviewer_mutation_log.txt"
    log_file.write_text("\n".join(log_lines), encoding="utf-8")
    print(f"Saved reviewer mutation log to {log_file}")

    all_killed = all(r["is_red"] for r in results)
    print(f"\nAll reviewer mutations KILLED: {all_killed}")
    return 0 if all_killed else 1


if __name__ == "__main__":
    sys.exit(main())
