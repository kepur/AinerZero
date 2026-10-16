"""S0 CPU properties and boundary cases; no model runtime imports."""
import math
import sys

import numpy as np
import pytest

from ainerzero.v9.geometry import (
    SE2,
    SE3,
    GravityFrame,
    KnownRotationGaussian,
    ObservabilityError,
    RelativeFactor,
    TangentGaussian,
    bounded_translation_update,
    boxminus,
    boxplus,
    linear_translation_error_bound,
    skew,
    solve_pose_graph,
    tangent_jacobian,
)


def close(a, b, tol=1e-9):
    assert np.max(np.abs(np.asarray(a) - np.asarray(b))) <= tol


def matrix_exponential(a):
    """Independent convergent matrix series for bounded test matrices."""
    out, term = np.eye(len(a)), np.eye(len(a))
    for k in range(1, 120):
        term = term @ a / k
        out += term
        if np.max(np.abs(term)) < 1e-17:
            break
    return out


@pytest.mark.parametrize("group", [SE2, SE3])
def test_random_group_properties_and_independent_exp(group):
    rng = np.random.default_rng(20261016)
    for _ in range(128):
        twists = rng.uniform(-1, 1, (3, group.dof))
        twists[:, :group.dim] *= 10
        a, b, c = [group.exp(x) for x in twists]
        close(group.compose(group.compose(a, b), c), group.compose(a, group.compose(b, c)))
        close(group.compose(a, group.inverse(a)), group.identity())
        close(group.exp(group.log(a)), a)
        hat = np.zeros_like(a)
        hat[:group.dim, group.dim] = twists[0, :group.dim]
        hat[:group.dim, :group.dim] = (skew(twists[0, 3:]) if group is SE3
                                      else np.array([[0, -twists[0, 2]], [twists[0, 2], 0]]))
        close(group.exp(twists[0]), matrix_exponential(hat))
        for side in ("left", "right"):
            close(boxplus(group, a, boxminus(group, b, a, side=side), side=side), b)
        close(group.act(a, group.act(b, np.ones(group.dim))), group.act(group.compose(a, b), np.ones(group.dim)))


@pytest.mark.parametrize("group", [SE2, SE3])
@pytest.mark.parametrize("angle", [0, 1e-12, 1e-8, 1e-4, math.pi - 1e-5, math.pi - 1e-8, math.pi - 1e-12, math.pi])
def test_small_angles_near_pi_principal_transform_roundtrip(group, angle):
    rng = np.random.default_rng(20261016)
    axes = [np.array([1., 0, 0]), np.array([0., 1, 0]), np.array([0., 0, -1])]
    axes += [x / np.linalg.norm(x) for x in rng.normal(size=(12, 3))]
    for axis in axes:
        xi = (np.r_[[2., -3.], angle] if group is SE2 else np.r_[[2., -3., 1.], axis * angle])
        transform = group.exp(xi)
        principal = group.log(transform)
        close(group.exp(principal), transform)
        assert np.linalg.norm(principal[group.dim:]) <= math.pi + 1e-12
    # Tangent is non-injective: the test must not require log(exp(xi))=xi globally.
    xi = np.zeros(group.dof)
    xi[-1] = 2 * math.pi
    assert np.linalg.norm(group.log(group.exp(xi))) < 1e-9


@pytest.mark.parametrize("group", [SE2, SE3])
def test_adjoint_by_conjugation_and_left_right_errors(group):
    xi = np.arange(1, group.dof + 1) / 10
    mu = group.exp(xi)
    delta = np.arange(group.dof) / 13 - 0.2
    expected = group.compose(group.compose(mu, group.exp(delta)), group.inverse(mu))
    close(group.exp(group.adjoint(mu) @ delta), expected)
    close(boxplus(group, mu, delta), boxplus(group, mu, group.adjoint(mu) @ delta, side="left"))
    close(group.adjoint(group.inverse(mu)), np.linalg.inv(group.adjoint(mu)))


@pytest.mark.parametrize("group", [SE2, SE3])
@pytest.mark.parametrize("side", ["right", "left"])
def test_reset_jacobian_by_finite_difference(group, side):
    xi = np.arange(1, group.dof + 1) / 20
    new_mean = group.exp(xi)
    eps = 1e-6
    columns = []
    for d in np.eye(group.dof) * eps:
        p = boxminus(group, group.exp(xi + d), new_mean, side=side)
        m = boxminus(group, group.exp(xi - d), new_mean, side=side)
        columns.append((p - m) / (2 * eps))
    close(tangent_jacobian(group, xi, side=side), np.column_stack(columns), 2e-6)


@pytest.mark.parametrize("group", [SE2, SE3])
def test_gaussian_prediction_convention_and_covariance(group):
    mu = group.exp(np.arange(group.dof) / 7)
    p = np.diag(np.arange(1, group.dof + 1) / 10)
    right = TangentGaussian(group, mu, p)
    left = right.with_side("left")
    close(left.with_side("right").covariance, p)
    for dt in (0, 1e-12, 1 / 120, 10):
        a = right.predict(np.ones(group.dof) * .01, dt, np.eye(group.dof) * .001)
        b = left.predict(np.ones(group.dof) * .01, dt, np.eye(group.dof) * .001).with_side("right")
        close(a.mean, b.mean)
        close(a.covariance, b.covariance)
        close(a.covariance, a.covariance.T)
        assert np.linalg.eigvalsh(a.covariance)[0] > 0
    close(right.predict(np.ones(group.dof), 0, np.zeros_like(p)).mean, mu)
    # Extreme finite dt with tiny known velocities remains a valid bounded transform.
    extreme = right.predict(np.ones(group.dof) * 1e-12, 1e12, np.zeros_like(p))
    group.validate(extreme.mean)


@pytest.mark.parametrize("group", [SE2, SE3])
def test_position_updates_and_local_left_right_equivalence(group):
    mu = group.exp(np.arange(group.dof) / 10)
    right = TangentGaussian(group, mu, np.eye(group.dof) * .01)
    left = right.with_side("left")
    z = mu[:group.dim, group.dim] + np.ones(group.dim) * 1e-7
    a, _ = right.update_position(z, np.eye(group.dim) * .001)
    b, _ = left.update_position(z, np.eye(group.dim) * .001)
    close(a.mean, b.mean)
    close(a.covariance, b.with_side("right").covariance, 2e-6)
    assert np.linalg.eigvalsh(a.covariance)[0] > 0
    assert np.linalg.eigvalsh(b.covariance)[0] > 0


@pytest.mark.parametrize("bad", [np.diag([1., 1., -1.]), np.diag([1., 1., 0.]), [[1, 1, 0], [0, 1, 0], [0, 0, 1]], np.full((3, 3), np.nan)])
def test_invalid_covariance_is_not_silently_repaired(bad):
    with pytest.raises(ValueError):
        TangentGaussian(SE2, np.eye(3), bad)


@pytest.mark.parametrize("dt", [-1, float("nan"), float("inf")])
def test_invalid_dt_rejected(dt):
    with pytest.raises(ValueError):
        TangentGaussian(SE2, np.eye(3), np.eye(3)).predict([1, 0, 0], dt, np.eye(3))


def test_invalid_rotations_and_tangent_sides_rejected():
    reflected = np.diag([1., -1., 1.])
    with pytest.raises(ValueError):
        SE2.log(reflected)
    with pytest.raises(ValueError):
        boxplus(SE2, np.eye(3), [0, 0, 0], side="guess")
    belief = TangentGaussian(SE2, np.eye(3), np.eye(3))
    with pytest.raises(ValueError):
        belief.update_tangent([0], [[1, 0, 0]], [[1]], side="left")


@pytest.mark.parametrize("up", [[0, 0, 1], [0, 1, 0], [1, 2, 3]])
def test_gravity_frame_roundtrip_and_explicit_convention(up):
    up = np.asarray(up, dtype=float)
    up /= np.linalg.norm(up)
    horizontal = [1, 0, 0] if abs(up[0]) < .9 else [0, 1, 0]
    frame = GravityFrame(-9.81 * up, up, horizontal)
    p = SE2.exp([1, 2, .7])
    lifted = frame.lift(p, .4)
    close(lifted[:3, :3] @ up, up)
    back, height = frame.project(lifted)
    close(back, p)
    assert abs(height - .4) <= 1e-9
    with pytest.raises(ValueError):
        GravityFrame(9.81 * up, up, horizontal)
    with pytest.raises(ValueError):
        GravityFrame(-9.81 * up, up, up)


def test_gravity_frame_rejects_roll_pitch():
    frame = GravityFrame([0, 0, -9.81], [0, 0, 1], [1, 0, 0])
    with pytest.raises(ValueError):
        frame.project(SE3.exp([0, 0, 0, .2, 0, 0]))


@pytest.mark.parametrize("group", [SE2, SE3])
def test_pose_graph_loop_and_gauge(group):
    twists = np.zeros((4, group.dof))
    twists[1, :2], twists[2, :2], twists[3, :2] = [1, 0], [1, 1], [0, 1]
    truth = [group.exp(x) for x in twists]
    info = np.eye(group.dof)
    edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
    factors = [RelativeFactor(i, j, group.compose(group.inverse(truth[i]), truth[j]), info) for i, j in edges]
    initial = [truth[0]] + [boxplus(group, t, np.ones(group.dof) * .03) for t in truth[1:]]
    fit = solve_pose_graph(group, initial, factors, anchor=0)
    assert fit.converged
    assert fit.rank == fit.free_dimensions
    assert fit.residual_norm <= 1e-9
    for a, b in zip(fit.poses, truth):
        close(a, b)
    with pytest.raises(ObservabilityError):
        solve_pose_graph(group, initial, factors)
    with pytest.raises(ObservabilityError):
        solve_pose_graph(group, initial, factors[:1], anchor=0)


def test_partial_factors_do_not_hide_unobserved_rotation():
    factor = RelativeFactor(0, 1, SE2.identity(), np.diag([1., 1., 0.]))
    with pytest.raises(ObservabilityError):
        solve_pose_graph(SE2, [SE2.identity(), SE2.identity()], [factor], anchor=0)


def test_wrong_loop_has_nonzero_residual_not_truth_substitution():
    poses = [SE2.exp([i, 0, 0]) for i in range(3)]
    factors = [RelativeFactor(0, 1, SE2.exp([1, 0, 0]), np.eye(3)),
               RelativeFactor(1, 2, SE2.exp([1, 0, 0]), np.eye(3)),
               RelativeFactor(2, 0, SE2.exp([-1.5, 0, 0]), np.eye(3))]
    fit = solve_pose_graph(SE2, poses, factors, anchor=0, fixed_rotations=True)
    assert fit.residual_norm > .1
    assert np.array_equal(fit.poses[0], poses[0])


def test_linear_bound_contracts():
    a = np.array([[1., 0.], [-1., 1.], [0., -1.]])
    e = np.array([[.1, -.1], [.1, -.1], [0., 0.]])
    estimate_error = np.linalg.lstsq(a, e, rcond=None)[0]
    bound = linear_translation_error_bound(a, np.ones(3), e)
    assert np.linalg.norm(estimate_error) <= bound + 1e-9
    predicted, updated = bounded_translation_update(.1, .01, .02, np.eye(2) * .5)
    assert abs(predicted - .11) < 1e-12
    assert abs(updated - .065) < 1e-12


@pytest.mark.parametrize("group", [SE2, SE3])
def test_known_rotation_reference_does_not_randomize_orientation(group):
    n = group.dim
    mean = group.exp(np.arange(group.dof) / 10)
    conditional = KnownRotationGaussian(group, mean, np.eye(n) * .04)
    position = mean[:n, n].copy()
    rotation = mean[:n, :n].copy()
    bound = 0.
    for _ in range(24):
        velocity = np.arange(n) / 10 + .1
        position += velocity
        bias, obs_bias = np.ones(n) * .003, np.ones(n) * .002
        conditional = conditional.predict(velocity + bias, 1., np.eye(n) * .0004)
        conditional, gain = conditional.update_position(position + obs_bias, np.eye(n) * .0025)
        _, bound = bounded_translation_update(bound, np.linalg.norm(bias), np.linalg.norm(obs_bias), gain)
        assert np.linalg.norm(conditional.mean[:n, n] - position) <= bound + 1e-9
        assert np.array_equal(conditional.mean[:n, :n], rotation)
        assert np.linalg.eigvalsh(conditional.translation_covariance)[0] > 0


def test_gravity_lift_is_group_action_not_full_rotation_invariance():
    frame = GravityFrame([0, -9.81, 0], [0, 1, 0], [1, 0, 0])
    a, b = SE2.exp([.2, -.3, .4]), SE2.exp([1, 2, -.7])
    close(SE3.compose(frame.lift(a, .2), frame.lift(b, .3)), frame.lift(SE2.compose(a, b), .5))


def test_imports_are_cpu_only():
    assert not any(name.split('.')[0] in {'mlx', 'torch', 'onnxruntime', 'tensorflow'} for name in sys.modules)
