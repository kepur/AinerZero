#!/usr/bin/env python3
"""Isolated source-mutation bad controls runner for E1 wiring entry (ainerzero.V9.P76 r2).

Executes 4 isolated source-mutation bad controls in temporary sandbox copies:
1. 预留改回 1 s -> test_reserve_amount_equals_cell_wall_budget turns RED.
2. 忽略 runner 状态，一律记 completed -> test_runner_stopped_recorded_as_stopped_and_permits_rerun turns RED.
3. 去掉 try/except -> test_runner_exception_recorded_as_failed turns RED.
4. 防重复也算上 stopped -> test_runner_stopped_recorded_as_stopped_and_permits_rerun turns RED.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
PYTEST_BIN = REPO_ROOT / ".venv-ainerzero" / "bin" / "pytest"


def run_mutation_test(
    name: str,
    description: str,
    mutations: list[tuple[str, str, str]],  # (rel_file, target, replacement)
    test_target: str,
) -> dict[str, Any]:
    print(f"\n[MUTATION] {name}: {description}")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        shutil.copytree(REPO_ROOT / "src", tdp / "src")
        shutil.copytree(REPO_ROOT / "tests", tdp / "tests")
        shutil.copy(REPO_ROOT / "pyproject.toml", tdp / "pyproject.toml")

        for rel_file, target, replacement in mutations:
            file_path = tdp / rel_file
            print(f"  Mutating isolated copy: {file_path}")
            code = file_path.read_text(encoding="utf-8")
            if target not in code:
                raise RuntimeError(f"Target pattern not found in {rel_file} for mutation {name}:\n{target[:60]}")
            code = code.replace(target, replacement, 1)
            file_path.write_text(code, encoding="utf-8")

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
            "stdout_tail": "\n".join(proc.stdout.strip().splitlines()[-12:]),
        }


def main():
    print("=" * 70)
    print("RUNNING ISOLATED BAD CONTROLS FOR E1 WIRING (ainerzero.V9.P76 r2)")
    print(f"Runner script location: {__file__}")
    print("=" * 70)

    # Mutation 1: 预留改回 1 s
    m1_target = "    ledger.reserve(run_id, active_seconds=cell_wall_budget)"
    m1_replacement = "    ledger.reserve(run_id, active_seconds=1.0)"
    m1 = run_mutation_test(
        "bad_control_1_revert_reservation_to_1s",
        "Revert central budget reservation from cell_wall_budget to hardcoded 1.0 s",
        [("src/ainerzero/v9/experiments/e1/worker.py", m1_target, m1_replacement)],
        "tests/test_e1_wiring.py::test_reserve_amount_equals_cell_wall_budget",
    )

    # Mutation 2: 忽略 runner 状态，一律记 completed
    m2_target = """    runner_status = result_data.get("status") if isinstance(result_data, dict) else None
    if runner_status == "stopped":
        final_state = "stopped"
        reason = result_data.get("reason", "runner_stopped")
    elif runner_status == "failed":
        final_state = "failed"
        reason = result_data.get("reason", "runner_failed")
    else:
        final_state = "completed"
        reason = "finished_successfully\""""
    m2_replacement = """    final_state = "completed"
    reason = "finished_successfully\""""
    m2 = run_mutation_test(
        "bad_control_2_ignore_runner_status_always_completed",
        "Ignore runner returned status and unconditionally finalize as completed",
        [("src/ainerzero/v9/experiments/e1/worker.py", m2_target, m2_replacement)],
        "tests/test_e1_wiring.py::test_runner_stopped_recorded_as_stopped_and_permits_rerun",
    )

    # Mutation 3: 去掉 try/except
    m3_target = """    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {str(exc)}"
        ledger.finish_run(run_id, state="failed", reason=err_msg)
        raise"""
    m3_replacement = """    except Exception:
        raise"""
    m3 = run_mutation_test(
        "bad_control_3_remove_runner_try_except",
        "Remove try/except around runner invocation leaving failed runs in work state",
        [("src/ainerzero/v9/experiments/e1/worker.py", m3_target, m3_replacement)],
        "tests/test_e1_wiring.py::test_runner_exception_recorded_as_failed",
    )

    # Mutation 4: 防重复也算上 stopped
    m4_target = """        for row in cursor.fetchall():
            state = row["state"]
            if state != "completed":
                continue"""
    m4_replacement = """        for row in cursor.fetchall():
            state = row["state"]
            if state not in ("completed", "stopped"):
                continue"""
    m4 = run_mutation_test(
        "bad_control_4_anti_duplicate_counts_stopped_runs",
        "Modify check_cell_already_completed to count stopped runs as completed (blocks rerun)",
        [("src/ainerzero/v9/experiments/e1/worker.py", m4_target, m4_replacement)],
        "tests/test_e1_wiring.py::test_runner_stopped_recorded_as_stopped_and_permits_rerun",
    )

    results = [m1, m2, m3, m4]
    all_passed = all(r["is_red"] for r in results)

    output_summary = REPO_ROOT / "reports" / "V9-E1W" / "gemini-cv3y" / "r2" / "bad_controls_summary.json"
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_summary.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    print("\n" + "=" * 70)
    print(f"SUMMARY: {'ALL 4 RED (PASSED)' if all_passed else 'SOME FAILED TO TRIGGER RED'}")
    print(f"Summary written to: {output_summary}")
    print("=" * 70)

    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
