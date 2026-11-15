#!/usr/bin/env python3
"""S6 r2 review, item 3: recompute DESIGN-r2's round-G numbers (§0 lines 52-53, §1 lines 146-173) from
tier1-explore/results-s6g.json with this file's own arithmetic (not s6/analysis.py), and the K = 1 intervals
of analyze-s6g.log with an independent world bootstrap (own seed, so the bounds agree only approximately).
CPU / NumPy only."""
import json
import math

import numpy as np

X = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN/tier1-explore"
res = json.load(open(f"{X}/results-s6g.json"))
KINDS = ("collision", "graze", "wall_pillar", "free")
cnt = {t: np.array(res["counts"][t], dtype=float) for t in res["counts"]}       # [W, 4]
eb = {t: np.array(res["eb"][t], dtype=float) for t in res["eb"]}                 # [W]
S = {a: {t: np.array(res["arms"][a]["rounds"][3][t]["sums"]) for t in cnt} for a in res["arms"]}  # [nets, W, 4]


def arm_stats(a, t, w=None):
    s = S[a][t] if w is None else S[a][t][:, w]
    c = cnt[t] if w is None else cnt[t][w]
    b = eb[t].sum() if w is None else eb[t][w].sum()
    tot = s.sum(1)                                                               # [nets, 4]
    out = {"D": float(np.mean(1 - tot[:, 0] / b))}
    for k, name in enumerate(KINDS):
        out[name] = float(np.mean(tot[:, k] / c.sum(0)[k]))
    out["all"] = float(np.mean(tot.sum(1) / c.sum()))
    return out


rows = []


def chk(label, design, value, digits):
    shown = (f"{value:+.{digits}f}" if design[0] in "+-−" else f"{value:.{digits}f}").replace("-", "−")
    rows.append((label, design, value, shown, shown == design.replace("-", "−")))


m6 = {a: arm_stats(a, "main6") for a in S}
x10 = {a: arm_stats(a, "extrap10") for a in S}
table = {"R": ("0.732", "0.0330", "0.706", "0.0096", "0.0279", "0.708"), "E": ("0.825", "0.0302", "0.638", "0.0113", "0.0269", "0.794"),
         "Z": ("0.839", "0.0294", "0.727", "0.0096", "0.0269", "0.811"), "T": ("0.783", "0.0627", "0.771", "0.0143", "0.0347", "0.751"),
         "P": ("0.839", "0.0317", "0.634", "0.0109", "0.0264", "0.808"), "G": ("0.881", "0.0378", "0.728", "0.0090", "0.0265", "0.853")}
for a, (d, g, w, f, al, dx) in table.items():
    chk(f"§1 l.148-153 {a} D(6)", d, m6[a]["D"], 3); chk(f"§1 {a} graze", g, m6[a]["graze"], 4)
    chk(f"§1 {a} wall", w, m6[a]["wall_pillar"], 3); chk(f"§1 {a} free", f, m6[a]["free"], 4)
    chk(f"§1 {a} all", al, m6[a]["all"], 4); chk(f"§1 {a} D(10)", dx, x10[a]["D"], 3)
shares = {"E": ("0.028", "0.231", "0.089", "0.077"), "Z": ("0.028", "0.351", "0.158", "0.049"), "G": ("0.028", "0.555", "0.000", "0.001"),
          "R": ("0.028", "0.026", "0.029", "0.032")}
for a, v in shares.items():
    for r, s in enumerate(v):
        chk(f"§1 {a} contact share round {r + 1}", s, res["arms"][a]["contact_share_by_round"][r], 3)
# §0 lines 52-53, §1 lines 169-173
for a, s in (("E", "1.18"), ("Z", "1.00"), ("T", "1.49"), ("G", "0.94")):
    chk(f"§0 l.52 free {a}/R", s, m6[a]["free"] / m6["R"]["free"], 2)
chk("§0 l.44 G vs E D (0.881 / 0.825)", "−0.056", m6["E"]["D"] - m6["G"]["D"], 3)
chk("§1 l.170 D(E)-D(Z)", "−0.014", m6["E"]["D"] - m6["Z"]["D"], 3)
chk("§1 l.171 wall E/Z", "0.877", m6["E"]["wall_pillar"] / m6["Z"]["wall_pillar"], 3)
chk("§1 l.171 graze E/Z", "1.03", m6["E"]["graze"] / m6["Z"]["graze"], 2)
chk("§1 l.172 free E/Z", "1.18", m6["E"]["free"] / m6["Z"]["free"], 2)
chk("§1 l.173 D(P)-D(E)", "+0.013", m6["P"]["D"] - m6["E"]["D"], 3)
chk("§1 l.169 GS +0.093", "+0.093", m6["E"]["D"] - m6["R"]["D"], 3)

# gate point values (own arithmetic) and K=1 intervals (own world bootstrap, normal quantile)
def gates(w6=None, w10=None):
    a = {k: arm_stats(k, "main6", w6) for k in S}
    x = {k: arm_stats(k, "extrap10", w10) for k in S}
    return {"GS": a["E"]["D"] - a["R"]["D"], "GT": (a["E"]["D"] - a["R"]["D"]) - 0.5 * (a["T"]["D"] - a["R"]["D"]),
            "GZ-D": a["E"]["D"] - a["Z"]["D"], "GZ-W": math.log(a["E"]["wall_pillar"] / a["Z"]["wall_pillar"]),
            "GK-A": math.log(a["E"]["all"] / a["R"]["all"]), "GK-F": math.log(a["E"]["free"] / a["Z"]["free"]),
            "GP": a["P"]["D"] - a["R"]["D"], "GX": x["E"]["D"] - x["R"]["D"]}


def zq(p):
    lo, hi = 0.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if 0.5 * (1 + math.erf(mid / math.sqrt(2))) < p else (lo, mid)
    return (lo + hi) / 2


pt = gates()
rng = np.random.default_rng(7)
B = 2000
boot = {g: [] for g in pt}
for _ in range(B):
    w6, w10 = rng.integers(0, 30, 30), rng.integers(0, 15, 15)
    for g, v in gates(w6, w10).items():
        boot[g].append(v)
q = zq(1 - 0.05 / 16)
log_gates = ("GZ-W", "GK-A", "GK-F")
design_pt = {"GS": "+0.093", "GT": "+0.068", "GZ-D": "−0.014", "GZ-W": "0.877", "GK-A": "0.966", "GK-F": "1.177", "GP": "+0.106", "GX": "+0.086"}
print(f"normal quantile at 1 - 0.05/16: {q:.4f}; own world bootstrap {B} draws, seed 7\n")
print(f"{'gate':5} {'own point':>10} {'own K=1 Bonf interval':>26}")
for g, v in pt.items():
    se = float(np.std(boot[g], ddof=1))
    lo, hi = v - q * se, v + q * se
    if g in log_gates:
        val, lo, hi = math.exp(v), math.exp(lo), math.exp(hi)
    else:
        val = v
    chk(f"§1 l.159-166 gate {g} point", design_pt[g], val, 3)
    print(f"{g:5} {val:+10.4f}   [{lo:+.4f}, {hi:+.4f}]")
print()
for lab, d, v, s, ok in rows:
    print(f"{lab:38} | {d:>7} | {v: .6f} | {s:>7} | {'OK' if ok else 'MISMATCH'}")
print(f"\n{sum(r[-1] for r in rows)}/{len(rows)} OK")
