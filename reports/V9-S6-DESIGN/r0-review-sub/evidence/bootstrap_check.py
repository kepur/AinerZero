#!/usr/bin/env python3
"""S6 r0 review, items 2-4 (CPU only): read the per-world sums written by proxy_rules.py and

(a) reproduction: compare the rerun random / disagree / truthcur rounds with results-s6c.json (bit for bit?);
(b) item 2: apply DESIGN-r0's GS and GK criteria to the zero-knowledge proxy rules, with the design's
    statistics (per world average over the arm's networks, then paired bootstrap over worlds, 10000 draws,
    95% and Bonferroni m = 6), against the rerun random arm;
(c) item 3: compare the world-bootstrap spread of a difference with the spread across the four
    exploration runs (C, D, r3, r4) and across same-seed networks.

Splits: C_all30 (round C's combined 20 six-disk + 10 ten-disk test, the scale of 0.676 / 0.744 / 0.749),
main6 (the design's main evaluation is six-disk only), extrap10.
"""
import json
import sys

import numpy as np

from ainerzero.v9.experiments.s4 import metrics as M

E = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN/r0-review-sub/evidence"
X = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN"
M_BONF = 6
KINDS = ("collision", "graze", "wall_pillar", "free")

runs = {}
for f in ("perworld-s6x.json", "proxy-s6x.json"):
    try:
        d = json.load(open(f"{E}/{f}"))
    except FileNotFoundError:
        print(f"missing {f}"); continue
    runs.update(d["arms"])
splits = {"C_all30": list(range(30)), "main6": list(range(20)), "extrap10": list(range(20, 30))}


def world_sums(arm, rnd=-1):
    """Per world, averaged over the arm's networks: coll, wall, free, all error sums; counts; E-B coll."""
    pw = runs[arm]["rounds"][rnd]["per_world"]
    seeds = sorted(pw)
    nW = len(pw[seeds[0]])
    s = np.array([[pw[k][w]["sums"] for w in range(nW)] for k in seeds])        # [nets, W, 4]
    c = np.array([pw[seeds[0]][w]["cnt"] for w in range(nW)], dtype=float)       # [W, 4]
    eb = np.array([pw[seeds[0]][w]["eb_coll"] for w in range(nW)])
    return s, c, eb


def boot(stat, sums, idx):
    return M.bootstrap(stat, {k: np.asarray(v)[idx] for k, v in sums.items()}, m=M_BONF)


def fmt(b):
    if b["ci_low"] is None:
        return f"{b['value']:+.4f} [no interval]"
    return f"{b['value']:+.4f}  95% [{b['ci_low']:+.4f}, {b['ci_high']:+.4f}]  Bonf(m=6) [{b['bonf_low']:+.4f}, {b['bonf_high']:+.4f}]"


# (a) reproduction against results-s6c.json
print("=== (a) rerun vs results-s6c.json (round C), C_all30, full precision ===")
C = json.load(open(f"{X}/tier1-explore/results-s6c.json"))["curves"]
for arm in ("random", "disagree", "truthcur", "maxspeed", "mindist"):
    if arm not in runs:
        continue
    ref_arm = arm if arm in C else "random"
    rounds = range(len(runs[arm]["rounds"])) if arm in C else [0]   # proxies share only round 0 with random
    for r in rounds:
        mine = runs[arm]["rounds"][r]["C_all30"]
        ref = C[ref_arm][r]
        diffs = {k: mine[k] - ref[k] for k in ("collision", "graze", "wall_pillar", "free", "all", "D")}
        same = all(mine[k] == ref[k] for k in diffs)
        print(f"{arm:9} r{r} vs {ref_arm} r{r}: bit-identical={same}  max|diff|={max(abs(v) for v in diffs.values()):.3e}  "
              f"D {mine['D']!r} vs {ref['D']!r}; contact share {runs[arm]['rounds'][r]['disk_contact_share']!r} vs {ref['disk_contact_share']!r}")

if "random" not in runs:
    sys.exit("no random arm with per-world sums yet")

# (b) GS / GK for every arm against the rerun random arm
print("\n=== (b) DESIGN-r0 GS / GK criteria, each arm vs the rerun random arm, round 3 (12000 labels) ===")
sR, cR, eb = world_sums("random")
for split, idx in splits.items():
    print(f"\n--- split {split} ({len(idx)} worlds) ---")
    for arm in ("disagree", "truthcur", "maxspeed", "mindist"):
        if arm not in runs:
            continue
        sX, cX, ebX = world_sums(arm)
        assert np.array_equal(cX, cR) and np.array_equal(ebX, eb)
        xm, rm = sX.mean(0), sR.mean(0)     # per world, averaged over the 3 networks
        sums = {"x_coll": xm[:, 0], "r_coll": rm[:, 0], "b": eb, "x_all": xm.sum(1), "r_all": rm.sum(1),
                "x_wall": xm[:, 2], "r_wall": rm[:, 2], "x_free": xm[:, 3], "r_free": rm[:, 3]}
        dD = boot(lambda x_coll, r_coll, b, **_: (r_coll - x_coll) / b, sums, idx)
        rall = boot(lambda x_all, r_all, **_: M._ratio(x_all, r_all), sums, idx)
        rwall = boot(lambda x_wall, r_wall, **_: M._ratio(x_wall, r_wall), sums, idx)
        rfree = boot(lambda x_free, r_free, **_: M._ratio(x_free, r_free), sums, idx)
        per_net = [float((sR[k][idx, 0].sum() - sX[k][idx, 0].sum()) / eb[idx].sum()) for k in range(3)]
        dX = 1 - xm[idx, 0].sum() / eb[idx].sum()
        dR = 1 - rm[idx, 0].sum() / eb[idx].sum()
        gs = dD["value"] >= 0.03 and dD["bonf_low"] is not None and dD["bonf_low"] > 0 and all(p > 0 for p in per_net)
        gk_all = rall["value"] <= 1.10 and rall["bonf_high"] is not None and rall["bonf_high"] <= 1.20
        gk_wall = rwall["value"] <= 1.0 and rwall["bonf_high"] is not None and rwall["bonf_high"] <= 1.10
        print(f"{arm:9} D={dX:.4f} (random {dR:.4f})")
        print(f"   dD vs random     {fmt(dD)}   per network (same seed) {['%+.4f' % p for p in per_net]}  -> GS {'PASS' if gs else 'fail'}")
        print(f"   all-step ratio   {fmt(rall)}  -> GK(all) {'PASS' if gk_all else 'fail'}")
        print(f"   wall ratio       {fmt(rwall)}  -> GK(wall) {'PASS' if gk_wall else 'fail'}")
        print(f"   free ratio       {fmt(rfree)}  (not gated in DESIGN-r0)")

# (c) item 3: world bootstrap vs run-to-run spread
print("\n=== (c) world-bootstrap spread vs spread across runs / networks (round 3) ===")
for (a, b_), sp in [(p, q) for p in (("disagree", "random"), ("disagree", "truthcur"), ("truthcur", "random")) for q in ("C_all30", "main6")]:
    if a not in runs or b_ not in runs:
        continue
    sA, _, _ = world_sums(a); sB, _, _ = world_sums(b_)
    idx = splits[sp]
    print(f"[{sp}]", end=" ")
    sums = {"a": sA.mean(0)[:, 0], "bb": sB.mean(0)[:, 0], "e": eb}  # all 30 worlds; idx selects
    bt = boot(lambda a, bb, e, **_: (bb - a) / e, sums, idx)
    rng = np.random.default_rng(M.BOOT_SEED)
    draws = rng.integers(0, len(idx), size=(M.BOOT_N, len(idx)))
    se = float(np.std((sums["bb"][idx][draws].sum(1) - sums["a"][idx][draws].sum(1)) / sums["e"][idx][draws].sum(1), ddof=1))
    per_net = [float((sB[k][idx, 0].sum() - sA[k][idx, 0].sum()) / eb[idx].sum()) for k in range(3)]
    print(f"D({a}) - D({b_}): {fmt(bt)}")
    print(f"   world-bootstrap SE ({len(idx)} worlds) {se:.4f}; scaled to 50 / 200 worlds ~ {se * np.sqrt(len(idx) / 50):.4f} / {se * np.sqrt(len(idx) / 200):.4f}")
    print(f"   same-seed per-network differences {['%+.4f' % p for p in per_net]}  SD {np.std(per_net, ddof=1):.4f}")
four = {}
for name, path in (("C", "tier1-explore/results-s6c.json"), ("D", "tier1-explore/results-s6d.json"),
                   ("r3", "replication/results-s6r3.json"), ("r4", "replication/results-s6r4.json")):
    cur = json.load(open(f"{X}/{path}"))["curves"]
    four[name] = (cur["disagree"][-1]["D"] - cur["random"][-1]["D"], cur["disagree"][-1]["D"] - cur["truthcur"][-1]["D"],
                  cur["truthcur"][-1]["D"] - cur["random"][-1]["D"])
for j, lab in enumerate(("E-R", "E-T", "T-R")):
    v = np.array([four[k][j] for k in four])
    print(f"four exploration runs {lab}: {['%+.4f' % x for x in v]}  mean {v.mean():+.4f}  SD {v.std(ddof=1):.4f}  range {v.max() - v.min():.4f}")

# (d) what the rules pick: per round, the new picks' disk-contact and geo shares, and overlap with disagree's picks
print("\n=== (d) selections: new picks per round (rounds 1-3), overlap with disagree's new picks ===")
per = 3000
for arm in ("disagree", "maxspeed", "mindist", "random", "truthcur"):
    if arm not in runs:
        continue
    ch = runs[arm]["chosen"]
    line = []
    for r in (1, 2, 3):
        new = set(ch[r * per:(r + 1) * per])
        ov = ""
        if "disagree" in runs and arm != "disagree":
            dn = set(runs["disagree"]["chosen"][r * per:(r + 1) * per])
            ov = f" overlap-with-disagree {len(new & dn) / per:.3f}"
        line.append(f"r{r}:{ov}")
    rows_ = runs[arm]["rounds"]
    shares = [f"{rows_[r]['disk_contact_share']:.3f}/{rows_[r]['geo_share']:.3f}" for r in range(len(rows_))]
    print(f"{arm:9} cumulative contact/geo share by round {shares}  {' '.join(line)}")
    allsel = set(ch)
    if "disagree" in runs and arm != "disagree":
        print(f"{'':9} overlap of all 12000 chosen with disagree's 12000: {len(allsel & set(runs['disagree']['chosen'])) / len(allsel):.3f}")

# (e) disagree against the zero-knowledge distance rule (what a gate "E beats the proxy" would see)
print("\n=== (e) disagree (E) vs mindist (Z), round 3, design statistics (Bonferroni m=6) ===")
if "disagree" in runs and "mindist" in runs:
    sE, _, _ = world_sums("disagree"); sZ, _, _ = world_sums("mindist")
    for split, idx in splits.items():
        em, zm = sE.mean(0), sZ.mean(0)
        sums = {"e_coll": em[:, 0], "z_coll": zm[:, 0], "b": eb, "e_wall": em[:, 2], "z_wall": zm[:, 2],
                "e_all": em.sum(1), "z_all": zm.sum(1), "e_free": em[:, 3], "z_free": zm[:, 3]}
        d = boot(lambda e_coll, z_coll, b, **_: (z_coll - e_coll) / b, sums, idx)
        w = boot(lambda e_wall, z_wall, **_: M._ratio(e_wall, z_wall), sums, idx)
        a = boot(lambda e_all, z_all, **_: M._ratio(e_all, z_all), sums, idx)
        f = boot(lambda e_free, z_free, **_: M._ratio(e_free, z_free), sums, idx)
        per_net = [float((sZ[k][idx, 0].sum() - sE[k][idx, 0].sum()) / eb[idx].sum()) for k in range(3)]
        print(f"{split:8} D(E)-D(Z) {fmt(d)}  per network {['%+.4f' % p for p in per_net]}")
        print(f"{'':8} wall E/Z  {fmt(w)}")
        print(f"{'':8} all  E/Z  {fmt(a)}")
        print(f"{'':8} free E/Z  {fmt(f)}")

# (f) what the all-step error is made of (random arm, round 3, main6): share of disk-steps and of the error sum by kind
print("\n=== (f) composition of the all-step error (round 3, main6, averaged over networks) ===")
idx = splits["main6"]
for arm in ("random", "disagree", "mindist"):
    if arm not in runs:
        continue
    s, c, _ = world_sums(arm)
    tot_s = s.mean(0)[idx].sum(0); tot_c = c[idx].sum(0)
    print(f"{arm:9} " + "  ".join(f"{KINDS[k]}: steps {tot_c[k] / tot_c.sum():.3f}, error-sum {tot_s[k] / tot_s.sum():.3f}" for k in range(4)))
