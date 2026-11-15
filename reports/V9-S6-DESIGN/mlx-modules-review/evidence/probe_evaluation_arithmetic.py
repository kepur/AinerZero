#!/usr/bin/env python3
"""Evidence 5: Numerical parity check between explore_s6a.py and cells.py evaluation arithmetic."""
import sys
from pathlib import Path

import mlx.core as mx
import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "reports/V9-S6-DESIGN/tier1-explore"))

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s6 import cells as C
from ainerzero.v9.experiments.s6 import epinet_mlx as E
import explore_s6a as EXP

mx.set_default_device(mx.cpu)

# Generate test episodes
ns = "s6t-eval-check"
eps = [W.generate_episode(ns, 0, 6, steps=30), W.generate_episode(ns, 1, 8, steps=30)]

# Check classify parity
for ep in eps:
    for t in range(len(ep.steps) - 1):
        c_exp = EXP.classify(ep, t)
        c_cells = C.classify(ep, t)
        assert np.array_equal(c_exp, c_cells)
print("classify() is identical across all steps and episodes.")

# Create models: one L-int, one EpiDynamics
model_lint = L.Dynamics("L-int")
model_epi = E.EpiDynamics()
model_epi.z = None

# Evaluate via explore_s6a
res_exp = EXP.evaluate({"lint": model_lint, "epi": model_epi}, eps)

# Evaluate via cells.py
tws = [C.prepare_world(ep) for ep in eps]
total_counts = np.zeros(4, dtype=np.int64)
total_eb = 0.0
for tw in tws:
    cnt, eb = C.world_counts(tw)
    total_counts += cnt
    total_eb += eb

sums_lint = np.zeros(4)
sums_epi = np.zeros(4)
for tw in tws:
    sums_lint += C.world_sums(model_lint, tw)
    sums_epi += C.world_sums(model_epi, tw)

mean_lint = sums_lint / total_counts
d_lint = 1.0 - sums_lint[0] / total_eb

mean_epi = sums_epi / total_counts
d_epi = 1.0 - sums_epi[0] / total_eb

print("\n--- Parity Check for L-int ---")
print("explore_s6a:", res_exp["lint"])
print("cells.py:   ", {"collision": mean_lint[0], "graze": mean_lint[1], "wall_pillar": mean_lint[2], "free": mean_lint[3],
                       "all": sums_lint.sum() / total_counts.sum(), "D": d_lint})

np.testing.assert_allclose([mean_lint[0], mean_lint[1], mean_lint[2], mean_lint[3], sums_lint.sum() / total_counts.sum(), d_lint],
                          [res_exp["lint"]["collision"], res_exp["lint"]["graze"], res_exp["lint"]["wall_pillar"],
                           res_exp["lint"]["free"], res_exp["lint"]["all"], res_exp["lint"]["D"]])
print("L-int parity: EXACT MATCH")

print("\n--- Parity Check for EpiDynamics (z=None) ---")
print("explore_s6a:", res_exp["epi"])
print("cells.py:   ", {"collision": mean_epi[0], "graze": mean_epi[1], "wall_pillar": mean_epi[2], "free": mean_epi[3],
                       "all": sums_epi.sum() / total_counts.sum(), "D": d_epi})

np.testing.assert_allclose([mean_epi[0], mean_epi[1], mean_epi[2], mean_epi[3], sums_epi.sum() / total_counts.sum(), d_epi],
                          [res_exp["epi"]["collision"], res_exp["epi"]["graze"], res_exp["epi"]["wall_pillar"],
                           res_exp["epi"]["free"], res_exp["epi"]["all"], res_exp["epi"]["D"]])
print("EpiDynamics (z=None) parity: EXACT MATCH")
