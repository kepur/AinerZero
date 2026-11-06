"""Tests for E1 biased physical prior integrator and central difference Jacobian.

Covers:
- Analytical case 1: Free fall in vacuum (g = 9.81 m/s^2, z(t) = z0 - 0.5 * g * t^2).
- Analytical case 2: Frictionless inclined plane sliding (a = g * sin(theta)).
- Analytical case 3: Elastic ground bounce (velocity reversal vz' = -e * vz).
- Analytical case 4: Coulomb friction deceleration on flat surface (a = -mu * g).
- Analytical case 5: Ramp pure rolling (a = 5/7 * g * sin(theta), error < 2%).
- Analytical case 6: Ramp rolling with slipping (mu < 2/7 * tan(theta), a = g*sin - mu*g*cos).
- Analytical case 7: StaticBox wall normal bounce with restitution e.
- Analytical case 8: Quaternion attitude integration under constant angular velocity (error < 1e-3 rad).
- Head-on sphere-sphere elastic collision (momentum conservation).
- Central difference Jacobian: sensitivity verification and step-size consistency.
- SVD truncated orthogonal projection basis (cutoff 1e-6 * sigma_max).
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from ainerzero.v9.experiments.e1.jacobian import (
    DEFAULT_REL_STEP,
    DEFAULT_SVD_REL_TOL,
    PARAM_NAMES,
    compute_orthogonal_projection_basis,
    compute_prior_jacobian,
)
from ainerzero.v9.experiments.e1.prior import (
    DEFAULT_BIASED_PRIOR,
    GRAVITY_ACCEL,
    REGISTERED_STRUCTURAL_BIASES,
    ActiveBody,
    GroundPlane,
    InclinedRamp,
    PhysicalParameters,
    StaticBox,
    StaticEnvironment,
    TableTop,
    integrate_quaternion,
    rollout,
    step_substep,
)

pytestmark = pytest.mark.native_mlx(reason="real MLX import at collection via the e1 package (arms_net) (A39)")


# =========================================================================
# 0. Structural Bias Registry Verification
# =========================================================================

def test_registered_structural_biases():
    """Verify all structural biases and surface defaults are registered."""
    assert "collision_geometry" in REGISTERED_STRUCTURAL_BIASES
    assert "inertia_model" in REGISTERED_STRUCTURAL_BIASES
    assert "friction_combine_rule" in REGISTERED_STRUCTURAL_BIASES
    assert "restitution_combine_rule" in REGISTERED_STRUCTURAL_BIASES
    assert "static_surface_defaults" in REGISTERED_STRUCTURAL_BIASES


# =========================================================================
# 1. Analytical Case: Free Fall in Vacuum
# =========================================================================

def test_analytical_free_fall():
    """Verify numerical free fall matches z(t) = z0 - 0.5 * g * t^2."""
    z0 = 10.0
    params = PhysicalParameters(mass=2.0, linear_damping=0.0, angular_damping=0.0)
    body = ActiveBody(
        name="FallingSphere",
        radius=0.5,
        params=params,
        position=np.array([0.0, 0.0, z0], dtype=np.float64),
        velocity=np.zeros(3, dtype=np.float64),
    )
    env = StaticEnvironment(ground=None)

    num_frames = 20  # 1/3 second
    dt_frame = 1.0 / 60.0

    traj = rollout([body], env, num_frames=num_frames)
    pos_history = traj["FallingSphere"][:, 0:3]
    vel_history = traj["FallingSphere"][:, 3:6]

    for frame in range(num_frames + 1):
        t = frame * dt_frame
        expected_z = z0 - 0.5 * GRAVITY_ACCEL * (t**2)
        expected_vz = -GRAVITY_ACCEL * t

        assert pos_history[frame, 2] == pytest.approx(expected_z, abs=0.005)
        assert vel_history[frame, 2] == pytest.approx(expected_vz, abs=0.01)

    # Broken control: Inverted gravity moves object UP instead of DOWN
    broken_traj = rollout([body], env, num_frames=num_frames, g=-GRAVITY_ACCEL)
    broken_z = broken_traj["FallingSphere"][:, 2]
    assert broken_z[-1] > z0
    assert broken_z[-1] > pos_history[-1, 2]


# =========================================================================
# 2. Analytical Case: Frictionless Inclined Plane Sliding
# =========================================================================

def test_analytical_frictionless_inclined_ramp():
    """Verify frictionless inclined plane sliding accelerates at a = g * sin(theta)."""
    theta_deg = 30.0
    theta_rad = math.radians(theta_deg)

    ramp_normal = np.array([0.0, -math.sin(theta_rad), math.cos(theta_rad)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)

    ramp = InclinedRamp(
        point=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        normal=ramp_normal,
        friction=0.0,
        restitution=0.0,
    )
    env = StaticEnvironment(ground=None, ramps=[ramp])

    init_pos = ramp.point + 0.5 * ramp_normal
    params = PhysicalParameters(friction=0.0, restitution=0.0, mass=2.0, linear_damping=0.0)
    body = ActiveBody(
        name="Slider",
        radius=0.5,
        params=params,
        position=init_pos,
        velocity=np.zeros(3, dtype=np.float64),
    )

    num_frames = 20
    dt_frame = 1.0 / 60.0
    traj = rollout([body], env, num_frames=num_frames)
    vel = traj["Slider"][:, 3:6]

    a_slope = GRAVITY_ACCEL * math.sin(theta_rad)
    t_end = num_frames * dt_frame
    expected_speed_end = a_slope * t_end

    speed_end = np.linalg.norm(vel[-1])
    assert speed_end == pytest.approx(expected_speed_end, rel=0.05)


# =========================================================================
# 3. Analytical Case: Elastic & Inelastic Ground Bounce
# =========================================================================

def test_ground_bounce_restitution():
    """Verify velocity reversal ratio matches restitution parameter e."""
    radius = 0.4
    e_test = 0.75

    params = PhysicalParameters(
        friction=0.0,
        restitution=e_test,
        mass=1.5,
        linear_damping=0.0,
        angular_damping=0.0,
    )
    ground = GroundPlane(z_plane=0.0, friction=0.0, restitution=e_test)
    env = StaticEnvironment(ground=ground)

    v_in = -4.0
    body = ActiveBody(
        name="BouncingBall",
        radius=radius,
        params=params,
        position=np.array([0.0, 0.0, 0.5], dtype=np.float64),
        velocity=np.array([0.0, 0.0, v_in], dtype=np.float64),
    )

    traj = rollout([body], env, num_frames=10)
    vel_z = traj["BouncingBall"][:, 5]

    v_out = np.max(vel_z)
    assert v_out > 0.0
    assert v_out == pytest.approx(e_test * abs(v_in), rel=0.05)

    # Broken control: Zero restitution (e=0) produces zero bounce
    params_zero_e = PhysicalParameters(restitution=0.0, mass=1.5, linear_damping=0.0)
    ground_zero_e = GroundPlane(z_plane=0.0, friction=0.0, restitution=0.0)
    body_zero_e = ActiveBody(
        name="DeadBall",
        radius=radius,
        params=params_zero_e,
        position=np.array([0.0, 0.0, 0.5], dtype=np.float64),
        velocity=np.array([0.0, 0.0, v_in], dtype=np.float64),
    )
    traj_zero = rollout([body_zero_e], StaticEnvironment(ground=ground_zero_e), num_frames=10)
    assert np.max(traj_zero["DeadBall"][:, 5]) == pytest.approx(0.0, abs=1e-3)


# =========================================================================
# 4. Analytical Case: Coulomb Friction Deceleration
# =========================================================================

def test_flat_ground_coulomb_friction():
    """Verify horizontal sliding decelerates with a = -mu * g during sliding phase."""
    mu = 0.30
    params = PhysicalParameters(friction=mu, restitution=0.0, mass=1.0, linear_damping=0.0)
    ground = GroundPlane(z_plane=0.0, friction=mu, restitution=0.0)
    env = StaticEnvironment(ground=ground)

    v0_x = 3.0
    body = ActiveBody(
        name="Slider",
        radius=0.5,
        params=params,
        position=np.array([0.0, 0.0, 0.5], dtype=np.float64),
        velocity=np.array([v0_x, 0.0, 0.0], dtype=np.float64),
    )

    traj = rollout([body], env, num_frames=10)
    vel_x = traj["Slider"][:, 3]

    dt_frame = 1.0 / 60.0
    for frame in range(1, 10):
        t = frame * dt_frame
        expected_v = max(0.0, v0_x - mu * GRAVITY_ACCEL * t)
        assert vel_x[frame] == pytest.approx(expected_v, abs=0.05)


# =========================================================================
# 5. Analytical Case: Ramp Pure Rolling (a = 5/7 * g * sin(theta), error < 2%)
# =========================================================================

def test_analytical_ramp_pure_rolling():
    """Verify pure rolling of a solid sphere down an incline with mu >= 2/7 * tan(theta).

    Theoretical acceleration: a = 5/7 * g * sin(theta).
    For theta = 20 deg, g = 9.81 m/s^2:
    a_theo = 5/7 * 9.81 * sin(20 deg) = 2.396584 m/s^2.
    """
    theta_deg = 20.0
    theta_rad = math.radians(theta_deg)
    radius = 0.20
    mass = 2.0
    mu = 0.50  # mu >= 2/7 * tan(20 deg) ~ 0.104 -> pure rolling holds

    # Ramp surface passing through origin with outward normal (0, -sin(theta), cos(theta))
    # Downhill tangent direction is (0, -cos(theta), -sin(theta))
    ramp_normal = np.array([0.0, -math.sin(theta_rad), math.cos(theta_rad)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)

    ramp = InclinedRamp(
        point=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        normal=ramp_normal,
        friction=mu,
        restitution=0.20,
    )
    env = StaticEnvironment(ground=None, ramps=[ramp])

    init_pos = ramp.point + radius * ramp_normal
    params = PhysicalParameters(
        friction=mu,
        restitution=0.20,
        mass=mass,
        linear_damping=0.0,
        angular_damping=0.0,
    )
    body = ActiveBody(
        name="RollingSphere",
        radius=radius,
        params=params,
        position=init_pos,
        velocity=np.zeros(3, dtype=np.float64),
        angular_velocity=np.zeros(3, dtype=np.float64),
    )

    num_frames = 60  # 1.0 second
    traj = rollout([body], env, num_frames=num_frames)

    vel = traj["RollingSphere"][:, 3:6]
    omega = traj["RollingSphere"][:, 10:13]

    speed_1s = np.linalg.norm(vel[-1])
    omega_1s = np.linalg.norm(omega[-1])

    a_theo = (5.0 / 7.0) * GRAVITY_ACCEL * math.sin(theta_rad)
    v_theo = a_theo * 1.0  # after 1 second

    # Relative error must be < 2%
    rel_err_v = abs(speed_1s - v_theo) / v_theo
    assert rel_err_v < 0.02, f"Pure rolling speed rel error {rel_err_v:.4e} exceeds 2%"

    # Pure rolling kinematic constraint: v = omega * R
    expected_omega = speed_1s / radius
    rel_err_w = abs(omega_1s - expected_omega) / expected_omega
    assert rel_err_w < 0.02, f"Rolling constraint |v - w*R| rel error {rel_err_w:.4e} exceeds 2%"


# =========================================================================
# 6. Analytical Case: Ramp Rolling with Slipping (mu < 2/7 * tan(theta))
# =========================================================================

def test_analytical_ramp_rolling_with_slipping():
    """Verify rolling with slipping when friction is below the pure rolling threshold.

    When mu < 2/7 * tan(theta):
    a = g * sin(theta) - mu * g * cos(theta)
    alpha = 5 * mu * g * cos(theta) / (2 * R)
    """
    theta_deg = 20.0
    theta_rad = math.radians(theta_deg)
    radius = 0.20
    mass = 2.0
    mu = 0.05  # mu < 2/7 * tan(20 deg) ~ 0.104 -> sliding while rolling

    ramp_normal = np.array([0.0, -math.sin(theta_rad), math.cos(theta_rad)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)

    ramp = InclinedRamp(
        point=np.array([0.0, 0.0, 0.0], dtype=np.float64),
        normal=ramp_normal,
        friction=mu,
        restitution=0.20,
    )
    env = StaticEnvironment(ground=None, ramps=[ramp])

    init_pos = ramp.point + radius * ramp_normal
    params = PhysicalParameters(
        friction=mu,
        restitution=0.20,
        mass=mass,
        linear_damping=0.0,
        angular_damping=0.0,
    )
    body = ActiveBody(
        name="SlippingSphere",
        radius=radius,
        params=params,
        position=init_pos,
        velocity=np.zeros(3, dtype=np.float64),
        angular_velocity=np.zeros(3, dtype=np.float64),
    )

    num_frames = 60  # 1.0 second
    traj = rollout([body], env, num_frames=num_frames)

    vel = traj["SlippingSphere"][:, 3:6]
    omega = traj["SlippingSphere"][:, 10:13]

    speed_1s = np.linalg.norm(vel[-1])
    omega_1s = np.linalg.norm(omega[-1])

    # Analytical solutions:
    a_theo = GRAVITY_ACCEL * math.sin(theta_rad) - mu * GRAVITY_ACCEL * math.cos(theta_rad)
    v_theo = a_theo * 1.0
    alpha_theo = (5.0 * mu * GRAVITY_ACCEL * math.cos(theta_rad)) / (2.0 * radius)
    omega_theo = alpha_theo * 1.0

    rel_err_v = abs(speed_1s - v_theo) / v_theo
    rel_err_w = abs(omega_1s - omega_theo) / omega_theo

    assert rel_err_v < 0.02, f"Rolling with slipping v error {rel_err_v:.4e} exceeds 2%"
    assert rel_err_w < 0.02, f"Rolling with slipping omega error {rel_err_w:.4e} exceeds 2%"


# =========================================================================
# 7. Analytical Case: StaticBox Wall Normal Bounce
# =========================================================================

def test_analytical_box_wall_normal_bounce():
    """Verify normal bounce against a StaticBox wall matches restitution coefficient e."""
    e_wall = 0.70
    box = StaticBox(
        min_point=np.array([5.0, -5.0, 0.0], dtype=np.float64),
        max_point=np.array([6.0, 5.0, 5.0], dtype=np.float64),
        friction=0.0,
        restitution=e_wall,
    )
    env = StaticEnvironment(ground=None, boxes=[box])

    v_in_x = 3.0
    radius = 0.25
    body = ActiveBody(
        name="BoxBouncer",
        radius=radius,
        params=PhysicalParameters(friction=0.0, restitution=e_wall, mass=1.5, linear_damping=0.0),
        position=np.array([4.5, 0.0, 2.0], dtype=np.float64),
        velocity=np.array([v_in_x, 0.0, 0.0], dtype=np.float64),
    )

    # Hits the wall at x=5.0 and bounces backwards
    traj = rollout([body], env, num_frames=15, g=0.0)
    vel_x = traj["BoxBouncer"][:, 3]

    # After bounce, vx should be approximately -e * v_in_x = -2.10 m/s
    min_vx = np.min(vel_x)
    assert min_vx < 0.0
    assert abs(min_vx - (-e_wall * v_in_x)) < 0.05


# =========================================================================
# 8. Analytical Case: Quaternion Attitude Constant Rotation
# =========================================================================

def test_analytical_quaternion_constant_rotation():
    """Verify quaternion attitude integration under constant angular velocity has error < 1e-3 rad."""
    omega_const = np.array([0.3, 0.5, 0.82], dtype=np.float64)
    omega_norm = float(np.linalg.norm(omega_const))

    body = ActiveBody(
        name="SpinningSphere",
        radius=0.5,
        params=PhysicalParameters(mass=1.0, linear_damping=0.0, angular_damping=0.0),
        position=np.zeros(3, dtype=np.float64),
        velocity=np.zeros(3, dtype=np.float64),
        orientation=np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64),
        angular_velocity=omega_const.copy(),
    )
    env = StaticEnvironment(ground=None)

    # 60 frames = 1.0 second in free space without gravity
    traj = rollout([body], env, num_frames=60, g=0.0)
    q_sim = traj["SpinningSphere"][-1, 6:10]

    # Analytical axis-angle rotation after 1.0 s
    total_angle = omega_norm * 1.0
    axis = omega_const / omega_norm
    half_angle = 0.5 * total_angle
    q_analytical = np.array(
        [
            math.cos(half_angle),
            axis[0] * math.sin(half_angle),
            axis[1] * math.sin(half_angle),
            axis[2] * math.sin(half_angle),
        ],
        dtype=np.float64,
    )

    # Angular error between two unit quaternions: 2 * arccos(|dot|)
    dot_prod = abs(float(np.dot(q_sim, q_analytical)))
    angle_error = 2.0 * math.acos(min(1.0, dot_prod))

    assert angle_error < 1e-3, f"Quaternion attitude error {angle_error:.4e} exceeds 1e-3 rad"


# =========================================================================
# 9. Head-on Elastic Body Collision (Momentum Conservation)
# =========================================================================

def test_head_on_body_collision_momentum_conservation():
    """Verify momentum is conserved during inter-body bounding sphere collision."""
    m1 = 2.0
    m2 = 3.0
    v1 = 4.0
    v2 = -2.0

    p1 = PhysicalParameters(mass=m1, restitution=1.0, friction=0.0, linear_damping=0.0)
    p2 = PhysicalParameters(mass=m2, restitution=1.0, friction=0.0, linear_damping=0.0)

    b1 = ActiveBody("Ball1", radius=0.5, params=p1, position=np.array([-1.0, 0.0, 5.0]), velocity=np.array([v1, 0.0, 0.0]))
    b2 = ActiveBody("Ball2", radius=0.5, params=p2, position=np.array([1.0, 0.0, 5.0]), velocity=np.array([v2, 0.0, 0.0]))

    env = StaticEnvironment(ground=None)
    traj = rollout([b1, b2], env, num_frames=15, g=0.0)

    initial_momentum = m1 * v1 + m2 * v2
    final_v1 = traj["Ball1"][-1, 3]
    final_v2 = traj["Ball2"][-1, 3]
    final_momentum = m1 * final_v1 + m2 * final_v2

    assert final_momentum == pytest.approx(initial_momentum, rel=1e-4)


# =========================================================================
# 10. Central Difference Jacobian & Sensitivity
# =========================================================================

def test_central_difference_jacobian():
    """Verify Jacobian computation w.r.t physical parameters with 13-dim state."""
    params = DEFAULT_BIASED_PRIOR.copy()
    body = ActiveBody(
        name="TargetActor",
        radius=0.5,
        params=params,
        position=np.array([0.0, 0.0, 3.0]),
        velocity=np.array([1.0, 0.0, 0.0]),
    )
    env = StaticEnvironment(ground=GroundPlane())

    jac = compute_prior_jacobian([body], env, num_frames=10, rel_step=DEFAULT_REL_STEP)

    assert set(jac.keys()) == set(PARAM_NAMES)
    for p_name in PARAM_NAMES:
        assert jac[p_name].shape == (11, 13)
        assert np.all(np.isfinite(jac[p_name]))

    # Verify sensitivity: increasing linear_damping must slow down the body
    d_v_d_damping = jac["linear_damping"][:, 3]  # vx component
    assert d_v_d_damping[-1] < 0.0


def test_central_difference_jacobian_symmetry_and_order():
    """Verify Jacobian uses symmetric central difference (cancelling O(h) one-sided bias)."""
    body = ActiveBody(
        name="TargetActor",
        radius=0.5,
        params=DEFAULT_BIASED_PRIOR.copy(),
        position=np.array([0.0, 0.0, 3.0], dtype=np.float64),
        velocity=np.array([1.0, 0.0, 0.0], dtype=np.float64),
    )
    env = StaticEnvironment(ground=GroundPlane())

    step_h = 0.05
    jac = compute_prior_jacobian([body], env, num_frames=10, rel_step=step_h)

    # Compute independent positive and negative perturbations
    p_idx = 3  # linear_damping
    orig_p = body.params.to_array()
    p_val = orig_p[p_idx]
    h = p_val * step_h

    body_p = body.copy()
    arr_p = orig_p.copy()
    arr_p[p_idx] = p_val + h
    body_p.params = PhysicalParameters.from_array(arr_p)

    body_m = body.copy()
    arr_m = orig_p.copy()
    arr_m[p_idx] = p_val - h
    body_m.params = PhysicalParameters.from_array(arr_m)

    traj_plus = rollout([body_p], env, num_frames=10)["TargetActor"]
    traj_minus = rollout([body_m], env, num_frames=10)["TargetActor"]
    traj_orig = rollout([body], env, num_frames=10)["TargetActor"]

    forward_diff = (traj_plus - traj_orig) / h
    backward_diff = (traj_orig - traj_minus) / h
    central_diff = (traj_plus - traj_minus) / (2.0 * h)

    # Exact match with central difference
    assert np.allclose(jac["linear_damping"], central_diff, atol=1e-10)

    # Curvature verification: forward and central difference must diverge
    diff_forward_central = float(np.linalg.norm(forward_diff - central_diff))
    assert diff_forward_central > 5e-5, "Forward difference must diverge from central difference"


# =========================================================================
# 11. SVD Truncated Orthogonal Projection Basis
# =========================================================================

def test_svd_orthogonal_projection_basis():
    """Verify SVD basis truncation and orthogonality."""
    rng = np.random.default_rng(101)
    J = rng.normal(size=(30, 5))

    basis, s_vals = compute_orthogonal_projection_basis(J, rel_svd_tol=DEFAULT_SVD_REL_TOL)
    assert basis.ndim == 2
    assert basis.shape[0] == 30
    assert basis.shape[1] <= 5

    gram = np.dot(basis.T, basis)
    assert np.allclose(gram, np.eye(basis.shape[1]), atol=1e-6)
