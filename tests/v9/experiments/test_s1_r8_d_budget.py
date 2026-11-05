"""r8 F3/F4: the D sub-run fits its frozen 2 s registration, and "exactly one
D evaluation" is enforced on the rows the product itself writes.

P21 F3: r7 registered the arm1 run with the generic eval entry budget (300 s)
while the experiment manifest carried ``arm1_deadline_seconds`` (2 s), so
``create_run`` refused ("run budget exceeds experiment run limits"); with a
smaller budget instead, the 5 s reservation floor swallowed the 2 s run.  No
budget value could complete the D re-check.

P21 F4: r7's guard matched ``config_snapshot["arm_id"] == "arm1"``, but the
product's ``open_aux_run`` never wrote ``arm_id``, so the row it had just
created was invisible to the guard and a second D evaluation was admitted.
"""

from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest

from ainerzero.v9.experiments.s1 import data, spec, worker

from s1_testkit import FAKE_COUNTS, fake_smoke, write_frozen

UPDATES = 3510
# r11: the registered eval_batches is 175, so these step times are the ones that
# reproduce the production document shape the tests below exercise -- 3510
# updates and a 450 s training deadline (TRAIN_STEP solves
# floor((75 - 875*s) / (3*s)) = 3510) and a 2 s D-candidate deadline
# (ceil(5250*D_STEP) = 2).  They are fixture values, not measurements.
TRAIN_STEP = 0.006575
D_STEP = 0.0003


class _DCandidateOutput:
    def __init__(self) -> None:
        self.metrics = {
            "symbol_nll_t0": 0.0989,
            "symbol_nll_t1": 2.4523,
            "observation_loss_t0": 0.1935,
            "observation_loss_t1": 2.7446,
        }


class _DCpuBackend:
    """CPU stand-in for the frozen D candidate forward (never MLX)."""

    name = "cpu-test-substitute-r8-d"

    def __init__(self) -> None:
        self.calls = 0
        self.d_candidate_info = {
            "parameter_count": FAKE_COUNTS["arm1"],
            "parameter_sha256": "cbb14d878dfda5af816dbc4903c7fb811aabbcfb17ce494f00e994ab3d6b286a",
        }

    def eval_d_candidate(self, *, seed: int):
        self.calls += 1
        return _DCandidateOutput()


def _document(identity: dict) -> dict:
    """The registered production shape: 3510 updates, 450 s, arm1 at 2 s."""
    from ainerzero.v9.experiments.s1 import prereg

    smoke = fake_smoke(TRAIN_STEP)
    smoke["d_candidate"]["forward_loss_step_seconds"] = D_STEP
    document = prereg.build_frozen(
        prereg.build_draft(data_identity=identity, parameter_counts=FAKE_COUNTS),
        smoke=smoke,
        data_identity=identity,
        created_unix=1_000.0,
    )
    assert document["training_protocol"]["updates"] == UPDATES
    assert float(document["timing"]["arm1_deadline_seconds"]) == 2.0
    return document


def _eval_root(tmp_path, canonical_root, synthetic_dataset):
    manifest, dataset_dir, _plan = synthetic_dataset
    identity = data.dataset_identity(manifest)
    target = tmp_path / "datasets" / manifest["dataset_digest"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(dataset_dir, target)
    root = canonical_root
    data.write_dataset_ref(root, manifest, target)
    path, digest, _doc = write_frozen(root / "pre_registration.json", document=_document(identity))
    return root, path, digest


def _run_arm1(root, path, backend):
    return worker.run_worker(
        "eval",
        output_root=root,
        limits=spec.RESOURCE_LIMITS,
        # The CLI default eval budget: exactly what made r7's D run impossible.
        wall_budget_seconds=300.0,
        prereg_path=path,
        arm="arm1",
        seed=0,
        backend=backend,
    )


# --- F3 ------------------------------------------------------------------
def test_the_frozen_arm1_sub_run_completes_inside_its_2s_registration(
    tmp_path, monkeypatch, canonical_root, synthetic_dataset
):
    root, path, _digest = _eval_root(tmp_path, canonical_root, synthetic_dataset)
    backend = _DCpuBackend()

    report = _run_arm1(root, path, backend)

    assert report["status"] == "completed", report.get("message")
    assert backend.calls == 1, "the frozen D candidate is probed exactly once"
    assert report["eval_details"]["forward_substitute"] is True
    assert report["eval_details"]["d_candidate_identity"]["manifest_digest_match"] is True
    assert report["eval_details"]["incomparable"]

    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        run = ledger.get(report["run_id"])
    finally:
        ledger.close()
    assert run["state"] == "completed"
    budget = run["config_snapshot"]["budget"]
    assert float(budget["max_wall_seconds"]) == pytest.approx(2.0)
    # The single pre-work reservation fits inside the 2 s allowance: no 5 s floor
    # and no reservation made after the work.
    assert 0 < float(run["reserved_active_seconds"]) <= 2.0
    assert int(run["reserved_optimizer_steps"]) == 0
    assert run["config_snapshot"]["arm_id"] == "arm1"


def test_the_shared_experiment_admits_the_2s_d_run_and_the_450s_train_run():
    """The manifest is a stable ceiling, not a per-caller payload (F3)."""
    for_updates = worker.train_experiment_manifest(updates=UPDATES)
    assert for_updates == worker.train_experiment_manifest(updates=UPDATES, deadline_seconds=2.0)
    assert for_updates == worker.train_experiment_manifest(updates=UPDATES, deadline_seconds=450.0)
    ceiling = float(for_updates["experiment_budget"]["max_wall_seconds"])
    assert ceiling >= 450.0
    assert int(for_updates["experiment_budget"]["max_optimizer_steps"]) >= UPDATES


def test_a_2s_run_and_a_450s_run_coexist_in_one_experiment(tmp_path):
    """D-before-train and train-before-D must not fight over the experiment."""
    from ainerzero.runtime.lifecycle import RunStore

    db = tmp_path / "control.sqlite3"
    store = RunStore(db)
    try:
        manifest = worker.train_experiment_manifest(updates=UPDATES)
        experiment = store.create_experiment(
            manifest, f"{worker.TRAIN_EXPERIMENT_ID}:training", worker.TRAIN_EXPERIMENT_ID
        )
        for label, budget, steps in (("d", 2.0, 1), ("train", 450.0, UPDATES)):
            snapshot = worker.run_config_snapshot(
                wall_budget_seconds=budget, purpose=label, max_optimizer_steps=steps
            )
            snapshot["arm_id"] = "arm1" if label == "d" else "arm2"
            store.create_run(
                snapshot,
                f"{worker.TRAIN_EXPERIMENT_ID}:{label}",
                f"run-{label}",
                experiment_id=experiment.experiment_id,
                role="auxiliary" if label == "d" else "model",
            )
            # The store admits one active run per experiment: the D sub-run and
            # the training run are sequential, and neither resets the other's
            # attempt record or the shared experiment.
            store.transition(f"run-{label}", "initializing", reason="test")
            store.transition(f"run-{label}", "validating", reason="test")
            store.transition(f"run-{label}", "completed", reason="test")
        assert len(store.list_runs()) == 2
    finally:
        store.close()


# --- F4 ------------------------------------------------------------------
def test_a_second_d_evaluation_is_refused_on_the_product_created_row(
    tmp_path, monkeypatch, canonical_root, synthetic_dataset
):
    root, path, _digest = _eval_root(tmp_path, canonical_root, synthetic_dataset)
    first = _run_arm1(root, path, _DCpuBackend())
    assert first["status"] == "completed"

    second = _run_arm1(root, path, _DCpuBackend())

    assert second["status"] == "refused"
    assert second["refused_stage"] == "already_attempted"
    assert second["attempt_run_ids"] == [first["run_id"]]
    ledger = worker.PrepLedger(root / "control.sqlite3")
    try:
        arm1_rows = [
            run
            for run in ledger.store.list_runs()
            if (run.config_snapshot or {}).get("arm_id") == "arm1"
        ]
    finally:
        ledger.close()
    assert len(arm1_rows) == 1, "the guard must see the row the product itself wrote"


def test_an_older_d_looking_row_without_arm_id_fails_closed(tmp_path):
    """A legacy row that may be a D attempt is refused, never auto-repaired."""
    from ainerzero.runtime.lifecycle import RunStore

    store = RunStore(tmp_path / "control.sqlite3")
    try:
        experiment = store.create_experiment(
            worker.train_experiment_manifest(updates=UPDATES),
            f"{worker.TRAIN_EXPERIMENT_ID}:training",
            worker.TRAIN_EXPERIMENT_ID,
        )
        snapshot = worker.run_config_snapshot(
            wall_budget_seconds=2.0, purpose="s1_phase1_d_candidate_eval:arm1"
        )
        store.create_run(
            snapshot, "legacy", "run-legacy", experiment_id=experiment.experiment_id,
            role="auxiliary",
        )
        store.transition("run-legacy", "initializing", reason="legacy")
        store.transition("run-legacy", "validating", reason="legacy")
        state = worker.d_candidate_attempt_state(store.list_runs())
    finally:
        store.close()
    assert state["status"] == "unidentifiable"
    assert state["run_ids"] == ["run-legacy"]


def test_a_row_with_another_arm_id_is_not_mistaken_for_a_d_attempt(tmp_path):
    from ainerzero.runtime.lifecycle import RunStore

    store = RunStore(tmp_path / "control.sqlite3")
    try:
        experiment = store.create_experiment(
            worker.train_experiment_manifest(updates=UPDATES),
            f"{worker.TRAIN_EXPERIMENT_ID}:training",
            worker.TRAIN_EXPERIMENT_ID,
        )
        snapshot = worker.run_config_snapshot(wall_budget_seconds=300.0, purpose="s1_phase1_eval:arm2")
        snapshot["arm_id"] = "arm2"
        store.create_run(
            snapshot, "other", "run-other", experiment_id=experiment.experiment_id, role="auxiliary"
        )
        store.transition("run-other", "initializing", reason="x")
        store.transition("run-other", "validating", reason="x")
        state = worker.d_candidate_attempt_state(store.list_runs())
    finally:
        store.close()
    assert state["status"] == "ok"


def test_an_unstarted_d_row_does_not_block_the_first_run(tmp_path):
    from ainerzero.runtime.lifecycle import RunStore

    store = RunStore(tmp_path / "control.sqlite3")
    try:
        experiment = store.create_experiment(
            worker.train_experiment_manifest(updates=UPDATES),
            f"{worker.TRAIN_EXPERIMENT_ID}:training",
            worker.TRAIN_EXPERIMENT_ID,
        )
        snapshot = worker.run_config_snapshot(wall_budget_seconds=2.0, purpose="d")
        snapshot["arm_id"] = "arm1"
        store.create_run(
            snapshot, "created-only", "run-created", experiment_id=experiment.experiment_id,
            role="auxiliary",
        )
        state = worker.d_candidate_attempt_state(store.list_runs())
    finally:
        store.close()
    assert state["status"] == "ok", "a row that never started is not an attempt"
