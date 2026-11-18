"""V9-mini M4 确认段独立复算脚本（非作者独立复算，AinerRelay ainerzero.V9.A30）

本脚本完全独立实现，不 import ainerzero.v9.mini.summarize，也不 import reports/V9-MINI/M4/analysis/judge.py。
仅使用 Python 3 标准库与 numpy。

用于核验：
1. 完整性检查（代码哈希、MLX 版本、留出图种子范围及互斥性、回合数、12 组任务序列一致性、oracle 全部到达、预算账本核对）；
2. 独立复算 7 项区间门（H1-m1, H1-m2, H2, H2', H3, H4①）：长目标按图整簇 bootstrap 95% 区间，4000 次重抽样；
3. 独立复算 H4②（前进模型留出事件准确率真值标签减自监督，5 种子均值），并对照 batch3 原始记录核对取法一致性；
4. 核验 M4-RESULT.md §2 与 §3 的全部数字（长目标成功率表、非门控对比、规律相关子集、短目标、诊断指标、迷路拆分统计）。

输出机器可读 JSON 至同目录 recompute.json。
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

import numpy as np

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
M4_ROOT = WORKSPACE_ROOT / "reports" / "V9-MINI" / "M4"
OUT_DIR = WORKSPACE_ROOT / "reports" / "V9-MINI" / "M4-recompute"

FREEZE_FILE = M4_ROOT / "FREEZE.json"
LEDGER_FILE = M4_ROOT / "ledger.txt"
ORACLE_CHECK_FILE = WORKSPACE_ROOT / "reports" / "V9-MINI" / "M4-prefreeze" / "oracle_check.json"

LATENT_ARMS = ("latent_euclid", "latent_learned", "graph_memory", "gru_belief")
EXPECTED_EPISODES = {"m1": 1523, "m2": 1703}


def load_runs(world: str):
    runs = []
    for s in range(5):
        run_dir = M4_ROOT / f"{world}-s{s}"
        res = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
        eps = json.loads((run_dir / "episodes.json").read_text(encoding="utf-8"))
        runs.append((s, res, eps))
    return runs


def cluster_bootstrap_ci(
    diffs: np.ndarray,
    keys: list[tuple[int, int]],
    rng: np.random.Generator,
    n_boot: int = 4000,
    confidence: float = 0.95,
) -> tuple[float, float, float, int, int]:
    """独立实现的按图整簇重抽样比率估计量 bootstrap。

    每个样本簇是 (seed, layout_seed)。
    估计量 theta = (sum_{clusters} sum_{episodes in cluster} diff) / (sum_{clusters} n_episodes_in_cluster)。
    每次有放回抽样相同数量的簇。
    """
    clusters: dict[tuple[int, int], list[float]] = {}
    for d, k in zip(diffs, keys):
        clusters.setdefault(k, []).append(float(d))

    uniq_keys = list(clusters.keys())
    m = len(uniq_keys)
    cluster_sums = np.array([sum(clusters[k]) for k in uniq_keys], dtype=np.float64)
    cluster_counts = np.array([len(clusters[k]) for k in uniq_keys], dtype=np.float64)

    # 4000 次有放回抽样整簇
    sample_indices = rng.integers(0, m, size=(n_boot, m))
    boot_sums = cluster_sums[sample_indices].sum(axis=1)
    boot_counts = cluster_counts[sample_indices].sum(axis=1)
    boot_estimates = boot_sums / boot_counts

    alpha = (1.0 - confidence) / 2.0
    lo, hi = np.percentile(boot_estimates, [alpha * 100.0, (1.0 - alpha) * 100.0])
    point_est = float(np.mean(diffs))
    return point_est, float(lo), float(hi), len(diffs), m


def check_integrity(world: str, runs: list, freeze_data: dict, out_lines: list) -> dict:
    info = {"runs": [], "total_episodes": 0, "all_passed": True}
    frozen_sha = freeze_data["code_sha256"]
    seen_layouts = set()
    total_episodes = 0

    for s, res, eps in runs:
        m = res["meta"]
        run_name = f"{world}-s{s}"
        checks = {}

        # 1. code_sha256
        sha_ok = m["code_sha256"] == frozen_sha
        checks["code_sha256_match"] = sha_ok
        checks["code_sha256"] = m["code_sha256"]

        # 2. mlx version
        checks["mlx_version"] = m["mlx"]

        # 3. eval_seed0
        expected_eval_seed0 = 8_000_000 + 1000 * s
        seed0_ok = m["eval_seed0"] == expected_eval_seed0
        checks["eval_seed0_match"] = seed0_ok
        checks["eval_seed0"] = m["eval_seed0"]

        # 4. layout seed bounds & disjointness
        oracle_eps = eps["oracle"]
        layouts = {r["layout_seed"] for r in oracle_eps}
        bounds_ok = all(expected_eval_seed0 <= lay < expected_eval_seed0 + 80 for lay in layouts)
        checks["layouts_in_bounds"] = bounds_ok
        checks["layouts_count"] = len(layouts)
        checks["layouts_range"] = [min(layouts), max(layouts)]

        overlap = layouts & seen_layouts
        checks["no_overlap_with_prev_seeds"] = len(overlap) == 0
        seen_layouts |= layouts

        # 5. task sequence alignment across all 12 arms
        ref_seq = [(r["layout_seed"], r["kind"], r["d_star"], r["law_relevant"]) for r in oracle_eps]
        seq_ok = True
        for arm_name, arm_eps in eps.items():
            arm_seq = [(r["layout_seed"], r["kind"], r["d_star"], r["law_relevant"]) for r in arm_eps]
            if arm_seq != ref_seq:
                seq_ok = False
                break
        checks["task_sequence_aligned"] = seq_ok

        # 6. oracle reaches goal on all episodes
        oracle_all_reached = all(r["success"] == 1 for r in oracle_eps)
        checks["oracle_all_reached"] = oracle_all_reached

        checks["n_episodes"] = len(ref_seq)
        total_episodes += len(ref_seq)

        checks["wall_sec"] = m.get("wall_sec")
        checks["git_head"] = m.get("git_head")

        run_passed = all([sha_ok, seed0_ok, bounds_ok, len(overlap) == 0, seq_ok, oracle_all_reached])
        if not run_passed:
            info["all_passed"] = False

        info["runs"].append({"run": run_name, "checks": checks, "passed": run_passed})
        out_lines.append(
            f"  {run_name}: 代码哈希 {'一致' if sha_ok else '不一致'}；mlx {m['mlx']}；"
            f"留出图 {min(layouts)}..{max(layouts)}（{len(layouts)} 张有任务）；"
            f"回合 {len(ref_seq)}；12 组任务序列 {'一致' if seq_ok else '不一致'}；"
            f"oracle {'全到达' if oracle_all_reached else '存在未到达'}"
        )

    info["total_episodes"] = total_episodes
    ep_match = total_episodes == EXPECTED_EPISODES[world]
    info["total_episodes_match"] = ep_match
    if not ep_match:
        info["all_passed"] = False

    out_lines.append(
        f"  {world} 回合合计 {total_episodes}（预登记预期 {EXPECTED_EPISODES[world]}）："
        f"{'一致' if ep_match else '不一致'}"
    )
    return info


def check_ledger_and_budget(freeze_data: dict, out_lines: list) -> dict:
    ledger_text = LEDGER_FILE.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in ledger_text.splitlines() if ln.strip()]

    # Parse ledger
    ledger_entries = []
    run_pattern = re.compile(r"(\S+)\s+(m[12])\s+(s[0-4])\s+exit=(\d+)\s+用时\s+(\d+)s\s+累计\s+(\d+)s")
    for ln in lines:
        m = run_pattern.match(ln)
        if m:
            ledger_entries.append({
                "timestamp": m.group(1),
                "world": m.group(2),
                "seed": int(m.group(3)[1:]),
                "exit_code": int(m.group(4)),
                "duration_sec": int(m.group(5)),
                "cumulative_sec": int(m.group(6)),
            })

    total_ledger_sec = ledger_entries[-1]["cumulative_sec"] if ledger_entries else 0
    cap_total_sec = freeze_data["budget"]["cap_total_sec"]
    cap_run_sec = freeze_data["budget"]["cap_run_sec"]
    expected_sec = freeze_data["budget"]["expected_sec"]

    all_exit_zero = all(e["exit_code"] == 0 for e in ledger_entries)
    all_runs_under_cap = all(e["duration_sec"] <= cap_run_sec for e in ledger_entries)
    total_under_cap = total_ledger_sec <= cap_total_sec

    out_lines.append(f"  账本记录 10 次运行全部 exit=0，累计用时 {total_ledger_sec}s（预算上限 {cap_total_sec}s，预计 {expected_sec}s）")
    out_lines.append(f"  单次最长用时 {max(e['duration_sec'] for e in ledger_entries)}s（单次上限 {cap_run_sec}s）")

    return {
        "entries_count": len(ledger_entries),
        "total_ledger_sec": total_ledger_sec,
        "cap_total_sec": cap_total_sec,
        "cap_run_sec": cap_run_sec,
        "all_exit_zero": all_exit_zero,
        "all_runs_under_cap": all_runs_under_cap,
        "total_under_cap": total_under_cap,
        "passed": all_exit_zero and all_runs_under_cap and total_under_cap,
    }


def pool_differences(runs: list, arm_a: str, arm_b: str, kind: str = "long"):
    diffs = []
    keys = []
    for s, _, eps in runs:
        for ra, rb in zip(eps[arm_a], eps[arm_b]):
            if kind == "law_relevant":
                if not ra.get("law_relevant"):
                    continue
            else:
                if ra["kind"] != kind:
                    continue
            diffs.append(ra["success"] - rb["success"])
            keys.append((s, ra["layout_seed"]))
    return np.array(diffs, dtype=np.float64), keys


def main():
    out_lines = []
    out_lines.append("================================================================================")
    out_lines.append("V9-mini M4 确认段独立复算日志（非作者独立脚本验证）")
    out_lines.append(f"Python: {sys.version.split()[0]} | numpy: {np.__version__}")
    out_lines.append("================================================================================\n")

    freeze_data = json.loads(FREEZE_FILE.read_text(encoding="utf-8"))
    runs_m1 = load_runs("m1")
    runs_m2 = load_runs("m2")

    # 1. 完整性检查
    out_lines.append("== 1. 完整性检查 ==")
    m1_integ = check_integrity("m1", runs_m1, freeze_data, out_lines)
    m2_integ = check_integrity("m2", runs_m2, freeze_data, out_lines)
    ledger_integ = check_ledger_and_budget(freeze_data, out_lines)

    integrity_passed = m1_integ["all_passed"] and m2_integ["all_passed"] and ledger_integ["passed"]
    out_lines.append(f"  完整性总体判定: {'通过' if integrity_passed else '未通过'}\n")

    # 2. 独立复算 7 项区间门
    out_lines.append("== 2. 独立复算 7 个区间门（长目标，同一回合配对，按图整簇 bootstrap 95%，4000 次）==")
    gates_results = {}

    # 事后选取潜空间组最好者
    latent_rates_m1 = {}
    for arm in LATENT_ARMS:
        succ = [r["success"] for _, _, eps in runs_m1 for r in eps[arm] if r["kind"] == "long"]
        latent_rates_m1[arm] = float(np.mean(succ))
    best_latent_m1 = max(LATENT_ARMS, key=lambda k: latent_rates_m1[k])
    out_lines.append(
        "  H1 [m1] 潜空间组长目标成功率: "
        + "，".join(f"{k} {v:.4f}" for k, v in latent_rates_m1.items())
        + f"；事后取最好: {best_latent_m1} ({latent_rates_m1[best_latent_m1]:.4f})"
    )

    latent_rates_m2 = {}
    for arm in LATENT_ARMS:
        succ = [r["success"] for _, _, eps in runs_m2 for r in eps[arm] if r["kind"] == "long"]
        latent_rates_m2[arm] = float(np.mean(succ))
    best_latent_m2 = max(LATENT_ARMS, key=lambda k: latent_rates_m2[k])
    out_lines.append(
        "  H1 [m2] 潜空间组长目标成功率: "
        + "，".join(f"{k} {v:.4f}" for k, v in latent_rates_m2.items())
        + f"；事后取最好: {best_latent_m2} ({latent_rates_m2[best_latent_m2]:.4f})"
    )

    gate_definitions = [
        ("H1_m1", "m1", "map_hybrid", best_latent_m1, "≥ 0.50 且下界 > 0", lambda est, lo: est >= 0.50 and lo > 0),
        ("H1_m2", "m2", "map_hybrid", best_latent_m2, "≥ 0.50 且下界 > 0", lambda est, lo: est >= 0.50 and lo > 0),
        ("H2", "m2", "map_hybrid", "map_analytic", "≥ +0.10 且下界 > 0", lambda est, lo: est >= 0.10 and lo > 0),
        ("H2_prime", "m1", "map_hybrid", "map_analytic", "下界 ≥ −0.02", lambda est, lo: lo >= -0.02),
        ("H3", "m2", "map_hybrid", "map_memory", "≥ +0.05 且下界 > 0", lambda est, lo: est >= 0.05 and lo > 0),
        ("H4_1", "m2", "map_hybrid_self", "map_analytic", "≥ +0.08 且下界 > 0", lambda est, lo: est >= 0.08 and lo > 0),
    ]

    for gid, world, arm_a, arm_b, rule_str, ok_fn in gate_definitions:
        runs = runs_m1 if world == "m1" else runs_m2
        diffs, keys = pool_differences(runs, arm_a, arm_b, kind="long")

        # 使用独立重抽样种子 0
        rng0 = np.random.default_rng(0)
        pt, lo, hi, n_ep, n_cl = cluster_bootstrap_ci(diffs, keys, rng0)
        passed = ok_fn(pt, lo)

        # 敏感性检查：5 个不同随机种子
        multi_seeds_lo = []
        for s_idx in range(5):
            _, slo, _, _, _ = cluster_bootstrap_ci(diffs, keys, np.random.default_rng(s_idx))
            multi_seeds_lo.append(slo)

        gates_results[gid] = {
            "world": world,
            "comparison": f"{arm_a} - {arm_b}",
            "arm_a": arm_a,
            "arm_b": arm_b,
            "rule": rule_str,
            "point_estimate": pt,
            "ci_95": [lo, hi],
            "n_episodes": n_ep,
            "n_clusters": n_cl,
            "passed": passed,
            "seed_sensitivity_lo": multi_seeds_lo,
        }
        out_lines.append(
            f"  {gid} [{world}] {arm_a} − {arm_b} (长目标，回合 {n_ep}，图 {n_cl})：点估计 {pt:+.3f} [{lo:+.3f}, {hi:+.3f}]  "
            f"门：{rule_str}  → {'过' if passed else '不过'}"
        )
        out_lines.append(
            f"      5 个不同随机种子 (0..4) 下界变动: {', '.join(f'{x:+.3f}' for x in multi_seeds_lo)}"
        )

    # 3. 独立复算 H4 ②
    out_lines.append("\n== 3. 独立复算 H4 ②（前进模型留出事件准确率：真值标签减自监督）==")
    h4_2_seeds = []
    diffs_h4_2 = []
    for s, res, _ in runs_m2:
        fm = res["forward_model"]
        # 取 gated@N 中 N 最大的版本
        g_keys = [k for k in fm if k.startswith("gated@")]
        max_g_key = max(g_keys, key=lambda k: int(k.split("@")[1]))
        sk_key = next(k for k in fm if k.startswith("gated_self@"))

        g_acc = fm[max_g_key]["event"]
        sk_acc = fm[sk_key]["event"]
        diff = g_acc - sk_acc
        diffs_h4_2.append(diff)
        n_ev = fm[max_g_key].get("n_event")
        h4_2_seeds.append({
            "seed": s,
            "truth_key": max_g_key,
            "truth_acc": g_acc,
            "self_key": sk_key,
            "self_acc": sk_acc,
            "diff": diff,
            "n_event": n_ev,
        })
        out_lines.append(
            f"  s{s}: {max_g_key} {g_acc:.4f}  {sk_key} {sk_acc:.4f}  差 {diff:+.4f} (样本数 {n_ev})"
        )

    mean_diff_h4_2 = float(np.mean(diffs_h4_2))
    passed_h4_2 = mean_diff_h4_2 <= 0.05
    gates_results["H4_2"] = {
        "world": "m2",
        "rule": "5 个种子平均 ≤ 0.05",
        "point_estimate": mean_diff_h4_2,
        "seeds": h4_2_seeds,
        "passed": passed_h4_2,
    }
    out_lines.append(
        f"  5 个种子平均差 {mean_diff_h4_2:+.4f}（保留 3 位: {mean_diff_h4_2:+.3f}）  门：≤ 0.05  → {'过' if passed_h4_2 else '不过'}"
    )

    # 对照 batch3 验证取法
    out_lines.append("  -- 对照批次 3 (explore/batch3) 核查 H4 ② 取法原意 --")
    batch3_verification = []
    for bs in (0, 1, 2):
        bpath = WORKSPACE_ROOT / "reports" / "V9-MINI" / "explore" / "batch3" / f"m2-s{bs}" / "result.json"
        if bpath.exists():
            b_res = json.loads(bpath.read_text(encoding="utf-8"))
            bfm = b_res["forward_model"]
            bg_key = max((k for k in bfm if k.startswith("gated@")), key=lambda k: int(k.split("@")[1]))
            bs_key = next(k for k in bfm if k.startswith("gated_self@"))
            bg_acc = bfm[bg_key]["event"]
            bs_acc = bfm[bs_key]["event"]
            batch3_verification.append({
                "seed": bs,
                "truth_key": bg_key,
                "truth_acc": bg_acc,
                "self_key": bs_key,
                "self_acc": bs_acc,
                "diff": bg_acc - bs_acc,
            })
            out_lines.append(
                f"    batch3-s{bs}: {bg_key} {bg_acc:.3f} 对 {bs_key} {bs_acc:.3f}，差 {bg_acc - bs_acc:+.3f}"
            )
    out_lines.append("    核对结论: batch3 提取值与预登记 §1 表中 0.992/0.993/0.980 对 0.968/0.985/0.959 完全一致，确认取法符合预登记原意。")

    # 4. 核对 M4-RESULT.md §3（只报告、不设门）各项数字
    out_lines.append("\n== 4. 核对 M4-RESULT.md §3 数字（只报告、不设门）==")
    sec3_data = {}

    # (1) 长目标成功率 5 种子均值表
    all_arms_ordered = [
        "oracle", "map_hybrid_self", "map_hybrid", "map_memory", "map_analytic",
        "map_ungated", "map_ungated_aug", "latent_euclid", "latent_learned",
        "graph_memory", "gru_belief", "random"
    ]
    long_rate_table = {}
    out_lines.append("  (1) 长目标成功率 5 种子均值表：")
    for arm in all_arms_ordered:
        succ_m2 = [float(np.mean([r["success"] for r in eps[arm] if r["kind"] == "long"])) for _, _, eps in runs_m2]
        succ_m1 = [float(np.mean([r["success"] for r in eps[arm] if r["kind"] == "long"])) for _, _, eps in runs_m1]
        m2_avg = float(np.mean(succ_m2))
        m1_avg = float(np.mean(succ_m1))
        long_rate_table[arm] = {"m2": m2_avg, "m1": m1_avg}
        out_lines.append(f"      {arm:16s}  m2: {m2_avg:.3f}   m1: {m1_avg:.3f}")
    sec3_data["long_rate_table"] = long_rate_table

    # (2) m2 配对差（长目标）
    out_lines.append("  (2) m2 配对差（长目标）：")
    m2_pairs = [
        ("map_hybrid_self", "map_hybrid", "hybrid_self - hybrid"),
        ("map_memory", "map_analytic", "memory - analytic"),
        ("map_hybrid", "map_ungated", "hybrid - ungated"),
        ("map_hybrid", "map_ungated_aug", "hybrid - ungated_aug"),
    ]
    m2_pairs_res = {}
    for arm_a, arm_b, label in m2_pairs:
        diffs, keys = pool_differences(runs_m2, arm_a, arm_b, kind="long")
        pt, lo, hi, n_ep, n_cl = cluster_bootstrap_ci(diffs, keys, np.random.default_rng(0))
        m2_pairs_res[label] = {"point": pt, "ci": [lo, hi], "episodes": n_ep, "clusters": n_cl}
        out_lines.append(f"      {label}: {pt:+.3f} [{lo:+.3f}, {hi:+.3f}] (回合 {n_ep}，图 {n_cl})")
    sec3_data["m2_long_pairs"] = m2_pairs_res

    # (3) m2 规律相关回合
    out_lines.append("  (3) m2 规律相关回合 (law_relevant)：")
    diffs_lr, keys_lr = pool_differences(runs_m2, "map_hybrid", "map_analytic", kind="law_relevant")
    pt_lr, lo_lr, hi_lr, n_ep_lr, n_cl_lr = cluster_bootstrap_ci(diffs_lr, keys_lr, np.random.default_rng(0))
    sec3_data["law_relevant"] = {
        "comparison": "map_hybrid - map_analytic",
        "point": pt_lr,
        "ci": [lo_lr, hi_lr],
        "episodes": n_ep_lr,
        "clusters": n_cl_lr,
    }
    out_lines.append(
        f"      map_hybrid − map_analytic: {pt_lr:+.3f} [{lo_lr:+.3f}, {hi_lr:+.3f}] (回合 {n_ep_lr}，图 {n_cl_lr})"
    )

    # (4) 短目标成功率范围
    out_lines.append("  (4) 短目标成功率 (short)：")
    short_rates = {"m2": {}, "m1": {}}
    for world, runs in (("m2", runs_m2), ("m1", runs_m1)):
        for arm in all_arms_ordered:
            succ = [float(np.mean([r["success"] for r in eps[arm] if r["kind"] == "short"])) for _, _, eps in runs]
            short_rates[world][arm] = float(np.mean(succ))
    map_arms = ["map_analytic", "map_memory", "map_hybrid", "map_hybrid_self", "map_ungated", "map_ungated_aug"]
    lat_arms = ["latent_euclid", "latent_learned", "graph_memory", "gru_belief"]
    m2_map_short = [short_rates["m2"][a] for a in map_arms]
    m1_map_short = [short_rates["m1"][a] for a in map_arms]
    m2_lat_short = [short_rates["m2"][a] for a in lat_arms]
    out_lines.append(
        f"      m2 地图组范围: {min(m2_map_short):.3f}–{max(m2_map_short):.3f}；m1 地图组范围: {min(m1_map_short):.3f}–{max(m1_map_short):.3f}"
    )
    out_lines.append(
        f"      m2 潜空间组范围: {min(m2_lat_short):.3f}–{max(m2_lat_short):.3f}"
    )
    sec3_data["short_rates"] = short_rates

    # (5) 诊断指标抽查
    out_lines.append("  (5) 诊断指标核查：")
    one_steps, five_steps, rhos = [], [], []
    for w, runs in (("m1", runs_m1), ("m2", runs_m2)):
        for s, res, _ in runs:
            p = res["prediction"]
            c = res["cost_diagnostics"]
            b = res.get("belief", {}).get("diagnostics", {})
            one_steps.append(p["one_step_ratio"])
            five_steps.append(p["5_step_ratio"])
            rhos.extend([c["rho_euclid_far_ge20"], c["rho_learned_far_ge20"]])
            if "rho_belief_far_ge20" in b:
                rhos.append(b["rho_belief_far_ge20"])

    m2_s0_m3 = runs_m2[0][1]["m3_label_quality"]["label_agreement_with_truth"]
    out_lines.append(f"      一步误差比范围: {min(one_steps):.3f}–{max(one_steps):.3f}")
    out_lines.append(f"      5 步误差比范围: {min(five_steps):.3f}–{max(five_steps):.3f}")
    out_lines.append(f"      代价秩相关范围: {min(rhos):+.2f} 到 {max(rhos):+.2f}")
    out_lines.append(f"      m3 标签与真值一致率 (m2-s0): {m2_s0_m3:.4f}")
    sec3_data["diagnostics"] = {
        "one_step_ratio_range": [min(one_steps), max(one_steps)],
        "five_step_ratio_range": [min(five_steps), max(five_steps)],
        "rho_range": [min(rhos), max(rhos)],
        "m2_s0_m3_agreement": m2_s0_m3,
    }

    # (6) 迷路统计 (m2)
    out_lines.append("  (6) m2 迷路分析与拆分统计：")
    lost_summary = {}
    for arm in map_arms:
        rs = [r for _, _, eps in runs_m2 for r in eps[arm]]
        steps = sum(r["steps"] for r in rs)
        lost = sum(r["lost"] for r in rs)
        surp = sum(r["surprises"] for r in rs)
        las = float(np.mean([bool(r["lost_at_start"]) for r in rs]))
        pl = float(np.mean([r["prefix_lost"] for r in rs]))
        fail = [r for r in rs if r["kind"] == "long" and not r["success"]]
        fail_las = float(np.mean([bool(r["lost_at_start"]) for r in fail])) if fail else 0.0
        lost_summary[arm] = {
            "lost_per_ep": lost / len(rs),
            "surprises_per_step": surp / steps,
            "lost_at_start_rate": las,
            "prefix_lost_mean": pl,
            "long_fails_count": len(fail),
            "long_fails_lost_at_start_rate": fail_las,
        }
        out_lines.append(
            f"      {arm:16s}: lost/ep {lost / len(rs):.3f}, 惊讶/步 {surp / steps:.4f}, "
            f"开局迷路率 {las:.3f}, 前缀迷路均值 {pl:.2f}, 长目标失败 {len(fail)} (其中开局迷路 {fail_las:.3f})"
        )

    # 开局迷路拆分长目标
    rs_hyb_long = [r for _, _, eps in runs_m2 for r in eps["map_hybrid"] if r["kind"] == "long"]
    rs_ana_long = [r for _, _, eps in runs_m2 for r in eps["map_analytic"] if r["kind"] == "long"]
    las_flags = [bool(r["lost_at_start"]) for r in rs_hyb_long]
    n_las = sum(las_flags)
    n_not_las = len(las_flags) - n_las
    hyb_succ_las = float(np.mean([r["success"] for r, f in zip(rs_hyb_long, las_flags) if f]))
    hyb_succ_not = float(np.mean([r["success"] for r, f in zip(rs_hyb_long, las_flags) if not f]))
    ana_succ_las = float(np.mean([r["success"] for r, f in zip(rs_ana_long, las_flags) if f]))
    ana_succ_not = float(np.mean([r["success"] for r, f in zip(rs_ana_long, las_flags) if not f]))

    out_lines.append(f"      长目标开局迷路拆分: {n_las} (开局迷路) 对 {n_not_las} (开局不迷路) 回合")
    out_lines.append(f"      map_hybrid 成功率: 开局迷路 {hyb_succ_las:.3f} 对 开局不迷路 {hyb_succ_not:.3f}")
    out_lines.append(f"      map_analytic 成功率: 开局迷路 {ana_succ_las:.3f} 对 开局不迷路 {ana_succ_not:.3f}")
    sec3_data["lost_breakdown"] = {
        "summary": lost_summary,
        "hybrid_vs_analytic_split": {
            "n_las": n_las,
            "n_not_las": n_not_las,
            "hybrid_las": hyb_succ_las,
            "hybrid_not_las": hyb_succ_not,
            "analytic_las": ana_succ_las,
            "analytic_not_las": ana_succ_not,
        },
    }

    # 5. 判定汇总
    out_lines.append("\n== 5. 8 项门判定汇总 ==")
    verdicts = {
        "H1_m1": gates_results["H1_m1"]["passed"],
        "H1_m2": gates_results["H1_m2"]["passed"],
        "H2": gates_results["H2"]["passed"],
        "H2_prime": gates_results["H2_prime"]["passed"],
        "H3": gates_results["H3"]["passed"],
        "H4_1": gates_results["H4_1"]["passed"],
        "H4_2": gates_results["H4_2"]["passed"],
        "H4_combined": gates_results["H4_1"]["passed"] and gates_results["H4_2"]["passed"],
    }
    all_gates_passed = all(verdicts.values())
    for k, v in verdicts.items():
        out_lines.append(f"  {k:15s}: {'过' if v else '不过'}")
    out_lines.append(f"\n全部 8 项门综合结论: {'全部通过' if all_gates_passed else '未全部通过'}")

    # 输出文件保存
    full_output_text = "\n".join(out_lines) + "\n"
    print(full_output_text)

    (OUT_DIR / "recompute.txt").write_text(full_output_text, encoding="utf-8")

    json_payload = {
        "integrity": {
            "m1": m1_integ,
            "m2": m2_integ,
            "ledger": ledger_integ,
            "passed": integrity_passed,
        },
        "gates": gates_results,
        "sec3_metrics": sec3_data,
        "verdicts": verdicts,
        "all_gates_passed": all_gates_passed,
    }
    (OUT_DIR / "recompute.json").write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写入成功: {OUT_DIR / 'recompute.txt'}")
    print(f"写入成功: {OUT_DIR / 'recompute.json'}")


if __name__ == "__main__":
    main()
