#!/usr/bin/env python3
"""Isolation mutation testing script for E1 freeze card (ainerzero.V9.P96).

Verifies bad controls on an isolated copy of the repository in a temporary directory:
1. spec SHA 改 1 字符 -> 测试挂 (RED)
2. DEFAULT_TRAIN_STEPS 改回 32000 -> 测试挂 (RED)
3. BUDGET_CAPS 破坏总和等式 -> 测试挂 (RED)
4. train_runner 空验证集不抛异常 -> 测试挂 (RED)
5. worker RunStore 预算改回魔数 100000 -> 测试挂 (RED)

Exits with code 0 if and only if all 5 bad controls turn RED and baseline is strictly verified.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
VENV_PYTEST = REPO_ROOT / ".venv" / "bin" / "pytest"


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_pytest(cwd: Path, test_target: str, env: dict[str, str]) -> tuple[int, str]:
    cmd = [
        str(VENV_PYTEST),
        "-q",
        "--tb=short",
        test_target,
    ]
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.returncode, proc.stdout


def main() -> int:
    print("================================================================================")
    print("E1 Frozen Code Card: Isolation Mutation Testing (Bad Controls)")
    print("================================================================================")

    # 1. Setup isolated sandbox
    temp_dir = Path(tempfile.mkdtemp(prefix="e1_mutation_sandbox_"))
    print(f"[*] Setting up isolated sandbox at: {temp_dir}")

    try:
        sandbox_src = temp_dir / "src"
        sandbox_tests = temp_dir / "tests"
        shutil.copytree(REPO_ROOT / "src", sandbox_src)
        shutil.copytree(REPO_ROOT / "tests", sandbox_tests)
        shutil.copy2(REPO_ROOT / "pyproject.toml", temp_dir / "pyproject.toml")

        # Set environment for sandbox
        sandbox_env = dict(os.environ)
        sandbox_env["PYTHONPATH"] = str(sandbox_src)

        mutations: list[dict[str, Any]] = [
            {
                "id": "MUT-1",
                "name": "spec_sha_mutated_1_char",
                "file": sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "spec.py",
                "target_test": "tests/test_e1_prereg.py::test_spec_constants",
                "mutator": lambda content: content.replace(
                    '"ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e"',
                    '"ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20f"',
                ),
                "expected_fail_str": "ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20",
            },
            {
                "id": "MUT-2",
                "name": "default_train_steps_reverted_to_32000",
                "file": sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "spec.py",
                "target_test": "tests/test_e1_prereg.py::test_spec_constants",
                "mutator": lambda content: content.replace(
                    "DEFAULT_TRAIN_STEPS: int = 64000",
                    "DEFAULT_TRAIN_STEPS: int = 32000",
                ),
                "expected_fail_str": "assert 32000 == 64000",
            },
            {
                "id": "MUT-3",
                "name": "budget_caps_sum_equation_broken",
                "file": sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "spec.py",
                "target_test": "tests/test_e1_prereg.py::test_spec_constants",
                "mutator": lambda content: content.replace(
                    '"train_total_wall_max_seconds": 10800.0,',
                    '"train_total_wall_max_seconds": 10801.0,',
                ),
                "expected_fail_str": "assert",
            },
            {
                "id": "MUT-4",
                "name": "train_runner_empty_validation_guard_disabled",
                "file": sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "train_runner.py",
                "target_test": "tests/test_e1_train_runner.py::test_compute_validation_loss_empty_windows_raises_value_error",
                "mutator": lambda content: content.replace(
                    'if len(val_windows) == 0:\n        raise ValueError("Cannot compute validation loss on empty validation windows")',
                    '# MUTATED: check disabled\n    pass',
                ),
                "expected_fail_str": "DID NOT RAISE <class 'ValueError'>",
            },
            {
                "id": "MUT-5",
                "name": "worker_runstore_optimizer_steps_reverted_to_100k",
                "file": sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "worker.py",
                "target_test": "tests/test_e1_wiring.py::test_runstore_budget_derived_from_spec",
                "mutator": lambda content: content.replace(
                    'derived_experiment_optimizer_steps = int(train_cells * max_steps_per_cell * 1.2)',
                    'derived_experiment_optimizer_steps = 100000',
                ),
                "expected_fail_str": "assert 100000 ==",
            },
        ]

        results = []
        all_passed = True

        for m in mutations:
            print(f"\n--- Running Mutation {m['id']}: {m['name']} ---")
            target_file: Path = m["file"]
            orig_content = target_file.read_text(encoding="utf-8")
            orig_sha = compute_sha256(target_file)

            # 1. Verify baseline passes first
            rc_base, out_base = run_pytest(temp_dir, m["target_test"], sandbox_env)
            if rc_base != 0:
                print(f"[ERROR] Baseline test {m['target_test']} did not pass before mutation!")
                print(out_base)
                all_passed = False
                break

            # 2. Mutate file
            mutated_content = m["mutator"](orig_content)
            if mutated_content == orig_content:
                print(f"[ERROR] Mutation {m['id']} mutator produced identical text!")
                all_passed = False
                break

            target_file.write_text(mutated_content, encoding="utf-8")
            mutated_sha = compute_sha256(target_file)

            # 3. Run target test (MUST FAIL)
            rc_mut, out_mut = run_pytest(temp_dir, m["target_test"], sandbox_env)

            # 4. Restore original file immediately
            target_file.write_text(orig_content, encoding="utf-8")
            restored_sha = compute_sha256(target_file)
            assert orig_sha == restored_sha, f"SHA mismatch on restore for {target_file}"

            # 5. Check outcome
            if rc_mut != 0:
                print(f"[OK] Mutation {m['id']} successfully turned RED (exit {rc_mut})")
                outcome = "RED (passed bad-control)"
            else:
                print(f"[FAIL] Mutation {m['id']} remained GREEN! Test did not catch mutation.")
                all_passed = False
                outcome = "GREEN (failed bad-control)"

            results.append({
                "id": m["id"],
                "name": m["name"],
                "file": str(target_file.relative_to(temp_dir)),
                "target_test": m["target_test"],
                "exit_code": rc_mut,
                "outcome": outcome,
                "orig_sha": orig_sha[:16],
                "mutated_sha": mutated_sha[:16],
                "restored_sha": restored_sha[:16],
                "error_snippet": [line.strip() for line in out_mut.splitlines() if "FAILED" in line or "assert" in line or "Error" in line][:3],
            })

        print("\n================================================================================")
        print("Mutation Bad-Control Summary Table:")
        print("================================================================================")
        print(f"{'ID':<6} | {'Mutation Name':<35} | {'Exit':<5} | {'Status':<10} | {'Test Target'}")
        print("-" * 100)
        for r in results:
            print(f"{r['id']:<6} | {r['name']:<35} | {r['exit_code']:<5} | {r['outcome']:<10} | {r['target_test']}")

        # Save summary json
        summary_path = REPO_ROOT / "reports" / "V9-E1FREEZE" / "mutation_results.json"
        summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nSaved mutation results to {summary_path}")

        if all_passed and len(results) == len(mutations):
            print("\n[SUCCESS] All 5 isolation mutations successfully verified! Baseline intact.")
            return 0
        else:
            print("\n[FAILURE] One or more mutations failed bad control requirements.")
            return 1

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"[*] Cleaned up isolated sandbox at: {temp_dir}")


if __name__ == "__main__":
    sys.exit(main())
