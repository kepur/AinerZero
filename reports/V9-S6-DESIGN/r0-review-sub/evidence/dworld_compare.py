#!/usr/bin/env python3
"""S6 r0 review, item 2 robustness: mindist on round D's world (proxy-s6x2.json, C-style combined test)
against round D's own arms (tier1-explore/results-s6d.json), point values at 12000 labels (no per-world
random arm for this world, so no interval)."""
import json
E = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN"
Z = json.load(open(f"{E}/r0-review-sub/evidence/proxy-s6x2.json"))["arms"]["mindist"]["rounds"]
D = json.load(open(f"{E}/tier1-explore/results-s6d.json"))["curves"]
z = Z[-1]["C_all30"]
r, e, t = D["random"][-1], D["disagree"][-1], D["truthcur"][-1]
print("round-0 check vs results-s6d random r0:", {k: (Z[0]["C_all30"][k] == D["random"][0][k]) for k in ("D", "collision", "wall_pillar", "free", "all")})
print(f"D: mindist {z['D']:.4f}  random {r['D']:.4f}  disagree {e['D']:.4f}  truthcur {t['D']:.4f}")
print(f"mindist - random dD {z['D'] - r['D']:+.4f}   disagree - random {e['D'] - r['D']:+.4f}   disagree - mindist {e['D'] - z['D']:+.4f}")
for k in ("all", "wall_pillar", "free", "graze"):
    print(f"{k:12} mindist/random {z[k] / r[k]:.4f}   disagree/random {e[k] / r[k]:.4f}   disagree/mindist {e[k] / z[k]:.4f}")
print("GS point (>= +0.03):", z["D"] - r["D"] >= 0.03, " GK all point (<= 1.10):", z["all"] / r["all"] <= 1.10, " GK wall point (<= 1.0):", z["wall_pillar"] / r["wall_pillar"] <= 1.0)
print(f"main6 D mindist {Z[-1]['main6']['D']:.4f} per network {[round(x, 4) for x in Z[-1]['main6']['D_per_seed']]}; extrap10 D {Z[-1]['extrap10']['D']:.4f}")
