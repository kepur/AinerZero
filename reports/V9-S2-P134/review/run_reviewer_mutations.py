#!/usr/bin/env python3
"""Reviewer adversarial mutation runner for V9.P133/P134 (V9.P135).

Performs 3 independent mutations in an isolated sandbox NOT in author's mutation table:
1. REV-M1: Remove train partition explicit scale requirement -> test_train_partition_requires_explicit_scale fails (RED).
2. REV-M2: Remove inter-partition disjointness check -> test_shared_seed_namespace_raises_error fails (RED).
3. REV-M3: Remove non-temporary path restriction in assert_output_root_is_temporary -> test_output_root_under_tmp_path_guard_and_refuses_production fails (RED).
4. REV-M4: Corrupt sha256sums_hash computation -> test_final_partition_written_to_sealed_final_and_never_read_back fails (RED).

Each mutation is run in an isolated sandbox, verified RED, byte-restored, and SHA-verified.
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
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P134" / "review"
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


def run_test_in_sandbox(sandbox: Path, test_name: str | None = None) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / "tests" / "v9" / "experiments" / "test_s2_data_runner.py"),
        "-v",
    ]
    if test_name:
        cmd.extend(["-k", test_name])

    res = subprocess.run(
        cmd,
        cwd=str(sandbox),
        env=env,
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout + "\n" + res.stderr


def main() -> int:
    print("=== Reviewer Adversarial Mutation Runner (P135) ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p135_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        runner_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "data_runner.py"
        orig_content = runner_file.read_text(encoding="utf-8")
        orig_sha = hashlib.sha256(orig_content.encode("utf-8")).hexdigest()

        # Pre-check: clean sandbox must pass all tests
        ret_clean, out_clean = run_test_in_sandbox(sandbox)
        if ret_clean != 0:
            print("[ERROR] Clean sandbox failed:\n", out_clean)
            return 1
        print("[PASS] Clean sandbox passed all 7 tests")

        # -------------------------------------------------------------------------
        # Mutation 1: REV-M1 Remove train partition explicit scale requirement
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation REV-M1: Remove train partition explicit scale requirement ---")
        m1_target = """        if n_worlds is None or episodes_per_world is None:
            raise ValueError(
                "train partition scale (n_worlds and episodes_per_world) must be explicitly provided"
            )
        actual_n_worlds = int(n_worlds)
        actual_episodes_per_world = int(episodes_per_world)"""
        m1_replacement = """        actual_n_worlds = int(n_worlds) if n_worlds is not None else 10
        actual_episodes_per_world = int(episodes_per_world) if episodes_per_world is not None else 2"""

        assert m1_target in orig_content, "m1_target not found"
        m1_content = orig_content.replace(m1_target, m1_replacement, 1)
        runner_file.write_text(m1_content, encoding="utf-8")

        ret_m1, out_m1 = run_test_in_sandbox(sandbox, "test_train_partition_requires_explicit_scale")
        is_red_m1 = ret_m1 != 0
        print(f"REV-M1 Result: returncode={ret_m1}, is_red={is_red_m1}")
        log_lines.append(f"=== REV-M1 Output ===\nReturnCode: {ret_m1}\n{out_m1}\n")

        # Restore
        runner_file.write_text(orig_content, encoding="utf-8")
        assert hashlib.sha256(runner_file.read_bytes()).hexdigest() == orig_sha

        results.append({
            "id": "REV-M1",
            "name": "omit_train_scale_requirement",
            "description": "Remove explicit scale requirement for train partition",
            "target_test": "test_train_partition_requires_explicit_scale",
            "returncode": ret_m1,
            "is_red": is_red_m1,
            "status": "KILLED" if is_red_m1 else "SURVIVED",
        })

        # -------------------------------------------------------------------------
        # Mutation 2: REV-M2 Remove inter-partition disjointness check
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation REV-M2: Remove inter-partition disjointness check ---")
        m2_target = """        # Check disjointness with all existing partitions
        if other_manifests:
            data.assert_partitions_disjoint([manifest_data, *other_manifests])"""
        m2_replacement = """        # Check disjointness omitted
        pass"""

        assert m2_target in orig_content, "m2_target not found"
        m2_content = orig_content.replace(m2_target, m2_replacement, 1)
        runner_file.write_text(m2_content, encoding="utf-8")

        ret_m2, out_m2 = run_test_in_sandbox(sandbox, "test_shared_seed_namespace_raises_error")
        is_red_m2 = ret_m2 != 0
        print(f"REV-M2 Result: returncode={ret_m2}, is_red={is_red_m2}")
        log_lines.append(f"=== REV-M2 Output ===\nReturnCode: {ret_m2}\n{out_m2}\n")

        # Restore
        runner_file.write_text(orig_content, encoding="utf-8")
        assert hashlib.sha256(runner_file.read_bytes()).hexdigest() == orig_sha

        results.append({
            "id": "REV-M2",
            "name": "omit_disjointness_check",
            "description": "Omit calling data.assert_partitions_disjoint against existing partitions",
            "target_test": "test_shared_seed_namespace_raises_error",
            "returncode": ret_m2,
            "is_red": is_red_m2,
            "status": "KILLED" if is_red_m2 else "SURVIVED",
        })

        # -------------------------------------------------------------------------
        # Mutation 3: REV-M3 Remove non-temporary path restriction in assert_output_root_is_temporary
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation REV-M3: Remove non-temporary path restriction ---")
        m3_target = """    if not is_under_temp:
        raise ValueError(
            f"output_root must be located under a temporary path, got: {out_path}"
        )"""
        m3_replacement = """    if False:
        pass"""

        assert m3_target in orig_content, "m3_target not found"
        m3_content = orig_content.replace(m3_target, m3_replacement, 1)
        runner_file.write_text(m3_content, encoding="utf-8")

        ret_m3, out_m3 = run_test_in_sandbox(sandbox, "test_output_root_under_tmp_path_guard_and_refuses_production")
        is_red_m3 = ret_m3 != 0
        print(f"REV-M3 Result: returncode={ret_m3}, is_red={is_red_m3}")
        log_lines.append(f"=== REV-M3 Output ===\nReturnCode: {ret_m3}\n{out_m3}\n")

        # Restore
        runner_file.write_text(orig_content, encoding="utf-8")
        assert hashlib.sha256(runner_file.read_bytes()).hexdigest() == orig_sha

        results.append({
            "id": "REV-M3",
            "name": "omit_non_temp_path_guard",
            "description": "Bypass Rule 2 in assert_output_root_is_temporary allowing non-temporary paths",
            "target_test": "test_output_root_under_tmp_path_guard_and_refuses_production",
            "returncode": ret_m3,
            "is_red": is_red_m3,
            "status": "KILLED" if is_red_m3 else "SURVIVED",
        })

        # -------------------------------------------------------------------------
        # Mutation 4: REV-M4 Corrupt sha256sums_hash computation
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation REV-M4: Corrupt sha256sums_hash computation ---")
        m4_target = """        sums_raw_bytes = sums_file.read_bytes()
        sha256sums_digest = hashlib.sha256(sums_raw_bytes).hexdigest()"""
        m4_replacement = """        sha256sums_digest = "dummy_corrupted_hash_value" """

        assert m4_target in orig_content, "m4_target not found"
        m4_content = orig_content.replace(m4_target, m4_replacement, 1)
        runner_file.write_text(m4_content, encoding="utf-8")

        ret_m4, out_m4 = run_test_in_sandbox(sandbox, "test_final_partition_written_to_sealed_final_and_never_read_back")
        is_red_m4 = ret_m4 != 0
        print(f"REV-M4 Result: returncode={ret_m4}, is_red={is_red_m4}")
        log_lines.append(f"=== REV-M4 Output ===\nReturnCode: {ret_m4}\n{out_m4}\n")

        # Restore
        runner_file.write_text(orig_content, encoding="utf-8")
        assert hashlib.sha256(runner_file.read_bytes()).hexdigest() == orig_sha

        results.append({
            "id": "REV-M4",
            "name": "corrupt_sha256sums_digest",
            "description": "Corrupt sha256sums_digest in result_payload",
            "target_test": "test_final_partition_written_to_sealed_final_and_never_read_back",
            "returncode": ret_m4,
            "is_red": is_red_m4,
            "status": "KILLED" if is_red_m4 else "SURVIVED",
        })

    # Summary and logs
    with open(REPORT_DIR / "reviewer_mutations.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    with open(REPORT_DIR / "reviewer_mutations_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    all_red = all(r["is_red"] for r in results)
    print(f"\nAll reviewer mutations RED: {all_red}")
    return 0 if all_red else 1


if __name__ == "__main__":
    sys.exit(main())
