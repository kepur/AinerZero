#!/usr/bin/env python3
"""Rehearsal on production ledger copy (ainerzero.V9.P104).

1. Copies artifacts/v9/e1/phase2/control.sqlite3 to a temporary directory.
   Verifies production SHA256 is unchanged before and after copy.
2. Verifies on copy: _check_phase_budget_ceiling(copy, 1200) -> consumed == 9600;
   P-family 9 cells and data generation are completed;
   S-family 9 cells are uncompleted.
3. Using fake runner and temporary output_root/lock with current real time as clock:
   Admits S-family 9 cells (arm 6: 1200s, arms 2,3: 450s);
   Admits dev 26 cells (arm 6: 150s, arms 2,3: 40s, non-train arms: 45s).
   Asserts consumed == 17640.0s.
   Asserts adding one more cell of 1200s is refused with phase_budget_exceeded.
4. Writes output to reports/V9-E1-A1/rehearsal.json.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from typing import Any
import numpy as np

# Ensure src is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from ainerzero.v9.experiments.e1 import commands, export, prereg, spec, worker


class RehearsalFakeRunner(worker.CellRunner):
    """Fake runner simulating cell execution without GPU or MLX."""

    def run_generate_data(self, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        return {"mode": "generate-data", "status": "completed"}

    def run_train(self, arm: int, family: str, seed: int, output_root: Path, data_dir: Path, clock_fn, deadline: float, budget: float, **kwargs):
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
        return {
            "mode": "eval",
            "arm": arm,
            "family": family,
            "seed": seed,
            "metrics": {"position_error_10_step": 0.05, "collision_f1": 0.95},
            "status": "completed",
        }

    def run_final_eval(self, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        return {
            "mode": "final-eval",
            "family": kwargs.get("family", "P"),
            "status": "completed",
            "final_read_once": True,
            "metrics": {"position_error_10_step": 0.048, "collision_f1": 0.96},
        }


def make_command_args(
    mode: str,
    output_root: Path,
    ledger: Path,
    lock_file: Path,
    research_log: Path,
    data_dir: Path,
    prereg_file: Path,
    runner: worker.CellRunner,
    arm: int | None = None,
    family: str | None = None,
    seed: int | None = None,
    wall_budget_seconds: float | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        command="e1-phase2",
        mode=mode,
        output_root=output_root,
        ledger=ledger,
        lock_file=lock_file,
        research_log=research_log,
        data_dir=data_dir,
        prereg=prereg_file,
        arm=arm,
        family=family,
        seed=seed,
        wall_budget_seconds=wall_budget_seconds,
        runner=runner,
        fake_clock=None,  # use real time clock
    )


def main():
    prod_ledger = REPO_ROOT / "artifacts" / "v9" / "e1" / "phase2" / "control.sqlite3"
    assert prod_ledger.is_file(), f"Production ledger missing at {prod_ledger}"

    # 1. SHA verification before copy
    sha_before = hashlib.sha256(prod_ledger.read_bytes()).hexdigest()
    print(f"Production ledger SHA256 before copy: {sha_before}")

    with tempfile.TemporaryDirectory(prefix="e1_p104_rehearsal_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        output_root = tmp_dir / "phase2"
        output_root.mkdir(parents=True, exist_ok=True)
        copy_ledger = output_root / "control.sqlite3"
        lock_file = tmp_dir / "m0-worker.lock"
        research_log = tmp_dir / "RESEARCH_LOG.md"
        data_dir = tmp_dir / "datasets"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Copy ledger
        shutil.copy2(prod_ledger, copy_ledger)

        # Re-verify production SHA
        sha_after = hashlib.sha256(prod_ledger.read_bytes()).hexdigest()
        print(f"Production ledger SHA256 after copy:  {sha_after}")
        assert sha_before == sha_after, "Production ledger was mutated during copy!"

        # 2. Check initial ledger state on copy
        ok_init, consumed_init, ceiling_init = commands._check_phase_budget_ceiling(copy_ledger, 1200.0)
        print(f"Initial on copy: ok={ok_init}, consumed={consumed_init}s, ceiling={ceiling_init}s")
        assert consumed_init == 9600.0, f"Expected 9600.0 consumed on r0 copy, got {consumed_init}"

        # Verify completed cells
        gen_done = worker.check_cell_already_completed(copy_ledger, "generate-data", None, None, None)
        assert gen_done is True, "generate-data should be completed on r0"

        p_cells_status = {}
        for arm in (2, 3, 6):
            for seed in (42, 43, 44):
                st = worker.check_cell_already_completed(copy_ledger, "train", arm, "P", seed)
                p_cells_status[f"train:{arm}:P:{seed}"] = st
                assert st is True, f"Cell train arm {arm} P seed {seed} should be completed on r0"

        s_cells_status = {}
        for arm in (2, 3, 6):
            for seed in (42, 43, 44):
                st = worker.check_cell_already_completed(copy_ledger, "train", arm, "S", seed)
                s_cells_status[f"train:{arm}:S:{seed}"] = st
                assert st is False, f"Cell train arm {arm} S seed {seed} should NOT be completed on r0"

        # 3. Setup temporary frozen prereg and approval for r1
        draft = prereg.build_draft()
        prereg.validate(draft)
        frozen_doc, digest = prereg.freeze(draft)
        prereg_file = output_root / "prereg.json"
        prereg_file.write_bytes(spec.canonical_json(frozen_doc))

        approval_text = f"""# Research Log
## R20261029-E1-approval
APPROVED e1-phase2 prereg document_sha256={digest}
"""
        research_log.write_text(approval_text, encoding="utf-8")

        # Generator identity
        gen_id = {
            "generator_digests": dict(draft.get("generator_digests") or {}),
            "velocity_injection": draft.get("required_velocity_injection", "disabled"),
            "timestamp": time.time(),
        }
        (data_dir / "generator_identity.json").write_text(json.dumps(gen_id), encoding="utf-8")

        # Copy existing production P checkpoints so dev eval passes preflight
        prod_ckpts = REPO_ROOT / "artifacts" / "v9" / "e1" / "phase2" / "checkpoints"
        temp_ckpts = output_root / "checkpoints"
        temp_ckpts.mkdir(parents=True, exist_ok=True)
        if prod_ckpts.is_dir():
            for p in prod_ckpts.iterdir():
                if p.is_dir():
                    shutil.copytree(p, temp_ckpts / p.name, dirs_exist_ok=True)

        runner = RehearsalFakeRunner()
        admitted_cells = []

        # (a) Admit S-family 9 cells:
        # Arm 6: 1200s, Arms 2, 3: 450s
        for arm in (6, 2, 3):
            b_sec = 1200.0 if arm == 6 else 450.0
            for seed in (42, 43, 44):
                args = make_command_args(
                    mode="train",
                    output_root=output_root,
                    ledger=copy_ledger,
                    lock_file=lock_file,
                    research_log=research_log,
                    data_dir=data_dir,
                    prereg_file=prereg_file,
                    runner=runner,
                    arm=arm,
                    family="S",
                    seed=seed,
                    wall_budget_seconds=b_sec,
                )
                rep, code = commands.e1_phase2_command(args)
                assert code == commands.EXIT_COMPLETED, f"S cell failed ({arm}, S, {seed}): {rep}"
                admitted_cells.append({
                    "cell": f"train:{arm}:S:{seed}",
                    "wall_budget_seconds": b_sec,
                    "status": rep.get("status"),
                })

        # Check consumed after S-family: 9600 + (3*1200 + 3*450 + 3*450) = 9600 + 6300 = 15900s
        _, consumed_after_s, _ = commands._check_phase_budget_ceiling(copy_ledger, 0.0)
        print(f"Consumed after S-family (9 cells): {consumed_after_s}s (expected 15900.0)")
        assert consumed_after_s == 15900.0

        # (b) Admit dev 26 cells:
        # Arm 6: 150s (6 cells = 900s)
        # Arm 2: 40s (6 cells = 240s)
        # Arm 3: 40s (6 cells = 240s)
        # Arms 1, 4, 5, 7: 45s (8 cells = 360s)
        # Total dev budget = 900 + 240 + 240 + 360 = 1740s
        dev_cells_spec = []
        for arm in (6, 2, 3):
            b_sec = 150.0 if arm == 6 else 40.0
            for fam in ("P", "S"):
                for seed in (42, 43, 44):
                    dev_cells_spec.append((arm, fam, seed, b_sec))

        for arm in (1, 4, 5, 7):
            for fam in ("P", "S"):
                dev_cells_spec.append((arm, fam, None, 45.0))

        assert len(dev_cells_spec) == 26, f"Expected 26 dev cells, got {len(dev_cells_spec)}"

        for arm, fam, seed, b_sec in dev_cells_spec:
            args = make_command_args(
                mode="eval",
                output_root=output_root,
                ledger=copy_ledger,
                lock_file=lock_file,
                research_log=research_log,
                data_dir=data_dir,
                prereg_file=prereg_file,
                runner=runner,
                arm=arm,
                family=fam,
                seed=seed,
                wall_budget_seconds=b_sec,
            )
            rep, code = commands.e1_phase2_command(args)
            assert code == commands.EXIT_COMPLETED, f"dev eval failed ({arm}, {fam}, {seed}): {rep}"
            admitted_cells.append({
                "cell": f"eval:{arm}:{fam}:{seed}",
                "wall_budget_seconds": b_sec,
                "status": rep.get("status"),
            })

        # Check total consumed after dev 26 cells: 15900 + 1740 = 17640.0s
        _, consumed_final, _ = commands._check_phase_budget_ceiling(copy_ledger, 0.0)
        print(f"Consumed after dev (26 cells): {consumed_final}s (expected 17640.0)")
        assert consumed_final == 17640.0

        # (c) Rejection of next 1200s cell
        # 1. Direct ceiling check
        ok_next, consumed_next, ceiling_next = commands._check_phase_budget_ceiling(copy_ledger, 1200.0)
        assert ok_next is False
        assert consumed_next == 17640.0
        assert ceiling_next == 18000.0

        # 2. Command admission rejection check (via final-eval requesting 1200.0s)
        args_rejected = make_command_args(
            mode="final-eval",
            output_root=output_root,
            ledger=copy_ledger,
            lock_file=lock_file,
            research_log=research_log,
            data_dir=data_dir,
            prereg_file=prereg_file,
            runner=runner,
            family="P",
            wall_budget_seconds=1200.0,
        )
        rep_rej, code_rej = commands.e1_phase2_command(args_rejected)
        print(f"Excess cell admission result: code={code_rej}, stage={rep_rej.get('stage')}")
        assert code_rej == commands.EXIT_REFUSED_RESOURCE
        assert rep_rej.get("stage") == "phase_budget_exceeded"
        assert rep_rej.get("consumed_seconds") == 17640.0
        assert rep_rej.get("cell_budget_seconds") == 1200.0
        assert rep_rej.get("ceiling_seconds") == 18000.0

        # 4. Write rehearsal output
        rehearsal_result = {
            "status": "success",
            "production_ledger": str(prod_ledger),
            "production_ledger_sha256_before": sha_before,
            "production_ledger_sha256_after": sha_after,
            "production_ledger_unaltered": (sha_before == sha_after),
            "initial_r0_consumed_seconds": consumed_init,
            "generate_data_completed_in_r0": gen_done,
            "p_family_completed_in_r0_count": sum(1 for v in p_cells_status.values() if v),
            "s_family_completed_in_r0_count": sum(1 for v in s_cells_status.values() if v),
            "s_family_admitted_count": 9,
            "s_family_budget_consumed_seconds": 6300.0,
            "dev_eval_admitted_count": 26,
            "dev_eval_budget_consumed_seconds": 1740.0,
            "total_admitted_cells_in_rehearsal": len(admitted_cells),
            "final_total_consumed_seconds": consumed_final,
            "total_ceiling_seconds": ceiling_init,
            "remaining_budget_seconds": ceiling_init - consumed_final,
            "excess_cell_attempt": {
                "requested_budget_seconds": 1200.0,
                "exit_code": code_rej,
                "refusal_stage": rep_rej.get("stage"),
                "status": rep_rej.get("status"),
                "message": rep_rej.get("message"),
            },
        }

        output_path = REPO_ROOT / "reports" / "V9-E1-A1" / "rehearsal.json"
        output_path.write_text(json.dumps(rehearsal_result, indent=2), encoding="utf-8")
        print(f"Rehearsal successfully written to {output_path}")


if __name__ == "__main__":
    main()
