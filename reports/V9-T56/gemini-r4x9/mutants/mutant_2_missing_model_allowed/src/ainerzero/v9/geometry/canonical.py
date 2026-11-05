"""G3 analytic canonicalization: gravity-aligned SE(2) agent frame, NumPy only.

This module implements ARCHITECTURE_V9 r5 section 4 equation 9::

    x_tilde = g(mu_hat)^-1 . x          (canonicalize)
    y       = g(mu_hat) . f(x_tilde)    (decanonicalize, wrapper form)

Conventions are inherited from G1 and are not redefined here:

- ``T_AB`` maps coordinates in frame B to frame A: ``p_A = T_AB p_B`` and
  ``T_AC = T_AB T_BC``.  ``T_AB`` is *not* an image warp.
- Right perturbation ``X = mu Exp(xi_r)``; left ``X = Exp(xi_l) mu``.  This
  module's first-order error propagation is defined for the right form only.
- Only the gravity-aligned part ``g(mu_hat) in SE(2)`` of an estimated pose is
  used.  Height and the gravity/up direction are preserved verbatim: there is
  no full SE(3) normalization, no roll/pitch change and no image/RGB warp.

The canonical lift is ``L(mu_hat) = frame.lift(g(mu_hat), 0) in SE(3)``: yaw
rotation plus a horizontal translation, with a *zero* vertical translation.
Hence ``L^-1`` leaves the component along the declared up axis untouched.

Strict SE(2) equivariance (section 4 equation 9) holds only for inputs that
have a defined SE(2) group action and only when the estimator is consistent,
``mu_hat(g . o) = g . mu_hat(o)``; the tests check exactly that precondition
with the left action ``g . x = frame.lift(g, 0) x``.  Supported inputs are
points/map coordinates, direction/velocity vectors, world SE(3) poses and
planar metric grids; raw RGB/images are explicitly out of scope.  Grid
resampling is bilinear with clamped boundary indices and a fill value outside
the source index rectangle, and returns a validity mask, so the equivariance
error can be reported separately for interpolation, boundary, numerical and
data-association sources (this operator performs no association).

Known limits, stated rather than hidden:

- The covariance propagation helpers are first-order (small-noise) results;
  they are not a deterministic full-path bound for unbounded Gaussian noise.
- Grid round trips are only approximate: the intermediate grid is piecewise
  bilinear (C0), so no universal analytic bound is claimed for arbitrary
  fields.  Tests register a field-specific bound plus a convergence order.
- Bias/scale of a real pose estimator is out of scope.  This module only turns
  an estimate into a canonical representation; it does not estimate poses.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .belief import TangentGaussian
from .gravity import GravityFrame
from .lie import SE2, SE3, boxplus, vector

__all__ = [
    "CanonicalBelief",
    "PlanarGrid",
    "WorldPoints",
    "WorldVectors",
    "apply_pose_error",
    "canonical_frame",
    "canonical_lift",
    "canonicalize",
    "canonicalize_grid",
    "canonicalize_points",
    "canonicalize_poses",
    "canonicalize_vectors",
    "decanonicalize",
    "decanonicalize_grid",
    "decanonicalize_points",
    "decanonicalize_poses",
    "decanonicalize_vectors",
    "inject_pose_error",
    "predicted_point_error_covariance",
    "predicted_vector_error_covariance",
    "sample_pose_errors",
]

# Tangent coordinates (translation first) that keep a gravity-aligned pose
# inside the SE(2) x height subgroup under a left or right perturbation:
# any translation plus yaw, no roll/pitch.  See ``sample_pose_errors``.
_GRAVITY_ALIGNED_TANGENT_INDICES = {SE2: (0, 1, 2), SE3: (0, 1, 2, 5)}


class WorldPoints(np.ndarray):
    """Tag: Euclidean points / map coordinates (SE(2) translation action).

    The tag distinguishes the point action from the rotation-only vector action
    for the generic ``canonicalize``/``decanonicalize`` dispatchers and is carried
    through canonical/world frames so a round trip stays well typed.
    """

    def __new__(cls, value):
        return np.array(value, dtype=np.float64, copy=True).view(cls)


class WorldVectors(np.ndarray):
    """Tag: direction / velocity vectors (SE(2) rotation-only action).

    Carried through canonical/world frames like ``WorldPoints`` so that the
    generic round trip applies the rotation without a translation.
    """

    def __new__(cls, value):
        return np.array(value, dtype=np.float64, copy=True).view(cls)


@dataclass(frozen=True)
class CanonicalBelief:
    """Estimated pose plus the explicit gravity frame used to canonicalize.

    ``belief`` must be a G1 ``TangentGaussian`` in SE(2) or SE(3).  For SE(3)
    the mean has to be exactly gravity aligned (no roll/pitch), which keeps the
    estimate inside the ``SE(2) x height`` subgroup declared by the architecture;
    ``GravityFrame.project`` enforces this and raises otherwise.

    The covariance belongs to the G1 tangent side (``belief.side``, default
    right).  Either side is supported; the first-order propagation helpers are
    defined for the right side only.
    """

    belief: TangentGaussian
    frame: GravityFrame

    def __post_init__(self):
        if not isinstance(self.belief, TangentGaussian):
            raise TypeError("belief must be a G1 TangentGaussian")
        if not isinstance(self.frame, GravityFrame):
            raise TypeError("frame must be a G1 GravityFrame")
        if self.belief.group not in (SE2, SE3):
            raise ValueError("canonicalization supports SE(2) or SE(3) beliefs")
        if self.belief.group is SE3:
            # Contract check: reject roll/pitch instead of silently projecting.
            self.frame.project(self.belief.mean)

    @property
    def group(self):
        return self.belief.group

    @property
    def side(self):
        return self.belief.side

    def planar(self):
        """Return ``g(mu_hat) in SE(2)``: yaw + horizontal translation only."""
        if self.belief.group is SE2:
            return np.array(self.belief.mean, copy=True)
        planar, _height = self.frame.project(self.belief.mean)
        return planar

    def lift(self):
        """Return ``L = frame.lift(g(mu_hat), 0) in SE(3)`` (zero vertical shift)."""
        return self.frame.lift(self.planar(), 0.0)

    def with_perturbation(self, xi):
        """Perturb the mean by a tangent vector on ``belief.side``; keep Sigma."""
        delta = vector(xi, self.belief.group.dof)
        mean = boxplus(self.belief.group, self.belief.mean, delta, side=self.belief.side)
        belief = TangentGaussian(
            self.belief.group, mean, self.belief.covariance, self.belief.side
        )
        return CanonicalBelief(belief, self.frame)

    def left_compose(self, planar_pose):
        """Return the world-frame left action ``g . belief`` used by equation 9.

        Points move as ``p -> frame.lift(g, 0) p`` and the mean moves the same
        way; a right-error covariance is unchanged by a pure left world-frame
        coordinate change (ARCHITECTURE_V9 section 4 conventions).
        """
        g = SE2.validate(np.asarray(planar_pose, dtype=np.float64))
        if self.belief.group is SE2:
            mean = SE2.compose(g, self.belief.mean)
        else:
            mean = SE3.compose(self.frame.lift(g, 0.0), self.belief.mean)
        belief = TangentGaussian(
            self.belief.group, mean, self.belief.covariance, self.belief.side
        )
        return CanonicalBelief(belief, self.frame)


def _require_belief(belief):
    if not isinstance(belief, CanonicalBelief):
        raise TypeError("belief must be a CanonicalBelief")
    return belief


def canonical_frame(belief):
    """``g(mu_hat) in SE(2)``: canonical (agent-centered, gravity-aligned) frame."""
    return _require_belief(belief).planar()


def canonical_lift(belief):
    """``L(mu_hat) = frame.lift(g(mu_hat), 0) in SE(3)``: world <- canonical."""
    return _require_belief(belief).lift()


def _action(belief):
    """``L^-1``: world -> canonical.  Single point of failure for mutation tests."""
    return SE3.inverse(canonical_lift(belief))


def _relative_planar(source_frame, target_frame):
    """``source^-1 target``: maps target-frame planar coordinates to source frame.

    Used by the grid resampler; corpus of the "grid rotation direction" mutation.
    """
    return SE2.compose(SE2.inverse(source_frame), target_frame)


def _point_array(value, name="points"):
    a = np.asarray(value, dtype=np.float64)
    if a.ndim == 1:
        if a.shape[0] not in (2, 3):
            raise ValueError(f"{name} must have a trailing dimension 2 or 3")
        return a.reshape(1, -1), True
    if a.ndim == 2:
        if a.shape[1] not in (2, 3):
            raise ValueError(f"{name} must have a trailing dimension 2 or 3")
        return a, False
    raise ValueError(
        f"{name}: expected (d,) or (n, d) with d in (2, 3); image/RGB inputs are out of scope"
    )


def _vector_array(value, name="vectors"):
    a, single = _point_array(value, name=name)
    return a, single


def _pose_array(value, name="poses"):
    a = np.asarray(value, dtype=np.float64)
    if a.shape == (4, 4):
        SE3.validate(a)
        return a.reshape(1, 4, 4), True
    if a.ndim == 3 and a.shape[1:] == (4, 4):
        for pose in a:
            SE3.validate(pose)
        return a, False
    raise ValueError(f"{name}: expected a (4, 4) SE(3) pose or an (n, 4, 4) batch")


def _scalar_or_batch(out, single):
    return out[0] if single else out


def canonicalize_points(value, belief):
    """Map world points/map coordinates into the canonical agent frame."""
    b = _require_belief(belief)
    a, single = _point_array(value)
    if a.shape[1] == 2:
        out = SE2.act(SE2.inverse(b.planar()), a)
    else:
        out = SE3.act(_action(b), a)
    return WorldPoints(_scalar_or_batch(out, single))


def decanonicalize_points(value, belief):
    """Map canonical-frame points/map coordinates back to the world frame."""
    b = _require_belief(belief)
    a, single = _point_array(value)
    if a.shape[1] == 2:
        out = SE2.act(b.planar(), a)
    else:
        out = SE3.act(canonical_lift(b), a)
    return _scalar_or_batch(out, single)


def canonicalize_vectors(value, belief):
    """Rotate world direction/velocity vectors into the canonical agent frame."""
    b = _require_belief(belief)
    a, single = _vector_array(value)
    if a.shape[1] == 2:
        out = SE2.act(SE2.inverse(b.planar()), a, vectors=True)
    else:
        out = SE3.act(_action(b), a, vectors=True)
    return WorldVectors(_scalar_or_batch(out, single))


def decanonicalize_vectors(value, belief):
    """Rotate canonical-frame vectors back to the world frame (no translation)."""
    b = _require_belief(belief)
    a, single = _vector_array(value)
    if a.shape[1] == 2:
        out = SE2.act(b.planar(), a, vectors=True)
    else:
        out = SE3.act(canonical_lift(b), a, vectors=True)
    return _scalar_or_batch(out, single)


def canonicalize_poses(value, belief):
    """Re-express world SE(3) poses in the canonical agent frame (``L^-1 T``)."""
    b = _require_belief(belief)
    a, single = _pose_array(value)
    out = np.einsum("ij,njk->nik", _action(b), a)
    return _scalar_or_batch(out, single)


def decanonicalize_poses(value, belief):
    """Re-express canonical-frame SE(3) poses in the world frame (``L T``)."""
    b = _require_belief(belief)
    a, single = _pose_array(value)
    out = np.einsum("ij,njk->nik", canonical_lift(b), a)
    return _scalar_or_batch(out, single)


@dataclass(frozen=True)
class PlanarGrid:
    """Metric grid sampled on a planar lattice expressed in gravity-frame coordinates.

    Cell ``(i, j)`` (row ``i``, column ``j``) covers the square
    ``[j r, (j + 1) r] x [i r, (i + 1) r]`` and its center is
    ``((j + 0.5) r, (i + 0.5) r)`` in the lattice frame.  ``frame`` is the
    SE(2) pose ``T_WG`` mapping lattice coordinates to the gravity-aligned
    planar world coordinates declared by the belief's ``GravityFrame``.
    ``data`` has shape ``(..., rows, cols)`` (leading dimensions are channels).
    ``valid`` marks cells whose value is usable; ``fill`` is used outside the
    source lattice and for invalid cells.  ``source_frame`` records the
    provenance lattice of a canonical grid so ``decanonicalize_grid`` can
    render the field back onto the lattice it came from.
    """

    data: np.ndarray
    resolution: float
    frame: np.ndarray
    fill: float = 0.0
    valid: np.ndarray | None = None
    source_frame: np.ndarray | None = None

    def __post_init__(self):
        data = np.array(self.data, dtype=np.float64, copy=True)
        if data.ndim < 2 or data.shape[-1] < 1 or data.shape[-2] < 1:
            raise ValueError("grid data must have shape (..., rows, cols) with rows, cols >= 1")
        if not np.isfinite(data).all():
            raise ValueError("grid data must be finite")
        resolution = float(self.resolution)
        if not np.isfinite(resolution) or resolution <= 0:
            raise ValueError("grid resolution must be finite and positive")
        fill = float(self.fill)
        if not np.isfinite(fill):
            raise ValueError("grid fill value must be finite")
        frame = SE2.validate(np.asarray(self.frame, dtype=np.float64))
        valid = self.valid
        if valid is None:
            valid = np.ones(data.shape[-2:], dtype=bool)
        else:
            valid = np.array(valid, dtype=bool, copy=True)
            if valid.shape != data.shape[-2:]:
                raise ValueError("grid valid mask shape must match the trailing grid shape")
        source_frame = self.source_frame
        if source_frame is not None:
            source_frame = SE2.validate(np.asarray(source_frame, dtype=np.float64))
        for array in (data, valid, frame, source_frame):
            if array is not None:
                array.setflags(write=False)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "resolution", resolution)
        object.__setattr__(self, "frame", frame)
        object.__setattr__(self, "fill", fill)
        object.__setattr__(self, "valid", valid)
        object.__setattr__(self, "source_frame", source_frame)

    @property
    def shape(self):
        """Grid shape ``(rows, cols)`` (excluding channel dimensions)."""
        return self.data.shape[-2:]


def _bilinear_sample(data, valid, rows, cols, fill):
    """Bilinear resampling with clamped boundary indices; returns (values, mask)."""
    height, width = data.shape[-2:]
    tol = 1e-12
    inside = (
        (rows >= -tol) & (rows <= height - 1 + tol) & (cols >= -tol) & (cols <= width - 1 + tol)
    )
    r0 = np.clip(np.floor(rows), 0, height - 1).astype(np.int64)
    c0 = np.clip(np.floor(cols), 0, width - 1).astype(np.int64)
    r1 = np.clip(r0 + 1, 0, height - 1)
    c1 = np.clip(c0 + 1, 0, width - 1)
    wr = np.clip(rows - r0, 0.0, 1.0)
    wc = np.clip(cols - c0, 0.0, 1.0)

    sampled = (
        data[..., r0, c0] * ((1.0 - wr) * (1.0 - wc))
        + data[..., r0, c1] * ((1.0 - wr) * wc)
        + data[..., r1, c0] * (wr * (1.0 - wc))
        + data[..., r1, c1] * (wr * wc)
    )
    ok = inside & valid[r0, c0] & valid[r0, c1] & valid[r1, c0] & valid[r1, c1]
    sampled = np.where(ok, sampled, fill)
    return sampled, ok


def _resample_planar(grid, relative, fill):
    """Sample ``grid`` on the lattice of ``relative``'s target frame."""
    height, width = grid.shape
    resolution = grid.resolution
    xs = (np.arange(width) + 0.5) * resolution
    ys = (np.arange(height) + 0.5) * resolution
    gx, gy = np.meshgrid(xs, ys)
    src_x = relative[0, 0] * gx + relative[0, 1] * gy + relative[0, 2]
    src_y = relative[1, 0] * gx + relative[1, 1] * gy + relative[1, 2]
    rows = src_y / resolution - 0.5
    cols = src_x / resolution - 0.5
    return _bilinear_sample(grid.data, grid.valid, rows, cols, fill)


def canonicalize_grid(value, belief):
    """Resample a world gravity-aligned metric grid onto the canonical agent lattice.

    Output lattice: same shape and resolution as the input, axis aligned in the
    canonical frame ``g(mu_hat)`` (agent-centered).  Bilinear interpolation,
    clamped boundary indices, ``fill`` outside the source index rectangle and a
    validity mask for output cells; the provenance frame is recorded.
    """
    b = _require_belief(belief)
    if not isinstance(value, PlanarGrid):
        raise TypeError("canonicalize_grid expects a PlanarGrid")
    canonical = b.planar()
    relative = _relative_planar(value.frame, canonical)
    data, valid = _resample_planar(value, relative, value.fill)
    return PlanarGrid(
        data=data,
        resolution=value.resolution,
        frame=canonical,
        fill=value.fill,
        valid=valid,
        source_frame=value.frame,
    )


def decanonicalize_grid(value, belief):
    """Render a canonical grid back onto its provenance (or world) lattice.

    The canonical grid must have been produced with the canonical frame of
    ``belief``.  The field is resampled bilinearly onto ``source_frame`` when
    recorded, otherwise onto the identity world lattice; the round trip is
    therefore approximate (double interpolation) and the result is valid only
    where the canonical grid was valid.
    """
    b = _require_belief(belief)
    if not isinstance(value, PlanarGrid):
        raise TypeError("decanonicalize_grid expects a PlanarGrid")
    canonical = b.planar()
    if not np.allclose(value.frame, canonical, atol=1e-9, rtol=0):
        raise ValueError("grid frame is not the canonical frame of the given belief")
    target = value.source_frame
    if target is None:
        target = SE2.identity()
    relative = _relative_planar(value.frame, target)
    data, valid = _resample_planar(value, relative, value.fill)
    return PlanarGrid(
        data=data,
        resolution=value.resolution,
        frame=target,
        fill=value.fill,
        valid=valid,
        source_frame=None,
    )


def canonicalize(x, belief):
    """Equation 9 canonical map, dispatching on the supported input types.

    Accepted: ``PlanarGrid``; tagged ``WorldVectors`` (rotation only); tagged
    ``WorldPoints`` or a plain array of points with trailing dimension 2 or 3;
    an SE(3) pose array with trailing shape ``(4, 4)``.  Raw images/RGB arrays
    are rejected instead of being silently treated as 3-D points.
    """
    b = _require_belief(belief)
    if isinstance(x, PlanarGrid):
        return canonicalize_grid(x, b)
    if isinstance(x, WorldVectors):
        return canonicalize_vectors(x, b)
    if isinstance(x, WorldPoints):
        return canonicalize_points(x, b)
    if isinstance(x, np.ndarray):
        if x.shape == (4, 4) or (x.ndim == 3 and x.shape[1:] == (4, 4)):
            return canonicalize_poses(x, b)
        if x.ndim >= 3:
            raise ValueError("image/RGB inputs are out of scope; only points, vectors, poses, grids")
        return canonicalize_points(x, b)
    raise TypeError("unsupported input type for canonicalize")


def decanonicalize(y, belief):
    """Inverse of ``canonicalize`` for the same supported input types."""
    b = _require_belief(belief)
    if isinstance(y, PlanarGrid):
        return decanonicalize_grid(y, b)
    if isinstance(y, WorldVectors):
        return decanonicalize_vectors(y, b)
    if isinstance(y, WorldPoints):
        return decanonicalize_points(y, b)
    if isinstance(y, np.ndarray):
        if y.shape == (4, 4) or (y.ndim == 3 and y.shape[1:] == (4, 4)):
            return decanonicalize_poses(y, b)
        if y.ndim >= 3:
            raise ValueError("image/RGB inputs are out of scope; only points, vectors, poses, grids")
        return decanonicalize_points(y, b)
    raise TypeError("unsupported input type for decanonicalize")


def _aligned_selector(belief):
    indices = _GRAVITY_ALIGNED_TANGENT_INDICES[belief.group]
    selector = np.zeros((len(indices), belief.group.dof))
    selector[np.arange(len(indices)), np.asarray(indices)] = 1.0
    return selector


def sample_pose_errors(belief, rng, count):
    """Sample ``count`` tangent perturbations that keep a gravity-aligned pose.

    For SE(2) the full 3-D covariance is sampled.  For SE(3) only the
    alignment-preserving tangent coordinates are sampled (any translation and
    yaw; no roll/pitch), because the G3 contract canonicalizes with the
    gravity-aligned part and rejects roll/pitch.  Sampling the marginal is a
    modeling choice, documented rather than hidden, and the returned vectors
    have the full ``group.dof`` length with zeros outside that subspace.
    """
    b = _require_belief(belief)
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be a numpy.random.Generator")
    if not isinstance(count, (int, np.integer)) or count < 1:
        raise ValueError("count must be a positive integer")
    sigma = np.asarray(b.belief.covariance, dtype=np.float64)
    selector = _aligned_selector(b)
    sigma_sub = selector @ sigma @ selector.T
    sigma_sub = (sigma_sub + sigma_sub.T) / 2.0
    tangent = rng.multivariate_normal(np.zeros(sigma_sub.shape[0]), sigma_sub, size=int(count))
    return tangent @ selector


def apply_pose_error(belief, xi):
    """Apply a tangent perturbation (on the belief's side) to the mean."""
    return _require_belief(belief).with_perturbation(xi)


def inject_pose_error(belief, rng):
    """Training-time pose-error injection: one perturbation sampled from Sigma."""
    xi = sample_pose_errors(belief, rng, 1)[0]
    return apply_pose_error(belief, xi)


def _right_only(belief, name):
    if belief.side != "right":
        raise ValueError(
            f"{name} is derived for the right-perturbation convention (G1 default, "
            "ARCHITECTURE_V9 section 4); convert the belief side explicitly first"
        )


def predicted_point_error_covariance(belief, canonical_point):
    """First-order covariance of canonicalized-point errors under right noise.

    For a right-perturbed estimate the canonical point error is, to first
    order, ``delta = -[rho_x, rho_y, 0] - theta * (J p)` in canonical
    coordinates, with ``J = [[0, -1], [1, 0]]``; only yaw and horizontal
    translation propagate, so height and roll/pitch directions drop out.
    Valid for small Sigma only; it is not a full uncertainty bound.
    """
    b = _require_belief(belief)
    _right_only(b, "predicted_point_error_covariance")
    p = vector(canonical_point, 3)
    sigma = np.asarray(b.belief.covariance, dtype=np.float64)
    if b.group is SE2:
        jacobian = np.zeros((3, 3))
        jacobian[0, 0] = jacobian[1, 1] = -1.0
        jacobian[0, 2] = p[1]
        jacobian[1, 2] = -p[0]
    else:
        jacobian = np.zeros((3, 6))
        jacobian[0, 0] = jacobian[1, 1] = -1.0
        jacobian[0, 5] = p[1]
        jacobian[1, 5] = -p[0]
    return jacobian @ sigma @ jacobian.T


def predicted_vector_error_covariance(belief, canonical_vector):
    """First-order covariance of canonicalized-vector errors under right noise.

    Direction vectors do not translate with the pose, so only yaw propagates:
    ``delta = -theta * (J v)`` to first order.  Same limits as the point helper.
    """
    b = _require_belief(belief)
    _right_only(b, "predicted_vector_error_covariance")
    v = vector(canonical_vector, 3)
    sigma = np.asarray(b.belief.covariance, dtype=np.float64)
    if b.group is SE2:
        jacobian = np.zeros((3, 3))
        jacobian[0, 2] = v[1]
        jacobian[1, 2] = -v[0]
    else:
        jacobian = np.zeros((3, 6))
        jacobian[0, 5] = v[1]
        jacobian[1, 5] = -v[0]
    return jacobian @ sigma @ jacobian.T
