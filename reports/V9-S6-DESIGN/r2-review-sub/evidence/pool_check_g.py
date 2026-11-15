#!/usr/bin/env python3
"""S6 r2 review, items 1 and 4, pure NumPy (no MLX, so no lock): rebuild round G's candidate source the way
s6/cells.candidate_source does (s6x-cand5, replicate 0: 240 worlds, 60000 (world, step) pairs drawn without
replacement with seed derive_seed(ns, 's6-pool', k), grouped by disk count, sorted by (world, step)),
re-implementing cells.pool_digest, and compare the digest with the pool_sha256 recorded in every round-G
cell.json. Then: are the states distinct, and what share of candidates has its successor state (step t+1 of
the same world = its one-step outcome) also among the candidates (DESIGN-r2 §6 says 'similar to ~81%')."""
import hashlib
import json
from pathlib import Path

import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import world as W

ns, k, nw, pool = "s6x-cand5", 0, 240, 60_000
eps = [W.generate_episode(ns, w, A.train_disks(ns, w)) for w in range(k * nw, (k + 1) * nw)]
pairs = [(e, t) for e, ep in enumerate(eps) for t in range(len(ep.steps))]
pick = np.random.default_rng(W.derive_seed(ns, "s6-pool", k)).choice(len(pairs), pool, replace=False)
chosen = sorted((eps[pairs[i][0]].n_disks, pairs[i][0], pairs[i][1]) for i in pick)
by_n = {}
for n, e, t in chosen:
    s = eps[e].steps[t]
    row = by_n.setdefault(n, {"p": [], "v": [], "pil": []})
    row["p"].append(np.asarray(s.positions, dtype=np.float64)); row["v"].append(np.asarray(s.velocities, dtype=np.float64))
    row["pil"].append(np.asarray(eps[e].pillars, dtype=np.float64))
src = {n: {kk: np.stack(v) for kk, v in d.items()} for n, d in sorted(by_n.items())}
h = hashlib.sha256()
for n in sorted(src):
    for key in sorted(src[n]):
        a = np.ascontiguousarray(src[n][key])
        h.update(f"{n}:{key}:{a.dtype}:{a.shape}".encode()); h.update(a.tobytes())
dig = h.hexdigest()
distinct = sum(len(np.unique(np.concatenate([d["p"].reshape(len(d["p"]), -1), d["v"].reshape(len(d["v"]), -1),
                                              d["pil"].reshape(len(d["pil"]), -1)], 1), axis=0)) for d in src.values())
print(f"states {sum(len(d['p']) for d in src.values())} of {len(pairs)}; distinct {distinct}; digest {dig[:16]}...")
root = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s6/explore/s6x-cand5-r0")
for arm in ("R", "E", "Z", "T", "P", "G"):
    rec = json.load(open(root / arm / "cell.json"))
    print(f"  {arm}: recorded pool_sha256 {rec['pool_sha256'][:16]}...  equal: {rec['pool_sha256'] == dig}")
cs = {(e, t) for _, e, t in chosen}
succ = np.array([(e, t + 1) in cs for _, e, t in chosen])
contact = np.array([any(kind == "disk" for kind, _, _ in eps[e].steps[t].contacts) for _, e, t in chosen])
print(f"successor state also a candidate: {succ.mean():.3f}; among candidates with a disk contact: {succ[contact].mean():.3f} "
      f"({int(succ[contact].sum())} of {int(contact.sum())}); disk-contact share {contact.mean():.4f}")
print("global ids: sorted by (disks, world, step), so id g and g+1 are consecutive steps of one world for "
      f"{np.mean([(a[1] == b[1] and b[2] == a[2] + 1) for a, b in zip(chosen, chosen[1:])]):.3f} of neighbouring id pairs")
