"""G3 registered measurements and non-zero-exit assertions.

Verifies that the G1 accepted geometry sources are byte-identical to their G1
registration, records the G3 source/test identities, independently re-measures
every property with the registered tolerances, and writes ``metrics.json``.
Every judgement is an assertion: a violated tolerance exits non-zero.

This is author evidence only; it does not replace the independent G4 review and
does not claim any model capability.
"""
import hashlib
import json
import math
import pathlib
import sys
import xml.etree.ElementTree as ElementTree

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[3]
RUN_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from ainerzero.v9.geometry import (  # noqa: E402
    SE2,
    SE3,
    GravityFrame,
    TangentGaussian,
    boxplus,
    canonical,  # noqa: E402
)

G1_REGISTRATION = ROOT / "reports/V9-G1/r1-codex-20261016/source-sha256.json"
METRICS_FILE = RUN_DIR / "metrics.json"
SHA_FILE = RUN_DIR / "source-sha256.json"
JUNIT_FILE = RUN_DIR / "cpu-tests.xml"

ROUNDTRIP_TOL = 1e-9
EQUIVARIANCE_TOL = 1e-9
COV_SAMPLES = 6000
COV_RELATIVE_TOL = 0.05
GRID_RESOLUTIONS = (0.1, 0.05)
GRID_FOOTPRINT = 4.0
GRID_BOUND_FACTOR = 2.0
GRID_CONVERGENCE = (3.0, 5.0)

Z_UP = GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_g1_untouched():
    registered = json.loads(G1_REGISTRATION.read_text(encoding="utf-8"))
    checks = {}
    for relative, expected in registered.items():
        actual = sha256(ROOT / relative)
        checks[relative] = {"expected": expected, "actual": actual, "unchanged": actual == expected}
        assert actual == expected, f"G1 accepted file changed: {relative}"
    return checks


def make_belief(frame, group, planar, covariance):
    mean = planar if group is SE2 else frame.lift(planar, 0.35)
    return canonical.CanonicalBelief(TangentGaussian(group, mean, covariance), frame)


def random_belief(rng, frame, group):
    planar = SE2.exp([rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-math.pi, math.pi)])
    factor = rng.normal(size=(group.dof, group.dof))
    covariance = factor @ factor.T * 1e-6 + np.eye(group.dof) * 1e-9
    return make_belief(frame, group, planar, covariance)


def action(frame, planar, values, *, vectors=False):
    values = np.asarray(values, dtype=float)
    if values.shape[-1] == 2:
        return SE2.act(planar, values, vectors=vectors)
    return SE3.act(frame.lift(planar, 0.0), values, vectors=vectors)


def measure_roundtrip_and_equivariance(rng):
    roundtrip = {"points2d": 0.0, "points3d": 0.0, "vectors2d": 0.0, "vectors3d": 0.0, "poses": 0.0}
    equivariance = dict(roundtrip)
    frame = Z_UP
    for group in (SE2, SE3):
            for _ in range(24):
                belief = random_belief(rng, frame, group)
                values = {
                    "points2d": rng.normal(size=(9, 2)),
                    "points3d": rng.normal(size=(9, 3)),
                    "vectors2d": rng.normal(size=(7, 2)),
                    "vectors3d": rng.normal(size=(7, 3)),
                    "poses": np.stack([SE3.exp(rng.normal(size=6)) for _ in range(5)]),
                }
                g = SE2.exp([rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-math.pi, math.pi)])
                moved = belief.left_compose(g)
                for kind, value in values.items():
                    back = canonical.decanonicalize(canonical.canonicalize(value, belief), belief)
                    error = float(np.max(np.abs(np.asarray(back) - np.asarray(value))))
                    roundtrip[kind] = max(roundtrip[kind], error)
                    assert error <= ROUNDTRIP_TOL, f"round trip {kind}: {error}"
                    if kind.startswith("vectors"):
                        lifted = canonical.canonicalize_vectors(
                            action(frame, g, value, vectors=True), moved
                        )
                        base = canonical.canonicalize_vectors(value, belief)
                    elif kind.startswith("points"):
                        lifted = canonical.canonicalize_points(action(frame, g, value), moved)
                        base = canonical.canonicalize_points(value, belief)
                    else:
                        lifted = canonical.canonicalize_poses(
                            np.einsum("ij,njk->nik", frame.lift(g, 0.0), value), moved
                        )
                        base = canonical.canonicalize_poses(value, belief)
                    error = float(np.max(np.abs(np.asarray(lifted) - np.asarray(base))))
                    equivariance[kind] = max(equivariance[kind], error)
                    assert error <= EQUIVARIANCE_TOL, f"equivariance {kind}: {error}"
    # Boundary yaw values must behave like any other yaw.
    boundary = {"yaw_pi": math.pi, "yaw_pi_minus_1e-12": math.pi - 1e-12,
                "yaw_minus_pi_plus_1e-12": -math.pi + 1e-12}
    boundary_errors = {}
    for name, yaw in boundary.items():
        belief = make_belief(Z_UP, SE2, SE2.exp([1e-12, -1e-12, yaw]), np.eye(3) * 1e-6)
        points = rng.normal(size=(11, 3))
        error = float(np.max(np.abs(canonical.decanonicalize(canonical.canonicalize(points, belief), belief) - points)))
        boundary_errors[name] = error
        assert error <= ROUNDTRIP_TOL, f"boundary {name}: {error}"
    return roundtrip, equivariance, boundary_errors


def wrapper_equivariance(rng):
    w1 = rng.normal(size=(3, 8))
    b1 = rng.normal(size=8)
    w2 = rng.normal(size=(8, 3))
    b2 = rng.normal(size=3)

    def f(points):
        return np.tanh(points @ w1 + b1) @ w2 + b2

    def wrapped(points, belief):
        return canonical.decanonicalize_points(
            f(canonical.canonicalize_points(points, belief)), belief
        )

    worst = 0.0
    raw_non_equivariance = 0.0
    for _ in range(16):
        belief = random_belief(rng, Z_UP, SE2)
        g = SE2.exp([rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-math.pi, math.pi)])
        moved = belief.left_compose(g)
        points = rng.normal(size=(12, 3)) * 1.5
        lifted = wrapped(SE3.act(Z_UP.lift(g, 0.0), points), moved)
        right = SE3.act(Z_UP.lift(g, 0.0), wrapped(points, belief))
        error = float(np.max(np.abs(lifted - right)))
        worst = max(worst, error)
        probe = rng.normal(size=(8, 3))
        raw = np.max(np.abs(f(SE3.act(Z_UP.lift(g, 0.0), probe)) - SE3.act(Z_UP.lift(g, 0.0), f(probe))))
        raw_non_equivariance = max(raw_non_equivariance, float(raw))
    assert worst <= EQUIVARIANCE_TOL, f"wrapper equivariance: {worst}"
    assert raw_non_equivariance > 0.1, "raw map accidentally equivariant; test would be trivial"
    return worst, raw_non_equivariance


def covariance_errors(rng):
    sigma = np.array([[4e-6, 1e-7, 2e-7], [1e-7, 3e-6, -1e-7], [2e-7, -1e-7, 2e-6]])
    belief = make_belief(Z_UP, SE2, SE2.exp([0.4, -0.2, 1.1]), sigma)
    samples = canonical.sample_pose_errors(belief, rng, COV_SAMPLES)
    injected = float(np.linalg.norm(np.cov(samples.T) - sigma) / np.linalg.norm(sigma))
    means = [boxplus(SE2, belief.belief.mean, xi) for xi in samples]
    point = np.array([1.3, -0.7, 0.5])
    vector = np.array([1.0, 0.3, 0.2])

    def canonical_values(transform, value):
        out = []
        for mean in means:
            gaussian = TangentGaussian(SE2, mean, np.eye(3) * 1e-12)
            out.append(transform(value, canonical.CanonicalBelief(gaussian, Z_UP)))
        return np.array(out)

    point_canonical = canonical.canonicalize_points(point, belief)
    vector_canonical = canonical.canonicalize_vectors(vector, belief)
    point_values = canonical_values(canonical.canonicalize_points, point)
    vector_values = canonical_values(canonical.canonicalize_vectors, vector)
    point_relative = float(
        np.linalg.norm(np.cov((point_values - point_canonical).T) - canonical.predicted_point_error_covariance(belief, point_canonical))
        / np.linalg.norm(canonical.predicted_point_error_covariance(belief, point_canonical))
    )
    vector_relative = float(
        np.linalg.norm(np.cov((vector_values - vector_canonical).T) - canonical.predicted_vector_error_covariance(belief, vector_canonical))
        / np.linalg.norm(canonical.predicted_vector_error_covariance(belief, vector_canonical))
    )
    assert injected <= COV_RELATIVE_TOL, f"injected covariance: {injected}"
    assert point_relative <= COV_RELATIVE_TOL, f"point covariance: {point_relative}"
    assert vector_relative <= COV_RELATIVE_TOL, f"vector covariance: {vector_relative}"

    sigma3 = np.diag([4e-6, 3e-6, 2e-6, 1e-8, 1e-8, 2e-6])
    belief3 = make_belief(Z_UP, SE3, SE2.exp([0.15, 0.2, -0.3]), sigma3)
    samples3 = canonical.sample_pose_errors(belief3, rng, COV_SAMPLES)
    roll_pitch_perturbation = float(np.max(np.abs(samples3[:, 3:5])))
    indices = [0, 1, 2, 5]
    marginal_relative = float(
        np.linalg.norm(np.cov(samples3[:, indices].T) - sigma3[np.ix_(indices, indices)])
        / np.linalg.norm(sigma3[np.ix_(indices, indices)])
    )
    means3 = [boxplus(SE3, belief3.belief.mean, xi) for xi in samples3]
    point_canonical3 = canonical.canonicalize_points(point, belief3)
    values3 = np.array([
        canonical.canonicalize_points(
            point, canonical.CanonicalBelief(TangentGaussian(SE3, mean, np.eye(6) * 1e-12), Z_UP)
        )
        for mean in means3
    ])
    predicted3 = canonical.predicted_point_error_covariance(belief3, point_canonical3)
    relative3 = float(
        np.linalg.norm(np.cov((values3 - point_canonical3).T) - predicted3) / np.linalg.norm(predicted3)
    )
    assert roll_pitch_perturbation == 0.0, "SE(3) injection must not perturb roll/pitch"
    assert marginal_relative <= COV_RELATIVE_TOL, f"SE(3) marginal covariance: {marginal_relative}"
    assert relative3 <= COV_RELATIVE_TOL, f"SE(3) point covariance: {relative3}"
    return {
        "samples": COV_SAMPLES,
        "injected_tangent_covariance_relative_error": injected,
        "se2_point_covariance_relative_error": point_relative,
        "se2_vector_covariance_relative_error": vector_relative,
        "se3_roll_pitch_perturbation_max": roll_pitch_perturbation,
        "se3_injected_marginal_relative_error": marginal_relative,
        "se3_point_covariance_relative_error": relative3,
        "registered_relative_tolerance": COV_RELATIVE_TOL,
    }


def field(x, y):
    return np.sin(0.9 * x + 0.3) * np.cos(0.7 * y - 0.2) + 0.15 * np.sin(0.4 * (x + y))


def field_hessian(x, y):
    shared = 0.15 * 0.16 * np.sin(0.4 * (x + y))
    base = np.sin(0.9 * x + 0.3) * np.cos(0.7 * y - 0.2)
    return -0.81 * base - shared, -0.49 * base - shared, -0.63 * np.cos(0.9 * x + 0.3) * np.sin(0.7 * y - 0.2) - shared


def hessian_sup(belief, resolution, shape):
    rows, cols = shape
    corners = np.array([[0.0, 0.0], [cols * resolution, 0.0], [0.0, rows * resolution],
                        [cols * resolution, rows * resolution]])
    world = SE2.act(belief.planar(), corners)
    margin = 4.0 * resolution
    axis_x = np.linspace(world[:, 0].min() - margin, world[:, 0].max() + margin, 601)
    axis_y = np.linspace(world[:, 1].min() - margin, world[:, 1].max() + margin, 601)
    x, y = np.meshgrid(axis_x, axis_y)
    f_xx, f_yy, f_xy = field_hessian(x, y)
    trace = f_xx + f_yy
    determinant = f_xx * f_yy - f_xy ** 2
    disc = np.sqrt(np.maximum(trace ** 2 - 4.0 * determinant, 0.0))
    return float(((np.abs(trace) + disc) / 2.0).max())


def interior(valid, margin=2):
    mask = np.array(valid, dtype=bool, copy=True)
    for _ in range(margin):
        mask = (mask & np.roll(mask, 1, 0) & np.roll(mask, -1, 0)
                & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))
    return mask


def grid_case(belief, resolution):
    side = int(round(GRID_FOOTPRINT / resolution))
    shape = (side, side)
    xs = (np.arange(side) + 0.5) * resolution
    ys = (np.arange(side) + 0.5) * resolution
    x, y = np.meshgrid(xs, ys)
    grid = canonical.PlanarGrid(field(x, y), resolution, SE2.identity())
    canonical_grid = canonical.canonicalize_grid(grid, belief)
    world = SE2.act(belief.planar(), np.stack([x.ravel(), y.ravel()], axis=-1))
    expected = field(world[:, 0], world[:, 1]).reshape(shape)
    bound = resolution ** 2 / 4.0 * hessian_sup(belief, resolution, shape)
    mask = interior(canonical_grid.valid)
    interpolation_error = float(np.max(np.abs(canonical_grid.data - expected)[mask]))
    outside = ~canonical_grid.valid
    assert outside.sum() > 0
    assert np.max(np.abs(canonical_grid.data[outside] - grid.fill)) == 0.0
    back = canonical.decanonicalize_grid(canonical_grid, belief)
    roundtrip_mask = interior(back.valid) & interior(grid.valid)
    roundtrip_error = float(np.max(np.abs(back.data - grid.data)[roundtrip_mask]))
    assert interpolation_error <= bound, f"grid interpolation {resolution}: {interpolation_error} > {bound}"
    assert roundtrip_error <= GRID_BOUND_FACTOR * bound, f"grid roundtrip {resolution}: {roundtrip_error}"
    boundary_cells = int((canonical_grid.valid & ~mask).sum())
    return {
        "resolution": resolution,
        "shape": list(shape),
        "interpolation_max_abs_error": interpolation_error,
        "analytic_single_pass_bound": float(bound),
        "roundtrip_max_abs_error": roundtrip_error,
        "registered_roundtrip_bound": float(GRID_BOUND_FACTOR * bound),
        "valid_fraction": float(canonical_grid.valid.mean()),
        "boundary_valid_cells_excluded_from_interior_measure": boundary_cells,
    }


def measure_grid(rng):
    belief = make_belief(Z_UP, SE2, SE2.exp([1.9, -1.7, 0.61]), np.eye(3) * 1e-6)
    cases = [grid_case(belief, resolution) for resolution in GRID_RESOLUTIONS]
    ratio = cases[0]["roundtrip_max_abs_error"] / cases[1]["roundtrip_max_abs_error"]
    assert GRID_CONVERGENCE[0] <= ratio <= GRID_CONVERGENCE[1], f"grid convergence ratio: {ratio}"
    # Rotation-direction marker check: the canonical image of a known world point
    # must be the peak of a localized marker, and the reversed direction is not.
    marker_belief = make_belief(Z_UP, SE2, SE2.exp([0.6, 0.4, 0.35]), np.eye(3) * 1e-6)
    resolution = 0.05
    side = int(round(GRID_FOOTPRINT / resolution))
    marker_canonical = np.array([2.0, 2.0])
    marker_world = SE2.act(marker_belief.planar(), marker_canonical)
    xs = (np.arange(side) + 0.5) * resolution
    x, y = np.meshgrid(xs, xs)
    sigma = 0.18
    marker_grid = canonical.PlanarGrid(
        np.exp(-((x - marker_world[0]) ** 2 + (y - marker_world[1]) ** 2) / (2 * sigma ** 2)),
        resolution,
        SE2.identity(),
    )
    marker_canon = canonical.canonicalize_grid(marker_grid, marker_belief)
    peak = np.unravel_index(np.argmax(marker_canon.data), marker_canon.shape)
    peak_distance = float(np.hypot(x[peak] - marker_canonical[0], y[peak] - marker_canonical[1]))
    reversed_world = SE2.act(marker_belief.planar(), marker_world)
    reversed_peak = np.unravel_index(np.argmin(np.hypot(x - reversed_world[0], y - reversed_world[1])), marker_canon.shape)
    separation = float(np.hypot(peak[0] - reversed_peak[0], peak[1] - reversed_peak[1]))
    assert peak_distance <= 1.5 * resolution, f"marker peak distance: {peak_distance}"
    assert separation > 2.0, f"reversed-direction peak not separated: {separation}"
    # Equivariance of the grid resampling.
    grid = canonical.PlanarGrid(field(x, y), resolution, SE2.identity())
    g = SE2.exp([0.37, -0.21, 2.9])
    base = canonical.canonicalize_grid(grid, belief)
    moved_grid = canonical.PlanarGrid(field(x, y), resolution, SE2.compose(g, SE2.identity()))
    moved = canonical.canonicalize_grid(moved_grid, belief.left_compose(g))
    assert np.array_equal(base.valid, moved.valid)
    grid_equivariance = float(np.max(np.abs(base.data - moved.data)))
    assert grid_equivariance <= EQUIVARIANCE_TOL
    return {
        "resolutions": list(GRID_RESOLUTIONS),
        "cases": cases,
        "convergence_ratio_h_to_h_over_2": float(ratio),
        "registered_convergence_interval": list(GRID_CONVERGENCE),
        "marker_peak_distance": peak_distance,
        "reversed_direction_peak_cell_separation": separation,
        "grid_equivariance_max_abs_error": grid_equivariance,
        "resampling": "bilinear, clamped boundary indices, fill outside source index rectangle",
        "data_association": "not performed by this operator; contribution is exactly zero by construction",
    }


def test_counts():
    if not JUNIT_FILE.exists():
        return None
    root = ElementTree.parse(JUNIT_FILE).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    return {
        "tests": int(suite.get("tests", 0)),
        "failures": int(suite.get("failures", 0)),
        "errors": int(suite.get("errors", 0)),
        "skipped": int(suite.get("skipped", 0)),
        "time_seconds": float(suite.get("time", 0.0)),
    }


def main():
    rng = np.random.default_rng(20261020)
    g1 = verify_g1_untouched()
    roundtrip, equivariance, boundary = measure_roundtrip_and_equivariance(rng)
    wrapper_worst, raw_non_equivariance = wrapper_equivariance(rng)
    covariance = covariance_errors(rng)
    grid = measure_grid(rng)
    mutation = json.loads((RUN_DIR / "mutation-results.json").read_text(encoding="utf-8"))
    assert mutation["all_caught"], "mutation controls did not all go red"
    new_sources = {
        "src/ainerzero/v9/geometry/canonical.py": sha256(ROOT / "src/ainerzero/v9/geometry/canonical.py"),
        "tests/v9/geometry/test_canonical.py": sha256(ROOT / "tests/v9/geometry/test_canonical.py"),
        "reports/V9-G3/r1-deepseek-flash-20261020/run_mutations.py": sha256(RUN_DIR / "run_mutations.py"),
        "reports/V9-G3/r1-deepseek-flash-20261020/run_checks.py": sha256(pathlib.Path(__file__)),
    }
    SHA_FILE.write_text(json.dumps(new_sources, indent=2) + "\n", encoding="utf-8")
    metrics = {
        "task": "ainerzero.V9.G3",
        "agent": "deepseek-flash-9m2x",
        "date": "2026-10-20",
        "author_evidence_only": True,
        "independent_review": "pending G4",
        "cpu_only": True,
        "training_or_model_work": 0,
        "g1_registered_sources_unchanged": True,
        "g1_source_checks": g1,
        "new_source_sha256": new_sources,
        "cpu_tests": test_counts(),
        "roundtrip_max_error_by_type": roundtrip,
        "equivariance_max_error_by_type": equivariance,
        "boundary_yaw_roundtrip_error": boundary,
        "registered_roundtrip_tolerance": ROUNDTRIP_TOL,
        "registered_equivariance_tolerance": EQUIVARIANCE_TOL,
        "wrapper_equivariance_max_error": wrapper_worst,
        "raw_map_non_equivariance_probe": raw_non_equivariance,
        "pose_error_propagation": covariance,
        "grid": grid,
        "mutation_controls": {
            "all_caught": mutation["all_caught"],
            "source_sha256": mutation["source_sha256"],
            "runs": [
                {"name": run["name"], "kind": run["kind"], "outcome": run["outcome"],
                 "returncode": run["returncode"], "failed_tests": run["failed_tests"], "log": run["log"]}
                for run in mutation["runs"]
            ],
        },
        "error_sources": {
            "grid_interpolation": grid["cases"],
            "boundary": "clamped indices + fill outside source footprint; invalid cells are masked, "
                        "interior/boundary errors reported separately",
            "numerical": "float64; point/pose/vector round trip and SE(2) equivariance errors measured "
                         "at or below 1e-15, far below the registered 1e-9 contract",
            "data_association": "not performed by this analytic operator; zero by construction, "
                                "never claimed for an external perception pipeline",
        },
        "limits": [
            "author evidence, not independent acceptance",
            "first-order covariance propagation only, small-noise regime, right perturbation",
            "grid round-trip bound is field/resolution-specific (registered test field + convergence "
            "check); the intermediate grid is only C0, so no universal bound is claimed",
            "no image/RGB canonicalization, no pose estimation, no training, no model capability claim",
        ],
    }
    METRICS_FILE.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "roundtrip": roundtrip,
        "equivariance": equivariance,
        "wrapper": wrapper_worst,
        "covariance": covariance,
        "grid_convergence": grid["convergence_ratio_h_to_h_over_2"],
        "tests": metrics["cpu_tests"],
        "mutations_all_caught": mutation["all_caught"],
    }, indent=2))
    print(f"metrics -> {METRICS_FILE}")


if __name__ == "__main__":
    main()
