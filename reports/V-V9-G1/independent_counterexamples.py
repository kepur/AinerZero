#!/usr/bin/env python3
"""G2 独立复核：自写不利反例（非作者，只读 G1 源码，不修改被验文件）。

每个反例（case）都：
  1) 用对抗性输入构造"最可能让实现出错"的场景；
  2) 断言数学/文档要求的行为，并记录一个**真实非零**的差异量（discrepancy）；
  3) 用同结构但故意改坏的 subject（poison）再跑一遍，要求它**必须变红**，
     以证明该断言不是空转（"故意改坏必须变红"对照）。

退出码：0 = 全部性质成立；1 = 有性质被违反（含不利发现）；2 = 复核脚本自身错误。
不导入 MLX/ORT/Torch/TF，不训练，不写被验目录，不联网。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

ROOT = Path('/Users/mac/AinerWorkFlow/AinerZero')
sys.path.insert(0, str(ROOT / 'src'))

import numpy as np  # noqa: E402

from ainerzero.v9.geometry import (  # noqa: E402
    SE2, SE3, GravityFrame, KnownRotationGaussian, ObservabilityError, RelativeFactor,
    TangentGaussian, bounded_translation_update, boxminus, boxplus,
    linear_translation_error_bound, skew, solve_pose_graph, tangent_jacobian,
)
from ainerzero.v9.geometry import belief as g1_belief  # noqa: E402
from ainerzero.v9.geometry import lie as g1_lie  # noqa: E402
from ainerzero.v9.geometry.belief import covariance as g1_covariance  # noqa: E402

RTOL = 1e-9


# ---------------------------------------------------------------- subject bundle
class Subject:
    """复核对象束：默认全部是 G1 真实实现，poison 只替换被故意改坏的那一项。"""

    def __init__(self, **overrides):
        self.SE2, self.SE3 = SE2, SE3
        self.TangentGaussian = TangentGaussian
        self.KnownRotationGaussian = KnownRotationGaussian
        self.GravityFrame = GravityFrame
        self.RelativeFactor = RelativeFactor
        self.solve_pose_graph = solve_pose_graph
        self.linear_translation_error_bound = linear_translation_error_bound
        self.bounded_translation_update = bounded_translation_update
        self.covariance = g1_covariance
        self.boxplus, self.boxminus, self.tangent_jacobian = boxplus, boxminus, tangent_jacobian
        self.adjoint_fn = lambda group, mean: group.adjoint(mean)
        self.position_update = lambda belief, z, rw: belief.update_position(z, rw)
        self.mutants = {}
        for key, value in overrides.items():
            setattr(self, key, value)


# ------------------------------------------------------- poisoned implementations
class NaiveSE3(SE3):
    """故意改坏：去掉近 pi / 小角分支，全部走 theta/sine*anti（G1 有该分支）。"""

    @staticmethod
    def log(value):
        t = SE3.validate(value)
        r = t[:3, :3]
        anti = np.array([r[2, 1] - r[1, 2], r[0, 2] - r[2, 0], r[1, 0] - r[0, 1]]) / 2
        sine = float(np.linalg.norm(anti))
        cosine = float(np.clip((np.trace(r) - 1) / 2, -1, 1))
        theta = math.atan2(sine, cosine)
        phi = theta / max(sine, 1e-300) * anti
        _, b, c = g1_lie._abc(theta)
        k = g1_lie.skew(phi)
        v = np.eye(3) + b * k + c * (k @ k)
        return np.r_[np.linalg.solve(v, t[:3, 3]), phi]


class ZeroRejectingGaussian(TangentGaussian):
    """故意改坏：把 dt=0 当成非法输入（G1 允许 dt=0 且是恒等）。"""

    def predict(self, body_velocity, dt, process_covariance_rate):
        if dt == 0:
            raise ValueError('poison: dt=0 rejected')
        return super().predict(body_velocity, dt, process_covariance_rate)


def loose_covariance(value, n, *, semidefinite=False):
    """故意改坏：特征值检查加 1e-6 容差（会静默接受轻微不定矩阵）。"""
    p = np.array(value, dtype=float, copy=True)
    p = (p + p.T) / 2
    smallest = np.linalg.eigvalsh(p)[0]
    if (smallest < -1e-6 if semidefinite else smallest <= 1e-6):
        raise ValueError('loose guard rejected')
    return p


class SignFlipFrame(GravityFrame):
    """故意改坏：重力方向约定取反（把 gravity 取负后再交给真实实现）。"""

    def __init__(self, gravity, up, horizontal_reference):
        super().__init__(-np.asarray(gravity, dtype=float), up, horizontal_reference)


def inverted_z_solve(group, initial_poses, factors, **kwargs):
    """故意改坏：把测量 Z 取逆（残差符号/约定错误）。"""
    flipped = [RelativeFactor(f.i, f.j, group.inverse(f.measurement), f.information) for f in factors]
    return solve_pose_graph(group, initial_poses, flipped, **kwargs)


def signflip_position_update(belief, observed_world_position, world_covariance):
    """故意改坏：SE2 左侧位置 Jacobian 的朝向列符号取反（G1 为 [-pos_y, pos_x]）。"""
    group = belief.group
    n = group.dim
    z = np.asarray(observed_world_position, dtype=float)
    rw = np.asarray(world_covariance, dtype=float)
    rot, pos = belief.mean[:n, :n], belief.mean[:n, n]
    h = np.zeros((n, group.dof))
    h[:, :n] = np.eye(n)
    if belief.side == 'right':
        innovation = rot.T @ (z - pos)
        noise = rot.T @ rw @ rot
    else:
        if n == 3:
            h[:, n:] = -skew(pos)
        else:
            h[:, n:] = np.array([[pos[1]], [-pos[0]]])  # flipped sign
        innovation, noise = z - pos, rw
    return belief.update_tangent(innovation, h, noise, side=belief.side)


def transposed_adjoint(group, mean):
    """故意改坏：Adjoint 用转置。"""
    return group.adjoint(mean).T


class JitterGaussian(TangentGaussian):
    """故意改坏：静默给协方差加 jitter（README 明确承诺不这么做）。"""

    def predict(self, body_velocity, dt, process_covariance_rate):
        out = super().predict(body_velocity, dt, process_covariance_rate)
        p = np.array(out.covariance)
        p += np.eye(len(p)) * 1e-18
        return JitterGaussian(out.group, out.mean, p, side=out.side)


# ------------------------------------------------------------------------ cases
CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def c1_near_singular_rotation(sub):
    """C1 近奇异旋转：SO(3) 近 pi、恰好 pi、SO(2) (-pi,pi] 主值与 -0.0 分支。"""
    metrics, violations = {}, []
    worst = 0.0
    samples = 0
    for group, dof, rdim, name in ((sub.SE2, 3, 2, 'SE2'), (sub.SE3, 6, 3, 'SE3')):
        for seed in range(120):
            rng = np.random.default_rng(seed)
            axis = rng.normal(size=rdim)
            axis /= np.linalg.norm(axis)
            rho = rng.normal(size=rdim) * 3.0
            for off in (0.0, 1e-14, 1e-13, 1e-12, 1e-9, 1e-6, 1e-3, 0.5, math.pi - 1e-4):
                theta = math.pi - off
                xi = np.r_[rho, axis * theta] if dof == 6 else np.r_[rho, theta]
                t = group.exp(xi)
                back = group.exp(group.log(t))
                err = float(np.abs(back - t).max())
                worst = max(worst, err)
                samples += 1
                if not (err <= RTOL):
                    violations.append(f'{name} off={off:g} exp(log(T)) 误差 {err:.3e} > {RTOL:g}')
                rot = group.log(t)[rdim:]
                if np.linalg.norm(rot) > math.pi + 1e-12:
                    violations.append(f'{name} off={off:g} 主值角 {np.linalg.norm(rot):.6f} > pi')
    # 恰好 pi 的轴符号约定 + SO(2) 主值上界与 -0.0 分支
    conv_bad = 0
    for seed in range(200):
        rng = np.random.default_rng(1000 + seed)
        axis = rng.normal(size=3)
        axis /= np.linalg.norm(axis)
        t = sub.SE3.exp(np.r_[np.zeros(3), axis * math.pi])
        log = sub.SE3.log(t)
        unit = log[3:] / np.linalg.norm(log[3:])  # 复制，不能原地改 log
        if not unit[np.argmax(np.abs(unit))] > 0:
            conv_bad += 1
        if np.abs(sub.SE3.exp(log) - t).max() > RTOL:
            violations.append(f'SE3 恰好 pi seed={seed}: exp(log(T)) != T')
    metrics['exact_pi_sign_convention_violations'] = conv_bad
    if conv_bad:
        violations.append(f'SE3 恰好 pi 轴符号约定被违反 {conv_bad}/200 次')
    for r11 in (-0.0, 0.0):
        rot = np.array([[-1.0, 0.0, 0.0], [r11, -1.0, 0.0], [0.0, 0.0, 1.0]])
        log = sub.SE2.log(rot)
        if not (abs(log[2]) <= math.pi + 1e-15 and abs(abs(log[2]) - math.pi) < 1e-12):
            violations.append(f'SE2 pi 主值异常 r[1,0]={r11!r}: w={log[2]}')
        if np.abs(sub.SE2.exp(log) - rot).max() > RTOL:
            violations.append(f'SE2 pi exp(log(T)) != T r[1,0]={r11!r}')
    metrics['samples'] = samples
    metrics['max_exp_log_roundtrip'] = worst
    metrics['note'] = '近 pi 主值/轴分支；SO2 (-pi,pi] 含 r[1,0]=-0.0'
    return metrics, violations


@case
def c2_dt_boundaries(sub):
    """C2 极小/极大 dt：恒等、次正规 dt、溢出拒绝、协方差单调。"""
    metrics, violations = {}, []
    g = sub.SE2
    mu = g.exp([0.3, -0.2, 0.4])
    p = np.diag([0.05, 0.04, 0.01])
    vel = np.array([0.5, -0.25, 0.3])
    rate = np.diag([1e-3, 1e-3, 1e-4])
    belief = sub.TangentGaussian(g, mu, p)

    zero = belief.predict(vel, 0.0, rate)
    d_mean = float(np.abs(zero.mean - mu).max())
    d_cov = float(np.abs(zero.covariance - p).max())
    metrics['dt0_mean_drift'] = d_mean
    metrics['dt0_cov_drift'] = d_cov
    metrics['dt0_exact_identity'] = bool(np.array_equal(zero.mean, mu) and np.array_equal(zero.covariance, p))
    if not metrics['dt0_exact_identity']:
        violations.append(f'dt=0 不是精确恒等（mean {d_mean:.3e}, cov {d_cov:.3e}）')

    tiny = belief.predict(vel, 5e-324, rate)  # 最小次正规数
    if not np.isfinite(tiny.mean).all() or not np.isfinite(tiny.covariance).all():
        violations.append('dt=5e-324 产生非有限值')
    metrics['subnormal_dt_cov_drift'] = float(np.abs(tiny.covariance - p).max())
    if metrics['subnormal_dt_cov_drift'] > 1e-17:
        violations.append('dt=5e-324 协方差漂移超过浮点分辨率')

    for dt in (1e-300, 1e-12, 1.0, 1e12, 1e300, 1e308):
        try:
            out = belief.predict(vel, dt, rate)
        except ValueError as exc:
            violations.append(f'dt={dt:g} 抛 ValueError（应可算或按文档拒绝）: {exc}')
            continue
        except Exception as exc:  # noqa: BLE001
            # 发现 F4：有限输入下 exp 的 _abc 用 python float ** 溢出，抛 OverflowError 而非 ValueError
            violations.append(f'dt={dt:g} 泄漏 {type(exc).__name__}: {exc}')
            metrics.setdefault('non_valueerror_dt', {})[repr(dt)] = f'{type(exc).__name__}: {exc}'
            continue
        if not (np.isfinite(out.mean).all() and np.isfinite(out.covariance).all()):
            violations.append(f'dt={dt:g} 产生非有限值')
        if np.linalg.eigvalsh(out.covariance)[0] <= 0:
            violations.append(f'dt={dt:g} 协方差非正定')
        g.validate(out.mean)
    rejected = []
    for dt in (-1.0, -1e-300, float('nan'), float('inf'), float('-inf')):
        try:
            belief.predict(vel, dt, rate)
            violations.append(f'dt={dt!r} 未被拒绝')
        except ValueError:
            rejected.append(repr(dt))
    metrics['rejected_dt'] = rejected

    traces = [float(np.trace(belief.predict(vel, dt, rate).covariance)) for dt in (0.0, 1e-9, 1e-3, 1.0, 1e3)]
    metrics['cov_trace_by_dt'] = traces
    if any(b < a - 1e-18 for a, b in zip(traces, traces[1:])):
        violations.append('协方差迹随 dt 不单调')

    small = belief.predict(vel, 1e-9, rate)
    step = float(np.linalg.norm(small.mean[:2, 2] - mu[:2, 2]))
    expect = float(np.linalg.norm(vel[:2]) * 1e-9)
    metrics['tiny_dt_step_relative_error'] = abs(step - expect) / expect
    if metrics['tiny_dt_step_relative_error'] > 1e-6:
        violations.append('极小 dt 位移不满足线性尺度律')
    return metrics, violations


@case
def c3_covariance_guards(sub):
    """C3 非正定/退化协方差注入：严格路径必须拒绝，半正定路径必须接受真 PSD。"""
    metrics, violations = {}, []
    guard = sub.covariance
    bad = {
        'indefinite': np.diag([1.0, 1.0, -1.0]),
        'singular': np.diag([1.0, 1.0, 0.0]),
        'asymmetric': np.array([[1.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
        'nan': np.full((3, 3), np.nan),
        'inf': np.diag([1.0, np.inf, 1.0]),
        'wrong_shape': np.eye(2),
    }
    for name, matrix in bad.items():
        try:
            guard(matrix, 3)
            violations.append(f'严格 SPD 路径静默接受 {name}')
        except ValueError:
            pass
        except Exception as exc:  # noqa: BLE001
            violations.append(f'{name} 抛非 ValueError: {type(exc).__name__}')
    ok_spd = guard(np.diag([1.0, 2.0, 3.0]), 3)
    if not np.allclose(ok_spd, np.diag([1.0, 2.0, 3.0])):
        violations.append('合法 SPD 被改写')
    for name, matrix in {'neg_def': -np.eye(3), 'nan': np.full((3, 3), np.nan)}.items():
        try:
            guard(matrix, 3, semidefinite=True)
            violations.append(f'半正定路径接受 {name}')
        except ValueError:
            pass

    # 真 PSD（rank-deficient）：文档说 information/过程协方差允许半正定以表达部分约束
    # 决定性样本：整数元素 → 存进 float64 后与精确矩阵逐位相同，且精确特征值非负。
    psd_cases = {
        'diag(1,1,0) 精确PSD': np.diag([1.0, 1.0, 0.0]),
        'outer([1,2,2]) 整数精确PSD': np.outer(np.array([1.0, 2.0, 2.0]), np.array([1.0, 2.0, 2.0])),
        'J^T J 整数精确PSD': np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 1.0]]).T @ np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 1.0]]),
    }
    rng = np.random.default_rng(4)
    psd_cases['u u^T 随机 rank1'] = np.outer(rng.normal(size=3), rng.normal(size=3))
    j = rng.normal(size=(2, 3))
    psd_cases['J^T J 随机 rank2'] = j.T @ j
    rejects = {}
    decisive = {}
    for name, matrix in psd_cases.items():
        exact = 'x' not in name  # 整数构造：精确特征值可判定非负
        count = 0
        for t in range(200):
            r = np.random.default_rng(2000 + t)
            m = matrix if ('整数' in name or name.startswith('diag')) else (
                np.outer(r.normal(size=3), r.normal(size=3)) if '随机 rank1' in name
                else (lambda a: a.T @ a)(r.normal(size=(2, 3))))
            try:
                guard(m, 3, semidefinite=True)
            except ValueError:
                count += 1
        rejects[name] = count
        if count:
            violations.append(f'半正定路径拒绝真 PSD [{name}] {count}/200 次')
        if exact:
            decisive[name] = {'eigmin_float64': float(np.linalg.eigvalsh(matrix)[0]),
                              'rejected': bool(count),
                              'exact_reason': '整数元素逐位精确；精确特征值 >= 0'}
    metrics['psd_rejections_per_200'] = rejects
    metrics['psd_exact_samples'] = decisive
    metrics['injected_bad_cases'] = sorted(bad)
    metrics['nonzero_evidence'] = int(sum(rejects.values()))
    return metrics, violations


@case
def c4_gravity_frame(sub):
    """C4 错误重力方向/退化水平参考，以及 lift/project 往返与 roll-pitch 拒绝。"""
    metrics, violations = {}, []
    frame_cls = sub.GravityFrame
    up = np.array([0.0, 0.0, 1.0])
    accept, reject = [], []
    tries = {
        'gravity=-9.81*up': (-9.81 * up, up, np.array([1.0, 0.0, 0.0])),
        'gravity=-9.81*up dev 1e-11': (-9.81 * up + 1e-11 * np.array([1.0, 0.0, 0.0]), up, np.array([1.0, 0.0, 0.0])),
        'gravity=+9.81*up (反号)': (9.81 * up, up, np.array([1.0, 0.0, 0.0])),
        'gravity=-9.81*up dev 1e-9': (-9.81 * up + 1e-9 * np.array([1.0, 0.0, 0.0]), up, np.array([1.0, 0.0, 0.0])),
        'horizontal || up': (-9.81 * up, up, up.copy()),
        'horizontal 垂直但极短 1e-13': (-9.81 * up, up, np.array([1e-13, 0.0, 0.0])),
        'horizontal 垂直但极短 1e-20': (-9.81 * up, up, np.array([1e-20, 0.0, 0.0])),
    }
    want_accept = {'gravity=-9.81*up', 'gravity=-9.81*up dev 1e-11',
                   'horizontal 垂直但极短 1e-13', 'horizontal 垂直但极短 1e-20'}
    results = {}
    for name, (gvec, uvec, hvec) in tries.items():
        try:
            frame_cls(gvec, uvec, hvec)
            results[name] = 'accepted'
        except ValueError as exc:
            results[name] = f'rejected: {exc}'
    metrics['gravity_guard_results'] = results
    for name, outcome in results.items():
        if name in want_accept and outcome != 'accepted':
            violations.append(f'合法输入被拒 [{name}]: {outcome}')
        if name not in want_accept and outcome == 'accepted':
            violations.append(f'非法输入被接受 [{name}]')

    # lift/project 往返、子群闭合、roll/pitch 拒绝
    worst_rt, worst_h, worst_up, worst_closure = 0.0, 0.0, 0.0, 0.0
    for uvec in (np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]), np.array([1.0, 2.0, 3.0]) / math.sqrt(14.0)):
        href = np.array([1.0, 0.0, 0.0]) if abs(uvec[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        frame = frame_cls(-9.81 * uvec, uvec, href)
        for seed in range(6):
            rng = np.random.default_rng(seed)
            planar = sub.SE2.exp(np.r_[rng.normal(size=2) * 2.0, rng.uniform(-math.pi, math.pi)])
            height = float(rng.normal())
            lifted = frame.lift(planar, height)
            back, got_h = frame.project(lifted)
            worst_rt = max(worst_rt, float(np.abs(back - planar).max()))
            worst_h = max(worst_h, abs(got_h - height))
            worst_up = max(worst_up, float(np.abs(lifted[:3, :3] @ (uvec / np.linalg.norm(uvec)) - uvec / np.linalg.norm(uvec)).max()))
        a = frame.lift(sub.SE2.exp([0.2, -0.3, 0.4]), 0.2)
        b = frame.lift(sub.SE2.exp([1.0, 2.0, -0.7]), 0.3)
        want = frame.lift(sub.SE2.compose(sub.SE2.exp([0.2, -0.3, 0.4]), sub.SE2.exp([1.0, 2.0, -0.7])), 0.5)
        worst_closure = max(worst_closure, float(np.abs(sub.SE3.compose(a, b) - want).max()))
        for roll in (1e-6, 1e-3):
            try:
                frame.project(sub.SE3.exp([0.0, 0.0, 0.0, roll, 0.0, 0.0]))
                violations.append(f'roll/pitch={roll:g} 未被拒绝')
            except ValueError:
                pass
    metrics['lift_project_roundtrip_max'] = worst_rt
    metrics['height_error_max'] = worst_h
    metrics['up_preserved_error_max'] = worst_up
    metrics['subgroup_closure_max'] = worst_closure
    if worst_rt > RTOL:
        violations.append(f'lift/project 往返误差 {worst_rt:.3e} > {RTOL:g}')
    if worst_h > RTOL:
        violations.append(f'高度往返误差 {worst_h:.3e} > {RTOL:g}')
    if worst_closure > RTOL:
        violations.append(f'子群闭合误差 {worst_closure:.3e} > {RTOL:g}')
    return metrics, violations


def _linear_graph(seed, n=6, wrong=True, noise=0.02):
    rng = np.random.default_rng(seed)
    truth = np.vstack([np.zeros((1, 2)), np.cumsum(rng.normal(size=(n - 1, 2)), axis=0)])
    edges = [(i, i + 1) for i in range(n - 1)] + ([(n - 1, 0)] if wrong else [])
    a = np.zeros((len(edges), n - 1))
    for k, (i, j) in enumerate(edges):
        if j:
            a[k, j - 1] += 1
        if i:
            a[k, i - 1] -= 1
    err = rng.normal(size=(len(edges), 2)) * noise
    if wrong:
        err[-1] = np.array([0.4, -0.3])  # 错误回环
    measured = a @ truth[1:] + err
    factors = [RelativeFactor(i, j, SE2.exp(np.r_[measured[k], 0.0]), np.eye(3))
               for k, (i, j) in enumerate(edges)]
    return truth, edges, a, err, measured, factors


@case
def c5_wrong_loop(sub):
    """C5 错误回环约束：GN 必须等于自写线性最小二乘，残差真实非零，界覆盖真误差。"""
    metrics, violations = {}, []
    worst_gap, min_residual, worst_bound_slack = 0.0, float('inf'), -float('inf')
    guard_ok = 0
    for seed in range(40):
        truth, edges, a, err, measured, factors = _linear_graph(seed)
        init = [SE2.identity()]
        for k in range(len(edges) - 1):
            init.append(SE2.compose(init[-1], factors[k].measurement))
        fit = sub.solve_pose_graph(SE2, init, factors, anchor=0, fixed_rotations=True)
        mine = np.linalg.lstsq(a, measured, rcond=None)[0]
        got = np.asarray([p[:2, 2] for p in fit.poses[1:]])
        worst_gap = max(worst_gap, float(np.abs(got - mine).max()))
        residual = float(np.linalg.norm(a @ mine - measured))
        min_residual = min(min_residual, residual)
        bound = sub.linear_translation_error_bound(a, np.ones(len(edges)), err)
        true_err = float(np.linalg.norm(got - truth[1:]))
        worst_bound_slack = max(worst_bound_slack, true_err - bound)
        if not np.array_equal(fit.poses[0], init[0]):
            violations.append(f'seed={seed}: anchor 未被逐位冻结')
        if fit.rank != fit.free_dimensions:
            violations.append(f'seed={seed}: rank {fit.rank} != free {fit.free_dimensions}')
    metrics['max_gn_vs_own_lstsq_gap'] = worst_gap
    metrics['min_ls_residual_norm'] = min_residual
    metrics['max_true_error_minus_bound'] = worst_bound_slack
    if worst_gap > RTOL:
        violations.append(f'GN 解与自写线性最小二乘差 {worst_gap:.3e} > {RTOL:g}')
    if min_residual < 0.1:
        violations.append(f'错误回环的最小残差 {min_residual:.3e} 过小（可能把不一致抹平）')
    if worst_bound_slack > RTOL:
        violations.append(f'解析界不覆盖真实误差，最大超出 {worst_bound_slack:.3e}')

    # 不可观/非法输入必须 fail-closed
    truth, edges, a, err, measured, factors = _linear_graph(0, n=3)
    probes = {
        'no anchor': lambda: sub.solve_pose_graph(SE2, [SE2.identity(), SE2.identity(), SE2.identity()], factors),
        'zero information': lambda: sub.solve_pose_graph(SE2, [SE2.identity(), SE2.identity()], [
            RelativeFactor(0, 1, SE2.exp([1, 0, 0]), np.zeros((3, 3)))], anchor=0),
        'singular info': lambda: sub.solve_pose_graph(SE2, [SE2.exp([0, 0, 0]), SE2.exp([1, 0, 0])], [
            RelativeFactor(0, 1, SE2.exp([1, 0, 0]), np.diag([1.0, 1.0, 0.0]))], anchor=0),
        'self edge': lambda: sub.solve_pose_graph(SE2, [SE2.identity(), SE2.identity()], [
            RelativeFactor(0, 0, SE2.identity(), np.eye(3))], anchor=0),
        'disconnected': lambda: sub.solve_pose_graph(SE2, [SE2.identity()] * 4, [
            RelativeFactor(0, 1, SE2.exp([1, 0, 0]), np.eye(3)),
            RelativeFactor(2, 3, SE2.exp([1, 0, 0]), np.eye(3))], anchor=0),
    }
    outcomes = {}
    for name, fn in probes.items():
        try:
            fn()
            outcomes[name] = 'accepted'
            violations.append(f'不可观/非法图形被接受 [{name}]')
        except (ObservabilityError, ValueError) as exc:
            outcomes[name] = type(exc).__name__
            guard_ok += 1
    metrics['fail_closed_guards'] = outcomes

    # gauge 语义：anchor 初值不是真值时，解 = gauge ∘ truth（用无噪声一致图，避免把噪声算成 gauge 偏差）
    truth, edges, a, err, measured, factors = _linear_graph(3, wrong=False, noise=0.0)
    gauge = SE2.exp([0.2, -0.1, 0.15])
    init = [SE2.compose(gauge, SE2.identity())]
    for k in range(len(edges)):  # 无闭环：每条边都要推进一步（共 m+1 个位姿）
        init.append(SE2.compose(init[-1], factors[k].measurement))
    fit = sub.solve_pose_graph(SE2, init, factors, anchor=0, fixed_rotations=True)
    shifted = [SE2.compose(gauge, SE2.exp(np.r_[t, 0.0])) for t in truth]
    gauge_gap = float(np.abs(np.asarray([p[:2, 2] for p in fit.poses]) -
                            np.asarray([p[:2, 2] for p in shifted])).max())
    metrics['gauge_semantics_gap'] = gauge_gap
    if gauge_gap > RTOL:
        violations.append(f'gauge 语义不符（解 != gauge ∘ truth）{gauge_gap:.3e}')
    return metrics, violations


def _position_of(group, t):
    return t[:group.dim, group.dim]


def _num_position_jacobian(sub, group, mu, side, eps=1e-7):
    """数值微分位置观测模型：扰动方向必须与该侧别一致（left: Exp(d) mu）。"""
    cols = []
    for k in range(group.dof):
        d = np.zeros(group.dof)
        d[k] = eps
        plus = _position_of(group, sub.boxplus(group, mu, d, side=side))
        minus = _position_of(group, sub.boxplus(group, mu, -d, side=side))
        cols.append((plus - minus) / (2 * eps))
    return np.column_stack(cols)


@case
def c6_observation_jacobian(sub):
    """C6 位置观测 Jacobian：与自写数值微分导出的增益独立对照（左右两侧、两群）。"""
    metrics, violations = {}, []
    worst = 0.0
    for group, name in ((sub.SE2, 'SE2'), (sub.SE3, 'SE3')):
        n = group.dim
        for side in ('right', 'left'):
            for seed in range(6):
                rng = np.random.default_rng(seed)
                mu = group.exp(rng.normal(size=group.dof) * 0.4)
                pm = rng.normal(size=(group.dof, group.dof))
                p = pm @ pm.T + np.eye(group.dof) * 0.01
                rw = np.diag(rng.uniform(0.005, 0.05, size=n))
                z = _position_of(group, mu) + rng.normal(size=n) * 0.01
                belief = sub.TangentGaussian(group, mu, p, side=side)
                _, gain = sub.position_update(belief, z, rw)
                h_true = _num_position_jacobian(sub, group, mu, side)
                rot = mu[:n, :n]
                if side == 'right':
                    h_eff, rn = rot.T @ h_true, rot.T @ rw @ rot
                else:
                    h_eff, rn = h_true, rw
                k_ref = p @ h_eff.T @ np.linalg.inv(h_eff @ p @ h_eff.T + rn)
                gap = float(np.linalg.norm(gain - k_ref) / max(np.linalg.norm(k_ref), 1e-300))
                worst = max(worst, gap)
                if gap > 1e-5:
                    violations.append(f'{name}/{side} seed={seed}: 增益与数值微分不一致 {gap:.3e}')
                moved, _ = sub.position_update(belief, z, np.eye(n) * 1e-10)
                if np.linalg.norm(_position_of(group, moved.mean) - z) > 1e-3:
                    violations.append(f'{name}/{side} seed={seed}: 高精度观测未把位置拉向测量')
    metrics['max_gain_vs_numeric_fd_relative_gap'] = worst
    metrics['note'] = 'G1 自测只比较左右一致，未与数值微分 Jacobian 对照'
    return metrics, violations


@case
def c7_tangent_sides(sub):
    """C7 左右切空间与 Adjoint 协方差：精确恒等式 + 蒙特卡洛一阶矩 + 侧别往返。"""
    metrics, violations = {}, []
    worst_identity, worst_roundtrip, worst_predict = 0.0, 0.0, 0.0
    mc = {}
    for group, name in ((sub.SE2, 'SE2'), (sub.SE3, 'SE3')):
        mu = group.exp(np.arange(1, group.dof + 1) / 9.0)
        ad = sub.adjoint_fn(group, mu)
        pm = np.arange(1, group.dof + 1) / 10.0
        p = np.diag(pm)
        ref = ad @ p @ ad.T
        for seed in range(4):
            rng = np.random.default_rng(seed)
            for scale in (1e-3, 1e-5):
                xi = rng.normal(size=group.dof) * scale
                x = group.compose(mu, group.exp(xi))
                xi_l = group.log(group.compose(x, group.inverse(mu)))
                worst_identity = max(worst_identity, float(np.abs(xi_l - ad @ xi).max()))
        for scale, samples in ((0.5, 20000), (0.2, 20000), (0.05, 20000)):
            rng = np.random.default_rng(99)
            chol = np.linalg.cholesky(p)
            draws = (chol @ rng.normal(size=(group.dof, samples))) * scale
            vals = np.empty((samples, group.dof))
            for k in range(samples):
                x = group.compose(mu, group.exp(draws[:, k]))
                vals[k] = group.log(group.compose(x, group.inverse(mu)))
            emp = np.cov(vals.T)
            ref_scaled = (scale ** 2) * ref  # xi_r 的协方差是 scale^2 * P
            rel = float(np.linalg.norm(emp - ref_scaled) / np.linalg.norm(ref_scaled))
            mc[f'{name}@{scale}'] = rel
            if scale == 0.05 and rel > 0.05:
                violations.append(f'{name} 蒙特卡洛一阶矩偏差 {rel:.3e} 过大')
        belief = sub.TangentGaussian(group, mu, p)
        left = belief.with_side('left')
        worst_roundtrip = max(worst_roundtrip, float(np.abs(left.with_side('right').covariance - p).max()))
        if not np.allclose(left.covariance, ref, atol=1e-15):
            violations.append(f'{name}: with_side 未用 Ad P Ad^T')
        a = belief.predict(np.ones(group.dof) * 0.05, 1e-3, np.eye(group.dof) * 1e-3)
        b = left.predict(np.ones(group.dof) * 0.05, 1e-3, np.eye(group.dof) * 1e-3).with_side('right')
        worst_predict = max(worst_predict,
                            float(np.abs(a.mean - b.mean).max()),
                            float(np.abs(a.covariance - b.covariance).max()))
    metrics['max_xi_left_minus_Ad_xi_right'] = worst_identity
    metrics['mc_relative_error_by_scale'] = mc
    metrics['max_side_roundtrip_gap'] = worst_roundtrip
    metrics['max_left_right_predict_gap'] = worst_predict
    if worst_identity > 1e-11:
        violations.append(f'xi_l = Ad(mu) xi_r 不成立（{worst_identity:.3e}）')
    if worst_roundtrip > 1e-15:
        violations.append(f'with_side 往返不精确（{worst_roundtrip:.3e}）')
    if worst_predict > 1e-12:
        violations.append(f'左右预测不一致（{worst_predict:.3e}）')
    return metrics, violations


def _hat(group, xi):
    if group is SE2:
        x, y, w = xi
        return np.array([[0.0, -w, x], [w, 0.0, y], [0.0, 0.0, 0.0]])
    rho, phi = xi[:3], xi[3:]
    out = np.zeros((4, 4))
    out[:3, :3] = skew(phi)
    out[:3, 3] = rho
    return out


def _exp_scaling_squaring(m):
    """独立矩阵指数：Taylor + scaling-and-squaring（G1 未实现该路径）。"""
    norm = float(np.abs(m).sum(axis=1).max())
    s = int(np.ceil(np.log2(norm / 0.5))) if norm > 0.5 else 0
    a = m / (2.0 ** s)
    out, term = np.eye(len(m)), np.eye(len(m))
    for k in range(1, 80):
        term = term @ a / k
        out += term
        if float(np.abs(term).max()) < 1e-18:
            break
    for _ in range(max(s, 0)):
        out = out @ out
    return out


def _taylor_abc(theta):
    t2 = theta * theta
    return (1 - t2 / 6 + t2 ** 2 / 120 - t2 ** 3 / 5040,
            0.5 - t2 / 24 + t2 ** 2 / 720 - t2 ** 3 / 40320,
            1 / 6 - t2 / 120 + t2 ** 2 / 5040 - t2 ** 3 / 362880)


class TaylorSE2(SE2):
    """故意改坏：_abc 永远走小角 Taylor（丢掉大角分支）。"""

    @staticmethod
    def exp(xi):
        x = np.asarray(xi, dtype=float)
        rho, w = x[:2], float(x[2])
        a, b, _ = _taylor_abc(w)
        j = np.array([[0.0, -1.0], [1.0, 0.0]])
        out = np.eye(3)
        out[:2, :2] = [[math.cos(w), -math.sin(w)], [math.sin(w), math.cos(w)]]
        out[:2, 2] = (a * np.eye(2) + b * w * j) @ rho
        return SE2.validate(out)


class TaylorSE3(SE3):
    """故意改坏：_abc 永远走小角 Taylor（丢掉大角分支）。"""

    @staticmethod
    def exp(xi):
        x = np.asarray(xi, dtype=float)
        phi = x[3:]
        theta = float(np.linalg.norm(phi))
        a, b, c = _taylor_abc(theta)
        k = skew(phi)
        k2 = k @ k
        out = np.eye(4)
        out[:3, :3] = np.eye(3) + a * k + b * k2
        out[:3, 3] = (np.eye(3) + b * k + c * k2) @ x[:3]
        return SE3.validate(out)


@case
def c8_independent_matrix_exponential(sub):
    """C8 独立矩阵指数对照：大角、2π 附近（SE Jacobian 近奇异）与 2pi 精确点。"""
    metrics, violations = {}, []
    worst = 0.0
    worst_rel = 0.0
    samples = 0
    for group, name, rdim in ((sub.SE2, 'SE2', 2), (sub.SE3, 'SE3', 3)):
        # 自检：小角下独立实现与 G1 一致（证明参考实现本身可信）
        tiny = np.r_[np.ones(rdim) * 0.1, np.ones(rdim) * 1e-6] if rdim == 3 else np.r_[np.ones(rdim) * 0.1, 1e-6]
        gap = float(np.abs(_exp_scaling_squaring(_hat(group, tiny)) - group.exp(tiny)).max())
        metrics[f'{name}_reference_selfcheck'] = gap
        if gap > 1e-14:
            violations.append(f'{name}: 独立矩阵指数自检不一致 {gap:.3e}')
        for seed in range(12):
            rng = np.random.default_rng(seed)
            axis = rng.normal(size=rdim)
            axis /= np.linalg.norm(axis)
            rho = rng.normal(size=rdim) * 3.0
            for theta in (0.0, 1e-12, 1e-8, 1e-4, 0.1, 1.0, math.pi - 1e-6, math.pi,
                          2 * math.pi - 1e-9, 2 * math.pi, 2 * math.pi + 1e-9, 10.0, 1e3):
                xi = np.r_[rho, axis * theta] if rdim == 3 else np.r_[rho, theta]
                got = group.exp(xi)
                ref = _exp_scaling_squaring(_hat(group, xi))
                scale = max(1.0, float(np.abs(ref).max()))
                err = float(np.abs(got - ref).max()) / scale
                worst = max(worst, float(np.abs(got - ref).max()))
                worst_rel = max(worst_rel, err)
                samples += 1
                if err > 1e-12:
                    violations.append(f'{name} theta={theta:g} seed={seed}: 与独立矩阵指数差 {err:.3e}')
                group.validate(got)
    metrics['samples'] = samples
    metrics['max_abs_gap_vs_independent_exp'] = worst
    metrics['max_scaled_gap'] = worst_rel
    metrics['note'] = '含 theta=2pi（SE Jacobian 精确奇异）与 1e3 大角'
    return metrics, violations


@case
def c9_covariance_long_run(sub):
    """C9 长运行数值稳定性：4000 步随机 predict/update 不得静默退化，且空操作必须逐位不变。"""
    metrics, violations = {}, []
    for group, name in ((sub.SE2, 'SE2'), (sub.SE3, 'SE3')):
        rng = np.random.default_rng(7)
        mu = group.exp(rng.normal(size=group.dof) * 0.3)
        p0 = np.diag(rng.uniform(1e-6, 1e-2, size=group.dof))
        belief = sub.TangentGaussian(group, mu, p0)
        # 空操作不变性：dt=0、零速度、零过程噪声 → 均值与协方差必须逐位不变
        noop = belief
        for _ in range(100):
            noop = noop.predict(np.zeros(group.dof), 0.0, np.zeros((group.dof, group.dof)))
        if not (np.array_equal(noop.mean, mu) and np.array_equal(noop.covariance, p0)):
            violations.append(f'{name}: 空操作不保值（mean {np.abs(noop.mean - mu).max():.3e}, '
                              f'cov {np.abs(noop.covariance - p0).max():.3e}）')
        fails, min_eig = 0, float('inf')
        for k in range(4000):
            try:
                belief = belief.predict(rng.normal(size=group.dof) * 0.5,
                                        10 ** rng.uniform(-3, 1),
                                        np.diag(rng.uniform(0.0, 1e-3, size=group.dof)))
                z = mu[:group.dim, group.dim] + rng.normal(size=group.dim) * 0.01
                belief, _ = sub.position_update(belief, z, np.diag(rng.uniform(1e-6, 1e-2, size=group.dim)))
            except Exception as exc:  # noqa: BLE001
                fails += 1
                if fails == 1:
                    metrics[f'{name}_first_failure'] = f'{type(exc).__name__}: {exc}'
            min_eig = min(min_eig, float(np.linalg.eigvalsh(belief.covariance)[0]))
        metrics[f'{name}_steps'] = 4000
        metrics[f'{name}_failures'] = fails
        metrics[f'{name}_min_eigenvalue'] = min_eig
        if fails:
            violations.append(f'{name}: 4000 步中 {fails} 步被拒/报错')
        if not np.isfinite(min_eig) or min_eig <= 0:
            violations.append(f'{name}: 协方差退化 eigmin={min_eig}')
    return metrics, violations


# ------------------------------------------------------------------- poisoning
POISONS = {
    'c1_near_singular_rotation': lambda: Subject(SE3=NaiveSE3),
    'c2_dt_boundaries': lambda: Subject(TangentGaussian=ZeroRejectingGaussian),
    'c3_covariance_guards': lambda: Subject(covariance=loose_covariance),
    'c4_gravity_frame': lambda: Subject(GravityFrame=SignFlipFrame),
    'c5_wrong_loop': lambda: Subject(solve_pose_graph=inverted_z_solve),
    'c6_observation_jacobian': lambda: Subject(position_update=signflip_position_update),
    'c7_tangent_sides': lambda: Subject(adjoint_fn=transposed_adjoint),
    'c8_independent_matrix_exponential': lambda: Subject(SE2=TaylorSE2, SE3=TaylorSE3),
    'c9_covariance_long_run': lambda: Subject(TangentGaussian=JitterGaussian),
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--json-out', type=Path, default=None)
    args = parser.parse_args()
    summary = {'cases': [], 'findings': [], 'controls': [], 'exit': 0}
    for fn in CASES:
        name = fn.__name__
        entry = {'case': name, 'doc': (fn.__doc__ or '').strip().splitlines()[0]}
        try:
            metrics, violations = fn(Subject())
            entry['metrics'] = metrics
            entry['violations'] = violations
        except Exception:  # noqa: BLE001
            entry['metrics'] = {}
            entry['violations'] = ['HARNESS ERROR:\n' + traceback.format_exc()]
        entry['verdict'] = 'PASS' if not entry['violations'] else 'FAIL(finding)'
        try:
            pmetrics, pviolations = None, []
            if name in POISONS:
                pmetrics, pviolations = fn(POISONS[name]())
            entry['poison_detected'] = bool(pviolations)
            entry['poison_violations'] = len(pviolations)
            entry['poison_example'] = (pviolations[0][:180] if pviolations else None)
        except Exception as exc:  # noqa: BLE001
            # poison 使用例直接崩掉也算"变红"（非零退出），但必须记录原因
            entry['poison_detected'] = True
            entry['poison_violations'] = -1
            entry['poison_example'] = f'poison crashed the case: {type(exc).__name__}: {exc}'
        summary['cases'].append(entry)
        if entry['verdict'] != 'PASS':
            summary['findings'].append(name)
        print(f"[{entry['verdict']:<14}] {name}: {len(entry['violations'])} 项违反, "
              f"poison_detected={entry.get('poison_detected')}")
        for v in entry['violations'][:4]:
            print('      - ' + v.replace('\n', ' ')[:220])
        print('      metrics: ' + json.dumps(entry['metrics'], ensure_ascii=False, default=str)[:400])
    controls_ok = all(c.get('poison_detected') for c in summary['cases'])
    summary['controls_all_red'] = controls_ok
    summary['exit'] = 1 if (summary['findings'] or not controls_ok) else 0
    print('---')
    print(f"cases={len(summary['cases'])} findings={len(summary['findings'])} "
          f"poison_all_detected={controls_ok} exit={summary['exit']}")
    if args.json_out:
        args.json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + '\n')
    if not controls_ok:
        print('复核自身失败：有 poison 未被检测（断言可能空转）')
    return summary['exit']


if __name__ == '__main__':
    sys.exit(main())
