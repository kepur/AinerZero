"""Small dense SE(2)/SE(3) Gauss-Newton reference, CPU only.

Factors measure Z_ij = X_i^-1 X_j, residual Log(Z_ij^-1 X_i^-1 X_j).
An explicit fixed anchor chooses the coordinate gauge; it is not a world-truth
observation. A disconnected/partially observed graph raises ObservabilityError.
This local solver does not promise a global optimum or reject every wrong loop.
"""
from dataclasses import dataclass

import numpy as np

from .belief import covariance
from .lie import boxplus


class ObservabilityError(ValueError):
    """Gauge not fixed, graph disconnected, or remaining directions unobserved."""


@dataclass(frozen=True)
class RelativeFactor:
    i: int
    j: int
    measurement: np.ndarray
    information: np.ndarray


@dataclass(frozen=True)
class PoseGraphResult:
    poses: tuple
    converged: bool
    iterations: int
    residual_norm: float
    rank: int
    free_dimensions: int
    singular_values: np.ndarray
    anchor: int
    gauge: str = "explicit fixed anchor; global coordinates not observed"


def solve_pose_graph(group, initial_poses, factors, *, anchor=None, fixed_rotations=False,
                     max_iterations=30, step_tolerance=1e-10, jacobian_step=1e-6):
    if anchor is None:
        raise ObservabilityError("no anchor: global translation and rotation gauge is unobservable")
    poses = [np.array(group.validate(t), copy=True) for t in initial_poses]
    if len(poses) < 2 or not 0 <= anchor < len(poses):
        raise ValueError("need at least two poses and a valid anchor index")
    if (max_iterations < 1 or not np.isfinite(step_tolerance) or step_tolerance <= 0
            or not np.isfinite(jacobian_step) or jacobian_step <= 0):
        raise ValueError("invalid iteration or numerical settings")
    frozen_anchor = poses[anchor].copy()
    prepared = []
    for f in factors:
        if not (0 <= f.i < len(poses) and 0 <= f.j < len(poses)) or f.i == f.j:
            raise ValueError("invalid factor endpoints")
        z = np.array(group.validate(f.measurement), copy=True)
        info = covariance(f.information, group.dof, semidefinite=True)
        eig, basis = np.linalg.eigh(info)
        root = np.diag(np.sqrt(eig)) @ basis.T
        prepared.append((f.i, f.j, group.inverse(z), root))
    nodes = [i for i in range(len(poses)) if i != anchor]
    coordinates = range(group.dim if fixed_rotations else group.dof)
    columns = [(node, axis) for node in nodes for axis in coordinates]
    if not prepared:
        raise ObservabilityError("no relative measurements")

    def residual(current):
        parts = []
        for i, j, zinv, weight in prepared:
            predicted = group.compose(group.inverse(current[i]), current[j])
            parts.append(weight @ group.log(group.compose(zinv, predicted)))
        return np.concatenate(parts)

    def linearize(current):
        cols = []
        for node, axis in columns:
            direction = np.eye(group.dof)[axis] * jacobian_step
            plus, minus = list(current), list(current)
            plus[node] = boxplus(group, current[node], direction)
            minus[node] = boxplus(group, current[node], -direction)
            cols.append((residual(plus) - residual(minus)) / (2 * jacobian_step))
        jac = np.column_stack(cols)
        singular = np.linalg.svd(jac, compute_uv=False)
        rank = int(np.linalg.matrix_rank(jac))
        if rank != len(columns):
            raise ObservabilityError(f"remaining unobserved directions: rank {rank}/{len(columns)}")
        return jac, rank, singular

    converged = False
    for iteration in range(1, max_iterations + 1):
        r = residual(poses)
        jac, rank, singular = linearize(poses)
        delta = np.linalg.lstsq(jac, -r, rcond=None)[0]
        if np.linalg.norm(delta, ord=np.inf) <= step_tolerance:
            converged = True
            break
        directions = {node: np.zeros(group.dof) for node in nodes}
        for (node, axis), value in zip(columns, delta):
            directions[node][axis] = value
        accepted = False
        # Bounded backtracking protects the local linearization, not a global guarantee.
        for power in range(12):
            trial = list(poses)
            for node in nodes:
                trial[node] = boxplus(group, poses[node], directions[node] * (0.5**power))
            if np.linalg.norm(residual(trial)) < np.linalg.norm(r):
                poses, accepted = trial, True
                break
        if not accepted:
            break
    jac, rank, singular = linearize(poses)
    assert np.array_equal(poses[anchor], frozen_anchor), "anchor must never change"
    return PoseGraphResult(tuple(poses), converged, iteration,
                           float(np.linalg.norm(residual(poses))), rank,
                           len(columns), singular, anchor)


def linear_translation_error_bound(incidence, sqrt_weights, bounded_edge_errors):
    """||error||2 <= ||(sqrt(W) A)^+||2 ||sqrt(W)e||2.

    Reduced incidence A must have full column rank (anchor removed). Applicable
    only to fixed-known-rotation, additive-translation least squares. Each row of
    bounded_edge_errors can be an actual bounded error vector or a scalar bound.
    """
    a = np.asarray(incidence, dtype=float)
    w = np.asarray(sqrt_weights, dtype=float)
    e = np.asarray(bounded_edge_errors, dtype=float)
    if (a.ndim != 2 or w.shape != (len(a),) or e.shape[0] != len(a)
            or not np.isfinite(a).all() or not np.isfinite(w).all()
            or not np.isfinite(e).all() or np.any(w <= 0)):
        raise ValueError("invalid linear translation bound inputs")
    weighted = a * w[:, None]
    if np.linalg.matrix_rank(weighted) != a.shape[1]:
        raise ObservabilityError("linear reference graph is not observable after anchoring")
    weighted_error = e * (w if e.ndim == 1 else w[:, None])
    return float(np.linalg.norm(np.linalg.pinv(weighted), 2) * np.linalg.norm(weighted_error))
