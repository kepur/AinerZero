#!/usr/bin/env python3
"""Reviewer mutations for ainerzero.V9.P156 (verifying P154).

Executed in an isolated replica sandbox outside the repo.
All mutations are strictly outside the author's mutations (P154-M1, M2, M3).

Mutations:
- REV-M1: In smoke_checks.py, change res["planner"] = "s2_planner" to "default_oracle"
  -> test_oracle_feasibility_with_s2_planner_two_worlds must fail (RED).
- REV-M2: In smoke.py, change shared_steps = min(per_arm_steps.values()) to max(per_arm_steps.values())
  -> test_smoke_timing_and_training_steps_minimum_rule must fail (RED).
- REV-M3: In smoke.py, force passed = True unconditionally at the end of run_smoke
  -> test_smoke_no_injected_measurements_fails_with_named_reasons must fail (RED).
- REV-M4: In smoke_checks.py, disable fuse circuit breaker by setting threshold = 0.0 in oracle_feasibility_with_s2_planner
  -> test_oracle_feasibility_budget_fuse_triggered must fail (RED).
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
REVIEW_DIR = REPO_ROOT / "reports" / "V9-S2-P154" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    {
        "id": "REV-M1",
        "name": "forge_planner_identity_string",
        "description": "Corrupt planner identity string returned by oracle_feasibility_with_s2_planner to default_oracle",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke_checks.py",
        "target": '    res["planner"] = "s2_planner"',
        "replacement": '    res["planner"] = "default_oracle"',
        "target_test": "tests/v9/experiments/test_s2_smoke_checks.py::test_oracle_feasibility_with_s2_planner_two_worlds",
    },
    {
        "id": "REV-M2",
        "name": "violate_minimum_arm_steps_budget_rule",
        "description": "Compute training steps taking max across arms instead of minimum, violating worst-case slot budget",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke.py",
        "target": "    shared_steps = min(per_arm_steps.values())",
        "replacement": "    shared_steps = max(per_arm_steps.values())",
        "target_test": "tests/v9/experiments/test_s2_wiring.py::test_smoke_timing_and_training_steps_minimum_rule",
    },
    {
        "id": "REV-M3",
        "name": "unconditional_smoke_passed_true",
        "description": "Unconditionally force passed=True in run_smoke regardless of accumulated failure reasons",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke.py",
        "target": "    # Determine overall pass\n    passed = (len(reasons) == 0)",
        "replacement": "    # Determine overall pass\n    passed = True",
        "target_test": "tests/v9/experiments/test_s2_wiring.py::test_smoke_no_injected_measurements_fails_with_named_reasons",
    },
    {
        "id": "REV-M4",
        "name": "suppress_oracle_feasibility_circuit_breaker",
        "description": "Disable fuse triggering in oracle_feasibility_with_s2_planner by forcing default threshold to -1.0",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke_checks.py",
        "target": "def oracle_feasibility_with_s2_planner(\n    layout_specs: Sequence[Any],\n    n_fwd: int = 4096,\n    rng: Any = None,\n    threshold: float = 0.05,\n) -> dict[str, Any]:",
        "replacement": "def oracle_feasibility_with_s2_planner(\n    layout_specs: Sequence[Any],\n    n_fwd: int = 4096,\n    rng: Any = None,\n    threshold: float = -1.0,\n) -> dict[str, Any]:",
        "target_test": "tests/v9/experiments/test_s2_smoke_checks.py::test_oracle_feasibility_with_s2_planner_two_worlds",
    },
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== Setting up isolated replica sandbox for P156 Review Mutations ===")
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

        summary_path = REVIEW_DIR / "reviewer_mutations.json"
        summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nWrote reviewer mutation summary to {summary_path}")

        log_path = REVIEW_DIR / "reviewer_mutations.log"
        log_path.write_text("\n".join(log_lines), encoding="utf-8")
        print(f"Wrote reviewer mutation log to {log_path}")

        all_killed = all(r["killed"] for r in results)
        print(f"\nAll reviewer mutations killed: {all_killed} ({len(results)}/{len(results)})")
        if not all_killed:
            sys.exit(1)


if __name__ == "__main__":
    main()
