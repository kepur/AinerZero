"""S1 start-up resource gate and runtime guard (pure CPU bookkeeping).

The gate is a *refusal* device: every registered protection line is measured
before a run is admitted, and any unmet line raises ``ResourceGateRefused`` with
one explicit reason per violation.  The runtime guard re-samples the same lines
while compute is running (the pilot worker convention: swap growth is measured
against the run-start baseline).  The duty cycle is checked twice: as a
configuration line on admission (``validate_limits``) and again by ``evaluate``
on every sample, so the runtime guard also refuses a loosened pace; the worker's
pacer then actually enforces it while training.

Registered lines (RESEARCH_LOG R20261021-P1-stageA-budget; unchanged):
process RSS <= 8 GiB, MLX <= 4 GiB, system available >= 16 GiB,
same-boot (run-start baseline) swap growth <= 1 GiB, duty cycle 0.25.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

import psutil

from . import spec

GIB = float(2**30)

REQUIRED_LIMIT_KEYS = (
    "process_memory_gib",
    "mlx_memory_gib",
    "system_reserve_gib",
    "swap_growth_gib",
    "training_duty_cycle",
    "disk_min_free_gib",
)


class ResourceGateRefused(RuntimeError):
    """The run may not start (or must stop) because a protection line is unmet."""

    def __init__(self, reasons: list[str], *, snapshot: dict | None = None):
        self.reasons = list(reasons)
        self.snapshot = dict(snapshot or {})
        super().__init__("; ".join(self.reasons))


def validate_limits(limits: Mapping[str, Any]) -> list[str]:
    """Validate a preregistered limit set: registered keys, tighten-only values."""
    reasons: list[str] = []
    if not isinstance(limits, Mapping):
        return ["resources must be an object"]
    missing = [key for key in REQUIRED_LIMIT_KEYS if key not in limits]
    extra = [key for key in limits if key not in REQUIRED_LIMIT_KEYS]
    if missing:
        reasons.append(f"resources missing required key(s) {missing}")
    if extra:
        reasons.append(f"resources carries unregistered key(s) {extra}")
    registered = spec.RESOURCE_LIMITS
    for key in REQUIRED_LIMIT_KEYS:
        if key in missing:
            continue
        value = limits[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            reasons.append(f"resources.{key} must be a finite number")
            continue
        if value <= 0:
            reasons.append(f"resources.{key} must be positive")
            continue
        cap = registered[key]
        if key == "system_reserve_gib":
            # A system reserve is a floor: raising it tightens, lowering it loosens.
            if value < cap:
                reasons.append(
                    f"resources.system_reserve_gib {value} is below registered {cap} "
                    "(loosening refused)"
                )
        elif value > cap:
            # Capacity lines are ceilings: lowering tightens, raising loosens.
            reasons.append(
                f"resources.{key} {value} exceeds registered {cap} (loosening refused)"
            )
    return reasons


@dataclass
class ResourceSnapshot:
    """One measurement of every registered line."""

    process_rss_bytes: float = 0.0
    mlx_active_bytes: float = 0.0
    mlx_peak_bytes: float = 0.0
    mlx_available: bool = False
    system_available_bytes: float = 0.0
    swap_used_bytes: float = 0.0
    swap_baseline_bytes: float = 0.0
    disk_free_bytes: float = 0.0
    measured_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "process_rss_gib": self.process_rss_bytes / GIB,
            "mlx_active_gib": self.mlx_active_bytes / GIB,
            "mlx_peak_gib": self.mlx_peak_bytes / GIB,
            "mlx_available": self.mlx_available,
            "system_available_gib": self.system_available_bytes / GIB,
            "swap_used_gib": self.swap_used_bytes / GIB,
            "swap_growth_gib": (self.swap_used_bytes - self.swap_baseline_bytes) / GIB,
            "disk_free_gib": self.disk_free_bytes / GIB,
            "measured_at": self.measured_at,
        }


def _process() -> psutil.Process:
    return psutil.Process()


def mlx_memory_probe() -> dict:
    """Best-effort MLX allocator probe; unavailable is reported, never invented."""
    try:
        import mlx.core as mx  # local import: the gate stays importable without MLX
    except Exception as exc:  # pragma: no cover - depends on host runtime
        return {"available": False, "active_bytes": 0.0, "peak_bytes": 0.0, "error": str(exc)}
    try:
        return {
            "available": True,
            "active_bytes": float(mx.get_active_memory()),
            "peak_bytes": float(mx.get_peak_memory()),
        }
    except Exception as exc:  # pragma: no cover - depends on host runtime
        return {"available": False, "active_bytes": 0.0, "peak_bytes": 0.0, "error": str(exc)}


def collect(
    *,
    root: str | object = ".",
    swap_baseline_bytes: float | None = None,
    mlx_probe: Callable[[], dict] | None = None,
    rss_probe: Callable[[], float] | None = None,
    memory_probe: Callable[[], Any] | None = None,
    swap_probe: Callable[[], Any] | None = None,
    disk_probe: Callable[[], float] | None = None,
) -> ResourceSnapshot:
    """Take one measurement; every probe is injectable for the negative tests."""
    rss = float(rss_probe()) if rss_probe else float(_process().memory_info().rss)
    mlx = mlx_probe() if mlx_probe else mlx_memory_probe()
    memory = memory_probe() if memory_probe else psutil.virtual_memory()
    swap = swap_probe() if swap_probe else psutil.swap_memory()
    free = float(disk_probe()) if disk_probe else float(psutil.disk_usage(str(root)).free)
    baseline = float(swap.used) if swap_baseline_bytes is None else float(swap_baseline_bytes)
    return ResourceSnapshot(
        process_rss_bytes=rss,
        mlx_active_bytes=float(mlx.get("active_bytes", 0.0)),
        mlx_peak_bytes=float(mlx.get("peak_bytes", 0.0)),
        mlx_available=bool(mlx.get("available", False)),
        system_available_bytes=float(memory.available),
        swap_used_bytes=float(swap.used),
        swap_baseline_bytes=baseline,
        disk_free_bytes=free,
    )


def evaluate(snapshot: ResourceSnapshot, limits: Mapping[str, Any]) -> list[str]:
    """Return every unmet line as an explicit refusal reason (empty = admitted)."""
    reasons: list[str] = []
    if snapshot.process_rss_bytes > float(limits["process_memory_gib"]) * GIB:
        reasons.append(
            "process_memory_limit: RSS "
            f"{snapshot.process_rss_bytes / GIB:.2f} GiB > {limits['process_memory_gib']} GiB"
        )
    mlx_cap = float(limits["mlx_memory_gib"]) * GIB
    if snapshot.mlx_active_bytes > mlx_cap:
        reasons.append(
            "mlx_memory_limit: active "
            f"{snapshot.mlx_active_bytes / GIB:.2f} GiB > {limits['mlx_memory_gib']} GiB"
        )
    if snapshot.mlx_peak_bytes > mlx_cap:
        reasons.append(
            "mlx_memory_limit: peak "
            f"{snapshot.mlx_peak_bytes / GIB:.2f} GiB > {limits['mlx_memory_gib']} GiB"
        )
    if snapshot.system_available_bytes < float(limits["system_reserve_gib"]) * GIB:
        reasons.append(
            "system_reserve_limit: available "
            f"{snapshot.system_available_bytes / GIB:.2f} GiB < {limits['system_reserve_gib']} GiB"
        )
    growth = snapshot.swap_used_bytes - snapshot.swap_baseline_bytes
    if growth > float(limits["swap_growth_gib"]) * GIB:
        reasons.append(
            "swap_growth_limit: growth "
            f"{growth / GIB:.2f} GiB > {limits['swap_growth_gib']} GiB"
        )
    if snapshot.disk_free_bytes < float(limits["disk_min_free_gib"]) * GIB:
        reasons.append(
            "disk_free_limit: free "
            f"{snapshot.disk_free_bytes / GIB:.2f} GiB < {limits['disk_min_free_gib']} GiB"
        )
    duty = float(limits["training_duty_cycle"])
    registered = float(spec.RESOURCE_LIMITS["training_duty_cycle"])
    if not 0.0 < duty <= registered:
        reasons.append(
            f"duty_cycle_limit: {duty} not in (0, {registered}] (registered pacing line)"
        )
    return reasons


def assert_start(
    limits: Mapping[str, Any],
    *,
    root: str | object = ".",
    swap_baseline_bytes: float | None = None,
    probes: Mapping[str, Any] | None = None,
) -> ResourceSnapshot:
    """Raise ``ResourceGateRefused`` unless every registered line is met."""
    reasons = validate_limits(limits)
    if reasons:
        raise ResourceGateRefused(reasons)
    snapshot = collect(root=root, swap_baseline_bytes=swap_baseline_bytes, **(probes or {}))
    reasons = evaluate(snapshot, limits)
    if reasons:
        raise ResourceGateRefused(reasons, snapshot=snapshot.to_dict())
    return snapshot


class RuntimeGuard:
    """Sample the protection lines during compute; stop on the first violation."""

    def __init__(
        self,
        limits: Mapping[str, Any],
        *,
        root: str | object = ".",
        initial_swap_bytes: float | None = None,
        min_interval_seconds: float = 1.0,
        probes: Mapping[str, Any] | None = None,
    ):
        self.limits = dict(limits)
        self.root = root
        self.initial_swap_bytes = initial_swap_bytes
        self.min_interval_seconds = float(min_interval_seconds)
        self._probes = dict(probes or {})
        self._last = 0.0
        self.samples: list[dict] = []
        self.peak_rss_bytes = 0.0
        self.peak_mlx_bytes = 0.0

    def sample(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        if not force and now - self._last < self.min_interval_seconds:
            return self.samples[-1] if self.samples else {}
        self._last = now
        snapshot = collect(root=self.root, swap_baseline_bytes=self.initial_swap_bytes, **self._probes)
        self.peak_rss_bytes = max(self.peak_rss_bytes, snapshot.process_rss_bytes)
        self.peak_mlx_bytes = max(
            self.peak_mlx_bytes, snapshot.mlx_active_bytes, snapshot.mlx_peak_bytes
        )
        reasons = evaluate(snapshot, self.limits)
        row = snapshot.to_dict()
        row["reasons"] = reasons
        self.samples.append(row)
        if reasons:
            raise ResourceGateRefused(reasons, snapshot=row)
        return row
