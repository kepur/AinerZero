#!/usr/bin/env python3
"""Adversarial Mutant Check for P54 (gemini-b4e7).

Task requirement:
"至少在源码副本里把切片函数改错一处（例如 arm3 改用完整 h，或 arm4 改切 [:place_dim]），
证明作者的回归测试变红；"
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
ADV_DIR = Path(__file__).resolve().parent
MUTANT_SRC = ADV_DIR / "mutant_src"
PY = str(REPO / ".venv/bin/python")


def main():
    print("=== Starting Adversarial Mutant Check ===", flush=True)

    # 1. Clean and copy src to mutant_src
    if MUTANT_SRC.exists():
        shutil.rmtree(MUTANT_SRC)
    shutil.copytree(REPO / "src", MUTANT_SRC, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # 2. Tamper arm3 probe slice in spec.py:
    # Change probe slice for arm3 to full hidden dimension (0, 192)
    spec_file = MUTANT_SRC / "ainerzero/v9/experiments/s1/spec.py"
    orig_text = spec_file.read_text(encoding="utf-8")

    old_block = '    if arm_id == "arm3":\n        place = int(d["place_dim"])\n        return {"graph": (0, place), "probe": (0, place)}'
    new_block = '    if arm_id == "arm3":\n        place = int(d["place_dim"])\n        return {"graph": (0, place), "probe": (0, int(d["hidden"]))}'

    assert old_block in orig_text, "Target block not found in spec.py!"
    tampered_text = orig_text.replace(old_block, new_block)
    spec_file.write_text(tampered_text, encoding="utf-8")

    # Generate unified diff
    diff = "".join(difflib.unified_diff(
        orig_text.splitlines(keepends=True),
        tampered_text.splitlines(keepends=True),
        fromfile="spec.py (original r15)",
        tofile="spec.py (tampered mutant: arm3 probe uses hidden)"
    ))
    (ADV_DIR / "mutant_slice.diff").write_text(diff, encoding="utf-8")
    print("  Created mutant diff:\n" + diff, flush=True)

    # 3. Run pytest against mutant_src
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(MUTANT_SRC)

    cmd = [
        PY, "-m", "pytest",
        "tests/v9/experiments/test_s1_r15_registration.py",
        "-k", "test_probe_slices_match_the_stored_node_widths_not_hidden",
        "-v", "-p", "no:cacheprovider"
    ]
    res = subprocess.run(cmd, env=env, cwd=str(REPO), capture_output=True, text=True)
    (ADV_DIR / "mutant_pytest_failure.log").write_text(res.stdout + "\n" + res.stderr, encoding="utf-8")

    print(f"  Pytest return code on mutant: {res.returncode} (expected != 0)", flush=True)
    assert res.returncode != 0, "Regression test unexpectedly passed on broken slice code!"
    assert "FAILED" in res.stdout, "FAILED marker missing from pytest output!"
    assert "assert 192 == 32" in res.stdout or "assert stop - start == node_width" in res.stdout or "assert" in res.stdout

    # 4. Also run the sliced few shot test against a mutant that breaks evaluation query
    # E.g. arm4 map/graph slice mismatch
    mutant_eval_src = ADV_DIR / "mutant_eval_src"
    if mutant_eval_src.exists():
        shutil.rmtree(mutant_eval_src)
    shutil.copytree(REPO / "src", mutant_eval_src, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    eval_file = mutant_eval_src / "ainerzero/v9/experiments/s1/evaluation.py"
    orig_eval_text = eval_file.read_text(encoding="utf-8")
    # Revert backend.probe_query to backend.encode (the r14 bug!)
    old_eval_call = "h_start = backend.probe_query(model, sequence[\"obs\"][index])"
    new_eval_call = "h_start = backend.encode(model, sequence[\"obs\"][index])"
    assert old_eval_call in orig_eval_text, "Target query call not found in evaluation.py!"
    tampered_eval = orig_eval_text.replace(
        "h_start = backend.probe_query(model, sequence[\"obs\"][index])",
        "h_start = backend.encode(model, sequence[\"obs\"][index])"
    ).replace(
        "h_end = backend.probe_query(model, sequence[\"obs\"][index + 1])",
        "h_end = backend.encode(model, sequence[\"obs\"][index + 1])"
    )
    eval_file.write_text(tampered_eval, encoding="utf-8")

    diff_eval = "".join(difflib.unified_diff(
        orig_eval_text.splitlines(keepends=True),
        tampered_eval.splitlines(keepends=True),
        fromfile="evaluation.py (original r15)",
        tofile="evaluation.py (reverted to r14 un-sliced query)"
    ))
    (ADV_DIR / "mutant_eval_revert.diff").write_text(diff_eval, encoding="utf-8")

    env_eval = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env_eval["PYTHONPATH"] = str(mutant_eval_src)

    cmd_eval = [
        PY, "-m", "pytest",
        "tests/v9/experiments/test_s1_r15_registration.py",
        "-k", "test_few_shot_with_a_sliced_memory_completes_through_probe_query",
        "-v", "-p", "no:cacheprovider"
    ]
    res_eval = subprocess.run(cmd_eval, env=env_eval, cwd=str(REPO), capture_output=True, text=True)
    (ADV_DIR / "mutant_eval_failure.log").write_text(res_eval.stdout + "\n" + res_eval.stderr, encoding="utf-8")

    print(f"  Pytest return code on un-sliced eval query: {res_eval.returncode} (expected != 0)", flush=True)
    assert res_eval.returncode != 0, "Test unexpectedly passed when un-sliced query was used!"
    assert "FAILED" in res_eval.stdout

    summary = {
        "status": "adversarial_checks_passed",
        "mutant_1_arm3_probe_slice_changed": {
            "diff_file": str(ADV_DIR / "mutant_slice.diff"),
            "pytest_rc": res.returncode,
            "test_failed_as_expected": True,
            "failure_log": str(ADV_DIR / "mutant_pytest_failure.log")
        },
        "mutant_2_revert_probe_query_to_full_encode": {
            "diff_file": str(ADV_DIR / "mutant_eval_revert.diff"),
            "pytest_rc": res_eval.returncode,
            "test_failed_as_expected": True,
            "failure_log": str(ADV_DIR / "mutant_eval_failure.log")
        }
    }
    (ADV_DIR / "adversarial_results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print("=== Adversarial Mutant Check Completed Successfully ===", flush=True)


if __name__ == "__main__":
    main()
