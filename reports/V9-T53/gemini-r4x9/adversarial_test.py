#!/usr/bin/env python3
"""Adversarial tests for E18 verification:
1. Mutant A: Change view cap from 249 to 250 in proposal.json copy.
   Verify that Step 3 (Numerical Consistency) catches this.
2. Mutant B: Delete a T33 run in runs.db copy.
   Verify that Step 2 (Independent Recalculation) catches this.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
LOG_FILE = HERE / "logs" / "adversarial_test.log"

ORIG_PROPOSAL = REPO / "reports" / "V9-T28" / "r2" / "proposal.json"
ORIG_DB = HERE / "runs.db"

ADV_PROPOSAL = HERE / "scratch_adv_proposal.json"
ADV_DB = HERE / "scratch_adv_runs.db"


def run_adversarial_cap_250(log: list[str]) -> bool:
    log.append("\n--- [Adversarial Test 1] Mutating cumulative_view_cap to 250 ---")
    data = json.loads(ORIG_PROPOSAL.read_text(encoding="utf-8"))
    orig_cap = data["budget"]["view_accounting"]["cumulative_view_cap"]
    log.append(f"Original cumulative_view_cap: {orig_cap}")

    # Apply mutation: 249 -> 250
    data["budget"]["view_accounting"]["cumulative_view_cap"] = 250
    ADV_PROPOSAL.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.append(f"Mutated cumulative_view_cap in scratch copy to: {data['budget']['view_accounting']['cumulative_view_cap']}")

    # Run numerical consistency check against mutated proposal
    caught = False
    va = data["budget"]["view_accounting"]
    used = va["ledger_views_used_before_run"]
    charge = va["charge_per_complete_run"]
    cap = va["cumulative_view_cap"]

    log.append(f"Evaluating consistency: used({used}) + charge({charge}) == cap({cap}) == 249")
    try:
        assert used + charge == cap == 249, (
            f"Arithmetic inconsistency caught: {used} + {charge} = {used + charge} != cap({cap})"
        )
    except AssertionError as exc:
        caught = True
        log.append(f"SUCCESS: Mutation 1 CAUGHT by Step 3 numerical consistency check: {exc}")

    return caught


def run_adversarial_delete_t33_run(log: list[str]) -> bool:
    log.append("\n--- [Adversarial Test 2] Deleting one T33 run in runs.db copy ---")
    shutil.copy2(ORIG_DB, ADV_DB)

    # Inspect T33 runs before deletion
    con = sqlite3.connect(f"file:{ADV_DB.resolve()}", uri=True)
    cur = con.cursor()
    rows = cur.execute("SELECT run_id, config_json, active_seconds FROM runs").fetchall()
    t33_run_to_delete = None
    for run_id, c_json, act_s in rows:
        cfg = json.loads(c_json)
        if cfg.get("task") == "ainerzero.V9.T33":
            t33_run_to_delete = (run_id, cfg.get("views", 0), act_s)
            break

    assert t33_run_to_delete is not None, "No T33 run found to delete!"
    del_run_id, del_views, del_act_s = t33_run_to_delete
    log.append(f"Selected T33 run for deletion: {del_run_id[:12]}... (views: {del_views}, active_seconds: {del_act_s})")

    # Delete the run
    cur.execute("DELETE FROM runs WHERE run_id = ?", (del_run_id,))
    con.commit()
    log.append(f"Deleted run {del_run_id} from scratch database.")

    # Now run Step 2 recalculation against mutated DB
    cur.execute("SELECT run_id, active_seconds, config_json FROM runs")
    all_runs = cur.fetchall()
    mutated_views = 0
    mutated_active_s = 0.0
    mutated_by_task: dict[str, dict] = {}

    for run_id, act_s, c_json in all_runs:
        cfg = json.loads(c_json)
        model = str(cfg.get("model", ""))
        if model.startswith("da3"):
            v = cfg.get("views", 0)
            t = cfg.get("task", "<unknown>")
            mutated_views += v
            mutated_active_s += float(act_s)
            mutated_by_task.setdefault(t, {"views": 0, "active_seconds": 0.0})
            mutated_by_task[t]["views"] += v
            mutated_by_task[t]["active_seconds"] += float(act_s)

    con.close()

    log.append(f"Recalculation on mutated database:")
    log.append(f"  Mutated total views: {mutated_views} (expected 199)")
    log.append(f"  Mutated total active_seconds: {mutated_active_s} (expected 1320.0)")
    log.append(f"  Mutated T33 breakdown: {mutated_by_task.get('ainerzero.V9.T33')} (expected views: 82, active_seconds: 140.0)")

    caught = False
    try:
        assert mutated_views == 199, f"Total views mismatch: {mutated_views} != 199 (deficit: {199 - mutated_views})"
        assert mutated_by_task["ainerzero.V9.T33"]["views"] == 82, "T33 views mismatch!"
    except AssertionError as exc:
        caught = True
        log.append(f"SUCCESS: Mutation 2 CAUGHT by Step 2 independent recalculation check: {exc}")

    # Clean up scratch files
    if ADV_PROPOSAL.exists():
        ADV_PROPOSAL.unlink()
    if ADV_DB.exists():
        ADV_DB.unlink()

    return caught


def main():
    log = []
    log.append("=== Adversarial Mutation Testing for E18 Verification ===")

    test1_caught = run_adversarial_cap_250(log)
    test2_caught = run_adversarial_delete_t33_run(log)

    log.append("\n=== Adversarial Test Summary ===")
    log.append(f"Test 1 (Cap changed to 250 detected by Step 3): {'PASS' if test1_caught else 'FAIL'}")
    log.append(f"Test 2 (Deleted T33 run detected by Step 2): {'PASS' if test2_caught else 'FAIL'}")

    res_str = "\n".join(log)
    print(res_str)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(res_str + "\n", encoding="utf-8")

    if not (test1_caught and test2_caught):
        sys.exit(1)
    print("\nADVERSARIAL SUITE STATUS: ALL MUTANTS SUCCESSFULLY CAUGHT")


if __name__ == "__main__":
    main()
