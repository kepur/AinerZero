"""r9 R1: one shared TRAIN experiment, reachable in either order, verified.

P24/P15-R8-DECISION reproduced the r8 defect with a minimal CPU script:

    {"train_then_D": {"T": "ok", "D": "ok"},
     "D_then_train": {"D": "ok", "error": "LifecycleError: experiment_id already exists"}}

The D sub-run created the shared experiment through ``open_aux_run`` (request_id
``...:eval:arm1``), while the training path called ``RunStore.create_experiment``
directly (request_id ``...:training``).  ``create_experiment`` is idempotent only
for the same ``request_id``; with the same experiment ID and a different
request_id it hits the primary key.  And the D path never compared the manifest
it found, so a foreign registration would be reused silently.

r9 routes both paths through ``worker.ensure_shared_experiment``:

* both orders register under the same experiment ID;
* an existing experiment is reused only when its ``manifest_hash`` equals the
  canonical digest of the manifest this caller would register;
* a pre-built experiment with a different manifest is refused by both paths.

Everything below drives the real public ``worker.run_worker`` entry with a CPU
double.  No MLX, no training of a real model, no approval line, no new data.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import data, spec, worker

from s1_testkit import write_frozen, write_research_log
# r8 CPU doubles and document builder (read-only reuse; r8 files are untouched)
from test_s1_r8_completion import _CpuBackend, _ScriptedClock, _install_loop
from test_s1_r8_d_budget import _DCpuBackend, _document

UPDATES = 3510
DEADLINE = 450.0
D_DEADLINE = 2.0


class _LoopClock(_ScriptedClock):
    """Scripted *loop* clock that still answers the real wall-clock read.

    ``worker.time`` is replaced by the training double.  The r8 double only
    implements ``perf_counter``/``sleep``; the phase accounting (which now sees a
    D row before the training run) also calls ``time.time()``.  Keeping that one
    read real leaves the ledger timestamps untouched.
    """

    def time(self) -> float:
        return time.time()


def _shared_root(tmp_path, monkeypatch, canonical_root, synthetic_dataset):
    """Isolated canonical host: bound dataset, frozen document, approval line."""
    manifest, dataset_dir, _plan = synthetic_dataset
    identity = data.dataset_identity(manifest)
    target = tmp_path / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dataset_dir, target)
    root = Path(canonical_root)
    data.write_dataset_ref(root, manifest, target)
    document = _document(identity)
    assert float(document["timing"]["deadline_seconds"]) == DEADLINE
    assert float(document["timing"]["arm1_deadline_seconds"]) == D_DEADLINE
    assert int(document["training_protocol"]["updates"]) == UPDATES
    path, digest, _doc = write_frozen(root / "pre_registration.json", document=document)
    log = write_research_log(tmp_path / "RESEARCH_LOG.md", approval_sha=digest)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log)
    return root, path, digest, log


def _run_d(root, path):
    return worker.run_worker(
        "eval",
        output_root=root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=300.0,
        prereg_path=path,
        arm="arm1",
        seed=0,
        backend=_DCpuBackend(),
    )


def _run_train(root, path, log, *, arm="arm2", seed=0):
    return worker.run_worker(
        "train",
        output_root=root,
        limits=spec.RESOURCE_LIMITS,
        wall_budget_seconds=DEADLINE,
        prereg_path=path,
        research_log=log,
        arm=arm,
        seed=seed,
        backend=_CpuBackend(_LoopClock()),
    )


def _experiment_rows(root: Path) -> list[sqlite3.Row]:
    with sqlite3.connect(root / "control.sqlite3") as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM experiments WHERE experiment_id=?", (worker.TRAIN_EXPERIMENT_ID,)
        ).fetchall()


def _assert_shared_experiment(root: Path, d_run: str, t_run: str) -> dict:
    """Both runs live under the one experiment ID; the phase view sees both."""
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        runs = {record.run_id: record for record in ledger.store.list_runs()}
        # The training double replaces ``worker.time`` with a scripted clock, so
        # the accounting instant is passed explicitly (one real wall-clock read).
        breakdown = worker.phase_ledger_breakdown(
            ledger.store.list_runs(), instant=time.time()
        )
    finally:
        ledger.close()

    assert d_run in runs and t_run in runs
    assert runs[d_run].experiment_id == worker.TRAIN_EXPERIMENT_ID
    assert runs[t_run].experiment_id == worker.TRAIN_EXPERIMENT_ID

    # The two registered run budgets are the frozen ones: 2 s for D, 450 s for
    # training.  Neither leaked into the shared experiment ceiling.
    assert float(runs[d_run].config_snapshot["budget"]["max_wall_seconds"]) == D_DEADLINE
    assert float(runs[t_run].config_snapshot["budget"]["max_wall_seconds"]) == DEADLINE

    rows = {row["run_id"]: row for row in breakdown["rows"]}
    assert d_run in rows and t_run in rows
    assert rows[d_run]["counted_seconds"] >= 1.0 - 1e-9  # the 1 s pre-work reservation
    assert breakdown["total_seconds"] >= rows[d_run]["counted_seconds"] + rows[t_run][
        "counted_seconds"
    ] - 1e-9

    # Exactly one experiment carries this ID: no replacement was created.
    assert len(_experiment_rows(root)) == 1
    return {"runs": runs, "breakdown": breakdown}


# --- forward: D first, then training --------------------------------------
def test_d_then_train_register_in_the_same_experiment(
    tmp_path, monkeypatch, canonical_root, synthetic_dataset
):
    root, path, _digest, log = _shared_root(
        tmp_path, monkeypatch, canonical_root, synthetic_dataset
    )

    d_report = _run_d(root, path)
    assert d_report["status"] == "completed", d_report.get("message")
    assert d_report["experiment_id"] == worker.TRAIN_EXPERIMENT_ID

    _install_loop(monkeypatch, _LoopClock())
    t_report = _run_train(root, path, log)
    assert t_report["status"] == "completed", json.dumps(
        {k: v for k, v in t_report.items() if k not in ("details", "run")}, default=str
    )[:2000]

    view = _assert_shared_experiment(root, d_report["run_id"], t_report["run_id"])
    # The D run kept its own 2 s allowance; the training run its 450 s one.
    assert view["runs"][d_report["run_id"]].config_snapshot["arm_id"] == "arm1"
    assert view["runs"][t_report["run_id"]].config_snapshot["arm_id"] == "arm2"


# --- reverse: training first, then D --------------------------------------
def test_train_then_d_register_in_the_same_experiment(
    tmp_path, monkeypatch, canonical_root, synthetic_dataset
):
    root, path, _digest, log = _shared_root(
        tmp_path, monkeypatch, canonical_root, synthetic_dataset
    )

    _install_loop(monkeypatch, _LoopClock())
    t_report = _run_train(root, path, log)
    assert t_report["status"] == "completed", t_report.get("message")

    d_report = _run_d(root, path)
    assert d_report["status"] == "completed", d_report.get("message")
    assert d_report["experiment_id"] == worker.TRAIN_EXPERIMENT_ID

    _assert_shared_experiment(root, d_report["run_id"], t_report["run_id"])


# --- reverse case: a foreign manifest under the same ID is refused --------
def _prebuild_foreign_experiment(root: Path) -> dict:
    """Same ID, same ceilings, one different non-budget field."""
    manifest = worker.train_experiment_manifest(updates=UPDATES)
    manifest["purpose"] = "r9 fixture: a foreign registration under the shared ID"
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        ledger.store.create_experiment(
            manifest, "r9-foreign-request", worker.TRAIN_EXPERIMENT_ID
        )
    finally:
        ledger.close()
    return manifest


def test_a_prebuilt_experiment_with_a_different_manifest_is_refused_by_both_paths(
    tmp_path, monkeypatch, canonical_root, synthetic_dataset
):
    root, path, _digest, log = _shared_root(
        tmp_path, monkeypatch, canonical_root, synthetic_dataset
    )
    foreign = _prebuild_foreign_experiment(root)

    d_report = _run_d(root, path)
    assert d_report["status"] == "refused"
    assert d_report["refused_stage"] == "train_experiment_manifest_mismatch"
    assert d_report["experiment_id"] == worker.TRAIN_EXPERIMENT_ID
    assert "ExperimentManifestMismatch" in d_report["error"]

    _install_loop(monkeypatch, _LoopClock())
    t_report = _run_train(root, path, log)
    assert t_report["status"] == "refused"
    assert t_report["refused_stage"] == "train_experiment_manifest_mismatch"
    assert "ExperimentManifestMismatch" in t_report["error"]

    # Neither path registered a run, and the foreign experiment is untouched.
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        assert ledger.store.list_runs() == []
    finally:
        ledger.close()
    rows = _experiment_rows(root)
    assert len(rows) == 1
    assert json.loads(rows[0]["manifest_json"])["purpose"] == foreign["purpose"]


# --- sabotage control: remove only the digest comparison ------------------
def test_removing_only_the_manifest_comparison_lets_the_foreign_experiment_through(
    tmp_path, monkeypatch, canonical_root, synthetic_dataset
):
    """The comparison, not something else, is what refuses the reuse.

    With ``_manifest_digest_matches`` forced to ``True`` (i.e. the comparison
    deleted), the D sub-run attaches to the foreign experiment and completes --
    which is exactly the r8 behaviour this card removes.
    """
    root, path, _digest, _log = _shared_root(
        tmp_path, monkeypatch, canonical_root, synthetic_dataset
    )
    _prebuild_foreign_experiment(root)
    monkeypatch.setattr(
        worker, "_manifest_digest_matches", lambda existing, expected: True
    )

    d_report = _run_d(root, path)
    assert d_report["status"] == "completed", d_report.get("message")
    assert d_report["experiment_id"] == worker.TRAIN_EXPERIMENT_ID
    assert len(_experiment_rows(root)) == 1, "the foreign experiment was reused, not replaced"


# --- unit level: the helper itself ----------------------------------------
def test_ensure_shared_experiment_is_idempotent_for_the_same_manifest(tmp_path):
    ledger = worker.PrepLedger(tmp_path / "control.sqlite3")
    try:
        manifest = worker.train_experiment_manifest(updates=UPDATES)
        first = worker.ensure_shared_experiment(
            ledger.store,
            manifest=manifest,
            request_id=f"{worker.TRAIN_EXPERIMENT_ID}:training",
            experiment_id=worker.TRAIN_EXPERIMENT_ID,
        )
        second = worker.ensure_shared_experiment(
            ledger.store,
            manifest=manifest,
            request_id=f"{worker.TRAIN_EXPERIMENT_ID}:eval:arm1",
            experiment_id=worker.TRAIN_EXPERIMENT_ID,
        )
        assert first.experiment_id == second.experiment_id == worker.TRAIN_EXPERIMENT_ID
        assert first.manifest_hash == second.manifest_hash
        assert first.request_id == f"{worker.TRAIN_EXPERIMENT_ID}:training"

        with pytest.raises(worker.ExperimentManifestMismatch):
            worker.ensure_shared_experiment(
                ledger.store,
                manifest={**manifest, "purpose": "different"},
                request_id="r9-other-request",
                experiment_id=worker.TRAIN_EXPERIMENT_ID,
            )
    finally:
        ledger.close()
