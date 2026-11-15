#!/usr/bin/env python3
"""Evidence 1: Label isolation probe (§6 four layers)."""
import ast
import inspect
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s6 import cells as C
from ainerzero.v9.experiments.s6 import sandbox as S

print("=== 1. Layer 1 & 2: CandidatePool and candidate_source ===")
# Generate small source
ns = "s6t-probe"
sizes = C.Sizes(per=5, rounds=2, steps=5, pool=20, cand_worlds=2)
source = C.candidate_source(ns, 0, sizes)

print(f"n_states: {C.n_states(source)}")
for n, d in source.items():
    print(f"Bucket {n}: keys={sorted(d.keys())}, p shape={d['p'].shape}, dtype={d['p'].dtype}")
    assert set(d.keys()) == {"p", "v", "pil"}

cp = C.make_candidate_pool(source)
print(f"cp._outcomes initially: {len(cp._outcomes)}")
print(f"cp._revealed initially: {len(cp._revealed)}")
print(f"cp.remaining() count: {len(cp.remaining())}")

states = cp.states()
for n, d in states.items():
    print(f"states()[{n}]: keys={sorted(d.keys())}, p.flags.writeable={d['p'].flags.writeable}")
    assert not d["p"].flags.writeable
    assert set(d.keys()) == {"id", "p", "v", "pil"}

print("\n=== 2. Layer 3: Sealed context manager & Trapping ===")
# Verify all items in _SEALED are trapped
print(f"_SEALED list length: {len(C._SEALED)}")
for obj, name in C._SEALED:
    print(f"  SEALED target: {getattr(obj, '__name__', str(obj))}.{name}")

ep = W.generate_episode(ns, 0, 4, steps=5)
P, V = ep.steps[0].positions[None], ep.steps[0].velocities[None]
pil = ep.pillars

with C.sealed():
    # 1. W.physics
    try:
        W.physics(P, V, pil)
        print("FAIL: W.physics not trapped")
    except C.SealBreach as e:
        print("OK: W.physics trapped:", e)

    # 2. W.generate_episode
    try:
        W.generate_episode(ns, 0, 4)
        print("FAIL: W.generate_episode not trapped")
    except C.SealBreach as e:
        print("OK: W.generate_episode trapped:", e)

    # 3. L.make_pool
    try:
        L.make_pool([ep], 2, np.random.default_rng(0), W.physics)
        print("FAIL: L.make_pool not trapped")
    except C.SealBreach as e:
        print("OK: L.make_pool trapped:", e)

    # 4. S.sim_labels
    try:
        S.sim_labels(P, V, np.asarray(pil, float)[None])
        print("FAIL: S.sim_labels not trapped")
    except C.SealBreach as e:
        print("OK: S.sim_labels trapped:", e)

    # 5. cp.reveal
    try:
        cp.reveal([0])
        print("FAIL: cp.reveal not trapped")
    except C.SealBreach as e:
        print("OK: cp.reveal trapped:", e)

    # 6. cp._simulate
    try:
        cp._simulate([0])
        print("FAIL: cp._simulate not trapped")
    except C.SealBreach as e:
        print("OK: cp._simulate trapped:", e)

print("\n=== 3. Module attribute vs Pre-saved function reference probe ===")
# What happens if a caller holds a pre-saved reference to W.physics vs calling cp._labeller?
saved_physics_ref = W.physics

with C.sealed():
    # Directly calling saved_physics_ref bypasses module attribute lookup on W:
    print("Direct call on saved_physics_ref inside sealed():")
    res_saved = saved_physics_ref(P, V, pil)
    print("  Outcome calculated via saved reference? YES, returned p shape:", res_saved[0].shape)

    # What about cp._labeller?
    # cp was instantiated BEFORE entering sealed().
    # cp._labeller points to S.sim_labels (which was the original function).
    # But sim_labels internally does `W.physics(...)`, which is a module attribute lookup on W!
    print("Call cp._labeller inside sealed():")
    try:
        cp._labeller(P, V, np.asarray(pil, float)[None])
        print("  FAIL: cp._labeller was not trapped!")
    except C.SealBreach as e:
        print("  OK: cp._labeller trapped via internal W.physics lookup:", e)

print("\n=== 4. Layer 4: Arm T vs Arm R parity ===")
k = 0
r_seed = C.pick_seed(ns, "R", k)
t_seed = C.pick_seed(ns, "T", k)
first_s = C.first_seed(ns, k)
print(f"R pick seed: {r_seed}, T pick seed: {t_seed}")
assert r_seed == t_seed, "T pick seed must equal R pick seed"

rng_r = np.random.default_rng(r_seed)
rng_t = np.random.default_rng(t_seed)
rem = np.arange(100)
p_r = S.pick_random(rem, 10, rng_r)
p_t = S.pick_random(rem, 10, rng_t)
print(f"Picks parity: {np.array_equal(p_r, p_t)}")
assert np.array_equal(p_r, p_t)

print("\nProbe complete.")
