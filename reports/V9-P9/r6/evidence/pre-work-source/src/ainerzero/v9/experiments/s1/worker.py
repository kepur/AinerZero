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
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from . import data, evaluation, prereg, resource_gate, runtime, spec

PREP_EXPERIMENT_ID = "s1-phase1-prereg-prep-20261021"
PREP_REQUEST_ID = "s1-phase1-prereg-prep"
TIMEZONE = "Europe/Belgrade"
PER_RUN_BUDGET = {"data": 600.0, "smoke": 300.0, "verify": 120.0}
TRAIN_EXPERIMENT_ID = spec.EXPERIMENT_ID


class BudgetStop(RuntimeError):
    """The run exhausted its reserved budget (never silently extended)."""


class EvalBindingError(RuntimeError):
    """A completed run/checkpoint/preregistration binding is missing or inconsistent."""


TRAIN_RECEIPT_PREFIX = "s1_train_completed:"
CHECKPOINT_RESERVE_SECONDS = 2.0
FINAL_SAVE_RESERVE_SECONDS = 0.5

# Modes whose budget (arm x seed attempts, phase wall total, optimizer steps)
# is anchored to the one central RunStore under the canonical phase-1 root.
# Preparation modes (data/smoke/verify) keep their per-root diagnostic ledger.
BOUNDED_MODES = ("train", "eval")
LEDGER_TABLES = {"metadata", "runs", "daily_budget", "run_transitions", "experiments"}


def canonical_ledger_path() -> Path:
    """The unique central RunStore for S1 phase 1 (notice #297 layout).

    Every bounded run registers here, never in a per-output-root copy: a new
    output root, a different cwd, another checkout or a copied preregistration
    must not be able to reset the attempt guard or the phase wall total.
    """
    return spec.PHASE1_ROOT / "control.sqlite3"


def canonical_ledger_state(path: Path | None = None) -> dict:
    """Read-only identity check of the central ledger (fail closed).

    A missing, unreadable, schema-less or unrecognised ledger is never opened
    for writing and never re-created: a bounded run fails closed instead of
    starting against a fresh, empty ledger.
    """
    ledger_path = Path(path) if path is not None else canonical_ledger_path()
    state: dict[str, Any] = {"path": str(ledger_path), "status": "ok"}
    if not ledger_path.is_file():
        state.update({"status": "missing", "reason": "no RunStore ledger file"})
        return state
    try:
        connection = sqlite3.connect(f"file:{ledger_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        state.update({"status": "unreadable", "reason": f"{type(exc).__name__}: {exc}"})
        return state
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not LEDGER_TABLES <= tables:
            state.update(
                {
                    "status": "unrecognized",
                    "reason": f"not a RunStore ledger (tables present: {sorted(tables)})",
                }
            )
            return state
        experiments = [
            row[0] for row in connection.execute("SELECT experiment_id FROM experiments")
        ]
        if PREP_EXPERIMENT_ID not in experiments:
            state.update(
                {
                    "status": "unrecognized",
                    "reason": "the phase-1 preparation experiment is absent; this is not the "
                    "central S1 phase-1 ledger",
                    "experiments": experiments,
                }
            )
            return state
        runs = int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
        state.update({"experiments": experiments, "runs": runs})
        return state
    except sqlite3.Error as exc:
        state.update({"status": "unreadable", "reason": f"{type(exc).__name__}: {exc}"})
        return state
    finally:
        connection.close()


def train_attempts(runs, *, arm_id: str, seed: int) -> list:
    """Runs that already *started* an arm x seed attempt.

    ``created`` is the only pre-start state.  Any other state (initializing,
    training, pausing, paused, completed, failed, stopped) means a real attempt
    was registered, so an unauthorized rerun must be refused.  A run that
    already reserved optimizer steps is also an attempt, even if a later
    lifecycle repair left it in a non-terminal state.
    """
    attempts = []
    for run in runs:
        config = run.config_snapshot or {}
        if config.get("arm_id") != arm_id:
            continue
        try:
            run_seed = int(config.get("seed", -1))
        except (TypeError, ValueError):
            continue
        if run_seed != int(seed):
            continue
        if run.state != "created" or int(run.reserved_optimizer_steps) > 0:
            attempts.append(run)
    return attempts


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


def run_config_snapshot(
    *, wall_budget_seconds: float, purpose: str, max_optimizer_steps: int = 1
) -> dict:
    return {
        "spec": spec.SPEC_NAME,
        "purpose": purpose,
        "budget": _budget_block(
            wall_budget_seconds, max_optimizer_steps=int(max_optimizer_steps)
        ),
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

    def open_aux_run(
        self,
        *,
        mode: str,
        wall_budget_seconds: float,
        manifest: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        experiment_id: str | None = None,
    ) -> str:
        experiment = self.store.create_experiment(
            prep_experiment_manifest() if manifest is None else manifest,
            PREP_REQUEST_ID if request_id is None else request_id,
            PREP_EXPERIMENT_ID if experiment_id is None else experiment_id,
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
    # r6 budget anchor: a bounded run (train/eval) registers in the one central
    # RunStore under the canonical phase-1 root and only runs at that root.  A
    # copied output root, a different cwd, another checkout or a copied
    # preregistration must not reset the arm x seed attempt guard or the phase
    # wall total; a missing/unreadable/unrecognized central ledger fails closed
    # and is never re-created.
    ledger_path = output_root / "control.sqlite3"
    if mode in BOUNDED_MODES:
        ledger_path = canonical_ledger_path()
        ledger_state = canonical_ledger_state(ledger_path)
        if ledger_state["status"] != "ok":
            return {
                "schema": "ainerzero.v9.s1.worker_report.v1",
                "spec": spec.SPEC_NAME,
                "mode": mode,
                "no_update": mode != "train",
                "control_db": str(ledger_path.resolve()),
                "status": "refused",
                "refused_stage": f"central_ledger_{ledger_state['status']}",
                "ledger": ledger_state,
                "message": "the central S1 phase-1 RunStore is missing, unreadable or "
                "unrecognized; a bounded run fails closed and never creates a new ledger",
            }
        if output_root.resolve() != spec.PHASE1_ROOT.resolve():
            return {
                "schema": "ainerzero.v9.s1.worker_report.v1",
                "spec": spec.SPEC_NAME,
                "mode": mode,
                "no_update": mode != "train",
                "control_db": str(ledger_path.resolve()),
                "status": "refused",
                "refused_stage": "output_root_not_canonical",
                "output_root": str(output_root.resolve()),
                "canonical_output_root": str(spec.PHASE1_ROOT.resolve()),
                "message": "train/eval only run at the canonical S1 phase-1 root; the "
                "central RunStore ledger and the phase budget are anchored there and a "
                "copied run root cannot reset them",
            }
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema": "ainerzero.v9.s1.worker_report.v1",
        "spec": spec.SPEC_NAME,
        "mode": mode,
        "no_update": mode != "train",
        "control_db": str(Path(ledger_path).resolve()),
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
    ledger = PrepLedger(ledger_path)
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

            # Guard: any *started* arm x seed attempt forbids an unauthorized rerun,
            # not only a completed one.  A pre-start resource refusal never reaches
            # this point (no run row exists), so the ledger stays authoritative.
            attempts = train_attempts(ledger.store.list_runs(), arm_id=arm, seed=seed)
            if attempts:
                first = attempts[0]
                report.update(
                    {
                        "status": "refused",
                        "refused_stage": "already_attempted",
                        "arm": arm,
                        "seed": seed,
                        "run_id": first.run_id,
                        "attempt_states": [r.state for r in attempts],
                        "attempt_run_ids": [r.run_id for r in attempts],
                        "message": f"arm {arm} seed {seed} already has a registered attempt "
                        f"({first.run_id}, state={first.state}); rerun is forbidden",
                    }
                )
                return report

            # Guard: check phase total wall clock budget <= 14400s
            phase_cap = float(document["timing"].get("phase_wall_max_seconds", 14400.0))
            deadline = float(document["timing"]["deadline_seconds"])
            total_wall = sum(
                float(r.wall_seconds)
                for r in ledger.store.list_runs()
                # The phase cap covers every registered run in this card-local
                # ledger, including auxiliary eval/verify runs.  Counting only the
                # training experiment would hide those costs.
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
            details = _train(
                document,
                output_root,
                ledger,
                active_run,
                guard,
                arm_id=arm,
                seed=seed,
                prereg_sha256=verified["sha256"],
            )
            report["details"] = details
            receipt = details.get("receipt") if isinstance(details, Mapping) else None
            if receipt:
                reason = TRAIN_RECEIPT_PREFIX + json.dumps(
                    receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            else:
                # Only a test double returns no receipt; a real _train always does.
                # Eval refuses such a run because it cannot bind an original SHA.
                reason = "s1_train_completed"
            record = ledger.finish(active_run, "completed", reason)
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
            # r6: evaluation consumption is registered inside the same
            # experiment as the training runs it scores, so the phase total
            # sees it.  The r1 preparation experiment's wall window has long
            # closed, so reusing it would refuse every eval at the canonical
            # root with an expired experiment wall budget.
            active_run = active_run or ledger.open_aux_run(
                mode="eval",
                wall_budget_seconds=budget,
                manifest=train_experiment_manifest(
                    deadline_seconds=float(document["timing"]["deadline_seconds"]),
                    updates=int(document["training_protocol"]["updates"]),
                ),
                request_id=f"{TRAIN_EXPERIMENT_ID}:training",
                experiment_id=TRAIN_EXPERIMENT_ID,
            )
            report["run_id"] = active_run
            report["experiment_id"] = PREP_EXPERIMENT_ID
            ledger.begin_work(active_run, work_state="validating")
            ledger.reserve(active_run, active_seconds=min(120.0, max(10.0, 0.5 * budget)))
            guard.sample(force=True)
            eval_details = _evaluate_arm(
                document,
                output_root,
                arm_id=arm,
                seed=eval_seed,
                prereg_sha256=verified["sha256"],
            )
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
    updates = int(document["training_protocol"]["updates"])
    snapshot = run_config_snapshot(
        wall_budget_seconds=float(document["timing"]["deadline_seconds"]),
        purpose=f"s1_phase1_training_run:{arm_id}:seed{seed}",
        # The run ledger must carry the *actual* frozen update count.  The old
        # default of 1 made the second optimizer reservation fail immediately;
        # the tail checkpoint reservation then failed as well because a zero
        # optimizer reserve is still rejected once the remaining count is 0.
        max_optimizer_steps=updates,
    )
    snapshot["arm_id"] = arm_id
    snapshot["seed"] = int(seed)
    snapshot["updates"] = updates
    snapshot["preregistration_sha256"] = approval.get("document_sha256")
    snapshot["dataset_digest"] = (document.get("data_identity") or {}).get("dataset_digest")
    snapshot["checkpoint_updates"] = [
        int(value) for value in document["training_protocol"].get("checkpoint_updates") or []
    ]
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


def _exclusive_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable metadata {path}")
    with open(path, "x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _exclusive_write_text(path: Path, text: str) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable metadata {path}")
    with open(path, "x", encoding="utf-8") as handle:
        handle.write(text)


def _checkpoint_path(output_root: Path, run_id: str, updates: int, update: int) -> Path:
    run_dir = Path(output_root) / "runs" / run_id
    if int(update) == int(updates):
        return run_dir / "params.npz"
    return run_dir / "checkpoints" / f"updates-{int(update)}.npz"


def _read_only(path: Path) -> None:
    try:
        Path(path).chmod(0o444)
    except OSError:
        pass


def _train(
    document: Mapping[str, Any],
    output_root: Path,
    ledger: PrepLedger,
    run_id: str,
    guard: resource_gate.RuntimeGuard,
    *,
    arm_id: str = "arm2",
    seed: int = 0,
    prereg_sha256: str | None = None,
    backend=None,
) -> dict:
    """Registered single arm x seed training loop for V9.P1 (r6 control flow).

    The ledger budget is the frozen update count, exactly.  Every one of the
    ``updates`` optimizer reservations also pre-reserves the wall allowance for
    the checkpoint probe/save that follows that update; no consume happens after
    the final optimizer step (the lifecycle rejects *any* reservation, including
    a zero-optimizer one, once an exhausted counter is at zero).

    r6 deadline semantics: the loop-top guard alone let the final gradient, the
    final checkpoint probe/save, the duty sleep and the receipt/metadata IO run
    past the frozen per-run deadline and still report ``completed``.  The real
    total wall clock is therefore re-checked before any authoritative receipt
    is written and again after the trailing metadata IO, so a timeout, a save
    failure or a guard refusal can never produce a legal ``completed`` run.
    """
    import numpy as np

    backend = backend or runtime.MlxBackend()
    protocol = document["training_protocol"]
    timing = document["timing"]
    updates = int(protocol["updates"])
    if updates <= 0:
        raise ValueError("the frozen training protocol has no updates")
    deadline = float(timing["deadline_seconds"])
    duty = float(document["resource_limits"]["training_duty_cycle"])
    dataset_dir = data.resolve_dataset_dir(output_root)
    train_windows = data.load_training_windows(dataset_dir)
    development_windows = data.load_development_windows(dataset_dir)

    declared = [int(value) for value in protocol.get("checkpoint_updates") or []]
    if any(value < 0 or value > updates for value in declared):
        raise ValueError(f"checkpoint updates {declared!r} are outside 0..{updates}")
    checkpoint_set = set(declared)

    started = time.perf_counter()
    arm_started = started

    def _enforce_deadline() -> None:
        # Exactly at the deadline is still inside budget; only strictly past it
        # aborts the run as failed (the 500 s supervision timeout stays the
        # outer hard fallback in commands.py).
        if time.perf_counter() - started > deadline:
            raise TimeoutError("frozen per-run deadline exceeded")

    model = backend.build_model(arm_id, seed=int(seed))
    optimizer = backend.make_optimizer(protocol)
    backend.init_optimizer(optimizer, model)
    value_grad = backend.value_and_grad(model)
    batches = data.iter_batches(
        train_windows, int(protocol["batch_size"]), seed=int(seed) + 17
    )

    run_dir = Path(output_root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    losses: list[float] = []
    curve: list[dict] = []
    saved: list[dict] = []
    checkpoint_wall_reservations = 0.0

    def _probe_and_save(update: int) -> None:
        nonlocal checkpoint_wall_reservations
        probe = backend.window_probe(model, development_windows, protocol)
        rows = probe.get("rows") or []
        if not rows:
            raise runtime.BackendError(
                f"checkpoint {update} development probe produced no rows; "
                "a missing NLL is not a zero"
            )
        development_nll = float(np.mean([float(row["loss"]) for row in rows]))
        curve.append(
            {
                "updates": int(update),
                "development_nll": development_nll,
                "nll_samples": len(rows),
                "batches": int(probe.get("batches", 0)),
            }
        )
        path = _checkpoint_path(output_root, run_id, updates, update)
        path.parent.mkdir(parents=True, exist_ok=True)
        backend.save_params(model, path, exclusive=True)
        _read_only(path)
        saved.append(
            {
                "updates": int(update),
                "path": str(path.relative_to(run_dir)),
                "sha256": spec.sha256_file(path),
                "parameter_sha256": backend.parameter_sha256(model),
                "development_nll": development_nll,
                "nll_samples": len(rows),
            }
        )

    # Checkpoint 0 is the pre-training measurement of record.  It is a wall-only
    # reservation: the optimizer counter is still untouched and positive.
    if 0 in checkpoint_set:
        ledger.reserve(run_id, active_seconds=CHECKPOINT_RESERVE_SECONDS)
        checkpoint_wall_reservations += CHECKPOINT_RESERVE_SECONDS
        _probe_and_save(0)

    previous = 0.05
    for update in range(1, updates + 1):
        _enforce_deadline()
        guard.sample()
        batch = next(batches)
        if update in checkpoint_set:
            extra = CHECKPOINT_RESERVE_SECONDS
        elif update == updates:
            extra = FINAL_SAVE_RESERVE_SECONDS
        else:
            extra = 0.0
        reservation = max(0.05, min(1.0, previous * 2.0)) + extra
        # Exactly one optimizer reservation per update, including the final one.
        ledger.reserve(run_id, active_seconds=reservation, optimizer_steps=1)
        if extra:
            checkpoint_wall_reservations += extra
        tick = time.perf_counter()
        (loss, _parts), grads = value_grad(model, batch)
        backend.eval(loss, grads)
        clipped, _norm = backend.clip_grad_norm(
            grads, float(protocol["gradient_clip_norm"])
        )
        backend.optimizer_update(optimizer, model, clipped)
        backend.sync_parameters(model, optimizer)
        previous = time.perf_counter() - tick
        losses.append(backend.loss_value(loss))
        if update in checkpoint_set:
            _probe_and_save(update)
        elif update == updates:
            path = _checkpoint_path(output_root, run_id, updates, update)
            path.parent.mkdir(parents=True, exist_ok=True)
            backend.save_params(model, path, exclusive=True)
            _read_only(path)
            saved.append(
                {
                    "updates": int(update),
                    "path": str(path.relative_to(run_dir)),
                    "sha256": spec.sha256_file(path),
                    "parameter_sha256": backend.parameter_sha256(model),
                    "development_nll": None,
                    "nll_samples": 0,
                }
            )
        rest = previous * (1.0 / duty - 1.0)
        if rest:
            time.sleep(min(rest, 2.0))

    # r6: the last gradient, the final checkpoint probe/save and the duty sleep
    # all happen after the final loop-top check, so the real total wall clock is
    # verified here, before any receipt or authoritative completion exists.
    _enforce_deadline()
    wall_seconds = time.perf_counter() - arm_started
    final_entries = [entry for entry in saved if int(entry["updates"]) == updates]
    if len(final_entries) != 1:
        raise RuntimeError(
            f"the final checkpoint was written {len(final_entries)} times (expected exactly once)"
        )
    final = final_entries[0]
    final_path = run_dir / final["path"]
    sha_text = f"{final['sha256']}  {Path(final['path']).name}\n"
    _exclusive_write_text(run_dir / "params.npz.sha256", sha_text)
    _read_only(run_dir / "params.npz.sha256")

    receipt = {
        "schema": "ainerzero.v9.s1.completion.v1",
        "spec": spec.SPEC_NAME,
        "run_id": run_id,
        "arm_id": arm_id,
        "seed": int(seed),
        "updates": updates,
        "preregistration_sha256": prereg_sha256,
        "dataset_digest": (document.get("data_identity") or {}).get("dataset_digest"),
        "checkpoint_updates": sorted(entry["updates"] for entry in saved),
        "checkpoints": sorted(saved, key=lambda entry: int(entry["updates"])),
        "final_checkpoint_updates": updates,
        "final_checkpoint_path": final["path"],
        "final_checkpoint_sha256": final["sha256"],
        "final_parameter_sha256": final["parameter_sha256"],
        "sample_efficiency_curve": curve,
        "final_training_loss": losses[-1] if losses else None,
        "wall_seconds": wall_seconds,
        "backend": getattr(backend, "name", type(backend).__name__),
        "ledger_accounting": {
            "optimizer_reservations": updates,
            "checkpoint_wall_reservations_seconds": checkpoint_wall_reservations,
            "post_final_optimizer_reservations": 0,
        },
        "checkpoint_policy": "one optimizer reservation per update; the final update's "
        "reservation includes the checkpoint probe/save wall allowance; no ledger "
        "consume is issued after the final optimizer step",
    }
    _exclusive_write_json(run_dir / "completion.json", receipt)
    run_info = {
        "schema": "ainerzero.v9.s1.run_info.v1",
        "authoritative": False,
        "authoritative_receipt": "completion.json",
        "note": "convenience copy only; eval binds the completed RunStore run, the "
        "frozen preregistration, the arm/seed and the original checkpoint SHA",
        **{key: receipt[key] for key in (
            "run_id",
            "arm_id",
            "seed",
            "updates",
            "preregistration_sha256",
            "dataset_digest",
            "final_checkpoint_sha256",
            "final_parameter_sha256",
            "sample_efficiency_curve",
            "final_training_loss",
            "wall_seconds",
        )},
        "checkpoint_path": str(final_path.resolve()),
        "checkpoint_sha256": final["sha256"],
        "parameter_sha256": final["parameter_sha256"],
    }
    _exclusive_write_json(run_dir / "run_info.json", run_info)
    # The ledger transition to ``completed`` happens after this return; trailing
    # metadata IO must not be able to cross the deadline unnoticed either.
    _enforce_deadline()

    return {
        "arm_id": arm_id,
        "seed": int(seed),
        "updates": updates,
        "final_training_loss": losses[-1] if losses else None,
        "sample_efficiency_curve": curve,
        "parameter_sha256": final["parameter_sha256"],
        "checkpoint_path": str(final_path.resolve()),
        "checkpoint_sha256": final["sha256"],
        "checkpoints": sorted(saved, key=lambda entry: int(entry["updates"])),
        "receipt": receipt,
        "wall_seconds": wall_seconds,
        "status": "completed",
    }


def _parse_receipt(reason: str | None) -> dict:
    if not reason:
        raise EvalBindingError("completed run has no completion receipt")
    if not reason.startswith(TRAIN_RECEIPT_PREFIX):
        raise EvalBindingError("completed run reason is not an r5 completion receipt")
    try:
        receipt = json.loads(reason[len(TRAIN_RECEIPT_PREFIX) :])
    except (TypeError, ValueError) as exc:
        raise EvalBindingError("completion receipt is not valid JSON") from exc
    if not isinstance(receipt, dict):
        raise EvalBindingError("completion receipt is not an object")
    return receipt


def _bind_completed_run(
    output_root: Path,
    *,
    arm_id: str,
    seed: int,
    prereg_sha256: str | None,
    updates: int,
    ledger_path: Path | None = None,
) -> dict:
    """Bind eval to the ledger's completed run and its original checkpoint SHA.

    The expected checkpoint digest comes from the immutable transition reason
    written when the run completed, never from ``run_info.json`` (which is only a
    convenience copy) and never from a re-hash of a tampered file.

    r6: the ledger is the one central RunStore by default, so a copied run root
    cannot bind against its own ledger copy; tests may pass an explicit
    ``ledger_path`` for an isolated fixture.
    """
    output_root = Path(output_root)
    control_db = (
        Path(ledger_path) if ledger_path is not None else canonical_ledger_path()
    )
    if not control_db.is_file():
        raise EvalBindingError(f"no RunStore ledger at {control_db}")
    from ainerzero.runtime.lifecycle import RunStore

    with RunStore(control_db) as store:
        runs = store.list_runs()
    matches = []
    for run in runs:
        config = run.config_snapshot or {}
        if run.state != "completed" or run.role != "model":
            continue
        if config.get("arm_id") != arm_id:
            continue
        try:
            if int(config.get("seed", -1)) != int(seed):
                continue
            if int(config.get("updates", -1)) != int(updates):
                continue
        except (TypeError, ValueError):
            continue
        if prereg_sha256 is not None and config.get("preregistration_sha256") != prereg_sha256:
            continue
        matches.append(run)
    if not matches:
        raise EvalBindingError(
            f"no completed run binds arm={arm_id} seed={seed} updates={updates} "
            f"preregistration={prereg_sha256}"
        )
    if len(matches) > 1:
        raise EvalBindingError(
            "more than one completed run matches this arm/seed/preregistration: "
            + ", ".join(sorted(run.run_id for run in matches))
        )
    run = matches[0]
    config = run.config_snapshot or {}
    budget_steps = int((config.get("budget") or {}).get("max_optimizer_steps", -1))
    if budget_steps != int(updates):
        raise EvalBindingError(
            f"run {run.run_id} budget max_optimizer_steps={budget_steps} does not equal "
            f"the frozen updates={updates}"
        )
    if int(run.reserved_optimizer_steps) != int(updates):
        raise EvalBindingError(
            f"run {run.run_id} reserved {run.reserved_optimizer_steps} optimizer steps, "
            f"not the frozen {updates}"
        )
    receipt = _parse_receipt(run.reason)
    for field, expected in (
        ("run_id", run.run_id),
        ("arm_id", arm_id),
        ("seed", int(seed)),
        ("updates", int(updates)),
    ):
        if receipt.get(field) != expected:
            raise EvalBindingError(
                f"completion receipt {field}={receipt.get(field)!r} does not match {expected!r}"
            )
    if prereg_sha256 is not None and receipt.get("preregistration_sha256") != prereg_sha256:
        raise EvalBindingError(
            "completion receipt is bound to a different preregistration SHA"
        )
    run_dir = (output_root / "runs" / run.run_id).resolve()
    entries = receipt.get("checkpoints") or []
    if not entries:
        raise EvalBindingError("completion receipt lists no checkpoints")
    checkpoints: dict[int, dict] = {}
    for entry in entries:
        try:
            update = int(entry["updates"])
            relative = Path(str(entry["path"]))
            expected_sha = str(entry["sha256"])
            expected_param = str(entry["parameter_sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvalBindingError("malformed checkpoint entry in completion receipt") from exc
        if relative.is_absolute() or ".." in relative.parts:
            raise EvalBindingError(f"checkpoint path escapes the run directory: {relative}")
        path = (run_dir / relative).resolve()
        if run_dir not in path.parents:
            raise EvalBindingError(f"checkpoint path escapes the run directory: {relative}")
        if not path.is_file():
            raise EvalBindingError(f"bound checkpoint is missing: {relative}")
        actual = spec.sha256_file(path)
        if actual != expected_sha:
            raise EvalBindingError(
                f"checkpoint {relative} SHA {actual} does not match the original "
                f"receipt SHA {expected_sha}"
            )
        if update in checkpoints:
            raise EvalBindingError(f"checkpoint update {update} appears twice")
        checkpoints[update] = {
            "updates": update,
            "path": path,
            "sha256": actual,
            "parameter_sha256": expected_param,
        }
    if int(updates) not in checkpoints:
        raise EvalBindingError("the completion receipt has no final checkpoint")
    if checkpoints[int(updates)]["path"].name != "params.npz":
        raise EvalBindingError("the final checkpoint is not runs/<run_id>/params.npz")
    if receipt.get("final_checkpoint_sha256") != checkpoints[int(updates)]["sha256"]:
        raise EvalBindingError("completion receipt final SHA disagrees with its checkpoint list")
    if receipt.get("dataset_digest") != (
        (config.get("dataset_digest") or None)
    ):
        raise EvalBindingError("completion receipt dataset digest disagrees with the run record")
    return {
        "run": run,
        "receipt": receipt,
        "checkpoints": checkpoints,
        "final": checkpoints[int(updates)],
        "run_dir": run_dir,
    }


def _evaluate_arm(
    document: Mapping[str, Any],
    output_root: Path,
    *,
    arm_id: str,
    seed: int = 0,
    prereg_sha256: str | None = None,
    backend=None,
) -> dict:
    import numpy as np

    from . import metrics

    backend = backend or runtime.MlxBackend()
    dataset_dir = data.resolve_dataset_dir(output_root)
    protocol = document["training_protocol"]
    updates = int(protocol["updates"])

    if arm_id == "arm1":
        # arm1 is the only frozen D-candidate path; keep the MLX-importing module
        # out of the arm2/3/4 evaluation import graph.
        from . import arms

        model, info = arms.load_d_candidate()
        batch = arms.d_candidate_fixed_batch()
        out = arms.d_candidate_forward_loss(model, batch, seed=int(seed))
        nll0 = float(out.metrics["symbol_nll_t0"])
        nll1 = float(out.metrics["symbol_nll_t1"])
        incomparable = list(spec.ARM_SPECS["arm1"]["incomparable"])
        not_applicable = {"status": "not_applicable", "reason": "incomparable input layout"}
        return {
            "arm_id": arm_id,
            "seed": int(seed),
            "kind": "frozen_candidate",
            "name": spec.ARM_SPECS["arm1"]["name"],
            "parameter_count": info["parameter_count"],
            "parameter_sha256": info["parameter_sha256"],
            "localization_error": not_applicable,
            "unseen_map_generalization": not_applicable,
            "topology_recovery": not_applicable,
            "few_shot_unseen_transition": not_applicable,
            "sample_efficiency": not_applicable,
            "m2_memory_interference": {
                "status": "not_applicable",
                "reason": "the frozen D candidate is a single fixed C0 probe; it has no "
                "S1 episodic memory to probe",
                "d_candidate_symbol_nll_t0": nll0,
                "d_candidate_symbol_nll_t1": nll1,
            },
            "d_candidate_c0_metrics": out.metrics,
            "incomparable": incomparable,
            "run_binding": {"status": "not_applicable", "kind": "frozen_candidate"},
            "status": "completed",
        }

    binding = _bind_completed_run(
        output_root,
        arm_id=arm_id,
        seed=int(seed),
        prereg_sha256=prereg_sha256,
        updates=updates,
    )
    receipt = binding["receipt"]
    document_digest = (document.get("data_identity") or {}).get("dataset_digest")
    if receipt.get("dataset_digest") != document_digest:
        raise EvalBindingError(
            "the completed run was trained on a different dataset digest than the "
            "frozen document"
        )
    actual_dataset = data.dataset_binding_state(output_root, document_digest)
    if actual_dataset.get("status") != "passed":
        raise EvalBindingError(
            f"dataset binding is {actual_dataset.get('status')}, expected passed"
        )

    model = backend.build_model(arm_id, seed=int(seed))
    final = binding["final"]
    backend.load_params(model, final["path"])
    loaded_param_sha = backend.parameter_sha256(model)
    if loaded_param_sha != final["parameter_sha256"]:
        raise EvalBindingError(
            "loaded parameters do not match the original receipt parameter SHA"
        )

    development_windows = data.load_development_windows(dataset_dir)
    truth_view = data.load_truth_view(dataset_dir, "development")
    if not truth_view:
        raise evaluation.EvaluationError("no development truth rows")

    final_probe = backend.window_probe(model, development_windows, protocol)
    final_rows = evaluation.development_rows(final_probe, truth_view)
    localization = evaluation.localization_report(final_rows)

    # Dual sample-efficiency curve: every frozen checkpoint is re-loaded from its
    # bound path and scored on the same development windows with the evaluator
    # truth sidecar (NLL + localization at each checkpoint).
    sample_rows = []
    for update in sorted(binding["checkpoints"]):
        entry = binding["checkpoints"][update]
        backend.load_params(model, entry["path"])
        loaded = backend.parameter_sha256(model)
        if loaded != entry["parameter_sha256"]:
            raise EvalBindingError(
                f"checkpoint {update} parameter SHA {loaded} does not match the "
                f"original receipt SHA {entry['parameter_sha256']}"
            )
        if update == updates:
            probe = final_probe
            rows = final_rows
        else:
            probe = backend.window_probe(model, development_windows, protocol)
            rows = evaluation.development_rows(probe, truth_view)
        unseen = metrics.strict_unseen_map(rows)
        sample_rows.append(
            {
                "updates": int(update),
                "development_nll": float(
                    np.mean([float(row["prediction_nll"]) for row in rows])
                ),
                "localization_translation_mean_m": float(
                    unseen["translation_mean_m"]
                ),
                "nll_samples": len(rows),
                "localization_samples": int(unseen["episodes"]),
            }
        )
    # Leave the model at the final checkpoint for the episodic probes.
    backend.load_params(model, final["path"])
    if backend.parameter_sha256(model) != final["parameter_sha256"]:
        raise EvalBindingError("final checkpoint reload changed the parameter SHA")

    development_episodes = data.load_training_episodes(dataset_dir, "development")
    sequences = [data.build_episode_sequence(episode) for episode in development_episodes]
    topology = evaluation.topology_report(backend, model, sequences, truth_view)
    few_shot = evaluation.few_shot_report(backend, model, sequences, truth_view)
    if len(sequences) < 5:
        raise evaluation.EvaluationError(
            "the M2 probe needs at least five development worlds"
        )
    probe_sequences = sequences[:3]
    history_sequence = sequences[3]
    new_world_sequence = sequences[4]
    interference = evaluation.m2_interference(
        backend,
        model,
        probe_sequences,
        truth_view,
        history_sequence,
        new_world_sequence,
    )
    sample_efficiency = evaluation.sample_efficiency(sample_rows)

    suite = metrics.metric_suite_report(
        localization=localization,
        unseen=localization["unseen"],
        topology=topology,
        few_shot=few_shot,
        sample_efficiency=sample_efficiency,
        interference=interference,
        arm_id=arm_id,
        seed=int(seed),
    )
    suite.update(
        {
            "name": spec.ARM_SPECS[arm_id]["name"],
            "kind": "trainable",
            "preregistration_sha256": prereg_sha256,
            "dataset_digest": document_digest,
            "run_binding": {
                "status": "passed",
                "run_id": binding["run"].run_id,
                "state": binding["run"].state,
                "reserved_optimizer_steps": int(binding["run"].reserved_optimizer_steps),
                "checkpoint_updates": sorted(binding["checkpoints"]),
                "final_checkpoint_path": str(final["path"]),
                "final_checkpoint_sha256": final["sha256"],
                "final_parameter_sha256": final["parameter_sha256"],
                "expected_sha_source": "immutable completed-run reason receipt",
                "run_info_used_for_binding": False,
            },
            "checkpoint_path": str(final["path"]),
            "checkpoint_sha256": final["sha256"],
            "parameter_sha256": final["parameter_sha256"],
            "incomparable": list(spec.ARM_SPECS[arm_id]["incomparable"]),
            "status": "completed",
        }
    )
    return suite



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
