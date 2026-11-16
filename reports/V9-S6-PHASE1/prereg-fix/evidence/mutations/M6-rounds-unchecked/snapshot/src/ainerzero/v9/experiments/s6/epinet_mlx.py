#!/usr/bin/env python3
"""S6 epinet MLX module: decoupled epinet on top of L-int dynamics.

Epinet (Osband et al., arXiv 2107.08924) on L-int:
  f(x, z) = mu(x) + sigma_L(sg[h], z) + PRIOR * sg[sigma_P(sg[h], z)]

Base network and epinet are trained decoupled:
  Total loss = rollout_loss(base) + epinet_loss(epinet on 1-step prediction)
Base network gradients are purely from rollout_loss, so base parameters evolve
identically to plain L-int dynamics without epinet under the same seed.
"""
from __future__ import annotations

import math
from typing import Any

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from mlx.utils import tree_flatten, tree_unflatten

from ainerzero.v9.experiments.s4 import learned_mlx as L

DZ = 8
KZ = 8
PRIOR = 1.0
EPI_HID = 32


class Epi(nn.Module):
    """Epinet multi-layer perceptron mapping [h, z] to 4 * DZ, projected with z."""

    def __init__(self, din: int):
        super().__init__()
        self.l1 = nn.Linear(din + DZ, EPI_HID)
        self.l2 = nn.Linear(EPI_HID, 4 * DZ)

    def __call__(self, h: mx.array, z: mx.array) -> mx.array:
        # h [B, n, H], z [B, DZ]
        B, n = h.shape[0], h.shape[1]
        zb = mx.broadcast_to(z[:, None, :], (B, n, DZ))
        inp = mx.concatenate([h, zb], axis=-1)
        g = self.l2(nn.relu(self.l1(inp))).reshape(B, n, 4, DZ)
        return (g * zb[:, :, None, :]).sum(axis=-1)


class EpiDynamics(L.Dynamics):
    """Dynamics model with learned epinet and frozen random prior network."""

    def __init__(self):
        super().__init__("L-int")
        self.epi = Epi(L.HID)
        self.prior = Epi(L.HID)
        self.prior.freeze()
        self.z: mx.array | None = None

    def hidden_out(
        self, p: mx.array, v: mx.array, pil: mx.array
    ) -> tuple[mx.array, mx.array, mx.array | None]:
        """Compute base hidden state, base output, and contact logits without epinet."""
        h = [L.node_features(p, v, pil)]
        logits, scal, _ = self.messages(p, v)
        h.append(scal)
        hid = nn.relu(self.up2(nn.relu(self.up1(mx.concatenate(h, axis=-1)))))
        return hid, self.out(hid), logits

    def __call__(
        self, p: mx.array, v: mx.array, pil: mx.array
    ) -> tuple[mx.array, mx.array, mx.array | None, mx.array | None]:
        hid, o, logits = self.hidden_out(p, v, pil)
        if self.z is not None:
            hs = mx.stop_gradient(hid)
            o = o + self.epi(hs, self.z) + PRIOR * mx.stop_gradient(self.prior(hs, self.z))
        p_next = p + v * L.DT + o[..., 0:2] * L.P_SCALE
        v_next = v + o[..., 2:4]
        return p_next, v_next, logits, None


def epinet_step_loss(model: EpiDynamics, batch: dict[str, mx.array], z: mx.array) -> mx.array:
    """1-step MSE loss for epinet: sg[mu(x)] + sigma_L + PRIOR*sigma_P against step-1 target.

    Position error is scaled by P_SCALE to match rollout_loss units.
    Base hidden states and base outputs are gradient-stopped, ensuring zero gradient to base.
    """
    p, v, pil = batch["p"], batch["v"], batch["pil"]
    p1, v1 = batch["p1"], batch["v1"]
    hid, o, _ = model.hidden_out(p, v, pil)
    hs = mx.stop_gradient(hid)
    pred = mx.stop_gradient(o) + model.epi(hs, z) + PRIOR * mx.stop_gradient(model.prior(hs, z))
    target = mx.concatenate([(p1 - p - v * L.DT) / L.P_SCALE, v1 - v], axis=-1)
    return ((pred - target) ** 2).mean()


def total_loss(model: EpiDynamics, batch: dict[str, mx.array], z: mx.array) -> mx.array:
    """Combined decoupled loss: rollout_loss for base + 1-step MSE for epinet."""
    old_z = model.z
    model.z = None
    lb = L.rollout_loss(model, batch)
    le = epinet_step_loss(model, batch, z)
    model.z = old_z
    return lb + le


def clip_parts(grads: Any) -> tuple[Any, mx.array]:
    """Clip base gradients and epinet gradients independently by L.CLIP."""
    flat = dict(tree_flatten(grads))
    base = {k: v for k, v in flat.items() if not k.startswith(("epi.", "prior."))}
    epi = {k: v for k, v in flat.items() if k.startswith(("epi.", "prior."))}
    base_clipped, norm_base = optim.clip_grad_norm(tree_unflatten(list(base.items())), max_norm=L.CLIP)
    epi_clipped, norm_epi = optim.clip_grad_norm(tree_unflatten(list(epi.items())), max_norm=L.CLIP)
    total_norm = mx.sqrt(norm_base ** 2 + norm_epi ** 2)
    clipped = tree_unflatten(list(dict(tree_flatten(base_clipped)).items()) + list(dict(tree_flatten(epi_clipped)).items()))
    return clipped, total_norm


def train(
    model: EpiDynamics,
    pool: Any,
    steps: int,
    batch: int = 256,
    seed: int = 0,
) -> list[float]:
    """Train EpiDynamics with decoupled base and epinet losses under Adam (lr=1e-3)."""
    mx.random.seed(seed)
    rng = np.random.default_rng(seed)
    opt = optim.Adam(learning_rate=1e-3)
    vg = nn.value_and_grad(model, total_loss)
    losses: list[float] = []

    for n, idx in L.batches(pool, steps, batch, rng, coll_share=0.0):
        b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
        # 每步每个样本重新抽 z
        z = mx.random.normal((len(idx), DZ))
        loss, grads = vg(model, b, z)
        clipped_grads, total_norm = clip_parts(grads)
        mx.eval(loss, total_norm)
        loss_val = float(loss.item())
        norm_val = float(total_norm.item())
        if not (math.isfinite(loss_val) and math.isfinite(norm_val)):
            raise ValueError(f"Non-finite loss or gradient encountered during training: loss={loss_val}, norm={norm_val}")

        opt.update(model, clipped_grads)
        mx.eval(model.parameters(), opt.state)
        losses.append(loss_val)

    model.z = None
    return losses


def spread(
    model: EpiDynamics,
    pool: Any,
    kz: int = KZ,
    index_seed: int = 1000,
) -> dict[int, np.ndarray] | np.ndarray:
    """Draw kz groups of z with fixed seeds and compute velocity spread per sample and disk.

    Returns the average distance of each member prediction to the ensemble mean:
      mean_k || v_pred_k - mean_v ||_2
    """
    old_z = model.z

    def _eval_spread(p_arr: mx.array, v_arr: mx.array, pil_arr: mx.array) -> np.ndarray:
        B = p_arr.shape[0]
        draws = []
        for k in range(kz):
            rng = np.random.default_rng(index_seed + k)
            z_k = mx.array(rng.normal(size=(B, DZ)).astype(np.float32))
            model.z = z_k
            _, v_next, _, _ = model(p_arr, v_arr, pil_arr)
            draws.append(np.array(v_next, dtype=np.float64))
        st = np.stack(draws, axis=0)  # [kz, B, n, 2]
        mean_v = st.mean(axis=0, keepdims=True)  # [1, B, n, 2]
        dist = np.linalg.norm(st - mean_v, axis=-1)  # [kz, B, n]
        return dist.mean(axis=0)  # [B, n]

    try:
        if hasattr(pool, "by_n"):
            out = {}
            for n, e in pool.by_n.items():
                p, v, pil = mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"])
                out[n] = _eval_spread(p, v, pil)
            return out
        else:
            p, v, pil = mx.array(pool["p"]), mx.array(pool["v"]), mx.array(pool["pil"])
            return _eval_spread(p, v, pil)
    finally:
        model.z = old_z
