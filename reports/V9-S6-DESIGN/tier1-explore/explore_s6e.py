#!/usr/bin/env python3
"""S6 exploration, round E (s6x-*; exploration only): epinet against the small ensemble as the
uncertainty that picks the experiments, in round C's budgeted from-scratch setting.

Epinet (Osband et al., arXiv 2107.08924), on L-int: f(x, z) = mu(x) + sigma_L(sg[h(x)], z) + sigma_P(sg[h(x)], z),
h the last hidden layer, z ~ N(0, I_DZ) an index fixed per sample over a rollout, sigma(h, z) = G(h, z) z
with G an MLP mapping [h, z] to OUT x DZ; sigma_P has fixed random weights scaled by PRIOR. At z = 0 the
output is the base network's. Uncertainty for selection: the spread over KZ index draws of the next-velocity
prediction (max over disks). Each seed is an independent learner with its own selection.

Arms (each 3 seeds): random (single network), disagree-ens (round C's 3-network ensemble, shared
selection), disagree-epi (single network with epinet). Same candidate pool, rounds and evaluation as
round C; the epinet learners are evaluated at z = 0.

Usage (MLX; under the shared lock): <this> PER ROUNDS STEPS_PER_ROUND OUT.json [CAND_NS TEST_NS]
"""
import json
import sys
import time

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import explore_s6a as XA  # noqa: E402
import explore_s6c as XC  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import world as W

DZ, KZ, PRIOR, EPI_HID = 8, 8, 1.0, 32


class Epi(nn.Module):
    def __init__(self, din):
        super().__init__()
        self.l1 = nn.Linear(din + DZ, EPI_HID)
        self.l2 = nn.Linear(EPI_HID, 4 * DZ)

    def __call__(self, h, z):            # h [B, n, H], z [B, DZ]
        zb = mx.broadcast_to(z[:, None, :], (h.shape[0], h.shape[1], DZ))
        g = self.l2(nn.relu(self.l1(mx.concatenate([h, zb], -1)))).reshape(h.shape[0], h.shape[1], 4, DZ)
        return (g * zb[:, :, None, :]).sum(-1)


class EpiDynamics(L.Dynamics):
    def __init__(self):
        super().__init__("L-int")
        self.epi = Epi(L.HID)
        self.prior = Epi(L.HID)
        self.prior.freeze()
        self.z = None

    def __call__(self, p, v, pil):
        h = [L.node_features(p, v, pil)]
        logits, scal, _ = self.messages(p, v)
        h.append(scal)
        hid = nn.relu(self.up2(nn.relu(self.up1(mx.concatenate(h, -1)))))
        o = self.out(hid)
        if self.z is not None:
            hs = mx.stop_gradient(hid)
            o = o + self.epi(hs, self.z) + PRIOR * mx.stop_gradient(self.prior(hs, self.z))
        return p + v * L.DT + o[..., 0:2] * L.P_SCALE, v + o[..., 2:4], logits, None


class EpiLearner:
    def __init__(self, seed):
        mx.random.seed(seed)
        self.model = EpiDynamics()
        mx.eval(self.model.parameters())
        self.opt = optim.Adam(learning_rate=XC.LR)
        self.vg = nn.value_and_grad(self.model, L.rollout_loss)
        self.rng = np.random.default_rng(seed)

    def train(self, pool, steps):
        for n, idx in L.batches(pool, steps, XC.BATCH, self.rng, coll_share=0.0):
            b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
            self.model.z = mx.random.normal((len(idx), DZ))
            loss, grads = self.vg(self.model, b)
            grads, _ = optim.clip_grad_norm(grads, max_norm=L.CLIP)
            self.opt.update(self.model, grads)
            mx.eval(self.model.parameters(), self.opt.state)
        self.model.z = None

    def spread(self, pool):
        out = {}
        for n, e in pool.by_n.items():
            p, v, pil = mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"])
            draws = []
            for k in range(KZ):
                self.model.z = mx.array(np.random.default_rng(1000 + k).normal(size=(len(e["p"]), DZ)).astype(np.float32))
                draws.append(np.array(self.model(p, v, pil)[1], dtype=np.float64))
            self.model.z = None
            st = np.stack(draws)
            out[n] = np.linalg.norm(st - st.mean(0)[None], axis=-1).mean(0).max(-1)
        return out


def main():
    per, rounds, spr, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    cand_ns = sys.argv[5] if len(sys.argv) > 5 else "s6x-cand"
    test_ns = sys.argv[6] if len(sys.argv) > 6 else "s6x-test"
    t0 = time.time()
    cand = L.make_pool(A.train_worlds(cand_ns, 120), 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
    test_eps = [W.generate_episode(test_ns, w, 6) for w in range(20)] + [W.generate_episode(test_ns, 1000 + w, 10) for w in range(10)]
    allp = XA.flat_pool(cand)
    coll = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])
    res = {"namespaces": {"candidates": cand_ns, "test": test_ns}, "per": per, "rounds": rounds, "steps_per_round": spr,
           "epinet": {"dz": DZ, "kz": KZ, "prior": PRIOR, "hidden": EPI_HID}, "curves": {"disagree-epi": []}, "seconds": {}}
    # epinet arm: three independent learners, each with its own selection
    t_arm = time.time()
    learners = [EpiLearner(s) for s in XA.SEEDS]
    chosen = [list(np.random.default_rng(100).choice(len(allp), per, replace=False)) for _ in XA.SEEDS]
    for r in range(rounds):
        mx.set_default_device(mx.gpu)
        for lr_, ch in zip(learners, chosen):
            lr_.train(XA.subset(cand, [allp[i] for i in ch]), spr)
        mx.set_default_device(mx.cpu)
        ev = XA.evaluate({f"epi#{s}": l.model for s, l in zip(XA.SEEDS, learners)}, test_eps)
        summ = {k: float(np.mean([ev[f"epi#{s}"][k] for s in XA.SEEDS])) for k in ("collision", "graze", "wall_pillar", "free", "all", "D")}
        summ["n_labels"] = len(chosen[0]); summ["disk_contact_share"] = float(np.mean([coll[c].mean() for c in chosen]))
        res["curves"]["disagree-epi"].append(summ)
        print(f"disagree-epi round {r} n={len(chosen[0]):6d} contact={summ['disk_contact_share']:.3f} D={summ['D']:.3f} coll={summ['collision']:.4f} "
              f"wall={summ['wall_pillar']:.4f} free={summ['free']:.4f} all={summ['all']:.4f}  {time.time() - t0:.0f}s", flush=True)
        if r == rounds - 1:
            break
        t_sel = time.time()
        for j, lr_ in enumerate(learners):
            sp = lr_.spread(cand)
            score = np.array([sp[n][i] for n, i in allp])
            rest = np.setdiff1d(np.arange(len(allp)), chosen[j])
            chosen[j] += list(rest[np.argsort(-score[rest])[:per]])
        res["seconds"].setdefault("epi_selection", []).append(time.time() - t_sel)
    res["seconds"]["epi_arm"] = time.time() - t_arm
    json.dump(res, open(out, "w"), indent=1)
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
