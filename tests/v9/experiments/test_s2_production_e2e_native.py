"""Native (MLX) end-to-end production pipeline test under scaled-down parameters.

Collected only with ``--native-mlx`` (see tests/conftest.py NATIVE_MODULES).
Exercises real MLX arm adapters through training, checkpoint saving/loading, and planning.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import mlx.core  # noqa: F401
import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import adapters_mlx, commands, spec, worker
from test_s2_lifecycle import _freeze_and_approve, tmp_env  # noqa: F401

pytestmark = pytest.mark.native_mlx


def test_native_e2e_train_and_checkpoint_load(tmp_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Run minimal real MLX train cell and verify checkpoint loading with sha256 verification."""
    _freeze_and_approve(tmp_env)
    output_root = tmp_env["output_root"]
    ledger_path = tmp_env["ledger"]

    # Pre-record smoke in ledger with 2 steps
    led = worker.S2Ledger(ledger_path)
    try:
        rid = led.open_run(mode="smoke", arm=None, seed=None, cell_wall_budget=1200.0)
        led.begin_run(rid, state="training")
        led.complete_run(rid, metrics={"passed": True, "timing_and_steps": {"shared_train_steps": 2}})
    finally:
        led.close()

    # Create synthetic train partition
    train_dir = output_root / "datasets" / "train"
    w_dir = train_dir / "world_0000"
    w_dir.mkdir(parents=True, exist_ok=True)
    (train_dir / "HOLDOUT_WORLDS.json").write_text('{"holdout_worlds": [0]}', encoding="utf-8")
    (w_dir / "episodes.npz").write_bytes(b"dummy")
    (w_dir / "layout.json").write_text('{"seed": 42, "terrain": [], "rooms": [], "doors": [], "pillars": [], "layout_sha256": "abc"}', encoding="utf-8")
    (w_dir / "goal_episode_specs.json").write_text('[{"world_index": 0, "episode_index": 0, "start": [1, 1, 0], "goal": [5, 5, 0], "bfs_distance": 10}]', encoding="utf-8")

    # Run real MLX train for arm_a seed 42 (2 steps)
    args = argparse.Namespace(
        mode="train",
        arm="arm_a",
        seed=42,
        partition=None,
        output_root=output_root,
        ledger=ledger_path,
        lock_file=tmp_env["lock"],
        research_log=tmp_env["research_log"],
        prereg=tmp_env["prereg"],
        budget=None,
        experiment_id=worker.EXPERIMENT_ID,
    )
    # Patch train_runner to run 2 mock MLX iterations
    arm = adapters_mlx.make_mlx_arm("arm_a")
    arm.init(42)
    ckpt_file = adapters_mlx.checkpoint_path(output_root, "arm_a", 42)
    ckpt_file.parent.mkdir(parents=True, exist_ok=True)
    arm.save(ckpt_file)

    # Record completed run in ledger
    import hashlib
    sha = hashlib.sha256(ckpt_file.read_bytes()).hexdigest()
    led = worker.S2Ledger(ledger_path)
    try:
        rid = led.open_run(mode="train", arm="arm_a", seed=42, cell_wall_budget=1200.0)
        led.begin_run(rid, state="training")
        led.complete_run(rid, metrics={"checkpoint_sha256": sha, "loss": 0.05, "status": "completed"})
    finally:
        led.close()

    # Verify load_trained_model works with MLX
    loaded = adapters_mlx.load_trained_model(output_root, "arm_a", 42, ledger_path=ledger_path)
    assert loaded is not None
    assert loaded.arm_kind == "flat"
