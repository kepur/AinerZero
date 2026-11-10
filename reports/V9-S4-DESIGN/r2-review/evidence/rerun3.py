"""复跑 explore3.run 的 6 组（含精确真值两组），与 results3-dynamics.json 比对；记录命名空间。复核者自写。
用法：rerun3.py <副本根> <输出>"""
import collections, json, sys
sys.path.insert(0, sys.argv[1] + "/reports/V9-S4-DESIGN/tier1-explore")
import explore3 as X
seen = collections.Counter(); orig = X.W.derive_seed
def audit(ns, *k):
    seen[ns] += 1; return orig(ns, *k)
X.W.derive_seed = audit
committed = json.load(open(sys.argv[1] + "/reports/V9-S4-DESIGN/tier1-explore/results3-dynamics.json"))
mine = [X.run(r["n_worlds"], r["n_disks"], tuple(r["noise"])) for r in committed]
same = [json.loads(json.dumps(m)) == c for m, c in zip(mine, committed)]
json.dump({"identical": same, "namespaces": dict(seen), "mlx": "mlx" in sys.modules, "mine": mine}, open(sys.argv[2], "w"), indent=1)
print("identical per entry:", same, "namespaces:", dict(seen), "MLX", "mlx" in sys.modules)
