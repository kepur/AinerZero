"""在隔离副本里重跑摸底脚本的 run()，记录 seed_of 收到的全部命名空间。复核者自写。
用法：rerun.py <explore.py 所在目录> <fov 度> <半径> <世界数> <输出 json> [命名空间]
"""
import collections, json, math, sys
sys.path.insert(0, sys.argv[1])
import explore as X
X.FOV, X.RANGE = math.radians(float(sys.argv[2])), float(sys.argv[3])
if len(sys.argv) > 6:
    assert sys.argv[6] in ("s4x-explore", "s4x-rv1110"); X.NS = sys.argv[6]
seen = collections.Counter(); orig = X.seed_of
def audit(*keys):
    seen[X.NS] += 1
    return orig(*keys)
X.seed_of = audit
n = int(sys.argv[4])
res = [X.run(dict(n_disks=6, n_pillars=3, T=300), n), X.run(dict(n_disks=10, n_pillars=3, T=300), n)]
json.dump(res, open(sys.argv[5], "w"), ensure_ascii=False, indent=1)
print("NAMESPACES", dict(seen), "MLX", "mlx" in sys.modules, flush=True)
