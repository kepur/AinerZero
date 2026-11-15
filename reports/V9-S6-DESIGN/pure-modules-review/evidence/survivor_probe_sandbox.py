#!/usr/bin/env python3
"""P256 review, item 4: are the surviving sandbox / cells-static mutants equivalent? (pure NumPy)

R4 (sim_labels marks wall and pillar contacts in the disk-contact matrix): which states would it change,
and do the pure test's states or the native test's states contain such contacts at step 1?
R1b (outcomes of earlier groups kept when a later group fails): what is left behind.
X2 (a module-level alias of W.physics): the cells.sealed() code, cut out of cells.py with ast (cells.py
imports MLX at module level, so it is not imported), run on a NumPy-only seal list."""
from __future__ import annotations

import ast
import sys
import types
from contextlib import contextmanager
from pathlib import Path

import numpy as np

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import sandbox as S

ROOT = Path(__file__).resolve().parents[4]


def step1_other_contacts(P, V, PIL):
    out = []
    for b in range(len(P)):
        _, _, c = W.physics(P[b:b + 1], V[b:b + 1], tuple(map(tuple, PIL[b])), log=True)
        out.append([x for x in c if x[0] != "disk"])
    return out


# --- R4 on the pure test's three states (test_sim_labels_is_the_simulator_rollout) ---
ep = W.generate_episode("s6t-sandbox-contacts", 0, 8, steps=300)
hit = [t for t in range(len(ep.steps)) if any(k == "disk" for k, i, j in ep.steps[t].contacts)][:2]
ts = hit + [t for t in range(len(ep.steps)) if t not in hit][:1]
P = np.stack([ep.steps[t].positions for t in ts]); V = np.stack([ep.steps[t].velocities for t in ts])
PIL = np.broadcast_to(np.asarray(ep.pillars, float), (3, 3, 3)).copy()
print("R4 pure test states", ts, "-> wall/pillar contacts at step 1:", step1_other_contacts(P, V, PIL))

# --- R4 on the native test's states (test_sim_labels_equal_make_pool_labels; same construction, no MLX) ---
eps = [W.generate_episode("s6t-sandbox-native", w, n, steps=80) for w, n in enumerate([4, 6, 8, 10, 6])]
rng = np.random.default_rng(4)
pairs = sorted({(int(rng.integers(5)), int(rng.integers(80))) for _ in range(200)})
n_other = sum(any(k != "disk" for k, _, _ in eps[e].steps[t].contacts) for e, t in pairs)
print(f"R4 native test states: {len(pairs)}; with a wall/pillar contact at step 1: {n_other} "
      "(make_pool marks disk contacts only, so the native comparison would differ on these)")

# --- R4 share of affected candidates on candidate-like worlds (4-8 disks, 300 steps) ---
tot = aff = 0
for w in range(20):
    e = W.generate_episode("s6r-review-pure", 100 + w, 4 + w % 5)
    for s in e.steps:
        tot += 1
        aff += any(k != "disk" for k, _, _ in s.contacts)
print(f"R4 candidate-like states (20 worlds x 300 steps): {aff}/{tot} = {aff / tot:.3f} have a wall/pillar contact at step 1, "
      "i.e. would get a wrong contact label under R4")

# --- R1b: what a two-group reveal that fails in its second group leaves behind, under the mutant ---
src = {n: {"p": np.stack([e.steps[t].positions for t in range(4)]), "v": np.stack([e.steps[t].velocities for t in range(4)]),
           "pil": np.broadcast_to(np.asarray(e.pillars, float), (4, 3, 3)).copy()}
       for n, e in ((4, W.generate_episode("s6r-review-pure", 0, 4, steps=8)), (6, W.generate_episode("s6r-review-pure", 1, 6, steps=8)))}


def failing_on_6(Pb, Vb, PILb):
    if Pb.shape[1] == 6:
        raise RuntimeError("simulator down for n=6")
    return S.sim_labels(Pb, Vb, PILb)


class R1b(S.CandidatePool):
    def reveal(self, ids):                     # the R1b mutant's reveal, verbatim apart from the class wrapper
        ids = self._check_new(ids)
        for n, (gs, rows) in self._groups(ids).items():
            self._outcomes.update(self._simulate(gs))
        self._revealed.extend(ids)
        self._revealed_set.update(ids)
        self._log.append({"call": len(self._log), "ids": list(ids)})
        return self._assemble(ids)


for cls in (S.CandidatePool, R1b):
    cp = cls(src, labeller=failing_on_6)
    try:
        cp.reveal([0, 1, 4])
    except RuntimeError:
        pass
    print(f"R1b {cls.__name__:13s}: after reveal([0, 1, 4]) failed on n=6 -> revealed {cp.revealed_ids().tolist()}, "
          f"log {cp.log()}, outcome store keys {sorted(cp._outcomes)}")

# --- X2: cells.sealed() against a saved reference ---
text = (ROOT / "src/ainerzero/v9/experiments/s6/cells.py").read_text(encoding="utf-8")
tree = ast.parse(text)
keep = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in ("SealBreach", "sealed")]
mod = types.ModuleType("cells_seal_extract"); sys.modules[mod.__name__] = mod
mod.__dict__.update({"contextmanager": contextmanager, "_SEALED": [(W, "physics"), (S, "sim_labels"),
                                                                     (S.CandidatePool, "_simulate"), (S.CandidatePool, "reveal")]})
exec(compile(ast.Module(body=keep, type_ignores=[]), "cells.py", "exec"), mod.__dict__)
print("X2 extracted from cells.py:", [n.name for n in keep], "| mlx imported:", any(m.startswith("mlx") for m in sys.modules))
_step = W.physics                                    # saved before the seal opens, as the X2 mutant does at import time
p0, v0 = P[:1], V[:1]
with mod.sealed():
    try:
        W.physics(p0, v0, ep.pillars)
        print("X2 W.physics inside the seal: returned")
    except mod.SealBreach as e:
        print("X2 W.physics inside the seal: SealBreach:", e)
    p1, v1, _ = _step(p0, v0, ep.pillars)
    print("X2 the saved alias inside the seal: returned an outcome, v1[0, 0] =", v1[0, 0].tolist())
    cp = S.CandidatePool(src)
    try:
        cp._labeller(src[4]["p"][:1], src[4]["v"][:1], src[4]["pil"][:1])
        print("X2 the pool's stored labeller (sim_labels, captured before the seal) inside the seal: returned")
    except mod.SealBreach as e:
        print("X2 the pool's stored labeller (sim_labels, captured before the seal) inside the seal: SealBreach (it calls W.physics):", e)
    try:
        cp._assemble([0])
    except KeyError as e:
        print("X2 _assemble of an unrevealed id inside the seal: KeyError", e, "(no outcome exists)")
print("X2 after the seal: W.physics restored:", W.physics is _step)

# --- R5: the constructor simulates everything directly (not through the labeller) ---
class R5(S.CandidatePool):
    def __init__(self, *a, **k):               # the R5 mutant's extra line, after the original constructor
        super().__init__(*a, **k)
        self._cache = {n: S.sim_labels(e["p"], e["v"], e["pil"]) for n, e in self._states.items()}


calls = [0]
real = W.physics


def counting(*a, **k):
    calls[0] += 1
    return real(*a, **k)


class Spy:
    def __init__(self):
        self.n = 0

    def __call__(self, P, V, PIL):
        self.n += 1
        return S.sim_labels(P, V, PIL)


for cls in (S.CandidatePool, R5):
    W.physics = counting
    calls[0] = 0
    spy = Spy()
    cp = cls(src, labeller=spy)
    st, rem = cp.states(), cp.remaining()
    built = calls[0]
    W.physics = real
    have = getattr(cp, "_cache", None)
    line = (f"R5 {cls.__name__:13s}: simulator calls during construction + states() + remaining(): {built}; labeller calls {spy.n}; "
            f"_outcomes {sorted(cp._outcomes)}")
    if have is not None:
        got = cp.reveal([5])
        line += (f"; labels of id 5 held before its reveal equal what reveal returns: "
                 f"{all(np.array_equal(have[6][k][1], got.by_n[6][k][0]) for k in S.LABEL_KEYS)}")
    print(line)
