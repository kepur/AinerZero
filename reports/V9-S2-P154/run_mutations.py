#!/usr/bin/env python3
"""Run mutations for ainerzero.V9.P154 in an isolated replica sandbox.

Mutations:
- P154-M1: Step 4 circuit breaker gate uses _default_oracle_mpc instead of oracle_feasibility_with_s2_planner
  -> test_smoke_p154_m1_default_oracle_mpc_red must fail (RED).
- P154-M2: Step 3 short-training sanity ignores arm failure (force passed=True)
  -> test_smoke_p154_m2_ignore_step3_arm_failure_red must fail (RED).
- P154-M3: smoke bypasses seed namespace check and reads train/dev namespace
  -> test_smoke_p154_m3_rejects_train_dev_namespace must fail (RED).
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
REPORT_DIR = REPO_ROOT / "reports" / "V9-S2-P154"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    {
        "id": "P154-M1",
        "name": "step4_gate_uses_default_oracle_mpc",
        "description": "Step 4 circuit breaker gate uses default_oracle_mpc instead of s2_planner",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke.py",
        "target": "planner_to_use = oracle_planner_override or smoke_checks.oracle_feasibility_with_s2_planner",
        "replacement": "planner_to_use = oracle_planner_override or smoke_checks.oracle_feasibility",
        "target_test": "tests/v9/experiments/test_s2_wiring.py::test_smoke_p154_m1_default_oracle_mpc_red",
    },
    {
        "id": "P154-M2",
        "name": "step3_ignore_arm_failure",
        "description": "Step 3 short-training sanity silently ignores arm failure",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke.py",
        "target": """            if not arm_sanity.get("passed", False):
                step_3_res["passed"] = False
                reasons.append(f"Step 3 short-train sanity failed for {arm_id}: {arm_sanity.get('reasons', [])}")""",
        "replacement": """            if not arm_sanity.get("passed", False):
                pass  # M2: ignore arm failure""",
        "target_test": "tests/v9/experiments/test_s2_wiring.py::test_smoke_p154_m2_ignore_step3_arm_failure_red",
    },
    {
        "id": "P154-M3",
        "name": "bypass_seed_namespace_check",
        "description": "smoke bypasses seed namespace check and allows train/dev/final namespace",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke.py",
        "target": """    # 1. Enforce seed namespace disjointness
    check_smoke_seed_namespace(seed_namespace)""",
        "replacement": """    # 1. Enforce seed namespace disjointness (M3 bypass)
    pass""",
        "target_test": "tests/v9/experiments/test_s2_wiring.py::test_smoke_p154_m3_rejects_train_dev_namespace",
    },
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== Setting up isolated replica sandbox for P154 Mutations ===")
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
                f"from ainerzero.v9.experiments.s2 import smoke\n"
                f"mod_path = str(smoke.__file__)\n"
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

        # Write summary and logs
        summary_path = REPORT_DIR / "mutation_summary.json"
        summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nWrote mutation summary to {summary_path}")

        log_path = REPORT_DIR / "mutation_log.txt"
        log_path.write_text("\n".join(log_lines), encoding="utf-8")
        print(f"Wrote mutation log to {log_path}")

        all_killed = all(r["killed"] for r in results)
        print(f"\nAll mutations killed: {all_killed} ({len(results)}/{len(results)})")
        if not all_killed:
            sys.exit(1)


if __name__ == "__main__":
    main()
