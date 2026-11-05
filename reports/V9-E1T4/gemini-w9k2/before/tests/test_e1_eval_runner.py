"""Unit tests for E1 evaluation runner (CPU / pure NumPy).

Specifications:
- Synthesize 2-3 sequences using prior (with 1 collision and 1 ballistic flight), export via export_sequence.
- PerfectArm -> position error == 0.0, F1 == 1.0.
- ErrorArm -> position error > 0, misses collision, F1 < 1.0.
- Prediction vs truth collisions computed separately.
- Empty dataset raises ValueError (no default values permitted).
- Sealed final second read raises FinalPartitionSealed.
- Direct read bypass forbidden / fails.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.e1.eval_runner import (
    DEFAULT_EVAL_K_STEPS,
    PREFIX_FRAMES,
    PRIMARY_K,
    evaluate_cell,
    evaluate_episode,
    evaluate_final_once,
)
from ainerzero.v9.experiments.e1.export import (
    DatasetError,
    FinalPartitionSealed,
    export_sequence,
    seal_final_dataset,
)
from ainerzero.v9.experiments.e1.prior import (
    ActiveBody,
    GroundPlane,
    PhysicalParameters,
    StaticEnvironment,
    rollout,
)


def synthesize_bounce_sequence(
    seq_idx: int,
    init_z: float = 0.5,
    init_vz: float = -1.0,
    num_frames: int = 35,
) -> tuple[dict[str, Any], dict[str, Any], np.ndarray]:
    """Synthesize an episode with a ballistic flight and a ground bounce using prior."""
    ground = GroundPlane(z_plane=0.0)
    env = StaticEnvironment(ground=ground)
    params = PhysicalParameters(friction=0.1, restitution=0.8, mass=1.0)
    radius = 0.20
    body = ActiveBody(
        "ball",
        radius=radius,
        params=params,
        position=np.array([float(seq_idx) * 0.2, 0.0, init_z], dtype=np.float64),
        velocity=np.array([0.0, 0.0, init_vz], dtype=np.float64),
    )
    traj = rollout([body], env, num_frames=num_frames)["ball"]

    frames = []
    for t in range(num_frames):
        p = traj[t, 0:3].tolist()
        v = traj[t, 3:6].tolist()
        contacts = []
        if p[2] - radius <= 0.004:
            contacts.append({
                "object_a": "Ground",
                "object_b": "ball",
                "distance": max(0.0, float(p[2] - radius)),
                "normal": [0.0, 0.0, 1.0],
            })
        frames.append({
            "frame": t,
            "time_seconds": t / 60.0,
            "objects": {
                "Ground": {"position": [0.0, 0.0, 0.0], "linear_velocity": [0.0, 0.0, 0.0]},
                "ball": {
                    "position": p,
                    "linear_velocity": v,
                    "rotation_quaternion": [1.0, 0.0, 0.0, 0.0],
                    "angular_velocity": [0.0, 0.0, 0.0],
                },
            },
            "contacts": contacts,
        })

    e0_data = {
        "sequence_id": f"synth_seq_{seq_idx}",
        "world_key": f"synth_world_{seq_idx}",
        "family": "P",
        "partition": "train",
        "scenario_type": "bounce_flight",
        "metadata": {
            "fps": 60,
            "hidden_parameters": {
                "Ground": {"shape": "PLANE", "dimensions": [10.0, 10.0, 0.0], "is_active": False},
                "ball": {"shape": "SPHERE", "dimensions": [0.4, 0.4, 0.4], "is_active": True},
            },
        },
        "frames": frames,
    }

    student_ep, truth_ep = export_sequence(e0_data)
    return student_ep, truth_ep, traj


class PerfectArm:
    """Arm that reproduces exact ground truth future trajectory."""

    def __init__(self, ground_truth_traj: np.ndarray):
        self._traj = ground_truth_traj

    def predict(
        self,
        observed_prefix: dict[str, np.ndarray],
        static_env: Any,
        n_future: int,
        *,
        radii_by_body: Any = None,
        **kwargs: Any,
    ) -> dict[str, np.ndarray]:
        return {"ball": self._traj[PREFIX_FRAMES : PREFIX_FRAMES + n_future]}


class ErrorArm:
    """Arm that predicts offset trajectory and misses collisions."""

    def __init__(self, ground_truth_traj: np.ndarray, offset_z: float = 1.0):
        self._traj = ground_truth_traj.copy()
        self._offset_z = offset_z

    def predict(
        self,
        observed_prefix: dict[str, np.ndarray],
        static_env: Any,
        n_future: int,
        *,
        radii_by_body: Any = None,
        **kwargs: Any,
    ) -> dict[str, np.ndarray]:
        future_traj = self._traj[PREFIX_FRAMES : PREFIX_FRAMES + n_future].copy()
        future_traj[:, 2] += self._offset_z
        return {"ball": future_traj}


# =========================================================================
# 0. Frozen Constants Verification (Imported from metrics.py)
# =========================================================================

def test_constants_imported_directly_from_metrics():
    """Verify that eval_runner does not redefine existing constants, but imports them from metrics."""
    import ainerzero.v9.experiments.e1.eval_runner as runner
    import ainerzero.v9.experiments.e1.metrics as metrics

    assert runner.CONTACT_TOLERANCE_M is metrics.CONTACT_TOLERANCE_M
    assert runner.COLLISION_VELOCITY_THRESHOLD_MPS is metrics.COLLISION_VELOCITY_THRESHOLD_MPS
    assert runner.COLLISION_DEBOUNCE_FRAMES is metrics.COLLISION_DEBOUNCE_FRAMES
    assert runner.COLLISION_MATCH_TOLERANCE_FRAMES is metrics.COLLISION_MATCH_TOLERANCE_FRAMES
    assert runner.BALLISTIC_MIN_FRAMES is metrics.BALLISTIC_MIN_FRAMES
    assert runner.DEFAULT_EVAL_K_STEPS is metrics.DEFAULT_K_STEPS
    assert runner.PRIMARY_K is metrics.PRIMARY_K
    assert runner.GRAVITY_ACCEL is metrics.GRAVITY_ACCEL


# =========================================================================
# 1. PerfectArm Zero Error and F1 = 1.0
# =========================================================================

def test_perfect_arm_zero_position_error_and_f1_one():
    """Verify that a perfect prediction produces 0.0 position error and 1.0 collision F1."""
    student_ep, truth_ep, traj = synthesize_bounce_sequence(0, init_z=0.5, init_vz=-1.0)
    arm = PerfectArm(traj)

    res = evaluate_episode(arm, student_ep, truth_ep)

    assert res["sequence_id"] == student_ep["sequence_id"]
    assert res["prefix_frames"] == PREFIX_FRAMES
    assert res["n_future"] == min(25, len(traj) - PREFIX_FRAMES)

    pos_err = res["position_errors"]
    assert pos_err["primary_error_m"] == pytest.approx(0.0, abs=1e-9)
    for k in (1, 5, 10):
        assert pos_err[str(k)]["mean_error_m"] == pytest.approx(0.0, abs=1e-9)
        assert pos_err[str(k)]["max_error_m"] == pytest.approx(0.0, abs=1e-9)

    f1_dict = res["collision_f1"]
    assert f1_dict["f1"] == pytest.approx(1.0)
    assert f1_dict["precision"] == pytest.approx(1.0)
    assert f1_dict["recall"] == pytest.approx(1.0)
    assert f1_dict["false_positives"] == 0
    assert f1_dict["false_negatives"] == 0
    assert f1_dict["num_pred_events"] == f1_dict["num_true_events"]
    assert f1_dict["num_true_events"] > 0

    drift = res["energy_drift"]
    assert drift["segments_count"] >= 1
    assert drift["mean_drift"] is not None
    assert drift["mean_drift"] < 0.05


def test_energy_drift_evaluated_on_prediction_not_truth():
    """Verify that energy drift is evaluated on arm predictions, not ground truth."""
    student_ep, truth_ep, traj = synthesize_bounce_sequence(3, init_z=1.0, init_vz=0.0)

    class DriftingArm:
        def predict(self, prefix, env, n_future, **kwargs):
            # Predict large artificial acceleration during free flight
            future = traj[PREFIX_FRAMES : PREFIX_FRAMES + n_future].copy()
            future[:, 3:6] *= 3.0
            return {"ball": future}

    arm = DriftingArm()
    res = evaluate_episode(arm, student_ep, truth_ep)
    assert res["energy_drift"]["mean_drift"] is not None
    assert res["energy_drift"]["mean_drift"] > 0.5, "DriftingArm must show large energy drift"


# =========================================================================
# 2. ErrorArm Non-zero Position Error and Missed Collision
# =========================================================================

def test_error_arm_nonzero_position_error_and_missed_collision():
    """Verify that an offset prediction produces positive error and F1 < 1.0."""
    student_ep, truth_ep, traj = synthesize_bounce_sequence(1, init_z=0.5, init_vz=-1.0)
    arm = ErrorArm(traj, offset_z=1.0)

    res = evaluate_episode(arm, student_ep, truth_ep)

    pos_err = res["position_errors"]
    assert pos_err["primary_error_m"] > 0.5
    assert pos_err["primary_error_m"] == pytest.approx(1.0, abs=1e-6)

    f1_dict = res["collision_f1"]
    assert f1_dict["f1"] < 1.0
    assert f1_dict["recall"] == pytest.approx(0.0)
    assert f1_dict["false_negatives"] > 0
    assert f1_dict["num_pred_events"] == 0
    assert f1_dict["num_true_events"] > 0


# =========================================================================
# 3. Prediction vs Truth Collisions Computed Separately
# =========================================================================

def test_prediction_and_truth_collisions_computed_separately():
    """Verify prediction-side and truth-side collision events are strictly isolated."""
    # 1. Sequence where truth never collides (high drop, stays above ground)
    student_ep_air, truth_ep_air, traj_air = synthesize_bounce_sequence(99, init_z=5.0, init_vz=0.0)

    class PhantomArm:
        def predict(self, prefix, env, n_future, **kwargs):
            future = traj_air[PREFIX_FRAMES : PREFIX_FRAMES + n_future].copy()
            # Predict a collision with ground at step 15
            future[15:18, 2] = 0.20
            future[15, 5] = -2.0
            return {"ball": future}

    res_phantom = evaluate_episode(PhantomArm(), student_ep_air, truth_ep_air)
    assert res_phantom["collision_f1"]["num_pred_events"] == 1
    assert res_phantom["collision_f1"]["num_true_events"] == 0
    assert res_phantom["collision_f1"]["false_positives"] == 1
    assert res_phantom["collision_f1"]["precision"] == 0.0
    assert res_phantom["collision_f1"]["f1"] == 0.0

    # 2. Sequence where truth collides, but arm predicts staying in the air
    student_ep_hit, truth_ep_hit, traj_hit = synthesize_bounce_sequence(2, init_z=0.5, init_vz=-1.0)

    class MissedArm:
        def predict(self, prefix, env, n_future, **kwargs):
            future = traj_hit[PREFIX_FRAMES : PREFIX_FRAMES + n_future].copy()
            # Keep ball high in the air
            future[:, 2] = 3.0
            future[:, 5] = 0.0
            return {"ball": future}

    res_missed = evaluate_episode(MissedArm(), student_ep_hit, truth_ep_hit)
    assert res_missed["collision_f1"]["num_pred_events"] == 0
    assert res_missed["collision_f1"]["num_true_events"] > 0
    assert res_missed["collision_f1"]["false_negatives"] > 0
    assert res_missed["collision_f1"]["recall"] == 0.0
    assert res_missed["collision_f1"]["f1"] == 0.0


# =========================================================================
# 4. Cell Evaluation and Empty Dataset Rejection
# =========================================================================

def test_evaluate_cell_aggregates_multiple_episodes(tmp_path: Path):
    """Verify evaluate_cell aggregates metrics across paired synthetic episodes."""
    student_dir = tmp_path / "cell_student"
    evaluator_dir = tmp_path / "cell_eval"
    student_dir.mkdir()
    evaluator_dir.mkdir()

    trajs = []
    for idx in range(3):
        s_ep, t_ep, tr = synthesize_bounce_sequence(idx, init_z=0.4 + idx * 0.1)
        trajs.append(tr)
        (student_dir / f"student_{s_ep['sequence_id']}.json").write_text(json.dumps(s_ep), encoding="utf-8")
        (evaluator_dir / f"eval_{t_ep['sequence_id']}.json").write_text(json.dumps(t_ep), encoding="utf-8")

    class MultiArm:
        def predict(self, prefix, env, n_future, **kwargs):
            # Predict from last frame of prefix with constant velocity
            last_p = prefix["ball"][-1, 0:3]
            last_v = prefix["ball"][-1, 3:6]
            out = np.zeros((n_future, 6), dtype=np.float64)
            for t in range(n_future):
                out[t, 0:3] = last_p + last_v * (t + 1) * (1.0 / 60.0)
                out[t, 3:6] = last_v
            return {"ball": out}

    arm = MultiArm()
    res = evaluate_cell(arm, student_dir, evaluator_dir)

    assert "summary" in res
    assert "episodes" in res
    assert res["summary"]["num_episodes"] == 3
    assert res["summary"]["primary_error_m"] is not None
    assert res["summary"]["primary_error_m"] > 0.0
    assert "10" in res["summary"]["k_step_errors"]
    assert res["summary"]["mean_latency_per_step_s"] >= 0.0


def test_evaluate_cell_rejects_empty_dataset(tmp_path: Path):
    """Verify evaluate_cell loudly raises ValueError on empty dataset (no default values permitted)."""
    empty_student = tmp_path / "empty_student"
    empty_evaluator = tmp_path / "empty_evaluator"
    empty_student.mkdir()
    empty_evaluator.mkdir()

    arm = PerfectArm(np.zeros((35, 13)))

    with pytest.raises(ValueError, match="No valid paired episodes"):
        evaluate_cell(arm, empty_student, empty_evaluator)


# =========================================================================
# 5. Sealed Final One-time Evaluation Channel
# =========================================================================

def test_evaluate_final_once_enforces_token_and_rejects_second_read(tmp_path: Path):
    """Verify evaluate_final_once executes via token and raises FinalPartitionSealed on second read."""
    staging_dir = tmp_path / "staging_final"
    staging_dir.mkdir()

    s_ep1, t_ep1, tr1 = synthesize_bounce_sequence(10)
    s_ep2, t_ep2, tr2 = synthesize_bounce_sequence(11)

    s_lines = [json.dumps(s_ep1), json.dumps(s_ep2)]
    t_lines = [json.dumps(t_ep1), json.dumps(t_ep2)]
    (staging_dir / "student_final.jsonl").write_text("\n".join(s_lines) + "\n", encoding="utf-8")
    (staging_dir / "truth_final.jsonl").write_text("\n".join(t_lines) + "\n", encoding="utf-8")
    (staging_dir / "export_meta.json").write_text(json.dumps({"version": "v1", "episodes": 2}), encoding="utf-8")

    sealed_root = tmp_path / "sealed_root"
    seal_res = seal_final_dataset(staging_dir, sealed_root=sealed_root, sealed_by="test_evaluator")
    digest = seal_res["dataset_digest"]
    sealed_dir = sealed_root / digest

    # 1. Direct bypass without matching digest must fail
    with pytest.raises(DatasetError, match="differs from expected digest"):
        evaluate_final_once(
            {"perfect": PerfectArm(tr1)},
            sealed_dir,
            expected_digest="bad_digest_000000000000000000000000000000000000000000000000000000000000",
        )

    # 2. First evaluation succeeds
    res_final = evaluate_final_once(
        {"perfect": PerfectArm(tr1)},
        sealed_dir,
        expected_digest=digest,
    )
    assert res_final["dataset_digest"] == digest
    assert "perfect" in res_final["arms"]
    assert res_final["arms"]["perfect"]["summary"]["num_episodes"] == 2

    # 3. Second evaluation attempt raises FinalPartitionSealed
    with pytest.raises(FinalPartitionSealed, match="already read"):
        evaluate_final_once(
            {"perfect": PerfectArm(tr1)},
            sealed_dir,
            expected_digest=digest,
        )
