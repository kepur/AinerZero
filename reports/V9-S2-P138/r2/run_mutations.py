#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 data runner guard and sealed_final fix (P138 r2).

Executes mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P138-M1: Guard permits all paths under artifacts -> test_p138_other_artifacts_path_e1_rejected fails (RED).
2. P138-M2: Path is not resolved before comparison -> test_p138_symlink_into_e1_artifacts_rejected fails (RED).
3. P138-M3: Revert to reading sealed_final/manifest.json -> test_p138_dev_generation_reads_only_layout_digests_from_sealed_final fails (RED).

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
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P138" / "r2"
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
    print("=== P138 r2 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p138_r2_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        runner_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "data_runner.py"
        orig_content = runner_file.read_text(encoding="utf-8")
        orig_sha = hashlib.sha256(orig_content.encode("utf-8")).hexdigest()

        # Pre-check: clean sandbox must pass all 12 tests
        ret_clean, out_clean = run_test_in_sandbox(sandbox)
        if ret_clean != 0:
            print("[ERROR] Clean sandbox failed:\n", out_clean)
            return 1
        print("[PASS] Clean sandbox passed all 12 tests")

        # -------------------------------------------------------------------------
        # Mutation 1: P138-M1 Guard permits all paths under artifacts
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P138-M1: Allow all paths under artifacts ---")
        m1_target = """    # Rule 2 & 3: Refuse any other path under artifacts
    if out_path == artifacts_root or out_path.is_relative_to(artifacts_root):
        raise ValueError(
            f"output_root cannot point to non-registered artifacts directory: {out_path} (registered is {registered_output})"
        )"""
        m1_replacement = """    # Mutation P138-M1: allow all paths under artifacts
    pass"""

        assert m1_target in orig_content, "m1_target not found in data_runner.py"
        m1_content = orig_content.replace(m1_target, m1_replacement, 1)
        runner_file.write_text(m1_content, encoding="utf-8")

        ret_m1, out_m1 = run_test_in_sandbox(sandbox, "test_p138_other_artifacts_path_e1_rejected")
        is_red_m1 = ret_m1 != 0
        print(f"P138-M1 Result: returncode={ret_m1}, is_red={is_red_m1}")
        log_lines.append(f"=== P138-M1 Output ===\nReturnCode: {ret_m1}\n{out_m1}\n")

        # Restore
        runner_file.write_text(orig_content, encoding="utf-8")
        restored_sha_m1 = hashlib.sha256(runner_file.read_bytes()).hexdigest()
        assert restored_sha_m1 == orig_sha, "Worker SHA mismatch after M1 restore!"

        results.append(
            {
                "id": "P138-M1",
                "name": "permit_all_paths_under_artifacts",
                "description": "Guard permits all paths under artifacts directory (bypasses e1 rejection)",
                "target_test": "test_p138_other_artifacts_path_e1_rejected",
                "returncode": ret_m1,
                "is_red": is_red_m1,
                "status": "KILLED" if is_red_m1 else "SURVIVED",
                "restored_sha256": restored_sha_m1,
            }
        )

        # -------------------------------------------------------------------------
        # Mutation 2: P138-M2 Do not resolve path before comparison
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P138-M2: Do not resolve path before comparison ---")
        m2_target = """    out_path = Path(output_root).resolve()"""
        m2_replacement = """    out_path = Path(output_root)"""

        assert m2_target in orig_content, "m2_target not found in data_runner.py"
        m2_content = orig_content.replace(m2_target, m2_replacement, 1)
        runner_file.write_text(m2_content, encoding="utf-8")

        ret_m2, out_m2 = run_test_in_sandbox(sandbox, "test_p138_symlink_into_e1_artifacts_rejected")
        is_red_m2 = ret_m2 != 0
        print(f"P138-M2 Result: returncode={ret_m2}, is_red={is_red_m2}")
        log_lines.append(f"=== P138-M2 Output ===\nReturnCode: {ret_m2}\n{out_m2}\n")

        # Restore
        runner_file.write_text(orig_content, encoding="utf-8")
        restored_sha_m2 = hashlib.sha256(runner_file.read_bytes()).hexdigest()
        assert restored_sha_m2 == orig_sha, "Worker SHA mismatch after M2 restore!"

        results.append(
            {
                "id": "P138-M2",
                "name": "omit_path_resolve_before_comparison",
                "description": "Guard fails to resolve symlink before checking if under artifacts",
                "target_test": "test_p138_symlink_into_e1_artifacts_rejected",
                "returncode": ret_m2,
                "is_red": is_red_m2,
                "status": "KILLED" if is_red_m2 else "SURVIVED",
                "restored_sha256": restored_sha_m2,
            }
        )

        # -------------------------------------------------------------------------
        # Mutation 3: P138-M3 Revert to reading sealed_final/manifest.json
        # -------------------------------------------------------------------------
        print("\n--- Testing Mutation P138-M3: Revert to reading sealed_final/manifest.json ---")
        m3_target = """            if candidate_name == "sealed_final":
                # For sealed_final, strictly read ONLY LAYOUT_DIGESTS.json without opening manifest.json
                cand_layout = cand_dir / "LAYOUT_DIGESTS.json"
                if cand_layout.is_file():
                    other_manifests.append(
                        json.loads(cand_layout.read_text(encoding="utf-8"))
                    )
            else:
                cand_manifest = cand_dir / "manifest.json"
                if cand_manifest.is_file():
                    other_manifests.append(
                        json.loads(cand_manifest.read_text(encoding="utf-8"))
                    )"""
        m3_replacement = """            # Mutation P138-M3: erroneously read manifest.json for sealed_final too
            cand_manifest = cand_dir / "manifest.json"
            if cand_manifest.is_file():
                other_manifests.append(
                    json.loads(cand_manifest.read_text(encoding="utf-8"))
                )"""

        assert m3_target in orig_content, "m3_target not found in data_runner.py"
        m3_content = orig_content.replace(m3_target, m3_replacement, 1)
        runner_file.write_text(m3_content, encoding="utf-8")

        ret_m3, out_m3 = run_test_in_sandbox(
            sandbox, "test_p138_dev_generation_reads_only_layout_digests_from_sealed_final"
        )
        is_red_m3 = ret_m3 != 0
        print(f"P138-M3 Result: returncode={ret_m3}, is_red={is_red_m3}")
        log_lines.append(f"=== P138-M3 Output ===\nReturnCode: {ret_m3}\n{out_m3}\n")

        # Restore
        runner_file.write_text(orig_content, encoding="utf-8")
        restored_sha_m3 = hashlib.sha256(runner_file.read_bytes()).hexdigest()
        assert restored_sha_m3 == orig_sha, "Worker SHA mismatch after M3 restore!"

        results.append(
            {
                "id": "P138-M3",
                "name": "revert_to_reading_sealed_final_manifest_json",
                "description": "Disjointness check reads sealed_final/manifest.json instead of LAYOUT_DIGESTS.json",
                "target_test": "test_p138_dev_generation_reads_only_layout_digests_from_sealed_final",
                "returncode": ret_m3,
                "is_red": is_red_m3,
                "status": "KILLED" if is_red_m3 else "SURVIVED",
                "restored_sha256": restored_sha_m3,
            }
        )

    # Post-check: clean restore
    clean_sha = sha256_file(REAL_ROOT / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "data_runner.py")
    assert clean_sha == orig_sha

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
