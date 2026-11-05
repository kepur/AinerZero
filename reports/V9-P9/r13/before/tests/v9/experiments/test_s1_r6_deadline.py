"""r6 final-wall-clock deadline tests (P15 item 2).

The r5 loop checked the frozen per-run deadline only at the top of the update
loop.  Everything after the final loop-top check -- the last gradient, the final
checkpoint probe/save, the duty sleep and the trailing receipt/metadata IO --
could therefore run past the 450 s deadline and still report ``completed``.

These tests drive the **real** ``worker._train`` loop with the registered
``updates = 3510`` and a scripted clock (never a shortened loop, never an extra
3511st step).  Each scenario makes exactly one late phase cross the deadline and
asserts the run aborts with ``TimeoutError`` before any authoritative receipt or
ledger completion exists, plus the exactly-at-boundary and near-boundary cases
that must still complete normally.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import data, spec, worker

from s1_testkit import frozen_document

UPDATES = 3510
DEADLINE = 450.0
DUTY = float(spec.RESOURCE_LIMITS["training_duty_cycle"])
CLOCK_START = 1_000.0
# Per-update active cost modelled by the gradient hook; small enough that the
# 3509 pre-final updates stay far inside the deadline.
PER_UPDATE_ACTIVE = 0.03


class _ScriptedClock:
    """Fake wall clock: only explicit advances move time forward.

    ``perf_counter`` reports the current value; hooks decide when time passes,
    which keeps every boundary scenario deterministic.  ``sleep`` charges the
    requested seconds (the pacer caps a single sleep at 2 s in production).
    """

    def __init__(self) -> None:
        self.now = CLOCK_START
        self.sleeps: list[float] = []
        self.perf_counter_calls = 0

    # -- clock protocol -------------------------------------------------
    def perf_counter(self) -> float:
        self.perf_counter_calls += 1
        return self.now

    def sleep(self, seconds: float) -> None:
        value = float(seconds)
        self.sleeps.append(value)
        self.now += value

    # -- scripting helpers ----------------------------------------------
    def advance(self, seconds: float) -> None:
        self.now += float(seconds)

    def set_to(self, value: float) -> None:
        self.now = float(value)

    @property
    def elapsed(self) -> float:
        return self.now - CLOCK_START


class _FakeLedger:
    def __init__(self) -> None:
        self.reservations: list[tuple[float, int]] = []

    def reserve(self, run_id, *, active_seconds, optimizer_steps=0):
        self.reservations.append((float(active_seconds), int(optimizer_steps)))

    def begin_work(self, run_id, work_state=None):  # pragma: no cover - unused
        return None

    def finish(self, run_id, state, reason=None):  # pragma: no cover - unused
        raise AssertionError("a deadline test must never finish a run")


class _FakeGuard:
    def __init__(self) -> None:
        self.calls = 0

    def sample(self, **kwargs):
        self.calls += 1
        return {}


class _FakeModel:
    def __init__(self, seed: int) -> None:
        self.params = {"w": np.zeros(4, dtype=np.float32)}


class _RecordingBackend:
    """CPU stand-in that counts gradients and saves and runs the clock hooks."""

    name = "cpu-test-substitute-r6-deadline"

    def __init__(self, clock: _ScriptedClock, *, on_gradient=None, on_save=None) -> None:
        self.clock = clock
        self.on_gradient = on_gradient
        self.on_save = on_save
        self.gradient_calls = 0
        self.saves: list[int] = []

    def build_model(self, arm_id, seed):
        return _FakeModel(seed)

    def make_optimizer(self, protocol):
        return {}

    def init_optimizer(self, optimizer, model):
        return None

    def value_and_grad(self, model):
        def apply(m, batch):
            self.gradient_calls += 1
            if self.on_gradient is not None:
                self.on_gradient(self.gradient_calls)
            return (np.float32(1.0), {}), {"w": np.zeros(4, dtype=np.float32)}

        return apply

    def eval(self, *values):
        return None

    def clip_grad_norm(self, grads, norm):
        return grads, 1.0

    def optimizer_update(self, optimizer, model, grads):
        return None

    def sync_parameters(self, model, optimizer):
        return None

    def loss_value(self, loss):
        return float(loss)

    def parameter_sha256(self, model):
        return "0" * 64

    def window_probe(self, model, windows, protocol, *, max_batches=None):
        return {"rows": [{"loss": 1.0}], "batches": 1}

    def save_params(self, model, path, *, exclusive=False):
        path = Path(path)
        if exclusive and path.exists():
            raise FileExistsError(path)
        if path.name == "params.npz":
            self.saves.append(UPDATES)
        else:  # checkpoints/updates-<n>.npz
            self.saves.append(int(path.stem.split("-")[-1]))
        if self.on_save is not None:
            self.on_save(path)
        with open(path, "xb" if exclusive else "wb") as handle:
            np.savez(handle, **model.params)


def _document(*, checkpoint_updates: list[int]) -> dict:
    document = frozen_document()
    protocol = document["training_protocol"]
    protocol["updates"] = UPDATES
    protocol["checkpoint_updates"] = list(checkpoint_updates)
    document["timing"]["deadline_seconds"] = DEADLINE
    return document


def _install(monkeypatch, clock: _ScriptedClock, backend: _RecordingBackend, tmp_path):
    """Wire the fakes ``_train`` needs; the loop body itself stays real."""
    windows = {"obs": np.zeros((4, 2, 72))}

    def _batches(*args, **kwargs):
        while True:
            yield {"obs": None}

    monkeypatch.setattr(worker, "time", clock)
    monkeypatch.setattr(worker.data, "resolve_dataset_dir", lambda root: tmp_path)
    monkeypatch.setattr(worker.data, "load_training_windows", lambda *a, **k: windows)
    monkeypatch.setattr(worker.data, "load_development_windows", lambda *a, **k: windows)
    monkeypatch.setattr(worker.data, "iter_batches", _batches)


def _assert_no_completion(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run-r6-deadline"
    assert not (run_dir / "completion.json").exists(), (
        "a receipt was written for a run that crossed the deadline"
    )


# --- the four late phases that must not be able to claim completion --------
def test_last_gradient_crossing_the_deadline_aborts(monkeypatch, tmp_path):
    def on_gradient(call_index: int) -> None:
        if call_index < UPDATES:
            clock_holder[0].advance(PER_UPDATE_ACTIVE)
        else:
            # The 3510th gradient itself runs past the frozen deadline.
            clock_holder[0].advance(DEADLINE + 50.0)

    clock = _ScriptedClock()
    clock_holder: list[_ScriptedClock] = [clock]
    ledger = _FakeLedger()
    backend = _RecordingBackend(clock, on_gradient=on_gradient)
    _install(monkeypatch, clock, backend, tmp_path)
    with pytest.raises(TimeoutError):
        worker._train(
            _document(checkpoint_updates=[]),
            tmp_path,
            ledger,
            "run-r6-deadline",
            _FakeGuard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256="a" * 64,
            backend=backend,
        )
    assert backend.gradient_calls == UPDATES, "the loop must run the registered 3510 updates"
    assert len(ledger.reservations) == UPDATES, "one optimizer reservation per update"
    assert sum(steps for _seconds, steps in ledger.reservations) == UPDATES
    _assert_no_completion(tmp_path)


def test_final_duty_sleep_crossing_the_deadline_aborts(monkeypatch, tmp_path):
    """The pacer's own rest after the last gradient crosses the deadline."""

    def on_gradient(call_index: int) -> None:
        clock = clock_holder[0]
        if call_index < UPDATES:
            clock.advance(PER_UPDATE_ACTIVE)
        else:
            # Just inside the deadline; the capped 2 s duty sleep that follows
            # the last gradient pushes the total past 450 s.
            clock.set_to(CLOCK_START + DEADLINE - 1.5)

    clock = _ScriptedClock()
    clock_holder: list[_ScriptedClock] = [clock]
    backend = _RecordingBackend(clock, on_gradient=on_gradient)
    _install(monkeypatch, clock, backend, tmp_path)
    with pytest.raises(TimeoutError):
        worker._train(
            _document(checkpoint_updates=[]),
            tmp_path,
            _FakeLedger(),
            "run-r6-deadline",
            _FakeGuard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256="a" * 64,
            backend=backend,
        )
    assert backend.gradient_calls == UPDATES
    assert len(clock.sleeps) == UPDATES, "one duty sleep per registered update"
    assert clock.sleeps[-1] == pytest.approx(2.0), "the pacer caps a single rest at 2 s"
    assert clock.elapsed == pytest.approx(DEADLINE + 0.5)
    _assert_no_completion(tmp_path)


def test_final_checkpoint_io_crossing_the_deadline_aborts(monkeypatch, tmp_path):
    """The final checkpoint probe/save itself crosses the deadline."""

    def on_gradient(call_index: int) -> None:
        if call_index < UPDATES:
            clock_holder[0].advance(PER_UPDATE_ACTIVE)

    def on_save(path: Path) -> None:
        if path.name == "params.npz":
            # The final checkpoint write takes long enough to cross 450 s.
            clock_holder[0].advance(DEADLINE + 50.0)

    clock = _ScriptedClock()
    clock_holder: list[_ScriptedClock] = [clock]
    backend = _RecordingBackend(clock, on_gradient=on_gradient, on_save=on_save)
    _install(monkeypatch, clock, backend, tmp_path)
    with pytest.raises(TimeoutError):
        worker._train(
            _document(checkpoint_updates=[0, UPDATES // 2, UPDATES]),
            tmp_path,
            _FakeLedger(),
            "run-r6-deadline",
            _FakeGuard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256="a" * 64,
            backend=backend,
        )
    assert backend.gradient_calls == UPDATES
    assert backend.saves == [0, UPDATES // 2, UPDATES], "every declared checkpoint was written"
    _assert_no_completion(tmp_path)


def test_trailing_metadata_io_crossing_the_deadline_aborts(monkeypatch, tmp_path):
    """The receipt is already on disk; the run_info IO must still be checked."""

    def on_gradient(call_index: int) -> None:
        if call_index < UPDATES:
            clock_holder[0].advance(PER_UPDATE_ACTIVE)

    clock = _ScriptedClock()
    clock_holder: list[_ScriptedClock] = [clock]
    backend = _RecordingBackend(clock, on_gradient=on_gradient)
    _install(monkeypatch, clock, backend, tmp_path)

    original = worker._exclusive_write_json

    def _slow_metadata(path: Path, payload) -> None:
        if Path(path).name == "run_info.json":
            clock_holder[0].advance(DEADLINE + 50.0)
        return original(path, payload)

    monkeypatch.setattr(worker, "_exclusive_write_json", _slow_metadata)
    with pytest.raises(TimeoutError):
        worker._train(
            _document(checkpoint_updates=[]),
            tmp_path,
            _FakeLedger(),
            "run-r6-deadline",
            _FakeGuard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256="a" * 64,
            backend=backend,
        )
    assert backend.gradient_calls == UPDATES
    run_dir = tmp_path / "runs" / "run-r6-deadline"
    assert (run_dir / "completion.json").exists(), (
        "the receipt is written before the trailing metadata IO; that is exactly "
        "why the third check exists"
    )
    assert (run_dir / "run_info.json").exists()


# --- the boundary cases that must still complete ---------------------------
def test_exactly_at_the_deadline_completes_normally(monkeypatch, tmp_path):
    """450.0 s total is inside budget; only strictly past it aborts."""

    def on_gradient(call_index: int) -> None:
        clock = clock_holder[0]
        if call_index < UPDATES:
            clock.advance(PER_UPDATE_ACTIVE)
        else:
            clock.set_to(CLOCK_START + DEADLINE - 2.0)

    clock = _ScriptedClock()
    clock_holder: list[_ScriptedClock] = [clock]
    backend = _RecordingBackend(clock, on_gradient=on_gradient)
    _install(monkeypatch, clock, backend, tmp_path)
    details = worker._train(
        _document(checkpoint_updates=[]),
        tmp_path,
        _FakeLedger(),
        "run-r6-deadline",
        _FakeGuard(),
        arm_id="arm2",
        seed=0,
        prereg_sha256="a" * 64,
        backend=backend,
    )
    assert details["status"] == "completed"
    assert details["updates"] == UPDATES
    assert backend.gradient_calls == UPDATES
    assert details["wall_seconds"] == pytest.approx(DEADLINE)
    assert len(clock.sleeps) == UPDATES
    run_dir = tmp_path / "runs" / "run-r6-deadline"
    assert (run_dir / "completion.json").exists()
    assert (run_dir / "run_info.json").exists()
    receipt = json.loads((run_dir / "completion.json").read_text(encoding="utf-8"))
    assert receipt["updates"] == UPDATES
    assert receipt["ledger_accounting"]["optimizer_reservations"] == UPDATES


def test_just_inside_the_deadline_completes_normally(monkeypatch, tmp_path):
    def on_gradient(call_index: int) -> None:
        clock = clock_holder[0]
        if call_index < UPDATES:
            clock.advance(PER_UPDATE_ACTIVE)
        else:
            clock.set_to(CLOCK_START + DEADLINE - 2.1)

    clock = _ScriptedClock()
    clock_holder: list[_ScriptedClock] = [clock]
    backend = _RecordingBackend(clock, on_gradient=on_gradient)
    _install(monkeypatch, clock, backend, tmp_path)
    details = worker._train(
        _document(checkpoint_updates=[0, UPDATES // 2, UPDATES]),
        tmp_path,
        _FakeLedger(),
        "run-r6-deadline",
        _FakeGuard(),
        arm_id="arm2",
        seed=0,
        prereg_sha256="a" * 64,
        backend=backend,
    )
    assert details["status"] == "completed"
    assert details["wall_seconds"] == pytest.approx(DEADLINE - 0.1)
    assert [entry["updates"] for entry in details["checkpoints"]] == [0, UPDATES // 2, UPDATES]
    assert backend.gradient_calls == UPDATES


# --- other late failures must not produce a legal completion ---------------
def test_final_save_failure_never_completes(monkeypatch, tmp_path):
    def on_gradient(call_index: int) -> None:
        if call_index < UPDATES:
            clock_holder[0].advance(PER_UPDATE_ACTIVE)

    clock = _ScriptedClock()
    clock_holder: list[_ScriptedClock] = [clock]
    backend = _RecordingBackend(clock, on_gradient=on_gradient)
    _install(monkeypatch, clock, backend, tmp_path)

    original_save = backend.save_params

    def _failing_save(model, path, *, exclusive=False):
        if Path(path).name == "params.npz":
            raise OSError("simulated final checkpoint write failure")
        return original_save(model, path, exclusive=exclusive)

    backend.save_params = _failing_save
    with pytest.raises(OSError):
        worker._train(
            _document(checkpoint_updates=[]),
            tmp_path,
            _FakeLedger(),
            "run-r6-deadline",
            _FakeGuard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256="a" * 64,
            backend=backend,
        )
    assert backend.gradient_calls == UPDATES
    _assert_no_completion(tmp_path)


def test_late_guard_refusal_never_completes(monkeypatch, tmp_path):
    class _RefusingGuard:
        def __init__(self) -> None:
            self.calls = 0

        def sample(self, **kwargs):
            self.calls += 1
            if self.calls >= UPDATES:
                raise worker.resource_gate.ResourceGateRefused(
                    ["simulated_guard_refusal"]
                )
            return {}

    clock = _ScriptedClock()
    clock_holder: list[_ScriptedClock] = [clock]
    backend = _RecordingBackend(clock)
    _install(monkeypatch, clock, backend, tmp_path)
    with pytest.raises(worker.resource_gate.ResourceGateRefused):
        worker._train(
            _document(checkpoint_updates=[]),
            tmp_path,
            _FakeLedger(),
            "run-r6-deadline",
            _RefusingGuard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256="a" * 64,
            backend=backend,
        )
    _assert_no_completion(tmp_path)


# --- the entry point must not be able to complete a timed-out run ---------
def test_run_worker_never_completes_a_timed_out_train(tmp_path, monkeypatch, canonical_root):
    from ainerzero.runtime.lifecycle import RunStore

    from s1_testkit import write_frozen, write_research_log

    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    monkeypatch.setattr(
        spec, "RESEARCH_LOG", write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    )
    monkeypatch.setattr(
        data,
        "dataset_binding_state",
        lambda root, digest: {
            "status": "passed",
            "expected_dataset_digest": digest,
            "actual_dataset_digest": digest,
        },
    )

    def _times_out(*args, **kwargs):
        raise TimeoutError("frozen per-run deadline exceeded")

    monkeypatch.setattr(worker, "_train", _times_out)
    output_root = tmp_path / "phase1"
    report = worker.run_worker(
        "train",
        output_root=output_root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=500.0,
        prereg_path=path,
        research_log=None,
        arm="arm2",
        seed=0,
    )
    # The worker converts the late failure into a failed report; it can never
    # return a completed report, and the ledger run is finished as failed.
    assert report["status"] == "failed"
    assert "TimeoutError" in report["error"]
    assert report.get("details") is None

    with RunStore(canonical_root / "control.sqlite3") as store:
        runs = store.list_runs()
    assert runs, "the attempt must be registered in the central ledger"
    assert all(run.state != "completed" for run in runs)
    assert [run.state for run in runs] == ["failed"]
    assert all(
        not (run.reason or "").startswith(worker.TRAIN_RECEIPT_PREFIX) for run in runs
    ), "no completion receipt may be committed for a timed-out run"
    _assert_no_completion(output_root)
