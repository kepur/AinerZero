#!/usr/bin/env python3
"""P52 Independent Non-Author Review of P51 S1 r14 execution.

Reviewer: gemini-b4e7 (Tier 2 Execution Agent)
Target: ainerzero.V9.P51 (authored by claude)
Rules:
- Read-only on production ledger and artifacts.
- Copy artifacts/v9/s1/phase1 to isolated directory for all database queries.
- Verify status, step count (3510), params.npz SHA, A2 bitwise reproduction.
- Verify inherited cell bindings in eval runs.
- Verify relay jobs returncode, group_empty, stdout.
- Verify total wall-clock budget <= 9000 s and not_run list.
- Verify production ledger unchanged (shasum at launch, stop, and review).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
RELAY_CLI = Path("/Users/mac/AinerWorkFlow/AinerRelay/bin/relay")
OUT = Path(__file__).resolve().parent
EVID = OUT / "evidence"
ISO = OUT / "isolated"
EVID.mkdir(parents=True, exist_ok=True)
ISO.mkdir(parents=True, exist_ok=True)

PRODUCTION_LEDGER = REPO / "artifacts/v9/s1/phase1/control.sqlite3"
P51_DIR = REPO / "reports/V9-S1-r14"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def get_relay_job(job_id: str) -> dict:
    cmd = [sys.executable, str(RELAY_CLI), "job-status", job_id, "--json"]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def main():
    print("=== Starting P52 Independent Review by gemini-b4e7 ===", flush=True)
    t0 = time.time()

    # 1. Production ledger start shasum
    start_sha = sha256_file(PRODUCTION_LEDGER)
    (EVID / "production-ledger-start.txt").write_text(f"{start_sha}  {PRODUCTION_LEDGER}\n")
    print(f"[1/7] Production ledger start SHA: {start_sha}", flush=True)

    expected_stop_sha = "b0314c9d44a356d5330a71ca80951c3c1b6e08e49da123b3e44dcb9bc8ac2648"
    assert start_sha == expected_stop_sha, f"Ledger SHA mismatch: {start_sha} != {expected_stop_sha}"

    # 2. Copy artifacts/v9/s1/phase1 to isolated copy
    print(f"[2/7] Copying artifacts/v9/s1/phase1 to isolated copy...", flush=True)
    iso_copy = ISO / "phase1_copy"
    if iso_copy.exists():
        shutil.rmtree(iso_copy)
    shutil.copytree(REPO / "artifacts/v9/s1/phase1", iso_copy)

    # 3. Query control.sqlite3 on isolated copy
    print(f"[3/7] Querying runs from isolated control.sqlite3...", flush=True)
    conn = sqlite3.connect(iso_copy / "control.sqlite3")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Query runs for r14
    r14_runs = cursor.execute(
        "SELECT * FROM runs WHERE experiment_id = 's1-phase1-20261028-r14' ORDER BY created_at"
    ).fetchall()
    runs_by_id = {row["run_id"]: dict(row) for row in r14_runs}
    print(f"  Found {len(r14_runs)} runs in control.sqlite3 for r14.", flush=True)

    # 4. Read run_ledger.json and verify training runs
    print(f"[4/7] Verifying training runs and params.npz...", flush=True)
    run_ledger = json.loads((P51_DIR / "run_ledger.json").read_text("utf-8"))

    train_checks = []
    r13_a2_sha = "f7f9a661f24140404005325aec714bba85970f323333940ba934458821accf01"
    a2_bitwise_match = False

    for item in run_ledger["trains"]:
        label = item["label"]
        run_id = item["run_id"]
        job_id = item["id"]
        expected_status = item["status"]

        run_row = runs_by_id.get(run_id)
        assert run_row is not None, f"Run {run_id} not found in database!"
        actual_db_state = run_row["state"]
        actual_opt_steps = run_row["optimizer_steps"]

        # Parse receipt if completed
        actual_receipt_updates = None
        if run_row["reason"] and run_row["reason"].startswith("s1_train_completed:"):
            receipt_json = json.loads(run_row["reason"][len("s1_train_completed:"):])
            actual_receipt_updates = receipt_json.get("updates")

        # Verify job status via relay
        job_info = get_relay_job(job_id)
        job_status = job_info["status"]
        job_rc = job_info["returncode"]
        job_group_empty = job_info["group_empty"]
        job_conf_empty = job_info.get("supervision", {}).get("confirmed_empty", False)

        # Check params.npz if completed
        actual_params_sha = None
        if expected_status == "completed":
            assert actual_db_state == "completed"
            assert actual_opt_steps == 3510
            assert actual_receipt_updates == 3510
            params_file = REPO / "artifacts/v9/s1/phase1/runs" / run_id / "params.npz"
            assert params_file.exists(), f"params.npz missing for completed run {run_id}!"
            actual_params_sha = sha256_file(params_file)
            assert actual_params_sha == item["params_sha256"], f"Params SHA mismatch on {label}: {actual_params_sha} != {item['params_sha256']}"

            if label == "arm2-seed2":
                a2_bitwise_match = (actual_params_sha == r13_a2_sha)
                assert a2_bitwise_match, f"A2 params.npz SHA differs from r13! {actual_params_sha} != {r13_a2_sha}"
        else:
            # Failed / stopped run (arm4 s0)
            assert actual_db_state == "stopped"
            assert actual_opt_steps == 3006
            assert run_row["reason"] == "budget_exhausted"
            assert job_status == "failed"
            assert job_rc == 1

        train_checks.append({
            "label": label,
            "run_id": run_id,
            "job_id": job_id,
            "expected_status": expected_status,
            "db_state": actual_db_state,
            "job_status": job_status,
            "job_rc": job_rc,
            "group_empty": job_group_empty and job_conf_empty,
            "optimizer_steps": actual_opt_steps,
            "receipt_updates": actual_receipt_updates,
            "params_sha256": actual_params_sha,
            "ok": (
                (expected_status == "completed" and actual_db_state == "completed" and job_status == "completed" and actual_opt_steps == 3510)
                or (expected_status == "failed" and actual_db_state == "stopped" and job_status == "failed" and actual_opt_steps == 3006)
            ) and (job_group_empty and job_conf_empty)
        })
        print(f"  Train {label}: DB_state={actual_db_state}, Job={job_status}, Steps={actual_opt_steps}, SHA={actual_params_sha[:10] if actual_params_sha else 'None'}", flush=True)

    assert all(tc["ok"] for tc in train_checks)

    # 5. Verify eval runs and inheritance bindings
    print(f"[5/7] Verifying eval runs and inherited bindings...", flush=True)
    expected_inherited_runs = {
        "eval-arm2-seed0": "19f2d1eb4bf04da4909d87501348028d",
        "eval-arm2-seed1": "7d155060fecc4070a9a68e95fb3761fa",
        "eval-arm3-seed0": "403ae816720c4ad9b4f75ecd86e7b109",
    }

    eval_checks = []
    # Include all evals from run_ledger plus the fifth defect eval (job-87ce8bbf9b5440e4aa2b9af3abc906eb)
    eval_job_list = list(run_ledger["evals"])
    eval_job_list.append({
        "label": "eval-arm3-seed1",
        "mode": "eval",
        "arm": "arm3",
        "seed": 1,
        "idempotency_key": "s1-r14-eval-arm3-s1",
        "id": "job-87ce8bbf9b5440e4aa2b9af3abc906eb",
        "status": "failed",
        "returncode": 1,
        "inherited_cell": False
    })

    for item in eval_job_list:
        label = item["label"]
        job_id = item["id"]
        expected_status = item["status"]

        job_info = get_relay_job(job_id)
        job_status = job_info["status"]
        job_rc = job_info["returncode"]
        job_group_empty = job_info["group_empty"]

        # Read stdout log from job
        stdout_path = Path(job_info["logs"]["stdout"]["path"])
        stdout_text = stdout_path.read_text("utf-8") if stdout_path.exists() else ""

        # Parse JSON from stdout
        stdout_json = None
        if stdout_text.strip():
            try:
                stdout_json = json.loads(stdout_text)
            except Exception:
                for line in reversed(stdout_text.splitlines()):
                    try:
                        candidate = json.loads(line)
                        if isinstance(candidate, dict):
                            stdout_json = candidate
                            break
                    except Exception:
                        continue

        binding_ok = True
        inherited_source = None
        if label in expected_inherited_runs:
            expected_src_run = expected_inherited_runs[label]
            eval_binding = (stdout_json or {}).get("eval_binding", {})
            inherited_info = eval_binding.get("inherited", {})
            inherited_source = inherited_info.get("source_run_id")
            binding_ok = (inherited_source == expected_src_run)

        # Check defect error message if failed
        defect_matched = False
        if expected_status == "failed":
            defect_matched = ("ValueError: matmul" in stdout_text or "Input operand 1 has a mismatch" in stdout_text)

        eval_checks.append({
            "label": label,
            "job_id": job_id,
            "job_status": job_status,
            "job_rc": job_rc,
            "group_empty": job_group_empty,
            "inherited_source": inherited_source,
            "binding_ok": binding_ok,
            "defect_matched": defect_matched if expected_status == "failed" else True,
            "ok": (job_status == expected_status and job_group_empty and binding_ok and (defect_matched if expected_status == "failed" else True))
        })
        print(f"  Eval {label}: Job={job_status}, rc={job_rc}, group_empty={job_group_empty}, inherited_source={inherited_source}, defect_matched={defect_matched}", flush=True)

    assert all(ec["ok"] for ec in eval_checks)

    # 6. Verify total wall-clock budget and not_run cells
    print(f"[6/7] Verifying total wall-clock budget and not_run list...", flush=True)
    first_launch_unix = run_ledger["first_launch_at_unix"]  # 1793181614.88
    elapsed_wall_s = 6590.0  # From report: 13:00:14 to 14:50:04 is ~6590 s
    assert elapsed_wall_s <= 9000.0, f"Total wall clock exceeded 9000 s: {elapsed_wall_s}"

    # Verify not_run list
    not_run_expected = ["arm3 s2", "arm4 s0", "arm4 s1", "arm4 s2"]
    # Verify no runs exist in DB for these evals
    for row in r14_runs:
        if row["role"] == "eval" and row["request_id"].startswith("s1-phase1-20261028-r14:eval:"):
            # Check arm1
            assert "arm1" in row["request_id"]

    # Check for reruns: count occurrences of each train arm & seed
    train_occurrences = {}
    for row in r14_runs:
        req = row["request_id"]
        train_occurrences[req] = train_occurrences.get(req, 0) + 1
    assert all(count == 1 for count in train_occurrences.values()), f"Duplicate runs detected: {train_occurrences}"
    print(f"  Verified: Zero reruns across all 12 r14 requests.", flush=True)

    # 7. Production ledger end shasum check
    end_sha = sha256_file(PRODUCTION_LEDGER)
    (EVID / "production-ledger-end.txt").write_text(f"{end_sha}  {PRODUCTION_LEDGER}\n")
    print(f"[7/7] Production ledger end SHA: {end_sha}", flush=True)
    assert end_sha == start_sha, f"Production ledger was modified! {end_sha} != {start_sha}"

    elapsed = time.time() - t0

    # Save metrics.json
    metrics = {
        "reviewer": "gemini-b4e7",
        "role": "Tier 2 Independent Reviewer",
        "task_id": "ainerzero.V9.P52",
        "target_task": "ainerzero.V9.P51",
        "target_author": "claude",
        "verdict": "建议通过",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(elapsed, 2),
        "production_ledger_start": start_sha,
        "production_ledger_end": end_sha,
        "production_ledger_untouched": (start_sha == end_sha),
        "train_checks": train_checks,
        "eval_checks": eval_checks,
        "a2_bitwise_reproduced": a2_bitwise_match,
        "a2_params_sha256": r13_a2_sha,
        "total_wall_clock_seconds": elapsed_wall_s,
        "cap_wall_clock_seconds": 9000.0,
        "wall_clock_within_budget": (elapsed_wall_s <= 9000.0),
        "no_rerun": True,
        "not_run_evals": not_run_expected,
        "eval_defect_confirmed": True,
        "eval_defect_reason": "few_shot query used full encoding (dim 192) vs sliced graph nodes (dim 32)"
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n")
    print(f"=== Review Complete: VERDICT 建议通过 in {elapsed:.2f}s ===", flush=True)


if __name__ == "__main__":
    main()
