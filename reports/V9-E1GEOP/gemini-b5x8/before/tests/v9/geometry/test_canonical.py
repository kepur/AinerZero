"""G3 CPU properties: identity, SE(2) equivariance, pose-error propagation, grids.

All judgements are assertions; registrations used below are deliberately small
and explicit:

- round-trip / equivariance tolerance 1e-9 (task card), measured errors are
  O(1e-15), so the registered bound is the contract, not the achieved value;
- pose-error propagation: N=6000 right-perturbation samples, relative Frobenius
  error of the empirical covariance against the first-order prediction <= 5%
  (sampling noise itself is about sqrt(2/N) ~ 1.8%);
- grid resampling: bilinear with clamped boundary indices and a fill value; the
  analytic single-pass bound is ``B1 = h^2 / 4 * sup ||Hessian f||_2`` for the
  registered C2 test field (derived from the 1-D linear interpolation bound and
  |f_xx| + |f_yy| <= 2 ||H||_2, which is invariant to the cell rotation), the
  registered double-interpolation round-trip bound is ``2 * B1`` and the
  empirical convergence ratio when halving h must lie in [3, 5].
- data association: this operator performs none; that error source is reported
  as exactly zero by construction and is not claimed for any external pipeline.

The module can be replaced by a mutated copy via the
``AINERZERO_CANONICAL_OVERRIDE`` environment variable (used by
``run_mutations.py`` to prove that the deliberately broken variants go red).
"""
import importlib
import importlib.util
import math
import os
import sys

import numpy as np
import pytest

from ainerzero.v9.geometry import SE2, SE3, GravityFrame, TangentGaussian, boxplus

_OVERRIDE = os.environ.get("AINERZERO_CANONICAL_OVERRIDE", "").strip()
if _OVERRIDE:
    _spec = importlib.util.spec_from_file_location("canonical_under_test", _OVERRIDE)
    canonical = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = canonical  # dataclasses need the module registered
    _spec.loader.exec_module(canonical)
else:
    canonical = importlib.import_module("ainerzero.v9.geometry.canonical")

ROUNDTRIP_TOL = 1e-9
EQUIVARIANCE_TOL = 1e-9
COV_SAMPLES = 6000
COV_RELATIVE_TOL = 0.05
GRID_RESOLUTIONS = (0.1, 0.05)
GRID_FOOTPRINT = 4.0
GRID_BOUND_FACTOR = 2.0
GRID_CONVERGENCE = (3.0, 5.0)

Z_UP = GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])
Y_UP = GravityFrame([0.0, -9.81, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0])


def make_belief(frame=Z_UP, group=SE2, mean=None, covariance=None, side="right"):
    if mean is None:
        mean = SE2.identity() if group is SE2 else frame.lift(SE2.identity(), 0.0)
    if covariance is None:
        covariance = np.eye(group.dof) * 1e-6
    return canonical.CanonicalBelief(TangentGaussian(group, mean, covariance, side), frame)


def random_belief(rng, frame=Z_UP, group=SE2, *, translation=2.0):
    planar = SE2.exp(
        [rng.uniform(-translation, translation), rng.uniform(-translation, translation),
         rng.uniform(-math.pi, math.pi)]
    )
    if group is SE2:
        mean = planar
    else:
        mean = frame.lift(planar, rng.uniform(-1.0, 1.0))
    factor = rng.normal(size=(group.dof, group.dof))
    covariance = factor @ factor.T * 1e-6 + np.eye(group.dof) * 1e-9
    return make_belief(frame=frame, group=group, mean=mean, covariance=covariance)


def world_action(frame, planar_pose):
    """``g`` as an SE(3) action matrix on 3-D world points/poses."""
    return frame.lift(planar_pose, 0.0)


def act_points(points, frame, planar_pose):
    points = np.asarray(points, dtype=float)
    if points.shape[-1] == 2:
        return SE2.act(planar_pose, points)
    return SE3.act(world_action(frame, planar_pose), points)


def act_vectors(vectors, frame, planar_pose):
    vectors = np.asarray(vectors, dtype=float)
    if vectors.shape[-1] == 2:
        return SE2.act(planar_pose, vectors, vectors=True)
    return SE3.act(world_action(frame, planar_pose), vectors, vectors=True)


def act_poses(poses, frame, planar_pose):
    return np.einsum("ij,njk->nik", world_action(frame, planar_pose), np.asarray(poses, float))


def act_grid(grid, frame, planar_pose):
    frame_pose = SE2.compose(planar_pose, grid.frame)
    return canonical.PlanarGrid(
        data=grid.data,
        resolution=grid.resolution,
        frame=frame_pose,
        fill=grid.fill,
        valid=grid.valid,
        source_frame=grid.source_frame,
    )


def test_cpu_only_imports():
    forbidden = {"mlx", "torch", "onnxruntime", "tensorflow", "jax"}
    assert not any(name.split(".")[0] in forbidden for name in sys.modules)


def test_height_and_gravity_direction_are_preserved():
    # SE(3) estimate with a non-zero height: only the gravity-aligned part is used.
    planar = SE2.exp([0.42, -0.31, 1.13])
    height = 0.37
    belief = make_belief(group=SE3, mean=Z_UP.lift(planar, height))
    agent_world = Z_UP.lift(planar, height)
    agent_xy = agent_world[:3, 3].copy()
    agent_xy[2] = 0.0
    # A world point at the agent's horizontal position keeps its own world height.
    point = agent_xy + np.array([0.0, 0.0, 1.25])
    expected = np.array([0.0, 0.0, 1.25])
    assert np.max(np.abs(canonical.canonicalize_points(point, belief) - expected)) <= ROUNDTRIP_TOL
    # A point above the agent keeps the same world height (no SE(3) subtraction).
    above = agent_xy + 2.0 * Z_UP.up
    assert np.max(np.abs(canonical.canonicalize_points(above, belief) - np.array([0.0, 0.0, 2.0]))) <= ROUNDTRIP_TOL
    # The agent pose canonicalizes to yaw-free, horizontal-zero with preserved height.
    canonical_agent = canonical.canonicalize_poses(agent_world, belief)
    assert np.max(np.abs(canonical_agent[:3, :3] - np.eye(3))) <= ROUNDTRIP_TOL
    assert np.max(np.abs(canonical_agent[:3, 3] - np.array([0.0, 0.0, height]))) <= ROUNDTRIP_TOL
    # The gravity/up direction is untouched by canonicalization.
    rng = np.random.default_rng(20261020)
    points = rng.normal(size=(32, 3)) * 3.0
    rotated = canonical.canonicalize_points(points, belief)
    assert np.max(np.abs(rotated @ Z_UP.up - points @ Z_UP.up)) <= ROUNDTRIP_TOL
    # Same contract for a Y-up world with an SE(2) belief.
    y_belief = make_belief(frame=Y_UP, mean=SE2.exp([0.2, -0.3, -2.9]))
    y_points = rng.normal(size=(16, 3)) * 2.0
    y_rotated = canonical.canonicalize_points(y_points, y_belief)
    assert np.max(np.abs(y_rotated @ Y_UP.up - y_points @ Y_UP.up)) <= ROUNDTRIP_TOL


def test_roll_pitch_pose_is_rejected_not_silently_normalized():
    planar = SE2.exp([0.1, 0.2, 0.3])
    tilted = SE3.compose(SE3.exp([0, 0, 0, 0.05, 0, 0]), Z_UP.lift(planar, 0.5))
    with pytest.raises(ValueError):
        make_belief(group=SE3, mean=tilted)
    # A yaw-only perturbation of the same estimate is accepted.
    made = make_belief(group=SE3, mean=SE3.compose(SE3.exp([0, 0, 0, 0, 0, 0.05]), Z_UP.lift(planar, 0.5)))
    assert made.planar().shape == (3, 3)


def test_input_validation_and_out_of_scope_images():
    belief = make_belief()
    with pytest.raises(ValueError):
        canonical.canonicalize(np.zeros((8, 8, 3)), belief)  # RGB/image is out of scope
    with pytest.raises(ValueError):
        canonical.canonicalize(np.zeros((5, 4)), belief)
    with pytest.raises(ValueError):
        canonical.canonicalize(np.array([np.nan, 0.0, 0.0]), belief)
    with pytest.raises(TypeError):
        canonical.canonicalize(np.zeros((2, 3)), object())
    with pytest.raises(TypeError):
        canonical.canonicalize("not an input", belief)
    with pytest.raises(ValueError):
        canonical.canonicalize_poses(np.zeros((4, 4)), belief)  # not a proper transform
    with pytest.raises(ValueError):
        canonical.PlanarGrid(np.zeros((4, 4)), 0.0, SE2.identity())
    with pytest.raises(ValueError):
        canonical.PlanarGrid(np.zeros((4, 4)), 0.1, SE2.identity(), valid=np.ones((3, 4), bool))
    grid = canonical.PlanarGrid(np.zeros((5, 5)), 0.1, SE2.identity())
    wrong_belief = make_belief(mean=SE2.exp([0.5, 0.5, 0.5]))
    with pytest.raises(ValueError):
        canonical.decanonicalize_grid(canonical.canonicalize_grid(grid, belief), wrong_belief)


def test_dispatchers_match_typed_functions():
    belief = make_belief(mean=SE2.exp([0.3, -0.2, 0.8]))
    points = np.array([[1.0, 2.0, 3.0], [-1.0, 0.5, 0.0]])
    vectors = np.array([[1.0, 0.0, 0.0], [0.2, -0.4, 0.1]])
    poses = np.stack([SE3.exp([0, 0, 0, 0, 0, 0.1]), SE3.exp([1, 2, 3, 0.1, -0.2, 0.3])])
    np.testing.assert_allclose(
        canonical.canonicalize(canonical.WorldPoints(points), belief),
        canonical.canonicalize_points(points, belief),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        canonical.canonicalize(canonical.WorldVectors(vectors), belief),
        canonical.canonicalize_vectors(vectors, belief),
        atol=1e-12,
    )
    np.testing.assert_allclose(
        canonical.canonicalize(poses, belief), canonical.canonicalize_poses(poses, belief), atol=1e-12
    )
    np.testing.assert_allclose(
        canonical.decanonicalize(canonical.canonicalize(poses, belief), belief), poses, atol=1e-12
    )
    single_point = np.array([1.0, -2.0, 0.5])
    assert canonical.canonicalize(single_point, belief).shape == (3,)
    assert canonical.canonicalize(poses[0], belief).shape == (4, 4)


@pytest.mark.parametrize("frame", [Z_UP, Y_UP])
@pytest.mark.parametrize("group", [SE2, SE3])
def test_roundtrip_is_identity_for_all_supported_inputs(frame, group):
    rng = np.random.default_rng(20261020)
    for _ in range(16):
        belief = random_belief(rng, frame=frame, group=group)
        points_3d = rng.normal(size=(17, 3)) * 2.0
        points_2d = rng.normal(size=(17, 2)) * 2.0
        vectors_3d = rng.normal(size=(9, 3))
        vectors_2d = rng.normal(size=(9, 2))
        poses = np.stack([SE3.exp(rng.normal(size=6)) for _ in range(6)])
        for x, kind in (
            (points_3d, "points3d"),
            (points_2d, "points2d"),
            (canonical.WorldVectors(vectors_3d), "vectors3d"),
            (canonical.WorldVectors(vectors_2d), "vectors2d"),
            (poses, "poses"),
        ):
            canonicalized = canonical.canonicalize(x, belief)
            back = canonical.decanonicalize(canonicalized, belief)
            assert canonicalized.shape == np.asarray(x).shape, kind
            assert np.max(np.abs(back - np.asarray(x))) <= ROUNDTRIP_TOL, kind
        # Empty inputs are legal and stay empty.
        for shape in ((0, 3), (0, 2)):
            empty = np.zeros(shape)
            assert canonical.decanonicalize(canonical.canonicalize(empty, belief), belief).shape == shape
        assert canonical.canonicalize(np.zeros((0, 4, 4)), belief).shape == (0, 4, 4)


@pytest.mark.parametrize("yaw", [math.pi, math.pi - 1e-12, -math.pi + 1e-12, -math.pi + 1e-9,
                                 math.pi - 1e-9, 0.0])
@pytest.mark.parametrize("translation", [0.0, 1e-12, -1e-12])
def test_boundary_yaw_near_pi_and_tiny_translation(yaw, translation):
    rng = np.random.default_rng(20261020)
    belief = make_belief(mean=SE2.exp([translation, -translation, yaw]))
    points = rng.normal(size=(12, 3))
    back = canonical.decanonicalize(canonical.canonicalize(points, belief), belief)
    assert np.max(np.abs(back - points)) <= ROUNDTRIP_TOL
    g = SE2.exp([translation, -translation, yaw + 1e-12])
    moved = belief.left_compose(g)
    error = canonical.canonicalize(act_points(points, Z_UP, g), moved) - canonical.canonicalize(points, belief)
    assert np.max(np.abs(error)) <= EQUIVARIANCE_TOL


@pytest.mark.parametrize("frame", [Z_UP, Y_UP])
@pytest.mark.parametrize("group", [SE2, SE3])
@pytest.mark.parametrize("kind", ["points2d", "points3d", "vectors2d", "vectors3d", "poses"])
def test_canonicalize_equivariance_under_se2_left_action(frame, group, kind):
    rng = np.random.default_rng(20261021)
    for _ in range(12):
        belief = random_belief(rng, frame=frame, group=group)
        g = SE2.exp([rng.uniform(-2, 2), rng.uniform(-2, 2), rng.uniform(-math.pi, math.pi)])
        moved = belief.left_compose(g)
        if kind == "points2d":
            x = rng.normal(size=(13, 2))
            base = canonical.canonicalize_points(x, belief)
            lifted = canonical.canonicalize_points(act_points(x, frame, g), moved)
        elif kind == "points3d":
            x = rng.normal(size=(13, 3))
            base = canonical.canonicalize_points(x, belief)
            lifted = canonical.canonicalize_points(act_points(x, frame, g), moved)
        elif kind == "vectors2d":
            x = rng.normal(size=(11, 2))
            base = canonical.canonicalize_vectors(x, belief)
            lifted = canonical.canonicalize_vectors(act_vectors(x, frame, g), moved)
        elif kind == "vectors3d":
            x = rng.normal(size=(11, 3))
            base = canonical.canonicalize_vectors(x, belief)
            lifted = canonical.canonicalize_vectors(act_vectors(x, frame, g), moved)
        else:
            x = np.stack([SE3.exp(rng.normal(size=6)) for _ in range(7)])
            base = canonical.canonicalize_poses(x, belief)
            lifted = canonical.canonicalize_poses(act_poses(x, frame, g), moved)
        assert np.max(np.abs(lifted - base)) <= EQUIVARIANCE_TOL, kind


def _non_equivariant_map(seed=20261022):
    rng = np.random.default_rng(seed)
    w1 = rng.normal(size=(3, 8))
    b1 = rng.normal(size=8)
    w2 = rng.normal(size=(8, 3))
    b2 = rng.normal(size=3)

    def f(points):
        return np.tanh(points @ w1 + b1) @ w2 + b2

    return f


def _wrap_equivariant(f, belief):
    def wrapped(points):
        y = f(canonical.canonicalize_points(points, belief))
        return canonical.decanonicalize_points(y, belief)

    return wrapped


def test_wrapper_makes_arbitrary_numpy_map_strictly_equivariant():
    rng = np.random.default_rng(20261022)
    f = _non_equivariant_map()
    for _ in range(8):
        belief = random_belief(rng, group=SE2, translation=1.0)
        g = SE2.exp([rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-math.pi, math.pi)])
        points = rng.normal(size=(15, 3)) * 1.5
        wrapped = _wrap_equivariant(f, belief)
        wrapped_moved = _wrap_equivariant(f, belief.left_compose(g))
        left = wrapped_moved(act_points(points, Z_UP, g))
        right = act_points(wrapped(points), Z_UP, g)
        assert np.max(np.abs(left - right)) <= EQUIVARIANCE_TOL
        # The raw map itself is genuinely non-equivariant, so the equality above
        # is produced by canonicalization and not by a trivial f.
        probe = rng.normal(size=(9, 3))
        moved_probe = act_points(probe, Z_UP, g)
        raw_non_equivariance = np.max(np.abs(f(moved_probe) - act_points(f(probe), Z_UP, g)))
        assert raw_non_equivariance > 0.1


def _covariance_relative_error(empirical, predicted):
    return float(np.linalg.norm(empirical - predicted) / np.linalg.norm(predicted))


def test_pose_error_injection_matches_sigma():
    rng = np.random.default_rng(20261023)
    sigma = np.array([[4e-6, 1e-7, 2e-7], [1e-7, 3e-6, -1e-7], [2e-7, -1e-7, 2e-6]])
    belief = make_belief(mean=SE2.exp([0.4, -0.2, 1.1]), covariance=sigma)
    samples = canonical.sample_pose_errors(belief, rng, COV_SAMPLES)
    assert samples.shape == (COV_SAMPLES, 3)
    assert _covariance_relative_error(np.cov(samples.T), sigma) <= COV_RELATIVE_TOL
    # Every injected estimate stays canonicalizable (gravity-aligned contract).
    for xi in samples[:200]:
        canonical.apply_pose_error(belief, xi)
    single = canonical.inject_pose_error(belief, rng)
    assert isinstance(single, canonical.CanonicalBelief)
    assert single.group is SE2
    assert np.array_equal(single.belief.covariance, sigma)
    with pytest.raises(TypeError):
        canonical.sample_pose_errors(belief, "not a generator", 4)
    with pytest.raises(ValueError):
        canonical.sample_pose_errors(belief, np.random.default_rng(1), 0)


def test_first_order_error_propagation_matches_empirical_covariance():
    rng = np.random.default_rng(20261024)
    sigma = np.array([[4e-6, 1e-7, 2e-7], [1e-7, 3e-6, -1e-7], [2e-7, -1e-7, 2e-6]])
    belief = make_belief(mean=SE2.exp([0.4, -0.2, 1.1]), covariance=sigma)
    samples = canonical.sample_pose_errors(belief, rng, COV_SAMPLES)
    means = [boxplus(SE2, belief.belief.mean, xi) for xi in samples]
    point = np.array([1.3, -0.7, 0.5])
    vector = np.array([1.0, 0.3, 0.2])
    point_canonical = canonical.canonicalize_points(point, belief)
    vector_canonical = canonical.canonicalize_vectors(vector, belief)
    point_values = np.array([
        canonical.canonicalize_points(
            point,
            canonical.CanonicalBelief(TangentGaussian(SE2, mean, np.eye(3) * 1e-12), belief.frame),
        )
        for mean in means
    ])
    vector_values = np.array([
        canonical.canonicalize_vectors(
            vector,
            canonical.CanonicalBelief(TangentGaussian(SE2, mean, np.eye(3) * 1e-12), belief.frame),
        )
        for mean in means
    ])
    point_empirical = np.cov((point_values - point_canonical).T)
    vector_empirical = np.cov((vector_values - vector_canonical).T)
    point_predicted = canonical.predicted_point_error_covariance(belief, point_canonical)
    vector_predicted = canonical.predicted_vector_error_covariance(belief, vector_canonical)
    assert _covariance_relative_error(point_empirical, point_predicted) <= COV_RELATIVE_TOL
    assert _covariance_relative_error(vector_empirical, vector_predicted) <= COV_RELATIVE_TOL
    # Height must not be confused with horizontal pose error.
    assert np.max(np.abs(point_predicted[2])) <= 1e-18
    assert np.max(np.abs(vector_predicted[2])) <= 1e-18
    # The prediction is only defined for the registered right-perturbation side.
    left = make_belief(side="left")
    with pytest.raises(ValueError):
        canonical.predicted_point_error_covariance(left, point_canonical)
    with pytest.raises(ValueError):
        canonical.predicted_vector_error_covariance(left, vector_canonical)


def test_se3_gravity_aligned_error_injection_and_propagation():
    rng = np.random.default_rng(20261025)
    sigma = np.diag([4e-6, 3e-6, 2e-6, 1e-8, 1e-8, 2e-6])
    mean = Z_UP.lift(SE2.exp([0.15, 0.2, -0.3]), 0.6)
    belief = make_belief(group=SE3, mean=mean, covariance=sigma)
    samples = canonical.sample_pose_errors(belief, rng, COV_SAMPLES)
    # Roll/pitch coordinates are never perturbed, so every sample stays aligned.
    assert np.max(np.abs(samples[:, 3:5])) == 0.0
    indices = [0, 1, 2, 5]
    marginal = sigma[np.ix_(indices, indices)]
    assert _covariance_relative_error(np.cov(samples[:, indices].T), marginal) <= COV_RELATIVE_TOL
    means = [boxplus(SE3, belief.belief.mean, xi) for xi in samples]
    point = np.array([1.3, -0.7, 0.5])
    canonical_point = canonical.canonicalize_points(point, belief)
    values = np.array([
        canonical.canonicalize_points(
            point,
            canonical.CanonicalBelief(TangentGaussian(SE3, mean, np.eye(6) * 1e-12), belief.frame),
        )
        for mean in means
    ])
    empirical = np.cov((values - canonical_point).T)
    predicted = canonical.predicted_point_error_covariance(belief, canonical_point)
    assert _covariance_relative_error(empirical, predicted) <= COV_RELATIVE_TOL
    assert np.max(np.abs(predicted[2])) <= 1e-18


def grid_field(x, y):
    return np.sin(0.9 * x + 0.3) * np.cos(0.7 * y - 0.2) + 0.15 * np.sin(0.4 * (x + y))


def grid_field_hessian_columns(x, y):
    shared = 0.15 * 0.16 * np.sin(0.4 * (x + y))
    base = np.sin(0.9 * x + 0.3) * np.cos(0.7 * y - 0.2)
    f_xx = -0.81 * base - shared
    f_yy = -0.49 * base - shared
    f_xy = -0.63 * np.cos(0.9 * x + 0.3) * np.sin(0.7 * y - 0.2) - shared
    return f_xx, f_yy, f_xy


def hessian_spectral_sup(belief, resolution, shape):
    """Sup of ||Hessian f||_2 over every world point the resampler can touch."""
    rows, cols = shape
    corners = np.array([[0.0, 0.0], [cols * resolution, 0.0], [0.0, rows * resolution],
                        [cols * resolution, rows * resolution]])
    world = SE2.act(belief.planar(), corners)
    margin = 4.0 * resolution
    low = world.min(axis=0) - margin
    high = world.max(axis=0) + margin
    axis_x = np.linspace(low[0], high[0], 601)
    axis_y = np.linspace(low[1], high[1], 601)
    x, y = np.meshgrid(axis_x, axis_y)
    f_xx, f_yy, f_xy = grid_field_hessian_columns(x, y)
    trace = f_xx + f_yy
    determinant = f_xx * f_yy - f_xy ** 2
    disc = np.sqrt(np.maximum(trace ** 2 - 4.0 * determinant, 0.0))
    spectral = (np.abs(trace) + disc) / 2.0
    return float(spectral.max())


def make_grid(resolution, frame=None, shape=None, field=None):
    if shape is None:
        side = int(round(GRID_FOOTPRINT / resolution))
        shape = (side, side)
    rows, cols = shape
    xs = (np.arange(cols) + 0.5) * resolution
    ys = (np.arange(rows) + 0.5) * resolution
    x, y = np.meshgrid(xs, ys)
    values = grid_field(x, y) if field is None else field(x, y)
    return canonical.PlanarGrid(
        data=values,
        resolution=resolution,
        frame=SE2.identity() if frame is None else frame,
    )


def analytic_bound(belief, resolution, shape):
    return resolution ** 2 / 4.0 * hessian_spectral_sup(belief, resolution, shape)


def interior_mask(valid, margin=2):
    mask = np.array(valid, dtype=bool, copy=True)
    for _ in range(margin):
        mask = (
            mask
            & np.roll(mask, 1, axis=0)
            & np.roll(mask, -1, axis=0)
            & np.roll(mask, 1, axis=1)
            & np.roll(mask, -1, axis=1)
        )
    return mask


def canonical_lattice_world(belief, resolution, shape):
    rows, cols = shape
    xs = (np.arange(cols) + 0.5) * resolution
    ys = (np.arange(rows) + 0.5) * resolution
    x, y = np.meshgrid(xs, ys)
    points = np.stack([x.ravel(), y.ravel()], axis=-1)
    world = SE2.act(belief.planar(), points)
    return world[:, 0].reshape(shape), world[:, 1].reshape(shape)


def test_grid_canonical_values_match_analytic_field():
    belief = make_belief(mean=SE2.exp([1.9, -1.7, 0.61]))
    for resolution in GRID_RESOLUTIONS:
        grid = make_grid(resolution)
        canonical_grid = canonical.canonicalize_grid(grid, belief)
        assert canonical_grid.shape == grid.shape
        assert np.array_equal(canonical_grid.frame, belief.planar())
        assert np.array_equal(canonical_grid.source_frame, grid.frame)
        world_x, world_y = canonical_lattice_world(belief, resolution, grid.shape)
        expected = grid_field(world_x, world_y)
        bound = analytic_bound(belief, resolution, grid.shape)
        interior = interior_mask(canonical_grid.valid)
        error = np.abs(canonical_grid.data - expected)
        assert interior.sum() > 0
        assert np.max(error[interior]) <= bound
        # Cells outside the source footprint are filled and marked invalid.
        outside = ~canonical_grid.valid
        assert outside.sum() > 0
        assert np.max(np.abs(canonical_grid.data[outside] - grid.fill)) == 0.0


def test_grid_validity_mask_matches_independent_predicate():
    belief = make_belief(mean=SE2.exp([0.7, -1.1, -2.4]))
    resolution = 0.1
    grid = make_grid(resolution)
    canonical_grid = canonical.canonicalize_grid(grid, belief)
    rows, cols = grid.shape
    world_x, world_y = canonical_lattice_world(belief, resolution, grid.shape)
    source = np.stack([world_x.ravel(), world_y.ravel()], axis=-1)
    source = SE2.act(SE2.inverse(grid.frame), source)
    row_index = source[:, 1] / resolution - 0.5
    col_index = source[:, 0] / resolution - 0.5
    tol = 1e-12
    expected = (
        (row_index >= -tol) & (row_index <= rows - 1 + tol)
        & (col_index >= -tol) & (col_index <= cols - 1 + tol)
    ).reshape(grid.shape)
    assert np.array_equal(canonical_grid.valid, expected)
    del rows, cols


def test_grid_roundtrip_and_second_order_convergence():
    belief = make_belief(mean=SE2.exp([1.3, -0.9, 2.7]))
    errors = []
    for resolution in GRID_RESOLUTIONS:
        grid = make_grid(resolution)
        canonical_grid = canonical.canonicalize_grid(grid, belief)
        back = canonical.decanonicalize_grid(canonical_grid, belief)
        assert np.array_equal(back.frame, grid.frame)
        interior = interior_mask(back.valid) & interior_mask(grid.valid)
        assert interior.sum() > 0
        error = np.max(np.abs(back.data - grid.data)[interior])
        bound = GRID_BOUND_FACTOR * analytic_bound(belief, resolution, grid.shape)
        assert error <= bound
        errors.append(error)
    ratio = errors[0] / errors[1]
    assert GRID_CONVERGENCE[0] <= ratio <= GRID_CONVERGENCE[1]
    # Data association is not performed by this operator: the only sources of
    # round-trip error are interpolation and boundary masking, never matching.
    # Numerical noise is checked separately below with an agent-aligned grid.
    identity_belief = make_belief(mean=SE2.identity())
    aligned = make_grid(0.05)
    canonical_aligned = canonical.canonicalize_grid(aligned, identity_belief)
    assert np.max(np.abs(canonical_aligned.data - aligned.data)) <= ROUNDTRIP_TOL
    assert np.array_equal(canonical_aligned.valid, aligned.valid)
    restored = canonical.decanonicalize_grid(canonical_aligned, identity_belief)
    assert np.max(np.abs(restored.data - aligned.data)) <= ROUNDTRIP_TOL


def test_grid_equivariance_under_se2_left_action():
    rng = np.random.default_rng(20261026)
    for _ in range(6):
        belief = random_belief(rng, group=SE2, translation=0.5)
        g = SE2.exp([rng.uniform(-0.6, 0.6), rng.uniform(-0.6, 0.6), rng.uniform(-math.pi, math.pi)])
        grid = make_grid(0.1)
        base = canonical.canonicalize_grid(grid, belief)
        moved = canonical.canonicalize_grid(act_grid(grid, Z_UP, g), belief.left_compose(g))
        assert np.array_equal(base.valid, moved.valid)
        assert np.max(np.abs(base.data - moved.data)) <= EQUIVARIANCE_TOL


def test_grid_rotation_direction_is_verified_by_a_localized_marker():
    belief = make_belief(mean=SE2.exp([0.6, 0.4, 0.35]))
    resolution = 0.05
    marker_canonical = np.array([2.0, 2.0])
    marker_world = SE2.act(belief.planar(), marker_canonical)
    sigma = 0.18
    grid = make_grid(resolution, field=lambda x, y: np.exp(-((x - marker_world[0]) ** 2 + (y - marker_world[1]) ** 2) / (2 * sigma ** 2)))
    canonical_grid = canonical.canonicalize_grid(grid, belief)
    expected = canonical.canonicalize_points(marker_world, belief)
    assert np.max(np.abs(expected - marker_canonical)) <= ROUNDTRIP_TOL
    rows, cols = canonical_grid.shape
    xs = (np.arange(cols) + 0.5) * resolution
    ys = (np.arange(rows) + 0.5) * resolution
    x, y = np.meshgrid(xs, ys)
    distance = np.hypot(x - expected[0], y - expected[1])
    peak = np.unravel_index(np.argmax(canonical_grid.data), canonical_grid.shape)
    assert distance[peak] <= 1.5 * resolution
    assert canonical_grid.data[peak] >= 0.9
    # A reversed rotation direction would predict the marker elsewhere, so the
    # assertion above is a genuine direction check and not a symmetric coincidence.
    wrong = SE2.act(belief.planar(), marker_world)
    wrong_distance = np.hypot(x - wrong[0], y - wrong[1])
    wrong_peak = np.unravel_index(np.argmin(wrong_distance), canonical_grid.shape)
    assert np.hypot(peak[0] - wrong_peak[0], peak[1] - wrong_peak[1]) > 2.0


def test_grid_boundary_fill_and_degenerate_grid():
    belief = make_belief(mean=SE2.exp([0.2, 0.1, 0.4]))
    tiny = canonical.PlanarGrid(np.array([[2.0]]), 0.1, belief.planar())
    canonical_tiny = canonical.canonicalize_grid(tiny, belief)
    assert canonical_tiny.shape == (1, 1)
    assert canonical_tiny.valid[0, 0]
    assert canonical_tiny.data[0, 0] == 2.0
    # A grid far from the agent is completely out of the resampled footprint.
    far = canonical.PlanarGrid(np.ones((3, 3)), 0.1, SE2.exp([100.0, 100.0, 0.0]))
    canonical_far = canonical.canonicalize_grid(far, belief)
    assert not canonical_far.valid.any()
    assert np.all(canonical_far.data == far.fill)
