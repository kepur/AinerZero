#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 data runner (ainerzero.V9.P133 / P134).

Executes mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P134-M1: Remove duplicate execution check -> test_duplicate_execution_returns_gracefully_and_does_not_overwrite MUST FAIL (RED).
2. P134-M2: Write final to datasets/final/ instead of sealed_final/ -> test_final_partition_written_to_sealed_final_and_never_read_back MUST FAIL (RED).
3. P134-M3: Remove output_root production artifacts check -> test_output_root_under_tmp_path_guard_and_refuses_production MUST FAIL (RED).

All mutations must turn RED, then restore original code byte-for-byte with SHA-256 validation.
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
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P134"
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

    # Copy src, tests, pyproject.toml
    shutil.copytree(REAL_ROOT / "src", sandbox / "src", symlinks=True)
    shutil.copytree(REAL_ROOT / "tests", sandbox / "tests", symlinks=True)
    shutil.copy2(REAL_ROOT / "pyproject.toml", sandbox / "pyproject.toml")

    return sandbox


def run_test_in_sandbox(sandbox: Path, test_filter: str) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / "tests" / "v9" / "experiments" / "test_s2_data_runner.py"),
        "-k",
        test_filter,
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
    print("=== P134 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p134_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        target_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "data_runner.py"
        orig_content = target_file.read_text(encoding="utf-8")
        orig_sha = hashlib.sha256(orig_content.encode("utf-8")).hexdigest()

        # 0. Clean baseline check
        ret_clean, out_clean = run_test_in_sandbox(sandbox, "test_s2_data_runner")
        print(f"Clean sandbox baseline: returncode {ret_clean} (expected 0)")
        if ret_clean != 0:
            print("[ERROR] Clean sandbox baseline failed:\n", out_clean)
            return 1

        mutations = [
            {
                "id": "P134-M1",
                "name": "remove_duplicate_execution_guard",
                "desc": "Bypass check_partition_already_completed in ledger",
                "target_pattern": """    # 3. Duplicate execution check against ledger
    if ledger is not None:
        completed_run_id = check_partition_already_completed(
            ledger, partition=part, experiment_id=experiment_id
        )
        if completed_run_id is not None:
            return {
                "status": "duplicate_execution",
                "partition": part,
                "message": f"Partition {part!r} has already completed in ledger run {completed_run_id}",
                "run_id": completed_run_id,
            }""",
                "replacement": """    # 3. Duplicate execution check bypassed (P134-M1 mutation)
    pass""",
                "test_filter": "test_duplicate_execution_returns_gracefully_and_does_not_overwrite",
            },
            {
                "id": "P134-M2",
                "name": "final_written_to_final_instead_of_sealed_final",
                "desc": "Leave final partition in datasets/final/ instead of renaming to sealed_final",
                "target_pattern": """        # 5. Handle write directory and sealed_final sealing
        if part == "final":
            final_raw_dir = datasets_dir / "final"
            target_part_dir = datasets_dir / "sealed_final"
            if target_part_dir.exists():
                shutil.rmtree(target_part_dir)
            if final_raw_dir.exists():
                final_raw_dir.rename(target_part_dir)
        else:
            target_part_dir = datasets_dir / part""",
                "replacement": """        # 5. Handle write directory: final written to final/ (P134-M2 mutation)
        target_part_dir = datasets_dir / part""",
                "test_filter": "test_final_partition_written_to_sealed_final_and_never_read_back",
            },
            {
                "id": "P134-M3",
                "name": "remove_production_artifacts_guard",
                "desc": "Bypass production artifacts path check in assert_output_root_is_temporary",
                "target_pattern": """    # Rule 1: Refuse any production artifacts directory
    if "artifacts" in out_path.parts:
        raise ValueError(
            f"output_root cannot point to production artifacts: {out_path}"
        )""",
                "replacement": """    # Rule 1: Production artifacts guard removed (P134-M3 mutation)
    pass""",
                "test_filter": "test_output_root_under_tmp_path_guard_and_refuses_production",
            },
        ]

        all_killed = True
        for mut in mutations:
            print(f"\n--- Testing Mutation {mut['id']}: {mut['name']} ---")
            assert mut["target_pattern"] in orig_content, f"Pattern not found for {mut['id']}"

            mutated = orig_content.replace(mut["target_pattern"], mut["replacement"], 1)
            target_file.write_text(mutated, encoding="utf-8")
            mut_sha = sha256_file(target_file)
            print(f"Applied mutation {mut['id']} (SHA: {mut_sha})")

            ret, out = run_test_in_sandbox(sandbox, mut["test_filter"])
            print(f"Pytest returncode: {ret}")
            is_red = (ret != 0)
            status = "KILLED" if is_red else "SURVIVED"

            # Restore original
            target_file.write_text(orig_content, encoding="utf-8")
            restored_sha = sha256_file(target_file)
            assert restored_sha == orig_sha, f"SHA mismatch! {restored_sha} != {orig_sha}"
            print(f"Restored clean file (SHA matches: {restored_sha == orig_sha})")

            failure_line = ""
            for line in out.splitlines():
                if "AssertionError" in line or "FAILED" in line or "assert " in line:
                    failure_line += line.strip() + " | "

            log_entry = (
                f"=== {mut['id']}: {mut['name']} ===\n"
                f"Description: {mut['desc']}\n"
                f"Status: {status} (returncode={ret})\n"
                f"Failure summary: {failure_line[:300]}\n"
                f"Tail output:\n{out[-800:]}\n"
            )
            log_lines.append(log_entry)

            results.append({
                "id": mut["id"],
                "name": mut["name"],
                "desc": mut["desc"],
                "status": status,
                "is_red": is_red,
                "returncode": ret,
                "target_test": mut["test_filter"],
                "sha_restored": (restored_sha == orig_sha),
            })

            if not is_red:
                print(f"[ERROR] Mutation {mut['id']} SURVIVED!")
                all_killed = False
            else:
                print(f"[OK] Mutation {mut['id']} KILLED (RED).")

    summary_file = REPORT_DIR / "mutations.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    log_file = REPORT_DIR / "mutation_log.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nAll mutations tested. Summary written to {summary_file}")
    return 0 if all_killed else 1


if __name__ == "__main__":
    sys.exit(main())
