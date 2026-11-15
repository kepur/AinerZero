#!/usr/bin/env python3
"""P256 review, item 1b: is sandbox.sim_labels the same algorithm as learned_mlx.make_pool?

learned_mlx imports MLX, which this review must not run. So the verbatim source text of ``Pool``,
``perturb`` and ``make_pool`` (and the module constants they use) is cut out of learned_mlx.py with
``ast`` and executed with NumPy only. make_pool is driven (as test_s6_sandbox_native.py does) to draw
exactly chosen (episode, step) pairs, exact states, and its labels are compared bit for bit with
sim_labels and with CandidatePool.reveal on the same states. make_pool rolls steps 2-10 batched over all
samples of one (disk count, episode) group; sim_labels rolls each sample alone, so this also checks that
the simulator is batch-invariant on these states. Review namespace s6r-review-pure, in memory only."""
from __future__ import annotations

import ast
import sys
import types
import typing
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import sandbox as S

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src/ainerzero/v9/experiments/s4/learned_mlx.py"
text = SRC.read_text(encoding="utf-8")
tree = ast.parse(text)
CONSTS = {"ARENA", "RADIUS", "N_PILLARS", "ROLLOUT", "EXACT_FRAC", "P_HIDDEN", "VISIBLE_SIGMA", "HIDDEN_SIGMA",
          "P_DROP", "GHOSTS", "GHOST_SIGMA"}
body = [n for n in tree.body if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id in CONSTS]
body += [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in ("Pool", "perturb", "make_pool")]
print("extracted from", SRC.relative_to(ROOT), ":", [getattr(n, "name", None) or n.targets[0].id for n in body])
mod = types.ModuleType("learned_mlx_extract")       # a real module object: dataclass looks itself up in sys.modules
sys.modules[mod.__name__] = mod
ns = mod.__dict__
ns.update({"np": np, "dataclass": dataclass, "Sequence": typing.Sequence})
exec(compile(ast.Module(body=body, type_ignores=[]), str(SRC), "exec"), ns)
print("mlx imported:", any(m.startswith("mlx") for m in sys.modules))
print("ROLLOUT", ns["ROLLOUT"], "== sandbox.ROLLOUT", S.ROLLOUT, ns["ROLLOUT"] == S.ROLLOUT)
make_pool = ns["make_pool"]


class ScriptedDraws:
    """make_pool per draw: integers(len(episodes)), integers(len(steps)), random() < exact_frac."""

    def __init__(self, pairs):
        self.seq = [x for e, t in pairs for x in (("i", e), ("i", t), ("r", 0.0))]
        self.pos = 0

    def _next(self, kind):
        k, v = self.seq[self.pos]
        assert k == kind
        self.pos += 1
        return v

    def integers(self, n):
        v = self._next("i")
        assert 0 <= v < n
        return v

    def random(self):
        return self._next("r")


disks = [4, 5, 6, 7, 8, 10, 6, 8, 4, 7]
eps = [W.generate_episode("s6r-review-pure", w, n) for w, n in enumerate(disks)]
rng = np.random.default_rng(20261115)
pairs = []
for e, ep in enumerate(eps):
    contact_steps = [t for t, s in enumerate(ep.steps) if any(k == "disk" for k, _, _ in s.contacts)]
    other = rng.choice(len(ep.steps), 120, replace=False).tolist()
    pairs += [(e, t) for t in sorted(set(contact_steps) | set(other))]
rng.shuffle(pairs)
pairs = [tuple(map(int, p)) for p in pairs]
print("states:", len(pairs), "from", len(eps), "worlds; disk counts", sorted(set(disks)))

pool = make_pool(eps, len(pairs), ScriptedDraws(pairs), W.physics, exact_frac=1.0)
order = sorted(range(len(pairs)), key=lambda i: (eps[pairs[i][0]].n_disks, pairs[i][0], i))
by_n_pairs: dict[int, list] = {}
for i in order:
    by_n_pairs.setdefault(eps[pairs[i][0]].n_disks, []).append(pairs[i])

src = {}
for n, prs in by_n_pairs.items():
    src[n] = {"p": np.stack([np.asarray(eps[e].steps[t].positions, np.float64) for e, t in prs]),
              "v": np.stack([np.asarray(eps[e].steps[t].velocities, np.float64) for e, t in prs]),
              "pil": np.stack([np.asarray(eps[e].pillars, np.float64) for e, t in prs])}

cp = S.CandidatePool(src)
rev = cp.reveal(np.arange(len(cp), dtype=np.int64))
mism, contacts, groups = [], 0, {}
for n in sorted(src):
    lab = S.sim_labels(src[n]["p"], src[n]["v"], src[n]["pil"])
    groups[n] = len({e for e, _ in by_n_pairs[n]})
    for k in S.STATE_KEYS + S.LABEL_KEYS:
        mp = pool.by_n[n][k]
        if k in S.LABEL_KEYS:
            if mp.dtype != lab[k].dtype or not np.array_equal(mp, lab[k]):
                mism.append(("sim_labels", n, k, mp.dtype, lab[k].dtype))
        if rev.by_n[n][k].dtype != mp.dtype or not np.array_equal(rev.by_n[n][k], mp):
            mism.append(("reveal", n, k, mp.dtype, rev.by_n[n][k].dtype))
    contacts += int(pool.by_n[n]["contact"].any((1, 2)).sum())
print("samples per disk count:", {n: len(v) for n, v in by_n_pairs.items()}, "| (disk count, world) groups per n:", groups)
print("samples with a disk contact at step 1 (make_pool labels):", contacts)
print("fields compared:", list(S.STATE_KEYS + S.LABEL_KEYS))
print("dtypes make_pool:", {k: str(v.dtype) for k, v in pool.by_n[6].items()})
print("dtypes reveal   :", {k: str(v.dtype) for k, v in rev.by_n[6].items()})
print("bit-for-bit mismatches (make_pool vs sim_labels, make_pool vs CandidatePool.reveal):", mism if mism else "none")

# batch invariance directly: steps 2-10 for one whole group at once vs one sample at a time, float64
e0 = [i for i, (e, t) in enumerate(by_n_pairs[8]) if e == by_n_pairs[8][0][0]]
P, V = src[8]["p"][e0], src[8]["v"][e0]
pil = tuple(map(tuple, src[8]["pil"][e0[0]]))
pb, vb = P.copy(), V.copy()
for _ in range(10):
    pb, vb, _ = W.physics(pb, vb, pil)
ps = np.empty_like(P); vs = np.empty_like(V)
for b in range(len(P)):
    p, v = P[b:b + 1], V[b:b + 1]
    for _ in range(10):
        p, v, _ = W.physics(p, v, pil)
    ps[b], vs[b] = p[0], v[0]
print(f"batched ({len(P)} samples) vs one-at-a-time, 10 steps, float64: identical p {np.array_equal(pb, ps)}, v {np.array_equal(vb, vs)}")

# negative controls: the same comparison does see small differences
lab32 = S.sim_labels(src[6]["p"].astype(np.float32).astype(np.float64), src[6]["v"].astype(np.float32).astype(np.float64), src[6]["pil"])
print("control: states rounded to float32 before simulating -> fields differing from make_pool:",
      [k for k in S.LABEL_KEYS if not np.array_equal(lab32[k], pool.by_n[6][k])])
print("control: make_pool p5 vs sim_labels p10 equal:", np.array_equal(pool.by_n[6]["p5"], S.sim_labels(src[6]["p"], src[6]["v"], src[6]["pil"])["p10"]))
