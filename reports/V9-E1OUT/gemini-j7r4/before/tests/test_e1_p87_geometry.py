"""P87 validation tests for explicit BodyGeometry propagation and static material injection.

Covers the 5 required test cases:
1. test_resting_box_physics: Box 1.2 x 1.2 x 1.0 resting on ground at z=0.5.
   Rollout 30 steps: z error < 1e-3, horizontal displacement < 1e-6 across Arms 1, 4, 5, 7.
   Arms 3 and 6 with zeroed residual network match Arm 1 and Arm 5 to < 1e-9.
2. test_probe_body_geometry_routing: Multi-body scene with Box and Sphere.
   Confirms Box uses half_extents while Sphere uses radius.
3. test_arm4_static_material_injection: Box sliding on ground with ground friction 0.2 vs 0.9.
   Arm 4 deceleration relative error < 5%; Arm 1 uses default 0.50 friction.
4. test_subspace_dim_two_bodies_dict: Two bodies in IdentifyArm with different identifiability k.
   Plain dictionary without cross-contamination.
5. test_no_radii_by_body_in_src: Walk all .py files in src/ainerzero/v9/experiments/e1/ and assert 0 occurrences.
"""

from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any
import numpy as np
import pytest
import mlx.core as mx

from ainerzero.v9.experiments.e1.prior import (
    DEFAULT_BIASED_PRIOR,
    DEFAULT_GROUND_FRICTION,
    ActiveBody,
    BodyGeometry,
    GroundPlane,
    PhysicalParameters,
    StaticEnvironment,
    geometry_from_student_body,
    make_active_body_from_state,
    rollout,
)
from ainerzero.v9.experiments.e1.arms_nonnet import (
    IdentifyArm,
    PriorArm,
    SymbolicResidualArm,
    TrueParamArm,
)
from ainerzero.v9.experiments.e1.arms_net import (
    IdentifyResidualArm,
    PriorResidualArm,
    PureNetArm,
)
from ainerzero.v9.experiments.e1.eval_runner import (
    evaluate_episode,
    extract_true_phi_from_episode,
    inject_truth_static_materials,
)
from ainerzero.v9.experiments.e1.train_runner import make_arm6_identifier


def test_resting_box_physics():
    """1. Box 1.2 x 1.2 x 1.0 resting at z=0.5 on ground with zero velocity.

    Arms 1, 4, 5, 7 rollout 30 steps -> z error < 1e-3, horizontal displacement < 1e-6.
    Arms 3 and 6 with zero network match Arm 1 and Arm 5 to diff < 1e-9.
    """
    dim_box = np.array([1.2, 1.2, 1.0], dtype=np.float64)
    half_extents = dim_box / 2.0  # [0.6, 0.6, 0.5]
    radius = float(np.linalg.norm(half_extents))  # ~0.98488

    ground = GroundPlane(z_plane=0.0, friction=0.5, restitution=0.5)
    env = StaticEnvironment(ground=ground)

    box_geo = BodyGeometry(radius=radius, half_extents=half_extents)
    geometry_by_body = {"box": box_geo}

    # Construct resting box state (30 frames)
    prefix_len = 5
    prefix = np.zeros((prefix_len, 13), dtype=np.float64)
    for i in range(prefix_len):
        prefix[i, 0:3] = [0.0, 0.0, 0.5]
        prefix[i, 3:6] = [0.0, 0.0, 0.0]
        prefix[i, 6] = 1.0  # quaternion w

    prefix_dict = {"box": prefix}
    n_future = 30

    # 1. Test Arms 1, 4, 5, 7
    arms = {
        "Arm 1 PriorArm": PriorArm(geometry_by_body=geometry_by_body),
        "Arm 4 TrueParamArm": TrueParamArm(
            true_params={"box": DEFAULT_BIASED_PRIOR.copy()},
            geometry_by_body=geometry_by_body,
        ),
        "Arm 5 IdentifyArm": IdentifyArm(geometry_by_body=geometry_by_body),
        "Arm 7 SymbolicResidualArm": SymbolicResidualArm(geometry_by_body=geometry_by_body),
    }

    pred_positions = {}
    for arm_name, arm in arms.items():
        res = arm.predict(prefix_dict, env, n_future=n_future, geometry_by_body=geometry_by_body)
        pos = res.positions["box"]
        pred_positions[arm_name] = pos

        # z error < 1e-3 across all 30 steps
        z_errors = np.abs(pos[:, 2] - 0.5)
        max_z_err = float(np.max(z_errors))
        assert max_z_err < 1e-3, f"{arm_name} max z error {max_z_err} exceeds 1e-3"

        # horizontal displacement < 1e-6 across all 30 steps
        xy_disp = np.linalg.norm(pos[:, :2], axis=-1)
        max_xy = float(np.max(xy_disp))
        assert max_xy < 1e-6, f"{arm_name} max horizontal displacement {max_xy} exceeds 1e-6"

    # 2. Arm 3 with zero network weights matches Arm 1 to diff < 1e-9
    arm3 = PriorResidualArm(seed=42, geometry_by_body=geometry_by_body)
    for mod in [arm3.net.fc1, arm3.net.fc2, arm3.net.out]:
        mod.weight = mx.zeros_like(mod.weight)
        mod.bias = mx.zeros_like(mod.bias)

    res3 = arm3.predict(prefix_dict, env, n_future=n_future, geometry_by_body=geometry_by_body)
    pos3 = res3["box"][1:, 0:3]
    diff3 = float(np.max(np.abs(pos3 - pred_positions["Arm 1 PriorArm"])))
    assert diff3 < 1e-9, f"Arm 3 diff from Arm 1 {diff3} >= 1e-9"

    # 3. Arm 6 with zero network weights matches Arm 5 to diff < 1e-9
    arm6 = IdentifyResidualArm(
        seed=42,
        identifier_fn=make_arm6_identifier(),
        geometry_by_body=geometry_by_body,
    )
    for mod in [arm6.net.fc1, arm6.net.fc2, arm6.net.out]:
        mod.weight = mx.zeros_like(mod.weight)
        mod.bias = mx.zeros_like(mod.bias)

    res6 = arm6.predict(prefix_dict, env, n_future=n_future, geometry_by_body=geometry_by_body)
    pos6 = res6["box"][1:, 0:3]
    diff6 = float(np.max(np.abs(pos6 - pred_positions["Arm 5 IdentifyArm"])))
    assert diff6 < 1e-9, f"Arm 6 diff from Arm 5 {diff6} >= 1e-9"


def test_probe_body_geometry_routing():
    """2. Multi-body scene with Box and Sphere: spy verifies routing to half_extents vs radius."""
    box_info = {
        "name": "box",
        "shape": "BOX",
        "dimensions": [1.2, 0.8, 0.6],
        "bounding_sphere_radius": 0.76157731,
    }
    sphere_info = {
        "name": "sphere",
        "shape": "SPHERE",
        "dimensions": [0.6, 0.6, 0.6],
        "bounding_sphere_radius": 0.3,
    }

    geo_box = geometry_from_student_body(box_info)
    geo_sphere = geometry_from_student_body(sphere_info)

    assert geo_box.half_extents is not None
    assert np.allclose(geo_box.half_extents, [0.6, 0.4, 0.3])
    assert geo_sphere.half_extents is None
    assert abs(geo_sphere.radius - 0.3) < 1e-6

    # Verify make_active_body_from_state creates ActiveBody with proper fields
    row_state = np.zeros(13, dtype=np.float64)
    row_state[0:3] = [0.0, 0.0, 1.0]
    row_state[6] = 1.0

    phi = DEFAULT_BIASED_PRIOR.copy()
    body_box = make_active_body_from_state(
        "box", row_state, phi, radius=geo_box.radius, half_extents=geo_box.half_extents
    )
    body_sphere = make_active_body_from_state(
        "sphere", row_state, phi, radius=geo_sphere.radius, half_extents=geo_sphere.half_extents
    )

    assert body_box.half_extents is not None
    assert np.allclose(body_box.half_extents, [0.6, 0.4, 0.3])
    assert body_sphere.half_extents is None
    assert abs(body_sphere.radius - 0.3) < 1e-6


def test_arm4_static_material_injection():
    """3. Box sliding on ground with truth ground friction 0.2 vs 0.9.

    Arm 4 deceleration matches truth with relative error < 5%;
    Arm 1 uses default 0.50 friction.
    """
    dim_box = [1.0, 1.0, 1.0]
    r_box = float(np.sqrt(0.5**2 + 0.5**2 + 0.5**2))
    dt = 1.0 / 60.0
    box_friction = 0.4
    n_frames = 25

    for truth_ground_friction in (0.2, 0.9):
        body = ActiveBody(
            "box",
            radius=r_box,
            params=PhysicalParameters(
                friction=box_friction,
                restitution=0.5,
                mass=1.0,
                linear_damping=0.0,
                angular_damping=0.0,
            ),
            position=np.array([0.0, 0.0, 0.5]),
            velocity=np.array([5.0, 0.0, 0.0]),
            half_extents=np.array([0.5, 0.5, 0.5]),
        )
        env_truth = StaticEnvironment(
            ground=GroundPlane(z_plane=0.0, friction=truth_ground_friction, restitution=0.5)
        )
        traj = rollout([body], env_truth, num_frames=n_frames)["box"]

        frames = []
        for t in range(n_frames):
            frames.append({
                "frame": t,
                "time_seconds": t * dt,
                "objects": {
                    "Ground": {"position": [0.0, 0.0, 0.0], "linear_velocity": [0.0, 0.0, 0.0]},
                    "box": {
                        "position": traj[t, 0:3].tolist(),
                        "linear_velocity": traj[t, 3:6].tolist(),
                        "orientation": traj[t, 6:10].tolist(),
                        "angular_velocity": traj[t, 10:13].tolist(),
                    },
                },
                "contacts": [],
            })

        student_ep = {
            "sequence_id": f"slide_seq_{truth_ground_friction}",
            "active_bodies": {
                "box": {
                    "name": "box",
                    "shape": "BOX",
                    "dimensions": dim_box,
                    "bounding_sphere_radius": r_box,
                },
            },
            "static_environment": {"ground": {"z_plane": 0.0}},
            "frames": frames,
        }

        truth_ep = {
            "family": "P",
            "metadata": {"fps": 60, "total_frames": n_frames},
            "hidden_parameters": {
                "box": {
                    "shape": "BOX",
                    "dimensions": dim_box,
                    "is_active": True,
                    "friction": box_friction,
                    "restitution": 0.5,
                    "mass": 1.0,
                    "linear_damping": 0.0,
                    "angular_damping": 0.0,
                },
                "Ground": {
                    "is_active": False,
                    "friction": truth_ground_friction,
                    "restitution": 0.5,
                },
            },
            "pairwise_collisions": [],
            "mechanisms": [],
        }

        phi_map = extract_true_phi_from_episode(truth_ep)
        arm4 = TrueParamArm(true_params=phi_map)
        arm1 = PriorArm()

        res4 = evaluate_episode(arm4, student_ep, truth_ep)
        res1 = evaluate_episode(arm1, student_ep, truth_ep)

        pos4 = np.asarray(res4["pred_positions"]["box"])
        pos1 = np.asarray(res1["pred_positions"]["box"])

        prefix_frames = res4["prefix_frames"]
        true_future = traj[prefix_frames : prefix_frames + len(pos4)]

        # Position error under Arm 4 is zero
        max_err_4 = float(np.max(np.abs(pos4 - true_future[:, 0:3])))
        assert max_err_4 < 1e-6, f"Arm 4 position error {max_err_4} exceeds 1e-6"

        # Calculate deceleration over prediction horizon
        v_init = traj[prefix_frames - 1, 3]
        x_init = traj[prefix_frames - 1, 0]
        t_span = len(pos4) * dt

        dx4 = pos4[-1, 0] - x_init
        a_arm4 = 2.0 * (dx4 - v_init * t_span) / (t_span**2)

        dx_true = true_future[-1, 0] - x_init
        a_true = 2.0 * (dx_true - v_init * t_span) / (t_span**2)

        dx1 = pos1[-1, 0] - x_init
        a_arm1 = 2.0 * (dx1 - v_init * t_span) / (t_span**2)

        rel_err4 = abs(a_arm4 - a_true) / abs(a_true)
        assert rel_err4 < 0.05, f"Arm 4 deceleration relative error {rel_err4:.4f} exceeds 5%"

        # Arm 1 uses default prior ground friction = 0.50, so its deceleration differs from truth
        diff1 = abs(a_arm1 - a_true)
        assert diff1 > 0.50, f"Arm 1 deceleration {a_arm1} was too close to truth {a_true}"


def test_subspace_dim_two_bodies_dict():
    """4. IdentifyArm with 2 bodies having different identifiability k.

    Asserts plain dict, correct keys, no cross-contamination.
    """
    env = StaticEnvironment(ground=GroundPlane(z_plane=0.0, friction=0.5, restitution=0.8))

    # ball_bounce bounces vertically: restitution identifiable -> k >= 1
    # ball_flight moves in air without contact: unidentifiable -> k = 0
    b_bounce = ActiveBody(
        "ball_bounce",
        radius=0.20,
        params=PhysicalParameters(friction=0.5, restitution=0.2),
        position=np.array([0.0, 0.0, 1.0]),
        velocity=np.array([0.0, 0.0, -2.0]),
    )
    b_flight = ActiveBody(
        "ball_flight",
        radius=0.20,
        params=PhysicalParameters(friction=0.5, restitution=0.2),
        position=np.array([5.0, 0.0, 10.0]),
        velocity=np.array([1.0, 0.0, 0.0]),
    )

    traj = rollout([b_bounce, b_flight], env, num_frames=35)
    prefix_data = {"ball_bounce": traj["ball_bounce"][:30], "ball_flight": traj["ball_flight"][:30]}

    geo = {
        "ball_bounce": BodyGeometry(radius=0.20),
        "ball_flight": BodyGeometry(radius=0.20),
    }

    arm5 = IdentifyArm(geometry_by_body=geo)
    res5 = arm5.predict(prefix_data, env, n_future=5, geometry_by_body=geo)

    assert type(res5.identified_subspace_dim) is dict
    assert "ball_bounce" in res5.identified_subspace_dim
    assert "ball_flight" in res5.identified_subspace_dim

    assert res5.identified_subspace_dim["ball_bounce"] >= 1
    assert res5.identified_subspace_dim["ball_flight"] == 0

    assert type(res5.identified_weight) is dict
    assert "ball_bounce" in res5.identified_weight
    assert "ball_flight" in res5.identified_weight
    assert res5.identified_weight["ball_bounce"]["restitution"] > 0.5


def test_no_radii_by_body_in_src():
    """5. Assert 0 occurrences of 'radii_by_body' in src/ainerzero/v9/experiments/e1/."""
    src_dir = Path(__file__).resolve().parent.parent / "src" / "ainerzero" / "v9" / "experiments" / "e1"
    py_files = list(src_dir.rglob("*.py"))
    assert len(py_files) > 0, "No python source files found in e1"

    violations = []
    for f in py_files:
        text = f.read_text(encoding="utf-8")
        if "radii_by_body" in text:
            violations.append(str(f.relative_to(src_dir)))

    assert violations == [], f"Found 'radii_by_body' in source files: {violations}"


def test_arm6_identifier_receives_box_half_extents():
    """Verify Arm ⑥ identifier receives exact half_extents for Box bodies."""
    box_he = np.array([0.6, 0.4, 0.3], dtype=np.float64)
    geo = {"box": BodyGeometry(radius=0.8, half_extents=box_he)}

    received_geos: list[BodyGeometry] = []

    def spy_id(prefix_data, env, geometry_by_body=None):
        assert geometry_by_body is not None
        assert "body_0" in geometry_by_body
        received_geos.append(geometry_by_body["body_0"])
        return DEFAULT_BIASED_PRIOR.copy()

    arm6 = IdentifyResidualArm(identifier_fn=spy_id, geometry_by_body=geo)
    prefix_data = {"box": np.ones((5, 6), dtype=np.float64)}
    env = StaticEnvironment(ground=None)
    arm6.predict(prefix_data, env, n_future=2, geometry_by_body=geo)

    assert len(received_geos) == 1
    assert received_geos[0].half_extents is not None
    assert np.allclose(received_geos[0].half_extents, box_he)


def test_truth_static_materials_no_leakage_to_other_arms():
    """r2 requirement 2: Invariance test asserting no truth material leakage to arms ①②③⑤⑥⑦.

    With identical student episode and two truth episodes differing only in
    ground friction (0.2 vs 0.9):
    - Arms ①②③⑤⑥⑦ must yield bitwise identical predictions.
    - Arm ④ must yield different predictions.
    - Passing a spoofed arm_name='Arm 4 (True Param Bias)' to a non-Arm-4 instance
      must not trigger truth material injection.
    """
    dim_box = [1.0, 1.0, 1.0]
    r_box = float(np.sqrt(0.5**2 + 0.5**2 + 0.5**2))
    dt = 1.0 / 60.0
    n_frames = 25

    body = ActiveBody(
        "box",
        radius=r_box,
        params=PhysicalParameters(
            friction=0.4,
            restitution=0.5,
            mass=1.0,
            linear_damping=0.0,
            angular_damping=0.0,
        ),
        position=np.array([0.0, 0.0, 0.5]),
        velocity=np.array([5.0, 0.0, 0.0]),
        half_extents=np.array([0.5, 0.5, 0.5]),
    )
    env_base = StaticEnvironment(ground=GroundPlane(z_plane=0.0, friction=0.5, restitution=0.5))
    traj = rollout([body], env_base, num_frames=n_frames)["box"]

    frames = []
    for t in range(n_frames):
        frames.append({
            "frame": t,
            "time_seconds": t * dt,
            "objects": {
                "Ground": {"position": [0.0, 0.0, 0.0], "linear_velocity": [0.0, 0.0, 0.0]},
                "box": {
                    "position": traj[t, 0:3].tolist(),
                    "linear_velocity": traj[t, 3:6].tolist(),
                    "orientation": traj[t, 6:10].tolist(),
                    "angular_velocity": traj[t, 10:13].tolist(),
                },
            },
            "contacts": [],
        })

    student_ep = {
        "sequence_id": "slide_invariance_seq",
        "active_bodies": {
            "box": {
                "name": "box",
                "shape": "BOX",
                "dimensions": dim_box,
                "bounding_sphere_radius": r_box,
            },
        },
        "static_environment": {"ground": {"z_plane": 0.0}},
        "frames": frames,
    }

    def make_truth(fric: float) -> dict[str, Any]:
        return {
            "family": "P",
            "metadata": {"fps": 60, "total_frames": n_frames},
            "hidden_parameters": {
                "box": {
                    "shape": "BOX",
                    "dimensions": dim_box,
                    "is_active": True,
                    "friction": 0.4,
                    "restitution": 0.5,
                    "mass": 1.0,
                    "linear_damping": 0.0,
                    "angular_damping": 0.0,
                },
                "Ground": {
                    "is_active": False,
                    "friction": fric,
                    "restitution": 0.5,
                },
            },
            "pairwise_collisions": [],
            "mechanisms": [],
        }

    t_ep1 = make_truth(0.2)
    t_ep2 = make_truth(0.9)

    # Test Arms ①②③⑤⑥⑦: All must have bitwise identical predictions across t_ep1 and t_ep2
    arms = [
        ("Arm 1 PriorArm", PriorArm()),
        ("Arm 2 PureNetArm", PureNetArm(seed=42)),
        ("Arm 3 PriorResidualArm", PriorResidualArm(seed=42)),
        ("Arm 5 IdentifyArm", IdentifyArm()),
        ("Arm 6 IdentifyResidualArm", IdentifyResidualArm(seed=42, identifier_fn=make_arm6_identifier())),
        ("Arm 7 SymbolicResidualArm", SymbolicResidualArm()),
    ]

    for arm_label, arm_obj in arms:
        res1 = evaluate_episode(arm_obj, student_ep, t_ep1)
        res2 = evaluate_episode(arm_obj, student_ep, t_ep2)
        pos1 = np.asarray(res1["pred_positions"]["box"])
        pos2 = np.asarray(res2["pred_positions"]["box"])
        assert np.array_equal(pos1, pos2), f"{arm_label} predictions differ across truth episodes: truth material leaked!"

    # Test Arm ④ TrueParamArm: must produce different predictions due to injected ground friction
    phi1 = extract_true_phi_from_episode(t_ep1)
    arm4_1 = TrueParamArm(true_params=phi1)
    res4_1 = evaluate_episode(arm4_1, student_ep, t_ep1)

    phi2 = extract_true_phi_from_episode(t_ep2)
    arm4_2 = TrueParamArm(true_params=phi2)
    res4_2 = evaluate_episode(arm4_2, student_ep, t_ep2)

    pos4_1 = np.asarray(res4_1["pred_positions"]["box"])
    pos4_2 = np.asarray(res4_2["pred_positions"]["box"])
    assert not np.array_equal(pos4_1, pos4_2), "Arm 4 failed to reflect differing truth ground friction!"

    # Requirement 1 verification: Passing spoofed arm_name to PriorArm must not trigger injection
    res_spoof1 = evaluate_episode(PriorArm(), student_ep, t_ep1, arm_name="Arm 4 (True Param Bias)")
    res_spoof2 = evaluate_episode(PriorArm(), student_ep, t_ep2, arm_name="Arm 4 (True Param Bias)")
    pos_spoof1 = np.asarray(res_spoof1["pred_positions"]["box"])
    pos_spoof2 = np.asarray(res_spoof2["pred_positions"]["box"])
    assert np.array_equal(pos_spoof1, pos_spoof2), "Spoofed arm_name caused truth material leakage!"

