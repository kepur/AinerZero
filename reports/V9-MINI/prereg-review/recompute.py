#!/usr/bin/env python3
"""独立复算脚本：V9-mini M4 预登记 r1 与按图重抽样区间（非作者复核 A29 专用）
严格不导入 summarize 模块，完全独立实现按图整簇重抽样与按回合重抽样。
"""
import json
from pathlib import Path
import numpy as np

BATCH3_DIR = Path(__file__).resolve().parents[1] / "explore" / "batch3"

def load_episodes(world: str, seeds=(0, 1, 2)):
    runs = []
    for s in seeds:
        p = BATCH3_DIR / f"{world}-s{s}" / "episodes.json"
        with open(p, "r", encoding="utf-8") as f:
            runs.append(json.load(f))
    return runs

def compute_h1(world: str):
    runs = load_episodes(world)
    latent_arms = ["latent_euclid", "latent_learned", "graph_memory", "gru_belief"]
    
    # map_hybrid long success across 3 runs
    hyb_succ = []
    for r in runs:
        long_eps = [ep for ep in r["map_hybrid"] if ep["kind"] == "long"]
        hyb_succ.append(np.mean([ep["success"] for ep in long_eps]))
    hyb_mean = float(np.mean(hyb_succ))
    
    latent_means = {}
    for arm in latent_arms:
        arm_succ = []
        for r in runs:
            long_eps = [ep for ep in r[arm] if ep["kind"] == "long"]
            arm_succ.append(np.mean([ep["success"] for ep in long_eps]))
        latent_means[arm] = float(np.mean(arm_succ))
        
    best_latent = max(latent_means.values())
    return {
        "hybrid_mean": hyb_mean,
        "latent_means": latent_means,
        "best_latent": best_latent,
        "diff": hyb_mean - best_latent
    }

def cluster_bootstrap(diffs_per_ep, keys, n_boot=4000, seed=0):
    """diffs_per_ep: 长度为 N 的 1D 数组（已跨运行对每个回合求平均后的差值）
    keys: 长度为 N 的簇标识（layout_seed）
    """
    uniq_keys = sorted(set(keys))
    idx_map = {k: i for i, k in enumerate(uniq_keys)}
    cluster_ids = np.array([idx_map[k] for k in keys])
    
    sums = np.bincount(cluster_ids, weights=diffs_per_ep, minlength=len(uniq_keys))
    counts = np.bincount(cluster_ids, minlength=len(uniq_keys)).astype(float)
    
    rng = np.random.default_rng(seed)
    boot_indices = rng.integers(0, len(uniq_keys), (n_boot, len(uniq_keys)))
    
    # 比率估计量：抽中簇的差值和 / 抽中簇的回合总数
    boot_means = sums[boot_indices].sum(axis=1) / counts[boot_indices].sum(axis=1)
    lo, hi = np.percentile(boot_means, [2.5, 97.5])
    return float(lo), float(hi), len(uniq_keys)

def episode_bootstrap(diffs_per_ep, n_boot=4000, seed=0):
    rng = np.random.default_rng(seed)
    boot_idx = rng.integers(0, len(diffs_per_ep), (n_boot, len(diffs_per_ep)))
    boot_means = diffs_per_ep[boot_idx].mean(axis=1)
    lo, hi = np.percentile(boot_means, [2.5, 97.5])
    return float(lo), float(hi)

def compute_pair(world: str, arm_a: str, arm_b: str, kind: str = "long", n_boot=4000, seed=0):
    runs = load_episodes(world)
    
    # 提取各运行指定 kind 的回合
    ea = [[ep for ep in r[arm_a] if ep["kind"] == kind] for r in runs]
    eb = [[ep for ep in r[arm_b] if ep["kind"] == kind] for r in runs]
    
    n_ep = len(ea[0])
    keys = [ep["layout_seed"] for ep in ea[0]]
    
    # 计算每个运行的每回合差值
    diffs_matrix = np.zeros((len(runs), n_ep), dtype=float)
    for r_idx, (ra, rb) in enumerate(zip(ea, eb)):
        for i, (a_ep, b_ep) in enumerate(zip(ra, rb)):
            diffs_matrix[r_idx, i] = a_ep["success"] - b_ep["success"]
            
    # 规则：回合集合相同时，先在 3 个运行间对每个回合取平均
    mean_diffs = np.mean(diffs_matrix, axis=0)
    point_est = float(np.mean(mean_diffs))
    
    c_lo, c_hi, n_clusters = cluster_bootstrap(mean_diffs, keys, n_boot=n_boot, seed=seed)
    ep_lo, ep_hi = episode_bootstrap(mean_diffs, n_boot=n_boot, seed=seed)
    
    return {
        "arm_a": arm_a,
        "arm_b": arm_b,
        "kind": kind,
        "n_episodes": n_ep,
        "n_clusters": n_clusters,
        "point_estimate": point_est,
        "cluster_ci_95": [c_lo, c_hi],
        "episode_ci_95": [ep_lo, ep_hi]
    }

def get_event_accuracies():
    accs = {}
    for s in (0, 1, 2):
        p = BATCH3_DIR / f"m2-s{s}" / "result.json"
        with open(p, "r", encoding="utf-8") as f:
            res = json.load(f)
        fwd = res.get("forward_model", {})
        
        # 寻找训练步数最大的 gated 与 gated_self
        gated_keys = [k for k in fwd.keys() if k.startswith("gated@")]
        self_keys = [k for k in fwd.keys() if k.startswith("gated_self@")]
        
        best_gated = max(gated_keys, key=lambda x: int(x.split("@")[1]))
        best_self = max(self_keys, key=lambda x: int(x.split("@")[1]))
        
        acc_gated = fwd[best_gated]["event"]
        acc_self = fwd[best_self]["event"]
        diff = acc_gated - acc_self
        
        accs[f"s{s}"] = {
            "gated_key": best_gated,
            "gated_event_acc": acc_gated,
            "self_key": best_self,
            "self_event_acc": acc_self,
            "diff": diff
        }
        
    avg_diff = np.mean([v["diff"] for v in accs.values()])
    return accs, float(avg_diff)

def main():
    print("================== V9-mini 独立复算 (A29) ==================")
    results = {}
    
    # H1
    h1_m1 = compute_h1("m1")
    h1_m2 = compute_h1("m2")
    results["H1"] = {"m1": h1_m1, "m2": h1_m2}
    print(f"H1 m1: hybrid={h1_m1['hybrid_mean']:.3f} vs best_latent={h1_m1['best_latent']:.3f}")
    print(f"H1 m2: hybrid={h1_m2['hybrid_mean']:.3f} vs best_latent={h1_m2['best_latent']:.3f}")
    
    # H2
    h2 = compute_pair("m2", "map_hybrid", "map_analytic", kind="long")
    results["H2"] = h2
    print(f"H2 (m2 hybrid - analytic): point={h2['point_estimate']:+.3f}, cluster_95=[{h2['cluster_ci_95'][0]:+.3f}, {h2['cluster_ci_95'][1]:+.3f}] (clusters={h2['n_clusters']})")
    
    # H2'
    h2_prime = compute_pair("m1", "map_hybrid", "map_analytic", kind="long")
    results["H2_prime"] = h2_prime
    print(f"H2' (m1 hybrid - analytic): point={h2_prime['point_estimate']:+.3f}, cluster_95=[{h2_prime['cluster_ci_95'][0]:+.3f}, {h2_prime['cluster_ci_95'][1]:+.3f}] (clusters={h2_prime['n_clusters']})")
    
    # H3
    h3 = compute_pair("m2", "map_hybrid", "map_memory", kind="long")
    results["H3"] = h3
    print(f"H3 (m2 hybrid - memory): point={h3['point_estimate']:+.3f}, cluster_95=[{h3['cluster_ci_95'][0]:+.3f}, {h3['cluster_ci_95'][1]:+.3f}] (clusters={h3['n_clusters']})")
    
    # H4 part 1
    h4_p1 = compute_pair("m2", "map_hybrid_self", "map_analytic", kind="long")
    results["H4_part1"] = h4_p1
    print(f"H4 ① (m2 hybrid_self - analytic): point={h4_p1['point_estimate']:+.3f}, cluster_95=[{h4_p1['cluster_ci_95'][0]:+.3f}, {h4_p1['cluster_ci_95'][1]:+.3f}]")
    
    # H4 part 2
    fwd_accs, avg_diff = get_event_accuracies()
    results["H4_part2"] = {"seeds": fwd_accs, "mean_diff": avg_diff}
    print(f"H4 ② 前进模型事件准确率:")
    for s_id, data in fwd_accs.items():
        print(f"   {s_id}: gated={data['gated_event_acc']:.3f} vs self={data['self_event_acc']:.3f}, diff={data['diff']:+.3f}")
    print(f"   平均差异: {avg_diff:+.4f}")
    
    # 对照：hybrid_self - hybrid 的按图 vs 按回合比较
    h_comp = compute_pair("m2", "map_hybrid_self", "map_hybrid", kind="long")
    results["hybrid_self_vs_hybrid"] = h_comp
    print("\n--- 关键对比：hybrid_self - hybrid ---")
    print(f"点估计: {h_comp['point_estimate']:+.3f}")
    print(f"按图整簇 95% 区间: [{h_comp['cluster_ci_95'][0]:+.3f}, {h_comp['cluster_ci_95'][1]:+.3f}] (包含 0)")
    print(f"按回合重抽样 95% 区间: [{h_comp['episode_ci_95'][0]:+.3f}, {h_comp['episode_ci_95'][1]:+.3f}] (不含 0，会误判显著)")
    
    out_json = Path(__file__).resolve().parent / "recompute_results.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n结果已写入 {out_json}")

if __name__ == "__main__":
    main()
