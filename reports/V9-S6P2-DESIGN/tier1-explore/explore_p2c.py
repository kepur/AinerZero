#!/usr/bin/env python3
"""S6 phase 2 exploration round C: can a learner-internal signal find a rare new mechanism?

Round B: with the ring in only 10% of the candidate worlds, disagreement (E) and version difference (V) did
not find it (ring skill H -0.03 after 6000 experiments, random -0.06, the rule that knows the answer 0.33).

The learner does know one more thing without reading any unrevealed label: how wrong it was on the
experiments it has already run. Two signals built on that, each a small head on the first network's
hidden state (stop-gradient) and node features, trained on revealed samples only:
  X  expected error: the head predicts log one-step error, trained on everything revealed (old experience
     and new experiments); pick the candidates with the largest predicted error (max over disks).
  Y  surprise ratio: one head trained on the old experience, one on the new experiments, both for the
     current networks' error; pick where the new-experiment head exceeds the old-experience head most.
     What was always hard (collisions) cancels; what is newly wrong remains.

Usage (MLX; under the shared lock): explore_p2c.py <out.json> <arms,comma> [b_share] [per] [rounds] [steps] [lr]
Same pool, tests and base as round B.
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
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import cells as C  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402
from ainerzero.v9.experiments.s6 import world_b as B  # noqa: E402

HEAD_STEPS, HEAD_BATCH, EPS = 600, 2048, 1e-3


class Head(nn.Module):
    def __init__(self, din):
        super().__init__()
        self.l1, self.l2 = nn.Linear(din, 64), nn.Linear(64, 1)

    def __call__(self, x):
        return self.l2(nn.relu(self.l1(x)))[..., 0]


def features(model, p, v, pil):
    """Per disk: the network's hidden state and its node features, [S, n, HID + NODE_F] (NumPy)."""
    p, v, pil = mx.array(p), mx.array(v), mx.array(pil)
    nf = L.node_features(p, v, pil)
    _, scal, _ = model.messages(p, v)
    hid = nn.relu(model.up2(nn.relu(model.up1(mx.concatenate([nf, scal], axis=-1)))))
    return np.array(mx.concatenate([hid, nf], axis=-1), dtype=np.float32)


def error_rows(pool, models):
    """(features [M, F], log one-step error [M]) for every disk of every sample of a labelled pool."""
    X, y = [], []
    for n, e in pool.by_n.items():
        f = features(models[0], e["p"], e["v"], e["pil"])
        pred = np.mean([np.array(m(mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"]))[1], dtype=np.float64) for m in models], 0)
        err = np.linalg.norm(pred - e["v1"], axis=-1)
        X.append(f.reshape(-1, f.shape[-1])); y.append(np.log(err.reshape(-1) + EPS))
    return np.concatenate(X), np.concatenate(y).astype(np.float32)


def fit_head(X, y, seed):
    mx.random.seed(seed)
    head = Head(X.shape[1])
    mx.eval(head.parameters())
    opt = optim.Adam(learning_rate=1e-3)
    vg = nn.value_and_grad(head, lambda h, a, b: ((h(a) - b) ** 2).mean())
    rng = np.random.default_rng(seed)
    for _ in range(HEAD_STEPS):
        idx = rng.integers(0, len(X), HEAD_BATCH)
        loss, grads = vg(head, mx.array(X[idx]), mx.array(y[idx]))
        opt.update(head, grads)
        mx.eval(head.parameters(), opt.state)
    return head


def head_scores(states, model, heads):
    """Per head: predicted log error per sample (max over disks), by global id."""
    total = sum(len(e["id"]) for e in states.values())
    out = [np.empty(total) for _ in heads]
    for n, e in states.items():
        f = features(model, e["p"], e["v"], e["pil"])
        for k, h in enumerate(heads):
            out[k][e["id"]] = np.array(h(mx.array(f)), dtype=np.float64).max(-1)
    return out


def surprise(states, model, head_new, head_old):
    total = sum(len(e["id"]) for e in states.values())
    out = np.empty(total)
    for n, e in states.items():
        f = mx.array(features(model, e["p"], e["v"], e["pil"]))
        out[e["id"]] = np.array(head_new(f) - head_old(f), dtype=np.float64).max(-1)
    return out


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
    flags = XA.halo_flags(probe.states())
    first = S.pick_random(probe.remaining(), per, np.random.default_rng(W.derive_seed(XB.CAND_NS, "first", 0)))
    print(f"pool {len(probe)}: {flags.mean():.3f} with a disk in a ring; {time.time() - t0:.0f}s", flush=True)
    res = json.loads(out.read_text()) if out.exists() else {
        "config": {"b_share": b_share, "per": per, "rounds": rounds, "steps": steps, "lr": lr, "head_steps": HEAD_STEPS}, "arms": {}}
    for arm in arms:
        pick, protect = arm[0], arm[1] == "+"
        mx.set_default_device(mx.gpu)
        cp = S.CandidatePool(cand, labeller=B.sim_labels_b, pool_type=L.Pool)
        learners = []
        for j in range(3):
            m = C.load_model("E", XA.BASE / f"r3-n{j}.safetensors")
            learners.append({"model": m, "opt": optim.Adam(learning_rate=lr), "vg": nn.value_and_grad(m, L.rollout_loss),
                             "rng": np.random.default_rng(1000 + j)})
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
            share = float(flags[np.asarray(picks)].mean())
            row = {"round": r, "ring_share_of_picks": share, **ev, "per_net": per_net}
            if r < rounds - 1:
                st, rem = cp.states(), cp.remaining()
                Xn, yn = error_rows(new_pool, models)
                Xo, yo = error_rows(old_pool, models)
                if pick == "X":
                    head = fit_head(np.concatenate([Xn, Xo]), np.concatenate([yn, yo]), 7 + r)
                    score = head_scores(st, models[0], [head])[0]
                elif pick == "Y":
                    h_new, h_old = fit_head(Xn, yn, 7 + r), fit_head(Xo, yo, 107 + r)
                    score = surprise(st, models[0], h_new, h_old)
                else:
                    raise ValueError(arm)
                # how well the score separates ring candidates among those still unrevealed (diagnostic only)
                order = rem[np.argsort(-score[rem])]
                row["ring_share_top_per"] = float(flags[order[:per]].mean())
                row["ring_share_remaining"] = float(flags[rem].mean())
                picks = S.pick_top(score, rem, per)
            curve.append(row)
            print(f"{arm} r{r} picks ring {share:.3f} | " + " ".join(f"{k}={v:.4f}" for k, v in ev.items() if k in ("H", "D_B", "free_B", "all_B", "D_A", "free_A", "all_A"))
                  + f"  {time.time() - t0:.0f}s", flush=True)
            mx.set_default_device(mx.gpu)
        res["arms"][arm] = curve
        out.write_text(json.dumps(res), encoding="utf-8")
    print(f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
