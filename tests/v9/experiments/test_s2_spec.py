"""Tests for S2 specification and frozen constants (ainerzero.V9.P124).

Verifies:
- All frozen numerical values and structures match reports/V9-S2-DESIGN/DESIGN-r2.md.
- 10 key numerical constants are present and match string representations in DESIGN-r2.md.
- ARM_DIMS registered table contains complete configurations for all arms.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from ainerzero.v9.experiments.s2 import spec


def test_experiment_identity() -> None:
    """Verify task, experiment, and specification identity strings."""
    assert spec.SPEC_NAME == "s2-phase1-v1"
    assert spec.TASK_ID == "ainerzero.V9.P124"
    assert spec.EXPERIMENT_ID == "s2-phase1-20261106-r0"
    assert spec.DESIGN_DOCUMENT_PATH == "reports/V9-S2-DESIGN/DESIGN-r2.md"


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return current.parents[3]


def test_spec_matches_design_document_constants() -> None:
    """Cross-check 10+ key numerical values directly against DESIGN-r2.md text."""
    design_file = _find_repo_root() / spec.DESIGN_DOCUMENT_PATH
    assert design_file.is_file(), f"Design document missing at {design_file}"
    content = design_file.read_text(encoding="utf-8")

    # 10 key numerical checks with exact string matching
    key_checks: list[tuple[str, str, bool]] = [
        ("25×25", "WORLD_SIZE: 25x25 grid", spec.WORLD_SIZE == 25 and spec.GRID_WIDTH == 25),
        ("3×3", "ROOMS: 3x3 rooms (9 rooms)", spec.ROOMS_X == 3 and spec.TOTAL_ROOMS == 9),
        ("7×7", "FOV: 7x7 field of view", spec.FOV_SIZE == 7),
        ("240", "EPISODE_STEPS: 240 steps", spec.EPISODE_STEPS == 240),
        ("40", "LONG_GOAL: shortest path >= 40", spec.LONG_GOAL_MIN_STEPS == 40),
        ("10", "SHORT_GOAL: shortest path <= 10", spec.SHORT_GOAL_MAX_STEPS == 10),
        ("4096", "N_FWD: 4096 evaluation budget", spec.N_FWD == 4096),
        ("1.0", "DELTA_PRED: 1.0 grid units", spec.DELTA_PRED == 1.0),
        ("10,000", "BOOTSTRAP: 10,000 resamples", spec.BOOTSTRAP_RESAMPLES == 10_000),
        ("72", "CALENDAR: 72 h window", spec.CALENDAR_WINDOW_HOURS == 72.0),
        ("15 h", "WALLCLOCK: 15 h total actual time (appendix F, user 11-08)", spec.TOTAL_ACTUAL_WALLCLOCK_HOURS == 15.0),
        ("300k", "PARAM_TARGET: 300k target", spec.TARGET_PARAMETER_COUNT == 300_000),
    ]

    for needle, desc, val_ok in key_checks:
        assert needle in content, f"Expected needle {needle!r} ({desc}) in DESIGN-r2.md"
        assert val_ok, f"Constant value check failed for {desc}"


def test_delta_pred_strict_value() -> None:
    """Strict verification of delta_pred value against design (§5, r2.2)."""
    assert spec.DELTA_PRED == 1.0, f"DELTA_PRED must be exactly 1.0, got {spec.DELTA_PRED}"


def test_world_and_data_constants() -> None:
    """Verify world geometry, observation, and distribution specifications."""
    assert spec.WORLD_SIZE == 25
    assert spec.TOTAL_ROOMS == 9
    assert spec.ROOM_INTERIOR_SIZE == 7
    assert spec.FOV_SIZE == 7
    assert spec.NUM_ACTIONS == 4
    assert spec.ACTION_DIM == 4
    assert spec.OBS_DIM == 205
    assert spec.TERRAIN_ONE_HOT_DIM == 196
    assert spec.K_DISTRIBUTION == {1: 0.5, 2: 0.3, 3: 0.2}
    assert spec.NON_BFS_RATIO_MIN == 0.5
    assert spec.EPISODE_L_FACTOR == 3.0
    assert spec.PERTURB_INSERT_STEP == 20
    assert spec.PERTURB_ACTION_COUNT == 5
    assert abs(spec.PERTURB_FRACTION - 1.0 / 3.0) < 1e-6


def test_evaluation_constants() -> None:
    """Verify dev and final partition parameters and regular dt subset."""
    assert spec.DEV_WORLDS_COUNT == 50
    assert spec.DEV_PAIRS_PER_WORLD == 6
    assert spec.DEV_LONG_GOAL_EPISODES == 300
    assert spec.FINAL_WORLDS_COUNT == 50
    assert spec.FINAL_PAIRS_PER_WORLD == 6
    assert spec.FINAL_LONG_GOAL_EPISODES == 300
    assert spec.REGULAR_DT_SUBSET_EPISODES == 100
    assert spec.NUM_SEEDS == 3
    assert spec.TRAINING_SEEDS == (42, 43, 44)


def test_planning_constants() -> None:
    """Verify planning forward count, macro step s2, and candidate grids."""
    assert spec.N_FWD == 4096
    assert spec.N_FWD_DEV_LEVELS == (2048, 4096, 8192)
    assert spec.S2_MACRO_STEPS == 8
    assert spec.REPLAN_M_STEPS == 4
    assert spec.FLAT_H_CANDIDATES == (16, 32, 48)
    assert spec.HIERARCHICAL_HORIZON_CANDIDATES == (4, 6, 8)
    assert spec.HIERARCHICAL_BUDGET_RATIO_CANDIDATES == (0.25, 0.5)
    assert spec.HYPERPARAM_SELECTION_MAX_EPISODES == 50


def test_gates_and_stopping_constants() -> None:
    """Verify decision gates, confidence levels, and circuit breaker."""
    assert spec.SUCCESS_RATE_DIFF_MIN == 0.10
    assert spec.BOOTSTRAP_RESAMPLES == 10_000
    assert spec.BOOTSTRAP_CONFIDENCE == 0.95
    assert spec.DELTA_PRED == 1.0
    assert spec.PROBE_RIDGE_LAMBDA == 1.0
    assert spec.PROBE_EVAL_STEPS == (1, 5, 10, 30, 60)
    assert spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD == 0.05
    assert spec.BASELINE_SUCCESS_PLAUSIBLE_RANGE == (0.1, 0.8)


def test_budget_envelope_constants() -> None:
    """Verify budget ceiling times and calendar window."""
    assert spec.BUDGET_SMOKE_MAX_SECONDS == 1200
    assert spec.BUDGET_DATA_MAX_SECONDS == 3600
    assert spec.BUDGET_TRAIN_PER_SLOT_SECONDS == 1200
    assert spec.BUDGET_TRAIN_SLOTS_MAIN == 9
    assert spec.BUDGET_TRAIN_MAIN_TOTAL_SECONDS == 10_800
    assert spec.BUDGET_ARM_D_SECONDS == 3600
    assert spec.BUDGET_BASELINE_E_SECONDS == 300
    # appendix F (user 11-08): total 15 h
    assert spec.BUDGET_HYPERPARAM_SELECTION_SECONDS == 2400
    assert spec.BUDGET_DEV_EVAL_SECONDS == 36_000
    assert spec.BUDGET_FINAL_EVAL_SECONDS == 9_000
    assert spec.TOTAL_ACTUAL_WALLCLOCK_HOURS == 15.0
    assert spec.TOTAL_ACTUAL_WALLCLOCK_SECONDS == 54_000
    assert spec.CALENDAR_WINDOW_HOURS == 72.0
    assert spec.CALENDAR_WINDOW_HOURS >= spec.TOTAL_ACTUAL_WALLCLOCK_HOURS


def test_arm_dims_table_completeness() -> None:
    """Verify ARM_DIMS registered table contains required dimensions for A, B, C."""
    assert set(spec.ARM_DIMS.keys()) == {"arm_a", "arm_b", "arm_c"}

    arm_a = spec.ARM_DIMS["arm_a"]
    assert arm_a["e1_input"] == 205
    assert arm_a["e1_hidden"] == 256
    assert arm_a["e1_output"] == 128
    assert arm_a["gru_input"] == 37
    assert arm_a["gru_hidden"] == 160
    assert arm_a["latent_dim"] == 32

    arm_b = spec.ARM_DIMS["arm_b"]
    assert arm_b["p1_hidden_1"] == 320
    assert arm_b["p1_hidden_2"] == 320
    assert arm_b["idm_hidden"] == 128

    arm_c = spec.ARM_DIMS["arm_c"]
    assert arm_c["p1_hidden_1"] == 256
    assert arm_c["p1_hidden_2"] == 256
    assert arm_c["e2_hidden"] == 128
    assert arm_c["z2_dim"] == 64
    assert arm_c["p2_hidden"] == 128
    assert arm_c["idm2_hidden"] == 64


def test_appendix_c_constants_match_design_document() -> None:
    """Verify Appendix C constants match DESIGN-r2.md text and numerical definitions."""
    design_file = _find_repo_root() / spec.DESIGN_DOCUMENT_PATH
    assert design_file.is_file(), f"Design document missing at {design_file}"
    content = design_file.read_text(encoding="utf-8")

    # Check presence of Appendix C needles in design document
    appendix_c_needles = [
        "附录 C",
        "1000 个世界",
        "8 回合",
        "10%",
        "s2p1-train-v1",
        "s2p1-dev-v1",
        "s2p1-final-v1",
        "s2p1-smoke-v1",
        "0.145 s/回合",
        "200 步",
    ]
    for needle in appendix_c_needles:
        assert needle in content, f"Expected needle {needle!r} in {spec.DESIGN_DOCUMENT_PATH}"

    # Verify spec constant values
    assert spec.TRAIN_N_WORLDS == 1000
    assert spec.TRAIN_EPISODES_PER_WORLD == 8
    assert spec.TRAIN_HOLDOUT_WORLD_FRACTION == 0.10
    assert spec.SEED_NAMESPACES == {
        "train": "s2p1-train-v1",
        "dev": "s2p1-dev-v1",
        "final": "s2p1-final-v1",
        "smoke": "s2p1-smoke-v1",
    }
    assert spec.MODEL_SELECTION_EVERY_STEPS == 200
    assert spec.SMOKE_SHORT_TRAIN_STEPS == 200
    assert "floor(1200*0.8/t" in spec.TRAIN_STEPS_RULE
    assert spec.DATA_ESTIMATED_SECONDS_PER_EPISODE == 0.145


def test_spec_existing_prefix_byte_for_byte_unchanged() -> None:
    """Verify spec.py prefix (prior to Appendix C append) is byte-for-byte identical to P124/HEAD."""
    import hashlib

    spec_file = Path(spec.__file__).resolve()
    raw_bytes = spec_file.read_bytes()
    prefix_bytes = raw_bytes[:8721]
    expected_sha = "b1992a6407453c68083c0236c188dd15877bde28d90a10fa69f6ac160f5d5522"
    actual_sha = hashlib.sha256(prefix_bytes).hexdigest()
    assert (
        actual_sha == expected_sha
    ), f"spec.py prefix SHA256 mismatch! expected {expected_sha}, got {actual_sha}"

