import json, random, sys, time
from pathlib import Path
import numpy as np
from ainerzero.v9.experiments.s2 import adapters_mlx, eval_runner, world, spec
OUT = Path("artifacts/v9/s2/phase1"); TRAIN = OUT / "datasets/train"; LEDGER = Path("/private/tmp/claude-501/-Users-mac-AinerWorkFlow-AinerZero/9ceafe9f-ae1e-4da6-a85d-2438a4c80c0b/scratchpad/ledgercheck/JwsC/control.sqlite3")
pc = json.load(open(OUT / "plan_config.json"))
hold = json.load(open(TRAIN / "HOLDOUT_WORLDS.json"))["holdout_worlds"][:10]
def specs_for(kind, n_per_world):
    out = []
    for w in hold:
        lay = json.load(open(TRAIN / f"world_{int(w):04d}" / "layout.json"))
        L = world.Layout(seed=int(lay["seed"]), terrain=[list(r) for r in lay["terrain"]], rooms=[tuple(r) for r in lay["rooms"]], doors=[tuple(x) for x in lay["doors"]], pillars=[tuple(p) for p in lay["pillars"]], layout_sha256=str(lay["layout_sha256"]))
        rng = random.Random(1000 + int(w))
        for k in range(n_per_world):
            s, g, go, st = world.sample_start_goal_pair(L, rng, kind=kind)
            out.append({"episode_index": len(out), "world_index": int(w), "kind": kind, "start": world.truth(s), "goal": world.truth(g), "bfs_distance": int(st["bfs_distance"]), "partition": "train", "layout": lay})
    return out
short = specs_for("short", 2)
print("short specs", len(short), "bfs", sorted(s["bfs_distance"] for s in short))
for arm in ("arm_a", "arm_b", "arm_c"):
    m = adapters_mlx.load_trained_model(OUT, arm, 42, ledger_path=LEDGER)
    cfg = pc["arms"][arm]["plan_choice"]
    t = time.time()
    sr = eval_runner._score_config_on_train(m, cfg, short, n_fwd=int(spec.N_FWD), dataset_dir=TRAIN)
    print(arm, "plan_choice", cfg, "short-goal success", round(sr, 3), "secs", round(time.time() - t, 1))
