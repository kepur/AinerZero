import math

import numpy as np
import pytest
from test_sequences import make_episode

from ainerzero.core.experience import DatasetPartition, OriginKind, TrainingPolicy
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.baselines import NoActionBaseline, copy_probabilities, symbol_metrics


def test_copy_uses_only_visible_current_bytes_with_exact_smoothing():
    symbols = np.arange(8, dtype=np.int32)
    visible = np.array([True, False] * 4)
    result = copy_probabilities(symbols, visible)
    assert result.shape == (8, 256)
    np.testing.assert_allclose(result.sum(axis=-1), 1.0)
    for cell in range(8):
        if visible[cell]:
            assert result[cell, cell] == pytest.approx(0.99 + 0.01 / 256)
            assert result[cell, 255] == pytest.approx(0.01 / 256)
        else:
            np.testing.assert_array_equal(result[cell], np.full(256, 1 / 256))
    hidden_changed = symbols.copy()
    hidden_changed[~visible] = 255
    np.testing.assert_array_equal(result, copy_probabilities(hidden_changed, visible))


def test_baselines_support_leading_batch_and_time_dimensions():
    episode, _, policy = make_episode()
    symbols = np.zeros((2, 3, 8), dtype=np.int32)
    mask = np.ones_like(symbols, dtype=bool)
    assert copy_probabilities(symbols, mask).shape == (2, 3, 8, 256)
    baseline = NoActionBaseline(policy).fit([episode])
    for horizon in (1, 4):
        probabilities = baseline.predict(symbols, mask, horizon=horizon)
        assert probabilities.shape == (2, 3, 8, 256)
        np.testing.assert_allclose(probabilities.sum(axis=-1), 1.0)
        assert np.all(probabilities > 0)


def test_no_action_fit_matches_public_empirical_transitions_and_unseen_is_uniform():
    episode, _, policy = make_episode(steps=128)
    baseline = NoActionBaseline(policy).fit([episode])
    current = np.asarray(episode.initial.payload.symbols)
    output = baseline.predict(current, np.ones(8, dtype=bool))
    for cell in range(8):
        successors = [
            t.next_observation.payload.symbols[cell]
            for t in episode.transitions
            if t.observation.payload.symbols[cell] == current[cell]
        ]
        for byte in set(successors):
            expected = 0.99 * successors.count(byte) / len(successors) + 0.01 / 256
            assert output[cell, byte] == pytest.approx(expected)
    unseen = np.array(
        [
            next(
                byte
                for byte in range(256)
                if all(t.observation.payload.symbols[cell] != byte for t in episode.transitions)
            )
            for cell in range(8)
        ]
    )
    np.testing.assert_allclose(
        baseline.predict(unseen, np.ones(8, dtype=bool)), np.full((8, 256), 1 / 256)
    )


def test_action_labels_do_not_influence_no_action_fit():
    episode, _, policy = make_episode()
    revised = episode.model_dump(mode="json")
    for transition in revised["transitions"]:
        transition["action_request"]["action"] = 3
        transition["action_result"]["action"] = 3
    relabeled = EpisodeTrajectory.model_validate(revised)
    symbols = np.asarray(episode.initial.payload.symbols)
    mask = np.ones(8, dtype=bool)
    a = NoActionBaseline(policy).fit([episode])
    b = NoActionBaseline(policy).fit([relabeled])
    np.testing.assert_array_equal(a.predict(symbols, mask), b.predict(symbols, mask))


def test_four_step_prediction_propagates_frozen_one_step_kernel_without_future():
    episode, _, policy = make_episode(steps=128)
    baseline = NoActionBaseline(policy).fit([episode])
    symbols = np.asarray(episode.initial.payload.symbols)
    visible = np.ones(8, dtype=bool)
    kernel = baseline.predict(
        np.repeat(np.arange(256)[:, None], 8, axis=1), np.ones((256, 8), dtype=bool)
    ).transpose(1, 0, 2)
    expected = np.stack(
        [np.linalg.matrix_power(kernel[cell], 4)[symbols[cell]] for cell in range(8)]
    )
    before = baseline.predict(symbols, visible)
    np.testing.assert_allclose(
        baseline.predict(symbols, visible, horizon=4), expected, rtol=1e-12, atol=1e-12
    )
    np.testing.assert_array_equal(before, baseline.predict(symbols, visible))
    invisible = np.zeros(8, dtype=bool)
    for horizon in (1, 4):
        np.testing.assert_array_equal(
            baseline.predict(symbols, invisible, horizon=horizon), np.full((8, 256), 1 / 256)
        )


@pytest.mark.parametrize("partition", [p for p in DatasetPartition if p != DatasetPartition.TRAIN])
@pytest.mark.parametrize("steps", [0, 2])
def test_baseline_cannot_fit_evaluation_or_quarantine(partition, steps):
    episode, _, policy = make_episode(steps=steps, partition=partition)
    with pytest.raises(ValueError, match="train partition"):
        NoActionBaseline(policy).fit([episode])


def test_fit_checks_actor_whitelist_and_revalidates_copied_evidence():
    episode, _, policy = make_episode()
    with pytest.raises(ValueError, match="not authorized"):
        NoActionBaseline(TrainingPolicy(allowed_actors=())).fit([episode])
    transition = episode.transitions[-1]
    poisoned = transition.model_copy(
        update={
            "next_observation": transition.next_observation.model_copy(
                update={"origin": OriginKind.TEACHER_CLAIM}
            )
        }
    )
    broken = episode.model_copy(update={"transitions": (*episode.transitions[:-1], poisoned)})
    with pytest.raises(ValueError, match="observed evidence"):
        NoActionBaseline(policy).fit([broken])


def test_failed_fit_does_not_modify_previous_model_and_successful_fit_replaces_counts():
    episode, _, policy = make_episode()
    development, _, _ = make_episode(partition=DatasetPartition.DEVELOPMENT)
    symbols = np.asarray(episode.initial.payload.symbols)
    visible = np.ones(8, dtype=bool)
    baseline = NoActionBaseline(policy).fit([episode])
    original = baseline.predict(symbols, visible)
    with pytest.raises(ValueError, match="train partition"):
        baseline.fit([episode, development])
    np.testing.assert_array_equal(original, baseline.predict(symbols, visible))
    baseline.fit([episode])
    np.testing.assert_array_equal(original, baseline.predict(symbols, visible))
    with pytest.raises(ValueError, match="duplicate episode"):
        baseline.fit([episode, episode])


def test_empty_fit_and_unfitted_prediction_rejected():
    episode, _, policy = make_episode(steps=0)
    baseline = NoActionBaseline(policy)
    for episodes in ([], [episode]):
        with pytest.raises(ValueError, match="visible observations"):
            baseline.fit(episodes)
    with pytest.raises(ValueError, match="must be fitted"):
        baseline.predict(np.zeros(8, dtype=np.int32), np.ones(8, dtype=bool))


@pytest.mark.parametrize("horizon", [0, -1, True, 1.5])
def test_bad_horizons_rejected(horizon):
    episode, _, policy = make_episode()
    baseline = NoActionBaseline(policy).fit([episode])
    with pytest.raises(ValueError, match="horizon"):
        baseline.predict(np.zeros(8, dtype=np.int32), np.ones(8, dtype=bool), horizon=horizon)


def test_metrics_exact_natural_log_loss_accuracy_and_changed_subset():
    previous = np.zeros(8, dtype=np.int32)
    target = np.array([0, 1, 1, 0, 0, 0, 0, 0])
    mask = np.array([True, True, False, False, False, False, False, False])
    probabilities = copy_probabilities(previous, np.ones(8, dtype=bool))
    metrics = symbol_metrics(probabilities, target, mask, previous, np.ones(8, dtype=bool))
    stay = -math.log(0.99 + 0.01 / 256)
    changed = -math.log(0.01 / 256)
    assert metrics == {
        "nll": pytest.approx((stay + changed) / 2),
        "count": 2,
        "accuracy": 0.5,
        "changed_nll": pytest.approx(changed),
        "changed_count": 1,
        "changed_accuracy": 0.0,
        "unchanged_count": 1,
        "unchanged_nll": pytest.approx(stay),
        "unchanged_accuracy": 1.0,
    }


def test_empty_target_and_changed_masks_are_unavailable_instead_of_zero_error():
    symbols = np.zeros(8, dtype=np.int32)
    visible = np.ones(8, dtype=bool)
    invisible = np.zeros(8, dtype=bool)
    probabilities = copy_probabilities(symbols, visible)
    empty = symbol_metrics(probabilities, symbols, invisible, symbols, visible)
    assert empty == {
        "nll": None,
        "count": 0,
        "accuracy": None,
        "changed_nll": None,
        "changed_count": 0,
        "changed_accuracy": None,
        "unchanged_count": 0,
        "unchanged_nll": None,
        "unchanged_accuracy": None,
    }
    steady = symbol_metrics(probabilities, symbols, visible, symbols, visible)
    assert steady["changed_nll"] is None and steady["changed_count"] == 0
    unknown_past = symbol_metrics(probabilities, symbols, visible)
    assert unknown_past["changed_count"] is None and unknown_past["changed_nll"] is None
    assert unknown_past["unchanged_count"] is None
    assert unknown_past["changed_accuracy"] is None
    targets = np.ones(8, dtype=np.int32)
    no_previous_visible = symbol_metrics(probabilities, targets, visible, symbols, invisible)
    assert no_previous_visible["changed_count"] == 0


@pytest.mark.parametrize("corruption", ["zero", "nan", "inf", "negative", "sum", "shape"])
def test_metrics_reject_invalid_probability_distributions(corruption):
    symbols = np.zeros(8, dtype=np.int32)
    visible = np.ones(8, dtype=bool)
    probabilities = np.full((8, 256), 1 / 256)
    if corruption == "shape":
        probabilities = probabilities[:, :-1]
    else:
        probabilities[0, 0] = {
            "zero": 0.0,
            "nan": np.nan,
            "inf": np.inf,
            "negative": -0.1,
            "sum": 0.5,
        }[corruption]
    with pytest.raises(ValueError, match="probabilities"):
        symbol_metrics(probabilities, symbols, visible)


@pytest.mark.parametrize(
    "symbols,mask",
    [
        (np.zeros(7, dtype=int), np.ones(7, dtype=bool)),
        (np.zeros(8, dtype=float), np.ones(8, dtype=bool)),
        (np.zeros(8, dtype=bool), np.ones(8, dtype=bool)),
        (np.full(8, -1), np.ones(8, dtype=bool)),
        (np.full(8, 256), np.ones(8, dtype=bool)),
        (np.zeros(8, dtype=int), np.ones(8, dtype=int)),
        (np.zeros(8, dtype=int), np.ones((1, 8), dtype=bool)),
    ],
)
def test_baseline_inputs_require_byte_symbols_and_matching_boolean_masks(symbols, mask):
    with pytest.raises(ValueError):
        copy_probabilities(symbols, mask)


def test_metrics_require_complete_matching_previous_observation():
    symbols = np.zeros(8, dtype=np.int32)
    mask = np.ones(8, dtype=bool)
    probabilities = copy_probabilities(symbols, mask)
    with pytest.raises(ValueError, match="supplied together"):
        symbol_metrics(probabilities, symbols, mask, previous_symbols=symbols)
    with pytest.raises(ValueError, match="match the target shape"):
        symbol_metrics(
            probabilities, symbols, mask, np.zeros((1, 8), dtype=int), np.ones((1, 8), dtype=bool)
        )
