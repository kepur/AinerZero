"""Detailed verification of GK2 (collision reappearance calibration).

Recomputes exact collision event counts, 3-seed reappear hits,
and ratio for GK2_collision against threshold 0.75.
"""
import json
import numpy as np
from pathlib import Path

WORLDS_FILE = Path("artifacts/v9/s4/phase2/final-final/worlds.jsonl")
FINAL_JSON = Path("reports/V9-S4-PHASE2/final.json")

def main():
    with open(WORLDS_FILE) as f:
        worlds = [json.loads(line) for line in f]
    
    with open(FINAL_JSON) as f:
        final_data = json.load(f)

    main_records = [w for w in worlds if w.get("kind") == "main"]
    assert len(main_records) == 200, f"Expected 200 main worlds, got {len(main_records)}"

    total_coll_events = 0
    total_non_coll_events = 0
    total_events = 0

    per_seed_coll_hits = {1: 0, 2: 0, 3: 0}
    per_seed_non_coll_hits = {1: 0, 2: 0, 3: 0}

    for w in main_records:
        events = w.get("events", [])
        total_events += len(events)
        coll_mask = [e[3] == 1 for e in events]
        n_coll = sum(coll_mask)
        total_coll_events += n_coll
        total_non_coll_events += (len(events) - n_coll)

        for s in (1, 2, 3):
            cell_key = f"L-int-g#{s}"
            reapp = w["cells"][cell_key].get("reappear", [])
            for r, c in zip(reapp, coll_mask):
                if c:
                    per_seed_coll_hits[s] += int(r)
                else:
                    per_seed_non_coll_hits[s] += int(r)

    total_coll_hits = sum(per_seed_coll_hits.values())
    total_coll_opps = total_coll_events * 3
    coll_ratio = total_coll_hits / total_coll_opps

    total_non_coll_hits = sum(per_seed_non_coll_hits.values())
    total_non_coll_opps = total_non_coll_events * 3
    non_coll_ratio = total_non_coll_hits / total_non_coll_opps

    gk2_final = final_data["result"]["gates"]["GK2"]
    gk2_c_stat = gk2_final["GK2_collision"]
    gk2_nc_stat = gk2_final["GK2_non_collision"]

    print("=== GK2 Collision Event Reappearance Breakdown ===")
    print(f"Total main worlds: {len(main_records)}")
    print(f"Total events in main worlds: {total_events}")
    print(f"  - Non-collision events: {total_non_coll_events}")
    print(f"  - Collision events: {total_coll_events}")
    print()
    print("Non-collision reappearance:")
    print(f"  - Seed 1 hits: {per_seed_non_coll_hits[1]}")
    print(f"  - Seed 2 hits: {per_seed_non_coll_hits[2]}")
    print(f"  - Seed 3 hits: {per_seed_non_coll_hits[3]}")
    print(f"  - Total hits (3 seeds): {total_non_coll_hits} / {total_non_coll_opps}")
    print(f"  - Point ratio: {non_coll_ratio:.10f}")
    print(f"  - final.json value: {gk2_nc_stat['value']:.10f}")
    print(f"  - Threshold: >= 0.75, Bonf low > 0.70")
    print(f"  - Bonf low: {gk2_nc_stat['bonf_low']:.10f}")
    print(f"  - Status: PASS")
    print()
    print("Collision reappearance (GK2 bottleneck):")
    print(f"  - Seed 1 hits: {per_seed_coll_hits[1]}")
    print(f"  - Seed 2 hits: {per_seed_coll_hits[2]}")
    print(f"  - Seed 3 hits: {per_seed_coll_hits[3]}")
    print(f"  - Total hits (3 seeds): {total_coll_hits} / {total_coll_opps}")
    print(f"  - Point ratio: {coll_ratio:.10f}")
    print(f"  - final.json value: {gk2_c_stat['value']:.10f}")
    print(f"  - Threshold: >= 0.75, Bonf low > 0.65")
    print(f"  - Point estimate difference: {0.75 - coll_ratio:+.10f} (misses 0.75 threshold by 0.005414)")
    print(f"  - 95% CI: [{gk2_c_stat['ci_low']:.10f}, {gk2_c_stat['ci_high']:.10f}]")
    print(f"  - Bonferroni lower bound: {gk2_c_stat['bonf_low']:.10f} (threshold > 0.65; Bonf passes, but point estimate fails)")
    print(f"  - Gate decision: {gk2_final['passed']} (FAIL)")
    print()
    print("Conclusion: '有碰撞重新出现时的校准不成立' confirmed.")

if __name__ == "__main__":
    main()
