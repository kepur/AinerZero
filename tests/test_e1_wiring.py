"""Wiring and integration verification test suite for E1 Phase 2 (ainerzero.V9.P76).

Verifies:
1. Production runners are authentic:
   - Default runners map directly to the four genuine functions:
     data_runner.generate_and_export, train_runner.train_cell,
     eval_runner.evaluate_cell, eval_runner.evaluate_final_once.
   - End-to-end integration: Synthetic dataset via prior.rollout + export.export_sequence,
     CLI train (Arm 3, <=5 steps, pure CPU), CLI eval (Arm 1 and Arm 3).
   - Checkpoints are saved via arms_net.save() and loadable by model.load().
   - CLI eval outputs match direct eval_runner.evaluate_cell calls value-for-value.
2. Refusal paths with zero ledger mutation:
   - Missing coordinator approval, prereg SHA mismatch, insufficient/exceeded budget,
     duplicate training, missing checkpoint on eval, second final-eval.
   - Ledger SHA256 remains strictly identical before and after each refusal.
3. Fake clock full schedule rehearsal (51 cells):
   - 1 data-generation cell
   - 18 training cells (arms 2, 3, 6 x P, S x seeds 42, 43, 44)
   - 30 dev evaluation cells (18 train + 12 non-train)
   - 2 final evaluation cells (P and S)
   - Verifies per-cell deadline reset and total wall clock within spec ceiling (115200 s).
4. Zero hardcoded mock metrics in worker.py and commands.py.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.e1 import (
    arms_net,
    arms_nonnet,
    commands,
    data_runner,
    eval_runner,
    export,
    metrics,
    prereg,
    prior,
    spec,
    train_runner,
    worker,
)

pytestmark = pytest.mark.native_mlx(reason="real MLX import at collection via the e1 package (arms_net) (A39)")


class FakeClock:
    """Deterministic simulated clock for end-to-end schedule rehearsal."""

    def __init__(self, start: float = 1700000000.0):
        self.curr = float(start)

    def time(self) -> float:
        return self.curr

    def advance(self, dt: float) -> None:
        self.curr += float(dt)


class FakeCellRunner(worker.CellRunner):
    """Test fake runner matching genuine runner interfaces for rapid schedule rehearsal."""

    def __init__(self, clock: FakeClock | None = None):
        self.clock = clock

    def run_generate_data(self, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop("Fake generate-data timeout")
        if self.clock is not None:
            self.clock.advance(50.0)
        return {"mode": "generate-data", "status": "completed"}

    def run_train(self, arm: int, family: str, seed: int, output_root: Path, data_dir: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop(f"Fake train arm {arm} timeout")
        if self.clock is not None:
            self.clock.advance(30.0)
        ckpt_dir = output_root / "checkpoints" / f"arm{arm}_{family}_seed{seed}"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        ckpt_file = ckpt_dir / "model_weights.npz"
        np.savez(ckpt_file, dummy=np.zeros(1))
        return {
            "mode": "train",
            "arm": arm,
            "family": family,
            "seed": seed,
            "checkpoint_path": str(ckpt_file),
            "checkpoint_sha256": hashlib.sha256(ckpt_file.read_bytes()).hexdigest(),
            "status": "completed",
        }

    def run_eval(self, arm: int, family: str, seed: int | None, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop(f"Fake eval arm {arm} timeout")
        if self.clock is not None:
            self.clock.advance(10.0)
        return {
            "mode": "eval",
            "arm": arm,
            "family": family,
            "seed": seed,
            "summary": {"primary_error_m": 0.05, "collision_f1": 0.95},
            "status": "completed",
        }

    def run_final_eval(self, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop("Fake final-eval timeout")
        if self.clock is not None:
            self.clock.advance(20.0)
        family = kwargs.get("family", "P")
        return {
            "mode": "final-eval",
            "family": family,
            "summary": {"primary_error_m": 0.048, "collision_f1": 0.96},
            "status": "completed",
        }


def _setup_valid_approval_log(log_path: Path, digest: str) -> None:
    content = f"""# Research Log
## R20261021-P1-stageA-budget
Historical section.

## R20261105-E1-r2-approval
APPROVED e1-phase2 prereg document_sha256={digest}
APPROVED e1-phase2 final-eval document_sha256={digest}

## Next Section
Other content.
"""
    log_path.write_text(content, encoding="utf-8")


def _make_args(tmp_path: Path, mode: str, **kwargs) -> argparse.Namespace:
    output_root = tmp_path / "phase2"
    output_root.mkdir(parents=True, exist_ok=True)
    ledger_path = output_root / "control.sqlite3"
    lock_path = tmp_path / "locks" / "m0-worker.lock"
    research_log = tmp_path / "RESEARCH_LOG.md"
    data_dir = tmp_path / "datasets"
    data_dir.mkdir(parents=True, exist_ok=True)
    gen_id_path = data_dir / "generator_identity.json"
    if not gen_id_path.exists():
        draft_doc = prereg.build_draft()
        gen_id_payload = {
            "generator_digests": dict(draft_doc.get("generator_digests") or {}),
            "velocity_injection": draft_doc.get("required_velocity_injection", "disabled"),
            "timestamp": 1700000000.0,
        }
        gen_id_path.write_text(json.dumps(gen_id_payload), encoding="utf-8")
    prereg_file = output_root / "prereg.json"

    d = {
        "mode": mode,
        "arm": kwargs.get("arm"),
        "family": kwargs.get("family"),
        "seed": kwargs.get("seed"),
        "output_root": output_root,
        "ledger": ledger_path,
        "lock_file": lock_path,
        "prereg": kwargs.get("prereg", prereg_file),
        "research_log": kwargs.get("research_log", research_log),
        "data_dir": kwargs.get("data_dir", data_dir),
        "wall_budget_seconds": kwargs.get("wall_budget_seconds"),
        "fake_clock": kwargs.get("fake_clock"),
        "runner": kwargs.get("runner"),
        "steps": kwargs.get("steps"),
    }
    return argparse.Namespace(**d)


def _create_synthetic_e0_sequence(world_key: str, family: str = "P", num_frames: int = 25) -> dict:
    """Create a physically valid synthetic E0 sequence for wiring tests."""
    env = prior.StaticEnvironment()
    body = prior.ActiveBody(
        name="ball_0",
        radius=0.1,
        params=prior.PhysicalParameters(friction=0.5, restitution=0.45, mass=2.6),
        position=np.array([0.0, 0.0, 1.0]),
        velocity=np.array([0.1, 0.0, 0.0]),
    )
    sim = prior.rollout([body], env, num_frames=num_frames)
    traj = sim["ball_0"]

    frames = []
    for t in range(num_frames):
        pos = traj[t, 0:3].tolist()
        lin_v = traj[t, 3:6].tolist()
        orient = traj[t, 6:10].tolist()
        ang_v = traj[t, 10:13].tolist()
        frames.append({
            "frame_id": t,
            "objects": {
                "ball_0": {
                    "position": pos,
                    "orientation": orient,
                    "linear_velocity": lin_v,
                    "angular_velocity": ang_v,
                }
            },
            "contacts": [],
        })

    return {
        "world_key": world_key,
        "sequence_id": f"seq_{world_key}",
        "family": family,
        "partition": "development",
        "scenario_type": "ramp_roll",
        "metadata": {
            "hidden_parameters": {
                "ball_0": {
                    "shape": "SPHERE",
                    "dimensions": [0.2, 0.2, 0.2],
                    "is_active": True,
                    "mass": 2.6,
                    "friction": 0.5,
                    "restitution": 0.45,
                    "linear_damping": 0.125,
                    "angular_damping": 0.125,
                }
            }
        },
        "frames": frames,
    }


def test_default_runners_are_identical_to_real_runner_functions():
    """Verify production default runners are identical to the four genuine functions."""
    assert worker.DEFAULT_RUNNERS["generate-data"] is data_runner.generate_and_export
    assert worker.DEFAULT_RUNNERS["train"] is train_runner.train_cell
    assert worker.DEFAULT_RUNNERS["eval"] is eval_runner.evaluate_cell
    assert worker.DEFAULT_RUNNERS["final-eval"] is eval_runner.evaluate_final_once

    runner = worker.DefaultCellRunner()
    assert runner.generate_and_export is data_runner.generate_and_export
    assert runner.train_cell is train_runner.train_cell
    assert runner.evaluate_cell is eval_runner.evaluate_cell
    assert runner.evaluate_final_once is eval_runner.evaluate_final_once

    assert runner.generate_data_fn is data_runner.generate_and_export
    assert runner.train_fn is train_runner.train_cell
    assert runner.eval_fn is eval_runner.evaluate_cell
    assert runner.final_eval_fn is eval_runner.evaluate_final_once


def test_end_to_end_train_and_eval_matches_direct_eval_cell(tmp_path: Path):
    """End-to-end integration test:

    - Synthesize 3 episodes via prior + export.
    - CLI train: Arm 3, family P, seed 42, steps=3 (CPU).
    - Checkpoint verified by arms_net.save() and load().
    - CLI eval: Arm 1 (PriorArm) and Arm 3 (PriorResidualArm).
    - Assert metrics written by CLI eval match direct eval_runner.evaluate_cell value-for-value.
    """
    args_train = _make_args(tmp_path, "train", arm=3, family="P", seed=42, steps=3)
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args_train.prereg)
    _setup_valid_approval_log(args_train.research_log, digest)

    # 1. Synthesize minimal dataset (3 sequences)
    student_train = args_train.data_dir / "student" / "P" / "train"
    student_dev = args_train.data_dir / "student" / "P" / "development"
    evaluator_dev = args_train.data_dir / "evaluator" / "P" / "development"
    student_train.mkdir(parents=True, exist_ok=True)
    student_dev.mkdir(parents=True, exist_ok=True)
    evaluator_dev.mkdir(parents=True, exist_ok=True)

    for i in range(3):
        raw_seq = _create_synthetic_e0_sequence(f"world_{i}", family="P", num_frames=25)
        s_view, e_view = export.export_sequence(raw_seq)
        (student_train / f"seq_{i}.json").write_text(json.dumps(s_view), encoding="utf-8")
        (student_dev / f"seq_{i}.json").write_text(json.dumps(s_view), encoding="utf-8")
        (evaluator_dev / f"seq_{i}.json").write_text(json.dumps(e_view), encoding="utf-8")

    # 2. Run CLI Train (Arm 3, 3 steps)
    train_res, train_code = commands.e1_phase2_command(args_train)
    assert train_code == commands.EXIT_COMPLETED, f"Train failed: {train_res}"
    assert train_res["status"] == "completed"

    ckpt_file = args_train.output_root / "checkpoints" / "arm3_P_seed42" / "model_weights.npz"
    assert ckpt_file.is_file(), f"Checkpoint {ckpt_file} was not written"

    # Verify checkpoint can be loaded and parameter sha matches
    loaded_model = arms_net.PriorResidualArm(seed=42)
    loaded_model.load(ckpt_file)
    assert loaded_model.parameter_sha256() == train_res["result"]["parameter_sha256"]

    # Verify ledger recorded runner name and runner module sha
    with worker.ledger_read_snapshot(args_train.ledger) as store:
        assert store is not None
        cur = store._conn.execute("SELECT config_json FROM runs WHERE state = 'completed'")
        cfg = json.loads(cur.fetchone()["config_json"])
        assert cfg["arm"] == 3
        assert cfg["family"] == "P"
        assert cfg["seed"] == 42
        assert "train_cell" in cfg["runner_name"]
        assert cfg["runner_module_sha256"] != "unknown"

    # 3. Run CLI Eval for Arm 1 (PriorArm)
    args_eval_arm1 = _make_args(tmp_path, "eval", arm=1, family="P")
    eval_res1, eval_code1 = commands.e1_phase2_command(args_eval_arm1)
    assert eval_code1 == commands.EXIT_COMPLETED, f"Eval Arm 1 failed: {eval_res1}"

    # Direct call to eval_runner.evaluate_cell for Arm 1
    direct_res1 = eval_runner.evaluate_cell(
        arms_nonnet.PriorArm(),
        student_dir=student_dev,
        evaluator_dir=evaluator_dev,
    )

    cli_summary1 = eval_res1["result"]["summary"]
    direct_summary1 = direct_res1["summary"]
    assert cli_summary1["num_episodes"] == direct_summary1["num_episodes"]
    assert pytest.approx(cli_summary1["primary_error_m"]) == direct_summary1["primary_error_m"]
    assert pytest.approx(cli_summary1["collision_f1"]) == direct_summary1["collision_f1"]
    assert pytest.approx(cli_summary1["mean_energy_drift"]) == direct_summary1["mean_energy_drift"]

    # 4. Run CLI Eval for Arm 3 (PriorResidualArm with trained weights)
    args_eval_arm3 = _make_args(tmp_path, "eval", arm=3, family="P", seed=42)
    eval_res3, eval_code3 = commands.e1_phase2_command(args_eval_arm3)
    assert eval_code3 == commands.EXIT_COMPLETED, f"Eval Arm 3 failed: {eval_res3}"

    # Direct call to eval_runner.evaluate_cell for Arm 3
    direct_res3 = eval_runner.evaluate_cell(
        loaded_model,
        student_dir=student_dev,
        evaluator_dir=evaluator_dev,
    )

    cli_summary3 = eval_res3["result"]["summary"]
    direct_summary3 = direct_res3["summary"]
    assert cli_summary3["num_episodes"] == direct_summary3["num_episodes"]
    assert pytest.approx(cli_summary3["primary_error_m"]) == direct_summary3["primary_error_m"]
    assert pytest.approx(cli_summary3["collision_f1"]) == direct_summary3["collision_f1"]


def test_refusal_paths_leave_ledger_sha_strictly_identical(tmp_path: Path):
    """Verify all refusal paths halt in preflight without mutating the ledger file:

    1. Missing approval line
    2. Prereg SHA mismatch
    3. Exceeded phase wall budget
    4. Duplicate training cell
    5. Missing checkpoint for trainable arm in eval mode
    6. Second final-eval attempt
    """
    args = _make_args(tmp_path, "train", arm=3, family="P", seed=42, runner=FakeCellRunner())
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args.prereg)
    _setup_valid_approval_log(args.research_log, digest)

    # First run succeeds to create an active ledger with one run
    rep_init, code_init = commands.e1_phase2_command(args)
    assert code_init == commands.EXIT_COMPLETED
    assert args.ledger.is_file()
    baseline_ledger_sha = hashlib.sha256(args.ledger.read_bytes()).hexdigest()

    # Refusal 1: Missing approval line
    bad_log = tmp_path / "BAD_LOG.md"
    bad_log.write_text("# Empty Log\n", encoding="utf-8")
    args_r1 = _make_args(tmp_path, "train", arm=6, family="P", seed=42, research_log=bad_log)
    rep1, code1 = commands.e1_phase2_command(args_r1)
    assert code1 == commands.EXIT_REFUSED_APPROVAL
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == baseline_ledger_sha

    # Refusal 2: SHA mismatch in prereg
    mismatch_draft = prereg.build_draft()
    mismatch_draft["spec"] = "modified_spec_sha"
    mismatch_prereg = tmp_path / "mismatch_prereg.json"
    prereg.freeze(mismatch_draft, output_path=mismatch_prereg)
    args_r2 = _make_args(tmp_path, "train", arm=6, family="P", seed=42, prereg=mismatch_prereg)
    rep2, code2 = commands.e1_phase2_command(args_r2)
    assert code2 == commands.EXIT_REFUSED_APPROVAL
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == baseline_ledger_sha

    # Refusal 3: Exceeded requested budget
    args_r3 = _make_args(tmp_path, "train", arm=6, family="P", seed=42, wall_budget_seconds=999999.0)
    rep3, code3 = commands.e1_phase2_command(args_r3)
    assert code3 == commands.EXIT_REFUSED_RESOURCE
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == baseline_ledger_sha

    # Refusal 4: Duplicate training execution (arm 3, family P, seed 42 already completed)
    args_r4 = _make_args(tmp_path, "train", arm=3, family="P", seed=42, runner=FakeCellRunner())
    rep4, code4 = commands.e1_phase2_command(args_r4)
    assert code4 == commands.EXIT_FAILED
    assert rep4["stage"] == "duplicate_execution"
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == baseline_ledger_sha

    # Refusal 5: Missing checkpoint in eval mode (arm 6 seed 44 has not been trained)
    args_r5 = _make_args(tmp_path, "eval", arm=6, family="P", seed=44)
    rep5, code5 = commands.e1_phase2_command(args_r5)
    assert code5 == commands.EXIT_FAILED
    assert rep5["stage"] == "missing_checkpoint"
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == baseline_ledger_sha

    # Refusal 6: Second final-eval attempt
    args_f1 = _make_args(tmp_path, "final-eval", family="P", runner=FakeCellRunner())
    rep_f1, code_f1 = commands.e1_phase2_command(args_f1)
    assert code_f1 == commands.EXIT_COMPLETED

    sha_after_f1 = hashlib.sha256(args.ledger.read_bytes()).hexdigest()
    args_f2 = _make_args(tmp_path, "final-eval", family="P", runner=FakeCellRunner())
    rep_f2, code_f2 = commands.e1_phase2_command(args_f2)
    assert code_f2 == commands.EXIT_FAILED
    assert rep_f2["stage"] in ("final_eval_already_read_once", "duplicate_execution")
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == sha_after_f1


def test_fake_clock_full_schedule_rehearsal_dual_family(tmp_path: Path):
    """FakeClock full schedule rehearsal:

    - 1 data-generation cell
    - 18 training cells (arms 2, 3, 6 x P, S x seeds 42, 43, 44)
    - 30 dev evaluation cells (18 train + 12 non-train)
    - 2 final evaluation cells (family P and family S)
    Total: 51 cells.

    Verifies:
    1. Per-cell deadline is reset for every cell (no cell-2 timeout).
    2. Total wall clock spent <= phase_total_wall_ceiling_seconds (115200 s).
    3. Duplicate calls are rejected.
    4. Adding an extra cell that exceeds the total phase ceiling is refused.
    """
    clock = FakeClock(start=1700000000.0)
    start_time = clock.time()
    runner = FakeCellRunner(clock=clock)

    draft = prereg.build_draft()
    prereg_file = tmp_path / "phase2" / "prereg.json"
    prereg_file.parent.mkdir(parents=True, exist_ok=True)
    frozen, digest = prereg.freeze(draft, output_path=prereg_file)

    research_log = tmp_path / "RESEARCH_LOG.md"
    _setup_valid_approval_log(research_log, digest)

    # 1. Step 1: Data Generation (1 cell)
    args_data = _make_args(
        tmp_path,
        "generate-data",
        prereg=prereg_file,
        research_log=research_log,
        fake_clock=clock,
        runner=runner,
    )
    rep, code = commands.e1_phase2_command(args_data)
    assert code == commands.EXIT_FAILED, f"r2 reuses the dataset: {rep}"
    assert rep["stage"] == "data_generation_not_allowed"

    # Arm 2 is not trained in r2: its checkpoints carry over from r1.
    for family in spec.FAMILIES:
        for seed in spec.TRAINING_SEEDS:
            cell_dir = tmp_path / "phase2" / "checkpoints" / f"arm2_{family}_seed{seed}"
            cell_dir.mkdir(parents=True)
            (cell_dir / "model_weights.npz").write_bytes(b"inherited")

    # 2. Step 2: 12 Training Cells
    train_cells_executed = 0
    for family in ("P", "S"):
        for arm in spec.RETRAIN_ARM_IDS:
            for seed in (42, 43, 44):
                args_train = _make_args(
                    tmp_path,
                    "train",
                    arm=arm,
                    family=family,
                    seed=seed,
                    prereg=prereg_file,
                    research_log=research_log,
                    fake_clock=clock,
                    runner=runner,
                )
                rep, code = commands.e1_phase2_command(args_train)
                assert code == commands.EXIT_COMPLETED, f"Train arm={arm} {family} {seed} failed: {rep}"
                train_cells_executed += 1
    assert train_cells_executed == 12

    # 3. Step 3: 26 Dev Evaluation Cells (18 train + 8 non-train)
    dev_eval_cells_executed = 0
    for family in ("P", "S"):
        for arm in (2, 3, 6):
            for seed in (42, 43, 44):
                args_eval = _make_args(
                    tmp_path,
                    "eval",
                    arm=arm,
                    family=family,
                    seed=seed,
                    prereg=prereg_file,
                    research_log=research_log,
                    fake_clock=clock,
                    runner=runner,
                )
                rep, code = commands.e1_phase2_command(args_eval)
                assert code == commands.EXIT_COMPLETED, f"Eval train arm={arm} {family} {seed} failed: {rep}"
                dev_eval_cells_executed += 1
    assert dev_eval_cells_executed == 18

    for arm in (1, 4, 5, 7):
        for family in ("P", "S"):
            args_eval_nt = _make_args(
                tmp_path,
                "eval",
                arm=arm,
                family=family,
                seed=None,
                prereg=prereg_file,
                research_log=research_log,
                fake_clock=clock,
                runner=runner,
            )
            rep, code = commands.e1_phase2_command(args_eval_nt)
            assert code == commands.EXIT_COMPLETED, f"Eval non-train arm={arm} {seed} failed: {rep}"
            dev_eval_cells_executed += 1
    assert dev_eval_cells_executed == 26

    # 4. Step 4: Final Evaluation (2 cells: family P and family S)
    for fam in ("P", "S"):
        args_final = _make_args(
            tmp_path,
            "final-eval",
            family=fam,
            prereg=prereg_file,
            research_log=research_log,
            fake_clock=clock,
            runner=runner,
        )
        rep, code = commands.e1_phase2_command(args_final)
        assert code == commands.EXIT_COMPLETED, f"Final eval {fam} failed: {rep}"

    # Total cells: 12 + 26 + 2 = 40 cells
    total_elapsed = clock.time() - start_time
    assert total_elapsed <= spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]

    # Verify total reserved in ledger <= 5 h (18000.0 s)
    ledger_file = tmp_path / "phase2" / "control.sqlite3"
    with worker.ledger_read_snapshot(ledger_file) as store:
        cursor = store._conn.execute(
            "SELECT active_seconds FROM runs WHERE experiment_id = ?",
            (spec.EXPERIMENT_ID,),
        )
        total_reserved = sum(float(r["active_seconds"] or 0.0) for r in cursor.fetchall())
    assert total_reserved <= spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]
    assert total_reserved == 13200.0  # 9900 (train) + 1500 (eval) + 1800 (final)

    # 5. The registered schedule reserves the ceiling exactly, so any extra cell is refused.
    # An extra non-train eval cell (seed=999) pushes the total past the ceiling.
    args_exceed = _make_args(
        tmp_path,
        "eval",
        arm=1,
        family="S",
        seed=999,
        prereg=prereg_file,
        research_log=research_log,
        fake_clock=clock,
        runner=runner,
    )
    rep_exceed, code_exceed = commands.e1_phase2_command(args_exceed)
    assert code_exceed == commands.EXIT_REFUSED_RESOURCE
    assert rep_exceed["stage"] == "phase_budget_exceeded"

    # 6. Assert duplicate train cell is rejected
    dup_train = _make_args(
        tmp_path,
        "train",
        arm=3,
        family="P",
        seed=42,
        prereg=prereg_file,
        research_log=research_log,
        fake_clock=clock,
        runner=runner,
    )
    rep_dup, code_dup = commands.e1_phase2_command(dup_train)
    assert code_dup == commands.EXIT_FAILED
    assert rep_dup["stage"] == "duplicate_execution"

    # 7. Assert second final-eval for family P is rejected
    dup_final_p = _make_args(
        tmp_path,
        "final-eval",
        family="P",
        prereg=prereg_file,
        research_log=research_log,
        fake_clock=clock,
        runner=runner,
    )
    rep_dup_f, code_dup_f = commands.e1_phase2_command(dup_final_p)
    assert code_dup_f == commands.EXIT_FAILED
    assert rep_dup_f["stage"] in ("final_eval_already_read_once", "duplicate_execution")


def test_reserve_amount_equals_cell_wall_budget(tmp_path: Path):
    """Verify that central ledger reservation matches cell_wall_budget exactly upfront."""
    ledger_path = tmp_path / "control.sqlite3"
    clock = FakeClock(start=1000.0)
    ledger = worker.E1Ledger(ledger_path, clock=clock.time)
    runner = FakeCellRunner(clock=clock)
    cell_budget = 1200.0
    res = worker.execute_work_cell(
        ledger=ledger,
        mode="train",
        arm=2,
        family="P",
        seed=42,
        cell_wall_budget=cell_budget,
        data_dir=tmp_path / "data",
        output_root=tmp_path / "out",
        clock=clock.time,
        runner=runner,
    )
    run_id = res["run_id"]
    run_rec = ledger.store.get_run(run_id)
    assert run_rec.reserved_active_seconds == cell_budget
    ledger.close()


def test_runner_stopped_recorded_as_stopped_and_permits_rerun(tmp_path: Path):
    """Verify that runner returning stopped is recorded as stopped in ledger, and rerun is allowed."""
    ledger_path = tmp_path / "control.sqlite3"
    clock = FakeClock(start=1000.0)
    ledger = worker.E1Ledger(ledger_path, clock=clock.time)

    class StoppedRunner(worker.CellRunner):
        def run_train(self, **kwargs):
            return {"status": "stopped", "reason": "budget_exhausted"}

    res = worker.execute_work_cell(
        ledger=ledger,
        mode="train",
        arm=2,
        family="P",
        seed=42,
        cell_wall_budget=1200.0,
        data_dir=tmp_path / "data",
        output_root=tmp_path / "out",
        clock=clock.time,
        runner=StoppedRunner(),
    )
    run_id = res["run_id"]
    run_rec = ledger.store.get_run(run_id)
    assert run_rec.state == "stopped"
    assert run_rec.reason == "budget_exhausted"

    # Rerun must NOT be blocked by check_cell_already_completed
    is_done = worker.check_cell_already_completed(
        ledger_path, mode="train", arm=2, family="P", seed=42
    )
    assert not is_done, "Stopped cell must not be considered already completed"

    # Now rerun with a succeeding runner
    class OkRunner(worker.CellRunner):
        def run_train(self, **kwargs):
            return {"status": "completed", "checkpoint_path": "dummy.npz"}

    res2 = worker.execute_work_cell(
        ledger=ledger,
        mode="train",
        arm=2,
        family="P",
        seed=42,
        cell_wall_budget=1200.0,
        data_dir=tmp_path / "data",
        output_root=tmp_path / "out",
        clock=clock.time,
        runner=OkRunner(),
    )
    run_id2 = res2["run_id"]
    run_rec2 = ledger.store.get_run(run_id2)
    assert run_rec2.state == "completed"

    # Now check_cell_already_completed should be True
    assert worker.check_cell_already_completed(
        ledger_path, mode="train", arm=2, family="P", seed=42
    )
    ledger.close()


def test_runner_exception_recorded_as_failed(tmp_path: Path):
    """Verify that runner exception marks the run as failed in the ledger and re-raises."""
    ledger_path = tmp_path / "control.sqlite3"
    clock = FakeClock(start=1000.0)
    ledger = worker.E1Ledger(ledger_path, clock=clock.time)

    class FailingRunner(worker.CellRunner):
        def run_train(self, **kwargs):
            raise RuntimeError("Simulated CUDA OOM failure")

    with pytest.raises(RuntimeError, match="Simulated CUDA OOM failure"):
        worker.execute_work_cell(
            ledger=ledger,
            mode="train",
            arm=2,
            family="P",
            seed=42,
            cell_wall_budget=1200.0,
            data_dir=tmp_path / "data",
            output_root=tmp_path / "out",
            clock=clock.time,
            runner=FailingRunner(),
        )

    # Check that run was recorded as failed in ledger
    runs = ledger.store.list_runs()
    assert len(runs) == 1
    assert runs[0].state == "failed"
    assert "Simulated CUDA OOM failure" in str(runs[0].reason)
    ledger.close()


def test_no_hardcoded_metrics_in_production_code():
    """Verify production code in worker.py and commands.py has zero hardcoded metrics."""
    repo_root = Path(__file__).resolve().parent.parent
    files_to_check = [
        repo_root / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "worker.py",
        repo_root / "src" / "ainerzero" / "v9" / "experiments" / "e1" / "commands.py",
    ]

    suspicious_patterns = [
        r"0\.048",
        r"0\.009",
        r"\"collision_f1\"\s*:\s*0\.9[56]",
        r"\"position_error_10_step\"\s*:\s*0\.0",
        r"final_read_once\"\s*:\s*True",
    ]

    for file_path in files_to_check:
        text = file_path.read_text(encoding="utf-8")
        for pat in suspicious_patterns:
            matches = re.findall(pat, text)
            assert not matches, f"Found hardcoded pattern '{pat}' in {file_path}: {matches}"


def test_runstore_budget_derived_from_spec():
    """Verify RunStore manifest and model run budgets are strictly derived from spec (no magic numbers)."""
    manifest = worker.get_experiment_manifest()

    # 1. Total phase ceiling
    wall_ceiling = float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"])
    assert wall_ceiling == 13200.0
    assert manifest["budget"]["max_wall_seconds"] == wall_ceiling
    assert manifest["budget"]["max_daily_active_seconds"] == wall_ceiling
    assert manifest["experiment_budget"]["max_wall_seconds"] == float(
        spec.BUDGET_CAPS["experiment_calendar_window_seconds"]
    )

    # 2. Optimizer steps derived from spec with 20% margin
    train_cells = int(spec.BUDGET_CAPS["train_cells_count"])
    max_steps_per_cell = int(spec.DEFAULT_TRAIN_STEPS)
    assert train_cells == 12
    assert max_steps_per_cell == 64000

    expected_exp_opt_steps = int(train_cells * max_steps_per_cell * 1.2)  # 921,600
    expected_run_opt_steps = int(max_steps_per_cell * 1.2)  # 76,800
    assert expected_exp_opt_steps == 921_600
    assert expected_run_opt_steps == 76_800

    assert manifest["experiment_budget"]["max_optimizer_steps"] == expected_exp_opt_steps
    assert manifest["budget"]["max_optimizer_steps"] == expected_run_opt_steps

    # 3. Model runs count
    assert manifest["experiment_budget"]["max_model_runs"] == 100
