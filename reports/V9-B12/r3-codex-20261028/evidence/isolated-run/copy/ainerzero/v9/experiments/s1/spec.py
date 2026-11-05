"""Frozen S1 phase-1 constants (ainerzero.V9.P9).

Everything in this module is part of the preregistration payload: the arm
structures, the registered caps (RESEARCH_LOG R20261021-P1-stageA-budget), the
resource protection lines, the timing rule and the stop rules.  Changing a value
here changes the frozen preregistration SHA256, which is why the freeze command
records the source digest of this file next to the document.

Sources:
- budget/preregistration: ``RESEARCH_LOG.md`` R20261021-P1-stageA-budget
  (train <= 2,000 worlds, <= 4 rounds/world, development <= 200 worlds;
  process <= 8 GiB, MLX <= 4 GiB, 16 GiB system reserve, duty 0.25,
  swap growth <= 1 GiB; per-run wall <= 20 min, phase wall <= 4 h;
  deadline = measured estimate x 1.25, supervision = deadline + 50 s).
- arms: ``ARCHITECTURE_V9.md`` §5 S1 and §1.1 (maps as memory, equivariant
  metric layer, episodic topology layer, 0.1M-2M student parameters).
- data: awz.V9.B3 r2 arena generator (incl. awz.V9.B19) and awz.V9.B1 r3
  restricted exit conventions; the final partition is never generated or read.
- arm (1) identity: ainerzero.V9.A2 frozen baseline manifest r3.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SPEC_NAME = "s1-phase1-v1"
TASK_ID = "ainerzero.V9.P9"
EXPERIMENT_ID = "s1-phase1-20261021"

# --- registered host anchor (S1-R7-DECISION) -----------------------------
# The formal ledger, RunStore, shared m0-worker lock and approval log are anchored
# to the authoritative registered host installation.  Resolving relative to
# __file__ in an executing checkout is forbidden because it allows foreign
# checkouts to reset attempts and spawn fresh unanchored ledgers.
REGISTERED_HOST_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
REGISTERED_HOST_PHASE1 = REGISTERED_HOST_ROOT / "artifacts" / "v9" / "s1" / "phase1"
REGISTERED_HOST_LEDGER = REGISTERED_HOST_PHASE1 / "control.sqlite3"
REGISTERED_HOST_APPROVAL = REGISTERED_HOST_ROOT / "RESEARCH_LOG.md"
REGISTERED_HOST_LOCK = REGISTERED_HOST_ROOT / "artifacts" / "locks" / "m0-worker.lock"

# One controlled resolver for the whole anchor.  Every bounded decision (run
# root, central RunStore, approval log, shared m0-worker lock) must be derived
# from this single dict: mixing a caller-supplied root with a global default is
# how a checkout can end up reading one ledger while locking another.
HOST_ANCHOR_SCHEMA = "ainerzero.v9.s1.host_anchor.v1"


def host_anchor_state(root: Path | str | None = None) -> dict:
    """Read-only identity state of the registered host anchor (fail closed).

    ``root`` exists for tests and for an explicit, *declared* alternative host;
    it is never populated from ``__file__``, the cwd, an environment variable or
    an unregistered CLI flag.  A missing root, a missing phase-1 directory or a
    missing/unreadable approval log is ``status != "ok"`` and every bounded path
    refuses instead of creating a fresh ledger next to a foreign checkout.
    """
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
    phase1 = anchor_root / "artifacts" / "v9" / "s1" / "phase1"
    state = {
        "schema": HOST_ANCHOR_SCHEMA,
        "status": "ok",
        "root": str(anchor_root),
        "phase1_root": str(phase1),
        "ledger": str(phase1 / "control.sqlite3"),
        "approval_log": str(anchor_root / "RESEARCH_LOG.md"),
        "lock": str(anchor_root / "artifacts" / "locks" / "m0-worker.lock"),
        "registered": root is None,
    }
    if not anchor_root.is_dir():
        state.update({"status": "missing_root", "reason": "host root is not a directory"})
        return state
    if not phase1.is_dir():
        state.update(
            {"status": "missing_phase1", "reason": "no phase-1 directory under the host root"}
        )
        return state
    approval = Path(state["approval_log"])
    if not approval.is_file():
        state.update({"status": "missing_approval", "reason": "no approval log at the anchor"})
        return state
    try:
        with open(approval, "rb") as handle:
            handle.read(1)
    except OSError as exc:
        state.update(
            {
                "status": "unreadable_approval",
                "reason": f"{type(exc).__name__}: {exc}",
            }
        )
    return state


def host_anchor(root: Path | str | None = None) -> dict:
    """The anchor dict for a bounded run, or ``RuntimeError`` when not anchored."""
    state = host_anchor_state(root)
    if state["status"] != "ok":
        raise RuntimeError(
            f"registered host anchor is {state['status']}: {state.get('reason', '')}"
        )
    return state

REPO_ROOT = REGISTERED_HOST_ROOT
AWZ_ROOT = Path("/Users/mac/AinerWorkFlow/AnimeWorldZero")
AWZ_PYTHON = AWZ_ROOT / ".venv" / "bin" / "python"
AWZ_PYTHONPATH = f"{AWZ_ROOT / 'python'}:/Users/mac/AinerWorkFlow/AinerForge"

# --- storage layout (level-1 notice #297) ---------------------------------
# The formal ledger and every byte of data live under artifacts/; reports/ only
# carries manifests and their SHA256.  Notice #297 (2026-10-21) fixes this split
# after r1 wrote the dataset and the RunStore into reports/V9-P9/.
ARTIFACTS_V9 = REPO_ROOT / "artifacts" / "v9"
PHASE1_ROOT = REGISTERED_HOST_PHASE1
DATASETS_DIR = ARTIFACTS_V9 / "s1" / "datasets"
REPORTS_DIR = REPO_ROOT / "reports" / "V9-P9"
# The coordinator's approval line for S1 phase 1 lives in this log and nowhere
# else; the preregistration status field is not an approval (V9.P10 F1).
RESEARCH_LOG = REGISTERED_HOST_APPROVAL

# --- registered caps -------------------------------------------------------
DATA_CAPS = {
    "train_worlds_max": 2_000,
    "rounds_per_world_max": 4,
    "development_worlds_max": 200,
}

# --- resource protection lines (RESEARCH_LOG R20261021-P1-stageA-budget) ---
RESOURCE_LIMITS = {
    "process_memory_gib": 8.0,
    "mlx_memory_gib": 4.0,
    "system_reserve_gib": 16.0,
    "swap_growth_gib": 1.0,
    "training_duty_cycle": 0.25,
    "disk_min_free_gib": 50.0,
}
RESOURCE_LIMIT_SOURCES = {
    "process_memory_gib": "pilot resource profile / registered run protection",
    "mlx_memory_gib": "pilot resource profile / registered run protection",
    "system_reserve_gib": "system reserve line (R20261021-P1-stageA-budget)",
    "swap_growth_gib": "same-boot swap growth line (registered)",
    "training_duty_cycle": "registered duty cycle for S1 phase 1",
    "disk_min_free_gib": "pilot storage protection",
}

# --- timing rule (frozen; the CLI cannot loosen any of it) -----------------
# r11 (RESEARCH_LOG R20261023-S1-phase1-r11-budget, user-approved option A):
# ``eval_batches`` covers the measured window-probe volume -- 5 frozen
# checkpoints x 35 development batches (550 windows / batch 16) = 175.  r10
# registered 48 and the eval entry therefore refused every trainable arm.
TIMING = {
    "deadline_factor": 1.25,
    "supervision_extra_seconds": 50.0,
    "per_run_wall_max_seconds": 1_200.0,
    "phase_wall_max_seconds": 14_400.0,
    "update_cost_factor": 3.0,  # forward+loss -> forward+backward+update estimate
    "smoke_steps": 3,
    "smoke_repeats": 5,
    "smoke_batch_size": 16,
    "eval_batches": 175,
    "eval_checkpoint_fractions": (0.0, 0.125, 0.25, 0.5, 1.0),
    "estimate_eval_overhead_factor": 1.20,
    "data_generation_budget_seconds": 300.0,
    "trainable_runs": 9,  # arms 2/3/4 x seeds 0/1/2
    "d_candidate_eval_runs": 1,
}

# --- r11 registered budget (RESEARCH_LOG R20261023-S1-phase1-r11-budget) ---
# The r10 phase run failed: all 9 trainings stopped at the 450 s deadline after
# 1591-2676 of 3510 updates, and the arm2/3/4 evals were refused because the
# registered eval_batches=48 cannot cover the 175-batch window probe.  The user
# approved option A verbatim: keep 3510 updates, register the single-run
# deadline as 1200 s (inside the registered per-run cap) instead of deriving it
# as ceil(1.25 x estimate), and raise eval_batches to 175.
#
# Why the deadline is a registered value and not a derived one: substituting the
# slowest measured P1 throughput (~0.283 s/step, below) into the derivation rule
# gives ceil(1.25 x 3510 x 0.283) = 1242 s > the 1200 s per-run cap, and the
# frozen code would then shrink the update count to ~3159 -- exactly what the
# user's "keep 3510 steps" forbids.  The registration below is therefore
# fail-closed in ``prereg.registered_budget``: a value that is not 1200, or an
# update count the shrink loop would have cut, is refused instead of frozen.
R11_EXPERIMENT_ID = "s1-phase1-20261023-r11"
R11_BUDGET_REGISTRATION = "RESEARCH_LOG R20261023-S1-phase1-r11-budget"
R11_DEADLINE_SOURCE = "user_approved R20261023-S1-phase1-r11-budget"
R11_REGISTERED_UPDATES = 3_510
R11_REGISTERED_DEADLINE_SECONDS = 1_200
# supervision stays deadline + 50 s = 1250 s (registered structure unchanged);
# it is only the hard-kill backstop, the training loop still stops in-process
# at the 1200 s deadline.
R11_SUPERVISION_SECONDS = (
    R11_REGISTERED_DEADLINE_SECONDS + TIMING["supervision_extra_seconds"]
)

# P1 measured throughput, derived from the 9 r10 training rows of
# reports/V9-S1/metrics.json (steps = 3510 - remaining_optimizer_steps,
# per-step = wall_seconds / steps): median 0.20182 s/step, slowest 0.2829
# s/step (arm4-seed2, 1591 steps in 450.097 s).  3510 steps at the slowest
# throughput need ~993 s, i.e. the registered 1200 s deadline carries ~21%
# headroom (1200 / 992.98 = 1.2085).  Recorded in the frozen r11 document so
# the registration is auditable against its measurement.
R11_MEASURED_THROUGHPUT_SOURCE = "reports/V9-S1/metrics.json"
R11_MEASURED_THROUGHPUT_SOURCE_SHA256 = (
    "8b5017c24fb710a3bf55508a8ac917d17cb41e29ba464c32b092e37b14db6ce4"
)
R11_MEASURED_THROUGHPUT = {
    "source": R11_MEASURED_THROUGHPUT_SOURCE,
    "source_sha256": R11_MEASURED_THROUGHPUT_SOURCE_SHA256,
    "per_step_seconds": {"median": 0.20182, "slowest": 0.2829},
    "derivation": "per-step = wall_seconds / (3510 - remaining_optimizer_steps) "
    "over the 9 r10 training rows of the source file",
    "steps": R11_REGISTERED_UPDATES,
    "slowest_wall_seconds": 992.98,
    "registered_deadline_seconds": R11_REGISTERED_DEADLINE_SECONDS,
    "deadline_over_slowest_ratio": 1.2085,
    "note": "3510 steps at the slowest measured throughput need about 993 s; "
    "the registered 1200 s deadline carries about 21% headroom",
}

# --- r12 re-freeze (ainerzero.V9.P34, P31-LEDGER-INCIDENT-RULING) ----------
# The r11 identity was consumed by an incident: during the P31 review a real CLI
# eval ran against the production output root and started the r11 4-hour
# experiment window at 2026-10-23 16:32:18.  The ruling keeps every r11 row as
# the incident record and re-freezes the *same* registration under a new
# identity, so the phase-1 attempt guards, the phase wall clock and the D guard
# start from zero again.  The r11 constants above stay as history; r12 is the
# identity that was run.
R12_EXPERIMENT_ID = "s1-phase1-20261023-r12"

# --- r13 re-freeze (ainerzero.V9.P38, R20261024-S1-phase1-r13-budget) ------
# S1 r12 phase was incomplete due to two host sleep events (3/9 completed, 2 failed,
# evals unrun, phase window closed). User approved r13 with identical values.
R13_EXPERIMENT_ID = "s1-phase1-20261024-r13"

# All three identities carry the one user-approved registration:
# r11 was frozen first, r12 repeated the same scientific values after P31,
# and r13 repeats them after the r12 phase window expired. Anything else is refused.
REGISTERED_EXPERIMENT_IDS = (R11_EXPERIMENT_ID, R12_EXPERIMENT_ID, R13_EXPERIMENT_ID)
# The identity a new freeze produces; r11 and r12 stay readable as archived history.
CURRENT_EXPERIMENT_ID = R13_EXPERIMENT_ID

# --- data plan (worlds/rounds frozen after the measured generation run) ----
DATA_PLAN = {
    "generator": "awz.V9.B3 r2 (including awz.V9.B19 staging fix)",
    "generator_commit": "2b0d4f2834298c18b237f7611451d1ec7625bf36",
    "generator_root": str(AWZ_ROOT),
    "restricted_exit": "awz.V9.B1 r3 conventions (HandleAllocator + CounterNoise + A3 validator)",
    "generator_seed": "awz-v9-b3-v0",
    "partition_namespace": {"train": 1, "development": 2, "final": 3},
    "families": ("navigation", "time", "relation", "e3_identity"),
    "scene_id_format": "s1-{partition}-{family}-{index:05d}",
    "train": {"worlds": 2_000, "rounds_per_world": 1},
    "development": {"worlds": 200, "rounds_per_world": 1},
    "final": "not_generated_not_read",
    "sample_interval": 12,
    "range_m": 6.5,
    "fov_deg": 90.0,
}

# --- observation encoding --------------------------------------------------
OBSERVATION = {
    "detection_slots": 6,
    "appearance_classes": (
        "prop/chair",
        "prop/lamp",
        "prop/table",
        "prop/door",
        "character/person",
        "other",
    ),
    "feature_dim": 72,
    "target_dim": 60,
    "slot_ordering": "detection slots sorted by (x, z, class index) in the agent frame",
    "target_layout": "next observation, per slot: x,y,z,present,class(6 one-hot)",
    "position_frame": "agent-local (right, up, forward) metres; x/z comparable, y=0",
    "time_fields": ("sim_hz", "t_ticks", "dt_ticks", "dt_s"),
}

# --- arm definitions (must stay within 0.1M-2M trainable parameters) ------
ARM_SPECS = {
    "arm1": {
        "arm_id": "arm1",
        "name": "D candidate re-verification (evaluate only)",
        "kind": "frozen_candidate",
        "architecture": "pilot_shared_symbol_v1",
        "training_updates": 0,
        "seeds": (),
        "identity": {
            "frozen_manifest": str(REPO_ROOT / "reports" / "V9-baseline" / "r3" / "baseline_manifest.json"),
            # r8 (S1-R8-DECISION F6): the manifest *bytes* are pinned as well as
            # its self digest, so a swapped manifest is refused before load.  The
            # value is the verified bytes of the A2 r3 deliverable; the manifest
            # itself and its original digest algorithm are unchanged.
            "frozen_manifest_file_sha256": "2c991f052f322112fa97c57f52585bd99779c3178b21108efdc494596184be5b",
            "frozen_manifest_digest": "3481b6ad70991478c658fa2de87d5621208fe69fc50369705cbaaa7492eb45e9",
            "frozen_manifest_digest_rule": "sha256(canonical_json(manifest minus generated_at, "
            "manifest_digest, policy_check)) -- original A2 r3 builder algorithm",
            "pilot_dir": "artifacts/pilot/pilot-b4e75e9b4a1a4ba086118d37017b2a1a",
            "checkpoint_id": "96b72328-d9c1-4b48-b69c-1fa30ba8123c",
            "experiment_id": "m2md-distill-20261013-r2",
            "tensors_sha256": "cbb14d878dfda5af816dbc4903c7fb811aabbcfb17ce494f00e994ab3d6b286a",
            "manifest_sha256": "76403018a033317c1cf4422f60318ee9a9df99d8b9e75c4c3211e444d4ba3892",
            "metadata_sha256": "0de030a55af2f9f6d5cca6a1d0c0b5f15eac1281a9ead3bffdadda5a0f8bf58a",
            "load_mode": "MLX CPU inference only; tensors.safetensors verified against the A2 manifest entry before load",
        },
        "incomparable": (
            "C0 8-cell symbol observations only; the S1 arena payloads (relative_objects/"
            "ego_motion) are not its registered input",
            "no metric map, no episodic topology memory, no pose estimate head",
            "S1 metrics are reported as not_applicable; its own C0 M2 diagnostics are the"
            " only comparable row and are flagged incomparable",
        ),
    },
    "arm2": {
        "arm_id": "arm2",
        "name": "equivariant metric map memory",
        "kind": "trainable",
        "architecture": "s1_equivariant_metric_map_v1",
        "dims": {"hidden": 224, "memory_channels": 32, "grid": 8, "extent_m": 6.5, "decay": 0.9},
        "training_updates": None,  # frozen by the smoke-based rule in prereg.freeze
        "seeds": (0, 1, 2),
        "incomparable": (),
    },
    "arm3": {
        "arm_id": "arm3",
        "name": "episodic topology graph",
        "kind": "trainable",
        "architecture": "s1_episodic_topology_graph_v1",
        "dims": {"hidden": 192, "place_dim": 32, "max_nodes": 32, "match_threshold": 0.9},
        "training_updates": None,
        "seeds": (0, 1, 2),
        "incomparable": (),
    },
    "arm4": {
        "arm_id": "arm4",
        "name": "equivariant metric map + episodic topology graph",
        "kind": "trainable",
        "architecture": "s1_metric_plus_topology_v1",
        "dims": {
            "hidden": 256,
            "memory_channels": 24,
            "grid": 8,
            "extent_m": 6.5,
            "decay": 0.9,
            "place_dim": 24,
            "max_nodes": 32,
            "match_threshold": 0.9,
        },
        "training_updates": None,
        "seeds": (0, 1, 2),
        "incomparable": (),
    },
}

# --- single frozen training protocol shared by arms 2/3/4 ------------------
TRAIN_COMMON = {
    "objective": "one-step observation prediction (self-supervised) + geometric pose consistency",
    "optimizer": "adamw",
    "learning_rate": 3.0e-4,
    "adam_betas": (0.9, 0.999),
    "adam_epsilon": 1.0e-8,
    "weight_decay": 0.01,
    "gradient_clip_norm": 1.0,
    "batch_size": 16,
    "sequence_steps": 2,
    "burn_in_steps": 1,
    "updates_min": 100,
    "updates_cap": 5_000,
    "target_estimate_seconds": 360.0,
    "eval_batches": TIMING["eval_batches"],
    "checkpoint_fractions": TIMING["eval_checkpoint_fractions"],
    "seeds": (0, 1, 2),
    "duty_cycle": RESOURCE_LIMITS["training_duty_cycle"],
    "data_seed_namespace": "S1_PHASE1_TRAIN_V1",
}

# --- evaluation registration (P26 / option A; not a new metric id) --------
# ``query_limit`` was previously a code-only default in ``metrics.split_support_query``.
# Option A (P1-READINESS) registers it in the preregistration and fail-closes when
# the key is missing or differs from this frozen value.  ``reporting_notes`` record
# k=8 / per-family / coverage facts without changing ``metrics[3]``.
EVALUATION = {
    "query_limit": 8,
    "reporting_notes": [
        "k=8 is always marked insufficient_data (0/200 worlds have samples); never record as 0 or a perfect score",
        "k curves are reported per family and never pooled",
        "coverage facts (k=8: 0/200; k=4: 50/200 and navigation family only) are reporting notes only; coverage/FPR are not phase-1 metrics",
    ],
}

# --- metric definitions (frozen; compute scripts live in metrics.py) ------
METRIC_DEFINITIONS = (
    {
        "id": "localization_error",
        "unit": "m / deg (translation, yaw)",
        "frame": "task frame",
        "direction": "lower_is_better",
        "definition": "per-step agent pose estimate error against evaluator truth pose; "
        "mean and median translation error (m) and yaw error (deg); loop-closure "
        "segment reported separately",
    },
    {
        "id": "unseen_map_generalization",
        "unit": "m / nats",
        "frame": "task frame / agent frame",
        "direction": "lower_is_better",
        "definition": "localization error and next-observation NLL on development worlds "
        "(never seen in training); final partition is read-once only after all training "
        "and is out of scope for this card",
    },
    {
        "id": "topology_recovery",
        "unit": "precision / recall",
        "frame": "world occupancy graph (evaluator truth)",
        "direction": "higher_is_better",
        "definition": "edge precision/recall of the arm's place graph against the true "
        "free-space adjacency graph restricted to visited cells; reported for confounded "
        "observations (shared appearance classes, handle reissue after occlusion)",
    },
    {
        "id": "few_shot_unseen_transition",
        "unit": "accuracy / m",
        "frame": "world occupancy graph (evaluator truth)",
        "direction": "higher_is_better",
        "definition": "write k in {0,1,2,4,8} support transitions of a development world "
        "into memory without parameter updates, then predict held-out transitions "
        "(edge existence and destination displacement); accuracy and displacement error "
        "vs k",
    },
    {
        "id": "sample_efficiency",
        "unit": "curve (metric vs updates)",
        "frame": "development worlds",
        "direction": "lower_is_better",
        "definition": "development localization error and next-observation NLL at the "
        "frozen update checkpoints; one curve per arm x seed",
    },
    {
        "id": "m2_memory_interference",
        "unit": "delta NLL / delta localization error",
        "frame": "development worlds",
        "direction": "lower_is_better",
        "definition": "zero-state vs history-paired probe and retention delta after "
        "writing a new world's memories without parameter updates; report with the "
        "D candidate row, incomparable items flagged",
    },
)

# --- stop rules ------------------------------------------------------------
STOP_RULES = (
    "non-finite loss, gradient or parameter aborts this run as failed",
    "exceeding the frozen per-run deadline aborts this run as failed",
    "exceeding the process memory line (8 GiB, RSS) aborts this run as failed",
    "exceeding the MLX memory line (4 GiB) aborts this run as failed",
    "exceeding the 16 GiB system reserve line aborts and marks the run failed",
    "same-boot swap growth above 1 GiB aborts this run as failed",
    "no rerun and no borrowing across seeds; a failed run stays failed",
    "any run outside the frozen preregistration needs a new coordinator registration",
)

# --- file/self identity ----------------------------------------------------
SELF_PATH = Path(__file__).resolve()


def canonical_json(payload: object) -> bytes:
    """Canonical UTF-8 JSON used for every digest in this package."""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def spec_source_digest() -> dict:
    """Source identity of the spec module itself (recorded in the prereg)."""
    return {
        "path": "src/ainerzero/v9/experiments/s1/spec.py",
        "sha256": sha256_file(SELF_PATH),
    }
