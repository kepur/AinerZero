"""一级补证 A28 必查项 1：所有地板格两两可达。

完全独立于 world.pose_bfs / reverse_bfs_to_cell / _strongly_connected：
只用 world.step 枚举每个位姿的三个后继，自建正向图和反向图，从起点格的四个朝向做正向 BFS，
再在反向图上做 BFS，要求每个地板格都在正向可达集里，且每个正向可达位姿都能回到起点格。
对确认段留出图（8_000_000 起）只生成地图做这项检查，不跑任何智能体或模型。
"""
import collections, sys, time
from ainerzero.v9.mini import world as W

cfg = W.Config(ice_rooms=2, portals=2)

def check(layout):
    s = cfg.size
    free = [(x, y) for y in range(s) for x in range(s) if layout.grid[y, x] >= W.FLOOR0]
    start = {(free[0][0], free[0][1], h) for h in range(4)}
    fwd, rev = set(start), collections.defaultdict(set)
    q = collections.deque(start)
    while q:
        p = q.popleft()
        for a in range(W.N_ACTIONS):
            n = W.step(layout, p, a)
            rev[n].add(p)
            if n not in fwd:
                fwd.add(n); q.append(n)
    cells = {(p[0], p[1]) for p in fwd}
    back, q = set(start), collections.deque(start)
    while q:
        p = q.popleft()
        for m in rev[p]:
            if m not in back:
                back.add(m); q.append(m)
    return all(c in cells for c in free) and fwd <= back

seeds = [7_100_000 + 1000 * s + i for s in range(5) for i in range(200)] + list(range(7_900_000, 7_900_030)) \
        + [8_000_000 + 1000 * s + i for s in range(5) for i in range(40)]
t0, bad = time.time(), []
for sd in seeds:
    if not check(W.make_layout(sd, cfg)):
        bad.append(sd)
print(f"检查 {len(seeds)} 张图，不满足两两可达 {len(bad)} 张 {bad[:10]}，{time.time() - t0:.0f} 秒")
# 反向对照：把房间 (0,0) 封死只留中间一格地板，这格走不到，检查必须判失败
L = W.make_layout(7_900_000, cfg)
g = L.grid.copy()
g[1:6, 1:6] = W.WALL
g[3, 3] = W.FLOOR0
iso = W.Layout(seed=L.seed, cfg=cfg, grid=g, portal_to={k: v for k, v in L.portal_to.items() if not (1 <= v[0] <= 5 and 1 <= v[1] <= 5)})
print("反向对照（孤立格）判为不可达：", not check(iso))
