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
    extract_true_phi_from_episode,
    is_arm_4,
)
from ainerzero.v9.experiments.e1.export import (
    DatasetError,
    FinalPartitionSealed,
    export_sequence,
    seal_final_dataset,
)
from ainerzero.v9.experiments.e1.prior import (
    ActiveBody,
    BodyGeometry,
    GroundPlane,
    PhysicalParameters,
    StaticEnvironment,
    rollout,
)

pytestmark = pytest.mark.native_mlx(reason="real MLX import at collection via the e1 package (arms_net) (A39)")


def synthesize_bounce_sequence(
    seq_idx: int,
    init_z: float = 0.5,
    init_vz: float = -1.0,
    num_frames: int = 35,
    params: PhysicalParameters | None = None,
) -> tuple[dict[str, Any], dict[str, Any], np.ndarray]:
    """Synthesize an episode with a ballistic flight and a ground bounce using prior."""
    ground = GroundPlane(z_plane=0.0)
    env = StaticEnvironment(ground=ground)
    if params is None:
        params = PhysicalParameters(
            friction=0.1,
            restitution=0.8,
            mass=1.0,
            linear_damping=0.125,
            angular_damping=0.125,
        )
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
                "Ground": {
                    "shape": "PLANE",
                    "dimensions": [10.0, 10.0, 0.0],
                    "is_active": False,
                    "friction": 0.50,
                    "restitution": 0.30,
                },
                "ball": {
                    "shape": "SPHERE",
                    "dimensions": [0.4, 0.4, 0.4],
                    "is_active": True,
                    "friction": params.friction,
                    "restitution": params.restitution,
                    "mass": params.mass,
                    "linear_damping": params.linear_damping,
                    "angular_damping": params.angular_damping,
                },
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
        geometry_by_body: Any = None,
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
        geometry_by_body: Any = None,
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


# =========================================================================
# 6. Arm ④ Per-Episode True φ* Diagnostic Rollout Tests
# =========================================================================

def test_arm4_eval_runner_uses_per_episode_true_phi(tmp_path: Path):
    """Verify Arm ④ uses distinct per-episode φ* for the same body name across episodes."""
    from ainerzero.v9.experiments.e1.arms_nonnet import TrueParamArm
    from ainerzero.v9.experiments.e1.export import assert_no_leakage

    student_dir = tmp_path / "cell_student"
    evaluator_dir = tmp_path / "cell_eval"
    student_dir.mkdir()
    evaluator_dir.mkdir()

    # Two episodes with identical object name 'ball', but different restitution: 0.2 vs 0.8
    phi1 = PhysicalParameters(friction=0.25, restitution=0.2, mass=1.0, linear_damping=0.0, angular_damping=0.0)
    phi2 = PhysicalParameters(friction=0.25, restitution=0.8, mass=1.0, linear_damping=0.0, angular_damping=0.0)

    s_ep1, t_ep1, _ = synthesize_bounce_sequence(101, init_z=1.0, init_vz=0.0, params=phi1)
    s_ep2, t_ep2, _ = synthesize_bounce_sequence(102, init_z=1.0, init_vz=0.0, params=phi2)

    # 1. Assert student views have zero leakage of hidden parameters
    assert_no_leakage(s_ep1)
    assert_no_leakage(s_ep2)
    assert "hidden_parameters" not in s_ep1
    assert "hidden_parameters" not in s_ep2

    (student_dir / f"student_{s_ep1['sequence_id']}.json").write_text(json.dumps(s_ep1), encoding="utf-8")
    (evaluator_dir / f"eval_{t_ep1['sequence_id']}.json").write_text(json.dumps(t_ep1), encoding="utf-8")
    (student_dir / f"student_{s_ep2['sequence_id']}.json").write_text(json.dumps(s_ep2), encoding="utf-8")
    (evaluator_dir / f"eval_{t_ep2['sequence_id']}.json").write_text(json.dumps(t_ep2), encoding="utf-8")

    # Arm ④ with dummy initial parameter map
    arm4 = TrueParamArm(true_params=PhysicalParameters(friction=0.5, restitution=0.5, mass=2.6))
    res = evaluate_cell(arm4, student_dir, evaluator_dir)

    # Ground truth rollouts with each episode's own φ*
    env = StaticEnvironment(ground=GroundPlane(z_plane=0.0))
    radius = 0.20
    radii_map = {"ball": radius}

    # Extract observed prefix from each episode
    prefix1 = {
        "ball": np.array([
            s_ep1["frames"][t]["objects"]["ball"]["position"]
            + s_ep1["frames"][t]["objects"]["ball"]["linear_velocity"]
            + s_ep1["frames"][t]["objects"]["ball"]["orientation"]
            + s_ep1["frames"][t]["objects"]["ball"]["angular_velocity"]
            for t in range(PREFIX_FRAMES)
        ], dtype=np.float64)
    }
    prefix2 = {
        "ball": np.array([
            s_ep2["frames"][t]["objects"]["ball"]["position"]
            + s_ep2["frames"][t]["objects"]["ball"]["linear_velocity"]
            + s_ep2["frames"][t]["objects"]["ball"]["orientation"]
            + s_ep2["frames"][t]["objects"]["ball"]["angular_velocity"]
            for t in range(PREFIX_FRAMES)
        ], dtype=np.float64)
    }

    n_future = 25
    geo_map = {"ball": BodyGeometry(radius=0.20)}
    expected_pred1 = TrueParamArm(phi1).predict(prefix1, env, n_future, geometry_by_body=geo_map)["ball"][:, 0:3]
    expected_pred2 = TrueParamArm(phi2).predict(prefix2, env, n_future, geometry_by_body=geo_map)["ball"][:, 0:3]
    wrong_pred2_using_phi1 = TrueParamArm(phi1).predict(prefix2, env, n_future, geometry_by_body=geo_map)["ball"][:, 0:3]

    episodes_by_id = {ep["sequence_id"]: ep for ep in res["episodes"]}
    ep1_actual = np.array(episodes_by_id[s_ep1["sequence_id"]]["pred_positions"]["ball"])
    ep2_actual = np.array(episodes_by_id[s_ep2["sequence_id"]]["pred_positions"]["ball"])

    # Assert predictions match each episode's own φ* rollout to 1e-9
    np.testing.assert_allclose(ep1_actual, expected_pred1, atol=1e-9, rtol=1e-9)
    np.testing.assert_allclose(ep2_actual, expected_pred2, atol=1e-9, rtol=1e-9)

    # Assert ep2 prediction is distinctly different from what it would be using ep1's φ*
    max_diff = float(np.max(np.abs(ep2_actual - wrong_pred2_using_phi1)))
    assert max_diff > 0.05, f"ep2 prediction should differ noticeably from wrong phi1 rollout, got {max_diff}"

    # Also test evaluate_final_once
    staging_dir = tmp_path / "staging_final_arm4"
    staging_dir.mkdir()
    (staging_dir / "student_final.jsonl").write_text(json.dumps(s_ep1) + "\n" + json.dumps(s_ep2) + "\n", encoding="utf-8")
    (staging_dir / "truth_final.jsonl").write_text(json.dumps(t_ep1) + "\n" + json.dumps(t_ep2) + "\n", encoding="utf-8")
    (staging_dir / "export_meta.json").write_text(json.dumps({"version": "v1", "episodes": 2}), encoding="utf-8")

    sealed_root = tmp_path / "sealed_root_arm4"
    seal_res = seal_final_dataset(staging_dir, sealed_root=sealed_root, sealed_by="test_arm4")
    digest = seal_res["dataset_digest"]
    res_final = evaluate_final_once({"arm4": arm4}, sealed_root / digest, expected_digest=digest)

    final_by_id = {ep["sequence_id"]: ep for ep in res_final["arms"]["arm4"]["episodes"]}
    final_ep1 = np.array(final_by_id[s_ep1["sequence_id"]]["pred_positions"]["ball"])
    final_ep2 = np.array(final_by_id[s_ep2["sequence_id"]]["pred_positions"]["ball"])
    np.testing.assert_allclose(final_ep1, expected_pred1, atol=1e-9, rtol=1e-9)
    np.testing.assert_allclose(final_ep2, expected_pred2, atol=1e-9, rtol=1e-9)


def test_arm4_missing_parameter_raises_key_error(tmp_path: Path):
    """Verify KeyError is raised with body name and sequence_id when evaluator view misses friction."""
    from ainerzero.v9.experiments.e1.arms_nonnet import TrueParamArm

    student_dir = tmp_path / "cell_student_err"
    evaluator_dir = tmp_path / "cell_eval_err"
    student_dir.mkdir()
    evaluator_dir.mkdir()

    phi = PhysicalParameters(friction=0.3, restitution=0.5, mass=1.0)
    s_ep, t_ep, _ = synthesize_bounce_sequence(201, init_z=1.0, init_vz=0.0, params=phi)

    # Deliberately remove 'friction' from evaluator truth view
    del t_ep["hidden_parameters"]["ball"]["friction"]

    (student_dir / f"student_{s_ep['sequence_id']}.json").write_text(json.dumps(s_ep), encoding="utf-8")
    (evaluator_dir / f"eval_{t_ep['sequence_id']}.json").write_text(json.dumps(t_ep), encoding="utf-8")

    arm4 = TrueParamArm(true_params=phi)
    with pytest.raises(KeyError) as exc_info:
        evaluate_cell(arm4, student_dir, evaluator_dir)

    err_msg = str(exc_info.value)
    assert "friction" in err_msg
    assert "ball" in err_msg
    assert s_ep["sequence_id"] in err_msg


def test_arm4_student_view_has_no_hidden_parameters():
    """Verify student view strictly contains no hidden parameters."""
    from ainerzero.v9.experiments.e1.export import assert_no_leakage

    phi = PhysicalParameters(friction=0.35, restitution=0.65, mass=2.1, linear_damping=0.1, angular_damping=0.1)
    s_ep, _, _ = synthesize_bounce_sequence(301, init_z=1.0, init_vz=0.0, params=phi)

    assert_no_leakage(s_ep)
    assert "hidden_parameters" not in s_ep
    s_json_str = json.dumps(s_ep)
    for hidden_key in ("friction", "restitution", "mass", "linear_damping", "angular_damping"):
        assert f'"{hidden_key}"' not in s_json_str


def test_arm4_worker_placeholder_cannot_predict_directly(tmp_path: Path):
    """r2 requirement 3: Direct evaluate_episode on worker's Arm ④ placeholder must raise RuntimeError."""
    from ainerzero.v9.experiments.e1.worker import build_arm_for_eval

    arm4 = build_arm_for_eval(
        arm=4,
        family="P",
        seed=None,
        output_root=tmp_path / "output",
        evaluator_dir=tmp_path / "evaluator",
    )
    phi = PhysicalParameters(friction=0.3, restitution=0.5, mass=1.0)
    s_ep, t_ep, _ = synthesize_bounce_sequence(401, init_z=1.0, init_vz=0.0, params=phi)

    with pytest.raises(RuntimeError, match="requires per-episode φ\\* injection"):
        evaluate_episode(arm4, s_ep, t_ep)


def test_arm4_param_map_missing_body_raises_key_error():
    """r2 requirement 4: TrueParamArm looking up body not in param_map strictly raises KeyError without default fallback."""
    from ainerzero.v9.experiments.e1.arms_nonnet import TrueParamArm

    phi = PhysicalParameters(friction=0.3, restitution=0.5, mass=1.0)
    # Mapping contains 'other_body' only, but episode has 'ball'
    arm4 = TrueParamArm(true_params={"other_body": phi}, geometry_by_body={"ball": BodyGeometry(radius=0.20)})

    prefix_data = {"ball": np.ones((5, 13), dtype=np.float64)}
    env = StaticEnvironment(ground=None)

    with pytest.raises(KeyError, match="Missing true parameters for body 'ball' in TrueParamArm"):
        arm4.predict(prefix_data, env, n_future=5, geometry_by_body={"ball": BodyGeometry(radius=0.20)})


def test_extract_true_phi_non_mapping_body_raises_type_error():
    """r2 requirement 4: extract_true_phi_from_episode raises TypeError if body info is not a Mapping."""
    truth_ep = {
        "sequence_id": "test_seq_non_mapping",
        "hidden_parameters": {
            "ball": "invalid_string_not_mapping",
        },
    }
    with pytest.raises(TypeError, match="hidden_parameters must be a Mapping"):
        extract_true_phi_from_episode(truth_ep)


def test_is_arm_4_strict_instance_and_subclass_only():
    """r2 requirement 2: is_arm_4 strictly checks isinstance/issubclass without heuristic name/attribute matches."""
    from ainerzero.v9.experiments.e1.arms_nonnet import PriorArm, TrueParamArm

    class SubTrueParamArm(TrueParamArm):
        pass

    class FakeArmWithAttributes:
        diagnostic_only = True
        arm_id = 4
        arm = 4

    assert is_arm_4(TrueParamArm) is True
    assert is_arm_4(SubTrueParamArm) is True
    assert is_arm_4(TrueParamArm(true_params=None)) is True
    assert is_arm_4(SubTrueParamArm(true_params=None)) is True

    # Negative checks: heuristic attributes or names must NOT qualify as Arm 4
    assert is_arm_4(PriorArm(), arm_name="arm4") is False
    assert is_arm_4(PriorArm(), arm_name="arm4_x") is False
    assert is_arm_4(PriorArm(), arm_name="trueparam_heuristics") is False
    assert is_arm_4(FakeArmWithAttributes(), arm_name="arm4") is False
    assert is_arm_4(FakeArmWithAttributes()) is False
    assert is_arm_4(4) is False
    assert is_arm_4("4") is False


def test_arm4_missing_all_physical_params_raises_key_error(tmp_path: Path):
    """r2 requirement 1: Verify missing physical parameters in evaluator view strictly raises KeyError without fallback_map."""
    from ainerzero.v9.experiments.e1.arms_nonnet import TrueParamArm

    student_dir = tmp_path / "cell_student_c"
    evaluator_dir = tmp_path / "cell_eval_c"
    student_dir.mkdir()
    evaluator_dir.mkdir()

    phi = PhysicalParameters(friction=0.3, restitution=0.5, mass=1.0)
    s_ep, t_ep, _ = synthesize_bounce_sequence(501, init_z=1.0, init_vz=0.0, params=phi)

    # Deliberately remove all physical parameters from evaluator view (keep only geometric)
    del t_ep["hidden_parameters"]["ball"]["friction"]
    del t_ep["hidden_parameters"]["ball"]["restitution"]
    del t_ep["hidden_parameters"]["ball"]["mass"]
    del t_ep["hidden_parameters"]["ball"]["linear_damping"]
    del t_ep["hidden_parameters"]["ball"]["angular_damping"]

    (student_dir / f"student_{s_ep['sequence_id']}.json").write_text(json.dumps(s_ep), encoding="utf-8")
    (evaluator_dir / f"eval_{t_ep['sequence_id']}.json").write_text(json.dumps(t_ep), encoding="utf-8")

    arm4 = TrueParamArm(true_params={"ball": phi}, geometry_by_body={"ball": BodyGeometry(radius=0.20)})
    with pytest.raises(KeyError, match="missing required parameter"):
        evaluate_cell(arm4, student_dir, evaluator_dir)


# =========================================================================
# 7. E1 Revision r2 / P89 Tests
# =========================================================================

def test_arm4_real_bounce_collision_dev_episode_regression():
    """Verify Arm 4 on real SMOKE3 bounce_collision dev episode has e_1 < 1 mm."""
    dataset_eval_dir = Path("reports/V9-E1SMOKE3/gemini-k7a4/smoke_env/datasets/evaluator/S/development")
    dataset_stud_dir = Path("reports/V9-E1SMOKE3/gemini-k7a4/smoke_env/datasets/student/S/development")

    if not dataset_eval_dir.exists() or not dataset_stud_dir.exists():
        pytest.skip(f"SMOKE3 dataset directory not found at {dataset_eval_dir}")

    # Locate a bounce_collision episode
    target_eval = None
    target_stud = None
    for f in sorted(dataset_eval_dir.glob("*.json")):
        data = json.loads(f.read_text())
        if data.get("scenario_type") == "bounce_collision":
            s_f = dataset_stud_dir / f.name
            if s_f.exists():
                target_eval = f
                target_stud = s_f
                break

    if target_eval is None:
        pytest.skip("No bounce_collision episode found in SMOKE3 development dataset")

    t_ep = json.loads(target_eval.read_text())
    s_ep = json.loads(target_stud.read_text())

    from ainerzero.v9.experiments.e1.arms_nonnet import TrueParamArm

    phi_map = extract_true_phi_from_episode(t_ep)
    arm = TrueParamArm(true_params=phi_map)
    res = evaluate_episode(arm, s_ep, t_ep, arm_name="Arm_4_TrueParam")

    pos_errs = res["position_errors"]
    assert "1" in pos_errs
    e_1 = pos_errs["1"]["mean_error_m"]
    # Collision happens after frame 21, so 1-step prediction error must be well under 1 mm
    assert e_1 < 0.001, f"Expected e_1 < 1 mm (0.001 m), got {e_1:.6f} m"


def test_evaluate_cell_aggregates_available_k_and_reports_n_available(tmp_path: Path):
    """Verify evaluate_cell averages only over episodes where horizon k is available and reports n_available."""
    student_dir = tmp_path / "cell_student_avail"
    evaluator_dir = tmp_path / "cell_eval_avail"
    student_dir.mkdir()
    evaluator_dir.mkdir()

    # Episode 1: 45 frames (k=30 available)
    s_ep1, t_ep1, tr1 = synthesize_bounce_sequence(1, init_z=1.0, init_vz=0.0, num_frames=45)
    # Episode 2: 35 frames (k=30 unavailable because 10 - 1 + 30 = 39 >= 35)
    s_ep2, t_ep2, tr2 = synthesize_bounce_sequence(2, init_z=1.0, init_vz=0.0, num_frames=35)

    (student_dir / f"student_{s_ep1['sequence_id']}.json").write_text(json.dumps(s_ep1), encoding="utf-8")
    (evaluator_dir / f"eval_{t_ep1['sequence_id']}.json").write_text(json.dumps(t_ep1), encoding="utf-8")
    (student_dir / f"student_{s_ep2['sequence_id']}.json").write_text(json.dumps(s_ep2), encoding="utf-8")
    (evaluator_dir / f"eval_{t_ep2['sequence_id']}.json").write_text(json.dumps(t_ep2), encoding="utf-8")

    class ConstOffsetArm:
        def predict(self, observed_prefix, static_env, n_future, geometry_by_body=None):
            return {
                "ball": np.zeros((n_future, 6)) + 0.1
            }

    res = evaluate_cell(ConstOffsetArm(), student_dir, evaluator_dir)
    summary = res["summary"]

    assert "k_step_n_available" in summary
    assert summary["k_step_n_available"]["1"] == 2
    assert summary["k_step_n_available"]["5"] == 2
    assert summary["k_step_n_available"]["10"] == 2
    assert summary["k_step_n_available"]["30"] == 1

    # Episode 2 has k=30 unavailable, so cell mean for k=30 must equal Episode 1 error exactly
    ep1_res = next(e for e in res["episodes"] if e["sequence_id"] == s_ep1["sequence_id"])
    assert "30" in ep1_res["position_errors"]
    assert summary["k_step_errors"]["30"] == pytest.approx(ep1_res["position_errors"]["30"]["mean_error_m"])


def synthesize_motion_sequence_ball_and_sliding_box(
    num_frames: int = 50,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, np.ndarray], dict[str, PhysicalParameters]]:
    """Synthesize an episode with an active flying ball and a sliding box on the ground (>= 40 frames)."""
    ground = GroundPlane(z_plane=0.0, friction=0.3, restitution=0.2)
    env = StaticEnvironment(ground=ground)

    phi_ball = PhysicalParameters(
        friction=0.2, restitution=0.7, mass=1.0, linear_damping=0.0, angular_damping=0.0
    )
    phi_box = PhysicalParameters(
        friction=0.35, restitution=0.1, mass=2.0, linear_damping=0.0, angular_damping=0.0
    )

    ball = ActiveBody(
        name="ball",
        radius=0.2,
        params=phi_ball,
        position=np.array([0.0, 0.0, 3.0], dtype=np.float64),
        velocity=np.array([1.5, 0.0, 1.0], dtype=np.float64),
    )
    box_half = np.array([0.3, 0.3, 0.2], dtype=np.float64)
    box_r = float(np.linalg.norm(box_half))
    box = ActiveBody(
        name="box",
        radius=box_r,
        half_extents=box_half,
        params=phi_box,
        position=np.array([0.0, 2.0, 0.2], dtype=np.float64),
        velocity=np.array([2.5, 0.0, 0.0], dtype=np.float64),
    )

    traj = rollout([ball, box], env, num_frames=num_frames)

    frames = []
    for t in range(num_frames):
        frames.append({
            "frame": t,
            "time_seconds": t / 60.0,
            "objects": {
                "Ground": {"position": [0.0, 0.0, 0.0], "linear_velocity": [0.0, 0.0, 0.0]},
                "ball": {
                    "position": traj["ball"][t, 0:3].tolist(),
                    "linear_velocity": traj["ball"][t, 3:6].tolist(),
                    "rotation_quaternion": traj["ball"][t, 6:10].tolist(),
                    "angular_velocity": traj["ball"][t, 10:13].tolist(),
                },
                "box": {
                    "position": traj["box"][t, 0:3].tolist(),
                    "linear_velocity": traj["box"][t, 3:6].tolist(),
                    "rotation_quaternion": traj["box"][t, 6:10].tolist(),
                    "angular_velocity": traj["box"][t, 10:13].tolist(),
                },
            },
            "contacts": [],
        })

    e0_data = {
        "sequence_id": "synth_motion_ball_box_0",
        "world_key": "synth_world_ball_box_0",
        "family": "P",
        "partition": "train",
        "scenario_type": "motion_ball_box",
        "metadata": {
            "fps": 60,
            "hidden_parameters": {
                "Ground": {
                    "shape": "PLANE",
                    "dimensions": [10.0, 10.0, 0.0],
                    "is_active": False,
                    "friction": 0.3,
                    "restitution": 0.2,
                },
                "ball": {
                    "shape": "SPHERE",
                    "dimensions": [0.4, 0.4, 0.4],
                    "is_active": True,
                    "friction": phi_ball.friction,
                    "restitution": phi_ball.restitution,
                    "mass": phi_ball.mass,
                    "linear_damping": phi_ball.linear_damping,
                    "angular_damping": phi_ball.angular_damping,
                },
                "box": {
                    "shape": "BOX",
                    "dimensions": [0.6, 0.6, 0.4],
                    "is_active": True,
                    "friction": phi_box.friction,
                    "restitution": phi_box.restitution,
                    "mass": phi_box.mass,
                    "linear_damping": phi_box.linear_damping,
                    "angular_damping": phi_box.angular_damping,
                },
            },
        },
        "frames": frames,
    }

    student_ep, truth_ep = export_sequence(e0_data)
    phi_map = {"ball": phi_ball, "box": phi_box}
    return student_ep, truth_ep, traj, phi_map


def test_motion_ball_and_box_seven_arms_predictions_and_assertions():
    """Verify r3 requirements on an active moving episode (flying ball and sliding box, >= 40 frames):

    1. ① and ④ have e_1 < 1e-3 m.
    2. ③ with zero network weights matches ① bitwise across all predicted frames.
    3. ⑥ with zero network weights matches ⑤ bitwise across all predicted frames.
    4. All seven arms return pred_positions with row count strictly equal to n_future.
    5. A fake arm returning n_future + 1 rows triggers ValueError in evaluate_episode.
    """
    import mlx.core as mx
    from ainerzero.v9.experiments.e1.arms_net import (
        IdentifyResidualArm,
        PriorResidualArm,
        PureNetArm,
    )
    from ainerzero.v9.experiments.e1.arms_nonnet import (
        ArmPrediction,
        IdentifyArm,
        PriorArm,
        SymbolicResidualArm,
        TrueParamArm,
    )
    from ainerzero.v9.experiments.e1.train_runner import make_arm6_identifier

    student_ep, truth_ep, traj, phi_map = synthesize_motion_sequence_ball_and_sliding_box(num_frames=50)

    # 1. Arm 1 PriorArm & Arm 4 TrueParamArm: e_1 < 1e-3 m
    arm1 = PriorArm()
    res1 = evaluate_episode(arm1, student_ep, truth_ep, arm_name="Arm 1 PriorArm")
    e_1_arm1 = res1["position_errors"]["1"]["mean_error_m"]
    assert e_1_arm1 < 1e-3, f"Arm 1 e_1 ({e_1_arm1:.6e} m) >= 1e-3 m"

    arm4 = TrueParamArm(true_params=phi_map)
    res4 = evaluate_episode(arm4, student_ep, truth_ep, arm_name="Arm 4 TrueParamArm")
    e_1_arm4 = res4["position_errors"]["1"]["mean_error_m"]
    assert e_1_arm4 < 1e-3, f"Arm 4 e_1 ({e_1_arm4:.6e} m) >= 1e-3 m"

    # 2. Arm 3 with zero network weights vs Arm 1: bitwise identical
    arm3 = PriorResidualArm(seed=42)
    for mod in [arm3.net.fc1, arm3.net.fc2, arm3.net.out]:
        mod.weight = mx.zeros_like(mod.weight)
        mod.bias = mx.zeros_like(mod.bias)
    res3 = evaluate_episode(arm3, student_ep, truth_ep, arm_name="Arm 3 PriorResidualArm")

    for bname in ["ball", "box"]:
        arr3 = np.asarray(res3["pred_positions"][bname])
        arr1 = np.asarray(res1["pred_positions"][bname])
        assert np.array_equal(arr3, arr1), f"Arm 3 zero-weight pred for {bname} is not bitwise identical to Arm 1!"

    # 3. Arm 6 with zero network weights vs Arm 5: bitwise identical
    arm5 = IdentifyArm()
    res5 = evaluate_episode(arm5, student_ep, truth_ep, arm_name="Arm 5 IdentifyArm")

    arm6 = IdentifyResidualArm(seed=42, identifier_fn=make_arm6_identifier())
    for mod in [arm6.net.fc1, arm6.net.fc2, arm6.net.out]:
        mod.weight = mx.zeros_like(mod.weight)
        mod.bias = mx.zeros_like(mod.bias)
    res6 = evaluate_episode(arm6, student_ep, truth_ep, arm_name="Arm 6 IdentifyResidualArm")

    for bname in ["ball", "box"]:
        arr6 = np.asarray(res6["pred_positions"][bname])
        arr5 = np.asarray(res5["pred_positions"][bname])
        assert np.array_equal(arr6, arr5), f"Arm 6 zero-weight pred for {bname} is not bitwise identical to Arm 5!"

    # 4. Seven arms pred_positions row count strictly equals n_future
    arm2 = PureNetArm(seed=42)
    arm7 = SymbolicResidualArm()
    seven_arms = {
        "Arm 1": (arm1, res1),
        "Arm 2": (arm2, evaluate_episode(arm2, student_ep, truth_ep, arm_name="Arm 2 PureNetArm")),
        "Arm 3": (arm3, res3),
        "Arm 4": (arm4, res4),
        "Arm 5": (arm5, res5),
        "Arm 6": (arm6, res6),
        "Arm 7": (arm7, evaluate_episode(arm7, student_ep, truth_ep, arm_name="Arm 7 SymbolicResidualArm")),
    }

    n_future = 30
    for label, (_, r) in seven_arms.items():
        for bname in ["ball", "box"]:
            rows = len(r["pred_positions"][bname])
            assert rows == n_future, f"{label} body '{bname}' pred_positions rows={rows} != n_future={n_future}"

    # 5. Fake arm returning n_future + 1 rows raises ValueError in evaluate_episode
    # 5a. Mapping return branch
    class FakeMappingArmExtraRow:
        def predict(self, prefix, env, n_future, **kwargs):
            return {
                "ball": np.zeros((n_future + 1, 6)),
                "box": np.zeros((n_future + 1, 6)),
            }

    with pytest.raises(ValueError, match="predicted 31 .* rows, expected exactly n_future=30"):
        evaluate_episode(FakeMappingArmExtraRow(), student_ep, truth_ep)

    # 5b. ArmPrediction return branch
    class FakeArmPredictionExtraRow:
        def predict(self, prefix, env, n_future, **kwargs):
            return ArmPrediction(
                trajectories={
                    "ball": np.zeros((n_future + 1, 6)),
                    "box": np.zeros((n_future + 1, 6)),
                }
            )

    with pytest.raises(ValueError, match="predicted 31 .* rows, expected exactly n_future=30"):
        evaluate_episode(FakeArmPredictionExtraRow(), student_ep, truth_ep)





