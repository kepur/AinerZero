#!/usr/bin/env python3
"""P256 recheck: are N1 and N2 equivalent? Mutants built in memory from the live files (nothing written)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "evidence"))
import indep_data as D  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402
from ainerzero.v9.experiments.s6 import analysis as AN  # noqa: E402
from ainerzero.v9.experiments.s6 import sandbox as S  # noqa: E402


def mutant(mod, name, pairs):
    s = Path(mod.__file__).read_text(encoding="utf-8")
    for old, new in pairs:
        assert s.count(old) == 1
        s = s.replace(old, new, 1)
    m = types.ModuleType(name); sys.modules[name] = m
    exec(compile(s, f"{name}.py", "exec"), m.__dict__)
    return m


# N2: point criterion ignored. E's wall-pillar error 0.97 of Z's (point fails <= 0.95), little noise (upper bound < 1)
N2 = mutant(AN, "analysis_N2", [('        point_ok = math.isfinite(x) and (spec["point"] is None or _holds(spec["point"][0], x, spec["point"][1]))',
                                  '        point_ok = math.isfinite(x)')])
fact = dict(D.FACT); fact["E"] = D.FACT["E"][:2] + [0.97] + D.FACT["E"][3:]; fact["P"] = [0.97] + D.FACT["P"][1:]
d = D.my_make_data(noise=0.01, fact=fact)
a, b = AN.decide(d, n=1000), N2.decide(d, n=1000)
for g in ("GZ-W", "GP"):
    x, y = a["gates"][g], b["gates"][g]
    print(f"N2 {g}: point {x['point']:.5f} bonferroni [{x['bonferroni'][0]:.5f}, {x['bonferroni'][1]:.5f}] | "
          f"original point_ok {x['point_ok']} passed {x['passed']} -> mutant point_ok {y['point_ok']} passed {y['passed']}")

# N1: the pool built by the mutant holds one-step outcomes of every candidate, and the trap on W.physics sees nothing
N1 = mutant(S, "sandbox_N1", [('STATE_KEYS = ("p", "v", "pil")\n', 'STATE_KEYS = ("p", "v", "pil")\n_phys = W.physics\n'),
                              ('        self._log: list[dict[str, Any]] = []',
                               '        self._log: list[dict[str, Any]] = []\n        self._cache = {n: [_phys(e["p"][i:i + 1], e["v"][i:i + 1], tuple(map(tuple, e["pil"][i]))) for i in range(len(e["p"]))]\n                       for n, e in self._states.items()}')])
ep = W.generate_episode("s6r-review-pure", 0, 4, steps=6)
src = {4: {"p": np.stack([s.positions for s in ep.steps]), "v": np.stack([s.velocities for s in ep.steps]),
           "pil": np.broadcast_to(np.asarray(ep.pillars, float), (6, 3, 3)).copy()}}
real, calls = W.physics, []
W.physics = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
try:
    cp0, cp1 = S.CandidatePool(src), N1.CandidatePool(src)
finally:
    W.physics = real
print("N1 trapped W.physics calls during construction (original, mutant):", len(calls), "| instance attributes original", sorted(vars(cp0)))
print("N1 mutant instance attributes", sorted(vars(cp1)), "| one-step v of id 2 held before any reveal equals reveal's v1:",
      np.array_equal(cp1._cache[4][2][1][0].astype(np.float32), cp0.reveal([2]).by_n[4]["v1"][0]))
