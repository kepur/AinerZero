"""复跑 explore4 的三组函数，与 results4-graze-nll.json 比对；记录命名空间。复核者自写。用法：rerun4.py <副本根> <输出>"""
import collections, json, sys
sys.path.insert(0, sys.argv[1] + "/reports/V9-S4-DESIGN/tier1-explore")
import explore4 as X
seen = collections.Counter(); orig = X.W.derive_seed
def audit(ns, *k):
    seen[ns] += 1; return orig(ns, *k)
X.W.derive_seed = audit
res = {"graze": [X.graze_and_collision(40, nd) for nd in (6, 10)], "nll": [X.nll_constant_vs_binned(40, nd) for nd in (6, 10)],
       "velocity_nll": [X.velocity_nll(40, nd) for nd in (6, 10)]}
committed = json.load(open(sys.argv[1] + "/reports/V9-S4-DESIGN/tier1-explore/results4-graze-nll.json"))
same = {k: [json.loads(json.dumps(a)) == b for a, b in zip(res[k], committed[k])] for k in res}
json.dump({"identical": same, "namespaces": dict(seen), "mlx": "mlx" in sys.modules}, open(sys.argv[2], "w"), indent=1)
print("identical:", same, "namespaces:", dict(seen), "MLX", "mlx" in sys.modules)
