#!/usr/bin/env python3
"""S6 phase 2 exploration round A: the world gains a new mechanism (world B: a big pillar with a vortex ring).

A learner that already knows world A (the three L-int networks of the phase-1 probe cell
artifacts/v9/s6/phase1/probe/cells/E-r0, round 3; the final cells are left for the registered run) gets a budget of experiments in world B's sandbox and
continues training. Three questions before a design can be written:
  1. can the network learn the new mechanism at all with this budget (ring skill H);
  2. does its own disagreement find where the new mechanism is (ring share of the picks, H against random);
  3. does it forget old skills without protection, and does replay of old experience prevent that
     (collision skill D and all-step error on world-A test worlds).

Arms: <pick><protection>. pick: R random, E disagreement of the three networks, Z closest pair (the phase-1
zero-knowledge rule), W picks states with a disk in the ring (knows the answer; upper bound).
protection: "+" every other batch replays the learner's old world-A experiments; "-" new data only.

Ring skill H = 1 - err(ring disk-steps) / err_old_law(ring disk-steps): 0 knows nothing new, 1 perfect.

Usage (MLX; under the shared lock): explore_p2a.py <out.json> <arms,comma> [per] [rounds] [steps] [lr]
Namespaces: s6x-p2a-cand (world B candidates), s6x-p2a-testB, s6x-p2a-testA. Exploration only.
"""
import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import cells as C
from ainerzero.v9.experiments.s6 import sandbox as S
from ainerzero.v9.experiments.s6 import world_b as B

REPO = Path(__file__).resolve().parents[3]
BASE = REPO / "artifacts/v9/s6/phase1/probe/cells/E-r0"
OLD_NS, CAND_NS, TEST_B, TEST_A = "s6p1-pcand", "s6x-p2a-cand", "s6x-p2a-testB", "s6x-p2a-testA"
POOL, CAND_WORLDS, BATCH = 60_000, 240, 256


def candidates_b():
    eps = [B.generate_episode_b(CAND_NS, w, A.train_disks(CAND_NS, w)) for w in range(CAND_WORLDS)]
    pairs = [(e, t) for e, ep in enumerate(eps) for t in range(len(ep.steps))]
    pick = np.random.default_rng(W.derive_seed(CAND_NS, "pool", 0)).choice(len(pairs), POOL, replace=False)
    chosen = sorted((eps[pairs[i][0]].n_disks, rank, pairs[i][0], pairs[i][1]) for rank, i in enumerate(pick))
    by_n = {}
    for n, _, e, t in chosen:
        row = by_n.setdefault(n, {"p": [], "v": [], "pil": []})
        row["p"].append(eps[e].steps[t].positions); row["v"].append(eps[e].steps[t].velocities)
        row["pil"].append(np.asarray(eps[e].pillars, dtype=np.float64))
    return {n: {k: np.stack(v) for k, v in d.items()} for n, d in sorted(by_n.items())}


def prepare_b(ep):
    T = len(ep.steps) - 1
    P = np.stack([s.positions for s in ep.steps[:T]]); V = np.stack([s.velocities for s in ep.steps[:T]])
    tgt = np.stack([s.velocities for s in ep.steps[1:T + 1]])
    kinds = np.stack([B.classify_b(ep, t) for t in range(T)])
    _, vb = Mo.bounce(P, V, ep.pillars)                              # E-B (no disk collisions), for D
    _, vo, _ = W.physics(P, V, ep.pillars)                           # the old law (no vortex), for H
    pil = np.broadcast_to(np.array(ep.pillars, dtype=np.float32), (T, 3, 3)).copy()
    return {"P": P.astype(np.float32), "V": V.astype(np.float32), "tgt": tgt, "kinds": kinds, "pil": pil,
            "eb": np.linalg.norm(vb - tgt, axis=-1), "old": np.linalg.norm(vo - tgt, axis=-1)}


def evaluate(models, tests_b, tests_a):
    """Mean over the networks: per-kind errors, D and H on world-B tests; D and all-step error on world-A tests."""
    rows = []
    for m in models:
        sums = np.zeros(5); cnt = np.zeros(5); eb = 0.0; old = 0.0
        for tw in tests_b:
            _, v, _, _ = m(mx.array(tw["P"]), mx.array(tw["V"]), mx.array(tw["pil"]))
            e = np.linalg.norm(np.array(v, dtype=np.float64) - tw["tgt"], axis=-1)
            for k in range(5):
                sums[k] += e[tw["kinds"] == k].sum(); cnt[k] += (tw["kinds"] == k).sum()
            eb += tw["eb"][tw["kinds"] == 0].sum(); old += tw["old"][tw["kinds"] == 4].sum()
        sa = np.zeros(4); ca = np.zeros(4); eba = 0.0
        for tw in tests_a:
            sa += C.world_sums(m, tw); c, e_ = C.world_counts(tw); ca += c; eba += e_
        rows.append({"H": 1 - sums[4] / old, "D_B": 1 - sums[0] / eb, "halo": sums[4] / cnt[4], "free_B": sums[3] / cnt[3],
                     "wall_B": sums[2] / cnt[2], "all_B": sums.sum() / cnt.sum(),
                     "D_A": 1 - sa[0] / eba, "free_A": sa[3] / ca[3], "wall_A": sa[2] / ca[2], "all_A": sa.sum() / ca.sum()})
    return {k: float(np.mean([r[k] for r in rows])) for k in rows[0]}, rows


def halo_flags(states):
    total = sum(len(e["id"]) for e in states.values())
    out = np.zeros(total, dtype=bool)
    for e in states.values():
        for b in range(len(e["id"])):
            out[e["id"][b]] = B.in_halo(e["p"][b].astype(np.float64), [tuple(x) for x in e["pil"][b].astype(np.float64)]).any()
    return out


def main():
    out = Path(sys.argv[1]); arms = sys.argv[2].split(",")
    per = int(sys.argv[3]) if len(sys.argv) > 3 else 1500
    rounds = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    steps = int(sys.argv[5]) if len(sys.argv) > 5 else 1000
    lr = float(sys.argv[6]) if len(sys.argv) > 6 else 1e-3
    t0 = time.time()
    # the learner's old experience: every experiment of the base cell, with its world-A outcomes
    rec = json.loads((BASE / "cell.json").read_text())
    old_source = C.candidate_source(OLD_NS, 0)
    assert C.pool_digest(old_source) == rec["pool_sha256"], "the old candidate pool does not rebuild"
    old_cp = C.make_candidate_pool(old_source)
    old_pool = old_cp.reveal(np.array([i for p in rec["tracks"][0]["picks"] for i in p], dtype=np.int64))
    print(f"old experience {old_pool.size()} samples, {time.time() - t0:.0f}s", flush=True)
    cand = candidates_b()
    tests_b = [prepare_b(B.generate_episode_b(TEST_B, w, 6)) for w in range(30)]
    tests_a = [C.prepare_world(W.generate_episode(TEST_A, w, 6)) for w in range(30)]
    probe = S.CandidatePool(cand, labeller=B.sim_labels_b, pool_type=L.Pool)
    flags = halo_flags(probe.states())
    print(f"world-B pool {len(probe)} states, {flags.mean():.3f} with a disk in the ring; {time.time() - t0:.0f}s", flush=True)
    first = S.pick_random(probe.remaining(), per, np.random.default_rng(W.derive_seed(CAND_NS, "first", 0)))
    mx.set_default_device(mx.cpu)
    base_models = [C.load_model("E", BASE / f"r3-n{j}.safetensors") for j in range(3)]
    base_eval, _ = evaluate(base_models, tests_b, tests_a)
    print("base    " + " ".join(f"{k}={v:.4f}" for k, v in base_eval.items()), flush=True)
    res = json.loads(out.read_text()) if out.exists() else {"config": {"per": per, "rounds": rounds, "steps": steps, "lr": lr},
                                                              "base": base_eval, "pool_halo_share": float(flags.mean()), "arms": {}}
    for arm in arms:
        pick, protect = arm[0], arm[1] == "+"
        mx.set_default_device(mx.gpu)
        cp = S.CandidatePool(cand, labeller=B.sim_labels_b, pool_type=L.Pool)
        learners = []
        for j in range(3):
            m = C.load_model("E", BASE / f"r3-n{j}.safetensors")
            learners.append({"model": m, "opt": optim.Adam(learning_rate=lr), "vg": nn.value_and_grad(m, L.rollout_loss),
                             "rng": np.random.default_rng(1000 + j)})
        rng = np.random.default_rng(W.derive_seed(CAND_NS, "pick", pick, 0))
        picks = first
        curve = []
        for r in range(rounds):
            cp.reveal(picks)
            new_pool = cp.revealed_pool()
            for lr_ in learners:
                gen_new = L.batches(new_pool, steps, BATCH, lr_["rng"], coll_share=0.0)
                gen_old = L.batches(old_pool, steps, BATCH, lr_["rng"], coll_share=0.0)
                for t in range(steps):
                    src, gen = (old_pool, gen_old) if (protect and t % 2 == 1) else (new_pool, gen_new)
                    n, idx = next(gen)
                    b = {k: mx.array(v[idx]) for k, v in src.by_n[n].items()}
                    loss, grads = lr_["vg"](lr_["model"], b)
                    grads, _ = optim.clip_grad_norm(grads, max_norm=L.CLIP)
                    lr_["opt"].update(lr_["model"], grads)
                    mx.eval(lr_["model"].parameters(), lr_["opt"].state)
            mx.set_default_device(mx.cpu)
            models = [l["model"] for l in learners]
            ev, per_net = evaluate(models, tests_b, tests_a)
            share = float(flags[np.asarray(picks)].mean())
            curve.append({"round": r, "ring_share_of_picks": share, **ev, "per_net": per_net})
            print(f"{arm} r{r} ring-share {share:.3f} | " + " ".join(f"{k}={v:.4f}" for k, v in ev.items()) + f"  {time.time() - t0:.0f}s", flush=True)
            if r < rounds - 1:
                st, rem = cp.states(), cp.remaining()
                if pick == "R":
                    picks = S.pick_random(rem, per, rng)
                elif pick == "E":
                    picks = S.pick_top(C.disagreement(st, models), rem, per)
                elif pick == "Z":
                    picks = S.pick_top(C.closest_pair(st), rem, per)
                elif pick == "W":
                    picks = S.pick_geo(flags, rem, per, rng)
                else:
                    raise ValueError(arm)
            mx.set_default_device(mx.gpu)
        res["arms"][arm] = curve
        out.write_text(json.dumps(res), encoding="utf-8")
    print(f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
