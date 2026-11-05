"""r6 central-ledger anchoring tests (P15 item 1, worker half).

A bounded run (train/eval) must register in the **one** central RunStore under
``spec.PHASE1_ROOT`` and must only run at that root.  A copied output root, a
relocated checkout or a replaced ledger must not reset the arm x seed attempt
guard or the phase wall total, and a missing / unreadable / unrecognized ledger
must fail closed -- never be re-created.

Every case runs against the isolated ``canonical_root`` fixture; the real
repository ledger under ``artifacts/v9/s1/phase1/`` is never touched.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import spec, worker

from s1_testkit import frozen_document, install_test_host, write_frozen, write_research_log

DEADLINE = 450.0


def _recognized_ledger(root: Path) -> Path:
    """Create a central ledger the identity check recognises (prep experiment)."""
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        ledger.store.create_experiment(
            worker.prep_experiment_manifest(),
            worker.PREP_REQUEST_ID,
            worker.PREP_EXPERIMENT_ID,
        )
    finally:
        ledger.close()
    return root / "control.sqlite3"


# --- the canonical path is the single anchor -------------------------------
def test_canonical_ledger_path_is_the_phase1_control_db(monkeypatch, tmp_path):
    monkeypatch.setattr(spec, "PHASE1_ROOT", tmp_path / "somewhere-else")
    assert worker.canonical_ledger_path() == tmp_path / "somewhere-else" / "control.sqlite3"


# --- the read-only identity check ------------------------------------------
def test_ledger_state_missing(tmp_path):
    state = worker.canonical_ledger_state(tmp_path / "absent" / "control.sqlite3")
    assert state["status"] == "missing"
    assert not (tmp_path / "absent").exists(), "the check must never create anything"


def test_ledger_state_unreadable_for_a_replaced_file(tmp_path):
    replaced = tmp_path / "control.sqlite3"
    replaced.write_text("this is not a sqlite database\n", encoding="utf-8")
    state = worker.canonical_ledger_state(replaced)
    assert state["status"] == "unreadable"


def test_ledger_state_unrecognized_without_the_runs_tables(tmp_path):
    empty = tmp_path / "control.sqlite3"
    with sqlite3.connect(empty) as connection:
        connection.execute("CREATE TABLE notes (body TEXT)")
    state = worker.canonical_ledger_state(empty)
    assert state["status"] == "unrecognized"
    assert "not a RunStore ledger" in state["reason"]


def test_ledger_state_unrecognized_without_the_prep_experiment(tmp_path):
    foreign = tmp_path / "control.sqlite3"
    ledger = worker.PrepLedger(foreign)
    try:
        # A real RunStore, but not the phase-1 preparation ledger.
        ledger.store.create_experiment(
            worker.prep_experiment_manifest(), "some-other-request", "some-other-experiment"
        )
    finally:
        ledger.close()
    state = worker.canonical_ledger_state(foreign)
    assert state["status"] == "unrecognized"
    assert worker.PREP_EXPERIMENT_ID not in state["experiments"]


def test_ledger_state_ok_for_the_recognized_ledger(tmp_path):
    ledger_path = _recognized_ledger(tmp_path)
    state = worker.canonical_ledger_state(ledger_path)
    assert state["status"] == "ok"
    assert worker.PREP_EXPERIMENT_ID in state["experiments"]
    assert state["runs"] == 0


# --- run_worker refuses every non-canonical or broken anchor ---------------
def _train_args(output_root: Path, prereg_path: Path) -> dict:
    return dict(
        mode="train",
        output_root=output_root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=prereg_path,
        research_log=None,
        arm="arm2",
        seed=0,
    )


def test_run_worker_refuses_a_relocated_output_root(monkeypatch, tmp_path, canonical_root):
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    elsewhere = tmp_path / "copied-run-root"
    report = worker.run_worker(**_train_args(elsewhere, path))
    assert report["status"] == "refused"
    assert report["refused_stage"] == "output_root_not_canonical"
    assert report["control_db"] == str((canonical_root / "control.sqlite3").resolve())
    assert not elsewhere.exists(), "a refused run must not even create the run root"


def test_run_worker_refuses_eval_at_a_relocated_output_root(monkeypatch, tmp_path, canonical_root):
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    report = worker.run_worker(
        mode="eval",
        output_root=tmp_path / "copied-run-root",
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        arm="arm2",
        seed=0,
    )
    assert report["status"] == "refused"
    assert report["refused_stage"] == "output_root_not_canonical"


def test_run_worker_fails_closed_when_the_central_ledger_is_missing(monkeypatch, tmp_path):
    root = install_test_host(monkeypatch, tmp_path)
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    report = worker.run_worker(**_train_args(root, path))
    assert report["status"] == "refused"
    assert report["refused_stage"] == "central_ledger_missing"
    assert report["ledger"]["status"] == "missing"
    assert not (root / "control.sqlite3").exists(), (
        "a bounded run must never create a new ledger to retry against"
    )


def test_run_worker_fails_closed_when_the_central_ledger_is_replaced(monkeypatch, tmp_path):
    root = install_test_host(monkeypatch, tmp_path)
    (root / "control.sqlite3").write_text("not a database", encoding="utf-8")
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    report = worker.run_worker(**_train_args(root, path))
    assert report["status"] == "refused"
    assert report["refused_stage"] == "central_ledger_unreadable"
    # The replaced file is left exactly as it was: never rewritten, never replaced.
    assert (root / "control.sqlite3").read_text(encoding="utf-8") == "not a database"


def test_run_worker_fails_closed_when_the_central_ledger_is_foreign(monkeypatch, tmp_path):
    root = install_test_host(monkeypatch, tmp_path)
    foreign = worker.PrepLedger(root / "control.sqlite3")
    try:
        foreign.store.create_experiment(
            worker.prep_experiment_manifest(), "another-request", "another-experiment"
        )
    finally:
        foreign.close()
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    report = worker.run_worker(**_train_args(root, path))
    assert report["status"] == "refused"
    assert report["refused_stage"] == "central_ledger_unrecognized"
    assert report["ledger"]["status"] == "unrecognized"


def test_run_worker_passes_the_anchor_and_reaches_the_approval_gate(
    monkeypatch, tmp_path, canonical_root
):
    """With a recognized central ledger at the canonical root the anchor is passed."""
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    monkeypatch.setattr(
        spec, "RESEARCH_LOG", write_research_log(tmp_path / "RESEARCH_LOG.md")  # no approval line
    )
    report = worker.run_worker(**_train_args(canonical_root, path))
    assert report["status"] == "refused"
    # Past the ledger/root anchors, stopped by the approval gate: the anchor
    # checks did not fail closed on a healthy ledger.
    assert report["refused_stage"] == "preregistration_not_approved"
    assert report["control_db"] == str((canonical_root / "control.sqlite3").resolve())


def test_run_worker_registers_in_the_central_ledger_not_a_copy(monkeypatch, tmp_path, canonical_root):
    """A run opened through the worker lands in the central ledger, once."""
    path, digest, _document = write_frozen(tmp_path / "pre_registration.json")
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)
    monkeypatch.setattr(
        worker.data,
        "dataset_binding_state",
        lambda root, digest: {
            "status": "passed",
            "expected_dataset_digest": digest,
            "actual_dataset_digest": digest,
        },
    )
    document = frozen_document()
    monkeypatch.setattr(
        worker,
        "_train",
        lambda *args, **kwargs: {
            "arm_id": "arm2",
            "seed": 0,
            "updates": int(document["training_protocol"]["updates"]),
            "receipt": {"schema": "ainerzero.v9.s1.completion.v1", "run_id": "stub"},
            "status": "completed",
        },
    )
    report = worker.run_worker(**_train_args(canonical_root, path))
    assert report["status"] == "completed", report
    assert report["run"]["state"] == "completed"
    # Exactly one ledger exists and it is the central one.
    ledgers = list(canonical_root.glob("**/control.sqlite3"))
    assert ledgers == [canonical_root / "control.sqlite3"]
    assert report["control_db"] == str((canonical_root / "control.sqlite3").resolve())
