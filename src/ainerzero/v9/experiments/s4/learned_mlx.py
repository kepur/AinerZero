"""S4 phase 1 learned dynamics in MLX (DESIGN-r3 §3).

Arms:
  L-ind      per-disk MLP: own state plus wall and pillar geometry; never sees another disk
  L-int      L-ind plus pairwise message passing within MSG_RADIUS, and a pairwise contact head
  L-int-c    as L-int, messages computed in the frame from sender to receiver and rotated back
  L-int-s    (L-int-σ) the mean of a trained L-int, frozen, plus a variance head (log-variance of the
             next position and velocity) trained on visible-noise inputs against the true next state;
             a descriptive arm for calibration only

Code constraint (DESIGN-r3 §3): no analytic collision response. The models see geometry
(distances, relative positions and velocities) and learn every bounce and impulse; nothing here
reflects or exchanges velocities, and this module does not import the world's physics.

Training pairs are built in NumPy by ``make_pool`` (the simulator is passed in and only labels
perturbed states) and ``make_sigma_pool``; both group samples by disk count, so batches need no
padding.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Sequence

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

ARENA = 10.0
RADIUS = 0.3
DT = 0.1
N_PILLARS = 3
MSG_RADIUS = 1.5
NODE_F = 4 + 4 + 4 * N_PILLARS   # state, wall gaps, pillar geometry
HID = 128
MSG = 64
ARMS = ("L-ind", "L-int", "L-int-c", "L-int-s")
MEAN_ARMS = ("L-ind", "L-int", "L-int-c")
P_SCALE = 0.1                   # position error scale in the loss
LOGVAR_RANGE = (-15.0, 5.0)
ROLLOUT = (1, 5, 10)
CONTACT_WEIGHT = 0.1
COLL_SHARE = 0.5                # share of each mean-arm batch drawn from samples with a disk contact at step 1
NEAR_SHARE = 0.0                # share drawn from near misses: no disk contact at step 1, a pair ending it within NEAR_GAP
NEAR_GAP = 2 * RADIUS + 0.3     # centre distance after step 1 that counts as a near miss
CLIP = 10.0                     # global gradient-norm clip
LR_END = None                   # None: constant learning rate; a number: cosine decay to it over the training steps
EPS_DIR = 0.01                  # softening of the pair direction in L-int-c: bounded at coincident disks

# perturbation rules (DESIGN-r3 §3)
P_HIDDEN = 0.7
VISIBLE_SIGMA = (0.05, 0.2)     # position, velocity
HIDDEN_SIGMA = (0.7, 0.6)
P_DROP = 0.1
GHOSTS = 0.3                    # Poisson mean
GHOST_SIGMA = 0.3
EXACT_FRAC = 0.2


# --- features (MLX, differentiable through rollouts) --------------------------------------------
def node_features(p: mx.array, v: mx.array, pil: mx.array) -> mx.array:
    """p, v [B, n, 2]; pil [B, 3, 3] (cx, cy, r). Returns [B, n, NODE_F]."""
    x, y = p[..., 0:1], p[..., 1:2]
    walls = mx.concatenate([(x - RADIUS), (ARENA - RADIUS - x), (y - RADIUS), (ARENA - RADIUS - y)], -1) / ARENA
    c = pil[:, None, :, :2]                                    # [B, 1, 3, 2]
    r = pil[:, None, :, 2:3]                                   # [B, 1, 3, 1]
    rel = c - p[:, :, None, :]                                 # [B, n, 3, 2]
    dist = mx.sqrt((rel ** 2).sum(-1, keepdims=True) + 1e-12)
    gap = dist - r - RADIUS
    rb = mx.broadcast_to(r, gap.shape)
    pg = mx.concatenate([rel / ARENA, gap / ARENA, rb / ARENA], -1).reshape(p.shape[0], p.shape[1], 4 * N_PILLARS)
    return mx.concatenate([p / ARENA, v, walls, pg], -1)


def pair_geometry(p: mx.array, v: mx.array):
    """dp[b, i, j] = p_j - p_i, dv = v_j - v_i, dist, mask (i != j and dist < MSG_RADIUS)."""
    dp = p[:, None, :, :] - p[:, :, None, :]
    dv = v[:, None, :, :] - v[:, :, None, :]
    dist = mx.sqrt((dp ** 2).sum(-1, keepdims=True) + 1e-12)
    n = p.shape[1]
    eye = mx.eye(n)[None, :, :, None]
    mask = (dist < MSG_RADIUS) * (1 - eye)
    return dp, dv, dist, mask


class Dynamics(nn.Module):
    def __init__(self, arm: str):
        super().__init__()
        if arm not in ARMS:
            raise ValueError(f"unknown arm {arm!r}")
        self.arm = arm
        self.interact = arm != "L-ind"
        self.canonical = arm == "L-int-c"
        extra = 0
        if self.interact:
            pin = 4 if self.canonical else 6
            self.msg1 = nn.Linear(pin, MSG)
            self.msg2 = nn.Linear(MSG, MSG)
            self.contact = nn.Linear(MSG, 1)
            extra = MSG + (2 if self.canonical else 0)
            if self.canonical:
                self.msg_vec = nn.Linear(MSG, 2)
        self.up1 = nn.Linear(NODE_F + extra, HID)
        self.up2 = nn.Linear(HID, HID)
        self.out = nn.Linear(HID, 4)
        if arm == "L-int-s":
            self.var1 = nn.Linear(HID, HID)
            self.var2 = nn.Linear(HID, 4)

    def messages(self, p: mx.array, v: mx.array):
        """(contact logits [B, n, n], summed scalar messages [B, n, MSG], summed vector messages [B, n, 2] or None)."""
        dp, dv, dist, mask = pair_geometry(p, v)
        if self.canonical:
            # direction receiver -> sender (dp = p_j - p_i), softened so that coincident disks (perturbed
            # inputs clipped into the same corner) do not give an unbounded Jacobian; |e| > 0.999 at contact
            e = dp / mx.sqrt((dp ** 2).sum(-1, keepdims=True) + EPS_DIR ** 2)
            eperp = mx.concatenate([-e[..., 1:2], e[..., 0:1]], -1)
            dv_loc = mx.concatenate([(dv * e).sum(-1, keepdims=True), (dv * eperp).sum(-1, keepdims=True)], -1)
            x = mx.concatenate([dist, dist - 2 * RADIUS, dv_loc], -1)
        else:
            x = mx.concatenate([dp, dv, dist, dist - 2 * RADIUS], -1)
        m = nn.relu(self.msg2(nn.relu(self.msg1(x))))       # [B, i, j, MSG]
        logits = self.contact(m)[..., 0]
        scal = (m * mask).sum(2)
        vec = None
        if self.canonical:
            w = self.msg_vec(m)                              # local (along e, along eperp)
            vec = ((w[..., 0:1] * e + w[..., 1:2] * eperp) * mask).sum(2)
        return logits, scal, vec

    def __call__(self, p: mx.array, v: mx.array, pil: mx.array):
        """Returns (p_next, v_next, contact_logits [B, n, n] or None, log_var [B, n, 4] or None)."""
        h = [node_features(p, v, pil)]
        logits = None
        if self.interact:
            logits, scal, vec = self.messages(p, v)
            h.append(scal)
            if vec is not None:
                h.append(vec)
        z = nn.relu(self.up2(nn.relu(self.up1(mx.concatenate(h, -1)))))
        o = self.out(z)
        v_next = v + o[..., 2:4]
        p_next = p + v * DT + o[..., 0:2] * P_SCALE
        logvar = None
        if self.arm == "L-int-s":
            logvar = mx.clip(self.var2(nn.relu(self.var1(mx.stop_gradient(z)))), *LOGVAR_RANGE)
        return p_next, v_next, logits, logvar


def param_count(model: nn.Module) -> int:
    from mlx.utils import tree_flatten

    return sum(x.size for _, x in tree_flatten(model.parameters()))


# --- training pools (NumPy; the simulator only labels perturbed states) ---------------------------
@dataclass(frozen=True)
class Pool:
    """Samples grouped by disk count n. Mean pools: p, v [S, n, 2], pil [S, 3, 3], labels p{k}, v{k}
    for k in ROLLOUT and contact [S, n, n] at step 1. Sigma pools: p, v, pil, tp, tv (true next state)."""
    by_n: dict[int, dict[str, np.ndarray]]

    def size(self) -> int:
        return sum(len(e["p"]) for e in self.by_n.values())


def perturb(pos, vel, rng, *, exact: bool):
    """DESIGN-r3 §3: per-disk visible (0.3) or hidden (0.7) noise, 10% dropped, Poisson(0.3) ghosts; or no change."""
    pos, vel = pos.copy(), vel.copy()
    if exact:
        return pos, vel
    hidden = rng.random(len(pos)) < P_HIDDEN
    sp = np.where(hidden, HIDDEN_SIGMA[0], VISIBLE_SIGMA[0])[:, None]
    sv = np.where(hidden, HIDDEN_SIGMA[1], VISIBLE_SIGMA[1])[:, None]
    pos = pos + rng.normal(0, 1, pos.shape) * sp
    vel = vel + rng.normal(0, 1, vel.shape) * sv
    keep = rng.random(len(pos)) >= P_DROP
    if keep.sum() < 2:
        keep[:2] = True
    pos, vel = pos[keep], vel[keep]
    for _ in range(rng.poisson(GHOSTS)):
        k = rng.integers(len(pos))
        pos = np.vstack([pos, pos[k] + rng.normal(0, GHOST_SIGMA, 2)])
        vel = np.vstack([vel, vel[k]])
    pos = np.clip(pos, RADIUS, ARENA - RADIUS)
    return pos, vel


def make_pool(episodes: Sequence, n_samples: int, rng: np.random.Generator, physics, *, exact_frac: float = EXACT_FRAC) -> Pool:
    """Draw states from the episodes, perturb them, label with ``physics`` rolled out 1, 5 and 10 steps.

    Step 1 runs per sample (the simulator logs contacts of its first copy only); steps 2-10 run
    batched over the samples of one episode with one disk count."""
    draws = []
    for _ in range(n_samples):
        e = int(rng.integers(len(episodes)))
        s = episodes[e].steps[int(rng.integers(len(episodes[e].steps)))]
        pos, vel = perturb(s.positions, s.velocities, rng, exact=rng.random() < exact_frac)
        draws.append((e, pos, vel))
    groups: dict[tuple[int, int], list[int]] = {}
    for i, (e, pos, _) in enumerate(draws):
        groups.setdefault((len(pos), e), []).append(i)
    rows: dict[int, dict[str, list]] = {}
    for (n, e), idx in sorted(groups.items()):
        pillars = tuple(map(tuple, episodes[e].pillars))
        P = np.stack([draws[i][1] for i in idx]); V = np.stack([draws[i][2] for i in idx])
        contact = np.zeros((len(idx), n, n), dtype=np.float32)
        p1, v1 = np.empty_like(P), np.empty_like(V)
        for b in range(len(idx)):
            pb, vb, c = physics(P[b:b + 1], V[b:b + 1], pillars, log=True)
            p1[b], v1[b] = pb[0], vb[0]
            for kind, i, j in c:
                if kind == "disk":
                    contact[b, i, j] = contact[b, j, i] = 1.0
        out = rows.setdefault(n, {"p": [], "v": [], "pil": [], "contact": [], **{f"{x}{k}": [] for k in ROLLOUT for x in "pv"}})
        out["p"].append(P); out["v"].append(V); out["contact"].append(contact)
        out["pil"].append(np.broadcast_to(np.array(pillars, dtype=np.float64), (len(idx), N_PILLARS, 3)))
        p, v = p1, v1
        for k in range(1, max(ROLLOUT) + 1):
            if k > 1:
                p, v, _ = physics(p, v, pillars)
            if k in ROLLOUT:
                out[f"p{k}"].append(p); out[f"v{k}"].append(v)
    return Pool({n: {key: np.concatenate(val).astype(np.float32) for key, val in d.items()} for n, d in sorted(rows.items())})


def make_sigma_pool(episodes: Sequence, n_samples: int, rng: np.random.Generator) -> Pool:
    """L-int-σ pairs: the true state plus visible-track noise, against the true next state."""
    rows: dict[int, dict[str, list]] = {}
    for _ in range(n_samples):
        ep = episodes[int(rng.integers(len(episodes)))]
        t = int(rng.integers(len(ep.steps) - 1))
        s, nxt = ep.steps[t], ep.steps[t + 1]
        pos = np.clip(s.positions + rng.normal(0, VISIBLE_SIGMA[0], s.positions.shape), RADIUS, ARENA - RADIUS)
        vel = s.velocities + rng.normal(0, VISIBLE_SIGMA[1], s.velocities.shape)
        d = rows.setdefault(len(pos), {"p": [], "v": [], "pil": [], "tp": [], "tv": []})
        d["p"].append(pos); d["v"].append(vel); d["pil"].append(np.array(ep.pillars, dtype=np.float64))
        d["tp"].append(nxt.positions); d["tv"].append(nxt.velocities)
    return Pool({n: {k: np.stack(v).astype(np.float32) for k, v in d.items()} for n, d in sorted(rows.items())})


# --- losses ------------------------------------------------------------------------------------
def rollout_loss(model: Dynamics, batch: dict[str, mx.array]) -> mx.array:
    """MSE of the model's own rollout against the simulator at 1, 5 and 10 steps, plus the contact loss."""
    p, v, pil = batch["p"], batch["v"], batch["pil"]
    loss = mx.array(0.0)
    for k in range(1, max(ROLLOUT) + 1):
        p, v, logits, _ = model(p, v, pil)
        if k == 1 and logits is not None:
            n = p.shape[1]
            off = 1 - mx.eye(n)[None]
            bce = nn.losses.binary_cross_entropy(logits, batch["contact"], with_logits=True, reduction="none")
            loss = loss + CONTACT_WEIGHT * (bce * off).sum() / mx.maximum(off.sum() * p.shape[0], 1)
        if k in ROLLOUT:
            loss = loss + (((p - batch[f"p{k}"]) / P_SCALE) ** 2).mean() + ((v - batch[f"v{k}"]) ** 2).mean()
    return loss


def nll_loss(model: Dynamics, batch: dict[str, mx.array]) -> mx.array:
    """L-int-σ: Gaussian NLL of the true next state around the frozen mean (keys p, v, pil, tp, tv)."""
    p, v, _, logvar = model(batch["p"], batch["v"], batch["pil"])
    err = mx.stop_gradient(mx.concatenate([p - batch["tp"], v - batch["tv"]], -1))
    return (0.5 * (logvar + err ** 2 / mx.exp(logvar))).mean()


# --- training ----------------------------------------------------------------------------------
def sample_kinds(e: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    """Indices of a mean bucket's samples (contact, near miss): a disk contact at step 1, or none
    and some pair of disks ending step 1 with centres closer than NEAR_GAP. Read from the
    simulator's labels only."""
    if "contact" not in e:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    hit = e["contact"].sum((1, 2)) > 0
    p1 = e["p1"]
    d = np.linalg.norm(p1[:, :, None] - p1[:, None], axis=-1) + np.eye(p1.shape[1])[None] * 99.0
    near = (d.min((1, 2)) < NEAR_GAP) & ~hit
    return np.flatnonzero(hit), np.flatnonzero(near)


def batches(pool: Pool, steps: int, batch: int, rng: np.random.Generator, *, coll_share: float = 0.0,
            near_share: float = 0.0) -> Iterator[tuple[int, np.ndarray]]:
    """Bucket chosen in proportion to its size, then ``batch`` indices drawn with replacement. With
    ``coll_share`` > 0 that share of the batch comes from the bucket's contact samples, with
    ``near_share`` > 0 that share from its near misses (see ``sample_kinds``); a kind the bucket
    does not have is drawn from the whole bucket instead. Order in the batch: contact, near, rest."""
    ns = sorted(pool.by_n)
    sizes = np.array([len(pool.by_n[n]["p"]) for n in ns], dtype=np.float64)
    w = sizes / sizes.sum()
    kinds = {n: sample_kinds(pool.by_n[n]) for n in ns}
    k, q = int(round(batch * coll_share)), int(round(batch * near_share))
    if k + q > batch:
        raise ValueError("the contact and near-miss shares exceed the batch")
    for _ in range(steps):
        j = int(rng.choice(len(ns), p=w))
        h, nr = kinds[ns[j]]
        parts = []
        if k and len(h):
            parts.append(h[rng.integers(0, len(h), k)])
        if q and len(nr):
            parts.append(nr[rng.integers(0, len(nr), q)])
        parts.append(rng.integers(0, int(sizes[j]), batch - sum(len(x) for x in parts)))
        yield ns[j], np.concatenate(parts)


def train(arm: str, pool: Pool, *, steps: int, batch: int, seed: int, lr: float = 1e-3,
          mean_model: Dynamics | None = None, log_every: int = 100) -> tuple[Dynamics, list[tuple[int, float]]]:
    """Adam on ``rollout_loss`` (mean arms; COLL_SHARE of each batch from contact samples and
    NEAR_SHARE from near misses) or, for L-int-s, on ``nll_loss`` with the mean taken from
    ``mean_model`` (a trained L-int) and frozen. The learning rate is ``lr``, constant or with a
    cosine decay to LR_END. Gradients are clipped to a global norm of CLIP; a non-finite loss or
    gradient stops training.
    Returns the model and (step, loss) every ``log_every``."""
    from mlx.utils import tree_flatten

    mx.random.seed(seed)
    model = Dynamics(arm)
    if arm == "L-int-s":
        if mean_model is None or mean_model.arm != "L-int":
            raise ValueError("L-int-s needs a trained L-int mean")
        model.load_weights(list(tree_flatten(mean_model.parameters())), strict=False)
        model.freeze()
        model.var1.unfreeze()
        model.var2.unfreeze()
        fn = nll_loss
    else:
        if mean_model is not None:
            raise ValueError("mean arms train from scratch")
        fn = rollout_loss
    share, near = (COLL_SHARE, NEAR_SHARE) if arm != "L-int-s" else (0.0, 0.0)
    mx.eval(model.parameters())
    opt = optim.Adam(learning_rate=lr if LR_END is None else optim.cosine_decay(lr, steps, LR_END))
    vg = nn.value_and_grad(model, fn)
    rng = np.random.default_rng(seed)
    log: list[tuple[int, float]] = []
    for t, (n, idx) in enumerate(batches(pool, steps, batch, rng, coll_share=share, near_share=near), 1):
        b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
        loss, grads = vg(model, b)
        grads, norm = optim.clip_grad_norm(grads, max_norm=CLIP)
        mx.eval(loss, norm)
        if not (np.isfinite(float(loss)) and np.isfinite(float(norm))):
            raise FloatingPointError(f"{arm} seed {seed}: non-finite loss or gradient at step {t}")
        opt.update(model, grads)
        mx.eval(model.parameters(), opt.state)
        if t % log_every == 0 or t == steps:
            log.append((t, float(loss)))
    return model, log


def save(model: Dynamics, path: str) -> None:
    model.save_weights(path)


def load(arm: str, path: str) -> Dynamics:
    model = Dynamics(arm)
    model.load_weights(path)
    mx.eval(model.parameters())
    return model


# --- filter interface --------------------------------------------------------------------------
def as_process_model(model: Dynamics, *, with_variance: bool = False):
    """Wrap a trained model for the filter: (P, V [M, n, 2], pillars) -> (P', V'[, var_p, var_v])."""
    if with_variance and model.arm != "L-int-s":
        raise ValueError("only L-int-s has a variance head")

    def step(P, V, pillars):
        if P.shape[1] == 0:
            return (P.copy(), V.copy()) if not with_variance else (P.copy(), V.copy(), np.zeros_like(P), np.zeros_like(V))
        pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], N_PILLARS, 3)))
        p, v, _, logvar = model(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), pil)
        mx.eval(p, v)
        out = (np.array(p, dtype=np.float64), np.array(v, dtype=np.float64))
        if with_variance:
            var = np.exp(np.array(logvar, dtype=np.float64))
            out = out + (var[..., 0:2], var[..., 2:4])
        return out
    return step
