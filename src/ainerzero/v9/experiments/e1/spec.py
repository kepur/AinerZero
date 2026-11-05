"""Frozen E1 phase-2 constants and specification (ainerzero.V9.P71).

Everything in this module defines the frozen preregistration payload for E1 Phase 2:
the arm structures, parameter counts, data partitions, metrics, primary decision
thresholds, budget caps, and host anchor rules.

Changing a value here changes the canonical document hash.

Citations & Sources:
- Draft Candidate r4: reports/V9-P48/PREREG_DRAFT_r4_candidate.md (SHA256 prefix: ef7856e7f757)
- Core Design: reports/frontier-integration-20261027/DESIGN_CORE.md (§1-§3, §5)
- Implementation Plan: reports/V9-P48/E1_IMPLEMENTATION_PLAN.md
- Prior & Jacobian: src/ainerzero/v9/experiments/e1/prior.py, jacobian.py
- Net Arms & Parameter Budget: src/ainerzero/v9/experiments/e1/arms_net.py
- Metrics Definitions: src/ainerzero/v9/experiments/e1/metrics.py
- Dataset & Partition Conventions: src/ainerzero/v9/experiments/e1/export.py
- Host Anchor & Approval Gate: ARCHITECTURE_V9.md §8.3, RESEARCH_LOG.md
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .arms_net import REGISTERED_PARAMETER_COUNT
from .jacobian import DEFAULT_REL_STEP, DEFAULT_SVD_REL_TOL
from .metrics import (
    BALLISTIC_MIN_FRAMES,
    BOOTSTRAP_CONFIDENCE,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    COLLISION_DEBOUNCE_FRAMES,
    COLLISION_MATCH_TOLERANCE_FRAMES,
    COLLISION_VELOCITY_THRESHOLD_MPS,
    CONTACT_TOLERANCE_M,
    DEFAULT_K_STEPS,
    GRAVITY_ACCEL,
    PRIMARY_K,
)
from .prior import DEFAULT_BIASED_PRIOR, DEFAULT_SUBSTEPS, SUBSTEP_DT

# --- Spec & Experiment Identity ---
SPEC_NAME = "e1-phase2-v1"
TASK_ID = "ainerzero.V9.P71"
EXPERIMENT_ID = "e1-phase2-20261105-r2"
# r2 keeps its own ledger under its own output root, so its budget ceiling counts r2 runs only.
# r0 and r1 stay in artifacts/v9/e1/phase2/control.sqlite3 as delivered evidence.
LEDGER_EXPERIMENT_IDS: tuple[str, ...] = (EXPERIMENT_ID,)
SUPERSEDED_EXPERIMENT_IDS: tuple[str, ...] = ("e1-phase2-20261029-r0", "e1-phase2-20261029-r1")
SUPERSEDED_DOCUMENT_SHA256 = "84f23f2ce3a6071f622613cfa4f43a8abb468b02e456da994917bc1db68fe9f6"

# What changed from r1, approved by the user on 2026-11-05 (RESEARCH_LOG.md, R20261105-E1-dev).
REVISION_CHANGES: tuple[str, ...] = (
    "prior: inter-body contact normal and depth from exact geometry (box-box SAT, sphere-box closest point)",
    "eval: prediction-side collision events use exact shape surface distance and per-pair static geometry",
    "final-eval: all registered arms, one read per family, separate user approval line",
)

# Only these arms are retrained in r2. Arm 2 does not use the prior, so its r1 checkpoints carry over.
# It is still evaluated in r2, because the collision metric changed.
RETRAIN_ARM_IDS: tuple[int, ...] = (3, 6)
DATA_GENERATION_ALLOWED: bool = False
INHERITED_ARM2_WEIGHTS_SHA256: dict[str, str] = {
    "arm2_P_seed42": "54b91b53af2197cd977ea70eb1ee8677c2d5e6fbb3d232996dbb2f606a71e287",
    "arm2_P_seed43": "3377c451d2589fee2ae5bb3ba46f5d34846751d3843bab0a55a016bceaf66dc6",
    "arm2_P_seed44": "fa3190b28a2654677192358b0eedabc15fb7f486c8219c464b9dcaebee4b5ddb",
    "arm2_S_seed42": "f49a9c52e47ccdd4c3de85587e388808fcce6414544f5ce97e138d738715ffd6",
    "arm2_S_seed43": "4f61d0a964fbc2313f6acb3a2d3ef50b76523f88d415882145a788a1a9f8b373",
    "arm2_S_seed44": "45d9adedf0277c8395b43d8baac5170e8a9477589a21559de78afc826beb1441",
}

PREREG_DRAFT_PATH = "reports/V9-P48/PREREG_DRAFT_r4_candidate.md"
PREREG_DRAFT_SHA256 = (
    "ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e"
)
PREREG_DRAFT_SHA256_PREFIX = "ef7856e7f757"

INHERITED_ARM2_NORMALIZATION_SHA256: dict[str, str] = {
    "arm2_P_seed42": "5ed265a63e667394ea7991c1b26c9f00250db0729116f1bc0d65690a66188ad5",
    "arm2_P_seed43": "3deb756a558c9107d15131ce9a054ce1832b1a79e72e77c45ddee33eb1eea9be",
    "arm2_P_seed44": "54d71079de5c9bfd26824b9a87dff9a7c3d78c3ee4763efba031e299babcc55d",
    "arm2_S_seed42": "ad73cd198479697e903a2346b6551ba54e758c6fb26bb3c89e2c7c9b486ab705",
    "arm2_S_seed43": "cc0013b9d38ed64c74aa2a5e0b4272de1a65ae593a57e51b714f77e58f622488",
    "arm2_S_seed44": "0e17f49d4d39945885f2d8ae5fca26c19dc240fbe83143818fa676b9e27d611a",
}

# --- Host Anchor (fail-closed) ---
REGISTERED_HOST_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REGISTERED_HOST_R1_PHASE2 = REGISTERED_HOST_ROOT / "artifacts" / "v9" / "e1" / "phase2"
REGISTERED_HOST_DATASETS = REGISTERED_HOST_R1_PHASE2 / "datasets"  # read-only, reused from r0/r1
REGISTERED_HOST_PHASE2 = REGISTERED_HOST_ROOT / "artifacts" / "v9" / "e1" / "phase2-r2"
REGISTERED_HOST_LEDGER = REGISTERED_HOST_PHASE2 / "control.sqlite3"
REGISTERED_HOST_APPROVAL = REGISTERED_HOST_ROOT / "RESEARCH_LOG.md"
REGISTERED_HOST_LOCK = REGISTERED_HOST_ROOT / "artifacts" / "locks" / "m0-worker.lock"
HOST_ANCHOR_SCHEMA = "ainerzero.v9.e1.host_anchor.v1"


def host_anchor_state(root: Path | str | None = None) -> dict[str, Any]:
    """Read-only identity state of the registered host anchor (fail closed)."""
    anchor_root = Path(root) if root is not None else REGISTERED_HOST_ROOT
    try:
        anchor_root = anchor_root.resolve()
    except OSError as exc:
        return {
            "schema": HOST_ANCHOR_SCHEMA,
            "status": "unresolvable",
            "root": str(anchor_root),
            "reason": f"{type(exc).__name__}: {exc}",
        }
    phase2 = anchor_root / "artifacts" / "v9" / "e1" / "phase2-r2"
    approval = anchor_root / "RESEARCH_LOG.md"
    state: dict[str, Any] = {
        "schema": HOST_ANCHOR_SCHEMA,
        "status": "ok",
        "root": str(anchor_root),
        "phase2_root": str(phase2),
        "ledger": str(phase2 / "control.sqlite3"),
        "approval_log": str(approval),
        "lock": str(anchor_root / "artifacts" / "locks" / "m0-worker.lock"),
        "registered": root is None,
    }
    if not anchor_root.is_dir():
        state.update({"status": "missing_root", "reason": "host root is not a directory"})
        return state
    if not approval.is_file():
        state.update({"status": "missing_approval", "reason": "no approval log at anchor"})
        return state
    try:
        with open(approval, "rb") as handle:
            handle.read(1)
    except OSError as exc:
        state.update(
            {"status": "unreadable_approval", "reason": f"{type(exc).__name__}: {exc}"}
        )
    return state


def host_anchor(root: Path | str | None = None) -> dict[str, Any]:
    """The anchor dict for a bounded run, or RuntimeError when not anchored."""
    state = host_anchor_state(root)
    if state["status"] != "ok":
        raise RuntimeError(
            f"registered host anchor is {state['status']}: {state.get('reason', '')}"
        )
    return state


REPO_ROOT = REGISTERED_HOST_ROOT
AWZ_ROOT = Path("/Users/mac/AinerWorkFlow/AnimeWorldZero")
RESEARCH_LOG = REGISTERED_HOST_APPROVAL
ARTIFACTS_E1 = REPO_ROOT / "artifacts" / "v9" / "e1"
REPORTS_E1 = REPO_ROOT / "reports" / "V9-E1E1"


# --- Arm Specifications (PREREG_DRAFT.md §2) ---
@dataclass(frozen=True)
class ArmSpec:
    """Registered configuration for an E1 experiment arm."""

    arm_id: int
    name: str
    trainable: bool
    parameter_count: int
    tag: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


REGISTERED_NET_PARAMETER_COUNT = REGISTERED_PARAMETER_COUNT
assert REGISTERED_NET_PARAMETER_COUNT == 6150, (
    f"Expected registered parameter count 6150, got {REGISTERED_NET_PARAMETER_COUNT}"
)

ARM_SPECS: tuple[ArmSpec, ...] = (
    ArmSpec(
        arm_id=1,
        name="BiasedPriorArm",
        trainable=False,
        parameter_count=0,
        tag="prior",
        description="Fixed biased physical prior (F_prior) with median parameter values",
    ),
    ArmSpec(
        arm_id=2,
        name="PureNetArm",
        trainable=True,
        parameter_count=REGISTERED_NET_PARAMETER_COUNT,
        tag="pure_neural",
        description="Pure MLX dynamics neural network (no prior inductive bias)",
    ),
    ArmSpec(
        arm_id=3,
        name="PriorResidualArm",
        trainable=True,
        parameter_count=REGISTERED_NET_PARAMETER_COUNT,
        tag="prior_residual",
        description="Biased prior F_prior + MLX residual network correction",
    ),
    ArmSpec(
        arm_id=4,
        name="TrueParamArm",
        trainable=False,
        parameter_count=0,
        tag="diagnostic",
        description="Analytical prior with ground truth parameters (upper bound diagnostic only, out of competition)",
    ),
    ArmSpec(
        arm_id=5,
        name="IdentifiedPriorArm",
        trainable=False,
        parameter_count=0,
        tag="identification",
        description="Biased prior with online parameter identification (SMC / filter) without neural network",
    ),
    ArmSpec(
        arm_id=6,
        name="IdentifyResidualArm",
        trainable=True,
        parameter_count=REGISTERED_NET_PARAMETER_COUNT,
        tag="hybrid_projected",
        description="Identified prior + MLX residual projected orthogonally onto ker(dF_prior/d_phi)^T",
    ),
    ArmSpec(
        arm_id=7,
        name="SymbolicResidualArm",
        trainable=False,
        parameter_count=0,
        tag="symbolic",
        description="Identified prior + STLSQ sparse symbolic regression residual",
    ),
)

ARMS_BY_ID: dict[int, ArmSpec] = {arm.arm_id: arm for arm in ARM_SPECS}
TRAINABLE_ARM_IDS: tuple[int, ...] = (2, 3, 6)
NON_TRAINABLE_ARM_IDS: tuple[int, ...] = (1, 4, 5, 7)
DIAGNOSTIC_ARM_IDS: tuple[int, ...] = (4,)


# --- World Families & Partitions (PREREG_DRAFT.md §3) ---
FAMILIES: tuple[str, ...] = ("P", "S")
FAMILY_DESCRIPTIONS: dict[str, str] = {
    "P": "Parameter variation only (friction, restitution, mass, damping)",
    "S": "Parameter variation + quadratic_drag_v1 drag field mechanism",
}

PARTITIONS: tuple[str, ...] = ("train", "development", "final")
TRAIN_WORLDS_PER_FAMILY: int = 1000
DEV_WORLDS_PER_FAMILY: int = 200
FINAL_WORLDS_PER_FAMILY: int = 200
WORLDS_PER_FAMILY_TOTAL: int = (
    TRAIN_WORLDS_PER_FAMILY + DEV_WORLDS_PER_FAMILY + FINAL_WORLDS_PER_FAMILY
)
TOTAL_EXPERIMENT_WORLDS: int = WORLDS_PER_FAMILY_TOTAL * len(FAMILIES)  # 2800

DATA_SEED: int = 1001
TRAINING_SEEDS: tuple[int, ...] = (42, 43, 44)


# --- Simulation & Alignment Constants (PREREG_DRAFT.md §3) ---
DEFAULT_TRAIN_STEPS: int = 64000
EARLY_STOP_EVAL_EVERY: int = 500
EARLY_STOP_PATIENCE: int = 10
VALIDATION_FRACTION: float = 0.1
VALIDATION_SPLIT_SEED: int = 20261030
DEFAULT_LEARNING_RATE: float = 1e-3
DEFAULT_BATCH_SIZE: int = 16

FPS_SIMULATION: int = 60
PHYSICS_TICKS_PER_SEC: int = 120
SUBSTEPS_PER_FRAME: int = DEFAULT_SUBSTEPS  # 10 sub-steps -> 600 Hz
SUBSTEP_DELTA_T: float = SUBSTEP_DT  # 1 / 600 s
TICKS_PER_FRAME_RATIO: int = PHYSICS_TICKS_PER_SEC // FPS_SIMULATION  # 2 ticks/frame
COORDINATE_SYSTEM: str = "right_handed_z_up"
GRAVITY_VECTOR: tuple[float, float, float] = (0.0, 0.0, -GRAVITY_ACCEL)

# Biased prior parameter defaults
PRIOR_MEDIAN_PARAMETERS: dict[str, float] = {
    "friction": DEFAULT_BIASED_PRIOR.friction,  # 0.5
    "restitution": DEFAULT_BIASED_PRIOR.restitution,  # 0.45
    "mass": DEFAULT_BIASED_PRIOR.mass,  # 2.6
    "linear_damping": DEFAULT_BIASED_PRIOR.linear_damping,  # 0.125
    "angular_damping": DEFAULT_BIASED_PRIOR.angular_damping,  # 0.125
}

# Jacobian / SVD Projection parameters (DESIGN_CORE §2 item 7)
JACOBIAN_REL_STEP: float = DEFAULT_REL_STEP  # 1e-3
SVD_REL_TOLERANCE: float = DEFAULT_SVD_REL_TOL  # 1e-6


# --- Metric Constants (PREREG_DRAFT.md §4) ---
EVAL_K_STEPS: tuple[int, ...] = DEFAULT_K_STEPS  # (1, 5, 10, 30)
EVAL_PRIMARY_K: int = PRIMARY_K  # 10
SURFACE_CONTACT_TOLERANCE_M: float = CONTACT_TOLERANCE_M  # 0.004 m
COLLISION_REL_VELOCITY_THRESHOLD_MPS: float = (
    COLLISION_VELOCITY_THRESHOLD_MPS  # 0.05 m/s
)
COLLISION_DEBOUNCE_FRAMES_COUNT: int = COLLISION_DEBOUNCE_FRAMES  # 3 frames
COLLISION_MATCH_TOLERANCE_FRAMES_COUNT: int = (
    COLLISION_MATCH_TOLERANCE_FRAMES  # +/- 1 frame
)
BALLISTIC_MIN_FRAMES_COUNT: int = BALLISTIC_MIN_FRAMES  # >= 5 frames

BOOTSTRAP_RESAMPLES_COUNT: int = BOOTSTRAP_RESAMPLES  # 10000
BOOTSTRAP_RNG_SEED: int = BOOTSTRAP_SEED  # 42
BOOTSTRAP_CONFIDENCE_LEVEL: float = BOOTSTRAP_CONFIDENCE  # 0.95


# --- Hypotheses & Primary Gate Thresholds (PREREG_DRAFT.md §1 & §5) ---
PRIMARY_GATE_NAME: str = "H-E1"
PRIMARY_ERROR_REDUCTION_MIN: float = 0.10  # >= 10% lower position error
COLLISION_F1_NON_DECREASING: bool = True  # collision F1 must not degrade
EXPLORATORY_HYPOTHESES: tuple[str, ...] = ("H-P", "H-S")
H_P_SIMILARITY_MAX_WIDTH_RATIO: float = 0.10  # CI contains 0 and width <= 10% of gap


# --- Registered Budget & Resource Caps (PREREG_DRAFT.md §6) ---
BUDGET_CAPS: dict[str, Any] = {
    "data_generation_max_seconds": 0.0,  # r2 reuses the r0 dataset; generate-data is refused
    "train_cell_compute_max_seconds": 300.0,  # 5 min computation (1200 * 0.25)
    "training_duty_cycle": 0.25,  # 25% compute duty cycle
    "train_cell_wall_max_seconds": 1200.0,  # per cell wall (including duty cycle)
    "train_cell_wall_by_arm": {"3": 500.0, "6": 1150.0},  # reserved per cell
    "train_cells_count": 12,  # 2 retrained arms * 2 families * 3 seeds
    "train_total_wall_max_seconds": 9900.0,  # 12 cells total <= 2.75 h
    "dev_eval_train_cell_max_seconds": 180.0,  # per train cell guardrail
    "dev_eval_nontrain_cell_max_seconds": 60.0,  # per non-train cell guardrail
    "dev_eval_cell_by_arm": {
        "1": 45.0,
        "2": 20.0,
        "3": 40.0,
        "4": 45.0,
        "5": 45.0,
        "6": 130.0,
        "7": 45.0,
    },  # reserved per cell
    "dev_eval_total_max_seconds": 1500.0,  # 26 cells total <= 25 min
    "final_eval_cell_max_seconds": 900.0,  # one read per family
    "final_eval_max_seconds": 1800.0,  # 2 families <= 30 min; needs its own approval line
    "phase_total_wall_ceiling_seconds": 13200.0,  # r2 only: train + dev + final
    "experiment_calendar_window_seconds": 259200.0,  # 72.0 h calendar window
}

RESOURCE_LIMITS: dict[str, float] = {
    "process_memory_gib": 8.0,
    "mlx_memory_gib": 4.0,
    "system_reserve_gib": 16.0,
    "swap_growth_gib": 1.0,
    "training_duty_cycle": 0.25,
    "disk_min_free_gib": 50.0,
}


# --- Implementation Source Tracking ---
IMPLEMENTATION_SOURCES: tuple[str, ...] = (
    "src/ainerzero/v9/experiments/e1/__init__.py",
    "src/ainerzero/v9/experiments/e1/analysis.py",
    "src/ainerzero/v9/experiments/e1/arms_net.py",
    "src/ainerzero/v9/experiments/e1/arms_nonnet.py",
    "src/ainerzero/v9/experiments/e1/commands.py",
    "src/ainerzero/v9/experiments/e1/contact_geometry.py",
    "src/ainerzero/v9/experiments/e1/data_runner.py",
    "src/ainerzero/v9/experiments/e1/eval_runner.py",
    "src/ainerzero/v9/experiments/e1/export.py",
    "src/ainerzero/v9/experiments/e1/identity.py",
    "src/ainerzero/v9/experiments/e1/jacobian.py",
    "src/ainerzero/v9/experiments/e1/metrics.py",
    "src/ainerzero/v9/experiments/e1/prereg.py",
    "src/ainerzero/v9/experiments/e1/prior.py",
    "src/ainerzero/v9/experiments/e1/spec.py",
    "src/ainerzero/v9/experiments/e1/train_runner.py",
    "src/ainerzero/v9/experiments/e1/worker.py",
)

# --- Generator Source Tracking & Velocity Injection ---
GENERATOR_SOURCES: tuple[str, ...] = (
    "python/animeworld/e0/_pure_hidden.py",
    "python/animeworld/e0/blender_runner.py",
    "python/animeworld/e0/blender_worker.py",
    "python/animeworld/e0/config.py",
    "python/animeworld/e0/dataset.py",
    "python/animeworld/e0/hidden_params.py",
    "python/animeworld/e0/scenarios.py",
    "python/animeworld/e0/verify.py",
)
REQUIRED_VELOCITY_INJECTION: str = "kinematic_preroll_2f_v1"


def canonical_json(data: Mapping[str, Any] | list[Any]) -> bytes:
    """Format dictionary or list into canonical deterministic JSON bytes."""
    payload = json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        indent=2,
        separators=(",", ": "),
    )
    return (payload + "\n").encode("utf-8")
