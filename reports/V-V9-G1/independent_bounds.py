#!/usr/bin/env python3
"""G2 独立复核：解析上界推导 vs 实测（自写推导 + 自写轨迹 + 可达性/锐度）。

三部分：
  A. 条件平移滤波界 B- = B + b_u, B+ = ||I-K||2 B- + ||K||2 b_z
     - 自写 24 步轨迹，逐步断言 实际误差 <= 该步界；
     - 可达性：在 ||e||<=B、||d_u||<=b_u、||d_z||<=b_z 上做对抗搜索，量测界有多紧；
     - 前提破坏（真实里程误差 5 倍于登记界）→ 界必须被违反（证明它是条件界，不是普遍界）。
  B. 位姿图线性界 ||x_hat-x_true||2 <= ||(sqrt(W)A)^+||2 ||sqrt(W)e||2
     - 自写随机图（含错误回环/离群）验证有效性与**锐度**（沿 A^+ 主左奇异方向取 e 时等号成立）；
     - 与 G1 报告数字独立复算（只用登记参数，不用它的求解输出）。
  C. G1 报告 JSON 的逐步界/误差内部一致性 + 用登记参数独立重算整条界序列。

只读 G1 源码与报告，不写被验目录。退出码 0=全部成立，1=有违反，2=脚本自身错误。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
G1 = ROOT / 'reports/V9-G1/r1-codex-20261016'
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np  # noqa: E402

from ainerzero.v9.geometry import (  # noqa: E402
    SE2, KnownRotationGaussian, ObservabilityError, RelativeFactor,
    bounded_translation_update, linear_translation_error_bound, solve_pose_graph,
)

RTOL = 1e-9
SLACK = 1e-12


def part_a(out):
    """条件平移滤波界：自写轨迹 + 可达性 + 前提破坏。"""
    violations = []
    # ---- A1 自写 24 步矩形轨迹（自选参数，不复用 G1 的数值）
    waypoints = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 1.2], [0.0, 1.2], [0.0, 0.0]])
    seg = np.diff(waypoints, axis=0)
    truth = [waypoints[0]]
    for k in range(4):
        for t in np.linspace(0.0, 1.0, 7)[1:]:
            truth.append(waypoints[k] + seg[k] * t)
    truth = np.asarray(truth[:25])
    drift = np.array([0.004, -0.0025])
    obs_bias = np.array([0.0015, -0.002])
    init_err = np.array([0.03, -0.045])
    steps = len(truth) - 1
    mean = truth[0] + init_err
    cov = np.diag([0.05, 0.03])
    q = np.diag([4e-4, 4e-4])
    r = np.diag([3e-3, 3e-3])
    bound = float(np.linalg.norm(init_err))
    rows = []
    for k, (prev, cur) in enumerate(zip(truth, truth[1:]), 1):
        mean = mean + (cur - prev) + drift
        cov = cov + q
        gain = np.linalg.solve(cov + r, cov).T
        mean = mean + gain @ ((cur + obs_bias) - mean)
        a = np.eye(2) - gain
        cov = a @ cov @ a.T + gain @ r @ gain.T
        pred_bound, bound = bounded_translation_update(
            bound, float(np.linalg.norm(drift)), float(np.linalg.norm(obs_bias)), gain)
        err = float(np.linalg.norm(mean - cur))
        rows.append({'step': k, 'error': err, 'bound': bound, 'pred_bound': pred_bound})
        if err > bound + SLACK:
            violations.append(f'A1 第 {k} 步实际误差 {err:.6g} > 界 {bound:.6g}')
        if np.linalg.eigvalsh(cov)[0] <= 0:
            violations.append(f'A1 第 {k} 步协方差非正定')
    ratio = max(r['error'] / r['bound'] for r in rows)
    out['A1_own_trajectory'] = {
        'steps': steps, 'max_error': max(r['error'] for r in rows),
        'max_bound': max(r['bound'] for r in rows), 'max_error_over_bound': ratio,
        'violations': 0 if not violations else len(violations),
    }

    # ---- A2 可达性：界有多紧（对抗搜索）
    rng = np.random.default_rng(20261016)
    worst_ratio, worst_case = 0.0, None
    for trial in range(400):
        km = rng.normal(size=(2, 2)) * 0.6
        gain = 0.5 * (km + km.T * 0) + np.eye(2) * 0.4
        b_prev, b_u, b_z = 0.2, 0.05, 0.03
        pred = b_prev + b_u
        _, bound = bounded_translation_update(b_prev, b_u, b_z, gain)
        best = 0.0
        for _ in range(4000):
            e = rng.normal(size=2)
            e *= b_prev / max(np.linalg.norm(e), 1e-300)
            du = rng.normal(size=2)
            du *= b_u / max(np.linalg.norm(du), 1e-300)
            dz = rng.normal(size=2)
            dz *= b_z / max(np.linalg.norm(dz), 1e-300)
            best = max(best, float(np.linalg.norm((np.eye(2) - gain) @ (e + du) + gain @ dz)))
        if bound > 0:
            r = best / bound
            if r > worst_ratio:
                worst_ratio, worst_case = r, (gain.tolist(), bound, best)
    out['A2_bound_attainability'] = {'best_search_ratio': worst_ratio, 'case': worst_case,
                                     'note': '三角不等式界；比值上限 1'}
    if worst_ratio > 1 + 1e-9:
        violations.append(f'A2 对抗搜索超过界（{worst_ratio:.6f} > 1），界无效')

    # ---- A3 前提破坏：真实里程误差 5 倍于登记界
    mean = truth[0].copy()
    bound = 10 * float(np.linalg.norm(drift))  # 只用已登记的界；偏差实际用 5 倍
    cam = 0.02
    qc = 1e-4
    brok = 0
    for prev, cur in zip(truth, truth[1:]):
        mean = mean + (cur - prev) + 5 * drift
        cam += qc
        k2 = cam / (cam + 1e-3)
        mean = mean + k2 * ((cur + obs_bias) - mean)
        cam = (1 - k2) ** 2 * cam + k2 ** 2 * 1e-3
        _, bound = bounded_translation_update(bound, float(np.linalg.norm(drift)), float(np.linalg.norm(obs_bias)),
                                              np.eye(2) * k2)
        if float(np.linalg.norm(mean - cur)) > bound + SLACK:
            brok += 1
    out['A3_premise_violation'] = {'steps_exceeding_bound': brok, 'steps': steps}
    if brok == 0:
        violations.append('A3 前提破坏后界仍未被违反：该界不是可证伪的条件界（推导可疑）')

    # ---- A4 退化/非法输入必须拒绝
    guards = {}
    for name, args in {
        'negative_bound': (-1.0, 0.1, 0.1, np.eye(2) * 0.5),
        'nan_bound': (float('nan'), 0.1, 0.1, np.eye(2) * 0.5),
        'nonsquare_gain': (0.1, 0.1, 0.1, np.ones((2, 3))),
        'inf_gain': (0.1, 0.1, 0.1, np.full((2, 2), np.inf)),
    }.items():
        try:
            bounded_translation_update(*args)
            guards[name] = 'accepted'
            violations.append(f'A4 {name} 未被拒绝')
        except ValueError:
            guards[name] = 'ValueError'
    out['A4_bound_guards'] = guards
    return violations


def part_b(out):
    """位姿图线性界：有效性 + 锐度（等号可达） + 谱范数复算。"""
    violations = []
    rng = np.random.default_rng(7)
    worst_validity, best_sharpness, worst_sharpness = -np.inf, 0.0, np.inf
    for trial in range(30):
        n = int(rng.integers(3, 9))
        pts = np.vstack([np.zeros((1, 2)), np.cumsum(rng.normal(size=(n - 1, 2)), axis=0)])
        edges = [(i, i + 1) for i in range(n - 1)] + [(n - 1, 0)]
        a = np.zeros((len(edges), n - 1))
        for k, (i, j) in enumerate(edges):
            if j:
                a[k, j - 1] += 1
            if i:
                a[k, i - 1] -= 1
        err = rng.normal(size=(len(edges), 2)) * 0.05
        err[-1] = np.array([0.3, -0.2]) if trial % 2 == 0 else err[-1]
        w = np.ones(len(edges))
        bound = linear_translation_error_bound(a, w, err)
        mine = float(np.linalg.norm(np.linalg.pinv(a), 2) * np.linalg.norm(err))
        if abs(bound - mine) > 1e-12 * max(1.0, abs(bound)):
            violations.append(f'B 与自写谱范数公式不一致 {bound} vs {mine}')
        true_err = float(np.linalg.norm(np.linalg.lstsq(a, err, rcond=None)[0]))
        worst_validity = max(worst_validity, true_err - bound)
        # 锐度：e 取 A^+ 的主左奇异方向，界等号成立
        u, s, vt = np.linalg.svd(a, full_matrices=False)
        e_star = np.outer(u[:, -1], np.ones(2))
        e_star *= np.linalg.norm(err) / np.linalg.norm(e_star)
        sharp_bound = linear_translation_error_bound(a, w, e_star)
        attained = float(np.linalg.norm(np.linalg.lstsq(a, e_star, rcond=None)[0]))
        ratio = attained / sharp_bound
        best_sharpness = max(best_sharpness, ratio)
        worst_sharpness = min(worst_sharpness, ratio)
        # 秩亏必须 fail-closed（删掉一个节点的列 → 该节点不可观）
        if trial == 0:
            rank_deficient = a.copy()
            rank_deficient[:, -1] = 0.0
            if np.linalg.matrix_rank(rank_deficient) == rank_deficient.shape[1]:
                violations.append('B 自写秩亏样本构造错误（仍满列秩）')
            try:
                linear_translation_error_bound(rank_deficient, np.ones(len(edges)), err)
            except ObservabilityError:
                pass
            else:
                violations.append('B 秩亏输入未抛 ObservabilityError')
    out['B_validity'] = {'max_true_error_minus_bound': worst_validity}
    out['B_sharpness_ratio'] = {'min': worst_sharpness, 'max': best_sharpness,
                                'note': '沿 A^+ 主左奇异方向构造 e，比值应为 1'}
    if worst_validity > SLACK:
        violations.append(f'B 界不覆盖真误差，超出 {worst_validity:.3e}')
    if abs(best_sharpness - 1.0) > 1e-9:
        violations.append(f'B 界不可达（最好比值 {best_sharpness:.6f} != 1），说明界偏松或推导有误')

    # GN（fix rotations）与自写线性最小二乘、与自写界三者闭合
    for seed in range(10):
        rng = np.random.default_rng(100 + seed)
        n = 6
        truth = np.vstack([np.zeros((1, 2)), np.cumsum(rng.normal(size=(n - 1, 2)), axis=0)])
        edges = [(i, i + 1) for i in range(n - 1)] + [(n - 1, 0)]
        a = np.zeros((len(edges), n - 1))
        for k, (i, j) in enumerate(edges):
            if j:
                a[k, j - 1] += 1
            if i:
                a[k, i - 1] -= 1
        err = rng.normal(size=(len(edges), 2)) * 0.03
        measured = a @ truth[1:] + err
        factors = [RelativeFactor(i, j, SE2.exp(np.r_[measured[k], 0.0]), np.eye(3))
                   for k, (i, j) in enumerate(edges)]
        init = [SE2.identity()]
        for k in range(len(edges) - 1):
            init.append(SE2.compose(init[-1], factors[k].measurement))
        fit = solve_pose_graph(SE2, init, factors, anchor=0, fixed_rotations=True)
        got = np.asarray([p[:2, 2] for p in fit.poses[1:]])
        ls = np.linalg.lstsq(a, measured, rcond=None)[0]
        bound = linear_translation_error_bound(a, np.ones(len(edges)), err)
        true_err = float(np.linalg.norm(got - truth[1:]))
        if np.abs(got - ls).max() > RTOL:
            violations.append(f'B seed={seed}: GN != 自写 lstsq')
        if true_err > bound + SLACK:
            violations.append(f'B seed={seed}: 真误差 {true_err:.3e} > 界 {bound:.3e}')
    return violations


def part_c(out):
    """用登记参数独立重算 G1 报告的整条界序列与图界，并做内部一致性检查。"""
    violations = []
    reg = json.loads((G1 / 'cpu_registration.json').read_text())
    rep = json.loads((G1 / 'reference-results-r1.json').read_text())
    drift = np.asarray(reg['filter_odometry_bias_per_step'], dtype=float)
    obs = np.asarray(reg['filter_measurement_bias'], dtype=float)
    init = np.asarray(reg['filter_initial_translation_error'], dtype=float)
    cov = np.diag(reg['filter_covariance_diagonal'][:2]).astype(float)
    q = np.diag(reg['filter_process_covariance_rate_diagonal'][:2]).astype(float)
    r = np.diag(reg['filter_measurement_covariance_diagonal']).astype(float)
    bound = float(np.linalg.norm(init))
    mine = []
    for _ in range(len(rep['references'][0]['filter'])):
        cov = cov + q
        gain = np.linalg.solve(cov + r, cov).T
        cov = (np.eye(2) - gain) @ cov @ (np.eye(2) - gain).T + gain @ r @ gain.T
        pb, bound = bounded_translation_update(bound, float(np.linalg.norm(drift)), float(np.linalg.norm(obs)), gain)
        mine.append((pb, bound))
    max_gap_pred, max_gap_upd, max_err_ratio = 0.0, 0.0, 0.0
    max_contraction = 0.0
    for k, ref in enumerate(rep['references']):
        for i, step in enumerate(ref['filter']):
            max_gap_pred = max(max_gap_pred, abs(step['prediction_bound'] - mine[i][0]))
            max_gap_upd = max(max_gap_upd, abs(step['updated_bound'] - mine[i][1]))
            max_contraction = max(max_contraction, step['updated_bound'] / step['prediction_bound'])
            if step['updated_error'] > step['updated_bound'] + 1e-9:
                violations.append(f'C {ref["name"]} step {step["step"]}: 报告误差 > 报告界')
            if step['prediction_error'] > step['prediction_bound'] + 1e-9:
                violations.append(f'C {ref["name"]} step {step["step"]}: 预测误差 > 预测界')
            if step['updated_bound'] > step['prediction_bound'] + 1e-12:
                violations.append(
                    f'C {ref["name"]} step {step["step"]}: 更新界 > 预测界（增益不收缩，需登记）')
            max_err_ratio = max(max_err_ratio, step['updated_error'] / step['updated_bound'])
    out['C1_bound_sequence_independent_recompute'] = {
        'steps': len(mine), 'max_gap_prediction_bound': max_gap_pred,
        'max_gap_updated_bound': max_gap_upd, 'max_reported_error_over_bound': max_err_ratio,
        'max_updated_over_predicted_bound': max_contraction,
    }
    if max_gap_pred > 1e-12 or max_gap_upd > 1e-12:
        violations.append(f'C 与报告界序列不符（pred {max_gap_pred:.3e}, upd {max_gap_upd:.3e}）')

    # 图界：只用登记的边误差与 reduced incidence 结构复算
    n = 25
    edges = [(i, i + 1) for i in range(n - 1)] + [(n - 1, 0)]
    a = np.zeros((len(edges), n - 1))
    for k, (i, j) in enumerate(edges):
        if j:
            a[k, j - 1] += 1
        if i:
            a[k, i - 1] -= 1
    err = np.zeros((len(edges), 2))
    err[:-1] = drift
    my_bound = float(np.linalg.norm(np.linalg.pinv(a), 2) * np.linalg.norm(err))
    reported = [ref['pose_graph']['analytic_error_bound_l2'] for ref in rep['references']]
    out['C2_graph_bound_independent_recompute'] = {'mine': my_bound, 'reported': reported}
    if any(abs(my_bound - v) > 1e-12 for v in reported):
        violations.append(f'C 图界复算不一致 {my_bound} vs {reported}')
    for ref in rep['references']:
        pg = ref['pose_graph']
        if pg['after_error_l2'] > pg['analytic_error_bound_l2'] + 1e-9:
            violations.append(f'C {ref["name"]}: 图误差 > 图界')
        if abs(pg['after_error_l2'] - pg['linear_exact_error_l2']) > 1e-9:
            violations.append(f'C {ref["name"]}: GN 解与线性精确解差 > 1e-9')
        if pg['rank'] != pg['free_dimensions']:
            violations.append(f'C {ref["name"]}: rank != free_dimensions')
    # 边误差只用登记值 → 界只依赖登记输入（不读求解输出）
    out['C3_bound_depends_only_on_registered_inputs'] = True
    return violations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json-out', type=Path, default=None)
    args = parser.parse_args()
    summary = {'parts': {}, 'violations': []}
    for name, fn in (('A_conditional_translation_bound', part_a),
                     ('B_pose_graph_linear_bound', part_b),
                     ('C_g1_reported_numbers_recompute', part_c)):
        try:
            v = fn(summary['parts'])
            summary['parts'][name] = {'violations': v, 'ok': not v}
            summary['violations'] += [f'{name}: {x}' for x in v]
        except Exception:  # noqa: BLE001
            summary['parts'][name] = {'violations': ['HARNESS ERROR:\n' + traceback.format_exc()], 'ok': False}
            summary['violations'].append(f'{name}: HARNESS ERROR')
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    ok = not summary['violations']
    print(f"--- bounds: ok={ok} violations={len(summary['violations'])}")
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + '\n')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
