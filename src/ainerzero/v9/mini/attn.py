"""注意力记忆组（Transformer 读整段历史，2026-11-18 起探索，不算证据）。

latent_topo 之后，审稿人还会问的一类长记忆是「用注意力读整段历史」的策略（Scene Memory Transformer、
Episodic Transformer 一类）。这里给它一个尽量公平的版本：目标条件的离线 Q 学习，目标用 hindsight 重标记
（Kaelbling 1993；HER，Andrychowicz 等 2017），记忆是因果 Transformer 读完整历史（前缀 + 本回合已走的步）。

全部自监督：
- 输入只有观察（含指南针朝向）和智能体自己的上一步动作，不读真值位姿、不读真值距离；
- 「到达」= 当前观察与目标画面完全相同（与 latent_topo 的「同一处」一样，是对原始观察的比对）；
- 代价（步数）的训练目标：Q(h_t, a_t, g) = 1 + min_a' Q⁻(h_{t+1}, a', g)，下一帧就是目标时为 1；
  同一条游走里之后第一次看到目标画面的步数是这条轨迹实际用掉的步数，是上界，目标取两者的较小值。
  Q⁻ 是 Polyak 平均的目标网络。

训练数据：与其他组相同的训练图、相同的环境步数，只是把每张图的 tpl 条 horizon 步游走换成 1 条
tpl × horizon 步的游走（同一种持续性随机游走），训练时的上下文长度才能覆盖测试时的 400 步前缀加回合步数。

结构：
- 观察编码（MLP）加上一步动作的嵌入 → 因果 Transformer（RoPE，前置 LayerNorm）→ h_t；
- 目标读出：位置 t 用 [h_t, e_g] 作查询，对 ≤ t 的所有 [h_j, x_j]（x_j 是第 j 帧的输入嵌入）做一层多头注意力，
  再接 MLP 输出 3 个动作的代价。这一层让模型能在记忆里找到目标画面出现在哪里、之后怎么走的。
- 初始代价偏悲观（约 100 步）：自举取 min，值从高处往下收；若从低处起步，每次自举只能往上涨 1，
  6000 步内到不了长目标需要的量级（11-18 按最初 30 步的日志推算）。
- 测试：每一步把完整历史重新过一遍（不缓存），取最后一个位置的代价，选最小的动作；随机动作概率 0.05，
  与其他学到的组相同。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import random
import time

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
from mlx.utils import tree_map
import numpy as np

from . import data as D
from . import world as W
from .data import Dataset
from .model import mlp, n_params

NONE_ACTION = W.N_ACTIONS     # 窗口第一帧没有上一步动作


@dataclass
class AttnConfig:
    steps: int = 6000
    batch: int = 16          # 每步取几段窗口
    goals: int = 8           # 每段窗口配几个目标
    window: int = 600        # 训练窗口的帧数；测试时前缀 401 帧加回合步数（预算 2d*+20，约 ≤ 150）
    d: int = 128
    layers: int = 4
    heads: int = 4
    lr: float = 3e-4
    tau: float = 0.02        # 目标网络 Polyak 系数（0.01 时 6000 步代价还在降，11-18 探索）
    q_init: float = 100.0    # 初始代价偏悲观：自举取 min，从高处往下收，蒙特卡洛上界一来就生效
    cap: float = 200.0       # 代价上限
    scale: float = 10.0      # 代价的输出尺度：Q = 1 + scale·softplus(out)，Huber 按 (Q−y)/scale 算
    seed: int = 0
    log_every: int = 500


class Block(nn.Module):
    def __init__(self, d: int, heads: int):
        super().__init__()
        self.heads = heads
        self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
        self.qkv = nn.Linear(d, 3 * d, bias=False)
        self.o = nn.Linear(d, d, bias=False)
        self.ff = mlp([d, 4 * d, d])
        self.rope = nn.RoPE(d // heads)

    def __call__(self, x: mx.array) -> mx.array:
        B, L, d = x.shape
        H, dh = self.heads, d // self.heads
        q, k, v = mx.split(self.qkv(self.ln1(x)), 3, axis=-1)
        q, k, v = (t.reshape(B, L, H, dh).transpose(0, 2, 1, 3) for t in (q, k, v))
        q, k = self.rope(q), self.rope(k)
        a = mx.fast.scaled_dot_product_attention(q, k, v, scale=dh ** -0.5, mask="causal")
        x = x + self.o(a.transpose(0, 2, 1, 3).reshape(B, L, d))
        return x + self.ff(self.ln2(x))


class AttnNets(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int = W.N_ACTIONS, d: int = 128, layers: int = 4, heads: int = 4,
                 scale: float = 10.0, q_init: float = 100.0):
        super().__init__()
        self.heads, self.scale = heads, scale
        self.b0 = float(np.log(np.expm1((q_init - 1.0) / scale)))   # softplus 的反函数：输出为 0 时 Q = q_init
        self.obs_enc = mlp([obs_dim, 256, d])
        self.act_emb = nn.Embedding(n_actions + 1, d)
        self.blocks = [Block(d, heads) for _ in range(layers)]
        self.ln = nn.LayerNorm(d)
        self.goal_enc = mlp([obs_dim, 256, d])
        self.rq = nn.Linear(2 * d, d, bias=False)
        self.rk = nn.Linear(2 * d, d, bias=False)
        self.rv = nn.Linear(2 * d, d, bias=False)
        self.ro = nn.Linear(d, d)
        self.rope = nn.RoPE(d // heads)
        self.head = mlp([3 * d, 256, n_actions])

    def encode(self, obs: mx.array, prev_a: mx.array) -> tuple[mx.array, mx.array]:
        """obs: (B, L, D)，prev_a: (B, L)。返回 (h, x)，都是 (B, L, d)。"""
        x = self.obs_enc(obs) + self.act_emb(prev_a)
        h = x
        for blk in self.blocks:
            h = blk(h)
        return self.ln(h), x

    def q_values(self, h: mx.array, x: mx.array, og: mx.array, last_only: bool = False) -> mx.array:
        """og: (B, G, D) 目标观察。返回各动作的代价 (B, G, L, A)；last_only 时只算最后一个位置 (B, G, 1, A)。"""
        B, L, d = h.shape
        G = og.shape[1]
        H, dh = self.heads, d // self.heads
        eg = self.goal_enc(og)                                               # (B, G, d)
        hq = h[:, -1:] if last_only else h
        Lq = hq.shape[1]
        hb = mx.broadcast_to(hq[:, None], (B, G, Lq, d))
        gb = mx.broadcast_to(eg[:, :, None], (B, G, Lq, d))
        q = self.rq(mx.concatenate([hb, gb], axis=-1))                       # (B, G, Lq, d)
        q = q.reshape(B, G, Lq, H, dh).transpose(0, 3, 1, 2, 4).reshape(B, H * G, Lq, dh)   # 查询头按 [头, 目标] 排，对应 GQA 的分组
        kv = mx.concatenate([h, x], axis=-1)
        k = self.rk(kv).reshape(B, L, H, dh).transpose(0, 2, 1, 3)
        v = self.rv(kv).reshape(B, L, H, dh).transpose(0, 2, 1, 3)
        k = self.rope(k)
        if last_only:
            q = self.rope(q, offset=L - 1)
            r = mx.fast.scaled_dot_product_attention(q, k, v, scale=dh ** -0.5)
        else:
            q = self.rope(q)
            r = mx.fast.scaled_dot_product_attention(q, k, v, scale=dh ** -0.5, mask="causal")
        r = r.reshape(B, H, G, Lq, dh).transpose(0, 2, 3, 1, 4).reshape(B, G, Lq, d)
        out = self.head(mx.concatenate([hb, gb, self.ro(r)], axis=-1))
        return 1.0 + self.scale * nn.softplus(out + self.b0)


# ---------------------------------------------------------------- 数据与标签（不用真值）

def long_walks(cfg: W.Config, layouts: int, tpl: int, horizon: int, seed0: int = D.TRAIN_SEED0) -> Dataset:
    """与 data.generate 相同的训练图、相同的环境步数，每张图 1 条 tpl × horizon 步的游走。"""
    return D.generate(layouts, 1, tpl * horizon, cfg, seed0=seed0)


def obs_ids(obs: np.ndarray) -> np.ndarray:
    """(N, T+1, D) → (N, T+1) 整数编号：观察完全相同的帧编号相同（对原始观察的精确比对）。"""
    table: dict[bytes, int] = {}
    flat = obs.reshape(-1, obs.shape[-1])
    ids = np.empty(len(flat), dtype=np.int64)
    for n, o in enumerate(flat):
        ids[n] = table.setdefault(np.ascontiguousarray(o).tobytes(), len(table))
    return ids.reshape(obs.shape[:-1])


def hindsight_labels(wid: np.ndarray, gid: np.ndarray):
    """wid: (B, L) 窗口内各帧的观察编号；gid: (B, G) 目标的观察编号。

    返回（都是 (B, G, L−1)，对应位置 t = 0..L−2 上执行 a_t 之后）：
    - ub：t 之后第一次看到目标画面用掉的步数（看不到为 inf），是代价的上界；
    - done：下一帧就是目标画面；
    - valid：t 这一帧还不是目标画面（已经到了的帧不参与训练，测试时也不会在那里决策）。
    """
    B, L = wid.shape
    eq = wid[:, None, :] == gid[:, :, None]                                  # (B, G, L)
    pos = np.where(eq, np.arange(L)[None, None], np.iinfo(np.int64).max)
    nxt = np.minimum.accumulate(pos[..., ::-1], axis=-1)[..., ::-1]          # nxt[t] = t 及之后第一次出现
    nxt_after = nxt[..., 1:]                                                 # t+1 及之后
    t = np.arange(L - 1)[None, None]
    ub = np.where(nxt_after < np.iinfo(np.int64).max, nxt_after - t, np.inf).astype(np.float64)
    return ub, eq[..., 1:], ~eq[..., :-1]


def compose_target(v_next: np.ndarray, done: np.ndarray, ub: np.ndarray, cap: float) -> np.ndarray:
    """y = min(下一帧是目标 ? 1 : 1 + min_a' Q⁻(t+1), 上界, cap)。"""
    y = np.where(done, 1.0, 1.0 + v_next)
    return np.minimum(np.minimum(y, ub), cap)


def sample_batch(ds: Dataset, ids: np.ndarray, rng: np.random.Generator, B: int, G: int, L: int):
    T1 = ds.obs.shape[1]
    if L > T1:
        raise ValueError("窗口比游走长")
    i = rng.integers(0, ds.n_traj, B)
    s = rng.integers(0, T1 - L + 1, B)
    idx = s[:, None] + np.arange(L)[None]
    obs = ds.obs[i[:, None], idx]                                            # (B, L, D)
    acts = ds.act[i[:, None], idx[:, :-1]]                                   # (B, L−1)，a_t
    prev = np.concatenate([np.full((B, 1), NONE_ACTION), acts], axis=1)      # 窗口第一帧没有上一步动作
    wid = ids[i[:, None], idx]
    gpos = rng.integers(0, L, (B, G))
    og = obs[np.arange(B)[:, None], gpos]                                     # (B, G, D)
    gid = wid[np.arange(B)[:, None], gpos]
    return obs, acts, prev, og, wid, gid


def train_attn(ds: Dataset, cfg: AttnConfig, log=print, on_step=None) -> tuple[AttnNets, dict]:
    """ds 只读 obs 和 act。on_step(step, net)：每步结束后调用（探索时存检查点用）。"""
    mx.random.seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed + 9_191)
    D_ = ds.obs.shape[-1]
    kw = dict(d=cfg.d, layers=cfg.layers, heads=cfg.heads, scale=cfg.scale, q_init=cfg.q_init)
    net, tgt = AttnNets(D_, **kw), AttnNets(D_, **kw)
    mx.eval(net.parameters())
    tgt.update(tree_map(lambda p: mx.array(p), net.parameters()))
    mx.eval(tgt.parameters())
    opt = optim.AdamW(learning_rate=cfg.lr, weight_decay=1e-4)
    ids = obs_ids(ds.obs)

    def loss_fn(m, obs, prev, og, acts, y, mask):
        h, x = m.encode(obs, prev)
        q = m.q_values(h, x, og)[:, :, :-1]                                  # (B, G, L−1, A)
        a = mx.broadcast_to(acts[:, None, :, None], q.shape[:-1] + (1,))
        qa = mx.take_along_axis(q, a, axis=-1)[..., 0]
        err = nn.losses.huber_loss(qa / cfg.scale, y / cfg.scale, reduction="none")
        return mx.sum(err * mask) / mx.maximum(mx.sum(mask), 1.0), mx.sum(qa * mask) / mx.maximum(mx.sum(mask), 1.0)

    vg = nn.value_and_grad(net, loss_fn)
    hist = []
    t0 = time.time()
    for step in range(1, cfg.steps + 1):
        obs, acts, prev, og, wid, gid = sample_batch(ds, ids, rng, cfg.batch, cfg.goals, cfg.window)
        ub, done, valid = hindsight_labels(wid, gid)
        o_m, p_m, g_m = mx.array(obs), mx.array(prev.astype(np.int32)), mx.array(og)
        ht, xt = tgt.encode(o_m, p_m)
        v_next = np.array(mx.min(tgt.q_values(ht, xt, g_m)[:, :, 1:], axis=-1))
        y = compose_target(v_next, done, ub, cfg.cap)
        (loss, qmean), g = vg(net, o_m, p_m, g_m, mx.array(acts.astype(np.int32)), mx.array(y.astype(np.float32)),
                              mx.array(valid.astype(np.float32)))
        opt.update(net, g)
        tgt.update(tree_map(lambda a, b: (1.0 - cfg.tau) * a + cfg.tau * b, tgt.parameters(), net.parameters()))
        mx.eval(net.parameters(), tgt.parameters(), opt.state, loss, qmean)
        if step % cfg.log_every == 0 or step == 1:
            m = valid
            row = {"step": step, "sec": round(time.time() - t0, 1), "loss": float(loss), "q_mean": float(qmean),
                   "y_mean": float(y[m].mean()), "ub_binds": float((ub[m] <= np.where(done, 1.0, 1.0 + v_next)[m]).mean()),
                   "ub_known": float(np.isfinite(ub[m]).mean())}
            hist.append(row)
            log("  attn " + "  ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in row.items()))
        if on_step is not None:
            on_step(step, net)
    return net, {"config": asdict(cfg), "params": n_params(net), "train_sec": round(time.time() - t0, 1),
                 "data": {"n_traj": int(ds.n_traj), "horizon": int(ds.horizon)}, "history": hist}


# ---------------------------------------------------------------- 智能体

class AttnAgent:
    def __init__(self, nets: AttnNets, eps: float = 0.05, seed: int = 0):
        self.nets, self.eps = nets, eps
        self.rng = random.Random(seed)

    def reset(self, ep) -> None:
        self.obs = [np.asarray(o, dtype=np.float32) for o in ep.prefix_obs]
        self.prev = [NONE_ACTION] + [int(a) for a in ep.prefix_acts]
        self.og = mx.array(np.asarray(ep.goal_obs, dtype=np.float32)[None, None])
        self.first = True
        self.last = None

    def q_last(self) -> np.ndarray:
        h, x = self.nets.encode(mx.array(np.stack(self.obs)[None]), mx.array(np.array([self.prev], dtype=np.int32)))
        return np.array(self.nets.q_values(h, x, self.og, last_only=True)).reshape(-1)

    def act(self, obs: np.ndarray, view, head) -> int:
        if not self.first:          # 前缀最后一帧就是任务第一帧，已经在历史里
            self.obs.append(np.asarray(obs, dtype=np.float32))
            self.prev.append(self.last)
        self.first = False
        if self.rng.random() < self.eps:
            a = self.rng.randrange(W.N_ACTIONS)
        else:
            q = self.q_last() + 1e-6 * np.array([self.rng.random() for _ in range(W.N_ACTIONS)])
            a = int(np.argmin(q))
        self.last = a
        return a
