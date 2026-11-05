#!/usr/bin/env python3
"""T45 独立探针：验证 worker_action=None 派生 real_pipeline 且 views≠18 时，
即使账本已满（81/82 累计视图），报错也是非标定视图预检拒绝（排在配额检查之前），
并且零扣账、零 worker 启动、零锁文件。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import ainerzero.v9.teachers.da3_controlled as DC
from ainerzero.v9.teachers.da3_controlled import (
    DA3RunSpec,
    BenchmarkRefusalError,
    BenchmarkBudgetRefused,
    REGISTERED_CALIBRATION_VIEWS,
    execute_guarded_da3_benchmark,
    T6_APPROVAL_SECTION,
    T6_APPROVAL_KEYWORD,
    T6_APPROVAL_TARGET,
)

OUT = REPO / "reports/V9-T45/evidence/04-probe-views-81-82.txt"

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def main() -> int:
    log: list[str] = []
    log.append("# T45 视图预检顺序与派生路径探针日志")
    log.append(f"# 仓库：{REPO}")
    log.append("")

    with tempfile.TemporaryDirectory(prefix="t45-probe-") as tmp:
        tmp_path = Path(tmp)
        # 复制真实 runs.db（当前中央账本状态正好为 81 视图 / 82 上限）
        central_db = REPO / "artifacts/v9/teachers/benchmark/runs.db"
        store_copy = tmp_path / "runs.db"
        shutil.copy2(central_db, store_copy)
        lock_copy = tmp_path / "worker.lock"

        # 查询初始账本
        sec_before, views_before = DC.query_t6_ledger_read_only(store_copy)
        effective_max = DC.get_effective_t6_max_views(store_copy)
        db_sha_before = sha256_bytes(store_copy.read_bytes())

        log.append("## 0. 账本初始状态")
        log.append(f"中央账本副本路径: {store_copy}")
        log.append(f"累计预留墙钟: {sec_before:.1f}s")
        log.append(f"累计已用视图: {views_before} / {effective_max} (距上限仅剩 1 视图)")
        log.append(f"账本 SHA256: {db_sha_before}")
        log.append("")

        assert views_before == 81, f"Expected 81, got {views_before}"
        assert effective_max == 82, f"Expected 82, got {effective_max}"

        # 替身探针替换 worker
        worker_calls: list = []
        def spy_worker(*args, **kwargs):
            worker_calls.append((args, kwargs))
            return {"status": "completed"}
        DC.run_supervised_da3_worker = spy_worker

        # 构造有效的研究日志与统计协议
        res_log = tmp_path / "RESEARCH_LOG.md"
        res_log.write_text(
            f"# Research Log\n"
            f"## {T6_APPROVAL_SECTION}：用户批准 T6 教师环境与推理基准（Claude 记录）\n"
            f"- 用户原话：「{T6_APPROVAL_KEYWORD}」（2026-10-26 约 15:00 +03）。批准对象：{T6_APPROVAL_TARGET}。\n"
            f"- 预算：\n"
            f"  - GPU 推理基准墙钟合计 ≤ 20 分钟，单次 ≤ 20 分钟（1200s）。\n"
            f"  - 一次只常驻一个模型；进程内存峰值超过 8 GB 立即停。\n"
            f"  - 视图数量上限 64 视图。\n"
            f"- 统计协议：\n"
            f"  - 统计协议与配对真值标定已登记，采用 Sim3 旋转角与平移相对误差。\n"
        )
        proto = tmp_path / "protocol.json"
        proto.write_text(json.dumps({
            "protocol_id": "az.v9.da3.calibration.v1",
            "metrics": ["rotation_error_deg", "translation_rel_error"],
            "calibration_inputs": {"world_list_sha256": "982dc676ad377d2439cb4ce92d4c58875d2175a949885fd2dfcc588d2f8a86ca", "n_worlds": 32},
            "tolerance": {"max_rotation_deg": 1.0, "max_translation_rel": 0.05},
        }))

        # 请求配置：views=17 (≠ 18 标定口径；且 81+17=98 > 82 会撞配额)
        # worker_action=None (通过 coordinator_release=True 派生为 real_pipeline)
        spec = DA3RunSpec(
            model="da3-small",
            wall_budget_seconds=10.0,
            views=17,
            research_log_path=res_log,
            store_path=store_copy,
            lock_path=lock_copy,
            weights_root=Path("artifacts/teachers/da3"),
            statistical_protocol_path=proto,
            coordinator_release=True,
            allow_model_execution=True,
        )

        log.append("## 1. 执行派生请求 (views=17, worker_action=None, coordinator_release=True)")
        caught = None
        try:
            execute_guarded_da3_benchmark(
                spec=spec,
                test_substitute=False,
                coordinator_release=True,
                allow_model_execution=True,
                worker_action=None,  # 派生 real_pipeline!
                allow_custom_paths=True,
            )
        except Exception as exc:
            caught = exc

        log.append(f"捕获异常类型: {type(caught).__name__}")
        log.append(f"异常消息: {caught}")
        log.append(f"异常 details: {getattr(caught, 'details', None)}")
        log.append("")

        # 断言异常类型与内容
        assert isinstance(caught, BenchmarkRefusalError), f"Expected BenchmarkRefusalError, got {type(caught)}"
        assert not isinstance(caught, BenchmarkBudgetRefused), "Must not raise BenchmarkBudgetRefused!"

        msg = str(caught)
        assert f"requires views == {REGISTERED_CALIBRATION_VIEWS}" in msg, "Must specify views requirement"
        assert "got views=17" in msg, "Must specify got views=17"
        assert "quota" not in msg.lower(), "Must NOT report quota exceeded!"

        det = caught.details
        assert det["requested_views"] == 17
        assert det["required_views"] == 18
        assert det["action"] == "real_pipeline"
        assert det["derived_from_release"] is True

        log.append("## 2. 预检门先行性验证结论")
        log.append("- 错误类型为 BenchmarkRefusalError（标定视图口径拒绝），而非 BenchmarkResourceRefused/BenchmarkBudgetRefused（配额错误）。")
        log.append("- 错误消息不含 'quota'，真因准确报告为 views != 18。")
        log.append("- details 包含 derived_from_release=True，确认派生路径正确被拦截。")
        log.append("")

        # 检查副作用（零扣账、零 worker、零锁）
        sec_after, views_after = DC.query_t6_ledger_read_only(store_copy)
        db_sha_after = sha256_bytes(store_copy.read_bytes())
        lock_exists = lock_copy.exists()
        worker_call_count = len(worker_calls)

        log.append("## 3. 零副作用核对")
        log.append(f"- 账本视图数: {views_before} -> {views_after} (完全未变)")
        log.append(f"- 账本墙钟数: {sec_before:.1f}s -> {sec_after:.1f}s (完全未变)")
        log.append(f"- 账本 SHA256: {db_sha_before} -> {db_sha_after} (逐字节未变)")
        log.append(f"- Worker 调用次数: {worker_call_count} (未启动)")
        log.append(f"- 锁文件存在: {lock_exists} (未创建)")
        log.append("")

        assert views_after == views_before, "Ledger views debited!"
        assert sec_after == sec_before, "Ledger seconds debited!"
        assert db_sha_after == db_sha_before, "Ledger file mutated!"
        assert worker_call_count == 0, f"Worker called {worker_call_count} times!"
        assert not lock_exists, "Lock file was created!"

        log.append("## 结论：验证完全通过！视图预检先于配额检查，且保持零扣账、零启动、零锁。")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
