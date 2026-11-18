"""真值诊断：只靠前缀记忆，最短能走多少步（不进任何智能体）。
U_cell：只走前缀里站过的格（任意朝向，真实动力学）。
U_pose：只走前缀里出现过的位姿（含朝向）。
U_fwd ：只沿前缀走过的有向转移（加同位姿合并），即纯重放。
U_both：前缀转移双向都可走，逆向一条按真实最少步数计（站过的格之内）。"""
import collections, heapq, sys, numpy as np
from ainerzero.v9.mini import data as D, evaluate as E, world as W
world = sys.argv[1]
cfg = W.Config() if world == "m1" else W.Config(ice_rooms=2, portals=2)
tasks = E.make_tasks(cfg, 30, 400, 2, 4, eval_seed0=D.EVAL_SEED0)
def bfs_restricted(lay, start, goal_cell, allowed):
    dist = {start: 0}; q = collections.deque([start])
    while q:
        p = q.popleft()
        if (p[0], p[1]) == goal_cell: return dist[p]
        for a in range(3):
            n = W.step(lay, p, a)
            if n not in dist and allowed(n):
                dist[n] = dist[p] + 1; q.append(n)
    return None
rows = []
for t in tasks:
    lay = W.make_layout(t["layout_seed"], cfg)
    P = t["prefix_poses"]; A = t["prefix_acts"]; gc = (t["goal"][0], t["goal"][1])
    cells = {(p[0], p[1]) for p in P}; poses = set(P)
    u_cell = bfs_restricted(lay, t["start"], gc, lambda n: (n[0], n[1]) in cells)
    u_pose = bfs_restricted(lay, t["start"], gc, lambda n: n in poses)
    # 纯重放：节点是位姿，边是前缀里出现过的 (p, a, p')
    adj = collections.defaultdict(set)
    for i in range(len(A)): adj[P[i]].add(P[i + 1])
    dist = {t["start"]: 0}; q = collections.deque([t["start"]]); u_fwd = None
    while q:
        p = q.popleft()
        if (p[0], p[1]) == gc: u_fwd = dist[p]; break
        for n in adj[p]:
            if n not in dist: dist[n] = dist[p] + 1; q.append(n)
    # 双向：逆向边按站过的格之内的真实最少步数
    radj = collections.defaultdict(dict)
    for i in range(len(A)):
        a, b = P[i], P[i + 1]
        radj[a][b] = min(radj[a].get(b, 9), 1)
        if a not in radj[b]:
            c = bfs_restricted(lay, b, (a[0], a[1]), lambda n: (n[0], n[1]) in cells)
            c = c if c is not None else 99
            # 到格即可，朝向再补转身最多 2 步
            radj[b][a] = c + 2
    d = {t["start"]: 0}; h = [(0, t["start"])]; u_both = None
    while h:
        dv, p = heapq.heappop(h)
        if dv > d.get(p, 1e9): continue
        if (p[0], p[1]) == gc: u_both = dv; break
        for n, w in radj[p].items():
            if dv + w < d.get(n, 1e9): d[n] = dv + w; heapq.heappush(h, (dv + w, n))
    rows.append((t["kind"], t["d_star"], u_cell, u_pose, u_fwd, u_both))
for kind in ("short", "long"):
    sub = [r for r in rows if r[0] == kind]
    budget = np.array([2 * r[1] + 20 for r in sub])
    print(kind, "n", len(sub), "d* 均值", round(np.mean([r[1] for r in sub]), 1))
    for k, name in ((2, "U_cell"), (3, "U_pose"), (4, "U_fwd"), (5, "U_both")):
        v = np.array([r[k] if r[k] is not None else 999 for r in sub], float)
        print(f"   {name}: 中位 {np.median(v):.0f}  均值(有限) {np.mean(v[v < 999]):.1f}  可达 {np.mean(v < 999):.2f}  在预算内 {np.mean(v <= budget):.2f}")
