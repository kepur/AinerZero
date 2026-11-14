#!/bin/bash
# Round E2 under one lock hold: a tiny smoke first (stops on error), then the full run.
set -euo pipefail
cd /Users/mac/AinerWorkFlow/AinerZero
D=reports/V9-S6-DESIGN/tier1-explore
.venv/bin/python - <<'PY'
import sys
sys.path.insert(0, "reports/V9-S6-DESIGN/tier1-explore")
import numpy as np, mlx.core as mx
import explore_s6e2 as E2, explore_s6a as XA
from ainerzero.v9.experiments.s4 import analysis as A, learned_mlx as L, world as W
pool = L.make_pool(A.train_worlds("s6x-smoke", 3), 400, np.random.default_rng(0), W.physics, exact_frac=1.0)
mx.set_default_device(mx.cpu)
lr = E2.Learner(1)
before = {k: np.array(v) for k, v in __import__("mlx.utils", fromlist=["tree_flatten"]).tree_flatten(lr.model.parameters()) if k.startswith("prior.")}
lr.train(pool, 5)
after = {k: np.array(v) for k, v in __import__("mlx.utils", fromlist=["tree_flatten"]).tree_flatten(lr.model.parameters()) if k.startswith("prior.")}
assert all(np.array_equal(before[k], after[k]) for k in before), "prior changed"
sp = lr.spread(pool)
assert all(np.isfinite(v).all() for v in sp.values())
print("smoke ok")
PY
.venv/bin/python $D/explore_s6e2.py 3000 4 2500 $D/results-s6e2.json
