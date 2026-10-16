#!/usr/bin/env python3
"""G2 复核发现的最小复现（F1 / F2 / F4）。

注意退出码语义：**0 = 发现成功复现**（不是"G1 通过"）。任一条复现不出来 → 退 1。
只读 G1 源码。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np  # noqa: E402

from ainerzero.v9.geometry import (  # noqa: E402
    SE2, GravityFrame, RelativeFactor, TangentGaussian, solve_pose_graph,
)
from ainerzero.v9.geometry.belief import covariance  # noqa: E402

ok = True


def check(name, condition, detail):
    global ok
    print(f"[{'REPRODUCED' if condition else 'NOT REPRODUCED'}] {name}: {detail}")
    ok = ok and condition


# ---- F1：半正定守卫拒绝**精确** PSD 的整数矩阵（对称性检查有 atol=1e-12，特征值检查无容差）
int_rank1 = np.outer(np.array([1.0, 2.0, 2.0]), np.array([1.0, 2.0, 2.0]))  # 元素为精确整数
j = np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 1.0]])
int_jtj = j.T @ j  # 元素为精确整数；精确特征值 = {0, sv(J)^2} >= 0
for tag, m in (('outer([1,2,2])', int_rank1), ('J^T J 整数', int_jtj)):
    assert np.array_equal(m, np.round(m)) and np.abs(m).max() < 2 ** 53  # 元素逐位精确
    try:
        covariance(m, 3, semidefinite=True)
        check(f'F1 {tag}', False, '被接受（未复现拒绝）')
    except ValueError as exc:
        check(f'F1 {tag}', True,
              f'eigmin(float64)={np.linalg.eigvalsh(m)[0]:+.3e} 但精确矩阵 PSD → ValueError: {exc}')
# 下游：solve_pose_graph 的 information 允许半正定表达部分约束，却在精确 PSD 上抛错
downstream = []
for tag, info in (('整数 outer([1,2,2])', int_rank1),
                  ('归一化 u u^T', np.outer(np.array([1.0, 0.5, 0.0]) / np.linalg.norm([1.0, 0.5, 0.0]),
                                            np.array([1.0, 0.5, 0.0]) / np.linalg.norm([1.0, 0.5, 0.0])))):
    try:
        solve_pose_graph(SE2, [SE2.identity(), SE2.exp([1, 0, 0])],
                         [RelativeFactor(0, 1, SE2.exp([1, 0, 0]), info)], anchor=0)
        downstream.append((tag, 'accepted'))
    except ValueError as exc:
        downstream.append((tag, f'ValueError: {exc}'))
    except Exception as exc:  # noqa: BLE001
        downstream.append((tag, f'{type(exc).__name__}: {exc}'))
print('    F1 下游结果:', downstream)
check('F1 下游 solve_pose_graph',
      any('positive semidefinite' in v for _, v in downstream),
      'rank-deficient PSD information 在 solve_pose_graph 里被协方差守卫拒绝（而非进入不可观判定）')

# ---- F2：GravityFrame 水平参考守卫按**绝对范数**判定，同一方向因尺度不同结论不同
up = np.array([0.0, 0.0, 1.0])
verdicts = {}
for scale in (1e-20, 1e-13, 1e-12, 1e-9, 1.0, 1e8):
    try:
        GravityFrame([0.0, 0.0, -9.81], up, np.array([scale, 0.0, 0.0]))
        verdicts[scale] = 'accepted'
    except ValueError as exc:
        verdicts[scale] = f'rejected({exc})'
print('    F2 结果表:', {f'{k:g}': v.split('(')[0] for k, v in verdicts.items()})
check('F2 同方向不同尺度结论不一致',
      verdicts[1e-13].startswith('rejected') and verdicts[1e-9] == 'accepted' and verdicts[1.0] == 'accepted',
      'h=[1e-13,0,0] 与 h=[1,0,0] 都是恰好垂直 up，但前者被拒、后者被接受')

# ---- F4：有限 dt 下 exp 的 _abc 用 python float ** 溢出 → 泄漏 OverflowError（文档失败模式是 ValueError）
belief = TangentGaussian(SE2, SE2.exp([0, 0, 0]), np.eye(3))
try:
    belief.predict([0.5, -0.25, 0.3], 1e300, np.eye(3) * 1e-3)
    check('F4 predict(dt=1e300)', False, '未抛异常（未复现）')
except OverflowError as exc:
    check('F4 predict(dt=1e300)', True, f'OverflowError 泄漏: {exc}（非 ValueError）')
except ValueError as exc:
    check('F4 predict(dt=1e300)', False, f'抛 ValueError: {exc}')
th = {}
for theta in (1e102, 1e103, 2 * np.pi, 1e150):
    try:
        SE2.exp([0.0, 0.0, float(theta)])
        th[theta] = 'ok'
    except Exception as exc:  # noqa: BLE001
        th[theta] = type(exc).__name__
print('    F4 SE2.exp 阈值扫描:', th)
check('F4 SE2.exp 大角泄漏 OverflowError', th[1e103] == 'OverflowError' and th[2 * np.pi] == 'ok',
      'theta=1e103 → OverflowError；theta=2pi → ok（阈值来自 _abc 的 theta**3）')

print('---')
print('发现最小复现全部成功' if ok else '有发现未能复现（脚本退 1）')
sys.exit(0 if ok else 1)
