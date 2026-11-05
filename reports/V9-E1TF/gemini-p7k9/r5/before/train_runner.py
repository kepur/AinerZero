"""E1 Phase 2 Training Runner (Pure CPU / MLX).

Specification:
1. build_training_windows(student_dir, K=4):
   - Extracts (recent K frames -> next frame delta) samples from student-side sequences.
   - Strictly reads only student-side fields (position, linear_velocity).
2. train_cell(arm_id, family, seed, student_dir, out_dir, *, ...):
   - Constructs trainable arms ②, ③, and ⑥.
   - Arm ⑥ uses arms_nonnet.IdentifyArm to identify physical parameters phi on prefix.
   - Iteratively calls model.train_step(batch).
   - Enforces compute budget and deadline checks after each step (stops with status='stopped').
   - Duty cycle pacing: sleeps (1/duty_cycle - 1) * compute_time (3x for duty_cycle=0.25).
   - On completion, writes actual model weights via save(), computing file and parameter SHA256.
   - Does NOT write weights if stopped due to budget or deadline.
3. Strict validation:
   - Only trainable arms (2, 3, 6) admitted.
   - Only registered seeds (42, 43, 44) admitted.
   - No hardcoded metrics, no fake checkpoints.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import mlx.core as mx
import numpy as np

from . import arms_net, spec
from .arms_net import (
    DEFAULT_INPUT_DIM,
    DEFAULT_OUTPUT_DIM,
    HISTORY_K,
    IdentificationFn,
    IdentifyResidualArm,
    PriorResidualArm,
    PureNetArm,
)
from .arms_nonnet import IdentifyArm
from .eval_runner import build_static_environment_from_student
from .prior import DEFAULT_BIASED_PRIOR, PhysicalParameters, StaticEnvironment

# Ensure default MLX execution device is strictly CPU
mx.set_default_device(mx.cpu)


def make_arm6_identifier() -> IdentificationFn:
    """Create parameter identification callback for Arm ⑥ using Arm ⑤ IdentifyArm."""
    arm5 = IdentifyArm()

    def identifier(
        prefix_data: Any,
        env: StaticEnvironment,
        radii_by_body: Mapping[str, float] | None = None,
    ) -> PhysicalParameters:
        static_env = env if env is not None else StaticEnvironment(ground=None)
        if isinstance(prefix_data, dict):
            if radii_by_body is None:
                raise KeyError("radii_by_body is required for parameter identification")
            params_dict, _, _ = arm5.identify(prefix_data, static_env, radii_by_body=radii_by_body)
            if params_dict:
                return next(iter(params_dict.values()))
            return DEFAULT_BIASED_PRIOR.copy()

        # Array input path:
        if radii_by_body is None:
            raise KeyError("radii_by_body is required for array input identification; none provided")

        if "body_0" not in radii_by_body or radii_by_body["body_0"] is None:
            raise KeyError(
                f"Missing radius for body_0 in radii_by_body: available keys {list(radii_by_body.keys())}"
            )
        rad = float(radii_by_body["body_0"])

        arr = np.asarray(prefix_data, dtype=np.float64)
        p_hat, _, _ = arm5.identify_body("body_0", arr, static_env, radius=rad)
        return p_hat

    return identifier


class TrainingWindows(dict):
    """Container for extracted windowed training samples from student sequences."""

    def __init__(
        self,
        inputs: np.ndarray,
        targets: np.ndarray,
        samples: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(inputs=inputs, targets=targets)
        self.inputs = inputs
        self.targets = targets
        self.samples = samples or []

    def __len__(self) -> int:
        return len(self.inputs)


def build_training_windows(
    student_dir: Path | str,
    K: int = HISTORY_K,
    *,
    model: Any | None = None,
    arm: Any | None = None,
) -> TrainingWindows:
    """Construct (recent K frames -> next frame target) samples from student sequences.

    When model/arm is provided, targets are constructed via model.training_target(...)
    guaranteeing mathematical consistency with each arm's predict() formulation:
        ② PureNetArm: y = s_{t+1} - s_t
        ③ PriorResidualArm: y = s_{t+1} - F_prior(s_t; phi_0)
        ⑥ IdentifyResidualArm: y = P_perp(phi_hat) * (s_{t+1} - F_prior(s_t; phi_hat))

    For Arm ⑥, physical parameter identification is cached per episode (run only once per episode).
    """
    student_path = Path(student_dir)
    if not student_path.exists():
        raise FileNotFoundError(f"Student directory does not exist: {student_dir}")

    arm_model = model if model is not None else arm

    # Discover sequence JSONs
    if student_path.is_file() and student_path.suffix == ".json":
        json_files = [student_path]
    else:
        json_files = sorted(list(student_path.glob("*.json")))
        if not json_files:
            json_files = sorted(list(student_path.rglob("*.json")))

    if not json_files:
        raise ValueError(f"No student sequence JSON files found in {student_dir}")

    x_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []
    samples_info: list[dict[str, Any]] = []

    # Episode-level cache for Arm 6 parameter identification: (sequence_id, body_name) -> phi_hat
    episode_phi_cache: dict[tuple[str, str], PhysicalParameters] = {}

    for path in json_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        frames = data.get("frames", [])
        if len(frames) <= K:
            continue

        seq_id = str(data.get("sequence_id", path.stem))
        static_geo = data.get("static_environment")
        env = build_static_environment_from_student(static_geo)

        # Extract active bodies and actual bounding radii
        active_bodies = data.get("active_bodies", {})
        first_objs = frames[0].get("objects", {})
        body_names = sorted(list(active_bodies.keys())) if active_bodies else sorted(list(first_objs.keys()))

        radii_by_body: dict[str, float] = {}
        for b_name in body_names:
            if (
                b_name in active_bodies
                and "bounding_sphere_radius" in active_bodies[b_name]
                and active_bodies[b_name]["bounding_sphere_radius"] is not None
            ):
                radii_by_body[b_name] = float(active_bodies[b_name]["bounding_sphere_radius"])
            else:
                raise KeyError(
                    f"Missing bounding_sphere_radius for body '{b_name}' in sequence '{seq_id}' "
                    f"(active_bodies keys: {list(active_bodies.keys())})"
                )

        # Extract trajectory for each body across frames
        states_by_body: dict[str, np.ndarray] = {}
        for b_name in body_names:
            states: list[np.ndarray] = []
            for fr in frames:
                objs = fr.get("objects", {})
                if b_name not in objs:
                    continue
                o = objs[b_name]
                p = o.get("position", [0.0, 0.0, 0.0])
                v = o.get("linear_velocity", [0.0, 0.0, 0.0])
                ori = o.get("orientation", [1.0, 0.0, 0.0, 0.0])
                ang = o.get("angular_velocity", [0.0, 0.0, 0.0])
                states.append(
                    np.array(
                        [
                            float(p[0]), float(p[1]), float(p[2]),
                            float(v[0]), float(v[1]), float(v[2]),
                            float(ori[0]), float(ori[1]), float(ori[2]), float(ori[3]),
                            float(ang[0]), float(ang[1]), float(ang[2]),
                        ],
                        dtype=np.float64,
                    )
                )
            if len(states) > K:
                states_by_body[b_name] = np.array(states, dtype=np.float64)

        if not states_by_body:
            continue

        seq_body_names = sorted(list(states_by_body.keys()))
        t_max = min(len(states_by_body[b]) for b in seq_body_names)
        if t_max <= K:
            continue

        # Arm 6: episode-level parameter identification (cached, only identified once per episode)
        params_by_body: dict[str, PhysicalParameters] | None = None
        if arm_model is not None and isinstance(arm_model, IdentifyResidualArm):
            params_by_body = {}
            for b_name in seq_body_names:
                cache_key = (seq_id, b_name)
                if cache_key in episode_phi_cache:
                    phi_hat = episode_phi_cache[cache_key]
                else:
                    prefix_data = states_by_body[b_name][:K, :6]
                    if arm_model.identifier_fn is not None:
                        body_radii = {b_name: float(radii_by_body[b_name]), "body_0": float(radii_by_body[b_name])}
                        body_radii.update(radii_by_body)
                        try:
                            phi_hat = arm_model.identifier_fn(
                                prefix_data, env, radii_by_body=body_radii
                            )
                        except TypeError:
                            phi_hat = arm_model.identifier_fn(prefix_data, env)
                    else:
                        phi_hat = DEFAULT_BIASED_PRIOR.copy()
                    episode_phi_cache[cache_key] = phi_hat
                params_by_body[b_name] = phi_hat

        for t in range(K - 1, t_max - 1):
            scene_t = {b: states_by_body[b][t] for b in seq_body_names}
            scene_next = {b: states_by_body[b][t + 1] for b in seq_body_names}

            if arm_model is not None and hasattr(arm_model, "scene_training_targets"):
                targets_t = arm_model.scene_training_targets(
                    scene_t,
                    scene_next,
                    static_env=env,
                    radii_by_body=radii_by_body,
                    params_by_body=params_by_body,
                )
            elif arm_model is not None and hasattr(arm_model, "training_target"):
                targets_t = {}
                for b_name in seq_body_names:
                    w = states_by_body[b_name][t - K + 1 : t + 1]
                    targets_t[b_name] = arm_model.training_target(
                        w,
                        scene_next[b_name],
                        static_env=env,
                        prefix_for_identification=params_by_body[b_name] if params_by_body else None,
                        body_name=b_name,
                        radii_by_body=radii_by_body,
                        scene_states=scene_t,
                        params_by_body=params_by_body,
                    )
            else:
                targets_t = {
                    b: (scene_next[b][:6] - scene_t[b][:6]).astype(np.float32)
                    for b in seq_body_names
                }

            for b_name in seq_body_names:
                window = states_by_body[b_name][t - K + 1 : t + 1]
                hist = window[:, :6].flatten().astype(np.float32)  # (K * 6,)
                target = targets_t[b_name]

                x_list.append(hist)
                y_list.append(target)
                samples_info.append(
                    {
                        "sequence_id": seq_id,
                        "body_name": b_name,
                        "t": t,
                    }
                )

    if not x_list:
        raise ValueError(f"No valid training windows could be extracted from {student_dir} (insufficient frames)")

    inputs_arr = np.array(x_list, dtype=np.float32)
    targets_arr = np.array(y_list, dtype=np.float32)

    return TrainingWindows(inputs=inputs_arr, targets=targets_arr, samples=samples_info)


def train_cell(
    arm_id: int,
    family: str,
    seed: int,
    student_dir: Path | str,
    out_dir: Path | str,
    *,
    compute_budget_s: float | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] | None = None,
    sleep_fn: Callable[[float], None] | None = None,
    duty_cycle: float = 0.25,
    steps: int | None = None,
    batch_size: int | None = None,
    lr: float | None = None,
) -> dict[str, Any]:
    """Train a network arm (②, ③, or ⑥) with compute budget, deadline, and duty cycle pacing."""
    # 1. Validation on arm, family, seed, duty_cycle
    if arm_id not in spec.TRAINABLE_ARM_IDS:
        raise ValueError(
            f"Arm {arm_id} is not trainable. Allowed trainable arms: {spec.TRAINABLE_ARM_IDS}"
        )
    if seed not in spec.TRAINING_SEEDS:
        raise ValueError(
            f"Seed {seed} is not in registered spec.TRAINING_SEEDS: {spec.TRAINING_SEEDS}"
        )
    if family not in spec.FAMILIES:
        raise ValueError(
            f"Family '{family}' is not in registered spec.FAMILIES: {spec.FAMILIES}"
        )
    if duty_cycle <= 0.0 or duty_cycle > 1.0:
        raise ValueError(f"duty_cycle must be in (0, 1], got {duty_cycle}")

    # Resolution of hyperparameters from spec
    n_steps = steps if steps is not None else spec.DEFAULT_TRAIN_STEPS
    b_size = batch_size if batch_size is not None else spec.DEFAULT_BATCH_SIZE
    learning_rate = lr if lr is not None else spec.DEFAULT_LEARNING_RATE
    clock_fn = clock if clock is not None else time.perf_counter
    actual_sleep_fn = sleep_fn if sleep_fn is not None else time.sleep

    # 2. Check initial budget and deadline
    start_time = clock_fn()
    if compute_budget_s is not None and compute_budget_s <= 0.0:
        return {
            "status": "stopped",
            "reason": "budget_exhausted",
            "arm_id": arm_id,
            "family": family,
            "seed": seed,
            "steps_completed": 0,
            "active_time_s": 0.0,
            "sleep_time_s": 0.0,
            "losses": [],
            "checkpoint_path": None,
            "checkpoint_sha256": None,
            "parameter_sha256": None,
        }

    if deadline is not None and start_time >= deadline:
        return {
            "status": "stopped",
            "reason": "deadline_exceeded",
            "arm_id": arm_id,
            "family": family,
            "seed": seed,
            "steps_completed": 0,
            "active_time_s": 0.0,
            "sleep_time_s": 0.0,
            "losses": [],
            "checkpoint_path": None,
            "checkpoint_sha256": None,
            "parameter_sha256": None,
        }

    # 3. Model construction
    if arm_id == 2:
        model = PureNetArm(seed=seed, learning_rate=learning_rate)
    elif arm_id == 3:
        model = PriorResidualArm(seed=seed, learning_rate=learning_rate)
    elif arm_id == 6:
        identifier = make_arm6_identifier()
        model = IdentifyResidualArm(seed=seed, learning_rate=learning_rate, identifier_fn=identifier)
    else:
        raise ValueError(f"Unsupported arm {arm_id}")

    # 4. Extract training windows using arm-specific training targets
    windows = build_training_windows(student_dir, K=arms_net.HISTORY_K, model=model)
    N = len(windows)
    rng = np.random.RandomState(seed)

    # 5. Training loop with compute budget, deadline, and duty cycle
    total_calc_time = 0.0
    total_sleep_time = 0.0
    losses: list[float] = []
    steps_done = 0
    was_stopped = False
    stop_reason = ""

    sleep_multiplier = (1.0 / duty_cycle) - 1.0

    for _ in range(n_steps):
        # Pre-step deadline check
        now = clock_fn()
        if deadline is not None and now >= deadline:
            was_stopped = True
            stop_reason = "deadline_exceeded"
            break

        # Batch sampling
        if N <= b_size:
            batch_x = windows.inputs
            batch_y = windows.targets
        else:
            indices = rng.choice(N, size=b_size, replace=False)
            batch_x = windows.inputs[indices]
            batch_y = windows.targets[indices]

        batch = {"inputs": batch_x, "targets": batch_y}

        # Time the calculation
        t_calc_0 = clock_fn()
        step_res = model.train_step(batch)
        t_calc_1 = clock_fn()

        calc_duration = max(t_calc_1 - t_calc_0, 0.0)
        total_calc_time += calc_duration
        loss_val = float(step_res["loss"])
        losses.append(loss_val)
        steps_done += 1

        # Duty cycle pacing: sleep (1/duty - 1) * calculation duration
        sleep_dur = sleep_multiplier * calc_duration
        if sleep_dur > 0.0:
            actual_sleep_fn(sleep_dur)
            total_sleep_time += sleep_dur

        # Post-step budget & deadline checks
        if compute_budget_s is not None and total_calc_time >= compute_budget_s:
            was_stopped = True
            stop_reason = "budget_exhausted"
            break
        if deadline is not None and clock_fn() >= deadline:
            was_stopped = True
            stop_reason = "deadline_exceeded"
            break

    # 6. Finalization
    if was_stopped:
        return {
            "status": "stopped",
            "reason": stop_reason,
            "arm_id": arm_id,
            "family": family,
            "seed": seed,
            "steps_completed": steps_done,
            "active_time_s": total_calc_time,
            "sleep_time_s": total_sleep_time,
            "losses": losses,
            "mean_loss": float(np.mean(losses)) if losses else 0.0,
            "final_loss": losses[-1] if losses else 0.0,
            "checkpoint_path": None,
            "checkpoint_sha256": None,
            "parameter_sha256": None,
        }

    # Completed successfully: save actual weights
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    ckpt_file = out_path / "model_weights.npz"
    model.save(ckpt_file)

    file_bytes = ckpt_file.read_bytes()
    file_sha = hashlib.sha256(file_bytes).hexdigest()
    param_sha = model.parameter_sha256()

    return {
        "status": "completed",
        "arm_id": arm_id,
        "family": family,
        "seed": seed,
        "steps_completed": steps_done,
        "active_time_s": total_calc_time,
        "sleep_time_s": total_sleep_time,
        "losses": losses,
        "mean_loss": float(np.mean(losses)) if losses else 0.0,
        "final_loss": losses[-1] if losses else 0.0,
        "checkpoint_path": str(ckpt_file),
        "checkpoint_sha256": file_sha,
        "parameter_sha256": param_sha,
    }
