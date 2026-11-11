"""P213: one-step coverage rows per arm (exploration results-p2f.json, or surrogate records): a row exists only
when the track was assigned at t-1 and at t, so arms that lose association contribute fewer rows.
Usage: python -I -B <this> FILE.json [main|extrap]"""
import json, sys
r = json.load(open(sys.argv[1]))
recs = r["per_world"] if "per_world" in r else r["records"]
kind = sys.argv[2] if len(sys.argv) > 2 else "main"
recs = [w for w in recs if w.get("kind", "main") == kind]
arms = sorted({k.rsplit("#", 1)[0] for k in recs[0]["cells"]})
print(f"{kind}: {len(recs)} worlds")
print(f"{'arm':14} {'rows all':>9} {'rows coll':>9} {'inside coll':>11} {'cov coll':>8} | {'coll events':>11}")
for a in arms:
    na = nc = ic = 0
    for w in recs:
        for s in (1, 2, 3):
            c = w["cells"][f"{a}#{s}"]
            o = c["one_step"]
            if "all" in o:                    # exploration format: all/collision/free [rows, inside]
                na += o["all"][0]; nc += o["collision"][0]; ic += o["collision"][1]
            else:                             # registered format: collision/other [rows, inside]
                na += o["collision"][0] + o["other"][0]; nc += o["collision"][0]; ic += o["collision"][1]
    ne = sum(e[3] for w in recs for e in w["events"])
    print(f"{a:14} {na:9d} {nc:9d} {ic:11.0f} {ic / nc:8.3f} | {ne:11d}")
