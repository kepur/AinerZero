"""Scenario runner for the r6 CPU-isolated approval simulation.

Executed as a subprocess with ``PYTHONPATH`` pointing at the isolated repo copy
and a per-scenario working directory, so every scenario exercises the *copy's*
``spec``/``worker``/``commands`` modules (its own canonical phase-1 root, its own
central RunStore, its own simulated approval line).  The real repository tree is
never imported and never written.

MLX is never used for a forward/gradient/optimizer step: ``runtime.MlxBackend``
is replaced by a numeric CPU substitute, exactly like the r5 evidence harness.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

COPY = Path(os.environ["S1_R6_SIM_ROOT"]).resolve()
SCENARIO = sys.argv[1]

import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s1 import spec, worker  # noqa: E402

PHASE1 = COPY / "artifacts" / "v9" / "s1" / "phase1"
R6 = PHASE1 / "r6"
CENTRAL_LEDGER = PHASE1 / "control.sqlite3"
PREREG = R6 / "pre_registration.json"
PREREG_SHA = worker.prereg.document_sha256(
    json.loads(PREREG.read_text(encoding="utf-8"))
)


class SubstituteModel:
    def __init__(self, seed: int):
        self.params = {"w": np.asarray([[float(seed)]], dtype=np.float32)}


class SubstituteBackend:
    """Numeric CPU substitute; counts every model call it is asked to make."""

    name = "cpu-approval-sim-substitute"

    def __init__(self, *, fail_mode: str | None = None) -> None:
        self.fail_mode = fail_mode
        self.value_and_grad_calls = 0
        self.save_calls = 0

    def build_model(self, arm_id, seed):
        return SubstituteModel(seed)

    def make_optimizer(self, protocol):
        return {"lr": protocol["learning_rate"]}

    def init_optimizer(self, optimizer, model):
        return None

    def value_and_grad(self, model):
        def apply(m, batch):
            self.value_and_grad_calls += 1
            if self.fail_mode == "backend-error" and self.value_and_grad_calls == 1:
                raise RuntimeError("simulated backend failure at the first gradient")
            if self.fail_mode == "budget-stop" and self.value_and_grad_calls == 1:
                raise worker.BudgetStop("simulated budget exhaustion at the first gradient")
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
            digest.update(np.ascontiguousarray(model.params[name]).tobytes())
        return digest.hexdigest()

    def window_probe(self, model, windows, protocol, *, max_batches=None):
        rows = [
            {"episode_id": meta["episode_id"], "start": int(meta["start"]), "loss": 0.5}
            for meta in windows["windows"]
        ]
        batch = int(protocol["batch_size"])
        return {"rows": rows, "batches": (len(rows) + batch - 1) // batch}

    def save_params(self, model, path, *, exclusive=False):
        self.save_calls += 1
        path = Path(path)
        if exclusive and path.exists():
            raise FileExistsError(path)
        with open(path, "xb" if exclusive else "wb") as handle:
            np.savez(handle, **model.params)


def install_backend(fail_mode: str | None = None) -> SubstituteBackend:
    backend = SubstituteBackend(fail_mode=fail_mode)
    worker.runtime.MlxBackend = lambda: backend
    return backend


def run_train(*, arm: str, seed: int, output_root: Path | None = None, fail_mode: str | None = None):
    backend = install_backend(fail_mode)
    report = worker.run_worker(
        "train",
        output_root=output_root or PHASE1,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=float(
            json.loads(PREREG.read_text(encoding="utf-8"))["timing"]["supervision_seconds"]
        ),
        prereg_path=PREREG,
        research_log=None,
        arm=arm,
        seed=seed,
    )
    return report, backend


def ledger_rows() -> list[dict]:
    from ainerzero.runtime.lifecycle import RunStore

    with RunStore(CENTRAL_LEDGER) as store:
        rows = []
        for run in store.list_runs():
            config = run.config_snapshot or {}
            rows.append(
                {
                    "run_id": run.run_id,
                    "state": run.state,
                    "role": run.role,
                    "arm_id": config.get("arm_id"),
                    "seed": config.get("seed"),
                    "updates": config.get("updates"),
                    "reserved_optimizer_steps": int(run.reserved_optimizer_steps),
                    "receipt_prefix": (run.reason or "")[: len(worker.TRAIN_RECEIPT_PREFIX)],
                    "has_train_receipt": (run.reason or "").startswith(worker.TRAIN_RECEIPT_PREFIX),
                }
            )
        return rows


def emit(payload: dict) -> int:
    payload["scenario"] = SCENARIO
    payload["cwd"] = str(Path.cwd())
    payload["mlx_imported"] = any(name.split(".")[0] == "mlx" for name in sys.modules)
    print("S1_R6_SIM_JSON " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def scenario_completed() -> int:
    report, backend = run_train(arm="arm2", seed=0)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "control_db": report.get("control_db"),
            "run_id": report.get("run_id"),
            "value_and_grad_calls": backend.value_and_grad_calls,
            "save_calls": backend.save_calls,
            "ledger_rows": ledger_rows(),
        }
    )


def scenario_second_arm() -> int:
    report, backend = run_train(arm="arm3", seed=0)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "value_and_grad_calls": backend.value_and_grad_calls,
            "ledger_rows": ledger_rows(),
        }
    )


def scenario_cross_root() -> int:
    import shutil

    copied = COPY / "artifacts" / "v9" / "s1" / "phase1-copy"
    if copied.exists():
        shutil.rmtree(copied)
    shutil.copytree(PHASE1, copied)
    report, _backend = run_train(arm="arm2", seed=0, output_root=copied)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "message": report.get("message"),
            "copied_root_ledger_unchanged": (
                copied / "control.sqlite3"
            ).read_bytes()
            == CENTRAL_LEDGER.read_bytes(),
        }
    )


def scenario_cwd_change() -> int:
    report, _backend = run_train(arm="arm2", seed=0)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "attempt_states": report.get("attempt_states"),
            "message": report.get("message"),
        }
    )


def scenario_prereg_copy() -> int:
    import shutil

    forged = COPY / "artifacts" / "v9" / "s1" / "phase1-forged"
    if forged.exists():
        shutil.rmtree(forged)
    forged.mkdir(parents=True)
    shutil.copy2(R6 / "pre_registration.json", forged / "pre_registration.json")
    shutil.copy2(R6 / "pre_registration.json.sha256", forged / "pre_registration.json.sha256")
    report, _backend = run_train(arm="arm2", seed=0, output_root=forged)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "forged_ledger_created": (forged / "control.sqlite3").exists(),
            "forged_run_started": (forged / "runs").exists(),
        }
    )


def scenario_failed_then_rerun() -> int:
    first, backend = run_train(arm="arm3", seed=1, fail_mode="backend-error")
    second, _ = run_train(arm="arm3", seed=1)
    return emit(
        {
            "first_status": first.get("status"),
            "first_error": first.get("error"),
            "first_run_state": (first.get("run") or {}).get("state"),
            "second_status": second.get("status"),
            "second_refused_stage": second.get("refused_stage"),
            "attempt_states": second.get("attempt_states"),
        }
    )


def scenario_stopped_then_rerun() -> int:
    first, backend = run_train(arm="arm4", seed=2, fail_mode="budget-stop")
    second, _ = run_train(arm="arm4", seed=2)
    return emit(
        {
            "first_status": first.get("status"),
            "first_error": first.get("error"),
            "first_run_state": (first.get("run") or {}).get("state"),
            "second_status": second.get("status"),
            "second_refused_stage": second.get("refused_stage"),
            "attempt_states": second.get("attempt_states"),
        }
    )


def scenario_ledger_deleted() -> int:
    CENTRAL_LEDGER.unlink()
    report, _backend = run_train(arm="arm2", seed=1)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "ledger_recreated": CENTRAL_LEDGER.exists(),
        }
    )


def scenario_ledger_replaced() -> int:
    CENTRAL_LEDGER.write_text("replaced by an attacker\n", encoding="utf-8")
    report, _backend = run_train(arm="arm2", seed=1)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "ledger_bytes_unchanged": CENTRAL_LEDGER.read_text(encoding="utf-8")
            == "replaced by an attacker\n",
        }
    )


def scenario_ledger_foreign() -> int:
    import os as _os

    from ainerzero.runtime.lifecycle import RunStore

    # Replace the central ledger with a *valid* RunStore that does not carry the
    # phase-1 preparation experiment: recognized schema, wrong identity.
    foreign = PHASE1 / "control-foreign.sqlite3"
    if foreign.exists():
        foreign.unlink()
    with RunStore(foreign) as store:
        store.create_experiment(
            worker.prep_experiment_manifest(), "foreign-request", "foreign-experiment"
        )
    _os.replace(foreign, CENTRAL_LEDGER)
    report, _backend = run_train(arm="arm2", seed=1)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
        }
    )


def scenario_real_ledger_phase_cap() -> int:
    """The copy carries the byte-identical real central ledger (r1 aux rows)."""
    from ainerzero.runtime.lifecycle import RunStore

    with RunStore(CENTRAL_LEDGER) as store:
        runs = store.list_runs()
        total_wall = sum(float(run.wall_seconds) for run in runs)
        rows = [
            {
                "run_id": run.run_id,
                "role": run.role,
                "state": run.state,
                "created_at": run.created_at,
                "wall_seconds": run.wall_seconds,
                "reserved_active_seconds": run.reserved_active_seconds,
            }
            for run in runs
        ]
    report, _backend = run_train(arm="arm2", seed=0)
    return emit(
        {
            "report_status": report.get("status"),
            "refused_stage": report.get("refused_stage"),
            "total_wall_seconds": total_wall,
            "phase_wall_max_seconds": 14400.0,
            "deadline_seconds": 450.0,
            "historical_rows": rows,
        }
    )


SCENARIOS = {
    "completed": scenario_completed,
    "real-ledger-phase-cap": scenario_real_ledger_phase_cap,
    "second-arm": scenario_second_arm,
    "cross-root": scenario_cross_root,
    "cwd-change": scenario_cwd_change,
    "prereg-copy": scenario_prereg_copy,
    "failed-then-rerun": scenario_failed_then_rerun,
    "stopped-then-rerun": scenario_stopped_then_rerun,
    "ledger-deleted": scenario_ledger_deleted,
    "ledger-replaced": scenario_ledger_replaced,
    "ledger-foreign": scenario_ledger_foreign,
}

if __name__ == "__main__":
    raise SystemExit(SCENARIOS[SCENARIO]())
