#!/usr/bin/env python3
"""Run independent reviewer mutations for ainerzero.V9.P157 in an isolated replica sandbox.

Reviewer mutations (distinct from author P156-M1/M2/M3):
- REV-M1: run_post_train_gates silently allows dev/final specs without raising PostTrainGateError
  -> test_post_train_gates_rejects_dev_or_final_specs must fail (RED).
- REV-M2: run_post_train_gates disables unplannable check (ignores sens < sensitivity_threshold)
  -> test_unplannable_arm_fails_gate_and_dev_refused must fail (RED).
- REV-M3: run_dev_eval does not raise PostTrainGateRefused when gates.passed is False
  -> test_c_arm_collusion_detected_and_dev_refused must fail (RED).
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
REVIEW_DIR = REPO_ROOT / "reports" / "V9-S2-P156" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    {
        "id": "REV-M1",
        "name": "omit_post_train_partition_check",
        "description": "run_post_train_gates omits checking episode spec partition == 'train'",
        "file_rel": "src/ainerzero/v9/experiments/s2/eval_runner.py",
        "target": """    for i, spec in enumerate(train_episode_specs):
        part = _spec_partition(spec)
        if part != "train":
            raise PostTrainGateError(
                f"run_post_train_gates refuses non-train specs: index={i} partition={part!r}"
            )""",
        "replacement": """    for i, spec in enumerate(train_episode_specs):
        part = _spec_partition(spec)
        pass  # REV-M1: silently allow non-train partitions""",
        "target_test": "tests/v9/experiments/test_s2_eval_runner.py::test_post_train_gates_rejects_dev_or_final_specs",
    },
    {
        "id": "REV-M2",
        "name": "disable_action_sensitivity_floor_check",
        "description": "run_post_train_gates ignores when action sensitivity is below threshold",
        "file_rel": "src/ainerzero/v9/experiments/s2/eval_runner.py",
        "target": """        sensitivity_by_arm[arm_name] = float(sens)
        if sens < sensitivity_threshold:
            unplannable_arms.append(arm_name)
            reasons.append(
                f"Arm {arm_name} action sensitivity {sens:.4f} < {sensitivity_threshold:.4f} (不可规划)"
            )""",
        "replacement": """        sensitivity_by_arm[arm_name] = float(sens)
        if False:  # REV-M2: disable unplannable check
            unplannable_arms.append(arm_name)
            reasons.append(
                f"Arm {arm_name} action sensitivity {sens:.4f} < {sensitivity_threshold:.4f} (不可规划)"
            )""",
        "target_test": "tests/v9/experiments/test_s2_eval_runner.py::test_unplannable_arm_fails_gate_and_dev_refused",
    },
    {
        "id": "REV-M3",
        "name": "omit_dev_eval_gate_failure_refusal",
        "description": "run_dev_eval does not raise PostTrainGateRefused when post_train_gates.passed is False",
        "file_rel": "src/ainerzero/v9/experiments/s2/eval_runner.py",
        "target": """        if not gates.get("passed", False):
            gate_reasons = "; ".join(gates.get("reasons", ["post_train_gates failed"]))
            raise PostTrainGateRefused(
                f"dev eval refused: post_train_gates failed: {gate_reasons}"
            )""",
        "replacement": """        if not gates.get("passed", False):
            pass  # REV-M3: do not raise on failed post_train_gates""",
        "target_test": "tests/v9/experiments/test_s2_eval_runner.py::test_c_arm_collusion_detected_and_dev_refused",
    },
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== Setting up isolated replica sandbox for P157 Reviewer Mutations ===")
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
                f"from ainerzero.v9.experiments.s2 import eval_runner\n"
                f"mod_path = str(eval_runner.__file__)\n"
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
        summary_path = REVIEW_DIR / "mutation_summary.json"
        summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nWrote mutation summary to {summary_path}")

        log_path = REVIEW_DIR / "mutation_log.txt"
        log_path.write_text("\n".join(log_lines), encoding="utf-8")
        print(f"Wrote mutation log to {log_path}")

        all_killed = all(r["killed"] for r in results)
        print(f"\nAll mutations killed: {all_killed} ({len(results)}/{len(results)})")
        if not all_killed:
            sys.exit(1)


if __name__ == "__main__":
    main()
