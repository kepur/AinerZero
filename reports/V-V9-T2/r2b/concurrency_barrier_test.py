#!/usr/bin/env python3
"""Dual-process Barrier concurrency verification for ainerzero.V9.T2 r2.

Verifies the 3 concurrency scenarios across 20 rounds each (total 60 Barrier rounds):
1) Cross-partition writes for same cache_key
2) Conflicting outputs for same cache_key
3) Same entry_id with different content (tampered license)
"""

import copy
import json
import multiprocessing as mp
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
sys.path.insert(0, str(ROOT / "src"))

import ainerzero.v9.teachers.cache as cm


def _worker_write_blob(root_str, args, data, q, barrier):
    import sys
    sys.path.insert(0, "/Users/mac/AinerWorkFlow/AinerZero/src")
    import ainerzero.v9.teachers.cache as c
    c.set_cache_root(Path(root_str))
    barrier.wait()
    try:
        c.write_blob(output_data=data, **args)
        q.put(("ok", None))
    except Exception as exc:
        q.put(("err", f"{type(exc).__name__}: {exc}"))


def _worker_write_entry(root_str, blob_args, entry, q, barrier):
    import sys
    sys.path.insert(0, "/Users/mac/AinerWorkFlow/AinerZero/src")
    import ainerzero.v9.teachers.cache as c
    c.set_cache_root(Path(root_str))
    # Pre-seed blob
    try:
        c.write_blob(output_data=b"shared_output_bytes", **blob_args)
    except Exception:
        pass
    barrier.wait()
    try:
        c.write_entry(entry)
        q.put(("ok", entry["source"]["partition"]))
    except Exception as exc:
        q.put(("err", f"{type(exc).__name__}: {exc}"))


def _worker_write_entry_conflict(root_str, blob_args, entry, q, barrier):
    import sys
    sys.path.insert(0, "/Users/mac/AinerWorkFlow/AinerZero/src")
    import ainerzero.v9.teachers.cache as c
    c.set_cache_root(Path(root_str))
    # Pre-seed blob
    try:
        c.write_blob(output_data=b"shared_output_bytes", **blob_args)
    except Exception:
        pass
    barrier.wait()
    try:
        c.write_entry(entry)
        q.put(("ok", None))
    except Exception as exc:
        q.put(("err", f"{type(exc).__name__}: {exc}"))


def get_fixtures():
    # Load valid contract baseline to ensure full schema compliance
    base = ROOT / "contracts/v9/examples/teacher_cache_v2"
    store = json.loads((base / "valid/valid_store.json").read_text())
    blob = [r for r in store if r.get("record_type") == "teacher_blob"][0]
    entry = [r for r in store if r.get("record_type") == "teacher_entry"][0]
    
    blob_args = {
        "cache_key": blob["cache_key"],
        "key_material": blob["key_material"],
        "teacher_license": blob["teacher_license"],
        "reproducibility": blob["reproducibility"],
        "output_metadata": {"shape": [64], "dtype": "float32"},
    }
    return blob_args, entry


def test_concurrent_different_outputs(rounds=20):
    ctx = mp.get_context("spawn")
    blob_args, _ = get_fixtures()
    results = []
    both_accepted_count = 0

    for r in range(rounds):
        with tempfile.TemporaryDirectory() as td:
            barrier = ctx.Barrier(2)
            q = ctx.Queue()
            p1 = ctx.Process(
                target=_worker_write_blob,
                args=(td, blob_args, b"OUTPUT_ALPHA_12345", q, barrier),
            )
            p2 = ctx.Process(
                target=_worker_write_blob,
                args=(td, blob_args, b"OUTPUT_BETA_67890", q, barrier),
            )
            p1.start()
            p2.start()
            p1.join(10)
            p2.join(10)

            q_results = [q.get() for _ in range(2)]
            oks = [res for res in q_results if res[0] == "ok"]
            errs = [res for res in q_results if res[0] == "err"]
            if len(oks) == 2:
                both_accepted_count += 1
            results.append({
                "round": r,
                "oks": len(oks),
                "errs": len(errs),
                "err_details": [e[1] for e in errs],
            })

    return {
        "rounds": rounds,
        "both_accepted_count": both_accepted_count,
        "pass": both_accepted_count == 0,
        "results": results,
    }


def test_concurrent_cross_partition(rounds=20):
    ctx = mp.get_context("spawn")
    blob_args, entry = get_fixtures()
    results = []
    both_accepted_count = 0

    for r in range(rounds):
        with tempfile.TemporaryDirectory() as td:
            barrier = ctx.Barrier(2)
            q = ctx.Queue()

            e1 = copy.deepcopy(entry)
            e1["source"]["partition"] = "train"
            e1["entry_id"] = cm.compute_entry_id(e1)

            e2 = copy.deepcopy(entry)
            e2["source"]["partition"] = "development"
            e2["source"]["world_key"] = "test:world-beta"
            e2["entry_id"] = cm.compute_entry_id(e2)

            p1 = ctx.Process(
                target=_worker_write_entry,
                args=(td, blob_args, e1, q, barrier),
            )
            p2 = ctx.Process(
                target=_worker_write_entry,
                args=(td, blob_args, e2, q, barrier),
            )
            p1.start()
            p2.start()
            p1.join(10)
            p2.join(10)

            q_results = [q.get() for _ in range(2)]
            oks = [res for res in q_results if res[0] == "ok"]
            errs = [res for res in q_results if res[0] == "err"]
            if len(oks) == 2:
                both_accepted_count += 1
            results.append({
                "round": r,
                "oks": len(oks),
                "errs": len(errs),
                "err_details": [e[1] for e in errs],
            })

    return {
        "rounds": rounds,
        "both_accepted_count": both_accepted_count,
        "pass": both_accepted_count == 0,
        "results": results,
    }


def test_concurrent_same_entry_id_conflict(rounds=20):
    ctx = mp.get_context("spawn")
    blob_args, entry = get_fixtures()
    results = []
    both_accepted_count = 0

    for r in range(rounds):
        with tempfile.TemporaryDirectory() as td:
            barrier = ctx.Barrier(2)
            q = ctx.Queue()

            e1 = copy.deepcopy(entry)
            e1["license"]["scope"]["train"] = True

            e2 = copy.deepcopy(entry)
            e2["license"]["scope"]["train"] = False
            # entry_id is invariant to license.scope.train change
            assert cm.compute_entry_id(e1) == cm.compute_entry_id(e2)

            p1 = ctx.Process(
                target=_worker_write_entry_conflict,
                args=(td, blob_args, e1, q, barrier),
            )
            p2 = ctx.Process(
                target=_worker_write_entry_conflict,
                args=(td, blob_args, e2, q, barrier),
            )
            p1.start()
            p2.start()
            p1.join(10)
            p2.join(10)

            q_results = [q.get() for _ in range(2)]
            oks = [res for res in q_results if res[0] == "ok"]
            errs = [res for res in q_results if res[0] == "err"]
            if len(oks) == 2:
                both_accepted_count += 1
            results.append({
                "round": r,
                "oks": len(oks),
                "errs": len(errs),
                "err_details": [e[1] for e in errs],
            })

    return {
        "rounds": rounds,
        "both_accepted_count": both_accepted_count,
        "pass": both_accepted_count == 0,
        "results": results,
    }


def main():
    print("Running 20 rounds of concurrent different outputs...")
    out_diff = test_concurrent_different_outputs(20)
    print(f"Diff outputs: both_accepted={out_diff['both_accepted_count']}/20, pass={out_diff['pass']}")

    print("Running 20 rounds of concurrent cross-partition writes...")
    out_cp = test_concurrent_cross_partition(20)
    print(f"Cross-partition: both_accepted={out_cp['both_accepted_count']}/20, pass={out_cp['pass']}")

    print("Running 20 rounds of concurrent same entry_id conflicting content...")
    out_conflict = test_concurrent_same_entry_id_conflict(20)
    print(f"Same entry_id conflict: both_accepted={out_conflict['both_accepted_count']}/20, pass={out_conflict['pass']}")

    all_pass = out_diff["pass"] and out_cp["pass"] and out_conflict["pass"]
    summary = {
        "concurrent_different_outputs_20": out_diff["pass"],
        "concurrent_cross_partition_20": out_cp["pass"],
        "concurrent_same_entry_id_conflict_20": out_conflict["pass"],
        "all_pass": all_pass,
        "details": {
            "different_outputs": out_diff,
            "cross_partition": out_cp,
            "same_entry_conflict": out_conflict,
        },
    }

    out_file = ROOT / "reports/V-V9-T2/r2b/concurrency_barrier_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"Overall concurrency verification: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
