"""Unit and contract tests for GridLab-S2 data module (r2).

Pure CPU, NumPy / standard library only. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §2.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import site
import subprocess
import sys

import pytest

from ainerzero.v9.experiments.s2.world import make_layout
from ainerzero.v9.experiments.s2.data import (
    run_episode,
    generate_partition,
    assert_partitions_disjoint,
    sample_k,
    assert_k_distribution,
    chi_square_k_distribution,
    K_CHI2_THRESHOLD,
    MIN_NON_BFS_RATIO,
)


def test_episode_determinism():
    """Same layout and episode seed produces bitwise identical exploration trajectory."""
    layout = make_layout(101)
    ep1 = run_episode(layout, random.Random(42), max_steps=60)
    ep2 = run_episode(layout, random.Random(42), max_steps=60)
    ep3 = run_episode(layout, random.Random(43), max_steps=60)

    assert ep1["total_env_steps"] == ep2["total_env_steps"] == 60
    assert ep1["steps"] == ep2["steps"]
    assert ep1["steps"] != ep3["steps"]


def test_regular_dt_k1():
    """When force_k1 is True, all step dt values equal 1."""
    layout = make_layout(202)
    ep = run_episode(layout, random.Random(999), max_steps=50, force_k1=True)
    assert ep["total_env_steps"] == 50
    for s in ep["steps"]:
        assert s["dt"] == 1
        assert s["student_obs"]["dt"] == 1


def test_non_bfs_segment_ratio_floor():
    """r2: non-BFS env-step share must be ≥ 0.5 on a full-length episode."""
    layout = make_layout(303)
    ep = run_episode(layout, random.Random(11), max_steps=240)
    ratio = ep["segment_stats"]["non_bfs_ratio"]
    assert ratio >= MIN_NON_BFS_RATIO, f"non_bfs_ratio {ratio} < {MIN_NON_BFS_RATIO}"
    assert ep["segment_stats"]["non_bfs_steps"] + ep["segment_stats"]["bfs_steps"] == 240


def test_k_distribution_chi_square():
    """Empirical k ~ {1:0.5,2:0.3,3:0.2}; χ² gate frozen (catches force_k≡3)."""
    rng = random.Random(20261106)
    counts = {1: 0, 2: 0, 3: 0}
    n = 6000
    for _ in range(n):
        counts[sample_k(rng)] += 1
    chi2 = assert_k_distribution(counts, threshold=K_CHI2_THRESHOLD, min_n=5000)
    assert chi2 <= K_CHI2_THRESHOLD

    # Sanity: forced k≡3 must exceed the frozen threshold.
    forced = {1: 0, 2: 0, 3: n}
    assert chi_square_k_distribution(forced) > K_CHI2_THRESHOLD
    with pytest.raises(AssertionError, match="χ²"):
        assert_k_distribution(forced, threshold=K_CHI2_THRESHOLD, min_n=5000)

    # Also check episode-emitted histogram aggregates similarly.
    layout = make_layout(404)
    hist = {1: 0, 2: 0, 3: 0}
    steps_drawn = 0
    seed = 0
    while steps_drawn < 5000:
        ep = run_episode(layout, random.Random(9000 + seed), max_steps=240)
        seed += 1
        for k, c in ep["k_histogram"].items():
            hist[int(k)] += int(c)
            steps_drawn += int(c)
    assert_k_distribution(hist, threshold=K_CHI2_THRESHOLD, min_n=5000)


def test_generate_partition_isolation_and_disjointness(tmp_path: Path):
    """Only requested partition directory is created; disjoint check validates namespaces and layouts."""
    out_dir = tmp_path / "dataset"
    out_dir.mkdir(parents=True, exist_ok=True)

    dev_manifest = generate_partition(
        partition="dev",
        n_worlds=1,
        episodes_per_world=2,
        output_root=out_dir,
        seed_namespace="s2-dev-test-ns",
        allowed_root=tmp_path,
        max_steps_per_episode=40,
    )

    assert (out_dir / "dev").is_dir()
    assert not (out_dir / "train").exists()
    assert not (out_dir / "final").exists()

    assert (out_dir / "dev" / "manifest.json").is_file()
    assert (out_dir / "dev" / "SHA256SUMS.txt").is_file()
    assert (out_dir / "dev" / "regular_dt_k1").is_dir()
    assert (out_dir / "dev" / "world_0000" / "goal_episode_specs.json").is_file()

    specs = json.loads((out_dir / "dev" / "world_0000" / "goal_episode_specs.json").read_text())
    assert len(specs) == 6
    assert all("perturb" in s for s in specs)
    assert any(s["perturb"] is True for s in specs)
    assert sum(1 for s in specs if s["perturb"]) == 2

    assert dev_manifest["segment_stats"]["non_bfs_ratio"] >= MIN_NON_BFS_RATIO

    train_manifest = generate_partition(
        partition="train",
        n_worlds=1,
        episodes_per_world=1,
        output_root=out_dir,
        seed_namespace="s2-train-test-ns",
        allowed_root=tmp_path,
        max_steps_per_episode=40,
    )

    assert_partitions_disjoint([dev_manifest, train_manifest])

    with pytest.raises(ValueError, match="Shared seed namespace"):
        assert_partitions_disjoint([dev_manifest, dev_manifest])

    forged_manifest = {
        "partition": "final",
        "seed_namespace": "forged-ns",
        "layout_digests": [dev_manifest["layout_digests"][0]],
    }
    with pytest.raises(ValueError, match="Partitions overlap"):
        assert_partitions_disjoint([dev_manifest, forged_manifest])


def test_pure_cpu_no_mlx_import_data():
    """Isolated subprocess check: importing s2 data does NOT import MLX."""
    user_site = site.getusersitepackages()
    code = (
        "import sys, site; "
        f"site.addsitedir({repr(user_site)}); "
        "sys.path.insert(0, 'src'); sys.path.insert(0, '.'); "
        "from ainerzero.v9.experiments.s2 import data; "
        "assert 'mlx' not in sys.modules; "
        "assert 'mlx.core' not in sys.modules; "
        "print('OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Import check failed: {proc.stderr}"
    assert "OK" in proc.stdout
