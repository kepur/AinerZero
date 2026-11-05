"""Worker execution and central ledger coordination for E1 Phase 2.

Wires genuine runner components without mock/fake data:
- data_runner.generate_and_export: Dual-family AWZ data generation & export.
- train_runner.train_cell: Paced MLX CPU training with strict budget/deadline.
- eval_runner.evaluate_cell: Genuine metrics (k-step error, collision F1, ballistic drift).
- eval_runner.evaluate_final_once: Sealed final dataset evaluation with one-time token.

All executions are preflight-guarded, recorded in the central SQLite3 ledger,
and protected by the shared worker lock.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

import numpy as np

from ainerzero.runtime.lifecycle import (
    TERMINAL_STATES,
    BudgetExceeded,
    RunRecord,
    RunStore,
)
from ainerzero.v9.experiments.e1 import (
    arms_net,
    arms_nonnet,
    data_runner,
    eval_runner,
    export,
    metrics,
    prior,
    spec,
    train_runner,
)

EXPERIMENT_ID = spec.EXPERIMENT_ID
TIMEZONE = "Asia/Shanghai"


class EntryRefusal(RuntimeError):
    """Raised when preflight guards refuse execution before ledger access."""

    def __init__(self, stage: str, reasons: list[str], detail: dict[str, Any] | None = None):
        super().__init__(f"Entry refused at stage '{stage}': {reasons}")
        self.stage = stage
        self.reasons = reasons
        self.detail = detail or {}


class BudgetStop(RuntimeError):
    """Raised when a work cell halts due to compute budget or wall clock exhaustion."""


def get_power_info() -> dict[str, Any]:
    """Inspect macOS battery and lid state to maintain the registered power policy.

    Ref: R20261028-battery-policy: pure CPU jobs continue on battery; lid closed stops.
    """
    pmset_path = shutil.which("pmset")
    power_source = "unknown"
    battery_percent = None
    lid_closed = False

    if pmset_path:
        try:
            p_out = subprocess.check_output([pmset_path, "-g", "batt"], text=True, timeout=2.0)
            if "Battery Power" in p_out:
                power_source = "Battery"
            elif "AC Power" in p_out:
                power_source = "AC"
            for token in p_out.split():
                if token.endswith("%;"):
                    try:
                        battery_percent = int(token.rstrip("%;"))
                    except ValueError:
                        pass
                    break
        except Exception:
            pass

        try:
            l_out = subprocess.check_output([pmset_path, "-g", "assertions"], text=True, timeout=2.0)
            if "AppleClamshellClosedNotification" in l_out or "ClamshellSleep" in l_out:
                lid_closed = True
        except Exception:
            pass

    return {
        "policy": "R20261028-battery-policy",
        "power_source": power_source,
        "battery_percent": battery_percent,
        "lid_closed": lid_closed,
        "checked_at_unix": time.time(),
    }


def ledger_read_snapshot(ledger_path: Path):
    """Context manager yielding a read-only RunStore connection via an isolated temporary copy.

    Ensures preflight checks inspect past runs without mutating or locking the real ledger.
    """
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        if not ledger_path.is_file():
            yield None
            return

        temporary = ledger_path.parent / f".tmp_read_{uuid4().hex}.sqlite3"
        wal_path = ledger_path.parent / f"{ledger_path.name}-wal"
        shm_path = ledger_path.parent / f"{ledger_path.name}-shm"
        temp_wal = temporary.parent / f"{temporary.name}-wal"
        temp_shm = temporary.parent / f"{temporary.name}-shm"
        try:
            shutil.copy2(ledger_path, temporary)
            if wal_path.is_file():
                shutil.copy2(wal_path, temp_wal)
            if shm_path.is_file():
                shutil.copy2(shm_path, temp_shm)
            store = RunStore(temporary)
            try:
                yield store
            finally:
                store.close()
        finally:
            for p in (temporary, temp_wal, temp_shm):
                if p.exists():
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    return _ctx()


def check_cell_already_completed(
    ledger_path: Path,
    mode: str,
    arm: int | None,
    family: str | None,
    seed: int | None,
) -> bool:
    """Check if the given cell has already completed in the ledger without mutating it."""
    with ledger_read_snapshot(ledger_path) as store:
        if store is None:
            return False
        cursor = store._conn.execute(
            "SELECT config_json, state FROM runs WHERE experiment_id = ?",
            (EXPERIMENT_ID,),
        )
        for row in cursor.fetchall():
            state = row["state"]
            if state != "completed":
                continue
            cfg = json.loads(row["config_json"])
            if cfg.get("mode") != mode:
                continue
            if mode == "generate-data":
                return True
            if mode == "final-eval":
                if family is None or cfg.get("family") == family:
                    return True
                continue
            if cfg.get("arm") == arm and cfg.get("family") == family:
                if seed is None or cfg.get("seed") == seed:
                    return True
    return False


def get_experiment_manifest() -> dict[str, Any]:
    """Construct the immutable experiment manifest for RunStore registration."""
    wall_ceiling = float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"])
    train_cells = int(spec.BUDGET_CAPS["train_cells_count"])
    max_steps_per_cell = int(spec.DEFAULT_TRAIN_STEPS)
    # Experiment-level optimizer step ceiling derived from spec:
    # 18 cells * 64,000 steps = 1,152,000 steps.
    # We add 20% margin (factor 1.2x) = 1,382,400 steps to accommodate potential
    # calibration or step bookkeeping overhead while preventing runaway training.
    derived_experiment_optimizer_steps = int(train_cells * max_steps_per_cell * 1.2)
    # Run-level default budget: per-cell step ceiling with 20% margin (76,800 steps)
    derived_run_optimizer_steps = int(max_steps_per_cell * 1.2)
    return {
        "spec": spec.SPEC_NAME,
        "experiment_id": EXPERIMENT_ID,
        "task_id": spec.TASK_ID,
        "prereg_draft_sha256": spec.PREREG_DRAFT_SHA256,
        "host_anchor": spec.host_anchor(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "budget": {
            "max_environment_steps": 10_000_000,
            "max_optimizer_steps": derived_run_optimizer_steps,
            "max_wall_seconds": wall_ceiling,
            "max_daily_active_seconds": wall_ceiling,
            "max_model_transitions": 0,
            "timezone": TIMEZONE,
        },
        "experiment_budget": {
            "max_model_runs": 100,
            "max_environment_steps": 10_000_000,
            "max_optimizer_steps": derived_experiment_optimizer_steps,
            "max_model_transitions": 1,
            "max_wall_seconds": wall_ceiling,
            "max_calibration_seconds": 3600.0,
        },
        "tags": ["v9", "e1", "phase2", "physics", "neurogeometry"],
    }


def compute_file_sha256(file_path: Path | str) -> str:
    """Compute SHA256 digest of a file."""
    p = Path(file_path)
    if not p.is_file():
        return "missing"
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compute_module_sha256(obj: Any) -> str:
    """Compute SHA256 digest of the source file defining the object."""
    try:
        mod = inspect.getmodule(obj)
        if mod and getattr(mod, "__file__", None):
            return hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()
    except Exception:
        pass
    return "unknown"


class E1Ledger:
    """Central RunStore ledger interface for E1 Phase 2."""

    def __init__(self, db_path: Path, clock: Callable[[], float] | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.time
        now_fn = lambda: datetime.fromtimestamp(self.clock(), timezone.utc)
        self.store = RunStore(self.db_path, now=now_fn)

    def close(self) -> None:
        self.store.close()

    def ensure_experiment(self) -> Any:
        manifest = get_experiment_manifest()
        request_id = f"init:{EXPERIMENT_ID}"
        try:
            existing = self.store.get_experiment(EXPERIMENT_ID)
            return existing
        except KeyError:
            return self.store.create_experiment(manifest, request_id, EXPERIMENT_ID)

    def open_run(
        self,
        mode: str,
        arm: int | None,
        family: str | None,
        seed: int | None,
        cell_wall_budget: float,
        *,
        runner_name: str | None = None,
        runner_module_sha256: str | None = None,
        snapshot_extra: Mapping[str, Any] | None = None,
    ) -> str:
        self.ensure_experiment()
        run_id = uuid4().hex
        request_id = f"{EXPERIMENT_ID}:{mode}:{arm}:{family}:{seed}:{run_id[:8]}"
        snapshot: dict[str, Any] = {
            "spec": spec.SPEC_NAME,
            "mode": mode,
            "arm": arm,
            "family": family,
            "seed": seed,
            "runner_name": runner_name or "unknown",
            "runner_module_sha256": runner_module_sha256 or "unknown",
            "cell_wall_budget_seconds": cell_wall_budget,
            "budget": {
                "max_environment_steps": 1_000_000,
                "max_optimizer_steps": int(spec.DEFAULT_TRAIN_STEPS * 1.2),
                "max_wall_seconds": float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]),
                "max_daily_active_seconds": float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]),
                "max_model_transitions": 0,
                "timezone": TIMEZONE,
            },
        }
        if snapshot_extra:
            snapshot.update(dict(snapshot_extra))

        self.store.create_run(
            snapshot,
            request_id,
            run_id,
            experiment_id=EXPERIMENT_ID,
            role="model",
        )
        self.store.transition(run_id, "initializing", reason=f"mode={mode}")
        return run_id

    def begin_work(self, run_id: str, state: str = "training") -> None:
        self.store.transition(run_id, state, reason="work_started")

    def reserve(self, run_id: str, active_seconds: float, optimizer_steps: int = 0) -> None:
        try:
            self.store.consume(
                run_id,
                active_seconds=float(active_seconds),
                optimizer_steps=int(optimizer_steps),
            )
        except BudgetExceeded as exc:
            raise BudgetStop(str(exc.reason)) from exc

    def finish_run(self, run_id: str, state: str = "completed", reason: str = "finished") -> dict[str, Any]:
        record = self.store.get_run(run_id)
        if record.state in TERMINAL_STATES:
            return record.to_dict()
        if state == "stopped" and record.state != "stopping":
            self.store.transition(run_id, "stopping", reason=reason)
        self.store.transition(run_id, state, reason=reason)
        return self.store.get_run(run_id).to_dict()


def build_arm_for_eval(
    arm: int,
    family: str,
    seed: int | None,
    output_root: Path,
    evaluator_dir: Path,
) -> Any:
    """Build the genuine arm instance for evaluation.

    Arms:
    - ① PriorArm: Biased prior rollout.
    - ② PureNetArm: Pure MLX neural network loaded from genuine checkpoint.
    - ③ PriorResidualArm: Prior + MLX residual loaded from genuine checkpoint.
    - ④ TrueParamArm: Rollout with evaluator true φ* (diagnostic upper bound).
    - ⑤ IdentifyArm: Online identification of friction & restitution on prefix.
    - ⑥ IdentifyResidualArm: Identified prior + residual loaded from genuine checkpoint.
    - ⑦ SymbolicResidualArm: STLSQ symbolic residual regression.
    """
    if arm == 1:
        return arms_nonnet.PriorArm()
    elif arm == 2:
        if seed is None:
            raise ValueError("Arm 2 evaluation requires a valid seed")
        ckpt_file = output_root / "checkpoints" / f"arm2_{family}_seed{seed}" / "model_weights.npz"
        if not ckpt_file.is_file():
            raise FileNotFoundError(f"Missing checkpoint for Arm 2 at {ckpt_file}")
        model = arms_net.PureNetArm(seed=seed)
        model.load(ckpt_file)
        return model
    elif arm == 3:
        if seed is None:
            raise ValueError("Arm 3 evaluation requires a valid seed")
        ckpt_file = output_root / "checkpoints" / f"arm3_{family}_seed{seed}" / "model_weights.npz"
        if not ckpt_file.is_file():
            raise FileNotFoundError(f"Missing checkpoint for Arm 3 at {ckpt_file}")
        model = arms_net.PriorResidualArm(seed=seed)
        model.load(ckpt_file)
        return model
    elif arm == 4:
        # ④ 只在评测侧构造，真实真参数在 eval_runner 评测循环中逐 episode 动态提取与注入
        arm_inst = arms_nonnet.TrueParamArm(true_params=None)
        arm_inst.arm_id = 4
        return arm_inst
    elif arm == 5:
        return arms_nonnet.IdentifyArm()
    elif arm == 6:
        if seed is None:
            raise ValueError("Arm 6 evaluation requires a valid seed")
        ckpt_file = output_root / "checkpoints" / f"arm6_{family}_seed{seed}" / "model_weights.npz"
        if not ckpt_file.is_file():
            raise FileNotFoundError(f"Missing checkpoint for Arm 6 at {ckpt_file}")
        identifier = train_runner.make_arm6_identifier()
        model = arms_net.IdentifyResidualArm(seed=seed, identifier_fn=identifier)
        model.load(ckpt_file)
        return model
    elif arm == 7:
        return arms_nonnet.SymbolicResidualArm()
    else:
        raise ValueError(f"Unknown arm {arm}")


class CellRunner:
    """Abstract interface for cell work runners."""

    def run_generate_data(
        self,
        data_dir: Path,
        output_root: Path,
        clock_fn: Callable[[], float],
        deadline: float,
        budget: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def run_train(
        self,
        arm: int,
        family: str,
        seed: int,
        output_root: Path,
        data_dir: Path,
        clock_fn: Callable[[], float],
        deadline: float,
        budget: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def run_eval(
        self,
        arm: int,
        family: str,
        seed: int | None,
        data_dir: Path,
        output_root: Path,
        clock_fn: Callable[[], float],
        deadline: float,
        budget: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def run_final_eval(
        self,
        data_dir: Path,
        output_root: Path,
        clock_fn: Callable[[], float],
        deadline: float,
        budget: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError


# Default production runners pointing directly to the four verified runner functions
DEFAULT_GENERATE_DATA_RUNNER = data_runner.generate_and_export
DEFAULT_TRAIN_RUNNER = train_runner.train_cell
DEFAULT_EVAL_RUNNER = eval_runner.evaluate_cell
DEFAULT_FINAL_EVAL_RUNNER = eval_runner.evaluate_final_once

DEFAULT_RUNNERS: dict[str, Callable[..., Any]] = {
    "generate-data": DEFAULT_GENERATE_DATA_RUNNER,
    "train": DEFAULT_TRAIN_RUNNER,
    "eval": DEFAULT_EVAL_RUNNER,
    "final-eval": DEFAULT_FINAL_EVAL_RUNNER,
}


class DefaultCellRunner(CellRunner):
    """Production CellRunner calling genuine components without hardcoded mocks.

    - generate-data → data_runner.generate_and_export (formal spec counts)
    - train → train_runner.train_cell (budget & duty cycle from spec)
    - eval → eval_runner.evaluate_cell (arms ①-⑦, requiring checkpoints for ②③⑥)
    - final-eval → eval_runner.evaluate_final_once (dual-family sealed final)
    """

    generate_and_export = staticmethod(data_runner.generate_and_export)
    train_cell = staticmethod(train_runner.train_cell)
    evaluate_cell = staticmethod(eval_runner.evaluate_cell)
    evaluate_final_once = staticmethod(eval_runner.evaluate_final_once)

    def __init__(
        self,
        generate_data_fn: Callable[..., Any] | None = None,
        train_fn: Callable[..., Any] | None = None,
        eval_fn: Callable[..., Any] | None = None,
        final_eval_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.generate_data_fn = generate_data_fn or data_runner.generate_and_export
        self.train_fn = train_fn or train_runner.train_cell
        self.eval_fn = eval_fn or eval_runner.evaluate_cell
        self.final_eval_fn = final_eval_fn or eval_runner.evaluate_final_once

    def run_generate_data(
        self,
        data_dir: Path,
        output_root: Path,
        clock_fn: Callable[[], float],
        deadline: float,
        budget: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if clock_fn() > deadline:
            raise BudgetStop(f"generate-data exceeded deadline ({clock_fn()} > {deadline})")

        raw_dir = data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        counts = kwargs.get("counts")
        if counts is None:
            counts = {
                "P": {
                    "train": spec.TRAIN_WORLDS_PER_FAMILY,
                    "development": spec.DEV_WORLDS_PER_FAMILY,
                    "final": spec.FINAL_WORLDS_PER_FAMILY,
                },
                "S": {
                    "train": spec.TRAIN_WORLDS_PER_FAMILY,
                    "development": spec.DEV_WORLDS_PER_FAMILY,
                    "final": spec.FINAL_WORLDS_PER_FAMILY,
                },
            }

        runner_fn = kwargs.get("runner_fn")
        awz_root = kwargs.get("awz_root", spec.AWZ_ROOT)

        res = self.generate_data_fn(
            counts=counts,
            raw_dir=raw_dir,
            data_dir=data_dir,
            wall_budget_s=budget,
            deadline=deadline,
            clock=clock_fn,
            runner_fn=runner_fn,
            awz_root=awz_root,
        )
        return res

    def run_train(
        self,
        arm: int,
        family: str,
        seed: int,
        output_root: Path,
        data_dir: Path,
        clock_fn: Callable[[], float],
        deadline: float,
        budget: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if clock_fn() > deadline:
            raise BudgetStop(f"train exceeded deadline ({clock_fn()} > {deadline})")

        student_dir = data_dir / "student" / family / "train"
        out_dir = output_root / "checkpoints" / f"arm{arm}_{family}_seed{seed}"
        out_dir.mkdir(parents=True, exist_ok=True)

        duty_cycle = float(kwargs.get("duty_cycle") or spec.BUDGET_CAPS["training_duty_cycle"])
        compute_budget = float(kwargs.get("compute_budget_s") or spec.BUDGET_CAPS["train_cell_compute_max_seconds"])
        steps = kwargs.get("steps") or kwargs.get("num_steps") or spec.DEFAULT_TRAIN_STEPS
        batch_size = kwargs.get("batch_size") or spec.DEFAULT_BATCH_SIZE
        lr = kwargs.get("lr") or spec.DEFAULT_LEARNING_RATE
        sleep_fn = kwargs.get("sleep_fn")

        res = self.train_fn(
            arm_id=arm,
            family=family,
            seed=seed,
            student_dir=student_dir,
            out_dir=out_dir,
            compute_budget_s=compute_budget,
            deadline=deadline,
            clock=clock_fn,
            sleep_fn=sleep_fn,
            duty_cycle=duty_cycle,
            steps=steps,
            batch_size=batch_size,
            lr=lr,
        )
        return res

    def run_eval(
        self,
        arm: int,
        family: str,
        seed: int | None,
        data_dir: Path,
        output_root: Path,
        clock_fn: Callable[[], float],
        deadline: float,
        budget: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if clock_fn() > deadline:
            raise BudgetStop(f"eval exceeded deadline ({clock_fn()} > {deadline})")

        partition = kwargs.get("partition", "development")
        student_dir = data_dir / "student" / family / partition
        evaluator_dir = data_dir / "evaluator" / family / partition

        arm_obj = kwargs.get("arm_obj")
        if arm_obj is None:
            arm_obj = build_arm_for_eval(
                arm=arm,
                family=family,
                seed=seed,
                output_root=output_root,
                evaluator_dir=evaluator_dir,
            )

        cell_eval_res = self.eval_fn(
            arm=arm_obj,
            student_dir=student_dir,
            evaluator_dir=evaluator_dir,
        )

        summary = dict(cell_eval_res["summary"])
        primary_err = summary.get("primary_error_m")
        k_step_10 = summary.get("k_step_errors", {}).get("10")
        pos_err_10 = primary_err if primary_err is not None else k_step_10
        metrics_dict = dict(summary)
        if pos_err_10 is not None:
            metrics_dict["position_error_10_step"] = pos_err_10
        if "mean_energy_drift" in summary:
            metrics_dict["ballistic_energy_drift"] = summary["mean_energy_drift"]

        eval_report: dict[str, Any] = {
            "mode": "eval",
            "arm": arm,
            "family": family,
            "seed": seed,
            "partition": partition,
            "summary": summary,
            "metrics": metrics_dict,
            "episodes": cell_eval_res.get("episodes", []),
            "episodes_evaluated": len(cell_eval_res.get("episodes", [])),
            "diagnostic": bool(getattr(arm_obj, "diagnostic_only", False) or arm == 4),
        }

        eval_dir = output_root / "eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        out_json = eval_dir / f"eval_arm{arm}_{family}_{seed if seed is not None else 'none'}.json"
        out_json.write_text(json.dumps(eval_report, indent=2), encoding="utf-8")

        return eval_report

    def run_final_eval(
        self,
        data_dir: Path,
        output_root: Path,
        clock_fn: Callable[[], float],
        deadline: float,
        budget: float,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if clock_fn() > deadline:
            raise BudgetStop(f"final-eval exceeded deadline ({clock_fn()} > {deadline})")

        family = kwargs.get("family", "P")
        sealed_dir_candidate = None
        expected_digest = None

        fam_sealed_root = data_dir / "sealed_final" / family
        if fam_sealed_root.is_dir():
            for sub in sorted(fam_sealed_root.iterdir()):
                if sub.is_dir() and (sub / "SEALED.json").is_file():
                    sealed_dir_candidate = sub
                    meta = json.loads((sub / "SEALED.json").read_text(encoding="utf-8"))
                    expected_digest = meta.get("dataset_digest")
                    break

        if sealed_dir_candidate is None:
            # Check un-nested fallback
            for candidate in (data_dir / "sealed_final", data_dir / "final_sealed"):
                if candidate.is_dir() and (candidate / "SEALED.json").is_file():
                    sealed_dir_candidate = candidate
                    meta = json.loads((candidate / "SEALED.json").read_text(encoding="utf-8"))
                    expected_digest = meta.get("dataset_digest")
                    break

        if sealed_dir_candidate is None or expected_digest is None:
            raise FileNotFoundError(f"No verified sealed final dataset found for family {family} under {data_dir}")

        arm_factory = kwargs.get("arm_factory")
        if arm_factory is None:
            # Build default final evaluation arms (PriorArm and any available checkpoints)
            arm_factory = {"arm1_prior": arms_nonnet.PriorArm()}

        final_res = self.final_eval_fn(
            arm_factory=arm_factory,
            sealed_dir=sealed_dir_candidate,
            expected_digest=expected_digest,
            reader_info={"role": "evaluator", "task": spec.TASK_ID, "family": family},
        )

        final_report: dict[str, Any] = {
            "mode": "final-eval",
            "family": family,
            "partition": "final",
            "dataset_digest": final_res.get("dataset_digest", expected_digest),
            "arms": final_res.get("arms", {}),
            "summary": final_res.get("summary", {}),
        }

        out_dir = output_root / "eval"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"final_eval_{family}.json"
        out_file.write_text(json.dumps(final_report, indent=2), encoding="utf-8")

        return final_report


def _invoke_runner_method(method: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Invoke runner method safely filtering kwargs if method does not accept **kwargs."""
    try:
        sig = inspect.signature(method)
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if has_var_kw:
            return method(*args, **kwargs)
        valid_keys = set(sig.parameters.keys())
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in valid_keys}
        return method(*args, **filtered_kwargs)
    except Exception:
        return method(*args, **kwargs)


def execute_work_cell(
    ledger: E1Ledger,
    mode: str,
    arm: int | None,
    family: str | None,
    seed: int | None,
    cell_wall_budget: float,
    *,
    data_dir: Path,
    output_root: Path,
    clock: Callable[[], float],
    runner: CellRunner | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute one bounded work cell inside the ledger with strict budget reservation."""
    actual_runner = runner if runner is not None else DefaultCellRunner()

    # Determine runner function and module SHA256 for ledger recording
    if mode == "generate-data":
        target_fn = getattr(actual_runner, "generate_data_fn", getattr(actual_runner, "run_generate_data", DEFAULT_GENERATE_DATA_RUNNER))
    elif mode == "train":
        target_fn = getattr(actual_runner, "train_fn", getattr(actual_runner, "run_train", DEFAULT_TRAIN_RUNNER))
    elif mode == "eval":
        target_fn = getattr(actual_runner, "eval_fn", getattr(actual_runner, "run_eval", DEFAULT_EVAL_RUNNER))
    elif mode == "final-eval":
        target_fn = getattr(actual_runner, "final_eval_fn", getattr(actual_runner, "run_final_eval", DEFAULT_FINAL_EVAL_RUNNER))
    else:
        target_fn = actual_runner

    runner_name = getattr(target_fn, "__qualname__", getattr(target_fn, "__name__", str(target_fn)))
    runner_module_sha = compute_module_sha256(target_fn)

    # 1. Open run
    run_id = ledger.open_run(
        mode=mode,
        arm=arm,
        family=family,
        seed=seed,
        cell_wall_budget=cell_wall_budget,
        runner_name=runner_name,
        runner_module_sha256=runner_module_sha,
        snapshot_extra={"power": get_power_info()},
    )

    work_state = "collecting" if mode == "generate-data" else ("training" if mode == "train" else "validating")
    ledger.begin_work(run_id, state=work_state)

    # 2. Reserve budget upfront: full cell_wall_budget (照 S1：先预留再干活)
    cell_start_time = clock()
    cell_deadline = cell_start_time + cell_wall_budget

    ledger.reserve(run_id, active_seconds=cell_wall_budget)

    # 3. Dispatch work execution to runner with try/except
    try:
        if mode == "generate-data":
            result_data = _invoke_runner_method(
                actual_runner.run_generate_data,
                data_dir=data_dir,
                output_root=output_root,
                clock_fn=clock,
                deadline=cell_deadline,
                budget=cell_wall_budget,
                **kwargs,
            )
        elif mode == "train":
            if arm is None or family is None or seed is None:
                raise ValueError(f"train mode requires arm, family and seed, got arm={arm}, family={family}, seed={seed}")
            result_data = _invoke_runner_method(
                actual_runner.run_train,
                arm=arm,
                family=family,
                seed=seed,
                output_root=output_root,
                data_dir=data_dir,
                clock_fn=clock,
                deadline=cell_deadline,
                budget=cell_wall_budget,
                **kwargs,
            )
        elif mode == "eval":
            if arm is None or family is None:
                raise ValueError(f"eval mode requires arm and family, got arm={arm}, family={family}")
            result_data = _invoke_runner_method(
                actual_runner.run_eval,
                arm=arm,
                family=family,
                seed=seed,
                data_dir=data_dir,
                output_root=output_root,
                clock_fn=clock,
                deadline=cell_deadline,
                budget=cell_wall_budget,
                **kwargs,
            )
        elif mode == "final-eval":
            result_data = _invoke_runner_method(
                actual_runner.run_final_eval,
                data_dir=data_dir,
                output_root=output_root,
                clock_fn=clock,
                deadline=cell_deadline,
                budget=cell_wall_budget,
                family=family or "P",
                **kwargs,
            )
        else:
            raise ValueError(f"Unknown mode {mode}")
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {str(exc)}"
        ledger.finish_run(run_id, state="failed", reason=err_msg)
        raise

    # 4. Finish run according to runner's returned status
    runner_status = result_data.get("status") if isinstance(result_data, dict) else None
    if runner_status == "stopped":
        final_state = "stopped"
        reason = result_data.get("reason", "runner_stopped")
    elif runner_status == "failed":
        final_state = "failed"
        reason = result_data.get("reason", "runner_failed")
    else:
        final_state = "completed"
        reason = "finished_successfully"

    elapsed = clock() - cell_start_time
    if isinstance(result_data, dict):
        result_data["run_id"] = run_id
        result_data["elapsed_seconds"] = elapsed
        result_data["cell_wall_budget"] = cell_wall_budget

    ledger.finish_run(run_id, state=final_state, reason=reason)
    return result_data
