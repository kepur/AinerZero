import json
from pathlib import Path
import numpy as np

LATENT = ("latent_euclid", "latent_learned", "graph_memory", "gru_belief", "latent_topo", "latent_attn")

def run_scale_check():
    ROOT = Path(__file__).resolve().parents[4]
    p_scale = ROOT / "reports/V9-MINI/explore/scale80-m5"
    
    # Run judge_m5
    import sys
    sys.path.insert(0, str(ROOT / "reports/V9-MINI/M5"))
    import judge_m5
    
    for w in ("m1", "m2"):
        p = p_scale / f"{w}-s0"
        eps = json.loads((p / "episodes.json").read_text())
        
        # Self implementation:
        long_eps = [r for r in eps["oracle"] if r["kind"] == "long"]
        n_long = len(long_eps)
        clusters = sorted(set(r["layout_seed"] for r in long_eps))
        n_clusters = len(clusters)
        
        arm_succ = {}
        for arm in eps:
            longs = [r["success"] for r in eps[arm] if r["kind"] == "long"]
            arm_succ[arm] = float(np.mean(longs))
            
        best_latent = max(LATENT, key=lambda a: (arm_succ[a], a))
        diff = arm_succ["map_hybrid_self"] - arm_succ[best_latent]
        
        # Compare with judge_m5
        j_res = judge_m5.judge([p], np.random.default_rng(0))
        
        print(f"=== {w}-s0 scale check ===")
        print(f"Self: n_long={n_long}, n_clusters={n_clusters}, best={best_latent}, map_hybrid_self={arm_succ['map_hybrid_self']:.4f}, diff={diff:.6f}")
        print(f"Judge: n_long={j_res['n_long']}, n_clusters={j_res['n_clusters']}, best={j_res['best_latent']}, diff={j_res['H1s']['diff']:.6f}, lo={j_res['H1s']['lo']:.4f}, pass={j_res['H1s']['pass']}")
        
        assert n_long == j_res["n_long"]
        assert n_clusters == j_res["n_clusters"]
        assert best_latent == j_res["best_latent"]
        assert abs(diff - j_res["H1s"]["diff"]) < 1e-9
        for arm in eps:
            assert abs(arm_succ[arm] - j_res["long_success"][arm]) < 1e-9
        print(f"{w}-s0 verified perfectly!")

if __name__ == "__main__":
    run_scale_check()
