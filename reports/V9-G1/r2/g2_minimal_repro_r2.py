#!/usr/bin/env python3
"""G2 最小复现（F1/F2 部分）在 G1 r2 修复后的转绿核对。

来源：`reports/V-V9-G1/findings_minimal_repro.py`（G2 非作者复核，2026-10-16）。
该脚本的语义是“0 = 发现成功复现”。修复后本脚本语义相反：**0 = F1/F2 已修复（转绿）**，
1 = 任一发现仍复现（回归）。G2 的 F4（exp 超大角泄漏 OverflowError）不在 r2 文件范围，
这里只报告其状态，不作为本脚本的退出条件。
只读源码；不写除 --json-out 之外的任何文件。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from ainerzero.v9.geometry import (  # noqa: E402
    GravityFrame,
    ObservabilityError,
    RelativeFactor,
    SE2,
    TangentGaussian,
    solve_pose_graph,
)
from ainerzero.v9.geometry.belief import covariance  # noqa: E402

ok = True
report: dict = {"task": "ainerzero.V9.G5", "source": "reports/V-V9-G1/findings_minimal_repro.py",
                "semantics": "exit 0 = F1/F2 已修复（转绿）；exit 1 = 仍有发现复现", "checks": []}


def check(name: str, fixed: bool, detail: str) -> None:
    global ok
    print(f"[{'GREEN' if fixed else 'STILL REPRODUCED'}] {name}: {detail}")
    report["checks"].append({"name": name, "green": fixed, "detail": detail})
    ok = ok and fixed


# ---- F1：G2 的精确整数 PSD 输入必须被半正定守卫接受 ----
int_rank1 = np.outer(np.array([1.0, 2.0, 2.0]), np.array([1.0, 2.0, 2.0]))
j = np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 1.0]])
int_jtj = j.T @ j
for tag, matrix in (("outer([1,2,2])", int_rank1), ("J^T J 整数", int_jtj)):
    assert np.array_equal(matrix, np.round(matrix)) and np.abs(matrix).max() < 2 ** 53
    eigmin = float(np.linalg.eigvalsh(matrix)[0])
    try:
        covariance(matrix, 3, semidefinite=True)
        check(f"F1 {tag}", True, f"被接受；G2 记录的 float64 最小特征值 {eigmin:+.3e}（精确矩阵 PSD）")
    except ValueError as exc:
        check(f"F1 {tag}", False, f"仍被拒绝（{eigmin:+.3e}）：{exc}")

# G2 的下游检查：rank-deficient PSD information 不再被协方差守卫拒绝，
# 而是进入既有可观测性检查并 fail-closed 为 ObservabilityError。
try:
    solve_pose_graph(
        SE2,
        [SE2.identity(), SE2.exp([1.0, 0.0, 0.0])],
        [RelativeFactor(0, 1, SE2.exp([1.0, 0.0, 0.0]), int_rank1)],
        anchor=0,
    )
    check("F1 下游 solve_pose_graph", False,
          "rank-deficient PSD information 被接受却没有触发不可观错误（可解性检查被绕过）")
except ObservabilityError as exc:
    covariance_rejected = "positive semidefinite" in str(exc)
    check("F1 下游 solve_pose_graph", not covariance_rejected,
          f"进入可观测性检查并 fail-closed：ObservabilityError({exc})")
except ValueError as exc:
    check("F1 下游 solve_pose_graph", False,
          f"ValueError 仍来自协方差守卫：{exc}")

# ---- F2：GravityFrame 水平参考守卫必须与尺度无关 ----
up = np.array([0.0, 0.0, 1.0])
verdicts = {}
for scale in (1e-20, 1e-13, 1e-12, 1e-9, 1.0, 1e8):
    try:
        GravityFrame([0.0, 0.0, -9.81], up, np.array([scale, 0.0, 0.0]))
        verdicts[scale] = "accepted"
    except ValueError as exc:
        verdicts[scale] = f"rejected({exc})"
print("    F2 结果表:", {f"{k:g}": v.split("(")[0] for k, v in verdicts.items()})
check("F2 同方向不同尺度结论一致", all(v == "accepted" for v in verdicts.values()),
      "恰好垂直的重力水平参考在 1e-20…1e8 全部被接受")

# 反向：与重力平行的参考（任意尺度）仍必须拒绝。
parallel_verdicts = {}
for scale in (1e-20, 1.0, 1e8):
    try:
        GravityFrame([0.0, 0.0, -9.81], up, np.array([0.0, 0.0, scale]))
        parallel_verdicts[scale] = "accepted"
    except ValueError:
        parallel_verdicts[scale] = "rejected"
check("F2 平行参考仍拒绝", all(v == "rejected" for v in parallel_verdicts.values()),
      f"{parallel_verdicts}")

# ---- F4（不在 r2 范围）：只报告状态，不参与退出码 ----
f4_status = {}
for theta in (1e102, 1e103, 2 * np.pi):
    try:
        SE2.exp([0.0, 0.0, float(theta)])
        f4_status[theta] = "ok"
    except Exception as exc:  # noqa: BLE001
        f4_status[theta] = type(exc).__name__
belief = TangentGaussian(SE2, SE2.exp([0, 0, 0]), np.eye(3))
try:
    belief.predict([0.5, -0.25, 0.3], 1e300, np.eye(3) * 1e-3)
    f4_predict = "ok"
except Exception as exc:  # noqa: BLE001
    f4_predict = type(exc).__name__
print(f"    F4（不在 r2 范围，仍保留）：SE2.exp 大角={f4_status}；predict(dt=1e300)={f4_predict}")
report["f4_out_of_scope"] = {"se2_exp": {str(k): v for k, v in f4_status.items()},
                             "predict_dt_1e300": f4_predict}

report["green"] = ok
print("---")
print("F1/F2 G2 最小复现已转绿" if ok else "F1/F2 仍有发现复现（脚本退 1）")
if args := sys.argv[1:]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out")
    ns = parser.parse_args(args)
    if ns.json_out:
        Path(ns.json_out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")
sys.exit(0 if ok else 1)
