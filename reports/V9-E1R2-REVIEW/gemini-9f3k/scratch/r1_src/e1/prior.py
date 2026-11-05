"""E1 Biased Physical Prior Integrator (pure NumPy / CPU).

Specification (reports/V9-P48/E1_IMPLEMENTATION_PLAN.md & r1 Architecture Update):
- 600 Hz semi-implicit Euler (10 substeps per 60 fps frame, dt = 1/600 s).
- Gravity g = (0, 0, -9.81) m/s^2 (Z-up coordinate system).
- Linear and angular damping.
- Contact impulses against static bodies (GroundPlane, InclinedRamp, TableTop, StaticBox).
  Coulomb friction and restitution with torque coupling:
  delta_v = J_t / m, delta_omega = -(h / I) * (n x J_t), I = 2/5 * m * R^2
- Inter-body contacts using support-function distance h(n) with torque coupling.
- Attitude integration: orientation quaternion [qw, qx, qy, qz] integrated at 600 Hz
  via exponential axis-angle map and normalized every substep.
- Rollout trajectory outputs 13 columns:
  [x, y, z, vx, vy, vz, qw, qx, qy, qz, wx, wy, wz].

### Registered Structural Biases (登记的结构偏差清单)
1. Collision Geometry: Box contact uses support distance h(n) = sum_i e_i * |n . a_i|, contact point at support projection r_c = -h(n) * n, inter-body normal uses center line, single-point contact. Spheres use radius R.
2. Moment of Inertia: Solid sphere moment of inertia I = 2/5 * m * R^2 for all bodies (using bounding sphere radius R).
3. Friction Combination Rule: Arithmetic mean mu_eff = 0.5 * (mu1 + mu2).
4. Restitution Combination Rule: Minimum e_eff = min(e1, e2).
5. Static Surface Defaults:
   - Ground: mu=0.50, e=0.30
   - Ramp: mu=0.25, e=0.25
   - Table: mu=0.20, e=0.35
   - Box: mu=0.50, e=0.30
6. Aerodynamic Drag: Zero air drag (Cd = 0).
7. Rolling Resistance: Zero rolling resistance coefficient (crr = 0).
8. Contact Dynamics: Single-point impulse response with Coulomb friction cone limit and torque coupling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np

# --- Simulation Constants ---
GRAVITY_ACCEL: float = 9.81
DEFAULT_FPS: int = 60
DEFAULT_SUBSTEPS: int = 10
SUBSTEP_DT: float = 1.0 / (DEFAULT_FPS * DEFAULT_SUBSTEPS)  # 1/600 s = 0.001666667 s
BOUNCE_VELOCITY_THRESHOLD: float = 0.05  # m/s; velocities below this threshold do not bounce

# --- Static Surface Defaults ---
DEFAULT_GROUND_FRICTION: float = 0.50
DEFAULT_GROUND_RESTITUTION: float = 0.30
DEFAULT_RAMP_FRICTION: float = 0.25
DEFAULT_RAMP_RESTITUTION: float = 0.25
DEFAULT_TABLE_FRICTION: float = 0.20
DEFAULT_TABLE_RESTITUTION: float = 0.35
DEFAULT_BOX_FRICTION: float = 0.50
DEFAULT_BOX_RESTITUTION: float = 0.30

# --- Registered Structural Biases ---
FRICTION_COMBINE_RULE: str = "mean: 0.5 * (f1 + f2)"
RESTITUTION_COMBINE_RULE: str = "min: min(e1, e2)"
INERTIA_APPROXIMATION: str = "solid_sphere: I = 2/5 * m * R^2"
COLLISION_GEOMETRY_APPROXIMATION: str = (
    "support_function: box contact uses support distance h(n)=sum(e_i*|n.a_i|), "
    "contact point at support projection r_c=-h(n)*n, inter-body normal uses center line, single-point contact"
)

REGISTERED_STRUCTURAL_BIASES: dict[str, str] = {
    "collision_geometry": COLLISION_GEOMETRY_APPROXIMATION,
    "inertia_model": INERTIA_APPROXIMATION,
    "friction_combine_rule": FRICTION_COMBINE_RULE,
    "restitution_combine_rule": RESTITUTION_COMBINE_RULE,
    "static_surface_defaults": (
        f"ground(mu={DEFAULT_GROUND_FRICTION}, e={DEFAULT_GROUND_RESTITUTION}), "
        f"ramp(mu={DEFAULT_RAMP_FRICTION}, e={DEFAULT_RAMP_RESTITUTION}), "
        f"table(mu={DEFAULT_TABLE_FRICTION}, e={DEFAULT_TABLE_RESTITUTION}), "
        f"box(mu={DEFAULT_BOX_FRICTION}, e={DEFAULT_BOX_RESTITUTION})"
    ),
    "aerodynamic_drag": "zero air drag (Cd=0)",
    "rolling_resistance": "zero rolling resistance coefficient (crr=0)",
    "contact_dynamics": "single-point impulse response with Coulomb friction cone limit and torque coupling",
}


@dataclass
class PhysicalParameters:
    """Physical parameters (phi) for an active rigid body."""

    friction: float = 0.50
    restitution: float = 0.45
    mass: float = 2.60
    linear_damping: float = 0.125
    angular_damping: float = 0.125

    def to_array(self) -> np.ndarray:
        return np.array(
            [self.friction, self.restitution, self.mass, self.linear_damping, self.angular_damping],
            dtype=np.float64,
        )

    @classmethod
    def from_array(cls, arr: Sequence[float]) -> PhysicalParameters:
        return cls(
            friction=float(arr[0]),
            restitution=float(arr[1]),
            mass=float(arr[2]),
            linear_damping=float(arr[3]),
            angular_damping=float(arr[4]),
        )

    def copy(self) -> PhysicalParameters:
        return PhysicalParameters(
            friction=self.friction,
            restitution=self.restitution,
            mass=self.mass,
            linear_damping=self.linear_damping,
            angular_damping=self.angular_damping,
        )


DEFAULT_BIASED_PRIOR = PhysicalParameters(
    friction=0.50,
    restitution=0.45,
    mass=2.60,
    linear_damping=0.125,
    angular_damping=0.125,
)


def quaternion_multiply(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """Quaternion multiplication q = q1 * q2, format [w, x, y, z]."""
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        dtype=np.float64,
    )


def integrate_quaternion(q: np.ndarray, omega: np.ndarray, dt: float) -> np.ndarray:
    """Integrate orientation quaternion q by angular velocity omega over dt.

    Uses the exact axis-angle map for constant angular velocity:
    delta_q = [cos(theta/2), u * sin(theta/2)]
    where theta = |omega| * dt, u = omega / |omega|.
    """
    omega_norm = float(np.linalg.norm(omega))
    if omega_norm < 1e-12:
        norm_q = float(np.linalg.norm(q))
        if norm_q > 1e-12:
            return q / norm_q
        return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)

    theta = omega_norm * dt
    axis = omega / omega_norm
    half_theta = 0.5 * theta
    sin_half = math.sin(half_theta)
    dq = np.array(
        [
            math.cos(half_theta),
            axis[0] * sin_half,
            axis[1] * sin_half,
            axis[2] * sin_half,
        ],
        dtype=np.float64,
    )
    q_new = quaternion_multiply(dq, q)
    norm_new = float(np.linalg.norm(q_new))
    if norm_new > 1e-12:
        return q_new / norm_new
    return np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)


def quaternion_to_rotation_matrix(q: np.ndarray) -> np.ndarray:
    """Convert unit quaternion [w, x, y, z] to 3x3 rotation matrix R.

    Columns of R correspond to body principal axes a_0, a_1, a_2 in world frame.
    """
    w, x, y, z = q
    return np.array(
        [
            [1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - w * z), 2.0 * (x * z + w * y)],
            [2.0 * (x * y + w * z), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - w * x)],
            [2.0 * (x * z - w * y), 2.0 * (y * z + w * x), 1.0 - 2.0 * (x * x + y * y)],
        ],
        dtype=np.float64,
    )


@dataclass
class ActiveBody:
    """State, bounding sphere, and optional box geometry of an active dynamic body."""

    name: str
    radius: float  # bounding sphere radius in meters (used for isotropic inertia)
    params: PhysicalParameters
    position: np.ndarray  # (3,)
    velocity: np.ndarray  # (3,)
    orientation: np.ndarray = field(
        default_factory=lambda: np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    )
    angular_velocity: np.ndarray = field(
        default_factory=lambda: np.zeros(3, dtype=np.float64)
    )
    half_extents: np.ndarray | None = None  # (3,) half-extents for box; None for sphere

    def copy(self) -> ActiveBody:
        return ActiveBody(
            name=self.name,
            radius=self.radius,
            params=self.params.copy(),
            position=np.array(self.position, dtype=np.float64, copy=True),
            velocity=np.array(self.velocity, dtype=np.float64, copy=True),
            orientation=np.array(self.orientation, dtype=np.float64, copy=True),
            angular_velocity=np.array(self.angular_velocity, dtype=np.float64, copy=True),
            half_extents=np.array(self.half_extents, dtype=np.float64, copy=True)
            if self.half_extents is not None
            else None,
        )


@dataclass(frozen=True)
class BodyGeometry:
    """Rigid body geometry: bounding sphere radius and optional box half-extents."""

    radius: float
    half_extents: np.ndarray | None = None

    def __post_init__(self) -> None:
        if self.radius < 0:
            raise ValueError(f"radius must be non-negative, got {self.radius}")
        if self.half_extents is not None:
            arr = np.asarray(self.half_extents, dtype=np.float64)
            if arr.shape != (3,):
                raise ValueError(f"half_extents must have shape (3,), got {arr.shape}")
            object.__setattr__(self, "half_extents", arr)


def geometry_from_student_body(info: Mapping[str, Any]) -> BodyGeometry:
    """Construct BodyGeometry from student active body metadata."""
    if not isinstance(info, Mapping):
        raise TypeError(f"body info must be a Mapping, got {type(info)}")
    for key in ("shape", "dimensions", "bounding_sphere_radius"):
        if key not in info or info[key] is None:
            raise KeyError(f"Missing required field '{key}' in body info: {info}")

    shape = str(info["shape"]).upper()
    radius = float(info["bounding_sphere_radius"])

    if shape == "SPHERE":
        return BodyGeometry(radius=radius, half_extents=None)
    elif shape == "BOX":
        dims = np.asarray(info["dimensions"], dtype=np.float64)
        if dims.shape != (3,):
            raise ValueError(f"BOX dimensions must have shape (3,), got {dims.shape}")
        return BodyGeometry(radius=radius, half_extents=dims / 2.0)
    else:
        raise NotImplementedError(f"Unsupported shape: {shape}")


def support_distance(body: ActiveBody, n_world: np.ndarray) -> float:
    """Compute support distance h(n) of body along world direction n_world.

    - Sphere (half_extents is None): returns radius.
    - Box (half_extents is not None): returns sum_i e_i * |n . a_i|,
      where a_i are the columns of rotation matrix R(q), and n is unit vector.
    """
    if body.half_extents is None:
        return float(body.radius)
    norm_n = float(np.linalg.norm(n_world))
    if norm_n < 1e-12:
        return float(body.radius)
    n = n_world / norm_n
    R = quaternion_to_rotation_matrix(body.orientation)
    # n . a_i = (R^T @ n)_i
    projections = np.abs(R.T @ n)
    return float(np.sum(body.half_extents * projections))


def make_active_body_from_state(
    name: str,
    state_13: np.ndarray,
    params: PhysicalParameters,
    radius: float = 0.5,
    half_extents: np.ndarray | None = None,
) -> ActiveBody:
    """Create an ActiveBody from a 13-dim state row [x,y,z, vx,vy,vz, qw,qx,qy,qz, wx,wy,wz].

    Backwards compatible: if half_extents is None, behavior is bitwise identical to pure sphere.
    """
    pos = np.array(state_13[0:3], dtype=np.float64, copy=True)
    vel = np.array(state_13[3:6], dtype=np.float64, copy=True)
    if len(state_13) >= 10:
        ori = np.array(state_13[6:10], dtype=np.float64, copy=True)
    else:
        ori = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    if len(state_13) >= 13:
        ang = np.array(state_13[10:13], dtype=np.float64, copy=True)
    else:
        ang = np.zeros(3, dtype=np.float64)

    he = (
        np.array(half_extents, dtype=np.float64, copy=True)
        if half_extents is not None
        else None
    )
    return ActiveBody(
        name=name,
        radius=radius,
        params=params.copy(),
        position=pos,
        velocity=vel,
        orientation=ori,
        angular_velocity=ang,
        half_extents=he,
    )


@dataclass
class GroundPlane:
    """Infinite static ground plane at z=z_plane with normal (0, 0, 1)."""

    z_plane: float = 0.0
    friction: float = DEFAULT_GROUND_FRICTION
    restitution: float = DEFAULT_GROUND_RESTITUTION
    name: str = "Ground"


@dataclass
class InclinedRamp:
    """Static inclined ramp surface.

    Defined by a plane passing through center_point with unit normal vector pointing outwards.
    x_bounds and y_bounds optionally limit the ramp extents.
    """

    point: np.ndarray  # (3,) point on the plane
    normal: np.ndarray  # (3,) unit normal pointing outwards
    friction: float = DEFAULT_RAMP_FRICTION
    restitution: float = DEFAULT_RAMP_RESTITUTION
    x_bounds: tuple[float, float] | None = None
    y_bounds: tuple[float, float] | None = None
    name: str = "Ramp"


@dataclass
class StaticBox:
    """Static axis-aligned box obstacle (e.g. table body, occluder wall).

    Defined by min_point (x_min, y_min, z_min) and max_point (x_max, y_max, z_max).
    """

    min_point: np.ndarray  # (3,)
    max_point: np.ndarray  # (3,)
    friction: float = DEFAULT_BOX_FRICTION
    restitution: float = DEFAULT_BOX_RESTITUTION
    name: str = "StaticBox"


@dataclass
class TableTop:
    """Static horizontal table top surface at z=z_top with rectangular bounds.

    Converts to a StaticBox with thickness for unified 6-face collision.
    """

    z_top: float
    x_bounds: tuple[float, float]
    y_bounds: tuple[float, float]
    thickness: float = 0.20
    friction: float = DEFAULT_TABLE_FRICTION
    restitution: float = DEFAULT_TABLE_RESTITUTION
    name: str = "TableTop"

    def to_box(self) -> StaticBox:
        return StaticBox(
            min_point=np.array(
                [self.x_bounds[0], self.y_bounds[0], self.z_top - self.thickness],
                dtype=np.float64,
            ),
            max_point=np.array(
                [self.x_bounds[1], self.y_bounds[1], self.z_top],
                dtype=np.float64,
            ),
            friction=self.friction,
            restitution=self.restitution,
            name=self.name,
        )


@dataclass
class StaticEnvironment:
    """Collection of static obstacles."""

    ground: GroundPlane | None = field(default_factory=GroundPlane)
    ramps: list[InclinedRamp] = field(default_factory=list)
    tables: list[TableTop] = field(default_factory=list)
    boxes: list[StaticBox] = field(default_factory=list)


def apply_surface_impulse(
    b: ActiveBody,
    normal: np.ndarray,
    surf_friction: float,
    surf_restitution: float,
    bounce_threshold: float = BOUNCE_VELOCITY_THRESHOLD,
) -> None:
    """Apply contact impulse and torque coupling between an active body and a static surface.

    Coupling equations:
    - Normal impulse: Jn = m * (1 + eff_e) * |vn|
    - Contact point: r_c = -h(n) * n
    - Contact velocity: vc = v - h * (omega x n)
    - Tangential velocity: v_ct = vc - (vc . n) * n
    - Tangential impulse: J_stick = |v_ct| / (1/m + h^2/I), J_max = mu * Jn
    - Torque coupling: delta_omega = -(h / I) * (n x J_t)
    Where I = 2/5 * m * R^2 (R is bounding sphere radius).
    When sphere (half_extents is None), h = R, degenerating bitwise identically to (2/7) * m * |v_ct|.
    """
    vn = float(np.dot(b.velocity, normal))
    if vn < 0.0:
        m = max(b.params.mass, 1e-6)
        e = min(b.params.restitution, surf_restitution)
        eff_e = e if abs(vn) > bounce_threshold else 0.0

        # Normal impulse
        delta_vn = -(1.0 + eff_e) * vn
        b.velocity += delta_vn * normal
        Jn = m * (1.0 + eff_e) * abs(vn)

        if b.half_extents is None:
            # Sphere: bitwise identical to legacy formula
            v_c = b.velocity - b.radius * np.cross(b.angular_velocity, normal)
            v_ct = v_c - float(np.dot(v_c, normal)) * normal
            v_ct_norm = float(np.linalg.norm(v_ct))

            if v_ct_norm > 1e-9:
                mu = 0.5 * (b.params.friction + surf_friction)
                J_stick = (2.0 / 7.0) * m * v_ct_norm
                J_max = mu * Jn
                if J_stick <= J_max:
                    J_t_mag = J_stick
                else:
                    J_t_mag = J_max

                J_t = -J_t_mag * (v_ct / v_ct_norm)
                b.velocity += J_t / m

                delta_omega = -(5.0 / (2.0 * m * b.radius)) * np.cross(normal, J_t)
                b.angular_velocity += delta_omega
        else:
            # Box: generalized impulse formula with support distance
            h = support_distance(b, normal)
            v_c = b.velocity - h * np.cross(b.angular_velocity, normal)
            v_ct = v_c - float(np.dot(v_c, normal)) * normal
            v_ct_norm = float(np.linalg.norm(v_ct))

            if v_ct_norm > 1e-9:
                mu = 0.5 * (b.params.friction + surf_friction)
                I = 0.4 * m * (b.radius ** 2)
                denom = 1.0 / m + (h ** 2) / I
                J_stick = v_ct_norm / denom
                J_max = mu * Jn
                if J_stick <= J_max:
                    J_t_mag = J_stick
                else:
                    J_t_mag = J_max

                J_t = -J_t_mag * (v_ct / v_ct_norm)
                b.velocity += J_t / m

                delta_omega = -(h / I) * np.cross(normal, J_t)
                b.angular_velocity += delta_omega


def resolve_sphere_box_collision(
    b: ActiveBody,
    box: StaticBox,
    bounce_threshold: float = BOUNCE_VELOCITY_THRESHOLD,
) -> None:
    """Resolve collision between active body and a static axis-aligned box."""
    closest = np.clip(b.position, box.min_point, box.max_point)
    diff = b.position - closest
    dist = float(np.linalg.norm(diff))

    if dist > 1e-12:
        # Body center is outside the box: outward normal from box to body
        normal = diff / dist
        h = support_distance(b, normal)
        if dist < h:
            pen = h - dist
            apply_surface_impulse(b, normal, box.friction, box.restitution, bounce_threshold)
            b.position += pen * normal
    else:
        # Body center is inside the box (deep penetration): find face of minimum exit distance
        d_min = b.position - box.min_point
        d_max = box.max_point - b.position
        face_dists = [
            (d_min[0], np.array([-1.0, 0.0, 0.0], dtype=np.float64)),
            (d_max[0], np.array([1.0, 0.0, 0.0], dtype=np.float64)),
            (d_min[1], np.array([0.0, -1.0, 0.0], dtype=np.float64)),
            (d_max[1], np.array([0.0, 1.0, 0.0], dtype=np.float64)),
            (d_min[2], np.array([0.0, 0.0, -1.0], dtype=np.float64)),
            (d_max[2], np.array([0.0, 0.0, 1.0], dtype=np.float64)),
        ]
        min_dist, normal = min(face_dists, key=lambda f: f[0])
        h = support_distance(b, normal)
        pen = h + min_dist
        apply_surface_impulse(b, normal, box.friction, box.restitution, bounce_threshold)
        b.position += pen * normal


def step_substep(
    bodies: list[ActiveBody],
    env: StaticEnvironment,
    dt: float = SUBSTEP_DT,
    g: float = GRAVITY_ACCEL,
    extra_accel_fn: Callable[[ActiveBody], np.ndarray] | None = None,
) -> None:
    """Advance physical simulation by a single 600 Hz substep (semi-implicit Euler)."""
    # 1. Continuous forces (Gravity + Damping + Extra) -> update velocity
    for b in bodies:
        m = max(b.params.mass, 1e-6)
        # Acceleration: gravity + linear damping
        a_lin = np.array([0.0, 0.0, -g], dtype=np.float64) - b.params.linear_damping * b.velocity
        if extra_accel_fn is not None:
            a_lin = a_lin + np.asarray(extra_accel_fn(b), dtype=np.float64)
        b.velocity += a_lin * dt

        # Angular damping
        a_ang = -b.params.angular_damping * b.angular_velocity
        b.angular_velocity += a_ang * dt

    # 2. Collisions with static environment
    for b in bodies:
        # Ground plane collision
        if env.ground is not None:
            normal = np.array([0.0, 0.0, 1.0], dtype=np.float64)
            z_surf = env.ground.z_plane
            h = support_distance(b, normal)
            dist = b.position[2] - z_surf - h
            if dist < 0.0:
                apply_surface_impulse(b, normal, env.ground.friction, env.ground.restitution)
                b.position[2] = z_surf + h

        # Inclined ramp collision
        for ramp in env.ramps:
            in_bounds = True
            if ramp.x_bounds is not None:
                in_bounds = in_bounds and (ramp.x_bounds[0] <= b.position[0] <= ramp.x_bounds[1])
            if ramp.y_bounds is not None:
                in_bounds = in_bounds and (ramp.y_bounds[0] <= b.position[1] <= ramp.y_bounds[1])

            if in_bounds:
                n = ramp.normal / np.linalg.norm(ramp.normal)
                plane_dist = float(np.dot(b.position - ramp.point, n))
                h = support_distance(b, n)
                surf_dist = plane_dist - h
                if surf_dist < 0.0:
                    apply_surface_impulse(b, n, ramp.friction, ramp.restitution)
                    b.position -= surf_dist * n

        # Static box collisions
        for box in env.boxes:
            resolve_sphere_box_collision(b, box)

        # TableTop collisions (processed as boxes)
        for table in env.tables:
            resolve_sphere_box_collision(b, table.to_box())

    # 3. Inter-body collisions
    n_bodies = len(bodies)
    for i in range(n_bodies):
        for j in range(i + 1, n_bodies):
            b1 = bodies[i]
            b2 = bodies[j]

            r_vec = b2.position - b1.position
            dist = float(np.linalg.norm(r_vec))

            if b1.half_extents is None and b2.half_extents is None:
                # Pure spheres: exact legacy arithmetic for bitwise identical regression
                r_sum = b1.radius + b2.radius
                if dist < r_sum and dist > 1e-9:
                    n = r_vec / dist
                    v_rel = b2.velocity - b1.velocity
                    vn = float(np.dot(v_rel, n))

                    if vn < 0.0:
                        e = min(b1.params.restitution, b2.params.restitution)
                        eff_e = e if abs(vn) > BOUNCE_VELOCITY_THRESHOLD else 0.0

                        m1 = max(b1.params.mass, 1e-6)
                        m2 = max(b2.params.mass, 1e-6)
                        m_eff = (m1 * m2) / (m1 + m2)

                        # Normal impulse
                        impulse_mag = -(1.0 + eff_e) * vn * m_eff
                        J_n_vec = impulse_mag * n
                        b1.velocity -= J_n_vec / m1
                        b2.velocity += J_n_vec / m2

                        # Relative contact point velocity
                        v_c1 = b1.velocity - b1.radius * np.cross(b1.angular_velocity, n)
                        v_c2 = b2.velocity + b2.radius * np.cross(b2.angular_velocity, n)
                        v_c_rel = v_c2 - v_c1
                        v_c_rel_t = v_c_rel - float(np.dot(v_c_rel, n)) * n
                        v_ct_norm = float(np.linalg.norm(v_c_rel_t))

                        if v_ct_norm > 1e-9:
                            mu = 0.5 * (b1.params.friction + b2.params.friction)
                            J_stick = (2.0 / 7.0) * m_eff * v_ct_norm
                            J_max = mu * impulse_mag
                            if J_stick <= J_max:
                                J_t_mag = J_stick
                            else:
                                J_t_mag = J_max

                            J_t_vec = -J_t_mag * (v_c_rel_t / v_ct_norm)
                            b1.velocity -= J_t_vec / m1
                            b2.velocity += J_t_vec / m2

                            # Torque coupling on both bodies
                            b1.angular_velocity -= (5.0 / (2.0 * m1 * b1.radius)) * np.cross(n, J_t_vec)
                            b2.angular_velocity -= (5.0 / (2.0 * m2 * b2.radius)) * np.cross(n, J_t_vec)

                    # Position separation (penetration resolution)
                    overlap = r_sum - dist
                    m1 = max(b1.params.mass, 1e-6)
                    m2 = max(b2.params.mass, 1e-6)
                    w1 = m2 / (m1 + m2)
                    w2 = m1 / (m1 + m2)
                    b1.position -= w1 * overlap * n
                    b2.position += w2 * overlap * n
            else:
                # At least one body is a box: support-function contact
                if dist > 1e-9:
                    n = r_vec / dist
                    h1 = support_distance(b1, n)
                    h2 = support_distance(b2, -n)
                    gap = dist - h1 - h2

                    if gap < 0.0:
                        v_rel = b2.velocity - b1.velocity
                        vn = float(np.dot(v_rel, n))

                        if vn < 0.0:
                            e = min(b1.params.restitution, b2.params.restitution)
                            eff_e = e if abs(vn) > BOUNCE_VELOCITY_THRESHOLD else 0.0

                            m1 = max(b1.params.mass, 1e-6)
                            m2 = max(b2.params.mass, 1e-6)
                            m_eff = (m1 * m2) / (m1 + m2)

                            # Normal impulse
                            impulse_mag = -(1.0 + eff_e) * vn * m_eff
                            J_n_vec = impulse_mag * n
                            b1.velocity -= J_n_vec / m1
                            b2.velocity += J_n_vec / m2

                            # Relative contact point velocity
                            v_c1 = b1.velocity - h1 * np.cross(b1.angular_velocity, n)
                            v_c2 = b2.velocity + h2 * np.cross(b2.angular_velocity, n)
                            v_c_rel = v_c2 - v_c1
                            v_c_rel_t = v_c_rel - float(np.dot(v_c_rel, n)) * n
                            v_ct_norm = float(np.linalg.norm(v_c_rel_t))

                            if v_ct_norm > 1e-9:
                                mu = 0.5 * (b1.params.friction + b2.params.friction)
                                I1 = 0.4 * m1 * (b1.radius ** 2)
                                I2 = 0.4 * m2 * (b2.radius ** 2)
                                denom = (1.0 / m1 + (h1 ** 2) / I1) + (1.0 / m2 + (h2 ** 2) / I2)
                                J_stick = v_ct_norm / denom
                                J_max = mu * impulse_mag
                                if J_stick <= J_max:
                                    J_t_mag = J_stick
                                else:
                                    J_t_mag = J_max

                                J_t_vec = -J_t_mag * (v_c_rel_t / v_ct_norm)
                                b1.velocity -= J_t_vec / m1
                                b2.velocity += J_t_vec / m2

                                b1.angular_velocity -= (h1 / I1) * np.cross(n, J_t_vec)
                                b2.angular_velocity -= (h2 / I2) * np.cross(n, J_t_vec)

                        # Position separation (penetration resolution)
                        overlap = -gap
                        m1 = max(b1.params.mass, 1e-6)
                        m2 = max(b2.params.mass, 1e-6)
                        w1 = m2 / (m1 + m2)
                        w2 = m1 / (m1 + m2)
                        b1.position -= w1 * overlap * n
                        b2.position += w2 * overlap * n

    # 4. Attitude and position update (semi-implicit Euler)
    for b in bodies:
        b.orientation = integrate_quaternion(b.orientation, b.angular_velocity, dt)
        b.position += b.velocity * dt


def simulate_frame(
    bodies: list[ActiveBody],
    env: StaticEnvironment,
    substeps: int = DEFAULT_SUBSTEPS,
    dt: float = SUBSTEP_DT,
    g: float = GRAVITY_ACCEL,
    extra_accel_fn: Callable[[ActiveBody], np.ndarray] | None = None,
) -> None:
    """Advance the physical simulation by 1 frame (substeps * dt)."""
    for _ in range(substeps):
        step_substep(bodies, env, dt=dt, g=g, extra_accel_fn=extra_accel_fn)


def rollout(
    bodies: Sequence[ActiveBody],
    env: StaticEnvironment,
    num_frames: int,
    substeps: int = DEFAULT_SUBSTEPS,
    dt: float = SUBSTEP_DT,
    g: float = GRAVITY_ACCEL,
    extra_accel_fn: Callable[[ActiveBody], np.ndarray] | None = None,
) -> dict[str, np.ndarray]:
    """Roll out physical simulation for num_frames at 60 fps (each frame having substeps).

    Returns:
        dict mapping body names to trajectory arrays of shape (num_frames + 1, 13)
        containing [x, y, z, vx, vy, vz, qw, qx, qy, qz, wx, wy, wz].
    """
    sim_bodies = [b.copy() for b in bodies]

    trajectories = {
        b.name: np.zeros((num_frames + 1, 13), dtype=np.float64) for b in sim_bodies
    }

    # Record frame 0
    for b in sim_bodies:
        trajectories[b.name][0, 0:3] = b.position
        trajectories[b.name][0, 3:6] = b.velocity
        trajectories[b.name][0, 6:10] = b.orientation
        trajectories[b.name][0, 10:13] = b.angular_velocity

    # Step through frames
    for frame_idx in range(1, num_frames + 1):
        simulate_frame(sim_bodies, env, substeps=substeps, dt=dt, g=g, extra_accel_fn=extra_accel_fn)
        for b in sim_bodies:
            trajectories[b.name][frame_idx, 0:3] = b.position
            trajectories[b.name][frame_idx, 3:6] = b.velocity
            trajectories[b.name][frame_idx, 6:10] = b.orientation
            trajectories[b.name][frame_idx, 10:13] = b.angular_velocity

    return trajectories
