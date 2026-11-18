"""真值诊断：地点图（节点 = 前缀站过的格，任意朝向；原地转身随时可做；前进只能沿前缀里实际走过的 (格, 朝向) → 格）。"""
import collections, heapq, sys, numpy as np
from ainerzero.v9.mini import data as D, evaluate as E, world as W
world = sys.argv[1]
cfg = W.Config() if world == "m1" else W.Config(ice_rooms=2, portals=2)
tasks = E.make_tasks(cfg, 30, 400, 2, 4, eval_seed0=D.EVAL_SEED0)
res = {"short": [], "long": []}
for t in tasks:
    P, A = t["prefix_poses"], t["prefix_acts"]; gc = (t["goal"][0], t["goal"][1])
    fwd = {}
    for i, a in enumerate(A):
        if a == W.FORWARD and (P[i][0], P[i][1]) != (P[i + 1][0], P[i + 1][1]):
            fwd[(P[i][0], P[i][1], P[i][2])] = P[i + 1]
    s = t["start"]; d = {s: 0}; h = [(0, s)]; best = None
    while h:
        dv, p = heapq.heappop(h)
        if dv > d.get(p, 1e9): continue
        if (p[0], p[1]) == gc: best = dv; break
        nxt = [(p[0], p[1], (p[2] - 1) % 4), (p[0], p[1], (p[2] + 1) % 4)]
        if p in fwd: nxt.append(fwd[p])
        for n in nxt:
            if dv + 1 < d.get(n, 1e9): d[n] = dv + 1; heapq.heappush(h, (dv + 1, n))
    res[t["kind"]].append((t["d_star"], best))
for k, v in res.items():
    b = np.array([2 * x + 20 for x, _ in v]); u = np.array([y if y is not None else 999 for _, y in v])
    print(world, k, "可达", round(float(np.mean(u < 999)), 2), "预算内", round(float(np.mean(u <= b)), 2), "中位", np.median(u), "d*中位", np.median([x for x, _ in v]))
