"""前进一步会走多远：解析先验 + 学习残差（式 16 的门控混合），以及对照用的不门控版本。

输入是前方 RAY_LEN 格的折叠类型（未知/墙/冰/传送门/地板），输出类别：
0..RAY_LEN 表示沿朝向移动的格数，RAY_LEN+1 表示传送（去向不在射线上，要靠记忆）。

- 解析先验：前方一格不是墙就走 1 格，否则 0 格（未知按可走）。它不知道冰和传送门。
- 门控（gated）：门 m 判断「这里解析先验会错」，只在门开时用残差 r 的预测。残差只用事件样本训练。
- 不门控（ungated）：一个分类器对所有前进样本直接预测结果，不用先验。

训练标签是真实的前进结果。M2 里标签来自真值位姿，这是一项特权输入（M3 改成由重定位得到）。
"""
from __future__ import annotations

from dataclasses import dataclass
import random

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from . import world as W

N_OUT = W.RAY_LEN + 2
TELEPORT = W.RAY_LEN + 1


def analytic_outcome(rays: np.ndarray) -> np.ndarray:
    """rays: (..., RAY_LEN) 折叠类型。前方一格是墙就 0，否则 1。"""
    return np.where(rays[..., 0] == 1, 0, 1)


def _onehot(rays: np.ndarray) -> np.ndarray:
    return np.eye(W.RAY_CLASSES, dtype=np.float32)[rays].reshape(*rays.shape[:-1], -1)


class _MLP:
    """MLX 训练，numpy 推理（规划时一次要算几千个位姿，numpy 足够快）。"""

    def __init__(self, n_in: int, n_out: int, hidden: int = 64, seed: int = 0):
        mx.random.seed(seed)
        self.net = nn.Sequential(nn.Linear(n_in, hidden), nn.ReLU(), nn.Linear(hidden, n_out))
        mx.eval(self.net.parameters())

    def fit(self, x: np.ndarray, y: np.ndarray, steps: int = 600, lr: float = 3e-3, seed: int = 0) -> None:
        if len(x) == 0:
            return
        opt = optim.Adam(learning_rate=lr)
        xs, ys = mx.array(x), mx.array(y.astype(np.int32))
        rng = np.random.default_rng(seed)

        def loss_fn(m, xb, yb):
            return mx.mean(nn.losses.cross_entropy(m(xb), yb))

        vg = nn.value_and_grad(self.net, loss_fn)
        n = len(x)
        for _ in range(steps):
            idx = mx.array(rng.integers(0, n, min(256, n)))
            _, g = vg(self.net, xs[idx], ys[idx])
            opt.update(self.net, g)
            mx.eval(self.net.parameters(), opt.state)
        self.w = [(np.array(l.weight), np.array(l.bias)) for l in (self.net.layers[0], self.net.layers[2])]

    def logits(self, x: np.ndarray) -> np.ndarray:
        (w1, b1), (w2, b2) = self.w
        return np.maximum(x @ w1.T + b1, 0) @ w2.T + b2


@dataclass
class ForwardModel:
    kind: str                     # "analytic" / "gated" / "ungated"
    gate: _MLP | None = None
    resid: _MLP | None = None
    full: _MLP | None = None
    n_train: int = 0
    n_events: int = 0

    def predict(self, rays: np.ndarray) -> np.ndarray:
        prior = analytic_outcome(rays)
        if self.kind == "analytic":
            return prior
        x = _onehot(rays)
        flat = x.reshape(-1, x.shape[-1])
        if self.kind == "ungated":
            return self.full.logits(flat).argmax(-1).reshape(prior.shape)
        if self.resid is None:
            return prior
        m = self.gate.logits(flat).argmax(-1).reshape(prior.shape)
        r = self.resid.logits(flat).argmax(-1).reshape(prior.shape)
        return np.where(m == 1, r, prior)


def collect(cfg: W.Config, n_layouts: int, traj: int, horizon: int, seed0: int,
            mask_prob: float = 0.5, seed: int = 0, near_mask_prob: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """前进样本：射线（视野以外的格按 mask_prob 随机置为未知，模拟地图没看全）和真实结果。

    near_mask_prob > 0 时，视野内的近处格也按这个概率置为未知（增强：让模型见过「前方未知」的输入）。
    被遮住的格不改标签，标签仍是真实结果。
    """
    rng = random.Random(seed)
    xs, ys = [], []
    for i in range(n_layouts):
        layout = W.make_layout(seed0 + i, cfg)
        for _ in range(traj):
            poses, acts = W.walk(layout, W.random_pose(layout, rng), horizon, rng)
            for p, a in zip(poses, acts):
                if a != W.FORWARD:
                    continue
                r = W.ray(layout.grid, p)
                for k in range(cfg.view_radius, W.RAY_LEN):
                    if rng.random() < mask_prob:
                        r[k] = 0
                for k in range(0, cfg.view_radius):
                    if near_mask_prob and rng.random() < near_mask_prob:
                        r[k] = 0
                xs.append(r)
                ys.append(W.forward_outcome(layout, p))
    return np.asarray(xs, dtype=np.int64), np.asarray(ys, dtype=np.int64)


def fit(kind: str, rays: np.ndarray, out: np.ndarray, seed: int = 0, steps: int = 600) -> ForwardModel:
    fm = ForwardModel(kind=kind, n_train=len(rays))
    if kind == "analytic":
        return fm
    x = _onehot(rays)
    if kind == "ungated":
        fm.full = _MLP(x.shape[-1], N_OUT, seed=seed)
        fm.full.fit(x, out, steps=steps, seed=seed)
        return fm
    event = out != analytic_outcome(rays)
    fm.n_events = int(event.sum())
    fm.gate = _MLP(x.shape[-1], 2, seed=seed)
    fm.gate.fit(x, event.astype(np.int64), steps=steps, seed=seed)
    if event.any():
        fm.resid = _MLP(x.shape[-1], N_OUT, seed=seed + 1)
        fm.resid.fit(x[event], out[event], steps=steps, seed=seed + 1)
    return fm


def accuracy(fm: ForwardModel, rays: np.ndarray, out: np.ndarray) -> dict:
    pred = fm.predict(rays)
    event = out != analytic_outcome(rays)
    return {"all": float((pred == out).mean()),
            "event": float((pred[event] == out[event]).mean()) if event.any() else float("nan"),
            "non_event": float((pred[~event] == out[~event]).mean()),
            "n_event": int(event.sum()), "n": len(out)}


def collect_self(cfg: W.Config, n_layouts: int, traj: int, horizon: int, seed0: int,
                 seed: int = 0) -> tuple[np.ndarray, np.ndarray, dict]:
    """M3：不用真值位姿的前进样本。

    让只有解析先验的地图智能体在训练图上走同样的游走，射线取自它自己的地图（含未知格），
    标签取自它自己的定位：一致就是预测位移，射线上重定位成功就是射线上的位移，迷路就记传送。
    真值只用来统计标签对了多少（返回的 quality），不进训练。
    """
    from .agents import Episode
    from .mapagent import MapAgent
    rng = random.Random(seed)
    xs, ys, agree, total = [], [], 0, 0
    analytic = ForwardModel(kind="analytic")
    for i in range(n_layouts):
        layout = W.make_layout(seed0 + i, cfg)
        for _ in range(traj):
            poses, acts = W.walk(layout, W.random_pose(layout, rng), horizon, rng)
            views = [W.ego_view(layout, p) for p in poses]
            ag = MapAgent(cfg, analytic, memory=False)
            ag.forward_log = []
            ep = Episode(None, views, [p[2] for p in poses], list(acts), None, views[-1], poses[-1][2])
            ag.reset(ep)
            for r, lab, step in ag.forward_log:   # 迷路期间的前进不记录；按步号取真值，只用于统计
                xs.append(r)
                ys.append(lab)
                total += 1
                agree += int(lab == W.forward_outcome(layout, poses[step]))
    quality = {"n": total, "label_agreement_with_truth": agree / max(1, total)}
    return np.asarray(xs, dtype=np.int64), np.asarray(ys, dtype=np.int64), quality

