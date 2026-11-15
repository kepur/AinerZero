#!/usr/bin/env python3
"""S6 r1 review, item 4: the numbers DESIGN-r1 added from the r0 review (Z rows, E-Z, composition table,
gate 'exploration values') against r0-review-sub/evidence. Prints design value | recomputed | match
(match = the recomputed value rounded to the design's digits equals the design value). CPU only."""
import json

X = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN"
E = f"{X}/r0-review-sub/evidence"
pz = json.load(open(f"{E}/proxy-s6x.json"))["arms"]
pw = json.load(open(f"{E}/perworld-s6x.json"))["arms"]
z2 = json.load(open(f"{E}/proxy-s6x2.json"))["arms"]["mindist"]["rounds"]
Cd = json.load(open(f"{X}/tier1-explore/results-s6d.json"))["curves"]
last = lambda a, sp="C_all30": a["rounds"][-1][sp]  # noqa: E731
Z, ZD, EC = last(pz["mindist"]), z2[-1]["C_all30"], last(pw["disagree"])
eD = Cd["disagree"][-1]
rows = []


def chk(label, design, value, digits):
    shown = (f"{value:+.{digits}f}" if design[0] in "+-−" else f"{value:.{digits}f}").replace("-", "−")
    rows.append((label, design, value, shown, shown == design.replace("-", "−")))


chk("l.74 Z C D", "0.749", Z["D"], 3); chk("l.74 Z C free", "0.0139", Z["free"], 4); chk("l.74 Z C all", "0.0355", Z["all"], 4)
chk("l.74 Z D D", "0.784", ZD["D"], 3); chk("l.74 Z D free", "0.0148", ZD["free"], 4); chk("l.74 Z D all", "0.0353", ZD["all"], 4)
chk("l.76 Z contact share C (13.5%)", "0.135", pz["mindist"]["rounds"][-1]["disk_contact_share"], 3)
chk("l.76 Z contact share D (14.6%)", "0.146", z2[-1]["disk_contact_share"], 3)
chk("l.80 E-Z D (C)", "−0.006", EC["D"] - Z["D"], 3); chk("l.80 E-Z D (D)", "−0.009", eD["D"] - ZD["D"], 3)
chk("l.81 wall E/Z (C)", "0.90", EC["wall_pillar"] / Z["wall_pillar"], 2); chk("l.81 wall E/Z (D)", "0.93", eD["wall_pillar"] / ZD["wall_pillar"], 2)
chk("l.82 free E/Z (C)", "1.03", EC["free"] / Z["free"], 2); chk("l.82 free E/Z (D)", "1.00", eD["free"] / ZD["free"], 2)
chk("l.83 graze E/Z (D)", "1.12", eD["graze"] / ZD["graze"], 2)
m6 = lambda a: a["rounds"][-1]["main6"]  # noqa: E731
chk("l.114 Z main6 D", "0.741", m6(pz["mindist"])["D"], 3)
for i, s in enumerate(("0.764", "0.713", "0.747")):
    chk(f"l.114 Z main6 seed{i + 1}", s, m6(pz["mindist"])["D_per_seed"][i], 3)
chk("l.114 Z extrap10 D", "0.754", pz["mindist"]["rounds"][-1]["extrap10"]["D"], 3)
chk("l.115 maxspeed main6 D", "0.638", m6(pz["maxspeed"])["D"], 3)
for i, s in enumerate(("0.644", "0.609", "0.660")):
    chk(f"l.115 maxspeed main6 seed{i + 1}", s, m6(pz["maxspeed"])["D_per_seed"][i], 3)
chk("l.115 maxspeed extrap10 D", "0.660", pz["maxspeed"]["rounds"][-1]["extrap10"]["D"], 3)
chk("l.33 maxspeed - random (C)", "−0.025", last(pz["maxspeed"])["D"] - last(pw["random"])["D"], 3)
chk("l.191 GS 6-disk +0.072", "+0.072", m6(pw["disagree"])["D"] - m6(pw["random"])["D"], 3)
chk("l.196 GK-F free E/Z (D) 1.002", "1.002", eD["free"] / ZD["free"], 3)
# composition table (C, main6, random arm, averaged over networks)
r = pw["random"]["rounds"][-1]["per_world"]
seeds = sorted(r)
tot_s = [sum(sum(r[s][w]["sums"][k] for s in seeds) / 3 for w in range(20)) for k in range(4)]
tot_c = [sum(r[seeds[0]][w]["cnt"][k] for w in range(20)) for k in range(4)]
for k, (st, es) in enumerate((("0.9%", "12.0%"), ("6.6%", "9.3%"), ("2.0%", "47.9%"), ("90.6%", "30.7%"))):
    a, b = 100 * tot_c[k] / sum(tot_c), 100 * tot_s[k] / sum(tot_s)
    rows.append((f"l.124-127 composition kind {k} steps", st, a, f"{a:.1f}%", f"{a:.1f}%" == st))
    rows.append((f"l.124-127 composition kind {k} error-sum", es, b, f"{b:.1f}%", f"{b:.1f}%" == es))
for lab, d, v, s, ok in rows:
    print(f"{lab:40} | {d:>7} | {v: .6f} | {s:>7} | {'OK' if ok else 'MISMATCH'}")
print(f"\n{sum(x[-1] for x in rows)}/{len(rows)} OK")
