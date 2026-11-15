#!/usr/bin/env python3
"""S6 r0 review, budget check (§5): time one evaluation pass (explore_s6a.evaluate, CPU) of 3 networks on the
30 s6x-test worlds, and 200 training steps of one learner (GPU), to extrapolate to the probe (50 + 25 worlds)
and final (200 + 100 worlds) evaluation sizes of DESIGN-r0. Untrained networks: the cost does not depend on
the weights. Usage (MLX; under the shared lock): <this>
"""
import sys
import time

import mlx.core as mx
import numpy as np

sys.path.insert(0, "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN/tier1-explore")
import explore_s6a as XA  # noqa: E402
import explore_s6c as XC  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

t = time.time()
eps = [W.generate_episode("s6x-test", w, 6) for w in range(20)] + [W.generate_episode("s6x-test", 1000 + w, 10) for w in range(10)]
t_gen = time.time() - t
mx.set_default_device(mx.gpu)
learners = [XC.Learner(s) for s in XA.SEEDS]
pool = L.make_pool(A.train_worlds("s6x-cand", 10), 3000, np.random.default_rng(11), W.physics, exact_frac=1.0)
t = time.time()
learners[0].train(pool, 200, 0.0)
t_train200 = time.time() - t
mx.set_default_device(mx.cpu)
t = time.time()
XA.evaluate({str(s): l.model for s, l in zip(XA.SEEDS, learners)}, eps)
t_eval = time.time() - t
print(f"generate 30 test worlds: {t_gen:.1f}s")
print(f"train 200 steps (1 network, GPU): {t_train200:.1f}s -> 2500 steps ~ {t_train200 * 12.5:.0f}s")
print(f"evaluate 3 networks on 30 worlds (CPU): {t_eval:.1f}s -> per network-world {t_eval / 90:.3f}s")
per_nw = t_eval / 90
for name, nw in (("probe", 75), ("final", 300)):
    tot = per_nw * nw * 54 * 4
    print(f"{name}: {nw} worlds x 54 networks x 4 rounds = {tot / 3600:.2f} h of evaluation alone")
