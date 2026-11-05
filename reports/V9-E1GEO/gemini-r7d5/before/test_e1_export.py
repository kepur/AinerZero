"""Unit tests for E1-X dataset export module.

Specifications:
- Verified tick mapping: frame * 2 ticks (120 Hz).
- Z-up identity coordinate assertion.
- Static geometry conversion without friction/restitution.
- Bounding sphere radii calculated from object dimensions.
- Normal speed calculation with analytical hand-crafted check:
  (v_b - v_a) . n != |v_rel|.
- Missing contact distance is +inf.
- Strict leakage guard: intercepts all forbidden keys and prefixes.
- S <-> P pairing present on evaluator side only.
- Final partition sealing and one-time read channel.
- Read-only integration check on AWZ sample pilot train/development (final untouched).
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.e1.export import (
    DEFAULT_SALT,
    FINAL_FILES,
    NON_OBJECT_HIDDEN_KEYS,
    TICKS_PER_FRAME,
    DatasetError,
    FinalPartitionSealed,
    LeakageError,
    assert_no_leakage,
    compute_bounding_sphere_radius,
    compute_pairwise_collisions,
    convert_static_geometry,
    export_sequence,
    final_digest,
    final_inventory,
    final_marker_path,
    frame_to_tick,
    make_opaque_sequence_id,
    map_coordinates,
    open_sealed_final_once,
    seal_final_dataset,
    verify_sealed_final,
)
from ainerzero.v9.experiments.e1.prior import (
    GroundPlane,
    InclinedRamp,
    StaticBox,
    StaticEnvironment,
    TableTop,
)


# =========================================================================
# 1. Tick and Coordinate Mapping
# =========================================================================

def test_tick_and_coordinate_mapping():
    """Verify tick = 2 * frame and coordinate identity."""
    assert TICKS_PER_FRAME == 2

    for frame in (0, 1, 5, 20, 45):
        assert frame_to_tick(frame) == 2 * frame

    # Coordinate mapping identity
    test_coords = [
        (0.0, 0.0, 0.0),
        (1.23, -4.56, 7.89),
        (-0.5, 2.0, -1.0),
    ]
    for c in test_coords:
        mapped = map_coordinates(c)
        assert mapped == c


# =========================================================================
# 2. Geometry Conversion and Bounding Sphere
# =========================================================================

def test_bounding_sphere_radius_calculation():
    """Verify bounding sphere radius for SPHERE (d/2) and BOX (half diagonal)."""
    # Sphere diameter 0.8 -> radius 0.4
    r_sphere = compute_bounding_sphere_radius("SPHERE", (0.8, 0.8, 0.8))
    assert r_sphere == pytest.approx(0.4)

    # Unit box (1.0, 1.0, 1.0) -> diagonal sqrt(3), radius sqrt(3)/2
    r_box = compute_bounding_sphere_radius("BOX", (1.0, 1.0, 1.0))
    expected_r_box = 0.5 * math.sqrt(3.0)
    assert r_box == pytest.approx(expected_r_box)

    # Non-cubic box (1.2, 1.2, 1.0)
    r_box2 = compute_bounding_sphere_radius("BOX", (1.2, 1.2, 1.0))
    expected_r2 = 0.5 * math.sqrt(1.44 + 1.44 + 1.0)
    assert r_box2 == pytest.approx(expected_r2)


def test_static_geometry_conversion_omits_friction_restitution():
    """Verify static geometry converts to prior classes without friction/restitution."""
    raw_meta = {
        "Ground": {
            "shape": "PLANE",
            "is_active": False,
            "dimensions": (30.0, 30.0, 1.0),
            "friction": 0.654,  # Hidden truth - must NOT leak into student geometry!
            "restitution": 0.432,
        },
        "TableTop": {
            "shape": "TABLE",
            "is_active": False,
            "dimensions": (4.0, 2.5, 0.2),
            "friction": 0.25,
            "restitution": 0.35,
        },
        "ActiveActor": {
            "shape": "SPHERE",
            "is_active": True,
            "dimensions": (0.8, 0.8, 0.8),
        },
    }
    first_frame_objs = {
        "Ground": {"position": [0.0, 0.0, -0.5]},
        "TableTop": {"position": [0.0, 0.0, 1.6]},
        "ActiveActor": {"position": [0.0, 0.0, 2.0]},
    }

    student_geo, env = convert_static_geometry(raw_meta, first_frame_objs)

    # 1. Verify Ground: top z = -0.5 + 0.5 = 0.0
    assert student_geo["ground"] == {"z_plane": 0.0}
    assert isinstance(env.ground, GroundPlane)
    assert env.ground.z_plane == 0.0

    # 2. Verify TableTop: z_top = 1.6, bounds (-2.0, 2.0), (-1.25, 1.25)
    assert len(student_geo["tables"]) == 1
    t_info = student_geo["tables"][0]
    assert t_info["z_top"] == 1.6
    assert t_info["x_bounds"] == [-2.0, 2.0]
    assert t_info["y_bounds"] == [-1.25, 1.25]
    assert t_info["thickness"] == 0.2
    assert isinstance(env.tables[0], TableTop)

    # 3. Verify hidden friction/restitution is strictly omitted
    student_str = json.dumps(student_geo)
    assert "friction" not in student_str
    assert "restitution" not in student_str
    assert "0.654" not in student_str
    assert "0.432" not in student_str


# =========================================================================
# 3. Analytical Normal Velocity vs Scalar Relative Speed
# =========================================================================

def test_hand_crafted_normal_velocity_vs_scalar_relative_speed():
    """Verify normal_speed is (v_b - v_a) . n, NOT |v_rel| (scalar relative_speed)."""
    # Hand-crafted collision test:
    # Body A: velocity va = [0.0, 0.0, 0.0]
    # Body B: velocity vb = [1.0, -2.0, 3.0]
    # Contact normal pointing from A to B: n = [0.0, -0.6, 0.8] (unit vector since 0.36 + 0.64 = 1)
    # v_rel = vb - va = [1.0, -2.0, 3.0]
    # Projected normal speed: (vb - va) . n = 1.0 * 0.0 + (-2.0) * (-0.6) + 3.0 * 0.8 = 0.0 + 1.2 + 2.4 = 3.6 m/s
    # Scalar speed: ||vb - va|| = sqrt(1^2 + (-2)^2 + 3^2) = sqrt(14) ~= 3.741657 m/s
    va = [0.0, 0.0, 0.0]
    vb = [1.0, -2.0, 3.0]
    n = [0.0, -0.6, 0.8]

    expected_normal_speed = 3.6
    expected_scalar_speed = math.sqrt(14.0)
    assert expected_normal_speed != pytest.approx(expected_scalar_speed)

    # Construct two frames: frame 0 no contact, frame 1 contact
    frames = [
        {
            "frame": 1,
            "time_seconds": 0.0,
            "objects": {
                "A": {"linear_velocity": va},
                "B": {"linear_velocity": vb},
            },
            "contacts": [],
        },
        {
            "frame": 2,
            "time_seconds": 1.0 / 60.0,
            "objects": {
                "A": {"linear_velocity": va},
                "B": {"linear_velocity": vb},
            },
            "contacts": [
                {
                    "object_a": "A",
                    "object_b": "B",
                    "distance": 0.002,
                    "normal": n,
                    "relative_speed": expected_scalar_speed,  # E0 records scalar |v_rel|
                }
            ],
        },
    ]

    collisions = compute_pairwise_collisions(frames, ["B"], ["A", "B"])
    pair_record = collisions["A:B"]

    # Frame 0: no contact -> distance = +inf, normal_speed = 0.0
    assert pair_record["distances"][0] == float("inf")
    assert pair_record["normal_speeds"][0] == 0.0
    assert not pair_record["in_contact"][0]

    # Frame 1: contact -> distance = 0.002, normal_speed = 3.6 (NOT 3.741657)
    assert pair_record["distances"][1] == pytest.approx(0.002)
    assert pair_record["normal_speeds"][1] == pytest.approx(expected_normal_speed)
    assert pair_record["normal_speeds"][1] != pytest.approx(expected_scalar_speed)
    assert pair_record["relative_speeds_scalar"][1] == pytest.approx(expected_scalar_speed)
    assert pair_record["in_contact"][1]


# =========================================================================
# 4. Strict Leakage Guard
# =========================================================================

def test_leakage_guard_intercepts_all_prohibited_items():
    """Verify assert_no_leakage raises LeakageError for every prohibited key/string."""
    clean_dict = {
        "sequence_id": "abc12345def67890",
        "scenario_type": "ramp_roll",
        "frames": [{"tick": 0, "objects": {"RollingActor": {"position": [0, 0, 1]}}}],
    }
    # Clean passes without error
    assert_no_leakage(clean_dict)

    # 1. Prohibited keys
    bad_keys = [
        "family",
        "world_key",
        "hidden_parameters",
        "mechanisms",
        "paired_p_world_key",
        "contacts",
        "contact_specification",
    ]
    for k in bad_keys:
        contaminated = copy.deepcopy(clean_dict)
        contaminated[k] = "leak"
        with pytest.raises(LeakageError):
            assert_no_leakage(contaminated)

    # 2. Prohibited prefixes in keys or values
    bad_values = [
        "s_train_1001_ramp_roll_000",
        "seq_s_train_ramp_roll_000",
        "s_test",
    ]
    for v in bad_values:
        contaminated = copy.deepcopy(clean_dict)
        contaminated["custom_field"] = v
        with pytest.raises(LeakageError):
            assert_no_leakage(contaminated)

    # 3. Prohibited key prefix
    bad_key_dict = copy.deepcopy(clean_dict)
    bad_key_dict["s_hidden"] = 123
    with pytest.raises(LeakageError):
        assert_no_leakage(bad_key_dict)


# =========================================================================
# 5. S <-> P Pairing and Decoupling
# =========================================================================

def test_s_and_p_pairing_and_decoupling():
    """Verify S-family sequence is sanitized and pairing is kept strictly in eval_view."""
    p_seq = {
        "sequence_id": "seq_train_ramp_roll_000",
        "world_key": "train_1001_ramp_roll_000",
        "family": "P",
        "partition": "train",
        "seed": 1001,
        "scenario_type": "ramp_roll",
        "metadata": {
            "fps": 60,
            "hidden_parameters": {
                "RollingActor": {"shape": "SPHERE", "dimensions": (0.8, 0.8, 0.8), "is_active": True}
            },
        },
        "frames": [
            {
                "frame": 1,
                "time_seconds": 0.0,
                "objects": {
                    "RollingActor": {
                        "position": [0.0, 0.0, 2.0],
                        "linear_velocity": [0.0, 0.0, 0.0],
                        "rotation_quaternion": [1.0, 0.0, 0.0, 0.0],
                        "angular_velocity": [0.0, 0.0, 0.0],
                    }
                },
                "contacts": [],
            }
        ],
    }

    s_seq = copy.deepcopy(p_seq)
    s_seq["sequence_id"] = "seq_s_train_ramp_roll_000"
    s_seq["world_key"] = "s_train_1001_ramp_roll_000"
    s_seq["family"] = "S"
    s_seq["metadata"]["mechanisms"] = [{"id": "quadratic_drag_v1", "params": {"cd": 0.45}}]
    s_seq["metadata"]["paired_p_world_key"] = "train_1001_ramp_roll_000"

    p_student, p_eval = export_sequence(p_seq)
    s_student, s_eval = export_sequence(s_seq, paired_p_e0_data=p_seq)

    # 1. Both student views pass leakage guard
    assert_no_leakage(p_student)
    assert_no_leakage(s_student)

    # 2. Student views have unguessable opaque IDs and NO family tags
    assert p_student["sequence_id"] != p_seq["world_key"]
    assert s_student["sequence_id"] != s_seq["world_key"]
    assert not s_student["sequence_id"].startswith("s_")
    assert "family" not in s_student
    assert "paired_p_world_key" not in s_student

    # 3. Evaluator side maintains exact pairing
    assert s_eval["paired_p_opaque_id"] == p_student["sequence_id"]
    assert s_eval["family"] == "S"
    assert p_eval["family"] == "P"
    assert len(s_eval["mechanisms"]) == 1


def test_real_b25_s_family_hidden_parameters_export():
    """Verify real B25 format where mechanisms and paired_p_world_key reside in hidden_parameters."""
    p_seq = {
        "sequence_id": "b25_ramp_roll_p_seed1001_0",
        "world_key": "ramp_roll_p_seed1001",
        "family": "P",
        "partition": "train",
        "seed": 1001,
        "scenario_type": "ramp_roll",
        "metadata": {
            "fps": 60,
            "hidden_parameters": {
                "RollingActor": {
                    "friction": 0.35,
                    "restitution": 0.2,
                    "mass": 1.5,
                    "linear_damping": 0.05,
                    "angular_damping": 0.1,
                    "is_active": True,
                    "shape": "SPHERE",
                    "dimensions": (0.8, 0.8, 0.8),
                },
                "Ramp": {
                    "friction": 0.4,
                    "restitution": 0.1,
                    "mass": 0.0,
                    "linear_damping": 0.0,
                    "angular_damping": 0.0,
                    "is_active": False,
                    "shape": "RAMP",
                    "dimensions": (5.0, 2.0, 1.0),
                },
            },
        },
        "frames": [
            {
                "frame": 1,
                "time_seconds": 0.0,
                "objects": {
                    "RollingActor": {
                        "position": [0.0, 0.0, 2.0],
                        "linear_velocity": [0.0, 0.0, 0.0],
                        "rotation_quaternion": [1.0, 0.0, 0.0, 0.0],
                        "angular_velocity": [0.0, 0.0, 0.0],
                    }
                },
                "contacts": [],
            }
        ],
    }

    # Real AWZ B25 r3 format: mechanisms and paired_p_world_key injected into hidden_parameters
    s_seq = copy.deepcopy(p_seq)
    s_seq["sequence_id"] = "b25_ramp_roll_s_seed1001_0"
    s_seq["world_key"] = "ramp_roll_s_seed1001"
    s_seq["family"] = "S"
    s_seq["metadata"]["hidden_parameters"]["mechanisms"] = [
        {
            "id": "quadratic_drag_v1",
            "scope": "all_active_objects_all_frames",
            "coefficient": 0.372136,
            "linear_coefficient": 0.0,
        }
    ]
    s_seq["metadata"]["hidden_parameters"]["paired_p_world_key"] = "ramp_roll_p_seed1001"

    # Export both
    p_student, p_eval = export_sequence(p_seq)
    s_student, s_eval = export_sequence(s_seq, paired_p_e0_data=p_seq)

    # 1. Leakage checks
    assert_no_leakage(p_student)
    assert_no_leakage(s_student)

    # 2. Student view assertions: no non-object body keys in active_bodies or frames
    assert "mechanisms" not in s_student["active_bodies"]
    assert "paired_p_world_key" not in s_student["active_bodies"]
    assert "mechanisms" not in s_student
    assert "paired_p_world_key" not in s_student
    for fr in s_student["frames"]:
        assert "mechanisms" not in fr["objects"]
        assert "paired_p_world_key" not in fr["objects"]

    # 3. Evaluator view assertions: mechanisms and paired key extracted correctly
    assert s_eval["family"] == "S"
    assert s_eval["paired_p_opaque_id"] == p_student["sequence_id"]
    assert s_eval["paired_p_world_key"] == "ramp_roll_p_seed1001"
    assert len(s_eval["mechanisms"]) == 1
    assert s_eval["mechanisms"][0]["id"] == "quadratic_drag_v1"
    assert s_eval["mechanisms"][0]["coefficient"] == 0.372136

    # 4. Evaluator view object friction/restitution should NOT include mechanisms or paired key
    assert "mechanisms" not in s_eval["hidden_parameters"]
    assert "paired_p_world_key" not in s_eval["hidden_parameters"]
    assert "RollingActor" in s_eval["hidden_parameters"]


def test_convert_static_geometry_ignores_non_object_keys():
    """Verify convert_static_geometry ignores NON_OBJECT_HIDDEN_KEYS."""
    raw_meta = {
        "Ground": {
            "shape": "PLANE",
            "is_active": False,
            "dimensions": (30.0, 30.0, 1.0),
            "friction": 0.5,
        },
        "mechanisms": [{"id": "quadratic_drag_v1", "coefficient": 0.4}],
        "paired_p_world_key": "ramp_roll_p_1001",
    }
    first_frame_objs = {
        "Ground": {"position": [0.0, 0.0, -0.5]},
    }
    student_geo, env = convert_static_geometry(raw_meta, first_frame_objs)
    assert student_geo["ground"] == {"z_plane": 0.0}
    assert isinstance(env.ground, GroundPlane)
    assert env.ground.z_plane == 0.0


# =========================================================================
# 6. Sealed Final Partition (Read-once Channel)
# =========================================================================

def test_final_partition_sealed_read_once(tmp_path: Path):
    """Verify final partition is sealed and raises FinalPartitionSealed on second read."""
    staging_dir = tmp_path / "staging_final"
    staging_dir.mkdir()

    (staging_dir / "student_final.jsonl").write_text('{"row": 1}\n', encoding="utf-8")
    (staging_dir / "truth_final.jsonl").write_text('{"truth": 1}\n', encoding="utf-8")
    (staging_dir / "export_meta.json").write_text('{"meta": 1}\n', encoding="utf-8")

    sealed_root = tmp_path / "sealed_root"

    # 1. Seal final partition
    seal_record = seal_final_dataset(
        staging_dir,
        sealed_root=sealed_root,
        sealed_by="gemini-t8m4",
    )
    digest = seal_record["dataset_digest"]
    sealed_dir = sealed_root / digest

    # 2. Verify seal passes
    status = verify_sealed_final(sealed_dir, expected_digest=digest)
    assert status["status"] == "passed"
    assert not status["already_read"]

    # 3. First read succeeds and issues FinalReadToken
    reader_info = {"agent": "gemini-t8m4", "purpose": "eval_arm3"}
    token = open_sealed_final_once(sealed_dir, expected_digest=digest, reader=reader_info)
    assert token.dataset_digest == digest
    assert Path(token.marker_path).is_file()

    # 4. Second read MUST be rejected
    with pytest.raises(FinalPartitionSealed, match="already read"):
        open_sealed_final_once(sealed_dir, expected_digest=digest, reader=reader_info)


# =========================================================================
# 7. Read-Only Integration Check on Real Sample Pilot (Train & Dev Only)
# =========================================================================

def test_read_only_integration_on_awz_pilot(tmp_path: Path):
    """Read AWZ pilot train and development samples, export to tmp_path, verify guard.

    Mandate: Do NOT open or access final partition!
    """
    awz_pilot_dir = Path("/Users/mac/AinerWorkFlow/AnimeWorldZero/reports/V9-B20/r1/pilot_raw")
    if not awz_pilot_dir.exists():
        pytest.skip(f"AWZ pilot directory not found at {awz_pilot_dir}")

    exported_count = 0

    for partition in ("train", "development"):
        part_dir = awz_pilot_dir / partition
        out_part_dir = tmp_path / partition
        out_part_dir.mkdir(parents=True, exist_ok=True)

        for seq_file in sorted(part_dir.glob("*.json")):
            with open(seq_file, "r", encoding="utf-8") as f:
                e0_data = json.load(f)

            student_view, eval_view = export_sequence(e0_data)

            # Leakage guard verification
            assert_no_leakage(student_view)

            # Check tick mapping on frames
            for fr in student_view["frames"]:
                assert fr["tick"] == 2 * fr["frame"]

            # Save exported artifacts to tmp_path
            s_out = out_part_dir / f"student_{student_view['sequence_id']}.json"
            e_out = out_part_dir / f"eval_{eval_view['sequence_id']}.json"
            s_out.write_text(json.dumps(student_view, indent=2), encoding="utf-8")
            e_out.write_text(json.dumps(eval_view, indent=2), encoding="utf-8")

            exported_count += 1

    assert exported_count == 12, f"Expected 12 pilot sequences (6 train + 6 dev), got {exported_count}"
