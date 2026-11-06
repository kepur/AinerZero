#!/usr/bin/env python3
"""Run mutations for ainerzero.V9.P152 in an isolated replica sandbox.

Mutations:
- P152-M1: short_train_sanity does not check NaN -> test_short_train_sanity_nan_loss_fails must fail.
- P152-M2: oracle_feasibility default threshold changed to 0.5 -> test_oracle_feasibility_partial_success_does_not_fuse_at_005 must fail.
- P152-M3: stuff constant metric dictionary literal in smoke_checks.py -> test_anti_fabrication_ast_scan must fail.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PYTHON_BIN = REPO_ROOT / ".venv" / "bin" / "python"
REPORT_DIR = REPO_ROOT / "reports" / "V9-S2-P152"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    {
        "id": "P152-M1",
        "name": "omit_nan_finite_loss_check",
        "description": "short_train_sanity omits checking if loss is finite/NaN",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke_checks.py",
        "target": """    all_finite = True
    for idx, l in enumerate(losses):
        if not math.isfinite(l):
            all_finite = False
            reasons.append(f"Non-finite loss ({l}) encountered at step {idx}")
            break""",
        "replacement": """    all_finite = True""",
        "target_test": "tests/v9/experiments/test_s2_smoke_checks.py::test_short_train_sanity_nan_loss_fails",
    },
    {
        "id": "P152-M2",
        "name": "relax_fuse_threshold_to_05",
        "description": "oracle_feasibility default threshold changed to 0.5 (instead of 0.05)",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke_checks.py",
        "target": "threshold: float = 0.05,",
        "replacement": "threshold: float = 0.50,",
        "target_test": "tests/v9/experiments/test_s2_smoke_checks.py::test_oracle_feasibility_partial_success_does_not_fuse_at_005",
    },
    {
        "id": "P152-M3",
        "name": "insert_constant_metric_dict_literal",
        "description": "Insert forbidden constant metric dictionary literal in smoke_checks.py",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke_checks.py",
        "target": """def _extract_loss(step_output: Any) -> float:""",
        "replacement": """def _extract_loss(step_output: Any) -> float:
    _forbidden_dummy = {"long_goal_success_rates": {"arm_a": 0.25}}""",
        "target_test": "tests/v9/experiments/test_s2_smoke_checks.py::test_anti_fabrication_ast_scan",
    },
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== Setting up isolated replica workspace for P152 Mutations ===")
    with tempfile.TemporaryDirectory() as td:
        sandbox_dir = Path(td) / "ainerzero_sandbox"
        sandbox_dir.mkdir()

        print(f"Copying src/, tests/, pyproject.toml to {sandbox_dir}...")
        shutil.copytree(REPO_ROOT / "src", sandbox_dir / "src")
        shutil.copytree(REPO_ROOT / "tests", sandbox_dir / "tests")
        shutil.copy2(REPO_ROOT / "pyproject.toml", sandbox_dir / "pyproject.toml")

        # Assert import resolution resolves strictly to the replica
        verify_import_cmd = [
            str(PYTHON_BIN),
            "-c",
            (
                f"import sys\n"
                f"sys.path.insert(0, '{sandbox_dir}/src')\n"
                f"from ainerzero.v9.experiments.s2 import smoke_checks\n"
                f"mod_path = str(smoke_checks.__file__)\n"
                f"assert '{sandbox_dir}' in mod_path, f'Expected replica path, got {{mod_path}}'\n"
                f"print('Replica import resolution verified:', mod_path)\n"
            ),
        ]
        res_import = subprocess.run(verify_import_cmd, capture_output=True, text=True)
        assert res_import.returncode == 0, f"Replica import verification failed: {res_import.stderr}"
        print(res_import.stdout.strip())

        results = []
        log_lines = []

        for mut in MUTATIONS:
            print(f"\n--- Running Mutation: {mut['id']} ({mut['name']}) ---")
            target_path = sandbox_dir / mut["file_rel"]
            orig_text = target_path.read_text(encoding="utf-8")
            orig_sha = sha256_file(target_path)

            assert mut["target"] in orig_text, f"Target text not found for {mut['id']}"
            mutated_text = orig_text.replace(mut["target"], mut["replacement"], 1)

            try:
                target_path.write_text(mutated_text, encoding="utf-8")
                mutated_sha = sha256_file(target_path)
                assert mutated_sha != orig_sha

                # Run target test in sandbox
                env = dict(os.environ)
                env["PYTHONPATH"] = f"{sandbox_dir}/src"

                proc = subprocess.run(
                    [str(PYTHON_BIN), "-m", "pytest", mut["target_test"]],
                    cwd=str(sandbox_dir),
                    capture_output=True,
                    text=True,
                    env=env,
                )

                killed = (proc.returncode != 0)
                status = "KILLED" if killed else "SURVIVED"
                print(f"Result for {mut['id']}: {status} (exit code: {proc.returncode})")

                log_entry = (
                    f"=== Mutation {mut['id']} ===\n"
                    f"Name: {mut['name']}\n"
                    f"Target test: {mut['target_test']}\n"
                    f"Status: {status} (exit_code: {proc.returncode})\n"
                    f"Stdout:\n{proc.stdout}\n"
                    f"Stderr:\n{proc.stderr}\n"
                )
                log_lines.append(log_entry)

                results.append({
                    "id": mut["id"],
                    "name": mut["name"],
                    "description": mut["description"],
                    "target_file": mut["file_rel"],
                    "target_test": mut["target_test"],
                    "status": status,
                    "exit_code": proc.returncode,
                    "killed": killed,
                })

            finally:
                target_path.write_text(orig_text, encoding="utf-8")
                restored_sha = sha256_file(target_path)
                assert restored_sha == orig_sha, f"SHA mismatch on restore for {mut['id']}"

        summary_file = REPORT_DIR / "mutation_summary.json"
        summary_file.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        log_file = REPORT_DIR / "mutation_log.txt"
        log_file.write_text("\n".join(log_lines), encoding="utf-8")

        all_killed = all(r["killed"] for r in results)
        print(f"\nSaved mutation summary to {summary_file}")
        print(f"Saved mutation log to {log_file}")

        if all_killed:
            print("[SUCCESS] All 3 P152 mutations were KILLED in the isolated sandbox.")
            return 0
        else:
            print("[FAIL] Some mutations SURVIVED.")
            return 1


if __name__ == "__main__":
    sys.exit(main())
