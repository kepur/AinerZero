"""Native (MLX) test for S2 probe fitting and error evaluation on real MLX arms.

Runs only when --native-mlx is provided (Card W6: inference only, no training, <= 30s).
"""

from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import probe_eval, spec

pytestmark = pytest.mark.native_mlx


def _make_native_test_dataset(root: Path, n_worlds: int = 2, is_train: bool = False) -> None:
    """Create a minimal synthetic partition for fast MLX probe rollout smoke."""
    root.mkdir(parents=True, exist_ok=True)
    for w_idx in range(n_worlds):
        w_dir = root / f"world_{w_idx:04d}"
        w_dir.mkdir(parents=True, exist_ok=True)

        for ep_idx in range(2):
            steps: list[dict[str, Any]] = []
            for i in range(120):
                view = np.zeros((spec.FOV_SIZE, spec.FOV_SIZE), dtype=np.int64)
                obs = {
                    "view": view.tolist(),
                    "heading": [1, 0, 0, 0],
                    "last_action": [1, 0, 0, 0],
                    "dt": 1,
                }
                steps.append({
                    "student_obs": obs,
                    "action": i % spec.ACTION_DIM,
                    "dt": 1,
                    "truth_before": {"x": float(i % 10), "y": float((i // 10) % 10)},
                    "truth_after": {"x": float((i + 1) % 10), "y": float(((i + 1) // 10) % 10)},
                })
            ep_data = {"steps": steps}
            (w_dir / f"episode_{ep_idx:04d}.json").write_text(json.dumps(ep_data), encoding="utf-8")

    if is_train:
        (root / "HOLDOUT_WORLDS.json").write_text(
            json.dumps({"holdout_worlds": [0]}),
            encoding="utf-8",
        )


def test_native_three_arms_fit_and_probe_errors_smoke(tmp_path: Path) -> None:
    """Card W6: Real MLX 3 arms randomly initialized; fit_probe and probe_errors run cleanly in <= 30s."""
    from ainerzero.v9.experiments.s2 import adapters_mlx

    train_dir = tmp_path / "native_train"
    dev_dir = tmp_path / "native_dev"
    _make_native_test_dataset(train_dir, n_worlds=2, is_train=True)
    _make_native_test_dataset(dev_dir, n_worlds=1, is_train=False)

    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    mean_errors: dict[str, dict[int, float]] = {}

    for arm_id in ("arm_a", "arm_b", "arm_c"):
        t0 = time.perf_counter()
        arm = adapters_mlx.make_mlx_arm(arm_id)
        arm.init(seed=42)

        # 1. Fit probe (scaled down to 50 samples for speed)
        fitted_probe = probe_eval.fit_probe(
            arm,
            train_dir,
            n_samples=50,
            seed_namespace="s2p1-train-v1|probe",
        )
        expected_latent_dim = arm.encode(np.zeros(spec.OBS_DIM)).shape[0]
        assert fitted_probe.weights.shape == (expected_latent_dim, 2)

        # 2. Evaluate multi-step probe errors
        results = probe_eval.probe_errors(
            arm,
            fitted_probe,
            dev_dir,
            steps=(1, 5),
            start_points=(0, 30),
            max_horizon=35,
        )
        assert 1 in results["mean_by_k"]
        assert 5 in results["mean_by_k"]
        assert results["mean_by_k"][1] >= 0.0

        t1 = time.perf_counter()
        timings[arm_id] = t1 - t0
        mean_errors[arm_id] = results["mean_by_k"]

    total_time = time.perf_counter() - t_start
    print(f"\n[NATIVE MLX W6 PROBE TIMINGS] total={total_time:.3f}s per_arm={timings}")
    print(f"[NATIVE MLX W6 ERRORS] {mean_errors}")

    assert total_time <= 30.0, f"Native smoke took {total_time:.2f}s, expected <= 30s"
