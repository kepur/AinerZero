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
import mlx.utils
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
from .prior import (
    DEFAULT_BIASED_PRIOR,
    BodyGeometry,
    PhysicalParameters,
    StaticEnvironment,
    geometry_from_student_body,
)

# Ensure default MLX execution device is strictly CPU
mx.set_default_device(mx.cpu)


def make_arm6_identifier() -> IdentificationFn:
    """Create parameter identification callback for Arm ⑥ using Arm ⑤ IdentifyArm."""
    arm5 = IdentifyArm()

    def identifier(
        prefix_data: Any,
        env: StaticEnvironment,
        geometry_by_body: Mapping[str, BodyGeometry] | None = None,
    ) -> PhysicalParameters:
        static_env = env if env is not None else StaticEnvironment(ground=None)
        if isinstance(prefix_data, dict):
            if geometry_by_body is None:
                raise KeyError("geometry_by_body is required for parameter identification")
            params_dict, _, _ = arm5.identify(prefix_data, static_env, geometry_by_body=geometry_by_body)
            if params_dict:
                return next(iter(params_dict.values()))
            return DEFAULT_BIASED_PRIOR.copy()

        # Array input path:
        if geometry_by_body is None:
            raise KeyError("geometry_by_body is required for array input identification; none provided")

        if "body_0" not in geometry_by_body or geometry_by_body["body_0"] is None:
            raise KeyError(
                f"Missing geometry for body_0 in geometry_by_body: available keys {list(geometry_by_body.keys())}"
            )
        geo = geometry_by_body["body_0"]

        arr = np.asarray(prefix_data, dtype=np.float64)
        p_hat, _, _ = arm5.identify_body("body_0", arr, static_env, geometry=geo)
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


def get_validation_split_seed(family: str) -> int:
    """Deterministic validation split seed derived strictly from family name."""
    family_offset = sum(ord(c) for c in family)
    return int(spec.VALIDATION_SPLIT_SEED + family_offset)


def split_episodes(
    episode_files: Sequence[Path],
    family: str,
    val_fraction: float = spec.VALIDATION_FRACTION,
) -> tuple[list[Path], list[Path]]:
    """Partition episode files into train and validation disjoint subsets.

    Validation set is chosen deterministically based ONLY on family and episode files,
    independent of training seed or model arm.
    """
    sorted_files = sorted(episode_files, key=lambda p: p.stem)
    n_total = len(sorted_files)
    if n_total < 2:
        raise ValueError(
            f"At least 2 episodes are required to create disjoint train/validation split; got {n_total}"
        )

    n_val = max(1, int(round(n_total * val_fraction)))
    if n_val >= n_total:
        n_val = n_total - 1

    split_seed = get_validation_split_seed(family)
    rng = np.random.RandomState(split_seed)
    perm = rng.permutation(n_total)
    val_indices = set(perm[:n_val])

    val_files = [sorted_files[i] for i in sorted(val_indices)]
    train_files = [sorted_files[i] for i in range(n_total) if i not in val_indices]
    if len(train_files) == 0:
        raise ValueError(
            f"Training episode split is empty ({n_total} episodes, val_fraction={val_fraction})"
        )
    if len(val_files) == 0:
        raise ValueError(
            f"Validation episode split is empty ({n_total} episodes, val_fraction={val_fraction})"
        )
    return train_files, val_files


def compute_validation_loss(model: Any, val_windows: TrainingWindows) -> float:
    """Compute MSE loss on all validation windows in standardized space."""
    if len(val_windows) == 0:
        raise ValueError("Cannot compute validation loss on empty validation windows")
    norm_x = (val_windows.inputs - model.input_mean) / model.input_std
    norm_y = (val_windows.targets - model.target_mean) / model.target_std
    inputs = mx.array(norm_x, dtype=mx.float32)
    targets = mx.array(norm_y, dtype=mx.float32)
    preds = model.net(inputs)
    loss = mx.mean((preds - targets) ** 2)
    mx.eval(loss)
    return float(loss)


def build_training_windows(
    student_dir: Path | str,
    K: int = HISTORY_K,
    *,
    model: Any | None = None,
    arm: Any | None = None,
    json_files: Sequence[Path] | None = None,
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
    if json_files is not None:
        target_files = sorted(list(json_files), key=lambda p: p.stem)
    elif student_path.is_file() and student_path.suffix == ".json":
        target_files = [student_path]
    else:
        target_files = sorted(list(student_path.glob("*.json")))
        if not target_files:
            target_files = sorted(list(student_path.rglob("*.json")))

    if not target_files:
        raise ValueError(f"No student sequence JSON files found in {student_dir}")

    x_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []
    samples_info: list[dict[str, Any]] = []

    # Episode-level cache for Arm 6 parameter identification: (sequence_id, body_name) -> phi_hat
    episode_phi_cache: dict[tuple[str, str], PhysicalParameters] = {}

    for path in target_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        frames = data.get("frames", [])
        if len(frames) <= K:
            continue

        seq_id = str(data.get("sequence_id", path.stem))
        static_geo = data.get("static_environment")
        env = build_static_environment_from_student(static_geo)

        # Extract active bodies and actual geometry
        active_bodies = data.get("active_bodies", {})
        first_objs = frames[0].get("objects", {})
        body_names = sorted(list(active_bodies.keys())) if active_bodies else sorted(list(first_objs.keys()))

        geometry_by_body: dict[str, BodyGeometry] = {}
        for b_name in body_names:
            if b_name in active_bodies:
                geometry_by_body[b_name] = geometry_from_student_body(active_bodies[b_name])
            else:
                raise KeyError(
                    f"Missing active body info for '{b_name}' in sequence '{seq_id}' "
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
                        body_geo = {"body_0": geometry_by_body[b_name]}
                        phi_hat = arm_model.identifier_fn(
                            prefix_data, env, geometry_by_body=body_geo
                        )
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
                    geometry_by_body=geometry_by_body,
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
                        geometry_by_body=geometry_by_body,
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
    eval_every: int | None = None,
    patience: int | None = None,
    val_loss_hook: Callable[[int, float], float] | None = None,
    val_eval_callback: Callable[[int, Any], None] | None = None,
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
    actual_eval_every = eval_every if eval_every is not None else spec.EARLY_STOP_EVAL_EVERY
    actual_patience = patience if patience is not None else spec.EARLY_STOP_PATIENCE

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
            "best_step": 0,
            "stopped_step": 0,
            "val_loss_curve": [],
            "val_episodes": [],
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
            "best_step": 0,
            "stopped_step": 0,
            "val_loss_curve": [],
            "val_episodes": [],
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

    # 4. Discover episode JSONs and split into train and validation disjoint subsets
    student_path = Path(student_dir)
    if not student_path.exists():
        raise FileNotFoundError(f"Student directory does not exist: {student_dir}")

    if student_path.is_file() and student_path.suffix == ".json":
        all_json_files = [student_path]
    else:
        all_json_files = sorted(list(student_path.glob("*.json")))
        if not all_json_files:
            all_json_files = sorted(list(student_path.rglob("*.json")))

    if not all_json_files:
        raise ValueError(f"No student sequence JSON files found in {student_dir}")
    if len(all_json_files) < 2:
        raise ValueError(
            f"At least 2 student episode JSON files required in {student_dir} to construct train/validation split, got {len(all_json_files)}"
        )

    train_files, val_files = split_episodes(
        all_json_files, family, val_fraction=spec.VALIDATION_FRACTION
    )
    val_episodes = [f.stem for f in val_files]

    # Extract windows using arm-specific training targets
    train_windows = build_training_windows(
        student_dir, K=arms_net.HISTORY_K, model=model, json_files=train_files
    )
    if len(train_windows) == 0:
        raise ValueError(
            f"Training windows set is empty after window construction ({len(train_files)} train episodes yielded 0 windows)"
        )

    val_windows = build_training_windows(
        student_dir, K=arms_net.HISTORY_K, model=model, json_files=val_files
    )
    if len(val_windows) == 0:
        raise ValueError(
            f"Validation windows set is empty after window construction ({len(val_files)} val episodes yielded 0 windows)"
        )

    # Compute normalization statistics STRICTLY from train subset only
    input_mean = np.mean(train_windows.inputs, axis=0)
    input_std = np.maximum(np.std(train_windows.inputs, axis=0), 1e-6)
    target_mean = np.mean(train_windows.targets, axis=0)
    target_std = np.maximum(np.std(train_windows.targets, axis=0), 1e-6)
    model.set_normalization(input_mean, input_std, target_mean, target_std)

    N = len(train_windows)
    rng = np.random.RandomState(seed)

    # 5. Training loop with early stopping, compute budget, deadline, and duty cycle
    total_calc_time = 0.0
    total_sleep_time = 0.0
    losses: list[float] = []
    steps_done = 0
    was_stopped = False
    stop_reason = ""

    best_step = 0
    best_weights = {k: mx.array(v) for k, v in mlx.utils.tree_flatten(model.net.parameters())}
    best_val_loss = float("inf")
    patience_counter = 0
    val_loss_curve: list[dict[str, Any]] = []

    sleep_multiplier = (1.0 / duty_cycle) - 1.0

    for _ in range(n_steps):
        # Pre-step deadline check
        now = clock_fn()
        if deadline is not None and now >= deadline:
            was_stopped = True
            stop_reason = "deadline_exceeded"
            break

        # Batch sampling from train_windows
        if N <= b_size:
            batch_x = train_windows.inputs
            batch_y = train_windows.targets
        else:
            indices = rng.choice(N, size=b_size, replace=False)
            batch_x = train_windows.inputs[indices]
            batch_y = train_windows.targets[indices]

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

        # Validation evaluation & early stopping check
        should_eval = (len(val_windows) > 0) and (
            steps_done % actual_eval_every == 0 or steps_done == n_steps
        )
        if should_eval:
            if val_eval_callback is not None:
                val_eval_callback(steps_done, model)
            raw_val_loss = compute_validation_loss(model, val_windows)
            cur_val_loss = (
                val_loss_hook(steps_done, raw_val_loss)
                if val_loss_hook is not None
                else raw_val_loss
            )
            val_loss_curve.append({"step": steps_done, "val_loss": float(cur_val_loss)})

            if cur_val_loss < best_val_loss:
                best_val_loss = cur_val_loss
                best_step = steps_done
                best_weights = {
                    k: mx.array(v) for k, v in mlx.utils.tree_flatten(model.net.parameters())
                }
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= actual_patience:
                    break

        # Post-step budget & deadline checks
        if compute_budget_s is not None and total_calc_time >= compute_budget_s:
            was_stopped = True
            stop_reason = "budget_exhausted"
            break
        if deadline is not None and clock_fn() >= deadline:
            was_stopped = True
            stop_reason = "deadline_exceeded"
            break

    # If no validation set existed (e.g. 1 sequence in micro-test), best_step is final step
    if len(val_windows) == 0:
        best_step = steps_done
        best_weights = {k: mx.array(v) for k, v in mlx.utils.tree_flatten(model.net.parameters())}

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
            "best_step": best_step,
            "stopped_step": steps_done,
            "val_loss_curve": val_loss_curve,
            "val_episodes": val_episodes,
        }

    # Completed successfully: restore best weights and save checkpoint
    if best_weights is not None:
        model.net.update(mlx.utils.tree_unflatten(list(best_weights.items())))
    model.best_step = best_step
    model.stopped_step = steps_done

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    ckpt_file = out_path / "model_weights.npz"
    model.save(ckpt_file, best_step=np.int64(best_step), stopped_step=np.int64(steps_done))

    file_bytes = ckpt_file.read_bytes()
    file_sha = hashlib.sha256(file_bytes).hexdigest()
    param_sha = model.parameter_sha256()

    val_summary = {
        "count": len(val_episodes),
        "sha256": hashlib.sha256(
            json.dumps(val_episodes, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    meta = {
        "best_step": best_step,
        "stopped_step": steps_done,
        "val_loss_curve": val_loss_curve,
        "val_episodes": val_episodes,
        "val_episodes_summary": val_summary,
    }
    (out_path / "checkpoint_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )

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
        "best_step": best_step,
        "stopped_step": steps_done,
        "val_loss_curve": val_loss_curve,
        "val_episodes": val_episodes,
    }
