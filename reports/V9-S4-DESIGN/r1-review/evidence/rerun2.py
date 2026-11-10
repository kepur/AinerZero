"""在隔离副本里复跑 explore2.run（欧氏关联、40 世界）与默认的马氏版本，记录命名空间。复核者自写。
用法：rerun2.py <explore2 目录> <assoc> <世界数> <输出>"""
import collections, json, math, sys
sys.path.insert(0, sys.argv[1])
import explore2 as X
X.ASSOC = sys.argv[2]
seen = collections.Counter(); orig = X.seed_of
def audit(*k):
    seen[X.NS] += 1; return orig(*k)
X.seed_of = audit
n = int(sys.argv[3])
grid = [dict(n_disks=6, n_pillars=3, T=300, fov=math.radians(180), rng_=7.0), dict(n_disks=10, n_pillars=3, T=300, fov=math.radians(180), rng_=7.0)]
res = [X.run(c, n) for c in grid]
json.dump(res, open(sys.argv[4], "w"), ensure_ascii=False, indent=1)
print("NAMESPACES", dict(seen), "MLX", "mlx" in sys.modules, flush=True)
