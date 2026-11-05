"""r8 F1/F8: one completion protocol for the whole bounded run.

P21 F1 showed that r7 re-checked the frozen deadline only *before* ``_train``
returned; the final metadata IO, the receipt and -- above all -- the ledger's
terminal ``completed`` commit (which may wait for a SQLite write lock and fsync)
were outside every check, so an over-budget run could still be returned and
consumed as ``completed``.  P21 F8 showed the train branch did not forward a CPU
double, so the *public* ``run_worker`` control flow was not reviewable without
MLX.

Every test below drives the real public path (``worker.run_worker`` ->
``_train`` -> ``completion.CompletionProtocol`` -> ``PrepLedger.finish``) with a
CPU stand-in backend.  Nothing here trains, imports MLX, or approves anything.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import completion, data, spec, worker

from s1_testkit import FAKE_COUNTS, fake_smoke, frozen_document, write_frozen, write_research_log

UPDATES = 3510
DEADLINE = 450.0
PER_UPDATE_ACTIVE = 0.03


# --- fixtures -------------------------------------------------------------
class _ScriptedClock:
    """Fake *loop* clock; only explicit advances move it forward."""

    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.now += float(seconds)

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class _FakeModel:
    def __init__(self, seed: int) -> None:
        self.params = {"w": np.zeros(4, dtype=np.float32)}


class _CpuBackend:
    """CPU stand-in for the MLX backend (no MLX import, no real training)."""

    name = "cpu-test-substitute-r8-completion"

    def __init__(self, clock: _ScriptedClock) -> None:
        self.clock = clock
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
            self.clock.advance(PER_UPDATE_ACTIVE)
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
        self.saves.append(int(path.stem.split("-")[-1]) if "-" in path.stem else UPDATES)
        with open(path, "xb" if exclusive else "wb") as handle:
            np.savez(handle, **model.params)


def _install_loop(monkeypatch, clock: _ScriptedClock) -> None:
    """Replace the loop clock and the batch iterator only.

    The dataset *binding* path stays real (the frozen digest must still resolve
    and verify); only the batch stream is a stub, because the synthetic fixture
    holds fewer windows than the frozen batch size.
    """
    monkeypatch.setattr(worker, "time", clock)

    def _batches(*args, **kwargs):
        while True:
            yield {"obs": None}

    monkeypatch.setattr(worker.data, "iter_batches", _batches)


# The registered smoke step time: it reproduces the *frozen production shape*
# (3510 updates, 450 s deadline, checkpoints 0/439/878/1755/3510) instead of
# shortening the loop for the test.
REGISTERED_STEP_SECONDS = 0.0069624580000891


def _approved_document(identity: dict) -> dict:
    """A frozen document bound to the synthetic dataset, at the registered 3510."""
    from ainerzero.v9.experiments.s1 import prereg

    document = prereg.build_frozen(
        prereg.build_draft(data_identity=identity, parameter_counts=FAKE_COUNTS),
        smoke=fake_smoke(REGISTERED_STEP_SECONDS),
        data_identity=identity,
        created_unix=1_000.0,
    )
    assert document["training_protocol"]["updates"] == UPDATES
    assert float(document["timing"]["deadline_seconds"]) == DEADLINE
    return document


def _train_root(tmp_path: Path, monkeypatch, canonical_root, synthetic_dataset):
    """Isolated canonical host with an approved document and a bound dataset."""
    manifest, dataset_dir, _plan = synthetic_dataset
    identity = data.dataset_identity(manifest)
    target = tmp_path / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(dataset_dir, target)
    root = Path(canonical_root)
    data.write_dataset_ref(root, manifest, target)
    document = _approved_document(identity)
    path, digest, _doc = write_frozen(root / "pre_registration.json", document=document)
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)
    return root, path, digest, log


# --- F8: the public train control flow runs on a CPU double ---------------
def test_public_run_worker_train_completes_through_the_completion_protocol(
    tmp_path, monkeypatch, canonical_root, synthetic_dataset
):
    root, path, digest, log = _train_root(tmp_path, monkeypatch, canonical_root, synthetic_dataset)
    clock = _ScriptedClock()
    backend = _CpuBackend(clock)
    _install_loop(monkeypatch, clock)

    report = worker.run_worker(
        "train",
        output_root=root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        research_log=log,
        arm="arm2",
        seed=0,
        backend=backend,
    )

    assert report["status"] == "completed", json.dumps(
        {k: v for k, v in report.items() if k not in ("details", "run")}, default=str
    )[:1500]
    # F8: the double really drove the registered 3510 updates through the
    # public branch (not only through a private _train call).
    assert backend.gradient_calls == UPDATES
    assert backend.saves == [0, 439, 878, 1755, UPDATES]
    protocol_record = report["completion_protocol"]
    assert protocol_record["schema"] == completion.SCHEMA
    phases = [event["phase"] for event in protocol_record["events"]]
    # One shared timer for the whole run: every loop iteration, then the receipt,
    # then the pre/in-flight/post commit checks.
    assert phases.count("train_loop") >= UPDATES
    assert phases[-3:] == [
        "train:pre_terminal_commit",
        "train:terminal_commit:before",
        "train:terminal_commit:after",
    ]
    assert protocol_record["elapsed_at_record_seconds"] <= DEADLINE

    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        run = ledger.get(report["run_id"])
    finally:
        ledger.close()
    assert run["state"] == "completed"
    assert run["reserved_optimizer_steps"] == UPDATES

    # The consumer accepts this run: receipt + protocol + checkpoint binding.
    bound = worker._bind_completed_run(
        root,
        arm_id="arm2",
        seed=0,
        prereg_sha256=digest,
        updates=UPDATES,
        ledger_path=root / "control.sqlite3",
    )
    assert bound["run"].run_id == report["run_id"]
    assert bound["final"]["updates"] == UPDATES


# --- F1: the commit itself is inside the deadline ------------------------
def _ledger_in_training(root: Path) -> tuple[worker.PrepLedger, str]:
    ledger = worker.PrepLedger(root / "control.sqlite3")
    document = {
        "training_protocol": {"updates": UPDATES, "checkpoint_updates": [0, UPDATES]},
        "timing": {"deadline_seconds": DEADLINE},
        "data_identity": {"dataset_digest": "e" * 64},
    }
    run_id = worker._open_train_run(
        document,
        ledger,
        {"document_sha256": "d" * 64, "line": "test", "line_number": 1},
        arm_id="arm2",
        seed=0,
    )
    ledger.begin_work(run_id, work_state="training")
    return ledger, run_id


def test_a_delay_before_the_terminal_commit_is_refused_before_any_completion(
    tmp_path, canonical_root
):
    """A 21 s stall between the last check and the commit must not complete."""
    root = Path(canonical_root)
    ledger, run_id = _ledger_in_training(root)
    protocol = completion.CompletionProtocol(deadline_seconds=20.0)

    def _seam(phase: str, elapsed: float) -> None:
        # Inject the stall once, right after the pre-commit check measured the
        # clock: the *next* check (inside run_monitored) sees 21 s > 20 s.
        if phase == "train:pre_terminal_commit" and not protocol.events[1:]:
            time.sleep(0.0)
            protocol.started -= 21.0

    completion.TEST_SEAM = _seam
    try:
        report = worker._complete_run(
            report={"schema": "test", "mode": "train"},
            ledger=ledger,
            run_id=run_id,
            protocol=protocol,
            output_root=root,
            reason="s1_train_completed",
            kind="train",
        )
    finally:
        completion.TEST_SEAM = None

    assert report["status"] == "failed"
    assert report["refused_stage"] == "completion_deadline_exceeded"
    state = ledger.get(run_id)["state"]
    assert state != "completed", "an over-budget run must never reach completed"
    assert state == "failed"
    assert report["rolled_back"] is False
    assert Path(report["completion_invalid_marker"]).is_file()
    ledger.close()


def test_a_commit_that_lands_after_the_deadline_is_refused_and_never_rewritten(
    tmp_path, canonical_root
):
    """A real SQLite write-lock wait inside ``ledger.finish`` is captured.

    The lock makes the terminal commit itself run past the deadline.  The row is
    then already ``completed`` (the ledger is append-only): the protocol must not
    pretend it rolled back, must not rewrite ``completed`` to ``stopped``, and no
    consumer may accept the run -- an immutable marker says so.
    """
    import threading

    root = Path(canonical_root)
    ledger, run_id = _ledger_in_training(root)
    protocol = completion.CompletionProtocol(deadline_seconds=0.30)
    released = threading.Event()
    state: dict = {}

    def _hold_the_write_lock(phase: str, elapsed: float) -> None:
        """Take the SQLite write lock exactly when the commit is about to start.

        The seam runs after the ``:before`` measurement and before the action, so
        the *commit itself* is what waits for the lock -- not the pre-commit
        checks.  The lock is released 0.6 s later, well past the 0.3 s deadline.
        """
        if phase != "train:terminal_commit:before" or "holder" in state:
            return
        holder = sqlite3.connect(
            root / "control.sqlite3", timeout=5.0, isolation_level=None,
            check_same_thread=False,
        )
        holder.execute("BEGIN IMMEDIATE")
        state["holder"] = holder

        def _release() -> None:
            time.sleep(0.6)
            holder.execute("COMMIT")
            released.set()

        threading.Thread(target=_release, daemon=True).start()

    completion.TEST_SEAM = _hold_the_write_lock
    try:
        report = worker._complete_run(
            report={"schema": "test", "mode": "train"},
            ledger=ledger,
            run_id=run_id,
            protocol=protocol,
            output_root=root,
            reason="s1_train_completed",
            kind="train",
        )
        assert released.wait(timeout=10.0)
    finally:
        completion.TEST_SEAM = None
        state.get("holder") and state["holder"].close()

    assert report["status"] == "failed"
    assert report["refused_stage"] == "completion_deadline_exceeded"
    assert report["completion_protocol"]["expired_in_flight"] is True
    record = ledger.get(run_id)
    # Honest boundary: the commit had already landed, so the terminal row stays
    # exactly as committed -- it is not rewritten, not deleted and not refunded.
    assert record["state"] == "completed"
    assert record["reason"] == "s1_train_completed"
    assert report["rolled_back"] is False
    markers = completion.invalid_markers(root / "runs" / run_id)
    assert markers, "a late terminal commit must leave an invalidation marker"
    payload = json.loads(markers[0].read_text(encoding="utf-8"))
    assert payload["status"] == "invalid"
    assert payload["ledger_state_at_invalidation"] == "completed"
    assert payload["protocol"]["expired_in_flight"] is True
    ledger.close()


def test_a_consumer_refuses_a_receipt_without_the_completion_protocol(
    tmp_path, canonical_root
):
    """``completion.json`` alone is not evidence of a valid completion."""
    root = Path(canonical_root)
    ledger, run_id = _ledger_in_training(root)
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "ainerzero.v9.s1.completion.v1",
        "run_id": run_id,
        "arm_id": "arm2",
        "seed": 0,
        "updates": UPDATES,
        "checkpoints": [
            {"updates": UPDATES, "path": "checkpoints/updates-3510.npz", "sha256": "a" * 64,
             "parameter_sha256": "0" * 64}
        ],
        "preregistration_sha256": "d" * 64,
    }
    (run_dir / "completion.json").write_text(json.dumps(receipt), encoding="utf-8")
    ledger.reserve(run_id, active_seconds=1.0, optimizer_steps=UPDATES)
    ledger.finish(run_id, "completed", worker.TRAIN_RECEIPT_PREFIX + json.dumps(receipt))

    with pytest.raises(worker.EvalBindingError) as excinfo:
        worker._bind_completed_run(
            root,
            arm_id="arm2",
            seed=0,
            prereg_sha256="d" * 64,
            updates=UPDATES,
            ledger_path=root / "control.sqlite3",
        )
    assert "completion-protocol" in str(excinfo.value) or "protocol" in str(excinfo.value)
    ledger.close()


def test_a_consumer_refuses_a_run_carrying_an_invalid_marker(tmp_path, canonical_root):
    """A ``completed`` row plus a full receipt is still refused when invalidated."""
    root = Path(canonical_root)
    ledger, run_id = _ledger_in_training(root)
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    protocol = completion.CompletionProtocol(deadline_seconds=10.0)
    protocol.check("train_receipt")
    record = protocol.record(phase="train_receipt")
    receipt = {
        "schema": "ainerzero.v9.s1.completion.v1",
        "run_id": run_id,
        "arm_id": "arm2",
        "seed": 0,
        "updates": UPDATES,
        "checkpoints": [
            {"updates": UPDATES, "path": "checkpoints/updates-3510.npz", "sha256": "a" * 64,
             "parameter_sha256": "0" * 64}
        ],
        "preregistration_sha256": "d" * 64,
        "completion_protocol": record,
    }
    (run_dir / "completion.json").write_text(json.dumps(receipt), encoding="utf-8")
    completion.write_invalid_marker(
        run_dir,
        protocol=protocol,
        phase="train:terminal_commit",
        reason="deadline_exceeded_in_commit",
        ledger_state="completed",
        detail="injected",
    )
    ledger.reserve(run_id, active_seconds=1.0, optimizer_steps=UPDATES)
    ledger.finish(run_id, "completed", worker.TRAIN_RECEIPT_PREFIX + json.dumps(receipt))

    with pytest.raises(worker.EvalBindingError) as excinfo:
        worker._bind_completed_run(
            root,
            arm_id="arm2",
            seed=0,
            prereg_sha256="d" * 64,
            updates=UPDATES,
            ledger_path=root / "control.sqlite3",
        )
    assert "invalidation marker" in str(excinfo.value)
    ledger.close()
