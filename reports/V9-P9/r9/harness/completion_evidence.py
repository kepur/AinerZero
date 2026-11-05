"""r9 R2 evidence: the P24 F1 double-call probe, re-run against the r9 code.

P24's probe called the internal ``_complete_run`` twice at three truncation
points.  The first call was refused (marker written); the second returned
``status=completed`` -- and at the ``before`` point the ledger row still said
``failed``.

This harness repeats that probe on temporary card-local ledgers and records the
answers, plus the sabotage control in which only the new precondition is
removed (the bug returns, which is what makes the guard load-bearing).

No model, no MLX, no central ledger.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from ainerzero.v9.experiments.s1 import completion, worker  # noqa: E402

OUT = REPO / "reports/V9-P9/r9/evidence/completion-precondition.json"
SCRATCH = REPO / ".tmp/r9-evidence"

UPDATES = 3510
DEADLINE = 450.0
DOCUMENT = {
    "training_protocol": {"updates": UPDATES, "checkpoint_updates": [0, UPDATES]},
    "timing": {"deadline_seconds": DEADLINE},
    "data_identity": {"dataset_digest": "e" * 64},
}
APPROVAL = {"document_sha256": "d" * 64, "line": "test", "line_number": 1}


def _ledger(name: str):
    root = SCRATCH / name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    ledger = worker.PrepLedger(root / "control.sqlite3")
    run_id = worker._open_train_run(DOCUMENT, ledger, APPROVAL, arm_id="arm2", seed=0)
    ledger.begin_work(run_id, work_state="training")
    return root, ledger, run_id


def _complete(ledger, run_id, root, *, protocol):
    return worker._complete_run(
        report={"schema": "test", "mode": "train"},
        ledger=ledger,
        run_id=run_id,
        protocol=protocol,
        output_root=root,
        reason="s1_train_completed",
        kind="train",
    )


def _marker_count(root: Path, run_id: str) -> int:
    return len(completion.invalid_markers(Path(root) / "runs" / run_id))


def _summary(report: dict) -> dict:
    return {
        "status": report.get("status"),
        "refused_stage": report.get("refused_stage"),
        "ledger_state": report.get("ledger_state"),
        "ledger_state_is_completed": report.get("ledger_state_is_completed"),
        "completion_invalid_markers": report.get("completion_invalid_markers"),
        "rolled_back": report.get("rolled_back"),
    }


def _before_truncation() -> dict:
    root, ledger, run_id = _ledger("R2-before")
    protocol = completion.CompletionProtocol(deadline_seconds=20.0)

    def _seam(phase: str, elapsed: float) -> None:
        if phase == "train:pre_terminal_commit" and not protocol.events[1:]:
            protocol.started -= 21.0

    completion.TEST_SEAM = _seam
    try:
        first = _complete(ledger, run_id, root, protocol=protocol)
    finally:
        completion.TEST_SEAM = None
    state_after_first = ledger.get(run_id)["state"]
    markers_after_first = _marker_count(root, run_id)

    second = _complete(
        ledger, run_id, root, protocol=completion.CompletionProtocol(deadline_seconds=20.0)
    )
    payload = {
        "truncation_point": "before the terminal commit",
        "first_call": _summary(first),
        "ledger_state_after_first": state_after_first,
        "markers_after_first": markers_after_first,
        "second_call": _summary(second),
        "ledger_state_after_second": ledger.get(run_id)["state"],
        "markers_after_second": _marker_count(root, run_id),
        "second_call_claims_completed": second.get("status") == "completed",
    }
    ledger.close()
    return payload


def _after_truncation() -> dict:
    root, ledger, run_id = _ledger("R2-after")
    run_dir = Path(root) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    protocol = completion.CompletionProtocol(deadline_seconds=10.0)
    protocol.check("train_receipt")
    completion.write_invalid_marker(
        run_dir,
        protocol=protocol,
        phase="train:terminal_commit",
        reason="deadline_exceeded_in_commit",
        ledger_state="completed",
        detail="injected: commit landed after the deadline",
    )
    ledger.finish(run_id, "completed", "s1_train_completed")

    second = _complete(
        ledger, run_id, root, protocol=completion.CompletionProtocol(deadline_seconds=10.0)
    )
    payload = {
        "truncation_point": "inside/after the terminal commit (row already completed)",
        "second_call": _summary(second),
        "ledger_state_after_second": ledger.get(run_id)["state"],
        "markers_after_second": _marker_count(root, run_id),
        "second_call_claims_completed": second.get("status") == "completed",
    }
    ledger.close()
    return payload


def _terminal_without_marker() -> dict:
    root, ledger, run_id = _ledger("R2-terminal")
    ledger.finish(run_id, "failed", "worker_failure")
    second = _complete(
        ledger, run_id, root, protocol=completion.CompletionProtocol(deadline_seconds=10.0)
    )
    payload = {
        "truncation_point": "no marker; ledger row already failed",
        "second_call": _summary(second),
        "ledger_state_after_second": ledger.get(run_id)["state"],
        "second_call_claims_completed": second.get("status") == "completed",
    }
    ledger.close()
    return payload


def _sabotage_control() -> dict:
    root, ledger, run_id = _ledger("R2-sabotage")
    ledger.finish(run_id, "failed", "worker_failure")
    original = worker._completion_precondition
    worker._completion_precondition = lambda **kwargs: None
    try:
        report = _complete(
            ledger, run_id, root, protocol=completion.CompletionProtocol(deadline_seconds=10.0)
        )
    finally:
        worker._completion_precondition = original
    payload = {
        "guard_removed": "_completion_precondition",
        "reported_status": report.get("status"),
        "ledger_state": ledger.get(run_id)["state"],
        "bug_reproduced": report.get("status") == "completed"
        and ledger.get(run_id)["state"] == "failed",
    }
    ledger.close()
    return payload


def main() -> int:
    payload = {
        "schema": "ainerzero.v9.s1.r9.completion_precondition_evidence.v1",
        "frozen": {"updates": UPDATES, "deadline_seconds": DEADLINE},
        "before_truncation": _before_truncation(),
        "after_truncation": _after_truncation(),
        "terminal_without_marker": _terminal_without_marker(),
        "sabotage_control": _sabotage_control(),
        "scratch_root": str(SCRATCH.relative_to(REPO)),
        "note": "temporary card-local RunStore files only; no model work, no central ledger",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    print(json.dumps(payload, ensure_ascii=False, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
