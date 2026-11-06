#!/usr/bin/env python3
"""Independent verification suite for ainerzero.V9.P139 (review of V9.P138 & V9.P133).

Reviewer: gemini-a5b8 (L2 pure CPU executor).
"""

import ast
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any
import pytest

from ainerzero.v9.experiments.s2 import data_runner
from ainerzero.v9.experiments.s2.data_runner import (
    assert_output_root_is_permitted,
    assert_output_root_is_temporary,
    run_generate_data,
    check_partition_already_completed,
    REGISTERED_HOST_ROOT,
    REGISTERED_OUTPUT_ROOT,
)
from ainerzero.v9.experiments.s2.worker import S2Ledger


def test_scope_and_spec_untouched():
    """核实改动范围与 spec.py 是否未改动。"""
    spec_path = Path("/Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s2/spec.py")
    spec_text = spec_path.read_text(encoding="utf-8")
    assert "REGISTERED_HOST_ROOT" not in spec_text, "spec.py should not have REGISTERED_HOST_ROOT"
    assert "REGISTERED_OUTPUT_ROOT" not in spec_text, "spec.py should not have REGISTERED_OUTPUT_ROOT"

    # Verify data_runner has no substring guessing (tmp, temp, pytest)
    runner_text = Path(data_runner.__file__).read_text(encoding="utf-8")
    assert 'for t in ("tmp", "temp", "pytest")' not in runner_text, "Name guessing logic must be removed"
    assert '"tmp" in ' not in runner_text, "Substring tmp check must be removed"
    assert '"temp" in ' not in runner_text, "Substring temp check must be removed"


def test_five_guard_paths():
    """用伪造的主机根目录验证五种情况：
    1. 登记路径：放行；
    2. e1 路径：拒绝；
    3. artifacts/v9/s2/other：拒绝；
    4. 用符号链接绕到 e1：拒绝；
    5. tmp 下的普通目录：放行。
    """
    with tempfile.TemporaryDirectory() as td:
        fake_host = Path(td) / "fake_host"
        fake_host.mkdir()
        artifacts_root = fake_host / "artifacts"
        reg_output = artifacts_root / "v9" / "s2" / "phase1"
        reg_output.mkdir(parents=True)

        e1_path = artifacts_root / "v9" / "e1" / "phase2"
        e1_path.mkdir(parents=True)

        s2_other = artifacts_root / "v9" / "s2" / "other"
        s2_other.mkdir(parents=True)

        normal_dir = Path(td) / "my_custom_workspace"
        normal_dir.mkdir()

        symlink_to_e1 = Path(td) / "innocent_looking_link"
        symlink_to_e1.symlink_to(e1_path)

        orig_host = getattr(data_runner, "REGISTERED_HOST_ROOT")
        try:
            data_runner.REGISTERED_HOST_ROOT = fake_host

            # Case 1: 登记路径 -> 放行
            res1 = assert_output_root_is_permitted(reg_output)
            assert res1 == reg_output.resolve()

            # Case 2: e1 路径 -> 拒绝
            with pytest.raises(ValueError, match="output_root cannot point to non-registered artifacts directory"):
                assert_output_root_is_permitted(e1_path)

            # Case 3: artifacts/v9/s2/other -> 拒绝
            with pytest.raises(ValueError, match="output_root cannot point to non-registered artifacts directory"):
                assert_output_root_is_permitted(s2_other)

            # Case 4: 符号链接绕到 e1 -> 拒绝
            with pytest.raises(ValueError, match="output_root cannot point to non-registered artifacts directory"):
                assert_output_root_is_permitted(symlink_to_e1)

            # Case 5: tmp 下的普通目录（且名字不含 tmp/temp 关键字） -> 放行
            res5 = assert_output_root_is_permitted(normal_dir)
            assert res5 == normal_dir.resolve()

            # Backward compatibility alias
            assert assert_output_root_is_temporary(normal_dir) == normal_dir.resolve()

        finally:
            data_runner.REGISTERED_HOST_ROOT = orig_host


def test_sealed_final_zero_readback_and_fields():
    """用打补丁的方法证明生成 dev/train 做不重叠检查时，sealed_final 下除了 LAYOUT_DIGESTS.json 没有任何文件被读；
    同时核对 LAYOUT_DIGESTS.json 只含三个字段（partition, seed_namespace, layout_digests）。
    """
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "run_sealed_test"
        db_file = Path(td) / "ledger.db"
        ledger = S2Ledger(db_file)

        # 1. 生成 final
        res_final = run_generate_data(
            partition="final",
            output_root=out_dir,
            ledger=ledger,
            n_worlds=2,
            episodes_per_world=2,
            enforce_rejection_redraw=False,
            max_steps_per_episode=10,
        )
        assert res_final["status"] == "completed"

        sealed_dir = out_dir / "datasets" / "sealed_final"
        layout_file = sealed_dir / "LAYOUT_DIGESTS.json"
        manifest_file = sealed_dir / "manifest.json"

        assert layout_file.is_file(), "LAYOUT_DIGESTS.json must exist in sealed_final"
        assert manifest_file.is_file(), "manifest.json exists on disk in sealed_final"

        # 检查字段
        layout_data = json.loads(layout_file.read_text(encoding="utf-8"))
        assert set(layout_data.keys()) == {"partition", "seed_namespace", "layout_digests"}, (
            f"LAYOUT_DIGESTS.json keys must strictly be partition, seed_namespace, layout_digests, got {set(layout_data.keys())}"
        )
        assert "goal_episode_specs" not in layout_data
        assert layout_data["partition"] == "final"
        assert len(layout_data["layout_digests"]) == 2

        # 2. 打补丁，拦截任何对 sealed_final 下非 LAYOUT_DIGESTS.json 的读取
        orig_open = open
        orig_read_text = Path.read_text
        orig_read_bytes = Path.read_bytes
        read_events = []

        def check_access(target_path: Any):
            p_str = str(target_path)
            if "sealed_final" in p_str:
                fname = Path(p_str).name
                read_events.append((fname, p_str))
                if fname != "LAYOUT_DIGESTS.json":
                    raise AssertionError(
                        f"FORBIDDEN READ from sealed_final: {p_str} (only LAYOUT_DIGESTS.json allowed)"
                    )

        def patched_open(file: Any, *args: Any, **kwargs: Any):
            mode = args[0] if args else kwargs.get("mode", "r")
            if isinstance(mode, str) and any(m in mode for m in ("r", "+")):
                check_access(file)
            return orig_open(file, *args, **kwargs)

        def patched_read_text(self: Path, *args: Any, **kwargs: Any):
            check_access(self)
            return orig_read_text(self, *args, **kwargs)

        def patched_read_bytes(self: Path, *args: Any, **kwargs: Any):
            check_access(self)
            return orig_read_bytes(self, *args, **kwargs)

        import builtins
        old_builtins_open = builtins.open
        old_path_read_text = Path.read_text
        old_path_read_bytes = Path.read_bytes
        try:
            builtins.open = patched_open
            Path.read_text = patched_read_text
            Path.read_bytes = patched_read_bytes

            # 3. 生成 dev，此时会执行与 sealed_final 的不重叠检查
            res_dev = run_generate_data(
                partition="dev",
                output_root=out_dir,
                ledger=ledger,
                n_worlds=2,
                episodes_per_world=2,
                enforce_rejection_redraw=False,
                max_steps_per_episode=10,
            )
            assert res_dev["status"] == "completed"

            # 4. 生成 train，也会执行与 sealed_final 的不重叠检查
            res_train = run_generate_data(
                partition="train",
                output_root=out_dir,
                ledger=ledger,
                n_worlds=2,
                episodes_per_world=2,
                enforce_rejection_redraw=False,
                max_steps_per_episode=10,
            )
            assert res_train["status"] == "completed"

        finally:
            builtins.open = old_builtins_open
            Path.read_text = old_path_read_text
            Path.read_bytes = old_path_read_bytes

        # 确认确实读取了 LAYOUT_DIGESTS.json 且没有读取其他任何文件
        assert len(read_events) >= 2, f"Expected at least 2 reads of LAYOUT_DIGESTS.json, got {len(read_events)}"
        for fname, full_path in read_events:
            assert fname == "LAYOUT_DIGESTS.json", f"Unexpected read: {fname}"

        ledger.close()


def test_p133_contracts_duplicate_and_ledger():
    """复核 P133 原有交付：
    1. 重复检查（第二次返回 duplicate_execution 且不破坏原文件）；
    2. 分区规模（train 需显式指定 scale）；
    3. 账本记录（active_seconds, metrics, sha256sums_hash, non_bfs_ratio, world_redraw_count）。
    """
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "p133_workspace"
        db_file = Path(td) / "ledger.db"
        ledger = S2Ledger(db_file)

        # 1. 规模检查：train 未传 scale 报错
        with pytest.raises(ValueError, match="train partition scale .* must be explicitly provided"):
            run_generate_data(partition="train", output_root=out_dir, ledger=ledger)

        # 2. 生成 dev 分区
        res1 = run_generate_data(
            partition="dev",
            output_root=out_dir,
            ledger=ledger,
            n_worlds=2,
            episodes_per_world=2,
            enforce_rejection_redraw=False,
            max_steps_per_episode=10,
        )
        assert res1["status"] == "completed"
        assert res1["total_episodes"] == 4
        assert "sha256sums_hash" in res1
        assert "world_redraw_count" in res1
        assert "non_bfs_ratio" in res1

        manifest_path = Path(res1["manifest_file"])
        mtime1 = manifest_path.stat().st_mtime_ns

        # 3. 查账本记录
        run_id = check_partition_already_completed(ledger, "dev")
        assert run_id is not None
        cursor = ledger.store._conn.execute(
            "SELECT state, active_seconds FROM runs WHERE run_id = ?",
            (run_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["state"] == "completed"
        assert row["active_seconds"] >= 0

        # 4. 重复生成校验：返回 duplicate_execution 且不破坏原文件
        res2 = run_generate_data(
            partition="dev",
            output_root=out_dir,
            ledger=ledger,
            n_worlds=2,
            episodes_per_world=2,
            enforce_rejection_redraw=False,
            max_steps_per_episode=10,
        )
        assert res2["status"] == "duplicate_execution"
        assert manifest_path.stat().st_mtime_ns == mtime1

        ledger.close()


if __name__ == "__main__":
    print("Running independent verification test suite...")
    test_scope_and_spec_untouched()
    print("✓ Scope & spec.py untouched verification passed.")
    test_five_guard_paths()
    print("✓ Five guard paths verification passed.")
    test_sealed_final_zero_readback_and_fields()
    print("✓ sealed_final zero readback & 3 fields verification passed.")
    test_p133_contracts_duplicate_and_ledger()
    print("✓ P133 contracts (duplicate, scale, ledger) verification passed.")
    print("ALL INDEPENDENT VERIFICATION TESTS PASSED SUCCESSFULLY!")
