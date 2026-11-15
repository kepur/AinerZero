#!/usr/bin/env python3
"""Point-gate check of the surrogate arms against the archived s6c random arm.

Same label count only. This is not the design's world bootstrap: results JSON
has no per-world sums, and each surrogate arm is one draw of three seeds.
"""
import json
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN")
s6c = json.loads((ROOT / "tier1-explore/results-s6c.json").read_text())
repro = json.loads((ROOT / "r0-review/evidence/repro-s6c-r0.json").read_text())
sur = json.loads((ROOT / "r0-review/evidence/surrogate-results.json").read_text())

keys = ("D", "collision", "graze", "wall_pillar", "free", "all", "n_labels", "disk_contact_share")
a = s6c["curves"]["random"][0]
b = repro["curves"]["random"][0]
print("repro round0 vs results-s6c random round0")
for k in keys:
    print(f"  {k} equal={a[k] == b[k]} s6c={a[k]!r} repro={b[k]!r}")

print("\nsame-budget point comparison (surrogate mixed minus s6c arm at the same n_labels)")
for arm in ("vmax", "mindist"):
    print(f"\n# {arm}")
    for i, row in enumerate(sur["curves"][arm]):
        base = s6c["curves"]["random"][i]
        dis = s6c["curves"]["disagree"][i]
        tru = s6c["curves"]["truthcur"][i]
        m = row["mixed"]
        dD = m["D"] - base["D"]
        wr = m["wall_pillar"] / base["wall_pillar"]
        ar = m["all"] / base["all"]
        print(
            f"  n={row['n_labels']:5d} contact={row['disk_contact_share']:.4f} "
            f"D={m['D']:.6f} dD_vs_random={dD:+.6f} dD_vs_disagree={m['D'] - dis['D']:+.6f} "
            f"dD_vs_truthcur={m['D'] - tru['D']:+.6f} wall_ratio={wr:.6f} all_ratio={ar:.6f} "
            f"free_delta={m['free'] - base['free']:+.6f} main6D={row['main6']['D']:.6f} "
            f"extrapD={row['extrap10']['D']:.6f}"
        )

print("\n12000-label point gates (GS: dD>=0.03; GK all<=1.10; GK wall<=1.0)")
for arm in ("vmax", "mindist"):
    row = sur["curves"][arm][-1]
    base = s6c["curves"]["random"][-1]
    m = row["mixed"]
    dD = m["D"] - base["D"]
    wr = m["wall_pillar"] / base["wall_pillar"]
    ar = m["all"] / base["all"]
    gs = dD >= 0.03
    gk_all = ar <= 1.10
    gk_wall = wr <= 1.0
    print(
        f"  {arm}: GS_point={gs} GK_all={gk_all} GK_wall={gk_wall} "
        f"GS_and_GK={gs and gk_all and gk_wall} dD={dD:+.6f} all_ratio={ar:.6f} wall_ratio={wr:.6f}"
    )
print("bounds and the three-repeat sign check were not computed (no per-world sums; one draw)")
