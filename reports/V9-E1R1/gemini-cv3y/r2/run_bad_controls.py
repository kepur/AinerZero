#!/usr/bin/env python3
"""Isolated source-mutation bad controls runner for E1 R1 eval runner r2 (ainerzero.V9.P73).

Executes 5 isolated source-mutation bad controls in temporary sandbox copies:
1. Constants local override (CONTACT_TOLERANCE_M = 0.03 instead of importing from metrics) -> RED.
2. F1 mutated to truth vs truth -> RED (assert f1 < 1.0 fails).
3. Energy drift mutated to truth trajectory -> RED (assert mean_drift > 0.5 fails).
4. Empty dataset returns default -> RED (pytest.raises(ValueError) fails).
5. Final bypasses token -> RED (pytest.raises(FinalPartitionSealed) fails).
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
    mut_target: str,
    mut_replacement: str,
    test_target: str,
) -> dict[str, str | bool | int]:
    print(f"\n[MUTATION] {name}: {description}")
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        shutil.copytree(REPO_ROOT / "src", tdp / "src")
        shutil.copytree(REPO_ROOT / "tests", tdp / "tests")
        shutil.copy(REPO_ROOT / "pyproject.toml", tdp / "pyproject.toml")

        eval_runner_file = tdp / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "eval_runner.py"
        code = eval_runner_file.read_text(encoding="utf-8")
        if mut_target not in code:
            raise RuntimeError(f"Target pattern not found in eval_runner.py for mutation: {name}")

        mutated_code = code.replace(mut_target, mut_replacement, 1)
        eval_runner_file.write_text(mutated_code, encoding="utf-8")

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
    print("RUNNING ISOLATED BAD CONTROLS FOR E1 EVAL RUNNER R2 (ainerzero.V9.P73)")
    print("=" * 70)

    # Mutation 0: Local constant redefinition to 0.03
    m0_target = """PREFIX_FRAMES: int = 10  # 待一级冻结: number of prefix observation frames"""
    m0_rep = """PREFIX_FRAMES: int = 10  # 待一级冻结: number of prefix observation frames
CONTACT_TOLERANCE_M: float = 0.03  # bad control local redefinition"""
    r0 = run_mutation_test(
        "bad_control_0_local_threshold_override",
        "Redefine CONTACT_TOLERANCE_M locally to 0.03 instead of importing from metrics.py",
        m0_target,
        m0_rep,
        "tests/test_e1_eval_runner.py::test_constants_imported_directly_from_metrics",
    )

    # Mutation 1: F1 mutated to truth vs truth
    m1_target = """    collision_f1 = compute_collision_f1(
        all_pred_events,
        all_true_events,
        match_tolerance_frames=COLLISION_MATCH_TOLERANCE_FRAMES,
    )"""
    m1_rep = """    collision_f1 = compute_collision_f1(
        all_true_events,
        all_true_events,
        match_tolerance_frames=COLLISION_MATCH_TOLERANCE_FRAMES,
    )"""
    r1 = run_mutation_test(
        "bad_control_1_f1_truth_vs_truth",
        "Collision F1 evaluated as truth vs truth instead of pred vs truth",
        m1_target,
        m1_rep,
        "tests/test_e1_eval_runner.py::test_error_arm_nonzero_position_error_and_missed_collision",
    )

    # Mutation 2: Drift mutated to truth trajectory
    m2_target = """        drift_dict = compute_ballistic_energy_drift(
            pred_positions[name],
            pred_velocities[name],
            in_contact=truth_in_contact,
            mass=1.0,
            min_segment_frames=BALLISTIC_MIN_FRAMES,
            g=GRAVITY_ACCEL,
        )"""
    m2_rep = """        truth_pos_window = np.array([frames[t]["objects"][name]["position"] for t in range(PREFIX_FRAMES, PREFIX_FRAMES + n_future)], dtype=np.float64)
        truth_vel_window = np.array([frames[t]["objects"][name]["linear_velocity"] for t in range(PREFIX_FRAMES, PREFIX_FRAMES + n_future)], dtype=np.float64)
        drift_dict = compute_ballistic_energy_drift(
            truth_pos_window,
            truth_vel_window,
            in_contact=truth_in_contact,
            mass=1.0,
            min_segment_frames=BALLISTIC_MIN_FRAMES,
            g=GRAVITY_ACCEL,
        )"""
    r2 = run_mutation_test(
        "bad_control_2_drift_truth_trajectory",
        "Ballistic energy drift evaluated on truth trajectory instead of arm prediction",
        m2_target,
        m2_rep,
        "tests/test_e1_eval_runner.py::test_energy_drift_evaluated_on_prediction_not_truth",
    )

    # Mutation 3: Empty dataset returns default
    m3_target = """    if not episodes_data:
        raise ValueError(
            f"No valid paired episodes found between student_dir ({student_dir}) and evaluator_dir ({evaluator_dir})"
        )"""
    m3_rep = """    if not episodes_data:
        return {"episodes": [], "summary": {}}"""
    r3 = run_mutation_test(
        "bad_control_3_empty_dataset_default",
        "Empty dataset returns default dict instead of loudly raising ValueError",
        m3_target,
        m3_rep,
        "tests/test_e1_eval_runner.py::test_evaluate_cell_rejects_empty_dataset",
    )

    # Mutation 4: Final bypasses token
    m4_target = """    token = open_sealed_final_once(sealed_dir, expected_digest=expected_digest, reader=reader)"""
    m4_rep = """    class DummyToken:
        dataset_digest = expected_digest
        nonce = "bypassed_nonce"
        sealed_dir = Path(sealed_dir)
    token = DummyToken()"""
    r4 = run_mutation_test(
        "bad_control_4_final_bypasses_token",
        "Final partition evaluation bypasses open_sealed_final_once token",
        m4_target,
        m4_rep,
        "tests/test_e1_eval_runner.py::test_evaluate_final_once_enforces_token_and_rejects_second_read",
    )

    results = [r0, r1, r2, r3, r4]

    print("\n" + "=" * 70)
    print("BAD CONTROLS SUMMARY:")
    all_red = True
    for r in results:
        print(f"[{r['status']}] {r['name']}: {r['description']}")
        if not r["is_red"]:
            all_red = False
    print("=" * 70)

    out_file = REPO_ROOT / "reports" / "V9-E1R1" / "gemini-cv3y" / "r2" / "bad_controls_summary.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Summary written to {out_file}")

    if not all_red:
        print("ERROR: Not all bad controls were RED!")
        sys.exit(1)
    else:
        print("ALL 5 BAD CONTROLS VERIFIED RED.")


if __name__ == "__main__":
    main()
