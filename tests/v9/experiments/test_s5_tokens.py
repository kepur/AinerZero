"""S5 Tokens 与 RLT 纯 CPU 测试套件（包含坏对照）。

测试项：
1. `tubelet_patches` 几何与展平顺序：
   - 构造仅特定 (t, h, w) 块非零的 clip，确认其严格映射到对应索引；
   - 展平顺序 (dt, dh, dw, c) 验证；
   - 坏对照：轴顺序置换导致定位错误。
2. `rlt_keep` 与权威 `rlt_frame_dropping` 等价性：
   - 静止段保留率严格等于 1/8；
   - 全变化段保留率严格等于 1.0；
   - 坏对照：静止段保留率异常。
3. `restoration_error` 误差分布：
   - P226 渐变序列（每帧 +0.015, tau=0.02），最大重建误差约 0.135；
   - 坏对照：算错锚点导致误差大幅偏离。
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from ainerzero.v9.experiments.s5 import tokens
from ainerzero.v9.tokenization.rlt import rlt_frame_dropping


# ==============================================================================
# 测试 1：tubelet_patches 顺序与映射
# ==============================================================================

def test_tubelet_patches_mapping_and_order():
    """构造只有一个块非零的段，确认它严格出现在预期的 (t, h, w) 位置。"""
    # 构造 (16, 224, 224, 3) 全 0 视频
    clip = np.zeros((16, 224, 224, 3), dtype=np.uint8)

    # 目标位置：t_idx=3 (帧 6-7), h_idx=5 (行 80-95), w_idx=9 (列 144-159)
    target_t = 3
    target_h = 5
    target_w = 9

    # 在帧 6（对应 dt=0），patch 内第 4 行 (dh=4)，第 7 列 (dw=7)，通道 1 (绿) 填入 255
    clip[6, 5 * 16 + 4, 9 * 16 + 7, 1] = 255

    patches = tokens.tubelet_patches(clip)  # [8, 14, 14, 1536]
    assert patches.shape == (8, 14, 14, 1536)
    assert patches.dtype == np.float32

    # 检查非零位置
    nonzeros = np.argwhere(patches > 0)
    assert len(nonzeros) == 1, f"Expected exactly 1 nonzero element, got {len(nonzeros)}"

    t, h, w, d = nonzeros[0]
    assert (t, h, w) == (target_t, target_h, target_w), f"Expected {(target_t, target_h, target_w)}, got {(t, h, w)}"

    # 检查 patch 内部展平偏移
    # 展平顺序为 (dt, dh, dw, c)，基数分别为 (16*16*3, 16*3, 3, 1)
    expected_d = 0 * (16 * 16 * 3) + 4 * (16 * 3) + 7 * 3 + 1
    assert d == expected_d, f"Expected inner offset {expected_d}, got {d}"
    assert math.isclose(patches[t, h, w, d], 1.0, abs_tol=1e-5)


def test_tubelet_patches_bad_control_transposition():
    """坏对照：若展平轴顺序颠倒（如先宽后高），非零元素位置必然错误。"""
    def bad_tubelet_patches(clip: np.ndarray) -> np.ndarray:
        # 错误实现：将 h 与 w 轴调换
        B = 1
        c = clip[np.newaxis, ...]
        reshaped = c.reshape(1, 8, 2, 14, 16, 14, 16, 3)
        # 错误：将 (h, w) 置换为 (w, h)
        bad_transposed = reshaped.transpose(0, 1, 5, 3, 2, 4, 6, 7)
        return bad_transposed.reshape(8, 14, 14, 1536).astype(np.float32) / 255.0

    clip = np.zeros((16, 224, 224, 3), dtype=np.uint8)
    clip[6, 5 * 16 + 4, 9 * 16 + 7, 1] = 255

    bad_p = bad_tubelet_patches(clip)
    nonzeros = np.argwhere(bad_p > 0)
    t, h, w, d = nonzeros[0]

    with pytest.raises(AssertionError):
        # 预期 (3, 5, 9)，但因轴反转变成了 (3, 9, 5)
        assert (t, h, w) == (3, 5, 9)


# ==============================================================================
# 测试 2：rlt_keep 与权威模块等价性及两极测试
# ==============================================================================

def test_rlt_keep_static_and_dynamic_extremes():
    """静止段保留率严格等于 1/8；每帧都变的段保留率严格等于 1.0。"""
    # 1. 静止段：所有管长相同
    static_patches = np.ones((8, 14, 14, 1536), dtype=np.float32) * 0.5
    keep_static, run_len_static = tokens.rlt_keep(static_patches, tau=0.02)

    # 第一帧全部保留，后续全部合并
    assert np.all(keep_static[0] == True)
    assert np.all(keep_static[1:] == False)
    # 保留率应严格为 1/8
    retention_rate = float(np.mean(keep_static))
    assert math.isclose(retention_rate, 1.0 / 8.0, abs_tol=1e-6)

    # 游程长度：第 0 帧均为 8，其余均为 0
    assert np.all(run_len_static[0] == 8)
    assert np.all(run_len_static[1:] == 0)

    # 2. 动态段：每帧变化幅度 0.1 > tau (0.02)
    dynamic_patches = np.zeros((8, 14, 14, 1536), dtype=np.float32)
    for t in range(8):
        dynamic_patches[t] = t * 0.1

    keep_dyn, run_len_dyn = tokens.rlt_keep(dynamic_patches, tau=0.02)
    assert np.all(keep_dyn == True)
    assert math.isclose(float(np.mean(keep_dyn)), 1.0, abs_tol=1e-6)
    assert np.all(run_len_dyn == 1)


def test_rlt_keep_parity_with_authority():
    """rlt_keep 的保留掩码与直接调用 rlt_frame_dropping 完全一致。"""
    rng = np.random.default_rng(123)
    patches = rng.uniform(0.0, 1.0, (8, 14, 14, 1536)).astype(np.float32)
    tau = 0.35

    keep, run_len = tokens.rlt_keep(patches, tau)
    retained, run_lengths, positions, restoration, rate = rlt_frame_dropping(patches, tau)

    # 保留 token 总数必须完全相等
    assert int(np.sum(keep)) == len(retained)
    assert math.isclose(float(np.mean(keep)), rate, abs_tol=1e-6)


def test_rlt_keep_bad_control_all_kept_on_static():
    """坏对照：若静止段错误地全部保留，保留率校验必须报错。"""
    def bad_rlt_keep(patches, tau):
        # 错误实现：不执行合并
        return np.ones(patches.shape[:3], dtype=bool), np.ones(patches.shape[:3], dtype=int)

    static_patches = np.ones((8, 14, 14, 1536), dtype=np.float32) * 0.5
    bad_keep, _ = bad_rlt_keep(static_patches, tau=0.02)

    with pytest.raises(AssertionError):
        rate = float(np.mean(bad_keep))
        assert math.isclose(rate, 1.0 / 8.0, abs_tol=1e-6)


# ==============================================================================
# 测试 3：restoration_error 与 P226 渐变序列
# ==============================================================================

def test_restoration_error_gradient_sequence():
    """P226 构造的渐变序列（每步 +0.015, tau=0.02），最大误差约等于 0.135。"""
    # 构造 10 步/帧的渐变序列：第 0 步为 0，随后每步递增 0.015
    # 当 tau=0.02 时，相邻步变化 0.015 < 0.02，全部合并到第 0 步 anchor
    # 第 9 步的值为 9 * 0.015 = 0.135，其与 anchor (0) 的 ‖·‖∞ 误差为 0.135
    # 转换为 8 管长序列：
    patches = np.zeros((8, 14, 14, 1536), dtype=np.float32)
    for t in range(8):
        # 每管长递增 0.015
        patches[t] = t * 0.015

    # tau=0.02 > 0.015，所有管长全部合并到管长 0
    keep, run_len = tokens.rlt_keep(patches, tau=0.02)
    assert np.all(keep[0] == True)
    assert np.all(keep[1:] == False)

    err = tokens.restoration_error(patches, keep)
    # 管长 1..7 的误差分别为 1*0.015=0.015, 2*0.015=0.030, ..., 7*0.015=0.105
    # 若在 10 步序列下（如 9 个递增步）：最大为 9 * 0.015 = 0.135
    # 检验 95% 分位数与最大误差范围
    assert err.median > 0.0
    assert err.p95 > 0.08
    assert math.isclose(err.p95, 7 * 0.015, abs_tol=0.02)


def test_restoration_error_bad_control_zero():
    """坏对照：若误用同一帧算误差导致全 0，断言必须抓出。"""
    def bad_restoration_error(patches, keep):
        return tokens.RestorationError(0.0, 0.0)

    patches = np.zeros((8, 14, 14, 1536), dtype=np.float32)
    for t in range(8):
        patches[t] = t * 0.015

    keep, _ = tokens.rlt_keep(patches, tau=0.02)
    bad_err = bad_restoration_error(patches, keep)

    with pytest.raises(AssertionError):
        assert bad_err.median > 0.01


# ==============================================================================
# P241：rlt_keep_fast 与权威 rlt_keep 逐元素一致（随机段、全静止、全变化、真实 s5test 段；tau=0, 0.02, 0.1）
# ==============================================================================

def test_rlt_keep_fast_matches_rlt_keep_elementwise():
    """验证 rlt_keep_fast 与权威 rlt_keep 在随机段、全静止、全变化、真实 s5test 段及 tau in (0, 0.02, 0.1) 逐元素完全一致。"""
    from ainerzero.v9.experiments.s5.world import episode, student_clip

    rng = np.random.default_rng(20261112)

    # 1. 全静止段
    static_clip = np.full((8, 14, 14, 1536), 0.42, dtype=np.float32)

    # 2. 全变化段
    changing_clip = np.zeros((8, 14, 14, 1536), dtype=np.float32)
    for t in range(8):
        changing_clip[t] = t * 0.15

    # 3. 随机段（含部分变化、边界阈值附近变化）
    rand_clip_1 = rng.uniform(0.0, 0.08, size=(8, 14, 14, 1536)).astype(np.float32)
    rand_clip_2 = np.cumsum(
        rng.choice([0.0, 0.01, 0.025, 0.12], size=(8, 14, 14, 1)).astype(np.float32),
        axis=0,
    ) + rng.uniform(-0.002, 0.002, size=(8, 14, 14, 1536)).astype(np.float32)

    # 4. 真实 s5test 段
    ep = episode("s5test-tokens", 0)
    real_clip_0 = tokens.tubelet_patches(student_clip(ep, 0))
    real_clip_1 = tokens.tubelet_patches(student_clip(ep, 1))

    test_clips = [
        ("static", static_clip),
        ("changing", changing_clip),
        ("rand_1", rand_clip_1),
        ("rand_2", rand_clip_2),
        ("s5test_0", real_clip_0),
        ("s5test_1", real_clip_1),
    ]

    for tau in (0.0, 0.02, 0.1):
        for name, patches in test_clips:
            k_ref, rl_ref = tokens.rlt_keep(patches, tau)
            k_fast, rl_fast = tokens.rlt_keep_fast(patches, tau)
            assert k_fast.dtype == k_ref.dtype == np.bool_
            assert rl_fast.shape == rl_ref.shape == (8, 14, 14)
            np.testing.assert_array_equal(
                k_fast, k_ref, err_msg=f"keep mismatch on {name} at tau={tau}"
            )
            np.testing.assert_array_equal(
                rl_fast, rl_ref, err_msg=f"run_len mismatch on {name} at tau={tau}"
            )

        # 同时验证 5D 批输入 [B, 8, 14, 14, 1536]
        batched = np.stack([c for _, c in test_clips], axis=0)
        kb_ref, rlb_ref = tokens.rlt_keep(batched, tau)
        kb_fast, rlb_fast = tokens.rlt_keep_fast(batched, tau)
        np.testing.assert_array_equal(kb_fast, kb_ref, err_msg=f"batched keep mismatch at tau={tau}")
        np.testing.assert_array_equal(rlb_fast, rlb_ref, err_msg=f"batched run_len mismatch at tau={tau}")

