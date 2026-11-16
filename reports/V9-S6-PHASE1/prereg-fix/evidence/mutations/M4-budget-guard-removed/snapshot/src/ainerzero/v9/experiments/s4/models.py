"""S4 phase 1 hand-made process models (DESIGN-r3 §3). Pure CPU, NumPy only.

All take member states P, V [M, n, 2] and the pillars and return the next (P, V).
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from ainerzero.v9.experiments.s4 import world as W


def constant_velocity(P: np.ndarray, V: np.ndarray, pillars: Sequence[W.Pillar]):
    """E-CV: straight lines, no walls, no disks."""
    return P + V * W.DT, V.copy()


def bounce(P: np.ndarray, V: np.ndarray, pillars: Sequence[W.Pillar]):
    """E-B: constant velocity with wall and pillar reflections; no disk-disk collisions."""
    p, v, _ = W.physics(P, V, pillars, disks=False)
    return p, v


def true_physics(P: np.ndarray, V: np.ndarray, pillars: Sequence[W.Pillar]):
    """E-P: the generator's physics."""
    p, v, _ = W.physics(P, V, pillars)
    return p, v


HAND_MODELS = {"E-CV": constant_velocity, "E-B": bounce, "E-P": true_physics}
