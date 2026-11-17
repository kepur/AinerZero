"""智能体。所有学到的臂共用同一个训练好的模型（编码器 + 预测器 + 代价头），只换代价或记忆。

- LatentTree(cost="euclid")：S2 的做法，潜空间欧氏距离当代价（对照）。
- LatentTree(cost="learned")：同一个潜空间、同一个规划器，代价换成学到的可达性（式 14 ①）。
- Graph：拓扑地图即记忆（式 14 ②）。节点是探索前缀里见过的潜状态，边是观察到的转移和
  学到的可达性 ≤ δ 的近邻；图上最短路选下一个路点，再用学到的代价做局部规划。
- AnalyticMap：便宜规则，不学习。按指南针朝向和「前方不是墙就前进」做里程计，把视野写进
  自己坐标系的栅格地图，把目标视野和地图逐格匹配定位，再在地图上 BFS。
- Oracle：真值地图上的最短路（上界，只作可行性检查）。Random：随机动作。
"""
from __future__ import annotations

import collections
import itertools
import random

import mlx.core as mx
import numpy as np

from . import world as W
from .model import WorldModel


class Episode:
    """一个回合给智能体的信息：探索前缀（观察与动作）和目标观察。不含坐标。"""

    def __init__(self, prefix_obs, prefix_views, prefix_heads, prefix_acts, goal_obs, goal_view, goal_head):
        self.prefix_obs = prefix_obs        # (P+1, D)
        self.prefix_views = prefix_views    # list[(V, V)]
        self.prefix_heads = prefix_heads    # list[int]
        self.prefix_acts = prefix_acts      # list[int]，长度 P
        self.goal_obs = goal_obs            # (D,)
        self.goal_view = goal_view
        self.goal_head = goal_head


class LatentTree:
    def __init__(self, model: WorldModel, cost: str, horizon: int = 3, eps: float = 0.05, seed: int = 0):
        self.m, self.cost, self.eps = model, cost, eps
        self.rng = random.Random(seed)
        self.seqs = mx.array(np.array(list(itertools.product(range(W.N_ACTIONS), repeat=horizon)), dtype=np.int32))
        self.horizon = horizon

    def reset(self, ep: Episode) -> None:
        self.zg = self.m.encode(mx.array(ep.goal_obs[None]))
        self.target = self.zg

    def _c(self, z: mx.array, zt: mx.array) -> mx.array:
        if self.cost == "euclid":
            return mx.sqrt(mx.sum((z - zt) ** 2, axis=-1))
        return self.m.reach(z, zt)

    def plan_to(self, obs: np.ndarray, zt: mx.array) -> int:
        if self.rng.random() < self.eps:
            return self.rng.randrange(W.N_ACTIONS)
        n = self.seqs.shape[0]
        z = mx.broadcast_to(self.m.encode(mx.array(obs[None])), (n, self.zg.shape[-1]))
        zt = mx.broadcast_to(zt, z.shape)
        total = mx.zeros((n,))
        for i in range(self.horizon):
            z = self.m.predict(z, self.seqs[:, i])
            total = total + self._c(z, zt)
        tot = np.array(total) + 1e-6 * np.array([self.rng.random() for _ in range(n)])
        return int(np.array(self.seqs)[int(np.argmin(tot)), 0])

    def act(self, obs: np.ndarray, view: np.ndarray, head: int) -> int:
        return self.plan_to(obs, self.target)


class Graph(LatentTree):
    def __init__(self, model: WorldModel, delta: float = 3.0, **kw):
        super().__init__(model, cost="learned", **kw)
        self.delta = delta

    def reset(self, ep: Episode) -> None:
        super().reset(ep)
        z = self.m.encode(mx.array(ep.prefix_obs))
        s, a = self.m.cost_embed(z)
        sg, ag = self.m.cost_embed(self.zg)
        self.z_nodes = z
        self.s, self.a = np.array(s), np.array(a)
        n = self.s.shape[0]
        dmat = np.sqrt(((self.s[:, None] - self.s[None]) ** 2).sum(-1) + 1e-8) + \
            np.maximum(self.a[:, None] - self.a[None], 0).sum(-1)
        w = np.where(dmat <= self.delta, dmat, np.inf)
        idx = np.arange(n - 1)
        w[idx, idx + 1] = np.minimum(w[idx, idx + 1], 1.0)   # 观察到的转移
        np.fill_diagonal(w, 0.0)
        for k in range(n):                                    # Floyd–Warshall
            w = np.minimum(w, w[:, k:k + 1] + w[k:k + 1, :])
        d_goal = np.sqrt(((self.s - np.array(sg)) ** 2).sum(-1) + 1e-8) + \
            np.maximum(self.a - np.array(ag), 0).sum(-1)
        d_goal = np.where(d_goal <= self.delta, d_goal, np.inf)
        self.to_goal = np.min(w + d_goal[None, :], axis=1)    # 每个节点经图到目标的代价

    def act(self, obs: np.ndarray, view: np.ndarray, head: int) -> int:
        z = self.m.encode(mx.array(obs[None]))
        s, a = self.m.cost_embed(z)
        s, a = np.array(s)[0], np.array(a)[0]
        sg, ag = self.m.cost_embed(self.zg)
        d_cur_goal = float(np.sqrt(((s - np.array(sg)[0]) ** 2).sum()) + np.maximum(a - np.array(ag)[0], 0).sum())
        d_cur = np.sqrt(((s[None] - self.s) ** 2).sum(-1) + 1e-8) + np.maximum(a[None] - self.a, 0).sum(-1)
        near = d_cur <= self.delta
        if d_cur_goal <= self.delta or not near.any():
            return self.plan_to(obs, self.zg)
        total = np.where(near, d_cur + self.to_goal, np.inf)
        if not np.isfinite(total).any() or d_cur_goal <= total.min():
            return self.plan_to(obs, self.zg)
        # 近邻里经图到目标最近的那个当路点（往前推进最多）
        cand = np.where(near & np.isfinite(self.to_goal))[0]
        wp = cand[np.argmin(self.to_goal[cand])]
        return self.plan_to(obs, self.z_nodes[wp:wp + 1])


class AnalyticMap:
    """便宜规则：里程计 + 栅格地图 + 视野匹配定位 + BFS。不学习，不用坐标真值。"""

    def __init__(self, cfg: W.Config, seed: int = 0):
        self.cfg = cfg
        self.rng = random.Random(seed)
        self.n = 2 * cfg.size + 1

    def _write(self, view: np.ndarray, pose) -> None:
        x, y, h = pose
        for row, col, dx, dy in W.ego_offsets(self.cfg.view_radius, h):
            v = view[row, col]
            if v != W.OOB:
                self.map[y + dy, x + dx] = v

    def reset(self, ep: Episode) -> None:
        c = self.cfg.size
        self.map = np.full((self.n, self.n), -1, dtype=np.int16)
        self.pose = (c, c, ep.prefix_heads[0])
        self._write(ep.prefix_views[0], self.pose)
        for a, v in zip(ep.prefix_acts, ep.prefix_views[1:]):
            self.pose = W.analytic_step(self.map, self.pose, a)
            self._write(v, self.pose)
        self.goal_view, self.goal_head = ep.goal_view, ep.goal_head
        self.goal = None
        self.last = None

    def _localize_goal(self):
        offs = W.ego_offsets(self.cfg.view_radius, self.goal_head)
        need = [(dx, dy, self.goal_view[r, c]) for r, c, dx, dy in offs if self.goal_view[r, c] != W.OOB]
        best, best_n = None, -1
        ys, xs = np.nonzero(self.map >= W.FLOOR0)
        for x, y in zip(xs.tolist(), ys.tolist()):
            known = ok = 0
            for dx, dy, v in need:
                mv = self.map[y + dy, x + dx] if 0 <= y + dy < self.n and 0 <= x + dx < self.n else -1
                if mv == -1:
                    continue
                known += 1
                if mv != v:
                    ok = -1
                    break
            if ok == 0 and known >= 0.8 * len(need) and known > best_n:
                best, best_n = (x, y), known
        return best

    def _bfs_first_action(self, targets) -> int | None:
        start = self.pose
        prev = {start: None}
        q = collections.deque([start])
        while q:
            p = q.popleft()
            if (p[0], p[1]) in targets:
                while prev[p] is not None and prev[p][0] != start:
                    p = prev[p][0]
                return prev[p][1] if prev[p] is not None else None
            for a in range(W.N_ACTIONS):
                nxt = W.analytic_step(self.map, p, a)
                if nxt not in prev and 0 < nxt[0] < self.n - 1 and 0 < nxt[1] < self.n - 1:
                    prev[nxt] = (p, a)
                    q.append(nxt)
        return None

    def act(self, obs: np.ndarray, view: np.ndarray, head: int) -> int:
        if self.last is not None:
            self.pose = W.analytic_step(self.map, self.pose, self.last)
        self._write(view, self.pose)
        if self.goal is None:
            self.goal = self._localize_goal()
        if self.goal is not None:
            a = self._bfs_first_action({self.goal})
        else:   # 没定位到目标：去最近的未知边界
            ys, xs = np.nonzero(self.map == -1)
            frontier = {(x, y) for x, y in zip(xs.tolist(), ys.tolist())
                        if any(0 <= y + dy < self.n and 0 <= x + dx < self.n and self.map[y + dy, x + dx] >= W.FLOOR0
                               for dx, dy in W.DELTA)}
            a = self._bfs_first_action(frontier)
        if a is None:
            a = self.rng.randrange(W.N_ACTIONS)
        self.last = a
        return a


class Oracle:
    def __init__(self, layout: W.Layout, goal_cell, seed: int = 0):
        self.layout = layout
        self.dist = W.reverse_bfs_to_cell(layout, goal_cell)
        self.rng = random.Random(seed)
        self.pose = None

    def reset(self, ep: Episode) -> None:
        pass

    def act_pose(self, pose) -> int:
        ds = [self.dist.get(W.step(self.layout, pose, a), 10 ** 6) for a in range(W.N_ACTIONS)]
        return int(np.argmin(ds))


class Random:
    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def reset(self, ep: Episode) -> None:
        pass

    def act(self, obs, view, head) -> int:
        return self.rng.randrange(W.N_ACTIONS)
