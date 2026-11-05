"""E1 Biased Physical Prior Integrator (pure NumPy / CPU).

Specification (reports/V9-P48/E1_IMPLEMENTATION_PLAN.md):
- 600 Hz semi-implicit Euler (10 substeps per 60 fps frame, dt = 1/600 s).
- Gravity g = (0, 0, -9.81) m/s^2 (Z-up coordinate system).
- Linear and angular damping.
- Contact impulses against static bodies (Ground plane, inclined Ramp, Table top, Occluder).
  Coulomb friction and restitution.
- Inter-body contacts using bounding-sphere approximation.
- Registered structural bias: bounding-sphere collision geometry, zero rolling friction,
  zero air drag. This forms the biased prior F_prior.
- Parameter vector phi for each active body:
  (friction, restitution, mass, linear_damping, angular_damping)
  Default biased prior phi_hat_0 = (0.50, 0.45, 2.60, 0.125, 0.125).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

# --- Simulation Constants ---
GRAVITY_ACCEL: float = 9.81
DEFAULT_FPS: int = 60
DEFAULT_SUBSTEPS: int = 10
SUBSTEP_DT: float = 1.0 / (DEFAULT_FPS * DEFAULT_SUBSTEPS)  # 1/600 s = 0.001666667 s


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


@dataclass
class ActiveBody:
    """State and bounding sphere of an active dynamic body."""

    name: str
    radius: float  # bounding sphere radius in meters
    params: PhysicalParameters
    position: np.ndarray  # (3,)
    velocity: np.ndarray  # (3,)
    angular_velocity: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float64))

    def copy(self) -> ActiveBody:
        return ActiveBody(
            name=self.name,
            radius=self.radius,
            params=self.params.copy(),
            position=np.array(self.position, dtype=np.float64, copy=True),
            velocity=np.array(self.velocity, dtype=np.float64, copy=True),
            angular_velocity=np.array(self.angular_velocity, dtype=np.float64, copy=True),
        )


@dataclass
class GroundPlane:
    """Infinite static ground plane at z=z_plane with normal (0, 0, 1)."""

    z_plane: float = 0.0
    friction: float = 0.50
    restitution: float = 0.30


@dataclass
class InclinedRamp:
    """Static inclined ramp surface.

    Defined by a plane passing through center_point with normal vector.
    bounds_xy optionally limits the ramp extents in local/world coordinates.
    """

    point: np.ndarray  # (3,) point on the plane
    normal: np.ndarray  # (3,) unit normal pointing outwards
    friction: float = 0.25
    restitution: float = 0.25
    x_bounds: tuple[float, float] | None = None
    y_bounds: tuple[float, float] | None = None


@dataclass
class TableTop:
    """Static horizontal table top surface at z=z_top with rectangular bounds."""

    z_top: float
    x_bounds: tuple[float, float]
    y_bounds: tuple[float, float]
    friction: float = 0.20
    restitution: float = 0.35


@dataclass
class StaticEnvironment:
    """Collection of static obstacles."""

    ground: GroundPlane | None = field(default_factory=GroundPlane)
    ramps: list[InclinedRamp] = field(default_factory=list)
    tables: list[TableTop] = field(default_factory=list)


def step_substep(
    bodies: list[ActiveBody],
    env: StaticEnvironment,
    dt: float = SUBSTEP_DT,
    g: float = GRAVITY_ACCEL,
) -> None:
    """Advance the physical simulation by a single 600 Hz substep (semi-implicit Euler)."""
    # 1. Continuous forces (Gravity + Damping) -> update velocity
    for b in bodies:
        m = max(b.params.mass, 1e-6)
        # Acceleration: gravity + linear damping
        a_lin = np.array([0.0, 0.0, -g], dtype=np.float64) - b.params.linear_damping * b.velocity
        b.velocity += a_lin * dt

        # Angular damping
        a_ang = -b.params.angular_damping * b.angular_velocity
        b.angular_velocity += a_ang * dt

    # 2. Collisions with static environment
    for b in bodies:
        # Ground plane collision
        if env.ground is not None:
            # Distance from body center to ground
            z_surf = env.ground.z_plane
            dist = b.position[2] - z_surf - b.radius
            if dist < 0.0:
                # Penetration or contact
                vn = b.velocity[2]
                if vn < 0.0:
                    e = min(b.params.restitution, env.ground.restitution)
                    # Normal impulse
                    b.velocity[2] = -e * vn

                    # Tangential Coulomb friction
                    vt = np.array([b.velocity[0], b.velocity[1], 0.0], dtype=np.float64)
                    vt_norm = np.linalg.norm(vt)
                    if vt_norm > 1e-9:
                        mu = 0.5 * (b.params.friction + env.ground.friction)
                        max_vt_drop = mu * (1.0 + e) * abs(vn)
                        if max_vt_drop >= vt_norm:
                            b.velocity[0] = 0.0
                            b.velocity[1] = 0.0
                        else:
                            ratio = (vt_norm - max_vt_drop) / vt_norm
                            b.velocity[0] *= ratio
                            b.velocity[1] *= ratio

                # Position correction to resolve penetration
                b.position[2] = z_surf + b.radius

        # Table top collision
        for table in env.tables:
            if table.x_bounds[0] <= b.position[0] <= table.x_bounds[1] and (
                table.y_bounds[0] <= b.position[1] <= table.y_bounds[1]
            ):
                dist = b.position[2] - table.z_top - b.radius
                if dist < 0.0:
                    vn = b.velocity[2]
                    if vn < 0.0:
                        e = min(b.params.restitution, table.restitution)
                        b.velocity[2] = -e * vn

                        vt = np.array([b.velocity[0], b.velocity[1], 0.0], dtype=np.float64)
                        vt_norm = np.linalg.norm(vt)
                        if vt_norm > 1e-9:
                            mu = 0.5 * (b.params.friction + table.friction)
                            max_vt_drop = mu * (1.0 + e) * abs(vn)
                            if max_vt_drop >= vt_norm:
                                b.velocity[0] = 0.0
                                b.velocity[1] = 0.0
                            else:
                                ratio = (vt_norm - max_vt_drop) / vt_norm
                                b.velocity[0] *= ratio
                                b.velocity[1] *= ratio
                    b.position[2] = table.z_top + b.radius

        # Inclined ramp collision
        for ramp in env.ramps:
            # Check xy bounds if specified
            in_bounds = True
            if ramp.x_bounds is not None:
                in_bounds = in_bounds and (ramp.x_bounds[0] <= b.position[0] <= ramp.x_bounds[1])
            if ramp.y_bounds is not None:
                in_bounds = in_bounds and (ramp.y_bounds[0] <= b.position[1] <= ramp.y_bounds[1])

            if in_bounds:
                n = ramp.normal / np.linalg.norm(ramp.normal)
                # Distance to ramp plane
                plane_dist = np.dot(b.position - ramp.point, n)
                surf_dist = plane_dist - b.radius
                if surf_dist < 0.0:
                    vn = np.dot(b.velocity, n)
                    if vn < 0.0:
                        e = min(b.params.restitution, ramp.restitution)
                        # Normal impulse
                        delta_vn = -(1.0 + e) * vn
                        # Tangential velocity
                        v_tangent = b.velocity - vn * n
                        vt_norm = np.linalg.norm(v_tangent)

                        b.velocity += delta_vn * n

                        if vt_norm > 1e-9:
                            mu = 0.5 * (b.params.friction + ramp.friction)
                            max_vt_drop = mu * (1.0 + e) * abs(vn)
                            if max_vt_drop >= vt_norm:
                                b.velocity -= v_tangent
                            else:
                                b.velocity -= (max_vt_drop / vt_norm) * v_tangent

                    # Position correction along normal
                    b.position -= surf_dist * n

    # 3. Inter-body collisions (Bounding sphere approximation)
    n_bodies = len(bodies)
    for i in range(n_bodies):
        for j in range(i + 1, n_bodies):
            b1 = bodies[i]
            b2 = bodies[j]

            r_vec = b2.position - b1.position
            dist = np.linalg.norm(r_vec)
            r_sum = b1.radius + b2.radius

            if dist < r_sum and dist > 1e-9:
                n = r_vec / dist
                v_rel = b2.velocity - b1.velocity
                vn = np.dot(v_rel, n)

                if vn < 0.0:
                    # Closing in
                    e = min(b1.params.restitution, b2.params.restitution)
                    m1 = max(b1.params.mass, 1e-6)
                    m2 = max(b2.params.mass, 1e-6)
                    m_eff = (m1 * m2) / (m1 + m2)

                    impulse_mag = -(1.0 + e) * vn * m_eff
                    b1.velocity -= (impulse_mag / m1) * n
                    b2.velocity += (impulse_mag / m2) * n

                    # Tangential friction
                    v_rel_after = b2.velocity - b1.velocity
                    v_tangent = v_rel_after - np.dot(v_rel_after, n) * n
                    vt_norm = np.linalg.norm(v_tangent)
                    if vt_norm > 1e-9:
                        mu = 0.5 * (b1.params.friction + b2.params.friction)
                        max_fric_impulse = mu * impulse_mag
                        needed_impulse = m_eff * vt_norm
                        actual_fric_impulse = min(max_fric_impulse, needed_impulse)

                        t_dir = v_tangent / vt_norm
                        b1.velocity += (actual_fric_impulse / m1) * t_dir
                        b2.velocity -= (actual_fric_impulse / m2) * t_dir

                # Position separation (penetration resolution)
                overlap = r_sum - dist
                m1 = max(b1.params.mass, 1e-6)
                m2 = max(b2.params.mass, 1e-6)
                w1 = m2 / (m1 + m2)
                w2 = m1 / (m1 + m2)
                b1.position -= w1 * overlap * n
                b2.position += w2 * overlap * n

    # 4. Position update (semi-implicit Euler)
    for b in bodies:
        b.position += b.velocity * dt


def simulate_frame(
    bodies: list[ActiveBody],
    env: StaticEnvironment,
    substeps: int = DEFAULT_SUBSTEPS,
    dt: float = SUBSTEP_DT,
    g: float = GRAVITY_ACCEL,
) -> None:
    """Advance the physical simulation by 1 frame (substeps * dt)."""
    for _ in range(substeps):
        step_substep(bodies, env, dt=dt, g=g)


def rollout(
    bodies: Sequence[ActiveBody],
    env: StaticEnvironment,
    num_frames: int,
    substeps: int = DEFAULT_SUBSTEPS,
    dt: float = SUBSTEP_DT,
    g: float = GRAVITY_ACCEL,
) -> dict[str, np.ndarray]:
    """Roll out physical simulation for num_frames at 60 fps (each frame having substeps).

    Returns:
        dict mapping body names to trajectory arrays of shape (num_frames + 1, 6)
        containing [x, y, z, vx, vy, vz].
    """
    sim_bodies = [b.copy() for b in bodies]

    trajectories = {
        b.name: np.zeros((num_frames + 1, 6), dtype=np.float64) for b in sim_bodies
    }

    # Record frame 0
    for b in sim_bodies:
        trajectories[b.name][0, 0:3] = b.position
        trajectories[b.name][0, 3:6] = b.velocity

    # Step through frames
    for frame_idx in range(1, num_frames + 1):
        simulate_frame(sim_bodies, env, substeps=substeps, dt=dt, g=g)
        for b in sim_bodies:
            trajectories[b.name][frame_idx, 0:3] = b.position
            trajectories[b.name][frame_idx, 3:6] = b.velocity

    return trajectories
