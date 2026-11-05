"""r6 entry-side guard tests (P15 item 1, commands half).

The command entry validates the canonical run root and the central RunStore
*before* the approval gate is even read (dual validation with the worker), and
the attempt / phase-total guards read the one central ledger and fail closed on
it.  The tripwire patterns below prove the refusals happen before any worker
subprocess is started.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainerzero.v9.experiments.s1 import commands, data, spec, worker

from s1_testkit import install_test_host, write_frozen, write_research_log

DEADLINE = 450.0


def _args(output_root: Path, prereg_path: Path, *, mode: str = "train", arm: str = "arm2", seed: int = 0):
    return SimpleNamespace(
        mode=mode,
        output_root=output_root,
        prereg=prereg_path,
        limits_file=None,
        wall_budget_seconds=None,
        research_log=None,
        arm=arm,
        seed=seed,
    )


def _approved(tmp_path, monkeypatch, output_root: Path):
    """A frozen preregistration with a valid approval line and a passing dataset."""
    path, digest, document = write_frozen(output_root / "pre_registration.json")
    monkeypatch.setattr(
        spec, "RESEARCH_LOG", write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    )
    monkeypatch.setattr(
        data,
        "dataset_binding_state",
        lambda root, digest: {
            "status": "passed",
            "expected_dataset_digest": digest,
            "actual_dataset_digest": digest,
        },
    )
    return path, digest, document


def _register_attempt(canonical_root: Path, document, digest: str, *, arm: str = "arm2", seed: int = 0):
    ledger = worker.PrepLedger(canonical_root / "control.sqlite3")
    try:
        return worker._open_train_run(
            document, ledger, {"document_sha256": digest}, arm_id=arm, seed=seed
        )
    finally:
        ledger.close()


# --- the canonical run root, entry half ------------------------------------
def test_canonical_run_root_accepts_the_phase1_root(monkeypatch, tmp_path):
    anchor = install_test_host(monkeypatch, tmp_path)
    root, refusal = commands._canonical_run_root(_args(anchor, tmp_path / "p.json"), "train")
    assert refusal is None
    assert root == anchor


def test_canonical_run_root_defaults_to_the_phase1_root(monkeypatch, tmp_path):
    anchor = install_test_host(monkeypatch, tmp_path)
    args = SimpleNamespace(mode="train", prereg=tmp_path / "p.json")
    root, refusal = commands._canonical_run_root(args, "train")
    assert refusal is None
    assert root == anchor


def test_canonical_run_root_refuses_a_copied_root(monkeypatch, tmp_path):
    install_test_host(monkeypatch, tmp_path)
    copied = tmp_path / "copied" / "phase1"
    _root, refusal = commands._canonical_run_root(_args(copied, tmp_path / "p.json"), "train")
    assert refusal is not None
    assert refusal["stage"] == "output_root_not_canonical"
    assert refusal["refused_stage"] == "output_root_not_canonical"
    assert refusal["mode"] == "train"


def test_mode_train_refuses_a_copied_root_before_any_worker(monkeypatch, tmp_path, canonical_root):
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    copied = tmp_path / "copied-run-root"

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("the worker started from a copied run root")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_train(_args(copied, path))
    assert report["status"] == "refused"
    assert report["stage"] == "output_root_not_canonical"
    assert not copied.exists(), "the entry must refuse before creating the run root"
    assert commands._exit_code_for(report) == commands.EXIT_REFUSED_APPROVAL


def test_s1_command_exit_code_is_three_for_a_copied_root(monkeypatch, tmp_path, canonical_root):
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")
    report, code = commands.s1_phase1_command(_args(tmp_path / "copied-run-root", path))
    assert code == commands.EXIT_REFUSED_APPROVAL == 3
    assert report["stage"] == "output_root_not_canonical"


# --- the central ledger, entry half ----------------------------------------
def test_mode_train_fails_closed_on_a_missing_central_ledger(monkeypatch, tmp_path):
    root = install_test_host(monkeypatch, tmp_path)
    path, _digest, _document = _approved(tmp_path, monkeypatch, root)

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("the worker started without the central ledger")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_train(_args(root, path))
    assert report["status"] == "refused"
    assert report["stage"] == "central_ledger_missing"
    assert not (root / "control.sqlite3").exists()


def test_mode_train_fails_closed_on_a_replaced_central_ledger(monkeypatch, tmp_path):
    root = install_test_host(monkeypatch, tmp_path)
    (root / "control.sqlite3").write_text("replaced", encoding="utf-8")
    path, _digest, _document = _approved(tmp_path, monkeypatch, root)

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("the worker started against a replaced ledger")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_train(_args(root, path))
    assert report["status"] == "refused"
    assert report["stage"] == "central_ledger_unreadable"
    assert (root / "control.sqlite3").read_text(encoding="utf-8") == "replaced"


def test_mode_train_fails_closed_on_a_foreign_central_ledger(monkeypatch, tmp_path):
    root = install_test_host(monkeypatch, tmp_path)
    foreign = worker.PrepLedger(root / "control.sqlite3")
    try:
        foreign.store.create_experiment(
            worker.prep_experiment_manifest(), "another-request", "another-experiment"
        )
    finally:
        foreign.close()
    path, _digest, _document = _approved(tmp_path, monkeypatch, root)

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("the worker started against a foreign ledger")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_train(_args(root, path))
    assert report["status"] == "refused"
    assert report["stage"] == "central_ledger_unrecognized"


# --- the attempt guard reads the central ledger ----------------------------
def test_mode_train_refuses_a_second_attempt_from_the_central_ledger(
    tmp_path, monkeypatch, canonical_root
):
    path, digest, document = _approved(tmp_path, monkeypatch, canonical_root)
    run_id = _register_attempt(canonical_root, document, digest)

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("a rerun reached the worker")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_train(_args(canonical_root, path))
    assert report["status"] == "refused"
    assert report["stage"] == "already_attempted"
    assert report["run_id"] == run_id
    assert report["attempt_states"]
    assert commands._exit_code_for(report) == commands.EXIT_REFUSED_APPROVAL


def test_mode_train_refuses_when_the_phase_wall_total_is_exhausted(
    tmp_path, monkeypatch, canonical_root
):
    path, digest, document = _approved(tmp_path, monkeypatch, canonical_root)
    run_id = _register_attempt(canonical_root, document, digest)
    # Reset the row to the pre-start state so only the phase cap can refuse, and
    # inflate its wall time so the cap is provably the refusing guard.
    with sqlite3.connect(canonical_root / "control.sqlite3") as connection:
        connection.execute(
            "UPDATE runs SET state = 'created', created_at = created_at - 14200.0 WHERE run_id = ?",
            (run_id,),
        )

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("an over-budget run reached the worker")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_train(_args(canonical_root, path))
    assert report["status"] == "refused"
    assert report["stage"] == "phase_budget_exceeded"
    assert report["total_wall_seconds"] + report["deadline_seconds"] > report["phase_wall_max_seconds"]
    assert commands._exit_code_for(report) == commands.EXIT_REFUSED_APPROVAL


# --- eval mirrors the same entry checks ------------------------------------
def test_mode_eval_refuses_a_copied_root(monkeypatch, tmp_path, canonical_root):
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("eval started from a copied run root")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_eval(_args(tmp_path / "copied-run-root", path, mode="eval", arm="arm2"))
    assert report["status"] == "refused"
    assert report["stage"] == "output_root_not_canonical"


def test_mode_eval_fails_closed_on_a_missing_central_ledger(monkeypatch, tmp_path):
    root = install_test_host(monkeypatch, tmp_path)
    path, _digest, _document = write_frozen(tmp_path / "pre_registration.json")

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("eval started without the central ledger")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_eval(_args(root, path, mode="eval", arm="arm2"))
    assert report["status"] == "refused"
    assert report["stage"] == "central_ledger_missing"


def test_mode_eval_passes_the_anchor_to_the_worker(tmp_path, monkeypatch, canonical_root):
    """With a healthy anchor the eval entry hands off to the worker."""
    path, digest, _document = write_frozen(canonical_root / "pre_registration.json")
    captured: dict = {}

    def _fake_worker(mode, **kwargs):
        captured.update({"mode": mode, **kwargs})
        return {
            "schema": "ainerzero.v9.s1.worker_report.v1",
            "mode": mode,
            "status": "completed",
            "control_db": str(kwargs["output_root"] / "control.sqlite3"),
        }

    monkeypatch.setattr(commands, "_supervised_worker", _fake_worker)
    report = commands.mode_eval(_args(canonical_root, path, mode="eval", arm="arm2"))
    assert report["status"] == "completed"
    assert captured["mode"] == "eval"
    assert captured["output_root"] == canonical_root
    assert captured["budget"] == commands.PREP_BUDGET["eval"]
