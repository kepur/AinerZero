#!/usr/bin/env python3
"""Run 4 adversarial mutations for P126 in an isolated sandbox.

- P126-M1: Experiment-level max_wall_seconds changed from 72h to 10h -> test_d turns RED.
- P126-M2: Phase ceiling only queries current EXPERIMENT_ID -> test_c turns RED.
- P126-M3: Anti-duplicate check ignores seed -> test_b turns RED.
- P126-M4: Approval scanning accepts blockquotes -> test_e turns RED.

All mutations run inside a temporary copy, assert isolation, and verify byte-level SHA restoration.
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

ROOT = Path(__file__).resolve().parents[2]


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


MUTATIONS = [
    {
        "id": "P126-M1",
        "name": "calendar_window_collapsed_to_compute_ceiling",
        "file": "src/ainerzero/v9/experiments/s2/worker.py",
        "target": "\"max_wall_seconds\": calendar_window,",
        "replacement": "\"max_wall_seconds\": wall_ceiling,",
        "expected_fail_test": "tests/v9/experiments/test_s2_lifecycle.py::test_d_calendar_window_separation_and_expiration",
        "desc": "Experiment-level max_wall_seconds collapsed to 10h compute ceiling; 30h idle gap fails",
    },
    {
        "id": "P126-M2",
        "name": "phase_ceiling_only_current_experiment_id",
        "file": "src/ainerzero/v9/experiments/s2/commands.py",
        "target": "experiment_ids: tuple[str, ...] = worker.LEDGER_EXPERIMENT_IDS,",
        "replacement": "experiment_ids: tuple[str, ...] = (worker.EXPERIMENT_ID,),",
        "expected_fail_test": "tests/v9/experiments/test_s2_lifecycle.py::test_c_phase_budget_ceiling_boundary_and_lineage_accumulation",
        "desc": "Phase budget ceiling only checks current experiment ID, failing cross-lineage accumulation",
    },
    {
        "id": "P126-M3",
        "name": "anti_duplicate_ignores_seed",
        "file": "src/ainerzero/v9/experiments/s2/worker.py",
        "target": "            if cfg.get(\"arm\") == arm:\n                if seed is None or cfg.get(\"seed\") == seed:\n                    return True",
        "replacement": "            if cfg.get(\"arm\") == arm:\n                return True",
        "expected_fail_test": "tests/v9/experiments/test_s2_lifecycle.py::test_b_qualified_approval_admits_train_and_detects_duplicate",
        "desc": "check_cell_already_completed ignores seed, rejecting subsequent runs of different seeds as duplicate",
    },
    {
        "id": "P126-M4",
        "name": "approval_scan_accepts_blockquote",
        "file": "src/ainerzero/v9/experiments/s2/commands.py",
        "target": "        if stripped.startswith(\">\"):\n            skipped[\"blockquote\"].append(number)\n            continue",
        "replacement": "        if stripped.startswith(\">\"):\n            stripped = stripped.lstrip(\">\").strip()",
        "expected_fail_test": "tests/v9/experiments/test_s2_lifecycle.py::test_e_approval_line_in_quote_or_code_refused",
        "desc": "scan_approval_log strips '>' and accepts approval line inside blockquotes",
    },
]


def run_all_mutations():
    temp_dir = Path(tempfile.mkdtemp(prefix="p126_mutations_sandbox_"))
    log_lines = []
    summary = []

    try:
        replica_src = temp_dir / "src"
        replica_tests = temp_dir / "tests"
        shutil.copytree(ROOT / "src", replica_src)
        shutil.copytree(ROOT / "tests", replica_tests)
        shutil.copy2(ROOT / "pyproject.toml", temp_dir / "pyproject.toml")

        # Verify isolation
        check_env = os.environ.copy()
        check_env["PYTHONPATH"] = f"{temp_dir}:{replica_src}"
        check_env["PYTHONDONTWRITEBYTECODE"] = "1"

        res = subprocess.run(
            [sys.executable, "-c", "import ainerzero.v9.experiments.s2.commands as c; print(c.__file__)"],
            cwd=temp_dir,
            env=check_env,
            capture_output=True,
            text=True,
            check=True,
        )
        imported_path = res.stdout.strip()
        assert str(replica_src) in imported_path, f"Isolation failure: imported {imported_path}"
        log_lines.append(f"Isolation verified: {imported_path}")

        # Baseline run
        base_proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/v9/experiments/test_s2_lifecycle.py", "-q"],
            cwd=temp_dir,
            env=check_env,
            capture_output=True,
            text=True,
        )
        assert base_proc.returncode == 0, f"Baseline tests failed in sandbox:\n{base_proc.stdout}"
        log_lines.append(f"Baseline tests: ALL PASSED (exit {base_proc.returncode})")

        for m in MUTATIONS:
            target_file = temp_dir / m["file"]
            original_content = target_file.read_text(encoding="utf-8")
            original_sha = sha256_file(target_file)
            assert m["target"] in original_content, f"Target string not found for {m['id']} in {target_file}"

            # Apply mutation
            mutated_content = original_content.replace(m["target"], m["replacement"], 1)
            target_file.write_text(mutated_content, encoding="utf-8")

            # Run test
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", m["expected_fail_test"], "-q"],
                cwd=temp_dir,
                env=check_env,
                capture_output=True,
                text=True,
            )

            # Restore original immediately
            target_file.write_text(original_content, encoding="utf-8")
            restored_sha = sha256_file(target_file)
            assert restored_sha == original_sha, f"Restoration failure for {m['id']}"

            is_red = (proc.returncode != 0)
            status_str = "RED (Caught)" if is_red else "SURVIVED"
            log_entry = f"[{m['id']}] {status_str}: exit={proc.returncode} test={m['expected_fail_test']}"
            log_lines.append(log_entry)
            log_lines.append(proc.stdout[:400])
            print(log_entry)

            summary.append({
                "id": m["id"],
                "name": m["name"],
                "desc": m["desc"],
                "expected_fail_test": m["expected_fail_test"],
                "returncode": proc.returncode,
                "is_red": is_red,
                "sha_restored": True,
            })

        out_summary = ROOT / "reports/V9-S2-P126/mutation_summary.json"
        out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        out_log = ROOT / "reports/V9-S2-P126/mutation_log.txt"
        out_log.write_text("\n".join(log_lines), encoding="utf-8")

        all_red = all(item["is_red"] for item in summary)
        print(f"All mutations turned red: {all_red}")
        return all_red

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    success = run_all_mutations()
    sys.exit(0 if success else 1)
