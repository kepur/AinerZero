#!/usr/bin/env python3
"""Recompute DESIGN-r0.md §1 numbers from the exploration and P251 JSON files.

Reads only. Prints raw values, rounded values, and the design's printed figures.
"""
import json
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN")
FILES = {
    "C": ROOT / "tier1-explore/results-s6c.json",
    "D": ROOT / "tier1-explore/results-s6d.json",
    "F": ROOT / "tier1-explore/results-s6f.json",
    "r3": ROOT / "replication/results-s6r3.json",
    "r4": ROOT / "replication/results-s6r4.json",
    "E2": ROOT / "tier1-explore/results-s6e2.json",
}


def load(key):
    return json.loads(FILES[key].read_text())


def r3(x):
    return round(float(x) + 0.0, 3)


def r4(x):
    return round(float(x) + 0.0, 4)


def last(curve):
    return curve[-1]


def main():
    c, d, r3j, r4j, f = load("C"), load("D"), load("r3"), load("r4"), load("F")
    print("n_labels check", {k: last(load(k)["curves"]["disagree"])["n_labels"] for k in ("C", "D", "r3", "r4")})
    print("F n_labels", last(f["curves"]["disagree"])["n_labels"], "geo_flagged_share", f["geo_flagged_share"])

    print("\n== C/D/r3/r4 final round (index -1) ==")
    header = f"{'run':4} {'arm':10} {'D':10} {'free':10} {'all':10} {'wall':10} {'coll':10} {'contact':10}"
    print(header)
    for name, doc, arms in (
        ("C", c, ("random", "disagree", "oracle", "truthcur")),
        ("D", d, ("random", "disagree", "truthcur")),
        ("r3", r3j, ("random", "disagree", "truthcur")),
        ("r4", r4j, ("random", "disagree", "truthcur")),
    ):
        for arm in arms:
            row = last(doc["curves"][arm])
            print(f"{name:4} {arm:10} {row['D']:.6f} {row['free']:.6f} {row['all']:.6f} {row['wall_pillar']:.6f} {row['collision']:.6f} {row['disk_contact_share']:.6f}")

    print("\n== summary deltas at 12000 labels ==")
    print(f"{'run':4} {'dD_vs_R':10} {'dfree':10} {'all_ratio':10} {'wall_ratio':10} {'dD_vs_T':10} {'dWall':10}")
    for name, doc in (("C", c), ("D", d), ("r3", r3j), ("r4", r4j)):
        e, r, t = last(doc["curves"]["disagree"]), last(doc["curves"]["random"]), last(doc["curves"]["truthcur"])
        dD = e["D"] - r["D"]
        dfree = e["free"] - r["free"]
        ar = e["all"] / r["all"]
        wr = e["wall_pillar"] / r["wall_pillar"]
        dT = e["D"] - t["D"]
        dW = e["wall_pillar"] - r["wall_pillar"]
        print(f"{name:4} {dD:.6f} {dfree:.6f} {ar:.6f} {wr:.6f} {dT:.6f} {dW:.6f}")
        print(f"     rounded3/4  dD={r3(dD):+.3f} dfree={r4(dfree):+.4f} all={r3(ar):.2f}? {ar:.4f} wall={wr:.4f} dT={r3(dT):+.3f}")
        print(f"     from already-rounded prints: dD={r3(e['D'])-r3(r['D']):+.3f} dfree={r4(e['free'])-r4(r['free']):+.4f} dT={r3(e['D'])-r3(t['D']):+.3f}")

    print("\n== contact share by round, disagree ==")
    for name, doc in (("C", c), ("D", d), ("r3", r3j), ("r4", r4j)):
        shares = [round(row["disk_contact_share"], 4) for row in doc["curves"]["disagree"]]
        print(name, shares)

    print("\n== F final ==")
    for arm in ("random", "disagree", "geo"):
        row = last(f["curves"][arm])
        m, x = row["main6"], row["extrap10"]
        print(arm, "contact", f"{row['disk_contact_share']:.6f}")
        print("  main6", {k: m[k] for k in ("D", "free", "wall_pillar", "all", "collision")})
        print("  D_per_seed", m["D_per_seed"])
        print("  extrap10 D", x["D"], "all", x["all"])
    rd, dd, gd = (last(f["curves"][a])["main6"] for a in ("random", "disagree", "geo"))
    print("paired dD", [dd["D_per_seed"][i] - rd["D_per_seed"][i] for i in range(3)])
    print("geo - disagree main6 D", gd["D"] - dd["D"])
    print("disagree - random main6 D", dd["D"] - rd["D"])
    print("disagree - random extrap D", last(f["curves"]["disagree"])["extrap10"]["D"] - last(f["curves"]["random"])["extrap10"]["D"])
    print("wall ratios F", dd["wall_pillar"] / rd["wall_pillar"], gd["wall_pillar"] / rd["wall_pillar"])
    print("free deltas F disagree, geo", dd["free"] - rd["free"], gd["free"] - rd["free"])
    print("all ratios F disagree, geo", dd["all"] / rd["all"], gd["all"] / rd["all"])

    e2p = FILES["E2"]
    if e2p.exists():
        e2 = json.loads(e2p.read_text())
        print("\n== E2 type", type(e2.get("curves")).__name__, "keys", list(e2.keys()))
        curves = e2["curves"]
        # E2 stores one arm as a list of round dicts.
        if isinstance(curves, list):
            row0, row1, rowL = curves[0], curves[1], curves[-1]
            print("E2 round0 D", row0["D"], "round1 contact", row1["disk_contact_share"])
            print("E2 final", {k: rowL[k] for k in ("D", "free", "all", "wall_pillar", "collision", "n_labels", "disk_contact_share")})
            print("E2 minus C random D", rowL["D"] - c["curves"]["random"][-1]["D"])


if __name__ == "__main__":
    main()
