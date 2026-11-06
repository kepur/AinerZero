#!/usr/bin/env python3
"""Independent Review Test: Real Ledger Zero Modification & WAL-only completed run visibility.

Covers Requirements 2 & 3:
1. Zero Modification:
   - Creates a protected SQLite database with active WAL and SHM files in a dedicated directory.
   - Measures exact stat (st_mtime_ns, st_size, st_ino) and SHA256 of main db, -wal, and -shm.
   - Measures directory entry list.
   - Calls worker.ledger_read_snapshot and worker.check_cell_already_completed.
   - Asserts 100% byte-for-byte and stat-for-stat identity on all three files.
   - Asserts 0 new files created in ledger directory.
2. Complete WAL State Visibility:
   - Configures WAL autocheckpoint=0 so completed run resides exclusively in the WAL file.
   - Asserts WAL file exists and contains data.
   - Calls worker.ledger_read_snapshot and worker.check_cell_already_completed.
   - Asserts completed run is accurately observed.
"""

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# Find repo root dynamically relative to __file__ or cwd
if "ainerzero" not in sys.modules:
    REPO_ROOT = Path(__file__).resolve().parent
    while REPO_ROOT != REPO_ROOT.parent and not (REPO_ROOT / "src" / "ainerzero").is_dir():
        REPO_ROOT = REPO_ROOT.parent
    if (REPO_ROOT / "src").is_dir() and str(REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src"))
else:
    REPO_ROOT = Path(".").resolve()

from ainerzero.v9.experiments.s2 import worker


def get_file_stat_and_sha(p: Path) -> tuple[int, int, int, str]:
    st = p.stat()
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    return (st.st_mtime_ns, st.st_size, st.st_ino, sha)


def test_independent_zero_modification(tmp_path: Path | None = None) -> dict:
    if tmp_path is None:
        td = tempfile.TemporaryDirectory(prefix="rev_test_zero_mod_")
        target_dir = Path(td.name)
    else:
        td = None
        target_dir = tmp_path

    try:
        ledger_dir = target_dir / "protected_ledger_independent"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / "control.sqlite3"
        wal_path = ledger_dir / "control.sqlite3-wal"
        shm_path = ledger_dir / "control.sqlite3-shm"

        # Hold a live connection in WAL mode to simulate concurrent worker
        conn = sqlite3.connect(ledger_path)
        conn.execute("PRAGMA journal_mode=WAL")

        ledger = worker.S2Ledger(ledger_path)
        r_id = ledger.open_run(mode="train", arm="arm_rev_zero", seed=101, cell_wall_budget=60.0)
        ledger.begin_run(r_id, state="training")
        ledger.store._conn.execute("PRAGMA wal_autocheckpoint=0")
        ledger.complete_run(r_id, active_seconds=5.0)

        assert ledger_path.is_file(), "DB file missing"
        assert wal_path.is_file() and wal_path.stat().st_size > 0, "WAL file missing or empty"
        assert shm_path.is_file(), "SHM file missing"

        pre_dir_files = sorted(f.name for f in ledger_dir.iterdir())
        pre_ledger = get_file_stat_and_sha(ledger_path)
        pre_wal = get_file_stat_and_sha(wal_path)
        pre_shm = get_file_stat_and_sha(shm_path)

        # Call snapshot context manager
        with worker.ledger_read_snapshot(ledger_path) as store:
            assert store is not None, "Snapshot store was None"
            runs = store.list_runs()
            assert len(runs) >= 1, "Expected at least 1 run in snapshot"

        # Call preflight check_cell_already_completed
        is_completed = worker.check_cell_already_completed(
            ledger_path, mode="train", arm="arm_rev_zero", seed=101
        )
        assert is_completed is True, "Expected check_cell_already_completed to return True"

        # Check directory state
        post_dir_files = sorted(f.name for f in ledger_dir.iterdir())
        assert post_dir_files == pre_dir_files, f"Directory files altered: {pre_dir_files} -> {post_dir_files}"

        # Check file stats and sha
        post_ledger = get_file_stat_and_sha(ledger_path)
        post_wal = get_file_stat_and_sha(wal_path)
        post_shm = get_file_stat_and_sha(shm_path)

        assert post_ledger == pre_ledger, f"DB file modified: {pre_ledger} != {post_ledger}"
        assert post_wal == pre_wal, f"WAL file modified: {pre_wal} != {post_wal}"
        assert post_shm == pre_shm, f"SHM file modified: {pre_shm} != {post_shm}"

        ledger.close()
        conn.close()

        return {
            "status": "PASS",
            "dir_files_before": pre_dir_files,
            "dir_files_after": post_dir_files,
            "ledger_stat_match": True,
            "wal_stat_match": True,
            "shm_stat_match": True,
            "sha256_match": True,
        }
    finally:
        if td:
            td.cleanup()


def test_independent_wal_visibility(tmp_path: Path | None = None) -> dict:
    if tmp_path is None:
        td = tempfile.TemporaryDirectory(prefix="rev_test_wal_vis_")
        target_dir = Path(td.name)
    else:
        td = None
        target_dir = tmp_path

    try:
        ledger_dir = target_dir / "wal_only_independent"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / "control.sqlite3"
        wal_path = ledger_dir / "control.sqlite3-wal"

        conn = sqlite3.connect(ledger_path)
        conn.execute("PRAGMA journal_mode=WAL")

        ledger = worker.S2Ledger(ledger_path)
        r_id = ledger.open_run(mode="train", arm="arm_wal_vis", seed=202, cell_wall_budget=120.0)
        ledger.begin_run(r_id, state="training")
        ledger.store._conn.execute("PRAGMA wal_autocheckpoint=0")
        ledger.complete_run(r_id, active_seconds=12.0)

        assert wal_path.is_file() and wal_path.stat().st_size > 0, "WAL file must exist and be non-empty"

        wal_size_during = wal_path.stat().st_size
        assert wal_size_during > 0, f"WAL size must be > 0 during uncheckpointed state, got {wal_size_during}"

        # Verify snapshot sees completed run
        with worker.ledger_read_snapshot(ledger_path) as store:
            assert store is not None, "Snapshot store was None"
            matching = [
                r for r in store.list_runs()
                if r.state == "completed" and r.config_snapshot.get("seed") == 202
            ]
            assert len(matching) == 1, f"Expected 1 completed run with seed 202, found: {len(matching)}"

        # Verify preflight check sees it
        assert worker.check_cell_already_completed(
            ledger_path, mode="train", arm="arm_wal_vis", seed=202
        ) is True, "Preflight check failed to see WAL-only completed run"

        ledger.close()
        conn.close()

        return {
            "status": "PASS",
            "wal_size_bytes_during_test": wal_size_during,
            "wal_only_completed_run_visible": True,
            "preflight_check_passed": True,
        }
    finally:
        if td:
            td.cleanup()


def test_replica_directory_cleaned_up(tmp_path: Path | None = None) -> dict:
    if tmp_path is None:
        td = tempfile.TemporaryDirectory(prefix="rev_test_cleanup_")
        target_dir = Path(td.name)
    else:
        td = None
        target_dir = tmp_path

    try:
        ledger_dir = target_dir / "ledger_cleanup"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / "control.sqlite3"

        ledger = worker.S2Ledger(ledger_path)
        r_id = ledger.open_run(mode="train", arm="arm_cleanup", seed=303, cell_wall_budget=60.0)
        ledger.begin_run(r_id, state="training")
        ledger.complete_run(r_id, active_seconds=3.0)
        ledger.close()

        replica_parent_dir = None
        with worker.ledger_read_snapshot(ledger_path) as store:
            assert store is not None
            assert store.path is not None
            replica_path = store.path
            replica_parent_dir = replica_path.parent
            assert replica_parent_dir.exists(), "Replica temp dir must exist during snapshot read"

        # Upon exit, replica_parent_dir MUST be deleted
        assert not replica_parent_dir.exists(), f"Replica directory {replica_parent_dir} was NOT cleaned up!"

        return {
            "status": "PASS",
            "replica_cleaned": True,
        }
    finally:
        if td:
            td.cleanup()


def main() -> int:
    print("=== Running Independent Zero-Modification & WAL Visibility Tests ===")
    res_zero = test_independent_zero_modification()
    print(f"[PASS] Zero-modification test: {res_zero}")

    res_wal = test_independent_wal_visibility()
    print(f"[PASS] WAL-only visibility test: {res_wal}")

    res_clean = test_replica_directory_cleaned_up()
    print(f"[PASS] Replica directory cleanup test: {res_clean}")

    summary = {
        "zero_modification": res_zero,
        "wal_visibility": res_wal,
        "replica_cleanup": res_clean,
    }
    out_file = REPO_ROOT / "reports" / "V9-S2-P136" / "review" / "zero_mod_and_wal_results.json"
    out_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results written to {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
