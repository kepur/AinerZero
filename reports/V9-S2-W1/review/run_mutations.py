#!/usr/bin/env python3
"""Run reviewer mutations for ainerzero.V9.P165 in an isolated replica sandbox.

Mutations:
1. W1-M1: Fallback step count to spec.H_TRAIN (16) if smoke steps missing
   -> test_w1_train_rejects_missing_or_failed_smoke must fail (RED).
2. W1-M2: Holdout set cut by random sequence permutation instead of world-cut
   -> test_w1_train_runner_holdout_separation_and_checkpoint_path must fail (RED).
3. W1-M3: Model selection interval defaults to 5 instead of spec.MODEL_SELECTION_EVERY_STEPS
   -> test_w1_model_selection_interval_defaults_to_spec must fail (RED).
4. W1-M4: Training data directory defaults to output_root / 'data' instead of datasets/train
   -> test_w1_train_resolves_steps_from_passed_smoke_and_executes must fail (RED).
5. W1-M5: Commands generate-data allows passing --arm without rejection
   -> test_w1_cli_generate_data_argument_validation must fail (RED).
6. REV-M6 (Self-selected): Omit generating HOLDOUT_WORLDS.json in train partition
   -> test_w1_data_holdout_worlds_generation must fail (RED).
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
REVIEW_DIR = REPO_ROOT / "reports" / "V9-S2-W1" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)

MUTATIONS = [
    {
        "id": "W1-M1",
        "name": "fallback_steps_to_h_train",
        "description": "Fallback step count to spec.H_TRAIN (16) if smoke steps missing",
        "file_rel": "src/ainerzero/v9/experiments/s2/commands.py",
        "target": """        if runner_arg is None and steps_arg is None:
            smoke_steps = _resolve_smoke_train_steps(paths["ledger"])
            if smoke_steps is None or smoke_steps <= 0:
                return {
                    "status": "refused",
                    "mode": mode,
                    "stage": "smoke_steps_missing",
                    "message": "Missing or non-passed smoke run in ledger providing shared_train_steps",
                }, EXIT_FAILED""",
        "replacement": """        if runner_arg is None and steps_arg is None:
            smoke_steps = 16  # W1-M1: silently ignore missing smoke steps and default to 16""",
        "target_test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_train_rejects_missing_or_failed_smoke",
    },
    {
        "id": "W1-M2",
        "name": "holdout_by_sequence_permutation",
        "description": "Holdout set cut by random sequence permutation instead of world-cut",
        "file_rel": "src/ainerzero/v9/experiments/s2/train_runner.py",
        "target": """    if not train_seqs:
        raise ValueError(f"no training sequences found under non-holdout worlds in {train_root}")
    if not hold_seqs:
        raise ValueError(f"no holdout sequences found under holdout worlds in {train_root}")

    return train_seqs, hold_seqs, rel_files""",
        "replacement": """    # W1-M2: zero out train_seqs to simulate empty non-holdout world assignment
    return [], hold_seqs, rel_files""",
        "target_test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_train_runner_holdout_separation_and_checkpoint_path",
    },
    {
        "id": "W1-M3",
        "name": "model_selection_interval_default_5",
        "description": "Model selection interval defaults to 5 instead of spec.MODEL_SELECTION_EVERY_STEPS",
        "file_rel": "src/ainerzero/v9/experiments/s2/train_runner.py",
        "target": """    eval_every: int = spec.MODEL_SELECTION_EVERY_STEPS,""",
        "replacement": """    eval_every: int = 5,  # W1-M3: default to 5""",
        "target_test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_model_selection_interval_defaults_to_spec",
    },
    {
        "id": "W1-M4",
        "name": "data_dir_default_output_root_data",
        "description": "Training data directory defaults to output_root / 'data' instead of datasets/train",
        "file_rel": "src/ainerzero/v9/experiments/s2/commands.py",
        "target": """            data_dir = kwargs.get("data_dir") or getattr(args, "data_dir", None) or (Path(output_root) / "datasets" / "train")""",
        "replacement": """            data_dir = kwargs.get("data_dir") or getattr(args, "data_dir", None) or (Path(output_root) / "data")""",
        "target_test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_train_resolves_steps_from_passed_smoke_and_executes",
    },
    {
        "id": "W1-M5",
        "name": "generate_data_allows_arm_flag",
        "description": "Commands generate-data allows passing --arm without rejection",
        "file_rel": "src/ainerzero/v9/experiments/s2/commands.py",
        "target": """            if arm is not None:
                return {
                    "status": "refused",
                    "mode": mode,
                    "stage": "argument_validation",
                    "message": "generate-data does not accept --arm; use --partition instead",
                }, EXIT_FAILED""",
        "replacement": """            if arm is not None:
                pass  # W1-M5: allow arm flag""",
        "target_test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_cli_generate_data_argument_validation",
    },
    {
        "id": "REV-M6",
        "name": "omit_holdout_worlds_json_generation",
        "description": "Omit writing HOLDOUT_WORLDS.json during train partition generation",
        "file_rel": "src/ainerzero/v9/experiments/s2/data.py",
        "target": """        holdout_file.write_text(json.dumps(holdout_payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
        generated_files.append(holdout_file)""",
        "replacement": """        pass  # REV-M6: omit HOLDOUT_WORLDS.json""",
        "target_test": "tests/v9/experiments/test_s2_w1_integration.py::test_w1_data_holdout_worlds_generation",
    },
]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    print("=== Setting up isolated replica sandbox for P165 Reviewer Mutations ===")
    with tempfile.TemporaryDirectory() as td:
        sandbox_dir = Path(td) / "ainerzero_sandbox"
        sandbox_dir.mkdir()

        print(f"Copying src/, tests/, pyproject.toml to {sandbox_dir}...")
        shutil.copytree(REPO_ROOT / "src", sandbox_dir / "src")
        shutil.copytree(REPO_ROOT / "tests", sandbox_dir / "tests")
        shutil.copy2(REPO_ROOT / "pyproject.toml", sandbox_dir / "pyproject.toml")

        # Verify replica import resolution
        verify_import_cmd = [
            str(PYTHON_BIN),
            "-c",
            (
                f"import sys\n"
                f"sys.path.insert(0, '{sandbox_dir}/src')\n"
                f"from ainerzero.v9.experiments.s2 import commands\n"
                f"assert '{sandbox_dir}' in str(commands.__file__)\n"
                f"print('Sandbox commands path verified:', commands.__file__)\n"
            ),
        ]
        res_import = subprocess.run(verify_import_cmd, capture_output=True, text=True)
        assert res_import.returncode == 0, f"Sandbox verification failed: {res_import.stderr}"
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

                cmd = [
                    str(PYTHON_BIN),
                    "-m",
                    "pytest",
                    "-q",
                    str(sandbox_dir / mut["target_test"]),
                ]
                env = os.environ.copy()
                env["PYTHONPATH"] = f"{sandbox_dir / 'src'}:{env.get('PYTHONPATH', '')}"

                res = subprocess.run(cmd, cwd=sandbox_dir, env=env, capture_output=True, text=True)

                turned_red = (res.returncode != 0)
                print(f"Result: returncode={res.returncode}, turned_red={turned_red}")
                summary_line = ""
                for line in res.stdout.splitlines():
                    if "FAILED" in line or "error" in line or "assert" in line:
                        summary_line = line.strip()
                        break
                if not summary_line and res.stderr:
                    summary_line = res.stderr.splitlines()[0]

                log_lines.append(f"=== Mutation {mut['id']}: {mut['name']} ===")
                log_lines.append(f"Target: {mut['target_test']}")
                log_lines.append(f"Exit Code: {res.returncode}")
                log_lines.append(f"Turned Red: {turned_red}")
                log_lines.append(f"Stdout:\n{res.stdout}")
                log_lines.append(f"Stderr:\n{res.stderr}\n")

                results.append({
                    "id": mut["id"],
                    "name": mut["name"],
                    "description": mut["description"],
                    "file": mut["file_rel"],
                    "target_test": mut["target_test"],
                    "turned_red": turned_red,
                    "exit_code": res.returncode,
                    "failure_summary": summary_line,
                    "sha_mutated": mutated_sha,
                })
            finally:
                # Restore exactly
                target_path.write_text(orig_text, encoding="utf-8")
                restored_sha = sha256_file(target_path)
                assert restored_sha == orig_sha, f"SHA mismatch on restore for {mut['id']}"
                print(f"Restored and verified original SHA: {restored_sha}")

        all_turned_red = all(r["turned_red"] for r in results)
        print(f"\nAll mutations turned red: {all_turned_red}")

        # Write summary files
        summary_payload = {
            "all_turned_red": all_turned_red,
            "mutation_count": len(results),
            "killed_count": sum(1 for r in results if r["turned_red"]),
            "mutations": results,
        }
        (REVIEW_DIR / "mutations.json").write_text(
            json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8"
        )
        (REVIEW_DIR / "mutation_summary.json").write_text(
            json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8"
        )
        (REVIEW_DIR / "mutations.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        print(f"Saved results to {REVIEW_DIR / 'mutations.json'} and {REVIEW_DIR / 'mutations.log'}")


if __name__ == "__main__":
    main()
