"""P215: recompute round G's gate statistics, decisions and descriptive table from the stored records
(tier1-explore/results-p2g.json) with the registered analysis_p2.gate_stats / decide / summarize_descriptive,
print them exactly as explore_p2g.py does, and check the recomputed statistics against those stored in the JSON.
Pure CPU. Usage (repository root): python -I -B <this> results-p2g.json > OUT.txt"""
import json
import sys

from ainerzero.v9.experiments.s4 import analysis_p2 as P2

r = json.load(open(sys.argv[1]))
recs = r["records"]
main_r = [x for x in recs if x["kind"] == "main"]
ext_r = [x for x in recs if x["kind"] == "extrap"]
st = P2.gate_stats(main_r, ext_r)
passed, neg = P2.decide(st)
desc = P2.summarize_descriptive(main_r, ext_r, P2.HAND + P2.LEARNED)
# --- the print block of explore_p2g.py (lines 40-51), verbatim ---
f = lambda d: "—" if d is None or d.get("value") is None else f"{d['value']:+.3f} [{d['bonf_low']:+.3f}, {d['bonf_high']:+.3f}]"
for k, v in st.items():
    print(f"{k:18} {f(v)}")
print("passed", passed, "negative control", neg)
for part in ("main", "extrap"):
    print(f"\n{part}: arm  coll  non  all | 1-step all/coll | reappear non/coll | C | gate share")
    for a, row in desc[part].items():
        c = row.get("C", {}).get("value") if isinstance(row.get("C"), dict) else None
        print(f"{a:11} {row['acc_collision']:.3f} {row['acc_non_collision']:.3f} {row['acc_all']:.3f} | {row['one_step_all']:.3f}/{row['one_step_collision']:.3f}"
              f" | {row['reappear_non_collision']:.3f}/{row['reappear_collision']:.3f} | {'' if c is None else f'{c:.3f}'} | {row.get('gate_share') or ''}")
    print("L-int-g − L-sc-g:", {w: f(v) for w, v in desc["learned_minus_scatter"][part].items()})
print("\ndynamics", json.dumps({p: {a: {k: round(x, 4) for k, x in v.items() if x is not None} for a, v in d.items()} for p, d in desc["dynamics"].items()}))
# --- checks against the stored JSON (to stderr, so stdout stays diffable) ---
same_st = json.dumps(st, sort_keys=True) == json.dumps(r["stats"], sort_keys=True)
print(f"records: main {len(main_r)} extrap {len(ext_r)}; stored stats identical to recomputed: {same_st}; "
      f"stored passed identical: {r['passed'] == passed}; stored negative control identical: {r['negative_control'] == neg}", file=sys.stderr)
