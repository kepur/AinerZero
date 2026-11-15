#!/usr/bin/env python3
"""S6 r0 review, item 4: recompute DESIGN-r0 §1 numbers from the exploration JSONs (CPU, read only).

Each line: label | design value (as printed in DESIGN-r0.md) | recomputed (full precision, then rounded
to the design's digits) | match. Rounding: the design's number of decimals; differences are computed from
full-precision JSON values, ratios likewise.
"""
import json

B = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN"
C = json.load(open(f"{B}/tier1-explore/results-s6c.json"))["curves"]
D = json.load(open(f"{B}/tier1-explore/results-s6d.json"))["curves"]
F = json.load(open(f"{B}/tier1-explore/results-s6f.json"))["curves"]
E2 = json.load(open(f"{B}/tier1-explore/results-s6e2.json"))["curves"]
R3 = json.load(open(f"{B}/replication/results-s6r3.json"))["curves"]
R4 = json.load(open(f"{B}/replication/results-s6r4.json"))["curves"]
RUNS = {"C": C, "D": D, "r3": R3, "r4": R4}

rows = []


def chk(label, design, value, digits):
    """design: the string printed in DESIGN-r0.md (with its sign); value: recomputed float."""
    shown = f"{value:+.{digits}f}" if design.startswith(("+", "−", "-")) else f"{value:.{digits}f}"
    norm = design.replace("−", "-")
    ok = float(norm) == float(shown)
    rows.append((label, design, value, shown, "OK" if ok else "MISMATCH"))


last = lambda curves, arm: curves[arm][-1]  # noqa: E731

# --- table C/D (DESIGN-r0.md lines 53-58)
for run, cur, arms in (("C", C, ("random", "disagree", "oracle", "truthcur")), ("D", D, ("random", "disagree", "truthcur"))):
    design = {
        ("C", "random"): ("0.676", "0.0107", "0.0338"), ("C", "disagree"): ("0.744", "0.0144", "0.0352"),
        ("C", "oracle"): ("0.723", "0.0151", "0.0366"), ("C", "truthcur"): ("0.749", "0.0151", "0.0406"),
        ("D", "random"): ("0.707", "0.0125", "0.0348"), ("D", "disagree"): ("0.775", "0.0149", "0.0347"),
        ("D", "truthcur"): ("0.758", "0.0206", "0.0454"),
    }
    for arm in arms:
        dD, dfree, dall = design[(run, arm)]
        r = last(cur, arm)
        chk(f"§1 C/D table {run} {arm} D", dD, r["D"], 3)
        chk(f"§1 C/D table {run} {arm} free", dfree, r["free"], 4)
        chk(f"§1 C/D table {run} {arm} all", dall, r["all"], 4)

# --- text lines 60-62
chk("§1 l.60 disagree contact share, round 1 (C) [12-15%]", "0.135", C["disagree"][1]["disk_contact_share"], 3)
chk("§1 l.60 disagree contact share, round 1 (D)", "0.155", D["disagree"][1]["disk_contact_share"], 3)
chk("§1 l.60 random contact share (C, 12000) [2.8%]", "0.028", last(C, "random")["disk_contact_share"], 3)
chk("§1 l.61 wall disagree C", "0.704", last(C, "disagree")["wall_pillar"], 3)
chk("§1 l.61 wall random C", "0.775", last(C, "random")["wall_pillar"], 3)
chk("§1 l.61 wall disagree D", "0.722", last(D, "disagree")["wall_pillar"], 3)
chk("§1 l.61 wall random D", "0.785", last(D, "random")["wall_pillar"], 3)
chk("§1 l.61 free diff C (text says +0.0037)", "+0.0037", last(C, "disagree")["free"] - last(C, "random")["free"], 4)
chk("§1 l.61 free diff D (text says +0.0024)", "+0.0024", last(D, "disagree")["free"] - last(D, "random")["free"], 4)
chk("§1 l.62 E-T C", "−0.005", last(C, "disagree")["D"] - last(C, "truthcur")["D"], 3)
chk("§1 l.62 E-T D", "+0.017", last(D, "disagree")["D"] - last(D, "truthcur")["D"], 3)

# --- four-run table (lines 66-71)
four = {"C": ("+0.068", "+0.0036", "1.04", "0.91", "−0.006"), "D": ("+0.068", "+0.0023", "1.00", "0.92", "+0.017"),
        "r3": ("+0.077", "+0.0036", "1.01", "0.87", "+0.047"), "r4": ("+0.083", "+0.0027", "1.02", "0.94", "+0.014")}
for run, (dd, df, ra, rw, dt) in four.items():
    cur = RUNS[run]
    e, r, t = last(cur, "disagree"), last(cur, "random"), last(cur, "truthcur")
    chk(f"§1 four-run {run} E-R dD", dd, e["D"] - r["D"], 3)
    chk(f"§1 four-run {run} E-R dfree", df, e["free"] - r["free"], 4)
    chk(f"§1 four-run {run} all E/R", ra, e["all"] / r["all"], 2)
    chk(f"§1 four-run {run} wall E/R", rw, e["wall_pillar"] / r["wall_pillar"], 2)
    chk(f"§1 four-run {run} E-T dD", dt, e["D"] - t["D"], 3)

# --- E2 (line 77)
e2 = E2[-1]
chk("§1 l.77 E2 D", "0.746", e2["D"], 3)
chk("§1 l.77 E2 free", "0.0138", e2["free"], 4)
chk("§1 l.77 E2 all", "0.0344", e2["all"], 4)
chk("§1 l.78 E2 round-0 D", "0.471", E2[0]["D"], 3)
chk("§4 GP 'E2' P-R (+0.070), R from run C", "+0.070", e2["D"] - last(C, "random")["D"], 3)

# --- F table (lines 84-88)
fd = {"random": ("0.661", ("0.673", "0.639", "0.672"), "0.0105", "0.756", "0.0311", "0.686"),
      "disagree": ("0.733", ("0.746", "0.706", "0.746"), "0.0134", "0.691", "0.0321", "0.751"),
      "geo": ("0.795", ("0.809", "0.766", "0.810"), "0.0095", "0.795", "0.0300", "0.807")}
for arm, (d6, seeds, fr, wl, al, d10) in fd.items():
    r = last(F, arm)
    chk(f"§1 F {arm} D main6", d6, r["main6"]["D"], 3)
    for i, s in enumerate(seeds):
        chk(f"§1 F {arm} D main6 seed{i + 1}", s, r["main6"]["D_per_seed"][i], 3)
    chk(f"§1 F {arm} free main6", fr, r["main6"]["free"], 4)
    chk(f"§1 F {arm} wall main6", wl, r["main6"]["wall_pillar"], 3)
    chk(f"§1 F {arm} all main6", al, r["main6"]["all"], 4)
    chk(f"§1 F {arm} D extrap10", d10, r["extrap10"]["D"], 3)
chk("§1 l.90 geo contact share round 1", "0.267", F["geo"][1]["disk_contact_share"], 3)
for i, s in enumerate(("+0.073", "+0.067", "+0.074")):
    chk(f"§1 l.91 F E-R same-seed seed{i + 1}", s, last(F, "disagree")["main6"]["D_per_seed"][i] - last(F, "random")["main6"]["D_per_seed"][i], 3)
chk("§0 l.24 / §7 l.196 geo-disagree (F, main6) +0.062", "+0.062", last(F, "geo")["main6"]["D"] - last(F, "disagree")["main6"]["D"], 3)
chk("§4 GX 'F' E-R extrap10 +0.065", "+0.065", last(F, "disagree")["extrap10"]["D"] - last(F, "random")["extrap10"]["D"], 3)

# derived quantities the design does not print but that matter for the review
extra = []
for run, cur in list(RUNS.items()) + [("F-main6", None)]:
    if cur is None:
        e, r = last(F, "disagree")["main6"], last(F, "random")["main6"]
        extra.append((run, "free E/R", e["free"] / r["free"]))
        g = last(F, "geo")["main6"]
        extra.append((run, "free G/R", g["free"] / r["free"]))
        extra.append((run, "wall G/R", g["wall_pillar"] / r["wall_pillar"]))
        continue
    e, r, t = last(cur, "disagree"), last(cur, "random"), last(cur, "truthcur")
    extra.append((run, "free E/R", e["free"] / r["free"]))
    extra.append((run, "T-R dD", t["D"] - r["D"]))
    extra.append((run, "wall T/R", t["wall_pillar"] / r["wall_pillar"]))
    extra.append((run, "free T/R", t["free"] / r["free"]))

n_ok = sum(1 for x in rows if x[-1] == "OK")
print(f"{'label':58} | design | recomputed (full) | shown | match")
for label, design, value, shown, ok in rows:
    print(f"{label:58} | {design:>7} | {value: .6f} | {shown:>7} | {ok}")
print(f"\n{n_ok}/{len(rows)} OK, {len(rows) - n_ok} mismatch")
print("\nderived (not printed in the design):")
for run, k, v in extra:
    print(f"  {run:8} {k:10} {v:.4f}")
