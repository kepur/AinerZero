"""Tests for S6 epinet MLX module (s6/epinet_mlx.py).

Verifies:
  - Bitwise parity with base network when z is None or z == 0.
  - Decoupled training bitwise parity with plain rollout_loss on base parameters.
  - Prior network remains frozen during and after training.
  - Stop-gradient isolation: epinet loss gradients do not flow into base hidden or base parameters.
  - Spread reproducibility with same index_seed and variance with different seed.
  - Training loss decreases and is deterministic under identical seed.
  - Non-finite loss raises ValueError.
  - AST check: module does not import or call world.physics.
"""
from __future__ import annotations

import ast
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
import pytest
from mlx.utils import tree_flatten

from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s6 import epinet_mlx as E


def _make_synthetic_pool(S: int = 48, n: int = 3, seed: int = 42) -> L.Pool:
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.1, 0.9, size=(S, n, 2)).astype(np.float32)
    v = rng.uniform(-0.1, 0.1, size=(S, n, 2)).astype(np.float32)
    pil = rng.uniform(0.2, 0.8, size=(S, 3, 3)).astype(np.float32)
    contact = rng.integers(0, 2, size=(S, n, n)).astype(np.float32)
    data = {"p": p, "v": v, "pil": pil, "contact": contact}
    for k in L.ROLLOUT:
        data[f"p{k}"] = (p + k * 0.01 * v).astype(np.float32)
        data[f"v{k}"] = v.copy()
    return L.Pool(by_n={n: data})


def test_epinet_zero_or_none_bitwise_identical_to_base_network():
    """z = 0 或 model.z = None 时，输出与基础网络逐位相同。"""
    mx.random.seed(11)
    base = L.Dynamics("L-int")
    mx.eval(base.parameters())

    epi_model = E.EpiDynamics()
    epi_model.update(base.parameters())
    mx.eval(epi_model.parameters())

    rng = np.random.default_rng(77)
    p = mx.array(rng.uniform(0.1, 0.9, size=(4, 3, 2)).astype(np.float32))
    v = mx.array(rng.uniform(-0.1, 0.1, size=(4, 3, 2)).astype(np.float32))
    pil = mx.array(rng.uniform(0.2, 0.8, size=(4, 3, 3)).astype(np.float32))

    # Case 1: model.z is None
    epi_model.z = None
    p_b, v_b, log_b, _ = base(p, v, pil)
    p_e, v_e, log_e, _ = epi_model(p, v, pil)
    assert mx.array_equal(p_b, p_e), "p_next mismatch when z is None"
    assert mx.array_equal(v_b, v_e), "v_next mismatch when z is None"
    assert mx.array_equal(log_b, log_e), "contact logits mismatch when z is None"

    # Case 2: model.z is all zeros
    epi_model.z = mx.zeros((4, E.DZ))
    p_z0, v_z0, log_z0, _ = epi_model(p, v, pil)
    assert mx.array_equal(p_b, p_z0), "p_next mismatch when z == 0"
    assert mx.array_equal(v_b, v_z0), "v_next mismatch when z == 0"
    assert mx.array_equal(log_b, log_z0), "contact logits mismatch when z == 0"


def test_decoupled_training_base_parameters_bitwise_identical_to_plain_rollout_loss():
    """同种子下，基础参数与只用 rollout_loss 训练的结果逐位相同。"""
    pool = _make_synthetic_pool(S=64, n=3, seed=55)

    # 1. Plain base network trained with rollout_loss
    mx.random.seed(88)
    base = L.Dynamics("L-int")
    mx.eval(base.parameters())

    opt_base = optim.Adam(learning_rate=1e-3)
    vg_base = nn.value_and_grad(base, L.rollout_loss)
    rng_base = np.random.default_rng(1234)

    for n, idx in L.batches(pool, steps=5, batch=8, rng=rng_base, coll_share=0.0):
        b = {k: mx.array(v[idx]) for k, v in pool.by_n[n].items()}
        _, grads = vg_base(base, b)
        grads, _ = optim.clip_grad_norm(grads, max_norm=L.CLIP)
        opt_base.update(base, grads)
        mx.eval(base.parameters(), opt_base.state)

    # 2. EpiDynamics decoupled training
    mx.random.seed(88)
    init_base = L.Dynamics("L-int")
    epi_model = E.EpiDynamics()
    epi_model.update(init_base.parameters())
    mx.eval(epi_model.parameters())

    E.train(epi_model, pool, steps=5, batch=8, seed=1234)

    base_trained = dict(tree_flatten(base.parameters()))
    epi_trained = dict(tree_flatten(epi_model.parameters()))

    for k in base_trained:
        assert k in epi_trained, f"Missing base parameter {k} in epi_model"
        v_base = base_trained[k]
        v_epi = epi_trained[k]
        assert mx.array_equal(v_base, v_epi), (
            f"Parameter {k} not bitwise identical after training! max diff: "
            f"{float(mx.max(mx.abs(v_base - v_epi)).item())}"
        )


def test_prior_network_remains_frozen_after_training():
    """先验网络权重在训练后保持完全不变，且处于 freeze 状态。"""
    pool = _make_synthetic_pool(S=32, n=3, seed=12)
    model = E.EpiDynamics()
    mx.eval(model.parameters())

    # Check prior has 0 trainable parameters
    assert len(tree_flatten(model.prior.trainable_parameters())) == 0, "Prior network is not frozen!"

    prior_before = {k: mx.array(v) for k, v in tree_flatten(model.prior.parameters())}

    E.train(model, pool, steps=4, batch=8, seed=42)

    prior_after = dict(tree_flatten(model.prior.parameters()))
    for k in prior_before:
        assert mx.array_equal(prior_before[k], prior_after[k]), f"Prior parameter {k} changed during training!"
    assert len(tree_flatten(model.prior.trainable_parameters())) == 0, "Prior network unfrozen after training!"


def test_stop_gradient_blocks_gradients_into_base_network():
    """只训 epinet 时，基础参数的梯度严格为零（stop_gradient 有效）。"""
    model = E.EpiDynamics()
    mx.eval(model.parameters())

    rng = np.random.default_rng(21)
    p = mx.array(rng.uniform(0.1, 0.9, size=(4, 3, 2)).astype(np.float32))
    v = mx.array(rng.uniform(-0.1, 0.1, size=(4, 3, 2)).astype(np.float32))
    pil = mx.array(rng.uniform(0.2, 0.8, size=(4, 3, 3)).astype(np.float32))
    b = {
        "p": p, "v": v, "pil": pil,
        "p1": p + 0.01 * v, "v1": v,
    }
    z = mx.array(rng.normal(size=(4, E.DZ)).astype(np.float32))

    vg_epi = nn.value_and_grad(model, E.epinet_step_loss)
    loss, grads = vg_epi(model, b, z)
    mx.eval(loss, grads)

    flat_grads = dict(tree_flatten(grads))
    for k, g in flat_grads.items():
        if not k.startswith("epi."):
            # All non-epinet parameters (base parameters and prior) must have strictly zero gradient
            assert float(mx.max(mx.abs(g)).item()) == 0.0, f"Gradient leaked into base/prior param {k}: {g}"


def test_spread_reproducible_with_same_seed_and_varies_with_different_seed():
    """spread 在同一 index_seed 下完全可重复，不同种子产生不同离散度。"""
    pool = _make_synthetic_pool(S=16, n=3, seed=9)
    model = E.EpiDynamics()
    mx.eval(model.parameters())

    # Call with pool object (by_n dict)
    sp1 = E.spread(model, pool, kz=8, index_seed=1000)
    sp2 = E.spread(model, pool, kz=8, index_seed=1000)
    sp3 = E.spread(model, pool, kz=8, index_seed=2000)

    assert isinstance(sp1, dict)
    for n in sp1:
        assert np.array_equal(sp1[n], sp2[n]), f"Spread not reproducible for n={n} with same index_seed"
        assert not np.array_equal(sp1[n], sp3[n]), f"Spread did not vary for n={n} with different index_seed"
        assert sp1[n].shape == (16, n), f"Unexpected spread shape {sp1[n].shape}"

    # Also test single-dict pool input
    single_dict = pool.by_n[3]
    s_single1 = E.spread(model, single_dict, kz=8, index_seed=1000)
    s_single2 = E.spread(model, single_dict, kz=8, index_seed=1000)
    s_single3 = E.spread(model, single_dict, kz=8, index_seed=3000)
    assert np.array_equal(s_single1, s_single2)
    assert not np.array_equal(s_single1, s_single3)
    assert s_single1.shape == (16, 3)


def test_training_loss_decreases_and_reproducible_under_same_seed():
    """训练同种子下完全可重复，在评估批次上损失显著降低。"""
    pool = _make_synthetic_pool(S=64, n=3, seed=33)
    b_eval = {k: mx.array(v[:8]) for k, v in pool.by_n[3].items()}
    z_eval = mx.zeros((8, E.DZ))

    mx.random.seed(101)
    m1 = E.EpiDynamics()
    mx.eval(m1.parameters())

    mx.random.seed(101)
    m2 = E.EpiDynamics()
    mx.eval(m2.parameters())

    l_before = float(E.total_loss(m1, b_eval, z_eval).item())

    losses1 = E.train(m1, pool, steps=20, batch=8, seed=42)
    losses2 = E.train(m2, pool, steps=20, batch=8, seed=42)

    l_after = float(E.total_loss(m1, b_eval, z_eval).item())

    assert len(losses1) == 20
    assert np.allclose(losses1, losses2, atol=1e-6), "Loss trajectories differ under identical seed"
    assert l_after < l_before, f"Loss did not decrease on eval batch: {l_before} -> {l_after}"

    p1 = dict(tree_flatten(m1.parameters()))
    p2 = dict(tree_flatten(m2.parameters()))
    for k in p1:
        assert mx.array_equal(p1[k], p2[k]), f"Model parameters differ after identical seed training on {k}"


def test_non_finite_loss_raises_error():
    """损失非有限时抛出异常。"""
    pool = _make_synthetic_pool(S=16, n=3, seed=5)
    # Inject NaN into pool target
    pool.by_n[3]["p1"][0, 0, 0] = np.nan

    model = E.EpiDynamics()
    mx.eval(model.parameters())

    with pytest.raises(ValueError, match="Non-finite loss"):
        E.train(model, pool, steps=3, batch=8, seed=1)


def test_epinet_module_does_not_call_world_physics_ast():
    """AST 检查：模块不得导入或调用 world.physics。"""
    src_file = Path("src/ainerzero/v9/experiments/s6/epinet_mlx.py")
    assert src_file.is_file()

    tree = ast.parse(src_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "world" not in alias.name, f"Forbidden import: {alias.name}"
                assert "physics" not in alias.name, f"Forbidden import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert "world" not in mod, f"Forbidden from-import module: {mod}"
            for alias in node.names:
                assert "physics" not in alias.name, f"Forbidden from-import name: {alias.name}"
        elif isinstance(node, ast.Attribute):
            assert node.attr != "physics", f"Forbidden attribute access: {node.attr}"
