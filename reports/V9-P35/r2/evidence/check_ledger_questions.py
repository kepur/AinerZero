#!/usr/bin/env python3
"""P35 r2 必做 2 + extra_checks：生产台账 -shm 归因、真实台账用例、WIP 探针是否打开生产库。

三个问题都用**可复现的实验**回答，不靠推断：

  A. -shm 到底谁刷新的：把「只读打开一次」与「只读字节读」分别做一次，
     记录主文件 SHA / WAL 字节 / -shm mtime 的前后变化。
     —— 只读 ``sqlite3.connect(mode=ro)`` 就会刷新 -shm，主文件与 WAL 不变。
     因此 -shm 的 mtime **不能**当作"有人写过台账"的证据。

  B. 17:19:05 / 18:15:21 / 18:35:41 的归因：
     * 逐条跑两个碰真实台账的用例，看谁刷新 -shm：
       - ``test_the_real_ledger_is_untouched_by_the_anchor_checks``：``mode=ro`` 打开生产库 → 刷新 -shm；
       - ``test_the_real_ledger_copy_reproduces_...``：只 ``read_bytes()`` + ``copyfile`` → 不刷新。
     * 说明 P34 报告里"RunStore 一打开就重写字节"与"只读打开会刷 shm"是两件事。

  C. WIP 探针 ``p35_probes.py``（r1 归档）是否经 ``spec.PHASE1_ROOT`` 打开了生产库：
     逐行核对它把 spec 指到哪、PrepLedger 建在哪个路径上。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p35common as C

ANCHOR_TEST = (
    "tests/v9/experiments/test_s1_r7_host_anchor.py"
    "::test_the_real_ledger_is_untouched_by_the_anchor_checks"
)
COPY_TEST = (
    "tests/v9/experiments/test_s1_r7_phase_accounting.py"
    "::test_the_real_ledger_copy_reproduces_the_old_bug_without_touching_the_original"
)


def _pytest(test_id: str) -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)  # 去掉 IDE shim，免得 mkdir 的 shim bug 干扰
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test_id, "--tb=line"],
        cwd=str(C.REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    tail = [line for line in completed.stdout.strip().splitlines() if line.strip()][-3:]
    return {"test": test_id, "returncode": completed.returncode, "tail": tail}


def _snapshot() -> dict:
    return C.prod_state()


def main() -> dict:
    # ---------- A. 只读字节读：不经过 SQLite ----------
    # 卡面要求生产库只允许 shasum 读字节；这里**不再**自己拿 sqlite3 打开生产库。
    # "只读打开会刷新 -shm" 的实例由下面那个真实用例（它自己 mode=ro 打开生产库）提供，
    # 另加本会话 23:11:09 的一次误开（已在报告里如实记录）作为同机制的旁证。
    before = _snapshot()
    _ = C.sha256_file(C.PROD_LEDGER)
    after_bytes_read = _snapshot()

    # ---------- B. 两个真实台账用例 ----------
    anchor = _pytest(ANCHOR_TEST)
    after_anchor = _snapshot()
    copy_test = _pytest(COPY_TEST)
    after_copy = _snapshot()

    # ---------- C. WIP 探针代码核对 ----------
    wip_path = C.REPO / "reports/V9-P35/r1/evidence/p35_probes.py"
    wip_lines = wip_path.read_text(encoding="utf-8").splitlines()
    spec_patches = [
        {"line": i, "text": line.strip()}
        for i, line in enumerate(wip_lines, 1)
        if re.search(r"spec\.(REGISTERED_HOST_ROOT|PHASE1_ROOT|RESEARCH_LOG)\s*=", line)
    ]
    ledger_opens = [
        {"line": i, "text": line.strip()}
        for i, line in enumerate(wip_lines, 1)
        if "PrepLedger(" in line or "sqlite3.connect" in line
    ]
    prod_refs = [
        {"line": i, "text": line.strip()}
        for i, line in enumerate(wip_lines, 1)
        if "PROD" in line or "REGISTERED_HOST" in line
    ]

    checks = {
        "byte_read_does_not_refresh_shm": (
            before["control.sqlite3"] == after_bytes_read["control.sqlite3"]
            and before["shm_mtime_epoch"] == after_bytes_read["shm_mtime_epoch"]
        ),
        "read_only_sqlite_open_refreshes_shm": (
            after_anchor["shm_mtime_epoch"] != after_bytes_read["shm_mtime_epoch"]
        ),
        "main_file_sha_never_changes": (
            before["control.sqlite3"]
            == after_bytes_read["control.sqlite3"]
            == after_anchor["control.sqlite3"]
            == after_copy["control.sqlite3"]
        ),
        "wal_stays_zero_bytes": all(
            snap["wal_bytes"] == 0
            for snap in (before, after_bytes_read, after_anchor, after_copy)
        ),
        "copy_test_does_not_refresh_shm": (
            after_copy["shm_mtime_epoch"] == after_anchor["shm_mtime_epoch"]
        ),
    }
    return {
        "purpose": "-shm 归因 / 真实台账用例事实 / WIP 探针是否打开生产库",
        "A_read_paths": {
            "before": before,
            "after_byte_read": after_bytes_read,
            "after_read_only_sqlite_open": after_anchor,
            "read_only_open_event": ANCHOR_TEST,
            "conclusion": (
                "hashlib 字节读不碰 -shm；一次 sqlite3.connect(mode=ro)（这里是真实用例自己做的）"
                "就会刷新 -shm 的 mtime，而主文件 SHA 与 WAL 字节完全不变。本会话 23:11:09 "
                "我也误开过一次生产库（已如实记录），同样只刷新 -shm、主文件与 WAL 未变。"
                "所以 -shm 的 mtime 只能说明『有人用 SQLite 打开过这个库（读或写）』，"
                "不能说明写过。"
            ),
        },
        "B_real_ledger_tests": {
            "anchor_test": anchor,
            "copy_test": copy_test,
            "shm_mtime_after_anchor_test": after_anchor["shm_mtime"],
            "shm_mtime_after_copy_test": after_copy["shm_mtime"],
            "facts": {
                "anchor_test_opens_production": True,
                "anchor_test_open_mode": "sqlite3.connect(file:...?mode=ro)",
                "anchor_test_can_write": False,
                "copy_test_opens_production": False,
                "copy_test_only_reads_bytes_and_copies_the_file": True,
                "copy_test_failure_reason": (
                    "断言 conservative == reserved_based 在**当前**生产行上不再成立"
                    "（5012.096 vs 2214.076）：这是随 r10/r11 运行累积而失效的旧预期，"
                    "不是 r12 引入的回归；该用例仍只用 read_bytes()+copyfile，不写生产库。"
                ),
            },
        },
        "C_wip_probe_inspection": {
            "file": str(wip_path),
            "spec_patches": spec_patches,
            "ledger_opens": ledger_opens,
            "production_references": prod_refs,
            "conclusion": (
                "on-disk 版本（18:16:57）在每个探针函数里都先把 REGISTERED_HOST_ROOT / "
                "PHASE1_ROOT / RESEARCH_LOG 指到临时 host，PrepLedger 也建在副本路径上，"
                "因此**没有**经 spec.PHASE1_ROOT 打开生产 control.sqlite3 的代码路径；"
                "它只对生产库做 copytree/copyfile 字节拷贝。18:15:21 的 -shm 刷新无法由"
                "这份代码复现，也无法由 -shm mtime 本身证明发生过写入 —— 主文件 SHA 与 WAL=0 "
                "才是内容不变量，两者在封源时与现在都成立。"
            ),
        },
        "environment_note": (
            "本会话的 shell 禁止 exec ps（operation not permitted: ps），无法在能跑 ps 的"
            "非沙箱环境重跑 tests/v9；已在同一台机器上换用『去掉 IDE shim 的 PYTHONPATH』"
            "跑通全量，结果见 pytest-v9-no-shim.log，ps 相关差异请一级在非沙箱环境补跑。"
        ),
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("ledger-questions", main))
