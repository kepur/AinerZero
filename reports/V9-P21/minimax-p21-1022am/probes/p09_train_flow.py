"""P21 probe 09: the production training control flow, the 450 s deadline chain
and the finish/receipt hole.

* the frozen protocol (3510 updates, checkpoints 0/439/878/1755/3510) is driven
  through the real ``worker._train`` with a real RunStore ledger in an isolated
  host and the real development dataset, using a CPU numeric substitute;
* the deadline chain is probed independently: the last gradient, the duty
  sleep, the checkpoint IO and the trailing metadata IO must all abort the run
  instead of producing a ``completed`` run, and the exact boundary must still
  complete;
* the step after the last deadline check -- the ``ledger.finish`` transition
  that writes the ``completed`` state -- is probed as well: a run whose final
  commit crosses the deadline must not be ``completed`` either.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402

from ainerzero.v9.experiments.s1 import prereg, spec, worker  # noqa: E402

R7_PREREG = lib.REPO / "artifacts/v9/s1/phase1/r7/pre_registration.json"
REAL_PHASE1 = lib.REPO / "artifacts/v9/s1/phase1"
FROZEN = json.loads(R7_PREREG.read_text(encoding="utf-8"))
PREREG_SHA = prereg.document_sha256(FROZEN)
UPDATES = int(FROZEN["training_protocol"]["updates"])
CHECKPOINTS = [int(v) for v in FROZEN["training_protocol"]["checkpoint_updates"]]
DEADLINE = float(FROZEN["timing"]["deadline_seconds"])


class Model:
    def __init__(self, seed: int) -> None:
        self.params = {"w": np.asarray([[float(seed)]], dtype=np.float32)}


class SubstituteBackend:
    """A CPU numeric stand-in: it records every model call it is asked to make."""

    name = "p21-cpu-substitute"

    def __init__(self) -> None:
        self.value_and_grad_calls = 0
        self.window_probe_calls = 0
        self.window_probe_batches = 0
        self.save_calls = 0
        self.load_calls = 0

    def build_model(self, arm_id, seed):
        return Model(seed)

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

    def save_params(self, model, path, *, exclusive=False):
        self.save_calls += 1
        path = Path(path)
        if exclusive and path.exists():
            raise FileExistsError(path)
        with open(path, "xb" if exclusive else "wb") as handle:
            np.savez(handle, **model.params)

    def load_params(self, model, path):
        self.load_calls += 1
        with np.load(path) as loaded:
            model.params = {name: np.asarray(loaded[name]) for name in loaded.files}

    def window_probe(self, model, windows, protocol, *, max_batches=None):
        self.window_probe_calls += 1
        batch = int(protocol["batch_size"])
        rows = [
            {
                "episode_id": meta["episode_id"],
                "start": int(meta["start"]),
                "loss": 0.5,
                "parts": {"presence": 0.2, "class": 0.3, "position": 0.1},
                "pose": np.zeros(4),
                "prediction": None,
            }
            for meta in windows["windows"]
        ]
        batches = (len(rows) + batch - 1) // batch
        self.window_probe_batches += batches
        return {"rows": rows, "batches": batches, "windows": len(rows)}


class Guard:
    def sample(self, **kwargs):
        return {}


class ScriptedClock:
    """A fake wall clock: only explicit advances move time forward."""

    def __init__(self) -> None:
        self.now = 1_000.0
        self.sleeps: list[float] = []

    def perf_counter(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        value = float(seconds)
        self.sleeps.append(value)
        self.now += value

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)

    def set_to(self, value: float) -> None:
        self.now = float(value)


def document(*, updates=UPDATES, checkpoints=None, deadline=DEADLINE) -> dict:
    return {
        "training_protocol": {
            "updates": int(updates),
            "batch_size": int(FROZEN["training_protocol"]["batch_size"]),
            "sequence_steps": int(FROZEN["training_protocol"]["sequence_steps"]),
            "learning_rate": float(FROZEN["training_protocol"]["learning_rate"]),
            "adam_betas": FROZEN["training_protocol"]["adam_betas"],
            "adam_epsilon": float(FROZEN["training_protocol"]["adam_epsilon"]),
            "weight_decay": float(FROZEN["training_protocol"]["weight_decay"]),
            "gradient_clip_norm": float(FROZEN["training_protocol"]["gradient_clip_norm"]),
            "checkpoint_updates": (
                list(CHECKPOINTS) if checkpoints is None else list(checkpoints)
            ),
        },
        "timing": {"deadline_seconds": float(deadline)},
        "resource_limits": dict(FROZEN["resource_limits"]),
        "data_identity": dict(FROZEN["data_identity"]),
    }


def fresh_root(prefix: str) -> Path:
    root = lib.scratch_dir(prefix)
    shutil.copy2(REAL_PHASE1 / "dataset_ref.json", root / "dataset_ref.json")
    return root


def open_train_run(root: Path, doc: dict):
    ledger = worker.PrepLedger(root / "control.sqlite3")
    run_id = worker._open_train_run(
        doc, ledger, {"document_sha256": PREREG_SHA}, arm_id="arm2", seed=0
    )
    ledger.begin_work(run_id, work_state="training")
    return ledger, run_id


def finish_like_run_worker(ledger, run_id: str, details: dict) -> dict:
    """Exactly the sequence ``worker.run_worker`` performs after ``_train``."""
    receipt = details.get("receipt") if isinstance(details, dict) else None
    if receipt:
        reason = worker.TRAIN_RECEIPT_PREFIX + json.dumps(
            receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    else:
        reason = "s1_train_completed"
    return ledger.finish(run_id, "completed", reason)


def deadline_control(kind: str) -> dict:
    """Drive the real training loop so that one late phase crosses the deadline."""
    root = fresh_root(f"p21-deadline-{kind}-")
    doc = document(checkpoints=[0, UPDATES // 2, UPDATES] if kind == "checkpoint-io" else [])
    ledger, run_id = open_train_run(root, doc)
    clock = ScriptedClock()
    backend = SubstituteBackend()
    original_value_and_grad = backend.value_and_grad

    def value_and_grad(model):
        apply = original_value_and_grad(model)

        def wrapped(m, batch):
            apply(m, batch)
            if kind == "last-gradient" and backend.value_and_grad_calls >= UPDATES:
                clock.advance(DEADLINE + 50.0)
            elif kind == "duty-sleep" and backend.value_and_grad_calls >= UPDATES:
                clock.set_to(1_000.0 + DEADLINE - 1.5)
            elif kind == "exact-boundary" and backend.value_and_grad_calls >= UPDATES:
                clock.set_to(1_000.0 + DEADLINE - 2.0)
            return apply.__wrapped__ if False else None

        # keep the call counter and the clock hook in one place
        def apply2(m, batch):
            backend.value_and_grad_calls += 1
            m.params["w"] = np.asarray(m.params["w"], dtype=np.float32) + 1.0
            if kind == "last-gradient" and backend.value_and_grad_calls >= UPDATES:
                clock.advance(DEADLINE + 50.0)
            elif kind == "duty-sleep" and backend.value_and_grad_calls >= UPDATES:
                clock.set_to(1_000.0 + DEADLINE - 1.5)
            elif kind == "exact-boundary" and backend.value_and_grad_calls >= UPDATES:
                clock.set_to(1_000.0 + DEADLINE - 2.0)
            return (np.float32(0.5), {}), {"w": np.zeros((1, 1), dtype=np.float32)}

        return apply2

    backend.value_and_grad = value_and_grad
    original_save = backend.save_params

    def save_params(model, path, *, exclusive=False):
        if kind == "checkpoint-io" and Path(path).name == "params.npz":
            clock.advance(DEADLINE + 50.0)
        return original_save(model, path, exclusive=exclusive)

    backend.save_params = save_params
    original_write_json = worker._exclusive_write_json

    def slow_metadata(path, payload):
        if kind == "metadata-io" and Path(path).name == "run_info.json":
            clock.advance(DEADLINE + 50.0)
        return original_write_json(path, payload)

    worker._exclusive_write_json = slow_metadata
    worker_time = worker.time
    worker.time = clock
    original_iter = worker.data.iter_batches
    worker.data.iter_batches = lambda *a, **k: iter([{"obs": None}] * (UPDATES + 8))
    outcome = {"kind": kind}
    try:
        details = worker._train(
            doc,
            root,
            ledger,
            run_id,
            Guard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256=PREREG_SHA,
            backend=backend,
        )
        outcome["status"] = details["status"]
        outcome["wall_seconds"] = details["wall_seconds"]
        outcome["receipt_written"] = (root / "runs" / run_id / "completion.json").exists()
        # the step after the last deadline check
        record = finish_like_run_worker(ledger, run_id, details)
        outcome["ledger_state_after_finish"] = record["state"]
    except TimeoutError as exc:
        outcome["status"] = "aborted"
        outcome["error"] = f"{type(exc).__name__}: {exc}"
        outcome["receipt_written"] = (root / "runs" / run_id / "completion.json").exists()
    finally:
        worker.time = worker_time
        worker._exclusive_write_json = original_write_json
        worker.data.iter_batches = original_iter
        ledger.close()
    outcome["gradient_calls"] = backend.value_and_grad_calls
    outcome["duty_sleeps"] = len(clock.sleeps)
    outcome["checkpoint_saves"] = backend.save_calls
    return outcome


def real_time_finish_hole() -> dict:
    """Real wall clock: the final commit crosses the deadline and the run is
    still recorded as ``completed``."""
    root = fresh_root("p21-finish-hole-")
    doc = document(updates=4, checkpoints=[4], deadline=20.0)
    ledger, run_id = open_train_run(root, doc)
    backend = SubstituteBackend()
    details = worker._train(
        doc,
        root,
        ledger,
        run_id,
        Guard(),
        arm_id="arm2",
        seed=0,
        prereg_sha256=PREREG_SHA,
        backend=backend,
    )
    time.sleep(21.0)  # a slow final commit (fsync stall)
    record = finish_like_run_worker(ledger, run_id, details)
    reader = worker.PrepLedger(root / "control.sqlite3")
    try:
        stored = reader.store.get_run(run_id)
    finally:
        reader.close()
    ledger.close()
    return {
        "deadline_seconds": 20.0,
        "real_sleep_before_the_final_commit_seconds": 21.0,
        "train_status": details["status"],
        "ledger_state": record["state"],
        "run_wall_seconds_at_completion": stored.wall_seconds,
        "exceeded_the_deadline": stored.wall_seconds > 20.0,
        "reported_completed": record["state"] == "completed",
        "note": "worker._train's last deadline check happens before it returns; "
        "worker.run_worker then calls ledger.finish(...) with no further time check "
        "and RunStore.transition does not check the wall budget for a terminal state",
    }


def real_time_gradient_control() -> dict:
    """Control: the same overrun inside the last gradient must abort the run."""
    root = fresh_root("p21-finish-control-")
    doc = document(updates=4, checkpoints=[4], deadline=20.0)
    ledger, run_id = open_train_run(root, doc)
    backend = SubstituteBackend()
    original = backend.value_and_grad

    def value_and_grad(model):
        apply = original(model)

        def apply2(m, batch):
            result = apply(m, batch)
            if backend.value_and_grad_calls >= 4:
                time.sleep(21.0)
            return result

        return apply2

    backend.value_and_grad = value_and_grad
    outcome = {}
    try:
        details = worker._train(
            doc,
            root,
            ledger,
            run_id,
            Guard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256=PREREG_SHA,
            backend=backend,
        )
        outcome["status"] = details["status"]
    except TimeoutError as exc:
        outcome["status"] = "aborted"
        outcome["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        ledger.close()
    outcome["receipt_written"] = (root / "runs" / run_id / "completion.json").exists()
    return outcome


def main() -> int:
    started = time.perf_counter()
    scratch = lib.scratch_dir("p21-train")

    # --- 1) the frozen 3510-update control flow ----------------------------
    root = fresh_root("p21-train-3510-")
    doc = document()
    ledger, run_id = open_train_run(root, doc)
    reservations = []
    original_reserve = ledger.reserve

    def spy(run_id_arg, *, active_seconds, optimizer_steps=0):
        reservations.append((int(optimizer_steps), float(active_seconds)))
        return original_reserve(
            run_id_arg, active_seconds=active_seconds, optimizer_steps=optimizer_steps
        )

    ledger.reserve = spy
    backend = SubstituteBackend()
    details = worker._train(
        doc,
        root,
        ledger,
        run_id,
        Guard(),
        arm_id="arm2",
        seed=0,
        prereg_sha256=PREREG_SHA,
        backend=backend,
    )
    record = finish_like_run_worker(ledger, run_id, details)
    ledger.close()
    receipt = details["receipt"]
    final_entries = [e for e in receipt["checkpoints"] if int(e["updates"]) == UPDATES]
    train = {
        "run_id": run_id,
        "updates": UPDATES,
        "checkpoint_updates": sorted(int(e["updates"]) for e in receipt["checkpoints"]),
        "value_and_grad_calls": backend.value_and_grad_calls,
        "reservations_total": len(reservations),
        "optimizer_reservations": sum(1 for row in reservations if row[0] == 1),
        "wall_only_reservations": sum(1 for row in reservations if row[0] == 0),
        "post_final_optimizer_reservations": receipt["ledger_accounting"][
            "post_final_optimizer_reservations"
        ],
        "final_checkpoint_entries": len(final_entries),
        "final_checkpoint_file": str(
            (root / "runs" / run_id / final_entries[0]["path"]).resolve()
        ),
        "final_checkpoint_sha256": final_entries[0]["sha256"],
        "final_checkpoint_file_sha256": lib.sha256_file(
            root / "runs" / run_id / final_entries[0]["path"]
        ),
        "window_probe_calls": backend.window_probe_calls,
        "save_calls": backend.save_calls,
        "ledger_state": record["state"],
        "run_dir_files": sorted(
            str(path.relative_to(root / "runs" / run_id))
            for path in (root / "runs" / run_id).rglob("*")
            if path.is_file()
        ),
        "dataset_digest": receipt["dataset_digest"],
        "seconds": time.perf_counter() - started,
    }

    # --- 2) the deadline chain ---------------------------------------------
    controls = [
        deadline_control(kind)
        for kind in (
            "last-gradient",
            "duty-sleep",
            "checkpoint-io",
            "metadata-io",
            "exact-boundary",
        )
    ]

    # --- 3) the finish/receipt hole (real time) ----------------------------
    hole = real_time_finish_hole()
    control = real_time_gradient_control()

    payload = {
        "schema": "ainerzero.v9.p21.probe09_train_control_flow.v1",
        "frozen_document": str(R7_PREREG),
        "frozen_preregistration_sha256": PREREG_SHA,
        "train": train,
        "deadline_controls": controls,
        "finish_hole": hole,
        "gradient_control": control,
        "mlx_imported": lib.mlx_imported(),
        "real_mlx_loaded": lib.real_mlx_loaded(),
        "elapsed_seconds": time.perf_counter() - started,
    }
    payload["verdict"] = {
        "value_and_grad_calls_equal_updates": train["value_and_grad_calls"] == UPDATES,
        "one_reservation_per_update_plus_the_wall_only_ones": train[
            "optimizer_reservations"
        ]
        == UPDATES,
        "reservations_total_3511": train["reservations_total"] == UPDATES + 1,
        "no_reservation_after_the_final_optimizer_step": train[
            "post_final_optimizer_reservations"
        ]
        == 0,
        "exactly_one_final_checkpoint": train["final_checkpoint_entries"] == 1,
        "final_checkpoint_file_matches_the_receipt": train["final_checkpoint_sha256"]
        == train["final_checkpoint_file_sha256"],
        "frozen_checkpoint_set": train["checkpoint_updates"] == sorted(CHECKPOINTS),
        "run_completed": train["ledger_state"] == "completed",
        "deadline_controls_abort": all(
            control_["status"] == "aborted"
            for control_ in controls
            if control_["kind"] != "exact-boundary"
        ),
        "exact_boundary_completes": next(
            control_["status"] for control_ in controls if control_["kind"] == "exact-boundary"
        )
        == "completed",
        "no_mlx_loaded": not lib.real_mlx_loaded(),
    }
    payload["findings"] = {
        "finish_hole": hole,
        "gradient_control": control,
        "why": "the last deadline check lives at the end of worker._train; worker.run_worker "
        "then calls ledger.finish(active_run, 'completed', reason) with no further time check, "
        "and RunStore.transition performs no wall-budget check for a terminal state, so a run "
        "whose final commit crosses the frozen per-run deadline is still recorded as completed",
        "decision_requirement": "S1-R7-DECISION item 5: 'the last-step IO / ledger.finish commit "
        "taking more than 450 s must also not be completed'",
    }
    out = lib.write_json("09-train-control-flow.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    print(json.dumps(hole, indent=1))
    print(json.dumps(control, indent=1))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
