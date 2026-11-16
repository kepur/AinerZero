"""Minimum-cost assignment (Hungarian algorithm, O(n^3)) without SciPy.

Pure NumPy / standard library. Rectangular matrices are padded; only real (row, col) pairs are returned.
"""

from __future__ import annotations

import numpy as np


def hungarian(cost: np.ndarray) -> list[tuple[int, int]]:
    """Pairs (row, col) of a minimum-cost assignment; every row or every column is assigned."""
    cost = np.asarray(cost, dtype=np.float64)
    if cost.ndim != 2:
        raise ValueError("cost must be 2-D")
    nr, nc = cost.shape
    if nr == 0 or nc == 0:
        return []
    if not np.isfinite(cost).all():
        raise ValueError("cost must be finite")
    n = max(nr, nc)
    c = np.full((n, n), cost.max() + 1.0)
    c[:nr, :nc] = cost
    u = np.zeros(n + 1)
    v = np.zeros(n + 1)
    p = np.zeros(n + 1, dtype=np.int64)
    way = np.zeros(n + 1, dtype=np.int64)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = np.full(n + 1, np.inf)
        used = np.zeros(n + 1, dtype=bool)
        while True:
            used[j0] = True
            i0 = p[j0]
            free = ~used[1:]
            cur = c[i0 - 1] - u[i0] - v[1:]
            better = free & (cur < minv[1:])
            minv[1:][better] = cur[better]
            way[1:][better] = j0
            cand = np.where(free, minv[1:], np.inf)
            j1 = int(np.argmin(cand)) + 1
            delta = cand[j1 - 1]
            u[p[used]] += delta
            v[used] -= delta
            minv[~used] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    return [(int(p[j]) - 1, j - 1) for j in range(1, n + 1) if p[j] and p[j] - 1 < nr and j - 1 < nc]
