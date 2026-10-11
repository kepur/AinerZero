import copy
import shutil
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from ainerzero.core.contracts import ActionStatus
from ainerzero.core.experience import (
    ActionRequestV2,
    ActionResultV2,
    Actor,
    ActorKind,
    DatasetPartition,
    EpisodeIdentity,
    ExperienceTransition,
    ObservationV2,
    OriginKind,
    TrainingPolicy,
)
from ainerzero.data.sequences import SequenceSampler
from ainerzero.data.trajectory import EpisodeTrajectory, save_trajectory
from ainerzero.environments.c0 import ACTION_SCHEMA_REVISION, ENVIRONMENT_REVISION, C0Environment


def make_episode(steps=32, seed=47, partition=DatasetPartition.TRAIN):
    environment = C0Environment(seed)
    snapshot = environment.snapshot()
    actor = Actor(kind=ActorKind.BASELINE, actor_id="fixture", policy_revision="v1")
    context = EpisodeIdentity(
        run_id=uuid4(),
        episode_id=uuid4(),
        partition=partition,
        environment_instance_id=environment.instance_id,
        environment_revision=ENVIRONMENT_REVISION,
        action_schema_revision=ACTION_SCHEMA_REVISION,
    )
    before = initial = ObservationV2(
        context=context, step=0, origin=OriginKind.OBSERVED, payload=environment.observe()
    )
    transitions = []
    rng = np.random.default_rng(seed + 1)
    for step in range(steps):
        request = ActionRequestV2(
            context=context, step=step, actor=actor, action=int(rng.integers(4))
        )
        after = ObservationV2(
            context=context,
            step=step + 1,
            origin=OriginKind.OBSERVED,
            payload=environment.step(request.action),
        )
        result = ActionResultV2(
            context=context,
            step=step,
            origin=OriginKind.OBSERVED,
            request_id=request.id,
            action=request.action,
            status=ActionStatus.ACCEPTED,
            observation_id=after.id,
            submitted_at=before.created_at,
            completed_at=after.created_at,
            elapsed_ns=17,
        )
        transitions.append(
            ExperienceTransition(
                observation=before,
                action_request=request,
                action_result=result,
                next_observation=after,
            )
        )
        before = after
    return (
        EpisodeTrajectory(
            initial=initial,
            transitions=tuple(transitions),
            stop_reason="episode_limit" if steps == 128 else "requested_steps",
        ),
        snapshot,
        TrainingPolicy(allowed_actors=(actor,)),
    )


def episode_arrays(episode):
    observations = [episode.initial.payload] + [
        t.next_observation.payload for t in episode.transitions
    ]
    return {
        "symbols": np.asarray([o.symbols for o in observations], dtype=np.int32),
        "visible_mask": np.asarray([o.visible_mask for o in observations], dtype=np.bool_),
        "cursor": np.asarray([o.cursor for o in observations], dtype=np.int32),
        "episode_start": np.asarray([o.episode_start for o in observations], dtype=np.bool_),
        "actions": np.asarray(
            [t.action_request.action for t in episode.transitions], dtype=np.int32
        ),
    }


def save_episode(tmp_path, **kwargs):
    episode, snapshot, policy = make_episode(**kwargs)
    return save_trajectory(tmp_path, episode, snapshot), episode, policy


def test_default_shapes_types_and_no_private_or_identifier_inputs(tmp_path, monkeypatch):
    path, _, policy = save_episode(tmp_path)
    real_open = Path.open

    def public_only_open(path, *args, **kwargs):
        assert path.name != "private.json", "sampling may never read private world state"
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", public_only_open)
    sampler = SequenceSampler([path], policy)
    batch = sampler.sample(3, np.random.default_rng(42))
    assert set(batch) == {"symbols", "visible_mask", "cursor", "episode_start", "actions"}
    assert batch["symbols"].shape == (3, 21, 8)
    assert batch["visible_mask"].shape == (3, 21, 8)
    assert batch["cursor"].shape == batch["episode_start"].shape == (3, 21)
    assert batch["actions"].shape == (3, 20)
    for key in ("symbols", "cursor", "actions"):
        assert batch[key].dtype == np.int32
    for key in ("visible_mask", "episode_start"):
        assert batch[key].dtype == np.bool_
    assert sampler.episode_count == 1
    assert sampler.window_count == 13
    assert sampler.paths == (path.resolve(),)


@pytest.mark.parametrize("burn_in,sequence_steps", [(0, 1), (4, 16), (0, 32), (31, 1)])
def test_windows_are_exact_in_episode_slices_with_aligned_next_observations(
    tmp_path, burn_in, sequence_steps
):
    left, a, policy = save_episode(tmp_path / "a", seed=47)
    right, b, _ = save_episode(tmp_path / "b", seed=48, steps=25)
    sampler = SequenceSampler([left, right], policy, burn_in=burn_in, sequence_steps=sequence_steps)
    length = burn_in + sequence_steps
    assert sampler.window_count == max(33 - length, 0) + max(26 - length, 0)
    # Reconstruct the finite reference pool from public observations, independently
    # of the sampler's indexing. Each sampled row must match one complete window.
    expected = []
    for episode in (a, b):
        arrays = episode_arrays(episode)
        for start in range(len(episode.transitions) - length + 1):
            expected.append(
                {
                    key: values[start : start + length + (key != "actions")]
                    for key, values in arrays.items()
                }
            )
    batch = sampler.sample(64, np.random.default_rng(61))
    for row in range(64):
        assert any(
            all(np.array_equal(batch[key][row], window[key]) for key in batch)
            for window in expected
        )
        assert not batch["episode_start"][row, 1:].any()


def test_caller_rng_state_restores_batches_and_batches_cannot_mutate_source(tmp_path):
    path, _, policy = save_episode(tmp_path)
    sampler = SequenceSampler([path], policy)
    rng = np.random.default_rng(51)
    state = copy.deepcopy(rng.bit_generator.state)
    expected = sampler.sample(8, rng)
    sampler.sample(3, rng)
    rng.bit_generator.state = state
    restored = sampler.sample(8, rng)
    for key in expected:
        np.testing.assert_array_equal(expected[key], restored[key])
        restored[key].fill(0)
    rng.bit_generator.state = state
    again = sampler.sample(8, rng)
    for key in expected:
        np.testing.assert_array_equal(expected[key], again[key])


def test_single_complete_window_includes_burn_in_without_padding(tmp_path):
    path, episode, policy = save_episode(tmp_path, steps=20)
    sampler = SequenceSampler([path], policy)
    assert sampler.window_count == 1
    batch = sampler.sample(2, np.random.default_rng(51))
    expected = episode_arrays(episode)
    for key in expected:
        np.testing.assert_array_equal(batch[key][0], expected[key])
        np.testing.assert_array_equal(batch[key][1], expected[key])
    assert batch["episode_start"][0, 0]


def test_short_episodes_are_counted_but_never_padded_into_windows(tmp_path):
    short, _, policy = save_episode(tmp_path / "short", steps=3)
    long, _, _ = save_episode(tmp_path / "long", steps=20)
    sampler = SequenceSampler([short, long], policy)
    assert sampler.episode_count == 2
    assert sampler.window_count == 1


@pytest.mark.parametrize("partition", [p for p in DatasetPartition if p != DatasetPartition.TRAIN])
def test_eval_and_quarantine_are_rejected_even_if_too_short_to_sample(tmp_path, partition):
    path, _, policy = save_episode(tmp_path, steps=0, partition=partition)
    with pytest.raises(ValueError, match="train partition"):
        SequenceSampler([path], policy)


def test_actor_allowlist_and_revision_enforced(tmp_path):
    path, _, policy = save_episode(tmp_path)
    with pytest.raises(ValueError, match="not authorized"):
        SequenceSampler([path], TrainingPolicy(allowed_actors=()))
    actor = policy.allowed_actors[0].model_copy(update={"policy_revision": "v2"})
    with pytest.raises(ValueError, match="not authorized"):
        SequenceSampler([path], TrainingPolicy(allowed_actors=(actor,)))


def test_duplicate_paths_and_episode_ids_are_rejected(tmp_path):
    path, _, policy = save_episode(tmp_path / "original")
    with pytest.raises(ValueError, match="duplicate trajectory paths"):
        SequenceSampler([path, path.parent / "." / path.name], policy)
    duplicate = tmp_path / "copy" / path.name
    shutil.copytree(path, duplicate)
    with pytest.raises(ValueError, match="duplicate episode IDs"):
        SequenceSampler([path, duplicate], policy)


@pytest.mark.parametrize("steps", [0, 1, 19])
def test_all_short_episodes_are_rejected(tmp_path, steps):
    path, _, policy = save_episode(tmp_path, steps=steps)
    with pytest.raises(ValueError, match="enough transitions"):
        SequenceSampler([path], policy)


@pytest.mark.parametrize(
    "field,value",
    [
        ("burn_in", -1),
        ("burn_in", True),
        ("burn_in", 1.0),
        ("sequence_steps", 0),
        ("sequence_steps", False),
    ],
)
def test_invalid_window_configuration_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        SequenceSampler([], TrainingPolicy(allowed_actors=()), **{field: value})


def test_empty_paths_rejected():
    with pytest.raises(ValueError, match="at least one"):
        SequenceSampler([], TrainingPolicy(allowed_actors=()))


@pytest.mark.parametrize("size", [0, -1, True, 1.0])
def test_invalid_batch_size_rejected(tmp_path, size):
    path, _, policy = save_episode(tmp_path)
    with pytest.raises(ValueError, match="batch_size"):
        SequenceSampler([path], policy).sample(size, np.random.default_rng(1))


def test_rng_must_be_explicit_generator(tmp_path):
    path, _, policy = save_episode(tmp_path)
    with pytest.raises(TypeError, match="Generator"):
        SequenceSampler([path], policy).sample(1, 123)
