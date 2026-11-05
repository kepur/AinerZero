"""P21 probe 06: the phase total counts every phase row, and the cap is enforced
through the real entry path.

* an isolated central ledger is seeded with rows of every phase kind (prep
  data / smoke / verify, a training arm x seed attempt, an evaluation run) in
  completed, failed, stopped and active states;
* every one of them must be counted by ``phase_total_wall_seconds`` -- the
  budget is not a "training rows only" number;
* a failed or stopped attempt must never be cleared (``train_attempts`` keeps
  returning it);
* the real entry path (``commands.mode_train``) must refuse with
  ``phase_budget_exceeded`` once the accumulated total plus the frozen deadline
  crosses the registered 4 h cap, and the refusal must carry the per-row
  breakdown.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p21lib as lib  # noqa: E402
from p03_entry_path import approval_log_with_line, args_for, isolated_host  # noqa: E402

from ainerzero.runtime.lifecycle import RunStore  # noqa: E402
from ainerzero.v9.experiments.s1 import commands, prereg, spec, worker  # noqa: E402

R7_PREREG = lib.REPO / "artifacts/v9/s1/phase1/r7/pre_registration.json"


def seed_phase_rows(ledger_path: Path, *, big: bool = False, with_train_attempt: bool = True):
    """Seed prep / train / eval rows in every lifecycle state."""
    with RunStore(ledger_path) as store:
        store.create_experiment(
            worker.prep_experiment_manifest(), worker.PREP_REQUEST_ID, worker.PREP_EXPERIMENT_ID
        )
        store.create_experiment(
            worker.train_experiment_manifest(deadline_seconds=450.0, updates=3510),
            f"{worker.TRAIN_EXPERIMENT_ID}:training",
            worker.TRAIN_EXPERIMENT_ID,
        )
        rows = []
        # 1) prep rows (data / smoke / verify) in the preparation experiment
        for mode, state, reserved in (
            ("data", "completed", 120.0),
            ("smoke", "failed", 30.0),
            ("verify", "stopped", 15.0),
        ):
            run_id = f"p21-prep-{mode}"
            snapshot = worker.run_config_snapshot(
                wall_budget_seconds=600.0, purpose=f"preregistration_prep:{mode}"
            )
            store.create_run(
                snapshot,
                f"{worker.PREP_REQUEST_ID}:{mode}:{run_id}",
                run_id,
                experiment_id=worker.PREP_EXPERIMENT_ID,
                role="auxiliary",
            )
            store.transition(run_id, "initializing", reason="p21")
            store.transition(run_id, "collecting" if mode == "data" else "validating", reason="p21")
            store.consume(run_id, active_seconds=reserved, optimizer_steps=0)
            if state == "stopped":
                store.transition(run_id, "stopping", reason="p21")
            store.transition(run_id, state, reason="p21")
            rows.append((run_id, mode, state, reserved))
        # 2) a training attempt (arm2 seed0) in a failed state
        if with_train_attempt:
            run_id = "p21-train-arm2-seed0"
            snapshot = worker.run_config_snapshot(
                wall_budget_seconds=450.0, purpose="s1_phase1_training_run:arm2:seed0",
                max_optimizer_steps=3510,
            )
            snapshot.update({"arm_id": "arm2", "seed": 0, "updates": 3510})
            store.create_run(
                snapshot,
                f"{worker.TRAIN_EXPERIMENT_ID}:arm2:0:{run_id}",
                run_id,
                experiment_id=worker.TRAIN_EXPERIMENT_ID,
                role="model",
            )
            store.transition(run_id, "initializing", reason="p21")
            store.transition(run_id, "training", reason="p21")
            store.consume(run_id, active_seconds=200.0, optimizer_steps=0)
            store.transition(run_id, "failed", reason="p21")
            rows.append((run_id, "train", "failed", 200.0))
        # 3) an evaluation run (auxiliary), terminal
        run_id = "p21-eval-run"
        snapshot = worker.run_config_snapshot(
            wall_budget_seconds=300.0, purpose="preregistration_prep:eval"
        )
        store.create_run(
            snapshot,
            f"{worker.PREP_REQUEST_ID}:eval:{run_id}",
            run_id,
            experiment_id=worker.PREP_EXPERIMENT_ID,
            role="auxiliary",
        )
        store.transition(run_id, "initializing", reason="p21")
        store.transition(run_id, "validating", reason="p21")
        store.consume(run_id, active_seconds=40.0, optimizer_steps=0)
        store.transition(run_id, "completed", reason="p21")
        rows.append((run_id, "eval", "completed", 40.0))
        # 4) an optional row that alone busts the 4 h cap
        if big:
            run_id = "p21-cap-buster"
            snapshot = worker.run_config_snapshot(
                wall_budget_seconds=600.0, purpose="preregistration_prep:verify"
            )
            store.create_run(
                snapshot,
                f"{worker.PREP_REQUEST_ID}:verify:{run_id}",
                run_id,
                experiment_id=worker.PREP_EXPERIMENT_ID,
                role="auxiliary",
            )
            store.transition(run_id, "initializing", reason="p21")
            store.transition(run_id, "validating", reason="p21")
            store.transition(run_id, "completed", reason="p21")
            rows.append((run_id, "cap_buster", "completed", 15000.0))
        records = {run.run_id: run for run in store.list_runs()}
    if big:
        # a raw reservation of 15 000 s (the ledger's own budget would not allow
        # such a reservation; the row is edited the way a foreign write would)
        import sqlite3

        connection = sqlite3.connect(ledger_path)
        try:
            connection.execute(
                "UPDATE runs SET active_seconds = 15000.0 WHERE run_id = 'p21-cap-buster'"
            )
            connection.commit()
        finally:
            connection.close()
    return rows, records


def main() -> int:
    document = json.loads(R7_PREREG.read_text(encoding="utf-8"))
    document_sha = prereg.document_sha256(document)
    scratch = lib.scratch_dir("p21-phase-scope")

    # --- 1) every phase kind is counted (terminal rows) --------------------
    ledger_path = scratch / "ledger" / "control.sqlite3"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    rows, records = seed_phase_rows(ledger_path)
    with RunStore(ledger_path) as store:
        run_records = store.list_runs()
    breakdown = worker.phase_ledger_breakdown(run_records, instant=None)
    counted_ids = {row["run_id"] for row in breakdown["rows"]}
    all_counted = all(run_id in counted_ids for run_id, *_ in rows)
    total = worker.phase_total_wall_seconds(run_records)
    prep_only = sum(
        row["counted_seconds"]
        for row in breakdown["rows"]
        if (records[row["run_id"]].config_snapshot or {}).get("purpose", "").startswith(
            "preregistration_prep"
        )
    )
    train_only = sum(
        row["counted_seconds"]
        for row in breakdown["rows"]
        if (records[row["run_id"]].config_snapshot or {}).get("arm_id") == "arm2"
    )
    scope = {
        "rows": [{"run_id": r[0], "kind": r[1], "state": r[2]} for r in rows],
        "total_seconds": total,
        "prep_rows_seconds": prep_only,
        "train_row_seconds": train_only,
        "every_phase_row_counted": all_counted,
        "prep_and_eval_rows_are_part_of_the_total": prep_only > 0 and total > train_only,
        "breakdown": breakdown["rows"],
    }

    # --- 2) a failed attempt is never cleared ------------------------------
    attempts = worker.train_attempts(run_records, arm_id="arm2", seed=0)
    scope["failed_attempt_still_registered"] = [
        {"run_id": run.run_id, "state": run.state} for run in attempts
    ]

    # --- 3) the real entry path refuses when the cap is crossed ------------
    with isolated_host(
        scratch / "entry", approval=True, document_sha=document_sha, seed_attempts_=False
    ) as host:
        big_rows, _ = seed_phase_rows(host["ledger"], big=True, with_train_attempt=False)
        report = commands.mode_train(args_for(host["phase1"]))
        scope["entry_refusal"] = {
            "status": report.get("status"),
            "refused_stage": report.get("refused_stage") or report.get("stage"),
            "total_wall_seconds": report.get("total_wall_seconds"),
            "deadline_seconds": report.get("deadline_seconds"),
            "phase_wall_max_seconds": report.get("phase_wall_max_seconds"),
            "has_breakdown": bool(report.get("phase_breakdown")),
            "breakdown_rows": len(report.get("phase_breakdown", {}).get("rows", [])),
            "approval_passed": report.get("refused_stage") == "phase_budget_exceeded",
            "message": report.get("message"),
        }
        scope["entry_seeded_rows"] = len(big_rows)

    # --- 4) a row in a state the S1 product itself writes ------------------
    # The worker moves prep data runs to "collecting" and prep smoke/verify and
    # every eval run to "validating"; the lifecycle also has "stopping".  The
    # r7 accounting must count those rows (decision: every phase-related
    # prep/train/eval/verify row counts), not refuse them as unknown states.
    with isolated_host(
        scratch / "states", approval=True, document_sha=document_sha, seed_attempts_=False
    ) as host:
        state_cases = {}
        for state in ("collecting", "validating", "stopping", "training", "created"):
            run_id = f"p21-state-{state}"
            with RunStore(host["ledger"]) as store:
                # one experiment per case: the lifecycle allows only one live run
                # per experiment, and the cases must stay non-terminal
                store.create_experiment(
                    worker.prep_experiment_manifest(),
                    f"p21-state-{state}-request",
                    f"p21-state-{state}",
                )
                snapshot = worker.run_config_snapshot(
                    wall_budget_seconds=600.0, purpose=f"preregistration_prep:{state}"
                )
                store.create_run(
                    snapshot,
                    f"p21-state-{state}:{run_id}",
                    run_id,
                    experiment_id=f"p21-state-{state}",
                    role="auxiliary",
                )
                store.transition(run_id, "initializing", reason="p21")
                if state in ("collecting", "validating", "training"):
                    store.transition(run_id, state, reason="p21")
                elif state == "stopping":
                    store.transition(run_id, "validating", reason="p21")
                    store.transition(run_id, "stopping", reason="p21")
                records_now = store.list_runs()
            try:
                counted = worker.run_conservative_wall_seconds(records_now[-1], instant=None)
            except (ValueError, OverflowError) as exc:
                state_cases[state] = {
                    "in_worker_known_states": state in worker.KNOWN_STATES,
                    "in_lifecycle_states": state
                    in set(__import__("ainerzero.runtime.lifecycle", fromlist=["x"]).WORK_STATES)
                    | {"created", "initializing", "pausing", "paused", "stopping"}
                    | set(__import__("ainerzero.runtime.lifecycle", fromlist=["x"]).TERMINAL_STATES),
                    "accounted": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            else:
                state_cases[state] = {
                    "in_worker_known_states": state in worker.KNOWN_STATES,
                    "accounted": True,
                    "counted_seconds": counted,
                }
        # the entry path with such a row present
        report = commands.mode_train(args_for(host["phase1"]))
        state_cases["entry_refusal"] = {
            "status": report.get("status"),
            "refused_stage": report.get("refused_stage") or report.get("stage"),
            "message": report.get("message"),
        }
    scope["product_written_states"] = state_cases

    payload = {
        "schema": "ainerzero.v9.p21.probe06_phase_scope.v1",
        "scope": scope,
        "mlx_imported": lib.mlx_imported(),
    }
    payload["verdict"] = {
        "every_phase_row_counted": scope["every_phase_row_counted"],
        "prep_and_eval_rows_counted": scope["prep_and_eval_rows_are_part_of_the_total"],
        "failed_attempt_not_cleared": bool(attempts),
        "entry_refuses_over_cap": (
            scope["entry_refusal"]["refused_stage"] == "phase_budget_exceeded"
        ),
        "entry_refusal_carries_breakdown": scope["entry_refusal"]["has_breakdown"],
    }
    payload["findings"] = {
        "product_written_states_refused": {
            state: row
            for state, row in state_cases.items()
            if state != "entry_refusal" and not row.get("accounted")
        },
        "why": "worker.ACTIVE_STATES = {created, initializing, training, pausing, paused} does not "
        "contain the lifecycle's own WORK_STATES 'collecting' and 'validating' (the S1 worker "
        "moves every prep data run to 'collecting' and every prep smoke/verify and every eval "
        "run to 'validating') and does not contain the transient 'stopping'.  Such a row is "
        "refused as an 'unknown state', so the phase total raises and the train/eval entry "
        "refuses with 'ledger_timestamp_invalid' (a misleading reason: the timestamps are "
        "fine) instead of counting the row as the decision requires",
        "entry_refusal": state_cases["entry_refusal"],
    }
    out = lib.write_json("06-phase-scope.json", payload)
    print(json.dumps(payload["verdict"], indent=1))
    print(json.dumps(payload["findings"]["product_written_states_refused"], indent=1))
    print(json.dumps(scope["entry_refusal"], indent=1))
    print("wrote", out)
    return 0 if all(payload["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
