"""E1-X Dataset Export Module: E0 Sequences to Student States & Evaluator Truth.

Specifications & References:
- reports/V9-P48/E1_IMPLEMENTATION_PLAN.md (E1-X row)
- reports/V9-P48/PREREG_DRAFT.md §3 (World and Data)
- AnimeWorldZero B20/B23/B25 specifications
- src/ainerzero/v9/experiments/e1/prior.py (StaticEnvironment & Bodies)
- src/ainerzero/v9/experiments/e1/metrics.py (Normal collision speed)
- src/ainerzero/v9/experiments/s1/data.py (Sealed final partition & one-time read)

Features:
1. Reads E0 sequence JSONs (from AWZ dataset.py / blender_worker.py).
2. Time & Coordinate Mapping: 1 frame (60 fps) = 2 ticks (120 Hz). Z-up coordinate identity.
3. Student-side View:
   - Position, orientation, linear_velocity, angular_velocity for all active bodies.
   - Converted static geometry (GroundPlane, InclinedRamp, TableTop, StaticBox) without friction/restitution.
   - Bounding sphere radii computed from object dimensions.
   - Opaque sequence ID hashed with evaluator-side salt.
   - Forbidden: family, world_key, s_/seq_s_ prefixes, hidden_parameters, mechanisms, paired_p_world_key, contacts.
4. Evaluator-side View:
   - Complete truth metadata, hidden_parameters, mechanisms, S<->P opaque ID pairings.
   - Pairwise collision inputs: distance (+inf if not in contact) and normal_speed (v_b - v_a) . n.
5. Sealed Final Partition:
   - seal_final_dataset, open_sealed_final_once with exclusive READ_ONCE marker.
6. Strict Leakage Guard:
   - Scans student output; raises LeakageError if prohibited keys or substrings are present.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .prior import (
    ActiveBody,
    GroundPlane,
    InclinedRamp,
    PhysicalParameters,
    StaticBox,
    StaticEnvironment,
    TableTop,
)

# --- Time & Coordinate Constants ---
SOURCE_FPS: int = 60
CLOCK_HZ: int = 120
TICKS_PER_FRAME: int = 2  # tick = 2 * frame (locked frozen constant)

DEFAULT_SALT: str = "ainerzero_v9_e1_salt_20261029"

# Prohibited keys in student-side output
PROHIBITED_STUDENT_KEYS: frozenset[str] = frozenset(
    {
        "family",
        "world_key",
        "hidden_parameters",
        "mechanisms",
        "paired_p_world_key",
        "contacts",
        "contact_specification",
        "paired_p_id",
        "paired_p_opaque_id",
        "s_world_key",
        "p_world_key",
    }
)

PROHIBITED_PREFIXES: tuple[str, ...] = ("s_", "seq_s_")

# Pre-registered standard dimensions for canonical E0 objects
STANDARD_OBJECT_DIMENSIONS: dict[str, tuple[float, float, float]] = {
    "Ground": (30.0, 30.0, 1.0),
    "Ramp": (3.0, 5.0, 0.4),
    "RollingActor": (0.8, 0.8, 0.8),
    "BoxBottom": (1.2, 1.2, 1.0),
    "BoxTop": (1.0, 1.0, 1.0),
    "ImpactSphere": (0.8, 0.8, 0.8),
    "TableTop": (4.0, 2.5, 0.2),
    "TableSlider": (0.7, 0.7, 0.6),
    "OccluderWall": (0.2, 2.0, 3.0),
    "OccludedActor": (0.9, 0.9, 0.9),
    "BouncingSphere": (0.8, 0.8, 0.8),
    "BouncingBox": (0.9, 0.9, 0.9),
}

# Registered non-object metadata keys stored inside E0 hidden_parameters dictionary
NON_OBJECT_HIDDEN_KEYS: frozenset[str] = frozenset({
    "mechanisms",
    "paired_p_world_key",
})


class LeakageError(RuntimeError):
    """Raised when ground truth or forbidden metadata leaks into student view."""


class DatasetError(RuntimeError):
    """Generic dataset integrity or specification error."""


class FinalPartitionSealed(DatasetError):
    """Raised when sealed final dataset is unverified or read more than once."""


# =========================================================================
# 1. Coordinate & Time Mapping
# =========================================================================

def map_coordinates(coord: Sequence[float]) -> tuple[float, float, float]:
    """Identity mapping for right-handed Z-up coordinates between E0 and AinerZero."""
    assert len(coord) == 3, f"Coordinate must be 3D, got {coord}"
    x, y, z = float(coord[0]), float(coord[1]), float(coord[2])
    # Coordinate system is strictly identical (Z-up identity mapping)
    assert (x, y, z) == (float(coord[0]), float(coord[1]), float(coord[2]))
    return (x, y, z)


def frame_to_tick(frame_idx: int) -> int:
    """Map 60 fps frame index to 120 Hz tick count."""
    return int(frame_idx * TICKS_PER_FRAME)


# =========================================================================
# 2. Geometry & Bounding Spheres
# =========================================================================

def compute_bounding_sphere_radius(
    shape: str,
    dimensions: Sequence[float],
) -> float:
    """Compute outer bounding sphere radius from object shape and dimensions.

    - For SPHERE: R = d / 2.
    - For BOX / other: R = 0.5 * sqrt(dx^2 + dy^2 + dz^2).
    """
    shape_u = shape.upper()
    if shape_u == "SPHERE":
        return float(dimensions[0]) / 2.0
    dx, dy, dz = float(dimensions[0]), float(dimensions[1]), float(dimensions[2])
    return 0.5 * math.sqrt(dx * dx + dy * dy + dz * dz)


def convert_static_geometry(
    raw_objects_metadata: Mapping[str, Any],
    first_frame_objects: Mapping[str, Any],
) -> tuple[dict[str, Any], StaticEnvironment]:
    """Convert E0 static objects into prior.py static classes and student geometric metadata.

    Crucial: Static surface friction and restitution are hidden parameters and are
    strictly omitted from student-side geometry!
    """
    env = StaticEnvironment(ground=None, ramps=[], tables=[], boxes=[])
    student_geo: dict[str, Any] = {
        "ground": None,
        "ramps": [],
        "tables": [],
        "boxes": [],
    }

    for name, obj_meta in raw_objects_metadata.items():
        if name in NON_OBJECT_HIDDEN_KEYS or not isinstance(obj_meta, Mapping):
            continue
        is_active = bool(obj_meta.get("is_active", True))
        if is_active:
            continue

        shape = str(obj_meta.get("shape", "")).upper()
        dims = obj_meta.get("dimensions")
        if dims is None:
            raise ValueError(f"Missing dimensions for static object {name!r}")

        pose = first_frame_objects.get(name)
        if pose is None:
            raise ValueError(f"Missing first-frame pose for static object {name!r}")
        if "position" not in pose:
            raise ValueError(f"Missing position for static object {name!r}")
        pos = pose["position"]

        if shape == "PLANE" or name == "Ground":
            # Ground top plane: pos[2] + dims[2]/2 (e.g. -0.5 + 0.5 = 0.0)
            z_plane = float(pos[2]) + float(dims[2]) / 2.0
            env.ground = GroundPlane(z_plane=z_plane)
            student_geo["ground"] = {"z_plane": z_plane}

        elif shape == "RAMP" or name == "Ramp":
            # Ramp surface
            mat = pose.get("matrix_world")
            if mat is None or len(mat) < 3:
                raise ValueError(f"Missing matrix_world for static object {name!r}")

            normal = np.array([mat[0][2], mat[1][2], mat[2][2]], dtype=np.float64)
            norm_val = float(np.linalg.norm(normal))
            if norm_val <= 1e-6:
                raise ValueError(f"Degenerate normal in matrix_world for static object {name!r}")
            normal = normal / norm_val

            width = float(dims[0])
            length = float(dims[1])
            thick = float(dims[2])

            point = np.array(pos, dtype=np.float64) + normal * (thick / 2.0)
            x_b = (float(pos[0]) - width / 2.0, float(pos[0]) + width / 2.0)

            # Local y axis (column 1 of matrix_world) projected onto world y
            local_y = np.array([mat[0][1], mat[1][1], mat[2][1]], dtype=np.float64)
            norm_y = float(np.linalg.norm(local_y))
            if norm_y > 1e-6:
                local_y = local_y / norm_y
            delta_y = abs(float(local_y[1])) * (length / 2.0)
            y_b = (float(pos[1]) - delta_y, float(pos[1]) + delta_y)

            ramp_obj = InclinedRamp(point=point, normal=normal, x_bounds=x_b, y_bounds=y_b)
            env.ramps.append(ramp_obj)
            student_geo["ramps"].append(
                {
                    "point": point.tolist(),
                    "normal": normal.tolist(),
                    "x_bounds": list(x_b),
                    "y_bounds": list(y_b),
                }
            )

        elif shape == "TABLE" or name == "TableTop":
            w_x, l_y, thick = float(dims[0]), float(dims[1]), float(dims[2])
            z_top = float(pos[2]) + thick / 2.0
            x_b = (float(pos[0]) - w_x / 2.0, float(pos[0]) + w_x / 2.0)
            y_b = (float(pos[1]) - l_y / 2.0, float(pos[1]) + l_y / 2.0)

            table_obj = TableTop(z_top=z_top, x_bounds=x_b, y_bounds=y_b, thickness=thick)
            env.tables.append(table_obj)
            student_geo["tables"].append(
                {
                    "z_top": z_top,
                    "x_bounds": list(x_b),
                    "y_bounds": list(y_b),
                    "thickness": thick,
                }
            )

        elif shape in ("BOX", "OCCLUDER") or name == "OccluderWall":
            quat = pose.get("rotation_quaternion")
            if quat is None:
                raise ValueError(f"Missing rotation_quaternion for static object {name!r}")
            # Check if rotated away from identity quaternion
            is_identity = (
                abs(abs(float(quat[0])) - 1.0) <= 1e-6
                and abs(float(quat[1])) <= 1e-6
                and abs(float(quat[2])) <= 1e-6
                and abs(float(quat[3])) <= 1e-6
            )
            if not is_identity:
                raise NotImplementedError(
                    f"Rotated static box {name!r} with quaternion {quat} is not supported (only axis-aligned boxes)"
                )

            # Axis-aligned static obstacle box
            dx, dy, dz = float(dims[0]), float(dims[1]), float(dims[2])
            min_pt = np.array([pos[0] - dx / 2.0, pos[1] - dy / 2.0, pos[2] - dz / 2.0])
            max_pt = np.array([pos[0] + dx / 2.0, pos[1] + dy / 2.0, pos[2] + dz / 2.0])

            box_obj = StaticBox(min_point=min_pt, max_point=max_pt)
            env.boxes.append(box_obj)
            student_geo["boxes"].append(
                {
                    "min_point": min_pt.tolist(),
                    "max_point": max_pt.tolist(),
                }
            )

    return student_geo, env


# =========================================================================
# 3. Opaque ID & Leakage Guard
# =========================================================================

def make_opaque_sequence_id(world_key: str, *, salt: str = DEFAULT_SALT) -> str:
    """Generate unguessable opaque sequence ID by salting world_key."""
    payload = f"{world_key}:{salt}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def assert_no_leakage(data: Any, path: str = "$") -> None:
    """Recursively scan data structure and raise LeakageError if any forbidden item is found."""
    if isinstance(data, dict):
        for k, v in data.items():
            k_lower = str(k).lower()
            if k_lower in PROHIBITED_STUDENT_KEYS:
                raise LeakageError(f"Forbidden key {k!r} found at {path}")
            for pfx in PROHIBITED_PREFIXES:
                if k_lower.startswith(pfx):
                    raise LeakageError(f"Forbidden prefix in key {k!r} at {path}")
            assert_no_leakage(v, path=f"{path}.{k}")

    elif isinstance(data, list):
        for idx, item in enumerate(data):
            assert_no_leakage(item, path=f"{path}[{idx}]")

    elif isinstance(data, str):
        val_lower = data.lower()
        for pfx in PROHIBITED_PREFIXES:
            if val_lower.startswith(pfx):
                raise LeakageError(f"Forbidden prefix in value {data!r} at {path}")
        for forbidden in PROHIBITED_STUDENT_KEYS:
            if forbidden in val_lower:
                raise LeakageError(f"Forbidden keyword {forbidden!r} in string at {path}: {data!r}")


# =========================================================================
# 4. Normal Velocity & Pairwise Collision Extraction
# =========================================================================

def compute_pairwise_collisions(
    frames: Sequence[Mapping[str, Any]],
    active_body_names: Sequence[str],
    all_body_names: Sequence[str],
) -> dict[str, dict[str, list[Any]]]:
    """Extract collision inputs for every object pair across all frames.

    Direction convention for normal_speed:
    - Normal vector n is directed from object_a to object_b.
    - Relative velocity is v_rel = v_b - v_a.
    - Projected normal speed: normal_speed = (v_b - v_a) . n.
      When objects are closing (approaching along n), (v_b - v_a) . n < 0.
    - If no contact occurs in frame t:
      distance is float('inf'), normal_speed is 0.0.
    """
    # Sort pairs canonically (name_a < name_b)
    pairs: list[tuple[str, str]] = []
    names_list = sorted(all_body_names)
    for i in range(len(names_list)):
        for j in range(i + 1, len(names_list)):
            pairs.append((names_list[i], names_list[j]))

    num_frames = len(frames)
    collision_records: dict[str, dict[str, list[Any]]] = {}

    for name_a, name_b in pairs:
        pair_key = f"{name_a}:{name_b}"
        collision_records[pair_key] = {
            "distances": [float("inf")] * num_frames,
            "normal_speeds": [0.0] * num_frames,
            "relative_speeds_scalar": [0.0] * num_frames,
            "in_contact": [False] * num_frames,
            "normals": [None] * num_frames,
        }

    for t, frame in enumerate(frames):
        objects = frame.get("objects", {})
        contacts = frame.get("contacts", [])

        for ct in contacts:
            o_a = ct.get("object_a")
            o_b = ct.get("object_b")
            if not o_a or not o_b:
                continue

            # Ensure canonical pair order
            swap = o_a > o_b
            c_a, c_b = (o_b, o_a) if swap else (o_a, o_b)
            pair_key = f"{c_a}:{c_b}"
            if pair_key not in collision_records:
                continue

            dist = float(ct.get("distance", float("inf")))
            raw_n = np.asarray(ct.get("normal", [0.0, 0.0, 1.0]), dtype=np.float64)
            # If swapped, normal from A to B reverses
            n_vec = -raw_n if swap else raw_n

            v_a = np.asarray(objects.get(c_a, {}).get("linear_velocity", [0.0, 0.0, 0.0]), dtype=np.float64)
            v_b = np.asarray(objects.get(c_b, {}).get("linear_velocity", [0.0, 0.0, 0.0]), dtype=np.float64)

            v_rel = v_b - v_a
            norm_speed = float(np.dot(v_rel, n_vec))
            scalar_speed = float(np.linalg.norm(v_rel))

            collision_records[pair_key]["distances"][t] = dist
            collision_records[pair_key]["normal_speeds"][t] = norm_speed
            collision_records[pair_key]["relative_speeds_scalar"][t] = scalar_speed
            collision_records[pair_key]["in_contact"][t] = True
            collision_records[pair_key]["normals"][t] = n_vec.tolist()

    return collision_records


# =========================================================================
# 5. Core Export Function
# =========================================================================

def export_sequence(
    e0_data: Mapping[str, Any],
    *,
    salt: str = DEFAULT_SALT,
    paired_p_e0_data: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Export single E0 sequence into decoupled student view and evaluator truth view.

    Parameters:
        e0_data: E0 ground truth dictionary.
        salt: secret salt for opaque ID generation.
        paired_p_e0_data: optional paired P-family sequence data for S-family export.

    Returns:
        tuple (student_view, eval_view).
    """
    metadata = e0_data.get("metadata", {})
    hidden_params = metadata.get("hidden_parameters", {})
    frames = e0_data.get("frames", [])
    if not frames:
        raise DatasetError("E0 sequence has no frames")

    world_key = e0_data.get("world_key", "")
    family = e0_data.get("family", "P").upper()
    partition = e0_data.get("partition", "train")
    scenario_type = e0_data.get("scenario_type", "unknown")

    # Generate opaque sequence ID
    opaque_id = make_opaque_sequence_id(world_key, salt=salt)

    # 1. Identify active vs static objects, filtering out non-object configuration keys
    first_frame_objs = frames[0].get("objects", {})
    object_hidden_params = {
        k: dict(v) if isinstance(v, Mapping) else v
        for k, v in hidden_params.items()
        if k not in NON_OBJECT_HIDDEN_KEYS and isinstance(v, Mapping)
    }
    all_obj_names = sorted(list(set(list(object_hidden_params.keys()) + list(first_frame_objs.keys()))))

    # For canonical E0 objects, if raw metadata omitted dimensions in hidden_parameters,
    # populate registered standard dimensions to enable exact geometric calculation.
    for name in all_obj_names:
        if name in object_hidden_params and isinstance(object_hidden_params[name], dict):
            if "dimensions" not in object_hidden_params[name] and name in STANDARD_OBJECT_DIMENSIONS:
                object_hidden_params[name]["dimensions"] = STANDARD_OBJECT_DIMENSIONS[name]
        elif name not in object_hidden_params and name in STANDARD_OBJECT_DIMENSIONS:
            object_hidden_params[name] = {"dimensions": STANDARD_OBJECT_DIMENSIONS[name]}

    active_bodies_info: dict[str, dict[str, Any]] = {}
    for name in all_obj_names:
        h_info = object_hidden_params.get(name, {})
        is_active = bool(h_info.get("is_active", True)) if "is_active" in h_info else (name not in ("Ground", "Ramp", "TableTop", "OccluderWall"))
        if is_active:
            shape = str(h_info.get("shape", "BOX")).upper()
            dims = h_info.get("dimensions") or STANDARD_OBJECT_DIMENSIONS.get(name, (1.0, 1.0, 1.0))
            radius = compute_bounding_sphere_radius(shape, dims)
            active_bodies_info[name] = {
                "name": name,
                "shape": shape,
                "dimensions": [float(x) for x in dims],
                "bounding_sphere_radius": round(radius, 6),
            }

    # 2. Convert static geometry
    student_static_geo, _ = convert_static_geometry(object_hidden_params, first_frame_objs)

    # 3. Export student-side frame trajectories
    student_frames: list[dict[str, Any]] = []
    for f_idx, fr in enumerate(frames):
        tick = frame_to_tick(f_idx)
        time_sec = float(fr.get("time_seconds", f_idx / SOURCE_FPS))

        frame_objs: dict[str, dict[str, Any]] = {}
        for b_name in active_bodies_info:
            if b_name in fr.get("objects", {}):
                raw_b = fr["objects"][b_name]
                pos = map_coordinates(raw_b["position"])
                vel = map_coordinates(raw_b.get("linear_velocity", [0.0, 0.0, 0.0]))
                quat = raw_b.get("rotation_quaternion", [1.0, 0.0, 0.0, 0.0])
                ang = raw_b.get("angular_velocity", [0.0, 0.0, 0.0])

                frame_objs[b_name] = {
                    "position": [float(x) for x in pos],
                    "linear_velocity": [float(x) for x in vel],
                    "orientation": [float(x) for x in quat],
                    "angular_velocity": [float(x) for x in ang],
                }

        student_frames.append(
            {
                "tick": tick,
                "frame": f_idx,
                "time_seconds": time_sec,
                "objects": frame_objs,
            }
        )

    # Assemble student view (strictly sanitized)
    student_view: dict[str, Any] = {
        "sequence_id": opaque_id,
        "scenario_type": scenario_type,
        "static_environment": student_static_geo,
        "active_bodies": active_bodies_info,
        "frames": student_frames,
    }

    # Apply strict leakage guard
    assert_no_leakage(student_view)

    # 4. Assemble evaluator truth view
    pairwise_collisions = compute_pairwise_collisions(
        frames,
        list(active_bodies_info.keys()),
        all_obj_names,
    )

    # S <-> P pairing and mechanisms extraction (supporting metadata or hidden_parameters)
    raw_mechanisms = metadata.get("mechanisms")
    if raw_mechanisms is None and "mechanisms" in hidden_params:
        raw_mechanisms = hidden_params["mechanisms"]
    mechanisms = list(raw_mechanisms) if raw_mechanisms else []

    paired_p_world_key = (
        metadata.get("paired_p_world_key")
        or hidden_params.get("paired_p_world_key")
        or (paired_p_e0_data.get("world_key") if paired_p_e0_data else None)
    )

    paired_p_opaque_id = None
    if paired_p_e0_data is not None:
        p_wk = paired_p_e0_data.get("world_key", "")
        paired_p_opaque_id = make_opaque_sequence_id(p_wk, salt=salt)
    elif paired_p_world_key:
        paired_p_opaque_id = make_opaque_sequence_id(paired_p_world_key, salt=salt)

    eval_view: dict[str, Any] = {
        "sequence_id": opaque_id,
        "world_key": world_key,
        "family": family,
        "partition": partition,
        "scenario_type": scenario_type,
        "seed": e0_data.get("seed"),
        "hidden_parameters": object_hidden_params,
        "mechanisms": mechanisms,
        "paired_p_opaque_id": paired_p_opaque_id,
        "paired_p_world_key": paired_p_world_key,
        "pairwise_collisions": pairwise_collisions,
        "metadata": {
            "fps": metadata.get("fps", SOURCE_FPS),
            "total_frames": len(frames),
            "camera": metadata.get("camera"),
            "velocity_specification": metadata.get("velocity_specification"),
        },
    }

    return student_view, eval_view


# =========================================================================
# 6. Final Partition Sealing and One-time Read Channel
# =========================================================================

FINAL_FILES = ("student_final.jsonl", "truth_final.jsonl", "export_meta.json")
SEALED_SCHEMA = "ainerzero.v9.e1.sealed_final.v1"


@dataclass(frozen=True)
class FinalReadToken:
    """Opaque token permitting exactly one evaluation read of the sealed final dataset."""
    dataset_digest: str
    sealed_dir: Path
    marker_path: Path
    nonce: str


def final_inventory(directory: Path | str) -> dict[str, str]:
    """Compute sha256 inventory of required final dataset files."""
    d = Path(directory)
    missing = [f for f in FINAL_FILES if not (d / f).is_file()]
    if missing:
        raise DatasetError(f"Final dataset is missing required files: {missing}")
    return {f: hashlib.sha256((d / f).read_bytes()).hexdigest() for f in FINAL_FILES}


def final_digest(inventory: Mapping[str, str]) -> str:
    """Compute top-level canonical digest of final dataset inventory."""
    record = {"schema": SEALED_SCHEMA, "files": dict(sorted(inventory.items()))}
    canonical = json.dumps(record, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def final_marker_path(sealed_dir: Path | str) -> Path:
    """Return path to exclusive READ_ONCE marker file."""
    p = Path(sealed_dir)
    return p.parent / f"{p.name}.READ_ONCE.json"


def seal_final_dataset(
    staging_dir: Path | str,
    *,
    sealed_root: Path | str,
    sealed_by: str,
) -> dict[str, Any]:
    """Seal a freshly exported final dataset under sealed_root/<digest>/ read-only."""
    staging = Path(staging_dir)
    inventory = final_inventory(staging)
    digest = final_digest(inventory)

    target = Path(sealed_root) / digest
    marker = final_marker_path(target)
    if target.exists() or marker.exists():
        raise DatasetError(f"Refusing to overwrite existing sealed final dataset at {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(parents=True, exist_ok=True)

    for rel in FINAL_FILES:
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staging / rel, target / rel)

    if final_inventory(target) != inventory:
        raise DatasetError("Sealed copy differs from staged final dataset")

    record = {
        "schema": SEALED_SCHEMA,
        "dataset_digest": digest,
        "files": inventory,
        "sealed_by": sealed_by,
        "sealed_at_unix": time.time(),
        "read_once_marker": marker.name,
    }
    (target / "SEALED.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # Set read-only permissions
    for path in sorted(target.rglob("*"), reverse=True):
        os.chmod(path, 0o555 if path.is_dir() else 0o444)
    os.chmod(target, 0o555)

    return record


def verify_sealed_final(sealed_dir: Path | str, *, expected_digest: str) -> dict[str, Any]:
    """Verify integrity of sealed final dataset without opening read marker."""
    d = Path(sealed_dir)
    record_path = d / "SEALED.json"
    if not record_path.is_file():
        return {"status": "missing", "sealed_dir": str(d)}

    record = json.loads(record_path.read_text(encoding="utf-8"))
    inventory = final_inventory(d)
    problems = []

    if record.get("schema") != SEALED_SCHEMA:
        problems.append("SEALED.json schema mismatch")
    if record.get("files") != inventory:
        problems.append("A sealed file was modified after sealing")
    if final_digest(inventory) != record.get("dataset_digest"):
        problems.append("Computed digest mismatch with record")
    if record.get("dataset_digest") != expected_digest:
        problems.append("Recorded digest differs from expected digest")

    marker = final_marker_path(d)
    return {
        "status": "passed" if not problems else "failed",
        "problems": problems,
        "dataset_digest": record.get("dataset_digest"),
        "already_read": marker.exists(),
        "marker_path": str(marker),
    }


def open_sealed_final_once(
    sealed_dir: Path | str,
    *,
    expected_digest: str,
    reader: Mapping[str, Any],
) -> FinalReadToken:
    """Open sealed final dataset for evaluation exactly once."""
    d = Path(sealed_dir)
    status = verify_sealed_final(d, expected_digest=expected_digest)
    if status["status"] != "passed":
        raise FinalPartitionSealed(
            f"Sealed final dataset verification failed: {status.get('problems')}"
        )

    marker = final_marker_path(d)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    except FileExistsError as exc:
        raise FinalPartitionSealed(
            f"The sealed final dataset was already read ({marker.name} exists)"
        ) from exc

    nonce = hashlib.sha256(f"{expected_digest}:{time.time_ns()}:{os.getpid()}".encode()).hexdigest()
    with os.fdopen(fd, "w", encoding="utf-8") as h:
        h.write(
            json.dumps(
                {
                    "dataset_digest": expected_digest,
                    "opened_at_unix": time.time(),
                    "pid": os.getpid(),
                    "reader": dict(reader),
                    "nonce": nonce,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    return FinalReadToken(
        dataset_digest=expected_digest,
        sealed_dir=d,
        marker_path=marker,
        nonce=nonce,
    )
