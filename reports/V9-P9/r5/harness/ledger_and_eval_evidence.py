"""r5 engineering evidence: production _train + _evaluate_arm on the real dev split.

This is CPU-only.  It imports no MLX and never builds an MLX model: a controlled
numeric backend stands in for `MlxBackend`, while the *production* control flow
(`worker._train`, `worker._evaluate_arm`), the real `RunStore` ledger, the real
frozen development dataset and the real 3510-update count are exercised.

Outputs one JSON evidence file; nothing under artifacts/ is modified.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.runtime.lifecycle import BudgetExceeded, RunStore  # noqa: E402
from ainerzero.v9.experiments.s1 import prereg, spec, worker  # noqa: E402

PHASE1 = REPO / "artifacts/v9/s1/phase1"
R5 = PHASE1 / "r5"
FROZEN = json.loads((R5 / "pre_registration.json").read_text(encoding="utf-8"))
PREREG_SHA = prereg.document_sha256(FROZEN)
UPDATES = int(FROZEN["training_protocol"]["updates"])
CHECKPOINTS = [int(v) for v in FROZEN["training_protocol"]["checkpoint_updates"]]
OUT = REPO / "reports/V9-P9/r5/evidence/ledger-and-eval.json"


class Model:
    def __init__(self, seed: int):
        self.params = {"w": np.asarray([[float(seed)]], dtype=np.float32)}


class CountingBackend:
    """Numeric substitute that records every model call it is asked to make."""

    name = "cpu-evidence-substitute"

    def __init__(self) -> None:
        self.value_and_grad_calls = 0
        self.window_probe_calls = 0
        self.window_probe_batches = 0
        self.step_sequence_calls = 0
        self.step_frames = 0
        self.probe_graph_calls = 0
        self.encode_calls = 0
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
        rows = []
        for meta in windows["windows"]:
            rows.append(
                {
                    "episode_id": meta["episode_id"],
                    "start": int(meta["start"]),
                    "loss": 0.5,
                    "parts": {"presence": 0.2, "class": 0.3, "position": 0.1},
                    "pose": np.zeros(4),
                    "prediction": None,
                }
            )
        batches = (len(rows) + batch - 1) // batch
        self.window_probe_batches += batches
        return {"rows": rows, "batches": batches, "windows": len(rows)}

    def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
        self.step_sequence_calls += 1
        frames = len(sequence["obs"]) if stop is None else int(stop)
        self.step_frames += frames
        if memory is None:
            nodes = []
            edges = set()
        else:
            nodes = list(memory["nodes"])
            edges = set(memory["edges"])
        start = len(nodes)
        for index in range(frames):
            nodes.append(np.asarray(sequence["obs"][index], dtype=np.float32))
            if index + start > 0:
                edges.add((len(nodes) - 2, len(nodes) - 1))
        graph = {
            "nodes": np.stack(nodes) if nodes else np.zeros((0, 1), dtype=np.float32),
            "positions": np.zeros((len(nodes), 2)),
            "edges": edges,
            "threshold": 0.0,
        }
        steps = [
            {
                "frame": index + 1,
                "loss": 0.5,
                "pose": np.zeros(4),
                "predictions": None,
                "parts": {"presence": 0.2, "class": 0.3},
            }
            for index in range(frames - 1)
        ]
        return {"steps": steps, "memory": graph, "pose": np.zeros((1, 4))}

    def probe_graph(self, model, memory, pose=None):
        self.probe_graph_calls += 1
        if memory is None:
            return {
                "nodes": np.zeros((0, 1)),
                "positions": np.zeros((0, 2)),
                "edges": set(),
                "threshold": 0.0,
            }
        return memory

    def encode(self, model, obs_row):
        self.encode_calls += 1
        return np.asarray(obs_row, dtype=np.float32)


class Guard:
    def sample(self, **kwargs):
        return {}


def document(*, updates=UPDATES, checkpoints=None):
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
        "timing": {"deadline_seconds": float(FROZEN["timing"]["deadline_seconds"])},
        "resource_limits": dict(FROZEN["resource_limits"]),
        "data_identity": dict(FROZEN["data_identity"]),
    }


def fresh_root(prefix: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix))
    shutil.copy2(PHASE1 / "dataset_ref.json", root / "dataset_ref.json")
    return root


def run_train(root: Path, *, doc=None, budget_steps=None):
    doc = doc or document()
    ledger = worker.PrepLedger(root / "control.sqlite3")
    if budget_steps is None:
        run_id = worker._open_train_run(
            doc, ledger, {"document_sha256": PREREG_SHA}, arm_id="arm2", seed=0
        )
    else:
        experiment = ledger.store.create_experiment(
            worker.train_experiment_manifest(
                deadline_seconds=float(doc["timing"]["deadline_seconds"]),
                updates=int(doc["training_protocol"]["updates"]),
            ),
            "r5-boundary-experiment",
            "r5-boundary-experiment",
        )
        snapshot = worker.run_config_snapshot(
            wall_budget_seconds=450.0, purpose="r5-boundary", max_optimizer_steps=budget_steps
        )
        snapshot.update(
            {
                "arm_id": "arm2",
                "seed": 0,
                "updates": int(doc["training_protocol"]["updates"]),
                "preregistration_sha256": PREREG_SHA,
                "dataset_digest": doc["data_identity"]["dataset_digest"],
                "checkpoint_updates": list(doc["training_protocol"]["checkpoint_updates"]),
            }
        )
        run_id = "r5-boundary-run"
        ledger.store.create_run(
            snapshot,
            "r5-boundary-run",
            run_id,
            experiment_id=experiment.experiment_id,
            role="model",
        )
        ledger.store.transition(run_id, "initializing", reason="evidence")
    ledger.begin_work(run_id, work_state="training")
    return ledger, run_id


def main() -> int:
    started = time.perf_counter()
    root = fresh_root("s1-r5-evidence-")
    ledger, run_id = run_train(root)
    reservations: list[tuple[int, float]] = []
    original = ledger.reserve

    def spy(run_id_arg, *, active_seconds, optimizer_steps=0):
        reservations.append((int(optimizer_steps), float(active_seconds)))
        return original(
            run_id_arg, active_seconds=active_seconds, optimizer_steps=optimizer_steps
        )

    ledger.reserve = spy
    train_backend = CountingBackend()
    details = worker._train(
        document(),
        root,
        ledger,
        run_id,
        Guard(),
        arm_id="arm2",
        seed=0,
        prereg_sha256=PREREG_SHA,
        backend=train_backend,
    )
    receipt = details["receipt"]
    ledger.finish(
        run_id,
        "completed",
        worker.TRAIN_RECEIPT_PREFIX + json.dumps(receipt, sort_keys=True, separators=(",", ":")),
    )
    ledger.close()
    train_seconds = time.perf_counter() - started

    with RunStore(root / "control.sqlite3") as store:
        record = store.get_run(run_id)
        train_state = {
            "state": record.state,
            "reserved_optimizer_steps": int(record.reserved_optimizer_steps),
            "remaining": dict(record.remaining),
        }
        attempts_after_completed = [
            run.run_id for run in worker.train_attempts(store.list_runs(), arm_id="arm2", seed=0)
        ]

    frozen_checks = {
        "optimizer_reservations": sum(1 for row in reservations if row[0] == 1),
        "wall_only_reservations": [row for row in reservations if row[0] == 0],
        "last_reservation": list(reservations[-1]) if reservations else None,
        "checkpoint_updates_reserved": sorted(
            entry["updates"] for entry in receipt["checkpoints"]
        ),
        "checkpoint_wall_reservations_seconds": receipt["ledger_accounting"][
            "checkpoint_wall_reservations_seconds"
        ],
        "post_final_optimizer_reservations": receipt["ledger_accounting"][
            "post_final_optimizer_reservations"
        ],
        "final_checkpoint_entries": len(
            [e for e in receipt["checkpoints"] if int(e["updates"]) == UPDATES]
        ),
        "final_checkpoint_sha256": receipt["final_checkpoint_sha256"],
        "final_checkpoint_file_sha256": spec.sha256_file(
            root / "runs" / run_id / receipt["final_checkpoint_path"]
        ),
        "train_value_and_grad_calls": train_backend.value_and_grad_calls,
        "train_window_probe_calls": train_backend.window_probe_calls,
        "train_window_probe_batches": train_backend.window_probe_batches,
        "train_save_calls": train_backend.save_calls,
        "run_dir_files": sorted(
            str(path.relative_to(root / "runs" / run_id))
            for path in (root / "runs" / run_id).rglob("*")
            if path.is_file()
        ),
        "run_info_authoritative": json.loads(
            (root / "runs" / run_id / "run_info.json").read_text(encoding="utf-8")
        )["authoritative"],
    }

    # --- negative control 1: 3511th optimizer reservation is refused ---------
    boundary_root = fresh_root("s1-r5-boundary-")
    boundary_doc = document(updates=UPDATES + 1, checkpoints=[0, UPDATES + 1])
    boundary_ledger, boundary_run = run_train(
        boundary_root, doc=boundary_doc, budget_steps=UPDATES
    )
    boundary_reservations: list[int] = []
    original_boundary = boundary_ledger.reserve

    def boundary_spy(run_id_arg, *, active_seconds, optimizer_steps=0):
        boundary_reservations.append(int(optimizer_steps))
        return original_boundary(
            run_id_arg, active_seconds=active_seconds, optimizer_steps=optimizer_steps
        )

    boundary_ledger.reserve = boundary_spy
    boundary_error = None
    try:
        worker._train(
            boundary_doc,
            boundary_root,
            boundary_ledger,
            boundary_run,
            Guard(),
            arm_id="arm2",
            seed=0,
            prereg_sha256=PREREG_SHA,
            backend=CountingBackend(),
        )
    except worker.BudgetStop as exc:
        boundary_error = f"{type(exc).__name__}: {exc}"
    boundary_ledger.close()
    with RunStore(boundary_root / "control.sqlite3") as store:
        boundary_record = store.get_run(boundary_run)
        boundary_state = {
            "state": boundary_record.state,
            "reserved_optimizer_steps": int(boundary_record.reserved_optimizer_steps),
        }
        try:
            store.consume(boundary_run, optimizer_steps=1, active_seconds=0.01)
            consume_refused = None
        except BudgetExceeded as exc:
            consume_refused = f"{type(exc).__name__}: {exc}"
    boundary = {
        "document_updates": UPDATES + 1,
        "run_budget_optimizer_steps": UPDATES,
        "reservation_pattern_head": boundary_reservations[:3],
        "reservation_pattern_tail": boundary_reservations[-3:],
        "reservations_total": len(boundary_reservations),
        "refusal": boundary_error,
        "run_state_after_refusal": boundary_state,
        "direct_consume_refused": consume_refused,
    }

    # --- negative control 2: eval replays the completed run, not run_info ----
    eval_backend = CountingBackend()
    result = worker._evaluate_arm(
        document(),
        root,
        arm_id="arm2",
        seed=0,
        prereg_sha256=PREREG_SHA,
        backend=eval_backend,
    )

    # --- negative control 3: tampered / missing / wrong-prereg bindings ------
    tampered_root = Path(tempfile.mkdtemp(prefix="s1-r5-tampered-"))
    shutil.copytree(root, tampered_root, dirs_exist_ok=True)
    params = tampered_root / "runs" / run_id / receipt["final_checkpoint_path"]
    params.chmod(0o644)
    with open(params, "ab") as handle:
        handle.write(b"tampered")
    tampered_error = None
    try:
        worker._bind_completed_run(
            tampered_root, arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, updates=UPDATES
        )
    except worker.EvalBindingError as exc:
        tampered_error = str(exc)

    missing_root = Path(tempfile.mkdtemp(prefix="s1-r5-missing-"))
    shutil.copytree(root, missing_root, dirs_exist_ok=True)
    (missing_root / "runs" / run_id / "checkpoints" / "updates-0.npz").unlink()
    missing_error = None
    try:
        worker._bind_completed_run(
            missing_root, arm_id="arm2", seed=0, prereg_sha256=PREREG_SHA, updates=UPDATES
        )
    except worker.EvalBindingError as exc:
        missing_error = str(exc)

    wrong_prereg_error = None
    try:
        worker._bind_completed_run(
            root, arm_id="arm2", seed=0, prereg_sha256="f" * 64, updates=UPDATES
        )
    except worker.EvalBindingError as exc:
        wrong_prereg_error = str(exc)

    groups = {
        key: (sorted(result[key]) if isinstance(result.get(key), dict) else None)
        for key in (
            "localization_error",
            "unseen_map_generalization",
            "topology_recovery",
            "few_shot_unseen_transition",
            "sample_efficiency",
            "m2_memory_interference",
        )
    }
    few = result["few_shot_unseen_transition"]
    topo = result["topology_recovery"]
    sample = result["sample_efficiency"]
    m2 = result["m2_memory_interference"]
    eval_section = {
        "status": result["status"],
        "run_binding": result["run_binding"],
        "checkpoint_sha256": result["checkpoint_sha256"],
        "parameter_sha256": result["parameter_sha256"],
        "dataset_digest": result["dataset_digest"],
        "groups": groups,
        "unseen_map": {
            key: result["unseen_map_generalization"][key]
            for key in ("episodes", "worlds", "translation_mean_m", "translation_median_m")
            if key in result["unseen_map_generalization"]
        },
        "topology": {
            key: topo[key]
            for key in ("episodes", "worlds", "precision", "recall", "f1")
            if key in topo
        },
        "topology_families": sorted(topo.get("by_family") or {}),
        "few_shot": {
            "k_values": few["k_values"],
            "curve": {
                k: {
                    "queries": row["queries"],
                    "worlds": row["worlds"],
                    "accuracy": row["accuracy"],
                    "displacement_mae_m": row["displacement_mae_m"],
                }
                for k, row in (few.get("curve") or {}).items()
            },
            "unavailable": few.get("unavailable") or {},
        },
        "sample_efficiency_updates": [
            row["updates"] for row in sample["checkpoints"]
        ],
        "sample_efficiency_curves": {
            "nll_points": len(sample["nll_curve"].get("checkpoints", [])),
            "localization_points": len(sample["localization_curve"].get("checkpoints", [])),
        },
        "m2": {
            "zero_state": m2["zero_state"],
            "history_paired": m2["history_paired"],
            "after_new_world": m2["after_new_world"],
            "retention_delta": {
                key: m2[key]
                for key in m2
                if "delta" in key or "retention" in key
            },
            "parameter_sha256_before": m2["probe"]["parameter_sha256_before"],
            "parameter_sha256_after": m2["probe"]["parameter_sha256_after"],
        },
        "model_calls": {
            "window_probe_calls": eval_backend.window_probe_calls,
            "window_probe_batches": eval_backend.window_probe_batches,
            "step_sequence_calls": eval_backend.step_sequence_calls,
            "step_frames": eval_backend.step_frames,
            "probe_graph_calls": eval_backend.probe_graph_calls,
            "encode_calls": eval_backend.encode_calls,
            "load_params_calls": eval_backend.load_calls,
            "save_params_calls": eval_backend.save_calls,
            "value_and_grad_calls": eval_backend.value_and_grad_calls,
        },
        "call_accounting_by_group": {
            "window_probe": "one probe over all development windows per frozen checkpoint "
            f"({len(CHECKPOINTS)} probes of {eval_backend.window_probe_batches} batches)",
            "topology_recovery": "one step_sequence + one probe_graph per development episode",
            "few_shot": "per k: one probe_graph plus one support step_sequence per world with a "
            "held-out query; two encode() calls per query transition",
            "m2": "three memory-paired step_sequence probes x 3 conditions + history/new-world "
            "writes; parameter SHA before/after",
            "sample_efficiency": "re-loads every frozen checkpoint and re-probes dev windows",
        },
        "registered_eval_batches": int(FROZEN["training_protocol"]["eval_batches"]),
    }

    evidence = {
        "schema": "ainerzero.v9.s1.r5.ledger_eval_evidence.v1",
        "spec": spec.SPEC_NAME,
        "backend": train_backend.name,
        "cpu_only": True,
        "mlx_imported": any(name.split(".")[0] == "mlx" for name in sys.modules),
        "dataset": {
            "digest": FROZEN["data_identity"]["dataset_digest"],
            "counts": FROZEN["data_identity"]["counts"],
        },
        "frozen_preregistration_sha256": PREREG_SHA,
        "frozen_updates": UPDATES,
        "frozen_checkpoints": CHECKPOINTS,
        "run_id": run_id,
        "train": {
            "seconds": train_seconds,
            "reservations_total": len(reservations),
            **frozen_checks,
            "run_state": train_state,
            "rerun_attempts_after_completed": attempts_after_completed,
        },
        "boundary_3511": boundary,
        "eval": eval_section,
        "binding_negative_controls": {
            "tampered_checkpoint": tampered_error,
            "missing_checkpoint": missing_error,
            "wrong_preregistration_sha": wrong_prereg_error,
        },
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": [
            "numeric CPU substitute; no MLX forward/gradient/training and no capability claim",
            "the training loss is a constant placeholder, so sample-efficiency values are plumbing-"
            "only, not scientific results",
            "the real 9 arm x seed runs are still refused until a tier-1 approval line exists",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps({k: evidence[k] for k in ("run_id", "train", "boundary_3511", "eval")}, indent=1)[:4000])
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
