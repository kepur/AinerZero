"""复现不是由提交脚本 __main__ 直接生成的两份结果：q 敏感性（explore2.run）与第一轮（explore.run）。"""
import json, sys
COPY, LIVE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, COPY + "/reports/V9-S3-PHASE3-DESIGN/tier1-explore")
import explore as X, explore2 as X2
assert X.NS == "s3p3x-explore"
out = {}
committed = json.load(open(LIVE + "/results2-q-sensitivity.json"))
mine = [X2.run(r["cfg"], 100) for r in committed]
out["q_sensitivity_equal"] = [m == c for m, c in zip(json.loads(json.dumps(mine)), committed)]
r1 = json.load(open(LIVE + "/results-round1.json"))
r1 = r1 if isinstance(r1, list) else [r1]
mine1 = [X.run(r["cfg"], r["n_worlds"]) for r in r1]
m1 = json.loads(json.dumps(mine1))
out["round1_equal"] = [m == c for m, c in zip(m1, r1)]
out["round1_diff_keys"] = [[k for k in set(m) | set(c) if m.get(k) != c.get(k)] for m, c in zip(m1, r1)]
if not all(out["round1_equal"]):
    out["round1_acc_diff"] = {k: (m1[0]["acc"].get(k), r1[0]["acc"].get(k)) for k in set(m1[0]["acc"]) | set(r1[0]["acc"]) if m1[0]["acc"].get(k) != r1[0]["acc"].get(k)}
json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "round1_acc_diff"}), flush=True)
