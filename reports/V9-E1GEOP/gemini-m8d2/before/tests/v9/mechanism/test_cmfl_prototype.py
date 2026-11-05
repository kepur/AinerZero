"""Comprehensive unit and adversarial tests for the CMFL pure-NumPy prototype (V9.G7).

Verifies ADR-0014 r3 requirements:
- Pure NumPy & stdlib only (no MLX, SciPy, or torch imports).
- 8-route MSG waterfall (including 4a COVARIANCE_INCONSISTENT lower tail).
- M8 D_permit provenance guard and D_permit removal sensitivity ablation.
- §8.6 'same observation, different future' invariance & information boundary.
- M5 + N1 deterministic greedy independent-context counting algorithm.
- C7 + R1 standalone ParamBelief & ParamBeliefStore (never mixed into UpdateScheduler belief Mapping),
  plus NEES calibration on P_family.
- D4 + S2 Gaussian & nested-MC EIG_phi and MechBench-order probe selection.
- D2-7 + S1/S5 single-step and k-step sensitivity orthogonal projection.
- D2-1/D2-8 ExecutablePriorChecker, data thinning, and WeakFormSTLSQ recovery on S_family and altered_law_family.
- D3 One-Sided Promotion Gate: world-level block bootstrap (M2), C_clean 4a exclusion (N4),
  FPCA basis separation (S3), ALDER missing-basis negative control (0% false admission),
  N3 re-test accounting rule, C2 producer independence guard, and M2 dev-only vs all-env e-LOND.
"""
from __future__ import annotations

import ast
from pathlib import Path
import tempfile

import numpy as np
import pytest

from ainerzero.v9.mechanism import (
    CMFLRegistration,
    DEFAULT_PHI,
    DEFAULT_SCALE,
    DPermitSpec,
    DiscoveredCandidate,
    ExecutablePriorChecker,
    MechanismSufficiencyGate,
    ObservationContext,
    OneSidedPromotionGate,
    ParamBelief,
    ParamBeliefStore,
    RouteCode,
    WeakFormSTLSQ,
    DomainEnvelope,
    are_contexts_independent,
    build_benchmark_suite,
    build_facttest_null_controls,
    calibrate_conformal_domain,
    calibrate_facttest_threshold,
    chi2_cdf,
    chi2_ppf,
    data_thin_gaussian_residuals,
    default_basis_library,
    default_cmfl_registration,
    dimensionless_fisher_information,
    evaluate_msg_confusion_matrix,
    gaussian_eig_phi,
    greedy_independent_context_set,
    identify_parameters_bayesian,
    nested_mc_eig_phi,
    project_residual_orthogonal_to_sensitivity,
    require_independent_slow_producer,
    screen_and_select_probe,
    simulate_elond_dev_only_vs_all_env,
    simulate_window,
    toy_slow_d_valid_envelope,
    verify_same_observation_different_future,
)


def _default_prior_belief() -> ParamBelief:
    return ParamBelief(
        mean=DEFAULT_PHI.copy(),
        cov=np.diag([1.5, 0.25, 0.60]),
        dimensionless_scale=DEFAULT_SCALE.copy(),
    )


def test_pure_numpy_no_forbidden_imports() -> None:
    """Ensure src/ainerzero/v9/mechanism/ imports only numpy and Python stdlib."""
    mech_dir = Path(__file__).resolve().parents[3] / "src/ainerzero/v9/mechanism"
    forbidden = {"mlx", "torch", "scipy", "sklearn", "jax", "tensorflow"}
    py_files = sorted(mech_dir.glob("*.py"))
    assert len(py_files) >= 6
    for pf in py_files:
        tree = ast.parse(pf.read_text(encoding="utf-8"), filename=str(pf))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden, f"{pf.name} imports forbidden package {top!r}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                assert top not in forbidden, f"{pf.name} imports from forbidden package {top!r}"


def test_chi2_cdf_and_ppf_accuracy() -> None:
    """Verify pure-Python chi-square CDF and PPF inversion accuracy across degrees of freedom."""
    # Known exact/reference values:
    # dof=2: CDF(x) = 1 - exp(-x/2) -> PPF(p) = -2 ln(1 - p)
    for p in (0.025, 0.05, 0.50, 0.95, 0.975):
        exact_q = -2.0 * np.log(1.0 - p)
        q = chi2_ppf(p, 2)
        assert abs(q - exact_q) < 1e-11
        assert abs(chi2_cdf(q, 2) - p) < 1e-12

    # dof=80 (W=20, d=4): verify round-trip chi2_cdf(chi2_ppf(p, 80), 80) == p
    for p in (0.025, 0.975):
        q80 = chi2_ppf(p, 80)
        assert abs(chi2_cdf(q80, 80) - p) < 1e-12


def test_registration_freeze_and_d_permit_provenance_guard() -> None:
    """Verify CMFLRegistration 12 items, deterministic SHA256, and M8 D_permit guards."""
    reg = default_cmfl_registration()
    sha1 = reg.registration_sha()
    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "cmfl_registration.json"
        sha2 = reg.save_json(out_path)
        assert sha1 == sha2
        assert out_path.exists()

    # M8 guard: D_permit must reject negative world knowledge ('no_unknown_mechanism_region')
    with pytest.raises(ValueError, match="negative world knowledge"):
        DPermitSpec(
            version="v-bad",
            allowed_variables=("x", "y"),
            position_limit=10.0,
            speed_limit=10.0,
            action_limit=10.0,
            provenance_issuer="teacher",
            provenance_basis="hardware_spec",
            provenance_data_sha="0" * 64,
            extra_metadata={"no_unknown_mechanism_region": [[-1, 1], [-1, 1]]},
        )

    # M8 guard: D_permit provenance must not touch test set T or eval_world
    with pytest.raises(ValueError, match="must not touch test set"):
        DPermitSpec(
            version="v-bad2",
            allowed_variables=("x", "y"),
            position_limit=10.0,
            speed_limit=10.0,
            action_limit=10.0,
            provenance_issuer="teacher",
            provenance_basis="calibrated_on_test_set_T",
            provenance_data_sha="0" * 64,
        )


def test_msg_eight_routes_confusion_matrix_and_d_permit_sensitivity() -> None:
    """Verify all 8 MSG routes achieve 100% recall on the benchmark suite, plus M8 D_permit sensitivity."""
    reg = default_cmfl_registration()
    contexts, metas = build_benchmark_suite(reg, n_per_route=8, seed=20261028)
    prior = _default_prior_belief()

    # r2: OUT_OF_DOMAIN comes only from the frozen D_valid covariate envelope (no per-window label).
    gate = MechanismSufficiencyGate(reg, domain_envelope=toy_slow_d_valid_envelope())
    records = [gate.route(ctx, prior, scope_id=ctx.context_id) for ctx in contexts]
    cm = evaluate_msg_confusion_matrix(records, metas)

    assert cm["total"] == 64
    assert cm["accuracy"] == 1.0, f"Expected 100% 8-route accuracy, got {cm['accuracy']}: {cm['per_class_recall']}"
    for route_name, recall in cm["per_class_recall"].items():
        assert recall == 1.0, f"Route {route_name} recall={recall} < 1.0"
    assert gate.mid_discovery_triggered is True

    abstain_ids = {m.context_id for m in metas if m.true_route.value == "ABSTAIN"}

    # Fail-closed: without a frozen D_valid envelope nothing past D_permit is certified in-domain.
    gate_no_env = MechanismSufficiencyGate(reg)
    recs_no_env = [gate_no_env.route(ctx, prior, scope_id=ctx.context_id) for ctx in contexts]
    assert all(
        r.route_code.value == ("ABSTAIN" if r.context_id in abstain_ids else "OUT_OF_DOMAIN") for r in recs_no_env
    )

    # M8 Sensitivity Ablation: disable D_permit (ABSTAIN never fires).  D_valid is a subset of D_permit,
    # so the 8 action-limit violators are now caught one row later as OUT_OF_DOMAIN, not as ABSTAIN.
    gate_no_dp_env = MechanismSufficiencyGate(reg, domain_envelope=toy_slow_d_valid_envelope(), disable_d_permit=True)
    recs_no_dp_env = [gate_no_dp_env.route(ctx, prior, scope_id=ctx.context_id) for ctx in contexts]
    assert all(r.route_code.value == "OUT_OF_DOMAIN" for r in recs_no_dp_env if r.context_id in abstain_ids)

    # Double ablation: no D_permit and a permissive envelope (|u| <= 20): the violators reach the statistical rows.
    permissive = DomainEnvelope.symmetric_box(position_limit=15.0, speed_limit=20.0, action_limit=20.0)
    gate_no_dpermit = MechanismSufficiencyGate(reg, domain_envelope=permissive, disable_d_permit=True)
    records_no_dp = [gate_no_dpermit.route(ctx, prior, scope_id=ctx.context_id) for ctx in contexts]
    cm_no_dp = evaluate_msg_confusion_matrix(records_no_dp, metas)
    assert cm_no_dp["predicted_counts"]["ABSTAIN"] == 0
    # 去掉 D_permit 后，8 个本应 ABSTAIN 的上下文（物理有效，只是动作超界）落到**剩下的统计判定**上：
    # 绝大多数是 SUFFICIENT；NIS 是 χ²(80) 的一次随机实现，落进下尾（2.5%）的会被 4a 判为 COVARIANCE_INCONSISTENT。
    # 这是有限样本下的统计判定而不是缺陷，所以只断言「全部离开 ABSTAIN、只落在这两条路由、且 SUFFICIENT 至少多了 6 个」，
    # 不把 seed 恰好抽到的 6/2 当作常数写死。关键结论是 D_permit 不是冗余的：关掉它，越界动作的上下文会被当作可信数据放行。
    moved = [r for r in records_no_dp if r.context_id in abstain_ids]
    assert len(moved) == 8 and all(r.route_code.value in {"SUFFICIENT", "COVARIANCE_INCONSISTENT"} for r in moved)
    assert sum(r.route_code.value == "SUFFICIENT" for r in moved) >= 6
    assert cm_no_dp["accuracy"] < 1.0 and cm_no_dp["predicted_counts"]["ABSTAIN"] == 0


def test_same_observation_different_future_invariance_and_greedy_independent_set() -> None:
    """Verify §8.6 'same observation, different future' invariance and M5+N1 greedy independent-set algorithm."""
    reg = default_cmfl_registration()
    contexts, _ = build_benchmark_suite(reg, n_per_route=2, seed=20261028)
    prior = _default_prior_belief()

    for ctx in contexts:
        res = verify_same_observation_different_future(reg, ctx, prior, domain_envelope=toy_slow_d_valid_envelope())
        assert res["identical"] is True

    # Test M5+N1 deterministic greedy independent context selection:
    # 3 contexts in the SAME world with overlapping objects or small time gap (< tau_decorr=20)
    # should collapse to 1 independent context; adding a context at t_start=25 with disjoint object gives 2.
    base_ctx = contexts[0]
    c1 = ObservationContext(
        context_id="c_b",
        world_instance_id="w_same",
        t_start=5,
        object_keys=("obj_1",),
        dt=base_ctx.dt,
        integrator=base_ctx.integrator,
        states=base_ctx.states,
        next_states=base_ctx.next_states,
        actions=base_ctx.actions,
        innovation_cov=base_ctx.innovation_cov,
    )
    c2 = ObservationContext(
        context_id="c_a",
        world_instance_id="w_same",
        t_start=0,
        object_keys=("obj_1",),
        dt=base_ctx.dt,
        integrator=base_ctx.integrator,
        states=base_ctx.states,
        next_states=base_ctx.next_states,
        actions=base_ctx.actions,
        innovation_cov=base_ctx.innovation_cov,
    )
    c3 = ObservationContext(
        context_id="c_c",
        world_instance_id="w_same",
        t_start=25,
        object_keys=("obj_1",),  # same object -> still NOT independent!
        dt=base_ctx.dt,
        integrator=base_ctx.integrator,
        states=base_ctx.states,
        next_states=base_ctx.next_states,
        actions=base_ctx.actions,
        innovation_cov=base_ctx.innovation_cov,
    )
    c4 = ObservationContext(
        context_id="c_d",
        world_instance_id="w_same",
        t_start=25,
        object_keys=("obj_2",),  # gap >= 20 AND disjoint object -> independent of c2!
        dt=base_ctx.dt,
        integrator=base_ctx.integrator,
        states=base_ctx.states,
        next_states=base_ctx.next_states,
        actions=base_ctx.actions,
        innovation_cov=base_ctx.innovation_cov,
    )
    assert not are_contexts_independent(c2, c1, tau_decorr=20)
    assert not are_contexts_independent(c2, c3, tau_decorr=20)
    assert are_contexts_independent(c2, c4, tau_decorr=20)

    indep = greedy_independent_context_set([c1, c3, c4, c2], tau_decorr=20)
    assert [c.context_id for c in indep] == ["c_a", "c_d"]


def test_parameter_identification_nees_and_standalone_store() -> None:
    """Verify online parameter identification NEES calibration on P_family and C7/R1 ParamBeliefStore."""
    reg = default_cmfl_registration()
    rng = np.random.default_rng(1028)
    prior = _default_prior_belief()
    store = ParamBeliefStore()

    with pytest.raises(TypeError, match="only accepts ParamBelief"):
        store.put("bad", {"not": "a_param_belief"})  # type: ignore[arg-type]

    nees_values: list[float] = []
    rmse_values: list[float] = []
    for i in range(16):
        true_phi = DEFAULT_PHI + rng.normal(0.0, [0.8, 0.15, 0.35])
        ctx = simulate_window(
            context_id=f"p_cal_{i}",
            world_instance_id=f"w_p_{i}",
            t_start=0,
            W=reg.W,
            dt=0.02,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=true_phi,
            true_mechanism="none",
            true_coeff=0.0,
            noise_std=0.002,
            reported_cov_scale=1.0,
            rng=rng,
        )
        post = identify_parameters_bayesian(ctx, prior)
        store.put(f"scope_{i}", post)
        nees_values.append(post.nees(true_phi))
        rmse_values.append(float(np.linalg.norm(post.mean - true_phi)))

    mean_nees = float(np.mean(nees_values))
    mean_rmse = float(np.mean(rmse_values))
    # For dim(phi)=3, well-calibrated Bayesian posterior NEES has expected value ~ 3.0
    assert 1.2 <= mean_nees <= 5.5, f"Expected calibrated mean NEES near 3.0, got {mean_nees:.3f}"
    assert mean_rmse < 0.08, f"Expected parameter RMSE < 0.08, got {mean_rmse:.4f}"
    assert len(store.keys()) == 16


def test_eig_probe_selection_and_sensitivity_orthogonal_projection() -> None:
    """Verify D4 EIG (analytical vs nested MC) and D2-7 single-step & k-step orthogonal projection."""
    reg = default_cmfl_registration()
    prior = _default_prior_belief()
    state = np.array([1.5, -1.2, 2.0, -1.8], dtype=float)
    cov_s = np.eye(4) * (0.004 ** 2)

    candidates = [
        np.array([0.0, 0.0]),
        np.array([4.0, -3.0]),
        np.array([8.0, 6.0]),
        np.array([25.0, 0.0]),  # outside D_permit action_limit=12.0 -> must be filtered out
    ]
    probe = screen_and_select_probe(state, candidates, 0.02, prior, cov_s, reg.d_permit)
    assert float(np.max(np.abs(probe.selected_action))) <= reg.d_permit.action_limit
    assert len(probe.distinguishable_observables) == 4
    assert probe.selected_eig > 0.0

    # Verify nested MC EIG exhibits upward Jensen bias at small M_in and approaches exact Gaussian EIG at larger M_in
    rng = np.random.default_rng(42)
    exact_eig = gaussian_eig_phi(state, np.array([2.0, -1.0]), 0.02, prior, np.eye(4) * 0.05)
    mc_small_in = nested_mc_eig_phi(
        state, np.array([2.0, -1.0]), 0.02, prior, np.eye(4) * 0.05, M_out=60, M_in=4, rng=rng
    )
    mc_large_in = nested_mc_eig_phi(
        state, np.array([2.0, -1.0]), 0.02, prior, np.eye(4) * 0.05, M_out=120, M_in=250, rng=rng
    )
    assert mc_small_in > exact_eig  # Jensen upward bias for small inner sample count
    assert abs(mc_large_in - exact_eig) < abs(mc_small_in - exact_eig)

    # Verify D2-7 orthogonal projection for both single_step and k_step modes (S1)
    ctx = simulate_window(
        context_id="ctx_proj",
        world_instance_id="w_proj",
        t_start=0,
        W=reg.W,
        dt=0.01,
        true_integrator="rk4",
        model_integrator="rk4",
        true_phi=DEFAULT_PHI + np.array([0.8, -0.1, 0.3]),
        true_mechanism="quadratic_drag",
        true_coeff=0.40,
        noise_std=0.002,
        reported_cov_scale=1.0,
        rng=rng,
    )
    for mode in ("single_step", "k_step"):
        proj = project_residual_orthogonal_to_sensitivity(ctx, DEFAULT_PHI, mode=mode)
        assert proj.max_abs_inner_product < 1e-12, f"{mode} projection not orthogonal: {proj.max_abs_inner_product}"
        # Total residual decomposition r = r_perp + r_absorbed
        assert np.allclose(proj.raw_residuals, proj.projected_residuals + proj.absorbed_component, atol=1e-12)


def test_executable_prior_checker_data_thinning_and_weak_stlsq() -> None:
    """Verify ExecutablePriorChecker pruning, data thinning independence, and WeakFormSTLSQ recovery."""
    checker = ExecutablePriorChecker()
    full_lib = default_basis_library()
    kept, verdicts = checker.filter_library(full_lib)
    kept_names = {t.name for t in kept}
    assert kept_names == {"quadratic_drag", "coulomb_friction", "altered_inv_r_gravity", "cubic_spring"}
    verdict_map = {v.term_name: v for v in verdicts}
    assert verdict_map["spurious_energy_pump"].passed is False
    assert verdict_map["spurious_energy_pump"].passivity_ok is False
    assert verdict_map["spurious_anisotropic_x2"].passed is False
    assert verdict_map["spurious_anisotropic_x2"].dimensional_ok is False
    assert verdict_map["spurious_anisotropic_x2"].se2_symmetry_ok is False

    # Verify Data Thinning uncorrelated property
    rng = np.random.default_rng(99)
    true_signal = np.ones((500, 4), dtype=float) * 0.5
    cov = np.eye(4) * 0.04
    noisy_r = true_signal + rng.multivariate_normal(np.zeros(4), cov, size=500)
    r_sel, r_inf = data_thin_gaussian_residuals(noisy_r, cov, rng)
    centered_sel = r_sel - true_signal
    centered_inf = r_inf - true_signal
    cross_corr = float(np.mean(centered_sel * centered_inf))
    assert abs(cross_corr) < 0.01

    # Verify WeakFormSTLSQ discovers exact support on S_family (quadratic_drag) and altered_law_family (altered_inv_r_gravity)
    stlsq = WeakFormSTLSQ(threshold=0.20)
    s_contexts = [
        simulate_window(
            context_id=f"s_disc_{i}",
            world_instance_id=f"w_s_disc_{i}",
            t_start=0,
            W=20,
            dt=0.01,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=DEFAULT_PHI,
            true_mechanism="quadratic_drag",
            true_coeff=0.45,
            noise_std=0.002,
            reported_cov_scale=1.0,
            rng=rng,
        )
        for i in range(6)
    ]
    cand_s = stlsq.discover(s_contexts, DEFAULT_PHI, rng=rng, candidate_id="cand_quad_drag")
    assert cand_s.active_terms == ("quadratic_drag",)
    assert abs(float(cand_s.coefficients[0]) - 0.45) < 0.06

    alt_contexts = [
        simulate_window(
            context_id=f"alt_disc_{i}",
            world_instance_id=f"w_alt_disc_{i}",
            t_start=0,
            W=20,
            dt=0.01,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=DEFAULT_PHI,
            true_mechanism="altered_inv_r_gravity",
            true_coeff=6.5,
            noise_std=0.002,
            reported_cov_scale=1.0,
            rng=rng,
        )
        for i in range(6)
    ]
    cand_alt = stlsq.discover(alt_contexts, DEFAULT_PHI, rng=rng, candidate_id="cand_inv_r")
    assert cand_alt.active_terms == ("altered_inv_r_gravity",)
    assert abs(float(cand_alt.coefficients[0]) - 6.5) < 0.6


def test_one_sided_promotion_gate_positive_and_negative_controls() -> None:
    """Verify D3 promotion gate:
    1. True discovered mechanism is admitted on disjoint D, C, T.
    2. ALDER negative control (true mechanism excluded from candidate basis library) -> 0% admission rate.
    3. N4 4a COVARIANCE_INCONSISTENT windows in C are deterministically stripped to form C_clean.
    4. C2 producer guard ('student' rejected), D/C/T overlap guard, and N3 re-test accounting guard.
    5. M2 dev-only vs all-environment e-LOND simulation.
    """
    reg = default_cmfl_registration()
    rng = np.random.default_rng(20261028)
    prior = _default_prior_belief()
    stlsq = WeakFormSTLSQ(threshold=0.20)

    def make_s_dataset(prefix: str, count: int) -> list[ObservationContext]:
        out: list[ObservationContext] = []
        for i in range(count):
            fam_tag = reg.env_families[i % len(reg.env_families)]
            out.append(
                simulate_window(
                    # r2: ids carry no family substring; the family is the explicit env_family label.
                    context_id=f"{prefix}_ctx_{i:02d}",
                    world_instance_id=f"{prefix}_world_{i:02d}",
                    t_start=0,
                    W=reg.W,
                    dt=0.01,
                    true_integrator="rk4",
                    model_integrator="rk4",
                    true_phi=DEFAULT_PHI,
                    true_mechanism="quadratic_drag",
                    true_coeff=0.45,
                    noise_std=0.003,
                    reported_cov_scale=1.0,
                    rng=rng,
                    env_family=fam_tag,
                )
            )
        return out

    # r2: e-LOND is a hard conjunct, so T needs enough world blocks per family to reach 1/alpha_t
    # (15 per family at alpha_seq=0.05, gamma_1=6/pi^2, N=2 attempts -> 1/alpha ~ 66).
    n_test = 45
    valid_lib, _ = ExecutablePriorChecker().filter_library(default_basis_library())

    d_set = make_s_dataset("D", 6)
    c_set_small = make_s_dataset("C_small", 10)
    # Verify finite-sample boundary k = ceil((1 - 0.05) * (10 + 1)) = 11 > 10 -> certificate_valid=False
    cert_small = calibrate_conformal_domain(d_set, c_set_small, prior, reg)
    assert cert_small.certificate_valid is False

    c_set = make_s_dataset("C", 20)
    # Inject 2 lower-tail 4a COVARIANCE_INCONSISTENT windows into C to verify N4 deterministic stripping
    for j in range(2):
        c_set.append(
            simulate_window(
                context_id=f"C_cov4a_{j}",
                world_instance_id=f"C_world_cov4a_{j}",
                t_start=0,
                W=reg.W,
                dt=0.01,
                true_integrator="rk4",
                model_integrator="rk4",
                true_phi=DEFAULT_PHI,
                true_mechanism="none",
                true_coeff=0.0,
                noise_std=0.003,
                reported_cov_scale=15.0,  # 4a lower-tail NIS
                rng=rng,
            )
        )
    t_set_1 = make_s_dataset("T1", n_test)

    # Check N4 conformal calibration directly (n_cal_clean = 20 >= 19 -> k = ceil(0.95*21) = 20 <= 20)
    cert = calibrate_conformal_domain(d_set, c_set, prior, reg)
    assert cert.n_cal_raw == 22
    assert cert.n_removed_4a == 2
    assert cert.n_cal_clean == 20
    assert cert.certificate_valid is True

    # 1. Positive promotion with full basis library
    cand_good = stlsq.discover(d_set, DEFAULT_PHI, rng=rng, discovery_data_id="D_v1", candidate_id="cand_good")
    gate = OneSidedPromotionGate(reg)
    trusted = {"verified_producer": "isolated_sim_verifier_v1", "isolated_evaluator": True}

    dec_good = gate.evaluate_and_promote(
        cand_good,
        prior,
        discovery_contexts=d_set,
        calibration_contexts=c_set,
        test_contexts=t_set_1,
        discovery_data_id="D_v1",
        calibration_data_id="C_v1",
        test_data_id="T_v1",
        test_id="test_step_1",
        producer="isolated_sim_verifier_v1",
        trusted_context=trusted,
        facttest_null_candidates=build_facttest_null_controls(cand_good, d_set, prior, valid_lib),
    )
    assert dec_good.admitted is True, f"Valid candidate should be admitted, got reasons: {dec_good.rejection_reasons}"
    assert gate.num_promoted_R == 1
    assert dec_good.e_lond_passed and dec_good.facttest_passed
    assert dec_good.e_pers >= 1.0 / dec_good.alpha_per_candidate
    assert dec_good.facttest_n_null >= 29 and dec_good.facttest_threshold is not None
    assert dec_good.facttest_score > dec_good.facttest_threshold
    assert len(set(round(v, 9) for v in dec_good.e_by_family.values())) == 3  # three families, three e-values

    # 2. ALDER Negative Control: candidate library missing true mechanism ('quadratic_drag' excluded)
    # Run 8 independent negative-control trials; admission rate MUST be 0% (0/8)
    incomplete_lib = default_basis_library(exclude_terms=("quadratic_drag",))
    false_admissions = 0
    for trial in range(8):
        d_neg = make_s_dataset(f"D_neg_{trial}", 6)
        c_neg = make_s_dataset(f"C_neg_{trial}", 20)
        t_neg = make_s_dataset(f"T_neg_{trial}", n_test)
        cand_neg = stlsq.discover(
            d_neg,
            DEFAULT_PHI,
            library=incomplete_lib,
            rng=rng,
            discovery_data_id=f"D_neg_id_{trial}",
            candidate_id=f"cand_neg_{trial}",
        )
        dec_neg = gate.evaluate_and_promote(
            cand_neg,
            prior,
            discovery_contexts=d_neg,
            calibration_contexts=c_neg,
            test_contexts=t_neg,
            discovery_data_id=f"D_neg_id_{trial}",
            calibration_data_id=f"C_neg_id_{trial}",
            test_data_id=f"T_neg_id_{trial}",
            test_id=f"test_neg_{trial}",
            producer="isolated_sim_verifier_v1",
            trusted_context=trusted,
            facttest_null_candidates=build_facttest_null_controls(cand_neg, d_neg, prior, valid_lib),
        )
        if dec_neg.admitted:
            false_admissions += 1
    assert false_admissions == 0, f"ALDER negative control violated: {false_admissions}/8 false admissions"

    # 3. Guard tests: C2 student self-certification, D/C/T overlap, and N3 re-opening used T_v1
    with pytest.raises(ValueError, match="forbidden from issuing SLOW promotion evidence"):
        require_independent_slow_producer("student", trusted_context={"verified_producer": "student", "isolated_evaluator": True})

    with pytest.raises(ValueError, match="re-test accounting violation"):
        gate.evaluate_and_promote(
            cand_good,
            prior,
            discovery_contexts=d_set,
            calibration_contexts=c_set,
            test_contexts=t_set_1,
            discovery_data_id="D_v1",
            calibration_data_id="C_v1",
            test_data_id="T_v1",  # already opened in step 1!
            test_id="test_reuse_t1",
            producer="isolated_sim_verifier_v1",
            trusted_context=trusted,
        )

    # 4. FactTest order-statistic threshold calibration (D3-8)
    null_scores = np.linspace(-0.5, 0.05, 30)
    thresh, k_idx = calibrate_facttest_threshold(null_scores, reg.tau_cal, reg.delta_cal)
    assert 1 <= k_idx <= 30
    assert float(np.mean(null_scores > thresh)) <= reg.tau_cal
    # r2: too few nulls -> threshold +inf (fail-closed), not max(null)+1e-6
    thresh_small, k_small = calibrate_facttest_threshold(null_scores[:28], reg.tau_cal, reg.delta_cal)
    assert thresh_small == float("inf") and k_small == 29

    # 5. M2 dev-only vs all-environment e-LOND simulation
    elond_sim = simulate_elond_dev_only_vs_all_env(reg, n_steps=24, seed=20261028)
    # 分母不能是 0：两边都必须真的准入了东西，否则 FDP=0/max(0,1) 是「没人被准入」而不是「FDR 受控」
    assert elond_sim["dev_only_admitted"] >= 8 and elond_sim["all_env_admitted"] >= 3
    assert elond_sim["dev_only_persistent_fdp"] > 0.50
    assert elond_sim["all_env_persistent_fdp"] == 0.0
