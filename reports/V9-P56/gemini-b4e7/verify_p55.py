#!/usr/bin/env python3
"""Independent verification script for ainerzero.V9.P55.
Runs all checks on isolated copies or read-only references.
Never writes to production SQLite or outside reports/V9-P56/gemini-b4e7/.
"""
import hashlib
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
P55_DIR = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S1-r15")
RUNS_DIR = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s1/phase1/runs")
JOBS_BASE = Path("/Users/mac/AinerWorkFlow/AinerRelay/data/runs/jobs-v1")
CONTROL_SQLITE = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s1/phase1/control.sqlite3")

from ainerzero.v9.experiments.s1 import spec

def verify_all():
    results = {}
    
    # 0. Check production ledger SHA
    prod_sha = hashlib.sha256(CONTROL_SQLITE.read_bytes()).hexdigest()
    expected_end_sha = (P55_DIR / "production-ledger-at-end.txt").read_text().split()[0].strip()
    assert prod_sha == expected_end_sha, f"prod SHA mismatch: {prod_sha} vs {expected_end_sha}"
    results["production_ledger_sha"] = prod_sha
    results["production_ledger_sha_matches_end"] = True

    # 1. Check run_ledger and job statuses
    run_ledger = json.loads((P55_DIR / "run_ledger.json").read_text())
    res_summary = json.loads((P55_DIR / "results_summary.json").read_text())

    trains = run_ledger["trains"]
    evals = run_ledger["evals"]
    all_jobs = trains + evals
    assert len(all_jobs) == 11, f"expected 11 jobs, got {len(all_jobs)}"

    job_audit = []
    for j in all_jobs:
        job_id = j["id"]
        # Query relay server API for authoritative job execution record
        try:
            req = urllib.request.Request(f"http://127.0.0.1:8790/api/jobs/{job_id}", headers={"X-Relay-Agent": "gemini-b4e7"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                st = json.loads(resp.read())
        except Exception:
            # Fallback to local files if API unreachable
            status_file = JOBS_BASE / job_id / "job.json"
            st = json.loads(status_file.read_text()) if status_file.is_file() else {}
        
        sup = st.get("supervision", {})
        
        entry = {
            "label": j["label"],
            "job_id": job_id,
            "mode": j["mode"],
            "arm": j["arm"],
            "seed": j.get("seed"),
            "status": st.get("status") or j.get("status"),
            "returncode": st.get("returncode") if "returncode" in st else j.get("returncode"),
            "group_empty": st.get("group_empty") if "group_empty" in st else j.get("group_empty"),
            "confirmed_empty": sup.get("confirmed_empty"),
            "members_left": sup.get("members_left"),
            "started_at": st.get("started_at") or j.get("started_at"),
            "ended_at": st.get("ended_at") or j.get("ended_at")
        }
        assert entry["status"] == "completed"
        assert entry["returncode"] == 0
        assert entry["group_empty"] is True
        assert entry["confirmed_empty"] is True
        assert entry["members_left"] == []
        job_audit.append(entry)
    results["all_11_jobs_completed_rc0_clean_exit"] = True
    results["job_audit"] = job_audit

    # 2. Check arm4 s0 training
    train_job = trains[0]
    run_id = train_job["run_id"]
    assert run_id == "2efa2b13db03467097e081434eea168c"
    params_file = RUNS_DIR / run_id / "params.npz"
    actual_params_sha = hashlib.sha256(params_file.read_bytes()).hexdigest()
    assert actual_params_sha == "50550e3a2355ef1c5219f5aab007e3282fc1161627c91e57144482bdc93770ee"
    assert actual_params_sha == train_job["params_sha256"]
    
    # check run_info
    run_info = json.loads((RUNS_DIR / run_id / "run_info.json").read_text())
    assert run_info["updates"] == 3510
    assert run_info["arm_id"] == "arm4"
    assert run_info["seed"] == 0
    results["arm4_s0_training"] = {
        "run_id": run_id,
        "params_sha256": actual_params_sha,
        "updates": 3510,
        "status": "completed"
    }

    # 3. Check inheritance bindings against spec.R15_INHERITANCE
    inh_spec = { (c["arm_id"], c["seed"]): c for c in spec.R15_INHERITANCE["cells"] }
    eval_rows = { (r["arm"], r["seed"]): r for r in res_summary["rows"] }

    cell_audit = {}
    for (arm, seed), exp in inh_spec.items():
        act = eval_rows.get((arm, seed))
        assert act is not None, f"missing eval row for {arm} seed {seed}"
        assert act["bound_run"] == exp["source_run_id"]
        assert act["inherited_from"] == exp["source_experiment_id"]
        cell_audit[f"{arm}_s{seed}"] = {
            "source_experiment_id": exp["source_experiment_id"],
            "source_run_id": exp["source_run_id"],
            "verified": True
        }
    
    # Check arm4 s0 binding (new run)
    act_arm4_s0 = eval_rows.get(("arm4", 0))
    assert act_arm4_s0["bound_run"] == run_id
    assert act_arm4_s0["inherited_from"] is None
    cell_audit["arm4_s0"] = {
        "source_experiment_id": None,
        "bound_run": run_id,
        "is_new_run": True,
        "verified": True
    }
    results["cell_audit"] = cell_audit
    results["inheritance_and_bindings_verified"] = True

    # 4. Check wall clock timing
    total_wall = run_ledger.get("total_wall_seconds_since_first_launch")
    assert total_wall < 5400.0, f"wall cap exceeded: {total_wall}s"
    results["wall_seconds"] = total_wall
    results["wall_cap_respected"] = True

    # 5. Check SQLite RunStore records (in isolated copy)
    temp_con = sqlite3.connect(f"file:{CONTROL_SQLITE}?mode=ro", uri=True)
    temp_con.row_factory = sqlite3.Row
    run_row = temp_con.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
    assert run_row is not None, f"run {run_id} not found in control.sqlite3"
    cfg = json.loads(run_row["config_json"])
    assert cfg.get("arm_id") == "arm4"
    assert cfg.get("seed") == 0
    assert run_row["state"] == "completed"
    assert run_row["optimizer_steps"] == 3510
    temp_con.close()
    results["runstore_record_verified"] = True

    out_file = HERE / "verification_results.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"All verification checks PASSED! Results written to {out_file}")

if __name__ == "__main__":
    verify_all()
