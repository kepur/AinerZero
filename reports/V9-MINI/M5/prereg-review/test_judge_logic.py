import json
import tempfile
from pathlib import Path
import numpy as np

# 1. Synthetic test: 2 runs, 3 maps per run
# Run 0: maps 10, 20, 30. Each map has 2 long episodes.
# Run 1: maps 40, 50, 60. Each map has 1 long episode.
# Total 6 clusters: (0, 10), (0, 20), (0, 30), (1, 40), (1, 50), (1, 60).
# Total long episodes: 2*3 + 1*3 = 9.

def create_mock_run(run_idx, map_seeds, episodes_per_map, arm_success_map):
    # arm_success_map: {arm: [success for each episode]}
    episodes = {arm: [] for arm in arm_success_map}
    episodes["oracle"] = []
    
    ep_idx = 0
    for m in map_seeds:
        for _ in range(episodes_per_map):
            for arm in arm_success_map:
                episodes[arm].append({
                    "layout_seed": m,
                    "kind": "long",
                    "d_star": 20,
                    "steps": 25,
                    "success": arm_success_map[arm][ep_idx]
                })
            episodes["oracle"].append({
                "layout_seed": m,
                "kind": "long",
                "d_star": 20,
                "steps": 20,
                "success": 1.0
            })
            ep_idx += 1
    return episodes

# Let's define arms and successes
arms = ["random", "latent_euclid", "latent_learned", "graph_memory", "gru_belief", "latent_topo", "latent_attn",
        "map_analytic", "map_hybrid", "map_hybrid_self", "topo_oracle_ctrl"]

# Run 0 (6 episodes):
# map_hybrid_self: [1, 1, 1, 0, 1, 1] -> mean 5/6
# latent_topo:     [0, 1, 0, 0, 0, 0] -> mean 1/6
# latent_attn:     [0, 0, 0, 0, 0, 0] -> mean 0
# other latents:   all 0
r0_success = {a: [0]*6 for a in arms}
r0_success["map_hybrid_self"] = [1, 1, 1, 0, 1, 1]
r0_success["map_hybrid"] = [1, 1, 1, 1, 1, 1]
r0_success["latent_topo"] = [0, 1, 0, 0, 0, 0]

# Run 1 (3 episodes):
# map_hybrid_self: [1, 0, 1] -> mean 2/3
# latent_topo:     [0, 0, 0] -> mean 0
# latent_attn:     [1, 0, 0] -> mean 1/3
r1_success = {a: [0]*3 for a in arms}
r1_success["map_hybrid_self"] = [1, 0, 1]
r1_success["map_hybrid"] = [1, 1, 1]
r1_success["latent_topo"] = [0, 0, 0]
r1_success["latent_attn"] = [1, 0, 0]

# Overall 9 episodes:
# map_hybrid_self: 5 + 2 = 7 successes out of 9 -> 7/9 = 0.7777777777777778
# latent_topo: 1 + 0 = 1 out of 9 -> 1/9 = 0.1111111111111111
# latent_attn: 0 + 1 = 1 out of 9 -> 1/9 = 0.1111111111111111
# other latents: 0 out of 9
# In case of tie between latent_topo and latent_attn:
# latent_topo ("l-a-t-e-n-t-_-t...") > latent_attn ("l-a-t-e-n-t-_-a..."), so best_latent should be latent_topo!
# Diff (map_hybrid_self - latent_topo): 7/9 - 1/9 = 6/9 = 2/3 = 0.6666666666666666
# Clusters: (0, 10), (0, 20), (0, 30), (1, 40), (1, 50), (1, 60) -> 6 clusters.

with tempfile.TemporaryDirectory() as td:
    p0 = Path(td) / "run0"
    p1 = Path(td) / "run1"
    p0.mkdir()
    p1.mkdir()
    (p0 / "episodes.json").write_text(json.dumps(create_mock_run(0, [10, 20, 30], 2, r0_success)))
    (p1 / "episodes.json").write_text(json.dumps(create_mock_run(1, [40, 50, 60], 1, r1_success)))
    
    # Import judge from judge_m5
    import sys
    sys.path.insert(0, str(Path("reports/V9-MINI/M5").resolve()))
    import judge_m5
    
    res = judge_m5.judge([p0, p1], np.random.default_rng(0))
    
    print("Synthetic test results:")
    print("n_long:", res["n_long"], "expected: 9")
    print("n_clusters:", res["n_clusters"], "expected: 6")
    print("best_latent:", res["best_latent"], "expected: latent_topo")
    print("diff:", res["H1s"]["diff"], "expected:", 6/9)
    print("gate pass:", res["H1s"]["pass"], "expected: True")
    
    assert res["n_long"] == 9
    assert res["n_clusters"] == 6
    assert res["best_latent"] == "latent_topo"
    assert abs(res["H1s"]["diff"] - 2/3) < 1e-9
    assert res["H1s"]["pass"] == True
    print("Synthetic test PASSED successfully!")
