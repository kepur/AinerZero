#!/usr/bin/env python3
"""V9.G8 复核数字汇总（纯 CPU、纯 NumPy、零训练、零下载、零新包）。

用法：env -u PYTHONPATH -u HTTP_PROXY -u HTTPS_PROXY .venv/bin/python reports/V9-G8/run_g8.py

产出：
- reports/V9-G8/metrics.json
- reports/V9-G8/evidence/numbers.txt          逐条数字
- reports/V9-G8/evidence/mutation_matrix.txt  基线 vs 各坏控的对照矩阵
- reports/V9-G8/evidence/sha.txt              源码 SHA 复核（应与 V9-G7/evidence/SHA.txt 一致）
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(REPO / "src"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ainerzero.v9.mechanism as BASE  # noqa: E402
import g8_checks as K  # noqa: E402
from mutation_harness import MUTANTS, load_mutant, mutant_digest  # noqa: E402

OUT = HERE / "metrics.json"
EV = HERE / "evidence"
EV.mkdir(exist_ok=True)
lines: list[str] = []


def say(msg: str) -> None:
    print(msg)
    lines.append(msg)


numbers: dict = {"task": "ainerzero.V9.G8", "reviewed_task": "ainerzero.V9.G7", "seed_base": 20261028}

# ── 0. 源码 SHA 复核：确认复核没有改动被测源码 ──
def sha_table() -> dict[str, str]:
    files = sorted((REPO / "src/ainerzero/v9/mechanism").glob("*.py"))
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


sha = sha_table()
numbers["source_sha"] = sha
g7_sha = {}
p = REPO / "reports/V9-G7/evidence/SHA.txt"
if p.exists():
    for row in p.read_text(encoding="utf-8").splitlines():
        parts = row.split()
        if len(parts) == 2:
            g7_sha[Path(parts[1]).name] = parts[0]
match = {k: (g7_sha.get(k) == v) for k, v in sha.items()}
numbers["source_sha_matches_g7"] = match
say(f"[SHA] 被测源码 7 个文件与 V9-G7 报告登记一致：{all(match.values())} {match}")

# ── 1. MSG 八路由（独立生成器）──
msg = K.msg_suite(BASE, n=10)
numbers["msg_independent_generator"] = msg
say(f"[MSG] 独立生成器 80 个上下文：准确率 {msg['accuracy']:.4f}；逐路由召回 "
    f"{json.dumps({k: round(v, 3) for k, v in msg['per_route_recall'].items()}, ensure_ascii=False)}")
say(f"[MSG] 包络口径（OOD 不带标签）：n_cal={msg['envelope_n_cal']}，OOD 召回 {msg['envelope_ood_recall']:.2f}，"
    f"域内保留 {msg['envelope_in_domain_kept']:.2f}")

ood = K.msg_ood_leak_probe(BASE)
numbers["ood_leak_probe"] = ood
say(f"[MSG·OOD 泄漏] 只有标签无包络 {ood['label_only_no_envelope']}/{ood['n']}；只有包络无标签 "
    f"{ood['envelope_only_no_label']}/{ood['n']}；两者都没有 {ood['neither']}/{ood['n']}")

# ── 2. PARAMETRIC / STRUCTURAL 召回 ──
par = K.parametric_recall(BASE, n=30)
stc = K.structural_recall(BASE, n=20)
numbers["parametric_recall"] = par
numbers["structural_recall"] = stc
say(f"[PARAMETRIC] 30 个纯参数上下文：召回 {par['recall']:.4f}，路由分布 {par['counts']}")
say(f"[STRUCTURAL] 20 个结构上下文：召回 {stc['recall']:.4f}，路由分布 {stc['counts']}")

# ── 3. 共形有限样本修正 + 覆盖 ──
cf = K.conformal_boundary(BASE)
cov = K.conformal_coverage(BASE)
numbers["conformal_boundary"] = cf
numbers["conformal_coverage"] = cov
say(f"[共形] n_cal=18 → k={cf['n_cal_18']['k']}、有效={cf['n_cal_18']['valid']}；"
    f"n_cal=19 → k={cf['n_cal_19']['k']}、有效={cf['n_cal_19']['valid']}")
say(f"[共形覆盖] 名义 {cov.get('nominal')}，经验 {cov.get('empirical')}（n_cal={cov.get('n_cal')}，"
    f"{cov.get('trials')} 次留出）")

# ── 4. data thinning ──
th = K.thinning_views(BASE)
numbers["thinning"] = th
say(f"[thinning] 两视图相同={th['views_identical']}，最大差 {th['max_abs_diff']:.3e}，"
    f"交叉协方差 {th['cross_cov']:.3e}（方差 {th['var_sel']:.3e}）")
nfd = K.null_world_false_discovery(BASE)
numbers["null_world_false_discovery"] = nfd
say(f"[发现·空世界] 假发现 {nfd['false_discovery']}/{nfd['trials']} = {nfd['rate']:.2f}")

# ── 5. 正交投影 ──
pj = K.projection_invariant(BASE)
pe = K.projection_energy_ratio_single_context(BASE)
pu = K.discovery_purity(BASE)
numbers["projection"] = pj
numbers["projection_energy"] = pe
numbers["discovery_purity"] = pu
say(f"[投影·单上下文] max|<r_perp,q>| = {pj['max_abs_inner_product']['single_step']:.3e} / "
    f"{pj['max_abs_inner_product']['k_step']:.3e}；分解恒等式 {pj['decomposition_identity']}")
say(f"[投影·批量路径] 整批能量比 {pj['batch_energy_ratio']:.4f}；逐上下文比值 "
    f"{[round(v, 3) for v in pj['batch_per_context_ratio']]}（>1 表示能量反而增大）")
say(f"[投影·单上下文能量] 纯参数世界残余 {pe['param_mean_ratio']:.4f}；结构世界残余 {pe['struct_mean_ratio']:.4f}")
say(f"[发现质量] 纯参数世界假发现 {pu['param_world_false_discovery']}/{pu['param_world_trials']}；"
    f"结构世界精确支持 {pu['struct_exact_support']}/{pu['struct_trials']}，系数中位 {pu['struct_coeff_median']:.3f}")

# ── 6. 负对照与晋升门诊断 ──
nc = K.negative_controls(BASE, trials=6)
numbers["negative_controls"] = nc
for k, v in nc.items():
    say(f"[负对照] {k}: 非空候选 {v.get('nonempty_candidates', '-')}，准入 {v['admitted']}/{v['trials']}")
pd_ = K.promotion_diagnostics(BASE)
el = K.elond_gate_is_decorative(BASE)
numbers["promotion_diagnostics"] = pd_
numbers["elond_gate"] = el
say(f"[晋升门] admitted={pd_['admitted']}，n_candidates_submitted={pd_['n_candidates_submitted']}"
    f"（discover 内层迭代 {pd_['discovery_iterations']} 次），alpha_t={pd_['alpha_t']:.5f}，"
    f"alpha/N={pd_['alpha_per_candidate']:.5f}")
say(f"[晋升门·e-LOND] e_pers={pd_['e_pers']:.3f}，阈值 1/α={el['threshold_1_over_alpha']:.3f}，"
    f"e_lond_passed={pd_['e_lond_passed']}；环境族 e-value 唯一值个数 {pd_['e_by_family_unique_values']}")

# ── 7. 坏控矩阵 ──
mut_rows: list[str] = []
summary: dict[str, dict] = {}
for name in MUTANTS:
    M = load_mutant(name)
    row: dict = {"digest_changed_files": mutant_digest(name)}
    row["route_identity_equal"] = K.route_identity(M) == K.route_identity(BASE)
    row["parametric_recall"] = K.parametric_recall(M, n=30)["recall"]
    cfm = K.conformal_boundary(M)
    row["conformal_n18_k"] = cfm["n_cal_18"]["k"]
    row["conformal_n18_valid"] = cfm["n_cal_18"]["valid"]
    tm = K.thinning_views(M)
    row["thinning_views_identical"] = tm["views_identical"]
    row["thinning_cross_cov"] = tm["cross_cov"]
    row["null_world_false_discovery_rate"] = K.null_world_false_discovery(M)["rate"]
    pjm = K.projection_invariant(M)
    row["projection_max_ip_single_step"] = pjm["max_abs_inner_product"]["single_step"]
    row["projection_batch_energy_ratio"] = pjm["batch_energy_ratio"]
    row["struct_exact_support"] = K.discovery_purity(M)["struct_exact_support"]
    ncm = K.negative_controls(M, trials=6)
    row["nc_a_admission_rate"] = ncm["NC_A_missing_quadratic_drag"]["admission_rate"]
    row["nc_b_admission_rate"] = ncm["NC_B_missing_inv_r"]["admission_rate"]
    row["nc_c_admission_rate"] = ncm["NC_C_wrong_mechanism_nonempty"]["admission_rate"]
    pdm = K.promotion_diagnostics(M)
    row["admitted"] = pdm["admitted"]
    row["e_lond_passed"] = pdm["e_lond_passed"]
    summary[name] = row

numbers["mutation_matrix"] = summary

hdr = ("坏控 | 路由序列相同 | PARAMETRIC召回 | 共形k(n=18) | 共形有效 | 视图相同 | 交叉协方差 | 空世界假发现 "
       "| 投影max_ip | 批量能量比 | 结构精确支持 | NC-A | NC-B | NC-C | 准入 | e_lond")
mut_rows.append(hdr)
base_row = (
    "baseline | - | {:.3f} | {} | {} | {} | {:.2e} | {:.2f} | {:.2e} | {:.3f} | {}/20 | {:.2f} | {:.2f} | {:.2f} | {} | {}"
).format(par["recall"], cf["n_cal_18"]["k"], cf["n_cal_18"]["valid"], th["views_identical"], th["cross_cov"],
         nfd["rate"], pj["max_abs_inner_product"]["single_step"], pj["batch_energy_ratio"],
         pu["struct_exact_support"], nc["NC_A_missing_quadratic_drag"]["admission_rate"],
         nc["NC_B_missing_inv_r"]["admission_rate"], nc["NC_C_wrong_mechanism_nonempty"]["admission_rate"],
         pd_["admitted"], pd_["e_lond_passed"])
mut_rows.append(base_row)
for name, r in summary.items():
    mut_rows.append(
        "{} | {} | {:.3f} | {} | {} | {} | {:.2e} | {:.2f} | {:.2e} | {:.3f} | {}/20 | {:.2f} | {:.2f} | {:.2f} | {} | {}"
        .format(name, r["route_identity_equal"], r["parametric_recall"], r["conformal_n18_k"],
                r["conformal_n18_valid"], r["thinning_views_identical"], r["thinning_cross_cov"],
                r["null_world_false_discovery_rate"], r["projection_max_ip_single_step"],
                r["projection_batch_energy_ratio"], r["struct_exact_support"], r["nc_a_admission_rate"],
                r["nc_b_admission_rate"], r["nc_c_admission_rate"], r["admitted"], r["e_lond_passed"])
    )
(EV / "mutation_matrix.txt").write_text("\n".join(mut_rows) + "\n", encoding="utf-8")
say("[坏控] 矩阵已写入 evidence/mutation_matrix.txt")
for row in mut_rows:
    say("  " + row)

numbers["generated_at_unix"] = int(time.time())
OUT.write_text(json.dumps(numbers, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
(EV / "numbers.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
(EV / "sha.txt").write_text(
    "\n".join(f"{v}  src/ainerzero/v9/mechanism/{k}" for k, v in sha.items()) + "\n", encoding="utf-8"
)
print("\nwrote", OUT, "and", EV)
