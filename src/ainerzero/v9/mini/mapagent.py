"""地图即记忆的智能体（几何核心 + 度量地图 + 图搜索），按「学什么、记什么」分成几个臂。

共同部分（都不用坐标真值）：
- 里程计：指南针朝向 + 前进模型预测下一位姿；
- 地图：把视野写进自己坐标系的栅格；
- 惊讶：预测位姿处、地图上已知的格子和实际视野不一致，就是事件；
- 重定位：
  1. 先沿朝向那条射线就近找视野一致的位姿（滑动只会落在射线上）；
  2. 找不到就在整张地图上找，唯一一致就采用；
  3. 否则迷路：在一个新的局部碎片里继续建图，同时维护主地图上的候选位姿集，每步用前进模型推进、
     用当前视野和整块碎片地图筛选（碎片在该偏移下与主地图有任何一格冲突，这个偏移就作废）。
     只剩一个候选、且碎片与主地图在该偏移下的重叠格数够 MERGE_MIN_OVERLAP 时，才把碎片并回主地图。
     整图上唯一一致的位姿也不直接采用，同样走这条路（A27 F-04：只凭当前一帧就并图，约四成并错）；
- 规划：在位姿图上 BFS 到目标格，目标靠目标视野与地图逐格匹配定位。迷路时如果目标在碎片里，
  就在碎片里规划，否则沿碎片的未知边界探索。

各臂的区别：
- analytic：前进模型只有解析先验，不记事件（最强的不学习规则）。
- memory：解析先验 + 把本图里经历过的事件记下来（某位姿前进实际到了哪；某个传送门通向哪），不学习。
- hybrid（V9）：门控学习残差（式 16）+ 事件记忆。残差学到跨图通用的规律（冰面会滑、踏上传送门会被送走），
  记忆存本图的具体事实（这个门通向哪）。去向未知的传送门在规划时绕开。
- ungated：同 hybrid，但前进模型换成不门控的整块分类器（E1 教训的对照）。
"""
from __future__ import annotations

import collections
import random

import numpy as np

from . import world as W
from .residual import TELEPORT, ForwardModel

_FOLD = np.array([W.fold_type(v) for v in range(W.N_TYPES)], dtype=np.int64)
MERGE_MIN_OVERLAP = 20   # 并图前碎片与主地图在候选偏移下至少要有这么多格重叠（且全部一致）


class Frame:
    """一张自我坐标系的栅格地图，连同在这张图上的位姿和前进结果表。"""

    def __init__(self, n: int, cfg: W.Config, fm: ForwardModel, pose):
        self.n, self.cfg, self.fm = n, cfg, fm
        self.map = np.full((n, n), -1, dtype=np.int16)
        self.version, self._tv, self._tab = 0, -1, None
        self.pose = pose

    def write(self, view: np.ndarray, pose) -> None:
        x, y, h = pose
        for row, col, dx, dy in W.ego_offsets(self.cfg.view_radius, h):
            v = view[row, col]
            cx, cy = x + dx, y + dy
            if v != W.OOB and 0 <= cy < self.n and 0 <= cx < self.n and self.map[cy, cx] != v:
                self.map[cy, cx] = v
                self.version += 1

    def check(self, view: np.ndarray, pose) -> tuple[int, int, int]:
        """(已知格数, 不一致格数, 视野里可见格数)。"""
        x, y, h = pose
        known = bad = vis = 0
        for row, col, dx, dy in W.ego_offsets(self.cfg.view_radius, h):
            v = view[row, col]
            if v == W.OOB:
                continue
            vis += 1
            cx, cy = x + dx, y + dy
            mv = self.map[cy, cx] if 0 <= cy < self.n and 0 <= cx < self.n else -1
            if mv == -1:
                continue
            known += 1
            bad += int(mv != v)
        return known, bad, vis

    def ok(self, view, pose, frac: float, floor: int) -> tuple[bool, int]:
        known, bad, vis = self.check(view, pose)
        return bad == 0 and known >= max(floor, frac * vis), known

    def candidates(self, view, h: int) -> list:
        ys, xs = np.nonzero((self.map != -1) & (self.map != W.WALL))
        return [(x, y, h) for x, y in zip(xs.tolist(), ys.tolist()) if self.ok(view, (x, y, h), 0.6, 4)[0]]

    def table(self) -> np.ndarray:
        """所有位姿的前进结果 (n, n, 4)，地图变了才重算。"""
        if self._tv == self.version:
            return self._tab
        L, n = W.RAY_LEN, self.n
        folded = np.where(self.map < 0, 0, _FOLD[np.clip(self.map, 0, None)])
        pad = np.pad(folded, L, constant_values=1)
        rays = np.zeros((n, n, 4, L), dtype=np.int64)
        for h, (dx, dy) in enumerate(W.DELTA):
            for k in range(1, L + 1):
                rays[:, :, h, k - 1] = pad[L + k * dy:L + k * dy + n, L + k * dx:L + k * dx + n]
        self._tab = self.fm.predict(rays)
        self._tv = self.version
        return self._tab

    def in_bounds(self, p) -> bool:
        return 0 < p[0] < self.n - 1 and 0 < p[1] < self.n - 1

    def localize_goal(self, goal_view: np.ndarray, goal_head: int):
        offs = W.ego_offsets(self.cfg.view_radius, goal_head)
        need = [(dx, dy, goal_view[r, c]) for r, c, dx, dy in offs if goal_view[r, c] != W.OOB]
        best, best_n = None, -1
        ys, xs = np.nonzero((self.map != -1) & (self.map != W.WALL))
        for x, y in zip(xs.tolist(), ys.tolist()):
            known, ok = 0, True
            for dx, dy, v in need:
                cx, cy = x + dx, y + dy
                mv = self.map[cy, cx] if 0 <= cy < self.n and 0 <= cx < self.n else -1
                if mv == -1:
                    continue
                known += 1
                if mv != v:
                    ok = False
                    break
            if ok and known >= 0.8 * len(need) and known > best_n:
                best, best_n = (x, y), known
        return best


class MapAgent:
    def __init__(self, cfg: W.Config, fm: ForwardModel, memory: bool, seed: int = 0):
        self.cfg, self.fm, self.memory = cfg, fm, memory
        self.rng = random.Random(seed)
        self.n = 2 * cfg.size + 1
        self.forward_log = None   # M3：设成列表就记录 (前进前的射线, 自己定位得到的结果)，不用真值

    def _disp(self, before, after) -> int:
        dx, dy = W.DELTA[before[2]]
        for k in range(W.RAY_LEN + 1):
            if (before[0] + k * dx, before[1] + k * dy) == (after[0], after[1]):
                return k
        return TELEPORT

    def _log(self, ray, label) -> None:
        if self.forward_log is not None and ray is not None:
            self.forward_log.append((ray, label, self.steps - 1))   # 第几步（前缀里的动作序号）

    # ------------------------------------------------------------ 前进与转向
    def _next(self, fr: Frame, p, a: int, planning: bool, use_memory: bool):
        if a == W.LEFT:
            return (p[0], p[1], (p[2] - 1) % 4)
        if a == W.RIGHT:
            return (p[0], p[1], (p[2] + 1) % 4)
        x, y, h = p
        if use_memory and p in self.trans_mem:
            return self.trans_mem[p]
        dx, dy = W.DELTA[h]
        c1 = (x + dx, y + dy)
        k = int(fr.table()[y, x, h])
        if use_memory and k >= 1 and c1 in self.portal_mem:
            return (*self.portal_mem[c1], h)
        if k == TELEPORT:   # 去向未知的传送：规划时绕开，预测时只能按解析先验猜
            return p if planning else W.analytic_step(fr.map, p, a)
        q = (x + k * dx, y + k * dy, h)
        return q if fr.in_bounds(q) else p

    # ------------------------------------------------------------ 回合
    def reset(self, ep) -> None:
        c = self.cfg.size
        self.main = Frame(self.n, self.cfg, self.fm, (c, c, ep.prefix_heads[0]))
        self.trans_mem, self.portal_mem = {}, {}
        self.frag = None          # 迷路时的碎片
        self.cands = None         # 迷路时主地图上的候选：候选位姿 -> 碎片里的对应位姿
        self.rejected = set()     # 当前碎片已被整块地图否掉的偏移
        self.surprises = self.lost = self.steps = 0
        self.main.write(ep.prefix_views[0], self.main.pose)
        for a, v, h in zip(ep.prefix_acts, ep.prefix_views[1:], ep.prefix_heads[1:]):
            self._advance(a, v, h)
        self.prefix_surprises, self.prefix_lost = self.surprises, self.lost
        self.surprises = self.steps = 0
        self.goal_view, self.goal_head = ep.goal_view, ep.goal_head
        self.last = None

    @property
    def pose(self):
        return self.main.pose

    def _ray_candidate(self, view, before):
        x, y, h = before
        dx, dy = W.DELTA[h]
        best, key = None, None
        for k in range(0, W.RAY_LEN + 1):
            p = (x + k * dx, y + k * dy, h)
            if not self.main.in_bounds(p) or self.main.map[p[1], p[0]] == W.WALL:
                break
            ok, known = self.main.ok(view, p, 0.3, 3)
            if ok and (key is None or known > key):
                best, key = p, known
        return best

    def _resolved(self, before, a: int, landed) -> None:
        """事件解释清楚了：记进本图的事件记忆。"""
        if not (self.memory and a == W.FORWARD):
            return
        dx, dy = W.DELTA[before[2]]
        c1 = (before[0] + dx, before[1] + dy)
        if self.main.map[c1[1], c1[0]] == W.PORTAL:
            self.portal_mem[c1] = (landed[0], landed[1])
        else:
            self.trans_mem[before] = landed

    def _advance(self, a: int, view: np.ndarray, head: int) -> None:
        self.steps += 1
        if self.frag is not None:
            self._lost_step(a, view, head)
            return
        before = self.main.pose
        ray = W.ray(self.main.map, before) if (self.forward_log is not None and a == W.FORWARD) else None
        pred = self._next(self.main, before, a, planning=False, use_memory=self.memory)
        if self.main.check(view, pred)[1] == 0:
            self._log(ray, self._disp(before, pred))
            self.main.pose = pred
            self.main.write(view, pred)
            return
        self.surprises += 1
        loc = self._ray_candidate(view, before) if a == W.FORWARD else None
        if loc is None:   # 射线上解释不了：迷路，开碎片；整图候选（哪怕唯一）留给 _lost_step 用整块碎片验证
            cs = self.main.candidates(view, head)
            self._log(ray, TELEPORT)
            self.lost += 1
            c = self.cfg.size
            self.frag = Frame(self.n, self.cfg, self.fm, (c, c, head))
            self.frag.write(view, self.frag.pose)
            self.frag_origin = self.frag.pose
            self.lost_from, self.lost_action = before, a
            self.cands = {p: self.frag.pose for p in cs}
            self.rejected = set()
            return
        self._log(ray, self._disp(before, loc))
        self._resolved(before, a, loc)
        self.main.pose = loc
        self.main.write(view, loc)

    def _lost_step(self, a: int, view: np.ndarray, head: int) -> None:
        fr = self.frag
        fp = self._next(fr, fr.pose, a, planning=False, use_memory=False)
        if fr.check(view, fp)[1] != 0:   # 碎片内也解释不了：重开碎片
            c = self.cfg.size
            self.frag = fr = Frame(self.n, self.cfg, self.fm, (c, c, head))
            self.frag_origin = fp = fr.pose
            self.cands = {}
            self.rejected = set()
        fr.pose = fp
        fr.write(view, fp)
        nxt = {}
        for p in self.cands:
            q = self._next(self.main, p, a, planning=False, use_memory=self.memory)
            if self.main.ok(view, q, 0.3, 3)[0]:
                nxt[q] = fp
        if not nxt:
            nxt = {p: fp for p in self.main.candidates(view, head)}
        overlap = {}
        for q in list(nxt):   # 整块碎片验证：该偏移下有一格冲突就作废
            off = (q[0] - fp[0], q[1] - fp[1])
            known, bad = (0, 1) if off in self.rejected else self._overlap(fr, *off)
            if bad:
                self.rejected.add(off)
                del nxt[q]
            else:
                overlap[q] = known
        self.cands = nxt
        if len(nxt) == 1:
            (pose, fpose), = nxt.items()
            if overlap[pose] < MERGE_MIN_OVERLAP:   # 证据还不够，继续跟踪
                return
            ox, oy = pose[0] - fpose[0], pose[1] - fpose[1]
            self._merge(fr, ox, oy)
            origin = (self.frag_origin[0] + ox, self.frag_origin[1] + oy, self.frag_origin[2])
            self._resolved(self.lost_from, self.lost_action, origin)
            self.main.pose = pose
            self.main.write(view, pose)
            self.frag = self.cands = None
            self.rejected = set()

    def _overlap(self, fr: Frame, ox: int, oy: int) -> tuple[int, int]:
        """碎片平移 (ox, oy) 后与主地图的（重叠已知格数，其中不一致的格数）。"""
        ys, xs = np.nonzero(fr.map != -1)
        tx, ty = xs + ox, ys + oy
        inb = (tx >= 0) & (tx < self.n) & (ty >= 0) & (ty < self.n)
        if not inb.all():
            return 0, 1   # 碎片出了主地图的范围：偏移不可能对
        mv = self.main.map[ty, tx]
        both = mv != -1
        return int(both.sum()), int((mv[both] != fr.map[ys, xs][both]).sum())

    def _merge(self, fr: Frame, ox: int, oy: int) -> None:
        ys, xs = np.nonzero(fr.map != -1)
        tx, ty = xs + ox, ys + oy
        ok = (tx >= 0) & (tx < self.n) & (ty >= 0) & (ty < self.n)
        tx, ty, xs, ys = tx[ok], ty[ok], xs[ok], ys[ok]
        unknown = self.main.map[ty, tx] == -1
        if unknown.any():
            self.main.map[ty[unknown], tx[unknown]] = fr.map[ys[unknown], xs[unknown]]
            self.main.version += 1

    # ------------------------------------------------------------ 规划
    def _bfs_first_action(self, fr: Frame, targets, use_memory: bool) -> int | None:
        start = fr.pose
        prev = {start: None}
        q = collections.deque([start])
        while q:
            p = q.popleft()
            if (p[0], p[1]) in targets and p != start:
                while prev[p][0] != start:
                    p = prev[p][0]
                return prev[p][1]
            for a in range(W.N_ACTIONS):
                nxt = self._next(fr, p, a, planning=True, use_memory=use_memory)
                if nxt not in prev:
                    prev[nxt] = (p, a)
                    q.append(nxt)
        return None

    def _frontier(self, fr: Frame) -> set:
        m = fr.map
        known = (m != -1) & (m != W.WALL)
        nb = np.zeros_like(known)
        nb[1:] |= known[:-1]
        nb[:-1] |= known[1:]
        nb[:, 1:] |= known[:, :-1]
        nb[:, :-1] |= known[:, 1:]
        ys, xs = np.nonzero((m == -1) & nb)
        return set(zip(xs.tolist(), ys.tolist()))

    def act(self, obs, view: np.ndarray, head: int) -> int:
        if self.last is not None:
            self._advance(self.last, view, head)
        a = None
        if self.frag is None:
            goal = self.main.localize_goal(self.goal_view, self.goal_head)
            if goal is not None:
                a = self._bfs_first_action(self.main, {goal}, self.memory)
            if a is None:
                a = self._bfs_first_action(self.main, self._frontier(self.main), self.memory)
        else:
            goal = self.frag.localize_goal(self.goal_view, self.goal_head)
            if goal is not None:
                a = self._bfs_first_action(self.frag, {goal}, False)
            if a is None:   # 目标不在碎片里：按碎片的未知边界探索，走回已知区域才能并图
                a = self._bfs_first_action(self.frag, self._frontier(self.frag), False)
        if a is None:
            a = W.FORWARD if self.rng.random() < 0.7 else self.rng.choice((W.LEFT, W.RIGHT))
        self.last = a
        return a
