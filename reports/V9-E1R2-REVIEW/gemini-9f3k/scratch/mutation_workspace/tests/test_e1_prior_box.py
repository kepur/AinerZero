"""Analytical verification and regression tests for box contact using support functions.

Covers:
- Sphere regression: Bitwise identical reproduction of before-revision trajectories.
- Resting box on ground: 1.2x1.2x1.0 box on ground (z=0.5), flat and rotated 45 deg around z.
  Over 600 frames: |Delta z| < 1e-4, horizontal drift < 1e-4.
- Resting box on tabletop: TableTop at z_top=1.7, 0.7x0.7x0.6 box at z=2.0.
  Over 600 frames: error < 1e-4.
- Stacking: Two 1x1x1 boxes at z=0.5 and z=1.5, rolled out 120 frames.
  Both boxes have |Delta z| < 1e-3.
- Sliding deceleration: Box on ground sliding with v0=(2,0,0), decelerating at a = -mu_eff * g
  until stopped (relative error < 2%).
- Incline sliding: Box on inclined plane of angle theta sliding down with acceleration
  a = g * (sin(theta) - mu_eff * cos(theta)) (relative error < 3%).
- Sticking impulse: Box sticking impulse J_stick = |v_ct| / (1/m + h^2/I) vs legacy 2/7*m*|v_ct|.
- Support distance analytical verification: Spheres vs oriented boxes.
- Backward compatibility of make_active_body_from_state: half_extents=None preserves sphere behavior.
"""

from __future__ import annotations

import math
from pathlib import Path
import numpy as np
import pytest

from ainerzero.v9.experiments.e1.prior import (
    ActiveBody,
    GroundPlane,
    InclinedRamp,
    PhysicalParameters,
    StaticEnvironment,
    TableTop,
    EDGE_AXIS_PREFERENCE_M,
    GRAVITY_ACCEL,
    _box_interbody_contact,
    _obb_obb_contact,
    _sphere_obb_contact,
    make_active_body_from_state,
    quaternion_to_rotation_matrix,
    rollout,
    step_substep,
    support_distance,
)

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "e1_prior_sphere_regression.npz"


# =========================================================================
# 1. Sphere Regression (Bitwise Identical to Pre-Revision Integrator)
# =========================================================================

def test_sphere_regression_bitwise_identical():
    """Verify sphere trajectories remain bitwise identical to the baseline fixtures."""
    assert FIXTURES_PATH.exists(), f"Regression fixtures not found at {FIXTURES_PATH}"
    data = np.load(FIXTURES_PATH)

    # Scenario 1: Ground landing & bounce
    b1 = ActiveBody(
        name="SphereGround",
        radius=0.4,
        params=PhysicalParameters(
            friction=0.3, restitution=0.5, mass=1.5, linear_damping=0.05, angular_damping=0.05
        ),
        position=np.array([0.0, 0.0, 2.0], dtype=np.float64),
        velocity=np.array([1.0, 0.0, -1.0], dtype=np.float64),
    )
    env1 = StaticEnvironment(ground=GroundPlane(z_plane=0.0, friction=0.4, restitution=0.6))
    traj1 = rollout([b1], env1, num_frames=60)
    np.testing.assert_array_equal(traj1["SphereGround"], data["ground"])

    # Scenario 2: Ramp roll
    theta = math.radians(25.0)
    ramp_normal = np.array([0.0, -math.sin(theta), math.cos(theta)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)
    ramp = InclinedRamp(point=np.array([0.0, 0.0, 0.0]), normal=ramp_normal, friction=0.3, restitution=0.2)
    env2 = StaticEnvironment(ground=None, ramps=[ramp])
    b2 = ActiveBody(
        name="SphereRamp",
        radius=0.25,
        params=PhysicalParameters(
            friction=0.2, restitution=0.2, mass=2.0, linear_damping=0.0, angular_damping=0.0
        ),
        position=ramp.point + 0.25 * ramp_normal,
        velocity=np.zeros(3),
    )
    traj2 = rollout([b2], env2, num_frames=60)
    np.testing.assert_array_equal(traj2["SphereRamp"], data["ramp"])

    # Scenario 3: Two sphere collision
    b3a = ActiveBody(
        name="SphereA",
        radius=0.3,
        params=PhysicalParameters(
            friction=0.25, restitution=0.7, mass=1.8, linear_damping=0.0, angular_damping=0.0
        ),
        position=np.array([-1.0, 0.0, 0.5]),
        velocity=np.array([2.5, 0.5, 0.0]),
    )
    b3b = ActiveBody(
        name="SphereB",
        radius=0.35,
        params=PhysicalParameters(
            friction=0.35, restitution=0.8, mass=2.2, linear_damping=0.0, angular_damping=0.0
        ),
        position=np.array([1.0, 0.0, 0.5]),
        velocity=np.array([-1.5, -0.2, 0.0]),
    )
    env3 = StaticEnvironment(ground=GroundPlane(z_plane=0.0))
    traj3 = rollout([b3a, b3b], env3, num_frames=60)
    np.testing.assert_array_equal(traj3["SphereA"], data["collision_a"])
    np.testing.assert_array_equal(traj3["SphereB"], data["collision_b"])


# =========================================================================
# 2. Resting Box on Ground (Flat and 45-degree Yaw)
# =========================================================================

def test_box_resting_ground_flat_and_rotated():
    """Verify 1.2x1.2x1.0 box on ground (z=0.5) remains static for 600 frames.

    Requirements:
    - damping = 0.
    - Flat orientation: |Delta z| < 1e-4, horizontal drift < 1e-4.
    - Rotated 45 degrees around Z: identical bounds.
    """
    dims = np.array([1.2, 1.2, 1.0])
    half_extents = dims / 2.0  # [0.6, 0.6, 0.5]
    radius = float(np.linalg.norm(half_extents))  # ~0.985
    params = PhysicalParameters(friction=0.5, restitution=0.3, mass=2.0, linear_damping=0.0, angular_damping=0.0)
    env = StaticEnvironment(ground=GroundPlane(z_plane=0.0))

    # (a) Flat orientation
    b_flat = ActiveBody(
        name="BoxFlat",
        radius=radius,
        half_extents=half_extents,
        params=params,
        position=np.array([0.0, 0.0, 0.5]),
        velocity=np.zeros(3),
    )
    traj_flat = rollout([b_flat], env, num_frames=600)["BoxFlat"]
    max_dz_flat = float(np.max(np.abs(traj_flat[:, 2] - 0.5)))
    max_dxy_flat = float(np.max(np.linalg.norm(traj_flat[:, 0:2], axis=1)))

    assert max_dz_flat < 1e-4, f"Flat box vertical error {max_dz_flat:.4e} >= 1e-4"
    assert max_dxy_flat < 1e-4, f"Flat box horizontal drift {max_dxy_flat:.4e} >= 1e-4"

    # (b) 45-degree rotation around Z axis
    theta = np.pi / 4.0
    q_z45 = np.array([math.cos(theta / 2.0), 0.0, 0.0, math.sin(theta / 2.0)], dtype=np.float64)
    b_rot = ActiveBody(
        name="BoxRot",
        radius=radius,
        half_extents=half_extents,
        params=params,
        position=np.array([0.0, 0.0, 0.5]),
        velocity=np.zeros(3),
        orientation=q_z45,
    )
    traj_rot = rollout([b_rot], env, num_frames=600)["BoxRot"]
    max_dz_rot = float(np.max(np.abs(traj_rot[:, 2] - 0.5)))
    max_dxy_rot = float(np.max(np.linalg.norm(traj_rot[:, 0:2], axis=1)))

    assert max_dz_rot < 1e-4, f"Rotated box vertical error {max_dz_rot:.4e} >= 1e-4"
    assert max_dxy_rot < 1e-4, f"Rotated box horizontal drift {max_dxy_rot:.4e} >= 1e-4"


# =========================================================================
# 3. Resting Box on TableTop
# =========================================================================

def test_box_resting_tabletop():
    """Verify 0.7x0.7x0.6 box resting on tabletop at z_top=1.7 (center z=2.0).

    Requirements:
    - z_top = 1.7, half-height = 0.3 -> center z = 2.0.
    - Error < 1e-4 over 600 frames.
    """
    table = TableTop(z_top=1.7, x_bounds=(-2.0, 2.0), y_bounds=(-2.0, 2.0), thickness=0.20)
    env = StaticEnvironment(ground=None, tables=[table])

    dims = np.array([0.7, 0.7, 0.6])
    half_extents = dims / 2.0  # [0.35, 0.35, 0.30]
    radius = float(np.linalg.norm(half_extents))
    params = PhysicalParameters(friction=0.5, restitution=0.3, mass=1.5, linear_damping=0.0, angular_damping=0.0)

    b_table = ActiveBody(
        name="TableBox",
        radius=radius,
        half_extents=half_extents,
        params=params,
        position=np.array([0.0, 0.0, 2.0]),
        velocity=np.zeros(3),
    )
    traj = rollout([b_table], env, num_frames=600)["TableBox"]
    max_dz = float(np.max(np.abs(traj[:, 2] - 2.0)))
    max_dxy = float(np.max(np.linalg.norm(traj[:, 0:2], axis=1)))

    assert max_dz < 1e-4, f"Tabletop box vertical error {max_dz:.4e} >= 1e-4"
    assert max_dxy < 1e-4, f"Tabletop box horizontal drift {max_dxy:.4e} >= 1e-4"


# =========================================================================
# 4. Box Stacking
# =========================================================================

def test_box_stacking():
    """Verify stacking of two 1x1x1 boxes at z=0.5 and z=1.5 for 120 frames.

    Requirements:
    - Both |Delta z| < 1e-3.
    """
    half_extents = np.array([0.5, 0.5, 0.5])
    radius = float(np.linalg.norm(half_extents))
    params = PhysicalParameters(friction=0.5, restitution=0.0, mass=2.0, linear_damping=0.0, angular_damping=0.0)
    env = StaticEnvironment(ground=GroundPlane(z_plane=0.0))

    b_bottom = ActiveBody(
        name="BoxBottom",
        radius=radius,
        half_extents=half_extents,
        params=params,
        position=np.array([0.0, 0.0, 0.5]),
        velocity=np.zeros(3),
    )
    b_top = ActiveBody(
        name="BoxTop",
        radius=radius,
        half_extents=half_extents,
        params=params,
        position=np.array([0.0, 0.0, 1.5]),
        velocity=np.zeros(3),
    )
    traj = rollout([b_bottom, b_top], env, num_frames=120)

    max_dz_bottom = float(np.max(np.abs(traj["BoxBottom"][:, 2] - 0.5)))
    max_dz_top = float(np.max(np.abs(traj["BoxTop"][:, 2] - 1.5)))

    assert max_dz_bottom < 1e-3, f"Bottom box vertical error {max_dz_bottom:.4e} >= 1e-3"
    assert max_dz_top < 1e-3, f"Top box vertical error {max_dz_top:.4e} >= 1e-3"


# =========================================================================
# 5. Sliding Deceleration on Ground
# =========================================================================

def test_box_sliding_deceleration():
    """Verify flat sliding box with v0=(2,0,0) decelerates at a = -mu_eff * g until stopped.

    Requirements:
    - mu_eff is arithmetic mean of body and ground friction.
    - Deceleration relative error < 2% throughout sliding until stopped.
    """
    half_extents = np.array([0.5, 0.5, 0.001])
    radius = float(np.linalg.norm(half_extents))
    mu_b = 0.40
    mu_g = 0.60
    mu_eff = 0.5 * (mu_b + mu_g)  # 0.50

    params = PhysicalParameters(friction=mu_b, restitution=0.0, mass=2.0, linear_damping=0.0, angular_damping=0.0)
    env = StaticEnvironment(ground=GroundPlane(z_plane=0.0, friction=mu_g, restitution=0.0))

    v0 = 2.0
    b = ActiveBody(
        name="Slider",
        radius=radius,
        half_extents=half_extents,
        params=params,
        position=np.array([0.0, 0.0, 0.001]),
        velocity=np.array([v0, 0.0, 0.0]),
    )
    # Stop time: 2.0 / (0.5 * 9.81) = 0.407747 s -> ~25 frames at 60 fps
    traj = rollout([b], env, num_frames=30)["Slider"]
    vel_x = traj[:, 3]

    # Verify frame-by-frame linear deceleration during sliding
    dt_frame = 1.0 / 60.0
    a_expected = mu_eff * GRAVITY_ACCEL

    # Find the frame where the box reaches rest
    stopped_indices = np.where(vel_x <= 1e-4)[0]
    assert len(stopped_indices) > 0, "Box failed to stop within 30 frames"
    stop_frame = int(stopped_indices[0])

    # Check that all frames before stop_frame follow v(t) = v0 - a*t with < 2% relative error
    for f in range(1, stop_frame):
        t = f * dt_frame
        expected_v = v0 - a_expected * t
        rel_err = abs(vel_x[f] - expected_v) / v0
        assert rel_err < 0.02, f"Frame {f} speed error {rel_err:.4%} exceeds 2%"

    # Check average measured deceleration up to the last moving frame
    last_moving_frame = stop_frame - 1
    t_last = last_moving_frame * dt_frame
    a_measured = (v0 - vel_x[last_moving_frame]) / t_last
    rel_err_a = abs(a_measured - a_expected) / a_expected
    assert rel_err_a < 0.02, f"Measured deceleration error {rel_err_a:.4%} exceeds 2%"

    # Verify it stays stopped
    assert vel_x[-1] < 1e-4, f"Box did not remain stopped: vx={vel_x[-1]}"


# =========================================================================
# 6. Incline Sliding Acceleration
# =========================================================================

def test_box_incline_sliding():
    """Verify box sliding down incline theta accelerates at g*(sin(theta) - mu_eff*cos(theta)).

    Requirements:
    - Relative error < 3%.
    - mu_eff chosen small enough to ensure sliding downwards.
    """
    theta_deg = 30.0
    theta_rad = math.radians(theta_deg)
    ramp_normal = np.array([0.0, -math.sin(theta_rad), math.cos(theta_rad)], dtype=np.float64)
    ramp_normal /= np.linalg.norm(ramp_normal)

    mu_ramp = 0.10
    mu_box = 0.10
    mu_eff = 0.5 * (mu_ramp + mu_box)  # 0.10 (tan(30) ~ 0.577 >> 0.10)

    ramp = InclinedRamp(point=np.array([0.0, 0.0, 0.0]), normal=ramp_normal, friction=mu_ramp, restitution=0.0)
    env = StaticEnvironment(ground=None, ramps=[ramp])

    half_extents = np.array([0.5, 0.5, 0.001])
    radius = float(np.linalg.norm(half_extents))
    params = PhysicalParameters(friction=mu_box, restitution=0.0, mass=2.0, linear_damping=0.0, angular_damping=0.0)

    b = ActiveBody(
        name="RampSlider",
        radius=radius,
        half_extents=half_extents,
        params=params,
        position=ramp.point + 0.001 * ramp_normal,
        velocity=np.zeros(3),
    )
    num_frames = 60  # 1.0 s
    traj = rollout([b], env, num_frames=num_frames)["RampSlider"]

    vel_end = traj[-1, 3:6]
    speed_end = float(np.linalg.norm(vel_end))

    t_total = num_frames * (1.0 / 60.0)
    a_measured = speed_end / t_total
    a_expected = GRAVITY_ACCEL * (math.sin(theta_rad) - mu_eff * math.cos(theta_rad))
    rel_err = abs(a_measured - a_expected) / a_expected

    assert rel_err < 0.03, f"Incline acceleration error {rel_err:.4%} exceeds 3%"


# =========================================================================
# 7. Sticking Tangential Impulse Generalization vs Legacy Formula
# =========================================================================

def test_box_sticking_tangential_impulse():
    """Verify generalized sticking impulse J_stick = |v_ct| / (1/m + h^2/I).

    Under small tangential velocity (J_stick < J_max), the velocity increment
    delta_v = -J_stick / m differs significantly from legacy 2/7 * |v_ct| when h != R.
    """
    he = np.array([0.6, 0.6, 0.5])
    R = float(np.linalg.norm(he))  # ~0.984886
    m = 2.0
    b = ActiveBody(
        name="BoxStick",
        radius=R,
        half_extents=he,
        params=PhysicalParameters(friction=0.5, restitution=0.0, mass=m, linear_damping=0.0, angular_damping=0.0),
        position=np.array([0.0, 0.0, 0.499999]),  # Slight penetration to trigger contact
        velocity=np.array([0.001, 0.0, 0.0]),
    )
    env = StaticEnvironment(ground=GroundPlane(z_plane=0.0, friction=0.5))

    v0_x = b.velocity[0]
    step_substep([b], env)
    actual_dv = b.velocity[0] - v0_x

    # Analytical calculation:
    I = 0.4 * m * (R**2)
    h = 0.5
    denom = 1.0 / m + (h**2) / I
    expected_dv = -(0.001 / denom) / m

    # Legacy formula: J_stick_legacy = (2/7) * m * |v_ct| -> dv_legacy = - (2/7) * |v_ct|
    legacy_dv = -(2.0 / 7.0) * 0.001

    assert actual_dv == pytest.approx(expected_dv, rel=1e-5)
    # Ensure significant divergence from legacy formula (proving mutation sensitivity)
    assert abs(actual_dv - legacy_dv) > 1e-4


# =========================================================================
# 8. Support Distance Analytical Verification
# =========================================================================

def test_support_distance_analytical():
    """Verify support_distance on spheres and oriented boxes."""
    # Sphere: always returns radius
    sphere = ActiveBody(
        name="Sphere",
        radius=0.45,
        half_extents=None,
        params=PhysicalParameters(),
        position=np.zeros(3),
        velocity=np.zeros(3),
    )
    for n in [np.array([0, 0, 1]), np.array([1, 0, 0]), np.array([0.5, 0.5, 0.707])]:
        assert support_distance(sphere, n) == pytest.approx(0.45)

    # Box: sum_i e_i * |n . a_i|
    box = ActiveBody(
        name="Box",
        radius=1.0,
        half_extents=np.array([0.6, 0.4, 0.2]),
        params=PhysicalParameters(),
        position=np.zeros(3),
        velocity=np.zeros(3),
    )
    # Axis-aligned normals
    assert support_distance(box, np.array([1, 0, 0])) == pytest.approx(0.6)
    assert support_distance(box, np.array([0, 1, 0])) == pytest.approx(0.4)
    assert support_distance(box, np.array([0, 0, 1])) == pytest.approx(0.2)
    # Negative normals (absolute value test)
    assert support_distance(box, np.array([-1, 0, 0])) == pytest.approx(0.6)
    assert support_distance(box, np.array([0, -1, 0])) == pytest.approx(0.4)
    assert support_distance(box, np.array([0, 0, -1])) == pytest.approx(0.2)

    # 45 deg around Z
    theta = math.pi / 4.0
    box.orientation = np.array([math.cos(theta / 2.0), 0.0, 0.0, math.sin(theta / 2.0)])
    # along (1, 0, 0): projection is e_0 * |cos(45)| + e_1 * |-sin(45)| = (0.6 + 0.4)*sqrt(2)/2 = 1.0 * 0.70710678
    expected_h = (0.6 + 0.4) * math.cos(math.pi / 4.0)
    assert support_distance(box, np.array([1, 0, 0])) == pytest.approx(expected_h)
    # Z normal is unaffected by Z rotation
    assert support_distance(box, np.array([0, 0, 1])) == pytest.approx(0.2)


# =========================================================================
# 9. make_active_body_from_state Backward Compatibility
# =========================================================================

def test_make_active_body_compatibility():
    """Verify make_active_body_from_state maintains backwards compatibility."""
    state = np.array([1.0, 2.0, 3.0, 0.1, 0.2, 0.3, 1.0, 0.0, 0.0, 0.0, 0.01, 0.02, 0.03])
    params = PhysicalParameters()

    # Without half_extents -> None
    b_sphere = make_active_body_from_state("S", state, params, radius=0.4)
    assert b_sphere.half_extents is None
    assert b_sphere.radius == 0.4
    assert np.array_equal(b_sphere.position, state[0:3])

    # With half_extents -> box
    he = np.array([0.5, 0.4, 0.3])
    b_box = make_active_body_from_state("B", state, params, radius=0.7, half_extents=he)
    assert b_box.half_extents is not None
    assert np.array_equal(b_box.half_extents, he)
    assert b_box.radius == 0.7


# =========================================================================
# Inter-body contact geometry (r2): exact normal and depth
# =========================================================================

def _box(name, pos, half, *, vel=(0.0, 0.0, 0.0), ori=(1.0, 0.0, 0.0, 0.0), mass=2.0):
    half_arr = np.array(half, dtype=np.float64)
    return ActiveBody(
        name=name,
        radius=float(np.linalg.norm(half_arr)),
        params=PhysicalParameters(friction=0.5, restitution=0.0, mass=mass, linear_damping=0.0, angular_damping=0.0),
        position=np.array(pos, dtype=np.float64),
        velocity=np.array(vel, dtype=np.float64),
        orientation=np.array(ori, dtype=np.float64),
        half_extents=half_arr,
    )


def _sphere(name, pos, radius, *, vel=(0.0, 0.0, 0.0), mass=2.0):
    return ActiveBody(
        name=name,
        radius=radius,
        params=PhysicalParameters(friction=0.5, restitution=0.0, mass=mass, linear_damping=0.0, angular_damping=0.0),
        position=np.array(pos, dtype=np.float64),
        velocity=np.array(vel, dtype=np.float64),
    )


def _quat_z(angle):
    return (math.cos(angle / 2.0), 0.0, 0.0, math.sin(angle / 2.0))


def _random_quat(rng):
    q = rng.normal(size=4)
    return tuple(q / np.linalg.norm(q))


def _brute_force_sat(b1, b2):
    """Reference SAT written from the definition: 15 explicit axes, no shortcuts."""
    A = quaternion_to_rotation_matrix(b1.orientation)
    B = quaternion_to_rotation_matrix(b2.orientation)
    d = b2.position - b1.position
    axes = [(A[:, i], 0.0) for i in range(3)] + [(B[:, i], 0.0) for i in range(3)]
    for i in range(3):
        for j in range(3):
            c = np.cross(A[:, i], B[:, j])
            n = np.linalg.norm(c)
            if n >= 1e-6:
                axes.append((c / n, EDGE_AXIS_PREFERENCE_M))
    best = None
    for axis, bias in axes:
        depth = (
            np.sum(b1.half_extents * np.abs(A.T @ axis))
            + np.sum(b2.half_extents * np.abs(B.T @ axis))
            - abs(axis @ d)
        )
        if depth < 0.0:
            return None
        if best is None or depth + bias < best[0]:
            best = (depth + bias, depth, axis if axis @ d >= 0.0 else -axis)
    return best[1], best[2]


def test_offset_stacked_boxes_are_not_pushed_apart():
    """Two touching boxes offset sideways have no penetration, whatever the center line says."""
    bottom = _box("a", (0.0, 0.0, 0.5), (0.6, 0.6, 0.5))
    top = _box("b", (0.3, 0.0, 1.5), (0.5, 0.5, 0.5))

    # The registered center-line formula would report a large false overlap for this pose.
    r = top.position - bottom.position
    n = r / np.linalg.norm(r)
    assert support_distance(bottom, n) + support_distance(top, -n) - np.linalg.norm(r) > 0.15

    step_substep([bottom, top], StaticEnvironment(ground=None), g=0.0)
    np.testing.assert_allclose(bottom.position, (0.0, 0.0, 0.5), atol=1e-12)
    np.testing.assert_allclose(top.position, (0.3, 0.0, 1.5), atol=1e-12)


def test_box_box_depth_and_normal_axis_aligned():
    a = _box("a", (0.0, 0.0, 0.0), (0.5, 0.5, 0.5))
    b = _box("b", (0.2, 0.0, 0.95), (0.5, 0.5, 0.5))
    depth, n = _obb_obb_contact(a, b)
    assert depth == pytest.approx(0.05)
    np.testing.assert_allclose(n, (0.0, 0.0, 1.0), atol=1e-12)

    # The opposite pair order gives the same depth and the opposite normal.
    depth2, n2 = _obb_obb_contact(b, a)
    assert depth2 == pytest.approx(0.05)
    np.testing.assert_allclose(n2, (0.0, 0.0, -1.0), atol=1e-12)


def test_box_box_rotated_corner_against_face():
    """A box turned 45 degrees about z pokes its corner into the other box's +x face."""
    a = _box("a", (0.0, 0.0, 0.0), (0.5, 0.5, 0.5))
    corner = 0.5 * math.sqrt(2.0)
    b = _box("b", (0.5 + corner - 0.02, 0.0, 0.0), (0.5, 0.5, 0.5), ori=_quat_z(math.pi / 4.0))
    depth, n = _obb_obb_contact(a, b)
    assert depth == pytest.approx(0.02, abs=1e-9)
    np.testing.assert_allclose(n, (1.0, 0.0, 0.0), atol=1e-9)

    b.position[0] += 0.03
    assert _obb_obb_contact(a, b) is None


def test_box_box_edge_edge_contact_uses_a_cross_axis():
    """Crossed edges meet only along their cross product, which no face axis can represent."""
    a = _box("a", (0.0, 0.0, 0.0), (0.5, 0.5, 0.5), ori=(math.cos(math.pi / 8.0), math.sin(math.pi / 8.0), 0.0, 0.0))
    b = _box("b", (0.0, 0.0, 0.0), (0.5, 0.5, 0.5), ori=(math.cos(math.pi / 8.0), 0.0, math.sin(math.pi / 8.0), 0.0))
    gap = 2.0 * 0.5 * math.sqrt(2.0)
    b.position[2] = gap - 0.01
    depth, n = _obb_obb_contact(a, b)
    assert depth == pytest.approx(0.01, abs=1e-9)
    np.testing.assert_allclose(n, (0.0, 0.0, 1.0), atol=1e-9)


def test_box_box_matches_reference_sat_on_random_poses():
    rng = np.random.default_rng(20261105)
    in_contact = 0
    for _ in range(3000):
        a = _box("a", rng.uniform(-0.3, 0.3, 3), rng.uniform(0.2, 0.7, 3), ori=_random_quat(rng))
        b = _box("b", rng.uniform(-1.4, 1.4, 3), rng.uniform(0.2, 0.7, 3), ori=_random_quat(rng))
        ours = _obb_obb_contact(a, b)
        ref = _brute_force_sat(a, b)
        assert (ours is None) == (ref is None)
        if ours is not None:
            in_contact += 1
            assert ours[0] == pytest.approx(ref[0], abs=1e-9)
            np.testing.assert_allclose(ours[1], ref[1], atol=1e-7)
    assert in_contact > 300  # the sample has to exercise both outcomes


@pytest.mark.parametrize(
    "sphere_pos, depth, normal",
    [
        ((0.0, 0.0, 0.8), 0.1, (0.0, 0.0, 1.0)),  # above the top face
        ((0.7, 0.7, 0.0), 0.4 - math.sqrt(2.0) * 0.2, (math.sqrt(0.5), math.sqrt(0.5), 0.0)),  # off an edge
        ((0.0, 0.0, 0.4), 0.4 + 0.1, (0.0, 0.0, 1.0)),  # center inside: leaves through the nearest face
    ],
)
def test_sphere_box_depth_and_normal(sphere_pos, depth, normal):
    box = _box("b", (0.0, 0.0, 0.0), (0.5, 0.5, 0.5))
    sphere = _sphere("s", sphere_pos, 0.4)
    got_depth, got_normal = _sphere_obb_contact(sphere, box)
    assert got_depth == pytest.approx(depth)
    np.testing.assert_allclose(got_normal, normal, atol=1e-9)


def test_sphere_box_separated_and_pair_order():
    box = _box("b", (0.0, 0.0, 0.0), (0.5, 0.5, 0.5))
    assert _sphere_obb_contact(_sphere("s", (0.0, 0.0, 0.95), 0.4), box) is None

    # _box_interbody_contact reports the normal from its first argument to its second.
    sphere = _sphere("s", (0.0, 0.0, 0.8), 0.4)
    np.testing.assert_allclose(_box_interbody_contact(box, sphere)[1], (0.0, 0.0, 1.0), atol=1e-9)
    np.testing.assert_allclose(_box_interbody_contact(sphere, box)[1], (0.0, 0.0, -1.0), atol=1e-9)


def test_box_box_impact_conserves_momentum():
    a = _box("a", (0.0, 0.0, 0.0), (0.5, 0.5, 0.5), vel=(0.0, 0.0, 1.0), mass=2.0)
    b = _box("b", (0.2, 0.1, 0.99), (0.5, 0.5, 0.5), vel=(0.4, 0.0, -1.0), mass=3.0)
    before = a.params.mass * a.velocity + b.params.mass * b.velocity
    step_substep([a, b], StaticEnvironment(ground=None), g=0.0)
    after = a.params.mass * a.velocity + b.params.mass * b.velocity
    np.testing.assert_allclose(after, before, atol=1e-9)
    # The impulse acted along the contact normal, so the closing speed is gone.
    assert (b.velocity - a.velocity)[2] >= -1e-9
