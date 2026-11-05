"""r12: every CPU-only entry precondition is decided before the first ledger write.

Background (``P31-LEDGER-INCIDENT-RULING``): during the P31 review a real CLI
eval ran against the production output root.  The trainable-eval branch called
``open_aux_run`` -- experiment row, run row, ``begin_work`` transition,
pre-work reservation -- and only afterwards let ``_evaluate_arm`` raise
``EvalBindingError`` because no completed training run binds the arm x seed.
Three production ledger rows were written for an evaluation that could never
run, and the r11 experiment wall clock started (16:32:18, closing 20:32:18).

r12 decides every precondition that needs only the CPU -- approval line, source
binding, preregistration validation, the eval_batches call-budget gate, the
arm x seed training binding, the attempt guard, the D guard and the phase wall
-- *before* the first write, and refuses with ``refused_stage`` while the
central ledger keeps its bytes.  No new gate and no changed threshold: only the
position of the judgements moved.

These tests assert exactly that, on isolated temporary ledgers:

* every refusal branch leaves ``control.sqlite3``'s SHA256 identical;
* a copy of the product source with *only* the ordering guard removed (the bad
  control, no switch in the product code) writes the ledger and turns red.

Pure CPU: no MLX, no training, no real evaluation, no approval line, no write to
the repository ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import spec, worker

from s1_testkit import (
    FAKE_COUNTS,
    make_plan,
    make_source_checkout,
    stage_phase1_host,
)

R12 = spec.R12_EXPERIMENT_ID
R11 = spec.R11_EXPERIMENT_ID
REPO = Path(__file__).resolve().parents[3]
TESTS_DIR = Path(__file__).resolve().parent


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _install(monkeypatch, staged: dict) -> None:
    """Point ``spec`` at the isolated host (anchor, phase-1 root, approval log)."""
    monkeypatch.setattr(spec, "REGISTERED_HOST_ROOT", staged["host"])
    monkeypatch.setattr(spec, "PHASE1_ROOT", staged["phase1"])
    monkeypatch.setattr(spec, "RESEARCH_LOG", staged["log_path"])


def _staged(tmp_path: Path, **kwargs) -> dict:
    kwargs.setdefault("experiment_id", R12)
    kwargs.setdefault("budget_registration", spec.R11_BUDGET_REGISTRATION)
    return stage_phase1_host(tmp_path / "host", **kwargs)


def _rewrite_document(staged: dict, document: dict) -> Path:
    """Write a tampered frozen document plus a sidecar that matches it."""
    from ainerzero.v9.experiments.s1 import prereg

    path = staged["prereg_path"]
    path.write_text(json.dumps(document, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    digest = prereg.document_sha256(document)
    prereg.write_sha256_file(path, digest)
    return path


def _approve(staged: dict) -> None:
    """Write the one coordinator line that covers the *current* document.

    Used after a test tampers the frozen document: the approval gate is judged
    first, so a branch behind it can only be reached with a line that matches
    the document on disk.  A real executor never writes approval lines.
    """
    from ainerzero.v9.experiments.s1 import prereg

    from s1_testkit import write_research_log

    document = json.loads(staged["prereg_path"].read_text(encoding="utf-8"))
    write_research_log(staged["log_path"], approval_sha=prereg.document_sha256(document))


def _train(staged: dict, *, arm: str = "arm2", seed: int = 0) -> dict:
    return worker.run_worker(
        "train",
        output_root=staged["phase1"],
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=float(staged["document"]["timing"]["deadline_seconds"]),
        prereg_path=staged["prereg_path"],
        arm=arm,
        seed=seed,
    )


def _eval(staged: dict, *, arm: str = "arm2", seed: int = 0) -> dict:
    return worker.run_worker(
        "eval",
        output_root=staged["phase1"],
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0,
        prereg_path=staged["prereg_path"],
        arm=arm,
        seed=seed,
    )


def _started_run(staged: dict, *, experiment_id: str, arm_id: str, seed: int, run_id: str):
    """A real started run row inside one experiment (an attempt)."""
    ledger = worker.PrepLedger(staged["ledger_path"])
    try:
        try:
            ledger.store.get_experiment(experiment_id)
        except KeyError:
            ledger.store.create_experiment(
                worker.train_experiment_manifest(
                    updates=int(staged["document"]["training_protocol"]["updates"])
                ),
                f"{experiment_id}:training",
                experiment_id,
            )
        snapshot = worker.run_config_snapshot(
            wall_budget_seconds=1_200.0, purpose=f"s1_phase1_training_run:{arm_id}:seed{seed}"
        )
        snapshot["arm_id"] = arm_id
        snapshot["seed"] = int(seed)
        snapshot["updates"] = int(staged["document"]["training_protocol"]["updates"])
        ledger.store.create_run(
            snapshot,
            f"{experiment_id}:{arm_id}:{seed}:{run_id}",
            run_id,
            experiment_id=experiment_id,
            role="model",
        )
        ledger.store.transition(run_id, "initializing", reason="train_prereg_approved")
        ledger.store.transition(run_id, "training", reason="worker_started")
    finally:
        ledger.close()
    return run_id


def _age_runs(staged: dict, *, seconds: float, run_id: str) -> None:
    """Move one row's timestamps into the past (conservative phase accounting)."""
    import sqlite3

    with sqlite3.connect(staged["ledger_path"]) as connection:
        connection.execute(
            "UPDATE runs SET created_at = created_at - ?, updated_at = updated_at - ? "
            "WHERE run_id = ?",
            (float(seconds), float(seconds), run_id),
        )


def _assert_refused_untouched(staged: dict, report: dict, stage: str) -> None:
    """The refusal happened and the ledger file kept every byte."""
    assert report["status"] == "refused", report
    assert report["refused_stage"] == stage, report
    # Byte-for-byte: the refused entry registered nothing and started no clock.
    assert _sha(staged["ledger_path"]) == staged["ledger_sha256"]


# --- train entry -----------------------------------------------------------
def test_train_refusal_without_an_approval_line_leaves_the_ledger_untouched(
    tmp_path, monkeypatch
):
    staged = _staged(tmp_path)
    _install(monkeypatch, staged)
    report = _train(staged)
    _assert_refused_untouched(staged, report, "preregistration_not_approved")


def test_train_refusal_on_source_drift_leaves_the_ledger_untouched(tmp_path, monkeypatch):
    staged = _staged(tmp_path, approve=True)
    _install(monkeypatch, staged)
    document = json.loads(json.dumps(staged["document"]))
    bound = sorted(document["source_identity"]["package_files"])[0]
    document["source_identity"]["package_files"][bound] = "0" * 64
    _rewrite_document(staged, document)
    _approve(staged)
    report = _train(staged)
    _assert_refused_untouched(staged, report, "source_binding_drift")


def test_train_refusal_on_an_existing_attempt_leaves_the_ledger_untouched(tmp_path, monkeypatch):
    staged = _staged(tmp_path, approve=True)
    _install(monkeypatch, staged)
    # A prior started attempt under the *registered* experiment forbids a rerun.
    _started_run(staged, experiment_id=R12, arm_id="arm2", seed=0, run_id="r12-arm2-seed0")
    staged["ledger_sha256"] = _sha(staged["ledger_path"])
    report = _train(staged)
    _assert_refused_untouched(staged, report, "already_attempted")


def test_train_refusal_on_the_phase_wall_leaves_the_ledger_untouched(tmp_path, monkeypatch):
    staged = _staged(tmp_path, approve=True)
    _install(monkeypatch, staged)
    run_id = _started_run(
        staged, experiment_id=R12, arm_id="arm3", seed=1, run_id="r12-arm3-seed1"
    )
    # Charge the registration more than the 4 h phase cap, then ask for arm2/seed0.
    _age_runs(staged, seconds=14_300.0, run_id=run_id)
    staged["ledger_sha256"] = _sha(staged["ledger_path"])
    report = _train(staged)
    _assert_refused_untouched(staged, report, "phase_budget_exceeded")


def test_train_refusal_on_a_dataset_mismatch_leaves_the_ledger_untouched(tmp_path, monkeypatch):
    staged = _staged(tmp_path, approve=True)
    _install(monkeypatch, staged)
    document = json.loads(json.dumps(staged["document"]))
    document["data_identity"]["dataset_digest"] = "b" * 64
    _rewrite_document(staged, document)
    _approve(staged)
    report = _train(staged)
    _assert_refused_untouched(staged, report, "dataset_identity_mismatch")


# --- eval entry ------------------------------------------------------------
def test_eval_refusal_without_a_completed_training_run_leaves_the_ledger_untouched(
    tmp_path, monkeypatch
):
    """The load-bearing branch: this is the P31 incident, refused with zero writes.

    Before r12 the entry registered the experiment, the run, the begin_work
    transition and the reservation and only then failed with EvalBindingError,
    which is how the production ledger grew three rows for an eval that could
    never run.
    """
    staged = _staged(tmp_path)
    _install(monkeypatch, staged)
    report = _eval(staged, arm="arm2", seed=0)
    _assert_refused_untouched(staged, report, "eval_binding_unavailable")
    assert "EvalBindingError" in report["eval_binding"]["error"]
    # Nothing was registered: the registration experiment does not exist yet.
    import sqlite3

    with sqlite3.connect(staged["ledger_path"]) as connection:
        experiments = {
            row[0] for row in connection.execute("SELECT experiment_id FROM experiments")
        }
        runs = int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
    assert R12 not in experiments
    assert runs == 0


def test_eval_refusal_on_the_call_budget_leaves_the_ledger_untouched(tmp_path, monkeypatch):
    # 100 development worlds x 8 steps yield 600 development windows = 38 batches
    # per checkpoint, i.e. 5 x 38 = 190 window-probe batches > the registered
    # eval_batches=175 (measured: 6 windows per 8-step synthetic world).
    staged = _staged(
        tmp_path,
        plan=make_plan(train_worlds=4, development_worlds=100, rounds=1),
    )
    _install(monkeypatch, staged)
    report = _eval(staged, arm="arm3", seed=1)
    _assert_refused_untouched(staged, report, "eval_call_budget_exceeded")
    assert report["eval_call_plan"]["window_probe_batches"] == 190


def test_eval_refusal_on_the_d_guard_leaves_the_ledger_untouched(tmp_path, monkeypatch):
    staged = _staged(tmp_path)
    _install(monkeypatch, staged)
    _started_run(staged, experiment_id=R12, arm_id="arm1", seed=0, run_id="r12-arm1")
    staged["ledger_sha256"] = _sha(staged["ledger_path"])
    report = _eval(staged, arm="arm1", seed=0)
    _assert_refused_untouched(staged, report, "already_attempted")


def test_eval_refusal_on_source_drift_leaves_the_ledger_untouched(tmp_path, monkeypatch):
    staged = _staged(tmp_path)
    _install(monkeypatch, staged)
    document = json.loads(json.dumps(staged["document"]))
    bound = sorted(document["source_identity"]["package_files"])[0]
    document["source_identity"]["package_files"][bound] = "0" * 64
    _rewrite_document(staged, document)
    report = _eval(staged, arm="arm2", seed=0)
    _assert_refused_untouched(staged, report, "source_binding_drift")


# --- the bad control -------------------------------------------------------
# The scenario is built once by the *real* product source (so the frozen document
# binds the real files and the entry reaches the ordering guard).  Then the same
# driver runs the same eval against two source trees: the real one, and a
# throw-away checkout whose only difference is that the r12 ordering guard is
# gone.  The product code carries no switch for this -- the sabotage lives in the
# copy, which is why the control cannot be mistaken for a supported mode.
DRIVER = '''
import hashlib, json, sys
from pathlib import Path

host = Path(sys.argv[1])
from ainerzero.v9.experiments.s1 import spec, worker

spec.REGISTERED_HOST_ROOT = host
spec.PHASE1_ROOT = host / "artifacts" / "v9" / "s1" / "phase1"
spec.RESEARCH_LOG = host / "RESEARCH_LOG.md"

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

ledger = spec.PHASE1_ROOT / "control.sqlite3"
before = sha(ledger)
report = worker.run_worker(
    "eval",
    output_root=spec.PHASE1_ROOT,
    limits=spec.RESOURCE_LIMITS,
    wall_budget_seconds=300.0,
    prereg_path=spec.PHASE1_ROOT / "pre_registration.json",
    arm="arm2",
    seed=0,
)
after = sha(ledger)
print(json.dumps({
    "worker_module": worker.__file__,
    "status": report.get("status"),
    "refused_stage": report.get("refused_stage"),
    "error": report.get("error"),
    "ledger_before": before,
    "ledger_after": after,
    "unchanged": before == after,
}))
'''


def _run_driver(workdir: Path, host: Path, source_root: Path) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    driver = workdir / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(source_root), str(TESTS_DIR)])
    completed = subprocess.run(
        [sys.executable, str(driver), str(host)],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_the_ordering_guard_is_load_bearing_bad_control(tmp_path):
    scenario = _staged(tmp_path / "scenario")

    # 1. The real product source: refused, ledger bytes untouched.
    real = _run_driver(tmp_path / "real", scenario["host"], REPO / "src")
    assert Path(real["worker_module"]).resolve().is_relative_to((REPO / "src").resolve())
    assert real["status"] == "refused"
    assert real["refused_stage"] == "eval_binding_unavailable"
    assert real["unchanged"] is True

    # 2. The same scenario against a copy with only the ordering guard removed:
    #    the entry registers the experiment/run before it fails, so the ledger
    #    bytes change.  That is the P31 defect, reproduced.
    checkout = make_source_checkout(tmp_path / "checkout")
    worker_py = checkout / "src/ainerzero/v9/experiments/s1/worker.py"
    text = worker_py.read_text(encoding="utf-8")
    guard = """            binding_precondition = _eval_binding_precondition(
                output_root,
                arm_id=arm,
                seed=eval_seed,
                prereg_sha256=verified["sha256"],
                updates=int(document["training_protocol"]["updates"]),
                ledger_path=ledger_path,
            )"""
    assert guard in text, "the r12 ordering guard is not where this control expects it"
    worker_py.write_text(
        text.replace(
            guard,
            '            binding_precondition = {"status": "ok"}  # sabotage: guard removed',
            1,
        ),
        encoding="utf-8",
    )
    # A private copy of the same host, so the two runs cannot influence each other.
    import shutil

    sabotaged_host = tmp_path / "sabotaged-host"
    shutil.copytree(scenario["host"], sabotaged_host)
    sabotaged = _run_driver(tmp_path / "sabotaged", sabotaged_host, checkout / "src")
    assert Path(sabotaged["worker_module"]).resolve().is_relative_to((checkout / "src").resolve())
    assert sabotaged["unchanged"] is False, sabotaged
    assert sabotaged["status"] != "refused"
    assert "EvalBindingError" in sabotaged["error"]
