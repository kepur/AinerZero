from uuid import UUID

import numpy as np
import pytest
from pydantic import ValidationError

from ainerzero.core.contracts import SymbolObservation
from ainerzero.environments.c0 import (
    ACTION_SCHEMA_REVISION,
    ENVIRONMENT_REVISION,
    MAX_EPISODE_TICKS,
    MAX_SEED,
    C0Environment,
    C0Snapshot,
)


def known_world(**overrides):
    """A test-only world with deliberately noncanonical byte encodings."""
    return C0Snapshot.model_validate(
        {
            "schema_version": 1,
            "instance_id": UUID("165ea215-3df5-4535-80c6-cb0cbe304fc6"),
            "environment_revision": ENVIRONMENT_REVISION,
            "action_schema_revision": ACTION_SCHEMA_REVISION,
            "input_cells": (0, 2, 5, 7),
            "output_cells": (1, 3, 4, 6),
            "output_sources": (7, 0, 2, 2),
            "symbol_pairs": ((91, 11), (8, 90), (0, 255), (255, 0))
            + ((42, 9), (7, 1), (8, 90), (91, 11)),
            "bits": (0,) * 8,
            "cursor": 0,
            "tick": 0,
            **overrides,
        }
    )


def rules(snapshot):
    return snapshot.model_dump(exclude={"bits", "cursor", "tick"})


def test_public_sensor_payload_has_only_symbols_mask_cursor_and_start():
    env = C0Environment(12)
    before = env.snapshot()
    observation = env.observe()
    assert isinstance(observation, SymbolObservation)
    assert set(observation.model_dump()) == {
        "symbols",
        "visible_mask",
        "cursor",
        "episode_start",
    }
    assert observation.visible_mask == (True,) * 8
    assert env.snapshot() == before
    assert env.reset(100).episode_start
    assert not env.step(3).episode_start


@pytest.mark.parametrize("cursor", range(8))
@pytest.mark.parametrize("action", range(4))
def test_action_semantics_and_instant_copying(cursor, action):
    # Exercise every initial input bit combination as well as all four actions.
    for input_pattern in range(16):
        snapshot = known_world(cursor=cursor)
        bits = [0] * 8
        for index, cell in enumerate(snapshot.input_cells):
            bits[cell] = (input_pattern >> index) & 1
        for output, source in zip(snapshot.output_cells, snapshot.output_sources, strict=True):
            bits[output] = bits[source]
        snapshot = known_world(cursor=cursor, bits=bits)
        env = C0Environment.restore(snapshot)
        observation = env.step(action)

        expected_bits = list(bits)
        expected_cursor = cursor
        if action == 0:
            expected_cursor = max(0, cursor - 1)
        elif action == 1:
            expected_cursor = min(7, cursor + 1)
        elif action == 2 and cursor in snapshot.input_cells:
            expected_bits[cursor] ^= 1
        for output, source in zip(snapshot.output_cells, snapshot.output_sources, strict=True):
            expected_bits[output] = expected_bits[source]
        assert env.snapshot().bits == tuple(expected_bits)
        assert observation.symbols == tuple(
            pair[bit] for pair, bit in zip(snapshot.symbol_pairs, expected_bits, strict=True)
        )
        assert observation.cursor == expected_cursor
        assert observation.visible_mask == (True,) * 8
        assert not observation.episode_start
        assert env.tick == 1
        assert not env.done


def test_output_copy_means_hidden_bit_copy_not_identical_bytes():
    env = C0Environment.restore(known_world(cursor=0))
    before = env.observe()
    after = env.step(2)
    assert before.symbols[0] == 91 and after.symbols[0] == 11
    assert before.symbols[3] == 255 and after.symbols[3] == 0
    assert before.symbols[0] != before.symbols[3]
    assert after.symbols[0] != after.symbols[3]


def test_generation_uses_random_positions_sources_and_unordered_local_bytes():
    worlds = [C0Environment(seed).snapshot() for seed in range(32)]
    assert len({world.input_cells for world in worlds}) > 1
    assert len({world.output_sources for world in worlds}) > 1
    assert any(left > right for world in worlds for left, right in world.symbol_pairs)
    assert any(left < right for world in worlds for left, right in world.symbol_pairs)
    for world in worlds:
        assert len(set(world.input_cells + world.output_cells)) == 8
        assert all(source in world.input_cells for source in world.output_sources)
        assert all(left != right for left, right in world.symbol_pairs)


def test_cross_cell_byte_pairs_may_repeat_and_have_zero_visible():
    env = C0Environment.restore(known_world(symbol_pairs=((0, 255),) * 8))
    assert env.observe().symbols == (0,) * 8
    assert env.observe().visible_mask == (True,) * 8


def test_reset_preserves_instance_and_rules_and_only_resamples_episode_state():
    env = C0Environment(111)
    original = env.snapshot()
    first = env.reset(3)
    for action in (2, 1, 1, 2, 0, 3):
        env.step(action)
    assert env.reset(3) == first
    assert rules(env.snapshot()) == rules(original)
    assert env.instance_id == original.instance_id
    assert env.tick == 0
    assert not env.done
    states = [env.reset(seed) for seed in range(16)]
    assert len({item.symbols for item in states}) > 1
    assert len({item.cursor for item in states}) > 1
    assert rules(env.snapshot()) == rules(original)


@pytest.mark.parametrize("seed", [0, 3, 4567, MAX_SEED])
def test_seeds_determine_instance_state_and_replay_without_global_rng(seed):
    first = C0Environment(seed)
    global_state = np.random.get_state()
    try:
        np.random.seed(77)
        second = C0Environment(seed)
    finally:
        np.random.set_state(global_state)
    assert first.snapshot() == second.snapshot()
    for reset_seed in (0, 1, MAX_SEED):
        assert first.reset(reset_seed) == second.reset(reset_seed)
        for action in (2, 1, 1, 0, 2, 3) * 6:
            assert first.step(action) == second.step(action)
            assert first.snapshot() == second.snapshot()


def test_arbitrary_snapshot_json_round_trip_and_continuation():
    original = C0Environment(8)
    for action in (0, 2, 1, 2, 3) * 7:
        original.step(action)
    saved = original.snapshot()
    restored = C0Environment.restore(C0Snapshot.model_validate_json(saved.model_dump_json()))
    assert restored.observe() == original.observe()
    assert restored.tick == 35
    for action in (0, 2, 1, 2, 3) * 7:
        assert restored.step(action) == original.step(action)
    assert restored.snapshot() == original.snapshot()
    assert saved.tick == 35  # Saved immutable values do not change with the live world.
    for seed in (99, 101):
        assert restored.reset(seed) == original.reset(seed)
        assert restored.snapshot() == original.snapshot()


def test_terminal_boundary_allows_exactly_128_actions_and_reset_restores_capacity():
    env = C0Environment(2)
    for tick in range(1, MAX_EPISODE_TICKS + 1):
        env.step(3)
        assert env.tick == tick
        assert env.done == (tick == MAX_EPISODE_TICKS)
    saved = env.snapshot()
    restored = C0Environment.restore(saved)
    assert restored.done
    assert not restored.observe().episode_start
    for candidate in (env, restored):
        for action in range(4):
            with pytest.raises(ValueError, match="episode has ended"):
                candidate.step(action)
            assert candidate.snapshot() == saved
        assert candidate.reset(55).episode_start
        assert candidate.tick == 0
        assert not candidate.done
        assert rules(candidate.snapshot()) == rules(saved)
        candidate.step(3)
        assert candidate.tick == 1


@pytest.mark.parametrize("action", [-1, 4, True, False, "2", 2.0, None, np.int64(2)])
def test_invalid_action_is_rejected_without_changing_state(action):
    env = C0Environment(1)
    saved = env.snapshot()
    with pytest.raises(ValueError, match="action must be"):
        env.step(action)
    assert env.snapshot() == saved


@pytest.mark.parametrize("seed", [-1, MAX_SEED + 1, True, False, "3", 3.0, None, np.int64(3)])
def test_invalid_seed_is_rejected_without_changing_live_state(seed):
    with pytest.raises(ValueError, match="seed must be"):
        C0Environment(seed)
    env = C0Environment(1)
    saved = env.snapshot()
    with pytest.raises(ValueError, match="seed must be"):
        env.reset(seed)
    assert env.snapshot() == saved


@pytest.mark.parametrize("field", list(C0Snapshot.model_fields))
def test_snapshot_requires_all_private_state_and_version_fields(field):
    data = known_world().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        C0Snapshot.model_validate(data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": 2},
        {"schema_version": True},
        {"environment_revision": "switchlab_c1_v1"},
        {"action_schema_revision": "switchlab_actions_v2"},
        {"input_cells": (0, 0, 5, 7)},
        {"output_cells": (1, 3, 4, 7)},
        {"input_cells": (0, 2, 5)},
        {"output_sources": (1, 0, 2, 2)},
        {"output_sources": (7, 0, 2, 8)},
        {"output_sources": (7, 0, 2, True)},
        {"symbol_pairs": ((42, 42),) * 8},
        {"symbol_pairs": ((-1, 1),) * 8},
        {"symbol_pairs": ((0, 256),) * 8},
        {"symbol_pairs": ((True, 1),) * 8},
        {"symbol_pairs": ((1, 2),) * 7},
        {"bits": (1,) + (0,) * 7},
        {"bits": (0,) * 7},
        {"bits": (False,) * 8},
        {"bits": (2,) * 8},
        {"cursor": 8},
        {"cursor": True},
        {"tick": -1},
        {"tick": 129},
        {"tick": True},
        {"tick": 1.0},
        {"unexpected_hidden_field": "discard me"},
    ],
)
def test_snapshot_rejects_incompatible_or_inconsistent_state(overrides):
    with pytest.raises(ValidationError):
        known_world(**overrides)


def test_restore_revalidates_model_copy_and_snapshots_are_frozen():
    snapshot = known_world()
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.tick = 1
    with pytest.raises(TypeError):
        snapshot.symbol_pairs[0][0] = 9
    forged = snapshot.model_copy(update={"tick": 1000})
    with pytest.raises(ValidationError):
        C0Environment.restore(forged)
    forged = snapshot.model_copy(update={"bits": (1,) + (0,) * 7})
    with pytest.raises(ValidationError, match="output bits"):
        C0Environment.restore(forged)
