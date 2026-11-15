"""N3 follow-up: does the prototype's np.argsort(-score) break ties by id ascending at the sizes the runner uses?
Pure NumPy. Compares the prototype selection rest[np.argsort(-score[rest])[:k]] with sandbox.pick_top."""
import numpy as np
from ainerzero.v9.experiments.s6 import sandbox as S
print("numpy", np.__version__)
# the author's tie test input
score = np.array([0.5, 0.9, 0.9, 0.1, 0.9, 0.7, 0.9]); rem = np.array([1, 2, 3, 4, 5, 6])
print("author case: prototype", rem[np.argsort(-score[rem])[:5]].tolist(), "pick_top", S.pick_top(score, rem, 5).tolist())
rng = np.random.default_rng(0)
for n in (8, 16, 17, 20, 32, 64, 200, 3000, 60000):
    s = rng.integers(0, 3, n).astype(float)            # three score levels: heavy ties
    r = np.arange(n)
    k = max(1, n // 2)
    proto = r[np.argsort(-s[r])[:k]]
    mod = S.pick_top(s, r, k)
    print(f"n={n:6d} k={k:6d}: same order {np.array_equal(proto, mod)}; same set {set(proto.tolist()) == set(mod.tolist())}")
