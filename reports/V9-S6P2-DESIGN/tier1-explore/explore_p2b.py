#!/usr/bin/env python3
"""S6 phase 2 exploration round B: the new mechanism is rare, and a version-difference pick signal.

Round A (explore_p2a.py) showed the ring is learnable and that replay prevents forgetting, but selection had
nothing to add: 20% of all disk-steps of a world-B pool lie in the ring, so random experiments already cover
it, and disagreement kept spending the budget on the old hard cases (collisions, walls).

Here the sandbox offers mostly old-type worlds: only B_SHARE of the candidate worlds carry a big pillar, so
about 2% of the candidate disk-steps are in a ring (as rare as collisions were in phase 1).

Arms: <pick><protection>, protection as round A ("+" replay of the old experiments every other batch).
  R  random
  E  disagreement of the three networks (the phase-1 signal: total uncertainty)
  V  version difference: how far the current networks' mean prediction has moved from the promoted
     version's (the base networks), max over disks. It needs no label: where the learner has started to
     change its mind is where it found something new.
  Z  closest pair (phase-1 zero-knowledge rule)
  W  states with a disk in a ring (knows the answer; upper bound)

Usage (MLX; under the shared lock): explore_p2b.py <out.json> <arms,comma> [b_share] [per] [rounds] [steps] [lr]
Namespaces: s6x-p2b-cand, s6x-p2a-testB, s6x-p2a-testA. Exploration only.
"""
import json
import sys
import time
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import explore_p2a as XA  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import cells as C  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402
from ainerzero.v9.experiments.s6 import world_b as B  # noqa: E402

CAND_NS = "s6x-p2b-cand"
POOL, CAND_WORLDS, BATCH = 60_000, 240, 256


def candidates_mixed(b_share):
    """The first round(b_share * CAND_WORLDS) worlds are world B (a big pillar), the rest world A."""
    n_b = round(b_share * CAND_WORLDS)
    eps = [B.generate_episode_b(CAND_NS, w, A.train_disks(CAND_NS, w)) if w < n_b
           else W.generate_episode(CAND_NS, w, A.train_disks(CAND_NS, w)) for w in range(CAND_WORLDS)]
    pairs = [(e, t) for e, ep in enumerate(eps) for t in range(len(ep.steps))]
    pick = np.random.default_rng(W.derive_seed(CAND_NS, "pool", 0)).choice(len(pairs), POOL, replace=False)
    chosen = sorted((eps[pairs[i][0]].n_disks, rank, pairs[i][0], pairs[i][1]) for rank, i in enumerate(pick))
    by_n = {}
    for n, _, e, t in chosen:
        row = by_n.setdefault(n, {"p": [], "v": [], "pil": []})
        row["p"].append(eps[e].steps[t].positions); row["v"].append(eps[e].steps[t].velocities)
        row["pil"].append(np.asarray(eps[e].pillars, dtype=np.float64))
    return {n: {k: np.stack(v) for k, v in d.items()} for n, d in sorted(by_n.items())}


def mean_prediction(states, models):
    out = {}
    for n, e in states.items():
        p, v, pil = mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"])
        out[n] = np.mean([np.array(m(p, v, pil)[1], dtype=np.float64) for m in models], 0)
    return out


def version_difference(states, models, base_pred):
    cur = mean_prediction(states, models)
    total = sum(len(e["id"]) for e in states.values())
    score = np.empty(total)
    for n, e in states.items():
        score[e["id"]] = np.linalg.norm(cur[n] - base_pred[n], axis=-1).max(-1)
    return score


def main():
    out = Path(sys.argv[1]); arms = sys.argv[2].split(",")
    b_share = float(sys.argv[3]) if len(sys.argv) > 3 else 0.10
    per = int(sys.argv[4]) if len(sys.argv) > 4 else 1500
    rounds = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    steps = int(sys.argv[6]) if len(sys.argv) > 6 else 1000
    lr = float(sys.argv[7]) if len(sys.argv) > 7 else 1e-3
    t0 = time.time()
    rec = json.loads((XA.BASE / "cell.json").read_text())
    old_source = C.candidate_source(XA.OLD_NS, 0)
    assert C.pool_digest(old_source) == rec["pool_sha256"]
    old_pool = C.make_candidate_pool(old_source).reveal(np.array([i for p in rec["tracks"][0]["picks"] for i in p], dtype=np.int64))
    cand = candidates_mixed(b_share)
    tests_b = [XA.prepare_b(B.generate_episode_b(XA.TEST_B, w, 6)) for w in range(30)]
    tests_a = [C.prepare_world(W.generate_episode(XA.TEST_A, w, 6)) for w in range(30)]
    probe = S.CandidatePool(cand, labeller=B.sim_labels_b, pool_type=L.Pool)
    states0 = probe.states()
    flags = XA.halo_flags(states0)
    big = np.zeros(len(probe), dtype=bool)
    for e in states0.values():
        big[e["id"]] = e["pil"][:, :, 2].max(-1) >= B.BIG_MIN
    print(f"pool {len(probe)}: {big.mean():.3f} from big-pillar worlds, {flags.mean():.3f} with a disk in a ring; {time.time() - t0:.0f}s", flush=True)
    first = S.pick_random(probe.remaining(), per, np.random.default_rng(W.derive_seed(CAND_NS, "first", 0)))
    mx.set_default_device(mx.cpu)
    base_models = [C.load_model("E", XA.BASE / f"r3-n{j}.safetensors") for j in range(3)]
    base_eval, _ = XA.evaluate(base_models, tests_b, tests_a)
    base_pred = mean_prediction(states0, base_models)
    print("base    " + " ".join(f"{k}={v:.4f}" for k, v in base_eval.items()), flush=True)
    res = json.loads(out.read_text()) if out.exists() else {
        "config": {"b_share": b_share, "per": per, "rounds": rounds, "steps": steps, "lr": lr}, "base": base_eval,
        "pool": {"big_world_share": float(big.mean()), "ring_share": float(flags.mean())}, "arms": {}}
    for arm in arms:
        pick, protect = arm[0], arm[1] == "+"
        mx.set_default_device(mx.gpu)
        cp = S.CandidatePool(cand, labeller=B.sim_labels_b, pool_type=L.Pool)
        learners = []
        for j in range(3):
            m = C.load_model("E", XA.BASE / f"r3-n{j}.safetensors")
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
            ev, per_net = XA.evaluate(models, tests_b, tests_a)
            pk = np.asarray(picks)
            share = {"ring": float(flags[pk].mean()), "big_world": float(big[pk].mean())}
            curve.append({"round": r, "picks": share, **ev, "per_net": per_net})
            print(f"{arm} r{r} picks ring {share['ring']:.3f} big-world {share['big_world']:.3f} | "
                  + " ".join(f"{k}={v:.4f}" for k, v in ev.items()) + f"  {time.time() - t0:.0f}s", flush=True)
            if r < rounds - 1:
                st, rem = cp.states(), cp.remaining()
                if pick == "R":
                    picks = S.pick_random(rem, per, rng)
                elif pick == "E":
                    picks = S.pick_top(C.disagreement(st, models), rem, per)
                elif pick == "V":
                    picks = S.pick_top(version_difference(st, models, base_pred), rem, per)
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
