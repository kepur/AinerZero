#!/usr/bin/env python3
"""V9.G7 报告数字（CPU、纯 NumPy、零训练）：MSG 混淆矩阵、φ 的 NEES 校准、发现恢复率、负对照错误准入率。

用法：env -u PYTHONPATH .venv/bin/python reports/V9-G7/run_report.py
输出：reports/V9-G7/metrics_numbers.json 与 reports/V9-G7/evidence/numbers.txt。
所有随机性由固定 seed 派生；不读 MLX/torch；不碰台账与锁。真实路由标签只用于评测，不进任何判定输入。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.mechanism import (  # noqa: E402
    DEFAULT_PHI,
    DEFAULT_SCALE,
    MechanismSufficiencyGate,
    OneSidedPromotionGate,
    ParamBelief,
    WeakFormSTLSQ,
    build_benchmark_suite,
    chi2_ppf,
    default_basis_library,
    default_cmfl_registration,
    evaluate_msg_confusion_matrix,
    identify_parameters_bayesian,
    simulate_elond_dev_only_vs_all_env,
    simulate_window,
)

OUT_DIR = Path(__file__).resolve().parent
reg = default_cmfl_registration()
prior = ParamBelief(mean=DEFAULT_PHI.copy(), cov=np.diag([1.5, 0.25, 0.60]), dimensionless_scale=DEFAULT_SCALE.copy())
numbers: dict = {"seed_base": 20261028}
lines: list[str] = []


def say(msg: str) -> None:
    print(msg)
    lines.append(msg)


# ── 1. MSG 八路由混淆矩阵（5 个 seed × 64 个上下文），以及 M8 去 D_permit 对照 ──
total = 0
correct = 0
per_class_hits: dict[str, list[int]] = {}
no_dp_moves = {"SUFFICIENT": 0, "COVARIANCE_INCONSISTENT": 0, "other": 0}
for seed in range(20261028, 20261033):
    contexts, metas = build_benchmark_suite(reg, n_per_route=8, seed=seed)
    gate = MechanismSufficiencyGate(reg)
    recs = [gate.route(c, prior, scope_id=c.context_id) for c in contexts]
    cm = evaluate_msg_confusion_matrix(recs, metas)
    total += cm["total"]
    correct += round(cm["accuracy"] * cm["total"])
    for name, rec in cm["per_class_recall"].items():
        per_class_hits.setdefault(name, []).append(rec)
    gate_nd = MechanismSufficiencyGate(reg, disable_d_permit=True)
    recs_nd = [gate_nd.route(c, prior, scope_id=c.context_id) for c in contexts]
    abstain_ids = {m.context_id for m in metas if m.true_route.value == "ABSTAIN"}
    for r in recs_nd:
        if r.context_id in abstain_ids:
            key = r.route_code.value if r.route_code.value in ("SUFFICIENT", "COVARIANCE_INCONSISTENT") else "other"
            no_dp_moves[key] += 1
numbers["msg"] = {
    "seeds": 5, "contexts": total, "accuracy": correct / total,
    "per_class_recall_mean": {k: float(np.mean(v)) for k, v in per_class_hits.items()},
    "without_d_permit_former_abstain_routes": no_dp_moves,
}
say(f"[MSG] {total} 个上下文 / 5 个 seed：准确率 {correct / total:.4f}；各路由召回均值 {numbers['msg']['per_class_recall_mean']}")
say(f"[MSG M8] 去掉 D_permit 后，原 ABSTAIN 的 {sum(no_dp_moves.values())} 个上下文被放行到：{no_dp_moves}（D_permit 不是冗余）")

# ── 2. φ 的 NEES 校准（P 族：只有参数偏差）──
rng = np.random.default_rng(20261028)
nees, rmse = [], []
for i in range(200):
    true_phi = DEFAULT_PHI + rng.normal(0.0, [0.8, 0.15, 0.35])
    ctx = simulate_window(context_id=f"nees_{i}", world_instance_id=f"w_nees_{i}", t_start=0, W=reg.W, dt=0.02,
                          true_integrator="rk4", model_integrator="rk4", true_phi=true_phi, true_mechanism="none",
                          true_coeff=0.0, noise_std=0.002, reported_cov_scale=1.0, rng=rng)
    post = identify_parameters_bayesian(ctx, prior)
    nees.append(post.nees(true_phi))
    rmse.append(float(np.linalg.norm(post.mean - true_phi)))
nees = np.asarray(nees)
hi95 = chi2_ppf(0.95, 3)
lo05 = chi2_ppf(0.05, 3)
numbers["nees"] = {"n": 200, "dim": 3, "mean": float(nees.mean()), "expected_mean": 3.0,
                   "frac_below_chi2_95": float(np.mean(nees <= hi95)), "frac_above_chi2_05": float(np.mean(nees >= lo05)),
                   "rmse_mean": float(np.mean(rmse))}
say(f"[NEES] n=200 dim=3：均值 {nees.mean():.3f}（期望 3）；≤χ²₃(0.95)={hi95:.2f} 的比例 {np.mean(nees <= hi95):.3f}；"
    f"≥χ²₃(0.05)={lo05:.2f} 的比例 {np.mean(nees >= lo05):.3f}；参数 RMSE 均值 {np.mean(rmse):.4f}")

# ── 3. 发现恢复率（弱形式 STLSQ；每个机制 20 次独立试验，每次 6 个上下文）──
stlsq = WeakFormSTLSQ(threshold=0.20)
mechs = {"quadratic_drag": 0.45, "altered_inv_r_gravity": 6.5}
rec_rows = {}
for mech, coeff in mechs.items():
    exact, rel_err = 0, []
    for k in range(20):
        ctxs = [simulate_window(context_id=f"rec_{mech}_{k}_{i}", world_instance_id=f"w_rec_{mech}_{k}_{i}", t_start=0, W=20,
                                dt=0.01, true_integrator="rk4", model_integrator="rk4", true_phi=DEFAULT_PHI,
                                true_mechanism=mech, true_coeff=coeff, noise_std=0.002, reported_cov_scale=1.0, rng=rng)
                for i in range(6)]
        cand = stlsq.discover(ctxs, DEFAULT_PHI, rng=rng, candidate_id=f"rec_{mech}_{k}")
        if cand.active_terms == (mech,):
            exact += 1
            rel_err.append(abs(float(cand.coefficients[0]) - coeff) / coeff)
    rec_rows[mech] = {"trials": 20, "exact_support_recovery": exact / 20,
                      "median_rel_coeff_error_on_recovered": float(np.median(rel_err)) if rel_err else None}
# 空世界（无机制）上的假发现率
false_disc = 0
for k in range(20):
    ctxs = [simulate_window(context_id=f"nul_{k}_{i}", world_instance_id=f"w_nul_{k}_{i}", t_start=0, W=20, dt=0.01,
                            true_integrator="rk4", model_integrator="rk4", true_phi=DEFAULT_PHI, true_mechanism="none",
                            true_coeff=0.0, noise_std=0.002, reported_cov_scale=1.0, rng=rng) for i in range(6)]
    cand = stlsq.discover(ctxs, DEFAULT_PHI, rng=rng, candidate_id=f"nul_{k}")
    false_disc += int(len(cand.active_terms) > 0)
rec_rows["null_world_false_discovery_rate"] = false_disc / 20
numbers["discovery"] = rec_rows
say(f"[发现] {json.dumps(rec_rows, ensure_ascii=False)}")

# ── 4. 负对照：候选库缺项（ALDER）下的错误准入率；以及正对照准入率 ──
trusted = {"verified_producer": "isolated_sim_verifier_v1", "isolated_evaluator": True}


def dataset(prefix: str, count: int):
    out = []
    for i in range(count):
        fam = reg.env_families[i % len(reg.env_families)]
        out.append(simulate_window(context_id=f"{prefix}_ctx_{fam}_{i:02d}", world_instance_id=f"{prefix}_world_{fam}_{i:02d}",
                                   t_start=0, W=reg.W, dt=0.01, true_integrator="rk4", model_integrator="rk4",
                                   true_phi=DEFAULT_PHI, true_mechanism="quadratic_drag", true_coeff=0.45,
                                   noise_std=0.003, reported_cov_scale=1.0, rng=rng))
    return out


gate = OneSidedPromotionGate(reg)
n_trials = 20
admitted_pos = 0
admitted_neg = 0
incomplete = default_basis_library(exclude_terms=("quadratic_drag",))
for t in range(n_trials):
    for kind, lib in (("pos", None), ("neg", incomplete)):
        d, c, tt = dataset(f"D_{kind}{t}", 6), dataset(f"C_{kind}{t}", 20), dataset(f"T_{kind}{t}", 12)
        kw = {"library": lib} if lib is not None else {}
        cand = stlsq.discover(d, DEFAULT_PHI, rng=rng, discovery_data_id=f"Did_{kind}{t}", candidate_id=f"cand_{kind}{t}", **kw)
        dec = gate.evaluate_and_promote(cand, prior, discovery_contexts=d, calibration_contexts=c, test_contexts=tt,
                                        discovery_data_id=f"Did_{kind}{t}", calibration_data_id=f"Cid_{kind}{t}",
                                        test_data_id=f"Tid_{kind}{t}", test_id=f"test_{kind}{t}",
                                        producer="isolated_sim_verifier_v1", trusted_context=trusted)
        if dec.admitted:
            if kind == "pos":
                admitted_pos += 1
            else:
                admitted_neg += 1
numbers["promotion_gate"] = {"trials_each": n_trials, "positive_admission_rate": admitted_pos / n_trials,
                             "negative_control_false_admission_rate": admitted_neg / n_trials}
say(f"[晋升门] 正对照（完整库）准入率 {admitted_pos}/{n_trials}；负对照（库缺 quadratic_drag）错误准入率 {admitted_neg}/{n_trials}")

# ── 5. M2：dev-only vs 全环境 e-LOND ──
numbers["elond"] = simulate_elond_dev_only_vs_all_env(reg, n_steps=24, seed=20261028)
say(f"[e-LOND M2] {json.dumps(numbers['elond'], ensure_ascii=False)}")

numbers["generated_at_unix"] = int(time.time())
(OUT_DIR / "evidence").mkdir(exist_ok=True)
(OUT_DIR / "metrics_numbers.json").write_text(json.dumps(numbers, ensure_ascii=False, indent=1), encoding="utf-8")
(OUT_DIR / "evidence" / "numbers.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
