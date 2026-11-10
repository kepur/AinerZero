"""HC 的真先知：按真值的「这一步碰撞 / 擦边」分两箱拟合 σ（读未来，只作上限参考），与正确基线（碰撞 + 擦边步上拟合的常数）比。复核者自写。
数据与 explore4.velocity_nll 相同（世界 2000+，种子 0）。用法：hc_oracle.py <副本根> <输出>"""
import json, math, sys
import numpy as np
sys.path.insert(0, sys.argv[1] + "/src")
from ainerzero.v9.experiments.s4 import world as W
out = {}
for nd in (6, 10):
    rng = np.random.default_rng(0); rows = []
    for w in range(40):
        ep = W.generate_episode("s4x-explore", 2000 + w, nd)
        for s in ep.steps[:-1]:
            nxt = ep.steps[s.t + 1]
            coll = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
            p0 = s.positions + rng.normal(0, 0.05, s.positions.shape); v0 = s.velocities + rng.normal(0, 0.2, s.velocities.shape)
            _, vv, _ = W.physics(p0[None], v0[None], ep.pillars)
            r = vv[0] - nxt.velocities
            dn = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(nd) * 99
            for i in range(nd):
                kind = "coll" if i in coll else ("graze" if dn[i].min() < 2 * W.RADIUS + 0.3 else "free")
                rows.append((w, r[i, 0] ** 2 + r[i, 1] ** 2, kind))
    wid = np.array([x[0] for x in rows]); se = np.array([x[1] for x in rows]); kind = np.array([x[2] for x in rows])
    half = len(rows) // 2; tr = np.arange(len(rows)) < half; sub = kind != "free"; ev = ~tr & sub
    nll = lambda s2, e: np.log(2 * math.pi * s2) + e / (2 * s2)
    s2_sub = se[tr & sub].mean() / 2
    s2_k = {k: se[tr & (kind == k)].mean() / 2 for k in ("coll", "graze")}
    s2_or = np.where(kind == "coll", s2_k["coll"], s2_k["graze"])
    g = nll(s2_sub, se[ev]) - nll(s2_or[ev], se[ev])
    ws = sorted(set(wid[ev].tolist())); wi = {w: i for i, w in enumerate(ws)}
    s = np.zeros(len(ws)); n = np.zeros(len(ws)); np.add.at(s, [wi[x] for x in wid[ev]], g); np.add.at(n, [wi[x] for x in wid[ev]], 1)
    idx = np.random.default_rng(20261110).integers(0, len(ws), size=(4000, len(ws))); gb = s[idx].sum(1) / n[idx].sum(1)
    out[nd] = {"kind_oracle_gain_vs_const_sub": [round(float(g.mean()), 4), round(float(np.percentile(gb, 2.5)), 4), round(float(np.percentile(gb, 97.5)), 4)],
               "sigma_coll": round(math.sqrt(s2_k["coll"]), 4), "sigma_graze": round(math.sqrt(s2_k["graze"]), 4), "sigma_sub": round(math.sqrt(s2_sub), 4)}
print(json.dumps(out)); json.dump(out, open(sys.argv[2], "w"), indent=1)
