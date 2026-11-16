"""Frozen S2 multi-timescale experiment specification (ainerzero.V9.P124).

All numerical constants and architectural dimensions frozen for S2 Phase 1.
Every item is cited from reports/V9-S2-DESIGN/DESIGN-r2.md.

Citations:
- §1: Core question (H-S2)
- §2: World & Data (GridLab-S2 multi-room world)
- §3: Arms (parameter tolerance <= 10%, baseline E)
- §4: Planner & Forward Counter (N_fwd, s2, m, hyperparameter candidates)
- §5: Metrics & Gates (delta_pred, bootstrap, circuit breaker, ridge regression)
- §6: Budget envelope (10 h total actual wall clock, 72 h calendar window)
- §7: Stopping & incommensurability rules
- Appendix A: Arm architectures and parameter target (r2.2)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

# --- Spec & Experiment Identity (§1, §6, §8) ---
SPEC_NAME = "s2-phase1-v1"
TASK_ID = "ainerzero.V9.P124"
EXPERIMENT_ID = "s2-phase1-20261106-r0"
DESIGN_DOCUMENT_PATH = "reports/V9-S2-DESIGN/DESIGN-r2.md"

# Target parameter budget for all trainable arms (§3, Appendix A)
TARGET_PARAMETER_COUNT = 300_000
PARAMETER_TOLERANCE_FRACTION = 0.10  # +/- 10%
PARAM_COUNT_MIN = int(TARGET_PARAMETER_COUNT * (1.0 - PARAMETER_TOLERANCE_FRACTION))  # 270,000
PARAM_COUNT_MAX = int(TARGET_PARAMETER_COUNT * (1.0 + PARAMETER_TOLERANCE_FRACTION))  # 330,000

# --- World & Environment (§2) ---
# Grid layout: 25x25 grid, 3x3 rooms (~7x7 interior space per room)
WORLD_SIZE = 25
GRID_WIDTH = 25
GRID_HEIGHT = 25
ROOMS_X = 3
ROOMS_Y = 3
TOTAL_ROOMS = 9
ROOM_INTERIOR_SIZE = 7

# Field of View & Observation dimensions (§2, Appendix A)
FOV_SIZE = 7  # 7x7 view centered on agent
NUM_TERRAIN_CLASSES = 4  # FREE, WALL, PILLAR, UNSEEN
TERRAIN_ONE_HOT_DIM = FOV_SIZE * FOV_SIZE * NUM_TERRAIN_CLASSES  # 196
HEADING_DIM = 4  # one-hot heading
PREV_ACTION_DIM = 4  # one-hot previous action
DT_DIM = 1  # scalar dt
OBS_DIM = TERRAIN_ONE_HOT_DIM + HEADING_DIM + PREV_ACTION_DIM + DT_DIM  # 205

# Actions (§2)
NUM_ACTIONS = 4  # MOVE_FORWARD=0, TURN_LEFT=1, TURN_RIGHT=2, WAIT=3
ACTION_DIM = 4

# Irregular dt distribution (§2)
# k sampled from {1: 0.5, 2: 0.3, 3: 0.2}
K_DISTRIBUTION: Mapping[int, float] = {1: 0.5, 2: 0.3, 3: 0.2}

# Episode length & Segment rules (§2)
EPISODE_STEPS = 240
NON_BFS_RATIO_MIN = 0.5  # Non-BFS exploration segment fraction >= 50%
SEGMENT_LEN_MIN = 20
SEGMENT_LEN_MAX = 60
BFS_RANDOM_ACTION_PROB = 0.2
RANDOM_WALK_REPEAT_PROB = 0.7

# Goal definition & Distance thresholds (§2)
LONG_GOAL_MIN_STEPS = 40  # BFS shortest action steps >= 40
SHORT_GOAL_MAX_STEPS = 10  # BFS shortest action steps <= 10
ROOM_PILLARS_MIN = 0
ROOM_PILLARS_MAX = 3
MAX_REJECTION_RATE = 0.30  # Symmetry rejection rate threshold > 30% triggers redraw
MAX_REDRAW_RETRIES = 5  # Redraw attempts upper bound
DOORS_MIN = 1
DOORS_MAX = 2

# Evaluation protocols (§2, §5)
DEV_WORLDS_COUNT = 50
DEV_PAIRS_PER_WORLD = 6
DEV_LONG_GOAL_EPISODES = DEV_WORLDS_COUNT * DEV_PAIRS_PER_WORLD  # 300
FINAL_WORLDS_COUNT = 50
FINAL_PAIRS_PER_WORLD = 6
FINAL_LONG_GOAL_EPISODES = FINAL_WORLDS_COUNT * FINAL_PAIRS_PER_WORLD  # 300

# Episode budget factor L (§2)
# Episode budget: L = 3.0 * shortest action steps
EPISODE_L_FACTOR = 3.0

# Perturbation replanning evaluation (§2)
# In dev and final, 1/3 of long-goal episodes insert 5 random actions at step 20
PERTURB_FRACTION = 1.0 / 3.0
PERTURB_INSERT_STEP = 20
PERTURB_ACTION_COUNT = 5

# Regular dt evaluation subset (§5)
REGULAR_DT_SUBSET_EPISODES = 100

# Training seeds (§5, §6)
NUM_SEEDS = 3
TRAINING_SEEDS: tuple[int, ...] = (42, 43, 44)

# --- Planning (§4) ---
N_FWD = 4096
N_FWD_DEV_LEVELS: tuple[int, ...] = (2048, 4096, 8192)
S2_MACRO_STEPS = 8  # s2 = 8 observation steps
REPLAN_M_STEPS = 4  # replan after executing m = 4 observation steps

# Planning hyperparameter candidates (selected on train partition <= 50 episodes, §4)
FLAT_H_CANDIDATES: tuple[int, ...] = (16, 32, 48)
HIERARCHICAL_HORIZON_CANDIDATES: tuple[int, ...] = (4, 6, 8)
HIERARCHICAL_BUDGET_RATIO_CANDIDATES: tuple[float, ...] = (0.25, 0.5)
HYPERPARAM_SELECTION_MAX_EPISODES = 50

# --- Decision Gates & Metrics (§5) ---
# Primary hypothesis H-S2: success rate diff Arm C vs max(A, B) >= 0.10
SUCCESS_RATE_DIFF_MIN = 0.10
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_CONFIDENCE = 0.95

# Non-inferiority position prediction error threshold (§5)
# 30-step probe Euclidean position error bound delta_pred = 1.0 grid units
DELTA_PRED = 1.0

# Probe protocol (§5)
PROBE_RIDGE_LAMBDA = 1.0
PROBE_EVAL_STEPS: tuple[int, ...] = (1, 5, 10, 30, 60)

# Smoke pre-check circuit breaker (§5)
SMOKE_CIRCUIT_BREAKER_THRESHOLD = 0.05
BASELINE_SUCCESS_PLAUSIBLE_MIN = 0.1
BASELINE_SUCCESS_PLAUSIBLE_MAX = 0.8
BASELINE_SUCCESS_PLAUSIBLE_RANGE: tuple[float, float] = (
    BASELINE_SUCCESS_PLAUSIBLE_MIN,
    BASELINE_SUCCESS_PLAUSIBLE_MAX,
)

# --- Training & Architectures (Appendix A) ---
SHARED_E1_INPUT_DIM = 205
SHARED_E1_HIDDEN_DIM = 256
SHARED_E1_OUTPUT_DIM = 128
SHARED_E1_ACTIVATION = "GELU"

MACRO_ACTION_DIM = 7  # (dx, dy, dpsi, histogram 4)
MACRO_DT_DIM = 1

OPTIMIZER_NAME = "Adam"
LEARNING_RATE = 3e-4
BATCH_SIZE = 32
H_TRAIN = 16
SEQUENCE_LENGTH = H_TRAIN + 1  # 17

SIGREG_LAMBDA = 0.1
SIGREG_NUM_DIRECTIONS = 256
SIGREG_QUADRATURE_POINTS = 17

IDM_MU = 1.0
ARM_A_FREE_BITS = 1.0

# Training steps rule: steps = floor(1200 s * 0.8 / single_step_time)
TRAIN_STEP_TIME_BUDGET_SECONDS = 1200
TRAIN_STEP_EFFICIENCY_FACTOR = 0.8

# --- Budget Envelope (§6) ---
BUDGET_SMOKE_MAX_SECONDS = 1200  # 20 min
BUDGET_DATA_MAX_SECONDS = 3600  # 1 h
BUDGET_TRAIN_PER_SLOT_SECONDS = 1200  # 1200 s per slot
BUDGET_TRAIN_SLOTS_MAIN = 9  # A, B, C x 3 seeds = 9 slots (3 h)
BUDGET_TRAIN_MAIN_TOTAL_SECONDS = BUDGET_TRAIN_PER_SLOT_SECONDS * BUDGET_TRAIN_SLOTS_MAIN  # 10800 s (3 h)
BUDGET_ARM_D_SECONDS = 3600  # 1 h (3 slots, droppable)
BUDGET_BASELINE_E_SECONDS = 300  # 300 s (1 slot, droppable)
BUDGET_HYPERPARAM_SELECTION_SECONDS = 1800  # 30 min
BUDGET_DEV_EVAL_SECONDS = 9000  # 2.5 h
BUDGET_FINAL_EVAL_SECONDS = 5400  # 1.5 h

TOTAL_ACTUAL_WALLCLOCK_HOURS = 10.0  # 10 h
TOTAL_ACTUAL_WALLCLOCK_SECONDS = 36_000  # 10 * 3600
CALENDAR_WINDOW_HOURS = 72.0  # 72 h
CALENDAR_WINDOW_SECONDS = 259_200  # 72 * 3600

# --- Registered Arm Dimensions Table (Appendix A) ---
# Selected hidden dimensions ensuring all three arms fall within 300k +/- 10%
# Arm A: flat RSSM
# Arm B: flat JEPA (LeWM style)
# Arm C: hierarchical H-JEPA style
ARM_DIMS: dict[str, dict[str, Any]] = {
    "arm_a": {
        "name": "flat_rssm",
        "description": "flat RSSM with GRU deterministic state and Gaussian latent",
        "e1_input": SHARED_E1_INPUT_DIM,
        "e1_hidden": SHARED_E1_HIDDEN_DIM,
        "e1_output": SHARED_E1_OUTPUT_DIM,
        "latent_dim": 32,
        "gru_input": 37,  # [z_{t-1}(32), a(4), dt(1)]
        "gru_hidden": 160,  # narrowed from 196/256 to fit 300k budget
        "prior_hidden": 128,  # h -> 128 -> 64 (mean 32, std 32)
        "posterior_hidden": 128,  # [h, E1] -> 128 -> 64
        "decoder_hidden": 128,  # [h, z] -> 128 -> 205
    },
    "arm_b": {
        "name": "flat_jepa",
        "description": "flat JEPA with shared E1, residual predictor P1, and IDM",
        "e1_input": SHARED_E1_INPUT_DIM,
        "e1_hidden": SHARED_E1_HIDDEN_DIM,
        "e1_output": SHARED_E1_OUTPUT_DIM,
        "p1_input": 133,  # [z(128), a(4), dt(1)]
        "p1_hidden_1": 320,  # widened from 256 to fit 300k budget
        "p1_hidden_2": 320,  # widened from 256 to fit 300k budget
        "p1_output": 128,
        "idm_input": 256,  # [z_t(128), z_{t+1}(128)]
        "idm_hidden": 128,
        "idm_output": 4,
    },
    "arm_c": {
        "name": "hierarchical_hjepa",
        "description": "two-layer hierarchical H-JEPA; layer 1 + layer 2 macro dynamics",
        # Layer 1 (B structure with 256 width)
        "e1_input": SHARED_E1_INPUT_DIM,
        "e1_hidden": SHARED_E1_HIDDEN_DIM,
        "e1_output": SHARED_E1_OUTPUT_DIM,
        "p1_input": 133,
        "p1_hidden_1": 256,
        "p1_hidden_2": 256,
        "p1_output": 128,
        "idm_input": 256,
        "idm_hidden": 128,
        "idm_output": 4,
        # Layer 2 (macro dynamics across s2 steps)
        "e2_input": 128,
        "e2_hidden": 128,
        "z2_dim": 64,
        "p2_input": 72,  # [z2(64), macro_a(7), dt2(1)]
        "p2_hidden": 128,
        "p2_output": 64,
        "idm2_input": 128,  # [z2_t(64), z2_{t+s2}(64)]
        "idm2_hidden": 64,
        "idm2_output": 7,  # (dx, dy, dpsi, hist[4])
    },
}

# Smoke partition and short-training specifications (ainerzero.V9.P154)
SMOKE_N_WORLDS: int = 4
SMOKE_EPISODES_PER_WORLD: int = 4
SMOKE_LONG_GOAL_SPECS_COUNT: int = 12
SMOKE_SHORT_STEPS: int = 200

# --- 附录 C 冻结前补齐的登记参数（r2.4，2026-11-07）---
# 附录 C：train 分区与留出集
TRAIN_N_WORLDS = 1000
TRAIN_EPISODES_PER_WORLD = 8
TRAIN_HOLDOUT_WORLD_FRACTION = 0.10

# 附录 C：分区种子命名空间（互不重叠，由 validate 核验）
SEED_NAMESPACES = {
    "train": "s2p1-train-v1",
    "dev": "s2p1-dev-v1",
    "final": "s2p1-final-v1",
    "smoke": "s2p1-smoke-v1",
}

# 附录 C：模型选择与 smoke 短训步数
MODEL_SELECTION_EVERY_STEPS = 200
SMOKE_SHORT_TRAIN_STEPS = 200

# 附录 C：训练步数规则（具体步数由 smoke 实测后记账，不入预登记）
TRAIN_STEPS_RULE = "floor(1200*0.8/t_min_over_arms)"

# 附录 C：数据生成耗时估算系数（来源：P133 实测 0.145 s/回合）
DATA_ESTIMATED_SECONDS_PER_EPISODE = 0.145



# --- 附录 D3.1：CEM 参数由 N_fwd 推出的登记规则（r2.5，2026-11-07）---
CEM_N_ITERS = 4
CEM_ELITE_FRAC = 0.1
CEM_ENCODE_RESERVE = 8  # 每决策为 encode/E2 预留的计数
CEM_MIN_POP = 2
# smoke 计时与 oracle 熔断使用候选网格中位
SMOKE_PLAN_CHOICE = {
    "flat": {"H": 32},
    "hierarchical": {"macro_horizon": 6, "budget_ratio": 0.5},
}
# 上层 CEM 在 [-1, 1]^7 上搜索；还原尺度：dx, dy 乘 s2 * max(k)，dpsi 乘 pi，
# 直方图分量取 (u + 1) / 2 后归一化
MACRO_DXY_SCALE = float(S2_MACRO_STEPS * max(K_DISTRIBUTION))
# 目标观察的特征化约定（与回合起点一致）：last_action = WAIT(3)，dt = 1
GOAL_FEATURE_LAST_ACTION = 3
GOAL_FEATURE_DT = 1

# --- 附录 E 规划协议可行性修正（r2.6，2026-11-07）---
PLAN_REPLAN_EVERY_OBS_STEPS: int = 1
PLAN_FUTURE_DT_L1: int = 1
PLAN_FUTURE_DT_L2: int = 14  # round(S2_MACRO_STEPS * 1.7) = round(13.6) = 14
PLAN_COST_TRAJECTORY_SUM: str = "trajectory_sum"
PLAN_COST_TERMINAL: str = "terminal"

# --- 附录 D5.1：§5 探针评估与拟合参数（W6）---
PROBE_FIT_SAMPLES: int = 2000
PROBE_FIT_STEPS: int = 2000
PROBE_SEED_NAMESPACE: str = "s2p1-train-v1|probe"
PROBE_START_POINTS: tuple[int, ...] = (0, 60, 120)
PROBE_HORIZON_MAX: int = 60

# --- W6b：§5 第 2 道门的探针步数 ---
PROBE_GATE_STEP: int = 30

# --- 附录 B / §7：训练后门与 dev 次数的登记阈值（原只写在 eval_runner 字面量中，2026-11-07 收入 spec）---
ACTION_SENSITIVITY_FLOOR: float = 0.05
SUBGOAL_DROP_FLOOR: float = 0.10
MAX_DEV_EVALS: int = 2

# --- 统一训练批次格式规范（W8，2026-11-07）---
# 训练批次统一字典接口：
# - observations: (B, L, OBS_DIM) float32
# - actions: (B, L, ACTION_DIM) one-hot float32，表示第 t 步采取的动作
# - dts: (B, L) float32，表示第 t 步的 k
# - L = H_TRAIN + 1 = 17
# 语义：obs_t 经动作 a_t 和步长 dt_t，到达 obs_{t+1}
# 观察特征一律用 train_runner.flatten_student_obs，dt 槽位取该步的 k，与 learned_planning.featurize_obs 口径一致
BATCH_OBSERVATIONS_KEY: str = "observations"
BATCH_ACTIONS_KEY: str = "actions"
BATCH_DTS_KEY: str = "dts"
BATCH_REQUIRED_KEYS: tuple[str, ...] = (
    BATCH_OBSERVATIONS_KEY,
    BATCH_ACTIONS_KEY,
    BATCH_DTS_KEY,
)


# --- 用户 11-08 批准 S2 预算到 15 h（RESEARCH_LOG R20261108-S2-budget-15h）；覆盖上方原 10 h 分项 ---
# 依据 smoke 预演实测的最坏情况推算：总 53,844 s（dev 34,826 s、final 8,358 s），dev 只用一次
TOTAL_ACTUAL_WALLCLOCK_HOURS = 15.0
TOTAL_ACTUAL_WALLCLOCK_SECONDS = 54_000
BUDGET_HYPERPARAM_SELECTION_SECONDS = 2_400  # plan-select + 训练后门
BUDGET_DEV_EVAL_SECONDS = 36_000  # 10 h，一次 dev
BUDGET_FINAL_EVAL_SECONDS = 9_000  # 2.5 h

# --- W10（11-08）：规划期推理设备。GPU 上每个 predict 调用只算 15–63 行就要同步一次，以延迟为主；
# 改走 MLX CPU 流后三臂规划回合耗时约减半（实测见 reports/V9-S2-W10）。训练仍走默认 GPU。---
PLAN_INFERENCE_DEVICE: str = "cpu"

# --- 用户 11-08 批准（RESEARCH_LOG R20261108-S2-redraw-30）：世界重抽上限 5→30；拒绝门槛 MAX_REJECTION_RATE 0.30 不变。
# 登记种子下 train/dev/final 最多需要 20/17/10 次（R20261108-S2-data-r2-failed 全量模拟）。---
MAX_REDRAW_RETRIES = 30
