import json, random
from pathlib import Path
import numpy as np
from ainerzero.v9.experiments.s2 import adapters_mlx, world, learned_planning as lp, train_runner as tr, spec
OUT = Path("artifacts/v9/s2/phase1"); TRAIN = OUT / "datasets/train"; LEDGER = Path("/private/tmp/claude-501/-Users-mac-AinerWorkFlow-AinerZero/9ceafe9f-ae1e-4da6-a85d-2438a4c80c0b/scratchpad/ledgercheck/diagUXC3/control.sqlite3")
hold = json.load(open(TRAIN / "HOLDOUT_WORLDS.json"))["holdout_worlds"][:8]
def layout_of(w):
    lay = json.load(open(TRAIN / f"world_{int(w):04d}" / "layout.json"))
    return world.Layout(seed=int(lay["seed"]), terrain=[list(r) for r in lay["terrain"]], rooms=[tuple(r) for r in lay["rooms"]], doors=[tuple(x) for x in lay["doors"]], pillars=[tuple(p) for p in lay["pillars"]], layout_sha256=str(lay["layout_sha256"]))
def spearman(a, b):
    ra = np.argsort(np.argsort(a)); rb = np.argsort(np.argsort(b)); return float(np.corrcoef(ra, rb)[0, 1])
models = {a: adapters_mlx.load_trained_model(OUT, a, 42, ledger_path=LEDGER) for a in ("arm_a", "arm_b", "arm_c")}
# (1) one-step dynamics vs identity on holdout transitions
trans = []
for w in hold:
    e = json.load(open(TRAIN / f"world_{int(w):04d}" / "episode_0000.json"))
    st = e["steps"]
    for i in range(len(st) - 1):
        trans.append((st[i]["student_obs"], st[i]["action"], st[i]["dt"], st[i + 1]["student_obs"]))
trans = trans[:300]
for a, m in models.items():
    ep, ei = [], []
    for o, act, dt, o2 in trans:
        z = m.encode(lp.featurize_obs(o, int(o["dt"]))); z2 = m.encode(lp.featurize_obs(o2, int(o2["dt"])))
        p = m.predict_l1(z, int(act), float(dt))
        ep.append(np.linalg.norm(p - z2)); ei.append(np.linalg.norm(z - z2))
    print(a, "one-step: model err", round(float(np.mean(ep)), 4), "identity err", round(float(np.mean(ei)), 4), "ratio", round(float(np.mean(ep) / max(np.mean(ei), 1e-12)), 3))
# (2) latent goal distance vs BFS distance
rng = random.Random(7)
for a, m in models.items():
    lat, bfs = [], []
    for w in hold:
        L = layout_of(w)
        free = [(x, y) for y in range(world.SIZE) for x in range(world.SIZE) if world.is_free(L, x, y)] if hasattr(world, "is_free") else None
        for _ in range(25):
            try:
                s, g, go, stt = world.sample_start_goal_pair(L, rng, kind=rng.choice(["short", "long"]))
            except Exception:
                continue
            zg = m.encode(lp.featurize_goal(go))
            v = world.compute_ego_view(L, s.x, s.y, s.heading) if hasattr(world, "compute_ego_view") else None
            if v is None:
                from ainerzero.v9.experiments.s2.eval import compute_ego_view as cev
                v = cev(L, s.x, s.y, s.heading)
            obs = {"view": v, "heading": [1 if i == s.heading else 0 for i in range(4)], "last_action": [0, 0, 0, 1], "dt": 1}
            zs = m.encode(lp.featurize_obs(obs, 1))
            lat.append(float(np.linalg.norm(zs - zg))); bfs.append(int(stt["bfs_distance"]))
    print(a, "latent-vs-BFS spearman", round(spearman(np.array(lat), np.array(bfs)), 3), "n", len(lat), "BFS range", min(bfs), max(bfs))
