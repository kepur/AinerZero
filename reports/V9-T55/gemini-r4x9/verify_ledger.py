#!/usr/bin/env python3
"""Verification of runs.db ledger:
1. Verify production runs.db SHA256 equals 61242c30...
2. Compare local copy with pre-run backup runs-db-before-override.sqlite3.
3. Verify metadata key t6_views_override_20261028 (new_max_views=249).
4. Verify run a7bcc4c9... (views 50, active_seconds 120, task ainerzero.V9.T6).
5. Verify line-wide DA3 total views == 249 and active_seconds == 1440.0.
6. Verify production runs.db SHA256 strictly preserved.
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
LOG_FILE = HERE / "logs" / "ledger.log"

PROD_DB = REPO / "artifacts" / "v9" / "teachers" / "benchmark" / "runs.db"
BEFORE_DB = REPO / "reports" / "V9-T28" / "registration" / "runs-db-before-override.sqlite3"
LOCAL_DB = HERE / "runs.db"

EXPECTED_PROD_SHA = "61242c30ffb56621615107ce971c2ff7802e3a30b7491294297239df3c3e0d01"
EXPECTED_NEW_RUN_PREFIX = "a7bcc4c9"


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main():
    log = []
    log.append("=== Verification of Central runs.db Ledger ===")

    # 1. Production DB SHA
    sha_prod_before = sha256_of_file(PROD_DB)
    log.append(f"Production runs.db SHA256 before: {sha_prod_before}")
    assert sha_prod_before.startswith("61242c30"), f"Production runs.db SHA256 does not match 61242c30: {sha_prod_before}"
    assert sha_prod_before == EXPECTED_PROD_SHA, f"Production runs.db SHA256 mismatch: {sha_prod_before} vs {EXPECTED_PROD_SHA}"
    log.append("Check passed: Production runs.db matches expected 61242c30... SHA256.")

    # 2. Copy to local
    shutil.copy2(PROD_DB, LOCAL_DB)
    sha_local = sha256_of_file(LOCAL_DB)
    assert sha_local == sha_prod_before

    # 3. Open both with mode=ro
    con_before = sqlite3.connect(f"file:{BEFORE_DB.resolve()}?mode=ro", uri=True)
    con_after = sqlite3.connect(f"file:{LOCAL_DB.resolve()}?mode=ro", uri=True)

    # Metadata check
    meta_before = dict(con_before.execute("SELECT key, value FROM metadata").fetchall())
    meta_after = dict(con_after.execute("SELECT key, value FROM metadata").fetchall())

    new_meta_keys = set(meta_after.keys()) - set(meta_before.keys())
    log.append(f"\nMetadata keys added: {new_meta_keys}")
    assert new_meta_keys == {"t6_views_override_20261028"}, f"Unexpected metadata keys added: {new_meta_keys}"

    override_val_str = meta_after["t6_views_override_20261028"]
    override_val = json.loads(override_val_str)
    log.append(f"Metadata override value:\n{json.dumps(override_val, indent=2, ensure_ascii=False)}")
    assert override_val["new_max_views"] == 249, f"new_max_views != 249 ({override_val['new_max_views']})"
    assert override_val["views_requested"] == 50, f"views_requested != 50 ({override_val['views_requested']})"
    assert override_val["cumulative_wall_cap_s"] == 1440, f"cumulative_wall_cap_s != 1440 ({override_val['cumulative_wall_cap_s']})"
    assert override_val["user_words"] == "Whole line, 249/1440"
    log.append("Check passed: metadata key t6_views_override_20261028 has new_max_views=249.")

    # Runs check
    runs_before = {r[0]: r for r in con_before.execute("SELECT run_id, state, active_seconds, config_json FROM runs").fetchall()}
    runs_after = {r[0]: r for r in con_after.execute("SELECT run_id, state, active_seconds, config_json FROM runs").fetchall()}

    added_run_ids = set(runs_after.keys()) - set(runs_before.keys())
    removed_run_ids = set(runs_before.keys()) - set(runs_after.keys())
    log.append(f"\nRuns added count: {len(added_run_ids)}, removed count: {len(removed_run_ids)}")
    assert len(added_run_ids) == 1, f"Expected exactly 1 new run, got {len(added_run_ids)}"
    assert len(removed_run_ids) == 0, f"Expected 0 removed runs, got {len(removed_run_ids)}"

    new_run_id = list(added_run_ids)[0]
    log.append(f"New run_id: {new_run_id}")
    assert new_run_id.startswith(EXPECTED_NEW_RUN_PREFIX), f"New run_id does not start with {EXPECTED_NEW_RUN_PREFIX}: {new_run_id}"

    new_run_data = runs_after[new_run_id]
    state = new_run_data[1]
    active_s = new_run_data[2]
    cfg = json.loads(new_run_data[3])
    run_views = cfg.get("views")
    run_task = cfg.get("task")
    run_model = cfg.get("model")

    log.append(f"New run details:")
    log.append(f"  state: {state}")
    log.append(f"  active_seconds: {active_s} (Expected: 120.0)")
    log.append(f"  views: {run_views} (Expected: 50)")
    log.append(f"  task: {run_task} (Expected: ainerzero.V9.T6)")
    log.append(f"  model: {run_model} (Expected: da3-all)")

    assert active_s == 120.0, f"active_seconds != 120.0 ({active_s})"
    assert run_views == 50, f"views != 50 ({run_views})"
    assert run_task == "ainerzero.V9.T6", f"task != ainerzero.V9.T6 ({run_task})"
    assert state == "failed", f"state != failed ({state})"
    log.append("Check passed: new run a7bcc4c9... has views=50, active_seconds=120.0, task=ainerzero.V9.T6.")

    # Check prior runs untouched
    for r_id in runs_before:
        assert runs_before[r_id] == runs_after[r_id], f"Prior run {r_id} modified!"
    log.append(f"Check passed: all {len(runs_before)} prior runs are byte-for-byte identical.")

    # 4. Line-wide total DA3 calculation
    total_views = 0
    total_active_seconds = 0.0
    by_task: dict[str, dict] = {}
    da3_run_count = 0

    for r_id, r_tuple in runs_after.items():
        c = json.loads(r_tuple[3])
        m = str(c.get("model", ""))
        if m.startswith("da3"):
            v = c.get("views", 0)
            t = c.get("task", "<unknown>")
            s = float(r_tuple[2])
            total_views += v
            total_active_seconds += s
            by_task.setdefault(t, {"views": 0, "active_seconds": 0.0, "runs": 0})
            by_task[t]["views"] += v
            by_task[t]["active_seconds"] += s
            by_task[t]["runs"] += 1
            da3_run_count += 1

    log.append(f"\nLine-wide DA3 aggregation across {da3_run_count} runs:")
    log.append(f"  Total views: {total_views} (Expected: 249)")
    log.append(f"  Total active_seconds: {total_active_seconds:.1f} (Expected: 1440.0)")
    log.append("  Breakdown by task:")
    for t, data in sorted(by_task.items()):
        log.append(f"    - {t}: views={data['views']}, active_seconds={data['active_seconds']:.1f}, runs={data['runs']}")

    assert total_views == 249, f"Total views != 249 ({total_views})"
    assert total_active_seconds == 1440.0, f"Total active_seconds != 1440.0 ({total_active_seconds})"
    log.append("Check passed: Line-wide DA3 cumulative accounting equals 249 views / 1440.0 s.")

    con_before.close()
    con_after.close()

    # 5. Production DB SHA after
    sha_prod_after = sha256_of_file(PROD_DB)
    log.append(f"\nProduction runs.db SHA256 after check: {sha_prod_after}")
    assert sha_prod_before == sha_prod_after, "FATAL: Production runs.db SHA256 altered during review!"
    log.append("Check passed: Production runs.db strictly unmodified (SHA256 preserved).")

    out_str = "\n".join(log)
    print(out_str)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.write_text(out_str + "\n", encoding="utf-8")
    print("\nLEDGER VERIFICATION STATUS: PASS")


if __name__ == "__main__":
    main()
