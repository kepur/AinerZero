"""CMFL frozen registration, parameter belief store, route records, and chi2 utilities.

Pure NumPy and Python standard library only; no MLX, SciPy, or learned models.
Implements ADR-0014 r3 §2 D1 (M5/M8) and §3 C5/C7 (R1).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


class RouteCode(str, Enum):
    """8-route decision codes for Mechanism Sufficiency Gate (ADR-0014 §2 D1)."""

    ABSTAIN = "ABSTAIN"
    OUT_OF_DOMAIN = "OUT_OF_DOMAIN"
    NUMERICAL = "NUMERICAL"
    COVARIANCE_INCONSISTENT = "COVARIANCE_INCONSISTENT"  # 4a: lower-tail NIS < chi2(alpha_s/2)
    SUFFICIENT = "SUFFICIENT"  # 4b: NIS within [chi2(alpha_s/2), chi2(1-alpha_s/2)]
    PARAMETRIC = "PARAMETRIC"
    UNIDENTIFIABLE = "UNIDENTIFIABLE"
    STRUCTURAL = "STRUCTURAL"


ROUTE_PRIORITY: tuple[RouteCode, ...] = (
    RouteCode.ABSTAIN,
    RouteCode.OUT_OF_DOMAIN,
    RouteCode.NUMERICAL,
    RouteCode.COVARIANCE_INCONSISTENT,
    RouteCode.SUFFICIENT,
    RouteCode.PARAMETRIC,
    RouteCode.UNIDENTIFIABLE,
    RouteCode.STRUCTURAL,
)


# ---------------------------------------------------------------------------
# Pure Python/NumPy Chi-Square CDF & Quantile (PPF) without SciPy
# ---------------------------------------------------------------------------

def _gammainc_reg(a: float, x: float) -> float:
    """Regularized lower incomplete gamma P(a, x) = gamma(a, x) / Gamma(a)."""
    if x <= 0.0:
        return 0.0
    if a <= 0.0:
        raise ValueError("shape parameter a must be positive")
    if x < a + 1.0:
        # Series expansion
        ap = a
        total = 1.0 / a
        delta = total
        for _ in range(500):
            ap += 1.0
            delta *= x / ap
            total += delta
            if abs(delta) < abs(total) * 1e-15:
                break
        log_prefactor = -x + a * math.log(x) - math.lgamma(a)
        if log_prefactor < -700.0:
            return 0.0
        return min(1.0, max(0.0, total * math.exp(log_prefactor)))
    else:
        # Lentz's continued fraction for Q(a, x) = 1 - P(a, x)
        b = x + 1.0 - a
        c = 1.0 / 1e-30
        d = 1.0 / b
        h = d
        for i in range(1, 500):
            an = -i * (i - a)
            b += 2.0
            d = an * d + b
            if abs(d) < 1e-30:
                d = 1e-30
            c = b + an / c
            if abs(c) < 1e-30:
                c = 1e-30
            d = 1.0 / d
            delta = d * c
            h *= delta
            if abs(delta - 1.0) < 1e-15:
                break
        log_prefactor = -x + a * math.log(x) - math.lgamma(a)
        if log_prefactor < -700.0:
            return 1.0
        q_val = h * math.exp(log_prefactor)
        return min(1.0, max(0.0, 1.0 - q_val))


def _norm_ppf(p: float) -> float:
    """Acklam's rational approximation + 1 Halley step for standard normal quantile."""
    if not (0.0 < p < 1.0):
        raise ValueError("probability p must be in (0, 1)")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        z = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        z = (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        z = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    # One Newton refinement using math.erfc
    cdf = 0.5 * math.erfc(-z / math.sqrt(2.0))
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    z -= (cdf - p) / pdf
    return z


def chi2_cdf(x: float, dof: int) -> float:
    """Cumulative distribution function of chi-square(dof) at x."""
    if dof < 1:
        raise ValueError("dof must be a positive integer")
    if x <= 0.0:
        return 0.0
    return _gammainc_reg(0.5 * dof, 0.5 * x)


def chi2_ppf(p: float, dof: int) -> float:
    """Quantile (inverse CDF) of chi-square(dof) at probability p in (0, 1)."""
    if dof < 1:
        raise ValueError("dof must be a positive integer")
    if not (0.0 < p < 1.0):
        raise ValueError("probability p must be in (0, 1)")
    # Wilson-Hilferty initial guess
    z = _norm_ppf(p)
    h = 2.0 / (9.0 * dof)
    cube_root = 1.0 - h + z * math.sqrt(h)
    x = max(1e-6, float(dof) * (max(0.05, cube_root) ** 3))
    a = 0.5 * dof
    log_norm = a * math.log(2.0) + math.lgamma(a)
    for _ in range(40):
        err = chi2_cdf(x, dof) - p
        if abs(err) < 1e-13:
            break
        log_pdf = (a - 1.0) * math.log(max(x, 1e-300)) - 0.5 * x - log_norm
        pdf = math.exp(max(-700.0, log_pdf))
        if pdf <= 1e-300:
            break
        step = err / pdf
        x_next = x - step
        while x_next <= 0.0:
            step *= 0.5
            x_next = x - step
        x = x_next
    return float(x)


# ---------------------------------------------------------------------------
# D_permit Specification (ADR-0014 §2 D1 M8 & §2 D5)
# ---------------------------------------------------------------------------

FORBIDDEN_NEGATIVE_KNOWLEDGE_KEYS = frozenset(
    {
        "no_unknown_mechanism_region",
        "known_sufficient_region",
        "true_mechanism_hint",
        "eval_world_override",
        "skip_structural_discovery_region",
    }
)


@dataclass(frozen=True)
class DPermitSpec:
    """Boundary teacher D_permit specification with M8 provenance audit."""

    version: str
    allowed_variables: tuple[str, ...]
    position_limit: float
    speed_limit: float
    action_limit: float
    provenance_issuer: str
    provenance_basis: str
    provenance_data_sha: str
    extra_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.version or not self.provenance_issuer or not self.provenance_basis or not self.provenance_data_sha:
            raise ValueError("D_permit provenance fields (version, issuer, basis, data_sha) must be non-empty")
        if "test" in self.provenance_basis.lower() or "eval_world" in self.provenance_basis.lower():
            raise ValueError("D_permit provenance must not touch test set T or evaluation world config (M8)")
        forbidden_found = set(self.extra_metadata.keys()) & FORBIDDEN_NEGATIVE_KNOWLEDGE_KEYS
        if forbidden_found:
            raise ValueError(
                f"D_permit must not encode negative world knowledge ('no unknown mechanism in region'): {sorted(forbidden_found)}"
            )
        if self.position_limit <= 0 or self.speed_limit <= 0 or self.action_limit <= 0:
            raise ValueError("D_permit physical safety bounds must be positive")


# ---------------------------------------------------------------------------
# CMFL Frozen Registration (ADR-0014 §2 D1 M5 & §3 C5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CMFLRegistration:
    """Complete frozen CMFL configuration (ADR-0014 §2 D1 M5, 12 discovery/promotion items)."""

    registration_id: str
    # 1. MSG routing parameters
    alpha_s: float
    kappa: float
    tau_id: float
    tau_H: float
    K: int
    W: int
    tau_decorr: int
    integrators: tuple[str, ...]
    dt_set: tuple[float, ...]
    d_permit: DPermitSpec
    # 2. Discovery & promotion parameters (all 12 items from ADR-0014 §2 D1-2 / M5)
    delta_gain: float
    alpha_seq: float
    gamma_schedule: tuple[float, ...]
    N_max: int
    alpha_dom: float
    r_fpca: int
    alpha_audit: float
    n_min: int
    lambda_grid: tuple[float, ...]
    K_bet: int
    env_families: tuple[str, ...]
    B_boot: int
    rng_seed: int
    M_in: int
    M_out: int
    tau_cal: float
    delta_cal: float
    n_cal_min: int
    # 3. Single-authority SHA reference to r5 frozen baseline (never duplicated/overridden)
    r5_baseline_ref_sha: str

    def __post_init__(self) -> None:
        if not (0.0 < self.alpha_s < 1.0):
            raise ValueError("alpha_s must be in (0, 1)")
        if self.kappa <= 0.0 or self.tau_id <= 0.0 or self.tau_H <= 0.0:
            raise ValueError("kappa, tau_id, tau_H must be positive")
        if self.K < 1 or self.W < 2 or self.tau_decorr < 1:
            raise ValueError("K >= 1, W >= 2, tau_decorr >= 1 required")
        if self.delta_gain <= 0.0:
            raise ValueError("delta_gain must be positive")
        if not (0.0 < self.alpha_seq < 1.0) or not (0.0 < self.alpha_dom < 1.0) or not (0.0 < self.alpha_audit < 1.0):
            raise ValueError("alpha_seq, alpha_dom, alpha_audit must be in (0, 1)")
        if not self.gamma_schedule or any(g < 0.0 for g in self.gamma_schedule) or sum(self.gamma_schedule) > 1.0 + 1e-12:
            raise ValueError("gamma_schedule must be non-negative and sum to <= 1")
        if self.N_max < 1 or self.r_fpca < 1 or self.n_min < 1:
            raise ValueError("N_max, r_fpca, n_min must be >= 1")
        if len(self.lambda_grid) != self.K_bet or any(not (0.0 < lam < 1.0) for lam in self.lambda_grid):
            raise ValueError("lambda_grid length must equal K_bet and values must be in (0, 1)")
        if not self.env_families:
            raise ValueError("env_families must be non-empty")
        if self.B_boot < 10 or self.M_in < 2 or self.M_out < 2:
            raise ValueError("B_boot >= 10, M_in >= 2, M_out >= 2 required")
        if not (0.0 < self.tau_cal < 1.0) or not (0.0 < self.delta_cal < 1.0) or self.n_cal_min < 1:
            raise ValueError("FactTest parameters (tau_cal, delta_cal, n_cal_min) invalid")
        if not self.r5_baseline_ref_sha or len(self.r5_baseline_ref_sha) < 16:
            raise ValueError("r5_baseline_ref_sha must be a valid SHA reference string")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"

    def registration_sha(self) -> str:
        canonical = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def save_json(self, path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return self.registration_sha()


def default_cmfl_registration() -> CMFLRegistration:
    """Default frozen CMFL registration for G7 toy mechanics evaluation."""
    weights = tuple(6.0 / ((math.pi * (i + 1)) ** 2) for i in range(32))
    return CMFLRegistration(
        registration_id="cmfl-v9-g7-toy-v1",
        alpha_s=0.05,
        kappa=0.25,
        tau_id=1.5,
        tau_H=0.65,
        K=3,
        W=20,
        tau_decorr=20,
        integrators=("euler", "rk2", "rk4"),
        dt_set=(0.04, 0.01, 0.005),
        d_permit=DPermitSpec(
            version="d-permit-v1",
            allowed_variables=("x", "y", "vx", "vy", "ux", "uy"),
            position_limit=15.0,
            speed_limit=20.0,
            action_limit=12.0,
            provenance_issuer="boundary-teacher-v1",
            provenance_basis="actuator_hardware_limits_and_workspace_spec_only",
            provenance_data_sha="a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
        ),
        delta_gain=0.01,
        alpha_seq=0.05,
        gamma_schedule=weights,
        N_max=8,
        alpha_dom=0.05,
        r_fpca=2,
        alpha_audit=0.05,
        n_min=5,
        lambda_grid=(0.15, 0.30, 0.50, 0.70),
        K_bet=4,
        env_families=("P_family", "S_family", "altered_law_family"),
        B_boot=400,
        rng_seed=20261028,
        M_in=32,
        M_out=48,
        tau_cal=0.10,
        delta_cal=0.05,
        n_cal_min=8,
        r5_baseline_ref_sha="V9-r5-20261016-sha256-ref-only",
    )


# ---------------------------------------------------------------------------
# Standalone Parameter Belief & Store (ADR-0014 §3 C7 / R1 Option b)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParamBelief:
    """Frozen Gaussian belief over physical parameters phi (ADR-0014 §3 C7-i).

    Stored in ParamBeliefStore; NEVER placed in UpdateScheduler.update(belief=...).
    """

    mean: np.ndarray
    cov: np.ndarray
    dimensionless_scale: np.ndarray
    updated_at_ticks: int = 0
    param_names: tuple[str, ...] = ("g", "c_lin", "k_spring")

    def __post_init__(self) -> None:
        m = np.array(self.mean, dtype=float, copy=True)
        c = np.array(self.cov, dtype=float, copy=True)
        s = np.array(self.dimensionless_scale, dtype=float, copy=True)
        if m.ndim != 1 or m.size == 0 or not np.isfinite(m).all():
            raise ValueError("ParamBelief.mean must be a finite 1D vector")
        p = m.size
        if c.shape != (p, p) or not np.isfinite(c).all():
            raise ValueError("ParamBelief.cov must be a finite (p, p) matrix")
        if not np.allclose(c, c.T, atol=1e-12):
            raise ValueError("ParamBelief.cov must be symmetric")
        c = 0.5 * (c + c.T)
        if np.linalg.eigvalsh(c)[0] <= 0.0:
            raise ValueError("ParamBelief.cov must be positive definite")
        if s.shape != (p,) or not np.isfinite(s).all() or np.any(s <= 0.0):
            raise ValueError("ParamBelief.dimensionless_scale must be positive 1D vector of length p")
        if len(self.param_names) != p:
            raise ValueError("param_names length must match mean dimension")
        m.setflags(write=False)
        c.setflags(write=False)
        s.setflags(write=False)
        object.__setattr__(self, "mean", m)
        object.__setattr__(self, "cov", c)
        object.__setattr__(self, "dimensionless_scale", s)

    @property
    def dim(self) -> int:
        return int(self.mean.size)

    def nees(self, true_phi: Sequence[float] | np.ndarray) -> float:
        """Normalized Estimation Error Squared (evaluation-side calibration metric only)."""
        err = np.asarray(true_phi, dtype=float) - self.mean
        if err.shape != self.mean.shape:
            raise ValueError("true_phi dimension mismatch")
        return float(err @ np.linalg.solve(self.cov, err))


class ParamBeliefStore:
    """Learning-side container for ParamBelief (ADR-0014 §3 C7-i, R1 Option b).

    Completely separate from UpdateScheduler's node belief Mapping and BeliefSummary.
    """

    def __init__(self) -> None:
        self._store: dict[str, ParamBelief] = {}

    def get(self, scope_id: str) -> ParamBelief | None:
        return self._store.get(scope_id)

    def require(self, scope_id: str) -> ParamBelief:
        if scope_id not in self._store:
            raise KeyError(f"parameter belief for scope {scope_id!r} not found")
        return self._store[scope_id]

    def put(self, scope_id: str, belief: ParamBelief) -> None:
        if not isinstance(belief, ParamBelief):
            raise TypeError(f"ParamBeliefStore only accepts ParamBelief, got {type(belief).__name__}")
        self._store[str(scope_id)] = belief

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._store.keys()))


@dataclass(frozen=True)
class MSGRouteRecord:
    """Frozen route record emitted on every MSG decision (ADR-0014 §3 C7-ii)."""

    context_id: str
    t_ticks: int
    route_code: RouteCode
    reason: str
    nis_stat: float
    dof: int
    registration_sha: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "t_ticks": int(self.t_ticks),
            "route_code": self.route_code.value,
            "reason": self.reason,
            "nis_stat": float(self.nis_stat),
            "dof": int(self.dof),
            "registration_sha": self.registration_sha,
        }
