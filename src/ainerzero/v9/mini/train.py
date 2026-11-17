"""训练：一个优化器同时训练预测（编码器 + 预测器）和代价头；代价头的梯度不进编码器。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import time

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from .data import Dataset
from .model import WorldModel, cost_loss, n_params, random_directions, world_loss


@dataclass
class TrainConfig:
    steps: int = 6000
    batch: int = 256
    rollout_k: int = 3          # 式 15：k 步滚动损失
    sigreg_w: float = 0.1
    sigreg_dirs: int = 64
    lr: float = 3e-4
    cost_cap: float = 60.0
    lam0: float = 100.0
    constraint_target: float = 0.02
    seed: int = 0
    log_every: int = 500


def _sample_world(ds: Dataset, rng: np.random.Generator, b: int, k: int):
    i = rng.integers(0, ds.n_traj, b)
    t = rng.integers(0, ds.horizon - k + 1, b)
    idx = t[:, None] + np.arange(k + 1)[None]
    obs = ds.obs[i[:, None], idx]
    act = ds.act[i[:, None], idx[:, :-1]]
    return mx.array(obs), mx.array(act)


def _sample_cost(ds: Dataset, rng: np.random.Generator, b: int, tpl: int):
    T = ds.horizon
    i = rng.integers(0, ds.n_traj, b)
    t = rng.integers(0, T, b)
    one = rng.random(b) < 0.5
    kmax = T - t
    k = np.where(one, 1, 1 + (rng.random(b) * kmax).astype(np.int64))
    k = np.minimum(k, kmax)
    a = ds.obs[i, t]
    bb = ds.obs[i, t + k]
    # 同一张图里的随机配对
    lid = ds.layout_id[i]
    j1 = lid * tpl + rng.integers(0, tpl, b)
    j2 = lid * tpl + rng.integers(0, tpl, b)
    r1 = ds.obs[j1, rng.integers(0, T + 1, b)]
    r2 = ds.obs[j2, rng.integers(0, T + 1, b)]
    return mx.array(a), mx.array(bb), mx.array(k.astype(np.float32)), mx.array(r1), mx.array(r2)


def train(ds: Dataset, tpl: int, cfg: TrainConfig, log=print) -> tuple[WorldModel, dict]:
    mx.random.seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    model = WorldModel(ds.obs.shape[-1], n_actions=3)
    mx.eval(model.parameters())
    opt = optim.AdamW(learning_rate=cfg.lr, weight_decay=1e-4)
    lam = cfg.lam0

    def loss_fn(m, obs, act, dirs, a, b, k, r1, r2, lam_arr):
        lw, sw = world_loss(m, obs, act, dirs, cfg.sigreg_w)
        z = m.encode(mx.concatenate([a, b, r1, r2], axis=0))
        n = a.shape[0]
        lc, sc = cost_loss(m, z[:n], z[n:2 * n], k, z[2 * n:3 * n], z[3 * n:], lam_arr, cfg.cost_cap)
        return lw + lc, {**sw, **sc}

    vg = nn.value_and_grad(model, loss_fn)
    history = []
    t0 = time.time()
    for step in range(1, cfg.steps + 1):
        obs, act = _sample_world(ds, rng, cfg.batch, cfg.rollout_k)
        a, b, k, r1, r2 = _sample_cost(ds, rng, cfg.batch, tpl)
        dirs = random_directions(rng, cfg.sigreg_dirs, model.encoder.layers[-1].weight.shape[0])
        (loss, stats), grads = vg(model, obs, act, dirs, a, b, k, r1, r2, mx.array(lam, dtype=mx.float32))
        opt.update(model, grads)
        mx.eval(model.parameters(), opt.state, loss, stats)
        c = float(stats["constraint"])
        lam = float(np.clip(lam * math.exp(0.02 * (1 if c > cfg.constraint_target else -1)), 1.0, 1e4))
        if step % cfg.log_every == 0 or step == 1:
            row = {"step": step, "loss": float(loss), "lam": lam, "sec": round(time.time() - t0, 1),
                   **{kk: float(v) for kk, v in stats.items()}}
            history.append(row)
            log("  ".join(f"{kk}={v:.4g}" if isinstance(v, float) else f"{kk}={v}" for kk, v in row.items()))
    info = {"config": asdict(cfg), "params": n_params(model), "train_sec": round(time.time() - t0, 1),
            "history": history}
    return model, info
