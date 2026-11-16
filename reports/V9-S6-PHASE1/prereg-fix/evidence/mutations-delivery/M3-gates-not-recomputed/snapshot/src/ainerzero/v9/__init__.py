"""ainerzero.v9 — replaceable interface layer of ARCHITECTURE_V9 (r5).

This package is the *contract* layer: seven replaceable interfaces, their
shared types, the ObservationPacket/v1.1 payload gate, and CPU test doubles
(``fakes``).  Real implementations land in their own cards (G1 group/filter,
G3 canonicalisation, T8 RLT, B1 contract checker, ...); nothing here trains,
downloads, or imports a framework.

Layering (r5 §3): ``interfaces`` has no dependency on any concrete module,
``fakes`` depends only on ``interfaces`` (+ numpy), and the analytic geometry
package ``geometry`` (G1) is an optional cross-check target of the contract
tests, never imported at module load time.
"""

from __future__ import annotations

from .interfaces import INTERFACES

__all__ = ["INTERFACES", "LAYERING"]

LAYERING: dict = {
    "interfaces": ["__future__", "abc", "hashlib", "json", "math", "re", "typing", "numpy"],
    "fakes": ["interfaces", "numpy"],
    "forbidden_everywhere": ["mlx", "onnxruntime", "torch", "tensorflow", "jax"],
}
"""Declared import budget of each layer; ``test_interface_surface.py`` enforces it."""


def __getattr__(name: str):
    if name == "fakes":
        raise AttributeError(
            "ainerzero.v9.fakes must be imported explicitly (test doubles are never "
            "imported by the contract layer); use `from ainerzero.v9 import fakes`"
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
