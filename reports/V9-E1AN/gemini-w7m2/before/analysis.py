"""E1 Phase 2 Analysis and Decision Module (ainerzero.V9.P80).

Zero-run design: Strictly operates on evaluation output JSON files from eval_runner.
Does not load raw dataset episodes, does not invoke model training, and does not require GPU.

Primary Gate:
- H-E1 (the only gate): Evaluated per family independently (P and S, no pooling).
  - Baseline arm = best of Arm ① (BiasedPrior) and Arm ② (PureNet) on 10-step position error
    (macro-averaged across 3 training seeds for Arm ②; single-run value for Arm ①).
  - Pass condition:
        (error_baseline - error_arm3) / error_baseline >= 0.10  AND  F1(arm3) >= F1(baseline)
  - Both families must pass independently for overall success.

Confidence Intervals:
- Episode-paired bootstrap confidence intervals (10,000 resamples, frozen RNG seed 42)
  via metrics.paired_bootstrap_ci.
- Seed dimension is averaged per resample before taking the macro-average across seeds.

Exploratory Hypotheses (Reported only, no gate):
- H-P (Family P only):
  - Arm ⑤ (IdentifiedPrior) vs Arm ④ (TrueParam diagnostic).
  - Arm ⑤ vs Arm ③ (PriorResidual).
  - Similarity "≈": CI contains 0 and CI width <= 0.10 * |error_arm4 - error_arm1|.
- H-S (Family S only):
  - Arm ⑥ (IdentifyResidual) vs Arm ⑤.
  - Arm ⑦ (SymbolicResidual) vs Arm ⑤.
- Arm ④ (TrueParam) is strictly marked diagnostic upper-bound and excluded from all gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from . import metrics, spec
from .spec import (
    ARM_SPECS,
    ARMS_BY_ID,
    DIAGNOSTIC_ARM_IDS,
    FAMILIES,
    H_P_SIMILARITY_MAX_WIDTH_RATIO,
    NON_TRAINABLE_ARM_IDS,
    PRIMARY_ERROR_REDUCTION_MIN,
    PRIMARY_GATE_NAME,
    TRAINABLE_ARM_IDS,
    TRAINING_SEEDS,
)


class MissingCellError(KeyError):
    """Raised when one or more registered evaluation cells are missing."""


def get_expected_cells(
    partition: str = "development",
    families: Sequence[str] = FAMILIES,
) -> list[tuple[str, int, int | None]]:
    """Return list of expected cell tuples (family, arm_id, seed) for a partition."""
    expected: list[tuple[str, int, int | None]] = []
    for fam in families:
        for arm_id in range(1, 8):
            if arm_id in TRAINABLE_ARM_IDS:
                for seed in TRAINING_SEEDS:
                    expected.append((fam, arm_id, seed))
            else:
                expected.append((fam, arm_id, None))
    return expected


def _extract_10_step_error_from_summary(summary: Mapping[str, Any]) -> float:
    """Extract 10-step mean position error from summary dict."""
    k_step_errors = summary.get("k_step_errors", {})
    if "10" in k_step_errors:
        return float(k_step_errors["10"])
    if 10 in k_step_errors:
        return float(k_step_errors[10])
    if "primary_error_m" in summary and summary["primary_error_m"] is not None:
        return float(summary["primary_error_m"])
    if "position_error_10_step" in summary:
        return float(summary["position_error_10_step"])
    raise KeyError("Could not locate 10-step position error in summary")


def _extract_episode_10_step_errors(episodes: Sequence[Mapping[str, Any]]) -> np.ndarray:
    """Extract array of 10-step position errors per episode from cell episodes list."""
    errors: list[float] = []
    for ep in episodes:
        pos_errs = ep.get("position_errors", {})
        err_10 = pos_errs.get("10")
        if err_10 is None:
            err_10 = pos_errs.get(10)

        if isinstance(err_10, Mapping):
            val = err_10.get("mean_error_m", err_10.get("mean", 0.0))
        elif err_10 is not None:
            val = float(err_10)
        else:
            val = float(ep.get("primary_error_m", 0.0))
        errors.append(float(val))
    return np.asarray(errors, dtype=np.float64)


def load_cells(
    eval_dir: Path | str,
    partition: str = "development",
    *,
    allow_partial: bool = False,
) -> dict[tuple[str, int, int | None], dict[str, Any]]:
    """Load per-cell evaluation JSON reports from eval_dir.

    Parameters:
        eval_dir: Directory containing per-cell JSON evaluation reports.
        partition: Partition name ('development' or 'final').
        allow_partial: If True, do not raise MissingCellError if cells are missing.

    Returns:
        dict mapping (family, arm_id, seed) to cell evaluation dict.

    Raises:
        FileNotFoundError: If eval_dir does not exist.
        MissingCellError: If any registered cells are missing and allow_partial=False.
    """
    path = Path(eval_dir)
    if not path.is_dir():
        raise FileNotFoundError(f"Evaluation directory does not exist: {eval_dir}")

    # Discover all JSON files in eval_dir (and subdirectories)
    json_files = sorted(list(path.glob("*.json")))
    if not json_files:
        json_files = sorted(list(path.rglob("*.json")))

    loaded_cells: dict[tuple[str, int, int | None], dict[str, Any]] = {}

    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not isinstance(data, dict):
            continue

        arm = data.get("arm")
        family = data.get("family")
        seed = data.get("seed")
        part = data.get("partition", partition)

        # Normalize seed
        if seed == "none" or seed == "" or seed is None:
            norm_seed = None
        else:
            try:
                norm_seed = int(seed)
            except (ValueError, TypeError):
                norm_seed = None

        if arm is not None and family is not None:
            try:
                norm_arm = int(arm)
            except (ValueError, TypeError):
                continue
            norm_fam = str(family).upper()
            cell_key = (norm_fam, norm_arm, norm_seed)
            loaded_cells[cell_key] = data

    expected = get_expected_cells(partition=partition)
    missing = [c for c in expected if c not in loaded_cells]

    if missing and not allow_partial:
        missing_desc = [f"Family={c[0]}, Arm={c[1]}, Seed={c[2]}" for c in missing]
        raise MissingCellError(
            f"Missing {len(missing)} registered evaluation cells in {eval_dir} "
            f"for partition '{partition}':\n  " + "\n  ".join(missing_desc)
        )

    return loaded_cells


def decide_h_e1(
    cells: Mapping[tuple[str, int, int | None], dict[str, Any]],
    family: str,
) -> dict[str, Any]:
    """Evaluate primary hypothesis H-E1 gate for a specific family.

    Contract (PREREG_DRAFT §1 & §5, 一级裁定):
    1. Evaluated per family independently (no pooling).
    2. Baseline = best of Arm ① and Arm ② on 10-step position error
       (Arm ②: macro-average of 3 seeds; Arm ①: single run).
    3. Condition:
           relative_reduction = (error_baseline - error_arm3) / error_baseline >= 0.10
           AND collision_f1(arm3) >= collision_f1(baseline)
    4. Bootstrap CI computed on paired episodes via metrics.paired_bootstrap_ci.
    5. Arm ④ is strictly excluded from competition and marked diagnostic.
    """
    fam = str(family).upper()
    if fam not in FAMILIES:
        raise ValueError(f"Unknown family: {family}. Must be one of {FAMILIES}")

    # 1. Arm ① (BiasedPrior)
    key_1 = (fam, 1, None)
    if key_1 not in cells:
        raise MissingCellError(f"Missing Arm 1 cell for family {fam}")
    cell_1 = cells[key_1]
    err_1 = _extract_10_step_error_from_summary(cell_1.get("summary", cell_1.get("metrics", {})))
    f1_1 = float(cell_1.get("summary", cell_1.get("metrics", {})).get("collision_f1", 0.0))
    ep_errs_1 = _extract_episode_10_step_errors(cell_1.get("episodes", []))

    # 2. Arm ② (PureNet)
    cells_2 = []
    for s in TRAINING_SEEDS:
        k = (fam, 2, s)
        if k not in cells:
            raise MissingCellError(f"Missing Arm 2 seed {s} for family {fam}")
        cells_2.append(cells[k])

    errs_2 = [_extract_10_step_error_from_summary(c.get("summary", c.get("metrics", {}))) for c in cells_2]
    f1s_2 = [float(c.get("summary", c.get("metrics", {})).get("collision_f1", 0.0)) for c in cells_2]
    err_2 = float(np.mean(errs_2))
    f1_2 = float(np.mean(f1s_2))
    ep_errs_2 = np.array([_extract_episode_10_step_errors(c.get("episodes", [])) for c in cells_2])

    # 3. Determine Baseline Arm (best of ① and ②)
    if err_1 <= err_2:
        baseline_arm = 1
        err_baseline = err_1
        f1_baseline = f1_1
        # Replicate 1D episode array across 3 seeds for paired bootstrap compatibility
        n_ep = len(ep_errs_1)
        if n_ep > 0:
            ep_baseline = np.repeat(ep_errs_1[None, :], len(TRAINING_SEEDS), axis=0)
        else:
            ep_baseline = np.zeros((len(TRAINING_SEEDS), 0))
    else:
        baseline_arm = 2
        err_baseline = err_2
        f1_baseline = f1_2
        ep_baseline = ep_errs_2

    # 4. Arm ③ (PriorResidual)
    cells_3 = []
    for s in TRAINING_SEEDS:
        k = (fam, 3, s)
        if k not in cells:
            raise MissingCellError(f"Missing Arm 3 seed {s} for family {fam}")
        cells_3.append(cells[k])

    errs_3 = [_extract_10_step_error_from_summary(c.get("summary", c.get("metrics", {}))) for c in cells_3]
    f1s_3 = [float(c.get("summary", c.get("metrics", {})).get("collision_f1", 0.0)) for c in cells_3]
    err_3 = float(np.mean(errs_3))
    f1_3 = float(np.mean(f1s_3))
    ep_errs_3 = np.array([_extract_episode_10_step_errors(c.get("episodes", [])) for c in cells_3])

    # 5. Gate Conditions
    # relative_reduction = (err_baseline - err_3) / err_baseline
    rel_reduction = (err_baseline - err_3) / err_baseline if err_baseline > 1e-12 else 0.0
    # Use slight numerical tolerance 1e-9 for exact 10% floating-point comparisons
    error_passed = bool(rel_reduction >= PRIMARY_ERROR_REDUCTION_MIN - 1e-9)
    f1_passed = bool(f1_3 >= f1_baseline - 1e-9)
    gate_passed = bool(error_passed and f1_passed)

    # 6. Paired Bootstrap CI (relative difference: (err_3 - err_baseline) / err_baseline)
    bootstrap_info: dict[str, Any] = {}
    if ep_baseline.shape[1] >= 2 and ep_errs_3.shape[1] >= 2:
        ci_res = metrics.paired_bootstrap_ci(ep_baseline, ep_errs_3, mode="relative")
        bootstrap_info = {
            "point_estimate_relative": float(ci_res["point_estimate"]),
            "ci_lower_relative": float(ci_res["ci_lower"]),
            "ci_upper_relative": float(ci_res["ci_upper"]),
            "ci_width": float(ci_res["ci_width"]),
            "confidence_level": float(ci_res["confidence_level"]),
        }

    return {
        "gate": PRIMARY_GATE_NAME,
        "family": fam,
        "baseline_arm": baseline_arm,
        "arm1_error_10": err_1,
        "arm2_error_10": err_2,
        "baseline_error_10": err_baseline,
        "arm3_error_10": err_3,
        "relative_reduction": float(rel_reduction),
        "required_reduction_min": PRIMARY_ERROR_REDUCTION_MIN,
        "error_threshold_met": error_passed,
        "baseline_f1": f1_baseline,
        "arm3_f1": f1_3,
        "f1_non_decreasing": f1_passed,
        "passed": gate_passed,
        "paired_bootstrap": bootstrap_info,
        "diagnostic_arm4_excluded": True,
    }


def report_h_p(
    cells: Mapping[tuple[str, int, int | None], dict[str, Any]],
) -> dict[str, Any]:
    """Compute and report exploratory hypothesis H-P (Family P only).

    H-P Contract (PREREG_DRAFT §1 & §5):
    - Family P only has physical parameter variation (friction, restitution, mass, damping).
    - Compares:
        1. Arm ⑤ (IdentifiedPrior) vs Arm ④ (TrueParam diagnostic).
        2. Arm ⑤ vs Arm ③ (PriorResidual).
    - Similarity condition ('≈'):
        Bootstrap 95% CI contains 0 AND CI width <= 0.10 * |error_arm4 - error_arm1|.
    - Reported only, does not constitute a gating requirement.
    """
    fam = "P"
    cell_1 = cells.get((fam, 1, None))
    cell_4 = cells.get((fam, 4, None))
    cell_5 = cells.get((fam, 5, None))

    if not cell_1 or not cell_4 or not cell_5:
        raise MissingCellError("Missing Arm 1, 4, or 5 cell for Family P in H-P reporting")

    err_1 = _extract_10_step_error_from_summary(cell_1.get("summary", cell_1.get("metrics", {})))
    err_4 = _extract_10_step_error_from_summary(cell_4.get("summary", cell_4.get("metrics", {})))
    err_5 = _extract_10_step_error_from_summary(cell_5.get("summary", cell_5.get("metrics", {})))

    ep_1 = _extract_episode_10_step_errors(cell_1.get("episodes", []))
    ep_4 = _extract_episode_10_step_errors(cell_4.get("episodes", []))
    ep_5 = _extract_episode_10_step_errors(cell_5.get("episodes", []))

    # 1. Arm ⑤ vs Arm ④
    gap_4_1 = abs(err_4 - err_1)
    max_similarity_width = H_P_SIMILARITY_MAX_WIDTH_RATIO * gap_4_1

    # Pairwise bootstrap CI between Arm 4 and Arm 5 (absolute diff: err_5 - err_4)
    ci_5_vs_4 = metrics.paired_bootstrap_ci(ep_4[None, :], ep_5[None, :], mode="absolute")
    contains_zero = bool(ci_5_vs_4["contains_zero"])
    ci_width_5_vs_4 = float(ci_5_vs_4["ci_width"])
    is_similar_5_vs_4 = bool(contains_zero and (ci_width_5_vs_4 <= max_similarity_width + 1e-9))

    # 2. Arm ⑤ vs Arm ③
    cells_3 = [cells.get((fam, 3, s)) for s in TRAINING_SEEDS]
    if any(c is None for c in cells_3):
        raise MissingCellError("Missing Arm 3 seeds for Family P in H-P reporting")
    errs_3 = [_extract_10_step_error_from_summary(c.get("summary", c.get("metrics", {}))) for c in cells_3]  # type: ignore
    err_3 = float(np.mean(errs_3))
    ep_3 = np.array([_extract_episode_10_step_errors(c.get("episodes", [])) for c in cells_3])  # type: ignore

    ep_5_3x = np.repeat(ep_5[None, :], len(TRAINING_SEEDS), axis=0)
    # Difference: err_5 - err_3 (absolute)
    ci_5_vs_3 = metrics.paired_bootstrap_ci(ep_3, ep_5_3x, mode="absolute")

    return {
        "hypothesis": "H-P",
        "family": "P",
        "status": "reported",
        "arm1_error_10": err_1,
        "arm4_error_10_diagnostic": err_4,
        "arm5_error_10": err_5,
        "arm3_error_10": err_3,
        "gap_abs_arm4_arm1": gap_4_1,
        "max_similarity_ci_width": max_similarity_width,
        "arm5_vs_arm4": {
            "point_estimate_diff": float(ci_5_vs_4["point_estimate"]),
            "ci_lower": float(ci_5_vs_4["ci_lower"]),
            "ci_upper": float(ci_5_vs_4["ci_upper"]),
            "ci_width": ci_width_5_vs_4,
            "contains_zero": contains_zero,
            "is_similar_approx": is_similar_5_vs_4,
        },
        "arm5_vs_arm3": {
            "point_estimate_diff": float(ci_5_vs_3["point_estimate"]),
            "ci_lower": float(ci_5_vs_3["ci_lower"]),
            "ci_upper": float(ci_5_vs_3["ci_upper"]),
            "ci_width": float(ci_5_vs_3["ci_width"]),
            "arm5_not_worse_than_arm3": bool(err_5 <= err_3 + 1e-9),
        },
    }


def report_h_s(
    cells: Mapping[tuple[str, int, int | None], dict[str, Any]],
) -> dict[str, Any]:
    """Compute and report exploratory hypothesis H-S (Family S only).

    H-S Contract (PREREG_DRAFT §1 & §5):
    - Family S contains missing quadratic drag mechanism.
    - Compares:
        1. Arm ⑥ (IdentifyResidual) vs Arm ⑤ (IdentifiedPrior).
        2. Arm ⑦ (SymbolicResidual) vs Arm ⑤ (IdentifiedPrior).
    - Reported only, does not constitute a gating requirement.
    """
    fam = "S"
    cell_5 = cells.get((fam, 5, None))
    cell_7 = cells.get((fam, 7, None))

    if not cell_5 or not cell_7:
        raise MissingCellError("Missing Arm 5 or 7 cell for Family S in H-S reporting")

    err_5 = _extract_10_step_error_from_summary(cell_5.get("summary", cell_5.get("metrics", {})))
    err_7 = _extract_10_step_error_from_summary(cell_7.get("summary", cell_7.get("metrics", {})))

    ep_5 = _extract_episode_10_step_errors(cell_5.get("episodes", []))
    ep_7 = _extract_episode_10_step_errors(cell_7.get("episodes", []))

    cells_6 = [cells.get((fam, 6, s)) for s in TRAINING_SEEDS]
    if any(c is None for c in cells_6):
        raise MissingCellError("Missing Arm 6 seeds for Family S in H-S reporting")
    errs_6 = [_extract_10_step_error_from_summary(c.get("summary", c.get("metrics", {}))) for c in cells_6]  # type: ignore
    err_6 = float(np.mean(errs_6))
    ep_6 = np.array([_extract_episode_10_step_errors(c.get("episodes", [])) for c in cells_6])  # type: ignore

    # 1. Arm ⑥ vs Arm ⑤ (err_6 - err_5)
    ep_5_3x = np.repeat(ep_5[None, :], len(TRAINING_SEEDS), axis=0)
    ci_6_vs_5 = metrics.paired_bootstrap_ci(ep_5_3x, ep_6, mode="absolute")

    # 2. Arm ⑦ vs Arm ⑤ (err_7 - err_5)
    ci_7_vs_5 = metrics.paired_bootstrap_ci(ep_5[None, :], ep_7[None, :], mode="absolute")

    return {
        "hypothesis": "H-S",
        "family": "S",
        "status": "reported",
        "arm5_error_10": err_5,
        "arm6_error_10": err_6,
        "arm7_error_10": err_7,
        "arm6_vs_arm5": {
            "point_estimate_diff": float(ci_6_vs_5["point_estimate"]),
            "ci_lower": float(ci_6_vs_5["ci_lower"]),
            "ci_upper": float(ci_6_vs_5["ci_upper"]),
            "ci_width": float(ci_6_vs_5["ci_width"]),
            "arm6_better_than_arm5": bool(err_6 < err_5),
        },
        "arm7_vs_arm5": {
            "point_estimate_diff": float(ci_7_vs_5["point_estimate"]),
            "ci_lower": float(ci_7_vs_5["ci_lower"]),
            "ci_upper": float(ci_7_vs_5["ci_upper"]),
            "ci_width": float(ci_7_vs_5["ci_width"]),
            "arm7_better_than_arm5": bool(err_7 < err_5),
        },
    }


def build_analysis_summary(
    cells: Mapping[tuple[str, int, int | None], dict[str, Any]],
    *,
    partition: str = "development",
) -> dict[str, Any]:
    """Execute complete analysis across all families, gates, and exploratory hypotheses."""
    # 1. Evaluate H-E1 on each family independently
    h_e1_results = {fam: decide_h_e1(cells, fam) for fam in FAMILIES}
    overall_h_e1_passed = bool(all(res["passed"] for res in h_e1_results.values()))

    # 2. Exploratory hypotheses
    h_p_report = report_h_p(cells)
    h_s_report = report_h_s(cells)

    # 3. Compile overall summary table of all cells
    cells_overview = []
    for (fam, arm_id, seed), data in sorted(cells.items(), key=lambda x: (x[0][0], x[0][1], x[0][2] or 0)):
        summary = data.get("summary", data.get("metrics", {}))
        k_errs = summary.get("k_step_errors", {})
        cells_overview.append(
            {
                "family": fam,
                "arm": arm_id,
                "arm_name": ARMS_BY_ID[arm_id].name if arm_id in ARMS_BY_ID else f"Arm_{arm_id}",
                "seed": seed,
                "diagnostic": bool(data.get("diagnostic", False) or arm_id in DIAGNOSTIC_ARM_IDS),
                "error_10_m": _extract_10_step_error_from_summary(summary),
                "collision_f1": float(summary.get("collision_f1", 0.0)),
                "error_1_m": float(k_errs.get("1", k_errs.get(1, 0.0))),
                "error_5_m": float(k_errs.get("5", k_errs.get(5, 0.0))),
                "error_30_m": float(k_errs.get("30", k_errs.get(30, 0.0))),
                "mean_energy_drift": summary.get("mean_energy_drift"),
                "mean_latency_s": float(summary.get("mean_latency_per_step_s", 0.0)),
            }
        )

    return {
        "partition": partition,
        "primary_gate_h_e1": {
            "by_family": h_e1_results,
            "overall_passed": overall_h_e1_passed,
        },
        "exploratory_h_p": h_p_report,
        "exploratory_h_s": h_s_report,
        "cells_count": len(cells),
        "cells_overview": cells_overview,
    }


def generate_tables_markdown(summary: Mapping[str, Any]) -> str:
    """Generate GitHub-style markdown tables summarizing evaluation and hypothesis testing."""
    lines: list[str] = []
    lines.append("# E1 Phase 2 Evaluation & Decision Tables")
    lines.append("")
    lines.append(f"**Partition**: `{summary.get('partition', 'development')}`  ")
    lines.append(f"**Total Cells Evaluated**: `{summary.get('cells_count', 0)}`  ")
    lines.append("")

    # Table 1: H-E1 Primary Gate
    lines.append("## 1. Primary Hypothesis H-E1 Gate Decisions")
    lines.append("")
    lines.append("| Family | Baseline Arm | Baseline 10-Step Err (m) | Arm ③ 10-Step Err (m) | Relative Error Reduction (%) | Baseline F1 | Arm ③ F1 | 95% Bootstrap CI (Rel Diff) | Decision |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    h_e1_map = summary.get("primary_gate_h_e1", {}).get("by_family", {})
    for fam in FAMILIES:
        res = h_e1_map.get(fam, {})
        b_arm = res.get("baseline_arm", "-")
        b_err = f"{res.get('baseline_error_10', 0.0):.4f}"
        a3_err = f"{res.get('arm3_error_10', 0.0):.4f}"
        rel_red = f"{res.get('relative_reduction', 0.0) * 100.0:.2f}%"
        b_f1 = f"{res.get('baseline_f1', 0.0):.4f}"
        a3_f1 = f"{res.get('arm3_f1', 0.0):.4f}"
        ci = res.get("paired_bootstrap", {})
        if ci:
            ci_str = f"[{ci.get('ci_lower_relative', 0.0):.4f}, {ci.get('ci_upper_relative', 0.0):.4f}]"
        else:
            ci_str = "N/A"
        dec = "**PASS**" if res.get("passed") else "**FAIL**"
        lines.append(f"| **{fam}** | Arm {b_arm} | {b_err} | {a3_err} | {rel_red} (min 10%) | {b_f1} | {a3_f1} | {ci_str} | {dec} |")

    lines.append("")
    overall_p = summary.get("primary_gate_h_e1", {}).get("overall_passed", False)
    lines.append(f"**Overall H-E1 Decision**: `{'PASSED' if overall_p else 'FAILED'}` (both families independent)\n")

    # Table 2: Exploratory H-P
    lines.append("## 2. Exploratory Hypothesis H-P (Family P)")
    lines.append("")
    hp = summary.get("exploratory_h_p", {})
    lines.append("| Comparison | Baseline Err (m) | Candidate Err (m) | Diff Point Estimate | 95% Bootstrap CI | Criterion | Interpretation |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    c4 = hp.get("arm5_vs_arm4", {})
    ci4 = f"[{c4.get('ci_lower', 0.0):.4f}, {c4.get('ci_upper', 0.0):.4f}]" if c4 else "N/A"
    sim4 = "Yes (≈)" if c4.get("is_similar_approx") else "No"
    lines.append(f"| Arm ⑤ vs Arm ④ (Diag) | {hp.get('arm4_error_10_diagnostic', 0.0):.4f} | {hp.get('arm5_error_10', 0.0):.4f} | {c4.get('point_estimate_diff', 0.0):.4f} | {ci4} | Width <= 10% gap ({hp.get('max_similarity_ci_width', 0.0):.4f}) | {sim4} |")

    c3 = hp.get("arm5_vs_arm3", {})
    ci3 = f"[{c3.get('ci_lower', 0.0):.4f}, {c3.get('ci_upper', 0.0):.4f}]" if c3 else "N/A"
    not_worse = "Yes" if c3.get("arm5_not_worse_than_arm3") else "No"
    lines.append(f"| Arm ⑤ vs Arm ③ (Residual) | {hp.get('arm3_error_10', 0.0):.4f} | {hp.get('arm5_error_10', 0.0):.4f} | {c3.get('point_estimate_diff', 0.0):.4f} | {ci3} | Err(⑤) <= Err(③) | Not Worse: {not_worse} |")
    lines.append("")

    # Table 3: Exploratory H-S
    lines.append("## 3. Exploratory Hypothesis H-S (Family S)")
    lines.append("")
    hs = summary.get("exploratory_h_s", {})
    lines.append("| Comparison | Baseline Err (m) | Candidate Err (m) | Diff Point Estimate | 95% Bootstrap CI | Candidate Outperforms |")
    lines.append("| :--- | :---: | :---: | :---: | :---: | :---: |")
    c6 = hs.get("arm6_vs_arm5", {})
    ci6 = f"[{c6.get('ci_lower', 0.0):.4f}, {c6.get('ci_upper', 0.0):.4f}]" if c6 else "N/A"
    better6 = "Yes" if c6.get("arm6_better_than_arm5") else "No"
    lines.append(f"| Arm ⑥ (Proj Residual) vs Arm ⑤ | {hs.get('arm5_error_10', 0.0):.4f} | {hs.get('arm6_error_10', 0.0):.4f} | {c6.get('point_estimate_diff', 0.0):.4f} | {ci6} | {better6} |")

    c7 = hs.get("arm7_vs_arm5", {})
    ci7 = f"[{c7.get('ci_lower', 0.0):.4f}, {c7.get('ci_upper', 0.0):.4f}]" if c7 else "N/A"
    better7 = "Yes" if c7.get("arm7_better_than_arm5") else "No"
    lines.append(f"| Arm ⑦ (STLSQ Residual) vs Arm ⑤ | {hs.get('arm5_error_10', 0.0):.4f} | {hs.get('arm7_error_10', 0.0):.4f} | {c7.get('point_estimate_diff', 0.0):.4f} | {ci7} | {better7} |")
    lines.append("")

    # Table 4: All Cells Summary
    lines.append("## 4. Evaluation Cells Complete Overview")
    lines.append("")
    lines.append("| Family | Arm | Name | Seed | Diagnostic | Err@10 (m) | Collision F1 | Err@1 (m) | Err@5 (m) | Err@30 (m) | Mean Drift | Latency (ms) |")
    lines.append("| :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
    for row in summary.get("cells_overview", []):
        drift_str = f"{row['mean_energy_drift']:.4f}" if row['mean_energy_drift'] is not None else "-"
        lat_ms = f"{row['mean_latency_s'] * 1000.0:.2f}"
        diag_str = "Yes" if row['diagnostic'] else "No"
        seed_str = str(row['seed']) if row['seed'] is not None else "-"
        lines.append(
            f"| {row['family']} | {row['arm']} | {row['arm_name']} | {seed_str} | {diag_str} | "
            f"{row['error_10_m']:.4f} | {row['collision_f1']:.4f} | {row['error_1_m']:.4f} | "
            f"{row['error_5_m']:.4f} | {row['error_30_m']:.4f} | {drift_str} | {lat_ms} |"
        )
    lines.append("")

    return "\n".join(lines)


def write_report(
    eval_dir: Path | str,
    out_dir: Path | str,
    partition: str = "development",
) -> dict[str, Path]:
    """Execute analysis and write analysis.json and tables.md to out_dir.

    Parameters:
        eval_dir: Directory containing evaluation JSON reports.
        out_dir: Destination directory for analysis artifacts.
        partition: Partition name ('development' or 'final').

    Returns:
        dict mapping artifact keys ('analysis_json', 'tables_md') to output Paths.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    cells = load_cells(eval_dir, partition=partition)
    summary = build_analysis_summary(cells, partition=partition)

    json_path = out_path / "analysis.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = out_path / "tables.md"
    md_content = generate_tables_markdown(summary)
    md_path.write_text(md_content, encoding="utf-8")

    return {
        "analysis_json": json_path,
        "tables_md": md_path,
    }
