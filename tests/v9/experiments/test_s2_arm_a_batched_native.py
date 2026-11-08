"""W9 native checks: batched Arm A loss parity/speed and integer actions on all arms (--native-mlx)."""

from __future__ import annotations

import time

import mlx.core as mx  # noqa: F401  (native module: module-level MLX import)
import mlx.nn as nn
import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import adapters_mlx, arms_mlx, spec

pytestmark = pytest.mark.native_mlx


def _batch(B: int, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    L = int(spec.H_TRAIN) + 1
    return {
        spec.BATCH_OBSERVATIONS_KEY: rng.normal(size=(B, L, spec.OBS_DIM)).astype(np.float32),
        spec.BATCH_ACTIONS_KEY: np.eye(spec.ACTION_DIM, dtype=np.float32)[rng.integers(0, spec.ACTION_DIM, size=(B, L))],
        spec.BATCH_DTS_KEY: rng.integers(1, 4, size=(B, L)).astype(np.float32),
    }


def test_batched_arm_a_loss_and_grad_match_per_sequence_reference(monkeypatch):
    # Deterministic reparameterisation for both paths (shapes differ, so RNG draws cannot match).
    monkeypatch.setattr(mx.random, "normal", lambda shape, *a, **k: mx.zeros(shape))
    ad = adapters_mlx.make_mlx_arm("arm_a")
    ad.init(42)
    b = _batch(3)
    obs = mx.array(b[spec.BATCH_OBSERVATIONS_KEY])
    act = mx.array(b[spec.BATCH_ACTIONS_KEY])
    dts = mx.array(b[spec.BATCH_DTS_KEY])

    def ref(m):
        return mx.mean(mx.stack([arms_mlx.arm_a_loss_mlx(m, obs[i], act[i], dts[i]) for i in range(3)]))

    def bat(m):
        return arms_mlx.arm_a_loss_mlx_batched(m, obs, act, dts)

    l_ref, g_ref = nn.value_and_grad(ad.model, ref)(ad.model)
    l_bat, g_bat = nn.value_and_grad(ad.model, bat)(ad.model)
    assert abs(float(l_ref.item()) - float(l_bat.item())) <= 1e-4
    from mlx.utils import tree_flatten

    fr = dict(tree_flatten(g_ref))
    fb = dict(tree_flatten(g_bat))
    nr = float(np.sqrt(sum(float(mx.sum(v * v).item()) for v in fr.values())))
    nb = float(np.sqrt(sum(float(mx.sum(v * v).item()) for v in fb.values())))
    assert abs(nr - nb) <= 1e-3 * max(1.0, nr)


def test_arm_a_train_step_speed_close_to_other_arms():
    batch = _batch(int(spec.BATCH_SIZE))
    times = {}
    for arm_id in ("arm_a", "arm_b", "arm_c"):
        ad = adapters_mlx.make_mlx_arm(arm_id)
        ad.init(42)
        ad.train_step(batch)  # warm-up
        t0 = time.time()
        for _ in range(3):
            ad.train_step(batch)
        times[arm_id] = (time.time() - t0) / 3
    print("[W9 TRAIN STEP SECONDS]", {k: round(v, 3) for k, v in times.items()})
    assert times["arm_a"] <= 3.0 * max(times["arm_b"], times["arm_c"])


@pytest.mark.parametrize("arm_id", ["arm_a", "arm_b", "arm_c"])
def test_predict_l1_accepts_integer_actions(arm_id):
    ad = adapters_mlx.make_mlx_arm(arm_id)
    ad.init(42)
    z = ad.encode(np.zeros(spec.OBS_DIM, dtype=np.float32))
    outs = [ad.predict_l1(z, a) for a in (2, np.int64(2), np.array([2]), np.eye(spec.ACTION_DIM)[2])]
    for o in outs[1:]:
        np.testing.assert_allclose(o, outs[0], atol=1e-6)


def test_arm_a_latents_match_encode_planning_space():
    ad = adapters_mlx.make_mlx_arm("arm_a")
    ad.init(42)
    obs = np.random.default_rng(1).normal(size=(5, spec.OBS_DIM)).astype(np.float32)
    lat = ad.latents(obs)
    assert lat.shape == (5, int(spec.ARM_DIMS["arm_a"]["latent_dim"]))
    np.testing.assert_allclose(lat[2], ad.encode(obs[2]), atol=1e-5)
    # usable as a planning state
    assert ad.predict_l1(lat[0], 1).shape == lat[0].shape
