#!/usr/bin/env python3
"""Summarize explore_p2d/e/f (optionally one kind: main or extrap): per arm, re-identification on collision / non-collision / all events (seeds
averaged per event), paired world-bootstrap differences against E-B, one-step coverage by step kind,
and calibration at reappearance (coverage of the 90% region, NLL, error and spread) by event kind and gap."""
import json
import sys
from collections import defaultdict

import numpy as np

r = json.load(open(sys.argv[1]))
W = [w for w in r["per_world"] if len(sys.argv) < 3 or w.get("kind", "main") == sys.argv[2]]
arms = sorted({k.rsplit("#", 1)[0] for k in W[0]["cells"]})
GAPS = (0, 10, 25, 50, 10_000)


def ok(w, arm):
    return not any(w["cells"][f"{arm}#{s}"].get("diverged") for s in (1, 2, 3))


def acc_world(arm, which):
    out = []
    for w in W:
        if not w["events"] or not ok(w, arm):
            out.append((0.0, 0)); continue
        per = np.mean([w["cells"][f"{arm}#{s}"]["correct"] for s in (1, 2, 3)], axis=0)
        coll = np.array([e[3] == 1 for e in w["events"]])
        m = {"coll": coll, "non": ~coll, "all": np.ones_like(coll)}[which]
        out.append((float(per[m].sum()), int(m.sum())))
    return np.array(out)


def boot_diff(a, b, n=4000, seed=20261111):
    rng = np.random.default_rng(seed)
    pt = a[:, 0].sum() / a[:, 1].sum() - b[:, 0].sum() / b[:, 1].sum()
    idx = rng.integers(0, len(a), (n, len(a)))
    d = a[idx, 0].sum(1) / a[idx, 1].sum(1) - b[idx, 0].sum(1) / b[idx, 1].sum(1)
    return pt, *np.quantile(d, [0.025, 0.975])


def boot_C(x, b, p, n=4000, seed=20261111):
    rng = np.random.default_rng(seed)
    f = lambda X, B, P: (X[..., 0].sum(-1) / X[..., 1].sum(-1) - B[..., 0].sum(-1) / B[..., 1].sum(-1)) / (P[..., 0].sum(-1) / P[..., 1].sum(-1) - B[..., 0].sum(-1) / B[..., 1].sum(-1))
    idx = rng.integers(0, len(x), (n, len(x)))
    return f(x, b, p), *np.quantile(f(x[idx], b[idx], p[idx]), [0.025, 0.975])


eb = {k: acc_world("E-B", k) for k in ("coll", "non", "all")}
ep = acc_world("E-P", "coll")
print(f"{'arm':16} {'coll':>6} {'non':>6} {'all':>6} | non-EB [95%]        | all-EB [95%]        | C [95%]")
for a in arms:
    x = {k: acc_world(a, k) for k in ("coll", "non", "all")}
    v = {k: x[k][:, 0].sum() / x[k][:, 1].sum() for k in x}
    dn, dl = boot_diff(x["non"], eb["non"]), boot_diff(x["all"], eb["all"])
    c = boot_C(x["coll"], eb["coll"], ep)
    print(f"{a:16} {v['coll']:6.3f} {v['non']:6.3f} {v['all']:6.3f} | {dn[0]:+.3f} [{dn[1]:+.3f},{dn[2]:+.3f}] | {dl[0]:+.3f} [{dl[1]:+.3f},{dl[2]:+.3f}] | {c[0]:.2f} [{c[1]:.2f},{c[2]:.2f}]")

print("\none-step coverage (all / collision / free), reappearance coverage (collision events / non-collision), by gap bins (all events)")
for a in arms:
    one = defaultdict(lambda: [0, 0.0])
    rows = []
    nd = sum(1 for w in W for s in (1, 2, 3) if w["cells"][f"{a}#{s}"].get("diverged"))
    if nd:
        print(f"{a:16} diverged cells {nd}, worlds dropped {sum(1 for w in W if not ok(w, a))}")
    for w in W:
        for s in (1, 2, 3):
            c = w["cells"][f"{a}#{s}"]
            if c.get("diverged"):
                continue
            for k, (n, ins) in c["one_step"].items():
                one[k][0] += n; one[k][1] += ins
            rows += c["reappear"]
    R = np.array(rows, dtype=float)
    if not len(R):
        continue
    cov = lambda m: R[m, 2].mean() if m.sum() else float("nan")
    gb = [cov((R[:, 1] >= lo) & (R[:, 1] < hi)) for lo, hi in zip(GAPS[:-1], GAPS[1:])]
    print(f"{a:16} 1-step {one['all'][1]/one['all'][0]:.3f}/{one['collision'][1]/max(one['collision'][0],1):.3f}/{one['free'][1]/one['free'][0]:.3f} | "
          f"reappear coll {cov(R[:, 0] == 1):.3f} non {cov(R[:, 0] == 0):.3f} | gaps " + " ".join(f"{g:.3f}" for g in gb) +
          f" | nll {np.median(R[:, 3]):.2f}(med) err {R[:, 4].mean():.3f} spread {R[:, 5].mean():.3f} n {len(R)}")
