#!/usr/bin/env python3
"""Independent verification for requirement 3: duplicate, disjointness, and output_root."""

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from ainerzero.v9.experiments.s2.data_runner import (
    assert_output_root_is_temporary,
    run_generate_data,
)
from ainerzero.v9.experiments.s2.worker import S2Ledger


def main() -> None:
    print("=== Independent Verification for P133/P134 ===")

    # 1. output_root rejection of production paths
    prod_path = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/fake_prod")
    try:
        assert_output_root_is_temporary(prod_path)
        raise AssertionError("Failed to reject production artifacts path!")
    except ValueError as e:
        print(f"[PASS] Correctly rejected production artifacts: {e}")

    non_temp_path = Path("/Users/mac/Desktop/test_out")
    try:
        assert_output_root_is_temporary(non_temp_path)
        raise AssertionError("Failed to reject non-temp path!")
    except ValueError as e:
        print(f"[PASS] Correctly rejected non-temporary path: {e}")

    with tempfile.TemporaryDirectory(prefix="test_p135_verify_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        db_file = tmp_dir / "ledger.sqlite3"
        ledger = S2Ledger(db_file)

        out_root = tmp_dir / "out"

        # 2. First generation: dev partition (2 worlds x 2 episodes, max_steps=15)
        print("\n--- Running initial generation (dev partition) ---")
        res1 = run_generate_data(
            partition="dev",
            output_root=out_root,
            ledger=ledger,
            n_worlds=2,
            episodes_per_world=2,
            max_steps_per_episode=15,
            enforce_rejection_redraw=False,
        )
        assert res1["status"] == "completed"
        print(f"[PASS] First generation completed: {res1['status']}, sha={res1['sha256sums_hash'][:16]}...")

        # Stat of files
        dev_manifest = out_root / "datasets" / "dev" / "manifest.json"
        assert dev_manifest.is_file()
        mtime1 = dev_manifest.stat().st_mtime_ns
        content1 = dev_manifest.read_bytes()

        # 3. Duplicate generation attempt: must return duplicate_execution and preserve files
        print("\n--- Running duplicate generation attempt ---")
        res2 = run_generate_data(
            partition="dev",
            output_root=out_root,
            ledger=ledger,
            n_worlds=2,
            episodes_per_world=2,
            max_steps_per_episode=15,
            enforce_rejection_redraw=False,
        )
        assert res2["status"] == "duplicate_execution", f"Expected duplicate_execution, got {res2}"
        mtime2 = dev_manifest.stat().st_mtime_ns
        content2 = dev_manifest.read_bytes()
        assert mtime1 == mtime2, "File mtime modified during duplicate run!"
        assert content1 == content2, "File content modified during duplicate run!"
        print(f"[PASS] Duplicate generation refused: {res2['status']}, files unchanged (mtime/bytes match).")

        # 4. Disjointness check: shared seed_namespace must fail
        print("\n--- Running shared seed namespace collision test ---")
        shared_ns = "shared_seed_test_123"
        out_shared = tmp_dir / "out_shared"
        res_a = run_generate_data(
            partition="dev",
            output_root=out_shared,
            seed_namespace=shared_ns,
            n_worlds=2,
            episodes_per_world=2,
            max_steps_per_episode=15,
            enforce_rejection_redraw=False,
        )
        assert res_a["status"] == "completed"

        try:
            run_generate_data(
                partition="train",
                output_root=out_shared,
                seed_namespace=shared_ns,
                n_worlds=2,
                episodes_per_world=2,
                max_steps_per_episode=15,
                enforce_rejection_redraw=False,
            )
            raise AssertionError("Failed to reject shared seed namespace!")
        except ValueError as e:
            print(f"[PASS] Shared seed namespace correctly raised error: {e}")

        ledger.close()

    print("\n[ALL CHECKS PASSED SUCCESSFULLY]")


if __name__ == "__main__":
    main()
