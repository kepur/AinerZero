#!/usr/bin/env python3
"""Isolated mutation bad-control runner for E1 Scheme A (ainerzero.V9.P104).

Copies src, tests, pyproject.toml to a fully isolated temporary worktree.
Asserts imported module resolves to the isolated copy.
Executes mutations M1-M5, records failures (red), command exit codes, and output tails.
Restores each file by byte-for-byte fidelity and checks SHA256 integrity.
Outputs summary to reports/V9-E1-A1/mutations.json.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def compute_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest(worktree: Path, test_selector: str) -> tuple[int, str]:
    """Run pytest in isolated worktree with isolated PYTHONPATH."""
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{worktree / 'src'}"
    cmd = [
        str(REPO_ROOT / ".venv" / "bin" / "pytest"),
        test_selector,
        "-q",
        "--tb=short",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(worktree),
        env=env,
        capture_output=True,
        text=True,
    )
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode, output


def main():
    print("=== Starting E1 P104 Mutation Bad Controls in Isolated Worktree ===")

    with tempfile.TemporaryDirectory(prefix="e1_p104_mutations_") as tmp_str:
        worktree = Path(tmp_str)

        # 1. Copy src, tests, pyproject.toml
        shutil.copytree(REPO_ROOT / "src", worktree / "src")
        shutil.copytree(REPO_ROOT / "tests", worktree / "tests")
        shutil.copy2(REPO_ROOT / "pyproject.toml", worktree / "pyproject.toml")

        # 2. Verify import resolution in isolated worktree
        verify_cmd = [
            str(REPO_ROOT / ".venv" / "bin" / "python"),
            "-c",
            "import ainerzero; print(ainerzero.__file__)",
        ]
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{worktree / 'src'}"
        res = subprocess.run(verify_cmd, cwd=str(worktree), env=env, capture_output=True, text=True)
        assert res.returncode == 0, f"Import verification failed: {res.stderr}"
        resolved_path = res.stdout.strip()
        print(f"Isolated worktree import verified: {resolved_path}")
        assert str(worktree / "src") in resolved_path, f"Import did not resolve to isolated worktree: {resolved_path}"

        # Baseline check on isolated worktree before any mutation
        code_base, out_base = run_pytest(worktree, "tests/test_e1_calendar_window.py")
        print(f"Baseline pytest returncode: {code_base}")
        assert code_base == 0, f"Baseline tests failed in isolated worktree:\n{out_base}"

        mutations_results = []

        # ==========================================
        # M1: 实验级 max_wall_seconds 改回 phase_total_wall_ceiling_seconds
        # Target: (a) 和 (e) 必须变红
        # ==========================================
        target_file = worktree / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "worker.py"
        orig_bytes = target_file.read_bytes()
        orig_sha = hashlib.sha256(orig_bytes).hexdigest()

        content = target_file.read_text(encoding="utf-8")
        assert '"max_wall_seconds": calendar_window' in content
        mutated_content = content.replace(
            '"max_wall_seconds": calendar_window',
            '"max_wall_seconds": wall_ceiling',
        )
        target_file.write_text(mutated_content, encoding="utf-8")

        code_m1_a, out_m1_a = run_pytest(worktree, "tests/test_e1_calendar_window.py::test_case_a_gap_does_not_reject")
        code_m1_e, out_m1_e = run_pytest(worktree, "tests/test_e1_calendar_window.py::test_case_e_full_schedule_rehearsal_with_7_5h_gap")

        # Restore
        target_file.write_bytes(orig_bytes)
        assert compute_sha256(target_file) == orig_sha, "M1 restoration SHA mismatch"

        m1_success = (code_m1_a != 0) and (code_m1_e != 0)
        print(f"M1 result: (a) exit={code_m1_a}, (e) exit={code_m1_e} -> {'RED (PASS)' if m1_success else 'FAILED'}")
        mutations_results.append({
            "mutation_id": "M1",
            "description": "实验级 max_wall_seconds 改回 phase_total_wall_ceiling_seconds",
            "target_file": "src/ainerzero/v9/experiments/e1/worker.py",
            "expected_red": ["(a)", "(e)"],
            "case_a_exit_code": code_m1_a,
            "case_a_tail": "\n".join(out_m1_a.splitlines()[-8:]),
            "case_e_exit_code": code_m1_e,
            "case_e_tail": "\n".join(out_m1_e.splitlines()[-8:]),
            "restored_sha_matched": True,
            "passed_bad_control": m1_success,
        })

        # ==========================================
        # M2: _check_phase_budget_ceiling 只查 spec.EXPERIMENT_ID
        # Target: (b) 必须变红
        # ==========================================
        target_file = worktree / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "commands.py"
        orig_bytes = target_file.read_bytes()
        orig_sha = hashlib.sha256(orig_bytes).hexdigest()

        content = target_file.read_text(encoding="utf-8")
        assert "f\"SELECT active_seconds, config_json FROM runs WHERE experiment_id IN ({placeholders})\"" in content
        old_pattern = """            placeholders = ", ".join("?" for _ in spec.LEDGER_EXPERIMENT_IDS)
            cursor = store._conn.execute(
                f"SELECT active_seconds, config_json FROM runs WHERE experiment_id IN ({placeholders})",
                spec.LEDGER_EXPERIMENT_IDS,
            )"""
        m2_pattern = """            cursor = store._conn.execute(
                "SELECT active_seconds, config_json FROM runs WHERE experiment_id = ?",
                (spec.EXPERIMENT_ID,),
            )"""
        assert old_pattern in content
        mutated_content = content.replace(old_pattern, m2_pattern)
        target_file.write_text(mutated_content, encoding="utf-8")

        code_m2, out_m2 = run_pytest(worktree, "tests/test_e1_calendar_window.py::test_case_b_combined_phase_ceiling")

        # Restore
        target_file.write_bytes(orig_bytes)
        assert compute_sha256(target_file) == orig_sha, "M2 restoration SHA mismatch"

        m2_success = (code_m2 != 0)
        print(f"M2 result: (b) exit={code_m2} -> {'RED (PASS)' if m2_success else 'FAILED'}")
        mutations_results.append({
            "mutation_id": "M2",
            "description": "_check_phase_budget_ceiling 只查 spec.EXPERIMENT_ID",
            "target_file": "src/ainerzero/v9/experiments/e1/commands.py",
            "expected_red": ["(b)"],
            "case_b_exit_code": code_m2,
            "case_b_tail": "\n".join(out_m2.splitlines()[-8:]),
            "restored_sha_matched": True,
            "passed_bad_control": m2_success,
        })

        # ==========================================
        # M3: check_cell_already_completed 只查当前 id
        # Target: (c) 必须变红
        # ==========================================
        target_file = worktree / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "worker.py"
        orig_bytes = target_file.read_bytes()
        orig_sha = hashlib.sha256(orig_bytes).hexdigest()

        content = target_file.read_text(encoding="utf-8")
        old_pattern_m3 = """        placeholders = ", ".join("?" for _ in spec.LEDGER_EXPERIMENT_IDS)
        cursor = store._conn.execute(
            f"SELECT config_json, state FROM runs WHERE experiment_id IN ({placeholders})",
            spec.LEDGER_EXPERIMENT_IDS,
        )"""
        m3_pattern = """        cursor = store._conn.execute(
            "SELECT config_json, state FROM runs WHERE experiment_id = ?",
            (EXPERIMENT_ID,),
        )"""
        assert old_pattern_m3 in content
        mutated_content = content.replace(old_pattern_m3, m3_pattern)
        target_file.write_text(mutated_content, encoding="utf-8")

        code_m3, out_m3 = run_pytest(worktree, "tests/test_e1_calendar_window.py::test_case_c_cross_lineage_anti_duplicate")

        # Restore
        target_file.write_bytes(orig_bytes)
        assert compute_sha256(target_file) == orig_sha, "M3 restoration SHA mismatch"

        m3_success = (code_m3 != 0)
        print(f"M3 result: (c) exit={code_m3} -> {'RED (PASS)' if m3_success else 'FAILED'}")
        mutations_results.append({
            "mutation_id": "M3",
            "description": "check_cell_already_completed 只查当前 id",
            "target_file": "src/ainerzero/v9/experiments/e1/worker.py",
            "expected_red": ["(c)"],
            "case_c_exit_code": code_m3,
            "case_c_tail": "\n".join(out_m3.splitlines()[-8:]),
            "restored_sha_matched": True,
            "passed_bad_control": m3_success,
        })

        # ==========================================
        # M4: 删掉 validate 里的谱系检查
        # Target: (d) 必须变红
        # ==========================================
        target_file = worktree / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "prereg.py"
        orig_bytes = target_file.read_bytes()
        orig_sha = hashlib.sha256(orig_bytes).hexdigest()

        content = target_file.read_text(encoding="utf-8")
        lineage_block = """    # Lineage validation
    ledger_ids = document.get("ledger_experiment_ids")
    if not isinstance(ledger_ids, (list, tuple)):
        raise SpecValidationError("Missing or invalid ledger_experiment_ids list")
    if tuple(ledger_ids) != spec.LEDGER_EXPERIMENT_IDS:
        raise SpecValidationError(
            f"ledger_experiment_ids mismatch: expected {spec.LEDGER_EXPERIMENT_IDS}, got {tuple(ledger_ids)}"
        )
    if not ledger_ids or ledger_ids[-1] != document.get("experiment_id"):
        raise SpecValidationError(
            f"Last element of ledger_experiment_ids ({ledger_ids[-1] if ledger_ids else None}) "
            f"must match experiment_id ({document.get('experiment_id')})"
        )"""
        assert lineage_block in content
        mutated_content = content.replace(lineage_block, "    # Lineage validation removed for M4")
        target_file.write_text(mutated_content, encoding="utf-8")

        code_m4, out_m4 = run_pytest(worktree, "tests/test_e1_calendar_window.py::test_case_d_prereg_validation_and_subprocess")

        # Restore
        target_file.write_bytes(orig_bytes)
        assert compute_sha256(target_file) == orig_sha, "M4 restoration SHA mismatch"

        m4_success = (code_m4 != 0)
        print(f"M4 result: (d) exit={code_m4} -> {'RED (PASS)' if m4_success else 'FAILED'}")
        mutations_results.append({
            "mutation_id": "M4",
            "description": "删掉 validate 里的谱系检查",
            "target_file": "src/ainerzero/v9/experiments/e1/prereg.py",
            "expected_red": ["(d)"],
            "case_d_exit_code": code_m4,
            "case_d_tail": "\n".join(out_m4.splitlines()[-8:]),
            "restored_sha_matched": True,
            "passed_bad_control": m4_success,
        })

        # ==========================================
        # M5: LEDGER_EXPERIMENT_IDS 去掉 r0
        # Target: (b) 或 (c) 必须变红
        # ==========================================
        target_file = worktree / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "spec.py"
        orig_bytes = target_file.read_bytes()
        orig_sha = hashlib.sha256(orig_bytes).hexdigest()

        content = target_file.read_text(encoding="utf-8")
        old_ids = """LEDGER_EXPERIMENT_IDS: tuple[str, ...] = (
    "e1-phase2-20261029-r0",
    "e1-phase2-20261029-r1",
)"""
        new_ids = """LEDGER_EXPERIMENT_IDS: tuple[str, ...] = (
    "e1-phase2-20261029-r1",
)"""
        assert old_ids in content
        mutated_content = content.replace(old_ids, new_ids)
        target_file.write_text(mutated_content, encoding="utf-8")

        code_m5_b, out_m5_b = run_pytest(worktree, "tests/test_e1_calendar_window.py::test_case_b_combined_phase_ceiling")
        code_m5_c, out_m5_c = run_pytest(worktree, "tests/test_e1_calendar_window.py::test_case_c_cross_lineage_anti_duplicate")

        # Restore
        target_file.write_bytes(orig_bytes)
        assert compute_sha256(target_file) == orig_sha, "M5 restoration SHA mismatch"

        m5_success = (code_m5_b != 0) or (code_m5_c != 0)
        print(f"M5 result: (b) exit={code_m5_b}, (c) exit={code_m5_c} -> {'RED (PASS)' if m5_success else 'FAILED'}")
        mutations_results.append({
            "mutation_id": "M5",
            "description": "LEDGER_EXPERIMENT_IDS 去掉 r0",
            "target_file": "src/ainerzero/v9/experiments/e1/spec.py",
            "expected_red": ["(b)", "(c)"],
            "case_b_exit_code": code_m5_b,
            "case_b_tail": "\n".join(out_m5_b.splitlines()[-8:]),
            "case_c_exit_code": code_m5_c,
            "case_c_tail": "\n".join(out_m5_c.splitlines()[-8:]),
            "restored_sha_matched": True,
            "passed_bad_control": m5_success,
        })

        # Save to reports/V9-E1-A1/mutations.json
        out_json_path = REPO_ROOT / "reports" / "V9-E1-A1" / "mutations.json"
        out_json_path.write_text(json.dumps(mutations_results, indent=2), encoding="utf-8")
        print(f"All 5 mutations executed and recorded to {out_json_path}")

        # Assert all mutations turned red
        assert all(m["passed_bad_control"] for m in mutations_results), "One or more mutations failed to turn red!"


if __name__ == "__main__":
    main()
