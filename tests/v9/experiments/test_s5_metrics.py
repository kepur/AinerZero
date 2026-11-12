"""S5 评测指标与统计模块契约测试（纯 CPU）。

测试覆盖：
- grid_ap: 手算例子（完美、反序、保守并列）、独立朴素实现比对、全0无正例返回nan；
- grid_ap_by_distance: 距离格分组切分与常数边界、单组正例隔离；
- disk_recall: sigmoid 与阈值 >= 判定、各组召回率统计；
- logd_rmse: nan 过滤、object / floor 0.5 边界判定与分组切分；
- ordering_accuracy: 预测相等算错、equal 对不计、partial 归属规则；
- steps_to_target / stair: 首点达标、中间线性插值、未达标删失、非单调首发达标；
- ga_decision: P228 §2.1 数值用例、达标线 0.589、通过/打回行为、A0==A4 判定 False；
- paired_world_bootstrap: 确定性、常数退化单点、expand_world_index 重复计入、
  等尾分位数（alpha/2）、n_nan。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.s5 import metrics as M


# ------------------------------------------------------------------------------------------------
# 1. grid_ap
# ------------------------------------------------------------------------------------------------
def _naive_grid_ap(scores: np.ndarray, targets: np.ndarray) -> float:
    """独立参照实现：纯 Python 遍历排序并按保守口径断言 AP。"""
    s = scores.ravel().tolist()
    t = targets.ravel().tolist()
    num_pos = sum(1 for v in t if v == 1)
    if num_pos == 0:
        return float("nan")

    # 保守排序：分数高的在前；分数相同时负例 (0) 排在正例 (1) 前面
    items = sorted(zip(s, t), key=lambda x: (-x[0], x[1]))

    tp = 0
    prec_sum = 0.0
    for rank, (_, target) in enumerate(items, start=1):
        if target == 1:
            tp += 1
            prec_sum += tp / rank
    return prec_sum / num_pos


def test_grid_ap_perfect_ranking():
    # 完美排序：AP = 1.0
    scores = np.array([10.0, 9.0, 1.0, 0.0])
    targets = np.array([1, 1, 0, 0])
    ap = M.grid_ap(scores, targets)
    assert ap == pytest.approx(1.0, abs=1e-8)


def test_grid_ap_completely_reversed():
    # 完全反序：
    # 排序后: rank 1 (neg), rank 2 (neg), rank 3 (pos, prec=1/3), rank 4 (pos, prec=2/4=0.5)
    # AP = (1/3 + 1/2) / 2 = 5/12 ≈ 0.41666667
    scores = np.array([1.0, 2.0, 3.0, 4.0])
    targets = np.array([1, 1, 0, 0])
    ap = M.grid_ap(scores, targets)
    assert ap == pytest.approx(5.0 / 12.0, abs=1e-8)


def test_grid_ap_conservative_tie_breaking():
    # 保守并列测试：
    # 两个样本分数完全相同 (0.5, 0.5)，标签一正一负 (1, 0)
    # 保守口径：负例排 rank 1 (prec 0/1)，正例排 rank 2 (prec 1/2 = 0.5) -> AP = 0.5
    # 若乐观（正例先排）：正例排 rank 1 (prec 1/1 = 1.0) -> AP = 1.0
    scores = np.array([0.5, 0.5])
    targets = np.array([1, 0])
    ap = M.grid_ap(scores, targets)
    assert ap == pytest.approx(0.5, abs=1e-8)

    # 复杂并列：
    # 分数 [9.0, 5.0, 5.0, 1.0]，标签 [1, 1, 0, 0]
    # 降序: 9.0 (t=1, rank 1, prec=1/1=1.0)
    #       5.0 (t=0, rank 2, prec=1/2=0.5)  <-- 负例在同分时先排
    #       5.0 (t=1, rank 3, prec=2/3)
    #       1.0 (t=0, rank 4, prec=2/4=0.5)
    # AP = (1.0 + 2/3) / 2 = 5/6 ≈ 0.83333333
    scores2 = np.array([9.0, 5.0, 5.0, 1.0])
    targets2 = np.array([1, 1, 0, 0])
    assert M.grid_ap(scores2, targets2) == pytest.approx(5.0 / 6.0, abs=1e-8)


def test_grid_ap_no_positives_returns_nan():
    scores = np.array([0.9, 0.8, 0.1])
    targets = np.array([0, 0, 0])
    assert math.isnan(M.grid_ap(scores, targets))


def test_grid_ap_matches_naive_implementation():
    rng = np.random.default_rng(42)
    for _ in range(10):
        scores = rng.standard_normal((2, 12, 7))
        targets = rng.integers(0, 2, size=(2, 12, 7))
        got = M.grid_ap(scores, targets)
        expected = _naive_grid_ap(scores, targets)
        assert got == pytest.approx(expected, abs=1e-8)


# ------------------------------------------------------------------------------------------------
# 2. grid_ap_by_distance
# ------------------------------------------------------------------------------------------------
def test_grid_ap_by_distance_groups_and_nan_isolation():
    scores = np.random.default_rng(0).standard_normal((1, 12, 7))
    targets = np.zeros((1, 12, 7), dtype=np.uint8)

    # 正例仅放在 far 组 (第 6 格)
    targets[0, 2, 6] = 1
    targets[0, 5, 6] = 1

    res = M.grid_ap_by_distance(scores, targets)
    assert set(res.keys()) == {"near", "mid", "far"}
    assert math.isnan(res["near"])
    assert math.isnan(res["mid"])

    # far 组的值必须严格等于单独在该子网格上计算的 AP
    expected_far = M.grid_ap(scores[..., 6:7], targets[..., 6:7])
    assert res["far"] == pytest.approx(expected_far, abs=1e-8)

    # 边界严格隔离测试：正例放在第 4 格 (属于 mid 组边界)
    # near (0..3) 绝不能包含第 4 格，因此 near 必须为 nan，而 mid 必须有值
    targets_mid = np.zeros((1, 12, 7), dtype=np.uint8)
    targets_mid[0, 1, 4] = 1
    res_mid = M.grid_ap_by_distance(scores, targets_mid)
    assert math.isnan(res_mid["near"])
    assert not math.isnan(res_mid["mid"])
    assert math.isnan(res_mid["far"])


def test_grid_ap_by_distance_mid_bin5_and_near_bin3():
    """三个距离组都要落到自己的格上。

    正例只在第 5 格时，mid 必须等于第 4–5 格上单独算的 AP。
    若 mid 被缩成只有第 4 格，这一组没有正例，返回 nan，本断言失败。
    正例只在第 3 格时，near 有正例、mid 为 nan。
    切片下标写死，不读 DISTANCE_GRID_GROUPS，避免和被改坏的常量一起漂移。
    """
    scores = np.random.default_rng(7).standard_normal((2, 12, 7))

    targets_bin5 = np.zeros((2, 12, 7), dtype=np.int64)
    targets_bin5[0, 1, 5] = 1
    targets_bin5[1, 4, 5] = 1
    res5 = M.grid_ap_by_distance(scores, targets_bin5)
    expected_mid = M.grid_ap(scores[..., 4:6], targets_bin5[..., 4:6])
    assert not math.isnan(expected_mid)
    assert math.isnan(M.grid_ap(scores[..., 4:5], targets_bin5[..., 4:5]))
    assert res5["mid"] == pytest.approx(expected_mid, abs=1e-8)
    assert math.isnan(res5["near"])
    assert math.isnan(res5["far"])

    targets_bin3 = np.zeros((2, 12, 7), dtype=np.int64)
    targets_bin3[0, 0, 3] = 1
    targets_bin3[1, 2, 3] = 1
    res3 = M.grid_ap_by_distance(scores, targets_bin3)
    expected_near = M.grid_ap(scores[..., 0:4], targets_bin3[..., 0:4])
    assert not math.isnan(expected_near)
    assert res3["near"] == pytest.approx(expected_near, abs=1e-8)
    assert math.isnan(res3["mid"])
    assert math.isnan(res3["far"])


# ------------------------------------------------------------------------------------------------
# 3. disk_recall
# ------------------------------------------------------------------------------------------------
def test_disk_recall_threshold_boundary_and_grouping():
    # 构造 1 段，两圆盘：
    # 圆盘 1 在 (az=2, dist=1)，分在 "full" 组，对应分数 = 0.0 (sigmoid(0.0) = 0.5)
    # 圆盘 2 在 (az=5, dist=4)，分在 "partial" 组，对应分数 = -1.0 (sigmoid(-1.0) ≈ 0.2689 < 0.5)
    scores = np.full((1, 12, 7), -10.0, dtype=np.float32)
    scores[0, 2, 1] = 0.0
    scores[0, 5, 4] = -1.0

    disk_groups = [
        [
            {"azimuth_bin": 2, "distance_bin": 1, "occlusion_group": "full", "distance_group": "< 2"},
            {"azimuth_bin": 5, "distance_bin": 4, "occlusion_group": "partial", "distance_group": "2–4"},
        ]
    ]

    # threshold = 0.5，sigmoid(0.0) 刚好等于 0.5，按照 >= 算命中
    rec_occ = M.disk_recall(scores, disk_groups, threshold=0.5, key="occlusion_group")
    assert rec_occ["full"] == (1, 1, 1.0)
    assert rec_occ["partial"] == (0, 1, 0.0)

    # 按距离组划分
    rec_dist = M.disk_recall(scores, disk_groups, threshold=0.5, key="distance_group")
    assert rec_dist["< 2"] == (1, 1, 1.0)
    assert rec_dist["2–4"] == (0, 1, 0.0)
    assert math.isnan(rec_dist["> 4"][2]) and rec_dist["> 4"][1] == 0


# ------------------------------------------------------------------------------------------------
# 4. logd_rmse
# ------------------------------------------------------------------------------------------------
def test_logd_rmse_nan_filtering_and_split_boundaries():
    pred = np.zeros((1, 16, 14, 14), dtype=np.float32)
    target = np.full((1, 16, 14, 14), np.nan, dtype=np.float32)
    sky = np.zeros((1, 16, 14, 14), dtype=np.float32)
    obj = np.zeros((1, 16, 14, 14), dtype=np.float32)

    # 块 A (0, 0, 1, 1): object 边界测试，obj = 0.5，diff = 2.0 - 1.0 = 1.0
    pred[0, 0, 1, 1] = 2.0
    target[0, 0, 1, 1] = 1.0
    obj[0, 0, 1, 1] = 0.5
    sky[0, 0, 1, 1] = 0.1

    # 块 B (0, 0, 2, 2): floor 边界测试，1 - sky - obj = 1 - 0.5 - 0.0 = 0.5，diff = 3.0 - 1.0 = 2.0
    pred[0, 0, 2, 2] = 3.0
    target[0, 0, 2, 2] = 1.0
    obj[0, 0, 2, 2] = 0.0
    sky[0, 0, 2, 2] = 0.5

    # 块 C (0, 0, 3, 3): 纯天空 target 为 nan，pred 任意，必须被忽略
    pred[0, 0, 3, 3] = 999.0
    target[0, 0, 3, 3] = np.nan

    # 全量：包含块 A 和 块 B
    rmse_all = M.logd_rmse(pred, target)
    expected_all = math.sqrt((1.0**2 + 2.0**2) / 2.0)
    assert rmse_all == pytest.approx(expected_all, abs=1e-6)

    # object 切分：只有块 A (obj >= 0.5)
    rmse_obj = M.logd_rmse(pred, target, obj=obj, split="object")
    assert rmse_obj == pytest.approx(1.0, abs=1e-6)

    # floor 切分：只有块 B (1 - sky - obj >= 0.5)
    rmse_floor = M.logd_rmse(pred, target, sky=sky, obj=obj, split="floor")
    assert rmse_floor == pytest.approx(2.0, abs=1e-6)


# ------------------------------------------------------------------------------------------------
# 5. ordering_accuracy
# ------------------------------------------------------------------------------------------------
def test_ordering_accuracy_rules():
    pred_logd_last = np.zeros((1, 14, 14), dtype=np.float32)

    # 设置预测深度
    pred_logd_last[0, 2, 2] = 1.0  # object 100
    pred_logd_last[0, 4, 4] = 2.0  # object 101
    pred_logd_last[0, 6, 6] = 2.0  # object 102 (同分用于测试预测相等)
    pred_logd_last[0, 8, 8] = 3.0  # pillar 1

    disk_groups = [
        [
            {"disk_id": 0, "occlusion_group": "full"},     # 100
            {"disk_id": 1, "occlusion_group": "partial"},  # 101
            {"disk_id": 2, "occlusion_group": "full"},     # 102
        ]
    ]

    pairs = [
        [
            # Pair 1: disk 100 vs disk 101 (closer="a", pred_a=1.0 < pred_b=2.0 -> correct)
            # disk 101 为 partial，因此此 pair 应归入 partial
            {
                "type": "disk_disk",
                "id_a": 100,
                "id_b": 101,
                "patch_a": (2, 2),
                "patch_b": (4, 4),
                "closer": "a",
            },
            # Pair 2: disk 101 vs disk 102 (closer="a", pred_a=2.0 == pred_b=2.0 -> 预测相等算错)
            {
                "type": "disk_disk",
                "id_a": 101,
                "id_b": 102,
                "patch_a": (4, 4),
                "patch_b": (6, 6),
                "closer": "a",
            },
            # Pair 3: 真值为 "equal" 的样本对不计
            {
                "type": "disk_disk",
                "id_a": 100,
                "id_b": 102,
                "patch_a": (2, 2),
                "patch_b": (6, 6),
                "closer": "equal",
            },
            # Pair 4: disk 100 vs pillar 1 (closer="a", pred_a=1.0 < pred_b=3.0 -> correct)
            # disk 100 为 full，因此此 pair 归入 full
            {
                "type": "disk_pillar",
                "id_a": 100,
                "id_b": 1,
                "patch_a": (2, 2),
                "patch_b": (8, 8),
                "closer": "a",
            },
        ]
    ]

    res = M.ordering_accuracy(pred_logd_last, pairs, disk_groups)

    # 检查真值 equal 对被过滤：有效对数共 3 对
    assert res["all"][0] == 3
    # 3 对中有 Pair 1 与 Pair 4 正确，Pair 2 因同分算错，总准确率 = 2/3
    assert res["all"][1] == pytest.approx(2.0 / 3.0, abs=1e-6)

    # disk_disk: Pair 1 (正确) + Pair 2 (错误) -> 2 对，准确率 0.5
    assert res["disk_disk"] == (2, 0.5)

    # disk_pillar: Pair 4 (正确) -> 1 对，准确率 1.0
    assert res["disk_pillar"] == (1, 1.0)

    # partial 组: 包含 Pair 1 与 Pair 2 -> 2 对，准确率 0.5
    assert res["partial"] == (2, 0.5)

    # full 组: 包含 Pair 4 -> 1 对，准确率 1.0
    assert res["full"] == (1, 1.0)


def test_ordering_equal_prediction_wrong_for_both_truths():
    """预测相等必须算错，且与真值是 a 还是 b 无关。

    去掉「相等算错」后，相等比较会落到 else 分支，预测一律记成 b。
    真值为 a 的那对仍然算错，真值为 b 的那对会被误判为对，准确率不再是 0。
    """
    pred = np.zeros((1, 14, 14), dtype=np.float64)
    pred[0, 1, 1] = 2.0
    pred[0, 2, 2] = 2.0
    pred[0, 3, 3] = 4.0
    pred[0, 4, 4] = 4.0

    disk_groups = [[
        {"disk_id": 0, "occlusion_group": "full"},
        {"disk_id": 1, "occlusion_group": "full"},
        {"disk_id": 2, "occlusion_group": "full"},
        {"disk_id": 3, "occlusion_group": "full"},
    ]]
    pairs = [[
        {
            "type": "disk_disk",
            "id_a": 100,
            "id_b": 101,
            "patch_a": (1, 1),
            "patch_b": (2, 2),
            "closer": "a",
        },
        {
            "type": "disk_disk",
            "id_a": 102,
            "id_b": 103,
            "patch_a": (3, 3),
            "patch_b": (4, 4),
            "closer": "b",
        },
    ]]

    res = M.ordering_accuracy(pred, pairs, disk_groups)
    assert res["all"] == (2, 0.0)
    assert res["disk_disk"] == (2, 0.0)


# ------------------------------------------------------------------------------------------------
# 6. steps_to_target
# ------------------------------------------------------------------------------------------------
def test_steps_to_target_interpolation_and_censoring():
    steps = [100.0, 200.0, 300.0, 400.0]
    cap = 500.0

    # 1. 首点即达标
    ap_first = [0.65, 0.70, 0.75, 0.80]
    s, censored = M.steps_to_target(steps, ap_first, target=0.60, cap=cap)
    assert s == 100.0 and not censored

    # 2. 中间线性插值：
    # target=0.60，第 1 点为 (200, 0.50)，第 2 点为 (300, 0.70)
    # 线性插值步数 = 200 + (0.60 - 0.50) / (0.70 - 0.50) * (300 - 200) = 250.0
    ap_mid = [0.40, 0.50, 0.70, 0.80]
    s, censored = M.steps_to_target(steps, ap_mid, target=0.60, cap=cap)
    assert s == pytest.approx(250.0, abs=1e-6) and not censored

    # 阶梯版：不插值，直接取 300.0
    s_stair, c_stair = M.steps_to_target_stair(steps, ap_mid, target=0.60, cap=cap)
    assert s_stair == 300.0 and not c_stair

    # 3. 从未达标（删失）
    ap_never = [0.10, 0.20, 0.30, 0.40]
    s, censored = M.steps_to_target(steps, ap_never, target=0.60, cap=cap)
    assert s == cap and censored
    s_stair, c_stair = M.steps_to_target_stair(steps, ap_never, target=0.60, cap=cap)
    assert s_stair == cap and c_stair

    # 4. 非单调曲线：取首次跨过阈值处
    # 在 step 100(0.40) 与 step 200(0.60) 之间首次跨过 0.55
    # 插值: 100 + (0.55 - 0.40) / 0.20 * 100 = 175.0
    ap_nonmon = [0.40, 0.60, 0.50, 0.70]
    s, censored = M.steps_to_target(steps, ap_nonmon, target=0.55, cap=cap)
    assert s == pytest.approx(175.0, abs=1e-6) and not censored


# ------------------------------------------------------------------------------------------------
# 7. ga_decision
# ------------------------------------------------------------------------------------------------
def test_ga_decision_p228_numerical_cases():
    steps = np.linspace(100, 1600, 16)
    cap = 1600.0

    # A0 三个种子末次 AP 分别为 0.60, 0.62, 0.64 -> 中位数 0.62
    # 达标线 = 0.95 * 0.62 = 0.589
    # 构造曲线使得 A0 达到 0.589 的步数分别为 1200, 1300, 1400 -> A0 步数中位数为 1300
    def make_a0_curve(reach_step: float, final_ap: float):
        # 简单斜率构建
        ap = np.linspace(0.2, final_ap, 16)
        return (steps, ap)

    # 调整使得达到 0.589 的步数准确匹配
    c_a0_0 = (steps, np.where(steps >= 1200, 0.60, 0.50))
    c_a0_1 = (steps, np.where(steps >= 1300, 0.62, 0.50))
    c_a0_2 = (steps, np.where(steps >= 1400, 0.64, 0.50))
    a0_curves = [c_a0_0, c_a0_1, c_a0_2]

    # 情形 1A (P228 §2.1): A4 步数分别为 500, 600, 1600 (种子 3 删失)
    # A4 中位数 = 600. 比值 600 / 1300 = 0.4615 <= 0.7 -> passed = True
    c_a4_0 = (steps, np.where(steps >= 500, 0.590, 0.50))
    c_a4_1 = (steps, np.where(steps >= 600, 0.595, 0.50))
    c_a4_2 = (steps, np.full(16, 0.580))  # 从未达到 0.589，删失为 1600
    a4_curves_pass = [c_a4_0, c_a4_1, c_a4_2]

    res_pass = M.ga_decision(a0_curves, a4_curves_pass, cap=cap)
    assert res_pass["a0_last_median"] == pytest.approx(0.62, abs=1e-6)
    assert res_pass["target_ap"] == pytest.approx(0.589, abs=1e-6)
    # 阶梯版（取检查点步数）：中位数分别为 1300 与 600
    assert res_pass["stair"]["median_a0"] == 1300.0
    assert res_pass["stair"]["median_a4"] == 600.0
    assert res_pass["stair"]["ratio"] == pytest.approx(600.0 / 1300.0, abs=1e-6)
    assert res_pass["stair"]["passed"] is True

    # 线性插值版：
    assert res_pass["median_a0"] == pytest.approx(1274.1666666666667, abs=1e-6)
    assert res_pass["passed"] is True

    # 情形 1B (P228 §2.1): A4 全部未能达到 0.589，全部删失为 1600
    c_a4_fail = (steps, np.full(16, 0.580))
    res_fail = M.ga_decision(a0_curves, [c_a4_fail, c_a4_fail, c_a4_fail], cap=cap)
    assert res_fail["median_a4"] == 1600.0
    assert res_fail["passed"] is False

    # 零假设 H0: A4 与 A0 完全一样
    res_h0 = M.ga_decision(a0_curves, a0_curves, cap=cap)
    assert res_h0["ratio"] == pytest.approx(1.0, abs=1e-6)
    assert res_h0["passed"] is False

    # 临界判定测试：A4 步数中位数为 950，A0 步数中位数为 1274.17 (stair 为 1300)
    # 比值约为 950 / 1274 ≈ 0.745 > 0.7，必须判定为 passed = False (严格防止阈值从 0.7 放宽)
    c_a4_marginal = (steps, np.where(steps >= 950, 0.590, 0.50))
    res_marginal = M.ga_decision(a0_curves, [c_a4_marginal, c_a4_marginal, c_a4_marginal], cap=cap)
    assert 0.70 < res_marginal["ratio"] < 0.80
    assert res_marginal["passed"] is False


# ------------------------------------------------------------------------------------------------
# 8. paired_world_bootstrap
# ------------------------------------------------------------------------------------------------
def test_paired_world_bootstrap_properties():
    # 1. 种子固定时结果确定
    res1 = M.paired_world_bootstrap(32, lambda idx: float(np.mean(idx)), n_boot=200, seed=123)
    res2 = M.paired_world_bootstrap(32, lambda idx: float(np.mean(idx)), n_boot=200, seed=123)
    assert res1["point_estimate"] == res2["point_estimate"]
    assert res1["ci"] == res2["ci"]

    # 2. stat_fn 恒为常数时区间退化成一点
    res_const = M.paired_world_bootstrap(16, lambda idx: 42.0, n_boot=100, seed=0)
    assert res_const["point_estimate"] == 42.0
    assert res_const["ci_lower"] == 42.0
    assert res_const["ci_upper"] == 42.0
    assert res_const["bootstrap_std"] == 0.0

    # 3. expand_world_index：验证世界抽样时段的重复展开
    w_idx = np.array([2, 0, 2])
    expanded = M.expand_world_index(w_idx, clips_per_world=16)
    assert len(expanded) == 3 * 16
    # 世界 2 的段 [32..47] 出现两次
    assert np.array_equal(expanded[0:16], np.arange(32, 48))
    assert np.array_equal(expanded[16:32], np.arange(0, 16))
    assert np.array_equal(expanded[32:48], np.arange(32, 48))


def test_paired_world_bootstrap_single_positive_world_repetition():
    # 构造只有一个世界有正例的情形验证：
    # 假设共 4 个世界，每个世界 2 段。
    # 只有世界 0 包含正例：段 0 有 3 个正例，段 1 有 2 个正例（世界 0 共 5 个正例）；
    # 世界 1、2、3 所有段正例数均为 0。
    # 统计量定义为：抽样世界展开后的总正例数除以抽样段数。
    world_pos = np.array([5, 0, 0, 0], dtype=np.int64)

    def stat_fn(sampled_worlds: np.ndarray) -> float:
        # 当世界 0 被重复抽中 k 次时，总正例数为 5 * k
        k = np.sum(sampled_worlds == 0)
        return float(5 * k)

    # 验证当 sampled_worlds = [0, 0, 1, 2] 时，世界 0 被抽中 2 次，返回 10.0
    assert stat_fn(np.array([0, 0, 1, 2])) == 10.0
    # 点估计：全部 4 个世界 [0, 1, 2, 3]，世界 0 出现 1 次，返回 5.0
    res = M.paired_world_bootstrap(4, stat_fn, n_boot=500, seed=42)
    assert res["point_estimate"] == 5.0
    # 在 4 个世界中重抽样 4 次，二项分布 B(4, 0.25)
    # k 的取值可能为 0, 1, 2, 3, 4，对应统计量为 0, 5, 10, 15, 20
    assert res["ci_lower"] <= 5.0 <= res["ci_upper"]
    assert res["bootstrap_std"] > 0.0
    assert res["n_nan"] == 0


def _independent_world_bootstrap(n_worlds, stat_fn, n_boot, seed, level):
    """按生产函数同一 seed、同一 rng.choice 顺序重放自助样本，分位用 alpha/2。"""
    rng = np.random.default_rng(seed)
    vals = np.empty(n_boot, dtype=np.float64)
    for b in range(n_boot):
        idx = rng.choice(n_worlds, size=n_worlds, replace=True)
        vals[b] = float(stat_fn(idx))
    alpha = 1.0 - level
    lo = float(np.percentile(vals, 100.0 * (alpha / 2.0)))
    hi = float(np.percentile(vals, 100.0 * (1.0 - alpha / 2.0)))
    wrong_lo = float(np.percentile(vals, 100.0 * alpha))
    return lo, hi, wrong_lo


def test_paired_world_bootstrap_equal_tail_percentiles():
    """等尾区间的下界必须是 (1-level)/2，不能是未减半的 alpha。"""
    values = np.array([0.0, 1.0, 3.0, 6.0, 10.0, 15.0, 21.0, 28.0], dtype=np.float64)

    def stat_fn(idx: np.ndarray) -> float:
        return float(np.mean(values[np.asarray(idx, dtype=np.int64)]))

    widths = []
    for level in (0.95, 0.9833):
        res = M.paired_world_bootstrap(
            len(values), stat_fn, n_boot=2000, seed=0, level=level,
        )
        lo, hi, wrong_lo = _independent_world_bootstrap(
            len(values), stat_fn, n_boot=2000, seed=0, level=level,
        )
        assert res["point_estimate"] == pytest.approx(float(np.mean(values)), abs=1e-12)
        assert res["ci_lower"] == pytest.approx(lo, abs=1e-12)
        assert res["ci_upper"] == pytest.approx(hi, abs=1e-12)
        assert res["ci"] == (res["ci_lower"], res["ci_upper"])
        assert abs(lo - wrong_lo) > 1e-4
        assert res["n_nan"] == 0
        assert res["n_boot"] == 2000
        assert res["seed"] == 0
        assert res["level"] == pytest.approx(level, abs=1e-12)
        widths.append(hi - lo)
    assert widths[1] > widths[0]


def test_paired_world_bootstrap_counts_nan_replicates():
    """重抽结果为 nan 时计入 n_nan，且 np.percentile 把整个区间变成 nan。"""
    def stat_fn(idx: np.ndarray) -> float:
        idx = np.asarray(idx)
        if np.any(idx == 0):
            return float(np.mean(idx))
        return float("nan")

    res = M.paired_world_bootstrap(5, stat_fn, n_boot=400, seed=1, level=0.95)
    assert 0 < res["n_nan"] < 400
    assert math.isnan(res["ci_lower"])
    assert math.isnan(res["ci_upper"])
    assert math.isnan(res["ci"][0]) and math.isnan(res["ci"][1])


def test_metric_validation_and_error_handling():
    # 维度不匹配报错
    with pytest.raises(ValueError, match="scores shape"):
        M.grid_ap(np.zeros((2, 12, 7)), np.zeros((3, 12, 7)))

    # 距离格维度不匹配
    with pytest.raises(ValueError, match="last dimension"):
        M.grid_ap_by_distance(np.zeros((1, 12, 6)), np.zeros((1, 12, 6)))

    # rmse 缺失必要参数
    with pytest.raises(ValueError, match="obj must be provided"):
        M.logd_rmse(np.zeros((1, 16, 14, 14)), np.zeros((1, 16, 14, 14)), split="object")

    with pytest.raises(ValueError, match="both sky and obj"):
        M.logd_rmse(np.zeros((1, 16, 14, 14)), np.zeros((1, 16, 14, 14)), split="floor")

    # 未知 split
    with pytest.raises(ValueError, match="unknown split"):
        M.logd_rmse(np.zeros((1, 16, 14, 14)), np.zeros((1, 16, 14, 14)), split="invalid")
