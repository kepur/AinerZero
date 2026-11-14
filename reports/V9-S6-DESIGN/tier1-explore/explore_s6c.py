#!/usr/bin/env python3
"""S6 exploration, round C (s6x-*; exploration only): budgeted learning from scratch with a self-chosen
curriculum. Phase 1 needed a hand curriculum that reads the simulator labels (half of each batch from
samples with a disk contact at step 1) to learn collisions at all. Can the learner find that gap by itself?

Candidates: an exact-state pool (sandbox placements of real configurations) from s6x-cand worlds,
labels hidden until selected. Budget: ROUNDS rounds of PER samples; the first round is random. After
each round each seed's L-int continues training on everything selected so far (STEPS_PER_ROUND steps,
uniform batches), then the next round is selected. Arms:
  random     random samples each round, uniform batches
  disagree   each later round the PER candidates with the largest disagreement of the three seeds
             (max over disks of the spread of next-velocity predictions); no labels read
  oracle     each later round the PER candidates with the largest true error of the ensemble mean (reads labels)
  truthcur   random samples, but batches built like phase 1: half from selected samples with a disk
             contact at step 1 (reads labels)
Evaluation after every round on the s6x-test worlds (as explore_s6a.evaluate): error per step kind and D.

Usage (MLX; under the shared lock): <this> PER ROUNDS STEPS_PER_ROUND OUT.json [CAND_NS TEST_NS ARMS]
(defaults s6x-cand, s6x-test, random,disagree,oracle,truthcur; round D replicates on other namespaces)
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
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import world as W

LR = 1e-3
BATCH = 256


class Learner:
    def __init__(self, seed):
        mx.random.seed(seed)
        self.model = L.Dynamics("L-int")
        mx.eval(self.model.parameters())
        self.opt = optim.Adam(learning_rate=LR)
        self.vg = nn.value_and_grad(self.model, L.rollout_loss)
        self.rng = np.random.default_rng(seed)

    def train(self, pool, steps, coll_share):
        for n, idx in L.batches(pool, steps, BATCH, self.rng, coll_share=coll_share):
            b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
            loss, grads = self.vg(self.model, b)
            grads, _ = optim.clip_grad_norm(grads, max_norm=L.CLIP)
            self.opt.update(self.model, grads)
            mx.eval(self.model.parameters(), self.opt.state)


def main():
    per, rounds, spr, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    cand_ns = sys.argv[5] if len(sys.argv) > 5 else "s6x-cand"
    test_ns = sys.argv[6] if len(sys.argv) > 6 else "s6x-test"
    arms = sys.argv[7].split(",") if len(sys.argv) > 7 else ["random", "disagree", "oracle", "truthcur"]
    t0 = time.time()
    cand = L.make_pool(A.train_worlds(cand_ns, 120), 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
    test_eps = [W.generate_episode(test_ns, w, 6) for w in range(20)] + [W.generate_episode(test_ns, 1000 + w, 10) for w in range(10)]
    allp = XA.flat_pool(cand)
    coll = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])
    print(f"pool {time.time() - t0:.0f}s, disk-contact share {coll.mean():.3f}", flush=True)
    res = {"per": per, "rounds": rounds, "steps_per_round": spr, "curves": {}, "selection": {}}
    res["namespaces"] = {"candidates": cand_ns, "test": test_ns}
    for arm in arms:
        mx.set_default_device(mx.gpu)
        learners = [Learner(s) for s in XA.SEEDS]
        rng = np.random.default_rng(100)
        chosen = list(rng.choice(len(allp), per, replace=False))
        res["curves"][arm], res["selection"][arm] = [], []
        for r in range(rounds):
            pool = XA.subset(cand, [allp[i] for i in chosen])
            for lr_ in learners:
                lr_.train(pool, spr, 0.5 if arm == "truthcur" else 0.0)
            mx.set_default_device(mx.cpu)
            ev = XA.evaluate({f"{arm}#{s}": l.model for s, l in zip(XA.SEEDS, learners)}, test_eps)
            summ = {k: float(np.mean([ev[f"{arm}#{s}"][k] for s in XA.SEEDS])) for k in ("collision", "graze", "wall_pillar", "free", "all", "D")}
            summ["n_labels"] = len(chosen); summ["disk_contact_share"] = float(coll[chosen].mean())
            res["curves"][arm].append(summ)
            print(f"{arm:9} round {r} n={len(chosen):6d} contact={summ['disk_contact_share']:.3f} D={summ['D']:.3f} coll={summ['collision']:.4f} wall={summ['wall_pillar']:.4f} free={summ['free']:.4f} all={summ['all']:.4f}  {time.time() - t0:.0f}s", flush=True)
            if r == rounds - 1:
                break
            rest = np.setdiff1d(np.arange(len(allp)), chosen)
            if arm in ("random", "truthcur"):
                new = rng.choice(rest, per, replace=False)
            else:
                dis, err = XA.score_pool(cand, [l.model for l in learners])
                score = np.array([(dis if arm == "disagree" else err)[n][i] for n, i in allp])
                new = rest[np.argsort(-score[rest])[:per]]
            chosen += list(new)
            mx.set_default_device(mx.gpu)
    json.dump(res, open(out, "w"), indent=1)
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
