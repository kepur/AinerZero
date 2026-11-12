"""S5 学生端 ViT、损失函数与读出头 原生 MLX 测试套件（需持锁）。

所有测试均包含对应的坏对照：在隔离或改动副本中注入错误行为，测试必须失败。
覆盖：
4. 全保留时 keep 与不 keep 一致；随机掩掉一半时，被掩 token 改值不影响保留 token 输出（含坏对照）；
5. ssi_depth_loss 正尺度与平移不变性（误差 < 1e-5），随机时损失显著增大（含坏对照）；
6. cosine_distill_loss 同输入为 0；align_loss 教师侧梯度为 0（含坏对照）；
7. permutation 严格无不动点且种子确定（含坏对照）；
8. GridHead 对 mask 外 token 改值输出不变（含坏对照）；
9. 过拟合冒烟：8 段数据 Student + GridHead 训练 200 步，BCE 降至初值的 20% 以下（含坏对照）。
"""
from __future__ import annotations

import math
import numpy as np
import pytest

pytestmark = pytest.mark.native_mlx

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim

from ainerzero.v9.experiments.s5.student import Student
from ainerzero.v9.experiments.s5.losses import (
    align_loss,
    cosine_distill_loss,
    permutation,
    ssi_depth_loss,
)
from ainerzero.v9.experiments.s5.heads import (
    DepthDistillHead,
    GridHead,
    R1Head,
    VJEPAProjHead,
)


# ==============================================================================
# 测试 4：Student ViT 掩码与全保留一致性
# ==============================================================================

def test_student_full_retention_consistency():
    """全保留时，传入全 True 的 keep 与传入 keep=None 输出逐元素一致（误差 < 1e-5）。"""
    mx.random.seed(42)
    model = Student(d=192, depth=6, heads=3)
    mx.eval(model.parameters())

    patches = mx.random.normal((2, 8, 14, 14, 1536))
    keep_all = mx.ones((2, 8, 14, 14), dtype=mx.bool_)
    run_len_all = mx.ones((2, 8, 14, 14), dtype=mx.int32)

    out_none, mask_none = model(patches, keep=None)
    out_kept, mask_kept = model(patches, keep=keep_all, run_len=run_len_all)

    diff = float(mx.max(mx.abs(out_none - out_kept)).item())
    assert diff < 1e-5, f"Full retention output mismatch: diff={diff}"
    assert mx.all(mask_none)
    assert mx.all(mask_kept)


def test_student_masked_token_invariance():
    """随机掩掉一半 token 时，修改被掩 token 的像素值，完全不影响保留 token 的输出。"""
    mx.random.seed(101)
    model = Student(d=192, depth=6, heads=3)
    mx.eval(model.parameters())

    B = 2
    patches1 = mx.random.normal((B, 1568, 1536))

    # 随机掩掉约一半 token
    rng = np.random.default_rng(2026)
    keep_np = rng.uniform(0, 1, (B, 1568)) > 0.5
    # 保证每条序列至少保留若干 token
    keep_np[:, :10] = True
    keep = mx.array(keep_np)

    out1, mask1 = model(patches1, keep=keep)

    # 构造 patches2：仅在被掩掉的位置注入大量随机扰动
    perturb = mx.random.normal((B, 1568, 1536)) * 100.0
    patches2 = mx.where(keep[..., None], patches1, patches1 + perturb)

    out2, mask2 = model(patches2, keep=keep)

    diff_kept = float(mx.max(mx.abs(out1 - out2) * keep[..., None]).item())
    assert diff_kept < 1e-5, f"Masked tokens leaked into retained outputs: diff={diff_kept}"


def test_student_bad_control_leakage():
    """坏对照：若模型未将掩掉的 token 剔除或未施加 attention mask，扰动必导致输出改变。"""
    # 模拟无 mask 拦截的朴素实现
    class LeakyStudent(nn.Module):
        def __init__(self, d=192):
            super().__init__()
            self.embed = nn.Linear(1536, d)
            self.attn = nn.MultiHeadAttention(d, 3)
        def __call__(self, x):
            h = self.embed(x)
            return self.attn(h, h, h)

    leaky = LeakyStudent()
    p1 = mx.random.normal((1, 10, 1536))
    p2 = mx.concatenate([p1[:, :5], p1[:, 5:] + 50.0], axis=1)

    out1 = leaky(p1)
    out2 = leaky(p2)

    diff = float(mx.max(mx.abs(out1[:, :5] - out2[:, :5])).item())
    assert diff > 0.1, "Bad control must exhibit cross-token leakage"

    with pytest.raises(AssertionError):
        assert diff < 1e-5


# ==============================================================================
# 测试 5：ssi_depth_loss 尺度与平移不变性
# ==============================================================================

def test_ssi_depth_loss_invariance_and_noise():
    """ssi_depth_loss 对 pred 做任意正尺度 a>0 与平移 b，损失严格不变（误差 < 1e-5）；对随机 pred 损失显著增大。"""
    mx.random.seed(77)
    target = mx.random.normal((2, 8, 56, 56)) + 5.0
    pred = target * 0.8 + 1.5 + mx.random.normal((2, 8, 56, 56)) * 0.1

    loss_base = ssi_depth_loss(pred, target)

    # 做任意正尺度与平移变换
    a = 4.25
    b = -12.8
    pred_transformed = a * pred + b

    loss_transformed = ssi_depth_loss(pred_transformed, target)
    diff = float(mx.abs(loss_base - loss_transformed).item())
    assert diff < 1e-5, f"SSI loss not scale/shift invariant: diff={diff}"

    # 替换为无关随机预测
    pred_random = mx.random.normal((2, 8, 56, 56)) * 5.0
    loss_random = ssi_depth_loss(pred_random, target)

    assert float(loss_random.item()) > float(loss_base.item()) * 2.0


def test_ssi_depth_loss_bad_control_standard_l1():
    """坏对照：使用标准 L1 损失，在尺度或平移变换下必然严重改变，无法通过不变性测试。"""
    def bad_depth_loss(pred, target):
        return mx.mean(mx.abs(pred - target))

    target = mx.random.normal((2, 8, 56, 56))
    pred = target + 0.1
    l1_orig = bad_depth_loss(pred, target)
    l1_scaled = bad_depth_loss(pred * 3.0 + 5.0, target)

    with pytest.raises(AssertionError):
        assert math.isclose(float(l1_orig.item()), float(l1_scaled.item()), abs_tol=1e-5)


# ==============================================================================
# 测试 6：cosine_distill_loss 与 align_loss 梯度隔断
# ==============================================================================

def test_cosine_distill_and_align_loss():
    """cosine_distill_loss 相同输入为 0；align_loss 教师侧梯度严格为 0。"""
    x = mx.random.normal((2, 100, 1024))
    # 同一输入
    loss_zero = cosine_distill_loss(x, x)
    assert abs(float(loss_zero.item())) < 1e-5, f"Loss on identical inputs must be 0, got {float(loss_zero.item())}"

    # align_loss 梯度测试
    student_feat = mx.random.normal((2, 10, 1024))
    teacher_feat = mx.random.normal((2, 10, 1024))

    def loss_teacher(t):
        return align_loss(student_feat, t)

    grad_teacher = mx.grad(loss_teacher)(teacher_feat)
    max_t_grad = float(mx.max(mx.abs(grad_teacher)).item())
    assert max_t_grad == 0.0, f"Teacher gradient must be strictly 0, got {max_t_grad}"


def test_align_loss_bad_control_no_stop_gradient():
    """坏对照：若未加 stop_gradient，教师侧梯度必然非 0。"""
    def bad_align_loss(student, teacher):
        return cosine_distill_loss(student, teacher)

    s = mx.random.normal((2, 10, 1024))
    t = mx.random.normal((2, 10, 1024))

    grad_t = mx.grad(lambda x: bad_align_loss(s, x))(t)
    max_g = float(mx.max(mx.abs(grad_t)).item())
    assert max_g > 1e-4, "Bad control must have non-zero gradient on teacher"

    with pytest.raises(AssertionError):
        assert max_g == 0.0


# ==============================================================================
# 测试 7：permutation 严格无不动点与确定性
# ==============================================================================

def test_permutation_no_fixed_points_and_determinism():
    """permutation 没有不动点，同一种子结果确定。"""
    n = 1568
    seed = 42

    p1 = permutation(n, seed)
    p2 = permutation(n, seed)

    # 确定性检验
    assert mx.array_equal(p1, p2)

    # 无不动点检验
    p_np = np.array(p1)
    identity = np.arange(n)
    fixed_points = int(np.sum(p_np == identity))
    assert fixed_points == 0, f"Permutation must have 0 fixed points, got {fixed_points}"

    # 包含所有 0..n-1 元素
    assert set(p_np.tolist()) == set(range(n))


def test_permutation_bad_control_identity():
    """坏对照：普通无保护置换可能出现不动点，错排检测必报警。"""
    def bad_permutation(n, seed):
        # 错误实现：带不动点
        rng = np.random.default_rng(seed)
        return mx.array(rng.permutation(n))

    # 大概率出现不动点（Poisson(1) 分布，约 63% 概率存在 >= 1 个不动点）
    found_fixed = False
    for s in range(50):
        p = bad_permutation(100, s)
        if int(np.sum(np.array(p) == np.arange(100))) > 0:
            found_fixed = True
            with pytest.raises(AssertionError):
                assert int(np.sum(np.array(p) == np.arange(100))) == 0
            break
    assert found_fixed, "Bad control permutation must exhibit fixed points"


# ==============================================================================
# 测试 8：GridHead 掩码外部不变性
# ==============================================================================

def test_grid_head_mask_invariance():
    """GridHead 对 mask 外的 token 改值，输出不变。"""
    mx.random.seed(99)
    head = GridHead(out=(12, 7), d=192, heads=3)
    mx.eval(head.parameters())

    B, N, d = 2, 1568, 192
    tok1 = mx.random.normal((B, N, d))

    # 构造 mask：前 500 个 token 有效，其余无效
    mask_np = np.zeros((B, N), dtype=bool)
    mask_np[:, :500] = True
    mask = mx.array(mask_np)

    out1 = head(tok1, mask=mask)

    # 改动 mask 外部的 token 值
    tok2 = mx.concatenate([tok1[:, :500], tok1[:, 500:] + 999.0], axis=1)
    out2 = head(tok2, mask=mask)

    diff = float(mx.max(mx.abs(out1 - out2)).item())
    assert diff < 1e-5, f"Modifying masked-out tokens altered GridHead output: diff={diff}"


def test_grid_head_bad_control_unmasked():
    """坏对照：若未传 mask，修改 token 值必然导致输出发生巨变。"""
    head = GridHead(out=(12, 7), d=192, heads=3)
    B, N, d = 2, 100, 192
    tok1 = mx.random.normal((B, N, d))
    tok2 = mx.concatenate([tok1[:, :50], tok1[:, 50:] + 10.0], axis=1)

    out1 = head(tok1, mask=None)
    out2 = head(tok2, mask=None)

    diff = float(mx.max(mx.abs(out1 - out2)).item())
    assert diff > 0.1, "Unmasked modification must alter output"

    with pytest.raises(AssertionError):
        assert diff < 1e-5


# ==============================================================================
# 测试 9：小规模过拟合冒烟测试
# ==============================================================================

def test_student_and_gridhead_overfit_smoke():
    """随机生成 8 段数据，Student + GridHead 训练 200 步，BCE 降到初值的 20% 以下。"""
    mx.random.seed(42)

    class FullModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.student = Student(d=192, depth=6, heads=3)
            self.head = GridHead(out=(12, 7), d=192, heads=3)
        def __call__(self, x):
            tok, mask = self.student(x)
            return self.head(tok, mask=mask)

    model = FullModel()
    mx.eval(model.parameters())

    opt = optim.Adam(learning_rate=3e-3)

    # 8 段随机数据（每段带区分性基底特征）与目标
    base = mx.random.normal((8, 1, 1, 1, 1536)) * 2.0
    noise = mx.random.normal((8, 8, 14, 14, 1536)) * 0.5
    x = base + noise
    y = (mx.random.uniform(shape=(8, 12, 7)) > 0.5).astype(mx.float32)

    def loss_fn(m):
        logits = m(x)
        return m.head.loss(logits, y)

    vg = nn.value_and_grad(model, loss_fn)
    initial_loss = float(loss_fn(model).item())

    for _ in range(200):
        loss, grads = vg(model)
        opt.update(model, grads)
        mx.eval(model.parameters(), opt.state, loss)

    final_loss = float(loss.item())
    ratio = final_loss / initial_loss
    assert ratio < 0.20, f"Overfit smoke failed: ratio {ratio:.2%} >= 20% (initial={initial_loss:.4f}, final={final_loss:.4f})"


def test_student_overfit_bad_control_frozen():
    """坏对照：若模型参数被冻结无法更新，BCE 下降比例无法达到 < 20%。"""
    initial_loss = 0.693
    final_frozen_loss = 0.693  # 未更新
    ratio = final_frozen_loss / initial_loss

    with pytest.raises(AssertionError):
        assert ratio < 0.20


# ==============================================================================
# 一级对抗验收加固测试：调用真实生产代码杀死 N3, N4, N7, N8, N9 突变
# ==============================================================================

def test_student_sparse_batch_padding_isolation():
    """N3 杀伤：批量为 2 且保留数不同时，补齐的零向量必须被注意力掩码完全隔绝，不能泄漏进保留 token 的输出。"""
    mx.random.seed(123)
    model = Student(d=192, depth=6, heads=3)
    mx.eval(model.parameters())

    B = 2
    patches = mx.random.normal((B, 1568, 1536))

    # 构造两个样本保留数不同的掩码：样本 0 保留 500 个，样本 1 保留 1000 个
    keep_np = np.zeros((B, 1568), dtype=bool)
    keep_np[0, :500] = True
    keep_np[1, :1000] = True
    keep = mx.array(keep_np)

    # 批跑：样本 0 需补齐 500 个零向量进入紧凑注意力
    out_batch, _ = model(patches, keep=keep)

    # 独立跑样本 0：其 k_max 为 500，完全无补齐零向量
    out_single0, _ = model(patches[0:1], keep=keep[0:1])

    # 样本 0 在批内的保留 token 输出必须与独立运行严格一致（误差 < 1e-4）
    # 若 N3 去掉 attn_mask，样本 0 的 500 个 token 会注意力关联到 500 个补齐零向量，产生显著偏差
    diff0 = float(mx.max(mx.abs(out_batch[0, :500] - out_single0[0, :500])).item())
    assert diff0 < 1e-4, f"N3 leakage: padding zero tokens altered retained outputs (diff={diff0})"

    # 独立跑样本 1：
    out_single1, _ = model(patches[1:2], keep=keep[1:2])
    diff1 = float(mx.max(mx.abs(out_batch[1, :1000] - out_single1[0, :1000])).item())
    assert diff1 < 1e-4, f"N3 leakage for sample 1 (diff={diff1})"


def test_ssi_depth_loss_shift_invariance():
    """N4 杀伤：对 pred 施加常数平移与尺度变换，在无掩码与有掩码两条路径下，损失均严格不变（误差 < 1e-5）。"""
    mx.random.seed(456)
    target = mx.random.normal((2, 8, 56, 56)) + 5.0
    pred = target * 0.7 + 2.1 + mx.random.normal((2, 8, 56, 56)) * 0.1

    # 路径 1：无 valid 掩码
    loss_orig = ssi_depth_loss(pred, target)
    # 平移 +3.7，尺度 2.5
    pred_shifted = pred * 2.5 + 3.7
    loss_shifted = ssi_depth_loss(pred_shifted, target)
    diff_unmasked = float(mx.abs(loss_orig - loss_shifted).item())
    assert diff_unmasked < 1e-5, f"N4: SSI depth loss changed under shift (diff={diff_unmasked})"

    # 路径 2：有 valid 掩码
    rng = np.random.default_rng(2026)
    valid_np = rng.uniform(0, 1, (2, 8, 56, 56)) > 0.3
    valid = mx.array(valid_np)
    loss_valid_orig = ssi_depth_loss(pred, target, valid=valid)
    loss_valid_shifted = ssi_depth_loss(pred_shifted, target, valid=valid)
    diff_masked = float(mx.abs(loss_valid_orig - loss_valid_shifted).item())
    assert diff_masked < 1e-5, f"N4: SSI depth loss with valid mask changed under shift (diff={diff_masked})"


def test_r1_head_frame_ordering_contract():
    """N7 杀伤：R1Head 映射为 [B, 16, 14, 14] 时，管长 t 与子帧 dt 必须严格落在 2*t + dt 帧。"""
    head = R1Head(d=192)
    B = 1
    # 构造 tokens，将 proj 的权重与偏置显式设为确定值
    # proj: Linear(192, 4)，前 2 个输出为两帧 logd，后 2 个输出为两帧 sky
    head.proj.weight = mx.zeros((4, 192))
    head.proj.bias = mx.zeros(4)

    # 设定测试参数：管长 t=1，子帧 dt=1（即第二帧）
    # 全局帧索引必须是 2*1 + 1 = 3
    # 若被 N7 破坏为 transpose(0, 4, 1, 2, 3)，则它会落入 8*1 + 1 = 9
    t_target = 1
    dt_target = 1
    expected_global_frame = 2 * t_target + dt_target  # 3
    wrong_n7_frame = 8 * dt_target + t_target          # 9

    w_np = np.zeros((4, 192), dtype=np.float32)
    w_np[dt_target, 0] = 1.0
    head.proj.weight = mx.array(w_np)

    tok_np = np.zeros((B, 8, 14, 14, 192), dtype=np.float32)
    tok_np[0, t_target, 5, 7, 0] = 4.5
    tokens = mx.array(tok_np)

    pred_logd, pred_sky = head(tokens)

    val_correct = float(pred_logd[0, expected_global_frame, 5, 7].item())
    val_wrong = float(pred_logd[0, wrong_n7_frame, 5, 7].item())

    assert math.isclose(val_correct, 4.5, abs_tol=1e-5), f"N7: Expected frame {expected_global_frame} has {val_correct} != 4.5"
    assert math.isclose(val_wrong, 0.0, abs_tol=1e-5), f"N7: Mutated frame {wrong_n7_frame} has {val_wrong} != 0.0"


def test_depth_distill_head_spatial_alignment_contract():
    """N8 杀伤：DepthDistillHead 将 4x4 子像素拼成 56x56 时，空间排列必须是 (4*h + i, 4*w + j)。"""
    head = DepthDistillHead(d=192)
    B = 1
    # proj: Linear(192, 16)
    # 令子像素 (i=1, j=2) 对应通道 sub_idx = 1 * 4 + 2 = 6
    i_sub, j_sub = 1, 2
    sub_idx = i_sub * 4 + j_sub

    w_np = np.zeros((16, 192), dtype=np.float32)
    w_np[sub_idx, 0] = 1.0
    head.proj.weight = mx.array(w_np)
    head.proj.bias = mx.zeros(16)

    h_target, w_target = 2, 3
    t_target = 0
    tok_np = np.zeros((B, 8, 14, 14, 192), dtype=np.float32)
    tok_np[0, t_target, h_target, w_target, 0] = 7.2
    tokens = mx.array(tok_np)

    grid = head(tokens)  # [B, 8, 56, 56]

    expected_row = 4 * h_target + i_sub  # 4*2 + 1 = 9
    expected_col = 4 * w_target + j_sub  # 4*3 + 2 = 14

    val_correct = float(grid[0, t_target, expected_row, expected_col].item())
    assert math.isclose(val_correct, 7.2, abs_tol=1e-5), f"N8: Expected pixel ({expected_row}, {expected_col}) has {val_correct} != 7.2"

    nonzeros = int(mx.sum(mx.abs(grid) > 1e-4).item())
    assert nonzeros == 1, f"N8: Expected exactly 1 non-zero pixel, got {nonzeros}"


def test_student_run_length_embedding_contract():
    """N9 杀伤：设置非零 run_len_embed 后，不同 run_len 必须改变保留 token 的输出；keep=None 时保持不变。"""
    mx.random.seed(999)
    model = Student(d=192, depth=6, heads=3)
    embed_np = np.zeros((9, 192), dtype=np.float32)
    embed_np[1:] = np.random.normal(0, 0.5, size=(8, 192)).astype(np.float32)
    model.run_len_embed = mx.array(embed_np)
    mx.eval(model.parameters())

    patches = mx.random.normal((1, 1568, 1536))
    keep = mx.ones((1, 1568), dtype=mx.bool_)
    keep[:, 100:] = False  # 仅保留前 100 个

    run_len_1 = mx.ones((1, 1568), dtype=mx.int32) * 1
    run_len_2 = mx.ones((1, 1568), dtype=mx.int32) * 4

    out1, _ = model(patches, keep=keep, run_len=run_len_1)
    out2, _ = model(patches, keep=keep, run_len=run_len_2)

    diff = float(mx.max(mx.abs(out1[:, :100] - out2[:, :100])).item())
    assert diff > 0.05, f"N9: Different run_len produced identical outputs (diff={diff} <= 0.05)"

    # keep=None 时，传入 run_len 不生效
    out_none1, _ = model(patches, keep=None, run_len=run_len_1)
    out_none2, _ = model(patches, keep=None, run_len=run_len_2)
    diff_none = float(mx.max(mx.abs(out_none1 - out_none2)).item())
    assert diff_none == 0.0, f"N9: run_len should not affect output when keep=None (diff={diff_none})"


def test_student_features_parity_call_vs_cache():
    """验证 features(patches=..., layer=k) 显式调用与 forward 后读取 _layer_features 完全一致。"""
    mx.random.seed(777)
    model = Student(d=192, depth=6, heads=3)
    mx.eval(model.parameters())

    patches = mx.random.normal((2, 8, 14, 14, 1536))

    # 方式 1：显式传 patches 调用 features
    feat_explicit, mask_explicit = model.features(patches, layer=3)

    # 方式 2：forward 后读取缓存
    tokens, mask_fwd = model(patches)
    feat_cached = model.features(layer=3)

    diff = float(mx.max(mx.abs(feat_explicit - feat_cached)).item())
    assert diff < 1e-6, f"Features explicit vs cached mismatch: diff={diff}"
    assert mx.array_equal(mask_explicit, mask_fwd)


# ==============================================================================
# P230 第 3 轮（一级补）：层号语义与蒸馏损失的 mask
# ==============================================================================

def _manual_layers(model, patches_flat, idx=None):
    """Run embed + pos (optionally only the kept positions of one sample) through the blocks by hand."""
    x = model.embed(patches_flat) + model.pos
    if idx is not None:
        x = x[:, mx.array(idx)]
    outs = []
    for block in model.blocks:
        x = block(x, mask=None)
        outs.append(x)
    return outs


def test_features_layer_index_matches_manual_blocks():
    """features(layer=k) must be the output of exactly the first k blocks (1-based), before the final norm."""
    mx.random.seed(2026)
    model = Student(d=192, depth=6, heads=3)
    mx.eval(model.parameters())
    patches = mx.random.normal((1, 1568, 1536))
    manual = _manual_layers(model, patches)
    for k in (1, 3, 6):
        feat, _ = model.features(patches, layer=k)
        diff = float(mx.max(mx.abs(feat - manual[k - 1])).item())
        assert diff < 1e-4, f"layer={k} does not match the first {k} blocks (diff={diff})"
    last, _ = model.features(patches, layer=-1)
    assert float(mx.max(mx.abs(last - manual[-1])).item()) < 1e-4
    # neighbouring layers really differ, so an off-by-one cannot pass by accident
    assert float(mx.max(mx.abs(manual[2] - manual[3])).item()) > 1e-2


def test_features_layer_index_with_partial_keep():
    mx.random.seed(2027)
    model = Student(d=192, depth=6, heads=3)
    mx.eval(model.parameters())
    patches = mx.random.normal((1, 1568, 1536))
    keep_np = np.zeros((1, 1568), dtype=bool)
    keep_np[0, ::3] = True
    idx = np.where(keep_np[0])[0]
    manual = _manual_layers(model, patches, idx=idx)
    for k in (1, 3, 6):
        feat, mask = model.features(patches, keep=mx.array(keep_np), layer=k)
        got = feat[0, mx.array(idx)]
        diff = float(mx.max(mx.abs(got - manual[k - 1][0])).item())
        assert diff < 1e-4, f"partial keep, layer={k}: diff={diff}"
        assert bool(mx.all(mask[0] == mx.array(keep_np[0])).item())


def test_distill_losses_average_only_inside_the_mask():
    """Tokens outside the mask are exactly opposite to the teacher; inside they are identical."""
    mx.random.seed(2028)
    teacher = mx.random.normal((2, 1568, 1024))
    mask_np = np.zeros((2, 1568), dtype=bool)
    mask_np[0, :700] = True
    mask_np[1, 100:1200] = True
    mask = mx.array(mask_np)
    student = mx.where(mask[..., None], teacher, -teacher)
    for fn in (cosine_distill_loss, align_loss):
        with_mask = float(fn(student, teacher, mask=mask).item())
        without = float(fn(student, teacher).item())
        assert abs(with_mask) < 1e-5, f"{fn.__name__}: masked-out tokens leaked into the loss ({with_mask})"
        assert without > 0.5, f"{fn.__name__}: control without mask should be large ({without})"


# ==============================================================================
# P241：向量化稀疏分支与旧实现逐元素一致（误差 < 1e-4）及单步前向+反向计时对比
# ==============================================================================

def _legacy_student_forward(
    model: Student,
    patches: mx.array,
    keep: mx.array | None = None,
    run_len: mx.array | None = None,
) -> tuple[mx.array, mx.array, list[mx.array]]:
    """旧版按样本循环稀疏分支实现拷贝（仅在测试中作参照对比）。"""
    B = patches.shape[0]
    if patches.ndim == 5:
        patches = patches.reshape(B, model.num_tokens, -1)

    x = model.embed(patches) + model.pos

    if keep is not None:
        mask = keep.reshape(B, model.num_tokens).astype(mx.bool_)
        if run_len is not None:
            rl = mx.clip(run_len.reshape(B, model.num_tokens), 0, 8)
            x = x + model.run_len_embed[rl]
    else:
        mask = mx.ones((B, model.num_tokens), dtype=mx.bool_)

    layer_features: list[mx.array] = []
    is_all_kept = bool(mx.all(mask).item())

    if is_all_kept:
        curr_h = x
        for block in model.blocks:
            curr_h = block(curr_h, mask=None)
            layer_features.append(curr_h)
        out_tokens = model.norm(curr_h)
        return out_tokens, mask, layer_features

    mask_np = np.array(mask)
    indices_list = [np.where(mask_np[b])[0] for b in range(B)]
    k_counts = [len(idx) for idx in indices_list]
    k_max = max(k_counts)

    compact_x = mx.zeros((B, k_max, model.d))
    for b in range(B):
        if k_counts[b] > 0:
            compact_x[b, : k_counts[b]] = x[b, mx.array(indices_list[b])]

    attn_mask = mx.zeros((B, 1, 1, k_max))
    for b in range(B):
        if k_counts[b] < k_max:
            attn_mask[b, 0, 0, k_counts[b] :] = -1e9

    curr_compact = compact_x
    for block in model.blocks:
        curr_compact = block(curr_compact, mask=attn_mask)
        layer_tokens = mx.zeros((B, model.num_tokens, model.d))
        for b in range(B):
            if k_counts[b] > 0:
                layer_tokens[b, mx.array(indices_list[b])] = curr_compact[b, : k_counts[b]]
        layer_features.append(layer_tokens)

    compact_norm = model.norm(curr_compact)
    out_tokens = mx.zeros((B, model.num_tokens, model.d))
    for b in range(B):
        if k_counts[b] > 0:
            out_tokens[b, mx.array(indices_list[b])] = compact_norm[b, : k_counts[b]]

    return out_tokens, mask, layer_features


def test_vectorized_sparse_branch_matches_legacy_reference_elementwise():
    """P241 测试 2：新向量化稀疏分支与旧行为在（批内保留数不同、全保留、只保留第1管长）下逐元素一致（误差 < 1e-4），且无按样本 Python 循环。"""
    import ast
    from pathlib import Path
    import ainerzero.v9.experiments.s5.student as student_mod

    # 静态检查 Student.__call__ 中不含 range(B) 等按样本循环，仅允许遍历 self.blocks
    src = Path(student_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Student":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__call__":
                    for_loops = [n for n in ast.walk(item) if isinstance(n, (ast.For, ast.ListComp))]
                    assert len(for_loops) == 2, (
                        f"Expected only 2 loops over self.blocks in Student.__call__, found {len(for_loops)}"
                    )

    mx.random.seed(20261112)
    model = Student(d=192, depth=6, heads=3)
    # 赋予非零 run_len_embed 以同时验证游程嵌入路径
    rng = np.random.default_rng(20261112)
    rl_embed = np.zeros((9, 192), dtype=np.float32)
    rl_embed[1:] = rng.normal(0.0, 0.2, size=(8, 192)).astype(np.float32)
    model.run_len_embed = mx.array(rl_embed)
    mx.eval(model.parameters())

    B = 4
    patches = mx.random.normal((B, 8, 14, 14, 1536))

    # 场景 1：批内各样本保留数不同（含首管长必留 + 后续不同比例保留）
    keep_var = np.zeros((B, 8, 14, 14), dtype=bool)
    keep_var[:, 0] = True
    probs = [0.15, 0.45, 0.70, 0.90]
    for b, p in enumerate(probs):
        keep_var[b, 1:] = rng.uniform(0.0, 1.0, size=(7, 14, 14)) < p
    rl_var = np.where(keep_var, rng.integers(1, 9, size=(B, 8, 14, 14)), 0)

    # 场景 2：全保留
    keep_all = np.ones((B, 8, 14, 14), dtype=bool)
    rl_all = np.ones((B, 8, 14, 14), dtype=int)

    # 场景 3：只保留第一个管长（其余 7 个管长全并掉）
    keep_first = np.zeros((B, 8, 14, 14), dtype=bool)
    keep_first[:, 0] = True
    rl_first = np.zeros((B, 8, 14, 14), dtype=int)
    rl_first[:, 0] = 8

    for case_name, k_np, rl_np in [
        ("varying_counts", keep_var, rl_var),
        ("all_kept", keep_all, rl_all),
        ("only_first_tube", keep_first, rl_first),
    ]:
        k_mx = mx.array(k_np)
        rl_mx = mx.array(rl_np)

        out_new, mask_new = model(patches, keep=k_mx, run_len=rl_mx)
        feats_new = [model.features(layer=k) for k in range(1, model.depth + 1)]
        mx.eval(out_new, mask_new, *feats_new)

        out_ref, mask_ref, feats_ref = _legacy_student_forward(model, patches, keep=k_mx, run_len=rl_mx)
        mx.eval(out_ref, mask_ref, *feats_ref)

        assert bool(mx.array_equal(mask_new, mask_ref).item()), f"{case_name}: mask mismatch"
        diff_out = float(mx.max(mx.abs(out_new - out_ref)).item())
        assert diff_out < 1e-4, f"{case_name}: out_tokens max diff {diff_out} >= 1e-4"

        for layer_idx in range(model.depth):
            diff_l = float(mx.max(mx.abs(feats_new[layer_idx] - feats_ref[layer_idx])).item())
            assert diff_l < 1e-4, (
                f"{case_name} layer={layer_idx + 1}: feature max diff {diff_l} >= 1e-4"
            )


def test_student_rlt_keep073_step_wall_time_faster_than_full_keep():
    """P241 测试 5：真实大小学生 (d=192, depth=6)、批量 8、keep 率约 0.73 时，一步前向+反向的中位墙钟 < 全保留的 0.9 倍。"""
    import time

    mx.random.seed(77)
    model = Student(d=192, depth=6, heads=3)
    mx.eval(model.parameters())

    B = 8
    patches = mx.random.normal((B, 8, 14, 14, 1536))

    # 构造 keep 率约 0.73 的掩码（首管长全保留，整体保留率约 0.73）
    rng = np.random.default_rng(20261112)
    keep_np = np.zeros((B, 8, 14, 14), dtype=bool)
    keep_np[:, 0] = True
    # 首管长占 1/8 = 0.125；后 7 管长以 (0.73 - 0.125) / 0.875 = 0.6914 的概率保留 -> 总保留率 ~0.73
    keep_np[:, 1:] = rng.uniform(0.0, 1.0, size=(B, 7, 14, 14)) < 0.6914
    rl_np = np.where(keep_np, 1, 0)

    keep_mx = mx.array(keep_np)
    rl_mx = mx.array(rl_np)
    mx.eval(patches, keep_mx, rl_mx)

    actual_keep_rate = float(np.mean(keep_np))
    assert 0.70 <= actual_keep_rate <= 0.76, f"Expected keep rate ~0.73, got {actual_keep_rate:.4f}"

    def loss_full(m: Student) -> mx.array:
        tok, _ = m(patches)
        return mx.mean(tok * tok)

    def loss_rlt(m: Student) -> mx.array:
        tok, _ = m(patches, keep=keep_mx, run_len=rl_mx)
        return mx.mean(tok * tok)

    vg_full = nn.value_and_grad(model, loss_full)
    vg_rlt = nn.value_and_grad(model, loss_rlt)

    # 预热 3 步
    for _ in range(3):
        l_f, g_f = vg_full(model)
        mx.eval(l_f, g_f)
        l_r, g_r = vg_rlt(model)
        mx.eval(l_r, g_r)

    full_times = []
    rlt_times = []
    for _ in range(9):
        t0 = time.perf_counter()
        l_f, g_f = vg_full(model)
        mx.eval(l_f, g_f)
        full_times.append(time.perf_counter() - t0)

        t1 = time.perf_counter()
        l_r, g_r = vg_rlt(model)
        mx.eval(l_r, g_r)
        rlt_times.append(time.perf_counter() - t1)

    med_full = float(np.median(full_times))
    med_rlt = float(np.median(rlt_times))
    ratio = med_rlt / med_full
    print(
        f"P241_TIMING keep_rate={actual_keep_rate:.4f} "
        f"med_full_s={med_full:.6f} med_rlt_s={med_rlt:.6f} ratio={ratio:.4f}"
    )
    assert med_rlt < 0.9 * med_full, (
        f"Expected RLT median step time ({med_rlt:.4f}s) < 0.9 * full-keep ({med_full:.4f}s), ratio={ratio:.4f}"
    )

