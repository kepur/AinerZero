#!/usr/bin/env python3
"""P253 review, item 1: try to reach unrevealed labels of CandidatePool through public or common paths.

Pure NumPy (no MLX). A counting stand-in wraps the label store so every read is attributed to the call
that made it. Prints one line per probe; "LEAK" marks a path that hands out labels of an id that the
pool's own reveal log does not contain.
"""
from __future__ import annotations

import copy
import pickle
from dataclasses import dataclass

import numpy as np

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import sandbox as S

print("sandbox module:", S.__file__)
LABELS = ("contact", "p1", "p10", "p5", "v1", "v10", "v5")


@dataclass(frozen=True)
class FakePool:
    by_n: dict


def fake(sizes=((4, 6), (6, 5), (8, 4)), seed=0):
    rng = np.random.default_rng(seed)
    by_n = {}
    for w, (n, s) in enumerate(sizes):
        ep = W.generate_episode("s6r-review-leak", w, n, steps=20)
        e = {"p": np.stack([ep.steps[t].positions for t in range(s)]).astype(np.float32),
             "v": np.stack([ep.steps[t].velocities for t in range(s)]).astype(np.float32),
             "pil": np.broadcast_to(np.asarray(ep.pillars, np.float32), (s, 3, 3)).copy()}
        for k in ("p1", "p5", "p10", "v1", "v5", "v10"):
            e[k] = rng.normal(size=(s, n, 2)).astype(np.float32)
        e["contact"] = (rng.random((s, n, n)) < 0.3).astype(np.float32)
        by_n[n] = e
    return FakePool(by_n)


class Counting(dict):
    """dict that counts every read of a bucket (the label store is {n: {field: array}})."""
    reads = 0

    def __getitem__(self, k):
        Counting.reads += 1
        return super().__getitem__(k)

    def items(self):
        Counting.reads += 1
        return super().items()

    def values(self):
        Counting.reads += 1
        return super().values()

    def get(self, *a):
        Counting.reads += 1
        return super().get(*a)


def fresh():
    cp = S.CandidatePool(fake())
    cp._sealed_labels = Counting(cp._sealed_labels)
    Counting.reads = 0
    return cp


def reads_of(fn):
    before = Counting.reads
    try:
        out = fn()
        err = None
    except Exception as ex:  # noqa: BLE001
        out, err = None, f"{type(ex).__name__}: {ex}"
    return Counting.reads - before, out, err


src = fake()
N = sum(len(e["p"]) for e in src.by_n.values())
print("pool size", N)

# P1 states(): fields, memory sharing with the internal stores, and writability.
cp = fresh()
st = cp.states()
fields = {n: sorted(e) for n, e in st.items()}
share = any(np.shares_memory(a, b) for e in st.values() for a in e.values()
            for store in (cp._states, dict(cp._sealed_labels)) for bucket in store.values() for b in bucket.values())
a = st[4]["p"]
a.flags.writeable = True          # allowed: the returned array owns its data
a[0, 0, 0] = 1234.0
print("P1 states fields", fields, "| shares memory with internal stores:", share,
      "| own data:", all(a.flags.owndata for e in st.values() for a in e.values()),
      "| internal p after caller write:", float(cp._states[4]["p"][0, 0, 0]))

# P2 every public member and every dunder the class defines, called without arguments, reads no labels.
cp = fresh()
own_dunders = {n for n in vars(S.CandidatePool) if n.startswith("__") and n.endswith("__")}
print("P2 dunders the class itself defines:", sorted(own_dunders))
for name in sorted(set(dir(cp))):
    public = not name.startswith("_")
    if name == "reveal" or not (public or name in own_dunders) or name in ("__init__", "__dict__", "__module__",
                                                                          "__doc__", "__weakref__", "__annotations__",
                                                                          "__firstlineno__", "__static_attributes__"):
        continue
    attr = getattr(cp, name)
    if not callable(attr):
        print(f"P2 {name}: non-callable attribute, type {type(attr).__name__}")
        continue
    r, out, err = reads_of(attr)
    print(f"P2 {name}(): label reads {r}" + (f" ({err})" if err else ""))

# P3 reveal / revealed_pool hand out only revealed rows, and as copies.
cp = fresh()
got = cp.reveal([10, 1])
rp = cp.revealed_pool()
lab_store = dict(cp._sealed_labels)
shared = any(np.shares_memory(a, b) for q in (got, rp) for e in q.by_n.values() for a in e.values()
             for bucket in lab_store.values() for b in bucket.values())
rows = {n: len(e["p"]) for n, e in rp.by_n.items()}
print("P3 reveal([10, 1]) buckets", {n: len(e["p"]) for n, e in got.by_n.items()}, "| revealed_pool rows", rows,
      "| shares memory with label store:", shared)

# P4 failed reveals: no label read, no state change (ids, log), for every kind of bad input.
cp = fresh()
cp.reveal([2, 3])
bad = {"dup across calls": [3, 4], "dup within": [5, 5], "out of range": [N], "negative": [-1],
       "bool": [True, False], "float": [1.0], "2-D": [[6, 7]], "object dtype": np.array([6], dtype=object),
       "uint64 huge": np.array([2 ** 63 + 5], dtype=np.uint64), "valid then bad": [6, 7, N + 3]}
for k, ids in bad.items():
    r, _, err = reads_of(lambda ids=ids: cp.reveal(ids))
    print(f"P4 reveal({k}): {err} | label reads {r} | revealed {cp.revealed_ids().tolist()} | log calls {len(cp.log())}")

# P5 empty reveal: legal, but it consumes a log call number.
cp = fresh()
r, out, err = reads_of(lambda: cp.reveal([]))
print("P5 reveal([]):", err, "| returned buckets", None if out is None else dict(out.by_n), "| log", cp.log(),
      "| label reads", r)

# P6 generic Python copying of the pool object.
cp = fresh()
cp.reveal([0])
dc = copy.deepcopy(cp)
leak = dc.reveal([9])
print("P6 deepcopy(pool).reveal([9]) -> labels of id 9 obtained:", sorted(leak.by_n[6]),
      "| original pool revealed ids", cp.revealed_ids().tolist(), "| original log", cp.log(),
      "-> LEAK relative to the original's log" if 9 not in cp.revealed_ids().tolist() else "")
sc = copy.copy(cp)
sc.reveal([8])
print("P6 copy.copy(pool).reveal([8]) -> original revealed ids", cp.revealed_ids().tolist(),
      "(shallow copy shares the reveal history)")
blob = pickle.dumps(S.CandidatePool(src))
un = pickle.loads(blob)
lab = un._sealed_labels[4]["p1"]
print("P6 pickle round-trip carries the sealed store:", np.array_equal(lab, src.by_n[4]["p1"]),
      "| bytes", len(blob))

# P7 the caller's source pool keeps every label after construction (the module cannot take it away).
cp = S.CandidatePool(src)
print("P7 source pool still holds labels after CandidatePool(src):", sorted(k for k in src.by_n[4] if k in LABELS))

# P8 pick functions do not range-check ids: a negative id wraps around in score/flags indexing.
score = np.arange(N, dtype=float)
r, out, err = reads_of(lambda: S.pick_top(score, np.array([-1, 0, 1]), 1))
print("P8 pick_top(score, [-1, 0, 1], 1) ->", out, err, "| then reveal:",
      reads_of(lambda: S.CandidatePool(src).reveal(out))[2] if out is not None else None)
flags = np.zeros(N, bool); flags[-1] = True
print("P8 pick_geo(flags with last id set, remaining [-1, 0, 1], 1) ->",
      S.pick_geo(flags, np.array([-1, 0, 1]), 1, np.random.default_rng(0)))

# P9 _take is reachable only through reveal (checked ids) and revealed_pool (revealed ids): who calls it?
import ast, inspect  # noqa: E401,E402
tree = ast.parse(inspect.getsource(S))
callers = set()
for fn in ast.walk(tree):
    if isinstance(fn, ast.FunctionDef):
        for node in ast.walk(fn):
            if isinstance(node, ast.Attribute) and node.attr == "_take" and fn.name != "_take":
                callers.add(fn.name)
print("P9 functions referencing _take:", sorted(callers))

# P10 (final version) the label read itself fails: nothing may be registered.
cp = S.CandidatePool(src)


class Broken(dict):
    def __getitem__(self, k):
        raise RuntimeError("label door blocked")


real = cp._sealed_labels
cp._sealed_labels = Broken(real)
try:
    cp.reveal([3, 4])
except RuntimeError as ex:
    print("P10 reveal with a failing label read:", ex, "| revealed", cp.revealed_ids().tolist(), "| log", cp.log(),
          "| remaining has 3 and 4:", {3, 4} <= set(cp.remaining().tolist()))
cp._sealed_labels = real
print("P10 after unblocking, reveal([3, 4]) works:", sorted(cp.reveal([3, 4]).by_n), "| log", cp.log())
