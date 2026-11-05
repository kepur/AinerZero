#!/usr/bin/env python3
"""P35 r2 extra_check：test_s1_timing_sequence 的 stub 会不会掩盖回归。

P34 把 ``test_s1_timing_sequence.py`` 里的 ``_eval_binding_precondition`` stub 掉了，理由是
那个时序用例 mock 了 ``_evaluate_arm``、假训练 run 也没有 completion receipt，新的绑定前置
条件必然拒绝。要核实的是：**真实绑定路径在别的测试里确实被覆盖**，否则这个 stub 会掩盖回归。

做法：
  1. 与 ``reports/V9-P9/r12/before/`` 的同名文件做 diff，确认改动只有那一处 stub（+注释）；
  2. 用 AST 找出真正碰绑定判定的用例名（不是 grep 行号，是函数级归属）；
  3. 把这些用例单独跑一遍，记录结果；
  4. 明确指出：stub 掩盖的是「入口的**接受**分支」，而拒绝分支由 r12 ordering 覆盖，
     接受分支在本 r2 的 release drill 里已用真实 ``_bind_completed_run`` 走通。
"""
from __future__ import annotations

import ast
import difflib
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p35common as C

TARGET = "tests/v9/experiments/test_s1_timing_sequence.py"
BEFORE = C.REPO / "reports/V9-P9/r12/before" / TARGET
NEEDLES = ("EvalBindingError", "run_binding", "_eval_binding_precondition", "eval_binding_unavailable")


def _binding_tests(rel: str) -> list[str]:
    path = C.REPO / rel
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            if any(needle in body for needle in NEEDLES):
                found.append(f"{rel}::{node.name}")
    return found


def _run(test_ids: list[str]) -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *test_ids, "--tb=line"],
        cwd=str(C.REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    tail = [line for line in completed.stdout.strip().splitlines() if line.strip()][-4:]
    return {"returncode": completed.returncode, "tail": tail}


def main() -> dict:
    current = (C.REPO / TARGET).read_text(encoding="utf-8")
    before = BEFORE.read_text(encoding="utf-8")
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            current.splitlines(keepends=True),
            fromfile=f"before/{TARGET}",
            tofile=TARGET,
            n=2,
        )
    )
    (C.EVIDENCE / "timing-stub-diff.patch").write_text(diff, encoding="utf-8")
    added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
    removed = [line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]

    coverage = {}
    for rel in (
        "tests/v9/experiments/test_s1_r5_eval.py",
        "tests/v9/experiments/test_s1_r5_ledger.py",
        "tests/v9/experiments/test_s1_r8_completion.py",
        "tests/v9/experiments/test_s1_r12_ordering.py",
    ):
        coverage[rel] = _binding_tests(rel)
    all_tests = [test for tests in coverage.values() for test in tests]
    run = _run(all_tests)

    # 把新增行去掉注释与空行后，应当恰好是一句 monkeypatch.setattr(worker,
    # "_eval_binding_precondition", lambda ...) —— 也就是"只多了一个 stub"，没有别的逻辑。
    added_code = [
        line[1:]
        for line in added
        if line[1:].strip() and not line[1:].strip().startswith("#")
    ]
    try:
        import textwrap

        parsed = ast.parse(textwrap.dedent("\n".join(added_code)))
        single_stmt = len(parsed.body) == 1
        is_setattr = (
            single_stmt
            and isinstance(parsed.body[0], ast.Expr)
            and isinstance(parsed.body[0].value, ast.Call)
            and getattr(parsed.body[0].value.func, "attr", "") == "setattr"
            and '"_eval_binding_precondition"' in "\n".join(added_code)
        )
    except SyntaxError:
        single_stmt, is_setattr = False, False

    checks = {
        "stub_change_is_additive_only": not removed,
        "stub_is_a_single_setattr_of_the_binding_precondition": is_setattr,
        "real_binding_covered_by_named_tests": len(all_tests) >= 5,
        "those_tests_pass": run["returncode"] == 0,
    }
    return {
        "purpose": "timing 用例的 stub 是否掩盖回归",
        "diff_lines_added": len(added),
        "diff_lines_removed": len(removed),
        "diff_path": str(C.EVIDENCE / "timing-stub-diff.patch"),
        "coverage_tests": coverage,
        "coverage_run": run,
        "findings": {
            "refusal_branch": (
                "被 stub 掉的是入口的**接受**分支（binding ok → 继续）。拒绝分支"
                "（eval_binding_unavailable + 台账字节不变）由 "
                "test_s1_r12_ordering.py::test_eval_refusal_without_a_completed_training_run_"
                "leaves_the_ledger_untouched 与它的坏控覆盖，没有被 stub 影响。"
            ),
            "real_bind_completed_run": (
                "真实 _bind_completed_run 的正向路径由 "
                "test_s1_r5_eval.py::test_evaluate_arm_binds_run_and_computes_all_six_groups 覆盖，"
                "篡改/缺失/重复三类拒绝由 "
                "test_s1_r5_ledger.py::test_eval_binding_rejects_tampered_missing_and_duplicate_evidence "
                "覆盖，completion 协议与失效标记由 test_s1_r8_completion.py 的两个用例覆盖。"
            ),
            "gap_that_remains": (
                "在 r12 之前，『入口层 binding 通过 → 继续往下走』这一条没有被任何测试覆盖；"
                "stub 让它继续不被覆盖。本 r2 的 release drill 用真实 _bind_completed_run + "
                "伪造的完成记录把这条路径走通到 MLX 哨兵，补上了这个缺口（见 release-drill.json）。"
            ),
        },
        "checks": checks,
        "all_checks_pass": all(checks.values()),
    }


if __name__ == "__main__":
    raise SystemExit(C.wrap("timing-stub", main))
