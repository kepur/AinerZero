"""r9 R1 evidence: both registration orders, the foreign manifest, and the control.

This is the coordinator's minimal CPU reproduction (P24 / P15-R8-DECISION), run
against the r9 code.  It uses temporary card-local RunStore files only -- never
the central ledger, never MLX, never a real run.

Scenarios
---------
A  D (``open_aux_run``) then training (``_open_train_run``) -- must both succeed
   under one experiment ID.
B  training then D -- must both succeed under the same experiment ID.
C  a pre-built experiment with the same ID and a different manifest -- both
   paths must refuse (``ExperimentManifestMismatch``).
D  sabotage control: with only ``_manifest_digest_matches`` removed, the D path
   reuses the foreign experiment (proves the comparison is the guard).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import worker  # noqa: E402

OUT = REPO / "reports/V9-P9/r9/evidence/shared-experiment.json"
SCRATCH = REPO / ".tmp/r9-evidence"

UPDATES = 3510
DEADLINE = 450.0
D_DEADLINE = 2.0

DOCUMENT = {
    "training_protocol": {"updates": UPDATES, "checkpoint_updates": [0, 439, 878, 1755, UPDATES]},
    "timing": {"deadline_seconds": DEADLINE},
    "data_identity": {"dataset_digest": "e" * 64},
}
APPROVAL = {"document_sha256": "d" * 64, "line": "test", "line_number": 1}


def _store(name: str) -> worker.PrepLedger:
    root = SCRATCH / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return worker.PrepLedger(root / "control.sqlite3")


def _open_d(ledger: worker.PrepLedger) -> str:
    return ledger.open_aux_run(
        mode="eval",
        wall_budget_seconds=D_DEADLINE,
        manifest=worker.train_experiment_manifest(updates=UPDATES),
        request_id=f"{worker.TRAIN_EXPERIMENT_ID}:eval:arm1",
        experiment_id=worker.TRAIN_EXPERIMENT_ID,
        snapshot_extra={"arm_id": "arm1", "seed": 0},
    )


def _open_train(ledger: worker.PrepLedger) -> str:
    return worker._open_train_run(DOCUMENT, ledger, APPROVAL, arm_id="arm2", seed=0)


def _close(ledger: worker.PrepLedger, run_id: str, work_state: str) -> None:
    """Finish the scratch run so the next run of the same experiment may start.

    The ledger allows one open run per experiment; the real entry finishes each
    run before the next one opens.  Nothing here performs model work.
    """
    ledger.begin_work(run_id, work_state=work_state)
    ledger.finish(run_id, "completed", "r9_evidence_scratch")


def _observe(ledger: worker.PrepLedger, run_id: str) -> dict:
    record = ledger.get(run_id)
    return {
        "run_id": run_id,
        "state": record["state"],
        "experiment_id": record["experiment_id"],
        "wall_budget_seconds": record["config_snapshot"]["budget"]["max_wall_seconds"],
    }


def _experiments(ledger: worker.PrepLedger) -> list[dict]:
    rows = []
    with __import__("sqlite3").connect(ledger.db_path) as conn:
        for row in conn.execute(
            "SELECT experiment_id, request_id, manifest_hash FROM experiments ORDER BY created_at"
        ):
            rows.append(
                {"experiment_id": row[0], "request_id": row[1], "manifest_hash": row[2]}
            )
    return rows


def _order(name: str, first: str) -> dict:
    ledger = _store(name)
    try:
        d_run = t_run = None
        error = None
        try:
            if first == "D":
                d_run = _open_d(ledger)
                _close(ledger, d_run, "validating")
                t_run = _open_train(ledger)
                _close(ledger, t_run, "training")
            else:
                t_run = _open_train(ledger)
                _close(ledger, t_run, "training")
                d_run = _open_d(ledger)
                _close(ledger, d_run, "validating")
        except Exception as exc:  # the r8 defect surfaced here
            error = f"{type(exc).__name__}: {exc}"
        payload = {
            "order": f"{first}_first",
            "error": error,
            "d": _observe(ledger, d_run) if d_run else None,
            "train": _observe(ledger, t_run) if t_run else None,
            "experiments": _experiments(ledger),
        }
        payload["same_experiment"] = bool(
            d_run and t_run and payload["d"]["experiment_id"] == payload["train"]["experiment_id"]
        )
        payload["budgets"] = {
            "d": payload["d"]["wall_budget_seconds"] if d_run else None,
            "train": payload["train"]["wall_budget_seconds"] if t_run else None,
        }
        return payload
    finally:
        ledger.close()


def _foreign_manifest() -> dict:
    manifest = worker.train_experiment_manifest(updates=UPDATES)
    manifest["purpose"] = "r9 evidence: foreign registration under the shared ID"
    return manifest


def _foreign(name: str, *, sabotage: bool) -> dict:
    ledger = _store(name)
    original = worker._manifest_digest_matches
    try:
        ledger.store.create_experiment(
            _foreign_manifest(), "r9-foreign-request", worker.TRAIN_EXPERIMENT_ID
        )
        if sabotage:
            worker._manifest_digest_matches = lambda existing, expected: True
        result = {"sabotage": sabotage, "d": None, "train": None}
        try:
            d_run = _open_d(ledger)
            result["d"] = {"accepted": True, **_observe(ledger, d_run)}
            _close(ledger, d_run, "validating")
        except worker.ExperimentManifestMismatch as exc:
            result["d"] = {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}
        if sabotage:
            # With the comparison removed the D run is created and left active;
            # the ledger then (correctly) refuses a second concurrent run of the
            # same experiment, so the train leg is not exercised here.
            result["train"] = {"skipped": "D run left active; experiment runs are sequential"}
        else:
            try:
                t_run = _open_train(ledger)
                result["train"] = {"accepted": True, **_observe(ledger, t_run)}
            except worker.ExperimentManifestMismatch as exc:
                result["train"] = {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}
        result["experiments"] = _experiments(ledger)
        return result
    finally:
        worker._manifest_digest_matches = original
        ledger.close()


def main() -> int:
    payload = {
        "schema": "ainerzero.v9.s1.r9.shared_experiment_evidence.v1",
        "frozen": {
            "updates": UPDATES,
            "train_deadline_seconds": DEADLINE,
            "d_deadline_seconds": D_DEADLINE,
            "experiment_id": worker.TRAIN_EXPERIMENT_ID,
        },
        "A_d_then_train": _order("A-d-then-train", "D"),
        "B_train_then_d": _order("B-train-then-d", "T"),
        "C_foreign_manifest": _foreign("C-foreign", sabotage=False),
        "D_sabotage_control": _foreign("D-sabotage", sabotage=True),
        "scratch_root": str(SCRATCH.relative_to(REPO)),
        "note": "temporary card-local RunStore files only; the central ledger is untouched",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k.startswith(("A_", "B_", "C_", "D_"))}, indent=1)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
