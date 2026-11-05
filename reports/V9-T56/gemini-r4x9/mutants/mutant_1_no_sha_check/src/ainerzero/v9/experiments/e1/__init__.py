"""E1 experiment package (NeuroGeometry x H-JEPA world brain).

All E1 modules run purely in CPU / NumPy, without unapproved model training
or unapproved external framework imports.
"""

from __future__ import annotations

from . import jacobian, metrics, prior

__all__ = ["jacobian", "metrics", "prior"]
