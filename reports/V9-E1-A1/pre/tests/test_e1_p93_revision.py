"""Tests for E1 Revision r4 (ainerzero.V9.P93):

1. Zero-initialization equivalence:
   Untrained Arm 3 == Arm 1 bitwise across all future frames on moving episode (free flying ball + sliding box).
   Untrained Arm 6 == Arm 5 bitwise across all future frames on moving episode.
   Untrained Arm 2 is strictly motionless (predicted position equals last observed position).
2. Normalization roundtrip and missing stats exception:
   Save and load preserves mean/std bitwise. Missing normalization.npz raises FileNotFoundError.
3. Statistics computed strictly from train subset:
   Validation subset with extreme outlier does not contaminate normalization statistics.
4. Validation split determinism and disjointness:
   Disjoint train and validation episode sets; invariant across arms and training seeds.
5. Early stopping:
   Saves weights from best_step rather than last step.
6. Parameter count strictly frozen at 6150.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

import mlx.core as mx
import mlx.utils
import numpy as np
import pytest

from ainerzero.v9.experiments.e1 import spec
from ainerzero.v9.experiments.e1.arms_net import (
    REGISTERED_PARAMETER_COUNT,
    IdentifyResidualArm,
    PriorResidualArm,
    PureNetArm,
)
from ainerzero.v9.experiments.e1.arms_nonnet import IdentifyArm, PriorArm
from ainerzero.v9.experiments.e1.prior import (
    ActiveBody,
    BodyGeometry,
    DEFAULT_BIASED_PRIOR,
    GroundPlane,
    StaticEnvironment,
    simulate_frame,
)
from ainerzero.v9.experiments.e1.train_runner import (
    build_training_windows,
    make_arm6_identifier,
    split_episodes,
    train_cell,
)


@pytest.fixture(autouse=True)
def ensure_cpu_device():
    mx.set_default_device(mx.cpu)


def _generate_moving_episode_prefix(num_frames: int = 10) -> tuple[dict[str, np.ndarray], StaticEnvironment, dict[str, BodyGeometry]]:
    """Generate a physical moving episode with a free-flying ball and a ground-sliding box."""
    env = StaticEnvironment(ground=GroundPlane(z_plane=0.0))
    geo_map = {
        "ball": BodyGeometry(radius=0.15, half_extents=None),
        "box": BodyGeometry(radius=0.35, half_extents=np.array([0.25, 0.25, 0.25], dtype=np.float64)),
    }

    # Initial states: ball flying in the air, box sliding on the ground
    ball = ActiveBody(
        name="ball",
        radius=geo_map["ball"].radius,
        position=np.array([0.0, 0.0, 3.0], dtype=np.float64),
        velocity=np.array([1.5, 0.5, 2.0], dtype=np.float64),
        params=DEFAULT_BIASED_PRIOR.copy(),
    )
    box = ActiveBody(
        name="box",
        radius=geo_map["box"].radius,
        half_extents=geo_map["box"].half_extents,
        position=np.array([1.0, -0.5, 0.25], dtype=np.float64),
        velocity=np.array([2.0, 0.0, 0.0], dtype=np.float64),
        params=DEFAULT_BIASED_PRIOR.copy(),
    )

    bodies = [ball, box]
    trajectories: dict[str, list[np.ndarray]] = {b.name: [] for b in bodies}

    for _ in range(num_frames):
        for b in bodies:
            state = np.concatenate([b.position.copy(), b.velocity.copy(), b.orientation.copy(), b.angular_velocity.copy()])
            trajectories[b.name].append(state)
        simulate_frame(bodies, env)

    prefix_dict = {name: np.array(states, dtype=np.float64) for name, states in trajectories.items()}
    return prefix_dict, env, geo_map


# =========================================================================
# 1. Zero-initialization Equivalence Test
# =========================================================================

def test_zero_initialization_equivalence():
    """Verify untrained ③ == ① bitwise, untrained ⑥ == ⑤ bitwise, untrained ② == motionless."""
    prefix_dict, env, geo_map = _generate_moving_episode_prefix(num_frames=10)
    n_future = 10

    # Arm 1 vs Untrained Arm 3
    arm1 = PriorArm(geometry_by_body=geo_map)
    arm3 = PriorResidualArm(seed=42, geometry_by_body=geo_map)

    pred1 = arm1.predict(prefix_dict, env, n_future=n_future, geometry_by_body=geo_map)
    pred3 = arm3.predict(prefix_dict, env, n_future=n_future, geometry_by_body=geo_map)

    for name in ("ball", "box"):
        traj1 = pred1[name] if isinstance(pred1, dict) else pred1.trajectories[name]
        traj3 = pred3[name]
        assert np.array_equal(traj1, traj3), f"Untrained Arm 3 and Arm 1 diverged on {name}"

    # Arm 5 vs Untrained Arm 6
    arm5 = IdentifyArm(geometry_by_body=geo_map)
    identifier = make_arm6_identifier()
    arm6 = IdentifyResidualArm(seed=42, identifier_fn=identifier, geometry_by_body=geo_map)

    pred5 = arm5.predict(prefix_dict, env, n_future=n_future, geometry_by_body=geo_map)
    pred6 = arm6.predict(prefix_dict, env, n_future=n_future, geometry_by_body=geo_map)

    for name in ("ball", "box"):
        traj5 = pred5.trajectories[name]
        traj6 = pred6[name]
        assert np.array_equal(traj5, traj6), f"Untrained Arm 6 and Arm 5 diverged on {name}"

    # Untrained Arm 2: motionless (position equals last observed frame of prefix)
    arm2 = PureNetArm(seed=42, geometry_by_body=geo_map)
    pred2 = arm2.predict(prefix_dict, env, n_future=n_future, geometry_by_body=geo_map)

    for name in ("ball", "box"):
        last_obs_pos = prefix_dict[name][-1, 0:3]
        for step in range(n_future):
            pos_k = pred2[name][step, 0:3]
            assert np.array_equal(pos_k, last_obs_pos), (
                f"Untrained Arm 2 moved at step {step} on {name}: {pos_k} != {last_obs_pos}"
            )


# =========================================================================
# 2. Normalization Roundtrip and Loud Exception on Missing Stats
# =========================================================================

def test_normalization_roundtrip_and_missing_stats_exception(tmp_path: Path):
    """Verify normalization statistics save and load bitwise, and missing stats raise FileNotFoundError."""
    arm = PureNetArm(seed=42)
    custom_in_mean = np.linspace(-1.0, 1.0, 24, dtype=np.float32)
    custom_in_std = np.linspace(0.5, 2.5, 24, dtype=np.float32)
    custom_tar_mean = np.array([0.1, -0.2, 0.3, 0.01, -0.02, 0.03], dtype=np.float32)
    custom_tar_std = np.array([1.2, 0.8, 1.5, 0.5, 0.9, 1.1], dtype=np.float32)

    arm.set_normalization(custom_in_mean, custom_in_std, custom_tar_mean, custom_tar_std)

    ckpt_file = tmp_path / "model_weights.npz"
    arm.save(ckpt_file)

    loaded_arm = PureNetArm(seed=999)
    loaded_arm.load(ckpt_file)

    assert np.array_equal(loaded_arm.input_mean, custom_in_mean)
    assert np.array_equal(loaded_arm.input_std, custom_in_std)
    assert np.array_equal(loaded_arm.target_mean, custom_tar_mean)
    assert np.array_equal(loaded_arm.target_std, custom_tar_std)
    assert loaded_arm.parameter_sha256() == arm.parameter_sha256()

    # Missing normalization stats file loud exception
    norm_file = tmp_path / "normalization.npz"
    assert norm_file.is_file()
    norm_file.unlink()

    arm_missing = PureNetArm(seed=123)
    with pytest.raises(FileNotFoundError, match="Missing normalization statistics"):
        arm_missing.load(ckpt_file)


# =========================================================================
# 3. Statistics Computed Strictly From Train Subset Only
# =========================================================================

def _create_synthetic_episode_file(path: Path, seq_id: str, offset: float = 0.0) -> None:
    frames = []
    dt = 1.0 / 60.0
    for f in range(12):
        frames.append({
            "frame": f,
            "tick": f * 2,
            "time_seconds": f * dt,
            "objects": {
                "body_0": {
                    "position": [offset + float(f) * 0.1, 0.0, 1.0],
                    "linear_velocity": [1.0, 0.0, 0.0],
                    "orientation": [1.0, 0.0, 0.0, 0.0],
                    "angular_velocity": [0.0, 0.0, 0.0],
                }
            },
        })
    payload = {
        "sequence_id": seq_id,
        "scenario_type": "free_fall",
        "static_environment": {},
        "active_bodies": {
            "body_0": {
                "name": "body_0",
                "shape": "SPHERE",
                "dimensions": [0.2, 0.2, 0.2],
                "mass": 1.0,
                "radius": 0.1,
                "bounding_sphere_radius": 0.1,
            }
        },
        "frames": frames,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_normalization_computed_strictly_from_train_subset(tmp_path: Path):
    """Verify validation subset with extreme outlier does not contaminate normalization statistics."""
    data_dir = tmp_path / "dataset"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Create 10 normal episodes
    files = []
    for i in range(10):
        p = data_dir / f"seq_{i:02d}.json"
        _create_synthetic_episode_file(p, f"seq_{i:02d}", offset=float(i) * 0.5)
        files.append(p)

    # Determine which file lands in validation set for family "P"
    train_files, val_files = split_episodes(files, family="P", val_fraction=0.1)
    assert len(val_files) == 1
    val_file = val_files[0]

    # Mutate the validation file into an extreme outlier (values on order of 1e9)
    outlier_val_data = json.loads(val_file.read_text(encoding="utf-8"))
    for fr in outlier_val_data["frames"]:
        fr["objects"]["body_0"]["position"] = [1e9, 1e9, 1e9]
        fr["objects"]["body_0"]["linear_velocity"] = [1e9, 1e9, 1e9]
    val_file.write_text(json.dumps(outlier_val_data), encoding="utf-8")

    out_dir = tmp_path / "ckpt"
    res = train_cell(
        arm_id=2,
        family="P",
        seed=42,
        student_dir=data_dir,
        out_dir=out_dir,
        steps=5,
        batch_size=4,
    )
    assert res["status"] == "completed"

    loaded_arm = PureNetArm(seed=42)
    loaded_arm.load(res["checkpoint_path"])

    # Verify input_mean and target_mean are completely unaffected by the 1e9 outlier
    assert np.all(np.abs(loaded_arm.input_mean) < 100.0), f"input_mean contaminated: {loaded_arm.input_mean}"
    assert np.all(np.abs(loaded_arm.input_std) < 100.0), f"input_std contaminated: {loaded_arm.input_std}"
    assert np.all(np.abs(loaded_arm.target_mean) < 100.0), f"target_mean contaminated: {loaded_arm.target_mean}"
    assert np.all(np.abs(loaded_arm.target_std) < 100.0), f"target_std contaminated: {loaded_arm.target_std}"


# =========================================================================
# 4. Validation Split Determinism and Disjointness
# =========================================================================

def test_validation_split_disjoint_and_invariant_across_arms_and_seeds(tmp_path: Path):
    """Verify validation split is strictly disjoint from train set, and invariant to arms/seeds."""
    data_dir = tmp_path / "dataset_split"
    data_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(20):
        p = data_dir / f"ep_{i:03d}.json"
        _create_synthetic_episode_file(p, f"ep_{i:03d}")
        files.append(p)

    train_p, val_p = split_episodes(files, family="P", val_fraction=0.1)
    set_train_p = {f.stem for f in train_p}
    set_val_p = {f.stem for f in val_p}

    # Disjointness check
    assert set_train_p.isdisjoint(set_val_p)
    assert len(set_val_p) == 2
    assert len(set_train_p) == 18

    # Invariance check across runs of different arms and seeds for family "P"
    out_dir_2 = tmp_path / "ckpt_arm2_s42"
    out_dir_3 = tmp_path / "ckpt_arm3_s43"
    out_dir_6 = tmp_path / "ckpt_arm6_s44"

    res2 = train_cell(arm_id=2, family="P", seed=42, student_dir=data_dir, out_dir=out_dir_2, steps=2, batch_size=4)
    res3 = train_cell(arm_id=3, family="P", seed=43, student_dir=data_dir, out_dir=out_dir_3, steps=2, batch_size=4)
    res6 = train_cell(arm_id=6, family="P", seed=44, student_dir=data_dir, out_dir=out_dir_6, steps=2, batch_size=4)

    assert res2["val_episodes"] == res3["val_episodes"]
    assert res3["val_episodes"] == res6["val_episodes"]
    assert set(res2["val_episodes"]) == set_val_p


# =========================================================================
# 5. Early Stopping Test
# =========================================================================

def test_early_stopping_saves_best_step_weights(tmp_path: Path):
    """Verify early stopping preserves the weights from best_step (e.g. step 1500), not the final step."""
    data_dir = tmp_path / "dataset_es"
    data_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(10):
        p = data_dir / f"ep_{i:02d}.json"
        _create_synthetic_episode_file(p, f"ep_{i:02d}")
        files.append(p)

    # Injected validation loss hook: minimum strictly at step 1500
    def artificial_val_loss(step: int, raw_loss: float) -> float:
        # Step 500: 1.0, Step 1000: 0.5, Step 1500: 0.1 (minimum), Step 2000+: increasing
        if step == 500:
            return 1.0
        elif step == 1000:
            return 0.5
        elif step == 1500:
            return 0.1
        else:
            return 0.1 + float(step - 1500) * 0.01

    captured_eval_weights: dict[int, dict[str, np.ndarray]] = {}

    def on_eval(step: int, model: Any) -> None:
        captured_eval_weights[step] = {
            k: np.array(v) for k, v in mlx.utils.tree_flatten(model.net.parameters())
        }

    out_dir = tmp_path / "ckpt_es"
    # Train 2000 steps with eval_every=500
    res = train_cell(
        arm_id=2,
        family="P",
        seed=42,
        student_dir=data_dir,
        out_dir=out_dir,
        steps=2000,
        batch_size=4,
        eval_every=500,
        patience=10,
        val_loss_hook=artificial_val_loss,
        val_eval_callback=on_eval,
    )

    assert res["status"] == "completed"
    assert res["best_step"] == 1500
    assert res["stopped_step"] == 2000
    assert len(res["val_loss_curve"]) == 4

    # Verify checkpoint_meta.json exists and records best_step
    meta_path = out_dir / "checkpoint_meta.json"
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["best_step"] == 1500
    assert meta["stopped_step"] == 2000

    # Load model and verify its loaded weights match step 1500, NOT step 2000
    loaded_arm = PureNetArm(seed=42)
    loaded_arm.load(res["checkpoint_path"])
    assert getattr(loaded_arm, "best_step", None) == 1500

    loaded_weights = {k: np.array(v) for k, v in mlx.utils.tree_flatten(loaded_arm.net.parameters())}
    w_best = captured_eval_weights[1500]
    w_last = captured_eval_weights[2000]

    # Verify weights actually evolved between step 1500 and step 2000
    has_diff = any(not np.array_equal(w_best[k], w_last[k]) for k in w_best)
    assert has_diff, "Expected weights to differ between step 1500 and step 2000"

    # Verify saved checkpoint strictly matches best_step (1500) and differs from final step (2000)
    for k in w_best:
        assert np.array_equal(loaded_weights[k], w_best[k]), f"Weight {k} does not match best_step 1500"

    is_matching_last = all(np.array_equal(loaded_weights[k], w_last[k]) for k in w_last)
    assert not is_matching_last, "Saved weights incorrectly match final step 2000 instead of best_step 1500"


# =========================================================================
# 6. Predict Denormalization Applied Test
# =========================================================================

def test_predict_denormalization_applied():
    """Verify predict_delta strictly denormalizes the network output using target_mean and target_std."""
    arm = PureNetArm(seed=42)
    custom_tar_mean = np.array([12.5, -8.0, 4.25, 0.5, -1.2, 3.1], dtype=np.float32)
    custom_tar_std = np.array([2.5, 3.0, 1.5, 0.4, 0.8, 1.2], dtype=np.float32)

    arm.set_normalization(
        input_mean=np.zeros(24, dtype=np.float32),
        input_std=np.ones(24, dtype=np.float32),
        target_mean=custom_tar_mean,
        target_std=custom_tar_std,
    )

    # With zero-initialized output layer, raw network output is 0
    # With denormalization: out = 0 * std + mean = target_mean
    # If denormalization is omitted: out = 0 != target_mean
    hist = np.ones(24, dtype=np.float64)
    delta = arm.predict_delta(hist)
    assert np.allclose(delta, custom_tar_mean, atol=1e-5), (
        f"Denormalization missing in predict_delta: expected {custom_tar_mean}, got {delta}"
    )


# =========================================================================
# 7. Parameter Count Strictly Frozen
# =========================================================================

def test_parameter_counts_frozen():
    """Verify parameter count of Arms ②, ③, and ⑥ remains strictly frozen at 6150."""
    geo = {"body_0": BodyGeometry(radius=0.1)}
    arm2 = PureNetArm(seed=42, geometry_by_body=geo)
    arm3 = PriorResidualArm(seed=42, geometry_by_body=geo)
    arm6 = IdentifyResidualArm(seed=42, geometry_by_body=geo)

    assert arm2.count_parameters() == REGISTERED_PARAMETER_COUNT
    assert arm3.count_parameters() == REGISTERED_PARAMETER_COUNT
    assert arm6.count_parameters() == REGISTERED_PARAMETER_COUNT
    assert REGISTERED_PARAMETER_COUNT == 6150
