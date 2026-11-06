#!/usr/bin/env python3
"""Reviewer independent mutations runner for ainerzero.V9.P120.

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
        "id": "P120-REV-M1",
        "name": "data_py_inject_gridlab2d",
        "file": "src/ainerzero/v9/experiments/s2/data.py",
        "target": "from typing import Any",
        "replacement": "from typing import Any\nimport ainerzero.environments.gridlab2d",
        "expected_fail_test": "tests/v9/experiments/test_s2_world.py::test_no_gridlab_module_imported",
        "desc": "Inject gridlab2d import into s2/data.py (verified by test_no_gridlab_module_imported)",
    },
    {
        "id": "P120-REV-M2",
        "name": "begin_episode_noop_in_hierarchical",
        "file": "src/ainerzero/v9/experiments/s2/fwd_counter.py",
        "target": "    def begin_episode(self) -> None:\n        \"\"\"Begin a new episode: clear episode-scoped caches.\"\"\"\n        self._goal_cache = None\n        self._goal_sha = None",
        "replacement": "    def begin_episode(self) -> None:\n        pass",
        "expected_fail_test": "tests/v9/experiments/test_s2_planner.py::test_hierarchical_goal_embedding_cached_across_decisions_in_episode",
        "desc": "ForwardCounter.begin_episode() does not clear cache; hierarchical new episode fails assert snap4['by_name']['encode'] == 2",
    },
    {
        "id": "P120-REV-M3",
        "name": "world_line_of_sight_always_true",
        "file": "src/ainerzero/v9/experiments/s2/world.py",
        "target": "def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:\n    \"\"\"算法参照 GridLab-v1 的 line_of_sight（ainerzero.environments 中的 GridLab-v1 模块）。\"\"\"\n    if ax == bx and ay == by:\n        return True",
        "replacement": "def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:\n    return True",
        "expected_fail_test": "tests/v9/experiments/test_s2_world.py::test_line_of_sight_closed_form",
        "desc": "world.py line_of_sight always returns True (no raycast occlusion), failing LOS closed form test",
    },
    {
        "id": "P120-REV-M4",
        "name": "world_docstring_lowercase_gridlab_leak",
        "file": "src/ainerzero/v9/experiments/s2/world.py",
        "target": "    \"\"\"算法参照 GridLab-v1 的 line_of_sight（ainerzero.environments 中的 GridLab-v1 模块）。\"\"\"",
        "replacement": "    \"\"\"算法参照 gridlab_v1 的 line_of_sight。\"\"\"",
        "expected_fail_test": "tests/test_gridlab_s07.py::test_not_wired_into_training",
        "desc": "Re-introduce lowercase gridlab into world.py docstring, failing test_gridlab_s07 guard",
    },
]


def run_mutations():
    temp_dir = Path(tempfile.mkdtemp(prefix="p120_rev_mutations_"))
    try:
        replica_src = temp_dir / "src"
        replica_tests = temp_dir / "tests"
        shutil.copytree(ROOT / "src", replica_src)
        shutil.copytree(ROOT / "tests", replica_tests)
        shutil.copy2(ROOT / "pyproject.toml", temp_dir / "pyproject.toml")

        # Verify import isolation in subprocess
        check_env = os.environ.copy()
        check_env["PYTHONPATH"] = f"{temp_dir}:{replica_src}"
        res = subprocess.run(
            [sys.executable, "-c", "import ainerzero.v9.experiments.s2.world as w; print(w.__file__)"],
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
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", m["expected_fail_test"], "-q"],
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

        out_path = ROOT / "reports/V9-S2-P120/review/mutations_review.json"
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"Saved review mutation results to {out_path}")
        return results
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_mutations()
