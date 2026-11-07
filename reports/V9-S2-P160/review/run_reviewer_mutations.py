#!/usr/bin/env python3
"""Reviewer mutations for ainerzero.V9.P161 (verifying P160).

Executed in an isolated replica sandbox outside the repo.
All mutations are strictly outside author P160's mutations (P160-M1, M2).

Mutations:
- REV-P160-M1: In smoke_checks.py, when goal is missing, fall back to start_raw instead of raising ValueError
  -> test_oracle_feasibility_missing_start_or_goal_raises must fail (RED).
- REV-P160-M2: In smoke.py, hardcode total_short_steps = 200 instead of spec.SMOKE_SHORT_TRAIN_STEPS
  -> test_smoke_fails_when_smoke_short_train_steps_missing must fail (RED).
- REV-P160-M3: In smoke_checks.py, when start is missing, fall back to fake origin instead of raising ValueError
  -> test_oracle_feasibility_missing_start_or_goal_raises must fail (RED).
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
REVIEW_DIR = REPO_ROOT / "reports" / "V9-S2-P160" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    {
        "id": "REV-P160-M1",
        "name": "fallback_missing_goal_to_start",
        "description": "Fall back to start_raw when goal is missing instead of raising ValueError",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke_checks.py",
        "target": """        goal_raw = spec_data.get("goal") if isinstance(spec_data, Mapping) else getattr(spec_data, "goal", None)
        if goal_raw is None:
            raise ValueError(f"Missing goal in episode spec {idx}")""",
        "replacement": """        goal_raw = spec_data.get("goal") if isinstance(spec_data, Mapping) else getattr(spec_data, "goal", None)
        if goal_raw is None:
            goal_raw = start_raw""",
        "target_test": "tests/v9/experiments/test_s2_smoke_checks.py::test_oracle_feasibility_missing_start_or_goal_raises",
    },
    {
        "id": "REV-P160-M2",
        "name": "hardcode_total_short_steps_in_generate_partition",
        "description": "Hardcode total_short_steps = 200 instead of referencing spec.SMOKE_SHORT_TRAIN_STEPS",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke.py",
        "target": "    total_short_steps = spec.SMOKE_SHORT_TRAIN_STEPS",
        "replacement": "    total_short_steps = 200",
        "target_test": "tests/v9/experiments/test_s2_wiring.py::test_smoke_fails_when_smoke_short_train_steps_missing",
    },
    {
        "id": "REV-P160-M3",
        "name": "fallback_missing_start_to_origin",
        "description": "Fall back to origin dict when start is missing instead of raising ValueError",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke_checks.py",
        "target": """        start_raw = spec_data.get("start") if isinstance(spec_data, Mapping) else getattr(spec_data, "start", None)
        if start_raw is None:
            raise ValueError(f"Missing start in episode spec {idx}")""",
        "replacement": """        start_raw = spec_data.get("start") if isinstance(spec_data, Mapping) else getattr(spec_data, "start", None)
        if start_raw is None:
            start_raw = {"x": 0, "y": 0, "heading": 0}""",
        "target_test": "tests/v9/experiments/test_s2_smoke_checks.py::test_oracle_feasibility_missing_start_or_goal_raises",
    },
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== Setting up isolated replica sandbox for P161 Review Mutations ===")
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
