#!/usr/bin/env python3
"""Reviewer independent mutations runner for ainerzero.V9.P118.

Executes mutations in an isolated replica directory (src, tests, pyproject.toml).
Asserts that imports resolve to the replica.
Restores each file by byte-level copy and checks SHA256 after each mutation.
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

ROOT = Path(__file__).resolve().parents[3]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


MUTATIONS = [
    {
        "id": "REV-M1",
        "name": "hierarchical_cem_bypasses_goal_embedding",
        "file": "src/ainerzero/v9/experiments/s2/planner.py",
        "target": "z1_goal = counter.goal_embedding(goal_obs, encode)",
        "replacement": "z1_goal = encode(goal_obs)",
        "expected_fail_test": "test_goal_embedding_cached_across_decisions_in_episode",
        "desc": "Hierarchical CEM bypasses counter.goal_embedding and calls encode(goal_obs) directly each decision",
    },
    {
        "id": "REV-M2",
        "name": "counter_reset_clears_goal_cache",
        "file": "src/ainerzero/v9/experiments/s2/fwd_counter.py",
        "target": "    def reset(self) -> None:\n        \"\"\"Reset decision-level counters; preserves episode-level goal cache.\"\"\"\n        self._counts.clear()\n        self.total = 0",
        "replacement": "    def reset(self) -> None:\n        self._counts.clear()\n        self.total = 0\n        self._goal_cache = None\n        self._goal_sha = None",
        "expected_fail_test": "test_goal_embedding_cached_across_decisions_in_episode",
        "desc": "ForwardCounter.reset() errantly clears episode goal cache, forcing re-encoding every decision",
    },
    {
        "id": "REV-M3",
        "name": "goal_sha_hardcoded_constant",
        "file": "src/ainerzero/v9/experiments/s2/fwd_counter.py",
        "target": "sha = hashlib.sha256(canonical_bytes(goal_obs)).hexdigest()",
        "replacement": "sha = \"hardcoded_sha_constant\"",
        "expected_fail_test": "test_goal_embedding_changed_goal_in_same_episode_raises",
        "desc": "goal_embedding hashes to a constant string, preventing detection of goal changes in the same episode",
    },
    {
        "id": "REV-M4",
        "name": "flat_cem_bypasses_goal_embedding",
        "file": "src/ainerzero/v9/experiments/s2/planner.py",
        "target": "z_goal = counter.goal_embedding(goal_obs, encode)",
        "replacement": "z_goal = encode(goal_obs)",
        "expected_fail_test": "test_goal_embedding_cached_across_decisions_in_episode",
        "desc": "Flat CEM bypasses counter.goal_embedding and calls encode(goal_obs) directly each decision",
    },
    {
        "id": "REV-M5",
        "name": "goal_embedding_unwrapped_call_bypasses_charge",
        "file": "src/ainerzero/v9/experiments/s2/fwd_counter.py",
        "target": "        if hasattr(encode, \"__wrapped__\"):\n            res = encode(goal_obs)",
        "replacement": "        if hasattr(encode, \"__wrapped__\"):\n            res = encode.__wrapped__(goal_obs)",
        "expected_fail_test": "test_goal_embedding_cached_across_decisions_in_episode",
        "desc": "goal_embedding unwraps encode on first call to bypass the initial count charge",
    },
]


def run_mutations():
    temp_dir = Path(tempfile.mkdtemp(prefix="p118_rev_mutations_"))
    try:
        replica_src = temp_dir / "src"
        replica_tests = temp_dir / "tests"
        shutil.copytree(ROOT / "src", replica_src)
        shutil.copytree(ROOT / "tests", replica_tests)
        shutil.copy2(ROOT / "pyproject.toml", temp_dir / "pyproject.toml")

        # Verify import isolation in subprocess
        check_env = os.environ.copy()
        check_env["PYTHONPATH"] = str(replica_src)
        res = subprocess.run(
            [sys.executable, "-c", "import ainerzero.v9.experiments.s2.planner as p; print(p.__file__)"],
            cwd=temp_dir,
            env=check_env,
            capture_output=True,
            text=True,
            check=True,
        )
        imported_path = res.stdout.strip()
        assert str(replica_src) in imported_path, f"Isolation failure: imported {imported_path}"

        results = []
        for m in MUTATIONS:
            target_file = temp_dir / m["file"]
            original_content = target_file.read_text(encoding="utf-8")
            original_sha = sha256_file(target_file)
            assert m["target"] in original_content, f"Target string not found for {m['id']} in {target_file}"

            # Apply mutation
            mutated_content = original_content.replace(m["target"], m["replacement"], 1)
            target_file.write_text(mutated_content, encoding="utf-8")

            # Run pytest
            test_path = f"tests/v9/experiments/test_s2_planner.py::{m['expected_fail_test']}"
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", test_path, "-q"],
                cwd=temp_dir,
                env=check_env,
                capture_output=True,
                text=True,
            )

            # Restore original
            target_file.write_text(original_content, encoding="utf-8")
            restored_sha = sha256_file(target_file)
            assert restored_sha == original_sha, f"Restoration mismatch for {m['id']}"

            is_red = (proc.returncode != 0)
            results.append({
                "id": m["id"],
                "name": m["name"],
                "desc": m["desc"],
                "expected_fail_test": m["expected_fail_test"],
                "returncode": proc.returncode,
                "is_red": is_red,
                "stdout": proc.stdout.strip()[:300],
                "sha_restored": True,
            })
            print(f"[{m['id']}] {'RED (Caught)' if is_red else 'SURVIVED'}: exit={proc.returncode}")

        out_path = ROOT / "reports/V9-S2-P118/review/mutations_review.json"
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Saved review mutation results to {out_path}")
        return results
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_mutations()
