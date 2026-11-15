#!/usr/bin/env python3
"""P256 review, item 1: can anything obtain or compute an outcome of a candidate before it is revealed?

Pure NumPy. Counts every call of the simulator (W.physics, patched with a counter at module level, so the
count covers sim_labels and any direct use) and every call of the pool's labeller. Builds pools from the
review namespace s6r-review-pure only (in memory, nothing written)."""
from __future__ import annotations

import copy
import inspect
import pickle
import sys

import numpy as np

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import sandbox as S

print("sandbox from", S.__file__)
print("mlx imported:", any(m.startswith("mlx") for m in sys.modules))

REAL_PHYSICS = W.physics
PHYS_CALLS = [0]


def counting_physics(*a, **k):
    PHYS_CALLS[0] += 1
    return REAL_PHYSICS(*a, **k)


W.physics = counting_physics          # sim_labels calls W.physics through the module attribute


def states(sizes=((4, 7), (6, 5), (8, 3)), ns="s6r-review-pure"):
    by_n = {}
    for w, (n, s) in enumerate(sizes):
        ep = W.generate_episode(ns, w, n, steps=40)
        by_n[n] = {"p": np.stack([ep.steps[t].positions for t in range(s)]),
                   "v": np.stack([ep.steps[t].velocities for t in range(s)]),
                   "pil": np.broadcast_to(np.asarray(ep.pillars, float), (s, 3, 3)).copy()}
    return by_n


class CountingLabeller:
    def __init__(self, fail_on_n=None):
        self.calls, self.fail_on_n = [], fail_on_n

    def __call__(self, P, V, PIL):
        self.calls.append(P.shape)
        if self.fail_on_n is not None and P.shape[1] == self.fail_on_n:
            raise RuntimeError(f"simulator down for n={P.shape[1]}")
        return S.sim_labels(P, V, PIL)


def fresh(**kw):
    src = states()
    PHYS_CALLS[0] = 0
    return S.CandidatePool(src, **kw), src


# L1: every public method and every zero-argument callable reachable on the instance, before any reveal
lab = CountingLabeller()
cp, src = fresh(labeller=lab)
PHYS_CALLS[0] = 0
called = []
for name in sorted(set(dir(cp))):
    if name in ("reveal", "_simulate", "__init__", "__init_subclass__", "__new__", "__class__", "__reduce__",
                "__reduce_ex__", "__getstate__", "__subclasshook__", "__delattr__", "__setattr__", "__getattribute__"):
        continue
    attr = getattr(cp, name)
    if not callable(attr):
        continue
    try:
        sig = inspect.signature(attr)
    except (TypeError, ValueError):
        continue
    if all(p.default is not p.empty or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in sig.parameters.values()):
        try:
            attr()
            called.append(name)
        except Exception as e:      # noqa: BLE001
            called.append(f"{name}!{type(e).__name__}")
print("L1 zero-arg callables invoked before any reveal:", called)
print("L1 simulator calls:", PHYS_CALLS[0], "| labeller calls:", len(lab.calls), "| _outcomes keys:", sorted(cp._outcomes))
st = cp.states()
print("L1 states() fields:", {n: sorted(e) for n, e in st.items()},
      "| any label key:", any(set(e) & set(S.LABEL_KEYS) for e in st.values()))
print("L1 instance __dict__ keys:", sorted(vars(cp)))

# L2: outcomes exist exactly for the revealed ids, after reveals
cp.reveal([13, 2, 8]); cp.reveal(np.array([0], dtype=np.int64))
print("L2 after reveal([13,2,8]), reveal([0]): _outcomes keys", sorted(cp._outcomes), "| revealed", cp.revealed_ids().tolist(),
      "| labeller calls (rows per call)", [s[0] for s in lab.calls], "| simulator calls", PHYS_CALLS[0])

# L3: the assembly step cannot include an unrevealed sample (there is no outcome to assemble)
try:
    cp._assemble([5])
    print("L3 _assemble([5]) on an unrevealed id: RETURNED (leak)")
except KeyError as e:
    print("L3 _assemble([5]) on an unrevealed id: KeyError", e)

# L4: a reveal spanning two disk counts whose second group fails to simulate
lab4 = CountingLabeller(fail_on_n=6)
cp4, _ = fresh(labeller=lab4)
try:
    cp4.reveal([0, 1, 8, 9])
except RuntimeError as e:
    print("L4 reveal([0,1,8,9]) with n=6 failing:", e)
print("L4 labeller calls (n per call):", [s[1] for s in lab4.calls], "| revealed", cp4.revealed_ids().tolist(), "| log", cp4.log(),
      "| _outcomes keys", sorted(cp4._outcomes), "| remaining has 0,1,8,9:", set([0, 1, 8, 9]) <= set(cp4.remaining().tolist()))

# L5: the pool type fails after simulating (outside the documented guarantee, which covers simulation)
def bad_pool_type(by_n):
    raise RuntimeError("pool type rejected")


cp5, _ = fresh(pool_type=bad_pool_type)
try:
    cp5.reveal([3])
except RuntimeError as e:
    print("L5 reveal([3]) with a failing pool_type:", e)
print("L5 afterwards: revealed", cp5.revealed_ids().tolist(), "| log", cp5.log(), "| _outcomes keys", sorted(cp5._outcomes))

# L6: bad inputs raise before any simulation and leave nothing behind
lab6 = CountingLabeller()
cp6, _ = fresh(labeller=lab6)
cp6.reveal([1, 2])
n0 = len(lab6.calls)
bad = {"repeat across calls": [3, 2], "repeat within call": [4, 4], "past the end": [15], "negative": [-1],
       "empty": [], "2-D": [[1]], "float": [1.0], "bool": np.array([True]), "object": np.array([3], dtype=object),
       "uint64 huge": np.array([2**63 + 5], dtype=np.uint64), "valid then out of range": [5, 99]}
for name, ids in bad.items():
    try:
        cp6.reveal(ids)
        print(f"L6 {name}: ACCEPTED")
    except Exception as e:      # noqa: BLE001
        print(f"L6 {name}: {type(e).__name__}: {e}")
print("L6 labeller calls caused by the bad inputs:", len(lab6.calls) - n0, "| revealed", cp6.revealed_ids().tolist(),
      "| log calls", len(cp6.log()), "| _outcomes keys", sorted(cp6._outcomes))

# L7: writing into what reveal / revealed_pool hand out does not reach the pool's outcomes
cp7, _ = fresh()
got = cp7.reveal([7])
got.by_n[6]["v1"][...] = 123.0
got.by_n[6]["p"][...] = -5.0
again = cp7.revealed_pool()
print("L7 after writing into the returned arrays: revealed_pool v1 max", float(again.by_n[6]["v1"].max()),
      "| p min", float(again.by_n[6]["p"].min()), "| writeable returned:", got.by_n[6]["v1"].flags.writeable)

# L8: a labeller that writes into its inputs cannot change the stored states
def scribbling(P, V, PIL):
    out = S.sim_labels(P, V, PIL)
    P += 1.0; V *= 0.0; PIL[...] = 0.0
    return out


cp8, src8 = fresh(labeller=scribbling)
cp8.reveal([0, 7])
print("L8 stored states unchanged after a scribbling labeller:",
      all(np.array_equal(cp8._states[n][k], np.asarray(src8[n][k], float)) for n in src8 for k in S.STATE_KEYS))

# L9: generic Python copying (outside the module's reach), r2 vs the P253 sealed store
cp9, _ = fresh()
cp9.reveal([0])
dc = copy.deepcopy(cp9)
before = PHYS_CALLS[0]
dc.reveal([9])
print("L9 deepcopy(pool).reveal([9]) works:", 9 in dc.revealed_ids().tolist(), "| simulator calls for it:", PHYS_CALLS[0] - before,
      "| original log", cp9.log())
blob = pickle.dumps(cp9)
up = pickle.loads(blob)
print("L9 pickle carries outcomes only for revealed ids:", sorted(up._outcomes), "| bytes", len(blob))

# L10: labels can be recomputed from public states by anyone who calls the simulator (a seal matter, not the pool's)
cp10, src10 = fresh()
st = cp10.states()
p, v, _ = REAL_PHYSICS(st[6]["p"][:1].astype(np.float64), st[6]["v"][:1].astype(np.float64), tuple(map(tuple, st[6]["pil"][0].astype(np.float64))))
lab10 = cp10.reveal([7]).by_n[6]
print("L10 W.physics on the float32 public state vs revealed p1, v1: max |diff|",
      float(np.max(np.abs(p[0].astype(np.float32) - lab10["p1"][0]))), float(np.max(np.abs(v[0].astype(np.float32) - lab10["v1"][0]))))

# L11: the caller's id array is copied (changing it later does not change the log)
cp11, _ = fresh()
ids = np.array([4, 5], dtype=np.int64)
cp11.reveal(ids); ids[:] = [6, 7]
print("L11 log after the caller changes its id array:", cp11.log(), "| revealed", cp11.revealed_ids().tolist())

# L12: names in the class: what refers to the simulator, the labeller and the outcome store (bare names too)
import ast
src_cls = inspect.getsource(S.CandidatePool)
tree = ast.parse(src_cls)
for target in ("_simulate", "_labeller", "_outcomes", "sim_labels", "physics", "_assemble"):
    refs = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            for n in ast.walk(fn):
                if (isinstance(n, ast.Attribute) and n.attr == target) or (isinstance(n, ast.Name) and n.id == target):
                    refs.add(fn.name)
    print(f"L12 methods referring to {target} (attribute or bare name): {sorted(refs)}")
print("L12 class dict:", sorted(vars(S.CandidatePool)))
W.physics = REAL_PHYSICS
