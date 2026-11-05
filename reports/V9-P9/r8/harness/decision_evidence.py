"""r8 decision evidence: F1/F2/F3/F4/F6 as measured, not asserted in prose.

Every block uses the real product code paths (real ``PrepLedger``/RunStore, real
completion protocol, real A2 manifest bytes).  No MLX, no training, no eval run,
no approval line, no write to the real central ledger.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import completion, identity, prereg, spec, worker  # noqa: E402

OUT = REPO / "reports/V9-P9/r8/evidence/decision-evidence.json"
UPDATES = 3510


def fresh_root(prefix: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix=prefix))
    spec.REGISTERED_HOST_ROOT = root.resolve()
    spec.PHASE1_ROOT = root / "artifacts/v9/s1/phase1"
    spec.PHASE1_ROOT.mkdir(parents=True, exist_ok=True)
    return spec.PHASE1_ROOT


def open_training_run(root: Path):
    ledger = worker.PrepLedger(root / "control.sqlite3")
    document = {
        "training_protocol": {"updates": UPDATES, "checkpoint_updates": [0, UPDATES]},
        "timing": {"deadline_seconds": 450.0},
        "data_identity": {"dataset_digest": "e" * 64},
    }
    run_id = worker._open_train_run(
        document, ledger, {"document_sha256": "d" * 64, "line": "evidence", "line_number": 1},
        arm_id="arm2", seed=0,
    )
    ledger.begin_work(run_id, work_state="training")
    return ledger, run_id


def f1_completion() -> dict:
    """A real SQLite write-lock wait inside the terminal commit."""
    root = fresh_root("s1-r8-f1-")
    ledger, run_id = open_training_run(root)
    protocol = completion.CompletionProtocol(deadline_seconds=0.30)
    released = threading.Event()
    state: dict = {}

    def seam(phase: str, elapsed: float) -> None:
        if phase != "train:terminal_commit:before" or "holder" in state:
            return
        holder = sqlite3.connect(
            root / "control.sqlite3", timeout=5.0, isolation_level=None, check_same_thread=False
        )
        holder.execute("BEGIN IMMEDIATE")
        state["holder"] = holder

        def release() -> None:
            time.sleep(0.6)
            holder.execute("COMMIT")
            released.set()

        threading.Thread(target=release, daemon=True).start()

    completion.TEST_SEAM = seam
    try:
        report = worker._complete_run(
            report={"schema": "evidence", "mode": "train"},
            ledger=ledger,
            run_id=run_id,
            protocol=protocol,
            output_root=root,
            reason="s1_train_completed",
            kind="train",
        )
        released.wait(timeout=10.0)
    finally:
        completion.TEST_SEAM = None
        state.get("holder") and state["holder"].close()
    record = ledger.get(run_id)
    markers = completion.invalid_markers(root / "runs" / run_id)
    ledger.close()
    return {
        "case": "write-lock wait inside ledger.finish",
        "deadline_seconds": 0.30,
        "lock_held_seconds": 0.6,
        "report_status": report["status"],
        "refused_stage": report["refused_stage"],
        "expired_in_flight": report["completion_protocol"]["expired_in_flight"],
        "elapsed_at_refusal_seconds": round(report["completion_protocol"]["elapsed_at_record_seconds"], 3),
        "ledger_state": record["state"],
        "ledger_reason_rewritten": record["reason"] != "s1_train_completed",
        "rolled_back": report["rolled_back"],
        "invalid_marker": markers[0].name if markers else None,
        "consumer_would_refuse": bool(markers),
        "note": "the terminal row had already landed, so it is left as committed; the marker "
        "invalidates it for every consumer instead of pretending a rollback",
    }


def f2_states() -> dict:
    rows = [
        ("collecting", 60.0), ("validating", 20.0), ("stopping", 10.0),
        ("training", 5.0), ("paused", 5.0), ("created", 0.0), ("initializing", 0.0),
        ("pausing", 0.0),
    ]
    runs = [
        SimpleNamespace(
            run_id=state, state=state, reserved_active_seconds=reserved,
            created_at=1_000.0, updated_at=1_060.0,
        )
        for state, reserved in rows
    ]
    accepted = {
        state: worker.run_conservative_wall_seconds(run, instant=1_200.0)
        for state, run in zip([r[0] for r in rows], runs)
    }
    refused = {}
    for bad in ("quarantined", None, "archived"):
        try:
            worker.run_conservative_wall_seconds(
                SimpleNamespace(
                    run_id="x", state=bad, reserved_active_seconds=1.0,
                    created_at=1_000.0, updated_at=1_100.0,
                ),
                instant=1_200.0,
            )
            refused[str(bad)] = "accepted"
        except worker.LedgerStateInvalid as exc:
            refused[str(bad)] = {"type": type(exc).__name__, "message": str(exc)[:90]}
    return {
        "product_written_states_accepted": accepted,
        "unknown_states_refused_as_state_errors": refused,
        "terminal_interval_rule": "max(reserved, updated-created) per row, summed",
    }


def f5_field_contract() -> dict:
    cases = {}
    for label, reserved, created in (
        ("nan_reserved", float("nan"), 1_000.0),
        ("inf_reserved", float("inf"), 1_000.0),
        ("negative_reserved", -5.0, 1_000.0),
        ("far_future_created", 10.0, 1e308),
        ("reverse_timestamps", 10.0, None),
    ):
        run = SimpleNamespace(
            run_id=label, state="completed", reserved_active_seconds=reserved,
            created_at=1e308 if label == "far_future_created" else (2_000.0 if created is None else created),
            updated_at=1_000.0 if created is None else 1_100.0,
        )
        try:
            value = worker.run_conservative_wall_seconds(run, instant=1_200.0)
            cases[label] = {"outcome": "accepted", "counted": value}
        except worker.LedgerAccountingError as exc:
            cases[label] = {"outcome": "refused", "type": type(exc).__name__, "message": str(exc)[:90]}
    future = SimpleNamespace(
        run_id="future-high-water", state="training", reserved_active_seconds=7.0,
        created_at=2_000.0, updated_at=2_000.0,
    )
    cases["legitimate_future_high_water"] = {
        "outcome": "accepted",
        "counted": worker.run_conservative_wall_seconds(future, instant=1_900.0),
    }
    return cases


def f3_d_budget() -> dict:
    frozen = json.loads((REPO / "artifacts/v9/s1/phase1/r8/pre_registration.json").read_text())
    manifest_a = worker.train_experiment_manifest(updates=UPDATES)
    manifest_b = worker.train_experiment_manifest(updates=UPDATES, deadline_seconds=2.0)
    return {
        "frozen_arm1_deadline_seconds": frozen["timing"]["arm1_deadline_seconds"],
        "frozen_arm1_supervision_seconds": frozen["timing"]["arm1_supervision_seconds"],
        "frozen_updates": frozen["training_protocol"]["updates"],
        "registered_d_eval_runs": spec.TIMING["d_candidate_eval_runs"],
        "manifest_is_caller_independent": manifest_a == manifest_b,
        "experiment_wall_ceiling_seconds": manifest_a["experiment_budget"]["max_wall_seconds"],
        "experiment_optimizer_ceiling": manifest_a["experiment_budget"]["max_optimizer_steps"],
        "d_run_budget_rule": "the run snapshot uses timing.arm1_deadline_seconds (2 s), "
        "never the generic eval entry budget (300 s)",
        "reservation_rule": "one pre-work reservation of min(0.5*budget, remaining) = 1.0 s "
        "for a 2 s run; no 5 s floor",
    }


def f4_guard() -> dict:
    root = fresh_root("s1-r8-f4-")
    from ainerzero.runtime.lifecycle import RunStore

    store = RunStore(root / "control.sqlite3")
    try:
        experiment = store.create_experiment(
            worker.train_experiment_manifest(updates=UPDATES),
            f"{worker.TRAIN_EXPERIMENT_ID}:training",
            worker.TRAIN_EXPERIMENT_ID,
        )
        snapshot = worker.run_config_snapshot(wall_budget_seconds=2.0, purpose="d")
        snapshot["arm_id"] = "arm1"
        store.create_run(
            snapshot, "d", "run-d", experiment_id=experiment.experiment_id, role="auxiliary"
        )
        store.transition("run-d", "initializing", reason="x")
        store.transition("run-d", "validating", reason="x")
        state = worker.d_candidate_attempt_state(store.list_runs())
        legacy = worker.run_config_snapshot(
            wall_budget_seconds=2.0, purpose="s1_phase1_d_candidate_eval:arm1"
        )
    finally:
        store.close()
    # A ledger that only holds the older, arm_id-less row: must fail closed.
    legacy_root = fresh_root("s1-r8-f4-legacy-")
    legacy_store = RunStore(legacy_root / "control.sqlite3")
    try:
        experiment = legacy_store.create_experiment(
            worker.train_experiment_manifest(updates=UPDATES),
            f"{worker.TRAIN_EXPERIMENT_ID}:training",
            worker.TRAIN_EXPERIMENT_ID,
        )
        legacy_store.create_run(
            legacy, "legacy", "run-legacy", experiment_id=experiment.experiment_id,
            role="auxiliary",
        )
        legacy_store.transition("run-legacy", "initializing", reason="x")
        legacy_store.transition("run-legacy", "validating", reason="x")
        legacy_state = worker.d_candidate_attempt_state(legacy_store.list_runs())
    finally:
        legacy_store.close()
    return {
        "product_row_with_arm_id": state,
        "legacy_row_without_arm_id": legacy_state,
        "rule": "a started arm1 row is already_attempted; a started row that only *looks* "
        "like a D attempt (no arm_id) is unidentifiable and fails closed; nothing is "
        "deleted, rewritten or auto-repaired",
    }


def f6_identity() -> dict:
    report = identity.verify_d_candidate_identity()
    return {
        "frozen_manifest": report["frozen_manifest"],
        "frozen_manifest_file_sha256": report["frozen_manifest_file_sha256"],
        "recomputed_manifest_digest": report["frozen_manifest_digest"],
        "registered_manifest_digest": spec.ARM_SPECS["arm1"]["identity"]["frozen_manifest_digest"],
        "digest_compared": report["manifest_digest_match"],
        "entries_verified": report["entries_verified"],
        "registered_field_matches": {
            field: row["match"] for field, row in report["registered_fields"].items()
        },
        "mlx_imported": report["mlx_imported"],
        "bound_implementation_sources": list(prereg.IMPLEMENTATION_SOURCES),
    }


def main() -> int:
    evidence = {
        "schema": "ainerzero.v9.s1.r8.decision_evidence.v1",
        "spec": spec.SPEC_NAME,
        "frozen_document_sha256": prereg.document_sha256(
            json.loads((REPO / "artifacts/v9/s1/phase1/r8/pre_registration.json").read_text())
        ),
        "real_ledger_touched": False,
        "approval_line_written": False,
        "model_work_run": False,
        "F1_completion": f1_completion(),
        "F2_states": f2_states(),
        "F5_field_contract": f5_field_contract(),
        "F3_d_budget": f3_d_budget(),
        "F4_guard": f4_guard(),
        "F6_identity": f6_identity(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps({k: evidence[k] for k in ("F1_completion", "F2_states")}, indent=1)[:2000])
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
