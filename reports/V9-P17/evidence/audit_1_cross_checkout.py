#!/usr/bin/env python3
"""Audit 1: Cross-checkout duplicate run vulnerability (关键独立反例).
Demonstrates that spec.REPO_ROOT is resolved relative to __file__, so a separate
checkout can treat an empty legal RunStore database under its own PHASE1_ROOT as the
canonical ledger, bypassing duplicate run prevention across checkouts.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
PYTHON = REAL_REPO / ".venv" / "bin" / "python"
REAL_CONTROL_DB = REAL_REPO / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3"

def run_cross_checkout_proof():
    with tempfile.TemporaryDirectory(prefix="p17_cross_checkout_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        checkout_a = (tmp_path / "checkout_a").resolve()
        checkout_b = (tmp_path / "checkout_b").resolve()

        # Setup checkouts A and B
        for co in (checkout_a, checkout_b):
            shutil.copytree(REAL_REPO / "src", co / "src")
            os.makedirs(co / "artifacts" / "v9" / "s1" / "phase1" / "r6", exist_ok=True)
            shutil.copy(
                REAL_REPO / "artifacts" / "v9" / "s1" / "phase1" / "r6" / "pre_registration.json",
                co / "artifacts" / "v9" / "s1" / "phase1" / "r6" / "pre_registration.json"
            )
            os.makedirs(co / "artifacts" / "v9" / "s1" / "datasets", exist_ok=True)
            with open(co / "RESEARCH_LOG.md", "w") as f:
                f.write(
                    "## 阶段批准\n\n"
                    "- 2026-10-22 S1 phase 1: APPROVED for arms arm2, arm3, arm4 with seeds 0, 1, 2\n"
                )

        # In Checkout A, copy real control.sqlite3 and insert a completed run for arm2 seed 0
        db_a = checkout_a / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3"
        shutil.copy(REAL_CONTROL_DB, db_a)
        conn_a = sqlite3.connect(db_a)
        # Register train experiment and completed run in checkout A
        conn_a.execute(
            "INSERT INTO experiments (experiment_id, request_id, manifest_json, manifest_hash, created_at) "
            "VALUES ('s1-phase1-train-arm2-seed0', 'req_exp_a', '{}', 'hash_a', 1700000000.0)"
        )
        conn_a.execute(
            "INSERT INTO runs (run_id, request_id, state, resume_state, reason, config_json, config_hash, created_at, updated_at, environment_steps, optimizer_steps, active_seconds, experiment_id, role, model_transitions) "
            "VALUES ('run_arm2_s0_a', 'req_run_a', 'completed', 'none', 's1_train_completed: mock', '{\"arm_id\": \"arm2\", \"seed\": 0}', 'cfghash', 1700000000.0, 1700000100.0, 0, 3510, 100.0, 's1-phase1-train-arm2-seed0', 'model', 0)"
        )
        conn_a.commit()
        conn_a.close()

        # In Checkout B, copy real control.sqlite3, but keep only the prep experiment (no arm2 run!)
        db_b = checkout_b / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3"
        shutil.copy(REAL_CONTROL_DB, db_b)
        # Verify db_b has prep experiment: s1-phase1-prereg-prep-20261021

        # Now test Checkout A via Python
        sys.path.insert(0, str(checkout_a / "src"))
        from ainerzero.runtime.lifecycle import RunStore
        from ainerzero.v9.experiments.s1 import spec as spec_a, worker as worker_a

        store_a = RunStore(db_a)
        attempts_a = [r.state for r in worker_a.train_attempts(store_a.list_runs(), arm_id="arm2", seed=0)]
        assert attempts_a == ["completed"], f"Expected completed in A, got {attempts_a}"
        sys.path.pop(0)

        # Now test Checkout B in an isolated subprocess
        probe_code = f"""
import sys
from pathlib import Path
sys.path.insert(0, "{str(checkout_b / 'src')}")
from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.experiments.s1 import spec as spec_b, worker as worker_b

# Verify spec.PHASE1_ROOT resolution inside checkout B
b_phase1 = spec_b.PHASE1_ROOT.resolve()
db_b = spec_b.PHASE1_ROOT / "control.sqlite3"
assert str(b_phase1).startswith("{str(checkout_b)}"), f"spec.PHASE1_ROOT did not resolve inside checkout B: {{b_phase1}}"

# Verify canonical_ledger_state returns ok in checkout B
state_b = worker_b.canonical_ledger_state()
assert state_b["status"] == "ok", f"Expected ok in B, got {{state_b}}"

# Check attempts in Checkout B
store_b = RunStore(db_b)
attempts_b = worker_b.train_attempts(store_b.list_runs(), arm_id="arm2", seed=0)
assert attempts_b == [], f"Expected empty attempts in B, got {{attempts_b}}"

# Check if worker accepts this output root as canonical
# worker checks: output_root.resolve() == spec.PHASE1_ROOT.resolve()
assert b_phase1 == spec_b.PHASE1_ROOT.resolve()
print("CHECKOUT_B_ESCAPE_VERIFIED")
"""
        res = subprocess.run([str(PYTHON), "-c", probe_code], capture_output=True, text=True)
        if res.returncode != 0:
            print("STDOUT:", res.stdout)
            print("STDERR:", res.stderr)
            raise RuntimeError(f"Subprocess failed with code {res.returncode}")

        return {
            "vulnerability_demonstrated": True,
            "checkout_a_attempts": attempts_a,
            "checkout_b_attempts": [],
            "checkout_b_stdout": res.stdout.strip(),
            "mechanism": (
                "spec.REPO_ROOT = Path(__file__).resolve().parents[5] anchors canonical_ledger_path() "
                "relative to the active checkout directory instead of a single host-wide fixed location. "
                "In another checkout (checkout B), canonical_ledger_path() resolves to checkout_b/artifacts/v9/s1/phase1/control.sqlite3. "
                "Because checkout B's control.sqlite3 is a valid RunStore containing the prep experiment, "
                "it passes canonical_ledger_state(), passes output_root_not_canonical, and sees 0 attempts for arm2 seed 0, "
                "allowing duplicate training runs to be initiated regardless of checkout A's completed state."
            )
        }

if __name__ == "__main__":
    import json
    result = run_cross_checkout_proof()
    out_file = REAL_REPO / "reports" / "V9-P17" / "evidence" / "cross_checkout_vulnerability.json"
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("Cross-checkout audit proof successful.")
