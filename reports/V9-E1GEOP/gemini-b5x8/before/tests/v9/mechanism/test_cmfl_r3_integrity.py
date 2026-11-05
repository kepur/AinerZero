"""Author CPU regressions for G9 F1/F2/F3; not independent acceptance."""
from dataclasses import replace
import numpy as np
import pytest
import ainerzero.v9.mechanism as pkg
from test_cmfl_r2_adversarial import _worlds, _prior, _valid_lib, TRUSTED


def fixture():
    rng = np.random.default_rng(4128)
    d, c, t = (_worlds(pkg, rng, name, n) for name, n in (("D", 6), ("C", 20), ("T", 60)))
    # Fixed mechanism supplied to isolate promotion integrity from discovery recall.
    cand = pkg.DiscoveredCandidate(candidate_id="r3", proposer="sindy", active_terms=("quadratic_drag",),
        coefficients=np.array([0.45]), confidence_intervals=((0.45, 0.45),), abstained_terms=(),
        pareto_error=0., pareto_complexity=1, discovery_data_id="D", total_candidates_attempted=1,
        orthogonality_mode="single_step")
    return d, c, t, cand


def evaluate(gate, d, c, t, cand, nulls, tag="T"):
    return gate.evaluate_and_promote(cand, _prior(pkg), discovery_contexts=d, calibration_contexts=c,
        test_contexts=t, discovery_data_id="D", calibration_data_id="C", test_data_id=tag, test_id=tag,
        producer="isolated_sim_verifier_v1", trusted_context=TRUSTED, facttest_null_candidates=nulls)


@pytest.mark.parametrize("attack", ["same_id", "different_id", "one_coeff", "missing", "changed_D"])
def test_frozen_recipe_rejects_content_attacks(attack):
    d, c, t, cand = fixture()
    nulls = pkg.build_facttest_null_controls(cand, d, _prior(pkg), _valid_lib(pkg))
    good = evaluate(pkg.OneSidedPromotionGate(pkg.default_cmfl_registration()), d, c, t, cand, nulls)
    assert good.admitted, good.rejection_reasons
    if attack in ("same_id", "different_id"):
        nulls = [replace(nulls[0], candidate_id=str(i) if attack == "different_id" else "same") for i in range(29)]
    elif attack == "one_coeff":
        nulls[1] = replace(nulls[1], coefficients=nulls[1].coefficients * 1.001)
    elif attack == "missing":
        nulls = nulls[:-1]
    else:
        d = _worlds(pkg, np.random.default_rng(981), "newD", 6)
    bad = evaluate(pkg.OneSidedPromotionGate(pkg.default_cmfl_registration()), d, c, t, cand, nulls)
    assert not bad.admitted and not bad.facttest_passed
    assert bad.facttest_recipe_sha == good.facttest_recipe_sha
    assert bad.facttest_binding_sha != good.facttest_binding_sha


@pytest.mark.parametrize("relabel", [False, True])
def test_historical_world_and_content_replay_rejected(relabel):
    d, c, t, cand = fixture()
    nulls = pkg.build_facttest_null_controls(cand, d, _prior(pkg), _valid_lib(pkg))
    gate = pkg.OneSidedPromotionGate(pkg.default_cmfl_registration())
    first = evaluate(gate, d, c, t, cand, nulls)
    assert first.admitted
    if relabel:
        t = [replace(x, context_id=f"renamed{i}", world_instance_id=f"renamed{i}", t_start=987,
                     object_keys=("renamed",)) for i, x in enumerate(t)]
    with pytest.raises(ValueError, match="N3"):
        evaluate(gate, d, c, t, cand, nulls, "renamedT")
    assert gate.step_t == 1 and len(gate.ledger) == 1
    fresh = _worlds(pkg, np.random.default_rng(919), "freshT", 60)
    second = evaluate(gate, d, c, fresh, cand, nulls, "freshT")
    assert second.step_t == 2
    assert not set(first.test_content_shas) & set(second.test_content_shas)


def test_rejected_test_worlds_also_reserved():
    d, c, t, cand = fixture()
    gate = pkg.OneSidedPromotionGate(pkg.default_cmfl_registration())
    assert not evaluate(gate, d, c, t, cand, []).admitted
    with pytest.raises(ValueError, match="N3"):
        evaluate(gate, d, c, t, cand, [], "renamedT")


def test_within_step_content_relabel_rejected():
    d, c, t, cand = fixture()
    t[0] = replace(d[0], world_instance_id="laundered", context_id="laundered")
    with pytest.raises(ValueError, match="content"):
        evaluate(pkg.OneSidedPromotionGate(pkg.default_cmfl_registration()), d, c, t, cand, [])


def test_default_is_hard_projection_and_gls_not_orthogonal():
    d, _, _, _ = fixture()
    stl = pkg.WeakFormSTLSQ(threshold=0.20)
    implicit = stl.discover(d, pkg.DEFAULT_PHI, rng=np.random.default_rng(700))
    explicit = stl.discover(d, pkg.DEFAULT_PHI, rng=np.random.default_rng(700), nuisance_cov=None)
    assert implicit.active_terms == explicit.active_terms
    np.testing.assert_array_equal(implicit.coefficients, explicit.coefficients)
    ctx = d[0]
    g = pkg.step_sensitivity_jacobian(ctx.states, ctx.actions, ctx.dt, pkg.DEFAULT_PHI,
                                    integrator=ctx.integrator).reshape(-1, 3)
    q, _ = np.linalg.qr(g)
    views = [q[:, 0].reshape(ctx.states.shape)]
    hard = stl._project_views_orthogonal(views, stl._compute_context_orthogonal_bases([ctx], pkg.DEFAULT_PHI, "single_step", None))[0]
    gls = stl._project_views_orthogonal(views, stl._compute_context_orthogonal_bases([ctx], pkg.DEFAULT_PHI, "single_step", _prior(pkg).cov))[0]
    assert np.linalg.norm(q.T @ hard.reshape(-1)) < 1e-10
    assert np.linalg.norm(q.T @ gls.reshape(-1)) > 1e-8


def test_gls_diagnostic_candidate_cannot_promote():
    d, c, t, cand = fixture()
    gls = pkg.WeakFormSTLSQ(threshold=0.20).discover(d, pkg.DEFAULT_PHI,
        rng=np.random.default_rng(4128), nuisance_cov=_prior(pkg).cov)
    assert gls.diagnostic_only
    # Only the diagnostic flag changes relative to a demonstrated positive control.
    nulls = pkg.build_facttest_null_controls(cand, d, _prior(pkg), _valid_lib(pkg))
    assert evaluate(pkg.OneSidedPromotionGate(pkg.default_cmfl_registration()), d, c, t, cand, nulls).admitted
    tagged = replace(cand, diagnostic_only=gls.diagnostic_only)
    decision = evaluate(pkg.OneSidedPromotionGate(pkg.default_cmfl_registration()), d, c, t, tagged, nulls)
    assert not decision.admitted
    assert any("diagnostic only" in r for r in decision.rejection_reasons)
