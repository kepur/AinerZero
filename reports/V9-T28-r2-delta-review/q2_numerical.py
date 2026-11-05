#!/usr/bin/env python3
"""T46 问题 2 的数值依据：cpu_parity（atol=rtol=1e-3，全元素逐点）在 fp32 下能不能过？

不加载模型，只用三样只读材料：
  1. 夹具真值的 depth 量纲（决定 atol+rtol*|ref| 的实际阈值）
  2. 本仓唯一一次 MPS-vs-CPU fp32 实测（reports/V9-T6 归档 metrics）
  3. 对拍的元素数（决定"全元素逐点、0 个失败"有多难）
"""
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
FIX = REPO / "reports/V9-T6/r2-calib-fixtures"
T6_METRICS = REPO / "reports/V9-T6/r1-archive-codex-20261026/reports/V9-T6/metrics.json"


def main() -> int:
    ATOL = RTOL = 1e-3

    print("=" * 78)
    print("cpu_parity 的数值可行性（fp32，MPS 参考 vs CPU 被测）")
    print("=" * 78)

    man = json.loads((FIX / "manifest.json").read_text())
    rows = man["rows"]
    d0 = np.load(FIX / rows[0]["directory"] / "depth_camera_z.npy")
    depths = [np.load(FIX / r["directory"] / "depth_camera_z.npy") for r in rows]
    allv = np.concatenate([d.ravel() for d in depths])
    K = np.load(FIX / rows[0]["directory"] / "intrinsics.npy")

    print(f"\n[1] 真值 depth 量纲（决定 rtol 项）")
    print(f"    shape={d0.shape}  n={allv.size}  min={allv.min():.4f}  median={np.median(allv):.4f}  "
          f"p99={np.percentile(allv,99):.4f}  max={allv.max():.4f}")
    for label, val in (("p1", np.percentile(allv, 1)), ("median", np.median(allv)),
                       ("p99", np.percentile(allv, 99)), ("max", allv.max())):
        tol = ATOL + RTOL * val
        print(f"    depth={label:<6} ({val:6.3f}) -> 每元素允许 |a-b| <= {tol:.6f}")

    print(f"\n[2] 对拍元素数（全元素逐点、要求 0 个失败）")
    n_depth = 3 * d0.size
    n_conf = n_depth
    n_ext = 3 * 3 * 4
    n_int = 3 * 3 * 3
    print(f"    depth      : 3 views x {d0.size} = {n_depth}")
    print(f"    confidence : 3 views x {d0.size} = {n_conf}")
    print(f"    extrinsics : 3 x 3x4 = {n_ext}")
    print(f"    intrinsics : 3 x 3x3 = {n_int}")
    print(f"    合计 = {n_depth + n_conf + n_ext + n_int}  (卡面说的 ~3.5e5)")
    fx = float(K[0, 0])
    print(f"    intrinsics 的 fx={fx:.1f} -> rtol 项给出 {RTOL*fx:.4f} 的绝对容差（相对宽松）")

    print(f"\n[3] 本仓唯一一次 MPS-vs-CPU fp32 实测（V9-T6 归档）")
    m = json.loads(T6_METRICS.read_text())
    blk = m["acceptance_criteria_verification"]["6_numerical_consistency_and_negative_controls"]
    pc = blk["mps_vs_cpu_parity"]
    pf = blk["f32_vs_f16_parity"]
    print(f"    mps_vs_cpu: max_abs_diff={pc['max_abs_diff']}  当时的绝对阈值={pc['threshold']}  passed={pc['passed']}")
    print(f"    f32_vs_f16: max_abs_diff={pf['max_abs_diff']}  当时的绝对阈值={pf['threshold']}  passed={pf['passed']}")
    tol_med = ATOL + RTOL * float(np.median(allv))
    tol_max = ATOL + RTOL * float(allv.max())
    print(f"\n    观测到的 MPS/CPU 最大绝对差 {pc['max_abs_diff']} vs 本协议的每元素容差:")
    print(f"      / 中位深度容差 {tol_med:.6f} = {pc['max_abs_diff']/tol_med:.1f} 倍")
    print(f"      / 最大深度容差 {tol_max:.6f} = {pc['max_abs_diff']/tol_max:.1f} 倍")
    print(f"    => 若该量级的差异在 280 分辨率下依然成立，depth 字段会有非零 failed_elements，"
          f"cpu_parity 判红。")

    print(f"\n[4] 关于 f32_vs_f16 的 0.0 —— 一条独立的旁证")
    print(f"    本仓 pinned torch 是 2.3.1，其 torch/amp/autocast_mode.py 里 'mps' 出现 0 次，")
    print(f"    torch.autocast(device_type='mps', ...) 在 2.3.1 上是空操作；")
    print(f"    而 T6 的 f32_vs_f16 正是用 torch.autocast('mps', float16) 跑的，实测 max_abs=0.0。")
    print(f"    fp16 matmul 不可能给出 0.0（fp16 相对精度约 1e-3），所以那次所谓 fp16 前向")
    print(f"    实际上仍是 fp32 —— 这独立支持「本仓从未真正跑过 fp16 前向」的判断。")

    print("\n" + "=" * 78)
    print("结论（详见 REPORT.md 问题 2）：cpu_parity 在 fp32 下大概率红，且红的理由是")
    print("设备间 fp32 差异 + argmin 参考视角翻转，不是模型能力；红了会被如实记录（exit 5）。")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
