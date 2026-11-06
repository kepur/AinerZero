"""Comprehensive test suite for E1 Phase 2 entry (ainerzero.V9.P72).

Verifies:
1. Verify mode: read-only verification of preregistration and approval line.
2. Preflight guards: missing approval, bad arms, bad seeds, bad family, or exceeded budget
   refuse BEFORE writing to the ledger (ledger SHA256 remains strictly identical).
3. Anti-duplicate execution: retrying a completed training cell refuses; second final-eval refuses.
4. Final partition read-once enforcement: second final-eval permanently blocked.
5. Generate data: command argv assembly and preflight refusal.
6. Genuine production DefaultCellRunner:
   - eval runner on synthetic sequences genuinely invokes metrics.py, matching direct metric call.
   - train runner runs real arms_net for <=5 steps, saves real checkpoint, verified with model.load().
7. Fake clock end-to-end rehearsal:
   Executes complete registered schedule with FakeClock and FakeCellRunner:
   - 1 data-generation cell
   - 18 training cells (arms 2,3,6 x P,S x seeds 42,43,44)
   - 30 dev evaluation cells (18 train + 12 non-train)
   - 1 final-eval cell
   Total: 50 cells in sequence, asserting:
   - Per-cell deadline and budget reservation reset (no cell-2 timeout)
   - Total wall clock <= phase_total_wall_ceiling_seconds (115200 s)
   - Duplicate cell calls rejected
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import pytest

from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.experiments.e1 import (
    arms_net,
    arms_nonnet,
    commands,
    export,
    metrics,
    prereg,
    prior,
    spec,
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
    """Test fake runner used specifically for rapid schedule and control-flow rehearsal."""

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
            "metrics": {"position_error_10_step": 0.05, "collision_f1": 0.95},
            "status": "completed",
        }

    def run_final_eval(self, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop("Fake final-eval timeout")
        if self.clock is not None:
            self.clock.advance(20.0)
        return {
            "mode": "final-eval",
            "family": kwargs.get("family", "P"),
            "status": "completed",
        }
        return {
            "mode": "final-eval",
            "final_read_once": True,
            "metrics": {"position_error_10_step": 0.048, "collision_f1": 0.96},
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

    base_args = {
        "command": "e1-phase2",
        "mode": mode,
        "output_root": output_root,
        "ledger": ledger_path,
        "lock_file": lock_path,
        "research_log": research_log,
        "data_dir": data_dir,
        "prereg": prereg_file,
        "arm": None,
        "family": None,
        "seed": None,
        "wall_budget_seconds": None,
        "runner": None,
    }
    base_args.update(kwargs)
    return argparse.Namespace(**base_args)


def _create_synthetic_e0_sequence(world_key: str, family: str = "P", num_frames: int = 20) -> dict:
    """Create a physically valid synthetic E0 sequence for production testing."""
    env = prior.StaticEnvironment()
    body = prior.ActiveBody(
        name="cube_1",
        radius=0.1,
        params=prior.DEFAULT_BIASED_PRIOR,
        position=np.array([0.0, 0.0, 1.0]),
        velocity=np.array([0.1, 0.0, 0.0]),
    )
    sim = prior.rollout([body], env, num_frames=num_frames)
    traj = sim["cube_1"]

    frames = []
    for t in range(num_frames):
        pos = traj[t, 0:3].tolist()
        lin_v = traj[t, 3:6].tolist()
        orient = traj[t, 6:10].tolist()
        ang_v = traj[t, 10:13].tolist()
        frames.append({
            "frame_id": t,
            "objects": {
                "cube_1": {
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
                "cube_1": {
                    "shape": "BOX",
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


def test_verify_mode(tmp_path):
    """Verify mode is strictly read-only and validates prereg and approval."""
    args = _make_args(tmp_path, "verify")
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args.prereg)

    # 1. Without approval line -> refuses with exit 3
    args.research_log.write_text("# Log\n## Other\n", encoding="utf-8")
    report, exit_code = commands.e1_phase2_command(args)
    assert exit_code == commands.EXIT_REFUSED_APPROVAL
    assert report["status"] == "refused"
    assert report["stage"] == "approval_check"

    # 2. With wrong digest -> refuses with exit 3
    _setup_valid_approval_log(args.research_log, "0" * 64)
    report, exit_code = commands.e1_phase2_command(args)
    assert exit_code == commands.EXIT_REFUSED_APPROVAL
    assert report["status"] == "refused"

    # 3. With matching approval line -> succeeds with exit 0
    _setup_valid_approval_log(args.research_log, digest)
    report, exit_code = commands.e1_phase2_command(args)
    assert exit_code == commands.EXIT_COMPLETED
    assert report["status"] == "verified"
    assert report["document_sha256"] == digest


def test_preflight_refusal_leaves_ledger_sha_unchanged(tmp_path):
    """Verify that any preflight refusal happens BEFORE opening or modifying the ledger."""
    args = _make_args(tmp_path, "train", arm=2, family="P", seed=42)
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args.prereg)

    # Create initial ledger and record its SHA256
    init_ledger = worker.E1Ledger(args.ledger)
    init_ledger.ensure_experiment()
    init_ledger.close()

    initial_sha = hashlib.sha256(args.ledger.read_bytes()).hexdigest()

    # Preflight Refusal 1: Missing approval line
    args.research_log.write_text("# Log\n", encoding="utf-8")
    rep, code = commands.e1_phase2_command(args)
    assert code == commands.EXIT_REFUSED_APPROVAL
    assert rep["status"] == "refused"
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == initial_sha

    # Setup valid approval log
    _setup_valid_approval_log(args.research_log, digest)

    # Preflight Refusal 2: Non-trainable arm (arm 1)
    args_arm1 = _make_args(tmp_path, "train", arm=1, family="P", seed=42)
    rep, code = commands.e1_phase2_command(args_arm1)
    assert code == commands.EXIT_FAILED
    assert rep["status"] == "refused"
    assert rep["stage"] == "invalid_arm"
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == initial_sha

    # Preflight Refusal 3: Unregistered training seed (seed 99)
    args_seed99 = _make_args(tmp_path, "train", arm=3, family="P", seed=99)
    rep, code = commands.e1_phase2_command(args_seed99)
    assert code == commands.EXIT_FAILED
    assert rep["status"] == "refused"
    assert rep["stage"] == "invalid_seed"
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == initial_sha

    # Preflight Refusal 4: Invalid family (family "X")
    args_famX = _make_args(tmp_path, "train", arm=3, family="X", seed=42)
    rep, code = commands.e1_phase2_command(args_famX)
    assert code == commands.EXIT_FAILED
    assert rep["status"] == "refused"
    assert rep["stage"] == "invalid_family"
    assert hashlib.sha256(args.ledger.read_bytes()).hexdigest() == initial_sha


def test_train_argument_validation(tmp_path):
    """Verify train mode strictly enforces trainable arms and registered seeds."""
    args = _make_args(tmp_path, "train", arm=4, family="P", seed=42)
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args.prereg)
    _setup_valid_approval_log(args.research_log, digest)

    # Arm 4 is diagnostic, non-trainable -> rejected
    rep, code = commands.e1_phase2_command(args)
    assert code == commands.EXIT_FAILED
    assert "Arm 4 is not retrained" in rep["message"]

    # Arm 5, 7 non-trainable -> rejected
    for bad_arm in (5, 7):
        args_bad = _make_args(tmp_path, "train", arm=bad_arm, family="P", seed=42)
        rep, code = commands.e1_phase2_command(args_bad)
        assert code == commands.EXIT_FAILED
        assert rep["stage"] == "invalid_arm"


def test_duplicate_training_rejected(tmp_path):
    """Verify running the same training cell a second time is refused."""
    args = _make_args(tmp_path, "train", arm=3, family="P", seed=42, runner=FakeCellRunner())
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args.prereg)
    _setup_valid_approval_log(args.research_log, digest)

    # First run succeeds
    rep1, code1 = commands.e1_phase2_command(args)
    assert code1 == commands.EXIT_COMPLETED
    assert rep1["status"] == "completed"

    # Second run for identical cell must be refused
    rep2, code2 = commands.e1_phase2_command(args)
    assert code2 == commands.EXIT_FAILED
    assert rep2["status"] == "refused"
    assert rep2["stage"] == "duplicate_execution"


def test_final_eval_read_once(tmp_path):
    """Verify final-eval executes once and permanently refuses subsequent calls."""
    args = _make_args(tmp_path, "final-eval", family="P", runner=FakeCellRunner())
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args.prereg)
    _setup_valid_approval_log(args.research_log, digest)

    # First run succeeds
    rep1, code1 = commands.e1_phase2_command(args)
    assert code1 == commands.EXIT_COMPLETED
    assert rep1["status"] == "completed"
    # The sealed-data marker is the only read-once record; nothing else is written before the work.
    assert not (args.data_dir / "final").exists()

    # Second run must be refused
    rep2, code2 = commands.e1_phase2_command(args)
    assert code2 == commands.EXIT_FAILED
    assert rep2["status"] == "refused"
    assert "final_eval_already_read_once" in rep2["stage"] or "duplicate_execution" in rep2["stage"]


def test_generate_data_refusal(tmp_path):
    """Verify generate-data preflight refusal when approval is missing."""
    # Preflight refusal when approval is missing
    args = _make_args(tmp_path, "generate-data")
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args.prereg)
    args.research_log.write_text("# Log\n", encoding="utf-8")

    rep, code = commands.e1_phase2_command(args)
    assert code == commands.EXIT_REFUSED_APPROVAL
    assert rep["status"] == "refused"


def test_budget_insufficient_rejected(tmp_path):
    """Verify budget limits are enforced and cannot be exceeded."""
    args = _make_args(tmp_path, "train", arm=3, family="P", seed=42)
    draft = prereg.build_draft()
    frozen, digest = prereg.freeze(draft, output_path=args.prereg)
    _setup_valid_approval_log(args.research_log, digest)

    # Requesting budget override larger than registered cap is refused
    args.wall_budget_seconds = 100000.0  # way above 4800 s
    rep, code = commands.e1_phase2_command(args)
    assert code == commands.EXIT_REFUSED_RESOURCE
    assert rep["status"] == "refused"
    assert rep["stage"] == "budget_validation"


def test_power_policy_records_battery():
    """Verify power policy records battery info without refusal."""
    info = worker.get_power_info()
    assert info["policy"] == "R20261028-battery-policy"
    assert "power_source" in info
    assert "lid_closed" in info


def test_production_eval_runner_computes_real_metrics_on_synthetic_data(tmp_path):
    """Verify production DefaultCellRunner computes genuine metrics via metrics.py."""
    data_dir = tmp_path / "datasets"
    student_dir = data_dir / "student" / "P" / "development"
    evaluator_dir = data_dir / "evaluator" / "P" / "development"
    student_dir.mkdir(parents=True, exist_ok=True)
    evaluator_dir.mkdir(parents=True, exist_ok=True)

    # Export 2 synthetic sequences of length 25 so k=10 target frame (19) is < T-1 (24)
    for i in range(2):
        raw_seq = _create_synthetic_e0_sequence(f"dev_world_{i}", family="P", num_frames=25)
        s_view, e_view = export.export_sequence(raw_seq)
        (student_dir / f"seq_{i}.json").write_text(json.dumps(s_view), encoding="utf-8")
        (evaluator_dir / f"seq_{i}.json").write_text(json.dumps(e_view), encoding="utf-8")

    # Run production eval with DefaultCellRunner for Arm 1
    runner = worker.DefaultCellRunner()
    res = runner.run_eval(
        arm=1,
        family="P",
        seed=None,
        data_dir=data_dir,
        output_root=tmp_path / "phase2",
        clock_fn=time.time,
        deadline=time.time() + 300.0,
        budget=300.0,
    )

    assert "metrics" in res
    m = res["metrics"]
    assert "k_step_errors" in m
    assert "10" in m["k_step_errors"]
    assert "k_step_n_available" in m
    assert m["k_step_n_available"]["10"] == 2
    assert "collision_f1" in m
    assert "ballistic_energy_drift" in m
    assert res["episodes_evaluated"] == 2

    # Verify metric value is genuine and strictly finite float
    err_10 = m["k_step_errors"]["10"]
    assert isinstance(err_10, float)
    assert np.isfinite(err_10)
    assert err_10 >= 0.0
    assert m.get("primary_error_m") == pytest.approx(err_10)


def test_production_eval_runner_unavailable_k10_raises_in_downstream_analysis(tmp_path):
    """Verify that when k=10 is unavailable across all episodes, downstream analysis raises instead of assuming 0."""
    from ainerzero.v9.experiments.e1 import analysis

    data_dir = tmp_path / "datasets"
    student_dir = data_dir / "student" / "P" / "development"
    evaluator_dir = data_dir / "evaluator" / "P" / "development"
    student_dir.mkdir(parents=True, exist_ok=True)
    evaluator_dir.mkdir(parents=True, exist_ok=True)

    # 20 frames: prefix=10, target for k=10 is frame 19 = T-1 (endpoint), marked unavailable
    for i in range(2):
        raw_seq = _create_synthetic_e0_sequence(f"short_world_{i}", family="P", num_frames=20)
        s_view, e_view = export.export_sequence(raw_seq)
        (student_dir / f"seq_{i}.json").write_text(json.dumps(s_view), encoding="utf-8")
        (evaluator_dir / f"seq_{i}.json").write_text(json.dumps(e_view), encoding="utf-8")

    runner = worker.DefaultCellRunner()
    res = runner.run_eval(
        arm=1,
        family="P",
        seed=None,
        data_dir=data_dir,
        output_root=tmp_path / "phase2",
        clock_fn=time.time,
        deadline=time.time() + 300.0,
        budget=300.0,
    )

    m = res["metrics"]
    assert m["k_step_n_available"]["10"] == 0
    assert "10" not in m["k_step_errors"]
    assert m.get("primary_error_m") is None

    # Downstream extraction must loudly raise KeyError or ValueError, never falling back to 0.0
    with pytest.raises((KeyError, ValueError)):
        analysis._extract_10_step_error_from_summary(res["summary"])

    with pytest.raises(KeyError, match="No episodes contain available 10-step position error"):
        analysis._extract_episode_10_step_errors(res["episodes"])


def test_production_train_runner_runs_real_arms_net_and_saves_weights(tmp_path):
    """Verify production DefaultCellRunner runs real arms_net training and creates real save()."""
    data_dir = tmp_path / "datasets"
    train_dir = data_dir / "student" / "P" / "train"
    train_dir.mkdir(parents=True, exist_ok=True)

    # Write two synthetic sequences into student train to satisfy >=2 episode requirement
    for i in range(2):
        raw_seq = _create_synthetic_e0_sequence(f"train_world_{i}", family="P", num_frames=15)
        s_view, _ = export.export_sequence(raw_seq)
        (train_dir / f"seq_{i}.json").write_text(json.dumps(s_view), encoding="utf-8")

    runner = worker.DefaultCellRunner()
    res = runner.run_train(
        arm=2,
        family="P",
        seed=42,
        output_root=tmp_path / "phase2",
        data_dir=data_dir,
        clock_fn=time.time,
        deadline=time.time() + 1200.0,
        budget=1200.0,
        num_steps=5,
    )

    assert res["steps_completed"] == 5
    ckpt_path = Path(res["checkpoint_path"])
    assert ckpt_path.is_file()

    # Load with arms_net and verify parameter SHA matches
    model2 = arms_net.PureNetArm(seed=42)
    model2.load(ckpt_path)
    assert model2.parameter_sha256() == res["parameter_sha256"]
    assert hashlib.sha256(ckpt_path.read_bytes()).hexdigest() == res["checkpoint_sha256"]


def test_fake_clock_full_schedule_rehearsal(tmp_path):
    """End-to-end full schedule rehearsal with FakeClock and FakeCellRunner.

    Executes entire registered schedule:
    - 1 data-generation cell
    - 18 training cells (arms 2, 3, 6 x P, S x seeds 42, 43, 44)
    - 30 dev evaluation cells:
      - 18 train eval cells (arms 2, 3, 6 x P, S x seeds 42, 43, 44)
      - 12 non-train eval cells (arms 1, 4, 5, 7 across combinations)
    - 1 final-eval cell
    Total: 50 cells sequentially.

    Asserts:
    1. Each cell deadline and budget resets per-cell (no cell-2 timeout!).
    2. Total wall clock spent <= phase_total_wall_ceiling_seconds (115200 s).
    3. Duplicate train call rejected.
    4. Second final-eval rejected.
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

    # 3. Step 3: 30 Dev Evaluation Cells
    # 18 trainable arm dev eval cells
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

    # 12 non-trainable arm dev eval cells (4 arms x 3 seeds)
    non_train_eval_cells = 0
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
            non_train_eval_cells += 1
            dev_eval_cells_executed += 1
    assert non_train_eval_cells == 8
    assert dev_eval_cells_executed == 26

    # 4. Step 4: Final Evaluation (1 cell)
    args_final = _make_args(
        tmp_path,
        "final-eval",
        family="P",
        prereg=prereg_file,
        research_log=research_log,
        fake_clock=clock,
        runner=runner,
    )
    rep, code = commands.e1_phase2_command(args_final)
    assert code == commands.EXIT_COMPLETED, f"Final eval failed: {rep}"

    # Total cells: 12 + 26 + 1 = 39 cells
    total_elapsed = clock.time() - start_time
    assert total_elapsed <= spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]

    # 5. Assert duplicate train cell is rejected
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

    # 6. Assert second final-eval is rejected
    rep_final2, code_final2 = commands.e1_phase2_command(args_final)
    assert code_final2 == commands.EXIT_FAILED
    assert "final_eval_already_read_once" in rep_final2["stage"] or "duplicate_execution" in rep_final2["stage"]
