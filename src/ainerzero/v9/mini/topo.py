"""SPTM 式拓扑记忆组（更强的潜空间对照，2026-11-18 起探索）。

M4 里四个潜空间组长目标都接近 0，H1 因此差值很大。审稿人会问：换成文献里这类任务的标准做法呢？
这类任务（先给一段探索序列，再走到序列里见过的目标画面）的标准做法是 SPTM（Savinov 等，2018）和
ViNG（Shah 等，2021）一类的拓扑记忆。这里按它们的配方实现，全部自监督：只用训练游走里的时间间隔，
不用真值位姿、不用真值距离。

- 可达性网络 R(o_i, o_j)：同一条轨迹上相隔不超过 K_POS 步为正例，至少 K_NEG 步为负例。
  孪生编码器加对称的头（e_i+e_j、e_i*e_j、|e_i−e_j|），输出 logit。
- 运动网络 L(o_t, o_w)：同一条轨迹上 o_t 与 k 步之后的 o_{t+k}（1 ≤ k ≤ K_LOC），预测 a_t。k=1 时就是逆动力学。
- 记忆图：节点是探索前缀的每一帧。相邻帧双向连边（SPTM 的时间边）；R 很确信、且时间上不相邻的两帧之间加捷径边。
- 目标：R 判为与目标画面同一处的节点（多源）；没有足够确信的就取最像的一个。
- 定位：任务从前缀终点出发（地图组也知道这一点）。之后每步先在上一估计的图邻域内按 R 取最像的节点；
  邻域里都不像时全图重定位；全图也不像就保持原估计。
- 路点：从当前节点沿图上最短路往目标走，取前 H_WP 个节点里 R 判为可达的最远一个；运动网络朝路点走。
  当前画面已判为能到达目标时，直接朝目标走。

与其他学到的组的区别：它有自己的编码器（不共用世界模型），因为这是在给潜空间一方最好的机会，
不是在检验共用编码器。
"""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
import random
import time

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from . import world as W
from .data import Dataset
from .model import mlp, n_params


@dataclass
class TopoConfig:
    steps: int = 6000
    batch: int = 256
    lr: float = 3e-4
    emb: int = 64
    hidden: int = 256
    k_pos: int = 3        # 正例：相隔 ≤ k_pos 步
    k_neg: int = 25       # 负例：相隔 ≥ k_neg 步（游走会回头，负例有噪声，SPTM 同样接受）
    k_loc: int = 4        # 运动网络的目标最远隔几步
    seed: int = 0
    log_every: int = 1000


@dataclass
class TopoPlanConfig:
    near: bool = True          # 是否加 SPTM 的学到的捷径边（R 很确信、观察不同的两帧）
    s_near: float = 0.95       # 捷径边的 R 门槛
    w_near: float = 2.0        # 走一条捷径边按几步算（交给运动网络）
    min_gap: int = 4           # 捷径边只连时间上隔 ≥ min_gap 的两帧（更近的已由时间边连上）
    w_same: float = 0.01       # 观察完全相同的两帧之间的代价（接近 0，留一点免得走零代价环）
    w_rev: float = 3.0         # 逆着前缀走一条时间边的代价（不知道怎么倒回去，交给运动网络）
    s_loc: float = 0.5         # 定位门槛
    loc_hops: int = 4          # 定位只在预期节点的这么多跳以内找（同一处的边不计跳数）
    s_reach: float = 0.5       # 当前画面判为能直接到达目标的门槛
    h_path: int = 30           # 每步沿最短路最多看这么多条边
    eps: float = 0.05          # 随机动作概率，与其他学到的组相同


class TopoNets(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int = W.N_ACTIONS, emb: int = 64, hidden: int = 256):
        super().__init__()
        self.enc = mlp([obs_dim, hidden, hidden, emb])
        self.r_head = mlp([3 * emb, hidden, 1])
        self.l_head = mlp([3 * emb, hidden, n_actions])

    def embed(self, obs: mx.array) -> mx.array:
        return self.enc(obs)

    def reach_logit(self, ea: mx.array, eb: mx.array) -> mx.array:
        """对称：R(a, b) = R(b, a)。ea、eb 可广播。"""
        ea, eb = mx.broadcast_arrays(ea, eb)
        return self.r_head(mx.concatenate([ea + eb, ea * eb, mx.abs(ea - eb)], axis=-1))[..., 0]

    def action_logits(self, et: mx.array, ew: mx.array) -> mx.array:
        et, ew = mx.broadcast_arrays(et, ew)
        return self.l_head(mx.concatenate([et, ew, ew - et], axis=-1))


# ---------------------------------------------------------------- 训练（只用时间间隔，不用真值）

def sample_reach(ds: Dataset, rng: np.random.Generator, b: int, k_pos: int, k_neg: int):
    """返回 (i, t1, t2, y)：同一条轨迹 i 上的两帧及标签（1 = 相隔 ≤ k_pos，0 = 相隔 ≥ k_neg）。"""
    T = ds.horizon
    if k_neg > T:
        raise ValueError("k_neg 超过轨迹长度")
    i = rng.integers(0, ds.n_traj, b)
    t1 = rng.integers(0, T + 1, b)
    y = (rng.random(b) < 0.5).astype(np.float32)
    off = rng.integers(-k_pos, k_pos + 1, b)
    t2 = np.clip(t1 + off, 0, T)
    neg = y == 0
    # 负例：在 [0, T] 里相隔 ≥ k_neg 的位置中均匀取。左边可选 t1-k_neg+1 个，右边 T-t1-k_neg+1 个
    left = np.maximum(t1 - k_neg + 1, 0)
    right = np.maximum(T - t1 - k_neg + 1, 0)
    tot = left + right
    bad = neg & (tot == 0)
    y[bad] = 1.0                       # 轨迹太短找不到负例时改成正例（T ≥ 2·k_neg 时不会发生）
    neg = y == 0
    u = (rng.random(b) * np.maximum(tot, 1)).astype(np.int64)
    t2n = np.where(u < left, u, t1 + k_neg + (u - left))
    t2 = np.where(neg, t2n, t2)
    return i, t1, t2, y


def sample_loc(ds: Dataset, rng: np.random.Generator, b: int, k_loc: int):
    """返回 (i, t, k, a)：o_t 与 o_{t+k}，标签是 t 时刻的动作。"""
    T = ds.horizon
    i = rng.integers(0, ds.n_traj, b)
    t = rng.integers(0, T, b)
    k = 1 + (rng.random(b) * k_loc).astype(np.int64)
    k = np.minimum(k, T - t)
    return i, t, k, ds.act[i, t]


def train_topo(ds: Dataset, cfg: TopoConfig, log=print) -> tuple[TopoNets, dict]:
    mx.random.seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed + 7_777)
    nets = TopoNets(ds.obs.shape[-1], emb=cfg.emb, hidden=cfg.hidden)
    mx.eval(nets.parameters())
    opt = optim.AdamW(learning_rate=cfg.lr, weight_decay=1e-4)

    def loss_fn(m, oa, ob, y, ot, ow, a):
        n = oa.shape[0]
        e = m.embed(mx.concatenate([oa, ob, ot, ow], axis=0))
        lr_ = m.reach_logit(e[:n], e[n:2 * n])
        lr_loss = mx.mean(nn.losses.binary_cross_entropy(lr_, y, with_logits=True))
        la = m.action_logits(e[2 * n:3 * n], e[3 * n:])
        ll_loss = mx.mean(nn.losses.cross_entropy(la, a))
        r_acc = mx.mean(((lr_ > 0).astype(mx.float32) == y).astype(mx.float32))
        l_acc = mx.mean((mx.argmax(la, axis=-1) == a).astype(mx.float32))
        return lr_loss + ll_loss, {"r_loss": lr_loss, "l_loss": ll_loss, "r_acc": r_acc, "l_acc": l_acc}

    vg = nn.value_and_grad(nets, loss_fn)
    hist = []
    t0 = time.time()
    for step in range(1, cfg.steps + 1):
        i, t1, t2, y = sample_reach(ds, rng, cfg.batch, cfg.k_pos, cfg.k_neg)
        j, t, k, a = sample_loc(ds, rng, cfg.batch, cfg.k_loc)
        (loss, st), g = vg(nets, mx.array(ds.obs[i, t1]), mx.array(ds.obs[i, t2]), mx.array(y),
                           mx.array(ds.obs[j, t]), mx.array(ds.obs[j, t + k]), mx.array(a.astype(np.int32)))
        opt.update(nets, g)
        mx.eval(nets.parameters(), opt.state, loss, st)
        if step % cfg.log_every == 0 or step == 1:
            row = {"step": step, "sec": round(time.time() - t0, 1), **{kk: float(v) for kk, v in st.items()}}
            hist.append(row)
            log("  topo " + "  ".join(f"{kk}={v:.4g}" if isinstance(v, float) else f"{kk}={v}" for kk, v in row.items()))
    return nets, {"config": asdict(cfg), "params": n_params(nets), "train_sec": round(time.time() - t0, 1),
                  "history": hist}


# ---------------------------------------------------------------- 记忆图

FWD, REV, SAME, NEAR = 0, 1, 2, 3   # 边：沿前缀正向（重放记下的动作）、逆向（运动网络）、同一处（不用动）、学到的捷径（运动网络）


def obs_keys(obs: np.ndarray) -> list[bytes]:
    """观察的精确指纹。两帧观察完全相同才算「同一处」，这是对原始观察的比对，不用真值。"""
    return [np.ascontiguousarray(o).tobytes() for o in obs]


def build_graph(p_pair: np.ndarray, keys: list[bytes], cfg: TopoPlanConfig) -> list[list[tuple[int, float, int]]]:
    """p_pair：(n, n) 前缀各帧两两的 R 概率；keys：各帧观察指纹。返回有向带权邻接表 out[v] = [(u, 代价, 种类)]。"""
    n = p_pair.shape[0]
    out: list[list[tuple[int, float, int]]] = [[] for _ in range(n)]
    for v in range(n - 1):
        if keys[v] == keys[v + 1]:                   # 这一步观察没变（撞墙）
            out[v].append((v + 1, cfg.w_same, SAME))
            out[v + 1].append((v, cfg.w_same, SAME))
        else:
            out[v].append((v + 1, 1.0, FWD))
            out[v + 1].append((v, cfg.w_rev, REV))
    groups: dict[bytes, list[int]] = {}
    for v, k in enumerate(keys):
        groups.setdefault(k, []).append(v)
    for vs in groups.values():
        for a in vs:
            for b in vs:
                if a != b and abs(a - b) > 1:
                    out[a].append((b, cfg.w_same, SAME))
    if cfg.near:
        gap = np.abs(np.arange(n)[:, None] - np.arange(n)[None])
        ii, jj = np.nonzero((p_pair >= cfg.s_near) & (gap >= cfg.min_gap))
        for i, j in zip(ii.tolist(), jj.tolist()):
            if keys[i] != keys[j]:
                out[i].append((j, cfg.w_near, NEAR))
    return out


def dist_to(out: list[list[tuple[int, float, int]]], targets) -> np.ndarray:
    """Dijkstra：每个节点到目标集合的最小代价（到不了是 inf）。"""
    import heapq
    n = len(out)
    rev: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for v, es in enumerate(out):
        for u, w, _ in es:
            rev[u].append((v, w))
    d = np.full(n, np.inf)
    h = []
    for s in targets:
        d[s] = 0.0
        h.append((0.0, int(s)))
    heapq.heapify(h)
    while h:
        dv, v = heapq.heappop(h)
        if dv > d[v]:
            continue
        for u, w in rev[v]:
            if dv + w < d[u]:
                d[u] = dv + w
                heapq.heappush(h, (dv + w, u))
    return d


def hops(out, src: int, k: int) -> dict[int, int]:
    """不分方向，src 的 k 跳以内的节点及跳数；同一处的边不计跳数（0-1 BFS）。"""
    d = {src: 0}
    q = deque([src])
    while q:
        v = q.popleft()
        for u, _, kind in out[v]:
            du = d[v] + (0 if kind == SAME else 1)
            if du <= k and du < d.get(u, k + 1):
                d[u] = du
                if kind == SAME:
                    q.appendleft(u)
                else:
                    q.append(u)
    return d


def path_ahead(out, d: np.ndarray, cur: int, h: int) -> list[tuple[int, int]]:
    """从 cur 沿最短路走最多 h 条边，返回 [(下一个节点, 边的种类)]。并列时取编号大的（确定性）。"""
    path, v = [], cur
    for _ in range(h):
        if not np.isfinite(d[v]) or d[v] == 0:
            break
        best = None
        for u, w, kind in out[v]:
            c = w + d[u]
            if c <= d[v] + 1e-9 and (best is None or (c, -u) < (best[0], -best[1])):
                best = (c, u, kind)
        if best is None:
            break
        path.append((best[1], best[2]))
        v = best[1]
    return path


class TopoAgent:
    def __init__(self, nets: TopoNets, plan: TopoPlanConfig | None = None, seed: int = 0):
        self.nets = nets
        self.cfg = plan or TopoPlanConfig()
        self.rng = random.Random(seed)
        self.relocalizations = 0       # 预期节点附近找不到、改为全图重定位的次数（报告用；不叫 lost，免得和地图组的字段混）

    def _p(self, ea: mx.array, eb: mx.array) -> np.ndarray:
        return np.array(mx.sigmoid(self.nets.reach_logit(ea, eb)))

    def reset(self, ep) -> None:
        self.E = self.nets.embed(mx.array(ep.prefix_obs))                     # (n, emb)
        n = self.E.shape[0]
        self.acts = list(ep.prefix_acts)
        self.keys = obs_keys(ep.prefix_obs)
        self.by_key: dict[bytes, list[int]] = {}
        for v, k in enumerate(self.keys):
            self.by_key.setdefault(k, []).append(v)
        self.p_pair = self._p(self.E[:, None], self.E[None])                  # (n, n)
        self.out = build_graph(self.p_pair, self.keys, self.cfg)
        self.eg = self.nets.embed(mx.array(ep.goal_obs[None]))
        gk = obs_keys(ep.goal_obs[None])[0]
        if gk in self.by_key:                                                  # 前缀里有与目标画面完全相同的帧
            self.goal_nodes = np.array(self.by_key[gk])
        else:
            self.goal_nodes = np.array([int(np.argmax(self._p(self.eg, self.E)))])
        self.d_goal = dist_to(self.out, self.goal_nodes)
        self.cur = n - 1               # 任务从前缀终点出发
        self.expect = n - 1            # 上一步动作之后预期所在的节点
        self.first = True

    def _localize(self, key: bytes, p_cur: np.ndarray) -> None:
        c = self.cfg
        if self.first:                 # 第一帧就是前缀最后一帧
            self.first = False
            return
        near = hops(self.out, self.expect, c.loc_hops)
        same = self.by_key.get(key, [])
        if same:                       # 观察完全相同的帧：取离预期节点最近的；都不在附近就取第一个
            inn = [v for v in same if v in near]
            if inn:
                self.cur = min(inn, key=lambda v: (near[v], -v))
            else:
                self.relocalizations += 1
                self.cur = same[0]
            return
        cand = np.array(sorted(near))
        j = int(cand[int(np.argmax(p_cur[cand]))])
        if p_cur[j] >= c.s_loc:
            self.cur = j
            return
        self.relocalizations += 1
        j = int(np.argmax(p_cur))
        if p_cur[j] >= c.s_loc:
            self.cur = j

    def decide(self, obs: np.ndarray) -> tuple[str, int | None, mx.array]:
        """定位并决定这一步做什么。返回 (种类, 值, 当前嵌入)：
        ("random", 动作)、("replay", 动作)、("goto", 目标节点；None 表示目标画面本身)。"""
        c = self.cfg
        et = self.nets.embed(mx.array(obs[None]))
        p_cur = self._p(et, self.E)                                           # (n,)
        self._localize(obs_keys(obs[None])[0], p_cur)
        self.expect = self.cur
        if self.rng.random() < c.eps:
            return "random", self.rng.randrange(W.N_ACTIONS), et
        if float(self._p(et, self.eg).reshape(-1)[0]) >= c.s_reach:
            return "goto", None, et
        v = self.cur
        for u, kind in path_ahead(self.out, self.d_goal, self.cur, c.h_path):
            if kind == SAME:           # 同一处，不用动
                v = u
                continue
            if kind == FWD:            # 沿前缀正向：重放当时记下的动作（智能体自己的动作，不是真值）
                self.expect = u
                return "replay", int(self.acts[v]), et
            self.expect = v            # 逆向或学到的捷径：交给运动网络
            return "goto", u, et
        return "goto", None, et

    def act(self, obs: np.ndarray, view, head) -> int:
        kind, val, et = self.decide(obs)
        if kind in ("random", "replay"):
            return int(val)
        target = self.eg if val is None else self.E[val:val + 1]
        logits = np.array(self.nets.action_logits(et, target)).reshape(-1)
        return int(np.argmax(logits))


class TopoOracleControl(TopoAgent):
    """特权参照组（只报告，不进任何门，也不算「最好的潜空间组」的候选）。

    记忆图、定位、路径选择都与 latent_topo 完全相同，只是「goto」不用学到的运动网络，
    改用真值最短路走向目标节点所在的格（或目标格）。用来把差距拆开：
    latent_topo 与它的差，来自学到的运动网络；它与度量地图的差，来自记忆结构本身。
    """

    def reset(self, ep) -> None:
        super().reset(ep)
        self._rbfs: dict = {}

    def act_privileged(self, obs: np.ndarray, pose, layout: W.Layout, task: dict) -> int:
        kind, val, _ = self.decide(obs)
        if kind in ("random", "replay"):
            return int(val)
        g = task["goal"]
        p = task["prefix_poses"][val] if val is not None else g
        cell = (p[0], p[1])
        if cell not in self._rbfs:
            self._rbfs[cell] = W.reverse_bfs_to_cell(layout, cell)
        dm = self._rbfs[cell]
        return int(np.argmin([dm.get(W.step(layout, pose, a), 10 ** 6) for a in range(W.N_ACTIONS)]))
