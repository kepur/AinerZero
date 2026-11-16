"""S2 experiment preregistration draft generator and validator (ainerzero.V9.P124).

Implements:
- build_draft(): builds comprehensive draft dictionary capturing all frozen spec constants,
  ARM_DIMS, arm parameter counts, source digests under s2, budget envelope, and decision gates.
- validate(): strict validator enforcing required keys, parameter bounds (300k +/- 10%),
  calendar window >= total wallclock time, delta_pred == 1.0, and exact gate constants.
- Note: freeze() and approval line scanning are intentionally NOT implemented here,
  pending user budget approval in a future task.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from . import param_count, spec

SCHEMA = "ainerzero.v9.s2.preregistration.v1"
STATUS_DRAFT = "draft_awaiting_approval"


class SpecValidationError(ValueError):
    """Preregistration document violates frozen specification contracts."""


def canonical_json_bytes(data: Mapping[str, Any]) -> bytes:
    """Format dictionary into deterministic JSON bytes."""
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def compute_sha256(content: bytes) -> str:
    """Compute 64-char lowercase SHA256 hex digest."""
    return hashlib.sha256(content).hexdigest()


def _find_repo_root(start_path: Path | None = None) -> Path:
    """Find repository root containing pyproject.toml."""
    current = (start_path or Path(__file__)).resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return current.parents[4]


def collect_source_digests(repo_root: Path | str | None = None) -> dict[str, str]:
    """Compute SHA256 digests for all Python source files in the s2 experiment package."""
    root = Path(repo_root) if repo_root is not None else _find_repo_root()
    s2_dir = root / "src" / "ainerzero" / "v9" / "experiments" / "s2"
    if not s2_dir.is_dir():
        # Fallback to local package dir
        s2_dir = Path(__file__).resolve().parent
        root = _find_repo_root(s2_dir)

    digests: dict[str, str] = {}
    for py_file in sorted(s2_dir.glob("*.py")):
        if py_file.is_file() and not py_file.name.startswith("."):
            try:
                rel_path = str(py_file.relative_to(root))
            except ValueError:
                rel_path = f"src/ainerzero/v9/experiments/s2/{py_file.name}"
            digests[rel_path] = compute_sha256(py_file.read_bytes())
    return digests



def _r26_planning_fields() -> dict[str, Any]:
    """Registered planning fields of appendix D3.1 / E (r2.6); every value comes from spec."""
    return {
        "replan_every_obs_steps": spec.PLAN_REPLAN_EVERY_OBS_STEPS,
        "cem_n_iters": spec.CEM_N_ITERS,
        "cem_elite_frac": spec.CEM_ELITE_FRAC,
        "cem_encode_reserve": spec.CEM_ENCODE_RESERVE,
        "cem_min_pop": spec.CEM_MIN_POP,
        "smoke_plan_choice": {k: dict(v) for k, v in spec.SMOKE_PLAN_CHOICE.items()},
        "macro_dxy_scale": spec.MACRO_DXY_SCALE,
        "future_dt_l1": spec.PLAN_FUTURE_DT_L1,
        "future_dt_l2": spec.PLAN_FUTURE_DT_L2,
        "cost_mode": {
            "flat": spec.PLAN_COST_TRAJECTORY_SUM,
            "upper": spec.PLAN_COST_TRAJECTORY_SUM,
            "lower": spec.PLAN_COST_TERMINAL,
        },
        "goal_feature": {"last_action": spec.GOAL_FEATURE_LAST_ACTION, "dt": spec.GOAL_FEATURE_DT},
    }


def _probe_fields() -> dict[str, Any]:
    """Registered probe protocol of appendix D5.1; every value comes from spec."""
    return {
        "ridge_lambda": spec.PROBE_RIDGE_LAMBDA,
        "eval_steps": list(spec.PROBE_EVAL_STEPS),
        "fit_samples": spec.PROBE_FIT_SAMPLES,
        "seed_namespace": spec.PROBE_SEED_NAMESPACE,
        "start_points": list(spec.PROBE_START_POINTS),
        "horizon_max": spec.PROBE_HORIZON_MAX,
        "gate_step": spec.PROBE_GATE_STEP,
        "delta_pred": spec.DELTA_PRED,
    }

def build_draft(
    *,
    repo_root: Path | str | None = None,
    draft_time_utc: str | None = None,
) -> dict[str, Any]:
    """Build the complete preregistration draft dictionary from frozen spec constants."""
    root = Path(repo_root) if repo_root is not None else _find_repo_root()
    timestamp = draft_time_utc or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    arm_counts = param_count.count_all_arms_closed_form()

    # Design document digest
    design_path = root / spec.DESIGN_DOCUMENT_PATH
    design_sha256 = (
        compute_sha256(design_path.read_bytes()) if design_path.is_file() else "missing_design_doc"
    )

    doc: dict[str, Any] = {
        "schema": SCHEMA,
        "spec_name": spec.SPEC_NAME,
        "experiment_id": spec.EXPERIMENT_ID,
        "task_id": spec.TASK_ID,
        "status": STATUS_DRAFT,
        "created_utc": timestamp,
        "design_reference": {
            "path": spec.DESIGN_DOCUMENT_PATH,
            "sha256": design_sha256,
        },
        "target_parameters": {
            "target": spec.TARGET_PARAMETER_COUNT,
            "tolerance_fraction": spec.PARAMETER_TOLERANCE_FRACTION,
            "min": spec.PARAM_COUNT_MIN,
            "max": spec.PARAM_COUNT_MAX,
        },
        "arm_dims": copy.deepcopy(spec.ARM_DIMS),
        "arm_parameter_counts": arm_counts,
        "world": {
            "world_size": spec.WORLD_SIZE,
            "rooms_x": spec.ROOMS_X,
            "rooms_y": spec.ROOMS_Y,
            "total_rooms": spec.TOTAL_ROOMS,
            "room_interior_size": spec.ROOM_INTERIOR_SIZE,
            "fov_size": spec.FOV_SIZE,
            "terrain_classes": spec.NUM_TERRAIN_CLASSES,
            "num_actions": spec.NUM_ACTIONS,
            "k_distribution": dict(spec.K_DISTRIBUTION),
            "episode_steps": spec.EPISODE_STEPS,
            "non_bfs_ratio_min": spec.NON_BFS_RATIO_MIN,
            "segment_len_range": [spec.SEGMENT_LEN_MIN, spec.SEGMENT_LEN_MAX],
            "long_goal_min_steps": spec.LONG_GOAL_MIN_STEPS,
            "short_goal_max_steps": spec.SHORT_GOAL_MAX_STEPS,
            "room_pillars_range": [spec.ROOM_PILLARS_MIN, spec.ROOM_PILLARS_MAX],
            "max_rejection_rate": spec.MAX_REJECTION_RATE,
            "max_redraw_retries": spec.MAX_REDRAW_RETRIES,
        },
        "evaluation": {
            "dev_worlds": spec.DEV_WORLDS_COUNT,
            "dev_pairs_per_world": spec.DEV_PAIRS_PER_WORLD,
            "dev_long_goal_episodes": spec.DEV_LONG_GOAL_EPISODES,
            "final_worlds": spec.FINAL_WORLDS_COUNT,
            "final_pairs_per_world": spec.FINAL_PAIRS_PER_WORLD,
            "final_long_goal_episodes": spec.FINAL_LONG_GOAL_EPISODES,
            "episode_l_factor": spec.EPISODE_L_FACTOR,
            "perturb_fraction": spec.PERTURB_FRACTION,
            "perturb_insert_step": spec.PERTURB_INSERT_STEP,
            "perturb_action_count": spec.PERTURB_ACTION_COUNT,
            "regular_dt_subset_episodes": spec.REGULAR_DT_SUBSET_EPISODES,
            "num_seeds": spec.NUM_SEEDS,
            "training_seeds": list(spec.TRAINING_SEEDS),
        },
        "planning": {
            "n_fwd": spec.N_FWD,
            "n_fwd_dev_levels": list(spec.N_FWD_DEV_LEVELS),
            "s2_macro_steps": spec.S2_MACRO_STEPS,
            # r2.6 (appendix E) supersedes replan_m_steps
            **_r26_planning_fields(),
            "flat_h_candidates": list(spec.FLAT_H_CANDIDATES),
            "hierarchical_horizon_candidates": list(spec.HIERARCHICAL_HORIZON_CANDIDATES),
            "hierarchical_budget_ratio_candidates": list(spec.HIERARCHICAL_BUDGET_RATIO_CANDIDATES),
            "hyperparam_selection_max_episodes": spec.HYPERPARAM_SELECTION_MAX_EPISODES,
        },
        "probe": _probe_fields(),
        "gates": {
            "success_rate_diff_min": spec.SUCCESS_RATE_DIFF_MIN,
            "bootstrap_resamples": spec.BOOTSTRAP_RESAMPLES,
            "bootstrap_confidence": spec.BOOTSTRAP_CONFIDENCE,
            "delta_pred": spec.DELTA_PRED,
            "probe_ridge_lambda": spec.PROBE_RIDGE_LAMBDA,
            "probe_eval_steps": list(spec.PROBE_EVAL_STEPS),
            "smoke_circuit_breaker_threshold": spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD,
            "baseline_success_plausible_range": list(spec.BASELINE_SUCCESS_PLAUSIBLE_RANGE),
            "action_sensitivity_floor": spec.ACTION_SENSITIVITY_FLOOR,
            "subgoal_drop_floor": spec.SUBGOAL_DROP_FLOOR,
            "max_dev_evals": spec.MAX_DEV_EVALS,
        },
        "training": {
            "optimizer": spec.OPTIMIZER_NAME,
            "learning_rate": spec.LEARNING_RATE,
            "batch_size": spec.BATCH_SIZE,
            "h_train": spec.H_TRAIN,
            "sequence_length": spec.SEQUENCE_LENGTH,
            "sigreg_lambda": spec.SIGREG_LAMBDA,
            "sigreg_directions": spec.SIGREG_NUM_DIRECTIONS,
            "sigreg_quadrature_points": spec.SIGREG_QUADRATURE_POINTS,
            "idm_mu": spec.IDM_MU,
            "free_bits": spec.ARM_A_FREE_BITS,
            "train_step_time_budget_seconds": spec.TRAIN_STEP_TIME_BUDGET_SECONDS,
            "train_step_efficiency_factor": spec.TRAIN_STEP_EFFICIENCY_FACTOR,
            "model_selection_every_steps": spec.MODEL_SELECTION_EVERY_STEPS,
            "smoke_short_train_steps": spec.SMOKE_SHORT_TRAIN_STEPS,
            "train_steps_rule": spec.TRAIN_STEPS_RULE,
        },
        "data": {
            "train_n_worlds": spec.TRAIN_N_WORLDS,
            "train_episodes_per_world": spec.TRAIN_EPISODES_PER_WORLD,
            "train_holdout_world_fraction": spec.TRAIN_HOLDOUT_WORLD_FRACTION,
            "seed_namespaces": copy.deepcopy(spec.SEED_NAMESPACES),
            "data_estimated_seconds_per_episode": spec.DATA_ESTIMATED_SECONDS_PER_EPISODE,
        },
        "budget": {
            "smoke_max_seconds": spec.BUDGET_SMOKE_MAX_SECONDS,
            "data_max_seconds": spec.BUDGET_DATA_MAX_SECONDS,
            "train_per_slot_seconds": spec.BUDGET_TRAIN_PER_SLOT_SECONDS,
            "train_slots_main": spec.BUDGET_TRAIN_SLOTS_MAIN,
            "train_main_total_seconds": spec.BUDGET_TRAIN_MAIN_TOTAL_SECONDS,
            "arm_d_seconds": spec.BUDGET_ARM_D_SECONDS,
            "baseline_e_seconds": spec.BUDGET_BASELINE_E_SECONDS,
            "hyperparam_selection_seconds": spec.BUDGET_HYPERPARAM_SELECTION_SECONDS,
            "dev_eval_seconds": spec.BUDGET_DEV_EVAL_SECONDS,
            "final_eval_seconds": spec.BUDGET_FINAL_EVAL_SECONDS,
            "total_wallclock_hours": spec.TOTAL_ACTUAL_WALLCLOCK_HOURS,
            "total_wallclock_seconds": spec.TOTAL_ACTUAL_WALLCLOCK_SECONDS,
            "calendar_window_hours": spec.CALENDAR_WINDOW_HOURS,
            "calendar_window_seconds": spec.CALENDAR_WINDOW_SECONDS,
        },
        "stopping_rules": [
            "If both Arm B and Arm C are non-plannable in smoke pre-check: stop before full training.",
            "dev partition decisions allowed at most 2 times; 3rd requires new dev partition.",
            "GridLab-S2 world is incommensurable with S1; M2 reported as incommensurable.",
            "Any arm parameter count outside +/- 10% voids the comparison.",
            "Any planning forward evaluation exceeding N_fwd voids the comparison.",
            "delta_pred frozen at 1.0; no post-hoc tuning permitted on dev or final.",
        ],
        "source_digests": collect_source_digests(root),
    }
    return doc


def validate(document: Mapping[str, Any]) -> None:
    """Strictly validate a preregistration document against frozen specification contracts.

    Raises:
        SpecValidationError: If any required key is missing, parameter counts exceed +/- 10%,
                             calendar window is smaller than total wallclock time,
                             delta_pred != 1.0, or gates/planning constants deviate from spec.
    """
    if not isinstance(document, Mapping):
        raise SpecValidationError(f"Document must be a mapping, got {type(document).__name__}")

    # Top-level required keys
    required_keys = [
        "schema",
        "spec_name",
        "experiment_id",
        "task_id",
        "status",
        "target_parameters",
        "arm_dims",
        "arm_parameter_counts",
        "world",
        "evaluation",
        "planning",
        "gates",
        "probe",
        "training",
        "budget",
        "stopping_rules",
        "source_digests",
        "data",
    ]
    for key in required_keys:
        if key not in document:
            raise SpecValidationError(f"Missing required key in document: {key!r}")

    # Schema & identity contracts
    if document.get("schema") != SCHEMA:
        raise SpecValidationError(
            f"Schema mismatch: expected {SCHEMA}, got {document.get('schema')!r}"
        )
    if document.get("spec_name") != spec.SPEC_NAME:
        raise SpecValidationError(
            f"Spec name mismatch: expected {spec.SPEC_NAME}, got {document.get('spec_name')!r}"
        )
    if document.get("experiment_id") != spec.EXPERIMENT_ID:
        raise SpecValidationError(
            f"Experiment ID mismatch: expected {spec.EXPERIMENT_ID}, got {document.get('experiment_id')!r}"
        )

    # Arm parameter counts validation (300k +/- 10%)
    counts = document.get("arm_parameter_counts")
    if not isinstance(counts, Mapping):
        raise SpecValidationError("arm_parameter_counts must be a mapping")

    expected_arms = {"arm_a", "arm_b", "arm_c"}
    if set(counts.keys()) != expected_arms:
        raise SpecValidationError(
            f"arm_parameter_counts arms mismatch: expected {expected_arms}, got {set(counts.keys())}"
        )

    for arm, count in counts.items():
        if not isinstance(count, int):
            raise SpecValidationError(f"Parameter count for {arm} must be an integer, got {count!r}")
        if count < spec.PARAM_COUNT_MIN or count > spec.PARAM_COUNT_MAX:
            raise SpecValidationError(
                f"Arm {arm} parameter count {count} is outside the allowed +/- 10% range "
                f"[{spec.PARAM_COUNT_MIN}, {spec.PARAM_COUNT_MAX}] (target: {spec.TARGET_PARAMETER_COUNT})"
            )

    # Planning validation
    planning = document.get("planning")
    if not isinstance(planning, Mapping):
        raise SpecValidationError("Missing or invalid planning section")
    if planning.get("n_fwd") != spec.N_FWD:
        raise SpecValidationError(
            f"Planning N_fwd mismatch: expected {spec.N_FWD}, got {planning.get('n_fwd')}"
        )
    if planning.get("s2_macro_steps") != spec.S2_MACRO_STEPS:
        raise SpecValidationError(
            f"Planning s2 mismatch: expected {spec.S2_MACRO_STEPS}, got {planning.get('s2_macro_steps')}"
        )
    if "replan_m_steps" in planning:
        raise SpecValidationError("replan_m_steps is superseded by replan_every_obs_steps (r2.6)")
    if spec.PLAN_REPLAN_EVERY_OBS_STEPS != 1 or planning.get("replan_every_obs_steps") != 1:
        raise SpecValidationError("r2.6 requires replanning every observation step (m = 1)")
    for key, expected in _r26_planning_fields().items():
        if planning.get(key) != expected:
            raise SpecValidationError(f"Planning {key} mismatch: expected {expected!r}, got {planning.get(key)!r}")
    allowed_costs = {spec.PLAN_COST_TRAJECTORY_SUM, spec.PLAN_COST_TERMINAL}
    if not set(planning.get("cost_mode", {}).values()) <= allowed_costs:
        raise SpecValidationError(f"cost_mode values must be in {sorted(allowed_costs)}")

    # Post-train gate thresholds and dev cap (appendix B, §7)
    gates_doc = document.get("gates") or {}
    for key, expected in (
        ("action_sensitivity_floor", spec.ACTION_SENSITIVITY_FLOOR),
        ("subgoal_drop_floor", spec.SUBGOAL_DROP_FLOOR),
        ("max_dev_evals", spec.MAX_DEV_EVALS),
        ("baseline_success_plausible_range", list(spec.BASELINE_SUCCESS_PLAUSIBLE_RANGE)),
    ):
        if gates_doc.get(key) != expected:
            raise SpecValidationError(f"Gates {key} mismatch: expected {expected!r}, got {gates_doc.get(key)!r}")

    # Probe validation (DESIGN-r2 appendix D5.1)
    probe_doc = document.get("probe")
    if not isinstance(probe_doc, Mapping):
        raise SpecValidationError("Missing or invalid probe section")
    for key, expected in _probe_fields().items():
        if probe_doc.get(key) != expected:
            raise SpecValidationError(f"Probe {key} mismatch: expected {expected!r}, got {probe_doc.get(key)!r}")

    # Gates validation
    gates = document.get("gates")
    if not isinstance(gates, Mapping):
        raise SpecValidationError("Missing or invalid gates section")

    delta_pred = gates.get("delta_pred")
    if delta_pred != spec.DELTA_PRED:
        raise SpecValidationError(
            f"delta_pred mismatch: expected {spec.DELTA_PRED}, got {delta_pred}"
        )
    if gates.get("success_rate_diff_min") != spec.SUCCESS_RATE_DIFF_MIN:
        raise SpecValidationError(
            f"success_rate_diff_min mismatch: expected {spec.SUCCESS_RATE_DIFF_MIN}, "
            f"got {gates.get('success_rate_diff_min')}"
        )
    if gates.get("bootstrap_resamples") != spec.BOOTSTRAP_RESAMPLES:
        raise SpecValidationError(
            f"bootstrap_resamples mismatch: expected {spec.BOOTSTRAP_RESAMPLES}, "
            f"got {gates.get('bootstrap_resamples')}"
        )
    if gates.get("smoke_circuit_breaker_threshold") != spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD:
        raise SpecValidationError(
            f"smoke_circuit_breaker_threshold mismatch: expected {spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD}, "
            f"got {gates.get('smoke_circuit_breaker_threshold')}"
        )

    # Budget validation
    budget = document.get("budget")
    if not isinstance(budget, Mapping):
        raise SpecValidationError("Missing or invalid budget section")

    wallclock = budget.get("total_wallclock_hours")
    calendar = budget.get("calendar_window_hours")
    if wallclock is None or calendar is None:
        raise SpecValidationError("Budget must specify total_wallclock_hours and calendar_window_hours")
    if float(calendar) < float(wallclock):
        raise SpecValidationError(
            f"Calendar window ({calendar} h) cannot be smaller than total actual wallclock time ({wallclock} h)"
        )
    if float(wallclock) != spec.TOTAL_ACTUAL_WALLCLOCK_HOURS:
        raise SpecValidationError(
            f"total_wallclock_hours mismatch: expected {spec.TOTAL_ACTUAL_WALLCLOCK_HOURS}, got {wallclock}"
        )
    if float(calendar) != spec.CALENDAR_WINDOW_HOURS:
        raise SpecValidationError(
            f"calendar_window_hours mismatch: expected {spec.CALENDAR_WINDOW_HOURS}, got {calendar}"
        )

    # Source digests validation
    digests = document.get("source_digests")
    if not isinstance(digests, Mapping) or not digests:
        raise SpecValidationError("source_digests must be a non-empty mapping")
    for src_path, d in digests.items():
        if not isinstance(d, str) or len(d) != 64:
            raise SpecValidationError(f"Invalid SHA256 digest for {src_path}: {d!r}")

    # Training Appendix C constants validation
    training = document.get("training")
    if not isinstance(training, Mapping):
        raise SpecValidationError("Missing or invalid training section")
    if training.get("model_selection_every_steps") != spec.MODEL_SELECTION_EVERY_STEPS:
        raise SpecValidationError(
            f"model_selection_every_steps mismatch: expected {spec.MODEL_SELECTION_EVERY_STEPS}, "
            f"got {training.get('model_selection_every_steps')}"
        )
    if training.get("smoke_short_train_steps") != spec.SMOKE_SHORT_TRAIN_STEPS:
        raise SpecValidationError(
            f"smoke_short_train_steps mismatch: expected {spec.SMOKE_SHORT_TRAIN_STEPS}, "
            f"got {training.get('smoke_short_train_steps')}"
        )
    if training.get("train_steps_rule") != spec.TRAIN_STEPS_RULE:
        raise SpecValidationError(
            f"train_steps_rule mismatch: expected {spec.TRAIN_STEPS_RULE!r}, "
            f"got {training.get('train_steps_rule')!r}"
        )

    # Data & partition contracts (Appendix C)
    data_section = document.get("data")
    if not isinstance(data_section, Mapping):
        data_section = document.get("partitions")
    if not isinstance(data_section, Mapping):
        raise SpecValidationError("Missing or invalid data section")

    # 1. Four seed namespaces must be pairwise distinct
    namespaces = data_section.get("seed_namespaces")
    if not isinstance(namespaces, Mapping):
        raise SpecValidationError("seed_namespaces must be a mapping")
    required_ns_keys = {"train", "dev", "final", "smoke"}
    if not required_ns_keys.issubset(namespaces.keys()):
        raise SpecValidationError(
            f"seed_namespaces missing required keys: {required_ns_keys - set(namespaces.keys())}"
        )
    ns_values = [namespaces[k] for k in sorted(required_ns_keys)]
    if len(set(ns_values)) != len(ns_values):
        raise SpecValidationError(
            f"Seed namespaces must be pairwise distinct, got duplicates: {namespaces}"
        )

    # 2. Holdout fraction must be in (0, 0.5)
    holdout = data_section.get("train_holdout_world_fraction")
    if holdout is None or not (0.0 < float(holdout) < 0.5):
        raise SpecValidationError(
            f"train_holdout_world_fraction must be strictly in (0, 0.5), got {holdout!r}"
        )

    # 3. Train scale * 0.145 s/episode estimate <= data budget (3600 s)
    train_n_worlds = data_section.get("train_n_worlds")
    train_episodes_per_world = data_section.get("train_episodes_per_world")
    est_sec = data_section.get(
        "data_estimated_seconds_per_episode", spec.DATA_ESTIMATED_SECONDS_PER_EPISODE
    )

    if not isinstance(train_n_worlds, int) or train_n_worlds <= 0:
        raise SpecValidationError(
            f"train_n_worlds must be a positive integer, got {train_n_worlds!r}"
        )
    if not isinstance(train_episodes_per_world, int) or train_episodes_per_world <= 0:
        raise SpecValidationError(
            f"train_episodes_per_world must be a positive integer, got {train_episodes_per_world!r}"
        )
    if not isinstance(est_sec, (int, float)) or est_sec <= 0:
        raise SpecValidationError(
            f"data_estimated_seconds_per_episode must be a positive number, got {est_sec!r}"
        )

    estimated_data_seconds = train_n_worlds * train_episodes_per_world * float(est_sec)
    data_budget_seconds = spec.BUDGET_DATA_MAX_SECONDS
    if estimated_data_seconds > data_budget_seconds:
        raise SpecValidationError(
            f"Estimated train data generation time ({estimated_data_seconds:.1f} s) "
            f"exceeds data budget ({data_budget_seconds} s)"
        )

