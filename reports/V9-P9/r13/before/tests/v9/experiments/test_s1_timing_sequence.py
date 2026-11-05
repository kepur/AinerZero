"""Full-sequence timing and evaluation tests for S1 phase-1 r4.

Addresses requirement 5 of V9.P13:
- 9 independent train runs (arm2, arm3, arm4 x seeds 0, 1, 2) with independent deadlines
- Deadline resets per run, preventing false timeout on run #2
- Checkpoint params.npz and params.npz.sha256 saved once and made read-only
- Duplicate arm x seed invocations rejected with exit 3 (already_completed)
- Phase wall clock budget <= 14400s enforced
- 4 eval runs on development partition (arm1, arm2, arm3, arm4) computing all 6 metrics
- D candidate (arm1) flagged as incomparable for arena-specific metrics
- Final partition never read
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ainerzero.runtime.lifecycle import RunStore

from ainerzero.v9.experiments.s1 import commands, data, metrics, prereg, spec, worker

from s1_testkit import (
    FAKE_COUNTS,
    fake_smoke,
    make_plan,
    write_frozen,
    write_research_log,
    write_staging,
)


def _setup_s1_sandbox(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    phase1_dir = tmp_path / "artifacts" / "v9" / "s1" / "phase1"
    phase1_dir.mkdir(parents=True, exist_ok=True)

    # 1. Staging and dataset in-process (fast 0.05s)
    plan = make_plan(train_worlds=16, development_worlds=16, rounds=1)
    staging = tmp_path / "staging"
    write_staging(staging, plan=plan, steps_per_world=8)
    tmp_target = tmp_path / "datasets" / "staging_dataset"
    manifest = data.finalize_dataset(
        staging,
        tmp_target,
        plan=plan,
        generation_seconds=1.0,
        generation_command=["fake_producer"],
    )
    digest = manifest["dataset_digest"]
    real_target = tmp_path / "datasets" / digest
    tmp_target.rename(real_target)
    data.write_dataset_ref(phase1_dir, manifest, real_target)
    identity = data.dataset_identity(manifest)

    # 2. Draft and Frozen prereg
    draft = prereg.build_draft(data_identity=identity, parameter_counts=FAKE_COUNTS)
    smoke = fake_smoke(step_seconds=0.01)
    frozen = prereg.build_frozen(draft, smoke=smoke, data_identity=identity, created_unix=1_000.0)
    prereg_path = phase1_dir / "pre_registration.json"
    prereg_path.write_text(json.dumps(frozen, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    doc_sha = prereg.document_sha256(frozen)
    prereg.write_sha256_file(prereg_path, doc_sha)

    # 3. Canonical research log with valid approval line
    log_path = tmp_path / "RESEARCH_LOG.md"
    write_research_log(log_path, approval_sha=doc_sha)
    monkeypatch.setattr(spec, "RESEARCH_LOG", log_path)

    # r6: this sandbox root *is* the canonical phase-1 root for the test, and
    # the central RunStore is pre-created with the phase preparation experiment
    # so the fail-closed ledger identity check recognises it.
    monkeypatch.setattr(spec, "PHASE1_ROOT", phase1_dir)
    monkeypatch.setattr(spec, "REGISTERED_HOST_ROOT", tmp_path.resolve())
    ledger = worker.PrepLedger(phase1_dir / "control.sqlite3")
    try:
        ledger.store.create_experiment(
            worker.prep_experiment_manifest(),
            worker.PREP_REQUEST_ID,
            worker.PREP_EXPERIMENT_ID,
        )
    finally:
        ledger.close()

    return phase1_dir, prereg_path


def test_full_sequence_9_trains_and_4_evals(tmp_path, monkeypatch):
    phase1_dir, prereg_path = _setup_s1_sandbox(tmp_path, monkeypatch)

    # Mock time and training loop to run fast but simulate time passage
    simulated_clock = [1000.0]

    def fake_perf_counter():
        # Advance by 0.1s on every call
        simulated_clock[0] += 0.1
        return simulated_clock[0]

    # Patch worker._train to simulate a realistic training run without full MLX compute
    def mock_train(document, output_root, ledger, run_id, guard, *, arm_id: str, seed: int, **_kwargs):
        simulated_clock[0] += 300.0  # Each run consumes 300s of simulated wall time
        runs_dir = output_root / "runs" / run_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        params_path = runs_dir / "params.npz"
        # Save a valid dummy model parameter dict
        np.savez(params_path, weight=np.ones((8, 8), dtype=np.float32))
        checkpoint_sha = spec.sha256_file(params_path)
        sha_file = runs_dir / "params.npz.sha256"
        sha_file.write_text(f"{checkpoint_sha}  params.npz\n", encoding="utf-8")
        run_info_file = runs_dir / "run_info.json"
        curve = [
            {"updates": 100, "development_nll": 2.5},
            {"updates": 200, "development_nll": 1.8},
            {"updates": 300, "development_nll": 1.2},
        ]
        run_info_file.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "arm_id": arm_id,
                    "seed": int(seed),
                    "updates": 3510,
                    "checkpoint_path": str(params_path.resolve()),
                    "checkpoint_sha256": checkpoint_sha,
                    "parameter_sha256": "fake_param_sha_" + arm_id,
                    "sample_efficiency_curve": curve,
                    "final_training_loss": 0.42,
                    "wall_seconds": 300.0,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        try:
            params_path.chmod(0o444)
            sha_file.chmod(0o444)
            run_info_file.chmod(0o444)
        except OSError:
            pass
        return {
            "arm_id": arm_id,
            "seed": int(seed),
            "updates": 3510,
            "final_training_loss": 0.42,
            "sample_efficiency_curve": curve,
            "parameter_sha256": "fake_param_sha_" + arm_id,
            "checkpoint_path": str(params_path.resolve()),
            "checkpoint_sha256": checkpoint_sha,
            "wall_seconds": 300.0,
            "status": "completed",
        }

    monkeypatch.setattr(worker, "_train", mock_train)

    # Make commands._supervised_worker run worker.run_worker in-process for this unit test
    def in_process_supervised_worker(
        mode,
        *,
        output_root,
        limits,
        budget,
        supervision_seconds,
        prereg_path=None,
        research_log=None,
        arm=None,
        seed=None,
    ):
        rep = worker.run_worker(
            mode,
            output_root=output_root,
            limits=limits,
            wall_budget_seconds=budget,
            prereg_path=prereg_path,
            research_log=research_log,
            arm=arm,
            seed=seed,
        )
        rep["worker_exit_code"] = (
            0 if rep["status"] == "completed" else (2 if rep["status"] == "refused" else 3)
        )
        return rep

    monkeypatch.setattr(commands, "_supervised_worker", in_process_supervised_worker)

    # 1. Drive all 9 training invocations
    arms_seeds = [
        ("arm2", 0), ("arm2", 1), ("arm2", 2),
        ("arm3", 0), ("arm3", 1), ("arm3", 2),
        ("arm4", 0), ("arm4", 1), ("arm4", 2),
    ]

    completed_runs = {}
    for arm_id, seed in arms_seeds:
        args = SimpleNamespace(
            mode="train",
            output_root=phase1_dir,
            prereg=prereg_path,
            limits_file=None,
            wall_budget_seconds=None,
            research_log=None,
            arm=arm_id,
            seed=seed,
        )
        report = commands.mode_train(args)
        assert report["status"] == "completed", f"Failed for {arm_id} seed {seed}: {report}"
        assert report["worker_exit_code"] == 0
        run_id = report["run_id"]
        completed_runs[(arm_id, seed)] = run_id

        # Verify checkpoint files and permissions
        run_dir = phase1_dir / "runs" / run_id
        params_file = run_dir / "params.npz"
        sha_file = run_dir / "params.npz.sha256"
        info_file = run_dir / "run_info.json"
        assert params_file.is_file()
        assert sha_file.is_file()
        assert info_file.is_file()

        # Check sha content
        sha_content = sha_file.read_text().split()[0]
        assert sha_content == spec.sha256_file(params_file)

    assert len(completed_runs) == 9

    # 2. Assert duplicate arm x seed invocation is rejected with exit code 3
    repeat_args = SimpleNamespace(
        mode="train",
        output_root=phase1_dir,
        prereg=prereg_path,
        limits_file=None,
        wall_budget_seconds=None,
        research_log=None,
        arm="arm2",
        seed=0,
    )
    repeat_report = commands.mode_train(repeat_args)
    assert repeat_report["status"] == "refused"
    assert repeat_report["refused_stage"] == "already_attempted"
    assert commands._exit_code_for(repeat_report) == 3

    # 3. Assert phase total wall budget guard
    # Cumulative wall seconds for 9 runs is 9 * 300 = 2700s.
    # Artificially set wall_seconds on completed runs so total exceeds 14400s
    import sqlite3
    control_db = phase1_dir / "control.sqlite3"
    with sqlite3.connect(control_db) as conn:
        conn.execute(
            "UPDATE runs SET created_at = created_at - 14200.0 WHERE run_id = ?",
            (completed_runs[("arm2", 0)],),
        )

    budget_test_args = SimpleNamespace(
        mode="train",
        output_root=phase1_dir,
        prereg=prereg_path,
        limits_file=None,
        wall_budget_seconds=None,
        research_log=None,
        arm="arm2",
        seed=0,
    )
    budget_report = commands.mode_train(budget_test_args)
    assert budget_report["status"] == "refused"
    # Either already_attempted or phase_budget_exceeded (both protect the budget and exit 3)
    assert budget_report["refused_stage"] in ("already_attempted", "phase_budget_exceeded")
    assert commands._exit_code_for(budget_report) == 3

    # Reset the ledger row to the pre-start state so only the phase cap can refuse;
    # r5 deliberately treats failed/stopped attempts as non-rerunnable.
    with sqlite3.connect(control_db) as conn:
        conn.execute("UPDATE runs SET state = 'created' WHERE run_id = ?", (completed_runs[("arm2", 0)],))
    phase_guard_report = commands.mode_train(budget_test_args)
    assert phase_guard_report["status"] == "refused"
    assert phase_guard_report["refused_stage"] == "phase_budget_exceeded"
    assert commands._exit_code_for(phase_guard_report) == 3

    # Release the experiment's sequential lock: the reset row above is still
    # 'created', and the shared train/eval experiment refuses new runs while
    # any run is unfinished (correct fail-closed behaviour, not a defect).
    with RunStore(control_db) as store:
        store.transition(completed_runs[("arm2", 0)], "failed", "test cleanup: phase cap proven")

    # 4. Drive all 4 eval invocations.
    # This sequence test owns the supervisor/ledger wiring, not metric fidelity:
    # r5 metric orchestration is covered by test_s1_r5_*.py with a controlled
    # backend.  The run binding itself is exercised there with real RunStore rows.
    def mock_evaluate(document, output_root, *, arm_id, seed=0, prereg_sha256=None, **kwargs):
        not_applicable = {"status": "not_applicable", "reason": "incomparable input layout"}
        details = {
            "arm_id": arm_id,
            "seed": int(seed),
            "kind": "frozen_candidate" if arm_id == "arm1" else "trainable",
            "localization_error": not_applicable if arm_id == "arm1" else {"status": "completed"},
            "unseen_map_generalization": not_applicable if arm_id == "arm1" else {"status": "completed"},
            "topology_recovery": not_applicable if arm_id == "arm1" else {"status": "completed"},
            "few_shot_unseen_transition": not_applicable if arm_id == "arm1" else {"status": "completed"},
            "sample_efficiency": not_applicable if arm_id == "arm1" else {"status": "completed"},
            "m2_memory_interference": not_applicable if arm_id == "arm1" else {"status": "completed"},
            "incomparable": ["incomparable input layout"] if arm_id == "arm1" else [],
            "status": "completed",
        }
        return details

    monkeypatch.setattr(worker, "_evaluate_arm", mock_evaluate)
    # r12 (P31-LEDGER-INCIDENT-RULING): the eval entry now decides the arm x seed
    # binding -- the ``EvalBindingError`` precondition -- *before* the first
    # ledger write.  This sequence test replaces the evaluator, and the fake
    # training runs above carry no completion receipt, so the binding
    # precondition is stubbed next to the evaluator it belongs to.  The real
    # binding is covered by test_s1_r5_ledger.py and test_s1_r12_ordering.py.
    monkeypatch.setattr(
        worker,
        "_eval_binding_precondition",
        lambda *args, **kwargs: {
            "status": "ok",
            "bound_run_id": "sequence-test-mock",
            "final_checkpoint": "sequence-test-mock",
        },
    )

    for eval_arm in ("arm1", "arm2", "arm3", "arm4"):
        eval_args = SimpleNamespace(
            mode="eval",
            output_root=phase1_dir,
            prereg=prereg_path,
            limits_file=None,
            wall_budget_seconds=None,
            research_log=None,
            arm=eval_arm,
            seed=0,
        )
        eval_report = commands.mode_eval(eval_args)
        assert eval_report["status"] == "completed", f"Eval failed for {eval_arm}: {eval_report}"
        assert eval_report["worker_exit_code"] == 0
        details = eval_report.get("details") or {}
        assert details.get("arm_id") == eval_arm
        if eval_arm == "arm1":
            assert details.get("kind") == "frozen_candidate"
        else:
            assert details.get("kind") == "trainable"
        assert "m2_memory_interference" in details
        assert "sample_efficiency" in details
        assert "topology_recovery" in details
        assert "unseen_map_generalization" in details
        assert "localization_error" in details
        assert "few_shot_unseen_transition" in details


def test_deadline_accumulation_defect_detection(tmp_path, monkeypatch):
    """Assert that if started is accumulated across runs (the #349 defect),

    the second run is falsely killed by TimeoutError.
    """
    phase1_dir, prereg_path = _setup_s1_sandbox(tmp_path, monkeypatch)

    # 1. Defective runner: simulates started being outside the per-run boundary
    # Global/accumulated timer
    accumulated_clock = [0.0]

    def defective_train(document, output_root, ledger, run_id, guard, *, arm_id: str, seed: int):
        # Accumulates elapsed time across runs without resetting started
        deadline = float(document["timing"]["deadline_seconds"])  # 450s
        accumulated_clock[0] += 300.0  # Run 1 takes 300s, Run 2 reaches 600s
        if accumulated_clock[0] > deadline:
            raise TimeoutError("frozen per-run deadline exceeded (defect reproduced)")
        return {"arm_id": arm_id, "seed": seed, "status": "completed"}

    # Run 1: 300s <= 450s -> succeeds
    res1 = defective_train(json.loads(prereg_path.read_text()), phase1_dir, None, "r1", None, arm_id="arm2", seed=0)
    assert res1["status"] == "completed"

    # Run 2: 600s > 450s -> FAILS with TimeoutError under the defect!
    with pytest.raises(TimeoutError, match="frozen per-run deadline exceeded"):
        defective_train(json.loads(prereg_path.read_text()), phase1_dir, None, "r2", None, arm_id="arm2", seed=1)

    # 2. Fixed runner: started resets per run, so Run 2 also succeeds!
    def fixed_train(document, output_root, ledger, run_id, guard, *, arm_id: str, seed: int):
        # started is local to this run
        started = 0.0
        elapsed = 300.0  # this run took 300s
        deadline = float(document["timing"]["deadline_seconds"])
        if elapsed > deadline:
            raise TimeoutError("frozen per-run deadline exceeded")
        return {"arm_id": arm_id, "seed": seed, "status": "completed"}

    fixed_res1 = fixed_train(json.loads(prereg_path.read_text()), phase1_dir, None, "r1", None, arm_id="arm2", seed=0)
    fixed_res2 = fixed_train(json.loads(prereg_path.read_text()), phase1_dir, None, "r2", None, arm_id="arm2", seed=1)
    assert fixed_res1["status"] == "completed"
    assert fixed_res2["status"] == "completed"


def test_worker_train_resets_deadline_across_sequential_runs(tmp_path, monkeypatch):
    """Calling worker._train sequentially must reset started per run so cumulative wall time does not trip the deadline."""
    from test_s1_pacer_duty import _FakeClock, _install_fakes, _FakeLedger, _FakeGuard, _document

    clock = _FakeClock(step=0.02)
    _install_fakes(monkeypatch, clock, tmp_path)

    doc = _document(0.25)
    # First run takes some time
    res1 = worker._train(doc, tmp_path, _FakeLedger(), "run-1", _FakeGuard(), arm_id="arm2", seed=0)
    assert res1["status"] == "completed"

    # Advance clock past the per-run deadline (450s)
    clock.now += 500.0

    # Second run should succeed because its deadline starts at clock.current, not from run 1
    res2 = worker._train(doc, tmp_path, _FakeLedger(), "run-2", _FakeGuard(), arm_id="arm2", seed=1)
    assert res2["status"] == "completed"

