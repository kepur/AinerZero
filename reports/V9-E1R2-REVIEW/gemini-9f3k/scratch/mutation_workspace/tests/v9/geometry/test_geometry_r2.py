"""G1 r2 小修回归测试：F1 半正定相对容差 / F2 重力水平参考方向判定。

对应 `reports/V-V9-G1/`（G2 非作者复核）登记的 F1/F2；G2 的 F4（exp 在超大角
泄漏 OverflowError）不在 r2 文件范围，本文件不断言其行为。r1 的 49 项测试仍由
`tests/v9/geometry/test_geometry.py` 承担；本文件只新增 r2 正反例与 G2 最小复现。

判据里的 1e-12（PSD 相对容差）与 1e-9（水平参考 |sin theta| 容差）按 r2 登记写死
为字面量，不读取被测实现的常量：故意把实现改坏时必须真实变红。
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from ainerzero.v9.geometry import (
    SE2,
    SE3,
    GravityFrame,
    KnownRotationGaussian,
    ObservabilityError,
    RelativeFactor,
    TangentGaussian,
    solve_pose_graph,
)
from ainerzero.v9.geometry.belief import covariance

PSD_RTOL = 1e-12  # r2 登记的相对容差 tol = 1e-12 * max(1, ||M||_2)
SIN_TOL = 1e-9  # r2 登记的水平参考方向容差 |sin theta| < 1e-9 拒绝


def close(a, b, tol=1e-9):
    assert np.max(np.abs(np.asarray(a) - np.asarray(b))) <= tol


def psd_tol(matrix):
    m = np.asarray(matrix, dtype=float)
    return PSD_RTOL * max(1.0, float(np.linalg.norm(m, 2)))


def rank1(vector):
    v = np.asarray(vector, dtype=float)
    return np.outer(v, v)


def planar_pose(x, y):
    pose = np.eye(3)
    pose[:2, 2] = (x, y)
    return pose


def spatial_pose(x, y, z):
    pose = np.eye(4)
    pose[:3, 3] = (x, y, z)
    return pose


# ---------------------------------------------------------------------------
# F1：半正定守卫接受精确 PSD 的秩亏矩阵（G2 C3 的 200/200 拒绝输入）
# ---------------------------------------------------------------------------

G2_PSD_INTEGER_MATRICES = {
    "outer([1,2,2])": rank1([1.0, 2.0, 2.0]),
    "integer J^T J": np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 1.0]]).T
    @ np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 1.0]]),
}


@pytest.mark.parametrize("name", sorted(G2_PSD_INTEGER_MATRICES))
def test_f1_guard_accepts_exact_psd_integer_matrices(name):
    matrix = G2_PSD_INTEGER_MATRICES[name]
    # 前提：元素是逐位精确的整数，精确特征值非负；float64 eigvalsh 只是舍入为小负数。
    assert np.array_equal(matrix, np.round(matrix))
    assert np.all(np.abs(matrix) < 2 ** 53)
    assert np.linalg.eigvalsh(matrix)[0] < 0, "G2 输入必须复现 float64 负特征值，否则本测试失去意义"
    out = covariance(matrix, 3, semidefinite=True)
    assert np.array_equal(out, out.T)
    close(out, (matrix + matrix.T) / 2, 0)
    assert np.linalg.eigvalsh(out)[0] >= -psd_tol(matrix)


def test_f1_guard_accepts_rank_deficient_psd_inputs():
    inputs = {
        "diag(1,1,0)": np.diag([1.0, 1.0, 0.0]),
        "normalized u u^T": rank1(np.array([1.0, 0.5, 0.0]) / np.linalg.norm([1.0, 0.5, 0.0])),
        "zero matrix": np.zeros((3, 3)),
        "rank-2 PSD sum": rank1([1.0, 2.0, 2.0]) + rank1([2.0, -1.0, 2.0]),
    }
    for tag, matrix in inputs.items():
        assert np.linalg.eigvalsh(matrix)[0] >= -psd_tol(matrix), tag
        out = covariance(matrix, 3, semidefinite=True)
        assert np.isfinite(out).all(), tag
        assert np.linalg.eigvalsh(out)[0] >= -psd_tol(matrix), tag


def test_f1_guard_tolerance_is_relative_not_absolute():
    base = rank1([1.0, 2.0, 2.0])
    for scale in (1e6, 1e12):
        matrix = base * scale
        smallest = np.linalg.eigvalsh(matrix)[0]
        assert smallest < 0
        assert abs(smallest) > 1e-12, f"scale {scale}: 绝对 1e-12 容差会拒绝这个精确 PSD 输入"
        out = covariance(matrix, 3, semidefinite=True)
        assert np.linalg.eigvalsh(out)[0] >= -psd_tol(matrix)
    # 小尺度精确 PSD 也接受（浮点舍入特征值远小于 1e-12 绝对门）。
    assert covariance(base * 1e-6, 3, semidefinite=True).shape == (3, 3)


@pytest.mark.parametrize("scale", [1e-3, 1.0, 1e6])
def test_f1_guard_boundary_matches_registered_relative_formula(scale):
    # 矩阵谱范数 ~ scale；登记容差 = 1e-12 * max(1, ||M||_2)。
    tolerance = PSD_RTOL * max(1.0, scale)

    accepted = np.diag([scale, scale, -0.5 * tolerance])
    out = covariance(accepted, 3, semidefinite=True)
    assert np.linalg.eigvalsh(out)[0] >= -psd_tol(accepted)

    rejected = np.diag([scale, scale, -2.0 * tolerance])
    with pytest.raises(ValueError, match="positive semidefinite"):
        covariance(rejected, 3, semidefinite=True)


def test_f1_guard_rejects_true_negative_definite():
    cases = {
        "min eig = -1e-6*||M||": np.diag([1.0, 1.0, -1e-6]),
        "min eig = -1e-6*||M|| (scaled)": np.diag([10.0, 10.0, -1e-5]),
        "negative semidefinite": -rank1([1.0, 2.0, 2.0]),
        "rotated negative direction": np.array(
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        )
        - 1e-6 * rank1([1.0, 0.0, 0.0]),
    }
    for tag, matrix in cases.items():
        with pytest.raises(ValueError, match="positive semidefinite"):
            covariance(matrix, 3, semidefinite=True)


@pytest.mark.parametrize(
    "bad",
    [
        np.array([[1.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]),
        np.full((3, 3), np.nan),
        np.full((3, 3), np.inf),
        np.eye(2),
    ],
)
def test_f1_guard_still_rejects_malformed_input(bad):
    with pytest.raises(ValueError):
        covariance(bad, 3, semidefinite=True)


def test_f1_strict_positive_definite_path_unchanged():
    covariance(np.eye(3) * 0.01, 3)
    with pytest.raises(ValueError, match="positive definite"):
        covariance(np.diag([1.0, 1.0, 0.0]), 3)
    with pytest.raises(ValueError, match="positive definite"):
        covariance(np.diag([1.0, 1.0, -1e-13]), 3)
    with pytest.raises(ValueError, match="positive definite"):
        TangentGaussian(SE2, SE2.identity(), np.diag([1.0, 1.0, 0.0]))


def test_f1_rank_deficient_process_noise_accepted_downstream():
    right = TangentGaussian(SE2, SE2.identity(), np.eye(3) * 0.04)
    rate = rank1([1.0, 2.0, 2.0]) * 1e-6
    predicted = right.predict([0.1, -0.2, 0.05], 1.0, rate)
    assert np.isfinite(predicted.mean).all() and np.isfinite(predicted.covariance).all()
    assert np.linalg.eigvalsh(predicted.covariance)[0] > 0

    conditional = KnownRotationGaussian(SE2, SE2.identity(), np.eye(2) * 0.04)
    predicted = conditional.predict([0.1, -0.2], 1.0, rank1([1.0, 2.0]) * 1e-6)
    assert np.isfinite(predicted.translation_covariance).all()
    assert np.linalg.eigvalsh(predicted.translation_covariance)[0] > 0


# ---------------------------------------------------------------------------
# F1：pose_graph 用秩亏 PSD information 表达部分约束
# ---------------------------------------------------------------------------

### 可观测的秩亏 information 组合（整数 PSD 输入，会被相对容差接受）
SE2_PARTIAL_INFORMATION = [
    rank1([1.0, 2.0, 2.0]),
    rank1([2.0, 1.0, -2.0]),
    rank1([2.0, -2.0, 1.0]),
]


def test_f1_pose_graph_accepts_rank_deficient_information_and_solves():
    poses = [SE2.identity(), SE2.exp([1.0, 0.5, 0.2])]
    measurement = SE2.compose(SE2.inverse(poses[0]), poses[1])
    factors = [RelativeFactor(0, 1, measurement, info) for info in SE2_PARTIAL_INFORMATION]
    for info in SE2_PARTIAL_INFORMATION:
        assert np.linalg.eigvalsh(info)[0] < 0, "整数 PSD 输入必须复现 float64 负特征值"
    fit = solve_pose_graph(SE2, poses, factors, anchor=0)
    assert fit.converged
    assert fit.rank == fit.free_dimensions == 3
    assert np.isfinite(np.asarray(fit.poses)).all()
    assert fit.residual_norm <= 1e-9


def test_f1_pose_graph_accepts_se3_rank_deficient_information():
    poses = [spatial_pose(0, 0, 0), spatial_pose(1.0, 0.5, -0.2)]
    measurement = SE3.compose(SE3.inverse(poses[0]), poses[1])
    factors = []
    for axis in range(3):
        info = np.zeros((6, 6))
        info[axis, axis] = 1.0
        factors.append(RelativeFactor(0, 1, measurement, info))
    fit = solve_pose_graph(SE3, poses, factors, anchor=0, fixed_rotations=True)
    assert fit.converged
    assert fit.rank == fit.free_dimensions == 3
    assert np.isfinite(np.asarray(fit.poses)).all()
    assert fit.residual_norm <= 1e-9


def test_f1_pose_graph_partial_constraints_with_fixed_rotations():
    poses = [planar_pose(0, 0), planar_pose(1, 0), planar_pose(1, 1)]
    factors = [
        RelativeFactor(0, 1, SE2.exp([1, 0, 0]), np.diag([1.0, 0.0, 0.0])),
        RelativeFactor(0, 1, SE2.exp([1, 0, 0]), np.diag([0.0, 1.0, 0.0])),
        RelativeFactor(1, 2, SE2.exp([0, 1, 0]), np.diag([1.0, 0.0, 0.0])),
        RelativeFactor(1, 2, SE2.exp([0, 1, 0]), np.diag([0.0, 1.0, 0.0])),
    ]
    fit = solve_pose_graph(SE2, poses, factors, anchor=0, fixed_rotations=True)
    assert fit.converged
    assert fit.rank == fit.free_dimensions == 4
    assert np.isfinite(np.asarray(fit.poses)).all()
    close(np.asarray([p[:2, 2] for p in fit.poses]), np.asarray([p[:2, 2] for p in poses]), 1e-12)


def test_f1_pose_graph_clamps_tolerated_negative_information_without_nan():
    poses = [planar_pose(0, 0), planar_pose(1, 0), planar_pose(1, 1)]
    tiny_negative_information = np.diag([-5e-13, 1.0, 0.0])
    assert -psd_tol(tiny_negative_information) <= -5e-13 < 0
    factors = [
        RelativeFactor(0, 1, SE2.exp([1, 0, 0]), np.diag([1.0, 0.0, 0.0])),
        RelativeFactor(0, 1, SE2.exp([1, 0, 0]), np.diag([0.0, 1.0, 0.0])),
        RelativeFactor(1, 2, SE2.exp([0, 1, 0]), np.diag([1.0, 0.0, 0.0])),
        RelativeFactor(1, 2, SE2.exp([0, 1, 0]), tiny_negative_information),
    ]
    fit = solve_pose_graph(SE2, poses, factors, anchor=0, fixed_rotations=True)
    assert fit.converged
    assert fit.rank == fit.free_dimensions == 4
    for pose in fit.poses:
        assert np.isfinite(pose).all(), "容差内负特征值必须截为 0，不能开方出 NaN"
    close(np.asarray([p[:2, 2] for p in fit.poses]), np.asarray([p[:2, 2] for p in poses]), 1e-12)


def test_f1_pose_graph_partial_information_keeps_fail_closed_checks():
    # G2 最小复现的下游：2 个位姿 + 1 条 rank-1 PSD information 仍不可观。
    rank_one = rank1([1.0, 2.0, 2.0])
    with pytest.raises(ObservabilityError, match="unobserved"):
        solve_pose_graph(
            SE2,
            [SE2.identity(), SE2.exp([1.0, 0.0, 0.0])],
            [RelativeFactor(0, 1, SE2.exp([1.0, 0.0, 0.0]), rank_one)],
            anchor=0,
        )
    # 缺锚、断图仍 fail-closed（与 r1 行为一致）。
    eye = np.eye(3)
    factors = [RelativeFactor(0, 1, SE2.identity(), eye), RelativeFactor(1, 2, SE2.identity(), eye)]
    poses = [planar_pose(0, 0), planar_pose(1, 0), planar_pose(2, 0)]
    with pytest.raises(ObservabilityError, match="no anchor"):
        solve_pose_graph(SE2, poses, factors)
    with pytest.raises(ObservabilityError, match="unobserved"):
        solve_pose_graph(SE2, poses, [RelativeFactor(0, 1, SE2.identity(), eye)], anchor=0)


# ---------------------------------------------------------------------------
# F2：重力水平参考按方向判定，与尺度无关（G2 C4）
# ---------------------------------------------------------------------------

F2_SCALES = (1e-20, 1e-13, 1e-12, 1e-9, 1e-6, 1.0, 1e8)


@pytest.mark.parametrize("scale", F2_SCALES)
def test_f2_exactly_perpendicular_reference_accepted_at_any_scale(scale):
    up = np.array([0.0, 0.0, 1.0])
    frame = GravityFrame([0.0, 0.0, -9.81], up, np.array([scale, 0.0, 0.0]))
    assert np.array_equal(frame.basis[:, 2], up)
    close(frame.basis[:, 0], np.array([1.0, 0.0, 0.0]), 1e-15)
    pose = SE2.exp([0.3, -0.4, 0.2])
    lifted = frame.lift(pose, 0.7)
    restored, height = frame.project(lifted)
    close(restored, pose, 1e-12)
    assert abs(height - 0.7) <= 1e-12


def test_f2_basis_independent_of_reference_scale():
    frames = [GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], [s, 0.0, 0.0]) for s in F2_SCALES]
    for frame in frames[1:]:
        close(frame.basis, frames[0].basis, 1e-14)


@pytest.mark.parametrize("scale", (1e-20, 1.0, 1e8))
def test_f2_small_tilt_verdict_is_scale_independent(scale):
    angle = 2e-9  # |sin theta| = 2e-9 > 1e-9，方向合法
    reference = scale * np.array([math.sin(angle), 0.0, math.cos(angle)])
    frame = GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], reference)
    x = frame.horizontal_reference - frame.basis[:, 2] * (
        frame.basis[:, 2] @ frame.horizontal_reference
    )
    sin_theta = np.linalg.norm(x) / np.linalg.norm(frame.horizontal_reference)
    assert sin_theta == pytest.approx(math.sin(angle), rel=1e-6, abs=1e-15)
    close(frame.basis[:, 0], np.array([1.0, 0.0, 0.0]), 1e-7)


@pytest.mark.parametrize("scale", (1e-20, 1.0, 1e8))
def test_f2_parallel_reference_rejected_scale_independent(scale):
    reference = scale * np.array([0.0, 0.0, 1.0])
    with pytest.raises(ValueError, match="parallel"):
        GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], reference)


@pytest.mark.parametrize("scale", (1e-20, 1.0, 1e8))
def test_f2_near_parallel_reference_rejected_scale_independent(scale):
    angle = 5e-10  # |sin theta| = 5e-10 < 1e-9，必须拒绝
    reference = scale * np.array([math.sin(angle), 0.0, math.cos(angle)])
    with pytest.raises(ValueError, match="parallel"):
        GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], reference)


def test_f2_rejects_zero_and_nonfinite_reference():
    with pytest.raises(ValueError, match="nonzero"):
        GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0])
    for bad in (np.array([np.nan, 0.0, 0.0]), np.array([np.inf, 0.0, 0.0]),
                np.array([-np.inf, 0.0, 0.0])):
        with pytest.raises(ValueError, match="finite"):
            GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], bad)
    with pytest.raises(ValueError):
        GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], [1.0, 0.0])


def test_f2_rejects_invalid_gravity_and_up():
    with pytest.raises(ValueError, match="nonzero"):
        GravityFrame([0.0, 0.0, 0.0], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="nonzero"):
        GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="opposite"):
        GravityFrame([0.0, 0.0, 9.81], [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])
    for bad in (np.array([np.nan, 0.0, 0.0]), np.array([0.0, np.inf, 0.0])):
        with pytest.raises(ValueError, match="finite"):
            GravityFrame(bad, [0.0, 0.0, 1.0], [1.0, 0.0, 0.0])


def test_f2_rejection_message_states_the_actual_criterion():
    angle = 1e-12
    reference = np.array([math.sin(angle), 0.0, math.cos(angle)])
    with pytest.raises(ValueError) as excinfo:
        GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], reference)
    message = str(excinfo.value)
    assert "parallel" in message and "1e-9" in message
    with pytest.raises(ValueError) as zero_excinfo:
        GravityFrame([0.0, 0.0, -9.81], [0.0, 0.0, 1.0], [0.0, 0.0, 0.0])
    assert "nonzero" in str(zero_excinfo.value) and "parallel" not in str(zero_excinfo.value)


@pytest.mark.parametrize("up", ([0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [1.0, 2.0, 3.0]))
def test_f2_previously_accepted_frames_unchanged(up):
    up = np.asarray(up, dtype=float)
    up /= np.linalg.norm(up)
    horizontal = [1.0, 0.0, 0.0] if abs(up[0]) < 0.9 else [0.0, 1.0, 0.0]
    frame = GravityFrame(-9.81 * up, up, horizontal)
    basis = frame.basis
    close(basis.T @ basis, np.eye(3), 1e-15)
    assert np.linalg.det(basis) == pytest.approx(1.0, abs=1e-15)
    pose = SE2.exp([1.0, 2.0, 0.7])
    restored, height = frame.project(frame.lift(pose, 0.4))
    close(restored, pose, 1e-12)
    assert abs(height - 0.4) <= 1e-12


# ---------------------------------------------------------------------------
# G2 最小复现（reports/V-V9-G1/findings_minimal_repro.py 的 F1/F2 部分）转绿
# ---------------------------------------------------------------------------

def test_g2_minimal_reproduction_f1_f2_is_green():
    # --- F1：G2 的精确整数 PSD 输入必须被接受 ---
    int_rank1 = rank1([1.0, 2.0, 2.0])
    j = np.array([[1.0, 2.0, 0.0], [0.0, 1.0, 1.0]])
    int_jtj = j.T @ j
    for matrix in (int_rank1, int_jtj):
        assert np.array_equal(matrix, np.round(matrix))
        covariance(matrix, 3, semidefinite=True)  # 修复前：ValueError
    # G2 的下游检查：rank-deficient PSD information 不再被协方差守卫拒绝，
    # 而是进入既有可解性检查并 fail-closed 为 ObservabilityError。
    with pytest.raises(ObservabilityError) as excinfo:
        solve_pose_graph(
            SE2,
            [SE2.identity(), SE2.exp([1.0, 0.0, 0.0])],
            [RelativeFactor(0, 1, SE2.exp([1.0, 0.0, 0.0]), int_rank1)],
            anchor=0,
        )
    assert "positive semidefinite" not in str(excinfo.value)

    # --- F2：同方向不同尺度结论一致（G2 的尺度表） ---
    up = np.array([0.0, 0.0, 1.0])
    verdicts = {}
    for scale in (1e-20, 1e-13, 1e-12, 1e-9, 1.0, 1e8):
        try:
            GravityFrame([0.0, 0.0, -9.81], up, np.array([scale, 0.0, 0.0]))
            verdicts[scale] = "accepted"
        except ValueError as exc:  # pragma: no cover - 变红路径
            verdicts[scale] = f"rejected({exc})"
    assert all(verdict == "accepted" for verdict in verdicts.values()), verdicts
