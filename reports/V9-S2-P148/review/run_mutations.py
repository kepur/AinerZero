#!/usr/bin/env python3
"""Reviewer independent mutation runner for P148 r3 verification (ainerzero.V9.P149).

Runs:
1. Focus Check: P148-M5 (restoring default constants) -> killed by test_smoke_step3_step4_unimplemented_must_fail.
2. Reviewer Mutation 1 (REV-M1): check_smoke_seed_namespace allows forbidden partitions -> killed by test_smoke_seed_namespace_rejects_overlapping.
3. Reviewer Mutation 2 (REV-M2): make_smoke_timing_batch alters registered batch size -> killed by test_smoke_batch_shape_registered.
4. Reviewer Mutation 3 (REV-M3): _resolve_default_runner returns dummy runner -> killed by test_commands_dispatch_to_runners.
5. Reviewer Mutation 4 (REV-M4): check_smoke_budget forces sufficient = True -> killed by test_smoke_over_budget_fails.

All mutations are run in an isolated sandbox, verified to resolve imports to the sandbox,
and restored byte-for-byte with SHA-256 validation.
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

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REVIEW_DIR = REPO_ROOT / "reports" / "V9-S2-P148" / "review"
REVIEW_DIR.mkdir(parents=True, exist_ok=True)


def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    print("=== P149 Reviewer Independent Mutation Testing ===")
    with tempfile.TemporaryDirectory() as sandbox_dir:
        sandbox = Path(sandbox_dir)
        print(f"Creating isolated sandbox in {sandbox}...")
        shutil.copytree(REPO_ROOT / "src", sandbox / "src")
        shutil.copytree(REPO_ROOT / "tests", sandbox / "tests")
        shutil.copyfile(REPO_ROOT / "pyproject.toml", sandbox / "pyproject.toml")

        # Verify sandbox isolation
        check_code = f"""
import sys
from pathlib import Path
import ainerzero
mod_path = Path(ainerzero.__file__).resolve()
sandbox_path = Path('{sandbox}/src/ainerzero/__init__.py').resolve()
assert mod_path == sandbox_path, f'Expected {{sandbox_path}}, got {{mod_path}}'
print('RESOLVED_TO_SANDBOX')
"""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(sandbox / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        res = subprocess.run([sys.executable, "-c", check_code], env=env, capture_output=True, text=True)
        if res.returncode != 0 or "RESOLVED_TO_SANDBOX" not in res.stdout:
            print(f"Failed to verify sandbox import: {res.stderr}", file=sys.stderr)
            return 1

        smoke_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "smoke.py"
        commands_file = sandbox / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "commands.py"

        mutations = [
            {
                "id": "P148-M5",
                "desc": "smoke step 3 restores constant metrics instead of failing closed as not_implemented",
                "file": smoke_file,
                "orig_target": """        preconditions_metrics = {
            "status": "not_implemented",
            "step_3_short_train": {"status": "not_implemented"},
            "step_4_feasibility": {"status": "not_implemented"},
        }
        reasons.append("短训健全性与可行性熔断待 P152 实现")""",
                "mutant": """        preconditions_metrics = {
            "delta_sigreg": -0.01,
            "action_sensitivity": 0.08,
            "subgoal_shuffle_drop": 0.15,
            "long_goal_success_rates": {"arm_a": 0.20, "arm_b": 0.25, "arm_c": 0.35},
        }""",
                "test": "test_smoke_step3_step4_unimplemented_must_fail",
            },
            {
                "id": "REV-M1",
                "desc": "check_smoke_seed_namespace allows forbidden partitions (replaces raise with pass)",
                "file": smoke_file,
                "orig_target": """            raise ValueError(
                f"Smoke seed namespace {seed_namespace!r} must not overlap with {forbidden!r}"
            )""",
                "mutant": """            pass""",
                "test": "test_smoke_seed_namespace_rejects_overlapping",
            },
            {
                "id": "REV-M2",
                "desc": "make_smoke_timing_batch alters registered batch size from spec.BATCH_SIZE (32) to 16",
                "file": smoke_file,
                "orig_target": "batch_size: int = spec.BATCH_SIZE,",
                "mutant": "batch_size: int = 16,",
                "test": "test_smoke_batch_shape_registered",
            },
            {
                "id": "REV-M3",
                "desc": "_resolve_default_runner for mode smoke returns dummy runner with wrong output",
                "file": commands_file,
                "orig_target": "return _smoke_runner",
                "mutant": "return None",
                "test": "test_commands_dispatch_to_runners",
            },
            {
                "id": "REV-M4",
                "desc": "check_smoke_budget forces sufficient = True even when total exceeds ceiling",
                "file": smoke_file,
                "orig_target": "sufficient = total_estimated_seconds <= budget_ceiling_seconds",
                "mutant": "sufficient = True",
                "test": "test_smoke_over_budget_fails",
            },
        ]

        log_lines = []
        results = []

        for m in mutations:
            f = m["file"]
            sha_before = file_sha(f)
            content = f.read_text(encoding="utf-8")
            assert m["orig_target"] in content, f"Target pattern not found in {f.name} for {m['id']}"

            # Apply
            mutated_content = content.replace(m["orig_target"], m["mutant"], 1)
            f.write_text(mutated_content, encoding="utf-8")
            sha_mut = file_sha(f)
            assert sha_mut != sha_before

            test_cmd = [
                sys.executable, "-m", "pytest",
                str(sandbox / "tests" / "v9" / "experiments" / "test_s2_wiring.py"),
                "-k", m["test"],
                "-q",
            ]
            test_res = subprocess.run(test_cmd, cwd=str(sandbox), env=env, capture_output=True, text=True)
            killed = (test_res.returncode != 0)
            status_str = "KILLED (RED)" if killed else "SURVIVED (GREEN)"

            # Restore
            f.write_text(content, encoding="utf-8")
            sha_after = file_sha(f)
            assert sha_after == sha_before, f"Restore SHA mismatch for {f.name}"

            log_entry = (
                f"=== Mutation {m['id']} ===\n"
                f"Description: {m['desc']}\n"
                f"Test targeted: {m['test']}\n"
                f"Status: {status_str}\n"
                f"Exit code: {test_res.returncode}\n"
                f"Stdout:\n{test_res.stdout}\n"
                f"Stderr:\n{test_res.stderr}\n"
                f"Byte restoration SHA matched: True\n\n"
            )
            log_lines.append(log_entry)
            print(f"[{m['id']}] {status_str} (exit={test_res.returncode}) - {m['desc']}")

            results.append({
                "id": m["id"],
                "description": m["desc"],
                "test_targeted": m["test"],
                "killed": killed,
                "exit_code": test_res.returncode,
                "status": status_str,
                "restored_sha_matched": True,
            })

        summary = {
            "reviewer_agent": "gemini-7k2q",
            "task_id": "ainerzero.V9.P149",
            "target_task": "ainerzero.V9.P148",
            "total_mutations": len(results),
            "killed_mutations": sum(1 for r in results if r["killed"]),
            "survived_mutations": sum(1 for r in results if not r["killed"]),
            "all_killed": all(r["killed"] for r in results),
            "mutations": results,
        }

        with open(REVIEW_DIR / "mutation_summary.json", "w", encoding="utf-8") as sf:
            json.dump(summary, sf, indent=2)

        with open(REVIEW_DIR / "mutation_log.txt", "w", encoding="utf-8") as lf:
            lf.write("".join(log_lines))

        print(f"Mutation summary written to {REVIEW_DIR / 'mutation_summary.json'}")
        print(f"Mutation log written to {REVIEW_DIR / 'mutation_log.txt'}")
        return 0 if summary["all_killed"] else 1


if __name__ == "__main__":
    sys.exit(main())
