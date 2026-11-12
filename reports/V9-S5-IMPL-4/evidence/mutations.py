"""Adversarial mutation test harness for S5 metrics (P234).

Tests 11 adversarial mutations in an isolated temporary directory
against tests/v9/experiments/test_s5_metrics.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
VENV_PY = ROOT / ".venv/bin/python"


def main():
    mutations = {
        "M1_ap_optimistic_tie": (
            "    order = np.lexsort((t_flat, -s_flat))",
            "    order = np.lexsort((-t_flat, -s_flat))",
        ),
        "M2_grid_ap_dist_near_leak": (
            '    "near": (0, 4),',
            '    "near": (0, 5),',
        ),
        "M3_disk_recall_strict_gt": (
            "            is_hit = (prob >= threshold)",
            "            is_hit = (prob > threshold)",
        ),
        "M4_logd_rmse_strict_gt_obj": (
            "        mask = valid & (o_arr >= 0.5)",
            "        mask = valid & (o_arr > 0.5)",
        ),
        "M5_logd_rmse_strict_gt_floor": (
            "        mask = valid & (floor >= 0.5)",
            "        mask = valid & (floor > 0.5)",
        ),
        "M6_ordering_equal_pred_passes": (
            "            if math.isnan(z_pred_a) or math.isnan(z_pred_b) or z_pred_a == z_pred_b:\n                pred_closer = None",
            "            if math.isnan(z_pred_a) or math.isnan(z_pred_b) or z_pred_a == z_pred_b:\n                pred_closer = closer",
        ),
        "M7_ordering_partial_requires_both": (
            '                occ_group = "partial" if (occ_a == "partial" or occ_b == "partial") else "full"',
            '                occ_group = "partial" if (occ_a == "partial" and occ_b == "partial") else "full"',
        ),
        "M8_steps_to_target_no_interpolation": (
            "    interp_step = s_prev + ratio * (s_curr - s_prev)",
            "    interp_step = s_curr",
        ),
        "M9_ga_decision_relaxed_target": (
            "    target_ap = float(0.95 * a0_last_median)",
            "    target_ap = float(0.90 * a0_last_median)",
        ),
        "M10_ga_decision_ratio_relaxed": (
            "    passed = bool(median_a4 <= 0.7 * median_a0)",
            "    passed = bool(median_a4 <= 0.8 * median_a0)",
        ),
        "M11_bootstrap_no_replacement": (
            "        boot_idx = rng.choice(n_worlds, size=n_worlds, replace=True)",
            "        boot_idx = rng.choice(n_worlds, size=n_worlds, replace=False)",
        ),
    }

    with tempfile.TemporaryDirectory() as td:
        tpath = Path(td)
        shutil.copytree(ROOT / "src", tpath / "src")
        (tpath / "tests/v9/experiments").mkdir(parents=True)
        shutil.copy(ROOT / "tests/v9/experiments/test_s5_metrics.py", tpath / "tests/v9/experiments/test_s5_metrics.py")
        shutil.copy(ROOT / "tests/conftest.py", tpath / "tests/conftest.py")
        shutil.copy(ROOT / "pyproject.toml", tpath / "pyproject.toml")

        env = dict(os.environ, PYTHONPATH=str(tpath / "src"))
        target_file = tpath / "src/ainerzero/v9/experiments/s5/metrics.py"
        orig_content = target_file.read_text(encoding="utf-8")

        def run_pytest():
            res = subprocess.run(
                [str(VENV_PY), "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf", "tests/v9/experiments/test_s5_metrics.py"],
                cwd=tpath,
                env=env,
                capture_output=True,
                text=True,
            )
            failed_tests = [line.split("::")[-1].split()[0] for line in res.stdout.splitlines() if line.startswith("FAILED")]
            summary_lines = [line for line in res.stdout.splitlines() if "passed" in line or "failed" in line]
            summary = summary_lines[-1] if summary_lines else res.stdout.strip()
            return res.returncode, failed_tests, summary

        print("=== BASELINE TEST ===")
        rc, fails, summary = run_pytest()
        print(f"Baseline return code: {rc}, summary: {summary}")
        assert rc == 0, f"Baseline failed: {fails} {summary}"

        print("\n=== RUNNING 11 ADVERSARIAL MUTATIONS ===")
        all_killed = True
        for name, (orig_str, mut_str) in mutations.items():
            assert orig_content.count(orig_str) == 1, f"{name}: target string not found exactly once ({orig_content.count(orig_str)})"
            mutated_code = orig_content.replace(orig_str, mut_str)
            target_file.write_text(mutated_code, encoding="utf-8")

            rc, fails, summary = run_pytest()
            status = "KILLED" if rc != 0 else "SURVIVED"
            print(f"{name}: {status}")
            print(f"  Failing tests: {fails}")
            print(f"  Summary: {summary}")
            if status != "KILLED":
                all_killed = False

            # Revert to original for next mutation
            target_file.write_text(orig_content, encoding="utf-8")

        print(f"\nAll mutations killed: {all_killed}")


if __name__ == "__main__":
    main()
