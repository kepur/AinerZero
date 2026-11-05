"""Unit tests for E1 training runner (MLX CPU).

Specifications:
- CPU execution only: mx.set_default_device(mx.cpu).
- Tiny training runs: <= 5 steps, <= 10 s per test.
- Synthesize and export 2 sequences, train 3 steps: weights file exists, load reproduces parameter SHA, loss is finite.
- Budget = 0 or past deadline: immediately stopped, no weights written.
- Duty cycle: injected sleep duration is approximately 3x compute duration (duty_cycle = 0.25).
- Rejection of Arm 1 (or non-trainable arms) and unregistered seeds.
"""

from __future__ import annotations

import hashlib
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Any

import mlx.core as mx
import numpy as np
import pytest

from ainerzero.v9.experiments.e1.arms_net import (
    DEFAULT_INPUT_DIM,
    DEFAULT_OUTPUT_DIM,
    HISTORY_K,
    IdentifyResidualArm,
    PriorResidualArm,
    PureNetArm,
)
from ainerzero.v9.experiments.e1.train_runner import (
    TrainingWindows,
    build_training_windows,
    train_cell,
)


@pytest.fixture(autouse=True)
def ensure_cpu_device():
    """Ensure all tests run strictly on MLX CPU device."""
    mx.set_default_device(mx.cpu)


def create_synthetic_student_dataset(directory: Path, num_sequences: int = 2, num_frames: int = 15) -> Path:
    """Create synthetic student-side sequences adhering to student schema."""
    directory.mkdir(parents=True, exist_ok=True)
    dt = 1.0 / 60.0

    for seq_idx in range(num_sequences):
        frames = []
        pos = np.array([float(seq_idx) * 0.5, 0.0, 5.0], dtype=np.float64)
        vel = np.array([1.0, 0.2 * float(seq_idx), -0.5], dtype=np.float64)

        for f in range(num_frames):
            frames.append(
                {
                    "frame": f,
                    "tick": f * 2,
                    "time_seconds": f * dt,
                    "objects": {
                        "ball": {
                            "position": [float(pos[0]), float(pos[1]), float(pos[2])],
                            "linear_velocity": [float(vel[0]), float(vel[1]), float(vel[2])],
                            "orientation": [1.0, 0.0, 0.0, 0.0],
                            "angular_velocity": [0.0, 0.0, 0.0],
                        }
                    },
                }
            )
            # Physical simulation step (gravity)
            vel[2] += -9.81 * dt
            pos += vel * dt

        seq_data = {
            "sequence_id": f"student_seq_{seq_idx}",
            "scenario_type": "free_fall_ball",
            "static_environment": {},
            "active_bodies": {
                "ball": {
                    "name": "ball",
                    "shape": "SPHERE",
                    "dimensions": [0.4, 0.4, 0.4],
                    "bounding_sphere_radius": 0.2,
                }
            },
            "frames": frames,
        }
        (directory / f"seq_{seq_idx}.json").write_text(json.dumps(seq_data, indent=2), encoding="utf-8")

    return directory


# =========================================================================
# 1. build_training_windows Contract
# =========================================================================

def test_build_training_windows_extracts_correct_shapes(tmp_path: Path):
    """Verify build_training_windows extracts K-frame window inputs and delta targets."""
    dataset_dir = create_synthetic_student_dataset(tmp_path / "student_train", num_sequences=2, num_frames=12)

    windows = build_training_windows(dataset_dir, K=4)

    assert isinstance(windows, TrainingWindows)
    assert isinstance(windows, dict)
    assert "inputs" in windows
    assert "targets" in windows

    # num_frames=12, K=4 -> 12 - 4 = 8 windows per sequence -> 16 total
    assert len(windows) == 16
    assert windows.inputs.shape == (16, 24)  # K * 6 = 24
    assert windows.targets.shape == (16, 6)
    assert windows["inputs"].shape == (16, 24)
    assert windows["targets"].shape == (16, 6)

    # First window corresponds to frames 0..3 -> next frame 4
    first_x = windows.inputs[0]
    first_y = windows.targets[0]
    assert np.all(np.isfinite(first_x))
    assert np.all(np.isfinite(first_y))


# =========================================================================
# 2. 3-Step Training: Checkpoint Exists, Parameter SHA Consistent, Finite Loss
# =========================================================================

@pytest.mark.parametrize("arm_id,model_cls", [(2, PureNetArm), (3, PriorResidualArm), (6, IdentifyResidualArm)])
def test_train_3_steps_saves_weights_and_loads_identical_sha(tmp_path: Path, arm_id: int, model_cls: Any):
    """Verify training 3 steps produces real weights file, reproduces parameter SHA, and yields finite loss."""
    student_dir = create_synthetic_student_dataset(tmp_path / f"data_arm_{arm_id}", num_sequences=2, num_frames=12)
    out_dir = tmp_path / f"ckpt_arm_{arm_id}"

    res = train_cell(
        arm_id=arm_id,
        family="P",
        seed=42,
        student_dir=student_dir,
        out_dir=out_dir,
        steps=3,
        batch_size=4,
    )

    assert res["status"] == "completed"
    assert res["steps_completed"] == 3
    assert res["arm_id"] == arm_id
    assert res["family"] == "P"
    assert res["seed"] == 42
    assert len(res["losses"]) == 3
    assert math.isfinite(res["final_loss"])
    assert math.isfinite(res["mean_loss"])

    # Verify checkpoint file exists on disk
    ckpt_path = Path(res["checkpoint_path"])
    assert ckpt_path.is_file()

    # Verify file SHA matches disk bytes
    raw_bytes = ckpt_path.read_bytes()
    expected_file_sha = hashlib.sha256(raw_bytes).hexdigest()
    assert res["checkpoint_sha256"] == expected_file_sha

    # Verify parameter SHA reproduces exactly when loaded into a new model instance
    fresh_instance = model_cls(seed=999)  # initialized with completely different seed
    assert fresh_instance.parameter_sha256() != res["parameter_sha256"]

    fresh_instance.load(ckpt_path)
    assert fresh_instance.parameter_sha256() == res["parameter_sha256"]


# =========================================================================
# 3. Budget & Deadline: Zero Budget or Past Deadline Stops Without Writing Weights
# =========================================================================

def test_train_zero_budget_or_past_deadline_stops_without_writing_weights(tmp_path: Path):
    """Verify compute_budget_s=0 or expired deadline stops immediately without writing weights."""
    student_dir = create_synthetic_student_dataset(tmp_path / "data_budget", num_sequences=2, num_frames=10)

    # 1. Zero budget
    out_dir_budget = tmp_path / "ckpt_zero_budget"
    res_budget = train_cell(
        arm_id=2,
        family="P",
        seed=42,
        student_dir=student_dir,
        out_dir=out_dir_budget,
        compute_budget_s=0.0,
        steps=5,
    )
    assert res_budget["status"] == "stopped"
    assert res_budget["reason"] == "budget_exhausted"
    assert res_budget["steps_completed"] == 0
    assert res_budget["checkpoint_path"] is None
    assert res_budget["checkpoint_sha256"] is None
    assert res_budget["parameter_sha256"] is None
    # No files written to out_dir
    assert not out_dir_budget.exists() or list(out_dir_budget.glob("*")) == []

    # 2. Expired deadline
    out_dir_deadline = tmp_path / "ckpt_expired_deadline"
    res_deadline = train_cell(
        arm_id=2,
        family="P",
        seed=42,
        student_dir=student_dir,
        out_dir=out_dir_deadline,
        deadline=time.perf_counter() - 100.0,
        steps=5,
    )
    assert res_deadline["status"] == "stopped"
    assert res_deadline["reason"] == "deadline_exceeded"
    assert res_deadline["steps_completed"] == 0
    assert res_deadline["checkpoint_path"] is None
    assert not out_dir_deadline.exists() or list(out_dir_deadline.glob("*")) == []

    # 3. Micro budget that exhausts after first step
    out_dir_micro = tmp_path / "ckpt_micro_budget"
    res_micro = train_cell(
        arm_id=2,
        family="P",
        seed=42,
        student_dir=student_dir,
        out_dir=out_dir_micro,
        compute_budget_s=1e-8,
        steps=5,
    )
    assert res_micro["status"] == "stopped"
    assert res_micro["steps_completed"] < 5
    assert res_micro["checkpoint_path"] is None
    assert not out_dir_micro.exists() or list(out_dir_micro.glob("*")) == []


# =========================================================================
# 4. Duty Cycle Pacing: Injected Sleep Duration ~ 3x Calculation Time
# =========================================================================

def test_duty_cycle_sleep_injection_approx_3x_compute(tmp_path: Path):
    """Verify injected sleep function receives total sleep duration approximately 3x compute duration."""
    student_dir = create_synthetic_student_dataset(tmp_path / "data_duty", num_sequences=2, num_frames=10)
    out_dir = tmp_path / "ckpt_duty"

    recorded_sleeps: list[float] = []

    def mock_sleep(duration: float) -> None:
        recorded_sleeps.append(duration)

    res = train_cell(
        arm_id=2,
        family="P",
        seed=42,
        student_dir=student_dir,
        out_dir=out_dir,
        duty_cycle=0.25,
        steps=4,
        batch_size=4,
        sleep_fn=mock_sleep,
    )

    assert res["status"] == "completed"
    assert res["steps_completed"] == 4
    assert len(recorded_sleeps) == 4

    total_sleep = sum(recorded_sleeps)
    assert res["sleep_time_s"] == pytest.approx(total_sleep, rel=1e-6)
    assert res["active_time_s"] > 0.0

    # With duty_cycle = 0.25, sleep_multiplier is (1/0.25 - 1) = 3.0
    expected_sleep = 3.0 * res["active_time_s"]
    assert res["sleep_time_s"] == pytest.approx(expected_sleep, rel=1e-4)


# =========================================================================
# 5. Parameter Validation: Rejection of Non-Trainable Arms and Unregistered Seeds
# =========================================================================

def test_rejection_of_nontrainable_arm_and_unregistered_seed(tmp_path: Path):
    """Verify train_cell strictly rejects non-trainable arms (1, 4, 5, 7) and unregistered seeds."""
    student_dir = create_synthetic_student_dataset(tmp_path / "data_val", num_sequences=1, num_frames=10)
    out_dir = tmp_path / "ckpt_val"

    # Arm 1 is non-trainable
    with pytest.raises(ValueError, match="not trainable"):
        train_cell(arm_id=1, family="P", seed=42, student_dir=student_dir, out_dir=out_dir)

    # Arm 4 (diagnostic) is non-trainable
    with pytest.raises(ValueError, match="not trainable"):
        train_cell(arm_id=4, family="P", seed=42, student_dir=student_dir, out_dir=out_dir)

    # Arm 5 (pure identification) is non-trainable
    with pytest.raises(ValueError, match="not trainable"):
        train_cell(arm_id=5, family="P", seed=42, student_dir=student_dir, out_dir=out_dir)

    # Arm 7 (symbolic) is non-trainable
    with pytest.raises(ValueError, match="not trainable"):
        train_cell(arm_id=7, family="P", seed=42, student_dir=student_dir, out_dir=out_dir)

    # Seed 999 is unregistered
    with pytest.raises(ValueError, match="not in registered"):
        train_cell(arm_id=2, family="P", seed=999, student_dir=student_dir, out_dir=out_dir)

    # Invalid family
    with pytest.raises(ValueError, match="not in registered"):
        train_cell(arm_id=2, family="X", seed=42, student_dir=student_dir, out_dir=out_dir)

    # Invalid duty cycle
    with pytest.raises(ValueError, match="duty_cycle"):
        train_cell(arm_id=2, family="P", seed=42, student_dir=student_dir, out_dir=out_dir, duty_cycle=0.0)


# =========================================================================
# 6. Divergent Training Targets: Pairwise Distinct Parameter SHAs after 20 Steps
# =========================================================================

def test_training_20_steps_arms_parameter_sha_pairwise_different(tmp_path: Path):
    """Verify Arms 2, 3, and 6 trained on identical data and seed produce pairwise distinct parameter SHAs.

    Contract:
    - Same training sequences, same seed (42), same step count (20 steps).
    - Because training targets differ:
        Arm 2: delta state (s_{t+1} - s_t)
        Arm 3: prior residual (s_{t+1} - F_prior(s_t; phi_0))
        Arm 6: projected residual (P_perp * (s_{t+1} - F_prior(s_t; phi_hat)))
      the gradient trajectories diverge, resulting in pairwise different parameter SHA256 hashes.
    - If train_runner bypasses training_target (e.g. using s_{t+1} - s_t for all arms),
      all three arms have identical weights and identical SHA256 (fails).
    """
    student_dir = create_synthetic_student_dataset(tmp_path / "data_sha_diff", num_sequences=2, num_frames=15)

    res2 = train_cell(
        arm_id=2,
        family="P",
        seed=42,
        student_dir=student_dir,
        out_dir=tmp_path / "ckpt_sha_2",
        steps=20,
        batch_size=4,
    )
    res3 = train_cell(
        arm_id=3,
        family="P",
        seed=42,
        student_dir=student_dir,
        out_dir=tmp_path / "ckpt_sha_3",
        steps=20,
        batch_size=4,
    )
    res6 = train_cell(
        arm_id=6,
        family="P",
        seed=42,
        student_dir=student_dir,
        out_dir=tmp_path / "ckpt_sha_6",
        steps=20,
        batch_size=4,
    )

    assert res2["status"] == "completed"
    assert res3["status"] == "completed"
    assert res6["status"] == "completed"

    sha2 = res2["parameter_sha256"]
    sha3 = res3["parameter_sha256"]
    sha6 = res6["parameter_sha256"]

    assert sha2 is not None and sha3 is not None and sha6 is not None
    assert sha2 != sha3, f"Arm 2 and Arm 3 parameter SHA match unexpectedly: {sha2}"
    assert sha3 != sha6, f"Arm 3 and Arm 6 parameter SHA match unexpectedly: {sha3}"
    assert sha2 != sha6, f"Arm 2 and Arm 6 parameter SHA match unexpectedly: {sha2}"
