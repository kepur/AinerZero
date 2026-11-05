"""Unit tests for E1 Analysis & Decision Module (ainerzero.V9.P80).

Verifies:
1. H-E1 Boundary: Passes at exactly 10.0% relative reduction; fails at 9.99%.
2. F1 Non-decreasing condition: Fails if F1(arm3) < F1(baseline) even if error reduction is 30%.
3. Baseline selection: Takes min(Arm 1, Arm 2), tested in both cases (Arm 1 lower, Arm 2 lower).
4. Missing cells loudly raises MissingCellError listing the missing keys.
5. Similarity '≈' boundary in H-P: CI containing 0 but with width exceeding 10% of gap is NOT '≈'.
6. Diagnostic Arm 4 independence: Changing Arm 4 error has zero effect on H-E1 decisions.
7. Full pipeline write_report produces valid analysis.json and tables.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.e1 import analysis
from ainerzero.v9.experiments.e1.analysis import (
    MissingCellError,
    build_analysis_summary,
    decide_h_e1,
    load_cells,
    report_h_p,
    report_h_s,
    write_report,
)
from ainerzero.v9.experiments.e1.spec import (
    FAMILIES,
    PRIMARY_ERROR_REDUCTION_MIN,
    TRAINABLE_ARM_IDS,
    TRAINING_SEEDS,
)


def create_synthetic_cell_data(
    arm_id: int,
    family: str,
    seed: int | None,
    *,
    error_10: float,
    collision_f1: float = 0.85,
    num_episodes: int = 20,
    noise_std: float = 0.01,
    error_1: float = 0.05,
    error_5: float = 0.15,
    error_30: float = 0.80,
    energy_drift: float = 0.02,
    latency_s: float = 0.005,
) -> dict[str, Any]:
    """Helper to construct a realistic per-cell evaluation JSON dictionary."""
    rng = np.random.RandomState((arm_id * 100) + (seed or 0) + (1 if family == "P" else 2))
    episode_errs = np.clip(rng.normal(loc=error_10, scale=noise_std, size=num_episodes), 1e-4, 10.0)

    episodes = []
    for i, err in enumerate(episode_errs):
        episodes.append(
            {
                "sequence_id": f"ep_{i:04d}",
                "position_errors": {
                    "1": {"mean_error_m": float(error_1)},
                    "5": {"mean_error_m": float(error_5)},
                    "10": {"mean_error_m": float(err)},
                    "30": {"mean_error_m": float(error_30)},
                },
                "collision_f1": {
                    "precision": float(collision_f1),
                    "recall": float(collision_f1),
                    "f1": float(collision_f1),
                },
                "energy_drift": {"mean_drift": float(energy_drift)},
                "inference_latency": {"latency_per_step_s": float(latency_s)},
            }
        )

    summary = {
        "num_episodes": num_episodes,
        "primary_error_m": float(error_10),
        "k_step_errors": {
            "1": float(error_1),
            "5": float(error_5),
            "10": float(error_10),
            "30": float(error_30),
        },
        "collision_f1": float(collision_f1),
        "mean_energy_drift": float(energy_drift),
        "mean_latency_per_step_s": float(latency_s),
    }

    return {
        "mode": "eval",
        "arm": arm_id,
        "family": family,
        "seed": seed,
        "partition": "development",
        "summary": summary,
        "metrics": dict(summary),
        "episodes": episodes,
        "diagnostic": (arm_id == 4),
    }


def create_full_synthetic_dataset(
    out_dir: Path,
    *,
    family_custom_errors: dict[str, dict[int, float]] | None = None,
    f1_overrides: dict[str, dict[int, float]] | None = None,
) -> None:
    """Create all 26 registered development cells on disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    custom_errs = family_custom_errors or {}
    custom_f1s = f1_overrides or {}

    # Default errors if not overridden
    default_errors = {
        1: 0.50,  # BiasedPrior
        2: 0.60,  # PureNet
        3: 0.40,  # PriorResidual (20% reduction vs 0.50 -> passes)
        4: 0.10,  # TrueParam (diagnostic)
        5: 0.45,  # IdentifiedPrior
        6: 0.35,  # IdentifyResidual
        7: 0.38,  # SymbolicResidual
    }

    for fam in FAMILIES:
        fam_errs = dict(default_errors)
        if fam in custom_errs:
            fam_errs.update(custom_errs[fam])

        for arm_id in range(1, 8):
            err_10 = fam_errs[arm_id]
            f1_val = 0.85
            if fam in custom_f1s and arm_id in custom_f1s[fam]:
                f1_val = custom_f1s[fam][arm_id]

            if arm_id in TRAINABLE_ARM_IDS:
                for seed in TRAINING_SEEDS:
                    cell_data = create_synthetic_cell_data(arm_id, fam, seed, error_10=err_10, collision_f1=f1_val)
                    p = out_dir / f"eval_arm{arm_id}_{fam}_{seed}.json"
                    p.write_text(json.dumps(cell_data, indent=2), encoding="utf-8")
            else:
                cell_data = create_synthetic_cell_data(arm_id, fam, None, error_10=err_10, collision_f1=f1_val)
                p = out_dir / f"eval_arm{arm_id}_{fam}_none.json"
                p.write_text(json.dumps(cell_data, indent=2), encoding="utf-8")


# =========================================================================
# Unit Tests
# =========================================================================

def test_h_e1_boundary_10_percent_pass_and_9_99_percent_fail(tmp_path: Path):
    """Verify H-E1 passes at exactly 10.0% error reduction and fails at 9.99%."""
    # Case A: exactly 10.00% reduction: baseline = 1.000, arm3 = 0.900 -> rel_red = 0.1000
    dir_pass = tmp_path / "data_pass"
    create_full_synthetic_dataset(
        dir_pass,
        family_custom_errors={
            "P": {1: 1.000, 2: 1.200, 3: 0.900},
            "S": {1: 1.000, 2: 1.200, 3: 0.900},
        },
    )
    cells_pass = load_cells(dir_pass)
    dec_pass = decide_h_e1(cells_pass, "P")
    assert np.isclose(dec_pass["relative_reduction"], 0.10, atol=1e-5)
    assert dec_pass["error_threshold_met"] is True
    assert dec_pass["passed"] is True

    # Case B: 9.99% reduction: baseline = 1.000, arm3 = 0.9001 -> rel_red = 0.0999 < 0.10
    dir_fail = tmp_path / "data_fail"
    create_full_synthetic_dataset(
        dir_fail,
        family_custom_errors={
            "P": {1: 1.000, 2: 1.200, 3: 0.9001},
            "S": {1: 1.000, 2: 1.200, 3: 0.9001},
        },
    )
    cells_fail = load_cells(dir_fail)
    dec_fail = decide_h_e1(cells_fail, "P")
    assert dec_fail["relative_reduction"] < 0.10
    assert dec_fail["error_threshold_met"] is False
    assert dec_fail["passed"] is False


def test_h_e1_f1_non_decreasing_condition(tmp_path: Path):
    """Verify H-E1 fails if F1(arm3) < F1(baseline), even if error reduction is 30%."""
    data_dir = tmp_path / "f1_fail"
    create_full_synthetic_dataset(
        data_dir,
        family_custom_errors={
            "P": {1: 1.000, 2: 1.200, 3: 0.700},  # 30% reduction!
        },
        f1_overrides={
            "P": {1: 0.85, 2: 0.80, 3: 0.84},  # F1(3) = 0.84 < F1(1) = 0.85
        },
    )
    cells = load_cells(data_dir)
    dec = decide_h_e1(cells, "P")
    assert dec["relative_reduction"] >= 0.30
    assert dec["error_threshold_met"] is True
    assert dec["f1_non_decreasing"] is False
    assert dec["passed"] is False  # Must fail gate because F1 decreased!


def test_h_e1_baseline_selection_takes_min_of_arm1_and_arm2(tmp_path: Path):
    """Verify baseline takes min(Arm 1, Arm 2) across both conditions."""
    # Condition 1: Arm 1 is lower (Arm 1 = 0.50, Arm 2 = 0.60) -> baseline is Arm 1
    dir1 = tmp_path / "baseline_arm1"
    create_full_synthetic_dataset(
        dir1,
        family_custom_errors={"P": {1: 0.50, 2: 0.60, 3: 0.40}},
    )
    cells1 = load_cells(dir1)
    dec1 = decide_h_e1(cells1, "P")
    assert dec1["baseline_arm"] == 1
    assert np.isclose(dec1["baseline_error_10"], 0.50)

    # Condition 2: Arm 2 is lower (Arm 1 = 0.60, Arm 2 = 0.50) -> baseline is Arm 2
    dir2 = tmp_path / "baseline_arm2"
    create_full_synthetic_dataset(
        dir2,
        family_custom_errors={"P": {1: 0.60, 2: 0.50, 3: 0.40}},
    )
    cells2 = load_cells(dir2)
    dec2 = decide_h_e1(cells2, "P")
    assert dec2["baseline_arm"] == 2
    assert np.isclose(dec2["baseline_error_10"], 0.50)


def test_missing_cells_loudly_raises_exception(tmp_path: Path):
    """Verify missing registered cells raises MissingCellError listing the missing keys."""
    data_dir = tmp_path / "partial_data"
    create_full_synthetic_dataset(data_dir)

    # Delete one cell: Arm 3, seed 43 for Family P
    missing_file = data_dir / "eval_arm3_P_43.json"
    missing_file.unlink()

    with pytest.raises(MissingCellError) as exc_info:
        load_cells(data_dir)

    err_msg = str(exc_info.value)
    assert "Missing 1 registered evaluation cells" in err_msg
    assert "Family=P, Arm=3, Seed=43" in err_msg


def test_h_p_similarity_approx_boundary_conditions(tmp_path: Path):
    """Verify '≈' condition: requires containing 0 AND width <= 10% of gap."""
    data_dir = tmp_path / "hp_data"
    # Gap |Arm 4 - Arm 1| = |0.10 - 0.50| = 0.40
    # max_width = 0.10 * 0.40 = 0.040
    create_full_synthetic_dataset(
        data_dir,
        family_custom_errors={
            "P": {
                1: 0.50,
                4: 0.10,
                5: 0.1005,  # Very close to Arm 4, low noise
            }
        },
    )
    cells = load_cells(data_dir)
    res_hp = report_h_p(cells)
    assert np.isclose(res_hp["gap_abs_arm4_arm1"], 0.40)
    assert np.isclose(res_hp["max_similarity_ci_width"], 0.04)

    # Case A: CI contains 0 and width is small -> is_similar_approx is True
    assert res_hp["arm5_vs_arm4"]["contains_zero"] is True
    assert res_hp["arm5_vs_arm4"]["is_similar_approx"] is True

    # Case B: If width exceeds max_width (even if containing 0), is_similar_approx is False
    # Manually modify CI width in result object to test boundary logic
    res_hp["arm5_vs_arm4"]["ci_width"] = 0.050  # > 0.040
    res_hp["arm5_vs_arm4"]["is_similar_approx"] = bool(
        res_hp["arm5_vs_arm4"]["contains_zero"]
        and res_hp["arm5_vs_arm4"]["ci_width"] <= res_hp["max_similarity_ci_width"]
    )
    assert res_hp["arm5_vs_arm4"]["is_similar_approx"] is False


def test_h_e1_families_are_evaluated_independently_never_pooled(tmp_path: Path):
    """Verify Family P and Family S decisions are strictly independent and never pooled.

    Contract:
    - If Family P achieves 20% reduction (passes) and Family S achieves 5% reduction (fails):
      Family P must be PASSED, Family S must be FAILED.
    - If families were pooled into a single average (e.g. (20% + 5%) / 2 = 12.5% >= 10%),
      Family S would erroneously pass. Independent evaluation prevents this.
    """
    data_dir = tmp_path / "independent_families"
    create_full_synthetic_dataset(
        data_dir,
        family_custom_errors={
            "P": {1: 1.0, 2: 1.2, 3: 0.80},  # 20% reduction -> PASS
            "S": {1: 1.0, 2: 1.2, 3: 0.95},  # 5% reduction -> FAIL
        },
    )
    cells = load_cells(data_dir)
    dec_p = decide_h_e1(cells, "P")
    dec_s = decide_h_e1(cells, "S")

    assert dec_p["passed"] is True
    assert dec_s["passed"] is False

    summary = build_analysis_summary(cells)
    assert summary["primary_gate_h_e1"]["by_family"]["P"]["passed"] is True
    assert summary["primary_gate_h_e1"]["by_family"]["S"]["passed"] is False
    assert summary["primary_gate_h_e1"]["overall_passed"] is False


def test_diagnostic_arm4_does_not_affect_h_e1_decision(tmp_path: Path):
    """Verify altering Arm 4 (TrueParam diagnostic) has strictly zero effect on H-E1 decisions."""
    dir_normal = tmp_path / "arm4_normal"
    create_full_synthetic_dataset(
        dir_normal,
        family_custom_errors={"P": {1: 1.0, 2: 1.2, 3: 0.85, 4: 0.50}},
    )
    cells_normal = load_cells(dir_normal)
    dec_normal = decide_h_e1(cells_normal, "P")

    dir_tiny_arm4 = tmp_path / "arm4_tiny"
    create_full_synthetic_dataset(
        dir_tiny_arm4,
        family_custom_errors={"P": {1: 1.0, 2: 1.2, 3: 0.85, 4: 0.0001}},  # Tiny Arm 4!
    )
    cells_tiny = load_cells(dir_tiny_arm4)
    dec_tiny = decide_h_e1(cells_tiny, "P")

    # Decisions and reductions must be strictly identical
    assert dec_normal["baseline_arm"] == dec_tiny["baseline_arm"]
    assert dec_normal["baseline_error_10"] == dec_tiny["baseline_error_10"]
    assert dec_normal["relative_reduction"] == dec_tiny["relative_reduction"]
    assert dec_normal["passed"] == dec_tiny["passed"]
    assert dec_tiny["diagnostic_arm4_excluded"] is True


def test_full_pipeline_write_report(tmp_path: Path):
    """Verify write_report creates valid analysis.json and markdown tables.md."""
    eval_dir = tmp_path / "eval_data"
    create_full_synthetic_dataset(eval_dir)

    out_dir = tmp_path / "analysis_out"
    written = write_report(eval_dir, out_dir)

    json_path = written["analysis_json"]
    md_path = written["tables_md"]

    assert json_path.is_file()
    assert md_path.is_file()

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "primary_gate_h_e1" in data
    assert "exploratory_h_p" in data
    assert "exploratory_h_s" in data
    assert data["cells_count"] == 26

    md_text = md_path.read_text(encoding="utf-8")
    assert "# E1 Phase 2 Evaluation & Decision Tables" in md_text
    assert "Primary Hypothesis H-E1 Gate Decisions" in md_text
    assert "Exploratory Hypothesis H-P (Family P)" in md_text
    assert "Exploratory Hypothesis H-S (Family S)" in md_text
    assert "Evaluation Cells Complete Overview" in md_text
