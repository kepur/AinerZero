"""CPU test double for :class:`~ainerzero.v9.interfaces.GeometryCore`.

Self-contained SE(2) math (translation-first tangent ``[x, y, theta]``), written
independently of ``ainerzero.v9.geometry`` and cross-checked against it by
``tests/v9/contracts/test_geometry_contract.py`` (G1 is read-only there):

- ``T = [[R, t], [0, 1]]`` maps body coordinates into the world frame
  (``p' = R p + t``), so ``T_AC = T_AB @ T_BC`` (r5 §4);
- the adjoint is ``Ad(T) = [[R, (t_y, -t_x)], [0, 1]]``, verified against the
  defining relation ``T Exp(xi) T^-1 = Exp(Ad(T) xi)``;
- ``predict`` uses ``F = Ad(U^-1)`` on the right perturbation and adds the
  registered process-covariance *rate* ``Q = q_rate * dt``;
- 3-D points are handled through the gravity-aligned lift (the fake registers
  ``gravity = (0, 0, -1)``, so the lift keeps the vertical component: the SE(2)
  pose acts on ``xy`` and leaves ``z`` untouched).  Any other gravity direction
  is a job for the real GeometryCore, not for this double.

Pure CPU: numpy only, no model, no I/O, no side effect.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

import numpy as np

from ..interfaces.errors import ContractViolation, SingularMeasurementNoise, UnsupportedInput
from ..interfaces.geometry_core import GeometryCore
from ..interfaces.types import MapCoordinates, PoseBelief, Vectors

__all__ = ["FakeGeometryCore", "GRAVITY"]

GROUP = "SE2"
DOF = 3
GRAVITY = np.array([0.0, 0.0, -1.0])
GRAVITY.setflags(write=False)
_J = np.array([[0.0, -1.0], [1.0, 0.0]])
_ORTHO_TOL = 1e-9


def _abc(w: float) -> tuple[float, float]:
    """``(sin w / w, (1 - cos w) / w^2)`` with a stable small-angle expansion."""
    if abs(w) < 1e-8:
        return 1.0 - w * w / 6.0, 0.5 - w * w / 24.0
    return math.sin(w) / w, (1.0 - math.cos(w)) / (w * w)


def algebra_adjoint(xi: Any) -> np.ndarray:
    """``ad_xi`` of se(2) for ``xi = [x, y, theta]`` (translation first)."""
    vector = np.asarray(xi, dtype=float)
    if vector.shape != (DOF,):
        raise UnsupportedInput(f"a tangent vector must have shape ({DOF},), got {vector.shape}")
    x, y, w = vector
    return np.array([[0.0, -w, y], [w, 0.0, -x], [0.0, 0.0, 0.0]])


def tangent_jacobian(xi: Any, *, side: str = "right") -> np.ndarray:
    """dexp (reset) Jacobian by the convergent series on the principal domain."""
    ad = algebra_adjoint(xi) * (-1.0 if side == "right" else 1.0)
    if abs(float(np.asarray(xi, dtype=float)[2])) > math.pi + 1e-10:
        raise ContractViolation("reset Jacobian restricted to the principal rotation domain")
    out = np.eye(DOF)
    term = np.eye(DOF)
    for n in range(1, 64):
        term = term @ ad / (n + 1)
        out = out + term
        if np.linalg.norm(term, ord=np.inf) < 1e-16:
            break
    return out


def _as_matrix(value: Any, name: str) -> np.ndarray:
    matrix = np.array(value, dtype=float, copy=True)
    if matrix.shape != (3, 3):
        raise UnsupportedInput(f"{name} must have shape (3, 3) for SE(2), got {matrix.shape}")
    if not np.isfinite(matrix).all():
        raise UnsupportedInput(f"{name} must be finite")
    if not np.allclose(matrix[2], [0.0, 0.0, 1.0], atol=1e-12):
        raise UnsupportedInput(f"{name} must have last row [0, 0, 1]")
    rotation = matrix[:2, :2]
    if not np.allclose(rotation.T @ rotation, np.eye(2), atol=_ORTHO_TOL) or not math.isclose(
        float(np.linalg.det(rotation)), 1.0, abs_tol=_ORTHO_TOL
    ):
        raise UnsupportedInput(f"{name} rotation block must be a proper rotation")
    return matrix


def _as_vector(value: Any, name: str) -> np.ndarray:
    vector = np.array(value, dtype=float, copy=True)
    if vector.shape != (DOF,):
        raise UnsupportedInput(f"{name} must have shape ({DOF},), got {vector.shape}")
    if not np.isfinite(vector).all():
        raise UnsupportedInput(f"{name} must be finite")
    return vector


def _covariance(value: Any, name: str, *, strictly: bool) -> np.ndarray:
    matrix = np.array(value, dtype=float, copy=True)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or not np.isfinite(matrix).all():
        raise UnsupportedInput(f"{name} must be a finite square matrix")
    matrix = (matrix + matrix.T) / 2.0
    smallest = float(np.linalg.eigvalsh(matrix)[0])
    if strictly and smallest <= 0.0:
        raise SingularMeasurementNoise(f"{name} must be positive definite (min eig={smallest!r})")
    if not strictly and smallest < -1e-12 * max(1.0, float(np.linalg.norm(matrix, 2))):
        raise UnsupportedInput(f"{name} must be positive semidefinite (min eig={smallest!r})")
    return matrix


def _rotation3(pose: np.ndarray) -> np.ndarray:
    """Gravity-aligned lift of the SE(2) rotation block (gravity is ``-z``)."""
    rotation = np.eye(3)
    rotation[:2, :2] = pose[:2, :2]
    return rotation


class FakeGeometryCore(GeometryCore):
    """Analytic CPU double: SE(2) only, explicit gravity, right-perturbation beliefs."""

    supported_groups = (GROUP,)

    def __init__(self, process_covariance_rate: Any | None = None) -> None:
        """``Q = process_covariance_rate * dt`` inside :meth:`predict` (PSD, frozen)."""
        if process_covariance_rate is None:
            rate = np.zeros((DOF, DOF))
        else:
            rate = _covariance(process_covariance_rate, "process_covariance_rate", strictly=False)
        rate.setflags(write=False)
        self._q_rate = rate

    @property
    def gravity(self) -> np.ndarray:
        return GRAVITY

    @property
    def process_covariance_rate(self) -> np.ndarray:
        return self._q_rate

    def supported(self) -> tuple:
        return (GROUP,)

    # ---- group operations ------------------------------------------------- #

    def compose(self, a: Any, b: Any) -> np.ndarray:
        return _as_matrix(a, "compose(a)") @ _as_matrix(b, "compose(b)")

    def inverse(self, g: Any) -> np.ndarray:
        transform = _as_matrix(g, "inverse(g)")
        rotation = transform[:2, :2].T
        out = np.eye(3)
        out[:2, :2] = rotation
        out[:2, 2] = -(rotation @ transform[:2, 2])
        return out

    def exp(self, xi: Any) -> np.ndarray:
        vector = _as_vector(xi, "exp(xi)")
        rho, w = vector[:2], float(vector[2])
        a, b = _abc(w)
        out = np.eye(3)
        out[:2, :2] = [[math.cos(w), -math.sin(w)], [math.sin(w), math.cos(w)]]
        out[:2, 2] = (a * np.eye(2) + b * w * _J) @ rho
        return out

    def log(self, g: Any) -> np.ndarray:
        transform = _as_matrix(g, "log(g)")
        w = math.atan2(transform[1, 0], transform[0, 0])
        if w <= -math.pi:  # principal value in (-pi, pi]
            w = math.pi
        a, b = _abc(w)
        system = np.array([[a, -b * w], [b * w, a]])
        return np.r_[np.linalg.solve(system, transform[:2, 2]), w]

    def adjoint(self, g: Any) -> np.ndarray:
        transform = _as_matrix(g, "adjoint(g)")
        out = np.eye(3)
        out[:2, :2] = transform[:2, :2]
        out[:2, 2] = [transform[1, 2], -transform[0, 2]]
        return out

    def act(self, pose: Any, x: Any) -> Any:
        """Rigid action on tagged points / object vectors / map coordinates."""
        self.require_supported_input(x, origin="act")
        transform = _as_matrix(pose, "act(pose)")
        values = np.asarray(x, dtype=float)
        rotated_only = isinstance(x, Vectors)
        if values.shape[-1] == 3:
            # gravity-aligned lift: SE(2) acts on xy, the vertical component is kept
            if not np.allclose(GRAVITY, [0.0, 0.0, -1.0]):  # pragma: no cover - fake registers -z
                raise ContractViolation("this double only supports gravity=(0, 0, -1)")
            result = values @ _rotation3(transform).T
            if not rotated_only:
                result = result + np.array([transform[0, 2], transform[1, 2], 0.0])
        elif rotated_only:
            result = values @ transform[:2, :2].T
        else:
            result = values @ transform[:2, :2].T + transform[:2, 2]
        return self._retag(x, result)

    # ---- belief algebra --------------------------------------------------- #

    def predict(self, belief: PoseBelief, motion: Any, dt: float) -> PoseBelief:
        """``mu' = mu Exp(u dt)``, ``Sigma' = F Sigma F^T + Q dt``, ``F = Ad(U^-1)``."""
        self.require_belief(belief, group=GROUP, side="right")
        if isinstance(dt, bool) or not isinstance(dt, (int, float)) or not math.isfinite(float(dt)):
            raise UnsupportedInput(f"dt must be a finite number, got {dt!r}")
        if float(dt) < 0:
            raise UnsupportedInput(f"dt must be nonnegative, got {dt!r}")
        velocity = _as_vector(motion, "predict(motion)")
        transform = self.exp(velocity * float(dt))
        mean = self.compose(belief.mean, transform)
        f = self.adjoint(self.inverse(transform))
        p = f @ belief.covariance @ f.T + self._q_rate * float(dt)
        return PoseBelief(
            group=belief.group,
            mean=mean,
            covariance=(p + p.T) / 2.0,
            gravity=belief.gravity,
            unobservable_dof=belief.unobservable_dof,
            side="right",
            anchor=belief.anchor,
        )

    def update(self, belief: PoseBelief, obs: Any, model: Mapping) -> PoseBelief:
        """Joseph-form tangent update; ``model`` must declare ``H`` and ``R``.

        A singular (e.g. exactly zero) measurement noise is refused instead of
        being silently regularised (rejection contract C1, r5 §4.7).
        """
        self.require_belief(belief, group=GROUP, side="right")
        if not isinstance(model, Mapping) or "H" not in model or "R" not in model:
            raise ContractViolation("update(model) must declare both 'H' and 'R'")
        h = np.array(model["H"], dtype=float, copy=True)
        if h.ndim != 2 or h.shape[1] != DOF or not np.isfinite(h).all():
            raise UnsupportedInput(f"model['H'] must be a finite (m, {DOF}) matrix")
        noise = _covariance(model["R"], "model['R']", strictly=True)
        if noise.shape[0] != h.shape[0]:
            raise UnsupportedInput("model['R'] must be (m, m) matching H rows")
        innovation = np.array(obs, dtype=float, copy=True)
        if innovation.shape != (h.shape[0],) or not np.isfinite(innovation).all():
            raise UnsupportedInput(f"obs must be a finite vector of length {h.shape[0]}")
        p = belief.covariance
        s = h @ p @ h.T + noise
        gain = np.linalg.solve(s, h @ p).T
        correction = gain @ innovation
        mean = self.compose(belief.mean, self.exp(correction))
        a = np.eye(DOF) - gain @ h
        joseph = a @ p @ a.T + gain @ noise @ gain.T
        reset = tangent_jacobian(correction, side="right")
        covariance = reset @ joseph @ reset.T
        return PoseBelief(
            group=belief.group,
            mean=mean,
            covariance=(covariance + covariance.T) / 2.0,
            gravity=belief.gravity,
            unobservable_dof=belief.unobservable_dof,
            side="right",
            anchor=belief.anchor,
        )

    def with_side(self, belief: PoseBelief, side: str) -> PoseBelief:
        """Rewrite the tangent frame: ``P_l = Ad(mu) P_r Ad(mu)^T`` (and back)."""
        self.require_belief(belief, group=GROUP)
        if side not in ("right", "left"):
            raise UnsupportedInput(f"side must be 'right' or 'left', got {side!r}")
        if side == belief.side:
            return belief
        a = self.adjoint(belief.mean)
        if side == "right":
            a = self.inverse(a)
        return PoseBelief(
            group=belief.group,
            mean=belief.mean,
            covariance=a @ belief.covariance @ a.T,
            gravity=belief.gravity,
            unobservable_dof=belief.unobservable_dof,
            side=side,
            anchor=belief.anchor,
        )

    # ---- analytic canonicalisation (式 9) --------------------------------- #

    def canonicalize(self, x: Any, belief: PoseBelief) -> Any:
        """``x_tilde = g(mu)^-1 x`` for tagged points / vectors / map coordinates."""
        self.require_supported_input(x, origin="canonicalize")
        self.require_belief(belief, group=GROUP, side="right")
        values = np.asarray(x, dtype=float)
        if values.shape[-1] == 3:
            result = (values - np.array([belief.mean[0, 2], belief.mean[1, 2], 0.0])) @ _rotation3(
                belief.mean
            )
        elif isinstance(x, Vectors):
            result = values @ belief.mean[:2, :2]
        else:
            result = (values - belief.mean[:2, 2]) @ belief.mean[:2, :2]
        return self._retag(x, result)

    def decanonicalize(self, y: Any, belief: PoseBelief) -> Any:
        """``x = g(mu) x_tilde``; the inverse of :meth:`canonicalize`."""
        self.require_supported_input(y, origin="decanonicalize")
        self.require_belief(belief, group=GROUP, side="right")
        values = np.asarray(y, dtype=float)
        if values.shape[-1] == 3:
            result = values @ _rotation3(belief.mean).T + np.array(
                [belief.mean[0, 2], belief.mean[1, 2], 0.0]
            )
        elif isinstance(y, Vectors):
            result = values @ belief.mean[:2, :2].T
        else:
            result = values @ belief.mean[:2, :2].T + belief.mean[:2, 2]
        return self._retag(y, result)

    @staticmethod
    def _retag(source: Any, values: np.ndarray) -> Any:
        if isinstance(source, MapCoordinates):
            tagged = np.asarray(values).view(MapCoordinates)
            tagged.resolution_m = float(source.resolution_m)
        else:
            tagged = np.asarray(values).view(type(source))
        tagged.setflags(write=False)
        return tagged
