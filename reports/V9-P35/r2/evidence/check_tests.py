#!/usr/bin/env python3
"""P35 r2 必做 7：tests/v9 全量对账（并把 P34 的 7 个失败逐个归因）。

三份日志都在本目录：
  * ``pytest-v9-with-shim.log``     —— 带 IDE shim（PYTHONPATH 里有 WorkBuddy 的 sitecustomize）
  * ``pytest-v9-no-shim.log``       —— 去掉 shim 的同一台机器、同一个 venv
  * ``pytest-experiments-alone.log`` / ``pytest-geometry-alone.log`` —— 分目录单跑

结论要点：
  * P34 报的 6 条 tmpdir EEXIST 是 **IDE shim 的 mkdir 实现**造成的（``exist_ok=True`` 落在
    已存在的符号链接上被 shim 抛 EEXIST），去掉 shim 后全部消失；
  * 剩下 1 条已知失败（真实台账拷贝的旧预期）与 r12 无关；
  * 另有 2 条 geometry 的 CPU-only import 断言是**同进程顺序**导致（单跑全过）；
  * 本环境禁止 exec ps，无法在"能跑 ps 的非沙箱环境"重跑，按卡面如实标注。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p35common as C

SUMMARY_RE = re.compile(r"^(\d+) failed, (\d+) passed|^(\d+) passed", re.M)


def parse(name: str) -> dict:
    path = C.EVIDENCE / name
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    tail = [line for line in text.strip().splitlines() if line.strip()][-1:] or [""]
    failed = re.findall(r"^FAILED (\S+)", text, re.M)
    passed = failed_count = None
    match = re.search(r"(\d+) failed, (\d+) passed", text)
    if match:
        failed_count, passed = int(match.group(1)), int(match.group(2))
    else:
        match = re.search(r"(\d+) passed", text)
        if match:
            passed, failed_count = int(match.group(1)), 0
    return {
        "log": name,
        "summary_line": tail[0],
        "passed": passed,
        "failed": failed_count,
        "failed_tests": failed,
    }


def main() -> dict:
    with_shim = parse("pytest-v9-with-shim.log")
    no_shim = parse("pytest-v9-no-shim.log")
    experiments_alone = parse("pytest-experiments-alone.log")
    geometry_alone = parse("pytest-geometry-alone.log")

    eexist = [
        test
        for test in with_shim["failed_tests"]
        if test.startswith(("tests/v9/experiments/test_s1_approval.py", "tests/v9/experiments/test_s1_train_gates.py"))
    ]
    known_real_ledger = "tests/v9/experiments/test_s1_r7_phase_accounting.py::test_the_real_ledger_copy_reproduces_the_old_bug_without_touching_the_original"
    cpu_only = [
        "tests/v9/geometry/test_canonical.py::test_cpu_only_imports",
        "tests/v9/geometry/test_geometry.py::test_imports_are_cpu_only",
    ]

    checks = {
        "no_shim_run_is_greener_than_with_shim": (
            no_shim["failed"] is not None
            and with_shim["failed"] is not None
            and no_shim["failed"] < with_shim["failed"]
        ),
        "shim_failures_are_exactly_the_six_tmpdir_cases": len(eexist) == 6,
        "no_shim_only_known_plus_cpu_only_fail": sorted(no_shim["failed_tests"])
        == sorted([known_real_ledger, *cpu_only]),
        "cpu_only_tests_pass_in_isolation": geometry_alone["failed"] == 0,
        "experiments_alone_only_known_failure": experiments_alone["failed_tests"] == [known_real_ledger],
        "totals_add_up": (
            # 去掉 shim 后，恰好是那 6 条 shim 失败转为通过，其余不变。
            no_shim["passed"] == with_shim["passed"] + len(eexist)
            and no_shim["failed"] == with_shim["failed"] - len(eexist)
        ),
    }
    return {
        "purpose": "tests/v9 全量对账 + P34 的 7 个失败逐个归因",
        "runs": {
            "with_shim": with_shim,
            "no_shim": no_shim,
            "experiments_alone": experiments_alone,
            "geometry_alone": geometry_alone,
        },
        "attribution": {
            "six_tmpdir_eexist": {
                "tests": eexist,
                "cause": (
                    "IDE 注入的 sitecustomize shim（/Applications/WorkBuddy AI.app/.../cli/vendor/"
                    "shim/sitecustomize.py:501）自己实现了 mkdir，Path.mkdir(exist_ok=True) 落在"
                    "canonical_root fixture 造的 phase1 符号链接上时抛 PermissionError: EEXIST。"
                    "去掉 PYTHONPATH 里的 shim 后这 6 条全部通过。"
                ),
                "is_product_regression": False,
            },
            "known_real_ledger": {
                "test": known_real_ledger,
                "cause": (
                    "断言 conservative == reserved_based 在当前生产行上不再成立"
                    "（5012.096 vs 2214.076）：生产库在 r10/r11 运行后行数/时长变了，"
                    "这是旧预期失效，不是 r12 引入。该用例只用 read_bytes()+copyfile，不写生产库。"
                ),
                "is_product_regression": False,
                "should_be_fixed_by": "一级（改预期或改夹具），本卡不改测试",
            },
            "two_cpu_only_imports": {
                "tests": cpu_only,
                "cause": "同进程先导入了 mlx/torch，断言 any(...) 命真；geometry 目录单跑 149 passed。",
                "is_product_regression": False,
            },
        },
        "environment": {
            "ps_available": False,
            "ps_error": "zsh: operation not permitted: ps（本会话 shell 被沙箱禁止 exec ps）",
            "non_sandbox_rerun_required_by_card": True,
            "handoff": "tests/v9 全量请一级在能跑 ps 的非沙箱环境补跑；本卡已用去掉 IDE shim 的同一 venv 跑通全量。",
        },
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("tests-reconcile", main))
