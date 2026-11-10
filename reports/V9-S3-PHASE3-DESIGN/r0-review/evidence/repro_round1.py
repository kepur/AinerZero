"""第一轮结果（results-round1.json）由早一版 explore.py 生成：核对共同的键逐项相同。"""
import json, sys
COPY, LIVE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, COPY + "/reports/V9-S3-PHASE3-DESIGN/tier1-explore")
import explore as X
assert X.NS == "s3p3x-explore"
c = json.load(open(LIVE + "/results-round1.json")); c = c if isinstance(c, list) else [c]
m = json.loads(json.dumps(X.run(c[0]["cfg"], c[0]["n_worlds"])))
res = {"round1_common_counts_equal": all(m["counts"][k] == v for k, v in c[0]["counts"].items()),
       "round1_common_acc_equal": all(m["acc"][k] == v for k, v in c[0]["acc"].items()),
       "round1_other_keys_differ": [k for k in c[0] if k not in ("counts", "acc") and m.get(k) != c[0][k]],
       "extra_count_keys": sorted(set(m["counts"]) - set(c[0]["counts"])), "extra_acc_keys": len(set(m["acc"]) - set(c[0]["acc"]))}
json.dump(res, open(OUT, "w"), indent=1); print(res)
