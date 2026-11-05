#!/usr/bin/env python3
"""Adversarial mutation checks on S1 final read-once security mechanisms.
Executes in isolated test harness without modifying production files.
Proves that removing READ_ONCE, token verification, or seal checks turns tests RED.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "adversarial_evidence.json"

def test_mutations():
    results = {}

    # Baseline: check that original tests pass
    p0 = subprocess.run([sys.executable, "-m", "pytest", "tests/v9/experiments/test_s1_final_eval.py", "-q"],
                        cwd=str(REPO), capture_output=True, text=True)
    assert p0.returncode == 0, f"Baseline tests failed: {p0.stdout}\n{p0.stderr}"
    results["baseline_passed"] = True

    # Setup isolated test workdir
    temp_dir = Path(tempfile.mkdtemp(prefix="adv-final-eval-"))
    try:
        isolated_src = temp_dir / "src"
        shutil.copytree(REPO / "src", isolated_src)
        
        # Mutation 1: Remove exclusive O_EXCL marker creation in data.py
        data_py = isolated_src / "ainerzero/v9/experiments/s1/data.py"
        code1 = data_py.read_text(encoding="utf-8")
        assert "os.O_CREAT | os.O_EXCL | os.O_WRONLY" in code1
        # Mutate to allow non-exclusive opening (no O_EXCL) and no exception on exist
        mutated1 = code1.replace(
            "fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)",
            "fd = os.open(marker, os.O_CREAT | os.O_WRONLY, 0o444)  # MUTATED"
        )
        data_py.write_text(mutated1, encoding="utf-8")
        
        env1 = dict(os.environ, PYTHONPATH=f"{isolated_src}:{os.environ.get('PYTHONPATH', '')}")
        p1 = subprocess.run([
            sys.executable, "-m", "pytest",
            "tests/v9/experiments/test_s1_final_eval.py::test_open_once_creates_the_marker_reads_and_refuses_a_second_read",
            "-q"
        ], cwd=str(REPO), env=env1, capture_output=True, text=True)
        
        results["mutation_1_remove_o_excl"] = {
            "test": "test_open_once_creates_the_marker_reads_and_refuses_a_second_read",
            "returncode": p1.returncode,
            "turned_red": p1.returncode != 0,
            "stdout_summary": p1.stdout.strip()[:200]
        }
        assert p1.returncode != 0, "Mutation 1 failed to turn test red!"

        # Mutation 2: Bypass token nonce validation in data.py
        data_py.write_text(code1, encoding="utf-8")  # start from clean code1
        mutated2 = code1.replace(
            "and token.nonce in _ISSUED_FINAL_TOKENS",
            "# and token.nonce in _ISSUED_FINAL_TOKENS  # MUTATED"
        )
        data_py.write_text(mutated2, encoding="utf-8")
        p2 = subprocess.run([
            sys.executable, "-m", "pytest",
            "tests/v9/experiments/test_s1_final_eval.py::test_final_is_unreadable_without_an_issued_token",
            "-q"
        ], cwd=str(REPO), env=env1, capture_output=True, text=True)

        results["mutation_2_bypass_token_nonce_validity"] = {
            "test": "test_final_is_unreadable_without_an_issued_token",
            "returncode": p2.returncode,
            "turned_red": p2.returncode != 0,
            "stdout_summary": p2.stdout.strip()[:200]
        }
        assert p2.returncode != 0, "Mutation 2 failed to turn test red!"

        # Mutation 3: Bypass already_read refusal in final_eval.py
        data_py.write_text(code1, encoding="utf-8")  # restore data.py
        final_eval_py = isolated_src / "ainerzero/v9/experiments/s1/final_eval.py"
        code3 = final_eval_py.read_text(encoding="utf-8")
        assert 'if seal.get("already_read"):' in code3
        mutated3 = code3.replace(
            'if seal.get("already_read"):',
            'if False and seal.get("already_read"):  # MUTATED: ignore already_read'
        )
        final_eval_py.write_text(mutated3, encoding="utf-8")
        p3 = subprocess.run([
            sys.executable, "-m", "pytest",
            "tests/v9/experiments/test_s1_final_eval.py::test_final_eval_refuses_unapproved_already_read_and_a_bad_budget_without_writing",
            "-q"
        ], cwd=str(REPO), env=env1, capture_output=True, text=True)

        results["mutation_3_bypass_already_read_refusal"] = {
            "test": "test_final_eval_refuses_unapproved_already_read_and_a_bad_budget_without_writing",
            "returncode": p3.returncode,
            "turned_red": p3.returncode != 0,
            "stdout_summary": p3.stdout.strip()[:200]
        }
        assert p3.returncode != 0, "Mutation 3 failed to turn test red!"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    results["all_adversarial_mutations_turned_red"] = True
    OUT.write_text(json.dumps(results, indent=2))
    print(f"Adversarial checks completed successfully! Results written to {OUT}")
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    test_mutations()
