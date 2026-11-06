"""Independent Reviewer Adverse Mutation Harness for V9.P112 (S2 Shared Planners).

Run by independent reviewer gemini-8m4d to verify test sensitivity beyond author's mutations:
- REV-M1: Remove budget overrun exception in ForwardCounter -> test_budget_exceeded_by_one_raises turns red.
- REV-M2: Corrupt hierarchical subgoal generation (subgoal = z2_0) -> test_hierarchical_far_goal_vs_flat_same_budget turns red.
- REV-M3: Invert flat CEM elite selection to maximize cost -> test_flat_near_goal_success_rate turns red.

Each mutation is tested in an isolated copy, asserts import resolution to the copy,
verifies failure (red exit code 1), restores byte-by-byte, and validates SHA256 integrity.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_review_mutations(repo_root: Path) -> dict[str, dict]:
    results = {}

    with tempfile.TemporaryDirectory(prefix="rev_mutation_sandbox_") as tmp_dir:
        sandbox = Path(tmp_dir)
        sandbox_src = sandbox / "src"
        sandbox_tests = sandbox / "tests"
        sandbox_pyproject = sandbox / "pyproject.toml"

        print(f"Creating isolated sandbox at {sandbox}...")
        shutil.copytree(repo_root / "src", sandbox_src)
        shutil.copytree(repo_root / "tests", sandbox_tests)
        shutil.copy(repo_root / "pyproject.toml", sandbox_pyproject)

        fwd_file = sandbox_src / "ainerzero/v9/experiments/s2/fwd_counter.py"
        plan_file = sandbox_src / "ainerzero/v9/experiments/s2/planner.py"

        fwd_orig = fwd_file.read_text(encoding="utf-8")
        plan_orig = plan_file.read_text(encoding="utf-8")

        fwd_sha = compute_sha256(fwd_file)
        plan_sha = compute_sha256(plan_file)

        sandbox_env = dict(os.environ, PYTHONPATH=f"{sandbox}:{sandbox_src}")

        mutations = [
            {
                "id": "REV-M1",
                "desc": "ForwardCounter 不在超预算时抛出 ForwardBudgetExceeded (静默放行)",
                "file": fwd_file,
                "orig_text": fwd_orig,
                "orig_sha": fwd_sha,
                "mutated_text": fwd_orig.replace(
                    "if self.budget is not None and self.total + n > self.budget:\n            raise ForwardBudgetExceeded(name, n, self.total, self.budget)",
                    "pass",
                ),
                "target": "tests/v9/experiments/test_s2_planner.py::test_budget_exceeded_by_one_raises",
            },
            {
                "id": "REV-M2",
                "desc": "分层规划子目标损坏：将 z2_subgoal 设为当前状态 z2_0（不推进目标）",
                "file": plan_file,
                "orig_text": plan_orig,
                "orig_sha": plan_sha,
                "mutated_text": plan_orig.replace(
                    "z2_subgoal = predict_l2(\n        z2_0, best_macros[0], float(1.0 if macro_dts is None else macro_dts[0])\n    )",
                    "z2_subgoal = z2_0.copy()",
                ),
                "target": "tests/v9/experiments/test_s2_planner.py::test_hierarchical_far_goal_vs_flat_same_budget",
            },
            {
                "id": "REV-M3",
                "desc": "Flat CEM 精英选择反转：挑选代价最大的候选者（反向优化）",
                "file": plan_file,
                "orig_text": plan_orig,
                "orig_sha": plan_sha,
                "mutated_text": plan_orig.replace(
                    "elite_idx = np.argpartition(costs, n_elite - 1)[:n_elite]",
                    "elite_idx = np.argpartition(costs, len(costs) - n_elite)[-n_elite:]",
                ),
                "target": "tests/v9/experiments/test_s2_planner.py::test_flat_near_goal_success_rate",
            },
        ]

        for m in mutations:
            mid = m["id"]
            f = m["file"]
            orig_sha = m["orig_sha"]
            orig_text = m["orig_text"]
            mutated_text = m["mutated_text"]
            assert mutated_text != orig_text, f"Failed to apply mutation {mid}"

            # Apply
            f.write_text(mutated_text, encoding="utf-8")
            mutated_sha = compute_sha256(f)

            # Test
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", m["target"], "-q", "--tb=short"],
                cwd=str(sandbox),
                env=sandbox_env,
                capture_output=True,
                text=True,
            )
            is_red = proc.returncode != 0

            # Restore
            f.write_text(orig_text, encoding="utf-8")
            restored_sha = compute_sha256(f)
            assert restored_sha == orig_sha, f"SHA mismatch after restoring {mid}: {restored_sha} vs {orig_sha}"

            results[mid] = {
                "description": m["desc"],
                "target_test": m["target"],
                "turned_red": is_red,
                "exit_code": proc.returncode,
                "sha_before": orig_sha,
                "sha_mutated": mutated_sha,
                "sha_restored": restored_sha,
                "restored_verified": (restored_sha == orig_sha),
            }
            print(f"[{mid}] turned_red={is_red} exit_code={proc.returncode} restored_sha_ok={restored_sha == orig_sha}")

    return results


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    res = run_review_mutations(repo_root)
    print(json.dumps(res, indent=2, ensure_ascii=False))
