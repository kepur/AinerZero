"""S5 数据读取与训练循环原生 MLX 测试。

必须经锁执行（HOLD_LOCK artifacts/locks/m0-worker.lock）。
测试项：
5. 每个臂（A1、A2、A3、C-sh、R、A0、A4、A0-R、train_heads）均能跑 20 步，损失有限且下降；
6. C-sh 收到的教师目标确实是置换后的；
7. R 臂里被并掉 token 对应的 DA2 区域不计入损失：把这些区域的目标改成极端值，损失严格不变；
8. A4 的对齐项对教师没有梯度，对学生第 align_layer 层之前的参数有梯度；
9. 冻结学生的 train_heads 结束后，学生权重逐元素完全不变；
10. 检查点个数与步号：总步数 32、ckpt_every_frac=1/16 时存 16 个，最后一步必存；
11. 确定性：同一配置跑两次，权重逐元素相同。
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import mlx.core as mx
import mlx.nn as nn
from mlx.utils import tree_flatten
import numpy as np
import pytest

# 标记为原生 MLX 测试模块
pytestmark = pytest.mark.native_mlx

from ainerzero.v9.experiments.s5 import data as D
from ainerzero.v9.experiments.s5 import train as T
from ainerzero.v9.experiments.s5.heads import (
    DepthDistillHead,
    FlatHead,
    R1Head,
    VJEPAProjHead,
)
from ainerzero.v9.experiments.s5.losses import (
    align_loss,
    cosine_distill_loss,
    permutation,
    ssi_depth_loss,
)
from ainerzero.v9.experiments.s5.materialize import materialize_partition
from ainerzero.v9.experiments.s5.metrics import grid_ap
from ainerzero.v9.experiments.s5.student import Student
from ainerzero.v9.experiments.s5.tokens import rlt_keep


@pytest.fixture(scope="module")
def train_fixture(tmp_path_factory) -> Path:
    """创建极小的 2 世界 × 2 段数据集与假教师特征。"""
    root = tmp_path_factory.mktemp("train_fixture")
    part_dir = root / "part"
    materialize_partition("s5test-train", part_dir, world_range=(0, 2))

    # 保留每个世界前 2 段，删除其余段以保持极小规模 (2 世界 × 2 段 = 4 段)
    for w in range(2):
        wdir = part_dir / f"world_{w:04d}"
        for cf in list(wdir.glob("clip_*.npy")) + list(wdir.glob("labels_*.npz")):
            try:
                c_num = int(cf.name.split("_")[1].split(".")[0])
                if c_num >= 2:
                    cf.unlink()
            except (IndexError, ValueError):
                pass

    teachers_dir = root / "teachers"
    teachers_dir.mkdir(parents=True)
    ledger_lines = []

    for w in range(2):
        wdir = teachers_dir / f"world_{w:04d}"
        wdir.mkdir(parents=True)
        for c in range(2):
            # V-JEPA [1568, 1024] fp16
            v_file = wdir / f"clip_{c:02d}.vjepa.npy"
            rng = np.random.default_rng(w * 100 + c)
            v_data = rng.standard_normal((1568, 1024)).astype(np.float16)
            np.save(v_file, v_data)
            v_rel = f"world_{w:04d}/clip_{c:02d}.vjepa.npy"
            v_sha = D._sha256_file(v_file)
            ledger_lines.append(json.dumps({"file": v_rel, "sha256": v_sha, "seconds": 0.01, "at": 1000.0}))

            # DA2 [8, 56, 56] fp16
            d_file = wdir / f"da2_{c:02d}.da2.npy"
            d_data = (rng.uniform(1.0, 5.0, (8, 56, 56))).astype(np.float16)
            np.save(d_file, d_data)
            d_rel = f"world_{w:04d}/da2_{c:02d}.da2.npy"
            d_sha = D._sha256_file(d_file)
            ledger_lines.append(json.dumps({"file": d_rel, "sha256": d_sha, "seconds": 0.01, "at": 1000.0}))

    (teachers_dir / "progress.jsonl").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")
    return root


def _make_small_student() -> Student:
    """构建极小学生 ViT (d=32, depth=2, heads=2)。"""
    return Student(d=32, depth=2, heads=2)


# ------------------------------------------------------------------------------------------------
# 5. 每个臂跑 20 步，损失有限且下降
# ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "arm_config",
    [
        ("A1", "distill", {}),
        ("A2", "distill", {}),
        ("A3", "distill", {}),
        ("C-sh", "distill", {"perm_seed": 42}),
        ("R", "distill", {"tau": 0.02}),
        ("A0", "supervised", {}),
        ("A4", "supervised", {"eta": 0.5}),
        ("A0-R", "supervised", {"tau": 0.02}),
        ("train_heads", "heads", {}),
    ],
)
def test_all_arms_run_and_loss_decreases(train_fixture, arm_config):
    arm_name, mode, kwargs = arm_config
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"

    # batch_size=2，4段数据每轮2批；epochs=10共20步
    cfg = T.TrainConfig(
        lr=2e-3,
        batch_size=2,
        epochs=10,
        seed=1,
        tau=kwargs.get("tau"),
        eta=kwargs.get("eta"),
    )

    student = _make_small_student()

    if mode == "distill":
        distill_arm = "A3" if arm_name in ("C-sh", "R") else arm_name
        student, heads, log = T.distill(
            distill_arm,
            idx,
            teachers,
            cfg,
            perm_seed=kwargs.get("perm_seed"),
            student=student,
        )
    elif mode == "supervised":
        student, heads, log = T.train_supervised(
            idx,
            cfg,
            teachers=teachers,
            student=student,
        )
    elif mode == "heads":
        heads, log = T.train_heads(student, idx, cfg)

    assert log["total_steps"] == 20
    assert len(log["step_logs"]) == 20

    losses = [l["loss"] for l in log["step_logs"]]
    for loss in losses:
        assert np.isfinite(loss), f"{arm_name} loss is not finite: {loss}"

    # 验证损失整体收敛下降
    avg_first_3 = float(np.mean(losses[:3]))
    avg_last_3 = float(np.mean(losses[-3:]))
    assert avg_last_3 < avg_first_3, f"{arm_name}: last {avg_last_3} not < first {avg_first_3}"


# ------------------------------------------------------------------------------------------------
# 6. C-sh 目标确实被置换
# ------------------------------------------------------------------------------------------------
def test_c_sh_teacher_targets_are_permuted(train_fixture, monkeypatch):
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"
    n_items = len(idx)
    perm_seed = 99

    perm = np.array(permutation(n_items, perm_seed))
    # 验证错排无不动点
    assert not np.any(perm == np.arange(n_items))

    # 比对普通读取与置换读取的教师目标
    for i in range(n_items):
        item_orig = D.load_item(idx, i, teachers=teachers)
        item_perm = D.load_item(idx, perm[i], teachers=teachers)
        # 置换目标的特征与原目标的特征不相同
        assert not np.array_equal(item_orig["vjepa"], item_perm["vjepa"])
        assert not np.array_equal(item_orig["da2"], item_perm["da2"])

    # 验证 distill 在 C-sh 模式下确实向教师 load_teacher 传入了错排的 t_idx
    teacher_indices_loaded = []
    orig_load_teacher = T.load_teacher

    def tracking_load_teacher(index, i, teachers, **kwargs):
        teacher_indices_loaded.append(i)
        return orig_load_teacher(index, i, teachers, **kwargs)

    monkeypatch.setattr(T, "load_teacher", tracking_load_teacher)
    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=1, seed=1)
    s = _make_small_student()
    T.distill("A3", idx, teachers, cfg, perm_seed=perm_seed, student=s)

    # 验证被读取的教师索引确实为 perm_map[b_idx]，且与原 batch 索引无一相同（无不动点错排）
    assert len(teacher_indices_loaded) == 4
    batch_0 = list(T.batches(idx, 2, 1, 0))
    expected_t_indices = [perm[k] for b in batch_0 for k in b]
    assert teacher_indices_loaded == expected_t_indices


# ------------------------------------------------------------------------------------------------
# 7. R 臂被并掉 token 对应的 DA2 区域不计入损失
# ------------------------------------------------------------------------------------------------
def test_r_arm_dropped_tokens_da2_region_loss_invariance(train_fixture, monkeypatch):
    # 构造一批单样本预测与真实目标
    # 模拟在 R 臂下，某位置 token 被并掉 (keep = 0)
    pred_da2 = mx.random.normal((1, 8, 56, 56))
    target_da2 = mx.random.normal((1, 8, 56, 56))

    keep = np.ones((1, 8, 14, 14), dtype=np.bool_)
    # 将管长 0 的 (h=2, w=3) 设为被并掉 (keep=0)
    keep[0, 0, 2, 3] = False
    keep_mx = mx.array(keep)

    # 扩展为 56x56 掩码
    keep_56 = mx.repeat(mx.repeat(keep_mx, 4, axis=-2), 4, axis=-1)

    loss_clean = ssi_depth_loss(pred_da2, target_da2, valid=keep_56)

    # 将被并掉的 4x4 区域填充极端值 (+999999.0)
    target_corrupted = np.array(target_da2)
    target_corrupted[0, 0, 8:12, 12:16] = 999999.0
    loss_corrupted = ssi_depth_loss(pred_da2, mx.array(target_corrupted), valid=keep_56)

    # 验证损失严格完全不变
    assert abs(loss_clean.item() - loss_corrupted.item()) < 1e-6

    # 验证 distill 在 R 臂 (tau > 0) 下确实向 ssi_depth_loss 传入 valid 掩码
    passed_valid_masks = []
    orig_ssi = T.ssi_depth_loss

    def tracking_ssi(pred, target, *, valid=None):
        passed_valid_masks.append(valid)
        return orig_ssi(pred, target, valid=valid)

    monkeypatch.setattr(T, "ssi_depth_loss", tracking_ssi)
    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=1, seed=1, tau=0.02)
    s = _make_small_student()
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"
    T.distill("A1", idx, teachers, cfg, student=s)

    assert len(passed_valid_masks) > 0
    assert any(vm is not None for vm in passed_valid_masks), "valid_mask was not passed to ssi_depth_loss in R-arm distill"


# ------------------------------------------------------------------------------------------------
# 8. A4 对齐项对教师无梯度，对学生 align_layer 之前的参数有梯度
# ------------------------------------------------------------------------------------------------
def test_a4_alignment_gradients(train_fixture):
    student = Student(d=32, depth=4, heads=2)
    align_proj = VJEPAProjHead(d=32, out_dim=64)

    patches = mx.random.normal((1, 8, 14, 14, 1536))
    teacher_vjepa = mx.random.normal((1, 1568, 64))

    combined = T.ModelWithHeads(student, T.HeadsContainer({"align_proj": align_proj}))

    def loss_fn(model):
        feat, _ = model.student.features(patches, layer=2)  # align_layer=2
        proj_feat = model.heads["align_proj"](feat)
        return align_loss(proj_feat, teacher_vjepa)

    loss_val, grads = nn.value_and_grad(combined, loss_fn)(combined)

    # 1. 投影头有梯度
    assert mx.sum(mx.abs(grads["heads"]["align_proj"]["proj"]["weight"])).item() > 0.0

    # 2. 学生第 0、1 层 (layer <= align_layer) 应该有梯度
    b0_grad = mx.sum(mx.abs(grads["student"]["blocks"][0]["n1"]["weight"])).item()
    b1_grad = mx.sum(mx.abs(grads["student"]["blocks"][1]["n1"]["weight"])).item()
    assert b0_grad > 0.0
    assert b1_grad > 0.0

    # 3. 学生第 2、3 层 (layer > align_layer) 梯度应严格为 0
    b2_grad = mx.sum(mx.abs(grads["student"]["blocks"][2]["n1"]["weight"])).item()
    b3_grad = mx.sum(mx.abs(grads["student"]["blocks"][3]["n1"]["weight"])).item()
    assert b2_grad == 0.0
    assert b3_grad == 0.0

    # 4. 验证 train_supervised 在 A4 (eta > 0) 下对齐损失切实参与训练且更新 align_proj 头
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"
    cfg = T.TrainConfig(lr=1e-2, weight_decay=0.0, batch_size=2, epochs=1, seed=1, eta=0.5, align_layer=2)
    s = _make_small_student()
    init_proj = VJEPAProjHead(d=s.d, out_dim=1024)
    w_before = np.array(init_proj.proj.weight)
    heads_in = T.HeadsContainer(align_proj=init_proj)
    s_out, heads_out, log = T.train_supervised(idx, cfg, teachers=teachers, student=s, heads=heads_in)
    w_after = np.array(heads_out["align_proj"].proj.weight)
    assert not np.array_equal(w_before, w_after), "align_proj weight was not updated during A4 training"

    # 5. 验证 A4 严格取 cfg.align_layer 对应的特征层，而不是 align_layer + 1
    requested_layers = []
    orig_features = s.features

    def spy_features(*args, layer=-1, **kwargs):
        requested_layers.append(layer)
        return orig_features(*args, layer=layer, **kwargs)

    s.features = spy_features
    cfg_l1 = T.TrainConfig(lr=1e-3, batch_size=2, epochs=1, seed=1, eta=0.5, align_layer=1)
    T.train_supervised(idx, cfg_l1, teachers=teachers, student=s)
    assert len(requested_layers) > 0
    assert requested_layers[0] == 1, f"Expected align_layer=1, but got {requested_layers[0]}"


# ------------------------------------------------------------------------------------------------
# 9. 冻结学生的 train_heads 结束后，学生权重逐元素完全不变
# ------------------------------------------------------------------------------------------------
def test_frozen_student_weights_invariant_in_train_heads(train_fixture):
    idx = D.ClipIndex(train_fixture / "part")
    student = _make_small_student()

    weights_before = {k: np.array(v) for k, v in tree_flatten(student.parameters())}

    cfg = T.TrainConfig(lr=1e-2, batch_size=2, epochs=4, seed=42)
    heads, log = T.train_heads(student, idx, cfg)

    weights_after = {k: np.array(v) for k, v in tree_flatten(student.parameters())}

    for k in weights_before:
        np.testing.assert_array_equal(
            weights_before[k],
            weights_after[k],
            err_msg=f"Student weight {k} modified during train_heads",
        )


# ------------------------------------------------------------------------------------------------
# 10. 检查点个数与步号：总步数 32、ckpt_every_frac=1/16 时存 16 个；最后一步必存
# ------------------------------------------------------------------------------------------------
def test_checkpoints_count_and_step_numbers(train_fixture, tmp_path):
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"
    ckpt_dir = tmp_path / "ckpts"

    # 4 段数据，batch_size=2，每轮 2 步；epochs=16 -> total_steps=32
    cfg = T.TrainConfig(
        lr=1e-3,
        batch_size=2,
        epochs=16,
        seed=1,
        ckpt_every_frac=1.0 / 16.0,
        ckpt_dir=ckpt_dir,
    )

    student = _make_small_student()
    _, _, log = T.distill("A1", idx, teachers, cfg, student=student)

    assert log["total_steps"] == 32
    ckpts = log["checkpoints"]

    # 1. 验证正好 16 个检查点
    assert len(ckpts) == 16

    # 2. 验证步号严格为 [2, 4, 6, ..., 32]，步长为 2
    steps = [c["step"] for c in ckpts]
    assert steps == list(range(2, 33, 2))

    # 3. 最后一步第 32 步必须保存且文件存在
    assert steps[-1] == 32
    final_ckpt = Path(ckpts[-1]["path"])
    assert final_ckpt.exists()

    # 4. 验证当总步数不是 ckpt_interval 的整数倍时，最后一步依然必定保存
    idx_odd = D.ClipIndex(train_fixture / "part")
    idx_odd.items = idx_odd.items[:3]  # 3 items, batch_size=2 -> 1 batch per epoch
    cfg_odd = T.TrainConfig(
        lr=1e-3,
        batch_size=2,
        epochs=5,
        seed=1,
        ckpt_every_frac=0.5,
        ckpt_dir=tmp_path / "ckpts_odd",
    )
    s_odd = _make_small_student()
    _, _, log_odd = T.distill("A1", idx_odd, teachers, cfg_odd, student=s_odd)
    assert log_odd["total_steps"] == 5
    steps_odd = [c["step"] for c in log_odd["checkpoints"]]
    assert steps_odd[-1] == 5, f"Last step 5 not saved in odd run: {steps_odd}"


# ------------------------------------------------------------------------------------------------
# 11. 确定性：同一配置跑两次，权重逐元素相同
# ------------------------------------------------------------------------------------------------
def test_training_determinism(train_fixture):
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"

    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=2, seed=777)

    # Run 1
    mx.random.seed(cfg.seed)
    s1 = _make_small_student()
    s1, h1, _ = T.distill("A1", idx, teachers, cfg, student=s1)

    # Run 2
    mx.random.seed(cfg.seed)
    s2 = _make_small_student()
    s2, h2, _ = T.distill("A1", idx, teachers, cfg, student=s2)

    # 验证权重逐元素完全相同
    p1 = dict(tree_flatten(s1.parameters()))
    p2 = dict(tree_flatten(s2.parameters()))

    for k in p1:
        np.testing.assert_array_equal(np.array(p1[k]), np.array(p2[k]))


# ------------------------------------------------------------------------------------------------
# 12. 多头推理与预测形状
# ------------------------------------------------------------------------------------------------
def test_predict_shapes_and_tau(train_fixture):
    idx = D.ClipIndex(train_fixture / "part")
    student = _make_small_student()
    heads = T.HeadsContainer(
        r1=R1Head(d=student.d),
        r2=FlatHead(d=student.d, k=4),
        r3=FlatHead(d=student.d, k=4),
    )

    # 1. 无 tau 推理
    preds = T.predict(student, heads, idx, batch_size=2)
    assert preds["r1_logd"].shape == (4, 16, 14, 14)
    assert preds["r2_logit"].shape == (4, 12, 7)
    assert preds["r3_logit"].shape == (4, 12, 7)
    assert "keep_rate" not in preds

    # 2. 带 tau 推理
    preds_tau = T.predict(student, heads, idx, tau=0.02, batch_size=2)
    assert preds_tau["r1_logd"].shape == (4, 16, 14, 14)
    assert "keep_rate" in preds_tau
    assert 0.0 < preds_tau["keep_rate"] <= 1.0


# ------------------------------------------------------------------------------------------------
# 13. restore_runs 游程还原性质
# ------------------------------------------------------------------------------------------------
def test_restore_runs_properties():
    B, d = 2, 16
    tokens = mx.random.normal((B, 8, 14, 14, d))

    # 1. 全保留时为恒等变换
    keep_all = mx.ones((B, 8, 14, 14), dtype=mx.bool_)
    restored_all = T.restore_runs(tokens, keep_all)
    np.testing.assert_array_equal(np.array(tokens), np.array(restored_all))

    # keep=None 时为恒等变换
    np.testing.assert_array_equal(np.array(tokens), np.array(T.restore_runs(tokens, None)))

    # 2. 部分保留时，被并掉位置等于其游程起点的 token
    keep_part = np.ones((B, 8, 14, 14), dtype=np.bool_)
    # 在 (b=0, h=3, w=4) 处：t=1, 2 被并掉（从 t=0 延伸）
    keep_part[0, 1, 3, 4] = False
    keep_part[0, 2, 3, 4] = False
    # t=3 保留，t=4 被并掉（从 t=3 延伸）
    keep_part[0, 4, 3, 4] = False

    restored = T.restore_runs(tokens, mx.array(keep_part))
    # 验证 t=1 和 t=2 的 token 严格等于 t=0 的 token
    np.testing.assert_array_equal(np.array(restored[0, 1, 3, 4]), np.array(tokens[0, 0, 3, 4]))
    np.testing.assert_array_equal(np.array(restored[0, 2, 3, 4]), np.array(tokens[0, 0, 3, 4]))
    # 验证 t=4 的 token 严格等于 t=3 的 token
    np.testing.assert_array_equal(np.array(restored[0, 4, 3, 4]), np.array(tokens[0, 3, 3, 4]))

    # 3. 在被并掉位置填入极端脏数据，restore_runs 输出完全不变
    corrupted = np.array(tokens)
    corrupted[0, 1, 3, 4] = 999999.0
    corrupted[0, 2, 3, 4] = -888888.0
    corrupted[0, 4, 3, 4] = 777777.0
    restored_from_corrupted = T.restore_runs(mx.array(corrupted), mx.array(keep_part))
    np.testing.assert_array_equal(np.array(restored), np.array(restored_from_corrupted))


# ------------------------------------------------------------------------------------------------
# 14. A0-R 下被并掉位置的学生输出改极端值，R1 损失不变
# ------------------------------------------------------------------------------------------------
def test_a0_r_dropped_tokens_r1_loss_invariance():
    r1_head = R1Head(d=16)
    tokens = mx.random.normal((1, 8, 14, 14, 16))
    keep = np.ones((1, 8, 14, 14), dtype=np.bool_)
    keep[0, 1:4, 2, 2] = False  # t=1, 2, 3 被并掉
    keep_mx = mx.array(keep)

    target_logd = mx.random.normal((1, 16, 14, 14))
    target_sky = mx.random.normal((1, 16, 14, 14))

    r1_tokens_clean = T.restore_runs(tokens, keep_mx)
    pred_logd_c, pred_sky_c = r1_head(r1_tokens_clean)
    loss_clean = r1_head.loss(pred_logd_c, pred_sky_c, target_logd, target_sky)

    corrupted = np.array(tokens)
    corrupted[0, 1:4, 2, 2] = 999999.0
    r1_tokens_corrupted = T.restore_runs(mx.array(corrupted), keep_mx)
    pred_logd_bad, pred_sky_bad = r1_head(r1_tokens_corrupted)
    loss_corrupted = r1_head.loss(pred_logd_bad, pred_sky_bad, target_logd, target_sky)

    assert abs(loss_clean.item() - loss_corrupted.item()) < 1e-6


# ------------------------------------------------------------------------------------------------
# 15. A4 一步里 Student.__call__ 恰好只调用一次
# ------------------------------------------------------------------------------------------------
def test_a4_single_forward_call(train_fixture, monkeypatch):
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"
    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=1, seed=1, eta=0.5, align_layer=2)
    student = _make_small_student()

    call_count = 0
    orig_call = Student.__call__

    def counting_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return orig_call(*args, **kwargs)

    monkeypatch.setattr(Student, "__call__", counting_call)
    T.train_supervised(idx, cfg, teachers=teachers, student=student)

    # 4 段数据，batch_size=2，共 2 步，每步严格恰好 1 次前向
    assert call_count == 2, f"Expected exactly 2 forward calls for 2 steps, got {call_count}"


# ------------------------------------------------------------------------------------------------
# 16. train_supervised 训练确定性
# ------------------------------------------------------------------------------------------------
def test_train_supervised_determinism(train_fixture):
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"
    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=2, seed=42)

    # Run 1: 不传外部初始化的 student，验证函数内部 seed 后新建学生与读出头的确定性
    s1, h1, _ = T.train_supervised(idx, cfg, teachers=teachers, student=None)

    # 扰乱全局随机状态
    mx.random.seed(999)
    np.random.seed(999)

    # Run 2
    s2, h2, _ = T.train_supervised(idx, cfg, teachers=teachers, student=None)

    # 验证权重逐元素完全相同
    p1 = dict(tree_flatten(s1.parameters()))
    p2 = dict(tree_flatten(s2.parameters()))
    for k in p1:
        np.testing.assert_array_equal(np.array(p1[k]), np.array(p2[k]))

    h1_p = dict(tree_flatten(h1.parameters()))
    h2_p = dict(tree_flatten(h2.parameters()))
    for k in h1_p:
        np.testing.assert_array_equal(np.array(h1_p[k]), np.array(h2_p[k]))


# ------------------------------------------------------------------------------------------------
# 17. R 臂加 A2 时，被并掉 token 处 V-JEPA 教师特征改极端值，损失严格不变
# ------------------------------------------------------------------------------------------------
def test_r_arm_vjepa_dropped_tokens_loss_invariance(train_fixture, monkeypatch):
    # 1. 单元级验证 cosine_distill_loss 在传入 mask 时对 dropped token 的教师特征完全不变
    proj = mx.random.normal((1, 1568, 1024))
    target_clean = mx.random.normal((1, 1568, 1024))
    mask = mx.ones((1, 1568), dtype=mx.bool_)
    mask[0, 10] = False  # token 10 被并掉

    loss_clean = cosine_distill_loss(proj, target_clean, mask=mask)

    target_corrupted = np.array(target_clean)
    target_corrupted[0, 10, :] = 999999.0
    loss_corrupted = cosine_distill_loss(proj, mx.array(target_corrupted), mask=mask)

    assert abs(loss_clean.item() - loss_corrupted.item()) < 1e-5

    # 2. 验证 distill 在 R 臂 (tau > 0) + A2 下确实将 mask 传入了 cosine_distill_loss
    passed_masks = []
    orig_cosine = T.cosine_distill_loss

    def tracking_cosine(pred, target, *, mask=None):
        passed_masks.append(mask)
        return orig_cosine(pred, target, mask=mask)

    monkeypatch.setattr(T, "cosine_distill_loss", tracking_cosine)
    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=1, seed=1, tau=0.02)
    s = _make_small_student()
    idx = D.ClipIndex(train_fixture / "part")
    teachers = train_fixture / "teachers"
    T.distill("A2", idx, teachers, cfg, student=s)

    assert len(passed_masks) > 0
    assert any(m is not None for m in passed_masks), "mask was not passed to cosine_distill_loss in R-arm A2 distill"


# ------------------------------------------------------------------------------------------------
# P235 第 3 轮（一级补）：restore_runs 的三个调用点
# ------------------------------------------------------------------------------------------------
def _fill_dropped(fill):
    """Wrap Student.__call__ so that dropped (keep=False) token outputs are `fill` instead of zeros."""
    orig = Student.__call__

    def wrapped(self, patches, keep=None, run_len=None):
        tokens, mask = orig(self, patches, keep=keep, run_len=run_len)
        if keep is None:
            return tokens, mask
        return mx.where(mask[..., None], tokens, mx.array(fill, dtype=tokens.dtype)), mask

    return wrapped


def _r1_weights(heads):
    return {k: np.array(v) for k, v in tree_flatten(heads["r1"].parameters())}


def test_predict_restores_dropped_positions_from_run_start(train_fixture):
    """U2: with RLT, R1 predictions at a dropped tubelet equal those of its run-start tubelet."""
    idx = D.ClipIndex(train_fixture / "part")
    mx.random.seed(5)
    student = _make_small_student()
    heads = T.HeadsContainer(r1=R1Head(d=32), r2=FlatHead(d=32, k=4),
                             r3=FlatHead(d=32, k=4))
    out = T.predict(student, heads, idx, tau=0.02)
    plain = T.predict(student, heads, idx, tau=None)
    checked = 0
    for n in range(len(idx)):
        keep, _ = rlt_keep(D.load_item(idx, n)["patches"], 0.02)
        for t in range(1, 8):
            for h, w in zip(*np.where(~keep[t])):
                a = max(s for s in range(t + 1) if keep[s, h, w])
                np.testing.assert_allclose(out["r1_logd"][n, 2 * t:2 * t + 2, h, w],
                                           out["r1_logd"][n, 2 * a:2 * a + 2, h, w], atol=1e-6)
                checked += 1
    assert checked > 0, "fixture must contain dropped tokens at tau=0.02"
    assert not np.allclose(out["r1_logd"], plain["r1_logd"])     # restoration changed something


def test_train_heads_r1_ignores_dropped_token_values(train_fixture, monkeypatch):
    """U3: frozen-student head training must feed R1Head restored tokens, never dropped outputs."""
    idx = D.ClipIndex(train_fixture / "part")
    cfg = T.TrainConfig(lr=1e-2, batch_size=2, epochs=2, seed=11, tau=0.02)
    calls = []
    real = T.restore_runs
    monkeypatch.setattr(T, "restore_runs", lambda tok, keep: (calls.append(keep is not None), real(tok, keep))[1])
    results = []
    for fill in (0.0, 1.0e3):
        monkeypatch.setattr(Student, "__call__", _fill_dropped(fill))
        mx.random.seed(3)
        student = _make_small_student()
        heads, _ = T.train_heads(student, idx, cfg)
        results.append(_r1_weights(heads))
    assert calls and all(calls), "train_heads must call restore_runs with a keep mask under RLT"
    for k in results[0]:
        np.testing.assert_allclose(results[0][k], results[1][k], atol=1e-5, err_msg=k)


def test_a0r_r1_loss_ignores_dropped_token_values(train_fixture, monkeypatch):
    """U5: A0-R training losses must not depend on what the student emits at dropped positions."""
    idx = D.ClipIndex(train_fixture / "part")
    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=1, seed=13, tau=0.02)
    calls = []
    real = T.restore_runs
    monkeypatch.setattr(T, "restore_runs", lambda tok, keep: (calls.append(keep is not None), real(tok, keep))[1])
    losses = []
    for fill in (0.0, 1.0e3):
        monkeypatch.setattr(Student, "__call__", _fill_dropped(fill))
        mx.random.seed(4)
        _, _, log = T.train_supervised(idx, cfg, student=_make_small_student())
        losses.append([s["loss"] for s in log["step_logs"][:2]])
    assert calls and all(calls), "A0-R must call restore_runs with a keep mask"
    np.testing.assert_allclose(losses[0], losses[1], rtol=1e-5)


def test_predict_grid_logits_ignore_dropped_token_values(train_fixture, monkeypatch):
    """RLT 下被并掉位置的值不影响 r2/r3。机理是 restore_runs 之后再读 FlatHead，不再是 GridHead 掩码。"""
    idx = D.ClipIndex(train_fixture / "part")
    outs = []
    for fill in (0.0, 1.0e3):
        monkeypatch.setattr(Student, "__call__", _fill_dropped(fill))
        mx.random.seed(21)
        student = _make_small_student()
        heads = T.HeadsContainer(r1=R1Head(d=32), r2=FlatHead(d=32, k=4),
                                 r3=FlatHead(d=32, k=4))
        outs.append(T.predict(student, heads, idx, tau=0.02))
    for key in ("r2_logit", "r3_logit", "r1_logd"):
        np.testing.assert_allclose(outs[0][key], outs[1][key], rtol=1e-5, atol=1e-5, err_msg=key)


# ------------------------------------------------------------------------------------------------
# P240：FlatHead（最后一个管长逐 token 打分 + 按位置线性映射）
# ------------------------------------------------------------------------------------------------
def _mean_bce_with_logits(logits: np.ndarray, targets: np.ndarray) -> float:
    x = np.asarray(logits, dtype=np.float64)
    y = np.asarray(targets, dtype=np.float64)
    per = np.maximum(x, 0.0) - x * y + np.log1p(np.exp(-np.abs(x)))
    return float(np.mean(per))


def _mean_pool_then_project(head: FlatHead, tokens: mx.array) -> mx.array:
    """坏对照：展平前对 196 个位置做平均再广播。交换两个位置不再改变输出。"""
    B = tokens.shape[0]
    d = tokens.shape[-1]
    last = tokens.reshape(B, 8, 196, d)[:, 7]
    scores = head.score(head.norm(last))
    pooled = mx.mean(scores, axis=1, keepdims=True)
    flat = mx.broadcast_to(pooled, (B, 196, head.k)).reshape(B, 196 * head.k)
    return head.position(flat).reshape(B, head.out[0], head.out[1])


def test_flat_head_loss_is_unweighted_mean_bce():
    """BCE with_logits 的 mean，不加正例权重。"""
    logits = np.array([[0.2, -1.5, 0.7, 2.0], [-0.4, 0.1, 1.2, -2.2]], dtype=np.float32)
    targets = np.array([[0.0, 1.0, 1.0, 0.0], [1.0, 0.0, 1.0, 0.0]], dtype=np.float32)
    head = FlatHead(d=8, k=4)
    got = float(head.loss(mx.array(logits), mx.array(targets)).item())
    ref = _mean_bce_with_logits(logits, targets)
    assert abs(got - ref) < 1e-5
    weights = 1.0 + 9.0 * targets
    per = np.maximum(logits, 0.0) - logits * targets + np.log1p(np.exp(-np.abs(logits)))
    weighted = float(np.sum(weights * per) / np.sum(weights))
    assert abs(weighted - ref) > 1e-3


def test_flat_head_reads_only_the_last_tube():
    """改 0–6 管长不变；改第 7 管长的任一 token 则变。"""
    mx.random.seed(0)
    head = FlatHead(d=16, k=4)
    tokens = mx.random.normal((2, 1568, 16))
    base = np.array(head(tokens))

    early = np.array(tokens)
    early.reshape(2, 8, 196, 16)[:, :7] = np.random.default_rng(1).normal(size=(2, 7, 196, 16))
    same = np.array(head(mx.array(early)))
    np.testing.assert_allclose(base, same, atol=1e-5)

    last = np.array(tokens)
    last.reshape(2, 8, 196, 16)[:, 7, 3, 0] += 5.0
    changed = np.array(head(mx.array(last)))
    assert float(np.max(np.abs(changed - base))) > 1e-3


def test_flat_head_output_changes_when_positions_swap():
    """两个不同位置互换后输出改变。平均池化坏对照则不变。"""
    mx.random.seed(1)
    head = FlatHead(d=16, k=4)
    rng = np.random.default_rng(2)
    raw = rng.normal(size=(1, 1568, 16)).astype(np.float32)
    view = raw.reshape(1, 8, 196, 16)
    view[0, 7, 0] = rng.normal(size=16).astype(np.float32)
    view[0, 7, 17] = rng.normal(size=16).astype(np.float32)
    swapped = raw.copy()
    swapped_view = swapped.reshape(1, 8, 196, 16)
    swapped_view[0, 7, 0], swapped_view[0, 7, 17] = view[0, 7, 17].copy(), view[0, 7, 0].copy()

    tokens = mx.array(raw)
    other = mx.array(swapped)
    diff = float(np.max(np.abs(np.array(head(tokens)) - np.array(head(other)))))
    assert diff > 1e-3

    pooled_diff = float(np.max(np.abs(
        np.array(_mean_pool_then_project(head, tokens)) - np.array(_mean_pool_then_project(head, other))
    )))
    assert pooled_diff < 1e-5


def test_rlt_flat_head_receives_restored_tokens(train_fixture, monkeypatch):
    """开 tau 时，predict 与 train_heads 送进 FlatHead 的是 restore_runs 之后的整段 token。"""
    idx = D.ClipIndex(train_fixture / "part")
    state = {"restored": None, "keep_seen": [], "fed": 0}
    real_restore = T.restore_runs
    real_call = FlatHead.__call__

    def wrap_restore(tok, keep):
        out = real_restore(tok, keep)
        state["restored"] = out
        state["keep_seen"].append(keep is not None)
        return out

    def wrap_call(self, tokens):
        assert state["restored"] is not None, "FlatHead ran before restore_runs"
        np.testing.assert_allclose(np.array(tokens), np.array(state["restored"]), atol=1e-5)
        state["fed"] += 1
        return real_call(self, tokens)

    monkeypatch.setattr(T, "restore_runs", wrap_restore)
    monkeypatch.setattr(FlatHead, "__call__", wrap_call)

    dropped_last = 0
    for n in range(len(idx)):
        keep, _ = rlt_keep(D.load_item(idx, n)["patches"], 0.02)
        dropped_last += int(np.count_nonzero(~keep[7]))
    assert dropped_last > 0, "fixture must drop a last-tube token at tau=0.02"

    mx.random.seed(2)
    student = _make_small_student()
    heads = T.HeadsContainer(
        r1=R1Head(d=32), r2=FlatHead(d=32, k=4), r3=FlatHead(d=32, k=4)
    )
    T.predict(student, heads, idx, tau=0.02)
    assert state["keep_seen"] and all(state["keep_seen"])
    assert state["fed"] == 2 * len(idx)

    state["restored"] = None
    state["keep_seen"] = []
    state["fed"] = 0
    cfg = T.TrainConfig(lr=1e-2, batch_size=2, epochs=1, seed=3, tau=0.02)
    T.train_heads(_make_small_student(), idx, cfg)
    assert state["keep_seen"] and all(state["keep_seen"])
    assert state["fed"] >= 2


def test_supplied_r2_r3_heads_are_kept(train_fixture):
    """调用方传入的 r2、r3 照用，不换成内部新建的头。"""
    idx = D.ClipIndex(train_fixture / "part")
    cfg = T.TrainConfig(lr=1e-3, batch_size=2, epochs=1, seed=1)
    student = _make_small_student()
    r2 = FlatHead(d=student.d, k=4)
    r3 = FlatHead(d=student.d, k=4)
    _, heads, _ = T.train_supervised(idx, cfg, student=student, heads={"r2": r2, "r3": r3})
    assert heads["r2"] is r2 and heads["r3"] is r3
    assert isinstance(heads["r1"], R1Head)


def test_flat_head_train_ap_above_positive_rate(train_fixture):
    """冻结随机学生，只训 FlatHead。训练集 R2 AP 明显高于正例率。"""
    idx = D.ClipIndex(train_fixture / "part")
    mx.random.seed(0)
    student = _make_small_student()
    before = {k: np.array(v) for k, v in tree_flatten(student.parameters())}
    cfg = T.TrainConfig(lr=1e-2, weight_decay=0.0, batch_size=2, epochs=40, seed=0)
    heads, _ = T.train_heads(student, idx, cfg)
    after = {k: np.array(v) for k, v in tree_flatten(student.parameters())}
    for k in before:
        np.testing.assert_array_equal(before[k], after[k])
    assert isinstance(heads["r2"], FlatHead) and heads["r2"].k == 4
    assert isinstance(heads["r3"], FlatHead) and heads["r3"].k == 4

    preds = T.predict(student, heads, idx)
    targets = np.stack([D.load_item(idx, i)["r2"] for i in range(len(idx))], axis=0)
    pos_rate = float(np.mean(targets))
    assert pos_rate > 0.0
    ap = grid_ap(preds["r2_logit"], targets)
    print(f"P240_AP ap={ap:.6f} pos_rate={pos_rate:.6f} margin={ap - pos_rate:.6f}")
    assert ap > pos_rate + 0.05, f"train R2 AP {ap} vs positive rate {pos_rate}"
