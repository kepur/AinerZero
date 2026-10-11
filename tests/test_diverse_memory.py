"""Synthetic public records only: no environment actions, MLX or real student."""

import builtins
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest

from ainerzero.core.contracts import ActionStatus, SymbolObservation
from ainerzero.core.experience import (
    ActionRequestV2,
    ActionResultV2,
    DatasetPartition,
    EpisodeIdentity,
    ExperienceTransition,
    ObservationV2,
    OriginKind,
)
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.environments.c0 import ACTION_SCHEMA_REVISION, ENVIRONMENT_REVISION
from ainerzero.learning.diverse_memory import (
    diverse_training_schedule,
    get_diverse_batch,
    select_diverse_memory_samples,
)
from ainerzero.learning.micro_memory import _batch_digest, _digest
from ainerzero.runtime.c0_collection import RANDOM_ACTOR

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def synthetic_episode(world, *, steps=128, partition=DatasetPartition.TRAIN, mode="normal"):
    context = EpisodeIdentity(
        run_id=UUID(int=1),
        episode_id=UUID(int=world + 100),
        partition=partition,
        environment_instance_id=UUID(int=world + 1000),
        environment_revision=ENVIRONMENT_REVISION,
        action_schema_revision=ACTION_SCHEMA_REVISION,
    )
    observations = []
    for tick in range(steps + 1):
        value = tick // 8
        if mode == "no_change":
            value = 0
        elif mode == "too_few_changes":
            value = min(value, 3)
        elif mode == "no_unchanged":
            value = tick
        payload = SymbolObservation(
            symbols=(world + 10, value, 2, 3, 4, 5, 6, 7),
            visible_mask=(True,) * 8,
            cursor=tick % 8,
            episode_start=tick == 0,
        )
        observations.append(
            ObservationV2(
                id=UUID(int=100000 + world * 1000 + tick * 3),
                created_at=NOW,
                context=context,
                step=tick,
                origin=OriginKind.OBSERVED,
                payload=payload,
            )
        )
    transitions = []
    for tick in range(steps):
        request = ActionRequestV2(
            id=UUID(int=100001 + world * 1000 + tick * 3),
            created_at=NOW,
            context=context,
            step=tick,
            action=tick % 4,
            actor=RANDOM_ACTOR,
        )
        result = ActionResultV2(
            id=UUID(int=100002 + world * 1000 + tick * 3),
            created_at=NOW,
            context=context,
            step=tick,
            origin=OriginKind.OBSERVED,
            request_id=request.id,
            action=request.action,
            status=ActionStatus.ACCEPTED,
            observation_id=observations[tick + 1].id,
            submitted_at=NOW,
            completed_at=NOW,
            elapsed_ns=1,
        )
        transitions.append(
            ExperienceTransition(
                observation=observations[tick],
                action_request=request,
                action_result=result,
                next_observation=observations[tick + 1],
            )
        )
    return EpisodeTrajectory(
        initial=observations[0],
        transitions=tuple(transitions),
        stop_reason="episode_limit" if steps == 128 else "requested_steps",
    )


@pytest.fixture(scope="module")
def episodes():
    return [synthetic_episode(world) for world in range(16)]


@pytest.fixture(scope="module")
def selection(episodes):
    return select_diverse_memory_samples(episodes)


def test_selects_exact_quotas_and_chronological_candidates(selection):
    pool, evidence = selection
    assert pool["symbols"].shape == pool["visible_mask"].shape == (256, 2, 8)
    assert pool["cursor"].shape == pool["episode_start"].shape == (256, 2)
    assert pool["actions"].shape == (256, 1)
    assert evidence["partition"] == "train"
    assert evidence["burn_in"] == 0
    assert evidence["sequence_steps"] == 1
    assert evidence["sample_count"] == 256
    assert evidence["target_visible_count"] == 2048
    assert evidence["changed_count"] == 64
    assert evidence["unchanged_count"] == 1984
    assert pool["episode_start"][:, 0].all()
    assert not pool["episode_start"][:, 1].any()
    for world in range(16):
        samples = evidence["samples"][world * 16 : (world + 1) * 16]
        assert [s["world_rank"] for s in samples] == list(range(16))
        assert [s["row"] for s in samples] == list(range(world * 16, (world + 1) * 16))
        assert [s["query_tick"] for s in samples if s["changed_count"]] == [8, 16, 24, 32]
        assert [s["query_tick"] for s in samples if not s["changed_count"]] == [
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            9,
            10,
            11,
            12,
            13,
        ]
        assert [s["world_rank"] for s in samples if s["changed_count"]] == [0, 4, 8, 12]


def test_coverage_is_measured_from_public_targets_and_controls(selection):
    pool, evidence = selection
    coverage = evidence["coverage"]
    assert coverage["world_count"] == 16
    assert coverage["unique_previous_inputs"] == coverage["unique_edge_inputs"] == 256
    assert coverage["changed_edges"] == 64
    assert coverage["unchanged_edges"] == 192
    assert coverage["old_micro_fit_edges_included"] == 16
    assert coverage["target_symbol_ids"] == sorted(set(pool["symbols"][:, 0].ravel()))
    assert sum(coverage["target_symbol_counts"].values()) == 2048
    for position, counts in enumerate(coverage["target_symbol_counts_by_position"]):
        assert sum(counts.values()) == 256
        assert len(counts) == coverage["target_unique_symbols_by_position"][position]
    assert sum(coverage["action_counts"].values()) == 256
    assert sum(coverage["cursor_counts"].values()) == 256
    assert all(row["selected_count"] == 16 for row in coverage["worlds"])


def test_hashes_match_paired_input_identity_and_pool_data(episodes, selection):
    pool, evidence = selection
    lookup = {str(ep.initial.context.episode_id): ep for ep in episodes}
    assert evidence["batch_sha256"] == _batch_digest(pool)
    assert evidence["sample_manifest_sha256"] == _digest(evidence["samples"])
    for sample in evidence["samples"]:
        edge = lookup[sample["episode_id"]].transitions[sample["transition_index"]]

        def sensor(payload):
            return {
                "symbols": list(payload.symbols),
                "visible_mask": list(payload.visible_mask),
                "cursor": payload.cursor,
            }

        previous = sensor(edge.observation.payload)
        current = sensor(edge.next_observation.payload)
        assert sample["previous_input_sha256"] == _digest(previous)
        assert sample["edge_input_sha256"] == _digest(
            {
                "previous": previous,
                "current": current,
                "action": edge.action_request.action,
            }
        )
        assert sample["public_transition_sha256"] == _digest(edge.model_dump(mode="json"))
        assert sample["public_sample_sha256"] == _batch_digest(
            {name: values[sample["row"]] for name, values in pool.items()}
        )
    json.dumps(evidence, allow_nan=False)


def test_order_independent_and_does_not_mutate_inputs(episodes, selection):
    saved = deepcopy(episodes)
    pool, evidence = select_diverse_memory_samples(list(reversed(episodes)))
    assert evidence == selection[1]
    for name in pool:
        np.testing.assert_array_equal(pool[name], selection[0][name])
        pool[name][...] = 0
    assert episodes == saved


def test_selection_uses_no_filesystem_tensor_backend_or_environment(episodes, monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("mlx"):
            raise AssertionError("selection must not initialize MLX")
        return original_import(name, *args, **kwargs)

    def deny(*args, **kwargs):
        raise AssertionError("selection must not inspect private or filesystem data")

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(Path, "open", deny)
    monkeypatch.setattr(builtins, "open", deny)
    assert select_diverse_memory_samples(episodes)[1]["sample_count"] == 256


def test_schedule_is_fixed_balanced_and_covers_all_rows(selection):
    schedule = diverse_training_schedule()
    assert schedule.shape == (200, 16)
    assert schedule.dtype == np.int32
    for update, rows in enumerate(schedule):
        assert rows.tolist() == [w * 16 + (update + w) % 16 for w in range(16)]
        assert len(set(rows.tolist())) == 16
        assert (rows % 4 == 0).sum() == 4
        assert (rows // 16).tolist() == list(range(16))
    counts = np.bincount(schedule.ravel(), minlength=256)
    assert set(counts) == {12, 13}
    assert counts.sum() == 3200
    assert selection[1]["sample_presentations"] == counts.tolist()
    assert selection[1]["schedule_sha256"] == _digest(schedule.tolist())
    assert selection[1]["schedule"] == schedule.tolist()
    schedule[...] = 0
    assert diverse_training_schedule()[0, -1] == 255


@pytest.mark.parametrize("update", [0, 1, 15, 16, 99, 199])
def test_get_batch_obeys_schedule_and_returns_independent_arrays(selection, update):
    pool, _ = selection
    batch = get_diverse_batch(pool, update)
    rows = diverse_training_schedule()[update]
    for name, values in batch.items():
        np.testing.assert_array_equal(values, pool[name][rows])
        assert not np.shares_memory(values, pool[name])
    assert ((batch["symbols"][:, 0] != batch["symbols"][:, 1]).any(axis=1)).sum() == 4


@pytest.mark.parametrize("update", [-1, 200, 1.0, True, np.int32(1), None])
def test_get_batch_rejects_out_of_contract_update_indices(selection, update):
    with pytest.raises(ValueError, match="update_index"):
        get_diverse_batch(selection[0], update)


@pytest.mark.parametrize("count", [0, 1, 15, 17])
def test_requires_exactly_sixteen_worlds(episodes, count):
    source = episodes[:count] if count <= 16 else episodes + [synthetic_episode(17)]
    with pytest.raises(ValueError, match="exactly 16"):
        select_diverse_memory_samples(source)


@pytest.mark.parametrize("partition", [DatasetPartition.DEVELOPMENT, DatasetPartition.FINAL])
def test_rejects_nontraining_data(episodes, partition):
    source = episodes.copy()
    source[0] = synthetic_episode(0, partition=partition)
    with pytest.raises(ValueError, match="partition"):
        select_diverse_memory_samples(source)


def test_rejects_duplicate_episodes_or_worlds(episodes):
    source = episodes.copy()
    source[-1] = source[0]
    with pytest.raises(ValueError, match="distinct"):
        select_diverse_memory_samples(source)


@pytest.mark.parametrize("steps", [0, 127])
def test_requires_full_128_edge_trajectories(episodes, steps):
    source = episodes.copy()
    source[0] = synthetic_episode(0, steps=steps)
    with pytest.raises(ValueError, match="128 transitions"):
        select_diverse_memory_samples(source)


@pytest.mark.parametrize(
    "mode,quota",
    [
        ("no_change", "4 distinct changed"),
        ("too_few_changes", "4 distinct changed"),
        ("no_unchanged", "12 distinct unchanged"),
    ],
)
def test_missing_coverage_fails_without_repeating_or_changing_quota(episodes, mode, quota):
    source = episodes.copy()
    source[0] = synthetic_episode(0, mode=mode)
    with pytest.raises(ValueError, match=quota):
        select_diverse_memory_samples(source)


@pytest.mark.parametrize("field", ["actor", "assistance"])
def test_validates_unselected_final_edge_provenance(episodes, field):
    source = episodes.copy()
    raw = source[0].model_dump(mode="json")
    request = raw["transitions"][-1]["action_request"]
    if field == "actor":
        request["actor"]["actor_id"] = "other"
    else:
        request["assistance"] = ["curriculum"]
    source[0] = EpisodeTrajectory.model_validate(raw)
    with pytest.raises(ValueError, match="source|authorized"):
        select_diverse_memory_samples(source)


def test_consistent_but_unapproved_actor_is_rejected(episodes):
    source = []
    for ep in episodes:
        raw = ep.model_dump(mode="json")
        for edge in raw["transitions"]:
            edge["action_request"]["actor"]["actor_id"] = "other"
        source.append(EpisodeTrajectory.model_validate(raw))
    with pytest.raises(ValueError, match="authorized"):
        select_diverse_memory_samples(source)


@pytest.mark.parametrize("field", ["symbols", "visible_mask", "cursor", "episode_start", "actions"])
def test_batch_rejects_wrong_dtype_and_shape(selection, field):
    pool = deepcopy(selection[0])
    pool[field] = pool[field].astype(np.float64)
    with pytest.raises(ValueError, match=field):
        get_diverse_batch(pool, 0)
    pool = deepcopy(selection[0])
    pool[field] = pool[field][:-1]
    with pytest.raises(ValueError, match=field):
        get_diverse_batch(pool, 0)


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("symbols", 256, "bytes"),
        ("symbols", -1, "bytes"),
        ("cursor", 8, "cursor"),
        ("actions", 4, "actions"),
        ("episode_start", False, "fresh"),
    ],
)
def test_batch_rejects_invalid_values(selection, field, value, message):
    pool = deepcopy(selection[0])
    pool[field][0, 0] = value
    with pytest.raises(ValueError, match=message):
        get_diverse_batch(pool, 0)


def test_batch_rejects_extra_or_missing_fields(selection):
    pool = deepcopy(selection[0])
    pool["truth"] = np.zeros((256, 1))
    with pytest.raises(ValueError, match="only the public"):
        get_diverse_batch(pool, 0)
    del pool["truth"]
    del pool["actions"]
    with pytest.raises(ValueError, match="only the public"):
        get_diverse_batch(pool, 0)


def test_batch_rejects_hidden_values_and_wrong_class_rank(selection):
    pool = deepcopy(selection[0])
    pool["visible_mask"][0, 0, 0] = False
    with pytest.raises(ValueError, match="hidden"):
        get_diverse_batch(pool, 0)
    pool = deepcopy(selection[0])
    pool["symbols"][0, 1] = pool["symbols"][0, 0]
    with pytest.raises(ValueError, match="changed ranks"):
        get_diverse_batch(pool, 0)


def test_batch_rejects_duplicate_previous_observations(selection):
    pool = deepcopy(selection[0])
    for name in pool:
        pool[name][16] = pool[name][0]
    with pytest.raises(ValueError, match="preceding public observations must be distinct"):
        get_diverse_batch(pool, 0)
