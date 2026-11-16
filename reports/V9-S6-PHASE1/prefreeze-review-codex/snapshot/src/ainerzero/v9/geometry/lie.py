"""Float64 SE(2)/SE(3), translation-first tangent vectors.

T maps body coordinates to world coordinates: p_world = R p_body + t.
SO(2) log uses (-pi, pi]; SO(3) log has norm in [0, pi]. At exactly
pi its axis is ambiguous; the largest absolute axis component is made positive.
Only exp(log(T)) is globally meaningful. log(exp(xi)) is not a global identity.
"""
from __future__ import annotations

import math

import numpy as np


def vector(value, n):
    x = np.asarray(value, dtype=np.float64)
    if x.shape != (n,) or not np.isfinite(x).all():
        raise ValueError(f"expected finite vector of shape {(n,)}")
    return x


def skew(v):
    x, y, z = vector(v, 3)
    return np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=float)


def _abc(theta):
    if abs(theta) < 1e-4:
        t2 = theta * theta
        return (1 - t2 / 6 + t2**2 / 120 - t2**3 / 5040,
                0.5 - t2 / 24 + t2**2 / 720 - t2**3 / 40320,
                1 / 6 - t2 / 120 + t2**2 / 5040 - t2**3 / 362880)
    return (math.sin(theta) / theta,
            2 * math.sin(theta / 2)**2 / theta**2,
            (theta - math.sin(theta)) / theta**3)


class _SE:
    @classmethod
    def validate(cls, value):
        t = np.asarray(value, dtype=np.float64)
        n = cls.dim
        if t.shape != (n + 1, n + 1) or not np.isfinite(t).all():
            raise ValueError("invalid finite homogeneous transform")
        r = t[:n, :n]
        if (not np.allclose(t[n], np.eye(n + 1)[n], atol=1e-10, rtol=0)
                or not np.allclose(r.T @ r, np.eye(n), atol=1e-9, rtol=0)
                or abs(np.linalg.det(r) - 1) > 1e-9):
            raise ValueError("transform must contain a proper rotation and homogeneous last row")
        return t

    @classmethod
    def identity(cls):
        return np.eye(cls.dim + 1)

    @classmethod
    def compose(cls, a, b):
        return cls.validate(cls.validate(a) @ cls.validate(b))

    @classmethod
    def inverse(cls, value):
        t = cls.validate(value)
        n = cls.dim
        out = cls.identity()
        out[:n, :n] = t[:n, :n].T
        out[:n, n] = -out[:n, :n] @ t[:n, n]
        return out

    @classmethod
    def act(cls, value, points, *, vectors=False):
        """Known Euclidean point/vector action only; not an image warp."""
        t = cls.validate(value)
        p = np.asarray(points, dtype=float)
        if p.ndim not in (1, 2) or p.shape[-1] != cls.dim or not np.isfinite(p).all():
            raise ValueError("finite points must have trailing spatial dimension")
        return p @ t[:cls.dim, :cls.dim].T + (0 if vectors else t[:cls.dim, cls.dim])


class SE2(_SE):
    dim, dof = 2, 3

    @staticmethod
    def exp(xi):
        x = vector(xi, 3)
        rho, w = x[:2], float(x[2])
        a, b, _ = _abc(w)
        j = np.array([[0., -1.], [1., 0.]])
        out = np.eye(3)
        out[:2, :2] = [[math.cos(w), -math.sin(w)], [math.sin(w), math.cos(w)]]
        out[:2, 2] = (a * np.eye(2) + b * w * j) @ rho
        return SE2.validate(out)

    @staticmethod
    def log(value):
        t = SE2.validate(value)
        w = math.atan2(t[1, 0], t[0, 0])
        if w <= -math.pi:
            w = math.pi
        a, b, _ = _abc(w)
        v = np.array([[a, -b * w], [b * w, a]])
        return np.r_[np.linalg.solve(v, t[:2, 2]), w]

    @staticmethod
    def adjoint(value):
        t = SE2.validate(value)
        out = np.eye(3)
        out[:2, :2] = t[:2, :2]
        out[:2, 2] = [t[1, 2], -t[0, 2]]
        return out

    @staticmethod
    def algebra_adjoint(xi):
        x, y, w = vector(xi, 3)
        return np.array([[0., -w, y], [w, 0., -x], [0., 0., 0.]])


class SE3(_SE):
    dim, dof = 3, 6

    @staticmethod
    def exp(xi):
        x = vector(xi, 6)
        phi = x[3:]
        theta = float(np.linalg.norm(phi))
        if not math.isfinite(theta):
            raise ValueError("rotation magnitude overflow")
        a, b, c = _abc(theta)
        k = skew(phi)
        k2 = k @ k
        out = np.eye(4)
        out[:3, :3] = np.eye(3) + a * k + b * k2
        out[:3, 3] = (np.eye(3) + b * k + c * k2) @ x[:3]
        return SE3.validate(out)

    @staticmethod
    def log(value):
        t = SE3.validate(value)
        r = t[:3, :3]
        anti = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]]) / 2
        sine = float(np.linalg.norm(anti))
        cosine = float(np.clip((np.trace(r) - 1) / 2, -1, 1))
        theta = math.atan2(sine, cosine)
        if theta < 1e-7:
            phi = anti * (1 + theta**2 / 6 + 7 * theta**4 / 360)
        elif math.pi - theta < 1e-5:
            # Symmetric part has the rotation axis as the eigenvector at eigenvalue 1.
            _, eigenvectors = np.linalg.eigh((r + r.T) / 2)
            axis = eigenvectors[:, -1]
            if sine > 1e-13:
                if axis @ anti < 0:
                    axis = -axis
            elif axis[np.argmax(np.abs(axis))] < 0:
                axis = -axis
            phi = theta * axis
        else:
            phi = theta / sine * anti
        _, b, c = _abc(theta)
        k = skew(phi)
        v = np.eye(3) + b * k + c * (k @ k)
        return np.r_[np.linalg.solve(v, t[:3, 3]), phi]

    @staticmethod
    def adjoint(value):
        t = SE3.validate(value)
        r = t[:3, :3]
        out = np.zeros((6, 6))
        out[:3, :3] = out[3:, 3:] = r
        out[:3, 3:] = skew(t[:3, 3]) @ r
        return out

    @staticmethod
    def algebra_adjoint(xi):
        x = vector(xi, 6)
        out = np.zeros((6, 6))
        out[:3, :3] = out[3:, 3:] = skew(x[3:])
        out[:3, 3:] = skew(x[:3])
        return out


def boxplus(group, mean, delta, *, side="right"):
    if side == "right":
        return group.compose(mean, group.exp(delta))
    if side == "left":
        return group.compose(group.exp(delta), mean)
    raise ValueError("side must be left or right")


def boxminus(group, value, mean, *, side="right"):
    if side == "right":
        return group.log(group.compose(group.inverse(mean), value))
    if side == "left":
        return group.log(group.compose(value, group.inverse(mean)))
    raise ValueError("side must be left or right")


def tangent_jacobian(group, xi, *, side="right"):
    """d Log(Exp(-xi) Exp(xi+d)) / d(d), or its left version.

    The convergent dexp series is used on the principal rotation domain.
    This is a local Gaussian reset, not exact finite-noise moment propagation.
    """
    if side not in ("left", "right"):
        raise ValueError("side must be left or right")
    ad = group.algebra_adjoint(xi) * (-1 if side == "right" else 1)
    if np.linalg.norm(np.asarray(xi)[group.dim:]) > math.pi + 1e-10:
        raise ValueError("reset Jacobian restricted to principal rotation domain")
    out, term = np.eye(group.dof), np.eye(group.dof)
    for n in range(1, 64):
        term = term @ ad / (n + 1)
        out += term
        if np.linalg.norm(term, ord=np.inf) < 1e-16:
            break
    return out
