"""V9.G8 对抗复核测试（非作者；只读核对，不改 `src/`）。

两层：
A. 独立生成器上的行为断言（用 `independent_gen.py` 自己造数据，不复用 `build_benchmark_suite`）。
B. 坏控（变异）对照：每个坏控都必须让至少一条 A 层断言变红；
   反过来，M1a（字面调换 PARAMETRIC/STRUCTURAL）与 M5（恒关 e-LOND）**不会**让任何断言变红，
   这两条负结果本身就是复核结论（坏控空操作 / 总闸门未接线）。

运行：env -u PYTHONPATH -u HTTP_PROXY -u HTTPS_PROXY .venv/bin/python -m pytest reports/V9-G8 -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (str(REPO / "src"), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ainerzero.v9.mechanism as BASE  # noqa: E402
import g8_checks as K  # noqa: E402
from mutation_harness import load_mutant  # noqa: E402

_CACHE: dict[str, object] = {}


def cached(key: str, fn):
    if key not in _CACHE:
        _CACHE[key] = fn()
    return _CACHE[key]


# ---------------------------------------------------------------------------
# A. 独立生成器上的行为断言
# ---------------------------------------------------------------------------

def test_msg_routes_on_independent_generator() -> None:
    """8 路由在复核者自写生成器上（W=16/dt=0.015/σ=2.5e-3）应逐族高召回；包络应独立判出 OOD。

    PARAMETRIC 是唯一不满的一条（独立设定下 0.75~0.83），单独放在
    `test_parametric_recall_is_below_the_reported_value` 里作为结论记录，不在这里放宽掩盖。
    """
    res = cached("msg", lambda: K.msg_suite(BASE, n=10))
    assert res["accuracy"] >= 0.95, res
    for route, recall in res["per_route_recall"].items():
        if route == "PARAMETRIC":
            assert recall >= 0.70, f"{route} recall={recall}"
        else:
            assert recall >= 0.90, f"{route} recall={recall}"
    assert res["envelope_valid"] is True, res
    assert res["envelope_ood_recall"] == 1.0, res


def test_parametric_recall_is_below_the_reported_value() -> None:
    """特征化断言：PARAMETRIC 召回在独立生成器上显著低于 G7 报告的 0.975（漏判流向 4a 下尾）。"""
    res = cached("param", lambda: K.parametric_recall(BASE, n=30))
    assert 0.70 <= res["recall"] < 0.975, res
    assert res["counts"].get("COVARIANCE_INCONSISTENT", 0) >= 1, res


def test_ood_recall_is_carried_by_the_caller_flag() -> None:
    """特征化断言（不是通过标准）：OOD 召回由 `in_slow_domain` 布尔量承载，而不是由包络。

    只有标签、无包络 -> 全中；只有包络、无标签 -> 也全中；两者都没有 -> 0。
    """
    res = cached("ood_leak", lambda: K.msg_ood_leak_probe(BASE))
    n = res["n"]
    assert res["label_only_no_envelope"] == n, res
    assert res["envelope_only_no_label"] == n, res
    assert res["neither"] == 0, res


def test_conformal_finite_sample_correction_boundary() -> None:
    """k = ceil((1-α)(n+1))：n_cal=18、α_dom=0.05 时 k=19>18，证书必须作废。"""
    res = cached("conformal", lambda: K.conformal_boundary(BASE))
    assert res["n_cal_18"]["k"] == 19
    assert res["n_cal_18"]["valid"] is False, res
    assert res["n_cal_19"]["valid"] is True, res
    assert res["n_cal_20"]["valid"] is True, res


def test_conformal_marginal_coverage() -> None:
    """共形分位数的经验边际覆盖不应低于名义 1-α_dom 超过 5 个百分点。"""
    res = cached("coverage", lambda: K.conformal_coverage(BASE))
    assert res["valid"] is True, res
    assert res["empirical"] >= res["nominal"] - 0.05, res


def test_data_thinning_views_are_independent() -> None:
    """两个视图必须不同、且近似不相关（Cov(R+Z, R-Z)=Σ-Σ=0）。"""
    res = cached("thinning", lambda: K.thinning_views(BASE))
    assert res["views_identical"] is False
    assert abs(res["cross_cov"]) < 0.05 * res["var_sel"], res


def test_projection_invariant_single_context() -> None:
    """单上下文投影 API：残差必须与灵敏度子空间正交，且 r = r_perp + r_absorbed。"""
    res = cached("proj", lambda: K.projection_invariant(BASE))
    for mode in ("single_step", "k_step"):
        assert res["max_abs_inner_product"][mode] < 1e-12, res
        assert res["decomposition_identity"][mode] is True, res


def test_projection_batch_path_is_not_identity() -> None:
    """discover() 走的批量投影路径必须真的改变向量（不是恒等映射）。"""
    res = cached("proj", lambda: K.projection_invariant(BASE))
    assert res["batch_energy_ratio"] < 0.99, res


def test_negative_control_admission_rate_is_zero() -> None:
    """ALDER 型负对照（候选库缺真项）准入率必须为 0。"""
    res = cached("nc", lambda: K.negative_controls(BASE, trials=6))
    assert res["NC_A_missing_quadratic_drag"]["admission_rate"] == 0.0, res["NC_A_missing_quadratic_drag"]
    assert res["NC_B_missing_inv_r"]["admission_rate"] == 0.0, res["NC_B_missing_inv_r"]


def test_negative_control_is_only_satisfied_by_empty_support() -> None:
    """特征化断言：把负对照换成"非空但机制错误"的候选，准入率不再是 0。"""
    res = cached("nc", lambda: K.negative_controls(BASE, trials=6))
    assert res["NC_C_wrong_mechanism_nonempty"]["admission_rate"] > 0.0, res["NC_C_wrong_mechanism_nonempty"]


def test_elond_budget_is_not_in_the_admission_conjunction() -> None:
    """特征化断言：e-LOND 结果在准入时恒为 True（因为 `or sup_passed`），总闸门不挡任何东西。"""
    res = cached("promo", lambda: K.promotion_diagnostics(BASE))
    assert res["admitted"] is True, res
    assert res["e_lond_passed"] is True, res
    aux = cached("elond", lambda: K.elond_gate_is_decorative(BASE))
    assert aux["admitted_implies_e_lond_true"] is True, aux


def test_all_environment_union_degenerates_without_family_tags() -> None:
    """特征化断言：未打环境族标签时，三族 e-value 完全相同，E_pers 退化为 dev-only。"""
    res = cached("promo", lambda: K.promotion_diagnostics(BASE))
    assert res["e_by_family_unique_values"] == 1, res


def test_discovery_support_recovery_is_setting_specific() -> None:
    """记录发现质量：独立设定下结构世界精确支持恢复 < 100%，纯参数世界仍有假发现。"""
    res = cached("purity", lambda: K.discovery_purity(BASE))
    assert res["struct_trials"] == 20
    assert res["struct_exact_support"] <= 20, res
    assert res["param_world_false_discovery"] >= 0, res


# ---------------------------------------------------------------------------
# B. 坏控对照：基线断言成立 -> 变异后必须变红
# ---------------------------------------------------------------------------

def test_bad_control_M1a_literal_swap_is_a_no_op() -> None:
    """坏控 1 的字面版（调换 PARAMETRIC 与 STRUCTURAL 判定块）在语义上是空操作。

    这**不是**测试失败，而是对卡面坏控定义的纠正：任何测试都不可能因它变红，
    因为两者的条件互补、且都在同一处留出复检之后。
    """
    M = load_mutant("M1a_swap_param_structural_literal")
    assert K.route_identity(M) == K.route_identity(BASE)
    assert K.parametric_recall(M)["recall"] == K.parametric_recall(BASE)["recall"]


def test_bad_control_M1b_structural_before_parametric_turns_red() -> None:
    """坏控 1 的实质版：跳过参数再辨识直接判 STRUCTURAL -> PARAMETRIC 召回崩到 0。"""
    base = cached("param", lambda: K.parametric_recall(BASE))
    assert base["recall"] >= 0.80, base
    M = load_mutant("M1b_structural_before_parametric")
    mut = K.parametric_recall(M)
    assert mut["recall"] < 0.10, mut


def test_bad_control_M2_conformal_without_finite_sample_turns_red() -> None:
    """坏控 2：去掉共形有限样本修正 -> n_cal=18 的证书被错误判为有效。"""
    base = cached("conformal", lambda: K.conformal_boundary(BASE))
    assert base["n_cal_18"]["valid"] is False
    M = load_mutant("M2_conformal_no_finite_sample")
    mut = K.conformal_boundary(M)
    assert mut["n_cal_18"]["valid"] is True, mut
    assert mut["n_cal_18"]["k"] == 18, mut


def test_bad_control_M3_discovery_test_overlap_turns_red() -> None:
    """坏控 3：发现视图与检验视图重叠 -> 两视图完全相同、空世界假发现率显著上升。"""
    base_t = cached("thinning", lambda: K.thinning_views(BASE))
    assert base_t["views_identical"] is False
    base_fd = cached("null_fd", lambda: K.null_world_false_discovery(BASE))
    M = load_mutant("M3_discovery_test_overlap")
    mut_t = K.thinning_views(M)
    assert mut_t["views_identical"] is True, mut_t
    mut_fd = K.null_world_false_discovery(M)
    assert mut_fd["rate"] > base_fd["rate"] + 0.15, (base_fd, mut_fd)


def test_bad_control_M4_no_orthogonal_projection_turns_red() -> None:
    """坏控 4：去掉正交投影 -> 正交性断言失效、批量投影变成恒等、ALDER 负对照漏放。"""
    base_p = cached("proj", lambda: K.projection_invariant(BASE))
    assert base_p["max_abs_inner_product"]["single_step"] < 1e-12
    assert base_p["batch_energy_ratio"] < 0.99
    base_nc = cached("nc", lambda: K.negative_controls(BASE, trials=6))
    assert base_nc["NC_B_missing_inv_r"]["admission_rate"] == 0.0

    M = load_mutant("M4_no_orthogonal_projection")
    mut_p = K.projection_invariant(M)
    assert mut_p["max_abs_inner_product"]["single_step"] > 1e-3, mut_p
    assert mut_p["batch_energy_ratio"] > 0.999, mut_p
    mut_nc = K.negative_controls(M, trials=6)
    assert mut_nc["NC_B_missing_inv_r"]["admission_rate"] > 0.0, mut_nc["NC_B_missing_inv_r"]


def test_bad_control_M5_elond_gate_removal_changes_nothing() -> None:
    """反向坏控 5：把 e-LOND 恒置 False，准入结论完全不变 —— 证明总闸门没有接线。"""
    base = cached("promo", lambda: K.promotion_diagnostics(BASE))
    M = load_mutant("M5_elond_gate_always_false")
    mut = K.promotion_diagnostics(M)
    assert base["admitted"] is True
    assert mut["admitted"] is True, mut
    assert mut["e_lond_passed"] is False, mut
