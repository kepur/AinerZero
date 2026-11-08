import sys, time, random, json
from ainerzero.v9.experiments.s2 import data, world, spec
part = sys.argv[1]; start = int(sys.argv[2]); n = int(sys.argv[3]); n_pairs = int(sys.argv[4]); RMAX = 40
ns = spec.SEED_NAMESPACES[part]
need = []; t = time.time()
for w_idx in range(start, start + n):
    seed = data._get_derived_seed(ns, part, "world", w_idx)
    rng = random.Random(data._get_derived_seed(ns, part, "prep", w_idx))
    got = None
    for attempt in range(RMAX):
        layout = world.make_layout(seed + attempt * 10007)
        rej = att = 0; ok = True
        for _ in range(n_pairs):
            try:
                s, g, go, st = world.sample_start_goal_pair(layout, rng, kind="long")
            except RuntimeError:
                ok = False; break
            rej += int(st["rejections"]); att += int(st["attempts"])
        if not ok: continue
        if (rej / att if att else 0.0) > world.WORLD_REJECTION_RATE_THRESHOLD: continue
        got = attempt + 1; break
    need.append(got)
json.dump({"part": part, "start": start, "n": n, "n_pairs": n_pairs, "need": need, "secs": time.time() - t}, sys.stdout)
