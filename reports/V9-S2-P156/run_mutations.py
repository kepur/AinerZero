#!/usr/bin/env python3
"""Run bad control mutations in isolated sandbox for P156.

Mutations:
- P156-M1: Disable dev pre-check in run_dev_eval -> targeted test turns RED.
- P156-M2: Relax collusion threshold to -1.0 in run_post_train_gates -> targeted test turns RED.
- P156-M3: Identity permutation for C-arm subgoal shuffle -> targeted test turns RED.
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
REPORT_DIR = REPO_ROOT / "reports" / "V9-S2-P156"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

SRC_FILE = REPO_ROOT / "src/ainerzero/v9/experiments/s2/eval_runner.py"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    original_sha = sha256_file(SRC_FILE)
    original_code = SRC_FILE.read_text(encoding="utf-8")

    mutations = {
        "P156-M1": {
            "name": "disable_dev_precheck",
            "desc": "Disable dev pre-check in run_dev_eval",
            "target": '    if require_post_train_gates:\n        gates = ledger.get("post_train_gates")',
            "replacement": '    if False:\n        gates = ledger.get("post_train_gates")',
            "test": "tests/v9/experiments/test_s2_eval_runner.py::test_dev_eval_refused_without_post_train_gates",
        },
        "P156-M2": {
            "name": "relax_collusion_threshold",
            "desc": "Relax collusion threshold to -1.0 in run_post_train_gates",
            "target": "subgoal_drop_threshold: float = SUBGOAL_DROP_FLOOR,",
            "replacement": "subgoal_drop_threshold: float = -1.0,",
            "test": "tests/v9/experiments/test_s2_eval_runner.py::test_c_arm_collusion_detected_and_dev_refused",
        },
        "P156-M3": {
            "name": "identity_subgoal_shuffle",
            "desc": "Identity permutation for C-arm subgoal shuffle (no derangement/shuffle)",
            "target": (
                "        rng_shuffle = np.random.default_rng(shuffle_seed)\n"
                "        perm = rng_shuffle.permutation(n_c_eps)\n"
                "        if n_c_eps > 1:\n"
                "            fixed = np.where(perm == np.arange(n_c_eps))[0]\n"
                "            if len(fixed) > 0:\n"
                "                perm = (perm + 1) % n_c_eps"
            ),
            "replacement": "        perm = np.arange(n_c_eps)",
            "test": "tests/v9/experiments/test_s2_eval_runner.py::test_normal_model_passes_post_train_gates_and_enters_dev",
        },
    }

    summary: dict[str, dict] = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        shutil.copytree(REPO_ROOT / "src", tmp_path / "src")
        shutil.copytree(REPO_ROOT / "tests", tmp_path / "tests")
        shutil.copy(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")

        target_py = tmp_path / "src/ainerzero/v9/experiments/s2/eval_runner.py"
        env = {**os.environ, "PYTHONPATH": str(tmp_path / "src")}

        pytest_bin = REPO_ROOT / ".venv" / "bin" / "python"
        if not pytest_bin.exists():
            pytest_bin = Path(sys.executable)

        for m_id, m_info in mutations.items():
            assert m_info["target"] in original_code, f"Target not found for {m_id}"
            mutated_code = original_code.replace(m_info["target"], m_info["replacement"])
            target_py.write_text(mutated_code, encoding="utf-8")

            proc = subprocess.run(
                [str(pytest_bin), "-m", "pytest", m_info["test"]],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
            )
            detected = (proc.returncode != 0)
            summary[m_id] = {
                "name": m_info["name"],
                "description": m_info["desc"],
                "targeted_test": m_info["test"],
                "status": "KILLED" if detected else "SURVIVED",
                "mutation_detected": detected,
                "exit_code": proc.returncode,
                "stdout_tail": proc.stdout[-500:] if proc.stdout else "",
                "stderr_tail": proc.stderr[-300:] if proc.stderr else "",
            }
            print(f"[{m_id}] {m_info['name']}: {'KILLED (detected)' if detected else 'SURVIVED'}")

    # Verify original file untouched
    restored_sha = sha256_file(SRC_FILE)
    assert original_sha == restored_sha, "Source file SHA changed!"

    out_file = REPORT_DIR / "mutation_summary.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Saved mutation summary to {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
