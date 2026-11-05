"""V9.G8 复核用的可复用测量函数。

每个函数接收一个"包对象"（`ainerzero.v9.mechanism` 或 mutation_harness 加载的变异包），
返回**纯数据**（dict/float），既供 pytest 断言，也供 run_g8.py 汇总成指标。
测量本身全部基于 `independent_gen.py`（复核者自写的玩具生成器），不复用作者的 build_benchmark_suite。
"""
from __future__ import annotations

import numpy as np

import independent_gen as G

TRUSTED = {"verified_producer": "isolated_sim_verifier_v1", "isolated_evaluator": True}


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------

def make_prior(pkg, *, mean=None, cov_diag=(1.5, 0.25, 0.60)):
    m = G.G_PRIOR.copy() if mean is None else np.asarray(mean, dtype=float)
    return pkg.ParamBelief(mean=m, cov=np.diag(cov_diag), dimensionless_scale=G.SCALE.copy())


def _reg(pkg):
    return pkg.default_cmfl_registration()


# ---------------------------------------------------------------------------
# 1. MSG 八路由（独立生成器）
# ---------------------------------------------------------------------------

def msg_suite(pkg, *, n: int = 6, seed: int = 7000) -> dict:
    """两套测量：

    (a) `label_path`：与 G7 同构——OOD 上下文带 `in_slow_domain=False`，无包络。这是复现 G7 口径；
    (b) `envelope_path`：OOD 上下文**不带**标签，只给共形包络；检查包络能不能独立判出越界，
        同时确认包络不会把域内上下文误判成 OOD。
    """
    reg = _reg(pkg)
    prior = make_prior(pkg)

    # (a) G7 同构口径
    rows_label = G.gen_suite(seed=seed, n=n, ood_flag=True)
    gate = pkg.MechanismSufficiencyGate(reg)
    per_family: dict[str, list[int]] = {}
    for c, m in rows_label:
        hit = int(gate.route(c, prior).route_code.value == m.true_route)
        per_family.setdefault(m.true_route, []).append(hit)
    recall = {k: float(np.mean(v)) for k, v in per_family.items()}
    total = sum(len(v) for v in per_family.values())
    correct = sum(sum(v) for v in per_family.values())

    # (b) 包络口径
    d = (
        [c for c, _ in G.gen_sufficient(seed=seed + 101, n=8)]
        + [c for c, _ in G.gen_parametric(seed=seed + 103, n=7)]
        + [c for c, _ in G.gen_structural(seed=seed + 105, n=7)]
    )
    c_set = (
        [c for c, _ in G.gen_sufficient(seed=seed + 102, n=8)]
        + [c for c, _ in G.gen_parametric(seed=seed + 104, n=6)]
        + [c for c, _ in G.gen_structural(seed=seed + 106, n=6)]
        + [c for c, _ in G.gen_unidentifiable(seed=seed + 107, n=4)]
    )
    cert = pkg.calibrate_conformal_domain(
        d, c_set, prior, reg, discovery_data_id="Dg8_env", calibration_data_id="Cg8_env"
    )
    env = cert.envelope if cert.certificate_valid else None
    gate_env = pkg.MechanismSufficiencyGate(reg, domain_envelope=env)
    ood_hits = sum(
        gate_env.route(c, prior).route_code.value == "OUT_OF_DOMAIN"
        for c, _ in G.gen_ood(seed=seed + 7, n=n, in_slow_domain=True)
    )
    in_domain_ok = sum(
        gate_env.route(c, prior).route_code.value != "OUT_OF_DOMAIN"
        for c, _ in G.gen_sufficient(seed=seed + 8, n=n)
    )

    return {
        "n": total,
        "correct": correct,
        "accuracy": correct / total,
        "per_route_recall": recall,
        "mid_discovery_triggered": bool(gate.mid_discovery_triggered),
        "envelope_valid": bool(cert.certificate_valid),
        "envelope_n_cal": int(cert.n_cal_clean),
        "envelope_ood_recall": ood_hits / n,
        "envelope_in_domain_kept": in_domain_ok / n,
    }


def msg_ood_leak_probe(pkg, *, n: int = 6, seed: int = 7000) -> dict:
    """证明 OUT_OF_DOMAIN 的召回由 `in_slow_domain` 这个调用方布尔量承载，而不是包络。

    三种配置：(a) 只有真值标签、无包络；(b) 只有包络、标签恒 True；(c) 都没有。
    """
    reg = _reg(pkg)
    prior = make_prior(pkg)
    d = [c for c, _ in G.gen_sufficient(seed=seed + 101, n=10)]
    c_set = [c for c, _ in G.gen_sufficient(seed=seed + 102, n=20)]
    cert = pkg.calibrate_conformal_domain(
        d, c_set, prior, reg, discovery_data_id="Dg8_env2", calibration_data_id="Cg8_env2"
    )
    ood_flagged = [c for c, _ in G.gen_ood(seed=seed + 7, n=n, in_slow_domain=False)]
    ood_clean = [c for c, _ in G.gen_ood(seed=seed + 7, n=n, in_slow_domain=True)]

    def hits(gate, ctxs):
        return sum(gate.route(c, prior).route_code.value == "OUT_OF_DOMAIN" for c in ctxs)

    out = {}
    out["label_only_no_envelope"] = hits(pkg.MechanismSufficiencyGate(reg), ood_flagged)
    out["envelope_only_no_label"] = hits(pkg.MechanismSufficiencyGate(reg, domain_envelope=cert.envelope), ood_clean)
    out["neither"] = hits(pkg.MechanismSufficiencyGate(reg), ood_clean)
    out["n"] = n
    out["envelope_valid"] = bool(cert.certificate_valid)
    return out


# ---------------------------------------------------------------------------
# 2. PARAMETRIC 召回（独立生成器；用来抓"PARAMETRIC/STRUCTURAL 顺序"坏控）
# ---------------------------------------------------------------------------

def parametric_recall(pkg, *, n: int = 30, seed: int = 21) -> dict:
    reg = _reg(pkg)
    prior = make_prior(pkg)
    gate = pkg.MechanismSufficiencyGate(reg)
    counts: dict[str, int] = {}
    for c, _ in G.gen_parametric(seed=seed, n=n):
        r = gate.route(c, prior).route_code.value
        counts[r] = counts.get(r, 0) + 1
    return {"n": n, "counts": counts, "recall": counts.get("PARAMETRIC", 0) / n}


def structural_recall(pkg, *, n: int = 20, seed: int = 22) -> dict:
    reg = _reg(pkg)
    prior = make_prior(pkg)
    gate = pkg.MechanismSufficiencyGate(reg)
    counts: dict[str, int] = {}
    for c, _ in G.gen_structural(seed=seed, n=n):
        r = gate.route(c, prior).route_code.value
        counts[r] = counts.get(r, 0) + 1
    return {"n": n, "counts": counts, "recall": counts.get("STRUCTURAL", 0) / n}


def route_identity(pkg, *, n: int = 6, seed: int = 7000) -> list[str]:
    """整条独立套件的路由码序列（用于比较两个实现是否逐条等价）。"""
    reg = _reg(pkg)
    prior = make_prior(pkg)
    gate = pkg.MechanismSufficiencyGate(reg)
    return [gate.route(c, prior).route_code.value for c, _ in G.gen_suite(seed=seed, n=n, ood_flag=True)]


# ---------------------------------------------------------------------------
# 3. 共形有限样本修正（D3-4）
# ---------------------------------------------------------------------------

def conformal_boundary(pkg, *, alpha_dom: float | None = None) -> dict:
    reg = _reg(pkg)
    prior = make_prior(pkg)
    d = [c for c, _ in G.gen_sufficient(seed=32, n=10)]
    out = {}
    for n_cal in (18, 19, 20):
        c_set = [c for c, _ in G.gen_sufficient(seed=31, n=n_cal)]
        cert = pkg.calibrate_conformal_domain(
            d, c_set, prior, reg, discovery_data_id="Dcf", calibration_data_id=f"Ccf{n_cal}"
        )
        out[f"n_cal_{n_cal}"] = {
            "n_cal_clean": cert.n_cal_clean,
            "k": cert.order_stat_k,
            "valid": bool(cert.certificate_valid),
            "quantile": float(cert.residual_quantile),
        }
    return out


def conformal_coverage(pkg, *, n_cal: int = 40, trials: int = 200, seed: int = 41) -> dict:
    """边际覆盖自检：用 D/C 标定，在一批新的同分布上下文上看 max-step-error 是否落在分位数内。"""
    reg = _reg(pkg)
    prior = make_prior(pkg)
    d = [c for c, _ in G.gen_sufficient(seed=seed, n=12)]
    c_set = [c for c, _ in G.gen_sufficient(seed=seed + 1, n=n_cal)]
    cert = pkg.calibrate_conformal_domain(d, c_set, prior, reg, discovery_data_id="Dcov", calibration_data_id="Ccov")
    if not cert.certificate_valid:
        return {"valid": False}
    from ainerzero.v9.mechanism import integrate_one_step  # F_prior 是冻结模型，非生成器
    covered = 0
    for c, _ in G.gen_sufficient(seed=seed + 2, n=trials):
        pred = integrate_one_step(c.states, c.actions, c.dt, prior.mean, integrator=c.integrator)
        score = float(np.max(np.linalg.norm(c.next_states - pred, axis=-1)))
        covered += int(score <= cert.residual_quantile)
    return {"valid": True, "n_cal": cert.n_cal_clean, "k": cert.order_stat_k,
            "nominal": 1.0 - reg.alpha_dom, "empirical": covered / trials, "trials": trials}


# ---------------------------------------------------------------------------
# 4. data thinning（发现/检验数据分离）
# ---------------------------------------------------------------------------

def thinning_views(pkg, *, seed: int = 51, m: int = 400) -> dict:
    rng = np.random.default_rng(seed)
    signal = np.full((m, 4), 0.4, dtype=float)
    cov = np.eye(4) * (G.SIGMA_G8 ** 2)
    raw = signal + rng.multivariate_normal(np.zeros(4), cov, size=m)
    sel, inf = pkg.data_thin_gaussian_residuals(raw, cov, rng)
    same = bool(np.allclose(sel, inf))
    cs = sel - signal
    ci = inf - signal
    return {
        "views_identical": same,
        "max_abs_diff": float(np.max(np.abs(sel - inf))),
        "cross_cov": float(np.mean(cs * ci)),
        "var_sel": float(np.mean(cs ** 2)),
        "var_inf": float(np.mean(ci ** 2)),
    }


def null_world_false_discovery(pkg, *, trials: int = 20, n_ctx: int = 6, seed: int = 800) -> dict:
    stlsq = pkg.WeakFormSTLSQ(threshold=0.20)
    fp = 0
    for k in range(trials):
        ctxs = [c for c, _ in G.gen_sufficient(seed=seed + k, n=n_ctx)]
        cand = stlsq.discover(ctxs, G.G_PRIOR, rng=np.random.default_rng(seed + 100 + k))
        fp += int(len(cand.active_terms) > 0)
    return {"trials": trials, "false_discovery": fp, "rate": fp / trials}


# ---------------------------------------------------------------------------
# 5. 正交投影（D2-7）
# ---------------------------------------------------------------------------

def projection_invariant(pkg) -> dict:
    prior = make_prior(pkg)
    ctxs = [c for c, _ in G.gen_parametric(seed=401, n=6)]
    max_ip = {}
    decomp_ok = {}
    for mode in ("single_step", "k_step"):
        worst = 0.0
        ok = True
        for c in ctxs:
            p = pkg.project_residual_orthogonal_to_sensitivity(c, G.G_PRIOR, mode=mode)
            worst = max(worst, float(p.max_abs_inner_product))
            ok = ok and bool(np.allclose(p.raw_residuals, p.projected_residuals + p.absorbed_component, atol=1e-12))
        max_ip[mode] = worst
        decomp_ok[mode] = ok

    # discover() 的批量路径：必须真的改变向量（不是恒等映射）
    stlsq = pkg.WeakFormSTLSQ(threshold=0.20)
    q = stlsq._compute_pooled_orthogonal_basis(ctxs, G.G_PRIOR, "single_step")
    raws = [pkg.compute_innovations_and_nis(c, G.G_PRIOR)[0] for c in ctxs]
    proj = stlsq._project_views_orthogonal(raws, q)
    e_raw = sum(float(np.sum(r ** 2)) for r in raws)
    e_prj = sum(float(np.sum(r ** 2)) for r in proj)
    per_ctx = [float(np.sum(p ** 2) / np.sum(r ** 2)) for p, r in zip(proj, raws)]
    return {
        "max_abs_inner_product": max_ip,
        "decomposition_identity": decomp_ok,
        "batch_energy_ratio": e_prj / e_raw,
        "batch_per_context_ratio": per_ctx,
        "batch_per_context_max": max(per_ctx),
    }


def discovery_purity(pkg) -> dict:
    """纯参数世界（无结构项）上不该发现任何结构项；结构世界上应恢复 quadratic_drag。"""
    stlsq = pkg.WeakFormSTLSQ(threshold=0.20)
    param_fp = 0
    for k in range(10):
        ctxs = [c for c, _ in G.gen_parametric(seed=400 + k, n=6)]
        cand = stlsq.discover(ctxs, G.G_PRIOR, rng=np.random.default_rng(500 + k))
        param_fp += int(len(cand.active_terms) > 0)
    struct_ok = 0
    struct_coeff = []
    for k in range(20):
        ctxs = [c for c, _ in G.gen_structural(seed=600 + k, n=6)]
        cand = stlsq.discover(ctxs, G.G_PRIOR, rng=np.random.default_rng(700 + k))
        struct_ok += int(cand.active_terms == ("quadratic_drag",))
        if cand.active_terms == ("quadratic_drag",):
            struct_coeff.append(float(cand.coefficients[0]))
    return {
        "param_world_false_discovery": param_fp,
        "param_world_trials": 10,
        "struct_exact_support": struct_ok,
        "struct_trials": 20,
        "struct_coeff_median": float(np.median(struct_coeff)) if struct_coeff else None,
    }


def projection_energy_ratio_single_context(pkg) -> dict:
    """单上下文自投影：参数世界应几乎全被投掉，结构世界应保留结构信号。"""
    out = {"param": [], "struct": []}
    for tag, rows in (("param", G.gen_parametric(seed=401, n=6)), ("struct", G.gen_structural(seed=601, n=6))):
        for c, _ in rows:
            p = pkg.project_residual_orthogonal_to_sensitivity(c, G.G_PRIOR, mode="single_step")
            out[tag].append(float(np.sum(p.projected_residuals ** 2) / np.sum(p.raw_residuals ** 2)))
    return {
        "param_mean_ratio": float(np.mean(out["param"])),
        "struct_mean_ratio": float(np.mean(out["struct"])),
    }


# ---------------------------------------------------------------------------
# 6. 晋升门：负对照、e-LOND、环境族
# ---------------------------------------------------------------------------

def _ds(pkg, prefix: str, n: int, *, mech: str = "quadratic_drag", coeff: float = 0.55, seed: int = 0):
    out = []
    for i in range(n):
        rng = np.random.default_rng(seed * 1000 + i)
        out.append(pkg.simulate_window(
            context_id=f"{prefix}_{i}", world_instance_id=f"w{prefix}_{i}", t_start=0, W=20, dt=0.01,
            true_integrator="rk4", model_integrator="rk4", true_phi=G.G_PRIOR.copy(),
            true_mechanism=mech, true_coeff=coeff, noise_std=0.003, reported_cov_scale=1.0, rng=rng,
        ))
    return out


def negative_controls(pkg, *, trials: int = 6) -> dict:
    """三组负对照：
    NC-A 候选库缺真项（ALDER）→ 期望准入 0；
    NC-B 候选库缺真项但真实机制是 inv_r（库保留 quadratic_drag）→ 期望准入 0；
    NC-C 非空但机制错误的手工候选（coulomb_friction 顶替 quadratic_drag）→ **这是对"负对照准入=0"的加强版检验**。
    """
    reg = _reg(pkg)
    prior = make_prior(pkg)
    stlsq = pkg.WeakFormSTLSQ(threshold=0.20)
    out: dict[str, dict] = {}

    def run(lib, mech, coeff, tag):
        admitted = 0
        nonempty = 0
        reasons: list[tuple[str, ...]] = []
        for k in range(trials):
            d = _ds(pkg, f"D{tag}{k}", 6, mech=mech, coeff=coeff, seed=10 + k)
            c = _ds(pkg, f"C{tag}{k}", 22, mech=mech, coeff=coeff, seed=20 + k)
            t = _ds(pkg, f"T{tag}{k}", 12, mech=mech, coeff=coeff, seed=30 + k)
            cand = stlsq.discover(d, G.G_PRIOR, library=lib, rng=np.random.default_rng(40 + k),
                                  discovery_data_id=f"Did{tag}{k}", candidate_id=f"cand{tag}{k}")
            nonempty += int(len(cand.active_terms) > 0)
            gate = pkg.OneSidedPromotionGate(reg)
            dec = gate.evaluate_and_promote(
                cand, prior, discovery_contexts=d, calibration_contexts=c, test_contexts=t,
                discovery_data_id=f"Did{tag}{k}", calibration_data_id=f"Cid{tag}{k}",
                test_data_id=f"Tid{tag}{k}", test_id=f"t{tag}{k}",
                producer="isolated_sim_verifier_v1", trusted_context=TRUSTED,
            )
            admitted += int(dec.admitted)
            reasons.append(tuple(dec.rejection_reasons[:2]))
        return {"trials": trials, "nonempty_candidates": nonempty, "admitted": admitted,
                "admission_rate": admitted / trials, "sample_reasons": reasons[:3]}

    lib_no_quad = pkg.default_basis_library(exclude_terms=("quadratic_drag",))
    lib_no_invr = pkg.default_basis_library(exclude_terms=("altered_inv_r_gravity",))
    out["NC_A_missing_quadratic_drag"] = run(lib_no_quad, "quadratic_drag", 0.55, "A")
    out["NC_B_missing_inv_r"] = run(lib_no_invr, "altered_inv_r_gravity", 6.5, "B")

    # NC-C：非空但机制错误的候选（手工构造，系数取自"方向正确但机制不同"的替身）
    admitted_c = 0
    for k in range(trials):
        d = _ds(pkg, f"DC{k}", 6, seed=50 + k)
        c = _ds(pkg, f"CC{k}", 22, seed=60 + k)
        t = _ds(pkg, f"TC{k}", 12, seed=70 + k)
        cand = pkg.DiscoveredCandidate(
            candidate_id=f"cand_wrong_{k}", proposer="sindy", active_terms=("coulomb_friction",),
            coefficients=np.array([0.45]), confidence_intervals=((0.40, 0.50),), abstained_terms=(),
            pareto_error=0.1, pareto_complexity=1, discovery_data_id=f"DidC{k}",
            total_candidates_attempted=1, orthogonality_mode="single_step",
        )
        gate = pkg.OneSidedPromotionGate(reg)
        dec = gate.evaluate_and_promote(
            cand, prior, discovery_contexts=d, calibration_contexts=c, test_contexts=t,
            discovery_data_id=f"DidC{k}", calibration_data_id=f"CidC{k}", test_data_id=f"TidC{k}",
            test_id=f"tC{k}", producer="isolated_sim_verifier_v1", trusted_context=TRUSTED,
        )
        admitted_c += int(dec.admitted)
    out["NC_C_wrong_mechanism_nonempty"] = {"trials": trials, "admitted": admitted_c,
                                            "admission_rate": admitted_c / trials}
    return out


def promotion_diagnostics(pkg) -> dict:
    """e-LOND 总闸门是否接线 / 环境族交并是否退化 / N 的取值来源。"""
    reg = _reg(pkg)
    prior = make_prior(pkg)
    stlsq = pkg.WeakFormSTLSQ(threshold=0.20)
    d = _ds(pkg, "Dg", 6, seed=90)
    c = _ds(pkg, "Cg", 22, seed=91)
    t = _ds(pkg, "Tg", 12, seed=92)
    cand = stlsq.discover(d, G.G_PRIOR, rng=np.random.default_rng(93), discovery_data_id="Did_g", candidate_id="cand_g")
    gate = pkg.OneSidedPromotionGate(reg)
    dec = gate.evaluate_and_promote(
        cand, prior, discovery_contexts=d, calibration_contexts=c, test_contexts=t,
        discovery_data_id="Did_g", calibration_data_id="Cid_g", test_data_id="Tid_g", test_id="tg",
        producer="isolated_sim_verifier_v1", trusted_context=TRUSTED,
    )
    fam_vals = [round(float(v), 9) for v in dec.e_by_family.values()]
    return {
        "candidate_terms": list(cand.active_terms),
        "discovery_iterations": int(cand.total_candidates_attempted),
        "admitted": bool(dec.admitted),
        "n_candidates_submitted": int(dec.n_candidates_submitted),
        "alpha_t": float(dec.alpha_t),
        "alpha_per_candidate": float(dec.alpha_per_candidate),
        "e_pers": float(dec.e_pers),
        "e_lond_passed": bool(dec.e_lond_passed),
        "e_by_family": dict(dec.e_by_family),
        "e_by_family_unique_values": len(set(fam_vals)),
        "n_world_blocks": int(dec.n_world_blocks),
        "reasons": list(dec.rejection_reasons),
    }


def elond_gate_is_decorative(pkg) -> dict:
    """把 e_lond_passed 恒置 False 之后，准入结论是否改变（不变 = 总闸门未接线）。"""
    reg = _reg(pkg)
    prior = make_prior(pkg)
    stlsq = pkg.WeakFormSTLSQ(threshold=0.20)
    d = _ds(pkg, "Dg", 6, seed=94)
    c = _ds(pkg, "Cg", 22, seed=95)
    t = _ds(pkg, "Tg", 12, seed=96)
    cand = stlsq.discover(d, G.G_PRIOR, rng=np.random.default_rng(97), discovery_data_id="Did_g2", candidate_id="cand_g2")
    dec = pkg.OneSidedPromotionGate(reg).evaluate_and_promote(
        cand, prior, discovery_contexts=d, calibration_contexts=c, test_contexts=t,
        discovery_data_id="Did_g2", calibration_data_id="Cid_g2", test_data_id="Tid_g2", test_id="tg2",
        producer="isolated_sim_verifier_v1", trusted_context=TRUSTED,
    )
    # 准入合取式里是否包含 e_lond_passed / e_pers（源码级判定，见 report 引用的行号）
    src = (pkg.__file__,)
    return {
        "admitted": bool(dec.admitted),
        "e_lond_passed": bool(dec.e_lond_passed),
        "e_pers": float(dec.e_pers),
        "threshold_1_over_alpha": 1.0 / dec.alpha_per_candidate,
        "admitted_implies_e_lond_true": bool((not dec.admitted) or dec.e_lond_passed),
        "package_file": src[0],
    }
