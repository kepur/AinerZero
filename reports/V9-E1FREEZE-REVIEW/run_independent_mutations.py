#!/usr/bin/env python3
"""Independent adversarial mutation verifier for ainerzero.V9.P97.

Reviews P96 frozen code card by creating an isolated sandbox copy,
asserting imports resolve to the sandbox copy, injecting 6 targeted mutations,
verifying each mutation turns RED (fails/errors), restoring byte-for-byte,
and verifying that SHA256 matches baseline.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PYTHON_EXEC = REPO_ROOT / ".venv" / "bin" / "python"
PYTEST_EXEC = REPO_ROOT / ".venv" / "bin" / "pytest"

def compute_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    print("=== P97 Independent Adversarial Mutation Verification ===")
    
    # 1. Create isolated temp directory
    temp_dir = Path(tempfile.mkdtemp(prefix="p97_review_sandbox_"))
    print(f"Isolated sandbox directory: {temp_dir}")
    
    try:
        # Copy src and tests into sandbox
        sandbox_src = temp_dir / "src"
        sandbox_tests = temp_dir / "tests"
        shutil.copytree(REPO_ROOT / "src", sandbox_src)
        shutil.copytree(REPO_ROOT / "tests", sandbox_tests)
        
        # Also copy reports needed by spec (e.g. PREREG_DRAFT_r4_candidate.md)
        sandbox_reports = temp_dir / "reports"
        shutil.copytree(REPO_ROOT / "reports" / "V9-P48", sandbox_reports / "V9-P48")
        
        # 2. Assert import resolves to sandbox
        check_script = (
            f"import sys\n"
            f"sys.path.insert(0, '{sandbox_src}')\n"
            f"from ainerzero.v9.experiments.e1 import spec\n"
            f"print('SPEC_PATH:', spec.__file__)\n"
            f"assert str(spec.__file__).startswith('{sandbox_src}'), 'Import did not resolve to sandbox!'\n"
        )
        res = subprocess.run([str(PYTHON_EXEC), "-c", check_script], capture_output=True, text=True)
        print("Import check output:", res.stdout.strip())
        if res.returncode != 0:
            print("Import check FAILED:", res.stderr)
            sys.exit(1)
        print("Import resolution assert PASSED!")

        # Files under test
        spec_path = sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "spec.py"
        prereg_path = sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "prereg.py"
        train_runner_path = sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "train_runner.py"
        worker_path = sandbox_src / "ainerzero" / "v9" / "experiments" / "e1" / "worker.py"
        
        target_files = {
            "spec": spec_path,
            "prereg": prereg_path,
            "train_runner": train_runner_path,
            "worker": worker_path,
        }
        
        baseline_shas = {k: compute_sha(p) for k, p in target_files.items()}
        print("Baseline SHA-256 in sandbox:")
        for k, sha in baseline_shas.items():
            print(f"  {k}: {sha}")
            
        # Define 6 independent adversarial mutations
        mutations = [
            {
                "id": "ADV-1",
                "name": "mutate_default_train_steps_to_64001",
                "file_key": "spec",
                "target_test": str(sandbox_tests / "test_e1_prereg.py") + "::test_spec_constants",
                "old": "DEFAULT_TRAIN_STEPS: int = 64000",
                "new": "DEFAULT_TRAIN_STEPS: int = 64001",
                "description": "Mutates DEFAULT_TRAIN_STEPS to 64001 in spec.py",
            },
            {
                "id": "ADV-2",
                "name": "revert_draft_sha_to_old_r1_anchor",
                "file_key": "spec",
                "target_test": str(sandbox_tests / "test_e1_prereg.py") + "::test_spec_constants",
                "old": 'PREREG_DRAFT_SHA256 = (\n    "ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e"\n)',
                "new": 'PREREG_DRAFT_SHA256 = (\n    "372e724bd6b028da9dde76d7f1fb52aa6e1497926b5a081a64032950662f2872"\n)',
                "description": "Reverts PREREG_DRAFT_SHA256 in spec.py to old 372e724b hash",
            },
            {
                "id": "ADV-3",
                "name": "invert_prereg_duty_cycle_validation",
                "file_key": "prereg",
                "target_test": str(sandbox_tests / "test_e1_prereg.py") + "::test_build_and_validate_draft",
                "old": "if abs(cell_wall * duty - cell_compute) > 1e-3:",
                "new": "if abs(cell_wall * duty - cell_compute) <= 1e-3:",
                "description": "Inverts duty cycle validation condition in prereg.py:341 so valid spec fails",
            },
            {
                "id": "ADV-4",
                "name": "disable_train_runner_two_episodes_guard",
                "file_key": "train_runner",
                "target_test": str(sandbox_tests / "test_e1_train_runner.py") + "::test_split_episodes_raises_if_fewer_than_two_episodes",
                "old": "if n_total < 2:",
                "new": "if n_total < 0:",
                "description": "Disables minimum 2 episodes guard in train_runner.py:130",
            },
            {
                "id": "ADV-5",
                "name": "disable_validation_loss_empty_windows_guard",
                "file_key": "train_runner",
                "target_test": str(sandbox_tests / "test_e1_train_runner.py") + "::test_compute_validation_loss_empty_windows_raises_value_error",
                "old": "if len(val_windows) == 0:",
                "new": "if False and len(val_windows) == 0:",
                "description": "Disables empty val_windows guard in train_runner.py:159",
            },
            {
                "id": "ADV-6",
                "name": "revert_worker_experiment_optimizer_steps_to_100k",
                "file_key": "worker",
                "target_test": str(sandbox_tests / "test_e1_wiring.py") + "::test_runstore_budget_derived_from_spec",
                "old": '    derived_experiment_optimizer_steps = int(train_cells * max_steps_per_cell * 1.2)',
                "new": '    derived_experiment_optimizer_steps = 100_000',
                "description": "Reverts RunStore experiment optimizer steps calculation in worker.py:192 to 100k",
            },
        ]
        
        results = []
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{sandbox_src}:{sandbox_tests}"
        
        all_passed = True
        
        for mut in mutations:
            fpath = target_files[mut["file_key"]]
            orig_text = fpath.read_text(encoding="utf-8")
            if mut["old"] not in orig_text:
                raise ValueError(f"Target pattern not found for mutation {mut['id']}: {mut['old']}")
            
            # Apply mutation
            mut_text = orig_text.replace(mut["old"], mut["new"], 1)
            fpath.write_text(mut_text, encoding="utf-8")
            mut_sha = compute_sha(fpath)
            
            # Run pytest
            cmd = [str(PYTEST_EXEC), mut["target_test"], "-q"]
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=str(temp_dir))
            
            # Restore file
            fpath.write_text(orig_text, encoding="utf-8")
            restored_sha = compute_sha(fpath)
            
            assert restored_sha == baseline_shas[mut["file_key"]], (
                f"Byte-restore failed for {mut['id']}! Restored SHA {restored_sha} != Baseline {baseline_shas[mut['file_key']]}"
            )
            
            is_red = proc.returncode != 0
            if not is_red:
                all_passed = False
                
            res_entry = {
                "id": mut["id"],
                "name": mut["name"],
                "description": mut["description"],
                "target_file": str(fpath.relative_to(sandbox_src)),
                "target_test": mut["target_test"].replace(str(temp_dir) + "/", ""),
                "returncode": proc.returncode,
                "status": "RED (pass)" if is_red else "GREEN (unexpected pass / mutation silent)",
                "baseline_sha256": baseline_shas[mut["file_key"]],
                "mutated_sha256": mut_sha,
                "restored_sha256": restored_sha,
                "sha_matches_baseline": restored_sha == baseline_shas[mut["file_key"]],
                "stdout_tail": proc.stdout.strip().splitlines()[-3:] if proc.stdout else [],
                "stderr_tail": proc.stderr.strip().splitlines()[-3:] if proc.stderr else [],
            }
            results.append(res_entry)
            print(f"[{mut['id']}] {mut['name']} -> exit code {proc.returncode} -> {'RED (PASS)' if is_red else 'GREEN (FAIL)'}")
            
        output_file = REPO_ROOT / "reports" / "V9-E1FREEZE-REVIEW" / "mutation_results.json"
        output_file.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Results written to {output_file}")
        
        if not all_passed:
            print("ERROR: One or more mutations failed to turn RED!")
            sys.exit(1)
        else:
            print("ALL 6 ADVERSARIAL MUTATIONS SUCCESSFULLY TURNED RED AND RESTORED CLEANLY!")
            
    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        print("Sandbox cleaned up.")

if __name__ == "__main__":
    main()
