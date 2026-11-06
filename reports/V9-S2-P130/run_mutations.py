#!/usr/bin/env python3
"""Adversarial mutation test runner for S2 evaluation perturbation assertions (P130).

Executes mutations in an isolated temporary sandbox containing copies of:
- src/
- tests/
- pyproject.toml

Mutations:
1. P130-M1: Perturbation action count set to 1 (P123 REV-M4 reproduction).
2. P130-M2: Perturbation start step changed to step 10.

Both must fail test_perturb_inserts_at_step_20_and_is_reproducible (RED).
Each mutation is byte-for-byte restored with SHA-256 verification.
Real repository files are never modified.
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
REPORT_DIR = REAL_ROOT / "reports" / "V9-S2-P130"
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


def run_test_in_sandbox(sandbox: Path) -> tuple[int, str]:
    python_bin = REAL_ROOT / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{sandbox / 'src'}:{sandbox}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    cmd = [
        str(python_bin),
        "-m",
        "pytest",
        str(sandbox / "tests" / "v9" / "experiments" / "test_s2_eval.py"),
        "-k",
        "test_perturb_inserts_at_step_20_and_is_reproducible",
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
    print("=== P130 Adversarial Mutation Runner ===")
    results = []
    log_lines = []

    with tempfile.TemporaryDirectory(prefix="p130_mut_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        sandbox = setup_sandbox(tmp_dir)
        print(f"Created isolated sandbox at: {sandbox}")

        # Target file to mutate
        target_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "eval.py"
        orig_content = target_file.read_text(encoding="utf-8")
        orig_sha = hashlib.sha256(orig_content.encode("utf-8")).hexdigest()

        # 0. Pre-check: Clean sandbox must pass
        ret_clean, out_clean = run_test_in_sandbox(sandbox)
        print(f"Clean sandbox test status: {ret_clean} (expected 0)")
        if ret_clean != 0:
            print("[ERROR] Clean sandbox test failed:\n", out_clean)
            return 1

        mutations = [
            {
                "id": "P130-M1",
                "name": "perturb_count_one",
                "desc": "Perturbation action count set to 1 instead of 5",
                "target_pattern": 'n_perturb_actions = int(perturb_spec.get("n_random_actions", 5))',
                "replacement": 'n_perturb_actions = 1  # P130-M1 mutation',
                "expected_fail_test": "tests/v9/experiments/test_s2_eval.py::test_perturb_inserts_at_step_20_and_is_reproducible",
            },
            {
                "id": "P130-M2",
                "name": "perturb_start_step_10",
                "desc": "Perturbation trigger step changed from step 20 to step 10",
                "target_pattern": 'perturb_at_step = int(perturb_spec.get("at_step", 20))',
                "replacement": 'perturb_at_step = 10  # P130-M2 mutation',
                "expected_fail_test": "tests/v9/experiments/test_s2_eval.py::test_perturb_inserts_at_step_20_and_is_reproducible",
            },
        ]

        for mut in mutations:
            print(f"\n--- Testing Mutation {mut['id']}: {mut['name']} ---")
            assert mut["target_pattern"] in orig_content, f"Pattern not found: {mut['target_pattern']}"

            mutated_content = orig_content.replace(mut["target_pattern"], mut["replacement"])
            target_file.write_text(mutated_content, encoding="utf-8")
            mut_sha = sha256_file(target_file)
            print(f"Applied mutation. Target SHA: {mut_sha}")

            ret, out = run_test_in_sandbox(sandbox)
            print(f"Pytest returncode: {ret}")
            is_red = (ret != 0)

            # Restore original content
            target_file.write_text(orig_content, encoding="utf-8")
            restored_sha = sha256_file(target_file)
            assert restored_sha == orig_sha, f"SHA mismatch after restore! {restored_sha} != {orig_sha}"
            print(f"Restored original file. SHA matches: {restored_sha == orig_sha}")

            log_entry = (
                f"=== {mut['id']}: {mut['name']} ===\n"
                f"Description: {mut['desc']}\n"
                f"Returncode: {ret} (is_red={is_red})\n"
                f"Output snippet:\n{out[-800:]}\n"
            )
            log_lines.append(log_entry)

            results.append({
                "id": mut["id"],
                "name": mut["name"],
                "desc": mut["desc"],
                "expected_fail_test": mut["expected_fail_test"],
                "returncode": ret,
                "is_red": is_red,
                "sha_restored": (restored_sha == orig_sha),
            })

            if not is_red:
                print(f"[ERROR] Mutation {mut['id']} did NOT turn RED! Output:\n{out}")
                return 1

    summary_file = REPORT_DIR / "mutation_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    log_file = REPORT_DIR / "mutation_log.txt"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))

    print(f"\nAll mutations verified RED and restored. Summary saved to {summary_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
