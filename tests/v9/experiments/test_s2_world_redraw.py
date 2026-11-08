"""W11: world redraw cap / rejection threshold come from spec (single source) at call time.

User approval 11-08 (RESEARCH_LOG R20261108-S2-redraw-30): MAX_REDRAW_RETRIES 5 -> 30,
MAX_REJECTION_RATE stays 0.30. The registered seeds need up to 20 (train) / 17 (dev)
layout draws (R20261108-S2-data-r2-failed full-seed scan).
"""

from __future__ import annotations

import random

import pytest

from ainerzero.v9.experiments.s2 import data, prereg, spec, world


def _prepare(partition: str, w_idx: int):
    """Exactly the production call in data.generate_partition (6 long pairs per world)."""
    ns = spec.SEED_NAMESPACES[partition]
    seed = data._get_derived_seed(ns, partition, "world", w_idx)
    rng = random.Random(data._get_derived_seed(ns, partition, "prep", w_idx))
    return world.prepare_world_with_long_pairs(seed, rng, n_long_pairs=world.LONG_PAIRS_PER_WORLD)


def test_spec_values_and_aliases():
    assert spec.MAX_REDRAW_RETRIES == 30
    assert spec.MAX_REJECTION_RATE == pytest.approx(0.30)
    assert world.WORLD_REDRAW_MAX == spec.MAX_REDRAW_RETRIES
    assert world.WORLD_REJECTION_RATE_THRESHOLD == spec.MAX_REJECTION_RATE
    assert world.LONG_PAIRS_PER_WORLD == 6


def test_prereg_records_the_values_the_generator_uses():
    w = prereg.build_draft()["world"]
    assert w["max_redraw_retries"] == 30
    assert w["max_rejection_rate"] == pytest.approx(0.30)


@pytest.mark.parametrize(
    "partition,w_idx,need",
    [
        ("train", 11, 8),    # the world that failed the registered run P188 at cap 5
        ("train", 173, 20),  # hardest registered train world
        ("dev", 14, 17),     # hardest registered dev world
    ],
)
def test_registered_hard_worlds_succeed_with_spec_defaults(partition, w_idx, need):
    layout, pairs, summary = _prepare(partition, w_idx)
    assert len(pairs) == world.LONG_PAIRS_PER_WORLD
    assert summary["world_redraws"] == need - 1
    assert summary["rejection_rate"] <= spec.MAX_REJECTION_RATE


def test_cap_is_read_from_spec_at_call_time(monkeypatch):
    monkeypatch.setattr(spec, "MAX_REDRAW_RETRIES", 5)
    with pytest.raises(RuntimeError, match="after 5 redraws"):
        _prepare("train", 11)


def test_threshold_is_read_from_spec_at_call_time(monkeypatch):
    assert world.world_rejection_requires_redraw(0.5) is True
    monkeypatch.setattr(spec, "MAX_REJECTION_RATE", 0.9)
    assert world.world_rejection_requires_redraw(0.5) is False
    assert world.world_rejection_requires_redraw(0.95) is True


def test_nonpositive_cap_is_refused():
    rng = random.Random(0)
    with pytest.raises(ValueError, match="max_world_redraws"):
        world.prepare_world_with_long_pairs(1, rng, max_world_redraws=0)
