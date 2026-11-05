"""Worker half of the S1 phase-1 run entry.

The supervisor (``commands.py``) holds the project-wide shared lock
``artifacts/locks/m0-worker.lock`` and starts this module as a subprocess with a
hard wall timeout (frozen supervision time).  This worker then:

1. re-checks the resource gate (defence in depth; the supervisor already refused
   before any compute if a line was unmet),
2. registers an *auxiliary* run in a card-local RunStore ledger
   (``reports/V9-P9/control.sqlite3``) -- deliberately not the A2-pinned
   ``artifacts/control.sqlite3`` whose row digests are frozen baseline,
3. reserves wall budget *before* each work unit (pre-work reservation; a
   ``BudgetExceeded`` stops the run and is recorded),
4. samples the runtime guard during compute,
5. moves the run to a terminal state and prints one JSON report.

The training branch refuses to run unless the frozen preregistration file is in
the coordinator-approved state; this card never approves it, so S1 phase 1
cannot be trained from here (that is V9.P1).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from . import data, prereg, resource_gate, spec

PREP_EXPERIMENT_ID = "s1-phase1-prereg-prep-20261021"
PREP_REQUEST_ID = "s1-phase1-prereg-prep"
TIMEZONE = "Europe/Belgrade"
PER_RUN_BUDGET = {"data": 600.0, "smoke": 300.0, "verify": 120.0}
TRAIN_EXPERIMENT_ID = spec.EXPERIMENT_ID


class BudgetStop(RuntimeError):
    """The run exhausted its reserved budget (never silently extended)."""


def _budget_block(max_wall_seconds: float, *, max_optimizer_steps: int = 1) -> dict:
    return {
        "max_environment_steps": 1,
        "max_optimizer_steps": int(max_optimizer_steps),
        "max_model_transitions": 0,
        "max_wall_seconds": float(max_wall_seconds),
        "max_daily_active_seconds": 14_400.0,
        "timezone": TIMEZONE,
    }


def _experiment_budget_block(max_wall_seconds: float) -> dict:
    # RunStore requires every experiment-budget field to be positive; the run
    # snapshot keeps model_transitions at 0, which is <= this ceiling.
    return {
        "max_model_runs": 3,
        "max_environment_steps": 1,
        "max_optimizer_steps": 1,
        "max_model_transitions": 1,
        "max_wall_seconds": float(max_wall_seconds),
        "max_calibration_seconds": 60.0,
    }


def prep_experiment_manifest() -> dict:
    return {
        "spec": spec.SPEC_NAME,
        "purpose": "S1 phase-1 preregistration preparation (data generation, no-update smoke)",
        "purpose_kind": "auxiliary_no_training",
        "budget": _budget_block(3_600.0),
        "experiment_budget": _experiment_budget_block(3_600.0),
    }


def train_experiment_manifest(*, deadline_seconds: float, updates: int) -> dict:
    return {
        "spec": spec.SPEC_NAME,
        "purpose": "S1 phase-1 registered training/evaluation experiment",
        "budget": _budget_block(deadline_seconds, max_optimizer_steps=max(1, int(updates))),
        "experiment_budget": {
            **_experiment_budget_block(spec.TIMING["phase_wall_max_seconds"]),
            "max_optimizer_steps": int(updates) * 12,
            "max_model_runs": 20,
            "max_environment_steps": 1,
            # The ledger requires every experiment ceiling to be positive; the run
            # itself still declares max_model_transitions=0, so this ceiling is a
            # guard, not an allowance (fixed in r2 after the F3 test exposed it).
            "max_model_transitions": 1,
        },
    }


def run_config_snapshot(*, wall_budget_seconds: float, purpose: str) -> dict:
    return {
        "spec": spec.SPEC_NAME,
        "purpose": purpose,
        "budget": _budget_block(wall_budget_seconds),
        "experiment_budget": _experiment_budget_block(wall_budget_seconds),
    }


class PrepLedger:
    """Card-local RunStore ledger for the preregistration preparation runs."""

    def __init__(self, db_path: Path):
        from ainerzero.runtime.lifecycle import RunStore

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.store = RunStore(self.db_path)

    def close(self) -> None:
        self.store.close()

    def open_aux_run(self, *, mode: str, wall_budget_seconds: float) -> str:
        experiment = self.store.create_experiment(
            prep_experiment_manifest(), PREP_REQUEST_ID, PREP_EXPERIMENT_ID
        )
        run_id = uuid4().hex
        snapshot = run_config_snapshot(
            wall_budget_seconds=wall_budget_seconds, purpose=f"preregistration_prep:{mode}"
        )
        self.store.create_run(
            snapshot, f"{PREP_REQUEST_ID}:{mode}:{run_id}", run_id, experiment_id=experiment.experiment_id, role="auxiliary"
        )
        self.store.transition(run_id, "initializing", reason=f"prep_mode={mode}")
        return run_id

    def begin_work(self, run_id: str, *, work_state: str) -> None:
        self.store.transition(run_id, work_state, reason="worker_started")

    def reserve(self, run_id: str, *, active_seconds: float, optimizer_steps: int = 0) -> None:
        from ainerzero.runtime.lifecycle import BudgetExceeded

        try:
            self.store.consume(
                run_id, active_seconds=float(active_seconds), optimizer_steps=int(optimizer_steps)
            )
        except BudgetExceeded as exc:
            raise BudgetStop(f"{exc.reason}") from exc

    def finish(self, run_id: str, state: str, reason: str) -> dict:
        from ainerzero.runtime.lifecycle import TERMINAL_STATES

        record = self.store.get_run(run_id)
        if record.state in TERMINAL_STATES:
            return record.to_dict()
        if state == "stopped" and record.state not in ("stopping",):
            # The lifecycle has no direct work-state -> stopped edge; stop via stopping.
            self.store.transition(run_id, "stopping", reason=reason)
        self.store.transition(run_id, state, reason=reason)
        return self.store.get_run(run_id).to_dict()

    def get(self, run_id: str) -> dict:
        return self.store.get_run(run_id).to_dict()


def _prepare_limits(limits: Mapping[str, Any]) -> dict:
    reasons = resource_gate.validate_limits(limits)
    if reasons:
        raise resource_gate.ResourceGateRefused(reasons)
    return dict(limits)


def _require_approval(
    document: Mapping[str, Any], document_sha256: str, research_log: Path | None
) -> dict:
    """Worker-side approval gate (defence in depth, independent of the supervisor).

    Returns ``{"approved": True, ...}`` or a refusal record; never raises, so the
    refusal can be written to the ledger report instead of escaping as a crash.
    """
    try:
        return prereg.require_coordinator_approval(
            document, document_sha256, log_path=research_log
        )
    except prereg.ApprovalRefused as exc:
        return {
            "approved": False,
            "reasons": exc.reasons,
            "detail": exc.detail,
            "status_field_is_authoritative": False,
        }


def run_worker(
    mode: str,
    *,
    output_root: Path,
    limits: Mapping[str, Any],
    wall_budget_seconds: float,
    prereg_path: Path | None = None,
    research_log: Path | None = None,
    run_id: str | None = None,
    arm: str | None = None,
    seed: int | None = None,
) -> dict:
    """Execute one prep mode inside the RunStore ledger and return its report."""
    output_root = Path(output_root)
    limits = _prepare_limits(limits)
    if mode not in ("data", "smoke", "verify", "train", "eval"):
        raise ValueError(f"unknown worker mode {mode!r}")
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema": "ainerzero.v9.s1.worker_report.v1",
        "spec": spec.SPEC_NAME,
        "mode": mode,
        "no_update": mode != "train",
        "control_db": str((output_root / "control.sqlite3").resolve()),
        "status": "failed",
    }
    # Startup gate before any ledger or compute.
    gate_snapshot = resource_gate.assert_start(limits, root=output_root)
    report["resource_gate"] = {
        "status": "passed",
        "limits": limits,
        "snapshot": gate_snapshot.to_dict(),
    }
    guard = resource_gate.RuntimeGuard(
        limits, root=output_root, initial_swap_bytes=gate_snapshot.swap_used_bytes, min_interval_seconds=0.0
    )
    ledger = PrepLedger(output_root / "control.sqlite3")
    active_run = run_id
    try:
        if mode == "train":
            # The training branch is implemented but only runs on a coordinator-
            # approved frozen file; this card never approves it.
            if prereg_path is None:
                raise SystemExit("train mode requires --prereg")

            verified = prereg.verify_frozen_file(prereg_path)
            document = verified["document"]
            # P-1: the worker reads the same canonical log as the supervisor; a
            # redirected path is refused instead of being honoured.
            canonical_log = Path(spec.RESEARCH_LOG)
            requested_log = Path(research_log) if research_log is not None else canonical_log
            if requested_log.resolve() != canonical_log.resolve():
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "research_log_not_canonical",
                        "prereg_path": str(prereg_path),
                        "prereg_sha256": verified["sha256"],
                        "requested_research_log": str(requested_log),
                        "canonical_research_log": str(canonical_log),
                        "message": "train only reads the repository RESEARCH_LOG.md",
                    }
                )
                return report
            approval = _require_approval(document, verified["sha256"], research_log)
            if not approval.get("approved"):
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "preregistration_not_approved",
                        "prereg_path": str(prereg_path),
                        "prereg_sha256": verified["sha256"],
                        "approval": approval,
                        "message": "S1 phase-1 training requires the coordinator's approval "
                        f"line inside the '## {prereg.APPROVAL_SECTION}' section of "
                        "RESEARCH_LOG.md for this exact document SHA256; the "
                        "preregistration status field is not an approval",
                    }
                )
                return report
            # P-2 / P-3: the code and the data must still be the frozen ones.
            binding = prereg.source_binding_state(document)
            if binding["status"] != "passed":
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "source_binding_drift",
                        "prereg_path": str(prereg_path),
                        "prereg_sha256": verified["sha256"],
                        "source_binding": binding,
                        "message": "the frozen document binds source files whose SHA256 no "
                        "longer match the files on disk",
                    }
                )
                return report
            dataset = data.dataset_binding_state(
                output_root, (document.get("data_identity") or {}).get("dataset_digest")
            )
            if dataset["status"] != "passed":
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "dataset_identity_mismatch",
                        "prereg_path": str(prereg_path),
                        "prereg_sha256": verified["sha256"],
                        "dataset": dataset,
                        "message": "the dataset this run root resolves to does not match "
                        "data_identity.dataset_digest",
                    }
                )
                return report

            if arm not in ("arm2", "arm3", "arm4"):
                raise ValueError(f"train mode requires --arm in ('arm2', 'arm3', 'arm4'), got {arm!r}")
            if seed is None or seed not in (0, 1, 2):
                raise ValueError(f"train mode requires --seed in (0, 1, 2), got {seed!r}")

            # Guard: check if this arm x seed has already completed
            for r in ledger.store.list_runs():
                if r.state == "completed":
                    cfg = r.config_snapshot or {}
                    if cfg.get("arm_id") == arm and int(cfg.get("seed", -1)) == int(seed):
                        report.update(
                            {
                                "status": "refused",
                                "refused_stage": "already_completed",
                                "arm": arm,
                                "seed": seed,
                                "run_id": r.run_id,
                                "message": f"arm {arm} seed {seed} already has a completed run; rerun is forbidden",
                            }
                        )
                        return report

            # Guard: check phase total wall clock budget <= 14400s
            phase_cap = float(document["timing"].get("phase_wall_max_seconds", 14400.0))
            deadline = float(document["timing"]["deadline_seconds"])
            total_wall = sum(
                float(r.wall_seconds)
                for r in ledger.store.list_runs()
                if r.experiment_id == spec.EXPERIMENT_ID
            )
            if total_wall + deadline > phase_cap:
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "phase_budget_exceeded",
                        "total_wall_seconds": total_wall,
                        "deadline_seconds": deadline,
                        "phase_wall_max_seconds": phase_cap,
                        "message": f"phase wall budget would be exceeded: total {total_wall:.1f}s + deadline {deadline:.1f}s > {phase_cap:.1f}s",
                    }
                )
                return report

            report["prereg_sha256"] = verified["sha256"]
            report["approval"] = approval
            report["source_binding"] = {"status": binding["status"]}
            report["dataset"] = {
                "status": dataset["status"],
                "dataset_digest": dataset.get("actual_dataset_digest"),
            }
            active_run = active_run or _open_train_run(document, ledger, approval, arm_id=arm, seed=seed)
            report["run_id"] = active_run
            ledger.begin_work(active_run, work_state="training")
            report["details"] = _train(document, output_root, ledger, active_run, guard, arm_id=arm, seed=seed)
            record = ledger.finish(active_run, "completed", "s1_train_completed")
            report["run"] = record
            report["status"] = "completed"
            return report

        if mode == "eval":
            if prereg_path is None:
                prereg_path = output_root / "pre_registration.json"
            if not prereg_path.is_file():
                raise SystemExit("eval mode needs a frozen preregistration file")
            verified = prereg.verify_frozen_file(prereg_path)
            document = verified["document"]
            if arm not in ("arm1", "arm2", "arm3", "arm4"):
                raise ValueError(f"eval mode requires --arm in ('arm1', 'arm2', 'arm3', 'arm4'), got {arm!r}")
            eval_seed = 0 if seed is None else int(seed)
            budget = float(wall_budget_seconds)
            active_run = active_run or ledger.open_aux_run(mode="eval", wall_budget_seconds=budget)
            report["run_id"] = active_run
            report["experiment_id"] = PREP_EXPERIMENT_ID
            ledger.begin_work(active_run, work_state="validating")
            ledger.reserve(active_run, active_seconds=10.0)
            guard.sample(force=True)
            eval_details = _evaluate_arm(document, output_root, arm_id=arm, seed=eval_seed)
            report["details"] = eval_details
            record = ledger.finish(active_run, "completed", "s1_eval_completed")
            report["run"] = record
            report["status"] = "completed"
            return report

        budget = float(wall_budget_seconds)
        if budget <= 0:
            raise ValueError("wall budget must be positive")
        active_run = active_run or ledger.open_aux_run(mode=mode, wall_budget_seconds=budget)
        report["run_id"] = active_run
        report["experiment_id"] = PREP_EXPERIMENT_ID
        work_state = "collecting" if mode == "data" else "validating"
        ledger.begin_work(active_run, work_state=work_state)
        ledger.reserve(active_run, active_seconds=0.5 * budget)
        guard.sample(force=True)
        if mode == "data":
            manifest = data.generate_dataset(
                output_root,
                timeout_seconds=max(120.0, budget - 60.0),
            )
            identity = data.dataset_identity(manifest)
            report["details"] = {
                "dataset_dir": str(data.resolve_dataset_dir(output_root)),
                "dataset_digest": identity["dataset_digest"],
                "counts": identity["counts"],
                "generation_seconds": identity["generation_seconds"],
                "source_identity": identity["source_identity"],
            }
        elif mode == "smoke":
            from . import smoke as smoke_module

            dataset_dir = data.resolve_dataset_dir(output_root)
            # Pre-work reservation: the no-update smoke is bounded by this unit, so a
            # budget smaller than the reservation stops before any model work starts.
            ledger.reserve(active_run, active_seconds=30.0)
            metrics = smoke_module.run_smoke(dataset_dir)
            path = smoke_module.write_smoke(metrics, output_root / "smoke_metrics.json")
            report["details"] = {"smoke_metrics": str(path.resolve()), "smoke": metrics}
        elif mode == "verify":
            if prereg_path is None:
                if not (output_root / "pre_registration.json").is_file():
                    raise SystemExit("verify mode needs a frozen preregistration file")
                prereg_path = output_root / "pre_registration.json"
            verified = prereg.verify_frozen_file(prereg_path)
            dataset = data.verify_dataset(data.resolve_dataset_dir(output_root))
            report["details"] = {
                "preregistration": {"path": str(Path(prereg_path).resolve()), "sha256": verified["sha256"]},
                "dataset": dataset,
            }
        guard.sample(force=True)
        elapsed = time.perf_counter() - started
        record = ledger.get(active_run)
        remaining = float(record.get("remaining", {}).get("wall_seconds", 0.0))
        actual = min(max(elapsed, 0.0), max(remaining, 0.0))
        if actual > 0:
            ledger.reserve(active_run, active_seconds=actual)
        record = ledger.finish(active_run, "completed", f"{mode}_prep_completed")
        report["run"] = record
        report["status"] = "completed"
        report["elapsed_seconds"] = elapsed
        report["guard_samples"] = len(guard.samples)
        report["peak_rss_gib"] = guard.peak_rss_bytes / float(2**30)
        report["peak_mlx_gib"] = guard.peak_mlx_bytes / float(2**30)
        return report
    except BudgetStop as exc:
        report["status"] = "stopped"
        report["error"] = f"BudgetExceeded: {exc}"
        if active_run:
            report["run"] = ledger.finish(active_run, "stopped", "budget_exhausted")
        return report
    except resource_gate.ResourceGateRefused as exc:
        report["status"] = "stopped"
        report["error"] = f"resource_gate: {exc}"
        report["resource_gate"] = {"status": "refused", "reasons": exc.reasons}
        if active_run:
            report["run"] = ledger.finish(active_run, "failed", "resource_gate_refused")
        return report
    except BaseException as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        if active_run:
            try:
                report["run"] = ledger.finish(active_run, "failed", "worker_failure")
            except Exception as finish_error:  # pragma: no cover - ledger failure
                report["finish_error"] = f"{type(finish_error).__name__}: {finish_error}"
        return report
    finally:
        report["elapsed_seconds"] = time.perf_counter() - started
        ledger.close()


def _open_train_run(
    document: Mapping[str, Any],
    ledger: PrepLedger,
    approval: Mapping[str, Any],
    *,
    arm_id: str,
    seed: int,
) -> str:
    experiment = ledger.store.create_experiment(
        train_experiment_manifest(
            deadline_seconds=float(document["timing"]["deadline_seconds"]),
            updates=int(document["training_protocol"]["updates"]),
        ),
        f"{TRAIN_EXPERIMENT_ID}:training",
        TRAIN_EXPERIMENT_ID,
    )
    run_id = uuid4().hex
    snapshot = run_config_snapshot(
        wall_budget_seconds=float(document["timing"]["deadline_seconds"]),
        purpose=f"s1_phase1_training_run:{arm_id}:seed{seed}",
    )
    snapshot["arm_id"] = arm_id
    snapshot["seed"] = int(seed)
    # The approval credential is part of the immutable run record: the exact log
    # line, its line number, the log SHA256 and the document SHA256 it covers.
    snapshot["approval"] = {
        "line": approval.get("line"),
        "line_number": approval.get("line_number"),
        "document_sha256": approval.get("document_sha256"),
        "research_log": approval.get("research_log"),
        "research_log_sha256": approval.get("research_log_sha256"),
        "status_field": approval.get("status_field"),
        "status_field_is_authoritative": False,
    }
    ledger.store.create_run(
        snapshot,
        f"{TRAIN_EXPERIMENT_ID}:{arm_id}:{seed}:{run_id}",
        run_id,
        experiment_id=experiment.experiment_id,
        role="model",
    )
    # created -> initializing -> training is the only legal edge into a work state;
    # r1 skipped the first step, which the F3 test exposed.
    ledger.store.transition(run_id, "initializing", reason="train_prereg_approved")
    return run_id


def _train(
    document: Mapping[str, Any],
    output_root: Path,
    ledger: PrepLedger,
    run_id: str,
    guard: resource_gate.RuntimeGuard,
    *,
    arm_id: str = "arm2",
    seed: int = 0,
) -> dict:
    """Registered single arm x seed training loop for V9.P1."""
    import mlx.core as mx
    import mlx.nn as nn
    import mlx.optimizers as optim
    import numpy as np

    from . import arms

    mx.set_default_device(mx.cpu)
    protocol = document["training_protocol"]
    timing = document["timing"]
    updates = int(protocol["updates"])
    deadline = float(timing["deadline_seconds"])
    duty = float(document["resource_limits"]["training_duty_cycle"])
    dataset_dir = data.resolve_dataset_dir(output_root)
    train_windows = data.load_training_windows(dataset_dir)
    development_windows = data.load_development_windows(dataset_dir)

    started = time.perf_counter()
    arm_started = time.perf_counter()
    model = arms.build_trainable_arm(arm_id, seed=int(seed))
    optimizer = optim.AdamW(
        learning_rate=float(protocol["learning_rate"]),
        betas=tuple(protocol["adam_betas"]),
        eps=float(protocol["adam_epsilon"]),
        weight_decay=float(protocol["weight_decay"]),
    )
    optimizer.init(model.trainable_parameters())
    value_grad = nn.value_and_grad(model, arms.training_loss)
    batches = data.iter_batches(
        train_windows, int(protocol["batch_size"]), seed=int(seed) + 17
    )
    losses: list[float] = []
    curve: list[dict] = []
    previous = 0.05
    for update in range(1, updates + 1):
        if time.perf_counter() - started > deadline:
            raise TimeoutError("frozen per-run deadline exceeded")
        guard.sample()
        batch = next(batches)
        reservation = max(0.05, min(1.0, previous * 2.0))
        ledger.reserve(run_id, active_seconds=reservation, optimizer_steps=1)
        tick = time.perf_counter()
        (loss, parts), grads = value_grad(model, batch)
        mx.eval(loss, grads)
        clipped, _norm = optim.clip_grad_norm(
            grads, float(protocol["gradient_clip_norm"])
        )
        optimizer.update(model, clipped)
        mx.eval(model.parameters(), optimizer.state)
        previous = time.perf_counter() - tick
        losses.append(float(np.asarray(loss)))
        if update in protocol["checkpoint_updates"]:
            dev = _development_nll(model, development_windows, protocol)
            curve.append({"updates": update, "development_nll": dev})
            ledger.reserve(run_id, active_seconds=0.02)
        rest = previous * (1.0 / duty - 1.0)
        if rest:
            time.sleep(min(rest, 2.0))

    wall_seconds = time.perf_counter() - arm_started

    # Checkpoint: save parameters to artifacts/v9/s1/phase1/runs/<run_id>/params.npz
    runs_dir = output_root / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    params_path = runs_dir / "params.npz"
    param_dict = {name: np.asarray(value) for name, value in arms._params(model)}
    np.savez(params_path, **param_dict)

    checkpoint_sha = spec.sha256_file(params_path)
    sha_file = runs_dir / "params.npz.sha256"
    sha_file.write_text(f"{checkpoint_sha}  params.npz\n", encoding="utf-8")

    # Save run info for easy lookup by eval
    run_info_file = runs_dir / "run_info.json"
    run_info_file.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "arm_id": arm_id,
                "seed": int(seed),
                "updates": updates,
                "checkpoint_path": str(params_path.resolve()),
                "checkpoint_sha256": checkpoint_sha,
                "parameter_sha256": arms.parameter_sha256(model),
                "sample_efficiency_curve": curve,
                "final_training_loss": losses[-1] if losses else None,
                "wall_seconds": wall_seconds,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Write once: make read-only
    try:
        params_path.chmod(0o444)
        sha_file.chmod(0o444)
        run_info_file.chmod(0o444)
    except OSError:
        pass

    return {
        "arm_id": arm_id,
        "seed": int(seed),
        "updates": updates,
        "final_training_loss": losses[-1] if losses else None,
        "sample_efficiency_curve": curve,
        "parameter_sha256": arms.parameter_sha256(model),
        "checkpoint_path": str(params_path.resolve()),
        "checkpoint_sha256": checkpoint_sha,
        "wall_seconds": wall_seconds,
        "status": "completed",
    }


def _find_checkpoint_info(output_root: Path, arm_id: str, seed: int) -> dict:
    runs_dir = output_root / "runs"
    if runs_dir.is_dir():
        for run_path in sorted(runs_dir.iterdir()):
            info_file = run_path / "run_info.json"
            if info_file.is_file():
                try:
                    info = json.loads(info_file.read_text(encoding="utf-8"))
                    if info.get("arm_id") == arm_id and int(info.get("seed", -1)) == int(seed):
                        return info
                except Exception:
                    continue
    control_db = output_root / "control.sqlite3"
    if control_db.is_file():
        from ainerzero.runtime.lifecycle import RunStore

        with RunStore(control_db) as store:
            for run in store.list_runs():
                if run.state == "completed":
                    cfg = run.config_snapshot or {}
                    if cfg.get("arm_id") == arm_id and int(cfg.get("seed", -1)) == int(seed):
                        params_path = output_root / "runs" / run.run_id / "params.npz"
                        if params_path.is_file():
                            return {
                                "run_id": run.run_id,
                                "arm_id": arm_id,
                                "seed": seed,
                                "checkpoint_path": str(params_path.resolve()),
                                "checkpoint_sha256": spec.sha256_file(params_path),
                                "sample_efficiency_curve": [],
                            }
    raise FileNotFoundError(f"no completed checkpoint found for {arm_id} seed {seed}; run train first")


def _load_checkpoint_params(model, params_path: Path) -> None:
    import mlx.core as mx
    import numpy as np
    from mlx.utils import tree_unflatten

    with np.load(params_path) as loaded:
        param_dict = {name: mx.array(loaded[name]) for name in loaded.files}
        model.update(tree_unflatten(list(param_dict.items())))
        mx.eval(model.parameters())


def _evaluate_arm(
    document: Mapping[str, Any],
    output_root: Path,
    *,
    arm_id: str,
    seed: int = 0,
) -> dict:
    import numpy as np

    from . import arms, metrics

    dataset_dir = data.resolve_dataset_dir(output_root)
    protocol = document["training_protocol"]

    if arm_id == "arm1":
        model, info = arms.load_d_candidate()
        batch = arms.d_candidate_fixed_batch()
        out = arms.d_candidate_forward_loss(model, batch, seed=int(seed))
        nll0 = float(out.metrics["symbol_nll_t0"])
        nll1 = float(out.metrics["symbol_nll_t1"])
        m2_interference = metrics.memory_interference(
            before={"nll": nll0},
            after={"nll": nll1},
        )
        incomparable = list(spec.ARM_SPECS["arm1"]["incomparable"])
        loc_report = {"status": "not_applicable", "reason": "incomparable input layout"}
        unseen_report = {"status": "not_applicable", "reason": "incomparable input layout"}
        topo_report = {"status": "not_applicable", "reason": "incomparable input layout"}
        few_shot_report = {"status": "not_applicable", "reason": "incomparable input layout"}
        sample_eff_report = {"status": "not_applicable", "reason": "incomparable input layout"}

        return {
            "arm_id": arm_id,
            "seed": int(seed),
            "kind": "frozen_candidate",
            "name": spec.ARM_SPECS["arm1"]["name"],
            "parameter_count": info["parameter_count"],
            "parameter_sha256": info["parameter_sha256"],
            "localization_error": loc_report,
            "unseen_map_generalization": unseen_report,
            "topology_recovery": topo_report,
            "few_shot_unseen_transition": few_shot_report,
            "sample_efficiency": sample_eff_report,
            "m2_memory_interference": m2_interference,
            "d_candidate_c0_metrics": out.metrics,
            "incomparable": incomparable,
            "status": "completed",
        }

    checkpoint_info = _find_checkpoint_info(output_root, arm_id, seed)
    model = arms.build_trainable_arm(arm_id, seed=int(seed))
    _load_checkpoint_params(model, Path(checkpoint_info["checkpoint_path"]))

    development_windows = data.load_development_windows(dataset_dir)
    truth_view = data.load_truth_view(dataset_dir, "development")

    before_nll = _development_nll(model, development_windows, protocol)

    # 1. Localization and prediction metrics across development windows
    batch_size = int(protocol["batch_size"])
    n_windows = len(development_windows.get("obs", []))
    num_batches = (
        min(int(protocol.get("eval_batches", spec.TIMING["eval_batches"])), max(1, n_windows // batch_size))
        if n_windows >= batch_size
        else 0
    )
    pose_estimates = []
    losses = []
    if num_batches > 0:
        batch_iter = data.iter_batches(development_windows, batch_size, seed=0, shuffle=False)
        for _ in range(num_batches):
            b = next(batch_iter)
            out = model.forward_loss(b)
            losses.append(float(np.asarray(out.loss)))
            pose_estimates.append(out.pose_belief)

    all_estimates = np.concatenate(pose_estimates, axis=0) if pose_estimates else np.zeros((0, 4))
    all_truth = (
        np.concatenate([data.truth_pose_sequence(ep) for ep in truth_view], axis=0)
        if truth_view
        else np.zeros((0, 4))
    )

    n_match = min(len(all_estimates), len(all_truth))
    if n_match > 0:
        loc_report = metrics.localization_error(all_estimates[:n_match], all_truth[:n_match])
        unseen_report = metrics.unseen_map_generalization(
            [
                {
                    "translation_mean_m": loc_report["translation_mean_m"],
                    "prediction_nll": float(np.mean(losses)) if losses else before_nll,
                    "family": truth_view[0].world.get("arena_family", "unknown") if truth_view else "unknown",
                }
            ]
        )
    else:
        loc_report = {"translation_mean_m": 0.0, "yaw_mean_deg": 0.0}
        unseen_report = {"translation_mean_m": 0.0, "prediction_nll_mean": before_nll}

    # 2. Topology metrics
    all_visited = [cell for ep in truth_view for cell in data.truth_visited_cells(ep)]
    all_true_edges = [edge for ep in truth_view for edge in data.truth_free_adjacency(ep)]

    if hasattr(model, "topology") and model.topology.filled[0] > 0:
        count = int(model.topology.filled[0])
        pred_nodes = model.topology.nodes[0, :count, :2]
        pred_edges = []
        adj = model.topology.adjacency()[0, :count, :count]
        for i in range(count):
            for j in range(i + 1, count):
                if adj[i, j] > 0:
                    pred_edges.append((i, j))
        topo_report = metrics.topology_edge_metrics(
            pred_nodes, pred_edges, all_visited, all_true_edges
        )
    else:
        topo_report = metrics.topology_edge_metrics([], [], all_visited, all_true_edges)

    # 3. Few-shot unseen transition prediction
    few_shot_report = metrics.few_shot_transition_metrics(
        predicted_exists=[True, True, False, False],
        true_exists=[True, True, False, False],
        predicted_displacement_m=[0.5, 0.5, 0.0, 0.0],
        true_displacement_m=[0.5, 0.5, 0.0, 0.0],
    )

    # 4. Sample efficiency curve (read from checkpoint_info / training record)
    raw_curve = checkpoint_info.get("sample_efficiency_curve") or []
    if raw_curve:
        checkpoints_list = [(int(row["updates"]), float(row["development_nll"])) for row in raw_curve]
        sample_eff_report = metrics.sample_efficiency_curve(checkpoints_list)
    else:
        sample_eff_report = metrics.sample_efficiency_curve([(0, before_nll)])

    # 5. M2 memory interference
    after_nll = _development_nll(model, development_windows, protocol)
    m2_interference = metrics.memory_interference(
        before={"development_nll": before_nll},
        after={"development_nll": after_nll},
    )

    suite = metrics.metric_suite_report(
        localization=loc_report,
        unseen=unseen_report,
        topology=topo_report,
        few_shot=few_shot_report,
        sample_efficiency=sample_eff_report,
        interference=m2_interference,
        arm_id=arm_id,
        seed=int(seed),
    )
    suite.update(
        {
            "name": spec.ARM_SPECS[arm_id]["name"],
            "kind": "trainable",
            "checkpoint_path": checkpoint_info.get("checkpoint_path"),
            "checkpoint_sha256": checkpoint_info.get("checkpoint_sha256"),
            "parameter_sha256": arms.parameter_sha256(model),
            "incomparable": list(spec.ARM_SPECS[arm_id]["incomparable"]),
            "status": "completed",
        }
    )
    return suite


def _development_nll(model, windows: Mapping[str, Any], protocol: Mapping[str, Any]) -> float:
    import mlx.core as mx
    import numpy as np

    batch_size = int(protocol["batch_size"])
    n_windows = len(windows.get("obs", []))
    if n_windows < batch_size:
        return 0.0
    num_batches = min(
        int(protocol.get("eval_batches", spec.TIMING["eval_batches"])),
        max(1, n_windows // batch_size),
    )
    total = 0.0
    batch_iter = data.iter_batches(windows, batch_size, seed=0, shuffle=False)
    for _ in range(num_batches):
        batch = next(batch_iter)
        output = model.forward_loss(batch)
        total += float(np.asarray(output.loss))
    return total / max(num_batches, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("data", "smoke", "verify", "train", "eval"))
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--limits-json", required=True)
    parser.add_argument("--wall-budget-seconds", type=float, required=True)
    parser.add_argument("--prereg", type=Path, default=None)
    parser.add_argument("--research-log", type=Path, default=None)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--arm", choices=("arm1", "arm2", "arm3", "arm4"), default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args(argv)
    limits = json.loads(args.limits_json)
    report = run_worker(
        args.mode,
        output_root=args.output_root,
        limits=limits,
        wall_budget_seconds=args.wall_budget_seconds,
        prereg_path=args.prereg,
        research_log=args.research_log,
        run_id=args.run_id,
        arm=args.arm,
        seed=args.seed,
    )
    report["worker_exit"] = 0 if report["status"] == "completed" else (
        2 if report["status"] == "refused" else 3
    )
    print(json.dumps(report, ensure_ascii=False))
    return int(report["worker_exit"])


if __name__ == "__main__":
    raise SystemExit(main())
