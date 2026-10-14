"""Causality, weighting, and supervision checks; no GPU training jobs."""

import mlx.core as mx
import mlx.nn as nn
import numpy as np
import pytest
from mlx.utils import tree_flatten

from ainerzero.learning.evaluation import _Summary
from ainerzero.learning.pilot_model import (
    SharedSymbolPredictor,
    observation_loss,
    sequence_loss,
    transition_observation_loss,
)
from ainerzero.runtime.observation_worker import action_comparison_plan

pytestmark = pytest.mark.native_mlx(reason="module-level real MLX import (A39)")


@pytest.fixture(autouse=True)
def cpu_only():
    previous = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(previous)


def batch():
    return {
        "symbols": mx.zeros((1, 5, 8), dtype=mx.int32),
        "visible_mask": mx.ones((1, 5, 8), dtype=mx.bool_),
        "cursor": mx.zeros((1, 5), dtype=mx.int32),
        "episode_start": mx.zeros((1, 5), dtype=mx.bool_),
        "actions": mx.zeros((1, 4), dtype=mx.int32),
    }


class Spy:
    def __init__(self):
        self.inputs = []

    def initial(self, size):
        return mx.zeros((size, 1)), mx.zeros((size, 1))

    def logits(self, h):
        return {
            "symbols": mx.broadcast_to(
                (mx.arange(256)[None, None] == h[:, :, None]) * 5.0, (h.shape[0], 8, 256)
            ),
            "visibility": mx.zeros((h.shape[0], 8)),
            "cursor": mx.zeros((h.shape[0], 8)),
        }

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        h = symbols[:, :1].astype(mx.float32)
        return {"h": h, "z": h, "mean": h, "std": mx.ones_like(h), "logits": self.logits(h)}

    def imagine(self, h, z, actions, *, key):
        self.inputs.append((np.array(h), np.array(actions), np.array(key)))
        next_h = h + actions[:, None]
        return {"h": next_h, "z": next_h, "logits": self.logits(next_h)}

    def prior_distribution(self, h):
        return mx.zeros_like(h), mx.ones_like(h)


def compute(network, data, **kwargs):
    return sequence_loss(network, data, burn_in=0, beta_kl=0.1, key=mx.random.key(71), **kwargs)


def test_changed_weight_is_normalized_and_does_not_weight_hidden_or_reconstruction():
    logits = Spy().logits(mx.zeros((1, 1)))
    before = mx.zeros((1, 8), dtype=mx.int32)
    target = before.at[:, 0].add(1)
    visible = mx.ones((1, 8), dtype=mx.bool_)
    cursor = mx.array([0])
    total, raw = observation_loss(logits, target, visible, cursor)
    weighted, unchanged_raw = transition_observation_loss(
        logits, target, visible, cursor, before, visible, 8
    )
    errors = nn.losses.cross_entropy(logits["symbols"], target)
    expected = (errors[:, 0] * 8 + errors[:, 1:].sum(axis=-1)) / 15
    np.testing.assert_allclose(np.array(weighted - total + raw), np.array(expected), rtol=1e-6)
    np.testing.assert_array_equal(np.array(raw), np.array(unchanged_raw))
    # A newly revealed byte is not a known change.
    hidden_before = mx.array(visible)
    hidden_before[:, 0] = False
    hidden_loss, _ = transition_observation_loss(
        logits, target, visible, cursor, before, hidden_before, 8
    )
    np.testing.assert_allclose(np.array(hidden_loss), np.array(total), rtol=1e-6)


def test_four_step_branch_never_receives_intermediate_observations():
    original, altered = batch(), batch()
    altered["symbols"][:, 1:4] = 123
    a, b = Spy(), Spy()
    _, first = compute(a, original, rollout_horizon=4, rollout_weight=0.5)
    _, second = compute(b, altered, rollout_horizon=4, rollout_weight=0.5)
    for left, right in zip(a.inputs[:4], b.inputs[:4], strict=True):
        for x, y in zip(left, right, strict=True):
            np.testing.assert_array_equal(x, y)
    np.testing.assert_array_equal(np.array(first["rollout_loss"]), np.array(second["rollout_loss"]))
    assert first["rollout_valid_paths"].item() == 1
    # Changing the last future action really affects the four-step prediction.
    altered = batch()
    altered["actions"][:, 3] = 1
    _, third = compute(Spy(), altered, rollout_horizon=4, rollout_weight=0.5)
    assert third["rollout_loss"].item() > first["rollout_loss"].item()


@pytest.mark.parametrize(
    "field,index",
    [("valid_mask", 0), ("valid_mask", 2), ("episode_start", 1), ("episode_start", 4)],
)
def test_four_step_loss_masks_entire_broken_path(field, index):
    data = batch()
    data["valid_mask"] = mx.ones((1, 4), dtype=mx.bool_)
    data[field][:, index] = field == "episode_start"
    _, metrics = compute(Spy(), data, rollout_horizon=4, rollout_weight=0.5)
    assert metrics["rollout_valid_paths"].item() == 0
    assert metrics["rollout_loss"].item() == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"changed_weight": float("nan")},
        {"changed_weight": 17},
        {"rollout_horizon": 2},
        {"rollout_horizon": True},
        {"rollout_weight": -1},
        {"rollout_weight": 0.5},
    ],
)
def test_invalid_objectives_rejected(kwargs):
    with pytest.raises(ValueError):
        compute(Spy(), batch(), **kwargs)


def test_default_and_explicit_control_preserve_same_keys_values_and_gradients():
    model = SharedSymbolPredictor(key=mx.random.key(2))
    a, b = (
        compute(model, batch()),
        compute(model, batch(), changed_weight=1, rollout_horizon=1, rollout_weight=0),
    )
    np.testing.assert_array_equal(np.array(a[0]), np.array(b[0]))
    assert set(a[1]) == set(b[1])
    (_, metrics), grads = nn.value_and_grad(model, sequence_loss)(
        model,
        batch(),
        burn_in=0,
        beta_kl=0.1,
        key=mx.random.key(8),
        changed_weight=8,
        rollout_horizon=4,
        rollout_weight=0.5,
    )
    assert all(np.isfinite(np.array(v)).all() for _, v in tree_flatten(grads))
    assert metrics["rollout_valid_paths"].item() == 1


def test_weighted_group_aggregation_and_empty_groups():
    summary = _Summary()
    for count, changed_count in ((2, 1), (8, 2)):
        summary.add(
            {
                "count": count,
                "nll": 3.0,
                "accuracy": 0.6,
                "changed_count": changed_count,
                "changed_nll": 4.0,
                "changed_accuracy": 0.25,
                "unchanged_count": count - changed_count,
                "unchanged_nll": 2.0,
                "unchanged_accuracy": 0.75,
            }
        )
    result = summary.result()
    assert result["changed_count"] == 3 and result["unchanged_count"] == 7
    assert result["changed_accuracy"] == 0.25 and result["unchanged_accuracy"] == 0.75
    assert _Summary().result()["changed_accuracy"] is None


def test_comparison_is_fixed_and_cannot_expand_model_or_claim_equal_compute():
    plan = action_comparison_plan()
    assert plan["parameter_ceiling"] == 393232
    assert len(plan["arms"]) == 3 and plan["action_updates_max"] == 100
    assert plan["arms"][0]["changed_weight"] == 1
    assert plan["arms"][1]["changed_weight"] == plan["arms"][2]["changed_weight"] == 8
    assert plan["automatic_promotion"] is False
    assert "not_equal_compute" in plan["comparison"]


def test_explicit_single_arm_retry_does_not_silently_repeat_finished_arms():
    plan = action_comparison_plan("changed_four_step")
    assert [row["name"] for row in plan["arms"]] == ["changed_four_step"]
    assert plan["action_updates_max"] == 100
    assert plan["minimum_update_reservation_seconds"] == 5.0
    with pytest.raises(ValueError, match="unknown"):
        action_comparison_plan("bigger_model")
