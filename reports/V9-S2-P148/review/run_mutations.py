#!/usr/bin/env python3
"""Run reviewer mutations for ainerzero.V9.P149 in an isolated replica sandbox.

Mutations are strictly outside the author's mutation table (P148-M1..M4):
- REV-P148-M1: commands.py compute approval preflight bypassed (if not approved -> if False).
- REV-P148-M2: commands.py phase budget ceiling check bypassed (if not budget_ok -> if False).
- REV-P148-M3: smoke.py action sensitivity check inverted (act_sens >= threshold -> act_sens < threshold).
- REV-P148-M4: smoke.py seed namespace forbidden check disabled (if forbidden in norm -> if False).
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
REVIEW_DIR = REPO_ROOT / "reports" / "V9-S2-P148" / "review"

MUTATIONS = [
    {
        "id": "REV-P148-M1",
        "name": "bypass_compute_approval_preflight",
        "description": "Bypass approval check in commands.py for compute modes (if not approved -> if False)",
        "file_rel": "src/ainerzero/v9/experiments/s2/commands.py",
        "target": 'approved, approval_info = _check_approval_preflight(paths["research_log"])\n    if not approved:',
        "replacement": 'approved, approval_info = _check_approval_preflight(paths["research_log"])\n    if False:',
        "target_check": "test_commands_refuse_unapproved_compute",
    },
    {
        "id": "REV-P148-M2",
        "name": "bypass_phase_budget_ceiling_check",
        "description": "Bypass 10h phase budget ceiling check in commands.py (if not budget_ok -> if False)",
        "file_rel": "src/ainerzero/v9/experiments/s2/commands.py",
        "target": 'budget_ok, consumed, ceiling = _check_phase_budget_ceiling(paths["ledger"], cell_budget)\n    if not budget_ok:',
        "replacement": 'budget_ok, consumed, ceiling = _check_phase_budget_ceiling(paths["ledger"], cell_budget)\n    if False:',
        "target_check": "test_commands_refuse_budget_ceiling_exceeded",
    },
    {
        "id": "REV-P148-M3",
        "name": "invert_action_sensitivity_threshold_check",
        "description": "Invert action sensitivity check in smoke.py (act_sens >= threshold -> act_sens < threshold)",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke.py",
        "target": 'sens_ok = act_sens >= action_sensitivity_threshold',
        "replacement": 'sens_ok = act_sens < action_sensitivity_threshold',
        "target_check": "test_smoke_logic_five_independent_cases",
    },
    {
        "id": "REV-P148-M4",
        "name": "disable_seed_namespace_disjointness_check",
        "description": "Disable forbidden partition check in check_smoke_seed_namespace (if forbidden in norm -> if False)",
        "file_rel": "src/ainerzero/v9/experiments/s2/smoke.py",
        "target": 'if forbidden in norm:\n            raise ValueError(',
        "replacement": 'if False:\n            raise ValueError(',
        "target_check": "test_seed_namespace_and_no_partition_readback",
    },
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== Setting up isolated replica workspace for P149 Review Mutations ===")
    with tempfile.TemporaryDirectory() as td:
        sandbox_dir = Path(td) / "ainerzero_sandbox"
        sandbox_dir.mkdir()

        # Copy src, tests, pyproject.toml
        print(f"Copying src/, tests/, pyproject.toml to {sandbox_dir}...")
        shutil.copytree(REPO_ROOT / "src", sandbox_dir / "src")
        shutil.copytree(REPO_ROOT / "tests", sandbox_dir / "tests")
        shutil.copy2(REPO_ROOT / "pyproject.toml", sandbox_dir / "pyproject.toml")

        # Copy verify_all.py
        review_sub = sandbox_dir / "reports" / "V9-S2-P148" / "review"
        review_sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REVIEW_DIR / "verify_all.py", review_sub / "verify_all.py")

        # Assert import resolution resolves strictly to the replica
        verify_import_cmd = [
            str(PYTHON_BIN),
            "-c",
            (
                f"import sys\n"
                f"sys.path.insert(0, '{sandbox_dir}/src')\n"
                f"from ainerzero.v9.experiments.s2 import commands\n"
                f"mod_path = str(commands.__file__)\n"
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

                # Run verification suite in sandbox
                env = dict(os.environ)
                env["PYTHONPATH"] = f"{sandbox_dir}/src"

                proc = subprocess.run(
                    [str(PYTHON_BIN), str(review_sub / "verify_all.py")],
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
                    f"Target check: {mut['target_check']}\n"
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
                    "target_check": mut["target_check"],
                    "status": status,
                    "exit_code": proc.returncode,
                    "killed": killed,
                })

            finally:
                target_path.write_text(orig_text, encoding="utf-8")
                restored_sha = sha256_file(target_path)
                assert restored_sha == orig_sha, f"SHA mismatch on restore for {mut['id']}"

        # Save summary and log in review directory
        summary_file = REVIEW_DIR / "mutation_summary.json"
        summary_file.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        log_file = REVIEW_DIR / "mutation_log.txt"
        log_file.write_text("\n".join(log_lines), encoding="utf-8")

        all_killed = all(r["killed"] for r in results)
        print(f"\nSaved mutation summary to {summary_file}")
        print(f"Saved mutation log to {log_file}")

        if all_killed:
            print("[SUCCESS] All 4 reviewer mutations were KILLED in the isolated sandbox.")
            return 0
        else:
            print("[FAIL] Some reviewer mutations SURVIVED.")
            return 1


if __name__ == "__main__":
    sys.exit(main())
