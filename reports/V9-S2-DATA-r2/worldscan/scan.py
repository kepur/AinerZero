import sys, time, random, json, inspect
from ainerzero.v9.experiments.s2 import data, world, spec
part = sys.argv[1]; n = int(sys.argv[2])
ns = spec.SEED_NAMESPACES[part]
# mirror data.generate_partition's call
src = inspect.getsource(data.generate_partition)
fails = []; t = time.time()
for w_idx in range(n):
    w_seed = data._get_derived_seed(ns, part, "world", w_idx)
    prep_rng = random.Random(data._get_derived_seed(ns, part, "prep", w_idx))
    try:
        world.prepare_world_with_long_pairs(w_seed, prep_rng, n_long_pairs=3, enforce_rejection_redraw=True)
    except Exception as e:
        fails.append((w_idx, str(e)[:120]))
print(part, "worlds", n, "failed", len(fails), "secs", round(time.time()-t,1))
for f in fails[:8]: print("  ", f)
