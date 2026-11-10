"""在隔离副本里原样运行摸底脚本，同时记录 derive_seed 收到的全部命名空间。"""
import json, runpy, sys, collections
copy, script, log = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, copy + "/src")
import ainerzero.v9.experiments.s3.data as D
seen = collections.Counter(); orig = D.derive_seed
def wrapped(ns, *keys):
    seen[(ns, keys[0] if keys else None)] += 1
    return orig(ns, *keys)
D.derive_seed = wrapped
sys.argv = [script]
try:
    runpy.run_path(script, run_name="__main__")
finally:
    json.dump({f"{k[0]}|{k[1]}": v for k, v in sorted(seen.items())}, open(log, "w"), indent=1)
    mods = sorted(m for m in sys.modules if m.startswith("ainerzero"))
    print("NAMESPACES", sorted({k[0] for k in seen}), "MODULES", mods, flush=True)
    print("MLX loaded:", "mlx" in sys.modules, flush=True)
