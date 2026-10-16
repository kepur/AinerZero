"""Local invariant-error Gaussian prediction/update, without learned models.

Right error: X=mu Exp(xi_r); left error: X=Exp(xi_l) mu.
xi_l = Ad(mu) xi_r, so P_l = Ad(mu) P_r Ad(mu)^T (first-order moments).
Body motion prediction uses mu'=mu U; F_r=Ad(U^-1), F_l=I.
Noise Q is declared in the post-prediction right tangent frame.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .lie import SE2, SE3, boxplus, skew, tangent_jacobian, vector


def covariance(value, n, *, semidefinite=False):
    p = np.array(value, dtype=float, copy=True)
    if p.shape != (n, n) or not np.isfinite(p).all():
        raise ValueError("invalid finite covariance shape")
    if not np.allclose(p, p.T, atol=1e-12, rtol=0):
        raise ValueError("covariance must be symmetric")
    p = (p + p.T) / 2
    smallest = np.linalg.eigvalsh(p)[0]
    if (smallest < 0 if semidefinite else smallest <= 0):
        raise ValueError("covariance must be positive semidefinite" if semidefinite else "covariance must be positive definite")
    return p


@dataclass(frozen=True)
class TangentGaussian:
    group: type
    mean: np.ndarray
    covariance: np.ndarray
    side: str = "right"

    def __post_init__(self):
        if self.group not in (SE2, SE3) or self.side not in ("left", "right"):
            raise ValueError("unsupported group or tangent side")
        m = np.array(self.group.validate(self.mean), copy=True)
        p = covariance(self.covariance, self.group.dof)
        m.setflags(write=False)
        p.setflags(write=False)
        object.__setattr__(self, "mean", m)
        object.__setattr__(self, "covariance", p)

    def with_side(self, side):
        if side == self.side:
            return self
        if side not in ("left", "right"):
            raise ValueError("unknown tangent side")
        a = self.group.adjoint(self.mean)
        if side == "right":
            a = np.linalg.inv(a)
        return TangentGaussian(self.group, self.mean, a @ self.covariance @ a.T, side)

    def predict(self, body_velocity, dt, process_covariance_rate):
        if not np.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        g = self.group
        velocity = vector(body_velocity, g.dof)
        q = covariance(process_covariance_rate, g.dof, semidefinite=True) * dt
        delta = velocity * dt
        if not np.isfinite(delta).all() or not np.isfinite(q).all():
            raise ValueError("motion or covariance overflow")
        u = g.exp(delta)
        mean = g.compose(self.mean, u)
        f = g.adjoint(g.inverse(u)) if self.side == "right" else np.eye(g.dof)
        if self.side == "left":
            a = g.adjoint(mean)
            q = a @ q @ a.T
        p = f @ self.covariance @ f.T + q
        return TangentGaussian(g, mean, (p + p.T) / 2, self.side)

    def update_tangent(self, innovation, h, observation_covariance, *, side):
        """Local linearized measurement r=H xi + noise in explicitly named tangent.

        Caller supplies the observation model/Jacobian; the Joseph covariance
        update and dexp reset are local first-order approximations on the group.
        """
        if side != self.side:
            raise ValueError("observation and belief tangent conventions differ")
        h = np.asarray(h, dtype=float)
        if h.ndim != 2 or h.shape[1] != self.group.dof or not np.isfinite(h).all():
            raise ValueError("invalid observation Jacobian")
        r = vector(innovation, h.shape[0])
        noise = covariance(observation_covariance, len(r))
        p = self.covariance
        s = h @ p @ h.T + noise
        gain = np.linalg.solve(s, h @ p).T
        correction = gain @ r
        mean = boxplus(self.group, self.mean, correction, side=self.side)
        a = np.eye(self.group.dof) - gain @ h
        joseph = a @ p @ a.T + gain @ noise @ gain.T
        reset = tangent_jacobian(self.group, correction, side=self.side)
        cov = reset @ joseph @ reset.T
        return TangentGaussian(self.group, mean, (cov + cov.T) / 2, self.side), gain

    def update_position(self, observed_world_position, world_covariance):
        """Position sensor with explicit world-coordinate measurement model.

        This sensor is authorized only for analytic references or a task whose
        observation contract permits it; it is not a visual-pose estimator.
        """
        g = self.group
        n = g.dim
        z = vector(observed_world_position, n)
        rworld = covariance(world_covariance, n)
        rot, pos = self.mean[:n, :n], self.mean[:n, n]
        h = np.zeros((n, g.dof))
        if self.side == "right":
            h[:, :n] = np.eye(n)
            innovation = rot.T @ (z - pos)
            noise = rot.T @ rworld @ rot
        else:
            h[:, :n] = np.eye(n)
            h[:, n:] = -skew(pos) if n == 3 else np.array([[-pos[1]], [pos[0]]])
            innovation, noise = z - pos, rworld
        return self.update_tangent(innovation, h, noise, side=self.side)


def bounded_translation_update(previous_bound, odometry_error_bound, observation_error_bound, gain):
    """Exact norm bound ONLY for fixed-rotation additive-translation subproblem."""
    values = np.asarray([previous_bound, odometry_error_bound, observation_error_bound])
    if not np.isfinite(values).all() or np.any(values < 0):
        raise ValueError("error bounds must be finite and nonnegative")
    k = np.asarray(gain, dtype=float)
    if k.ndim != 2 or k.shape[0] != k.shape[1] or not np.isfinite(k).all():
        raise ValueError("gain must be a finite square translation gain")
    predicted = previous_bound + odometry_error_bound
    updated = np.linalg.norm(np.eye(len(k)) - k, 2) * predicted + np.linalg.norm(k, 2) * observation_error_bound
    return float(predicted), float(updated)


@dataclass(frozen=True)
class KnownRotationGaussian:
    """Exact linear-Gaussian reference conditional on a fixed, known rotation.

    Only translation is random. This is deliberately not a full-rank SE(n)
    Gaussian with a tiny but nonzero orientation variance. That would violate
    the commuting-translation premise behind the deterministic error bound.
    """
    group: type
    mean: np.ndarray
    translation_covariance: np.ndarray

    def __post_init__(self):
        if self.group not in (SE2, SE3):
            raise ValueError("unsupported group")
        mean = np.array(self.group.validate(self.mean), copy=True)
        p = covariance(self.translation_covariance, self.group.dim)
        mean.setflags(write=False)
        p.setflags(write=False)
        object.__setattr__(self, "mean", mean)
        object.__setattr__(self, "translation_covariance", p)

    def predict(self, world_velocity, dt, process_covariance_rate):
        if not np.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite and nonnegative")
        n = self.group.dim
        velocity = vector(world_velocity, n)
        q = covariance(process_covariance_rate, n, semidefinite=True)
        mean = np.array(self.mean, copy=True)
        mean[:n, n] += velocity * dt
        return KnownRotationGaussian(self.group, mean, self.translation_covariance + dt * q)

    def update_position(self, measurement, measurement_covariance):
        n = self.group.dim
        z = vector(measurement, n)
        r = covariance(measurement_covariance, n)
        p = self.translation_covariance
        gain = np.linalg.solve(p + r, p).T
        mean = np.array(self.mean, copy=True)
        mean[:n, n] += gain @ (z - mean[:n, n])
        a = np.eye(n) - gain
        updated = a @ p @ a.T + gain @ r @ gain.T
        return KnownRotationGaussian(self.group, mean, (updated + updated.T) / 2), gain
