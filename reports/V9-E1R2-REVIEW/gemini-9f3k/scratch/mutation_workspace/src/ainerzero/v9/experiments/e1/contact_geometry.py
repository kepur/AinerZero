"""Exact shape surface distance for prediction-side collision events (pure Python).

The ground truth side records contacts with AnimeWorldZero E0's
``compute_exact_shape_distance`` (python/animeworld/e0/blender_worker.py). The prereg
defines contact as exact shape surface distance within 0.004 m, so the prediction side has
to use the same geometry: otherwise a perfect prediction cannot score F1 = 1.

This is a port of that function, with one speed-up: when two boxes are separated by more
than ``contact_tolerance`` along some axis, the true distance is not computed and that gap
is returned instead. It is a lower bound of the true distance and is above the tolerance, so
it gives the same contact decision. tests/test_e1_contact_geometry.py checks parity with E0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

Vec = tuple[float, float, float]
Mat = list[list[float]]

# The student view stores only the top surfaces of these static bodies, not their full extents.
# E0 (AnimeWorldZero python/animeworld/e0/scenarios.py) builds the ground as a 30 x 30 x 1 m box and
# the ramp 0.4 m thick. The ground is treated as an effectively infinite plane here, as the prior
# does: no episode leaves its 15 m half extent, and a stray prediction should not fall off it.
GROUND_HALF_EXTENTS: Vec = (1.0e4, 1.0e4, 0.5)
E0_RAMP_THICKNESS_M: float = 0.4

IDENTITY_ROTATION: Mat = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]


@dataclass(frozen=True)
class Primitive:
    """Collision primitive: a sphere (half = radius on every axis) or an oriented box."""

    is_sphere: bool
    half: Vec
    position: Vec = (0.0, 0.0, 0.0)
    rotation: Mat | None = None


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _len(a: Vec) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def _norm(a: Vec, fallback: Vec = (0.0, 0.0, 1.0)) -> Vec:
    n = _len(a)
    if n < 1e-12:
        return fallback
    return (a[0] / n, a[1] / n, a[2] / n)


def quat_to_rotation(q: Sequence[float]) -> Mat:
    """Convert a (w, x, y, z) quaternion to a 3x3 rotation matrix, normalizing first."""
    w, x, y, z = float(q[0]), float(q[1]), float(q[2]), float(q[3])
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n > 1e-12:
        w, x, y, z = w / n, x / n, y / n, z / n
    return [
        [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)],
        [2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)],
        [2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)],
    ]


def _mat_vec(R: Mat, v: Vec) -> Vec:
    return (
        R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
        R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
        R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2],
    )


def _mat_t_vec(R: Mat, v: Vec) -> Vec:
    return (
        R[0][0] * v[0] + R[1][0] * v[1] + R[2][0] * v[2],
        R[0][1] * v[0] + R[1][1] * v[1] + R[2][1] * v[2],
        R[0][2] * v[0] + R[1][2] * v[1] + R[2][2] * v[2],
    )


def _closest_point_on_obb(pt: Vec, b_pos: Vec, R: Mat, half: Vec) -> tuple[float, Vec, Vec]:
    """Signed distance from a point to an OBB, closest surface point, outward normal from the OBB."""
    loc = _mat_t_vec(R, _sub(pt, b_pos))
    hx, hy, hz = half
    cx = max(-hx, min(hx, loc[0]))
    cy = max(-hy, min(hy, loc[1]))
    cz = max(-hz, min(hz, loc[2]))
    inside = abs(loc[0]) <= hx + 1e-12 and abs(loc[1]) <= hy + 1e-12 and abs(loc[2]) <= hz + 1e-12
    c_world = _add(b_pos, _mat_vec(R, (cx, cy, cz)))
    if not inside:
        diff = _sub(pt, c_world)
        return _len(diff), c_world, _norm(diff)

    dx, dy, dz = hx - abs(loc[0]), hy - abs(loc[1]), hz - abs(loc[2])
    m = min(dx, dy, dz)
    if m == dx:
        n_loc = (1.0 if loc[0] >= 0.0 else -1.0, 0.0, 0.0)
        p_loc = (hx if loc[0] >= 0.0 else -hx, loc[1], loc[2])
    elif m == dy:
        n_loc = (0.0, 1.0 if loc[1] >= 0.0 else -1.0, 0.0)
        p_loc = (loc[0], hy if loc[1] >= 0.0 else -hy, loc[2])
    else:
        n_loc = (0.0, 0.0, 1.0 if loc[2] >= 0.0 else -1.0)
        p_loc = (loc[0], loc[1], hz if loc[2] >= 0.0 else -hz)
    return -m, _add(b_pos, _mat_vec(R, p_loc)), _mat_vec(R, n_loc)


def _closest_points_seg_seg(p1: Vec, q1: Vec, p2: Vec, q2: Vec) -> tuple[Vec, Vec]:
    """Closest points between line segments [p1, q1] and [p2, q2]."""
    d1, d2, r = _sub(q1, p1), _sub(q2, p2), _sub(p1, p2)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    if a <= 1e-12 and e <= 1e-12:
        return p1, p2
    if a <= 1e-12:
        s = 0.0
        t = max(0.0, min(1.0, f / e))
    else:
        c = _dot(d1, r)
        if e <= 1e-12:
            t = 0.0
            s = max(0.0, min(1.0, -c / a))
        else:
            b = _dot(d1, d2)
            denom = a * e - b * b
            s = max(0.0, min(1.0, (b * f - c * e) / denom)) if denom != 0.0 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t = 0.0
                s = max(0.0, min(1.0, -c / a))
            elif t > 1.0:
                t = 1.0
                s = max(0.0, min(1.0, (b - c) / a))
    return _add(p1, _scale(d1, s)), _add(p2, _scale(d2, t))


def _obb_verts_edges(pos: Vec, R: Mat, half: Vec) -> tuple[list[Vec], list[tuple[Vec, Vec]]]:
    hx, hy, hz = half
    verts = [
        _add(pos, _mat_vec(R, (sx, sy, sz)))
        for sx in (-hx, hx)
        for sy in (-hy, hy)
        for sz in (-hz, hz)
    ]
    edges = [
        (verts[i], verts[i ^ bit]) for i in range(8) for bit in (1, 2, 4) if i < (i ^ bit)
    ]
    return verts, edges


def surface_distance(
    a: Primitive,
    b: Primitive,
    *,
    contact_tolerance: float,
) -> tuple[float, Vec]:
    """Signed surface distance and unit normal from a to b.

    The returned distance is exact whenever it is at or below ``contact_tolerance``. Above it,
    it is a lower bound of the true distance that is still above the tolerance.
    """
    if a.is_sphere and b.is_sphere:
        diff = _sub(b.position, a.position)
        return _len(diff) - (a.half[0] + b.half[0]), _norm(diff)

    if a.is_sphere:
        d, _, out = _closest_point_on_obb(a.position, b.position, b.rotation, b.half)
        return d - a.half[0], _scale(out, -1.0)  # out points from b toward a

    if b.is_sphere:
        d, _, out = _closest_point_on_obb(b.position, a.position, a.rotation, a.half)
        return d - b.half[0], out  # out points from a toward b

    Ra, Rb = a.rotation, b.rotation
    ha, hb = a.half, b.half
    axes_a = [(Ra[0][i], Ra[1][i], Ra[2][i]) for i in range(3)]
    axes_b = [(Rb[0][i], Rb[1][i], Rb[2][i]) for i in range(3)]
    diff_ab = _sub(b.position, a.position)

    test_axes = axes_a + axes_b
    for ax in axes_a:
        for bx in axes_b:
            cr = _cross(ax, bx)
            if _len(cr) > 1e-6:
                test_axes.append(_norm(cr))

    min_overlap = math.inf
    best_axis = _norm(diff_ab)
    separated = False
    for u in test_axes:
        ra = sum(abs(_dot(u, axes_a[i])) * ha[i] for i in range(3))
        rb = sum(abs(_dot(u, axes_b[i])) * hb[i] for i in range(3))
        along = _dot(diff_ab, u)
        overlap = ra + rb - abs(along)
        if overlap < 0.0:
            if -overlap > contact_tolerance:
                return -overlap, (u if along >= 0.0 else _scale(u, -1.0))
            separated = True
        elif overlap < min_overlap:
            min_overlap = overlap
            best_axis = u if along >= 0.0 else _scale(u, -1.0)

    if not separated:
        return -min_overlap, best_axis

    va, ea = _obb_verts_edges(a.position, Ra, ha)
    vb, eb = _obb_verts_edges(b.position, Rb, hb)
    best_d = math.inf
    best_norm = _norm(diff_ab)
    for v in va:
        d, cp, _ = _closest_point_on_obb(v, b.position, Rb, hb)
        if 0.0 <= d < best_d:
            best_d = d
            best_norm = _norm(_sub(cp, v), best_norm)
    for v in vb:
        d, cp, _ = _closest_point_on_obb(v, a.position, Ra, ha)
        if 0.0 <= d < best_d:
            best_d = d
            best_norm = _norm(_sub(v, cp), best_norm)
    for p1, q1 in ea:
        for p2, q2 in eb:
            c1, c2 = _closest_points_seg_seg(p1, q1, p2, q2)
            diff = _sub(c2, c1)
            d = _len(diff)
            if d < best_d:
                best_d = d
                best_norm = _norm(diff, best_norm)
    return best_d, best_norm


def active_primitive(info: Mapping[str, Any]) -> Primitive:
    """Primitive for an active body from its student-view metadata (pose filled in per frame)."""
    shape = str(info["shape"]).upper()
    dims = [float(x) for x in info["dimensions"]]
    if shape == "SPHERE":
        r = dims[0] / 2.0
        return Primitive(is_sphere=True, half=(r, r, r))
    if shape == "BOX":
        return Primitive(is_sphere=False, half=(dims[0] / 2.0, dims[1] / 2.0, dims[2] / 2.0))
    raise ValueError(f"Unsupported active body shape: {shape}")


def static_primitive(name: str, static_geo: Mapping[str, Any]) -> Primitive:
    """Rebuild a static body from the student view's static_environment, chosen by its name."""
    lower = name.lower()

    if "ground" in lower:
        g = static_geo.get("ground")
        if not g:
            raise ValueError(f"Static body '{name}' has no ground entry in static_environment")
        z_plane = float(g.get("z_plane", 0.0))
        center = (0.0, 0.0, z_plane - GROUND_HALF_EXTENTS[2])
        return Primitive(False, GROUND_HALF_EXTENTS, center, IDENTITY_ROTATION)

    if "ramp" in lower:
        ramps = static_geo.get("ramps") or []
        if len(ramps) != 1:
            raise ValueError(f"Static body '{name}' expects 1 ramp, found {len(ramps)}")
        r = ramps[0]
        n = _norm(tuple(float(x) for x in r["normal"]))
        point = tuple(float(x) for x in r["point"])
        xb, yb = r["x_bounds"], r["y_bounds"]
        # E0 tilts the ramp about the world x axis, so its local y axis is normal x (world x).
        local_y = _norm(_cross(n, (1.0, 0.0, 0.0)))
        if abs(local_y[1]) < 1e-6:
            raise ValueError(f"Ramp '{name}' is not tilted about the x axis: normal={n}")
        half_len = (float(yb[1]) - float(yb[0])) / 2.0 / abs(local_y[1])
        half_w = (float(xb[1]) - float(xb[0])) / 2.0
        center = _sub(point, _scale(n, E0_RAMP_THICKNESS_M / 2.0))
        rot = [[1.0, local_y[0], n[0]], [0.0, local_y[1], n[1]], [0.0, local_y[2], n[2]]]
        return Primitive(False, (half_w, half_len, E0_RAMP_THICKNESS_M / 2.0), center, rot)

    if "table" in lower:
        tables = static_geo.get("tables") or []
        if len(tables) != 1:
            raise ValueError(f"Static body '{name}' expects 1 table, found {len(tables)}")
        t = tables[0]
        xb, yb = t["x_bounds"], t["y_bounds"]
        thick = float(t.get("thickness", 0.20))
        z_top = float(t["z_top"])
        center = ((float(xb[0]) + float(xb[1])) / 2.0, (float(yb[0]) + float(yb[1])) / 2.0, z_top - thick / 2.0)
        half = ((float(xb[1]) - float(xb[0])) / 2.0, (float(yb[1]) - float(yb[0])) / 2.0, thick / 2.0)
        return Primitive(False, half, center, IDENTITY_ROTATION)

    boxes = static_geo.get("boxes") or []
    if len(boxes) != 1:
        raise ValueError(f"Static body '{name}' is unrecognized and expects 1 box, found {len(boxes)}")
    lo = [float(x) for x in boxes[0]["min_point"]]
    hi = [float(x) for x in boxes[0]["max_point"]]
    center = ((lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, (lo[2] + hi[2]) / 2.0)
    half = ((hi[0] - lo[0]) / 2.0, (hi[1] - lo[1]) / 2.0, (hi[2] - lo[2]) / 2.0)
    return Primitive(False, half, center, IDENTITY_ROTATION)
