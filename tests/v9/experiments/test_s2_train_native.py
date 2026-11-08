"""Native MLX tests for S2 unified batch training and smoke self-check (ainerzero.V9.P180).

Verifies:
1. Small train partition (2 worlds x 2 episodes) loaded via train_runner.
2. 3 steps of train_step and 1 rollout_error on MLXArmA, MLXArmB, MLXArmC yield finite losses.
3. Native self-check path from measure_real_smoke passes cleanly.
4. Bad control: 3D dts (B, L, 1) raises ValueError on Arm A.
"""

from __future__ import annotations

import math
from pathlib import Path
import mlx.core as mx
import numpy as np
import pytest

pytestmark = pytest.mark.native_mlx


def test_native_train_steps_and_rollout_error_finite(tmp_path: Path) -> None:
    """Train partition batch training: 3 train_step and 1 rollout_error on A, B, C have finite losses."""
    from ainerzero.v9.experiments.s2 import adapters_mlx, data, spec, train_runner

    data_dir = tmp_path / "data"
    data.generate_partition(
        partition="train",
        n_worlds=2,
        episodes_per_world=2,
        output_root=data_dir,
        seed_namespace="test_s2_train_native_ns",
    )
    train_root = data_dir / "train"
    seqs, rel_files = train_runner.load_train_sequences(train_root)
    assert len(seqs) > 0
    assert len(rel_files) == 4

    rng = np.random.RandomState(42)
    batch = train_runner.sample_batch(seqs, rng, batch_size=8)

    for arm_id in ("arm_a", "arm_b", "arm_c"):
        arm = adapters_mlx.make_mlx_arm(arm_id)
        arm.init(seed=42)

        # 3 train steps
        for step in range(3):
            loss_dict = arm.train_step(batch)
            assert "loss" in loss_dict, f"{arm_id} missing 'loss' key: {loss_dict}"
            loss = float(loss_dict["loss"])
            assert math.isfinite(loss), f"{arm_id} step {step} loss not finite: {loss}"
            assert loss > 0.0, f"{arm_id} step {step} loss not positive: {loss}"

        # 1 rollout error evaluation
        err = float(arm.rollout_error(batch, H=8))
        assert math.isfinite(err), f"{arm_id} rollout error not finite: {err}"
        assert err >= 0.0, f"{arm_id} rollout error negative: {err}"


def test_native_smoke_self_check_path() -> None:
    """Native self-check path matching smoke.measure_real_smoke passes cleanly."""
    from ainerzero.v9.experiments.s2 import adapters_mlx, core_math, smoke, spec

    # 1. Arm instantiation and init
    arms_by_id = {
        "arm_a": adapters_mlx.make_mlx_arm("arm_a"),
        "arm_b": adapters_mlx.make_mlx_arm("arm_b"),
        "arm_c": adapters_mlx.make_mlx_arm("arm_c"),
    }
    for arm in arms_by_id.values():
        arm.init(seed=42)

    # 2. Param counts check
    param_checks = smoke.check_native_param_counts(arms_by_id)
    assert all(param_checks.values()), f"Param count mismatch: {param_checks}"

    # 3. Forward shapes
    dummy_obs = np.zeros(spec.OBS_DIM, dtype=np.float32)
    za = arms_by_id["arm_a"].encode(dummy_obs)
    zb = arms_by_id["arm_b"].encode(dummy_obs)
    zc = arms_by_id["arm_c"].encode(dummy_obs)
    z2c = arms_by_id["arm_c"].encode_l2(zc)

    assert za.shape in ((spec.ARM_DIMS["arm_a"]["e1_output"],), (spec.ARM_DIMS["arm_a"]["latent_dim"],))
    assert zb.shape == (spec.ARM_DIMS["arm_b"]["e1_output"],)
    assert zc.shape == (spec.ARM_DIMS["arm_c"]["e1_output"],)
    assert z2c.shape == (spec.ARM_DIMS["arm_c"]["z2_dim"],)

    # 4. SIGReg alignment check (<= 1e-4)
    np_rng = np.random.RandomState(42)
    Z_test = np_rng.randn(32, 16).astype(np.float32)
    sigreg_np = core_math.compute_sigreg_numpy(Z_test)
    sigreg_mlx = smoke.mlx_sigreg_alignment(Z_test)
    diff = abs(sigreg_np - sigreg_mlx)
    assert diff <= 1e-4, f"SIGReg MLX vs NumPy alignment mismatch: {sigreg_np:.6f} vs {sigreg_mlx:.6f} (diff={diff})"

    # 5. Timing dummy batch executes on all arms
    dummy_batch = smoke.make_smoke_timing_batch(batch_size=8, seed=42)
    for arm_id, arm in arms_by_id.items():
        res = arm.train_step(dummy_batch)
        assert math.isfinite(float(res["loss"])), f"{arm_id} dummy train_step loss not finite"


def test_native_bad_control_dts_3d_fails_arm_a() -> None:
    """Bad control: 3D dts array of shape (B, L, 1) raises ValueError on Arm A."""
    from ainerzero.v9.experiments.s2 import adapters_mlx, train_runner

    arm_a = adapters_mlx.make_mlx_arm("arm_a")
    arm_a.init(seed=42)

    batch = train_runner.make_dummy_batch(batch_size=4, seq_len=17, seed=42)
    # Mutate dts to (B, L, 1)
    bad_batch = {
        "observations": batch["observations"],
        "actions": batch["actions"],
        "dts": batch["dts"][:, :, None],
    }

    with pytest.raises(ValueError, match=r"1-D dts array of shape|dts \(B,T\)"):
        arm_a.train_step(bad_batch)
