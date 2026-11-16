"""``GeometryCore`` interface (ARCHITECTURE_V9 r5 §3, §4 约定段).

Conventions are **not** re-defined here; they are the G1 contract
(``src/ainerzero/v9/geometry/belief.py`` and its README):

- ``T_AB`` maps coordinates of frame B into frame A, so ``p_A = T_AB @ p_B``
  and ``T_AC = T_AB @ T_BC``;
- the perturbation is the **right** one, ``X = mu @ Exp(xi_r)``;
- ``xi_l = Ad(mu) xi_r``, hence ``P_l = Ad(mu) P_r Ad(mu)^T`` (first-order
  moments).  This Adjoint only rewrites the same tangent vector from a right
  error to a left error; under a pure left world-frame change the right error
  and its covariance do not change;
- the canonical pose (first frame or a registered anchor) and every
  unobservable degree of freedom are declared, never estimated.

The real implementation is ainerzero.V9.G1 (group/filter) and ainerzero.V9.G3
(``canonicalize``/``decanonicalize``).  This card owns only the interface and a
CPU test double.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

import numpy as np

from .types import MapCoordinates, Points, PoseBelief, Vectors

__all__ = ["GeometryCore", "CanonicalInput"]

CanonicalInput = (Points, Vectors, MapCoordinates)
"""The only three input families ``canonicalize`` accepts (r4 §4: 点 / 对象向量 / 地图坐标)."""


class GeometryCore(ABC):
    """Replaceable analytical geometry kernel: no learned parameters, no model."""

    supported_groups: tuple = ()

    @property
    @abstractmethod
    def gravity(self) -> np.ndarray:
        """Explicit gravity direction (3-vector, non-zero); there is no default."""

    @abstractmethod
    def supported(self) -> tuple:
        """Groups this core can evaluate (e.g. ``("SE2",)``); callers must check."""

    # ---- group operations ------------------------------------------------- #

    @abstractmethod
    def compose(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """``T_AC = T_AB @ T_BC``."""

    @abstractmethod
    def inverse(self, g: np.ndarray) -> np.ndarray:
        """Group inverse."""

    @abstractmethod
    def exp(self, xi: np.ndarray) -> np.ndarray:
        """``Exp(xi)`` with ``xi`` in the right tangent space (translation first)."""

    @abstractmethod
    def log(self, g: np.ndarray) -> np.ndarray:
        """Principal-value ``Log(g)``; ``exp(log(g)) == g`` is the contract."""

    @abstractmethod
    def adjoint(self, g: np.ndarray) -> np.ndarray:
        """``Ad(g)`` with ``g Exp(xi) g^-1 = Exp(Ad(g) xi)``."""

    @abstractmethod
    def act(self, pose: np.ndarray, x: Any) -> Any:
        """Group action on tagged points / object vectors / map coordinates."""

    # ---- belief algebra --------------------------------------------------- #

    @abstractmethod
    def predict(self, belief: PoseBelief, motion: np.ndarray, dt: float) -> PoseBelief:
        """``mu' = mu U``, ``Sigma' = F Sigma F^T + Q(dt)`` with ``U = Exp(u dt)``, ``F = Ad(U^-1)``."""

    @abstractmethod
    def update(self, belief: PoseBelief, obs: np.ndarray, model: Mapping) -> PoseBelief:
        """Invariant-style tangent update; ``model`` declares ``H`` and ``R`` explicitly."""

    @abstractmethod
    def with_side(self, belief: PoseBelief, side: str) -> PoseBelief:
        """Rewrite the tangent frame: ``P_l = Ad(mu) P_r Ad(mu)^T`` (and back)."""

    # ---- analytic canonicalisation (式 9) --------------------------------- #

    @abstractmethod
    def canonicalize(self, x: Any, belief: PoseBelief) -> Any:
        """``x_tilde = g(mu_hat)^-1 x`` for points / object vectors / map coordinates."""

    @abstractmethod
    def decanonicalize(self, y: Any, belief: PoseBelief) -> Any:
        """``x = g(mu_hat) x_tilde``; the inverse of :meth:`canonicalize`."""

    # ---- shared validation ------------------------------------------------ #

    @staticmethod
    def require_supported_input(x: Any, *, origin: str) -> None:
        """Fail closed on anything that is not a tagged point/vector/map coordinate."""
        from .errors import UnsupportedInput

        if not isinstance(x, CanonicalInput):
            raise UnsupportedInput(
                f"{origin} only accepts tagged points, object vectors or map coordinates, "
                f"got {type(x).__name__}"
            )

    @staticmethod
    def require_belief(belief: Any, *, group: str | None = None, side: str | None = None) -> PoseBelief:
        """Validate a belief argument; ``side="right"`` rejects left-hand forms.

        Only :meth:`with_side` may rewrite the tangent frame (§4.5), so every other
        GeometryCore entry point must fail closed on a left-hand belief.
        """
        from .errors import UnsupportedInput

        if not isinstance(belief, PoseBelief):
            raise UnsupportedInput(f"belief must be a PoseBelief, got {type(belief).__name__}")
        if group is not None and belief.group != group:
            raise UnsupportedInput(f"belief group {belief.group!r} is not supported here ({group!r})")
        if side is not None and belief.side != side:
            raise UnsupportedInput(
                f"expected side={side!r}, got {belief.side!r}; a left-hand belief must be "
                "produced by with_side() only"
            )
        return belief
