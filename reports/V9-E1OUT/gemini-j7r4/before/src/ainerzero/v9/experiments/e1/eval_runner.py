"""Evaluation runner for E1 benchmark (ainerzero.V9.P73).

Evaluates Arm predictions against ground truth on student-side and evaluator-side data.
Key principles:
1. PREFIX_FRAMES = 10 (module constant, marked 待一级冻结).
2. Arm predicts future frames starting strictly from the end of the observed prefix:
   n_future = min(MAX_FUTURE_FRAMES, remaining frames).
3. Position errors: evaluated on the future window using metrics.compute_horizon_position_errors for k in (1, 5, 10, 30) (single-origin horizon error; PREREG_DRAFT r2 / P89).
4. Prediction-side collision events: computed from predicted positions, predicted velocities,
   student-side static geometry, and bounding sphere radii.
5. Ground-truth side collision events: computed from evaluator-side pairwise_collisions on the same future window.
   Both event lists are compared using metrics.compute_collision_f1.
6. Ballistic energy drift: evaluated on predicted trajectories over truth-determined ballistic segments
   (intervals where all active objects are contact-free for >= 5 consecutive frames).
   Mass is set to 1.0 because relative energy drift |Delta H| / H0 is mathematically independent of mass:
   H(t) = 0.5 * m * ||v(t)||^2 + m * g * z(t) = m * (0.5 * ||v(t)||^2 + g * z(t))
   |H(t) - H(0)| / |H(0)| = |m * H_tilde(t) - m * H_tilde(0)| / |m * H_tilde(0)|
                          = |H_tilde(t) - H_tilde(0)| / |H_tilde(0)|.
   The mass parameter m factors out entirely, making relative energy drift invariant to body mass
   without leaking hidden parameters to the evaluation pipeline.
7. Inference latency: measured wall-clock time of arm.predict divided by n_future.
8. Cell evaluation: aggregates episodes in student_dir and evaluator_dir.
   Raises ValueError if no episodes exist (no default values allowed).
9. Final evaluation: reads sealed final dataset strictly via export.open_sealed_final_once token.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.e1.export import (
    DatasetError,
    FinalPartitionSealed,
    open_sealed_final_once,
)
from ainerzero.v9.experiments.e1.metrics import (
    BALLISTIC_MIN_FRAMES,
    COLLISION_DEBOUNCE_FRAMES,
    COLLISION_MATCH_TOLERANCE_FRAMES,
    COLLISION_VELOCITY_THRESHOLD_MPS,
    CONTACT_TOLERANCE_M,
    DEFAULT_K_STEPS,
    DEFAULT_K_STEPS as DEFAULT_EVAL_K_STEPS,
    GRAVITY_ACCEL,
    PRIMARY_K,
    CollisionEvent,
    compute_ballistic_energy_drift,
    compute_collision_f1,
    compute_horizon_position_errors,
    detect_collision_events,
)
from ainerzero.v9.experiments.e1.arms_nonnet import TrueParamArm
from ainerzero.v9.experiments.e1.prior import (
    BodyGeometry,
    GroundPlane,
    InclinedRamp,
    PhysicalParameters,
    StaticBox,
    StaticEnvironment,
    TableTop,
    geometry_from_student_body,
)

# =========================================================================
# Module Constants (待一级冻结)
# Note: Existing constants (CONTACT_TOLERANCE_M, COLLISION_*, BALLISTIC_*,
# K_STEPS, PRIMARY_K, GRAVITY_ACCEL) are imported directly from metrics.py.
# =========================================================================

PREFIX_FRAMES: int = 10  # 待一级冻结: number of prefix observation frames
MAX_FUTURE_FRAMES: int = 30  # 待一级冻结: maximum rollout horizon


# =========================================================================
# Environment and Geometry Helpers
# =========================================================================

def build_static_environment_from_student(
    static_geo: Mapping[str, Any] | StaticEnvironment | None,
) -> StaticEnvironment:
    """Reconstruct StaticEnvironment instance from student-side geometric metadata."""
    if isinstance(static_geo, StaticEnvironment):
        return static_geo
    if not static_geo or not isinstance(static_geo, Mapping):
        return StaticEnvironment(ground=None, ramps=[], tables=[], boxes=[])

    ground = None
    if static_geo.get("ground"):
        z_plane = float(static_geo["ground"].get("z_plane", 0.0))
        g_name = str(static_geo["ground"].get("name", "Ground"))
        ground = GroundPlane(z_plane=z_plane, name=g_name)

    ramps: list[InclinedRamp] = []
    for r in static_geo.get("ramps", []):
        pt = np.asarray(r["point"], dtype=np.float64)
        n = np.asarray(r["normal"], dtype=np.float64)
        xb = tuple(r["x_bounds"]) if "x_bounds" in r and r["x_bounds"] is not None else None
        yb = tuple(r["y_bounds"]) if "y_bounds" in r and r["y_bounds"] is not None else None
        r_name = str(r.get("name", "Ramp"))
        ramps.append(InclinedRamp(point=pt, normal=n, x_bounds=xb, y_bounds=yb, name=r_name))

    tables: list[TableTop] = []
    for t in static_geo.get("tables", []):
        z_top = float(t["z_top"])
        xb = tuple(t["x_bounds"])
        yb = tuple(t["y_bounds"])
        thick = float(t.get("thickness", 0.20))
        t_name = str(t.get("name", "TableTop"))
        tables.append(TableTop(z_top=z_top, x_bounds=xb, y_bounds=yb, thickness=thick, name=t_name))

    boxes: list[StaticBox] = []
    for b in static_geo.get("boxes", []):
        min_p = np.asarray(b["min_point"], dtype=np.float64)
        max_p = np.asarray(b["max_point"], dtype=np.float64)
        b_name = str(b.get("name", "StaticBox"))
        boxes.append(StaticBox(min_point=min_p, max_point=max_p, name=b_name))

    return StaticEnvironment(ground=ground, ramps=ramps, tables=tables, boxes=boxes)


def inject_truth_static_materials(
    static_env: StaticEnvironment,
    truth_ep: Mapping[str, Any],
) -> StaticEnvironment:
    """Create a clone of StaticEnvironment with truth friction & restitution for Arm ④.

    Raises KeyError if any static surface present in static_env lacks truth friction or restitution.
    """
    if "metadata" in truth_ep and isinstance(truth_ep["metadata"], Mapping) and "hidden_parameters" in truth_ep["metadata"]:
        h_params = truth_ep["metadata"]["hidden_parameters"]
    elif "hidden_parameters" in truth_ep and isinstance(truth_ep["hidden_parameters"], Mapping):
        h_params = truth_ep["hidden_parameters"]
    else:
        raise KeyError("truth_ep missing hidden_parameters for static material injection")

    # 1. Ground
    new_ground: GroundPlane | None = None
    if static_env.ground is not None:
        g_name = getattr(static_env.ground, "name", "Ground")
        g_info = None
        for cand in (g_name, "Ground", "ground"):
            if cand in h_params:
                g_info = h_params[cand]
                break
        if g_info is None or not isinstance(g_info, Mapping):
            raise KeyError("Missing truth material for static body 'Ground'")
        if "friction" not in g_info or g_info["friction"] is None or "restitution" not in g_info or g_info["restitution"] is None:
            raise KeyError("Missing truth material for static body 'Ground'")
        new_ground = GroundPlane(
            z_plane=static_env.ground.z_plane,
            friction=float(g_info["friction"]),
            restitution=float(g_info["restitution"]),
            name=g_name,
        )

    # 2. Ramps
    new_ramps: list[InclinedRamp] = []
    for r in static_env.ramps:
        r_name = getattr(r, "name", "Ramp")
        r_info = None
        for cand in (r_name, "Ramp", "ramp"):
            if cand in h_params:
                r_info = h_params[cand]
                break
        if r_info is None:
            for k, v in h_params.items():
                if isinstance(v, Mapping) and "ramp" in k.lower():
                    r_info = v
                    r_name = k
                    break
        if r_info is None or not isinstance(r_info, Mapping):
            raise KeyError(f"Missing truth material for static body '{r_name}'")
        if "friction" not in r_info or r_info["friction"] is None or "restitution" not in r_info or r_info["restitution"] is None:
            raise KeyError(f"Missing truth material for static body '{r_name}'")
        new_ramps.append(
            InclinedRamp(
                point=np.array(r.point, copy=True),
                normal=np.array(r.normal, copy=True),
                friction=float(r_info["friction"]),
                restitution=float(r_info["restitution"]),
                x_bounds=r.x_bounds,
                y_bounds=r.y_bounds,
                name=r_name,
            )
        )

    # 3. Tables
    new_tables: list[TableTop] = []
    for t in static_env.tables:
        t_name = getattr(t, "name", "TableTop")
        t_info = None
        for cand in (t_name, "TableTop", "tabletop", "Table", "table"):
            if cand in h_params:
                t_info = h_params[cand]
                break
        if t_info is None:
            for k, v in h_params.items():
                if isinstance(v, Mapping) and "table" in k.lower():
                    t_info = v
                    t_name = k
                    break
        if t_info is None or not isinstance(t_info, Mapping):
            raise KeyError(f"Missing truth material for static body '{t_name}'")
        if "friction" not in t_info or t_info["friction"] is None or "restitution" not in t_info or t_info["restitution"] is None:
            raise KeyError(f"Missing truth material for static body '{t_name}'")
        new_tables.append(
            TableTop(
                z_top=t.z_top,
                x_bounds=t.x_bounds,
                y_bounds=t.y_bounds,
                thickness=t.thickness,
                friction=float(t_info["friction"]),
                restitution=float(t_info["restitution"]),
                name=t_name,
            )
        )

    # 4. Boxes
    new_boxes: list[StaticBox] = []
    for b in static_env.boxes:
        b_name = getattr(b, "name", "StaticBox")
        b_info = None
        for cand in (b_name, "StaticBox", "OccluderWall", "occluderwall", "box"):
            if cand in h_params:
                b_info = h_params[cand]
                break
        if b_info is None:
            for k, v in h_params.items():
                if isinstance(v, Mapping) and ("box" in k.lower() or "wall" in k.lower()) and not v.get("is_active", True):
                    b_info = v
                    b_name = k
                    break
        if b_info is None or not isinstance(b_info, Mapping):
            raise KeyError(f"Missing truth material for static body '{b_name}'")
        if "friction" not in b_info or b_info["friction"] is None or "restitution" not in b_info or b_info["restitution"] is None:
            raise KeyError(f"Missing truth material for static body '{b_name}'")
        new_boxes.append(
            StaticBox(
                min_point=np.array(b.min_point, copy=True),
                max_point=np.array(b.max_point, copy=True),
                friction=float(b_info["friction"]),
                restitution=float(b_info["restitution"]),
                name=b_name,
            )
        )

    return StaticEnvironment(
        ground=new_ground,
        ramps=new_ramps,
        tables=new_tables,
        boxes=new_boxes,
    )


def _compute_active_static_pairwise(
    body_name: str,
    pos: np.ndarray,
    vel: np.ndarray,
    radius: float,
    static_name: str,
    static_geo: Mapping[str, Any],
) -> tuple[np.ndarray, np.ndarray]:
    """Compute time-series surface distance and normal closing velocity between an active body and a static body.

    Returns:
        (distances, normal_speeds) arrays of shape (T,).
    """
    t_steps = pos.shape[0]
    distances = np.full(t_steps, float("inf"), dtype=np.float64)
    normal_speeds = np.zeros(t_steps, dtype=np.float64)

    name_lower = static_name.lower()
    if "ground" in name_lower or static_geo.get("ground"):
        g_info = static_geo.get("ground") or {}
        z_plane = float(g_info.get("z_plane", 0.0))
        # Distance from bottom of sphere to plane: (z - z_plane) - radius
        distances = (pos[:, 2] - z_plane) - radius
        # Normal is [0, 0, 1]. Closing velocity when falling down: -vel[:, 2]
        normal_speeds = np.abs(vel[:, 2])

    elif "ramp" in name_lower and static_geo.get("ramps"):
        r_info = static_geo["ramps"][0]
        n = np.asarray(r_info["normal"], dtype=np.float64)
        n = n / np.linalg.norm(n)
        pt = np.asarray(r_info["point"], dtype=np.float64)
        # Plane distance minus sphere radius
        diffs = pos - pt
        distances = np.dot(diffs, n) - radius
        normal_speeds = np.abs(np.dot(vel, n))

    elif "table" in name_lower and static_geo.get("tables"):
        t_info = static_geo["tables"][0]
        xb = t_info["x_bounds"]
        yb = t_info["y_bounds"]
        z_top = float(t_info["z_top"])
        thick = float(t_info.get("thickness", 0.20))
        min_pt = np.array([xb[0], yb[0], z_top - thick], dtype=np.float64)
        max_pt = np.array([xb[1], yb[1], z_top], dtype=np.float64)
        for t in range(t_steps):
            p = pos[t]
            q = np.clip(p, min_pt, max_pt)
            d_center = float(np.linalg.norm(p - q))
            distances[t] = d_center - radius
            if d_center > 1e-9:
                n_dir = (p - q) / d_center
                normal_speeds[t] = abs(float(np.dot(vel[t], n_dir)))
            else:
                normal_speeds[t] = float(np.linalg.norm(vel[t]))

    elif static_geo.get("boxes"):
        b_info = static_geo["boxes"][0]
        min_pt = np.asarray(b_info["min_point"], dtype=np.float64)
        max_pt = np.asarray(b_info["max_point"], dtype=np.float64)
        for t in range(t_steps):
            p = pos[t]
            q = np.clip(p, min_pt, max_pt)
            d_center = float(np.linalg.norm(p - q))
            distances[t] = d_center - radius
            if d_center > 1e-9:
                n_dir = (p - q) / d_center
                normal_speeds[t] = abs(float(np.dot(vel[t], n_dir)))
            else:
                normal_speeds[t] = float(np.linalg.norm(vel[t]))

    return distances, normal_speeds


# =========================================================================
# 1. Single Episode Evaluation
# =========================================================================

def evaluate_episode(
    arm: Any,
    student_ep: Mapping[str, Any],
    truth_ep: Mapping[str, Any],
    arm_name: str | None = None,
) -> dict[str, Any]:
    """Evaluate Arm prediction on a single paired episode.

    Parameters:
        arm: prediction arm instance implementing `predict(observed_prefix, static_env, n_future)`.
        student_ep: sanitized student view containing frames, active_bodies, static_environment.
        truth_ep: evaluator view containing pairwise_collisions, metadata, hidden_parameters.
        arm_name: optional name of arm for diagnostic checks.

    Returns:
        Dictionary containing position_errors, collision_f1, energy_drift, and inference_latency.
    """
    frames = student_ep.get("frames", [])
    total_frames = len(frames)
    if total_frames <= PREFIX_FRAMES:
        raise ValueError(
            f"Episode has {total_frames} frames, must be > PREFIX_FRAMES ({PREFIX_FRAMES})"
        )

    remaining_frames = total_frames - PREFIX_FRAMES
    n_future = min(MAX_FUTURE_FRAMES, remaining_frames)

    active_bodies = student_ep.get("active_bodies", {})
    body_names = sorted(active_bodies.keys())
    if not body_names:
        raise ValueError("Episode has no active bodies")

    geometry_by_body: dict[str, BodyGeometry] = {}
    for name in body_names:
        b_info = active_bodies[name]
        if not isinstance(b_info, Mapping):
            raise KeyError(f"Invalid info for body '{name}'")
        geometry_by_body[name] = geometry_from_student_body(b_info)

    # 1. Build observed prefix for arm.predict
    # Each body's prefix is extracted from frames 0 .. PREFIX_FRAMES - 1
    observed_prefix: dict[str, np.ndarray] = {}
    for name in body_names:
        body_traj = []
        for t in range(PREFIX_FRAMES):
            fr_objects = frames[t].get("objects")
            if fr_objects is None or name not in fr_objects:
                raise KeyError(f"Frame {t} missing object '{name}'")
            fr_obj = fr_objects[name]
            for required_field in ("position", "linear_velocity", "orientation", "angular_velocity"):
                if required_field not in fr_obj or fr_obj[required_field] is None:
                    raise KeyError(f"Frame {t} object '{name}' missing required field '{required_field}'")
            p = list(fr_obj["position"])
            v = list(fr_obj["linear_velocity"])
            ori = list(fr_obj["orientation"])
            ang = list(fr_obj["angular_velocity"])
            body_traj.append(p + v + ori + ang)
        observed_prefix[name] = np.asarray(body_traj, dtype=np.float64)

    # Convert student static environment
    static_geo = student_ep.get("static_environment") or {}
    static_env = build_static_environment_from_student(static_geo)

    if is_arm_4(arm):
        effective_static_env = inject_truth_static_materials(static_env, truth_ep)
    else:
        effective_static_env = static_env

    # 2. Invoke arm.predict and measure wall-clock inference latency
    t0 = time.perf_counter()
    pred_res = arm.predict(observed_prefix, effective_static_env, n_future, geometry_by_body=geometry_by_body)
    predict_wall_clock_s = time.perf_counter() - t0
    latency_per_step_s = predict_wall_clock_s / max(n_future, 1)

    # Extract predicted positions and velocities
    pred_positions: dict[str, np.ndarray] = {}
    pred_velocities: dict[str, np.ndarray] = {}
    for name in body_names:
        if hasattr(pred_res, "positions") and name in pred_res.positions:
            pos_arr = np.asarray(pred_res.positions[name], dtype=np.float64)
            vel_arr = np.asarray(pred_res.velocities[name], dtype=np.float64)
        elif isinstance(pred_res, Mapping) and name in pred_res:
            arr = np.asarray(pred_res[name], dtype=np.float64)
            pos_arr = arr[:n_future, 0:3]
            vel_arr = arr[:n_future, 3:6]
        else:
            raise KeyError(f"Predicted trajectory missing for active body '{name}'")
        pred_positions[name] = pos_arr[:n_future]
        pred_velocities[name] = vel_arr[:n_future]

    # 3. Position Errors (compute_horizon_position_errors, PREREG_DRAFT r2 / P89)
    true_positions_all = np.zeros((total_frames, len(body_names), 3), dtype=np.float64)
    for t in range(total_frames):
        for bi, name in enumerate(body_names):
            true_positions_all[t, bi] = frames[t]["objects"][name]["position"]

    pred_future_arr = np.zeros((n_future, len(body_names), 3), dtype=np.float64)
    for bi, name in enumerate(body_names):
        pred_future_arr[:, bi] = pred_positions[name]

    pos_errors = compute_horizon_position_errors(
        pred_future_arr,
        true_positions_all,
        prefix_frames=PREFIX_FRAMES,
        k_steps=DEFAULT_EVAL_K_STEPS,
        exclude_endpoints=True,
        primary_k=PRIMARY_K,
    )

    # 4. Collision Detection and Event F1
    # Future evaluation window frames: [PREFIX_FRAMES, PREFIX_FRAMES + n_future)
    truth_pairwise = truth_ep.get("pairwise_collisions") or {}

    all_pred_events: list[CollisionEvent] = []
    all_true_events: list[CollisionEvent] = []

    # Identify all candidate object pairs from truth pairwise records
    for pair_key, pc_data in truth_pairwise.items():
        parts = pair_key.split(":")
        if len(parts) != 2:
            continue
        c_a, c_b = parts[0], parts[1]

        # Ground truth side events for this pair in the future window
        t_start = PREFIX_FRAMES
        t_end = PREFIX_FRAMES + n_future
        truth_dists = np.asarray(pc_data["distances"][t_start:t_end], dtype=np.float64)
        truth_dists = np.nan_to_num(truth_dists, nan=1e6, posinf=1e6, neginf=-1e6)
        truth_vels = np.asarray(pc_data["normal_speeds"][t_start:t_end], dtype=np.float64)
        truth_vels = np.nan_to_num(truth_vels, nan=0.0, posinf=0.0, neginf=0.0)
        init_contact = bool(pc_data["in_contact"][t_start - 1]) if t_start > 0 else False

        t_events = detect_collision_events(
            truth_dists,
            np.abs(truth_vels),
            contact_tolerance=CONTACT_TOLERANCE_M,
            vel_threshold=COLLISION_VELOCITY_THRESHOLD_MPS,
            debounce_frames=COLLISION_DEBOUNCE_FRAMES,
            pair_id=pair_key,
            initial_in_contact=init_contact,
        )
        all_true_events.extend(t_events)

        # Prediction side events for this pair
        # Determine whether active-active or active-static
        pred_dists = np.full(n_future, 1e6, dtype=np.float64)
        pred_vels = np.zeros(n_future, dtype=np.float64)

        if c_a in body_names and c_b in body_names:
            # Active-active collision
            r_a = float(active_bodies[c_a]["bounding_sphere_radius"])
            r_b = float(active_bodies[c_b]["bounding_sphere_radius"])
            p_a, p_b = pred_positions[c_a], pred_positions[c_b]
            v_a, v_b = pred_velocities[c_a], pred_velocities[c_b]
            for t in range(n_future):
                diff = p_b[t] - p_a[t]
                d_c = float(np.linalg.norm(diff))
                pred_dists[t] = d_c - (r_a + r_b)
                if d_c > 1e-9:
                    n_dir = diff / d_c
                    pred_vels[t] = abs(float(np.dot(v_b[t] - v_a[t], n_dir)))
                else:
                    pred_vels[t] = float(np.linalg.norm(v_b[t] - v_a[t]))

        elif c_a in body_names or c_b in body_names:
            # Active-static collision
            active_name = c_a if c_a in body_names else c_b
            static_name = c_b if c_a in body_names else c_a
            rad = float(active_bodies[active_name]["bounding_sphere_radius"])
            pred_dists, pred_vels = _compute_active_static_pairwise(
                active_name,
                pred_positions[active_name],
                pred_velocities[active_name],
                rad,
                static_name,
                static_geo,
            )

        pred_dists = np.nan_to_num(pred_dists, nan=1e6, posinf=1e6, neginf=-1e6)
        pred_vels = np.nan_to_num(pred_vels, nan=0.0, posinf=0.0, neginf=0.0)

        p_events = detect_collision_events(
            pred_dists,
            pred_vels,
            contact_tolerance=CONTACT_TOLERANCE_M,
            vel_threshold=COLLISION_VELOCITY_THRESHOLD_MPS,
            debounce_frames=COLLISION_DEBOUNCE_FRAMES,
            pair_id=pair_key,
            initial_in_contact=init_contact,
        )
        all_pred_events.extend(p_events)

    collision_f1 = compute_collision_f1(
        all_pred_events,
        all_true_events,
        match_tolerance_frames=COLLISION_MATCH_TOLERANCE_FRAMES,
    )

    # 5. Ballistic Energy Drift
    # Evaluated on predicted trajectories over ground-truth contact-free segments
    # Mass is 1.0 because relative drift |Delta H| / H_0 is mathematically invariant to mass.
    energy_drift_by_body: dict[str, Any] = {}
    valid_mean_drifts: list[float] = []
    valid_max_drifts: list[float] = []
    total_segments_count: int = 0

    for name in body_names:
        # Build truth in-contact mask for this body during future window
        truth_in_contact = np.zeros(n_future, dtype=bool)
        for pair_key, pc_data in truth_pairwise.items():
            if name in pair_key.split(":"):
                in_c = pc_data.get("in_contact", [])
                window_c = in_c[PREFIX_FRAMES : PREFIX_FRAMES + n_future]
                truth_in_contact = truth_in_contact | np.asarray(window_c, dtype=bool)

        drift_dict = compute_ballistic_energy_drift(
            pred_positions[name],
            pred_velocities[name],
            in_contact=truth_in_contact,
            mass=1.0,
            min_segment_frames=BALLISTIC_MIN_FRAMES,
            g=GRAVITY_ACCEL,
        )
        energy_drift_by_body[name] = drift_dict
        total_segments_count += int(drift_dict.get("segments_count", 0))
        if drift_dict.get("mean_drift") is not None:
            valid_mean_drifts.append(float(drift_dict["mean_drift"]))
        if drift_dict.get("max_drift") is not None:
            valid_max_drifts.append(float(drift_dict["max_drift"]))

    energy_drift_summary = {
        "by_body": energy_drift_by_body,
        "segments_count": total_segments_count,
        "mean_drift": float(np.mean(valid_mean_drifts)) if valid_mean_drifts else None,
        "max_drift": float(np.max(valid_max_drifts)) if valid_max_drifts else None,
    }

    return {
        "sequence_id": student_ep.get("sequence_id"),
        "scenario_type": student_ep.get("scenario_type"),
        "prefix_frames": PREFIX_FRAMES,
        "n_future": n_future,
        "pred_positions": {name: arr.tolist() for name, arr in pred_positions.items()},
        "position_errors": pos_errors,
        "collision_f1": collision_f1,
        "energy_drift": energy_drift_summary,
        "inference_latency": {
            "predict_wall_clock_s": predict_wall_clock_s,
            "latency_per_step_s": latency_per_step_s,
        },
        "num_active_bodies": len(body_names),
    }


# =========================================================================
# 2. Cell Evaluation & Arm ④ Diagnostic φ* Extraction
# =========================================================================

PHYSICAL_PARAM_KEYS: tuple[str, ...] = (
    "friction",
    "restitution",
    "mass",
    "linear_damping",
    "angular_damping",
)


def extract_true_phi_from_episode(
    truth_ep: Mapping[str, Any],
) -> dict[str, PhysicalParameters]:
    """Extract true physical parameters from a single truth episode view.

    Parameters:
        truth_ep: evaluator view containing metadata, sequence_id, hidden_parameters.

    Returns:
        Dictionary mapping active body name to PhysicalParameters.

    Raises:
        KeyError: If hidden_parameters is missing or if any required parameter
                  (friction, restitution, mass, linear_damping, angular_damping)
                  is missing for an active body, explicitly naming the body and sequence_id.
        TypeError: If hidden_parameters or any body info is not a Mapping.
    """
    seq_id = str(truth_ep.get("sequence_id", "unknown_seq"))
    h_params = truth_ep.get("hidden_parameters")
    if not isinstance(h_params, Mapping):
        raise KeyError(f"Episode '{seq_id}' missing required hidden_parameters mapping")

    param_map: dict[str, PhysicalParameters] = {}
    for b_name, b_info in h_params.items():
        if not isinstance(b_info, Mapping):
            raise TypeError(
                f"Body '{b_name}' in sequence '{seq_id}' hidden_parameters must be a Mapping, got {type(b_info)}"
            )
        # Skip inactive bodies
        if "is_active" in b_info and not bool(b_info["is_active"]):
            continue
        if b_name in ("Ground", "Ramp", "TableTop", "OccluderWall") and not bool(b_info.get("is_active", False)):
            continue

        for req_field in PHYSICAL_PARAM_KEYS:
            if req_field not in b_info or b_info[req_field] is None:
                raise KeyError(
                    f"Body '{b_name}' in sequence '{seq_id}' missing required parameter '{req_field}'"
                )

        param_map[b_name] = PhysicalParameters(
            friction=float(b_info["friction"]),
            restitution=float(b_info["restitution"]),
            mass=float(b_info["mass"]),
            linear_damping=float(b_info["linear_damping"]),
            angular_damping=float(b_info["angular_damping"]),
        )
    return param_map


def is_arm_4(arm: Any, arm_name: str | None = None) -> bool:
    """Return True if arm is an instance or subclass of TrueParamArm."""
    if isinstance(arm, type) and issubclass(arm, TrueParamArm):
        return True
    if isinstance(arm, TrueParamArm):
        return True
    return False


def evaluate_cell(
    arm: Any,
    student_dir: Path | str,
    evaluator_dir: Path | str,
) -> dict[str, Any]:
    """Evaluate an arm on an entire cell (directory of paired episodes).

    Raises ValueError if no episodes exist (no default values permitted).
    """
    s_path = Path(student_dir)
    e_path = Path(evaluator_dir)
    if not s_path.is_dir() or not e_path.is_dir():
        raise ValueError(f"student_dir ({s_path}) or evaluator_dir ({e_path}) is not a directory")

    # Discover student and evaluator episodes
    student_files = sorted(s_path.glob("*.json"))
    evaluator_files = sorted(e_path.glob("*.json"))

    episodes_data: list[tuple[dict[str, Any], dict[str, Any]]] = []

    if student_files and evaluator_files:
        # Match by sequence_id
        eval_dict: dict[str, dict[str, Any]] = {}
        for ef in evaluator_files:
            try:
                data = json.loads(ef.read_text(encoding="utf-8"))
                sid = data.get("sequence_id") or ef.stem.replace("eval_", "")
                eval_dict[sid] = data
            except Exception:
                continue

        for sf in student_files:
            try:
                s_data = json.loads(sf.read_text(encoding="utf-8"))
                sid = s_data.get("sequence_id") or sf.stem.replace("student_", "")
                if sid in eval_dict:
                    episodes_data.append((s_data, eval_dict[sid]))
            except Exception:
                continue

    # Also support JSONL pairing if directory contains jsonl files
    if not episodes_data:
        s_jsonl = list(s_path.glob("*.jsonl"))
        e_jsonl = list(e_path.glob("*.jsonl"))
        if s_jsonl and e_jsonl:
            e_by_id: dict[str, dict[str, Any]] = {}
            for ej in e_jsonl:
                for line in ej.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        d = json.loads(line)
                        e_by_id[d["sequence_id"]] = d
            for sj in s_jsonl:
                for line in sj.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line:
                        s_d = json.loads(line)
                        sid = s_d.get("sequence_id")
                        if sid in e_by_id:
                            episodes_data.append((s_d, e_by_id[sid]))

    # Strict check: empty dataset must loudly raise ValueError (no default values permitted)
    if not episodes_data:
        raise ValueError(
            f"No valid paired episodes found between student_dir ({student_dir}) and evaluator_dir ({evaluator_dir})"
        )

    episode_summaries: list[dict[str, Any]] = []
    for s_ep, t_ep in episodes_data:
        if is_arm_4(arm):
            phi_map = extract_true_phi_from_episode(t_ep)
            ep_arm = TrueParamArm(true_params=phi_map, geometry_by_body=getattr(arm, "geometry_by_body", None))
        else:
            ep_arm = arm
        res = evaluate_episode(ep_arm, s_ep, t_ep)
        episode_summaries.append(res)

    # Compute macro summary across episodes
    num_ep = len(episode_summaries)
    primary_errors = [
        e["position_errors"]["primary_error_m"]
        for e in episode_summaries
        if e["position_errors"].get("primary_error_m") is not None
    ]

    mean_k_errors: dict[str, float] = {}
    k_n_available: dict[str, int] = {}
    for k in DEFAULT_EVAL_K_STEPS:
        k_str = str(k)
        k_vals = [
            e["position_errors"][k_str]["mean_error_m"]
            for e in episode_summaries
            if k_str in e["position_errors"] and e["position_errors"][k_str].get("mean_error_m") is not None
        ]
        k_n_available[k_str] = len(k_vals)
        if k_vals:
            mean_k_errors[k_str] = float(np.mean(k_vals))

    precisions = [e["collision_f1"]["precision"] for e in episode_summaries]
    recalls = [e["collision_f1"]["recall"] for e in episode_summaries]
    f1s = [e["collision_f1"]["f1"] for e in episode_summaries]

    energy_drifts = [
        e["energy_drift"]["mean_drift"]
        for e in episode_summaries
        if e["energy_drift"].get("mean_drift") is not None
    ]
    latencies = [e["inference_latency"]["latency_per_step_s"] for e in episode_summaries]

    summary = {
        "num_episodes": num_ep,
        "primary_error_m": float(np.mean(primary_errors)) if primary_errors else None,
        "k_step_errors": mean_k_errors,
        "k_step_n_available": k_n_available,
        "collision_precision": float(np.mean(precisions)) if precisions else 0.0,
        "collision_recall": float(np.mean(recalls)) if recalls else 0.0,
        "collision_f1": float(np.mean(f1s)) if f1s else 0.0,
        "mean_energy_drift": float(np.mean(energy_drifts)) if energy_drifts else None,
        "mean_latency_per_step_s": float(np.mean(latencies)) if latencies else 0.0,
    }

    return {
        "episodes": episode_summaries,
        "summary": summary,
    }


# =========================================================================
# 3. Final Partition One-time Evaluation
# =========================================================================

def evaluate_final_once(
    arm_factory: Any,
    sealed_dir: Path | str,
    expected_digest: str,
    *,
    reader_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate arms on sealed final dataset strictly via open_sealed_final_once token.

    Directly reading without a valid token is impossible and strictly forbidden.
    Second read attempt raises FinalPartitionSealed.
    """
    reader = dict(reader_info or {"evaluator": "e1_eval_runner", "pid": os.getpid(), "time": time.time()})

    # Token must be obtained via open_sealed_final_once
    token = open_sealed_final_once(sealed_dir, expected_digest=expected_digest, reader=reader)

    s_file = token.sealed_dir / "student_final.jsonl"
    t_file = token.sealed_dir / "truth_final.jsonl"
    if not s_file.is_file() or not t_file.is_file():
        raise DatasetError(f"Sealed directory missing student_final.jsonl or truth_final.jsonl: {token.sealed_dir}")

    student_episodes: list[dict[str, Any]] = []
    with open(s_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                student_episodes.append(json.loads(line))

    truth_episodes: list[dict[str, Any]] = []
    with open(t_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                truth_episodes.append(json.loads(line))

    if not student_episodes or not truth_episodes:
        raise ValueError(f"Sealed final dataset at {token.sealed_dir} contains no episodes")

    truth_by_id = {ep["sequence_id"]: ep for ep in truth_episodes}

    # Normalize arm dictionary
    arms_map: dict[str, Any] = {}
    if isinstance(arm_factory, Mapping):
        arms_map = dict(arm_factory)
    elif callable(arm_factory):
        if not hasattr(arm_factory, "predict"):
            arm_inst = arm_factory()
            arms_map = {"default_arm": arm_inst}
        else:
            arms_map = {"default_arm": arm_factory}
    else:
        arms_map = {"default_arm": arm_factory}

    arms_results: dict[str, Any] = {}
    for arm_name, arm_obj in arms_map.items():
        if isinstance(arm_obj, type) and issubclass(arm_obj, TrueParamArm):
            actual_arm = arm_obj
        elif callable(arm_obj) and not hasattr(arm_obj, "predict"):
            actual_arm = arm_obj()
        else:
            actual_arm = arm_obj
        ep_summaries = []
        for s_ep in student_episodes:
            sid = s_ep["sequence_id"]
            if sid not in truth_by_id:
                raise ValueError(f"Sequence {sid} in student_final missing from truth_final")
            t_ep = truth_by_id[sid]
            if is_arm_4(actual_arm):
                phi_map = extract_true_phi_from_episode(t_ep)
                ep_arm = TrueParamArm(true_params=phi_map, geometry_by_body=getattr(actual_arm, "geometry_by_body", None))
            else:
                ep_arm = actual_arm
            res = evaluate_episode(ep_arm, s_ep, t_ep, arm_name=arm_name)
            ep_summaries.append(res)

        primary_errors = [
            e["position_errors"]["primary_error_m"]
            for e in ep_summaries
            if e["position_errors"].get("primary_error_m") is not None
        ]
        mean_k_errors = {}
        k_n_available = {}
        for k in DEFAULT_EVAL_K_STEPS:
            k_str = str(k)
            k_vals = [
                e["position_errors"][k_str]["mean_error_m"]
                for e in ep_summaries
                if k_str in e["position_errors"] and e["position_errors"][k_str].get("mean_error_m") is not None
            ]
            k_n_available[k_str] = len(k_vals)
            if k_vals:
                mean_k_errors[k_str] = float(np.mean(k_vals))

        precisions = [e["collision_f1"]["precision"] for e in ep_summaries]
        recalls = [e["collision_f1"]["recall"] for e in ep_summaries]
        f1s = [e["collision_f1"]["f1"] for e in ep_summaries]
        energy_drifts = [e["energy_drift"]["mean_drift"] for e in ep_summaries if e["energy_drift"].get("mean_drift") is not None]
        latencies = [e["inference_latency"]["latency_per_step_s"] for e in ep_summaries]

        arms_results[arm_name] = {
            "episodes": ep_summaries,
            "summary": {
                "num_episodes": len(ep_summaries),
                "primary_error_m": float(np.mean(primary_errors)) if primary_errors else None,
                "k_step_errors": mean_k_errors,
                "k_step_n_available": k_n_available,
                "collision_precision": float(np.mean(precisions)) if precisions else 0.0,
                "collision_recall": float(np.mean(recalls)) if recalls else 0.0,
                "collision_f1": float(np.mean(f1s)) if f1s else 0.0,
                "mean_energy_drift": float(np.mean(energy_drifts)) if energy_drifts else None,
                "mean_latency_per_step_s": float(np.mean(latencies)) if latencies else 0.0,
            },
        }

    return {
        "dataset_digest": token.dataset_digest,
        "token_nonce": token.nonce,
        "sealed_dir": str(token.sealed_dir),
        "arms": arms_results,
    }
