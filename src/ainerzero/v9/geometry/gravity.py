"""Gravity-aligned SE(2) x height, with explicit frame convention.

No full SO(3) invariance is asserted for gravity-bound objects. No image
canonicalization is implemented here (that belongs to task G3).
"""
from dataclasses import dataclass

import numpy as np

from .lie import SE2, SE3, vector


@dataclass(frozen=True)
class GravityFrame:
    gravity: np.ndarray
    up: np.ndarray
    horizontal_reference: np.ndarray

    def __post_init__(self):
        g, u, h = (vector(x, 3).copy() for x in (self.gravity, self.up, self.horizontal_reference))
        if np.linalg.norm(g) == 0 or np.linalg.norm(u) == 0:
            raise ValueError("gravity and up must be nonzero")
        u /= np.linalg.norm(u)
        if not np.allclose(g / np.linalg.norm(g), -u, atol=1e-10, rtol=0):
            raise ValueError("gravity must point opposite the declared up direction")
        x = h - u * (u @ h)
        if np.linalg.norm(x) < 1e-12:
            raise ValueError("horizontal reference must not be parallel to gravity")
        x /= np.linalg.norm(x)
        basis = np.column_stack((x, np.cross(u, x), u))
        for name, value in [("gravity", g), ("up", u), ("horizontal_reference", h), ("basis", basis)]:
            value.setflags(write=False)
            object.__setattr__(self, name, value)

    def lift(self, planar_pose, height):
        p = SE2.validate(planar_pose)
        if not np.isfinite(height):
            raise ValueError("height must be finite")
        local = np.eye(3)
        local[:2, :2] = p[:2, :2]
        t = np.eye(4)
        t[:3, :3] = self.basis @ local @ self.basis.T
        t[:3, 3] = self.basis @ np.r_[p[:2, 2], height]
        return SE3.validate(t)

    def project(self, pose):
        t = SE3.validate(pose)
        r = self.basis.T @ t[:3, :3] @ self.basis
        if not np.allclose(r[2], [0, 0, 1], atol=1e-9, rtol=0):
            raise ValueError("pose is not gravity-aligned: roll/pitch is outside SE2 x height")
        p = np.eye(3)
        p[:2, :2] = r[:2, :2]
        xyz = self.basis.T @ t[:3, 3]
        p[:2, 2] = xyz[:2]
        return SE2.validate(p), float(xyz[2])
