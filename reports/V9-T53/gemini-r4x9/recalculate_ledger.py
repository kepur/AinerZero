#!/usr/bin/env python3
"""Independent recalculation of DA3 line-wide ledger from runs.db copy.

Steps:
1. Verify SHA256 of production runs.db.
2. Copy runs.db to local working directory if not already copied.
3. Open local copy with URI mode=ro.
4. Query all runs with config_json.model starting with 'da3'.
5. Aggregate views and active_seconds; group by task.
6. Verify against proposal.json ledger_by_task_2026_10_28.
7. Verify production runs.db SHA256 remained completely untouched.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LOG_FILE = HERE / "logs" / "recalculate_ledger.log"

PROD_DB = REPO / "artifacts" / "v9" / "teachers" / "benchmark" / "runs.db"
LOCAL_DB = HERE / "runs.db"
PROPOSAL_PATH = REPO / "reports" / "V9-T28" / "r2" / "proposal.json"


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    log = []
    log.append("=== Independent Recalculation of DA3 Line-Wide Ledger ===")

    # 1. Production DB SHA before
    sha_prod_before = sha256_of_file(PROD_DB)
    log.append(f"Production runs.db SHA256 before: {sha_prod_before}")

    # 2. Ensure local copy
    shutil.copy2(PROD_DB, LOCAL_DB)
    sha_local = sha256_of_file(LOCAL_DB)
    log.append(f"Local copy runs.db SHA256: {sha_local}")
    assert sha_prod_before == sha_local, "Local copy SHA256 mismatch with production!"

    # 3. Read proposal.json expected ledger
    proposal = json.loads(PROPOSAL_PATH.read_text(encoding="utf-8"))
    va = proposal["budget"]["view_accounting"]
    expected_ledger = va["ledger_by_task_2026_10_28"]
    expected_total_views = va["ledger_views_used_before_run"]
    expected_total_wall_s = proposal["budget"]["wall_accounting"]["ledger_reserved_s"]

    log.append(f"Expected total views from proposal: {expected_total_views}")
    log.append(f"Expected total active_seconds from proposal: {expected_total_wall_s}")
    log.append(f"Expected ledger_by_task_2026_10_28:\n{json.dumps(expected_ledger, indent=2)}")

    # 4. Open local DB mode=ro
    uri = f"file:{LOCAL_DB.resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    cur = con.cursor()

    rows = cur.execute(
        "SELECT run_id, state, active_seconds, config_json, created_at, updated_at FROM runs ORDER BY created_at ASC"
    ).fetchall()

    da3_runs = []
    total_views = 0
    total_active_seconds = 0.0
    by_task: dict[str, dict] = {}

    log.append(f"\nScanning {len(rows)} total runs in database...")
    for run_id, state, active_s, c_json, c_at, u_at in rows:
        cfg = json.loads(c_json)
        model = str(cfg.get("model", ""))
        if model.startswith("da3"):
            views = cfg.get("views", 0)
            task = cfg.get("task", "<unknown_task>")
            da3_runs.append({
                "run_id": run_id,
                "task": task,
                "model": model,
                "state": state,
                "views": views,
                "active_seconds": active_s,
                "created_at": c_at,
            })
            total_views += views
            total_active_seconds += float(active_s)
            by_task.setdefault(task, {"views": 0, "active_seconds": 0.0, "runs": []})
            by_task[task]["views"] += views
            by_task[task]["active_seconds"] += float(active_s)
            by_task[task]["runs"].append(run_id)

    con.close()

    log.append(f"Found {len(da3_runs)} runs matching config_json.model starting with 'da3':")
    for r in da3_runs:
        log.append(f"  - run_id: {r['run_id'][:12]}... | task: {r['task']:<22} | views: {r['views']:>2} | active_s: {r['active_seconds']:>5.1f} | state: {r['state']}")

    log.append("\nAggregated totals across all DA3 runs:")
    log.append(f"  Calculated total views: {total_views}")
    log.append(f"  Calculated total active_seconds: {total_active_seconds:.1f}")

    # Per task comparison
    summary_by_task = {}
    for t, data in sorted(by_task.items()):
        summary_by_task[t] = {
            "views": data["views"],
            "active_seconds": round(data["active_seconds"], 1),
        }
    log.append(f"\nCalculated ledger by task:\n{json.dumps(summary_by_task, indent=2)}")

    # Verification assertions
    assert total_views == 199, f"Total views mismatch: {total_views} != 199"
    assert total_views == expected_total_views, f"Total views mismatch with proposal: {total_views} != {expected_total_views}"
    assert total_active_seconds == 1320.0, f"Total active_seconds mismatch: {total_active_seconds} != 1320.0"
    assert total_active_seconds == expected_total_wall_s, f"Total active_seconds mismatch with proposal: {total_active_seconds} != {expected_total_wall_s}"

    assert summary_by_task == expected_ledger, (
        f"By-task breakdown does not match expected!\nCalculated: {summary_by_task}\nExpected: {expected_ledger}"
    )
    log.append("\nALL AGGREGATIONS AND PER-TASK BREAKDOWNS MATCH PROPOSAL EXACTLY.")

    # 5. Production DB SHA after
    sha_prod_after = sha256_of_file(PROD_DB)
    log.append(f"\nProduction runs.db SHA256 after: {sha_prod_after}")
    assert sha_prod_before == sha_prod_after, "FATAL: Production runs.db SHA256 changed during read!"
    log.append("Production runs.db SHA256 strictly preserved (zero modifications).")

    output_text = "\n".join(log)
    print(output_text)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(output_text + "\n", encoding="utf-8")
    print("\nRECALCULATE LEDGER STATUS: PASS")


if __name__ == "__main__":
    main()
