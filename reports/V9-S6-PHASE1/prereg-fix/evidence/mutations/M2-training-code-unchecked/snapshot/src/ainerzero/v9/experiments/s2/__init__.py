"""S2 multi-timescale experiment package (NumPy / CPU-only reference).

Mathematical core per reports/V9-S2-DESIGN/DESIGN-r0.md §3 and ARCHITECTURE_V9 §4.
Pure CPU, zero MLX imports.
"""

from __future__ import annotations

from .core_math import (
    RolloutResult,
    aggregate_macro,
    aggregate_macro_sequence,
    aggregate_macro_window,
    continuous_gaussian_nll,
    inverse_dynamics_loss,
    multistep_rollout_loss,
    normalize_angle,
    sigreg,
    sigreg_theoretical_expectation,
    soft_cross_entropy,
)

__all__: tuple[str, ...] = (
    "RolloutResult",
    "aggregate_macro",
    "aggregate_macro_sequence",
    "aggregate_macro_window",
    "continuous_gaussian_nll",
    "inverse_dynamics_loss",
    "multistep_rollout_loss",
    "normalize_angle",
    "sigreg",
    "sigreg_theoretical_expectation",
    "soft_cross_entropy",
)
