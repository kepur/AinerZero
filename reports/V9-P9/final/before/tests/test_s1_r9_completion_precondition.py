"""r9 R2: ``_complete_run`` must not report ``completed`` on an invalid run.

P24's F1 probe (``reports/V9-P24/logs/probe-f1.json``) called the internal
``_complete_run`` twice.  The first call was correctly refused at each of the
three truncation points and wrote ``completion_invalid.json``; the second call
walked straight into ``ledger.finish(run_id, "completed")``, the ledger returned
the already-terminal row unchanged, and the report said ``completed`` -- for the
``before`` truncation point the row itself still said ``failed``.

The public ``run_worker`` path is protected by the attempt guard, so this was
never an accepted completion; it still violated F1 ("a timeout/interruption must
not return completed", "file existence is not success").

r9 refuses up front when the run already carries an invalidation marker, or is
already terminal in a state other than ``completed``, and reports the ledger
state it actually found.  Nothing is deleted, rewritten or refunded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import completion, worker

UPDATES = 3510
DEADLINE = 450.0


def _ledger_in_training(root: Path):
    """One real run row in the ``training`` work state (no model work)."""
    ledger = worker.PrepLedger(Path(root) / "control.sqlite3")
    document = {
        "training_protocol": {"updates": UPDATES, "checkpoint_updates": [0, UPDATES]},
        "timing": {"deadline_seconds": DEADLINE},
        "data_identity": {"dataset_digest": "e" * 64},
    }
    run_id = worker._open_train_run(
        document,
        ledger,
        {"document_sha256": "d" * 64, "line": "test", "line_number": 1},
        arm_id="arm2",
        seed=0,
    )
    ledger.begin_work(run_id, work_state="training")
    return ledger, run_id


def _complete(ledger, run_id, root, *, deadline=20.0, protocol=None):
    return worker._complete_run(
        report={"schema": "test", "mode": "train"},
        ledger=ledger,
        run_id=run_id,
        protocol=protocol or completion.CompletionProtocol(deadline_seconds=deadline),
        output_root=Path(root),
        reason="s1_train_completed",
        kind="train",
    )


# --- 1. the exact P24 F1 sequence: refuse, then ask again ------------------
def test_a_second_completion_after_a_refusal_reports_the_failed_row(tmp_path, canonical_root):
    root = Path(canonical_root)
    ledger, run_id = _ledger_in_training(root)

    protocol = completion.CompletionProtocol(deadline_seconds=20.0)

    def _seam(phase: str, elapsed: float) -> None:
        if phase == "train:pre_terminal_commit" and not protocol.events[1:]:
            protocol.started -= 21.0  # the next check sees 21 s > 20 s

    completion.TEST_SEAM = _seam
    try:
        first = _complete(ledger, run_id, root, protocol=protocol)
    finally:
        completion.TEST_SEAM = None

    assert first["status"] == "failed"
    assert first["refused_stage"] == "completion_deadline_exceeded"
    assert ledger.get(run_id)["state"] == "failed"
    markers_before = completion.invalid_markers(root / "runs" / run_id)
    assert len(markers_before) == 1

    # The second call is the P24 probe: it must not claim completed.
    second = _complete(ledger, run_id, root)
    assert second["status"] != "completed"
    assert second["status"] == "refused"
    assert second["refused_stage"] == "completion_already_invalid"
    assert second["ledger_state"] == "failed"
    assert second["ledger_state_is_completed"] is False
    assert [str(path) for path in markers_before] == second["completion_invalid_markers"]
    assert second["rolled_back"] is False

    # Nothing was deleted, rewritten, duplicated or refunded.
    assert ledger.get(run_id)["state"] == "failed"
    assert completion.invalid_markers(root / "runs" / run_id) == markers_before
    ledger.close()


# --- 2. the "after" truncation point: completed row + marker --------------
def test_a_second_completion_on_an_invalid_completed_row_is_refused(tmp_path, canonical_root):
    root = Path(canonical_root)
    ledger, run_id = _ledger_in_training(root)
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    protocol = completion.CompletionProtocol(deadline_seconds=10.0)
    protocol.check("train_receipt")
    completion.write_invalid_marker(
        run_dir,
        protocol=protocol,
        phase="train:terminal_commit",
        reason="deadline_exceeded_in_commit",
        ledger_state="completed",
        detail="injected (P24 F1 'after' truncation point)",
    )
    ledger.finish(run_id, "completed", "s1_train_completed")

    report = _complete(ledger, run_id, root)
    assert report["status"] == "refused"
    assert report["refused_stage"] == "completion_already_invalid"
    assert report["ledger_state"] == "completed"
    assert report["ledger_state_is_completed"] is True
    assert len(report["completion_invalid_markers"]) == 1

    record = ledger.get(run_id)
    assert record["state"] == "completed"  # append-only: never rewritten
    assert len(completion.invalid_markers(run_dir)) == 1  # no second marker invented
    ledger.close()


# --- 3. a terminal row that is not completed, with no marker --------------
def test_a_terminal_non_completed_row_is_refused(tmp_path, canonical_root):
    root = Path(canonical_root)
    ledger, run_id = _ledger_in_training(root)
    ledger.finish(run_id, "failed", "worker_failure")

    report = _complete(ledger, run_id, root)
    assert report["status"] == "refused"
    assert report["refused_stage"] == "ledger_terminal_not_completed"
    assert report["ledger_state"] == "failed"
    assert report["completion_invalid_markers"] == []
    assert ledger.get(run_id)["state"] == "failed"
    ledger.close()


# --- 4. sabotage control: remove the precondition --------------------------
def test_removing_the_precondition_lets_the_buggy_claim_through(tmp_path, canonical_root, monkeypatch):
    """Without the guard the old behaviour returns: status completed, row failed.

    This reproduces P24 F1 exactly and proves the new precondition is what stops
    it (rather than the ledger, the protocol or the attempt guard).
    """
    root = Path(canonical_root)
    ledger, run_id = _ledger_in_training(root)
    ledger.finish(run_id, "failed", "worker_failure")

    monkeypatch.setattr(worker, "_completion_precondition", lambda **kwargs: None)
    report = _complete(ledger, run_id, root)

    assert report["status"] == "completed"  # the bug
    assert ledger.get(run_id)["state"] == "failed"  # the row was never completed
    ledger.close()
