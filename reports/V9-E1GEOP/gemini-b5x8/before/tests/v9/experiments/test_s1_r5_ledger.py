"""r5 ledger/checkpoint reachability tests (CPU only, no MLX).

The production ``worker._train`` control flow is executed with a controlled CPU
backend and the *real* RunStore.  No ``_train`` stub and no ledger waiver is
used: the test counts the actual optimizer reservations and the one final
checkpoint write.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from ainerzero.runtime.lifecycle import BudgetExceeded, RunStore
from ainerzero.v9.experiments.s1 import spec, worker

UPDATES = 3510


class _FakeModel:
    def __init__(self, seed: int):
        self.params = {"w": np.asarray([[float(seed)]], dtype=np.float32)}


class _FakeBackend:
    """Minimal numeric backend; it never imports MLX or runs a real model."""

    name = "cpu-test-substitute"

    def __init__(self):
        self.value_and_grad_calls = 0

    def build_model(self, arm_id: str, seed: int):
        return _FakeModel(seed)

    def make_optimizer(self, protocol):
        return {"lr": protocol["learning_rate"]}

    def init_optimizer(self, optimizer, model):
        return None

    def value_and_grad(self, model):
        def apply(m, batch):
            self.value_and_grad_calls += 1
            m.params["w"] = np.asarray(m.params["w"], dtype=np.float32) + 1.0
            return (np.float32(0.5), {}), {"w": np.zeros((1, 1), dtype=np.float32)}

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
        digest = hashlib.sha256()
        for name in sorted(model.params):
            digest.update(name.encode())
            digest.update(str(np.asarray(model.params[name]).shape).encode())
            digest.update(np.ascontiguousarray(model.params[name]).tobytes())
        return digest.hexdigest()

    def save_params(self, model, path: Path, *, exclusive: bool = False):
        path = Path(path)
        if exclusive and path.exists():
            raise FileExistsError(path)
        with open(path, "xb" if exclusive else "wb") as handle:
            np.savez(handle, **model.params)

    def load_params(self, model, path: Path):
        with np.load(path) as loaded:
            model.params = {name: np.asarray(loaded[name]) for name in loaded.files}

    def window_probe(self, model, windows, protocol, *, max_batches=None):
        return {
            "rows": [
                {
                    "loss": 0.5,
                    "episode_id": "e0",
                    "start": 0,
                    "pose": np.zeros(4),
                    "parts": {},
                }
            ],
            "batches": 1,
            "windows": 1,
        }


class _FakeGuard:
    def sample(self, **kwargs):
        return {}


def _document(updates: int, *, checkpoints=None) -> dict:
    return {
        "training_protocol": {
            "updates": updates,
            "seeds": [0],
            "batch_size": 1,
            "learning_rate": 3e-4,
            "adam_betas": (0.9, 0.999),
            "adam_epsilon": 1e-8,
            "weight_decay": 0.01,
            "gradient_clip_norm": 1.0,
            "checkpoint_updates": [0, updates] if checkpoints is None else checkpoints,
        },
        "timing": {"deadline_seconds": 450.0},
        "resource_limits": {**spec.RESOURCE_LIMITS, "training_duty_cycle": 0.25},
        "data_identity": {"dataset_digest": "d" * 64},
    }


def _patch_data(monkeypatch, root: Path):
    monkeypatch.setattr(worker.data, "resolve_dataset_dir", lambda _root: root)
    monkeypatch.setattr(
        worker.data, "load_training_windows", lambda *a, **k: {"obs": np.zeros((1, 2, 1))}
    )
    monkeypatch.setattr(
        worker.data,
        "load_development_windows",
        lambda *a, **k: {"obs": np.zeros((1, 2, 1))},
    )
    monkeypatch.setattr(
        worker.data, "iter_batches", lambda *a, **k: iter([{}] * 10_000)
    )


def _open_run(root: Path, *, updates: int, budget_steps: int | None = None) -> tuple[worker.PrepLedger, str]:
    ledger = worker.PrepLedger(root / "control.sqlite3")
    document = _document(updates)
    if budget_steps is None:
        return ledger, worker._open_train_run(
            document,
            ledger,
            {"document_sha256": "a" * 64},
            arm_id="arm2",
            seed=0,
        )
    experiment = ledger.store.create_experiment(
        worker.train_experiment_manifest(deadline_seconds=450.0, updates=updates),
        f"r5-boundary-experiment:{updates}",
        "r5-boundary-experiment",
    )
    snapshot = worker.run_config_snapshot(
        wall_budget_seconds=450.0,
        purpose="r5-boundary",
        max_optimizer_steps=budget_steps,
    )
    snapshot.update(
        {
            "arm_id": "arm2",
            "seed": 0,
            "updates": updates,
            "preregistration_sha256": "a" * 64,
            "dataset_digest": "d" * 64,
            "checkpoint_updates": [0, updates],
        }
    )
    run_id = "boundary-run"
    ledger.store.create_run(
        snapshot,
        "r5-boundary-run",
        run_id,
        experiment_id=experiment.experiment_id,
        role="model",
    )
    ledger.store.transition(run_id, "initializing", reason="test")
    return ledger, run_id


def test_production_train_3510_has_exactly_one_final_checkpoint(tmp_path, monkeypatch):
    _patch_data(monkeypatch, tmp_path)
    ledger, run_id = _open_run(tmp_path, updates=UPDATES)
    ledger.begin_work(run_id, work_state="training")

    reservations: list[tuple[int, float]] = []
    original = ledger.reserve

    def spy(run_id_arg, *, active_seconds, optimizer_steps=0):
        reservations.append((int(optimizer_steps), float(active_seconds)))
        return original(run_id_arg, active_seconds=active_seconds, optimizer_steps=optimizer_steps)

    ledger.reserve = spy
    backend = _FakeBackend()
    document = _document(UPDATES)
    try:
        details = worker._train(
            document,
            tmp_path,
            ledger,
            run_id,
            _FakeGuard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256="a" * 64,
            backend=backend,
        )
        receipt = details["receipt"]
        ledger.finish(
            run_id,
            "completed",
            worker.TRAIN_RECEIPT_PREFIX
            + json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        )
    finally:
        ledger.close()

    optimizer_reservations = [row for row in reservations if row[0] == 1]
    assert len(optimizer_reservations) == UPDATES
    assert backend.value_and_grad_calls == UPDATES
    # The last reservation is the final optimizer step and includes the checkpoint
    # wall allowance; nothing is consumed after it.
    assert reservations[-1][0] == 1
    assert reservations[-1][1] >= worker.CHECKPOINT_RESERVE_SECONDS
    assert all(row[0] == 0 for row in reservations[:1])

    checkpoint_updates = [row["updates"] for row in receipt["checkpoints"]]
    assert checkpoint_updates == [0, UPDATES]
    final_entries = [row for row in receipt["checkpoints"] if row["updates"] == UPDATES]
    assert len(final_entries) == 1
    run_dir = tmp_path / "runs" / run_id
    final_path = run_dir / "params.npz"
    assert final_path.is_file()
    assert spec.sha256_file(final_path) == receipt["final_checkpoint_sha256"]
    assert (run_dir / "completion.json").is_file()
    assert (run_dir / "run_info.json").read_text().find('"authoritative": false') >= 0
    # The checkpoint is exclusive: a second write must be refused.
    with pytest.raises(FileExistsError):
        backend.save_params(_FakeModel(0), final_path, exclusive=True)

    with RunStore(tmp_path / "control.sqlite3") as store:
        record = store.get_run(run_id)
        assert record.state == "completed"
        assert record.reserved_optimizer_steps == UPDATES
        assert record.remaining["optimizer_steps"] == 0

    # The completed run is bindable by the ledger receipt alone.
    binding = worker._bind_completed_run(
        tmp_path,
        arm_id="arm2",
        seed=0,
        prereg_sha256="a" * 64,
        updates=UPDATES,
        ledger_path=tmp_path / "control.sqlite3",
    )
    assert binding["run"].run_id == run_id
    assert sorted(binding["checkpoints"]) == [0, UPDATES]
    assert binding["final"]["sha256"] == receipt["final_checkpoint_sha256"]


def test_3511th_optimizer_reservation_is_refused_at_the_3510_budget(tmp_path, monkeypatch):
    _patch_data(monkeypatch, tmp_path)
    ledger, run_id = _open_run(tmp_path, updates=UPDATES + 1, budget_steps=UPDATES)
    ledger.begin_work(run_id, work_state="training")
    reservations: list[int] = []
    original = ledger.reserve

    def spy(run_id_arg, *, active_seconds, optimizer_steps=0):
        reservations.append(int(optimizer_steps))
        return original(run_id_arg, active_seconds=active_seconds, optimizer_steps=optimizer_steps)

    ledger.reserve = spy
    try:
        with pytest.raises(worker.BudgetStop):
            worker._train(
                _document(UPDATES + 1),
                tmp_path,
                ledger,
                run_id,
                _FakeGuard(),
                arm_id="arm2",
                seed=0,
                prereg_sha256="a" * 64,
                backend=_FakeBackend(),
            )
    finally:
        ledger.close()
    assert reservations == [0] + [1] * (UPDATES + 1)
    # The refusal is a real ledger rejection, not a harness waiver.
    with RunStore(tmp_path / "control.sqlite3") as store:
        assert store.get_run(run_id).reserved_optimizer_steps == UPDATES
        with pytest.raises(BudgetExceeded):
            store.consume(run_id, optimizer_steps=1, active_seconds=0.01)


def test_rerun_is_refused_after_any_started_attempt(tmp_path):
    root = tmp_path / "r5-rerun"
    root.mkdir(parents=True)
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        experiment = ledger.store.create_experiment(
            worker.prep_experiment_manifest(), "r5-rerun-prep", "r5-rerun-prep"
        )
        snapshot = worker.run_config_snapshot(wall_budget_seconds=10.0, purpose="r5-rerun")
        snapshot.update({"arm_id": "arm2", "seed": 0, "updates": 4})
        run_id = "created-run"
        ledger.store.create_run(
            snapshot,
            "r5-rerun-run",
            run_id,
            experiment_id=experiment.experiment_id,
            role="auxiliary",
        )
        assert worker.train_attempts(ledger.store.list_runs(), arm_id="arm2", seed=0) == []
        assert worker.train_attempts(ledger.store.list_runs(), arm_id="arm2", seed=1) == []
        ledger.store.transition(run_id, "initializing", reason="test")
        attempts = worker.train_attempts(ledger.store.list_runs(), arm_id="arm2", seed=0)
        assert [run.run_id for run in attempts] == [run_id]
        assert attempts[0].state == "initializing"
        ledger.store.transition(run_id, "collecting", reason="test")
        ledger.store.transition(run_id, "failed", reason="injected_failure")
        attempts = worker.train_attempts(ledger.store.list_runs(), arm_id="arm2", seed=0)
        assert [run.run_id for run in attempts] == [run_id]
        assert attempts[0].state == "failed"
    finally:
        ledger.close()


def _train_and_complete(root: Path, monkeypatch, *, updates: int = 3) -> str:
    _patch_data(monkeypatch, root)
    ledger, run_id = _open_run(root, updates=updates)
    ledger.begin_work(run_id, work_state="training")
    details = worker._train(
        _document(updates),
        root,
        ledger,
        run_id,
        _FakeGuard(),
        arm_id="arm2",
        seed=0,
        prereg_sha256="a" * 64,
        backend=_FakeBackend(),
    )
    receipt = details["receipt"]
    ledger.finish(
        run_id,
        "completed",
        worker.TRAIN_RECEIPT_PREFIX + json.dumps(receipt, sort_keys=True, separators=(",", ":")),
    )
    ledger.close()
    return run_id


def test_eval_binding_rejects_tampered_missing_and_duplicate_evidence(tmp_path, monkeypatch):
    root = tmp_path / "r5-binding"
    run_id = _train_and_complete(root, monkeypatch)
    worker._bind_completed_run(
        root, arm_id="arm2", seed=0, prereg_sha256="a" * 64, updates=3,
        ledger_path=root / "control.sqlite3",
    )

    tampered = tmp_path / "r5-tampered"
    shutil.copytree(root, tampered)
    params = tampered / "runs" / run_id / "params.npz"
    params.chmod(0o644)
    with open(params, "ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(worker.EvalBindingError, match="does not match the original receipt SHA"):
        worker._bind_completed_run(
            tampered, arm_id="arm2", seed=0, prereg_sha256="a" * 64, updates=3,
            ledger_path=tampered / "control.sqlite3",
        )

    missing = tmp_path / "r5-missing"
    shutil.copytree(root, missing)
    (missing / "runs" / run_id / "checkpoints" / "updates-0.npz").unlink()
    with pytest.raises(worker.EvalBindingError, match="missing"):
        worker._bind_completed_run(
            missing, arm_id="arm2", seed=0, prereg_sha256="a" * 64, updates=3,
            ledger_path=missing / "control.sqlite3",
        )

    wrong_prereg = worker._bind_completed_run
    with pytest.raises(worker.EvalBindingError):
        wrong_prereg(
        root, arm_id="arm2", seed=0, prereg_sha256="b" * 64, updates=3,
        ledger_path=root / "control.sqlite3",
    )

    duplicate = tmp_path / "r5-duplicate"
    shutil.copytree(root, duplicate)
    with RunStore(duplicate / "control.sqlite3") as store:
        experiment = store.create_experiment(
            worker.train_experiment_manifest(deadline_seconds=450.0, updates=3),
            "r5-duplicate-experiment",
            "r5-duplicate-experiment",
        )
        snapshot = worker.run_config_snapshot(
            wall_budget_seconds=450.0,
            purpose="r5-duplicate",
            max_optimizer_steps=3,
        )
        snapshot.update(
            {
                "arm_id": "arm2",
                "seed": 0,
                "updates": 3,
                "preregistration_sha256": "a" * 64,
                "dataset_digest": "d" * 64,
                "checkpoint_updates": [0, 3],
            }
        )
        second = "duplicate-run"
        store.create_run(
            snapshot,
            "r5-duplicate-run",
            second,
            experiment_id=experiment.experiment_id,
            role="model",
        )
        store.transition(second, "initializing", reason="test")
        store.transition(second, "training", reason="test")
        for _ in range(3):
            store.consume(second, optimizer_steps=1, active_seconds=0.01)
        store.transition(second, "completed", reason="not-a-receipt")
    with pytest.raises(worker.EvalBindingError, match="more than one completed run"):
        worker._bind_completed_run(
            duplicate, arm_id="arm2", seed=0, prereg_sha256="a" * 64, updates=3,
            ledger_path=duplicate / "control.sqlite3",
        )


def test_run_snapshot_carries_the_frozen_updates_and_a_one_step_budget_still_fails(
    tmp_path, monkeypatch
):
    """Bad control for the exact r4 defect: the aux default of 1 cannot train."""
    _patch_data(monkeypatch, tmp_path)
    ledger, run_id = _open_run(tmp_path, updates=7)
    with RunStore(tmp_path / "control.sqlite3") as store:
        run = store.get_run(run_id)
        assert run.config_snapshot["budget"]["max_optimizer_steps"] == 7
        assert run.remaining["optimizer_steps"] == 7
    ledger.close()

    # The pre-fix budget (1) must stop the second optimizer reservation.
    old_root = tmp_path / "old-default"
    old_root.mkdir()
    _patch_data(monkeypatch, old_root)
    ledger, run_id = _open_run(old_root, updates=2, budget_steps=1)
    ledger.begin_work(run_id, work_state="training")
    try:
        with pytest.raises(worker.BudgetStop):
            worker._train(
                _document(2),
                old_root,
                ledger,
                run_id,
                _FakeGuard(),
                arm_id="arm2",
                seed=0,
                prereg_sha256="a" * 64,
                backend=_FakeBackend(),
            )
    finally:
        ledger.close()
    with RunStore(old_root / "control.sqlite3") as store:
        assert store.get_run(run_id).reserved_optimizer_steps == 1
