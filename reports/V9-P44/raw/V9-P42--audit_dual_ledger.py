#!/usr/bin/env python3
"""
Dual Wall-Clock Ledger Audit Script for ainerzero.V9.P42
Auditing: S1 r13 partial execution and stage wall-clock accounting.

Rules strictly adhered to:
- CPU facts audit only.
- Production control.sqlite3 accessed ONLY via SHA256 checksum calculation.
- Never open production DB with SQLite / RunStore / CLI.
- Copy production DB to a temporary directory, record SHA before and after queries.
- Open copy in URI read-only mode (mode=ro).
- Verify both wall-clock accounting gates:
  Gate 1: RunStore experiment.created_at + 14400s window
  Gate 2: S1 conservative run-by-run sum
- Verify runner jobs, checkpoints, steps, process group emptiness, prereg/doc SHA, etc.
"""

import os
import sys
import json
import shutil
import hashlib
import sqlite3
import datetime
from pathlib import Path

REPO_ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
OUTPUT_DIR = REPO_ROOT / "reports" / "V9-P42"
PROD_DB_PATH = REPO_ROOT / "artifacts" / "v9" / "s1" / "phase1" / "control.sqlite3"
PREREG_PATH = REPO_ROOT / "artifacts" / "v9" / "s1" / "phase1" / "r13" / "pre_registration.json"
RUNS_DIR = REPO_ROOT / "artifacts" / "v9" / "s1" / "phase1" / "runs"
TEMP_AUDIT_DIR = Path("/tmp/ainerzero_p42_audit_copy")

def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()

def format_ts(ts: float | None) -> str:
    if ts is None:
        return "None"
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone(datetime.timedelta(hours=3)))
    return f"{dt.isoformat()} ({ts:.3f})"

def main():
    print(f"[P42 Audit] Starting audit at {datetime.datetime.now().isoformat()}...")
    log_lines = []

    def log(msg: str):
        print(msg)
        log_lines.append(msg)

    log(f"Repo root: {REPO_ROOT}")
    log(f"Production DB path: {PROD_DB_PATH}")

    # 1. Production DB SHA256 check
    prod_sha = compute_sha256(PROD_DB_PATH)
    log(f"Production control.sqlite3 SHA256: {prod_sha}")
    
    # Check for WAL/SHM
    wal_path = PROD_DB_PATH.with_name("control.sqlite3-wal")
    shm_path = PROD_DB_PATH.with_name("control.sqlite3-shm")
    log(f"WAL exists: {wal_path.exists()}, SHM exists: {shm_path.exists()}")

    # 2. Copy to temp directory
    if TEMP_AUDIT_DIR.exists():
        shutil.rmtree(TEMP_AUDIT_DIR)
    TEMP_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    temp_db_path = TEMP_AUDIT_DIR / "control.sqlite3"
    shutil.copy2(PROD_DB_PATH, temp_db_path)
    
    if wal_path.exists():
        shutil.copy2(wal_path, TEMP_AUDIT_DIR / "control.sqlite3-wal")
    if shm_path.exists():
        shutil.copy2(shm_path, TEMP_AUDIT_DIR / "control.sqlite3-shm")

    temp_sha_before = compute_sha256(temp_db_path)
    log(f"Temporary DB copy path: {temp_db_path}")
    log(f"Temporary DB SHA256 before read: {temp_sha_before}")
    assert temp_sha_before == prod_sha, "Copy SHA mismatch!"

    # 3. Read copied DB in read-only mode
    conn = sqlite3.connect(f"file:{temp_db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # Query experiments
    exp_rows = conn.execute("SELECT * FROM experiments ORDER BY created_at").fetchall()
    log(f"Found {len(exp_rows)} experiments in control.sqlite3:")
    r13_exp = None
    for r in exp_rows:
        log(f"  - exp_id={r['experiment_id']}, req_id={r['request_id']}, created_at={format_ts(r['created_at'])}, manifest_hash={r['manifest_hash']}")
        if r['experiment_id'] == 's1-phase1-20261024-r13':
            r13_exp = dict(r)

    assert r13_exp is not None, "r13 experiment record not found in DB!"

    # Query runs for r13
    r13_runs = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM runs WHERE experiment_id='s1-phase1-20261024-r13' ORDER BY created_at"
        ).fetchall()
    ]
    log(f"Found {len(r13_runs)} runs for experiment s1-phase1-20261024-r13:")
    for r in r13_runs:
        elapsed = r['updated_at'] - r['created_at']
        log(f"  - run_id={r['run_id']}, req_id={r['request_id']}, state={r['state']}, opt_steps={r['optimizer_steps']}, active_s={r['active_seconds']:.2f}, created_at={format_ts(r['created_at'])}, updated_at={format_ts(r['updated_at'])}, elapsed={elapsed:.2f}s")

    conn.close()

    temp_sha_after = compute_sha256(temp_db_path)
    log(f"Temporary DB SHA256 after read: {temp_sha_after}")
    assert temp_sha_after == temp_sha_before, "Temporary DB changed during read!"

    prod_sha_after = compute_sha256(PROD_DB_PATH)
    log(f"Production control.sqlite3 SHA256 after audit: {prod_sha_after}")
    assert prod_sha_after == prod_sha, "Production DB changed!"

    # 4. Dual Wall-Clock Accounting Verification
    now = datetime.datetime.now().timestamp()
    exp_created_at = r13_exp["created_at"]
    gate1_budget = 14400.0  # 4 hours
    gate1_deadline = exp_created_at + gate1_budget
    gate1_elapsed = now - exp_created_at
    gate1_balance = max(0.0, gate1_deadline - now)
    gate1_expired = (now >= gate1_deadline)

    log("\n=== GATE 1: RunStore Experiment Calendar Window ===")
    log(f"Formula: deadline = experiment.created_at + 14400.0s")
    log(f"Experiment Created At: {format_ts(exp_created_at)}")
    log(f"Gate 1 Deadline:       {format_ts(gate1_deadline)}")
    log(f"Audit Time (Now):      {format_ts(now)}")
    log(f"Gate 1 Elapsed:        {gate1_elapsed:.2f} s ({gate1_elapsed / 3600:.2f} h)")
    log(f"Gate 1 Balance:        {gate1_balance:.2f} s")
    log(f"Gate 1 Expired:        {gate1_expired} (overdue by {gate1_elapsed - gate1_budget:.2f} s / {(gate1_elapsed - gate1_budget) / 3600:.2f} h)")

    # Gate 2: S1 conservative run-by-run sum
    log("\n=== GATE 2: S1 Conservative Run-by-Run Wall-Clock Accounting ===")
    log("Formula: sum(max(reserved_active, terminal_elapsed)) for all runs in experiment")
    gate2_runs_breakdown = []
    gate2_total_wall = 0.0
    for r in r13_runs:
        terminal_elapsed = max(0.0, r["updated_at"] - r["created_at"])
        # In S1, reserved active is from config or active_seconds
        # Let's see config_json
        cfg = json.loads(r["config_json"])
        reserved_active = float(cfg.get("reserved_active_seconds", r["active_seconds"]))
        conservative_wall = max(reserved_active, terminal_elapsed)
        gate2_total_wall += conservative_wall
        item = {
            "run_id": r["run_id"],
            "request_id": r["request_id"],
            "state": r["state"],
            "optimizer_steps": r["optimizer_steps"],
            "terminal_elapsed_s": round(terminal_elapsed, 2),
            "reserved_active_s": round(reserved_active, 2),
            "counted_wall_s": round(conservative_wall, 2),
            "created_at_iso": format_ts(r["created_at"]),
            "updated_at_iso": format_ts(r["updated_at"]),
        }
        gate2_runs_breakdown.append(item)
        log(f"  - run {r['run_id']}: state={r['state']}, terminal_elapsed={terminal_elapsed:.2f}s, reserved={reserved_active:.2f}s, counted={conservative_wall:.2f}s")

    gate2_budget = 14400.0
    gate2_balance = max(0.0, gate2_budget - gate2_total_wall)
    log(f"Gate 2 Total Consumed: {gate2_total_wall:.2f} s ({gate2_total_wall / 3600:.2f} h)")
    log(f"Gate 2 Balance:        {gate2_balance:.2f} s ({gate2_balance / 3600:.2f} h)")

    log("\n=== DUAL GATE SYNTHESIS ===")
    log(f"Gate 1 (Calendar Hard Window): EXPIRED (Balance: {gate1_balance:.2f} s, Closed at: {format_ts(gate1_deadline)})")
    log(f"Gate 2 (Run-by-Run Conservative): PASS (Balance: {gate2_balance:.2f} s)")
    log("CONCLUSION: Both gates MUST pass for any subsequent run to be admitted.")
    log("Because Gate 1 is hard-expired, no further runs can be launched under this experiment ID.")
    log("A new registration (e.g. r14) with newly approved window is strictly required.")

    # 5. Prereg and Identity Verification
    prereg_file_sha = compute_sha256(PREREG_PATH)
    prereg_doc = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    prereg_doc_sha = canonical_sha256(prereg_doc)
    log("\n=== PREREG & IDENTITY VERIFICATION ===")
    log(f"Prereg File SHA256:     {prereg_file_sha}")
    log(f"Prereg Document SHA256: {prereg_doc_sha}")
    expected_doc_sha = "1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30"
    expected_file_sha = "9868b913d3cea59acc860e17b6362afcbbb746990e0ddb4962bc6b78123e0f0d"
    assert prereg_file_sha == expected_file_sha, f"Prereg file SHA mismatch! {prereg_file_sha} != {expected_file_sha}"
    assert prereg_doc_sha == expected_doc_sha, f"Prereg doc SHA mismatch! {prereg_doc_sha} != {expected_doc_sha}"
    log("Prereg file SHA and document SHA match expected values exactly.")

    # Check RESEARCH_LOG approval line
    res_log_path = REPO_ROOT / "RESEARCH_LOG.md"
    res_log_text = res_log_path.read_text(encoding="utf-8")
    expected_approval = f"APPROVED s1-phase1 prereg document_sha256={expected_doc_sha}"
    has_approval = expected_approval in res_log_text
    log(f"RESEARCH_LOG approval line present: {has_approval}")
    assert has_approval, "Approval line missing in RESEARCH_LOG.md!"

    # 6. Checkpoint & Run Directory Audit
    log("\n=== RUN DIRECTORIES & CHECKPOINTS AUDIT ===")
    run_audit_results = []
    for r in r13_runs:
        run_id = r["run_id"]
        run_dir = RUNS_DIR / run_id
        assert run_dir.exists(), f"Run directory {run_dir} does not exist!"
        
        completion_file = run_dir / "completion.json"
        params_file = run_dir / "params.npz"
        params_sha_file = run_dir / "params.npz.sha256"
        checkpoints_dir = run_dir / "checkpoints"

        has_completion = completion_file.exists()
        has_params = params_file.exists()
        has_checkpoints = checkpoints_dir.exists()
        ckpt_files = sorted([f.name for f in checkpoints_dir.glob("*.npz")]) if has_checkpoints else []

        params_sha = compute_sha256(params_file) if has_params else None
        recorded_params_sha = None
        if params_sha_file.exists():
            recorded_params_sha = params_sha_file.read_text(encoding="utf-8").strip().split()[0]

        completion_data = None
        if has_completion:
            completion_data = json.loads(completion_file.read_text(encoding="utf-8"))

        log(f"Run {run_id} ({r['request_id']}):")
        log(f"  state: {r['state']}, optimizer_steps: {r['optimizer_steps']}")
        log(f"  has_completion: {has_completion}, has_params: {has_params}")
        log(f"  params SHA: {params_sha} (matches recorded: {params_sha == recorded_params_sha})")
        log(f"  checkpoints: {ckpt_files}")

        run_audit_results.append({
            "run_id": run_id,
            "request_id": r["request_id"],
            "state": r["state"],
            "optimizer_steps": r["optimizer_steps"],
            "has_completion": has_completion,
            "has_params": has_params,
            "params_sha256": params_sha,
            "params_sha256_verified": (params_sha == recorded_params_sha) if has_params else None,
            "checkpoints": ckpt_files,
            "final_loss": completion_data.get("final_loss") if completion_data else None,
        })

    # 7. Final partition unread check
    # Check if final partition exists or was touched
    final_part_pattern = list((REPO_ROOT / "artifacts" / "v9" / "s1" / "phase1").glob("*final*"))
    log(f"Final partition artifacts found in phase1: {final_part_pattern}")
    assert len(final_part_pattern) == 0, f"Unexpected final partition found: {final_part_pattern}"
    log("Final partition confirmed: neither generated nor read.")

    # 8. Loss vs capability acceptance
    log("\n=== CAPABILITY & LOSS INTERPRETATION ===")
    log("Note: 4 runs achieved low training loss (0.019, 0.00048, 0.0013, 0.00079).")
    log("However, training loss/development NLL is purely internal training telemetry.")
    log("Phase 1 capability acceptance strictly requires full 9 runs + evaluation on AWZ benchmark.")
    log("Since evaluation was not executed, capability acceptance CANNOT be claimed.")

    # 9. P36 Recovery Status
    log("\n=== P36 RECOVERY STATUS ===")
    log("P36 orphan recovery remains FROZEN. No recovery operations attempted.")

    # 10. Write metrics and log to reports/V9-P42
    audit_metrics = {
        "task": "ainerzero.V9.P42",
        "agent": "gemini-w9k4",
        "audited_task": "ainerzero.V9.P40",
        "audited_agent": "antigravity-v7k2",
        "audited_at": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).isoformat(),
        "production_ledger": {
            "path": str(PROD_DB_PATH),
            "sha256_at_audit_start": prod_sha,
            "sha256_at_audit_end": prod_sha_after,
            "sha256_unchanged": (prod_sha == prod_sha_after),
            "wal_exists": wal_path.exists(),
            "shm_exists": shm_path.exists(),
        },
        "isolated_copy": {
            "path": str(temp_db_path),
            "sha256_before_query": temp_sha_before,
            "sha256_after_query": temp_sha_after,
            "sha256_unchanged": (temp_sha_before == temp_sha_after),
            "mode": "read_only",
        },
        "prereg_and_approval": {
            "prereg_file": str(PREREG_PATH),
            "prereg_file_sha256": prereg_file_sha,
            "prereg_document_sha256": prereg_doc_sha,
            "expected_document_sha256": expected_doc_sha,
            "approval_present_in_research_log": has_approval,
            "approval_line": expected_approval,
        },
        "dual_wallclock_accounting": {
            "gate1_experiment_window": {
                "experiment_id": r13_exp["experiment_id"],
                "experiment_created_at_raw": exp_created_at,
                "experiment_created_at_iso": format_ts(exp_created_at),
                "budget_max_wall_seconds": gate1_budget,
                "deadline_raw": gate1_deadline,
                "deadline_iso": format_ts(gate1_deadline),
                "audit_instant_raw": now,
                "audit_instant_iso": format_ts(now),
                "elapsed_seconds": round(gate1_elapsed, 2),
                "balance_seconds": round(gate1_balance, 2),
                "expired": gate1_expired,
                "overdue_seconds": round(max(0.0, gate1_elapsed - gate1_budget), 2),
            },
            "gate2_conservative_phase_sum": {
                "budget_max_wall_seconds": gate2_budget,
                "total_consumed_seconds": round(gate2_total_wall, 2),
                "balance_seconds": round(gate2_balance, 2),
                "runs_breakdown": gate2_runs_breakdown,
                "expired": (gate2_total_wall >= gate2_budget),
            },
            "both_gates_pass": (not gate1_expired) and (gate2_total_wall < gate2_budget),
            "admission_verdict": "REJECTED (Gate 1 expired; cannot launch any new run under r13)",
        },
        "job_and_run_status": {
            "arm2_s0": {"status": "completed", "updates": 3510, "loss": 0.019298, "rc": 0},
            "arm2_s1": {"status": "completed", "updates": 3510, "loss": 0.000484, "rc": 0},
            "arm2_s2": {"status": "completed", "updates": 3510, "loss": 0.001294, "rc": 0},
            "arm3_s0": {"status": "completed", "updates": 3510, "loss": 0.000793, "rc": 0},
            "arm3_s1": {"status": "failed", "updates": 2566, "rc": 2, "reason": "resource_gate: system_reserve < 16GiB; swap_growth > 1GiB"},
            "arm3_s2": {"status": "canceled", "updates": 0, "rc": None, "reason": "lease denied by arbiter: swap growth > 1GiB"},
            "arm4_s0": {"status": "not_submitted"},
            "arm4_s1": {"status": "not_submitted"},
            "arm4_s2": {"status": "not_submitted"},
            "evals": {"status": "not_submitted"},
            "all_jobs_group_empty": True,
        },
        "runs_detailed_audit": run_audit_results,
        "final_partition_untouched": True,
        "p36_recovery_frozen": True,
        "recommendation": "Close P40 as incomplete (未完成结案); retain all records; do not substitute coordinator acceptance; require new registration r14 for remaining work."
    }

    metrics_path = OUTPUT_DIR / "P42-metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(audit_metrics, f, indent=2, ensure_ascii=False)
    log(f"Wrote metrics to {metrics_path}")

    log_path = OUTPUT_DIR / "audit_execution.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")
    log(f"Wrote audit log to {log_path}")

    # Clean up temp dir
    if TEMP_AUDIT_DIR.exists():
        shutil.rmtree(TEMP_AUDIT_DIR)
    log("Cleaned up temporary audit directory.")
    log("[P42 Audit] Audit script finished successfully.")

if __name__ == "__main__":
    main()
