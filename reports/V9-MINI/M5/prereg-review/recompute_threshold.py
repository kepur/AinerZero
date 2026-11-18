import json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
EX = ROOT / "reports/V9-MINI/explore"
LATENT_ARMS = ("latent_euclid", "latent_learned", "graph_memory", "gru_belief", "latent_topo", "latent_attn")

def run():
    rng = np.random.default_rng(0)
    results = {}
    for w in ("m1", "m2"):
        runs = []
        for s in range(3):
            p_topo = EX / "topo-batch" / f"{w}-s{s}" / "episodes.json"
            p_b3 = EX / "batch3" / f"{w}-s{s}" / "episodes.json"
            p_attn = EX / "attn/batch" / f"{w}-s{s}" / "episodes.json"
            
            e_topo = json.loads(p_topo.read_text())
            e_b3 = json.loads(p_b3.read_text())
            e_attn = json.loads(p_attn.read_text())
            
            # verify episode tasks match exactly
            sig_topo = [(r["layout_seed"], r["kind"], r["d_star"]) for r in e_topo["oracle"]]
            sig_b3 = [(r["layout_seed"], r["kind"], r["d_star"]) for r in e_b3["map_hybrid_self"]]
            sig_attn = [(r["layout_seed"], r["kind"], r["d_star"]) for r in e_attn["latent_attn"]]
            
            assert sig_topo == sig_b3, f"Mismatch topo vs batch3 for {w}-s{s}"
            assert sig_topo == sig_attn, f"Mismatch topo vs attn for {w}-s{s}"
            
            merged = {}
            for k in e_topo:
                merged[k] = e_topo[k]
            merged["map_hybrid_self"] = e_b3["map_hybrid_self"]
            merged["latent_attn"] = e_attn["latent_attn"]
            runs.append(merged)
        
        # Verify across seeds that tasks are identical
        tasks_s0 = [(r["layout_seed"], r["kind"], r["d_star"]) for r in runs[0]["oracle"]]
        for s in (1, 2):
            tasks_s = [(r["layout_seed"], r["kind"], r["d_star"]) for r in runs[s]["oracle"]]
            assert tasks_s0 == tasks_s, f"Mismatch across seeds for {w}"
            
        long_indices = [i for i, r in enumerate(runs[0]["oracle"]) if r["kind"] == "long"]
        layout_seeds = [runs[0]["oracle"][i]["layout_seed"] for i in long_indices]
        uniq_layouts = sorted(set(layout_seeds))
        n_clusters = len(uniq_layouts)
        
        # Calculate long success rate for each arm
        arm_succ = {}
        for arm in list(runs[0].keys()):
            # array of shape (3, len(long_indices))
            arr = np.array([[runs[s][arm][i]["success"] for i in long_indices] for s in range(3)], dtype=float)
            arm_succ[arm] = arr
            
        mean_by_arm = {arm: float(np.mean(arm_succ[arm])) for arm in arm_succ}
        
        # Best latent arm:
        # Check success rates of all latent arms
        latent_scores = {arm: mean_by_arm[arm] for arm in LATENT_ARMS}
        # In case of tie, note ties
        max_score = max(latent_scores.values())
        best_latent = max(LATENT_ARMS, key=lambda a: (latent_scores[a], a))
        
        # Diff: map_hybrid_self - best_latent
        # Same task sequence across seeds:
        # First average across 3 seeds per episode:
        mhs_ep = np.mean(arm_succ["map_hybrid_self"], axis=0) # shape (n_long,)
        best_ep = np.mean(arm_succ[best_latent], axis=0)
        diff_ep = mhs_ep - best_ep
        point_est = float(np.mean(diff_ep))
        
        # Cluster bootstrap: cluster by layout_seed
        # Each unique layout_seed is a cluster.
        layout_to_idx = {l: i for i, l in enumerate(uniq_layouts)}
        g = np.array([layout_to_idx[l] for l in layout_seeds])
        
        # Count diff sum and episode count per cluster
        sum_diff = np.bincount(g, weights=diff_ep, minlength=n_clusters)
        count_per_cluster = np.bincount(g, minlength=n_clusters).astype(float)
        
        # Bootstrap 4000
        boot_idx = rng.integers(0, n_clusters, (4000, n_clusters))
        boot_means = sum_diff[boot_idx].sum(axis=1) / count_per_cluster[boot_idx].sum(axis=1)
        ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])
        
        results[w] = {
            "n_long_episodes": len(long_indices),
            "n_clusters": n_clusters,
            "latent_scores": latent_scores,
            "best_latent": best_latent,
            "map_hybrid_self_long": mean_by_arm["map_hybrid_self"],
            "best_latent_long": mean_by_arm[best_latent],
            "diff_point_est": point_est,
            "ci_95": [float(ci_lo), float(ci_hi)],
            "gate_0_50_pass": bool(point_est >= 0.50 and ci_lo > 0)
        }
        
    print(json.dumps(results, indent=2))
    return results

if __name__ == "__main__":
    run()
