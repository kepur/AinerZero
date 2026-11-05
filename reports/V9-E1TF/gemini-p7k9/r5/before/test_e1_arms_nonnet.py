"""Unit tests for E1 non-neural arms (CPU / pure NumPy).

Covers:
- ① PriorArm: Rollout with DEFAULT_BIASED_PRIOR.
- ④ TrueParamArm: Rollout with true φ* (diagnostic upper bound, diagnostic_only = True).
- ⑤ IdentifyArm: Identification of restitution and friction on 30-frame prefix (error < 0.5 * err_phi0).
  Fallback to φ̂₀ with identifiable=False on 3-frame prefix.
- ⑦ SymbolicResidualArm: STLSQ discovery of quadratic drag -c|v|v (relative error < 20%, promoted=True,
  10-step error lower than Arm ⑤). Rejection of promotion (promoted=False) on data without drag.
- Prefix isolation: Future frames with NaNs do not leak into or affect prefix evaluations.
- Error evaluation with metrics.py k-step error functions.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from ainerzero.v9.experiments.e1.arms_nonnet import (
    FISHER_MIN_EIGVAL_THRESHOLD,
    MAX_IDENTIFY_ITERATIONS,
    PARAM_BOUNDS,
    PROMOTE_MIN_GAIN,
    ArmPrediction,
    IdentifyArm,
    PriorArm,
    SymbolicResidualArm,
    TrueParamArm,
    rollout_with_accel,
)
from ainerzero.v9.experiments.e1.metrics import (
    compute_k_step_position_errors,
    compute_position_error,
)
from ainerzero.v9.experiments.e1.prior import (
    DEFAULT_BIASED_PRIOR,
    ActiveBody,
    InclinedRamp,
    PhysicalParameters,
    StaticEnvironment,
    rollout,
)


# =========================================================================
# 1. Arm ⑤ Tests: Online Parameter Identification & Identifiability Gate
# =========================================================================

def test_arm5_parameter_identification_restitution_and_friction():
    """Verify Arm ⑤ on 30-frame prefix achieves parameter error < 0.5 * phi0 error.

    Scene: Sphere bouncing and slipping down a 45-degree ramp with ground truth
    friction = 0.15 and restitution = 0.75.
    """
    theta_deg = 45.0
    theta_rad = math.radians(theta_deg)
    ramp_normal = np.array([0.0, -math.sin(theta_rad), math.cos(theta_rad)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)
    ramp = InclinedRamp(point=np.array([0.0, 0.0, 0.0]), normal=ramp_normal, friction=0.0, restitution=1.0)
    env = StaticEnvironment(ground=None, ramps=[ramp])

    init_pos = ramp.point + 0.20 * ramp_normal + np.array([0.0, 0.0, 0.2])
    init_vel = np.array([0.0, -1.0, -2.0])

    true_p = PhysicalParameters(friction=0.15, restitution=0.75, mass=2.6, linear_damping=0.0, angular_damping=0.0)
    body = ActiveBody("ball", radius=0.20, params=true_p, position=init_pos.copy(), velocity=init_vel.copy())

    full_traj = rollout([body], env, num_frames=35)["ball"]
    prefix_30 = {"ball": full_traj[:30]}

    arm5 = IdentifyArm(radii={"ball": 0.20})
    res5 = arm5.predict(prefix_30, env, n_future=5)

    assert res5.identifiable is True
    assert res5["identifiable"] is True

    p_hat = res5.identified_params["ball"]
    p0 = DEFAULT_BIASED_PRIOR

    err0 = float(np.linalg.norm([p0.friction - true_p.friction, p0.restitution - true_p.restitution]))
    err_hat = float(np.linalg.norm([p_hat.friction - true_p.friction, p_hat.restitution - true_p.restitution]))

    # Error must be reduced by more than half w.r.t biased prior
    assert err_hat < 0.5 * err0, f"Identified error {err_hat:.4f} is not < 0.5 * {err0:.4f}"

    # Bounds must be strictly satisfied
    assert PARAM_BOUNDS["friction"][0] <= p_hat.friction <= PARAM_BOUNDS["friction"][1]
    assert PARAM_BOUNDS["restitution"][0] <= p_hat.restitution <= PARAM_BOUNDS["restitution"][1]

    # Posterior covariance must be symmetric positive definite
    cov = res5.posterior_covariance["ball"]
    assert cov.shape == (2, 2)
    eigvals = np.linalg.eigvalsh(cov)
    assert np.all(eigvals > 0.0)


def test_arm5_short_prefix_unidentifiable_fallback():
    """Verify Arm ⑤ on 3-frame prefix falls back to phi0 with identifiable=False."""
    theta_deg = 45.0
    theta_rad = math.radians(theta_deg)
    ramp_normal = np.array([0.0, -math.sin(theta_rad), math.cos(theta_rad)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)
    ramp = InclinedRamp(point=np.array([0.0, 0.0, 0.0]), normal=ramp_normal, friction=0.0, restitution=1.0)
    env = StaticEnvironment(ground=None, ramps=[ramp])

    init_pos = ramp.point + 0.20 * ramp_normal + np.array([0.0, 0.0, 0.2])
    init_vel = np.array([0.0, -1.0, -2.0])

    true_p = PhysicalParameters(friction=0.15, restitution=0.75, mass=2.6, linear_damping=0.0, angular_damping=0.0)
    body = ActiveBody("ball", radius=0.20, params=true_p, position=init_pos.copy(), velocity=init_vel.copy())

    full_traj = rollout([body], env, num_frames=10)["ball"]
    prefix_3 = {"ball": full_traj[:3]}

    arm5 = IdentifyArm(radii={"ball": 0.20})
    res5 = arm5.predict(prefix_3, env, n_future=5)

    assert res5.identifiable is False
    assert res5["identifiable"] is False

    p_hat = res5.identified_params["ball"]
    assert p_hat.friction == pytest.approx(DEFAULT_BIASED_PRIOR.friction)
    assert p_hat.restitution == pytest.approx(DEFAULT_BIASED_PRIOR.restitution)


# =========================================================================
# 2. Arm ① vs Arm ④ Tests: Prior vs True Parameters Upper Bound
# =========================================================================

def test_arm1_and_arm4_true_param_comparison():
    """Verify Arm ④ achieves near-zero error and significantly outperforms Arm ①."""
    theta_deg = 45.0
    theta_rad = math.radians(theta_deg)
    ramp_normal = np.array([0.0, -math.sin(theta_rad), math.cos(theta_rad)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)
    ramp = InclinedRamp(point=np.array([0.0, 0.0, 0.0]), normal=ramp_normal, friction=0.0, restitution=1.0)
    env = StaticEnvironment(ground=None, ramps=[ramp])

    init_pos = ramp.point + 0.20 * ramp_normal + np.array([0.0, 0.0, 0.2])
    init_vel = np.array([0.0, -1.0, -2.0])

    true_p = PhysicalParameters(friction=0.15, restitution=0.75, mass=2.6, linear_damping=0.0, angular_damping=0.0)
    body = ActiveBody("ball", radius=0.20, params=true_p, position=init_pos.copy(), velocity=init_vel.copy())

    full_traj = rollout([body], env, num_frames=40)["ball"]
    prefix_30 = {"ball": full_traj[:30]}

    arm1 = PriorArm(radii={"ball": 0.20})
    arm4 = TrueParamArm(true_p, radii={"ball": 0.20})

    assert arm4.diagnostic_only is True

    res1 = arm1.predict(prefix_30, env, n_future=10)
    res4 = arm4.predict(prefix_30, env, n_future=10)

    ground_truth_future = full_traj[30:40, 0:3]

    err1 = compute_position_error(res1.positions["ball"], ground_truth_future)["mean_error_m"]
    err4 = compute_position_error(res4.positions["ball"], ground_truth_future)["mean_error_m"]

    # Arm 4 with exact true parameters should achieve machine-precision rollout
    assert err4 < 1e-6, f"TrueParamArm error {err4:.4e} exceeds 1e-6"
    assert err4 < err1 * 0.05, f"TrueParamArm error {err4} is not significantly lower than PriorArm {err1}"


# =========================================================================
# 3. Arm ⑦ Tests: STLSQ Residual Acceleration Discovery & Promotion
# =========================================================================

def test_arm7_quadratic_drag_discovery_and_promotion():
    """Verify Arm ⑦ discovers quadratic drag -c|v|v with < 20% relative error and lower error than Arm ⑤."""
    env = StaticEnvironment(ground=None)
    c_true = 0.35

    def drag_cb(b: ActiveBody) -> np.ndarray:
        v = b.velocity
        return -c_true * np.linalg.norm(v) * v

    body = ActiveBody(
        "ball",
        radius=0.20,
        params=PhysicalParameters(linear_damping=0.0),
        position=np.array([0.0, 0.0, 5.0]),
        velocity=np.array([3.0, 0.0, 0.0]),
    )

    full_traj = rollout_with_accel([body], env, num_frames=40, extra_accel_fn=drag_cb)["ball"]
    prefix_30 = {"ball": full_traj[:30]}

    arm7 = SymbolicResidualArm(radii={"ball": 0.20})
    res7 = arm7.predict(prefix_30, env, n_future=10)

    # 1. Promotion gate must pass
    assert res7.promoted is True
    assert res7["promoted"] is True
    assert "quadratic_drag" in res7.extra["active_terms"]

    # 2. Recovered coefficient relative error < 20%
    idx = res7.extra["active_terms"].index("quadratic_drag")
    c_rec = float(res7.extra["coefficients"][idx])
    rel_err = abs(c_rec - c_true) / c_true
    assert rel_err < 0.20, f"Recovered drag c={c_rec:.4f} rel_err={rel_err:.4f} exceeds 20%"

    # 3. 10-step error must be lower than Arm ⑤
    arm5 = IdentifyArm(radii={"ball": 0.20})
    res5 = arm5.predict(prefix_30, env, n_future=10)

    ground_truth_future = full_traj[30:40, 0:3]
    err7_10 = compute_position_error(res7.positions["ball"][-1:], ground_truth_future[-1:])["mean_error_m"]
    err5_10 = compute_position_error(res5.positions["ball"][-1:], ground_truth_future[-1:])["mean_error_m"]

    assert err7_10 < err5_10, f"Arm ⑦ 10-step error {err7_10:.4f} not lower than Arm ⑤ {err5_10:.4f}"


def test_arm7_no_drag_rejected_promotion():
    """Verify Arm ⑦ does not promote symbolic terms when data has no drag (promoted=False)."""
    env = StaticEnvironment(ground=None)
    body = ActiveBody(
        "ball",
        radius=0.20,
        params=PhysicalParameters(linear_damping=0.0),
        position=np.array([0.0, 0.0, 5.0]),
        velocity=np.array([3.0, 0.0, 0.0]),
    )

    full_traj = rollout([body], env, num_frames=40)["ball"]
    prefix_30 = {"ball": full_traj[:30]}

    arm7 = SymbolicResidualArm(radii={"ball": 0.20})
    res7 = arm7.predict(prefix_30, env, n_future=10)

    assert res7.promoted is False
    assert res7["promoted"] is False


def test_arm7_transient_force_rejected_by_validation_gate():
    """Verify promotion gate rejects candidate terms that fit training segment but fail validation.

    Adversarial setup:
    - Frames 0..20 (training segment): active quadratic drag force (-c|v|v) is applied.
      STLSQ will successfully identify quadratic_drag in active_terms.
    - Frames 20..30 (validation segment): drag force vanishes (pure ballistic motion).
    - Validation error under Arm ⑤ is low, while candidate Arm ⑦ slows down and incurs high error.
    - gain = (E5 - E7) / E5 < 0 < PROMOTE_MIN_GAIN -> gate must reject (promoted=False).
    - Mutating gate to 'if True:' will cause this test to fail.
    """
    env = StaticEnvironment(ground=None)
    c_true = 0.35
    params = PhysicalParameters(linear_damping=0.0)

    body = ActiveBody(
        "ball",
        radius=0.20,
        params=params,
        position=np.array([0.0, 0.0, 5.0]),
        velocity=np.array([4.0, 0.0, 0.0]),
    )

    traj_frames = [body.copy()]
    drag_cb = lambda b: -c_true * np.linalg.norm(b.velocity) * b.velocity

    # First 20 frames have drag
    for _ in range(20):
        cur_b = traj_frames[-1].copy()
        r = rollout([cur_b], env, num_frames=1, extra_accel_fn=drag_cb)["ball"]
        nb = ActiveBody(
            "ball",
            radius=0.20,
            params=params,
            position=r[1, 0:3],
            velocity=r[1, 3:6],
            orientation=r[1, 6:10],
            angular_velocity=r[1, 10:13],
        )
        traj_frames.append(nb)

    # Next 10 frames have NO drag
    for _ in range(10):
        cur_b = traj_frames[-1].copy()
        r = rollout([cur_b], env, num_frames=1, extra_accel_fn=None)["ball"]
        nb = ActiveBody(
            "ball",
            radius=0.20,
            params=params,
            position=r[1, 0:3],
            velocity=r[1, 3:6],
            orientation=r[1, 6:10],
            angular_velocity=r[1, 10:13],
        )
        traj_frames.append(nb)

    full_traj = np.zeros((31, 13), dtype=np.float64)
    for i, b in enumerate(traj_frames):
        full_traj[i, 0:3] = b.position
        full_traj[i, 3:6] = b.velocity
        full_traj[i, 6:10] = b.orientation
        full_traj[i, 10:13] = b.angular_velocity

    prefix_30 = {"ball": full_traj[:30]}
    arm7 = SymbolicResidualArm(radii={"ball": 0.20})
    res7 = arm7.predict(prefix_30, env, n_future=5)

    # STLSQ must have discovered quadratic drag on the training segment
    assert "quadratic_drag" in res7.extra["active_terms"], "STLSQ failed to find quadratic drag in train segment"
    # But validation gain must be below threshold
    assert res7.extra["promotion_gain"] < PROMOTE_MIN_GAIN
    # Promotion must be rejected
    assert res7.promoted is False, "Promotion gate failed to reject transient force!"


def test_arm7_short_prefix_no_sample_in_promotion():
    """Verify short prefix (val_len < 3) never promotes via sample-in variance gain.

    Prefix length = 6:
    t_split = floor(6 * 0.67) = 4, val_len = 6 - 1 - 4 = 1 < 3.
    Even though STLSQ discovers terms with high in-sample variance explanation,
    it must NOT promote because out-of-sample validation cannot be verified.
    """
    env = StaticEnvironment(ground=None)
    c_true = 0.35
    params = PhysicalParameters(linear_damping=0.0)

    body = ActiveBody(
        "ball",
        radius=0.20,
        params=params,
        position=np.array([0.0, 0.0, 5.0]),
        velocity=np.array([3.0, 0.0, 0.0]),
    )

    drag_cb = lambda b: -c_true * np.linalg.norm(b.velocity) * b.velocity
    full_traj = rollout([body], env, num_frames=10, extra_accel_fn=drag_cb)["ball"]
    prefix_6 = {"ball": full_traj[:6]}

    arm7 = SymbolicResidualArm(radii={"ball": 0.20})
    res7 = arm7.predict(prefix_6, env, n_future=5)

    assert "quadratic_drag" in res7.extra["active_terms"]
    assert res7.promoted is False, "Short prefix promoted without sufficient validation frames!"


def test_arm7_multi_body_validation_rejection():
    """Verify validation averages across all active bodies rather than only primary_name.

    Setup:
    - ball1 and ball2 both have quadratic drag in training (frames 0..20). STLSQ discovers drag.
    - In validation (frames 20..30): ball1 still has drag, but ball2 has NO drag.
    - For ball1 alone, gain is high (~1.0).
    - But for ball2, candidate drag degrades prediction.
    - Across all bodies, average gain < PROMOTE_MIN_GAIN -> rejected (promoted=False).
    - A mutant checking only primary_name would erroneously promote (True).
    """
    env = StaticEnvironment(ground=None)
    c_true = 0.35
    params = PhysicalParameters(linear_damping=0.0)

    b1 = ActiveBody("ball1", radius=0.20, params=params, position=np.array([0.0, 0.0, 5.0]), velocity=np.array([3.0, 0.0, 0.0]))
    b2 = ActiveBody("ball2", radius=0.20, params=params, position=np.array([0.0, 3.0, 5.0]), velocity=np.array([3.0, 0.0, 0.0]))

    t1_frames = [b1.copy()]
    t2_frames = [b2.copy()]
    drag_cb = lambda b: -c_true * np.linalg.norm(b.velocity) * b.velocity

    # Frames 0..20: both have drag
    for _ in range(20):
        r1 = rollout([t1_frames[-1].copy()], env, num_frames=1, extra_accel_fn=drag_cb)["ball1"]
        nb1 = ActiveBody("ball1", radius=0.20, params=params, position=r1[1, 0:3], velocity=r1[1, 3:6], orientation=r1[1, 6:10], angular_velocity=r1[1, 10:13])
        t1_frames.append(nb1)

        r2 = rollout([t2_frames[-1].copy()], env, num_frames=1, extra_accel_fn=drag_cb)["ball2"]
        nb2 = ActiveBody("ball2", radius=0.20, params=params, position=r2[1, 0:3], velocity=r2[1, 3:6], orientation=r2[1, 6:10], angular_velocity=r2[1, 10:13])
        t2_frames.append(nb2)

    # Frames 20..30: ball1 continues to have drag, ball2 stops having drag
    for _ in range(10):
        r1 = rollout([t1_frames[-1].copy()], env, num_frames=1, extra_accel_fn=drag_cb)["ball1"]
        nb1 = ActiveBody("ball1", radius=0.20, params=params, position=r1[1, 0:3], velocity=r1[1, 3:6], orientation=r1[1, 6:10], angular_velocity=r1[1, 10:13])
        t1_frames.append(nb1)

        r2 = rollout([t2_frames[-1].copy()], env, num_frames=1, extra_accel_fn=None)["ball2"]
        nb2 = ActiveBody("ball2", radius=0.20, params=params, position=r2[1, 0:3], velocity=r2[1, 3:6], orientation=r2[1, 6:10], angular_velocity=r2[1, 10:13])
        t2_frames.append(nb2)

    arr1 = np.zeros((31, 13), dtype=np.float64)
    arr2 = np.zeros((31, 13), dtype=np.float64)
    for i in range(31):
        arr1[i, 0:3] = t1_frames[i].position
        arr1[i, 3:6] = t1_frames[i].velocity
        arr2[i, 0:3] = t2_frames[i].position
        arr2[i, 3:6] = t2_frames[i].velocity

    prefix_30 = {"ball1": arr1[:30], "ball2": arr2[:30]}
    arm7 = SymbolicResidualArm(radii={"ball1": 0.20, "ball2": 0.20})
    res7 = arm7.predict(prefix_30, env, n_future=5)

    assert "quadratic_drag" in res7.extra["active_terms"]
    # Overall multi-body gain must be rejected
    assert res7.extra["promotion_gain"] < PROMOTE_MIN_GAIN
    assert res7.promoted is False, "Multi-body validation failed to reject inconsistent mechanism!"


def test_prior_rollout_single_source_truth_and_accel_callback():
    """Verify prior.rollout works as single source of truth with and without extra_accel_fn."""
    env = StaticEnvironment(ground=None)
    p = PhysicalParameters()
    b1 = ActiveBody("b1", radius=0.20, params=p, position=np.array([0.0, 0.0, 5.0]), velocity=np.array([2.0, 0.0, 0.0]))
    b2 = ActiveBody("b1", radius=0.20, params=p, position=np.array([0.0, 0.0, 5.0]), velocity=np.array([2.0, 0.0, 0.0]))

    r_def = rollout([b1], env, num_frames=20)
    r_none = rollout([b2], env, num_frames=20, extra_accel_fn=None)

    np.testing.assert_array_equal(r_def["b1"], r_none["b1"])

    # With extra accel, trajectory must differ
    extra_fn = lambda b: np.array([0.0, 0.0, 5.0])
    r_extra = rollout([b1.copy()], env, num_frames=20, extra_accel_fn=extra_fn)
    assert not np.allclose(r_def["b1"], r_extra["b1"])


# =========================================================================
# 4. Prefix Isolation & Future NaN Immunity
# =========================================================================

def test_arms_read_only_prefix_nan_isolation():
    """Verify that arms only read the prefix and never read future frames contaminated with NaNs."""
    theta_deg = 45.0
    theta_rad = math.radians(theta_deg)
    ramp_normal = np.array([0.0, -math.sin(theta_rad), math.cos(theta_rad)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)
    ramp = InclinedRamp(point=np.array([0.0, 0.0, 0.0]), normal=ramp_normal, friction=0.0, restitution=1.0)
    env = StaticEnvironment(ground=None, ramps=[ramp])

    init_pos = ramp.point + 0.20 * ramp_normal + np.array([0.0, 0.0, 0.2])
    init_vel = np.array([0.0, -1.0, -2.0])

    true_p = PhysicalParameters(friction=0.15, restitution=0.75, mass=2.6, linear_damping=0.0, angular_damping=0.0)
    body = ActiveBody("ball", radius=0.20, params=true_p, position=init_pos.copy(), velocity=init_vel.copy())

    full_traj = rollout([body], env, num_frames=40)["ball"]

    # Contaminate frames 30..40 with NaN
    corrupted_traj = full_traj.copy()
    corrupted_traj[30:] = np.nan
    corrupted_prefix = {"ball": corrupted_traj}

    # Clean 30-frame prefix
    clean_prefix = {"ball": full_traj[:30]}

    arms = [
        PriorArm(radii={"ball": 0.20}),
        TrueParamArm(true_p, radii={"ball": 0.20}),
        IdentifyArm(radii={"ball": 0.20}),
        SymbolicResidualArm(radii={"ball": 0.20}),
    ]

    for arm in arms:
        res_clean = arm.predict(clean_prefix, env, n_future=5)
        res_corrupt = arm.predict(corrupted_prefix, env, n_future=5)

        traj_clean = res_clean.positions["ball"]
        traj_corrupt = res_corrupt.positions["ball"]

        assert not np.isnan(traj_corrupt).any(), f"{arm.__class__.__name__} produced NaNs from corrupted future"
        np.testing.assert_allclose(
            traj_clean, traj_corrupt, rtol=1e-12, atol=1e-12,
            err_msg=f"{arm.__class__.__name__} output changed when future had NaNs"
        )


# =========================================================================
# 5. Metrics.py k-Step Horizon Error Integration
# =========================================================================

def test_metrics_k_step_evaluation_with_arms():
    """Verify compute_k_step_position_errors integrates directly with arm rollouts."""
    env = StaticEnvironment(ground=None)
    body = ActiveBody(
        "ball",
        radius=0.20,
        params=PhysicalParameters(linear_damping=0.0),
        position=np.array([0.0, 0.0, 5.0]),
        velocity=np.array([2.0, 0.0, 0.0]),
    )
    full_traj = rollout([body], env, num_frames=40)["ball"]
    prefix_30 = {"ball": full_traj[:30]}

    arm1 = PriorArm(radii={"ball": 0.20})
    res1 = arm1.predict(prefix_30, env, n_future=10)

    # Multi-step error evaluation
    true_positions = full_traj[:, 0:3]
    # Build pred_dict for k in (1, 5, 10)
    pred_dict = {
        1: full_traj[:, 0:3].copy(),
        5: full_traj[:, 0:3].copy(),
        10: full_traj[:, 0:3].copy(),
    }
    # Plug in predicted future at horizon 10
    pred_dict[10][39] = res1.positions["ball"][9]

    errs = compute_k_step_position_errors(pred_dict, true_positions, k_steps=(1, 5, 10), primary_k=10)
    assert "primary_error_m" in errs
    assert errs["primary_k"] == 10
