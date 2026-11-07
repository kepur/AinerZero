"""Native MLX tests for S2 model arm adapters (ainerzero.V9.P148).

NOTE: This is a NATIVE MODULE registered in tests/conftest.py under NATIVE_MODULES.
It is explicitly NOT executed during pure-CPU verification and remains reserved
for the future smoke/gpu execution stage pending user budget approval.

Verifies:
1. MLXArmAAdapter, MLXArmBAdapter, MLXArmCAdapter satisfy train_runner.ArmProtocol.
2. MLX arm adapters satisfy planning protocol with ForwardCounter accounting.
3. Arm A cost_fn evaluates observation-space cost.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest
import numpy as np
import mlx.core as mx

from ainerzero.v9.experiments.s2 import adapters_mlx, spec
from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter

pytestmark = pytest.mark.native_mlx


def test_native_adapter_train_protocol() -> None:
    """Verify adapters satisfy the ArmProtocol (init, train_step, rollout_error, save, n_params)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Batch dummy data (registered batch shape: 32 sequences x (H_train + 1) steps)
        B = spec.BATCH_SIZE
        T = spec.H_TRAIN + 1
        dummy_batch = {
            "observations": np.zeros((B, T, spec.OBS_DIM), dtype=np.float32),
            "actions": np.zeros((B, T, spec.ACTION_DIM), dtype=np.float32),
            "dts": np.ones((B, T, 1), dtype=np.float32),
        }

        for arm_id in ("arm_a", "arm_b", "arm_c"):
            adapter = adapters_mlx.make_mlx_arm(arm_id)
            adapter.init(seed=42)
            assert adapter.n_params() > 0

            # train_step
            step_res = adapter.train_step(dummy_batch)
            assert isinstance(step_res, dict)
            assert "loss" in step_res
            assert np.isfinite(step_res["loss"])

            # rollout_error
            err = adapter.rollout_error(dummy_batch, H=4)
            assert np.isfinite(err)

            # save
            save_path = tmp_path / f"{arm_id}.npz"
            sha = adapter.save(save_path)
            assert len(sha) == 64
            assert save_path.is_file()


def test_native_adapter_planning_protocol_and_counter() -> None:
    """Verify adapters satisfy planning protocol and charge ForwardCounter."""
    counter = ForwardCounter(budget=1000)

    # Arm A
    arm_a = adapters_mlx.make_mlx_arm("arm_a", counter=counter)
    assert arm_a.arm_kind == "flat"
    obs = np.zeros(spec.OBS_DIM, dtype=np.float64)
    z0 = arm_a.encode(obs)
    assert z0.shape == (spec.ARM_DIMS["arm_a"]["e1_output"],)
    assert counter.by_name.get("encode", 0) == 1

    z_next = arm_a.predict_l1(z0, np.array([0]))
    assert z_next.shape == (spec.ARM_DIMS["arm_a"]["latent_dim"],)
    assert counter.by_name.get("predict_l1", 0) == 1

    cost = arm_a.cost_fn(z_next, obs)
    assert np.isfinite(cost)
    assert counter.by_name.get("decode", 0) == 1

    # Arm C
    arm_c = adapters_mlx.make_mlx_arm("arm_c", counter=counter)
    assert arm_c.arm_kind == "hierarchical"
    z1 = arm_c.encode(obs)
    assert z1.shape == (spec.ARM_DIMS["arm_c"]["e1_output"],)
    z2 = arm_c.encode_l2(z1)
    assert z2.shape == (spec.ARM_DIMS["arm_c"]["z2_dim"],)
    assert counter.by_name.get("encode_l2", 0) == 1

    z2_next = arm_c.predict_l2(z2, np.zeros(spec.MACRO_ACTION_DIM), 1.0)
    assert z2_next.shape == (spec.ARM_DIMS["arm_c"]["z2_dim"],)
    assert counter.by_name.get("predict_l2", 0) == 1
