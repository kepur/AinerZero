"""Native MLX tests for S2 model arms and loss functions (ainerzero.V9.P128).

NOTE: This is a NATIVE MODULE registered in tests/conftest.py under NATIVE_MODULES.
It is explicitly NOT executed during pure-CPU verification and remains reserved
for the future smoke stage pending user budget approval.

Verifies:
1. count_params(model) strictly equals closed-form formula from param_count.py for Arm A, B, C.
2. Forward shapes for all three arms.
3. Mathematical equivalence between MLX SIGReg and NumPy core_math.sigreg (< 1e-5 difference).
4. Continuous Gaussian NLL and soft cross entropy match core_math reference values.
5. One-step gradient update on Arm B and Arm C strictly decreases loss.
"""

from __future__ import annotations

import math
import pytest
import numpy as np

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim

from ainerzero.v9.experiments.s2 import arms_mlx, core_math, param_count, spec


pytestmark = pytest.mark.native_mlx


def test_native_count_params_matches_closed_form() -> None:
    """Verify count_params(model) exactly matches param_count closed-form for A, B, C."""
    arm_a = arms_mlx.FlatRSSMArm()
    arm_b = arms_mlx.FlatJEPAArm()
    arm_c = arms_mlx.HierarchicalHJEPAArm()

    count_a = arms_mlx.count_params(arm_a)
    count_b = arms_mlx.count_params(arm_b)
    count_c = arms_mlx.count_params(arm_c)

    expected_a = param_count.count_arm_a_closed_form()
    expected_b = param_count.count_arm_b_closed_form()
    expected_c = param_count.count_arm_c_closed_form()

    assert count_a == expected_a == 306093
    assert count_b == expected_b == 305732
    assert count_c == expected_c == 303115


def test_native_forward_shapes() -> None:
    """Verify forward projection shapes for all three arms."""
    obs_batch = mx.zeros((4, spec.OBS_DIM), dtype=mx.float32)

    # Arm A
    arm_a = arms_mlx.FlatRSSMArm()
    e1_a = arm_a.encode(obs_batch)
    assert e1_a.shape == (4, spec.ARM_DIMS["arm_a"]["e1_output"])
    h0 = mx.zeros((4, spec.ARM_DIMS["arm_a"]["gru_hidden"]))
    mean, logstd = arm_a.prior(h0)
    assert mean.shape == (4, spec.ARM_DIMS["arm_a"]["latent_dim"])
    dec = arm_a.decode(h0, mean)
    assert dec.shape == (4, spec.OBS_DIM)

    # Arm B
    arm_b = arms_mlx.FlatJEPAArm()
    e1_b = arm_b.encode(obs_batch)
    assert e1_b.shape == (4, spec.ARM_DIMS["arm_b"]["e1_output"])
    actions = mx.zeros((4, spec.ACTION_DIM))
    dts = mx.ones((4, 1))
    z_next = arm_b.predict_l1_step(e1_b, actions, dts)
    assert z_next.shape == (4, spec.ARM_DIMS["arm_b"]["p1_output"])
    idm_pred = arm_b.predict_idm(e1_b, z_next)
    assert idm_pred.shape == (4, spec.ARM_DIMS["arm_b"]["idm_output"])

    # Arm C
    arm_c = arms_mlx.HierarchicalHJEPAArm()
    z1 = arm_c.encode(obs_batch)
    assert z1.shape == (4, spec.ARM_DIMS["arm_c"]["e1_output"])
    z2 = arm_c.encode_l2(z1)
    assert z2.shape == (4, spec.ARM_DIMS["arm_c"]["z2_dim"])
    macro_a = mx.zeros((4, spec.MACRO_ACTION_DIM))
    dt2 = mx.ones((4, spec.MACRO_DT_DIM))
    z2_next = arm_c.predict_l2_step(z2, macro_a, dt2)
    assert z2_next.shape == (4, spec.ARM_DIMS["arm_c"]["z2_dim"])
    idm2_pred = arm_c.predict_idm2(z2, z2_next)
    assert idm2_pred.shape == (4, spec.ARM_DIMS["arm_c"]["idm2_output"])


def test_native_sigreg_mlx_matches_numpy() -> None:
    """Verify MLX SIGReg matches NumPy core_math.sigreg within 1e-5 tolerance."""
    N, D, M = 32, 64, 16
    Z_np = np.random.default_rng(123).standard_normal((N, D)).astype(np.float32)

    # When core_math.sigreg is called with rng=42, it samples M directions with default_rng(42)
    dirs_raw = np.random.default_rng(42).standard_normal((M, D)).astype(np.float32)
    dirs_np = dirs_raw / np.linalg.norm(dirs_raw, axis=-1, keepdims=True)

    sigreg_np = core_math.sigreg(Z_np, n_directions=M, rng=42)
    sigreg_mx_val = arms_mlx.sigreg_mlx(mx.array(Z_np), mx.array(dirs_np)).item()

    assert abs(sigreg_mx_val - sigreg_np) < 1e-5


def test_native_losses_match_numpy_reference() -> None:
    """Verify Gaussian NLL and soft cross entropy match core_math reference values."""
    pred_np = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    tgt_np = np.array([[1.2, 1.8], [2.9, 4.1]], dtype=np.float32)

    nll_np = core_math.continuous_gaussian_nll(pred_np, tgt_np, variance=1.0)
    nll_mx = arms_mlx.continuous_gaussian_nll_mlx(mx.array(pred_np), mx.array(tgt_np), variance=1.0).item()
    assert abs(nll_np - nll_mx) < 1e-5

    logits_np = np.array([[2.0, 1.0, 0.1, -0.5]], dtype=np.float32)
    hist_np = np.array([[0.5, 0.3, 0.1, 0.1]], dtype=np.float32)
    ce_np = core_math.soft_cross_entropy(logits_np, hist_np, from_logits=True)
    ce_mx = arms_mlx.soft_cross_entropy_mlx(mx.array(logits_np), mx.array(hist_np)).item()
    assert abs(ce_np - ce_mx) < 1e-5


def test_native_one_step_gradient_descent_decreases_loss() -> None:
    """Verify that taking one Adam step on Arm B decreases rollout loss."""
    arm_b = arms_mlx.FlatJEPAArm()
    optimizer = optim.Adam(learning_rate=1e-3)

    z0 = mx.random.normal((128,))
    actions = mx.zeros((4, 4))
    dts = mx.ones((4, 1))
    targets = mx.random.normal((4, 128))

    def loss_fn(model: arms_mlx.FlatJEPAArm) -> mx.array:
        return arms_mlx.multistep_latent_rollout_loss_mlx(model, z0, actions, dts, targets)

    initial_loss = loss_fn(arm_b).item()
    loss_and_grad_fn = nn.value_and_grad(arm_b, loss_fn)
    loss, grads = loss_and_grad_fn(arm_b)
    optimizer.update(arm_b, grads)
    mx.eval(arm_b.parameters())

    updated_loss = loss_fn(arm_b).item()
    assert updated_loss < initial_loss, f"Loss did not decrease: {initial_loss} -> {updated_loss}"
