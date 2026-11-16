#!/usr/bin/env python3
"""S6 phase 2 exploration round D: remembering surprise by context.

Round C: a head that predicts where the new experiments are more wrong than the old experience (Y) enriched
ring samples 3-4x but hardly taught the ring (H +0.02; random -0.06; the rule that knows the answer 0.33).

Arm M does not ask a head to generalise. A candidate state carries its pillar layout, and every candidate
of one world has the same layout. The learner keeps, per layout, the mean surprise of the experiments it has
run there: surprise of an experiment = max over disks of (log error - what a head trained on the OLD
experience expects for that disk), so that what was always hard (collisions) cancels. Layouts whose mean
surprise is far above the rest (median + 3 robust standard deviations) are flagged, and the next experiments
are drawn at random from flagged layouts (filled at random if there are too few). Nothing about the new
mechanism is given: only the learner's own errors on revealed experiments.

Arm N (round E) measures the surprise of the PROMOTED version instead (the base networks, with an expectation
head fitted once on the old experience): the gap stays a gap until a new version is promoted.

Usage (MLX; under the shared lock): explore_p2d.py <out.json> <arms,comma> [b_share] [per] [rounds] [steps] [lr]
Same pool, tests and base as rounds B and C.
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
import explore_p2b as XB  # noqa: E402
import explore_p2c as XC  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import cells as C  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402
from ainerzero.v9.experiments.s6 import world_b as B  # noqa: E402


def layout_keys(pil):
    a = np.ascontiguousarray(pil, dtype=np.float32)
    return [a[i].tobytes() for i in range(len(a))]


def sample_surprise(pool, models, head_old):
    """Per revealed sample: (layout key, max over disks of log error minus the old-experience expectation)."""
    out = []
    for n, e in pool.by_n.items():
        f = XC.features(models[0], e["p"], e["v"], e["pil"])
        pred = np.mean([np.array(m(mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"]))[1], dtype=np.float64) for m in models], 0)
        err = np.linalg.norm(pred - e["v1"], axis=-1)
        s = (np.log(err + XC.EPS) - np.array(head_old(mx.array(f)), dtype=np.float64)).max(-1)
        out += list(zip(layout_keys(e["pil"]), s.tolist()))
    return out


def surprising_layouts(rows):
    by = {}
    for k, s in rows:
        by.setdefault(k, []).append(s)
    mean = {k: float(np.mean(v)) for k, v in by.items()}
    vals = np.array(list(mean.values()))
    med = np.median(vals)
    mad = 1.4826 * np.median(np.abs(vals - med))
    return {k for k, v in mean.items() if v > med + 3 * mad}, mean, float(med), float(mad)


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
    cand = XB.candidates_mixed(b_share)
    tests_b = [XA.prepare_b(B.generate_episode_b(XA.TEST_B, w, 6)) for w in range(30)]
    tests_a = [C.prepare_world(W.generate_episode(XA.TEST_A, w, 6)) for w in range(30)]
    probe = S.CandidatePool(cand, labeller=B.sim_labels_b, pool_type=L.Pool)
    states0 = probe.states()
    flags_true = XA.halo_flags(states0)
    cand_key = [None] * len(probe)
    big = np.zeros(len(probe), dtype=bool)
    for e in states0.values():
        for g, k in zip(e["id"], layout_keys(e["pil"])):
            cand_key[g] = k
        big[e["id"]] = e["pil"][:, :, 2].max(-1) >= B.BIG_MIN
    n_layouts = len(set(cand_key)); n_big = len({k for k, b in zip(cand_key, big) if b})
    first = S.pick_random(probe.remaining(), per, np.random.default_rng(W.derive_seed(XB.CAND_NS, "first", 0)))
    mx.set_default_device(mx.cpu)
    base_models = [C.load_model("E", XA.BASE / f"r3-n{j}.safetensors") for j in range(3)]
    base_head = XC.fit_head(*XC.error_rows(old_pool, base_models), 107)
    print(f"pool {len(probe)}: {n_layouts} layouts, {n_big} with a big pillar; {time.time() - t0:.0f}s", flush=True)
    res = json.loads(out.read_text()) if out.exists() else {
        "config": {"b_share": b_share, "per": per, "rounds": rounds, "steps": steps, "lr": lr}, "arms": {}}
    for arm in arms:
        pick, protect = arm[0], arm[1] == "+"
        mx.set_default_device(mx.gpu)
        cp = S.CandidatePool(cand, labeller=B.sim_labels_b, pool_type=L.Pool)
        learners = []
        for j in range(3):
            m = C.load_model("E", XA.BASE / f"r3-n{j}.safetensors")
            learners.append({"model": m, "opt": optim.Adam(learning_rate=lr), "vg": nn.value_and_grad(m, L.rollout_loss),
                             "rng": np.random.default_rng(1000 + j)})
        rng = np.random.default_rng(W.derive_seed(XB.CAND_NS, "pick", pick, 0))
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
            row = {"round": r, "picks": {"ring": float(flags_true[pk].mean()), "big_world": float(big[pk].mean())}, **ev, "per_net": per_net}
            if r < rounds - 1:
                rem = cp.remaining()
                if pick in ("M", "N"):
                    if pick == "M":      # surprise of the current networks; the expectation head is refitted every round
                        Xo, yo = XC.error_rows(old_pool, models)
                        head_old = XC.fit_head(Xo, yo, 107 + r)
                        flagged, mean, med, mad = surprising_layouts(sample_surprise(new_pool, models, head_old))
                    else:                # N: surprise of the PROMOTED version (the base networks), expectation head fitted once
                        flagged, mean, med, mad = surprising_layouts(sample_surprise(new_pool, base_models, base_head))
                    flags = np.array([k in flagged for k in cand_key])
                    truly = {k for k, b in zip(cand_key, big) if b}
                    row["layouts"] = {"seen": len(mean), "flagged": len(flagged), "flagged_big": len(flagged & truly),
                                      "big_total": len(truly), "median": med, "mad": mad}
                    picks = S.pick_geo(flags, rem, per, rng)
                else:
                    raise ValueError(arm)
            curve.append(row)
            extra = f" layouts flagged {row['layouts']['flagged']} ({row['layouts']['flagged_big']} big of {row['layouts']['big_total']})" if "layouts" in row else ""
            print(f"{arm} r{r} picks ring {row['picks']['ring']:.3f} big-world {row['picks']['big_world']:.3f} | "
                  + " ".join(f"{k}={v:.4f}" for k, v in ev.items() if k in ("H", "D_B", "free_B", "all_B", "D_A", "free_A", "all_A"))
                  + extra + f"  {time.time() - t0:.0f}s", flush=True)
            mx.set_default_device(mx.gpu)
        res["arms"][arm] = curve
        out.write_text(json.dumps(res), encoding="utf-8")
    print(f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
