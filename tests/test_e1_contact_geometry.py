"""Prediction-side collision geometry (r2).

Covers:
- Parity with the truth side: AnimeWorldZero E0's compute_exact_shape_distance.
- Static bodies rebuilt from the student view, chosen by the pair's name.
- A perfect prediction scores collision F1 = 1 on real development episodes, the check that
  exposed the original defect: before r2 it scored 0.565 (P) and 0.589 (S).
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import re
import sys

import numpy as np
import pytest

from ainerzero.v9.experiments.e1 import contact_geometry as cg
from ainerzero.v9.experiments.e1 import eval_runner, spec

pytestmark = pytest.mark.native_mlx(reason="real MLX import at collection via the e1 package (arms_net) (A39)")

TOL = 0.004
E0_WORKER = spec.AWZ_ROOT / "python" / "animeworld" / "e0" / "blender_worker.py"
DEV_ROOT = spec.REGISTERED_HOST_DATASETS


def _load_e0_worker():
    if not E0_WORKER.is_file():
        pytest.skip(f"AnimeWorldZero not available at {E0_WORKER}")
    module_spec = importlib.util.spec_from_file_location("e1_test_blender_worker", E0_WORKER)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def _random_quat(rng):
    q = rng.normal(size=4)
    return tuple(float(x) for x in q / np.linalg.norm(q))


def _prim(shape, pos, quat, dims):
    if shape == "SPHERE":
        r = dims[0] / 2.0
        return cg.Primitive(True, (r, r, r), tuple(pos))
    half = (dims[0] / 2.0, dims[1] / 2.0, dims[2] / 2.0)
    return cg.Primitive(False, half, tuple(pos), cg.quat_to_rotation(quat))


@pytest.mark.parametrize(
    "shape_a, shape_b",
    [("BOX", "BOX"), ("BOX", "SPHERE"), ("SPHERE", "BOX"), ("SPHERE", "SPHERE")],
)
def test_distance_matches_e0_truth_function(shape_a, shape_b):
    e0 = _load_e0_worker()
    rng = np.random.default_rng(20261105)
    near = 0
    for _ in range(1500):
        dims_a = tuple(float(x) for x in rng.uniform(0.3, 1.4, 3))
        dims_b = tuple(float(x) for x in rng.uniform(0.3, 1.4, 3))
        if shape_a == "SPHERE":
            dims_a = (dims_a[0],) * 3
        if shape_b == "SPHERE":
            dims_b = (dims_b[0],) * 3
        pos_a = tuple(float(x) for x in rng.uniform(-0.2, 0.2, 3))
        quat_a, quat_b = _random_quat(rng), _random_quat(rng)

        # Sample around the contact shell, where the decision matters.
        direction = rng.normal(size=3)
        direction /= np.linalg.norm(direction)
        pos_b = tuple(float(x) for x in np.array(pos_a) + direction * rng.uniform(0.2, 1.6))

        true_d, true_n = e0.compute_exact_shape_distance(
            shape_a, pos_a, quat_a, dims_a, shape_b, pos_b, quat_b, dims_b
        )
        ours_d, ours_n = cg.surface_distance(
            _prim(shape_a, pos_a, quat_a, dims_a),
            _prim(shape_b, pos_b, quat_b, dims_b),
            contact_tolerance=TOL,
        )
        assert (true_d <= TOL) == (ours_d <= TOL), f"contact decision differs: {true_d} vs {ours_d}"
        if true_d <= TOL:
            near += 1
            assert ours_d == pytest.approx(true_d, abs=1e-9)
            np.testing.assert_allclose(ours_n, true_n, atol=1e-9)
    assert near > 100


def test_ground_uses_the_exact_box_bottom_not_its_bounding_sphere():
    ground = cg.static_primitive("Ground", {"ground": {"z_plane": 0.0}})
    box = cg.Primitive(False, (0.6, 0.6, 0.5), (0.0, 0.0, 0.5), cg.IDENTITY_ROTATION)
    d, n = cg.surface_distance(ground, box, contact_tolerance=TOL)
    assert d == pytest.approx(0.0, abs=1e-12)
    np.testing.assert_allclose(n, (0.0, 0.0, 1.0), atol=1e-12)

    # 0.985 m bounding sphere: the old prediction side called this box deep in the ground at z = 0.9.
    box_high = cg.Primitive(False, (0.6, 0.6, 0.5), (0.0, 0.0, 0.9), cg.IDENTITY_ROTATION)
    assert cg.surface_distance(ground, box_high, contact_tolerance=TOL)[0] > TOL


def test_rebuilt_ramp_thickness_is_the_one_e0_scenes_use():
    scenarios = spec.AWZ_ROOT / "python" / "animeworld" / "e0" / "scenarios.py"
    if not scenarios.is_file():
        pytest.skip(f"AnimeWorldZero not available at {scenarios}")
    match = re.search(r"ramp_thickness = ([0-9.]+)", scenarios.read_text(encoding="utf-8"))
    assert float(match.group(1)) == cg.E0_RAMP_THICKNESS_M


def test_ramp_matches_the_e0_box_it_came_from():
    e0 = _load_e0_worker()
    angle = math.radians(28.0)
    dims = (3.0, 5.0, cg.E0_RAMP_THICKNESS_M)
    pos = (0.0, 0.0, 2.5 * math.sin(angle))
    quat = (math.cos(angle / 2.0), math.sin(angle / 2.0), 0.0, 0.0)
    R = cg.quat_to_rotation(quat)
    normal = (R[0][2], R[1][2], R[2][2])
    point = tuple(pos[i] + normal[i] * dims[2] / 2.0 for i in range(3))
    delta_y = abs(R[1][1]) * dims[1] / 2.0
    static_geo = {
        "ramps": [
            {
                "point": list(point),
                "normal": list(normal),
                "x_bounds": [pos[0] - 1.5, pos[0] + 1.5],
                "y_bounds": [pos[1] - delta_y, pos[1] + delta_y],
            }
        ]
    }
    ramp = cg.static_primitive("Ramp", static_geo)

    rng = np.random.default_rng(7)
    for _ in range(300):
        p = tuple(float(x) for x in np.array(pos) + rng.uniform(-2.0, 2.0, 3))
        true_d, _ = e0.compute_exact_shape_distance("SPHERE", p, (1.0, 0, 0, 0), (0.8, 0.8, 0.8), "RAMP", pos, quat, dims)
        ours_d, _ = cg.surface_distance(
            cg.Primitive(True, (0.4, 0.4, 0.4), p), ramp, contact_tolerance=TOL
        )
        assert ours_d == pytest.approx(true_d, abs=1e-9)


def test_static_bodies_are_chosen_by_name_not_by_what_the_scene_contains():
    """The defect: any scene with a ground routed every static pair to the ground."""
    static_geo = {
        "ground": {"z_plane": 0.0},
        "tables": [{"z_top": 1.7, "x_bounds": [-2.0, 2.0], "y_bounds": [-1.0, 1.0], "thickness": 0.2}],
        "boxes": [{"min_point": [-0.1, -2.5, 0.0], "max_point": [0.1, -0.5, 3.0]}],
    }
    ball_on_table = cg.Primitive(True, (0.4, 0.4, 0.4), (0.0, 0.0, 2.1))
    assert cg.surface_distance(ball_on_table, cg.static_primitive("TableTop", static_geo), contact_tolerance=TOL)[0] == pytest.approx(0.0, abs=1e-9)
    assert cg.surface_distance(ball_on_table, cg.static_primitive("Ground", static_geo), contact_tolerance=TOL)[0] == pytest.approx(1.7, abs=1e-9)

    ball_at_wall = cg.Primitive(True, (0.4, 0.4, 0.4), (0.5, -1.5, 1.5))
    assert cg.surface_distance(ball_at_wall, cg.static_primitive("OccluderWall", static_geo), contact_tolerance=TOL)[0] == pytest.approx(0.0, abs=1e-9)


def test_unrecognized_static_body_is_an_error():
    with pytest.raises(ValueError):
        cg.static_primitive("Mystery", {"ground": {"z_plane": 0.0}, "boxes": []})
    with pytest.raises(ValueError):
        cg.static_primitive("Ramp", {"ramps": []})


class _Oracle:
    name = "oracle"

    def __init__(self, frames):
        self._frames = frames

    def predict(self, prefix, env, n_future, *, geometry_by_body=None, **kwargs):
        start = eval_runner.PREFIX_FRAMES
        out = {}
        for name in prefix:
            rows = []
            for t in range(start, start + n_future):
                o = self._frames[t]["objects"][name]
                rows.append(o["position"] + o["linear_velocity"] + o["orientation"] + o["angular_velocity"])
            out[name] = np.array(rows, dtype=np.float64)
        return out


@pytest.mark.parametrize("family", spec.FAMILIES)
def test_perfect_prediction_scores_f1_one_on_real_episodes(family):
    student_dir = DEV_ROOT / "student" / family / "development"
    evaluator_dir = DEV_ROOT / "evaluator" / family / "development"
    files = sorted(student_dir.glob("*.json"))
    if not files:
        pytest.skip(f"Development data not available at {student_dir}")

    seen_scenes = set()
    events = 0
    for path in files[::4]:
        student = json.loads(path.read_text(encoding="utf-8"))
        truth = json.loads((evaluator_dir / path.name).read_text(encoding="utf-8"))
        result = eval_runner.evaluate_episode(_Oracle(student["frames"]), student, truth)["collision_f1"]
        assert result["f1"] == pytest.approx(1.0), f"{path.name} ({student['scenario_type']}): {result}"
        assert result["false_positives"] == 0
        assert result["false_negatives"] == 0
        seen_scenes.add(student["scenario_type"])
        events += result["num_true_events"]
    assert seen_scenes == {"bounce_collision", "box_stack", "occlusion_pass", "ramp_roll", "table_slide"}
    assert events > 50
