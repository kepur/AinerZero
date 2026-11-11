"""Compare the re-run of explore_p2f (first 3 main worlds) with tier1-explore/results-p2f.json cell by cell.
Usage: python -I compare_first3.py ORIGINAL.json RERUN.json"""
import json, sys
orig = json.load(open(sys.argv[1])); new = json.load(open(sys.argv[2]))
O = {(w["kind"], w["world"]): w for w in orig["per_world"]}
n_cells = n_same = 0
diff_fields = {}
for w in new["per_world"]:
    o = O[(w["kind"], w["world"])]
    print(f"world {w['kind']} {w['world']}: events identical: {o['events'] == w['events']}  n_events {len(w['events'])}  cells orig {len(o['cells'])} rerun {len(w['cells'])}")
    assert sorted(o["cells"]) == sorted(w["cells"])
    for k in sorted(w["cells"]):
        a, b = o["cells"][k], w["cells"][k]
        n_cells += 1
        same_c = a["correct"] == b["correct"]
        n_same += same_c
        for f in ("correct", "n_tracks", "reappear", "one_step"):
            if a.get(f) != b.get(f):
                diff_fields.setdefault(f, []).append(f"{w['world']}:{k}")
        print(f"  {k:16} correct identical: {same_c}  ({sum(a['correct'])}/{len(a['correct'])} vs {sum(b['correct'])}/{len(b['correct'])})  all fields identical: {a == b}")
print(f"cells compared {n_cells}; correct identical in {n_same}")
print("fields differing:", {k: len(v) for k, v in diff_fields.items()} or "none")
