"""Contract: GeometryCore (r5 §3, §4 conventions; G1 owns the real math).

Positive: group algebra, tagged actions, analytic canonicalisation, predict /
update / with_side against the registered conventions, explicit gravity.

Counter-examples: singular (zero) measurement noise, untagged inputs, a
left-hand belief handed to anything except ``with_side``, invalid dt, bad
belief construction.

Cross-checks: where ``ainzerzero.v9.geometry`` (G1, accepted) is importable,
the double's exp/log/compose/adjoint/predict/update/with_side must agree with
it numerically.  G1 is read-only here.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.fakes import FakeGeometryCore
from ainerzero.v9.interfaces.errors import (
    ContractViolation,
    SingularMeasurementNoise,
    UnsupportedInput,
)
from ainerzero.v9.interfaces.types import (
    PoseBelief,
    as_map_coordinates,
    as_points,
    as_vectors,
)

RNG = np.random.default_rng(20261020)


def make_belief(mean=None, covariance=None) -> PoseBelief:
    theta = 0.4
    mean = mean if mean is not None else (
        (float(np.cos(theta)), -float(np.sin(theta)), 1.3),
        (float(np.sin(theta)), float(np.cos(theta)), -0.6),
        (0.0, 0.0, 1.0),
    )
    covariance = covariance if covariance is not None else (
        (0.02, 0.003, 0.0),
        (0.003, 0.03, 0.0),
        (0.0, 0.0, 0.01),
    )
    return PoseBelief(
        group="SE2",
        mean=mean,
        covariance=covariance,
        gravity=(0.0, 0.0, -1.0),
        unobservable_dof=("global_translation", "global_yaw"),
    )


@pytest.fixture
def core() -> FakeGeometryCore:
    return FakeGeometryCore(process_covariance_rate=((1e-4, 0.0, 0.0), (0.0, 1e-4, 0.0), (0.0, 0.0, 1e-5)))


# ---- group algebra --------------------------------------------------------- #


@pytest.mark.parametrize("seed", range(8))
def test_exp_log_round_trip(core, seed):
    rng = np.random.default_rng(seed)
    xi = rng.normal(size=3)
    np.testing.assert_allclose(core.log(core.exp(xi)), xi, atol=1e-9)
    transform = core.exp(xi)
    np.testing.assert_allclose(core.exp(core.log(transform)), transform, atol=1e-12)


def test_compose_inverse_is_identity(core):
    transform = core.exp((0.7, -0.2, 0.9))
    np.testing.assert_allclose(
        core.compose(transform, core.inverse(transform)), np.eye(3), atol=1e-12
    )
    np.testing.assert_allclose(
        core.compose(core.inverse(transform), transform), np.eye(3), atol=1e-12
    )


def test_adjoint_satisfies_its_defining_relation(core):
    transform = core.exp((1.1, 0.4, -1.3))
    eta = RNG.normal(size=3)
    conjugated = core.compose(core.compose(transform, core.exp(eta)), core.inverse(transform))
    np.testing.assert_allclose(conjugated, core.exp(core.adjoint(transform) @ eta), atol=1e-9)
    # Ad(x^-1) == inv(Ad(x))
    np.testing.assert_allclose(
        core.adjoint(core.inverse(transform)), np.linalg.inv(core.adjoint(transform)), atol=1e-10
    )


def test_act_round_trips_and_keeps_tags(core):
    transform = core.exp((0.3, -0.5, 0.8))
    inverse = core.inverse(transform)
    points2 = as_points([[1.0, 2.0], [-3.0, 0.5]])
    points3 = as_points([[1.0, 2.0, 3.0], [-3.0, 0.5, -1.0]])
    vectors = as_vectors([[1.0, 0.0], [0.0, 1.0]])
    maps = as_map_coordinates([[1.0, 2.0]], 0.05)
    for tagged in (points2, points3, vectors, maps):
        once = core.act(transform, tagged)
        twice = core.act(inverse, once)
        np.testing.assert_allclose(np.asarray(twice), np.asarray(tagged), atol=1e-12)
        assert type(twice) is type(tagged)
    # gravity-aligned lift keeps the vertical component
    np.testing.assert_allclose(np.asarray(core.act(transform, points3))[:, 2], [3.0, -1.0])
    # map resolution metadata survives the action
    assert core.act(transform, maps).resolution_m == 0.05
    # vectors rotate, they do not translate
    rotated = core.act(transform, vectors)
    np.testing.assert_allclose(np.linalg.norm(np.asarray(rotated), axis=1), [1.0, 1.0], atol=1e-12)


def test_act_rejects_untagged_input(core):
    transform = core.exp((0.1, 0.2, 0.3))
    with pytest.raises(UnsupportedInput) as caught:
        core.act(transform, np.array([[1.0, 2.0]]))  # raw array: no tag, no contract
    assert caught.value.code == "unsupported_input"
    with pytest.raises(UnsupportedInput):
        core.act(transform, [[1.0, 2.0]])


# ---- canonicalisation (式 9) ----------------------------------------------- #


def test_canonicalisation_round_trips(core, belief):
    points = as_points([[2.0, 1.0], [0.0, -1.0], [5.0, 5.0]])
    vectors = as_vectors([[1.0, 0.0]])
    maps = as_map_coordinates([[2.0, 1.0]], 0.25)
    for tagged in (points, vectors, maps):
        local = core.canonicalize(tagged, belief)
        back = core.decanonicalize(local, belief)
        np.testing.assert_allclose(np.asarray(back), np.asarray(tagged), atol=1e-12)
    assert core.decanonicalize(core.canonicalize(maps, belief), belief).resolution_m == 0.25


def test_canonicalize_actually_changes_coordinates(core, belief):
    """Counter-example control: an identity canonicalisation must not pass."""
    points = as_points([[2.0, 1.0]])
    local = core.canonicalize(points, belief)
    assert not np.allclose(np.asarray(local), np.asarray(points), atol=1e-6)
    # world_point(local) == world_point via decanonicalize == original
    np.testing.assert_allclose(np.asarray(core.decanonicalize(local, belief)), [[2.0, 1.0]], atol=1e-12)


def test_canonicalize_rejects_untagged_and_left_hand_inputs(core, belief):
    with pytest.raises(UnsupportedInput):
        core.canonicalize(np.array([1.0, 2.0]), belief)
    left = core.with_side(belief, "left")
    with pytest.raises(UnsupportedInput) as caught:
        core.canonicalize(as_points([[1.0, 2.0]]), left)
    assert caught.value.code == "unsupported_input"
    with pytest.raises(UnsupportedInput):
        core.decanonicalize(np.array([1.0, 2.0]), belief)


# ---- predict / update ------------------------------------------------------ #


def test_predict_zero_dt_is_the_identity(core, belief):
    same = core.predict(belief, (0.4, -0.1, 0.2), 0.0)
    np.testing.assert_allclose(same.mean, belief.mean, atol=1e-15)
    np.testing.assert_allclose(same.covariance, belief.covariance, atol=1e-15)
    assert same.side == "right"
    assert np.array_equal(same.unobservable_dof, belief.unobservable_dof)


def test_predict_applies_body_motion_and_right_error(core, belief):
    velocity = (0.5, -0.2, 0.3)
    dt = 10 / 120
    result = core.predict(belief, velocity, dt)
    u = core.exp(np.array(velocity) * dt)
    np.testing.assert_allclose(result.mean, core.compose(belief.mean, u), atol=1e-12)
    f = core.adjoint(core.inverse(u))
    expected_p = f @ belief.covariance @ f.T + np.diag([1e-4, 1e-4, 1e-5]) * dt
    np.testing.assert_allclose(result.covariance, expected_p, atol=1e-14)
    # process noise only grows uncertainty
    assert float(np.linalg.eigvalsh(result.covariance)[0]) >= float(
        np.linalg.eigvalsh(f @ belief.covariance @ f.T)[0]
    )


@pytest.mark.parametrize("bad_dt", [-1.0, float("nan"), float("inf"), "0.1", True])
def test_predict_rejects_invalid_dt(core, belief, bad_dt):
    with pytest.raises(UnsupportedInput):
        core.predict(belief, (0.0, 0.0, 0.0), bad_dt)


def test_predict_rejects_a_left_hand_belief(core, belief):
    left = core.with_side(belief, "left")
    with pytest.raises(UnsupportedInput) as caught:
        core.predict(left, (0.1, 0.0, 0.0), 0.1)
    assert "side" in caught.value.detail


def test_update_fuses_and_shrinks_uncertainty(core, belief):
    model = {"H": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), "R": ((0.01, 0.0), (0.0, 0.02))}
    before = float(np.linalg.det(belief.covariance))
    after = core.update(belief, (0.05, -0.03), model)
    assert float(np.linalg.det(after.covariance)) < before
    assert after.side == "right"
    # the mean moves in the direction of the innovation
    delta = core.log(core.compose(core.inverse(belief.mean), after.mean))
    assert delta[0] > 0 and delta[1] < 0


def test_update_refuses_singular_measurement_noise(core, belief):
    """Rejection contract C1 (r5 §4.7): zero-noise measurements must not be fused."""
    model = {"H": ((1.0, 0.0, 0.0),), "R": ((0.0,),)}
    with pytest.raises(SingularMeasurementNoise) as caught:
        core.update(belief, (0.1,), model)
    assert caught.value.code == "singular_measurement_noise"
    with pytest.raises(SingularMeasurementNoise):  # singular, not just exactly zero
        core.update(
            belief,
            (0.1, -0.2),
            {"H": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), "R": ((1.0, 1.0), (1.0, 1.0))},
        )


def test_update_requires_explicit_H_and_R(core, belief):
    with pytest.raises(ContractViolation):
        core.update(belief, (0.1,), {"H": ((1.0, 0.0, 0.0),)})
    with pytest.raises(ContractViolation):
        core.update(belief, (0.1,), "not-a-mapping")
    with pytest.raises(UnsupportedInput):
        core.update(belief, (0.1,), {"H": ((1.0, 0.0),), "R": ((0.01,),)})


def test_update_rejects_a_left_hand_belief(core, belief):
    left = core.with_side(belief, "left")
    model = {"H": ((1.0, 0.0, 0.0),), "R": ((0.01,),)}
    with pytest.raises(UnsupportedInput):
        core.update(left, (0.1,), model)


# ---- side conversion (§4.5) ------------------------------------------------ #


def test_with_side_obeys_the_covariance_relation(core, belief):
    left = core.with_side(belief, "left")
    assert left.side == "left"
    adjoint = core.adjoint(belief.mean)
    expected = adjoint @ belief.covariance @ adjoint.T
    np.testing.assert_allclose(left.covariance, expected, atol=1e-14)
    np.testing.assert_allclose(left.mean, belief.mean, atol=1e-15)  # mean untouched
    back = core.with_side(left, "right")
    np.testing.assert_allclose(back.covariance, belief.covariance, atol=1e-12)
    assert core.with_side(belief, "right") is belief  # no-op path


def test_with_side_rejects_unknown_sides(core, belief):
    with pytest.raises(UnsupportedInput):
        core.with_side(belief, "diagonal")


def test_require_belief_enforces_the_side_contract(belief):
    left = FakeGeometryCore().with_side(belief, "left")
    with pytest.raises(UnsupportedInput):
        FakeGeometryCore.require_belief(left, side="right")
    FakeGeometryCore.require_belief(belief, group="SE2", side="right")
    with pytest.raises(UnsupportedInput):
        FakeGeometryCore.require_belief(belief, group="SE3")


# ---- probes and construction guards --------------------------------------- #


def test_gravity_is_explicit(core, belief):
    gravity = core.gravity
    assert gravity.shape == (3,)
    assert np.isfinite(gravity).all() and float(np.linalg.norm(gravity)) > 0
    assert belief.gravity.shape == (3,) and float(np.linalg.norm(belief.gravity)) > 0
    with pytest.raises(ValueError):  # counter-example: no silent default gravity
        PoseBelief(
            group="SE2",
            mean=np.eye(3),
            covariance=np.eye(3) * 0.01,
            gravity=(0.0, 0.0, 0.0),
            unobservable_dof=(),
        )


def test_supported_groups_are_declared(core):
    assert core.supported() == ("SE2",)
    assert core.supported_groups == ("SE2",)


def test_belief_construction_guards():
    with pytest.raises(ValueError):  # non positive-definite covariance
        PoseBelief(
            group="SE2",
            mean=np.eye(3),
            covariance=((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            gravity=(0.0, 0.0, -1.0),
            unobservable_dof=(),
        )
    with pytest.raises(ValueError):  # undeclared gauge freedom
        PoseBelief(
            group="SE2",
            mean=np.eye(3),
            covariance=np.eye(3) * 0.01,
            gravity=(0.0, 0.0, -1.0),
            unobservable_dof=("some_random_dof",),
        )
    with pytest.raises(ValueError):  # side must be right or left
        PoseBelief(
            group="SE2",
            mean=np.eye(3),
            covariance=np.eye(3) * 0.01,
            gravity=(0.0, 0.0, -1.0),
            unobservable_dof=(),
            side="diagonal",
        )


# ---- cross-check against the accepted G1 implementation (read-only) -------- #


@pytest.fixture(scope="module")
def g1():
    try:
        from ainerzero.v9.geometry.belief import TangentGaussian
        from ainerzero.v9.geometry.lie import SE2
    except Exception as exc:  # pragma: no cover - G1 lives in the same repo
        pytest.skip(f"ainzerzero.v9.geometry (G1) not importable: {exc}")
    return SE2, TangentGaussian


def test_matches_g1_group_operations(core, g1):
    se2, _ = g1
    for seed in range(6):
        rng = np.random.default_rng(seed)
        xi = rng.normal(size=3)
        mine, theirs = core.exp(xi), se2.exp(xi)
        np.testing.assert_allclose(mine, theirs, atol=1e-12)
        np.testing.assert_allclose(core.log(theirs), se2.log(theirs), atol=1e-9)
        np.testing.assert_allclose(core.compose(mine, theirs), se2.compose(mine, theirs), atol=1e-12)
        np.testing.assert_allclose(core.adjoint(mine), se2.adjoint(mine), atol=1e-12)
        np.testing.assert_allclose(core.inverse(mine), se2.inverse(mine), atol=1e-12)


def test_matches_g1_predict(core, belief, g1):
    se2, tangent = g1
    q_rate = np.diag([1e-4, 1e-4, 1e-5])
    velocity = np.array([0.4, -0.3, 0.25])
    dt = 7 / 120
    mine = core.predict(belief, velocity, dt)
    reference = tangent(se2, belief.mean, belief.covariance, "right").predict(
        velocity, dt, q_rate
    )
    np.testing.assert_allclose(mine.mean, reference.mean, atol=1e-12)
    np.testing.assert_allclose(mine.covariance, reference.covariance, atol=1e-12)


def test_matches_g1_update_and_side_conversion(core, belief, g1):
    se2, tangent = g1
    gaussian = tangent(se2, belief.mean, belief.covariance, "right")
    h = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    r = np.diag([0.01, 0.02])
    innovation = np.array([0.07, -0.04])
    mine = core.update(belief, innovation, {"H": h, "R": r})
    theirs, _ = gaussian.update_tangent(innovation, h, r, side="right")
    np.testing.assert_allclose(mine.mean, theirs.mean, atol=1e-10)
    np.testing.assert_allclose(mine.covariance, theirs.covariance, atol=1e-10)
    left = core.with_side(belief, "left")
    np.testing.assert_allclose(left.covariance, gaussian.with_side("left").covariance, atol=1e-12)
