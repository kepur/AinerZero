"""Why N7 (smuggle the LAST unrevealed id into revealed_pool) survived: replay the picks of the native test
test_reveal_matches_make_pool_and_prototype_subset and ask whether the last id was revealed. Imports MLX
(learned_mlx.make_pool): under the shared lock."""
import numpy as np
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import sandbox as S
print("sandbox module:", S.__file__)
eps = [W.generate_episode("s6t-sandbox-native", w, n, steps=80) for w, n in enumerate([4, 6, 8, 10, 6])]
pool = L.make_pool(eps, 1500, np.random.default_rng(3), W.physics, exact_frac=1.0)
cp = S.CandidatePool(pool)
rng = np.random.default_rng(0)
cp.reveal(S.pick_random(cp.remaining(), 200, rng))
flags = S.geo_flags(cp.states())
cp.reveal(S.pick_geo(flags, cp.remaining(), 150, rng))
last = len(cp) - 1
print(f"N={len(cp)}; flagged {int(flags.sum())}; last id {last} flagged {bool(flags[last])}; "
      f"last id revealed after the two rounds: {last in set(cp.revealed_ids().tolist())}")
