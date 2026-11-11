"""Independent recomputation of descriptive statistics for S4 Phase 2 final.

Recomputes directly from artifacts/v9/s4/phase2/final-final/worlds.jsonl:
1. Three event category accuracies (acc_collision, acc_non_collision, acc_all) across arms.
2. Gate share (fraction of open disk steps) across all gated arms.
3. Learned minus scatter difference across collision, non-collision, and all events.
4. Multistep k-step position error summary at steps 1, 5, 10, 30 for E-B and L-int-g.

Compares all values against reports/V9-S4-PHASE2/final.json["descriptive"].
"""
import json
import numpy as np
from pathlib import Path

WORLDS_PATH = Path("artifacts/v9/s4/phase2/final-final/worlds.jsonl")
FINAL_PATH = Path("reports/V9-S4-PHASE2/final.json")

def main():
    print("=== Item 6: Descriptive Statistics Independent Recomputation ===")
    with open(WORLDS_PATH) as f:
        worlds = [json.loads(line) for line in f]
    with open(FINAL_PATH) as f:
        final_data = json.load(f)

    desc = final_data["descriptive"]
    main_records = [w for w in worlds if w.get("kind") == "main"]
    extrap_records = [w for w in worlds if w.get("kind") == "extrap"]

    all_matched = True
    tolerance = 1e-9

    print(f"\n1. Recomputing Accuracies for Main Worlds (200 worlds):")
    arms = ["E-B", "E-P", "L-int", "L-int-g", "L-int-g3", "L-int-g7", "L-int-geo", "L-sc-g", "L-int-rand", "L-ind-geo"]
    for arm in arms:
        rec_desc = desc["main"][arm]
        for cat in ["collision", "non_collision", "all"]:
            hits = 0.0
            opps = 0.0
            for r in main_records:
                events = r.get("events", [])
                if cat == "collision":
                    mask = [e[3] == 1 for e in events]
                elif cat == "non_collision":
                    mask = [e[3] == 0 for e in events]
                else:
                    mask = [True for _ in events]

                # Check if arm has seeds or single entry
                seeds = (1, 2, 3)
                seed_keys = [f"{arm}#{s}" for s in seeds if f"{arm}#{s}" in r["cells"]]
                if seed_keys:
                    seed_hits = [sum(c for c, m in zip(r["cells"][k]["correct"], mask) if m) for k in seed_keys]
                    hits += float(np.mean(seed_hits))
                elif arm in r["cells"]:
                    hits += float(sum(c for c, m in zip(r["cells"][arm]["correct"], mask) if m))
                opps += sum(mask)

            acc = hits / opps if opps else 0.0
            key = f"acc_{cat}"
            expected = rec_desc[key]
            diff = abs(acc - expected)
            ok = diff < tolerance
            if not ok:
                all_matched = False
            print(f"  {arm:12s} {key:18s}: recomputed={acc:.10f}, recorded={expected:.10f}, diff={diff:.2e} -> {'OK' if ok else 'FAIL'}")

    print(f"\n2. Recomputing Gate Open Share (gate_share):")
    gated_arms = ["L-int-g", "L-int-g3", "L-int-g7", "L-int-geo", "L-sc-g", "L-int-rand", "L-ind-geo"]
    for arm in gated_arms:
        rec_desc = desc["main"][arm]
        o = 0
        t = 0
        for r in main_records:
            for s in (1, 2, 3):
                key = f"{arm}#{s}"
                if key in r["cells"]:
                    g = r["cells"][key].get("gate", [0, 0])
                    o += g[0]
                    t += g[1]
        share = o / t if t else None
        expected = rec_desc.get("gate_share")
        diff = abs(share - expected) if (share is not None and expected is not None) else 0.0
        ok = diff < tolerance
        if not ok:
            all_matched = False
        print(f"  {arm:12s} gate_share: recomputed={share:.10f} ({o}/{t}), recorded={expected:.10f}, diff={diff:.2e} -> {'OK' if ok else 'FAIL'}")

    print(f"\n3. Recomputing Learned Minus Scatter Difference:")
    for cat in ["collision", "non_collision", "all"]:
        diff_sum = 0.0
        opps = 0.0
        for r in main_records:
            events = r.get("events", [])
            if cat == "collision":
                mask = [e[3] == 1 for e in events]
            elif cat == "non_collision":
                mask = [e[3] == 0 for e in events]
            else:
                mask = [True for _ in events]

            hits_g = np.mean([sum(c for c, m in zip(r["cells"][f"L-int-g#{s}"]["correct"], mask) if m) for s in (1, 2, 3)])
            hits_sc = np.mean([sum(c for c, m in zip(r["cells"][f"L-sc-g#{s}"]["correct"], mask) if m) for s in (1, 2, 3)])
            diff_sum += (hits_g - hits_sc)
            opps += sum(mask)

        diff_val = diff_sum / opps if opps else 0.0
        expected = desc["learned_minus_scatter"]["main"][cat]["value"]
        diff = abs(diff_val - expected)
        ok = diff < tolerance
        if not ok:
            all_matched = False
        print(f"  L-int-g vs L-sc-g ({cat:14s}): recomputed={diff_val:.10f}, recorded={expected:.10f}, diff={diff:.2e} -> {'OK' if ok else 'FAIL'}")

    print(f"\n4. K-step Position Error Summary:")
    ks = {}
    for r in main_records:
        for name, sums in r.get("kstep", {}).items():
            arm = name.split("#")[0]
            for k, (s_val, n_val) in sums.items():
                acc = ks.setdefault(arm, {}).setdefault(k, [0.0, 0])
                acc[0] += s_val
                acc[1] += n_val
    recomputed_kstep = {a: {k: v[0] / v[1] for k, v in d.items() if v[1]} for a, d in ks.items()}

    for arm in ["E-B", "L-int-g"]:
        for step in ["1", "5", "10", "30"]:
            expected = desc["kstep_position_error"][arm][step]
            recomputed = recomputed_kstep[arm][step]
            diff = abs(recomputed - expected)
            ok = diff < tolerance
            if not ok:
                all_matched = False
            print(f"  {arm:10s} step {step:2s}: recomputed={recomputed:.10f}, recorded={expected:.10f}, diff={diff:.2e} -> {'OK' if ok else 'FAIL'}")

    print(f"\n>>> CONCLUSION: ITEM 6 RECOMPUTATION {'ALL MATCHED' if all_matched else 'FAILED'}.")

if __name__ == "__main__":
    main()
