"""Unit tests for S2 probe module & subgoal injection (pure CPU).

No MLX imports allowed in this default test suite.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import (
    fwd_counter,
    learned_planning as lp,
    planner,
    probe,
    probe_eval,
    spec,
)


def _encode_xy_into_view(x: float, y: float) -> np.ndarray:
    """Deterministic reversible base-3 encoding of coordinates into 7x7 view."""
    v = np.zeros((spec.FOV_SIZE, spec.FOV_SIZE), dtype=np.int64)
    ix, iy = int(round(x)), int(round(y))
    v[0, 0] = ix % 3
    v[0, 1] = (ix // 3) % 3
    v[0, 2] = (ix // 9) % 3
    v[0, 3] = iy % 3
    v[0, 4] = (iy // 3) % 3
    v[0, 5] = (iy // 9) % 3
    return v


def _decode_xy_from_feat(feat: np.ndarray) -> tuple[float, float]:
    """Inverse extraction of coordinates from featurized observation."""
    onehot = feat[:spec.TERRAIN_ONE_HOT_DIM].reshape(spec.FOV_SIZE, spec.FOV_SIZE, spec.NUM_TERRAIN_CLASSES)
    c0 = int(np.argmax(onehot[0, 0]))
    c1 = int(np.argmax(onehot[0, 1]))
    c2 = int(np.argmax(onehot[0, 2]))
    c3 = int(np.argmax(onehot[0, 3]))
    c4 = int(np.argmax(onehot[0, 4]))
    c5 = int(np.argmax(onehot[0, 5]))
    x = float(c0 + 3 * c1 + 9 * c2)
    y = float(c3 + 3 * c4 + 9 * c5)
    return x, y


class LinearPoseArm:
    """Linear fake arm: latent is exact [x, y]; predict_l1 simulates true grid action step."""

    def encode(self, feat: np.ndarray) -> np.ndarray:
        x, y = _decode_xy_from_feat(feat)
        return np.array([x, y], dtype=np.float64)

    def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        z_arr = np.asarray(z, dtype=np.float64)
        if z_arr.ndim == 1:
            x, y = float(z_arr[0]), float(z_arr[1])
            act = int(np.asarray(a).reshape(-1)[0])
            nx, ny = x, y
            if act == 0: ny = max(1.0, y - 1.0)
            elif act == 1: ny = min(23.0, y + 1.0)
            elif act == 2: nx = max(1.0, x - 1.0)
            elif act == 3: nx = min(23.0, x + 1.0)
            return np.array([nx, ny], dtype=np.float64)

        B = z_arr.shape[0]
        a_arr = np.asarray(a).reshape(B, -1)
        out = np.empty((B, 2), dtype=np.float64)
        for i in range(B):
            x, y = float(z_arr[i, 0]), float(z_arr[i, 1])
            act = int(a_arr[i, 0])
            nx, ny = x, y
            if act == 0: ny = max(1.0, y - 1.0)
            elif act == 1: ny = min(23.0, y + 1.0)
            elif act == 2: nx = max(1.0, x - 1.0)
            elif act == 3: nx = min(23.0, x + 1.0)
            out[i] = [nx, ny]
        return out


class RandomArm:
    """Random fake arm: latents and dynamics uncorrelated with true world pose."""

    def __init__(self, rng_seed: int = 999) -> None:
        self._rng = np.random.default_rng(rng_seed)

    def encode(self, feat: np.ndarray) -> np.ndarray:
        return self._rng.normal(0.0, 1.0, size=(2,)).astype(np.float64)

    def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        z_arr = np.asarray(z, dtype=np.float64)
        if z_arr.ndim == 1:
            return self._rng.normal(0.0, 1.0, size=(2,)).astype(np.float64)
        return self._rng.normal(0.0, 1.0, size=z_arr.shape).astype(np.float64)


def _make_synthetic_episode(start_x: int, start_y: int, n_steps: int = 120) -> dict[str, Any]:
    """Generate a valid episode payload whose observations embed pose."""
    steps: list[dict[str, Any]] = []
    x, y = float(start_x), float(start_y)
    for i in range(n_steps):
        act = i % 4
        nx, ny = x, y
        if act == 0: ny = max(1.0, y - 1.0)
        elif act == 1: ny = min(23.0, y + 1.0)
        elif act == 2: nx = max(1.0, x - 1.0)
        elif act == 3: nx = min(23.0, x + 1.0)

        obs = {
            "view": _encode_xy_into_view(x, y).tolist(),
            "heading": [1, 0, 0, 0],
            "last_action": [1, 0, 0, 0],
            "dt": 1,
        }
        steps.append({
            "student_obs": obs,
            "action": act,
            "dt": 1,
            "truth_before": {"x": float(x), "y": float(y)},
            "truth_after": {"x": float(nx), "y": float(ny)},
        })
        x, y = nx, ny
    return {"steps": steps}


def _create_synthetic_dataset(root: Path, starts_by_world: dict[int, list[tuple[int, int]]], n_steps: int = 120) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for w_idx, starts in starts_by_world.items():
        w_dir = root / f"world_{w_idx:04d}"
        w_dir.mkdir(parents=True, exist_ok=True)
        for ep_idx, (sx, sy) in enumerate(starts):
            ep_data = _make_synthetic_episode(sx, sy, n_steps=n_steps)
            (w_dir / f"episode_{ep_idx:04d}.json").write_text(json.dumps(ep_data), encoding="utf-8")
    _write_registered_holdout(root, sorted(starts_by_world))


def _write_registered_holdout(root: Path, worlds: list[int]) -> set[int]:
    """HOLDOUT_WORLDS.json per the registered rule (train_runner tamper check recomputes it)."""
    import hashlib

    from ainerzero.v9.experiments.s2 import spec

    ranked = sorted(worlds, key=lambda w: hashlib.sha256(f"s2p1-train-v1|holdout|{w}".encode()).hexdigest())
    hold = ranked[: max(1, int(round(len(worlds) * spec.TRAIN_HOLDOUT_WORLD_FRACTION)))]
    (root / "HOLDOUT_WORLDS.json").write_text(json.dumps({"holdout_worlds": hold}), encoding="utf-8")
    return set(hold)


def test_linear_vs_random_arm_probe_errors(tmp_path: Path) -> None:
    """Card W6: Linear arm k=1 error < 0.1 grid; Random arm error significantly larger (>3.0)."""
    train_dir = tmp_path / "train"
    dev_dir = tmp_path / "dev"

    train_starts = {0: [(3, 3), (12, 12), (18, 18), (5, 20)], 1: [(4, 9), (13, 6), (19, 15), (8, 17)]}
    dev_starts = {0: [(7, 7), (15, 10)]}
    _create_synthetic_dataset(train_dir, train_starts, n_steps=120)
    _create_synthetic_dataset(dev_dir, dev_starts, n_steps=120)

    # 1. Linear PoseArm on train and dev
    linear_arm = LinearPoseArm()
    trained_probe = probe_eval.fit_probe(
        linear_arm,
        train_dir,
        n_samples=200,
        seed_namespace="s2p1-train-v1|probe",
    )
    assert isinstance(trained_probe, probe.RidgeProbe)

    results_linear = probe_eval.probe_errors(
        linear_arm,
        trained_probe,
        dev_dir,
        steps=(1, 5, 10),
        start_points=(0, 30),
        max_horizon=60,
    )
    k1_error_linear = results_linear["mean_by_k"][1]
    assert k1_error_linear < 0.1, f"Expected k=1 error < 0.1 grid, got {k1_error_linear:.4f}"

    # 2. RandomArm
    random_arm = RandomArm(rng_seed=999)
    trained_random_probe = probe_eval.fit_probe(
        random_arm,
        train_dir,
        n_samples=200,
        seed_namespace="s2p1-train-v1|probe",
    )
    results_random = probe_eval.probe_errors(
        random_arm,
        trained_random_probe,
        dev_dir,
        steps=(1, 5, 10),
        start_points=(0, 30),
        max_horizon=60,
    )
    k1_error_random = results_random["mean_by_k"][1]
    assert k1_error_random > 3.0, f"Expected random arm error > 3.0 grids, got {k1_error_random:.4f}"


def test_fit_probe_strictly_excludes_holdout_worlds(tmp_path: Path) -> None:
    """W6/W6b: holdout comes from the tamper-checked HOLDOUT_WORLDS.json; poisoned holdout is never fit."""
    train_dir = tmp_path / "train_holdout_test"
    _create_synthetic_dataset(train_dir, {0: [(3, 3), (12, 12)], 1: [(6, 6), (9, 9)]}, n_steps=100)
    hold = json.loads((train_dir / "HOLDOUT_WORLDS.json").read_text())["holdout_worlds"]
    assert len(hold) == 1
    poisoned = train_dir / f"world_{hold[0]:04d}"
    for f in poisoned.glob("episode_*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for st in data["steps"]:
            st["truth_before"] = {"x": 99999.0, "y": 99999.0}
        f.write_text(json.dumps(data), encoding="utf-8")

    linear_arm = LinearPoseArm()
    test_obs = {"view": _encode_xy_into_view(5, 5).tolist(), "heading": [1, 0, 0, 0], "last_action": [1, 0, 0, 0], "dt": 1}
    for arg in (set(hold), None):
        probe = probe_eval.fit_probe(linear_arm, train_dir, holdout_worlds=arg, n_samples=100)
        pred = probe.predict(linear_arm.encode(lp.featurize_obs(test_obs, 1)))
        np.testing.assert_allclose(pred, np.array([5.0, 5.0]), atol=0.1)

    other = 1 - hold[0]
    with pytest.raises(ValueError, match="holdout_worlds argument"):
        probe_eval.fit_probe(linear_arm, train_dir, holdout_worlds={other}, n_samples=100)


def test_fit_probe_requires_holdout_file(tmp_path: Path) -> None:
    train_dir = tmp_path / "t"
    _create_synthetic_dataset(train_dir, {0: [(3, 3)], 1: [(6, 6)]}, n_steps=100)
    (train_dir / "HOLDOUT_WORLDS.json").unlink()
    with pytest.raises(FileNotFoundError):
        probe_eval.fit_probe(LinearPoseArm(), train_dir, n_samples=50)


def test_flat_layout_is_refused(tmp_path: Path) -> None:
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "episode_0000.json").write_text(json.dumps(_make_synthetic_episode(3, 3, n_steps=100)))
    arm = LinearPoseArm()
    with pytest.raises(FileNotFoundError):
        probe_eval.probe_errors(arm, None, flat)


def test_gate_step_default_is_registered() -> None:
    import inspect

    from ainerzero.v9.experiments.s2 import spec

    k_default = inspect.signature(probe_eval.prediction_noninferiority).parameters["k"].default
    assert k_default == spec.PROBE_GATE_STEP == 30


def test_prediction_noninferiority_matches_hand_calc() -> None:
    """Card W6: Assert non-inferiority gate CI upper bound matches hand-calculated values."""
    # Synthetic errors across 2 worlds, each having 3 episodes
    # Hand calculation 1: all pairwise diffs Delta = 0.4
    # e_c = 1.4, e_a = 1.0, e_b = 1.1 -> min(e_a, e_b) = 1.0 -> Delta = 0.4
    data_passing = {
        "arm_a": {
            42: {0: [1.0, 1.0, 1.0], 1: [1.0, 1.0, 1.0]},
            43: {0: [1.0, 1.0, 1.0], 1: [1.0, 1.0, 1.0]},
        },
        "arm_b": {
            42: {0: [1.1, 1.1, 1.1], 1: [1.1, 1.1, 1.1]},
            43: {0: [1.1, 1.1, 1.1], 1: [1.1, 1.1, 1.1]},
        },
        "arm_c": {
            42: {0: [1.4, 1.4, 1.4], 1: [1.4, 1.4, 1.4]},
            43: {0: [1.4, 1.4, 1.4], 1: [1.4, 1.4, 1.4]},
        },
    }
    res_passing = probe_eval.prediction_noninferiority(
        data_passing,
        k=30,
        delta_pred=1.0,
        n_boot=500,
        rng=np.random.default_rng(123),
    )
    assert res_passing["ci_upper"] == pytest.approx(0.4, abs=1e-5)
    assert res_passing["mean_diff"] == pytest.approx(0.4, abs=1e-5)
    assert res_passing["passed"] is True

    # Hand calculation 2: all pairwise diffs Delta = 1.5 (> delta_pred = 1.0)
    data_failing = {
        "arm_a": {42: {0: [1.0], 1: [1.0]}},
        "arm_b": {42: {0: [1.0], 1: [1.0]}},
        "arm_c": {42: {0: [2.5], 1: [2.5]}},
    }
    res_failing = probe_eval.prediction_noninferiority(
        data_failing,
        k=30,
        delta_pred=1.0,
        n_boot=500,
        rng=np.random.default_rng(123),
    )
    assert res_failing["ci_upper"] == pytest.approx(1.5, abs=1e-5)
    assert res_failing["passed"] is False


def test_subgoal_override_skips_upper_cem_and_records_info() -> None:
    """Card W6: When z2_subgoal_override is given, upper forwards count is 0 and info records it."""
    config = planner.HierCEMConfig(
        upper_pop=4,
        upper_iters=2,
        upper_elite_frac=0.1,
        lower_pop=4,
        lower_iters=2,
        lower_elite_frac=0.1,
        macro_horizon=3,
        s2=4,
        macro_dim=spec.MACRO_ACTION_DIM,
        action_dim=spec.ACTION_DIM,
        upper_budget=100,
        lower_budget=100,
    )
    target_subgoal = np.array([2.5, 3.5, 0.0, 1.0], dtype=np.float64)

    # Dummy functions
    def dummy_encode(x: np.ndarray) -> np.ndarray:
        return np.zeros(4, dtype=np.float64)

    def dummy_p1(z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
        return z

    def dummy_p2(z: np.ndarray, u: np.ndarray, dt: float = 1.0) -> np.ndarray:
        return z

    def dummy_enc2(z1: np.ndarray) -> np.ndarray:
        return z1

    counter = fwd_counter.ForwardCounter(budget=500)
    rng = np.random.default_rng(42)

    # 1. Batched planner with override
    res = planner.hierarchical_cem_plan(
        encode=dummy_encode,
        predict_l1=dummy_p1,
        predict_l2=dummy_p2,
        encode_l2=dummy_enc2,
        obs=np.zeros(spec.OBS_DIM),
        goal_obs=np.zeros(spec.OBS_DIM),
        config=config,
        rng=rng,
        counter=counter,
        z2_subgoal_override=target_subgoal,
    )
    assert res.info["upper_forwards"] == 0
    np.testing.assert_allclose(res.info["z2_subgoal"], target_subgoal)

    # 2. Sequential reference planner with override
    counter.reset()
    res_ref = planner.hierarchical_cem_plan_reference(
        encode=dummy_encode,
        predict_l1=dummy_p1,
        predict_l2=dummy_p2,
        encode_l2=dummy_enc2,
        obs=np.zeros(spec.OBS_DIM),
        goal_obs=np.zeros(spec.OBS_DIM),
        config=config,
        rng=rng,
        counter=counter,
        z2_subgoal_override=target_subgoal,
    )
    assert res_ref.info["upper_forwards"] == 0
    np.testing.assert_allclose(res_ref.info["z2_subgoal"], target_subgoal)


def test_make_plan_fn_subgoal_source() -> None:
    """Card W6: make_plan_fn receives subgoal_source and passes to hierarchical planner."""
    class DummyHierModel:
        counter = None

        def encode(self, obs: np.ndarray) -> np.ndarray:
            return np.zeros(4, dtype=np.float64)

        def predict_l1(self, z: np.ndarray, a: np.ndarray, dt: float = 1.0) -> np.ndarray:
            return z

        def encode_l2(self, z1: np.ndarray) -> np.ndarray:
            return z1

        def predict_l2(self, z2: np.ndarray, u: np.ndarray, dt: float = 1.0) -> np.ndarray:
            return z2

    target_subgoal = np.array([7.0, 8.0, 0.0, 0.0], dtype=np.float64)
    called_indices: list[int] = []

    def mock_subgoal_source(t: int) -> np.ndarray:
        called_indices.append(t)
        return target_subgoal

    plan_fn = lp.make_plan_fn(
        DummyHierModel(),
        "arm_c",
        spec.SMOKE_PLAN_CHOICE["hierarchical"],
        n_fwd=500,
        subgoal_source=mock_subgoal_source,
    )

    dummy_obs = {"view": np.zeros((spec.FOV_SIZE, spec.FOV_SIZE), dtype=np.int64), "heading": [1, 0, 0, 0], "last_action": [1, 0, 0, 0], "dt": 1}
    dummy_goal = {"view": np.zeros((spec.FOV_SIZE, spec.FOV_SIZE), dtype=np.int64), "heading": [1, 0, 0, 0], "last_action": [1, 0, 0, 0], "dt": 1}
    counter = fwd_counter.ForwardCounter(budget=500)
    rng = np.random.default_rng(42)

    plan_res = plan_fn(dummy_obs, dummy_goal, k=1, counter=counter, rng=rng)
    assert plan_res.info["upper_forwards"] == 0
    np.testing.assert_allclose(plan_res.info["z2_subgoal"], target_subgoal)
    assert called_indices == [0]

    # Calling for second decision gets t=1
    plan_fn(dummy_obs, dummy_goal, k=1, counter=counter, rng=rng)
    assert called_indices == [0, 1]

    # Flat arm rejects subgoal_source
    with pytest.raises(ValueError, match="only supported for hierarchical arm"):
        lp.make_plan_fn(
            DummyHierModel(),
            "arm_a",
            spec.SMOKE_PLAN_CHOICE["flat"],
            n_fwd=500,
            subgoal_source=mock_subgoal_source,
        )


def test_fail_closed_on_prohibited_attributes() -> None:
    """Card W6: Fail-closed if model exposes dev_Z or dev_XY test hooks."""
    class BadModel:
        dev_Z = np.array([1.0])

        def encode(self, obs: Any) -> np.ndarray:
            return np.zeros(4)

        def predict_l1(self, z: Any, a: Any, dt: float = 1.0) -> np.ndarray:
            return z

    with pytest.raises(ValueError, match="must not expose dev_Z or dev_XY"):
        probe_eval.fit_probe(BadModel(), "/tmp", n_samples=10)

    with pytest.raises(ValueError, match="must not expose dev_Z or dev_XY"):
        probe_eval.probe_errors(BadModel(), None, "/tmp")


def test_pure_cpu_no_mlx_in_sys_modules() -> None:
    """Card W6: Subprocess import of probe_eval must never load mlx."""
    cmd = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "import ainerzero.v9.experiments.s2.probe_eval; "
            "assert 'mlx' not in sys.modules, f'mlx leaked: {sys.modules.get(\"mlx\")}'; "
            "assert 'mlx.core' not in sys.modules, 'mlx.core leaked'; "
            "print('CPU_OK')"
        ),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert "CPU_OK" in res.stdout.strip()
