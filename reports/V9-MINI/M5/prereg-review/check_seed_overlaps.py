import sys
from pathlib import Path

# Confirmation ranges for M5:
# s in 0..4:
# eval: [8_100_000 + 1000*s, 8_100_000 + 1000*s + 80)
m5_eval_ranges = {f"m5_eval_s{s}": (8_100_000 + 1000*s, 8_100_000 + 1000*s + 80) for s in range(5)}

# Used ranges:
used_ranges = {
    "explore_7900k": (7_900_000, 7_900_000 + 30),
    "explore_7950k": (7_950_000, 7_950_000 + 80),
    "explore_7960k_scale": (7_960_000, 7_960_000 + 80),
}
for s in range(5):
    used_ranges[f"m4_eval_s{s}"] = (8_000_000 + 1000*s, 8_000_000 + 1000*s + 80)
    used_ranges[f"train_s{s}"] = (7_100_000 + 1000*s, 7_100_000 + 1000*s + 200)

print("Checking overlaps...")
all_disjoint = True
for m5_k, (m5_lo, m5_hi) in m5_eval_ranges.items():
    for u_k, (u_lo, u_hi) in used_ranges.items():
        # Check interval overlap
        overlap = max(0, min(m5_hi, u_hi) - max(m5_lo, u_lo))
        if overlap > 0:
            print(f"OVERLAP DETECTED between {m5_k} [{m5_lo}, {m5_hi}) and {u_k} [{u_lo}, {u_hi}): overlap={overlap}")
            all_disjoint = False

# Also check mutual overlap among m5 eval ranges
for s1 in range(5):
    for s2 in range(s1 + 1, 5):
        k1, (lo1, hi1) = f"m5_eval_s{s1}", m5_eval_ranges[f"m5_eval_s{s1}"]
        k2, (lo2, hi2) = f"m5_eval_s{s2}", m5_eval_ranges[f"m5_eval_s{s2}"]
        overlap = max(0, min(hi1, hi2) - max(lo1, lo2))
        if overlap > 0:
            print(f"Mutual overlap between {k1} and {k2}")
            all_disjoint = False

if all_disjoint:
    print("ALL M5 eval ranges are strictly disjoint from all past used sets and mutually disjoint!")
