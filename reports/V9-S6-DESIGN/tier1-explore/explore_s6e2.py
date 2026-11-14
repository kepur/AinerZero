#!/usr/bin/env python3
"""S6 exploration, round E2 (s6x-*; exploration only): epinet trained apart from the base network.

Round E trained the base jointly with the epinet noise, which biased the base (D at z = 0 about 0.09 below a
plain network after the first round). Here the base trains on the phase-1 rollout loss alone (gradients
clipped on their own norm), and the epinet on a one-step loss of sg[base output] + sigma_L + PRIOR sigma_P
against the one-step label (output units), so the base is the plain network. Selection uses the spread of
the epinet output over KZ index draws, as in round E. Same pool, rounds and evaluation as rounds C and E.

Usage (MLX; under the shared lock): <this> PER ROUNDS STEPS_PER_ROUND OUT.json [CAND_NS TEST_NS]
"""
import json
import sys
import time

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from mlx.utils import tree_flatten, tree_unflatten

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import explore_s6a as XA  # noqa: E402
import explore_s6c as XC  # noqa: E402
import explore_s6e as XE  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import world as W


class Decoupled(XE.EpiDynamics):
    def hidden_out(self, p, v, pil):
        h = [L.node_features(p, v, pil)]
        _, scal, _ = self.messages(p, v)
        h.append(scal)
        hid = nn.relu(self.up2(nn.relu(self.up1(mx.concatenate(h, -1)))))
        return hid, self.out(hid)


def loss_fn(model, b):
    zb = model.zb
    model.z = None
    lb = L.rollout_loss(model, b)
    hid, o = model.hidden_out(b["p"], b["v"], b["pil"])
    hs = mx.stop_gradient(hid)
    pred = mx.stop_gradient(o) + model.epi(hs, zb) + XE.PRIOR * mx.stop_gradient(model.prior(hs, zb))
    target = mx.concatenate([(b["p1"] - b["p"] - b["v"] * L.DT) / L.P_SCALE, b["v1"] - b["v"]], -1)
    return lb + ((pred - target) ** 2).mean()


def clip_parts(grads):
    flat = dict(tree_flatten(grads))
    base = {k: v for k, v in flat.items() if not k.startswith(("epi.", "prior."))}
    epi = {k: v for k, v in flat.items() if k.startswith(("epi.", "prior."))}
    base, _ = optim.clip_grad_norm(tree_unflatten(list(base.items())), max_norm=L.CLIP)
    epi, _ = optim.clip_grad_norm(tree_unflatten(list(epi.items())), max_norm=L.CLIP)
    return tree_unflatten(list(dict(tree_flatten(base)).items()) + list(dict(tree_flatten(epi)).items()))


class Learner(XE.EpiLearner):
    def __init__(self, seed):
        mx.random.seed(seed)
        self.model = Decoupled()
        mx.eval(self.model.parameters())
        self.opt = optim.Adam(learning_rate=XC.LR)
        self.vg = nn.value_and_grad(self.model, loss_fn)
        self.rng = np.random.default_rng(seed)

    def train(self, pool, steps):
        for n, idx in L.batches(pool, steps, XC.BATCH, self.rng, coll_share=0.0):
            b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
            self.model.zb = mx.random.normal((len(idx), XE.DZ))
            loss, grads = self.vg(self.model, b)
            self.opt.update(self.model, clip_parts(grads))
            mx.eval(self.model.parameters(), self.opt.state)
        self.model.z = None


def main():
    per, rounds, spr, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    cand_ns = sys.argv[5] if len(sys.argv) > 5 else "s6x-cand"
    test_ns = sys.argv[6] if len(sys.argv) > 6 else "s6x-test"
    t0 = time.time()
    cand = L.make_pool(A.train_worlds(cand_ns, 120), 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
    test_eps = [W.generate_episode(test_ns, w, 6) for w in range(20)] + [W.generate_episode(test_ns, 1000 + w, 10) for w in range(10)]
    allp = XA.flat_pool(cand)
    coll = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])
    res = {"namespaces": {"candidates": cand_ns, "test": test_ns}, "per": per, "rounds": rounds, "steps_per_round": spr, "curves": []}
    learners = [Learner(s) for s in XA.SEEDS]
    chosen = [list(np.random.default_rng(100).choice(len(allp), per, replace=False)) for _ in XA.SEEDS]
    for r in range(rounds):
        mx.set_default_device(mx.gpu)
        for lr_, ch in zip(learners, chosen):
            lr_.train(XA.subset(cand, [allp[i] for i in ch]), spr)
        mx.set_default_device(mx.cpu)
        ev = XA.evaluate({f"epi2#{s}": l.model for s, l in zip(XA.SEEDS, learners)}, test_eps)
        summ = {k: float(np.mean([ev[f"epi2#{s}"][k] for s in XA.SEEDS])) for k in ("collision", "graze", "wall_pillar", "free", "all", "D")}
        summ["n_labels"] = len(chosen[0]); summ["disk_contact_share"] = float(np.mean([coll[c].mean() for c in chosen]))
        res["curves"].append(summ)
        print(f"epi-decoupled round {r} n={len(chosen[0]):6d} contact={summ['disk_contact_share']:.3f} D={summ['D']:.3f} coll={summ['collision']:.4f} "
              f"wall={summ['wall_pillar']:.4f} free={summ['free']:.4f} all={summ['all']:.4f}  {time.time() - t0:.0f}s", flush=True)
        if r == rounds - 1:
            break
        for j, lr_ in enumerate(learners):
            sp = lr_.spread(cand)
            score = np.array([sp[n][i] for n, i in allp])
            rest = np.setdiff1d(np.arange(len(allp)), chosen[j])
            chosen[j] += list(rest[np.argsort(-score[rest])[:per]])
    json.dump(res, open(out, "w"), indent=1)
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
