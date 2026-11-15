"""Field order of a revealed bucket vs make_pool's order (p v pil contact p1 v1 p5 v5 p10 v10). Pure NumPy."""
from dataclasses import dataclass
import numpy as np
from ainerzero.v9.experiments.s6 import sandbox as S

@dataclass(frozen=True)
class FakePool:
    by_n: dict

keys = ["p", "v", "pil", "contact", "p1", "v1", "p5", "v5", "p10", "v10"]   # make_pool's rows.setdefault order
shape = {"p": (3, 4, 2), "v": (3, 4, 2), "pil": (3, 3, 3), "contact": (3, 4, 4)}
src = FakePool({4: {k: np.zeros(shape.get(k, (3, 4, 2)), np.float32) for k in keys}})
cp = S.CandidatePool(src)
print("source order  :", list(src.by_n[4]))
print("reveal order  :", list(cp.reveal([0, 1]).by_n[4]))
print("revealed_pool :", list(cp.revealed_pool().by_n[4]))
