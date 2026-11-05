"""Isolated source mutation test runner for T4 teacher benchmark guard gates.

Verifies that the guard code is load-bearing by applying 4 genuine, isolated
source mutations to a temporary copy of the codebase and confirming that each
targeted negative test turns red (fails).

Mutations tested:
1. Sabotage Approval Gate: Bypasses RESEARCH_LOG check -> test_approval_missing_rejected fails
2. Sabotage Per-Run Budget Gate: Bypasses per-run 600s check -> test_per_run_budget_exceeded_rejected fails
3. Sabotage Cumulative Budget Gate: Bypasses 1800s cumulative check -> test_cumulative_budget_exceeded_rejected fails
4. Sabotage Resource Gate: Bypasses 32 GiB RSS check -> test_resource_gate_rss_refused fails

Guarantees:
- Zero mutations in working tree
- Completely isolated in temp directory
- Confirms exit codes and failure output
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_EXE = REPO_ROOT / ".venv/bin/python"


def run_isolated_mutation_test(
    mutation_name: str,
    target_relpath: str,
    target_str: str,
    replacement_str: str,
    test_k_name: str,
) -> dict:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_src = Path(tmpdir) / "src"
        shutil.copytree(REPO_ROOT / "src", tmp_src)

        mutated_file = tmp_src / target_relpath
        original_content = mutated_file.read_text(encoding="utf-8")
        if target_str not in original_content:
            raise ValueError(f"Target string not found in {target_relpath}: {target_str}")

        mutated_content = original_content.replace(target_str, replacement_str, 1)
        mutated_file.write_text(mutated_content, encoding="utf-8")

        # Run pytest overriding pythonpath to force import from tmp_src
        cmd = [
            str(PYTHON_EXE),
            "-m",
            "pytest",
            "-o",
            f"pythonpath={tmp_src}",
            "tests/v9/teachers/test_benchmark_guard.py",
            "-k",
            test_k_name,
            "-v",
        ]

        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        turned_red = proc.returncode != 0
        return {
            "mutation_name": mutation_name,
            "target_file": target_relpath,
            "test_target": test_k_name,
            "return_code": proc.returncode,
            "turned_red": turned_red,
            "output_snippet": proc.stdout[-400:] if proc.stdout else "",
        }


def main():
    mutations = [
        {
            "name": "approval_gate_sabotage",
            "target_relpath": "ainerzero/v9/teachers/benchmark.py",
            "target": 'if not in_target_section or not section_lines:\n        raise BenchmarkApprovalRefused(',
            "replacement": 'if False:\n        raise BenchmarkApprovalRefused(',
            "test_k": "test_approval_missing_rejected",
        },
        {
            "name": "per_run_budget_gate_sabotage",
            "target_relpath": "ainerzero/v9/teachers/benchmark.py",
            "target": 'if spec.wall_budget_seconds > T4_MAX_PER_RUN_WALL_SECONDS:',
            "replacement": 'if False and spec.wall_budget_seconds > T4_MAX_PER_RUN_WALL_SECONDS:',
            "test_k": "test_per_run_budget_exceeded_rejected",
        },
        {
            "name": "cumulative_budget_gate_sabotage",
            "target_relpath": "ainerzero/v9/teachers/benchmark.py",
            "target": 'cumulative_reserved + spec.wall_budget_seconds\n                    > T4_MAX_CUMULATIVE_WALL_SECONDS',
            "replacement": 'False and (\n                        cumulative_reserved + spec.wall_budget_seconds\n                        > T4_MAX_CUMULATIVE_WALL_SECONDS\n                    )',
            "test_k": "test_cumulative_budget_exceeded_rejected",
        },
        {
            "name": "resource_gate_sabotage",
            "target_relpath": "ainerzero/v9/teachers/benchmark.py",
            "target": 'if rss_bytes > max_rss_bytes:',
            "replacement": 'if False and rss_bytes > max_rss_bytes:',
            "test_k": "test_resource_gate_rss_refused",
        },
    ]

    results = []
    all_passed = True
    print("=" * 60)
    print("Running Isolated Source Mutation Verification (4 Guard Gates)")
    print("=" * 60)

    for m in mutations:
        res = run_isolated_mutation_test(
            mutation_name=m["name"],
            target_relpath=m["target_relpath"],
            target_str=m["target"],
            replacement_str=m["replacement"],
            test_k_name=m["test_k"],
        )
        results.append(res)
        status = "PASSED (TURNS RED)" if res["turned_red"] else "FAILED (STILL GREEN)"
        print(f"[{status}] {res['mutation_name']}: rc={res['return_code']}")
        if not res["turned_red"]:
            all_passed = False

    summary = {
        "all_mutations_turned_red": all_passed,
        "count": len(results),
        "results": results,
    }

    out_file = REPO_ROOT / "reports/V9-T23/sabotage_result.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print("\nSummary written to reports/V9-T23/sabotage_result.json")

    if not all_passed:
        print("ERROR: Not all mutations turned red!")
        sys.exit(1)
    else:
        print("SUCCESS: All 4 mutations turned red under genuine source sabotage.")


if __name__ == "__main__":
    main()
