"""小模型（MLX）：编码器 + 动作条件预测器（JEPA + SIGReg）+ 可达性代价头。

设计要点（对应 r6 候选稿）：
- 预测空间：编码器 E 和预测器 F 只用潜空间预测损失（含 k 步滚动，式 15）和 SIGReg 训练，
  与 S2 的扁平 JEPA 臂同类。
- 规划代价与预测空间分开（r6 新增决定、式 14）：代价头 D 读 stop_gradient(z)，梯度不回传编码器。
  这样「潜空间欧氏距离」和「学到的可达性」比较的是同一个潜空间，只换代价。
- D 是拟度量（不对称，满足三角不等式）：d(x,y) = ||s(x)-s(y)|| + Σ relu(a(x)-a(y))。
  训练按 QRL 思路：一步转移的距离不超过 1、同轨迹 k 步的距离不超过 k，在此约束下把同一张图里
  随机配对的距离尽量撑大；极限下得到最短路距离。
"""
from __future__ import annotations

import math

import mlx.core as mx
import mlx.nn as nn
import numpy as np


def mlp(sizes: list[int], act=nn.GELU) -> nn.Sequential:
    layers = []
    for i in range(len(sizes) - 1):
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
        if i < len(sizes) - 2:
            layers.append(act())
    return nn.Sequential(*layers)


class WorldModel(nn.Module):
    def __init__(self, obs_dim: int, n_actions: int, z_dim: int = 64, hidden: int = 256,
                 s_dim: int = 64, a_dim: int = 32):
        super().__init__()
        self.n_actions = n_actions
        self.encoder = mlp([obs_dim, hidden, hidden, z_dim])
        self.predictor = mlp([z_dim + n_actions, hidden, hidden, z_dim])
        self.inverse = mlp([2 * z_dim, hidden, n_actions])   # 架构 §1：本层动作的逆动力学项
        self.cost_sym = mlp([z_dim, hidden, s_dim])
        self.cost_asym = mlp([z_dim, hidden, a_dim])

    # -- 预测
    def encode(self, obs: mx.array) -> mx.array:
        return self.encoder(obs)

    def predict(self, z: mx.array, a: mx.array) -> mx.array:
        oh = mx.eye(self.n_actions)[a]
        return z + self.predictor(mx.concatenate([z, oh], axis=-1))

    # -- 代价
    def cost_embed(self, z: mx.array) -> tuple[mx.array, mx.array]:
        z = mx.stop_gradient(z)
        return self.cost_sym(z), self.cost_asym(z)

    @staticmethod
    def quasi(sx: mx.array, ax: mx.array, sy: mx.array, ay: mx.array) -> mx.array:
        sym = mx.sqrt(mx.sum((sx - sy) ** 2, axis=-1) + 1e-8)
        asym = mx.sum(mx.maximum(ax - ay, 0.0), axis=-1)
        return sym + asym

    def reach(self, z_from: mx.array, z_to: mx.array) -> mx.array:
        sx, ax = self.cost_embed(z_from)
        sy, ay = self.cost_embed(z_to)
        return self.quasi(sx, ax, sy, ay)


def n_params(model: nn.Module) -> int:
    from mlx.utils import tree_flatten
    return sum(v.size for _, v in tree_flatten(model.parameters()))


# ---------------------------------------------------------------- SIGReg（与 S2 core_math 同式）

_KNOTS = np.linspace(0.2, 4.0, 17, dtype=np.float32)
_TRAPZ = np.full(17, (4.0 - 0.2) / 16, dtype=np.float32)
_TRAPZ[0] *= 0.5
_TRAPZ[-1] *= 0.5
_PHI0 = np.exp(-0.5 * _KNOTS ** 2).astype(np.float32)
_QW = (_TRAPZ * _PHI0).astype(np.float32)


def sigreg(z: mx.array, directions: mx.array) -> mx.array:
    """Epps–Pulley 正态性统计量，在随机单位方向上取平均。z: (N, D)，directions: (M, D)。"""
    x = z @ directions.T
    knots = mx.array(_KNOTS)
    tx = knots[:, None, None] * x[None]
    diff_cos = mx.mean(mx.cos(tx), axis=1) - mx.array(_PHI0)[:, None]
    mean_sin = mx.mean(mx.sin(tx), axis=1)
    stat = mx.sum(mx.array(_QW)[:, None] * (diff_cos ** 2 + mean_sin ** 2), axis=0)
    return mx.mean(stat)


def random_directions(rng: np.random.Generator, m: int, d: int) -> mx.array:
    v = rng.standard_normal((m, d)).astype(np.float32)
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return mx.array(v)


# ---------------------------------------------------------------- 损失

def world_loss(model: WorldModel, obs_seq: mx.array, act_seq: mx.array, dirs: mx.array,
               sigreg_w: float, inv_w: float = 1.0) -> tuple[mx.array, dict]:
    """obs_seq: (B, K+1, D)，act_seq: (B, K)。K 步滚动的潜空间预测损失 + SIGReg + 逆动力学。"""
    b, k1, d = obs_seq.shape
    k = k1 - 1
    z = model.encode(obs_seq.reshape(b * k1, d)).reshape(b, k1, -1)
    target = mx.stop_gradient(z[:, 1:])
    zh = z[:, 0]
    pred_losses = []
    for i in range(k):
        zh = model.predict(zh, act_seq[:, i])
        pred_losses.append(mx.mean(mx.sum((zh - target[:, i]) ** 2, axis=-1)))
    pred = sum(pred_losses) / k
    reg = sigreg(z.reshape(b * k1, -1), dirs)
    logits = model.inverse(mx.concatenate([z[:, :-1], z[:, 1:]], axis=-1))
    inv = mx.mean(nn.losses.cross_entropy(logits, act_seq))
    acc = mx.mean((mx.argmax(logits, axis=-1) == act_seq).astype(mx.float32))
    return pred + sigreg_w * reg + inv_w * inv, {"pred": pred, "pred1": pred_losses[0], "sigreg": reg,
                                                 "inv": inv, "inv_acc": acc}


def cost_loss(model: WorldModel, z_a: mx.array, z_b: mx.array, k: mx.array,
              z_r1: mx.array, z_r2: mx.array, lam: float, cap: float) -> tuple[mx.array, dict]:
    """z_a → z_b 在同一条轨迹上相隔 k 步（k ≥ 1）；(z_r1, z_r2) 是同一张图里的随机配对。

    约束：d(a, b) ≤ k（k=1 就是一步转移）。目标：随机配对的距离尽量大，在 cap 附近饱和。
    """
    d_ab = model.reach(z_a, z_b)
    viol = mx.maximum(d_ab - k, 0.0)
    constraint = mx.mean(viol ** 2)
    d_r = model.reach(z_r1, z_r2)
    beta = 0.1
    spread = mx.mean(-nn.softplus(beta * (cap - d_r)) / beta)
    loss = lam * constraint - spread
    return loss, {"constraint": constraint, "d_rand": mx.mean(d_r), "d_pos": mx.mean(d_ab)}


def softplus_inv(x: float) -> float:
    return math.log(math.expm1(x))
