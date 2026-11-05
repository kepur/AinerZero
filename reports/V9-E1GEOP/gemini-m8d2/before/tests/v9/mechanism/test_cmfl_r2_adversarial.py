"""V9.G7 r2 adversarial tests for the G8 findings (F1-F4) and the in_slow_domain truth leak.

Each guarded property is written as a scenario ``f(pkg) -> bool`` (True = guard holds).  The scenarios
run on the real package and on text mutants of a copy of ``src/ainerzero/v9/mechanism`` made in a
pytest tmp_path (the repository tree is never written).  Every mutant re-introduces one r1 defect and
must flip exactly the scenario that targets it.
"""
from __future__ import annotations

import importlib
from pathlib import Path
import shutil
import sys
from types import ModuleType
from typing import Callable

import numpy as np
import pytest

import ainerzero.v9.mechanism as base_pkg
from ainerzero.v9.mechanism.toy_worlds import FORBIDDEN_OBSERVATION_FIELDS

MECH_DIR = Path(__file__).resolve().parents[3] / "src/ainerzero/v9/mechanism"
PRIOR_COV = np.diag([1.5, 0.25, 0.60])
TRUSTED = {"verified_producer": "isolated_sim_verifier_v1", "isolated_evaluator": True}


def _prior(pkg: ModuleType):
    return pkg.ParamBelief(mean=pkg.DEFAULT_PHI.copy(), cov=PRIOR_COV.copy(), dimensionless_scale=pkg.DEFAULT_SCALE.copy())


def _worlds(
    pkg: ModuleType,
    rng: np.random.Generator,
    prefix: str,
    count: int,
    *,
    mech: str = "quadratic_drag",
    coeff: float = 0.45,
    families: tuple[str | None, ...] | None = None,
    phi_dev: bool = False,
    family_in_ids: bool = False,
):
    reg = pkg.default_cmfl_registration()
    fams = reg.env_families if families is None else families
    out = []
    for i in range(count):
        fam = fams[i % len(fams)]
        tag = f"_{fam}" if family_in_ids and fam else ""
        phi = pkg.DEFAULT_PHI + (rng.normal(0.0, [0.8, 0.15, 0.35]) if phi_dev else 0.0)
        out.append(
            pkg.simulate_window(
                context_id=f"{prefix}_ctx{tag}_{i:03d}",
                world_instance_id=f"{prefix}_world{tag}_{i:03d}",
                t_start=0,
                W=reg.W,
                dt=0.01,
                true_integrator="rk4",
                model_integrator="rk4",
                true_phi=phi,
                true_mechanism=mech,
                true_coeff=coeff,
                noise_std=0.003,
                reported_cov_scale=1.0,
                rng=rng,
                env_family=fam,
            )
        )
    return out


def _valid_lib(pkg: ModuleType):
    kept, _ = pkg.ExecutablePriorChecker().filter_library(pkg.default_basis_library())
    return kept


def _promote(pkg, cand, d, c, t, *, tag: str):
    prior = _prior(pkg)
    gate = pkg.OneSidedPromotionGate(pkg.default_cmfl_registration())
    return gate.evaluate_and_promote(
        cand,
        prior,
        discovery_contexts=d,
        calibration_contexts=c,
        test_contexts=t,
        discovery_data_id=f"D_{tag}",
        calibration_data_id=f"C_{tag}",
        test_data_id=f"T_{tag}",
        test_id=f"test_{tag}",
        producer="isolated_sim_verifier_v1",
        trusted_context=TRUSTED,
        facttest_null_candidates=pkg.build_facttest_null_controls(cand, d, prior, _valid_lib(pkg)),
    )


def _discover_true(pkg, d, rng, tag: str):
    # r3: isolate promotion gates with a declared toy truth mechanism. GLS discovery
    # is diagnostic only, so its recall cannot supply a promotion positive control.
    return pkg.DiscoveredCandidate(
        candidate_id=f"cand_{tag}", proposer="sindy", active_terms=("quadratic_drag",),
        coefficients=np.array([0.45]), confidence_intervals=((0.45, 0.45),), abstained_terms=(),
        pareto_error=0.0, pareto_complexity=1, discovery_data_id=f"D_{tag}",
        total_candidates_attempted=1, orthogonality_mode="single_step",
    )


# ---------------------------------------------------------------------------
# Scenarios (True = guard holds)
# ---------------------------------------------------------------------------

def scenario_f2_elond_is_a_conjunct(pkg: ModuleType) -> bool:
    """A true mechanism with too few world blocks (4 per family) passes the bootstrap but not e-LOND."""
    rng = np.random.default_rng(2028)
    d, c, t = _worlds(pkg, rng, "D", 6), _worlds(pkg, rng, "C", 20), _worlds(pkg, rng, "T", 12)
    cand = _discover_true(pkg, d, rng, "f2")
    dec = _promote(pkg, cand, d, c, t, tag="f2")
    assert dec.superiority_passed and dec.facttest_passed and dec.zero_regression_passed, dec.rejection_reasons
    return (not dec.admitted) and (not dec.e_lond_passed) and any(r.startswith("e-LOND") for r in dec.rejection_reasons)


def scenario_f3_unlabeled_families_rejected(pkg: ModuleType) -> bool:
    """Same data as an admissible run, but env_family missing (family names only inside the ids)."""
    rng = np.random.default_rng(3028)
    d, c = _worlds(pkg, rng, "D", 6), _worlds(pkg, rng, "C", 20)
    reg = pkg.default_cmfl_registration()
    t = _worlds(pkg, rng, "T", 45, families=reg.env_families, family_in_ids=True)
    t = [
        pkg.ObservationContext(**{**{f: getattr(x, f) for f in x.__dataclass_fields__}, "env_family": None})
        for x in t
    ]
    cand = _discover_true(pkg, d, rng, "f3")
    dec = _promote(pkg, cand, d, c, t, tag="f3")
    return (not dec.admitted) and any("env_family" in r for r in dec.rejection_reasons)


def scenario_f4_wrong_mechanism_rejected_by_facttest(pkg: ModuleType) -> bool:
    """G8 F4: coulomb_friction 0.45 standing in for quadratic_drag 0.55.  With 120 test worlds the
    bootstrap, zero-regression, conformal, stability and e-LOND checks all pass; only FactTest rejects."""
    ok = True
    for seed in (15, 16):
        rng = np.random.default_rng(seed)
        d = _worlds(pkg, rng, "FD", 6, coeff=0.55)
        c = _worlds(pkg, rng, "FC", 20, coeff=0.55)
        t = _worlds(pkg, rng, "FT", 120, coeff=0.55)
        wrong = pkg.DiscoveredCandidate(
            candidate_id=f"coulomb_wrong_{seed}",
            proposer="adversary",
            active_terms=("coulomb_friction",),
            coefficients=np.array([0.45]),
            confidence_intervals=((0.45, 0.45),),
            abstained_terms=(),
            pareto_error=0.0,
            pareto_complexity=1,
            discovery_data_id="FD",
            total_candidates_attempted=1,
            orthogonality_mode="single_step",
        )
        dec = _promote(pkg, wrong, d, c, t, tag=f"f4_{seed}")
        others_pass = (
            dec.superiority_passed
            and dec.zero_regression_passed
            and dec.conformal_certificate_valid
            and dec.reproducibility_filter_passed
            and dec.e_lond_passed
        )
        assert others_pass, f"scenario precondition broke (seed {seed}): {dec.rejection_reasons}"
        ok = ok and (not dec.admitted) and (not dec.facttest_passed)
    return ok


def scenario_no_envelope_fails_closed(pkg: ModuleType) -> bool:
    reg = pkg.default_cmfl_registration()
    contexts, metas = pkg.build_benchmark_suite(reg, n_per_route=2, seed=20261028)
    gate = pkg.MechanismSufficiencyGate(reg)
    suff = [c for c, m in zip(contexts, metas) if m.true_route.value == "SUFFICIENT"]
    return all(gate.route(c, _prior(pkg)).route_code.value == "OUT_OF_DOMAIN" for c in suff)


def scenario_projection_is_contraction(pkg: ModuleType) -> bool:
    rng = np.random.default_rng(1028)
    ctxs = _worlds(pkg, rng, "P", 6, mech="none", coeff=0.0, phi_dev=True)
    try:
        for nc in (None, PRIOR_COV):
            pkg.WeakFormSTLSQ(threshold=0.20).discover(ctxs, pkg.DEFAULT_PHI, rng=rng, nuisance_cov=nc)
    except AssertionError:
        return False
    return True


def scenario_facttest_unachievable_is_inf(pkg: ModuleType) -> bool:
    thr, k = pkg.calibrate_facttest_threshold(np.linspace(0.0, 0.5, 28), 0.10, 0.05)
    return thr == float("inf") and k == 29


SCENARIOS: dict[str, Callable[[ModuleType], bool]] = {
    "f2": scenario_f2_elond_is_a_conjunct,
    "f3": scenario_f3_unlabeled_families_rejected,
    "f4": scenario_f4_wrong_mechanism_rejected_by_facttest,
    "envelope": scenario_no_envelope_fails_closed,
    "f1": scenario_projection_is_contraction,
    "facttest_inf": scenario_facttest_unachievable_is_inf,
}

# Each mutant re-introduces one r1 behaviour.  (file, old, new); old must occur exactly once.
MUTANTS: dict[str, list[tuple[str, str, str]]] = {
    "f2": [(
        "promotion_gate.py",
        "e_lond_passed = bool(e_pers >= e_threshold)",
        "e_lond_passed = bool(e_pers >= e_threshold or sup_passed)",
    )],
    "f3": [
        (
            "promotion_gate.py",
            'fam = ctx.env_family if ctx.env_family is not None else ""',
            "fam = next((f for f in self.registration.env_families if f.lower() in wid.lower()), "
            "self.registration.env_families[0])",
        ),
        (
            "promotion_gate.py",
            "        bad_label = sorted(w for w in world_ids if world_fam.get(w) not in declared)\n",
            "        bad_label = []\n",
        ),
    ],
    "f4": [(
        "promotion_gate.py",
        "facttest_passed = bool(math.isfinite(thr) and ft_score > thr)",
        "facttest_passed = True",
    )],
    "envelope": [(
        "sufficiency_gate.py",
        '            return "no frozen D_valid envelope declared for the SLOW mechanism; fail-closed"',
        "            return None",
    )],
    "f1": [(
        "discovery.py",
        "proj = flat.copy() if q_c.size == 0 else flat - q_c @ (q_c.T @ flat)",
        "proj = flat.copy() if q_c.size == 0 else flat - 2.5 * q_c @ (q_c.T @ flat)",
    )],
    "facttest_inf": [(
        "promotion_gate.py",
        '    return float("inf"), n + 1',
        "    return float(scores[-1] + 1e-6), n + 1",
    )],
}


def _build_mutant(tmp_path: Path, key: str) -> ModuleType:
    name = f"g7r2_mutant_{key}"
    dst = tmp_path / name
    shutil.copytree(MECH_DIR, dst, ignore=shutil.ignore_patterns("__pycache__"))
    for fname, old, new in MUTANTS[key]:
        p = dst / fname
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, f"mutant {key}: anchor not unique in {fname}: {old[:60]!r}"
        p.write_text(text.replace(old, new), encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(tmp_path))


@pytest.mark.parametrize("key", sorted(SCENARIOS))
def test_guard_holds_on_real_package(key: str) -> None:
    assert SCENARIOS[key](base_pkg) is True


@pytest.mark.parametrize("key", sorted(MUTANTS))
def test_mutant_reintroducing_r1_defect_is_caught(key: str, tmp_path: Path) -> None:
    before = {p.name: p.read_bytes() for p in MECH_DIR.glob("*.py")}
    mutant = _build_mutant(tmp_path, key)
    try:
        holds = SCENARIOS[key](mutant)
    except AssertionError:
        holds = False  # the mutant broke the guard loudly (e.g. contraction assertion) - also a catch
    finally:
        sys.modules.pop(mutant.__name__, None)
        for sub in [m for m in sys.modules if m.startswith(mutant.__name__ + ".")]:
            sys.modules.pop(sub, None)
    assert holds is False, f"mutant {key} was not caught by its scenario"
    assert {p.name: p.read_bytes() for p in MECH_DIR.glob("*.py")} == before  # repository tree untouched


# ---------------------------------------------------------------------------
# Truth-leak removal (in_slow_domain) and covariate-only OUT_OF_DOMAIN
# ---------------------------------------------------------------------------

def test_in_slow_domain_is_truth_only() -> None:
    assert "in_slow_domain" in FORBIDDEN_OBSERVATION_FIELDS
    assert "in_slow_domain" not in base_pkg.ObservationContext.__dataclass_fields__
    assert "in_slow_domain" in base_pkg.GroundTruthMeta.__dataclass_fields__
    reg = base_pkg.default_cmfl_registration()
    contexts, metas = base_pkg.build_benchmark_suite(reg, n_per_route=1, seed=7)
    ctx = contexts[0]
    with pytest.raises(TypeError):
        base_pkg.ObservationContext(**{f: getattr(ctx, f) for f in ctx.__dataclass_fields__}, in_slow_domain=False)
    assert [m.in_slow_domain for m in metas if m.true_route.value == "OUT_OF_DOMAIN"] == [False]


def _shift_positions(pkg, ctx, dx: float, dy: float):
    off = np.array([dx, dy, 0.0, 0.0])
    fields = {f: getattr(ctx, f) for f in ctx.__dataclass_fields__}
    fields.update(context_id=ctx.context_id + "_shift", states=ctx.states + off, next_states=ctx.next_states + off)
    return pkg.ObservationContext(**fields)


def test_out_of_domain_is_decided_by_covariates_only() -> None:
    reg = base_pkg.default_cmfl_registration()
    contexts, metas = base_pkg.build_benchmark_suite(reg, n_per_route=4, seed=20261028)
    prior = _prior(base_pkg)
    gate = base_pkg.MechanismSufficiencyGate(reg, domain_envelope=base_pkg.toy_slow_d_valid_envelope())
    ood = [c for c, m in zip(contexts, metas) if m.true_route.value == "OUT_OF_DOMAIN"]
    suff = [c for c, m in zip(contexts, metas) if m.true_route.value == "SUFFICIENT"]
    assert all(gate.route(c, prior).route_code.value == "OUT_OF_DOMAIN" for c in ood)
    # Truth says OOD, covariates moved inside the frozen box -> the gate cannot (and must not) know.
    moved_in = [_shift_positions(base_pkg, c, -7.0, 7.0) for c in ood]
    assert all(float(np.max(np.abs(m.states[:, :2]))) < 8.0 for m in moved_in)
    assert all(gate.route(c, prior).route_code.value != "OUT_OF_DOMAIN" for c in moved_in)
    # Truth says SUFFICIENT, covariates moved outside the box (still inside D_permit) -> OOD.
    moved_out = [_shift_positions(base_pkg, c, 9.0, 0.0) for c in suff]
    assert all(float(np.max(np.abs(m.states[:, :2]))) < reg.d_permit.position_limit for m in moved_out)
    assert all(gate.route(c, prior).route_code.value == "OUT_OF_DOMAIN" for c in moved_out)


def test_strip_helper_matches_msg_row_4a() -> None:
    reg = base_pkg.default_cmfl_registration()
    contexts, _ = base_pkg.build_benchmark_suite(reg, n_per_route=4, seed=20261028)
    prior = _prior(base_pkg)
    gate = base_pkg.MechanismSufficiencyGate(reg, domain_envelope=base_pkg.toy_slow_d_valid_envelope())
    early = {"ABSTAIN", "OUT_OF_DOMAIN", "NUMERICAL"}
    checked = 0
    for c in contexts:
        rec = gate.route(c, prior)
        if rec.route_code.value in early:
            continue
        q_low, _ = base_pkg.nis_acceptance_bounds(reg.alpha_s, rec.dof)
        assert base_pkg.is_covariance_inconsistent(c, prior, reg) == (rec.nis_stat < q_low)
        checked += 1
    assert checked >= 16
    clean, removed = base_pkg.strip_covariance_inconsistent_windows(contexts, prior, reg)
    assert removed == sum(base_pkg.is_covariance_inconsistent(c, prior, reg) for c in contexts)
    assert len(clean) + removed == len(contexts)


# ---------------------------------------------------------------------------
# F1: per-context projection, energy, purity and recovery
# ---------------------------------------------------------------------------

def _pooled_r1_ratios(stl, ctxs, phi):
    """Re-implementation of the r1 pooled projection, only to show what r2 replaced."""
    p = len(phi)
    g = np.vstack([
        base_pkg.step_sensitivity_jacobian(c.states, c.actions, c.dt, phi, integrator=c.integrator).reshape(-1, p)
        for c in ctxs
    ])
    u, s, _ = np.linalg.svd(g, full_matrices=False)
    q = u[:, : int(np.sum(s > 1e-12 * s[0]))]
    raws = [base_pkg.compute_innovations_and_nis(c, phi)[0] for c in ctxs]
    stacked = np.concatenate([r.reshape(-1) for r in raws])
    proj = stacked - q @ (q.T @ stacked)
    chunks = np.split(proj, np.cumsum([r.size for r in raws])[:-1])
    return [float(ch @ ch / np.sum(r ** 2)) for ch, r in zip(chunks, raws)]


def test_per_context_projection_never_increases_block_energy() -> None:
    rng = np.random.default_rng(401)
    ctxs = _worlds(base_pkg, rng, "P", 6, mech="none", coeff=0.0, phi_dev=True) + _worlds(base_pkg, rng, "S", 6)
    stl = base_pkg.WeakFormSTLSQ(threshold=0.20)
    raws = [base_pkg.compute_innovations_and_nis(c, base_pkg.DEFAULT_PHI)[0] for c in ctxs]
    for nc in (None, PRIOR_COV):
        bases = stl._compute_context_orthogonal_bases(ctxs, base_pkg.DEFAULT_PHI, "single_step", nc)
        proj = stl._project_views_orthogonal(raws, bases)
        ratios = [float(np.sum(p ** 2) / np.sum(r ** 2)) for p, r in zip(proj, raws)]
        assert max(ratios) <= 1.0 + 1e-12
    # Characterisation of the r1 defect on the same data: pooled projection inflates some blocks.
    assert max(_pooled_r1_ratios(stl, ctxs, base_pkg.DEFAULT_PHI)) > 1.0
    with pytest.raises(ValueError, match="must align"):
        stl._project_views_orthogonal(raws, bases[:-1])


def test_gls_projection_purity_and_recovery_across_seeds() -> None:
    stl = base_pkg.WeakFormSTLSQ(threshold=0.20)
    false_disc = drag_exact = inv_r_exact = 0
    for k in range(10):
        rng = np.random.default_rng(3000 + k)
        cand = stl.discover(_worlds(base_pkg, rng, "P", 6, mech="none", coeff=0.0, phi_dev=True),
                            base_pkg.DEFAULT_PHI, rng=rng, nuisance_cov=PRIOR_COV)
        false_disc += int(len(cand.active_terms) > 0)
        rng = np.random.default_rng(4000 + k)
        cand = stl.discover(_worlds(base_pkg, rng, "S", 6), base_pkg.DEFAULT_PHI, rng=rng, nuisance_cov=PRIOR_COV)
        drag_exact += int(cand.active_terms == ("quadratic_drag",))
        rng = np.random.default_rng(5000 + k)
        cand = stl.discover(_worlds(base_pkg, rng, "A", 6, mech="altered_inv_r_gravity", coeff=6.5),
                            base_pkg.DEFAULT_PHI, rng=rng, nuisance_cov=PRIOR_COV)
        inv_r_exact += int(cand.active_terms == ("altered_inv_r_gravity",))
    assert false_disc <= 1, false_disc
    assert drag_exact >= 9 and inv_r_exact >= 9, (drag_exact, inv_r_exact)


def _g8_like_drag_windows(rng: np.random.Generator, n: int):
    """G8's independent setting (W=16, dt=0.015, sigma=2.5e-3, fixed s0), built with our generator."""
    return [
        base_pkg.simulate_window(
            context_id=f"g8like_{i}", world_instance_id=f"g8like_w_{i}", t_start=0, W=16, dt=0.015,
            true_integrator="rk4", model_integrator="rk4", true_phi=base_pkg.DEFAULT_PHI,
            true_mechanism="quadratic_drag", true_coeff=0.55, noise_std=2.5e-3, reported_cov_scale=1.0, rng=rng,
            init_state=np.array([1.9, -1.7, 3.6, -3.1]), actions=rng.uniform(-3.0, 3.0, size=(16, 2)),
        )
        for i in range(n)
    ]


def test_hard_projection_absorbs_collinear_drag_known_limitation() -> None:
    """Known limitation (documented in r2 report): in G8's setting quadratic drag is nearly collinear
    with the c_lin sensitivity of its own window.  The hard L2 limit keeps <2% of its energy and then
    misattributes the remainder to position terms; the prior-regularised (GLS) operator recovers it."""
    stl = base_pkg.WeakFormSTLSQ(threshold=0.20)
    keep_hard: list[float] = []
    exact = {"hard": 0, "gls": 0}
    for k in range(10):
        rng = np.random.default_rng(600 + k)
        ctxs = _g8_like_drag_windows(rng, 6)
        raws = [base_pkg.compute_innovations_and_nis(c, base_pkg.DEFAULT_PHI)[0] for c in ctxs]
        bases = stl._compute_context_orthogonal_bases(ctxs, base_pkg.DEFAULT_PHI, "single_step", None)
        proj = stl._project_views_orthogonal(raws, bases)
        keep_hard.append(float(np.mean([np.sum(p ** 2) / np.sum(r ** 2) for p, r in zip(proj, raws)])))
        for tag, nc in (("hard", None), ("gls", PRIOR_COV)):
            cand = stl.discover(ctxs, base_pkg.DEFAULT_PHI, rng=np.random.default_rng(700 + k), nuisance_cov=nc)
            exact[tag] += int(cand.active_terms == ("quadratic_drag",))
    assert float(np.mean(keep_hard)) < 0.02, keep_hard
    assert exact["gls"] >= 9 and exact["hard"] < exact["gls"], exact


def test_nuisance_cov_validation() -> None:
    rng = np.random.default_rng(1)
    ctxs = _worlds(base_pkg, rng, "V", 2)
    stl = base_pkg.WeakFormSTLSQ(threshold=0.20)
    with pytest.raises(ValueError, match="nuisance_cov must be"):
        stl.discover(ctxs, base_pkg.DEFAULT_PHI, rng=rng, nuisance_cov=np.eye(2))
    with pytest.raises(ValueError, match="positive semi-definite"):
        stl.discover(ctxs, base_pkg.DEFAULT_PHI, rng=rng, nuisance_cov=-np.eye(3))


# ---------------------------------------------------------------------------
# F3 / F4 direct checks
# ---------------------------------------------------------------------------

def test_family_labels_undeclared_or_empty_family_rejected_and_e_values_differ() -> None:
    rng = np.random.default_rng(3128)
    d, c = _worlds(base_pkg, rng, "D", 6), _worlds(base_pkg, rng, "C", 20)
    cand = _discover_true(base_pkg, d, rng, "lab")
    reg = base_pkg.default_cmfl_registration()

    t_ok = _worlds(base_pkg, rng, "Tok", 45)
    dec_ok = _promote(base_pkg, cand, d, c, t_ok, tag="lab_ok")
    assert dec_ok.admitted, dec_ok.rejection_reasons
    assert len(set(round(v, 9) for v in dec_ok.e_by_family.values())) == 3

    t_bad = _worlds(base_pkg, rng, "Tbad", 45, families=("P_family", "S_family", "Q_family"))
    dec_bad = _promote(base_pkg, cand, d, c, t_bad, tag="lab_bad")
    assert not dec_bad.admitted and any("undeclared" in r for r in dec_bad.rejection_reasons)
    assert any("altered_law_family" in r and "no test world" in r for r in dec_bad.rejection_reasons)

    t_two = _worlds(base_pkg, rng, "Ttwo", 45, families=reg.env_families[:2])
    dec_two = _promote(base_pkg, cand, d, c, t_two, tag="lab_two")
    assert not dec_two.admitted and dec_two.e_by_family["altered_law_family"] == 1.0


def test_facttest_needs_enough_nulls_and_records_threshold() -> None:
    rng = np.random.default_rng(4128)
    d, c, t = _worlds(base_pkg, rng, "D", 6), _worlds(base_pkg, rng, "C", 20), _worlds(base_pkg, rng, "T", 45)
    cand = _discover_true(base_pkg, d, rng, "ft")
    prior = _prior(base_pkg)
    reg = base_pkg.default_cmfl_registration()
    assert base_pkg.facttest_required_null_count(reg.tau_cal, reg.delta_cal) == 29
    nulls = base_pkg.build_facttest_null_controls(cand, d, prior, _valid_lib(base_pkg))
    assert len(nulls) >= 29
    for n_null, expect in ((0, False), (28, False), (len(nulls), True)):
        gate = base_pkg.OneSidedPromotionGate(reg)
        dec = gate.evaluate_and_promote(
            cand, prior, discovery_contexts=d, calibration_contexts=c, test_contexts=t,
            discovery_data_id="D_ft", calibration_data_id="C_ft", test_data_id=f"T_ft_{n_null}", test_id="ft",
            producer="isolated_sim_verifier_v1", trusted_context=TRUSTED,
            facttest_null_candidates=nulls[:n_null],
        )
        assert dec.facttest_passed is expect and dec.admitted is expect, (n_null, dec.rejection_reasons)
        assert dec.facttest_n_null == n_null
        if expect:
            assert dec.facttest_threshold is not None and dec.facttest_score > dec.facttest_threshold
        else:
            assert dec.facttest_threshold is None
