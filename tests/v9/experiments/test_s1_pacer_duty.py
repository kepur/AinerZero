"""Duty-cycle enforcement tests (V9.P10 F2).

Two separate guarantees are covered behaviourally, not by reading the source:

1. the worker's pacer actually sleeps to hold the registered 0.25 duty cycle
   (``worker._train`` driven with fake MLX/optimizer/clock objects), and
2. ``resource_gate.evaluate`` refuses a duty cycle above the registered line, so
   the runtime guard cannot be loosened even if the start-up config check is
   bypassed.

Deleting the pacer (P10 M1) or disabling the duty branch (P10 M2) turns these
red.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import arms, resource_gate, spec, worker

pytestmark = pytest.mark.native_mlx(reason="real MLX import at collection via s1.arms (A39)")

GIB = float(2**30)


class _FakeClock:
    """Deterministic clock: every perf_counter call advances by ``step``."""

    def __init__(self, step: float = 0.02):
        self.step = float(step)
        self.now = 0.0
        self.sleeps: list[float] = []

    def perf_counter(self) -> float:
        self.now += self.step
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.now += float(seconds)


class _FakeLedger:
    def __init__(self):
        self.reservations: list[tuple[float, int]] = []

    def reserve(self, run_id, *, active_seconds, optimizer_steps=0):
        self.reservations.append((float(active_seconds), int(optimizer_steps)))


class _FakeGuard:
    def __init__(self):
        self.calls = 0

    def sample(self, **kwargs):
        self.calls += 1
        return {}


class _FakeOptimizer:
    def __init__(self, **kwargs):
        self.state: dict = {}

    def init(self, parameters):
        return None

    def update(self, model, gradients):
        return None


class _FakeModel:
    ARCHITECTURE = "fake_pacer_model"

    def trainable_parameters(self):
        return {}

    def parameters(self):
        return {}

    def forward_loss(self, batch):  # pragma: no cover - the pacer never forwards
        raise AssertionError("forward must not be called in the pacer test")


def _document(duty: float) -> dict:
    return {
        "training_protocol": {
            "updates": 2,
            "seeds": [0],
            "learning_rate": 3e-4,
            "adam_betas": (0.9, 0.999),
            "adam_epsilon": 1e-8,
            "weight_decay": 0.01,
            "gradient_clip_norm": 1.0,
            "batch_size": 2,
            "checkpoint_updates": [],
        },
        "timing": {"deadline_seconds": 450.0},
        "resource_limits": {**spec.RESOURCE_LIMITS, "training_duty_cycle": duty},
    }


def _install_fakes(monkeypatch, clock: _FakeClock, dataset_dir):
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim

    monkeypatch.setattr(worker, "time", clock)
    monkeypatch.setattr(worker.data, "resolve_dataset_dir", lambda root: dataset_dir)
    monkeypatch.setattr(worker.data, "load_training_windows", lambda *a, **k: {"obs": np.zeros((4, 2, 72))})
    monkeypatch.setattr(worker.data, "load_development_windows", lambda *a, **k: {"obs": np.zeros((1, 2, 72))})
    monkeypatch.setattr(worker.data, "iter_batches", lambda *a, **k: iter([{"obs": None}] * 32))
    # worker imports ``arms`` inside _train; patching the module object is enough.
    monkeypatch.setattr(arms, "build_trainable_arm", lambda arm_id, seed: _FakeModel())
    monkeypatch.setattr(arms, "parameter_sha256", lambda model: "0" * 64)
    monkeypatch.setattr(
        nn, "value_and_grad", lambda model, loss: (lambda m, batch: ((np.float32(1.0), {}), {}))
    )
    monkeypatch.setattr(optim, "AdamW", _FakeOptimizer)
    monkeypatch.setattr(optim, "clip_grad_norm", lambda grads, norm: (grads, 1.0), raising=False)
    monkeypatch.setattr(mx, "eval", lambda *args, **kwargs: None)
    monkeypatch.setattr(mx, "set_default_device", lambda *args, **kwargs: None, raising=False)


@pytest.mark.parametrize("duty,expected_sleep", [(0.25, 0.06), (0.5, 0.02), (0.1, 0.18)])
def test_pacer_sleeps_to_hold_the_duty_cycle(monkeypatch, tmp_path, duty, expected_sleep):
    clock = _FakeClock(step=0.02)
    _install_fakes(monkeypatch, clock, tmp_path)
    result = worker._train(_document(duty), tmp_path, _FakeLedger(), "run-1", _FakeGuard(), arm_id="arm2", seed=0)

    # In r4, each run is 1 arm x 1 seed x 2 updates, one sleep per update, each sized from the
    # measured active step (0.02 s) and the configured duty.
    assert result["arm_id"] == "arm2"
    assert result["status"] == "completed"
    assert len(clock.sleeps) == 2, "the pacer did not sleep between updates"
    assert all(value == pytest.approx(expected_sleep) for value in clock.sleeps)


def test_pacer_records_the_registered_duty_cycle_only(monkeypatch, tmp_path):
    clock = _FakeClock(step=0.02)
    _install_fakes(monkeypatch, clock, tmp_path)
    worker._train(_document(0.25), tmp_path, _FakeLedger(), "run-1", _FakeGuard(), arm_id="arm2", seed=0)
    # active = 0.02 s per update -> resting time = active * (1/duty - 1) = 3x active.
    active_total = 2 * 0.02
    assert sum(clock.sleeps) == pytest.approx(active_total * 3.0)


def _snapshot(**overrides) -> resource_gate.ResourceSnapshot:
    base = dict(
        process_rss_bytes=1.0 * GIB,
        mlx_active_bytes=0.0,
        mlx_peak_bytes=0.0,
        mlx_available=True,
        system_available_bytes=64.0 * GIB,
        swap_used_bytes=0.0,
        swap_baseline_bytes=0.0,
        disk_free_bytes=200.0 * GIB,
    )
    base.update(overrides)
    return resource_gate.ResourceSnapshot(**base)


@pytest.mark.parametrize("duty", [0.5, 1.0, 0.2500001])
def test_evaluate_refuses_a_loosened_duty_cycle(duty):
    limits = {**spec.RESOURCE_LIMITS, "training_duty_cycle": duty}
    reasons = resource_gate.evaluate(_snapshot(), limits)
    assert any("duty_cycle_limit" in reason for reason in reasons), reasons


@pytest.mark.parametrize("duty", [0.0, -0.25])
def test_evaluate_refuses_a_nonpositive_duty_cycle(duty):
    limits = {**spec.RESOURCE_LIMITS, "training_duty_cycle": duty}
    reasons = resource_gate.evaluate(_snapshot(), limits)
    assert any("duty_cycle_limit" in reason for reason in reasons), reasons


def test_evaluate_admits_the_registered_duty_cycle():
    reasons = resource_gate.evaluate(_snapshot(), dict(spec.RESOURCE_LIMITS))
    assert not any("duty_cycle_limit" in reason for reason in reasons)


def test_runtime_guard_refuses_a_loosened_duty_cycle(monkeypatch):
    """The duty line is reachable at runtime, not only in the start-up config check."""
    limits = {**spec.RESOURCE_LIMITS, "training_duty_cycle": 0.5}
    guard = resource_gate.RuntimeGuard(
        limits,
        root=".",
        probes={
            "rss_probe": lambda: 1.0 * GIB,
            "mlx_probe": lambda: {"available": True, "active_bytes": 0.0, "peak_bytes": 0.0},
            "memory_probe": lambda: type("M", (), {"available": 64.0 * GIB})(),
            "swap_probe": lambda: type("S", (), {"used": 0.0})(),
            "disk_probe": lambda: 200.0 * GIB,
        },
    )
    with pytest.raises(resource_gate.ResourceGateRefused) as excinfo:
        guard.sample(force=True)
    assert any("duty_cycle_limit" in reason for reason in excinfo.value.reasons)
