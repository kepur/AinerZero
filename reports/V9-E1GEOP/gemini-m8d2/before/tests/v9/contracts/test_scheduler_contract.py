"""Contract: UpdateScheduler (r5 §3, §4 式 12b, §8.6 F2).

Positive: three learning-side signal sources, belief-node seeds, transitive
closure over the belief graph, full-set fallback past the frozen ``f_max``,
frozen thresholds.

Counter-examples: a world-entity/event/contact payload, a non-``bn-`` seed, a
seed outside the graph, an unknown signal kind, a dirty node missing from the
belief, an uncertainty below ``u_max`` (which must *not* seed), and mutable
thresholds.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.fakes import FakeUpdateScheduler
from ainerzero.v9.fakes.scheduler import BELIEF_NODE_PREFIX, WORLD_SIGNAL_KEYS
from ainerzero.v9.interfaces.errors import ContractViolation, SignalRejected, UnsupportedInput
from ainerzero.v9.interfaces.types import UPDATE_SIGNAL_KINDS, UpdateResult, UpdateSignal

GRAPH = {"bn-1": ["bn-2"], "bn-2": ["bn-3"], "bn-3": []}
BELIEF = {"bn-1": 0, "bn-2": 0, "bn-3": 0}


def signal(kind="observation_change", node="bn-1", tick=100, **detail) -> UpdateSignal:
    return UpdateSignal(kind=kind, node=node, source_t_ticks=tick, detail=detail)


@pytest.fixture
def scheduler() -> FakeUpdateScheduler:
    return FakeUpdateScheduler(f_max=3, u_max=0.5)


# ---- signal sources -------------------------------------------------------- #


def test_only_three_learning_side_sources_exist():
    assert UPDATE_SIGNAL_KINDS == ("observation_change", "executed_action", "belief_uncertainty")


@pytest.mark.parametrize("kind", UPDATE_SIGNAL_KINDS)
def test_registered_signal_kinds_are_accepted(scheduler, kind):
    scheduler.mark_dirty(signal(kind=kind, node="bn-1", uncertainty=0.9))
    # the seed bn-1 closes over the whole graph
    assert scheduler.dirty_set(GRAPH) == ("bn-1", "bn-2", "bn-3")


def test_unknown_signal_kind_is_refused(scheduler):
    with pytest.raises(ValueError) as caught:
        signal(kind="world_entity_state")
    assert "learning-side sources only" in str(caught.value)
    with pytest.raises(SignalRejected):  # not even a typed signal
        scheduler.mark_dirty({"kind": "observation_change"})


def test_seeds_must_be_belief_nodes(scheduler):
    with pytest.raises(SignalRejected) as caught:
        scheduler.mark_dirty(signal(node="node-7"))
    assert BELIEF_NODE_PREFIX in str(caught.value)
    with pytest.raises(ValueError):  # an empty node fails at the type level
        signal(node="")


@pytest.mark.parametrize("key", ["event_id", "world_entity_id", "contact", "truth_graph"])
def test_world_side_signal_payloads_are_refused(scheduler, key):
    assert key in WORLD_SIGNAL_KEYS
    with pytest.raises(SignalRejected) as caught:
        scheduler.mark_dirty(signal(**{key: "world-value"}))
    assert caught.value.code == "signal_rejected"


def test_observation_path_forbidden_keys_in_signals_are_refused(scheduler):
    with pytest.raises(SignalRejected):  # L1 absolute truth inside a signal
        scheduler.mark_dirty(signal(position=[0.0, 0.0]))
    with pytest.raises(SignalRejected):  # L6 randomness inside a signal
        scheduler.mark_dirty(signal(noise_seed=7))


# ---- closure --------------------------------------------------------------- #


def test_dirty_set_is_the_transitive_closure(scheduler):
    scheduler.mark_dirty(signal(node="bn-1"))
    assert scheduler.dirty_set(GRAPH) == ("bn-1", "bn-2", "bn-3")


def test_closure_handles_cycles_and_multiple_seeds(scheduler):
    cyclic = {"bn-1": ["bn-2"], "bn-2": ["bn-1", "bn-3"], "bn-3": []}
    scheduler.mark_dirty(signal(node="bn-2"))
    assert scheduler.dirty_set(cyclic) == ("bn-1", "bn-2", "bn-3")
    scheduler.mark_dirty(signal(node="bn-1"))
    scheduler.mark_dirty(signal(kind="executed_action", node="bn-3"))
    assert scheduler.dirty_set(cyclic) == ("bn-1", "bn-2", "bn-3")


def test_seeds_outside_the_belief_graph_are_refused(scheduler):
    scheduler.mark_dirty(signal(node="bn-9"))
    with pytest.raises(SignalRejected) as caught:
        scheduler.dirty_set(GRAPH)
    assert "not nodes of the belief graph" in str(caught.value)


def test_graph_argument_is_validated(scheduler):
    with pytest.raises(SignalRejected):
        scheduler.dirty_set(["bn-1", "bn-2"])
    with pytest.raises(SignalRejected):
        scheduler.dirty_set({"bn-1": "bn-2"})
    with pytest.raises(SignalRejected):
        scheduler.dirty_set({1: []})


# ---- sparse update vs full fallback (式 12b) ------------------------------- #


def test_sparse_update_touches_only_the_closure(scheduler):
    scheduler.mark_dirty(signal(node="bn-1"))
    dirty = scheduler.dirty_set(GRAPH)
    result = scheduler.update(BELIEF, dirty)
    assert isinstance(result, UpdateResult)
    assert result.mode == "sparse"
    assert result.fallback_reason is None
    assert scheduler.fallback_reason() is None
    assert dict(result.belief) == {"bn-1": 1, "bn-2": 1, "bn-3": 1}
    # seeds are consumed by one update
    assert scheduler.dirty_set(GRAPH) == ()


def test_sparse_update_leaves_untouched_nodes_untouched(scheduler):
    scheduler.mark_dirty(signal(node="bn-3"))
    result = scheduler.update(BELIEF, scheduler.dirty_set(GRAPH))
    assert result.nodes_updated == ("bn-3",)
    assert dict(result.belief) == {"bn-1": 0, "bn-2": 0, "bn-3": 1}
    assert result.expansions == 1


def test_closure_past_f_max_updates_everything_with_a_reason():
    scheduler = FakeUpdateScheduler(f_max=2, u_max=0.5)
    scheduler.mark_dirty(signal(node="bn-1"))
    full_set = scheduler.dirty_set(GRAPH)  # closure of 3 exceeds f_max=2
    assert full_set == ("bn-1", "bn-2", "bn-3")
    result = scheduler.update(BELIEF, full_set)
    assert result.mode == "full"
    assert "f_max=2" in result.fallback_reason
    assert scheduler.fallback_reason() == result.fallback_reason
    assert dict(result.belief) == {"bn-1": 1, "bn-2": 1, "bn-3": 1}


def test_thresholds_are_frozen(scheduler):
    thresholds = scheduler.thresholds()
    assert dict(thresholds) == {"f_max": 3, "u_max": 0.5}
    with pytest.raises(TypeError):
        thresholds["f_max"] = 999
    with pytest.raises(ContractViolation):  # construction guards
        FakeUpdateScheduler(f_max=0, u_max=0.5)
    with pytest.raises(ContractViolation):
        FakeUpdateScheduler(f_max=2, u_max=-1.0)
    with pytest.raises(ContractViolation):
        FakeUpdateScheduler(f_max=True, u_max=0.5)


# ---- uncertainty threshold ------------------------------------------------- #


def test_uncertainty_at_or_below_u_max_does_not_seed(scheduler):
    scheduler.mark_dirty(signal(kind="belief_uncertainty", node="bn-1", uncertainty=0.5))
    scheduler.mark_dirty(signal(kind="belief_uncertainty", node="bn-2", uncertainty=0.1))
    assert scheduler.dirty_set(GRAPH) == ()
    result = scheduler.update(BELIEF, ())
    assert dict(result.belief) == BELIEF  # nothing changed


def test_uncertainty_above_u_max_seeds(scheduler):
    scheduler.mark_dirty(signal(kind="belief_uncertainty", node="bn-1", uncertainty=0.51))
    assert scheduler.dirty_set(GRAPH) == ("bn-1", "bn-2", "bn-3")


def test_uncertainty_signal_must_carry_a_number(scheduler):
    with pytest.raises(SignalRejected):
        scheduler.mark_dirty(signal(kind="belief_uncertainty", node="bn-1"))
    with pytest.raises(SignalRejected):
        scheduler.mark_dirty(signal(kind="belief_uncertainty", node="bn-1", uncertainty="high"))


# ---- update argument guards ------------------------------------------------ #


def test_update_argument_guards(scheduler):
    scheduler.mark_dirty(signal(node="bn-9"))
    with pytest.raises(SignalRejected):
        scheduler.update(BELIEF, ("bn-9",))  # node not in the belief
    with pytest.raises(SignalRejected):
        scheduler.dirty_set(GRAPH)  # pending refusal stays refused
    with pytest.raises(UnsupportedInput):
        scheduler.update({}, ())  # empty belief
    with pytest.raises(UnsupportedInput):
        scheduler.update("not-a-mapping", ())
