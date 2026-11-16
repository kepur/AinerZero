#!/usr/bin/env python3
"""Evaluate cheaper rules on round-G candidate pool (600 worlds: 60 big, 60 tiny, 480 ordinary).

Rules tested:
  K+  Raw prediction error by layout (NO expectation head, NO learned baseline).
      On revealed samples, computes raw ||v_pred - v_true||, takes max over disks,
      groups by layout, flags layouts with mean > median + 3*MAD, with 20% random floor.
  D+  Radius deviation from old experience mean (zero model, zero labels).
      Flags candidates with max_i |r_i - mean(r_old)| >= 0.40, with 20% random floor.
  P+  Disk-to-pillar surface proximity (zero model, zero labels).
      Flags candidates where min gap to any pillar surface < 1.2 (within halo width).

Environment: S6P2_WORLDS=600 S6P2_BIG=60 S6P2_TINY=60 S6P2_NS=s6x-p2g-cand
"""
import json
import os
import sys
import time
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tier1-explore"))
import explore_p2a as XA  # noqa: E402
import explore_p2c as XC  # noqa: E402
import explore_p2d as XD  # noqa: E402
import explore_p2f as XF  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import cells as C  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402
from ainerzero.v9.experiments.s6 import world_b as B  # noqa: E402

CAND_NS = os.environ.get("S6P2_NS", "s6x-p2g-cand")
CAND_WORLDS = int(os.environ.get("S6P2_WORLDS", 600))
N_BIG = int(os.environ.get("S6P2_BIG", 60))
N_TINY = int(os.environ.get("S6P2_TINY", 60))
POOL = 60_000

def raw_error_surprise(pool, models):
    """Raw prediction error without subtracting any expectation head."""
    out = []
    for n, e in pool.by_n.items():
        pred = np.mean([np.array(m(mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"]))[1], dtype=np.float64) for m in models], 0)
        err = np.linalg.norm(pred - e["v1"], axis=-1)
        # raw log error, no expectation head subtraction
        s = np.log(err + XC.EPS).max(-1)
        out += list(zip(XD.layout_keys(e["pil"]), s.tolist()))
    return out

def pillar_radius_deviation_flags(states, mean_r=0.60, thresh=0.40):
    total = sum(len(e["id"]) for e in states.values())
    out = np.zeros(total, dtype=bool)
    for e in states.values():
        dev = np.abs(e["pil"][:, :, 2] - mean_r).max(-1)
        out[e["id"]] = dev >= thresh
    return out

def disk_pillar_proximity_flags(states, max_gap=1.2):
    total = sum(len(e["id"]) for e in states.values())
    out = np.zeros(total, dtype=bool)
    for e in states.values():
        # p: [batch, n_disks, 2], pil: [batch, 3, 3] (cx, cy, r)
        p = e["p"]
        pil = e["pil"]
        # gap per disk, pillar: hypot(p - c) - r - RADIUS
        # shape [batch, n_disks, 3]
        dx = p[:, :, None, 0] - pil[:, None, :, 0]
        dy = p[:, :, None, 1] - pil[:, None, :, 1]
        dist = np.hypot(dx, dy) - pil[:, None, :, 2] - W.RADIUS
        min_gap_per_state = dist.min(axis=(1, 2))
        out[e["id"]] = min_gap_per_state < max_gap
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
    
    cand = XF.candidates_three_kinds()
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
        tiny[e["id"]] = e["pil"][:, :, 2].min(-1) <= B.TINY_RADIUS[1]
    
    ranges = XF.input_ranges(old_pool)
    mean_old_r = float(np.mean([e["pil"][:, :, 2].mean() for e in old_pool.by_n.values()]))
    dev_flags = pillar_radius_deviation_flags(states0, mean_r=mean_old_r, thresh=0.38)
    prox_flags = disk_pillar_proximity_flags(states0, max_gap=1.2)
    
    mx.set_default_device(mx.cpu)
    base_models = [C.load_model("E", XA.BASE / f"r3-n{j}.safetensors") for j in range(3)]
    
    print(f"pool {len(probe)}: big {big.mean():.3f}, tiny {tiny.mean():.3f}, ring {ring.mean():.3f}; "
          f"dev_flags {dev_flags.mean():.3f} (big {dev_flags[big].mean():.2f}, tiny {dev_flags[tiny].mean():.2f}); "
          f"prox_flags {prox_flags.mean():.3f} (big {prox_flags[big].mean():.2f}); {time.time() - t0:.0f}s", flush=True)
          
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
                if pick == "K":
                    # Raw prediction error by layout without expectation head
                    raw_surp = raw_error_surprise(new_pool, base_models)
                    flagged, mean, med, mad = XD.surprising_layouts(raw_surp)
                    flags = np.array([k in flagged for k in cand_key])
                    kb = {k for k, b in zip(cand_key, big) if b}; kt = {k for k, b in zip(cand_key, tiny) if b}
                    row["layouts"] = {"seen": len(mean), "flagged": len(flagged), "big": len(flagged & kb), "tiny": len(flagged & kt),
                                      "big_seen": len(set(mean) & kb)}
                    floor = S.pick_random(rem, per // 5, rng)
                    picks = np.concatenate([floor, S.pick_geo(flags, np.setdiff1d(rem, floor), per - per // 5, rng)])
                elif pick == "D":
                    floor = S.pick_random(rem, per // 5, rng)
                    picks = np.concatenate([floor, S.pick_geo(dev_flags, np.setdiff1d(rem, floor), per - per // 5, rng)])
                elif pick == "P":
                    floor = S.pick_random(rem, per // 5, rng)
                    picks = np.concatenate([floor, S.pick_geo(prox_flags, np.setdiff1d(rem, floor), per - per // 5, rng)])
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
