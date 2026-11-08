"""W10 native checks: planning-time inference runs on the MLX device named by
spec.PLAN_INFERENCE_DEVICE (CPU stream), training keeps the default GPU device,
and CPU/GPU inference agree numerically (--native-mlx)."""

from __future__ import annotations

import mlx.core as mx
import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import adapters_mlx, spec

pytestmark = pytest.mark.native_mlx

ARMS = ("arm_a", "arm_b", "arm_c")
INFERENCE = {
    "arm_a": ("encode", "predict_l1", "latents"),
    "arm_b": ("encode", "predict_l1", "latents"),
    "arm_c": ("encode", "predict_l1", "latents", "encode_l2", "predict_l2"),
}


def _batch(B: int = 4, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    L = int(spec.H_TRAIN) + 1
    return {
        spec.BATCH_OBSERVATIONS_KEY: rng.normal(size=(B, L, spec.OBS_DIM)).astype(np.float32),
        spec.BATCH_ACTIONS_KEY: np.eye(spec.ACTION_DIM, dtype=np.float32)[rng.integers(0, spec.ACTION_DIM, size=(B, L))],
        spec.BATCH_DTS_KEY: rng.integers(1, 4, size=(B, L)).astype(np.float32),
    }


def _calls(ad, arm_id: str) -> dict:
    """Invoke every planning inference method once (single-sample and batched paths)."""
    rng = np.random.default_rng(1)
    obs = rng.normal(size=(spec.OBS_DIM,)).astype(np.float32)
    obs_seq = rng.normal(size=(5, spec.OBS_DIM)).astype(np.float32)
    out = {"encode": ad.encode(obs), "latents": ad.latents(obs_seq)}
    z = out["encode"]
    zb = np.repeat(z[None], 7, axis=0)
    out["predict_l1_single"] = ad.predict_l1(z, 2, 1.0)
    out["predict_l1_batch"] = ad.predict_l1(zb, np.arange(7) % spec.ACTION_DIM, 1.0)
    if arm_id == "arm_c":
        z2 = ad.encode_l2(z)
        out["encode_l2"] = z2
        dims = spec.ARM_DIMS["arm_c"]
        macro_dim = int(dims["p2_input"]) - int(dims["z2_dim"]) - 1  # [z2, macro_a, dt2]
        macro = np.eye(macro_dim, dtype=np.float32)[np.arange(7) % macro_dim]
        out["predict_l2_batch"] = ad.predict_l2(np.repeat(z2[None], 7, axis=0), macro, float(spec.PLAN_FUTURE_DT_L2))
    return out


def test_registered_planning_device_is_cpu():
    assert spec.PLAN_INFERENCE_DEVICE == "cpu"


@pytest.mark.parametrize("arm_id", ARMS)
def test_inference_methods_are_wrapped(arm_id):
    ad = adapters_mlx.make_mlx_arm(arm_id)
    for name in INFERENCE[arm_id]:
        assert getattr(getattr(type(ad), name), "__planning_device__", False), (arm_id, name)
    for name in ("train_step", "rollout_error", "init", "save", "load"):
        assert not getattr(getattr(type(ad), name), "__planning_device__", False), (arm_id, name)


@pytest.mark.parametrize("arm_id", ARMS)
def test_inference_runs_on_cpu_and_training_on_gpu(arm_id, monkeypatch):
    assert mx.default_device() == mx.gpu, "test assumes the process default device is the GPU"
    ad = adapters_mlx.make_mlx_arm(arm_id)
    ad.init(seed=3)

    seen: list = []
    real_to_np = adapters_mlx._to_np

    def spy_to_np(arr):
        seen.append(mx.default_device())
        return real_to_np(arr)

    monkeypatch.setattr(adapters_mlx, "_to_np", spy_to_np)
    _calls(ad, arm_id)
    assert seen and all(d == mx.cpu for d in seen), seen

    train_seen: list = []
    real_eval = mx.eval

    def spy_eval(*a, **k):
        train_seen.append(mx.default_device())
        return real_eval(*a, **k)

    monkeypatch.setattr(mx, "eval", spy_eval)
    ad.train_step(_batch())
    assert train_seen and all(d == mx.gpu for d in train_seen), train_seen
    assert mx.default_device() == mx.gpu


@pytest.mark.parametrize("arm_id", ARMS)
def test_cpu_and_gpu_inference_agree(arm_id, monkeypatch):
    ad = adapters_mlx.make_mlx_arm(arm_id)
    ad.init(seed=5)
    monkeypatch.setattr(spec, "PLAN_INFERENCE_DEVICE", "cpu")
    cpu = _calls(ad, arm_id)
    monkeypatch.setattr(spec, "PLAN_INFERENCE_DEVICE", "gpu")
    gpu = _calls(ad, arm_id)
    assert cpu.keys() == gpu.keys()
    for k in cpu:
        assert cpu[k].shape == gpu[k].shape, k
        np.testing.assert_allclose(cpu[k], gpu[k], atol=1e-4, rtol=1e-4, err_msg=f"{arm_id}.{k}")


def test_unknown_device_is_refused(monkeypatch):
    ad = adapters_mlx.make_mlx_arm("arm_b")
    ad.init(seed=0)
    monkeypatch.setattr(spec, "PLAN_INFERENCE_DEVICE", "tpu")
    with pytest.raises(ValueError, match="PLAN_INFERENCE_DEVICE"):
        ad.encode(np.zeros(spec.OBS_DIM, dtype=np.float32))


# --- W10: the registered seed determines the initial weights ---------------------------------

def _param_digest(ad) -> str:
    import hashlib

    from mlx.utils import tree_flatten

    h = hashlib.sha256()
    for k, v in sorted(tree_flatten(ad.model.parameters()), key=lambda kv: kv[0]):
        h.update(k.encode())
        h.update(np.asarray(v, dtype=np.float32).tobytes())
    return h.hexdigest()


@pytest.mark.parametrize("arm_id", ARMS)
def test_init_seed_determines_weights_in_process(arm_id):
    a = adapters_mlx.make_mlx_arm(arm_id)
    mx.random.normal((1234,))  # perturb the global key between constructions
    b = adapters_mlx.make_mlx_arm(arm_id)
    a.init(seed=7)
    mx.random.uniform(shape=(77,))
    b.init(seed=7)
    assert _param_digest(a) == _param_digest(b)
    c = adapters_mlx.make_mlx_arm(arm_id)
    c.init(seed=8)
    assert _param_digest(c) != _param_digest(a)


def test_init_seed_determines_weights_across_processes():
    import subprocess
    import sys

    code = (
        "import hashlib, os, numpy as np, mlx.core as mx\n"
        "from mlx.utils import tree_flatten\n"
        "from ainerzero.v9.experiments.s2 import adapters_mlx\n"
        "out = []\n"
        "for arm in ('arm_a', 'arm_b', 'arm_c'):\n"
        "    mx.random.seed(int.from_bytes(os.urandom(4), 'little'))  # fresh global key per arm\n"
        "    ad = adapters_mlx.make_mlx_arm(arm); ad.init(seed=11)\n"
        "    h = hashlib.sha256()\n"
        "    for k, v in sorted(tree_flatten(ad.model.parameters()), key=lambda kv: kv[0]):\n"
        "        h.update(k.encode()); h.update(np.asarray(v, dtype=np.float32).tobytes())\n"
        "    out.append(h.hexdigest())\n"
        "print(','.join(out))\n"
    )
    runs = [subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120) for _ in range(2)]
    for r in runs:
        assert r.returncode == 0, r.stderr[-2000:]
    first, second = (r.stdout.strip() for r in runs)
    assert first and first == second


@pytest.mark.parametrize("arm_id", ARMS)
def test_train_step_before_init_is_refused(arm_id):
    ad = adapters_mlx.make_mlx_arm(arm_id)
    with pytest.raises(RuntimeError, match="before init"):
        ad.train_step(_batch())
