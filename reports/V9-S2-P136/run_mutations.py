#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 ledger snapshot reading (P136).

Executes mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P136-M1: Revert back to directly opening real ledger -> test_g fails (RED) due to SHM / stat modification.
2. P136-M2: Omit copying WAL file -> test_h fails (RED) because uncheckpointed runs in WAL are invisible.

Each mutation is verified RED, byte-restored, and SHA-verified.
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
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P136"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


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

    return sandbox


def run_test_in_sandbox(sandbox: Path, test_name: str) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / "tests" / "v9" / "experiments" / "test_s2_lifecycle.py"),
        "-k",
        test_name,
        "-v",
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
    print("=== P136 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p136_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        worker_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "worker.py"
        orig_worker_content = worker_file.read_text(encoding="utf-8")
        orig_worker_sha = hashlib.sha256(orig_worker_content.encode("utf-8")).hexdigest()

        # Pre-check: clean sandbox must pass both tests
        for tname in [
            "test_g_ledger_read_snapshot_leaves_real_ledger_completely_untouched",
            "test_h_ledger_read_snapshot_reads_completed_run_residing_only_in_wal",
        ]:
            ret_clean, out_clean = run_test_in_sandbox(sandbox, tname)
            if ret_clean != 0:
                print(f"[ERROR] Clean sandbox test {tname} failed:\n", out_clean)
                return 1
            print(f"[PASS] Clean sandbox passed {tname}")

        # -------------------------------------------------------------------------
        # Mutation 1: P136-M1 Revert back to opening real ledger directly
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P136-M1: Direct open of real ledger ---")
        m1_target = """    try:
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
        m1_replacement = """    store = RunStore(p)
    try:
        yield store
    finally:
        store.close()"""

        assert m1_target in orig_worker_content, "m1_target not found in worker.py"
        m1_content = orig_worker_content.replace(m1_target, m1_replacement, 1)
        worker_file.write_text(m1_content, encoding="utf-8")

        ret_m1, out_m1 = run_test_in_sandbox(
            sandbox, "test_g_ledger_read_snapshot_leaves_real_ledger_completely_untouched"
        )
        is_red_m1 = ret_m1 != 0
        print(f"P136-M1 Result: returncode={ret_m1}, is_red={is_red_m1}")
        log_lines.append(f"=== P136-M1 Output ===\nReturnCode: {ret_m1}\n{out_m1}\n")

        # Restore
        worker_file.write_text(orig_worker_content, encoding="utf-8")
        restored_sha_m1 = hashlib.sha256(worker_file.read_bytes()).hexdigest()
        assert restored_sha_m1 == orig_worker_sha, "Worker SHA mismatch after M1 restore!"

        results.append(
            {
                "id": "P136-M1",
                "description": "Revert ledger_read_snapshot to directly opening real ledger without temp dir copy",
                "target_test": "test_g_ledger_read_snapshot_leaves_real_ledger_completely_untouched",
                "returncode": ret_m1,
                "is_red": is_red_m1,
                "restored_sha256": restored_sha_m1,
            }
        )

        # -------------------------------------------------------------------------
        # Mutation 2: P136-M2 Omit copying WAL file
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P136-M2: Omit copying WAL file ---")
        m2_target = """        if wal_path.is_file():
            shutil.copy2(wal_path, temp_wal)"""
        m2_replacement = """        # Intentionally omitted WAL copying
        pass"""

        assert m2_target in orig_worker_content, "m2_target not found in worker.py"
        m2_content = orig_worker_content.replace(m2_target, m2_replacement, 1)
        worker_file.write_text(m2_content, encoding="utf-8")

        ret_m2, out_m2 = run_test_in_sandbox(
            sandbox, "test_h_ledger_read_snapshot_reads_completed_run_residing_only_in_wal"
        )
        is_red_m2 = ret_m2 != 0
        print(f"P136-M2 Result: returncode={ret_m2}, is_red={is_red_m2}")
        log_lines.append(f"=== P136-M2 Output ===\nReturnCode: {ret_m2}\n{out_m2}\n")

        # Restore
        worker_file.write_text(orig_worker_content, encoding="utf-8")
        restored_sha_m2 = hashlib.sha256(worker_file.read_bytes()).hexdigest()
        assert restored_sha_m2 == orig_worker_sha, "Worker SHA mismatch after M2 restore!"

        results.append(
            {
                "id": "P136-M2",
                "description": "Omit copying WAL file during snapshot preparation",
                "target_test": "test_h_ledger_read_snapshot_reads_completed_run_residing_only_in_wal",
                "returncode": ret_m2,
                "is_red": is_red_m2,
                "restored_sha256": restored_sha_m2,
            }
        )

    # Post-check: clean restore
    clean_sha = sha256_file(REAL_ROOT / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "worker.py")
    assert clean_sha == orig_worker_sha

    # Write summary & log
    summary_file = REPORT_DIR / "mutation_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved mutation summary to {summary_file}")

    log_file = REPORT_DIR / "mutation_log.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print(f"Saved mutation log to {log_file}")

    all_passed = all(r["is_red"] for r in results)
    print(f"\nAll mutations RED: {all_passed}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
