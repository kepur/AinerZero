"""Contract: Fragment provenance / object / action keys (ADR-0014 r3 §3 C3).

Positive: the three ARCH §2 fields are stored, frozen and digested; old fragments
without them stay readable and queryable.

Counter-examples: a fragment missing any of the three cannot be promoted; bare
strings are not identifier sequences; world-truth identifiers are refused at
construction (§8.6); the content digest is content-sensitive.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.fakes import FakeSpatialMemory
from ainerzero.v9.interfaces.types import Fragment


def fragment(fid: str = "f-1", **overrides) -> Fragment:
    base = {
        "fragment_id": fid,
        "t_ticks": 100,
        "place": "room-a",
        "partition": "development",
        "encoder_version": "enc-v1",
        "metric": (0.0, 0.0),
        "provenance_ref": "obs/t0005.png",
        "object_keys": ("obj-a",),
        "action_keys": ("act-1",),
    }
    base.update(overrides)
    return Fragment(**base)


@pytest.fixture
def memory(geometry) -> FakeSpatialMemory:
    return FakeSpatialMemory(geometry)


def test_fragment_carries_the_arch_provenance_triple():
    stored = fragment()
    assert stored.provenance_ref == "obs/t0005.png"
    assert stored.object_keys == ("obj-a",)
    assert stored.action_keys == ("act-1",)
    assert stored.promotion_gaps() == ()


def test_old_fragment_stays_readable_and_queryable(memory):
    legacy = Fragment(
        fragment_id="f-legacy",
        t_ticks=10,
        place="room-a",
        partition="train",
        encoder_version="enc-v1",
        metric=(0.0, 0.0),
    )
    assert memory.write(legacy) == "f-legacy"
    assert memory.query_topology("room-a", encoder_version="enc-v1").entries == (legacy,)
    assert legacy.promotion_gaps() == ("provenance_ref", "object_keys", "action_keys")


@pytest.mark.parametrize(
    "overrides, gap",
    [
        ({"provenance_ref": ""}, "provenance_ref"),
        ({"object_keys": ()}, "object_keys"),
        ({"action_keys": ()}, "action_keys"),
    ],
)
def test_missing_field_is_reported_as_a_promotion_gap(overrides, gap):
    assert fragment(**overrides).promotion_gaps() == (gap,)


@pytest.mark.parametrize(
    "identifier",
    [
        "gt/world_id:7",
        "entity_id/3",
        "ground_truth/1",
        "labels/x",
        "layout_id/9",
    ],
)
def test_world_truth_identifiers_are_refused(identifier):
    with pytest.raises(ValueError) as caught:
        fragment(provenance_ref=identifier)
    assert "world-truth identifier" in str(caught.value)


def test_object_and_action_keys_reject_world_truth_ids():
    with pytest.raises(ValueError):
        fragment(object_keys=("obj-a", "instance_id/2"))
    with pytest.raises(ValueError):
        fragment(action_keys=("act-1", "gt_pose"))


def test_bare_string_is_not_an_identifier_sequence():
    with pytest.raises(ValueError) as caught:
        fragment(action_keys="act-1")
    assert "sequence" in str(caught.value)


def test_learning_side_identifiers_are_accepted():
    stored = fragment(
        provenance_ref="discovery/job-3",
        object_keys=("obj-a", "obj-b"),
        action_keys=("act-1", "act-2"),
    )
    assert stored.promotion_gaps() == ()


def test_content_digest_is_stable_and_content_sensitive():
    first = fragment()
    second = fragment()
    assert first.content_digest() == second.content_digest()
    assert len(first.content_digest()) == 64
    moved = fragment(metric=(0.5, 0.0))
    assert moved.content_digest() != first.content_digest()
    rekeyed = fragment(action_keys=("act-2",))
    assert rekeyed.content_digest() != first.content_digest()
