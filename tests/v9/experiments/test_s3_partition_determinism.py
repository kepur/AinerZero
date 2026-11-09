"""Test GridLab-S3 Partition Determinism, Seed Disjointness, and Final Gate.

Requirements:
- Deterministic regeneration: same seeds yield identical episodes.
- Seed namespaces across train, dev, final, and probe are mutually disjoint.
- Final partition generation is refused by default (raises PermissionError)
  unless allow_final=True is explicitly supplied.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.data import (
    derive_seed,
    generate_episode,
    generate_partition,
)


def test_episode_generation_determinism() -> None:
    """Assert running generation twice with same seeds produces identical outputs."""
    ep1 = generate_episode(world_seed=8001, episode_seed=8002, family="F1")
    ep2 = generate_episode(world_seed=8001, episode_seed=8002, family="F1")

    assert ep1["layout_sha256"] == ep2["layout_sha256"]
    assert ep1["summary"] == ep2["summary"]
    assert len(ep1["steps"]) == len(ep2["steps"])

    for s1, s2 in zip(ep1["steps"], ep2["steps"]):
        assert s1["t"] == s2["t"]
        assert s1["action"] == s2["action"]
        assert np.array_equal(s1["obs"], s2["obs"])
        assert s1["truth"] == s2["truth"]

    assert ep1["events"] == ep2["events"]


def test_seed_namespaces_disjointness() -> None:
    """Assert seeds generated across registered namespaces do not collide."""
    namespaces = spec.REGISTERED_NAMESPACES
    n_keys = 200

    seeds_by_ns: dict[str, set[int]] = {}
    for ns in namespaces:
        seeds = {derive_seed(ns, "key", i) for i in range(n_keys)}
        assert len(seeds) == n_keys, f"Internal collisions within namespace {ns}"
        seeds_by_ns[ns] = seeds

    for i, ns1 in enumerate(namespaces):
        for j, ns2 in enumerate(namespaces):
            if i < j:
                intersection = seeds_by_ns[ns1] & seeds_by_ns[ns2]
                assert not intersection, f"Cross-namespace seed collision between {ns1} and {ns2}: {intersection}"


def test_final_partition_refusal_by_default() -> None:
    """Assert generate_partition('final') raises PermissionError without allow_final=True."""
    with pytest.raises(PermissionError, match="refused by default"):
        generate_partition("final", n_worlds=1, episodes_per_world=1, allow_final=False)

    with pytest.raises(PermissionError, match="refused by default"):
        generate_partition(spec.NAMESPACE_FINAL, n_worlds=1, episodes_per_world=1)


def test_final_gate_opens_only_with_explicit_flag(monkeypatch) -> None:
    """Exercise allow_final=True on a stand-in namespace: the real final seeds stay ungenerated."""
    monkeypatch.setattr(spec, "NAMESPACE_FINAL", "test-final-standin")

    with pytest.raises(PermissionError, match="refused by default"):
        generate_partition("final", n_worlds=1, episodes_per_world=1)

    part = generate_partition(
        "final",
        n_worlds=1,
        episodes_per_world=1,
        family="F1",
        allow_final=True,
    )
    assert part["namespace"] == "test-final-standin"
    assert part["total_episodes"] == 1


def test_artifacts_path_write_refusal() -> None:
    """Assert writing partition to artifacts/ is strictly prohibited."""
    with pytest.raises(PermissionError, match="Writing dataset to artifacts/ is strictly prohibited"):
        generate_partition(
            "train",
            n_worlds=1,
            episodes_per_world=1,
            output_path="/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s3/illegal.json",
        )
