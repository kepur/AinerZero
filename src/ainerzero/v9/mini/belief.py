"""M1 的记忆臂：GRU 信念 + 接在信念上的可达性代价（整块学习的记忆，对照「地图即记忆」）。

- 信念 b_t = GRU(b_{t-1}, [z_t, 上一个动作])，z_t 是世界模型编码器的输出（stop_gradient，不改预测空间）。
- 代价 d(b_t, z_g)：信念一侧和目标一侧各有投影，组合方式同拟度量头。
  训练信号：同一条轨迹上 t → t+k 的距离不超过 k；同一张图里的随机配对尽量撑大。
- 规划：同一个 27 条序列的树搜索，信念按预测的潜状态往前推（S2 收口报告 §8 的「规划时带着 GRU 状态往前推」）。
"""
from __future__ import annotations

import itertools
import math
import random

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from . import world as W
from .data import Dataset
from .model import WorldModel, mlp

NONE_ACTION = 3


class Belief(nn.Module):
    def __init__(self, z_dim: int = 64, hidden: int = 128, s_dim: int = 64, a_dim: int = 32):
        super().__init__()
        self.gru = nn.GRU(z_dim + 4, hidden)
        self.bs, self.ba = mlp([hidden, 256, s_dim]), mlp([hidden, 256, a_dim])
        self.gs, self.ga = mlp([z_dim, 256, s_dim]), mlp([z_dim, 256, a_dim])

    def run(self, z: mx.array, prev_a: mx.array, h: mx.array | None = None) -> mx.array:
        """z: (B, L, Z)，prev_a: (B, L) 上一步动作（第一步用 NONE_ACTION）。返回 (B, L, H)。"""
        x = mx.concatenate([z, mx.eye(4)[prev_a]], axis=-1)
        return self.gru(x, hidden=h)

    def cost(self, b: mx.array, zg: mx.array) -> mx.array:
        sx, ax = self.bs(b), self.ba(b)
        sy, ay = self.gs(zg), self.ga(zg)
        return mx.sqrt(mx.sum((sx - sy) ** 2, axis=-1) + 1e-8) + mx.sum(mx.maximum(ax - ay, 0.0), axis=-1)


def train_belief(wm: WorldModel, ds: Dataset, tpl: int, steps: int = 1500, batch: int = 32, seed: int = 0,
                 cap: float = 60.0, log=print) -> tuple[Belief, dict]:
    mx.random.seed(seed)
    rng = np.random.default_rng(seed)
    bel = Belief(z_dim=wm.encoder.layers[-1].weight.shape[0])
    mx.eval(bel.parameters())
    opt = optim.AdamW(learning_rate=3e-4, weight_decay=1e-4)
    T = ds.horizon
    lam = 100.0

    def loss_fn(m, z, pa, tb, kk, zr_idx, zr_lay, lam_arr):
        b = m.run(z, pa)                                     # (B, T+1, H)
        B = z.shape[0]
        bi = mx.arange(B)[:, None]
        bt = b[bi, tb]                                       # (B, P, H)
        zt = z[bi, tb + kk]
        d = m.cost(bt, zt)
        viol = mx.maximum(d - kk.astype(mx.float32), 0.0)
        constraint = mx.mean(viol ** 2)
        zr = z[zr_lay, zr_idx]                               # 同一张图的随机观察
        dr = m.cost(bt, zr)
        spread = mx.mean(-nn.softplus(0.1 * (cap - dr)) / 0.1)
        return lam_arr * constraint - spread, (constraint, mx.mean(dr))

    vg = nn.value_and_grad(bel, loss_fn)
    hist = []
    P = 16
    for step in range(1, steps + 1):
        # 按图取 batch：每张图取 2 条轨迹，随机配对从同图另一条里取
        lays = rng.integers(0, ds.n_traj // tpl, batch // 2)
        idx = np.concatenate([lays * tpl + rng.integers(0, tpl, len(lays)), lays * tpl + rng.integers(0, tpl, len(lays))])
        z = mx.stop_gradient(wm.encode(mx.array(ds.obs[idx])))
        pa = np.concatenate([np.full((len(idx), 1), NONE_ACTION), ds.act[idx]], axis=1)
        tb = rng.integers(0, T, (len(idx), P))
        one = rng.random((len(idx), P)) < 0.3
        kk = np.where(one, 1, 1 + (rng.random((len(idx), P)) * (T - tb)).astype(np.int64))
        kk = np.minimum(kk, T - tb)
        partner = np.concatenate([np.arange(len(lays)) + len(lays), np.arange(len(lays))])
        zr_lay = np.repeat(partner[:, None], P, axis=1)
        zr_idx = rng.integers(0, T + 1, (len(idx), P))
        (loss, (c, dr)), g = vg(bel, z, mx.array(pa), mx.array(tb), mx.array(kk), mx.array(zr_idx),
                                mx.array(zr_lay), mx.array(lam, dtype=mx.float32))
        opt.update(bel, g)
        mx.eval(bel.parameters(), opt.state, loss)
        lam = float(np.clip(lam * math.exp(0.02 * (1 if float(c) > 0.02 else -1)), 1.0, 1e4))
        if step % 500 == 0 or step == 1:
            row = {"step": step, "constraint": float(c), "d_rand": float(dr), "lam": lam}
            hist.append(row)
            log(f"  belief {row}")
    return bel, {"history": hist}


class BeliefTree:
    """GRU 信念上的树搜索：只换「记忆」，规划器和世界模型与 LatentTree 相同。"""

    def __init__(self, wm: WorldModel, bel: Belief, horizon: int = 3, eps: float = 0.05, seed: int = 0):
        self.wm, self.bel, self.eps = wm, bel, eps
        self.rng = random.Random(seed)
        self.seqs = mx.array(np.array(list(itertools.product(range(W.N_ACTIONS), repeat=horizon)), dtype=np.int32))
        self.horizon = horizon

    def reset(self, ep) -> None:
        z = self.wm.encode(mx.array(ep.prefix_obs))[None]
        pa = mx.array(np.array([[NONE_ACTION] + list(ep.prefix_acts)], dtype=np.int32))
        hs = self.bel.run(z, pa)
        self.h = hs[:, -1]
        self.zg = self.wm.encode(mx.array(ep.goal_obs[None]))
        self.last = None
        self.first = True

    def act(self, obs, view, head) -> int:
        z = self.wm.encode(mx.array(obs[None]))
        if not self.first:   # 前缀最后一帧就是任务第一帧，已经在信念里
            self.h = self.bel.run(z[:, None], mx.array([[self.last]]), self.h)[:, -1]
        self.first = False
        if self.rng.random() < self.eps:
            a = self.rng.randrange(W.N_ACTIONS)
        else:
            n = self.seqs.shape[0]
            zz = mx.broadcast_to(z, (n, z.shape[-1]))
            hh = mx.broadcast_to(self.h, (n, self.h.shape[-1]))
            zg = mx.broadcast_to(self.zg, zz.shape)
            total = mx.zeros((n,))
            for i in range(self.horizon):
                a_i = self.seqs[:, i]
                zz = self.wm.predict(zz, a_i)
                hh = self.bel.run(zz[:, None], a_i[:, None], hh)[:, -1]
                total = total + self.bel.cost(hh, zg)
            tot = np.array(total) + 1e-6 * np.array([self.rng.random() for _ in range(n)])
            a = int(np.array(self.seqs)[int(np.argmin(tot)), 0])
        self.last = a
        return a
