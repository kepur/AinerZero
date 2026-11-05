#!/usr/bin/env python3
"""独立复核对抗反例套件（reports/V-V9-G5/independent_verification.py）。

包含 7 个独立设计的自写不利反例，对 G5 的 F1、F2、F3 修复及相关边界进行详尽检验。
所有判定使用严格断言，脚本真实退出码：
  0 = 全部自写反例通过（即被验代码在所有不利边界上均表现正确且 fail-closed）
  1 = 任一断言失败（发现缺陷或退化）

支持 --json-out 参数将详细结果保存为 JSON。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if not any("ainerzero/v9/geometry" in p for p in sys.path):
    if "PYTHONPATH" in os.environ:
        for p in reversed(os.environ["PYTHONPATH"].split(os.pathsep)):
            if p and p not in sys.path:
                sys.path.insert(0, p)
    else:
        sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from ainerzero.v9.geometry import (  # noqa: E402
    SE2,
    SE3,
    GravityFrame,
    ObservabilityError,
    RelativeFactor,
    TangentGaussian,
    solve_pose_graph,
)
from ainerzero.v9.geometry.belief import PSD_RELATIVE_TOL, covariance, psd_tolerance  # noqa: E402

# ---- 辅助函数 ----
def rot2d(theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]])


def random_orthogonal(dim: int, rng: np.random.Generator) -> np.ndarray:
    q, _ = np.linalg.qr(rng.standard_normal((dim, dim)))
    return q


def run_counterexamples() -> dict:
    results: dict = {
        "suite": "V9.G6 独立复核 G5 反例套件",
        "cases": [],
        "passed_count": 0,
        "failed_count": 0,
        "ok": True,
    }

    def record_case(cid: str, name: str, passed: bool, details: dict):
        status_str = "PASS" if passed else "FAIL"
        print(f"[{status_str}] {cid}: {name}")
        for k, v in details.items():
            print(f"       - {k}: {v}")
        results["cases"].append({
            "id": cid,
            "name": name,
            "passed": passed,
            "details": details,
        })
        if passed:
            results["passed_count"] += 1
        else:
            results["failed_count"] += 1
            results["ok"] = False

    rng = np.random.default_rng(20261020)

    # =========================================================================
    # C1: 近 PSD 与真负定边界对抗扫描（多维度、多尺度、不同秩亏、对称性扰动）
    # =========================================================================
    c1_ok = True
    c1_details: dict = {}
    scales = [1e-6, 1e-3, 1.0, 1e3, 1e6]
    dims = [2, 3, 6]
    c1_tested = 0
    c1_true_negatives_rejected = 0
    c1_near_psd_accepted = 0
    c1_asymmetric_rejected = 0

    for dim in dims:
        for scale in scales:
            q = random_orthogonal(dim, rng)
            norm_est = max(1.0, scale)
            tol = PSD_RELATIVE_TOL * norm_est

            for rank_def in [1, 2]:
                if rank_def >= dim:
                    continue
                c1_tested += 1

                # 1. 近 PSD（容差内的负特征值扰动）：最小特征值为 -0.5 * tol
                eigs_near = np.ones(dim) * scale
                for r in range(rank_def):
                    eigs_near[r] = 0.0
                eigs_near[0] = -0.5 * tol
                near_psd = q @ np.diag(eigs_near) @ q.T
                near_psd = (near_psd + near_psd.T) / 2.0
                try:
                    res_p = covariance(near_psd, dim, semidefinite=True)
                    assert res_p.shape == (dim, dim)
                    c1_near_psd_accepted += 1
                except Exception as exc:
                    c1_ok = False
                    c1_details[f"near_psd_fail_d{dim}_s{scale:g}_r{rank_def}"] = str(exc)

                # 2. 真负定（非法，必须拒绝）：最小特征值为 -1.5 * tol 与固定 -1e-6 * norm_est
                eigs_true_neg = np.ones(dim) * scale
                for r in range(rank_def):
                    eigs_true_neg[r] = 0.0
                eigs_true_neg[0] = -1.5 * tol
                true_neg = q @ np.diag(eigs_true_neg) @ q.T
                true_neg = (true_neg + true_neg.T) / 2.0
                try:
                    covariance(true_neg, dim, semidefinite=True)
                    c1_ok = False
                    c1_details[f"true_neg_leaked_d{dim}_s{scale:g}_r{rank_def}"] = "未被拒绝"
                except ValueError as exc:
                    if "positive semidefinite" in str(exc):
                        c1_true_negatives_rejected += 1
                    else:
                        c1_ok = False
                        c1_details[f"true_neg_wrong_exc_d{dim}_s{scale:g}_r{rank_def}"] = str(exc)

                # 2b. 固定真负定（-1e-6 * norm_est，防止容差被过度放宽）
                eigs_fixed_neg = np.ones(dim) * scale
                for r in range(rank_def):
                    eigs_fixed_neg[r] = 0.0
                eigs_fixed_neg[0] = -1e-6 * norm_est
                fixed_neg = q @ np.diag(eigs_fixed_neg) @ q.T
                fixed_neg = (fixed_neg + fixed_neg.T) / 2.0
                try:
                    covariance(fixed_neg, dim, semidefinite=True)
                    c1_ok = False
                    c1_details[f"fixed_neg_leaked_d{dim}_s{scale:g}_r{rank_def}"] = "真负定 -1e-6*norm 未被拒绝"
                except ValueError as exc:
                    if "positive semidefinite" in str(exc):
                        c1_true_negatives_rejected += 1
                    else:
                        c1_ok = False
                        c1_details[f"fixed_neg_wrong_exc_d{dim}_s{scale:g}_r{rank_def}"] = str(exc)

                # 3. 对称性扰动（即使特征值全正，破坏对称性必须被拒）
                asym = q @ np.diag(np.ones(dim) * scale) @ q.T
                asym = (asym + asym.T) / 2.0
                asym[0, 1] += 1e-4 * norm_est
                try:
                    covariance(asym, dim, semidefinite=True)
                    c1_ok = False
                    c1_details[f"asym_leaked_d{dim}_s{scale:g}"] = "未被拒绝"
                except ValueError as exc:
                    if "symmetric" in str(exc):
                        c1_asymmetric_rejected += 1
                    else:
                        c1_ok = False
                        c1_details[f"asym_wrong_exc_d{dim}_s{scale:g}"] = str(exc)

                # 4. 严格正定路径检查：semidefinite=False 时精确秩亏矩阵必须被拒
                psd_singular = np.diag([scale] * (dim - 1) + [0.0])
                try:
                    covariance(psd_singular, dim, semidefinite=False)
                    c1_ok = False
                    c1_details[f"strict_path_leaked_d{dim}_s{scale:g}"] = "严格路径放过了秩亏矩阵"
                except ValueError as exc:
                    assert "positive definite" in str(exc)

    c1_details.update({
        "tested_configurations": c1_tested,
        "near_psd_accepted": c1_near_psd_accepted,
        "true_negatives_rejected": c1_true_negatives_rejected,
        "asymmetric_rejected": c1_asymmetric_rejected,
        "tolerance_scales_tested": scales,
    })
    record_case("C1_PSD_BOUNDARY", "近 PSD 与真负定边界对抗扫描", c1_ok, c1_details)

    # =========================================================================
    # C2: pose_graph 秩亏 information 负舍入截断与不可观 fail-closed
    # =========================================================================
    c2_ok = True
    c2_details: dict = {}

    # Case 2a: 构造由秩亏信息因子组合成可观的 SE2 图
    # 两个边：边 1 只约束 x 平移 (rank 1)，边 2 约束 y 平移与旋转 (rank 2)
    info1 = np.diag([100.0, 0.0, 0.0])  # rank 1
    info2 = np.diag([0.0, 100.0, 50.0])  # rank 2
    # 注入微小数值舍入负特征值（在容差内）
    info1[1, 1] = -5e-14
    info2[0, 0] = -5e-14

    poses_init = [
        SE2.identity(),
        SE2.exp([1.0, 0.0, 0.0]),
        SE2.exp([1.0, 1.0, 0.1]),
    ]
    factors = [
        RelativeFactor(0, 1, SE2.exp([1.0, 0.0, 0.0]), info1),
        RelativeFactor(0, 1, SE2.exp([1.0, 0.0, 0.0]), info2),
        RelativeFactor(1, 2, SE2.exp([0.0, 1.0, 0.1]), np.eye(3) * 10.0),
    ]

    try:
        sol = solve_pose_graph(SE2, poses_init, factors, anchor=0)
        assert not np.any(np.isnan(sol.poses[1]))
        assert not np.any(np.isnan(sol.poses[2]))
        assert sol.converged
        c2_details["rank_deficient_sol_converged"] = True
        c2_details["rank_deficient_sol_rank"] = sol.rank
    except Exception as exc:
        c2_ok = False
        c2_details["rank_deficient_sol_error"] = str(exc)

    # Case 2b: 断图（包含孤立节点 3） -> 必须抛 ObservabilityError
    poses_broken = poses_init + [SE2.exp([5.0, 5.0, 0.0])]
    try:
        solve_pose_graph(SE2, poses_broken, factors, anchor=0)
        c2_ok = False
        c2_details["disconnected_graph_error"] = "断图未被捕获"
    except ObservabilityError as exc:
        c2_details["disconnected_graph_fail_closed"] = str(exc)
    except Exception as exc:
        c2_ok = False
        c2_details["disconnected_graph_unexpected_exc"] = f"{type(exc).__name__}: {exc}"

    # Case 2c: 缺锚（anchor is None） -> 必须抛 ObservabilityError
    try:
        solve_pose_graph(SE2, poses_init, factors, anchor=None)
        c2_ok = False
        c2_details["missing_anchor_error"] = "缺锚未被捕获"
    except ObservabilityError as exc:
        c2_details["missing_anchor_fail_closed"] = str(exc)
    except Exception as exc:
        c2_ok = False
        c2_details["missing_anchor_unexpected_exc"] = f"{type(exc).__name__}: {exc}"

    # Case 2d: 结构不可观（全部边都只测 x 坐标，旋转和 y 完全缺失）
    factors_unobs = [
        RelativeFactor(0, 1, SE2.exp([1.0, 0.0, 0.0]), info1),
        RelativeFactor(1, 2, SE2.exp([1.0, 0.0, 0.0]), info1),
    ]
    try:
        solve_pose_graph(SE2, poses_init, factors_unobs, anchor=0)
        c2_ok = False
        c2_details["unobservable_graph_error"] = "结构不可观未被捕获"
    except ObservabilityError as exc:
        c2_details["unobservable_graph_fail_closed"] = str(exc)
    except Exception as exc:
        c2_ok = False
        c2_details["unobservable_graph_unexpected_exc"] = f"{type(exc).__name__}: {exc}"

    record_case("C2_POSE_GRAPH_OBSERVABILITY", "pose_graph 秩亏负舍入截断与不可观 fail-closed", c2_ok, c2_details)

    # =========================================================================
    # C3: GravityFrame 水平参考向量尺度无关性与近平行/退化对抗测试
    # =========================================================================
    c3_ok = True
    c3_details: dict = {}
    gravity = np.array([0.0, 0.0, -9.81])
    up = np.array([0.0, 0.0, 1.0])

    # 1. 跨 26 个数量级（1e-13 到 1e13）的垂直参考向量必须全部 accepted 且基矩阵逐位一致
    scale_range = [1e-13, 1e-10, 1e-6, 1e-1, 1.0, 1e2, 1e6, 1e10, 1e13]
    baseline_basis = None
    max_basis_diff = 0.0
    for s in scale_range:
        h = np.array([s, 0.0, 0.0])
        try:
            gf = GravityFrame(gravity, up, h)
            if baseline_basis is None:
                baseline_basis = gf.basis
            else:
                diff = np.max(np.abs(gf.basis - baseline_basis))
                max_basis_diff = max(max_basis_diff, float(diff))
        except Exception as exc:
            c3_ok = False
            c3_details[f"scale_{s:g}_failed"] = str(exc)

    c3_details["scale_range_basis_max_diff"] = max_basis_diff
    assert max_basis_diff < 1e-15, f"不同尺度基矩阵存在微小漂移: {max_basis_diff}"

    # 2. 临界角度判定：|sin θ| 阈值 HORIZONTAL_SIN_TOL = 1e-9
    # 在尺度 1e-10, 1.0, 1e10 下构造：
    # h_accept: sin theta = 1.05e-9
    # h_reject: sin theta = 0.95e-9
    for s in [1e-10, 1.0, 1e10]:
        sin_acc = 1.05e-9
        cos_acc = math.sqrt(1.0 - sin_acc ** 2)
        h_acc = np.array([sin_acc * s, 0.0, cos_acc * s])
        try:
            GravityFrame(gravity, up, h_acc)
        except Exception as exc:
            c3_ok = False
            c3_details[f"critical_accept_failed_s{s:g}"] = str(exc)

        sin_rej = 0.95e-9
        cos_rej = math.sqrt(1.0 - sin_rej ** 2)
        h_rej = np.array([sin_rej * s, 0.0, cos_rej * s])
        try:
            GravityFrame(gravity, up, h_rej)
            c3_ok = False
            c3_details[f"critical_reject_leaked_s{s:g}"] = "临界近平行输入未被拒绝"
        except ValueError as exc:
            assert "|sin theta| < 1e-9" in str(exc)

    # 3. 完全平行参考（任意尺度）拒绝
    for s in [1e-13, 1.0, 1e13]:
        h_par = np.array([0.0, 0.0, s])
        try:
            GravityFrame(gravity, up, h_par)
            c3_ok = False
            c3_details[f"parallel_leaked_s{s:g}"] = "平行参考未被拒绝"
        except ValueError as exc:
            assert "parallel to gravity" in str(exc)

    # 4. 精确零向量与非有限值拒绝
    try:
        GravityFrame(gravity, up, np.zeros(3))
        c3_ok = False
        c3_details["zero_ref_leaked"] = "零向量未被拒绝"
    except ValueError as exc:
        assert "nonzero" in str(exc)

    for bad_vec in [np.array([np.nan, 0.0, 0.0]), np.array([np.inf, 1.0, 0.0])]:
        try:
            GravityFrame(gravity, up, bad_vec)
            c3_ok = False
            c3_details["nonfinite_ref_leaked"] = "非有限值未被拒绝"
        except ValueError as exc:
            assert "finite" in str(exc)

    c3_details["all_scales_invariant"] = True
    record_case("C3_GRAVITY_SCALE_INVARIANCE", "GravityFrame 水平参考向量尺度无关性与临界/退化对抗", c3_ok, c3_details)

    # =========================================================================
    # C4: 逐节差异与 S0 数学稳定性核实（架构文档 r3 vs r5 与调研文档）
    # =========================================================================
    c4_ok = True
    c4_details: dict = {}
    r2_reg_file = ROOT / "reports" / "V9-G1" / "r2" / "input_registration_r2.json"
    sec_changes_file = ROOT / "reports" / "V9-G1" / "r2" / "section_changes.json"

    assert r2_reg_file.is_file() and sec_changes_file.is_file()
    r2_reg = json.loads(r2_reg_file.read_text(encoding="utf-8"))
    sec_changes = json.loads(sec_changes_file.read_text(encoding="utf-8"))

    # 1. 核对 section_changes 的 SHA256 与登记一致
    computed_sec_sha = hashlib.sha256(sec_changes_file.read_bytes()).hexdigest()
    registered_sec_sha = r2_reg["section_changes_sha256"]
    if computed_sec_sha != registered_sec_sha:
        c4_ok = False
        c4_details["sec_changes_sha_mismatch"] = f"computed={computed_sec_sha} reg={registered_sec_sha}"

    # 2. 抽查 ARCHITECTURE_V9.md §4 与 §5
    arch_sections = sec_changes["documents"]["ARCHITECTURE_V9.md"]["sections"]
    sec_names = [s["title"] for s in arch_sections]
    assert any("数学定义" in s for s in sec_names), "缺少数学定义章节"
    assert any("研究顺序" in s for s in sec_names), "缺少研究顺序章节"

    # 检查 §4 中的 S0 结论标记
    sec_math = next(s for s in arch_sections if "数学定义" in s["title"])
    assert sec_math["s0_math_impact"] == "g1_reference_added", f"§4 标记不是 g1_reference_added: {sec_math['s0_math_impact']}"
    assert "以 G1 为准" in sec_math["s0_math_note"]

    # 3. 调研文档前缀检查
    survey_check = r2_reg["survey_old_text_prefix_check"]
    assert survey_check["old_text_is_prefix_of_new"] is True
    assert survey_check["appended_lines"] == 13

    # 独立读取验证 SURVEY 前缀
    git_survey = subprocess.run(
        ["git", "show", "995db72e6c9663083600a5096b1735153d8c0c7b:docs/research/V9_RESEARCH_SURVEY.md"],
        cwd=str(ROOT), capture_output=True, check=True
    ).stdout.decode("utf-8")
    curr_survey = (ROOT / "docs" / "research" / "V9_RESEARCH_SURVEY.md").read_text(encoding="utf-8")
    assert curr_survey.startswith(git_survey), "当前 survey 文档并非以旧 survey 为前缀"
    added_part = curr_survey[len(git_survey):]
    assert "## 9. r4 勘误" in added_part

    c4_details["sections_inspected"] = len(arch_sections)
    c4_details["s0_math_unchanged_verified"] = True
    c4_details["survey_prefix_verified"] = True
    record_case("C4_DOCUMENT_SECTIONS_AUDIT", "逐节差异与 S0 数学稳定性核验", c4_ok, c4_details)

    # =========================================================================
    # C5: 消费门未豁免文档逻辑与防篡改拦截验证
    # =========================================================================
    c5_ok = True
    c5_details: dict = {}
    verify_script = ROOT / "reports" / "V9-G1" / "r2" / "verify_registration_r2.py"
    verify_text = verify_script.read_text(encoding="utf-8")

    # 1. 静态代码审计：消费门中无豁免文档分支
    assert "exempt" not in verify_text.lower(), "消费门脚本中发现潜在的豁免关键字"
    assert "new_sha256" in verify_text, "消费门未核验 new_sha256"
    assert "curr_sha != expected_sha" in verify_text or "curr_sha != new_sha" in verify_text or "GateFailure" in verify_text

    # 2. 真实执行原 verify_registration_r2.py，必须通过
    proc_normal = subprocess.run([sys.executable, "-B", str(verify_script)], capture_output=True, text=True)
    if proc_normal.returncode != 0:
        c5_ok = False
        c5_details["normal_verify_failed"] = proc_normal.stderr
    else:
        c5_details["normal_verify_passed"] = True

    # 3. 故意构造被篡改文档哈希的临时登记，验证消费门真实 exit 1
    tampered_reg = json.loads(r2_reg_file.read_text(encoding="utf-8"))
    tampered_reg["documents"][0]["new_sha256"] = "a" * 64
    tmp_tampered_path = ROOT / "reports" / "V-V9-G5" / "evidence" / "tampered_reg_test.json"
    tmp_tampered_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_tampered_path.write_text(json.dumps(tampered_reg), encoding="utf-8")

    proc_tamper = subprocess.run(
        [sys.executable, "-B", str(verify_script), "--registration", str(tmp_tampered_path)],
        capture_output=True, text=True
    )
    if proc_tamper.returncode == 0:
        c5_ok = False
        c5_details["tamper_leak"] = "篡改文档哈希后消费门意外通过！"
    else:
        assert "FAIL" in (proc_tamper.stdout + proc_tamper.stderr) or "GateFailure" in (proc_tamper.stdout + proc_tamper.stderr)
        c5_details["tamper_successfully_blocked"] = f"exit_code={proc_tamper.returncode}"

    tmp_tampered_path.unlink(missing_ok=True)
    record_case("C5_CONSUMER_GATE_NO_EXEMPTION", "消费门未豁免文档逻辑与防篡改拦截核实", c5_ok, c5_details)

    # =========================================================================
    # C6: F4 异常类型与超大角边界状态核实
    # =========================================================================
    c6_ok = True
    c6_details: dict = {}

    # 核验大角度下的 SE2.exp 行为：
    # 1. 正常及极限安全大角 (θ = 1e3, 2π)：应精确计算且不溢出
    try:
        t_1e3 = SE2.exp([0.0, 0.0, 1000.0])
        assert not np.any(np.isnan(t_1e3))
        c6_details["se2_exp_1e3_safe"] = True
    except Exception as exc:
        c6_ok = False
        c6_details["se2_exp_1e3_fail"] = str(exc)

    # 2. 超大角 (θ = 1e103)：确认 G2 报告的 OverflowError 泄漏行为未被越权修改
    # 注意：由于 G5 明确说明 F4 不在本卡修改范围，复核必须确认其未被意外或静默改动
    try:
        SE2.exp([0.0, 0.0, 1e103])
        c6_ok = False
        c6_details["f4_overflow_silently_fixed"] = "F4 溢出被静默修复（超出本卡授权范围）"
    except OverflowError as exc:
        c6_details["f4_behavior_preserved"] = f"OverflowError 保留: {exc}"
    except Exception as exc:
        c6_ok = False
        c6_details["f4_unexpected_exception"] = f"{type(exc).__name__}: {exc}"

    # 3. predict(dt=1e300) 状态核验
    belief = TangentGaussian(SE2, SE2.exp([0, 0, 0]), np.eye(3))
    try:
        belief.predict([0.5, -0.25, 0.3], 1e300, np.eye(3) * 1e-3)
        c6_ok = False
        c6_details["f4_predict_overflow_silently_fixed"] = "predict(1e300) 被静默修复"
    except OverflowError as exc:
        c6_details["f4_predict_preserved"] = f"predict dt=1e300 OverflowError 保留: {exc}"
    except Exception as exc:
        c6_ok = False
        c6_details["f4_predict_unexpected"] = f"{type(exc).__name__}: {exc}"

    record_case("C6_F4_STATUS_AND_LARGE_ANGLE", "F4 超大角状态保留与安全角数值精度核实", c6_ok, c6_details)

    # =========================================================================
    # C7: 数值稳定性：近奇异协方差下的李群 EKF Predict/Update 闭环迭代测试
    # =========================================================================
    c7_ok = True
    c7_details: dict = {}

    # 在 SE2 上设置初值，过程噪声带有容差范围内的微小数值扰动（例如接近 rank-deficient 1）
    # 连续执行 100 步高频微扰 predict/update，验证协方差矩阵对称性与正定性保持，不发散
    prior_cov = np.diag([1e-2, 1e-2, 1e-4])
    filter_state = TangentGaussian(SE2, SE2.identity(), prior_cov)

    # 秩亏过程噪声（例如只在平移方向有噪声，角速度无噪声，但存在浮点舍入 -1e-15）
    proc_cov = np.diag([1e-3, 1e-3, 0.0])
    proc_cov[2, 2] = -5e-14  # 注入数值舍入小负数

    obs_cov = np.diag([1e-2, 1e-2])  # 2D 位置观测
    H = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])

    max_cov_norm = 0.0
    min_eig_recorded = 1.0

    for step in range(100):
        # 1. 预测步（已知速度 u = [0.1, 0.0, 0.02], dt = 0.1）
        filter_state = filter_state.predict(np.array([0.1, 0.0, 0.02]), 0.1, proc_cov)

        # 2. 模拟观测并更新
        pos_current = filter_state.mean[:2, 2]
        pos_meas = pos_current + rng.normal(0, 1e-2, size=2)
        residual = pos_meas - pos_current
        filter_state, _ = filter_state.update_tangent(residual, H, obs_cov, side="right")

        # 检验协方差合法性
        curr_cov = filter_state.covariance
        max_cov_norm = max(max_cov_norm, float(np.linalg.norm(curr_cov)))
        eigs = np.linalg.eigvalsh(curr_cov)
        min_eig_recorded = min(min_eig_recorded, float(eigs[0]))
        assert eigs[0] > 0, f"第 {step} 步滤波协方差变为非正定: {eigs[0]}"
        assert np.allclose(curr_cov, curr_cov.T, atol=1e-12), f"第 {step} 步滤波协方差失去对称性"

    c7_details.update({
        "iterations": 100,
        "max_cov_norm": max_cov_norm,
        "min_eig_recorded": min_eig_recorded,
        "stability_maintained": True,
    })
    record_case("C7_EKF_FILTER_NUMERICAL_STABILITY", "李群 EKF 在近秩亏过程噪声下的闭环稳定性", c7_ok, c7_details)

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-out")
    args = parser.parse_args()

    suite_res = run_counterexamples()
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(suite_res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    sys.exit(0 if suite_res["ok"] else 1)
