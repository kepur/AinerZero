#!/usr/bin/env python3
"""S6 phase 2 exploration round F: decoys, and the cheap rule "pick what looks unfamiliar".

Round E: surprise remembered by layout, measured against the promoted version (N), finds a rare new mechanism
(ring skill H 0.31; random -0.06; the rule that knows the answer 0.33). But a rule with no learning at all
would also find a big pillar: its radius lies outside everything the old experience contains.

Here the sandbox has three kinds of worlds: 10% with a big pillar and its ring (something new to learn),
10% with a tiny pillar (looks just as unfamiliar, old law: a decoy), 80% ordinary.

Arms (all with replay):
  N  surprise by layout against the promoted version (round E)
  Q  input novelty: flag candidates with an input outside the range the old experience covered (pillar radius,
     speed), pick among them at random. No learning, no outcome.
  R  random; W the rule that knows the answer (a disk in a ring).
  U  (round I) one-sided input novelty: a pillar larger than any in the old experience. Decoys in round I lie on
     both sides of the old range ("tiny" in the log then counts every decoy world).
  O  (round H) N with an exploration floor: a fifth of every round's experiments are drawn at random, so that
     layouts not yet tried keep being sampled.

Usage (MLX; under the shared lock): explore_p2f.py <out.json> <arms,comma> [per] [rounds] [steps] [lr]
Namespaces: s6x-p2f-cand, s6x-p2a-testB, s6x-p2a-testA. Exploration only.
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
import explore_p2c as XC  # noqa: E402
import explore_p2d as XD  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import cells as C  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402
from ainerzero.v9.experiments.s6 import world_b as B  # noqa: E402

import os  # noqa: E402

# Round F: 240 worlds (24 big, 24 tiny). Round G: S6P2_WORLDS=600 S6P2_BIG=60 S6P2_TINY=60 S6P2_NS=s6x-p2g-cand
CAND_NS = os.environ.get("S6P2_NS", "s6x-p2f-cand")
POOL = 60_000
CAND_WORLDS = int(os.environ.get("S6P2_WORLDS", 240))
N_BIG = int(os.environ.get("S6P2_BIG", 24))
N_TINY = int(os.environ.get("S6P2_TINY", 24))
N_LARGE = int(os.environ.get("S6P2_LARGE", 0))     # round I: decoys above the old range too (S6P2_TINY=30 S6P2_LARGE=30)


def candidates_three_kinds():
    eps = []
    for w in range(CAND_WORLDS):
        n = A.train_disks(CAND_NS, w)
        if w < N_BIG:
            eps.append(B.generate_episode_b(CAND_NS, w, n))
        elif w < N_BIG + N_TINY:
            eps.append(B.generate_episode_b(CAND_NS, w, n, kind="tiny"))
        elif w < N_BIG + N_TINY + N_LARGE:
            eps.append(B.generate_episode_b(CAND_NS, w, n, kind="large"))
        else:
            eps.append(W.generate_episode(CAND_NS, w, n))
    pairs = [(e, t) for e, ep in enumerate(eps) for t in range(len(ep.steps))]
    pick = np.random.default_rng(W.derive_seed(CAND_NS, "pool", 0)).choice(len(pairs), POOL, replace=False)
    chosen = sorted((eps[pairs[i][0]].n_disks, rank, pairs[i][0], pairs[i][1]) for rank, i in enumerate(pick))
    by_n = {}
    for n, _, e, t in chosen:
        row = by_n.setdefault(n, {"p": [], "v": [], "pil": []})
        row["p"].append(eps[e].steps[t].positions); row["v"].append(eps[e].steps[t].velocities)
        row["pil"].append(np.asarray(eps[e].pillars, dtype=np.float64))
    return {n: {k: np.stack(v) for k, v in d.items()} for n, d in sorted(by_n.items())}


def input_ranges(pool):
    """What the old experience covered: pillar radius and speed ranges (the learner's own record)."""
    r = np.concatenate([e["pil"][:, :, 2].ravel() for e in pool.by_n.values()])
    sp = np.concatenate([np.linalg.norm(e["v"], axis=-1).ravel() for e in pool.by_n.values()])
    return (float(r.min()), float(r.max())), (float(sp.min()), float(sp.max()))


def novelty_flags(states, ranges):
    (r_lo, r_hi), (s_lo, s_hi) = ranges
    total = sum(len(e["id"]) for e in states.values())
    out = np.zeros(total, dtype=bool)
    for e in states.values():
        r = e["pil"][:, :, 2]
        sp = np.linalg.norm(e["v"], axis=-1)
        out[e["id"]] = (r < r_lo).any(-1) | (r > r_hi).any(-1) | (sp < s_lo).any(-1) | (sp > s_hi).any(-1)
    return out


def main():
    out = Path(sys.argv[1]); arms = sys.argv[2].split(",")
    per = int(sys.argv[3]) if len(sys.argv) > 3 else 1500
    rounds = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    steps = int(sys.argv[5]) if len(sys.argv) > 5 else 1000
    lr = float(sys.argv[6]) if len(sys.argv) > 6 else 1e-3
    t0 = time.time()
    rec = json.loads((XA.BASE / "cell.json").read_text())
    old_source = C.candidate_source(XA.OLD_NS, 0)
    assert C.pool_digest(old_source) == rec["pool_sha256"]
    old_pool = C.make_candidate_pool(old_source).reveal(np.array([i for p in rec["tracks"][0]["picks"] for i in p], dtype=np.int64))
    cand = candidates_three_kinds()
    tests_b = [XA.prepare_b(B.generate_episode_b(XA.TEST_B, w, 6)) for w in range(30)]
    tests_a = [C.prepare_world(W.generate_episode(XA.TEST_A, w, 6)) for w in range(30)]
    probe = S.CandidatePool(cand, labeller=B.sim_labels_b, pool_type=L.Pool)
    states0 = probe.states()
    ring = XA.halo_flags(states0)
    cand_key = [None] * len(probe)
    big = np.zeros(len(probe), dtype=bool); tiny = np.zeros(len(probe), dtype=bool)
    for e in states0.values():
        for g, k in zip(e["id"], XD.layout_keys(e["pil"])):
            cand_key[g] = k
        big[e["id"]] = e["pil"][:, :, 2].max(-1) >= B.BIG_MIN
        rmax, rmin = e["pil"][:, :, 2].max(-1), e["pil"][:, :, 2].min(-1)
        tiny[e["id"]] = (rmin <= B.TINY_RADIUS[1]) | ((rmax >= B.LARGE_RADIUS[0] - 1e-6) & (rmax < B.BIG_MIN))   # any decoy world
    ranges = input_ranges(old_pool)
    novel = novelty_flags(states0, ranges)
    above = np.zeros(len(probe), dtype=bool)          # one-sided rule U: a pillar larger than any the old experience had
    for e in states0.values():
        above[e["id"]] = e["pil"][:, :, 2].max(-1) > ranges[0][1]
    mx.set_default_device(mx.cpu)
    base_models = [C.load_model("E", XA.BASE / f"r3-n{j}.safetensors") for j in range(3)]
    base_head = XC.fit_head(*XC.error_rows(old_pool, base_models), 107)
    print(f"pool {len(probe)}: big-world {big.mean():.3f}, tiny-world {tiny.mean():.3f}, ring {ring.mean():.3f}; "
          f"old ranges radius {ranges[0][0]:.3f}-{ranges[0][1]:.3f} speed {ranges[1][0]:.3f}-{ranges[1][1]:.3f}; "
          f"novel-input flag {novel.mean():.3f} (big {novel[big].mean():.2f}, tiny {novel[tiny].mean():.2f}, ordinary {novel[~big & ~tiny].mean():.3f}); "
          f"{time.time() - t0:.0f}s", flush=True)
    first = S.pick_random(probe.remaining(), per, np.random.default_rng(W.derive_seed(CAND_NS, "first", 0)))
    res = json.loads(out.read_text()) if out.exists() else {"config": {"per": per, "rounds": rounds, "steps": steps, "lr": lr}, "arms": {}}
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
                gen_new = L.batches(new_pool, steps, XA.BATCH, lr_["rng"], coll_share=0.0)
                gen_old = L.batches(old_pool, steps, XA.BATCH, lr_["rng"], coll_share=0.0)
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
            row = {"round": r, "picks": {"ring": float(ring[pk].mean()), "big_world": float(big[pk].mean()), "tiny_world": float(tiny[pk].mean())},
                   **ev, "per_net": per_net}
            if r < rounds - 1:
                rem = cp.remaining()
                if pick == "R":
                    picks = S.pick_random(rem, per, rng)
                elif pick == "W":
                    picks = S.pick_geo(ring, rem, per, rng)
                elif pick == "Q":
                    picks = S.pick_geo(novel, rem, per, rng)
                elif pick == "U":
                    picks = S.pick_geo(above, rem, per, rng)
                elif pick in ("N", "O"):
                    flagged, mean, med, mad = XD.surprising_layouts(XD.sample_surprise(new_pool, base_models, base_head))
                    flags = np.array([k in flagged for k in cand_key])
                    kb = {k for k, b in zip(cand_key, big) if b}; kt = {k for k, b in zip(cand_key, tiny) if b}
                    row["layouts"] = {"seen": len(mean), "flagged": len(flagged), "big": len(flagged & kb), "tiny": len(flagged & kt),
                                      "big_seen": len(set(mean) & kb)}
                    if pick == "N":
                        picks = S.pick_geo(flags, rem, per, rng)
                    else:            # O (round H): a fifth of every round is drawn at random first (an exploration floor)
                        floor = S.pick_random(rem, per // 5, rng)
                        picks = np.concatenate([floor, S.pick_geo(flags, np.setdiff1d(rem, floor), per - per // 5, rng)])
                else:
                    raise ValueError(arm)
            curve.append(row)
            extra = f" flagged {row['layouts']}" if "layouts" in row else ""
            print(f"{arm} r{r} picks ring {row['picks']['ring']:.3f} big {row['picks']['big_world']:.3f} tiny {row['picks']['tiny_world']:.3f} | "
                  + " ".join(f"{k}={v:.4f}" for k, v in ev.items() if k in ("H", "D_B", "all_B", "D_A", "free_A", "all_A")) + extra
                  + f"  {time.time() - t0:.0f}s", flush=True)
            mx.set_default_device(mx.gpu)
        res["arms"][arm] = curve
        out.write_text(json.dumps(res), encoding="utf-8")
    print(f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
