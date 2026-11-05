#!/usr/bin/env python3
"""Isolated source-mutation bad controls runner for E1 R3 data runner (ainerzero.V9.P75).

Executes 3 isolated source-mutation bad controls in temporary sandbox copies:
1. Only seal P family final (leave S unsealed) -> RED (assert "S" in sealed_info fails).
2. Skip calling generator (only export existing files) -> RED (assert P_train == 1 fails).
3. Remove budget checks -> RED (generator runner invoked when budget <= 0, pytest.fail).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
PYTEST_BIN = REPO_ROOT / ".venv-ainerzero" / "bin" / "pytest"


def run_mutation_test(
    name: str,
    description: str,
    mutations: list[tuple[str, str]],
    test_target: str,
) -> dict[str, Any]:
    print(f"\n[MUTATION] {name}: {description}")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        shutil.copytree(REPO_ROOT / "src", tdp / "src")
        shutil.copytree(REPO_ROOT / "tests", tdp / "tests")
        shutil.copy(REPO_ROOT / "pyproject.toml", tdp / "pyproject.toml")

        data_runner_file = tdp / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "data_runner.py"
        code = data_runner_file.read_text(encoding="utf-8")

        for target, replacement in mutations:
            if target not in code:
                raise RuntimeError(f"Target pattern not found in data_runner.py for mutation {name}: {target[:40]}")
            code = code.replace(target, replacement, 1)

        data_runner_file.write_text(code, encoding="utf-8")

        proc = subprocess.run(
            [str(PYTEST_BIN), test_target, "-v"],
            cwd=tdp,
            env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )

        is_red = proc.returncode != 0
        status = "RED (FAILED as expected)" if is_red else "GREEN (UNEXPECTED PASS)"
        print(f"Status: {status} (exit code {proc.returncode})")

        return {
            "name": name,
            "description": description,
            "test_target": test_target,
            "exit_code": proc.returncode,
            "is_red": is_red,
            "status": status,
            "stdout_tail": "\n".join(proc.stdout.strip().splitlines()[-10:]),
        }


def main():
    print("=" * 70)
    print("RUNNING ISOLATED BAD CONTROLS FOR E1 DATA RUNNER (ainerzero.V9.P75)")
    print("=" * 70)

    # Mutation 1: Only seal P family final
    m1 = run_mutation_test(
        "bad_control_1_only_seal_p_family",
        "Only seal P family final partition, leaving S unsealed",
        [
            (
                'for fam in DEFAULT_FAMILIES:\n        final_seqs = raw_sequences[fam]["final"]',
                'for fam in ("P",):  # bad control: only seal P\n        final_seqs = raw_sequences[fam]["final"]',
            )
        ],
        "tests/test_e1_data_runner.py::test_blender_smoke_generation_and_export",
    )

    # Mutation 2: Skip generator invocation
    m2_target = """    if runner_fn is not None:
        runner_fn(raw_path, norm_counts)
    else:
        run_awz_generator_subprocess(
            raw_path,
            norm_counts,
            awz_root=awz_root,
            awz_python=awz_python,
            timeout_s=remaining_budget,
        )"""
    m2 = run_mutation_test(
        "bad_control_2_skip_generator_invocation",
        "Do not invoke generator subprocess, only attempt to export existing files",
        [(m2_target, "    pass  # bad control: skip calling generator")],
        "tests/test_e1_data_runner.py::test_blender_smoke_generation_and_export",
    )

    # Mutation 3: Remove budget check
    m3 = run_mutation_test(
        "bad_control_3_remove_budget_checks",
        "Remove budget and deadline fail-closed checks",
        [
            (
                "if wall_budget_s <= 0 or (deadline is not None and clock() >= deadline):",
                "if False:  # bad control: bypass initial budget check",
            ),
            (
                "if remaining_budget <= 0:",
                "if False:  # bad control: bypass remaining budget check",
            ),
        ],
        "tests/test_e1_data_runner.py::test_zero_budget_immediately_stopped_without_calling_subprocess",
    )

    results = [m1, m2, m3]

    print("\n" + "=" * 70)
    print("BAD CONTROLS SUMMARY:")
    all_red = True
    for r in results:
        print(f"[{r['status']}] {r['name']}: {r['description']}")
        if not r["is_red"]:
            all_red = False
    print("=" * 70)

    out_file = REPO_ROOT / "reports" / "V9-E1R3" / "gemini-cv3y" / "bad_controls_summary.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Summary written to {out_file}")

    if not all_red:
        print("ERROR: Not all bad controls were RED!")
        sys.exit(1)
    else:
        print("ALL 3 BAD CONTROLS VERIFIED RED.")


if __name__ == "__main__":
    main()
