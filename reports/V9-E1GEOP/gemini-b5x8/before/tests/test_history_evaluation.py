"""CPU-only causal and accounting checks for frozen history diagnostics."""

from copy import deepcopy

import mlx.core as mx
import numpy as np
import pytest
from test_pilot_evaluation import baseline as baseline
from test_pilot_evaluation import episode, payloads_for

from ainerzero.learning.evaluation import evaluate_predictor

pytestmark = pytest.mark.native_mlx(reason="module-level real MLX import (A39)")


@pytest.fixture(autouse=True)
def cpu_stream():
    with mx.stream(mx.cpu):
        yield


class TracePredictor:
    """Order-sensitive toy state; the second state column only tags call ancestry."""

    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.initial_count = 0
        self.weight = np.array([1.25])

    def initial(self, size):
        tag = self.initial_count
        self.initial_count += 1
        self.events.append(dict(kind="initial", tag=tag, size=size))
        return mx.array([[0.0, float(tag)]] * size), mx.zeros((size, 1))

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        self.events.append(
            dict(
                kind="observe",
                tag=int(np.asarray(h)[0, 1]),
                state=np.asarray(h[:, :1]).tolist(),
                symbols=np.asarray(symbols).tolist(),
                visible=np.asarray(visible_mask).tolist(),
                cursor=np.asarray(cursor).tolist(),
                key=np.asarray(key).tolist(),
            )
        )
        digest = (h[:, :1] * 3 + symbols[:, :1] + cursor[:, None]) % 251
        return {"h": mx.concatenate((digest, h[:, 1:]), axis=-1), "z": symbols[:, :1]}

    def imagine(self, h, z, actions, *, key):
        size = actions.shape[0]
        self.events.append(
            dict(
                kind="imagine",
                tag=int(np.asarray(h)[0, 1]),
                state=np.asarray(h[:, :1]).tolist(),
                z=np.asarray(z).tolist(),
                actions=np.asarray(actions).tolist(),
                key=np.asarray(key).tolist(),
            )
        )
        digest = (h[:, :1] * 7 + actions[:, None] + 1) % 251
        labels = (digest[:, 0].astype(mx.int32) + z[:, 0]) % 256
        return {
            "h": mx.concatenate((digest, h[:, 1:]), axis=-1),
            "z": z,
            "logits": {
                "symbols": mx.broadcast_to(
                    (mx.arange(256)[None, None, :] == labels[:, None, None]) * 5.0,
                    (size, 8, 256),
                ),
                "cursor": (mx.arange(8)[None, :] == actions[:, None]) * 5.0,
            },
        }


def changing_episode(steps=8):
    source = episode(steps=steps)
    payloads = [
        item.model_copy(
            update={
                "symbols": tuple((tick + position * 17) % 256 for position in range(8)),
                "visible_mask": (True,) * 8,
                "cursor": (tick * 2) % 8,
            }
        )
        for tick, item in enumerate(payloads_for(source))
    ]
    return episode(steps=steps, payloads=payloads)


def without_history_groups(metric):
    return {
        key: value
        for key, value in metric.items()
        if key not in ("history_seen_at_position", "history_unseen_at_position")
    }


@pytest.mark.parametrize("action_ablation", [False, True])
def test_history_preserves_full_arm_keys_state_and_existing_metrics(baseline, action_ablation):
    data = changing_episode()
    regular, probe = TracePredictor(), TracePredictor()
    options = dict(support_ticks=2, query_stride=2, action_ablation=action_ablation)
    normal = evaluate_predictor(regular, [data], baseline, **options)
    result = evaluate_predictor(probe, [data], baseline, history_ablation=True, **options)
    assert regular.events == [event for event in probe.events if event["tag"] == 0]
    assert result["query_count"] == normal["query_count"]
    methods = ("model", "copy", "no_action") + (("action_ablation",) if action_ablation else ())
    for horizon in ("1", "4"):
        for method in methods:
            assert (
                without_history_groups(result["horizons"][horizon][method])
                == normal["horizons"][horizon][method]
            )
        if action_ablation:
            assert (
                result["horizons"][horizon]["action_probe"]
                == normal["horizons"][horizon]["action_probe"]
            )


def test_future_labels_never_enter_any_history_arm(baseline):
    data = changing_episode(steps=7)
    original = payloads_for(data)
    altered = [
        item
        if tick <= 3
        else item.model_copy(update={"symbols": tuple((x + 91) % 256 for x in item.symbols)})
        for tick, item in enumerate(original)
    ]
    models = [TracePredictor(), TracePredictor()]
    for model, sample in zip(models, [data, episode(steps=7, payloads=altered)], strict=True):
        evaluate_predictor(
            model,
            [sample],
            baseline,
            support_ticks=3,
            query_stride=128,
            history_ablation=True,
        )
    assert models[0].events == models[1].events


def test_current_frame_and_future_actions_and_keys_match_across_arms(baseline):
    model = TracePredictor()
    evaluate_predictor(
        model,
        [changing_episode(steps=8)],
        baseline,
        support_ticks=4,
        query_stride=128,
        history_ablation=True,
    )
    by_arm = [[event for event in model.events if event["tag"] == tag] for tag in range(3)]
    observations = [[item for item in arm if item["kind"] == "observe"] for arm in by_arm]
    current_frames = [arm[-1] for arm in observations]
    for field in ("symbols", "visible", "cursor", "key"):
        assert current_frames[0][field] == current_frames[1][field] == current_frames[2][field]
    assert len(observations[1]) == 1
    imagined = [[item for item in arm if item["kind"] == "imagine"] for arm in by_arm]
    for field in ("actions", "key"):
        assert (
            [item[field] for item in imagined[0][-4:]]
            == [item[field] for item in imagined[1][-4:]]
            == [item[field] for item in imagined[2][-4:]]
        )
    assert imagined[0][-5]["actions"] == imagined[2][-5]["actions"]


@pytest.mark.parametrize("tick", [0, 1])
def test_identity_shuffle_reproduces_full_history_at_short_prefixes(baseline, tick):
    result = evaluate_predictor(
        TracePredictor(),
        [changing_episode(steps=tick + 4)],
        baseline,
        support_ticks=tick,
        query_stride=128,
        history_ablation=True,
    )
    assert result["protocol"]["reordered_query_count"] == 0
    for horizon in ("1", "4"):
        value = result["horizons"][horizon]
        assert value["model"] == value["shuffled_history"]
        probe = value["history_probe"]["shuffled_history"]
        assert probe["mean_total_variation"] == 0
        assert probe["nll_delta_from_full"] == 0
        assert probe["argmax_change_count"] == 0
        if tick == 0:
            assert value["reset_history"] == value["model"]


def test_nontrivial_shuffle_is_reproducible_without_mutating_inputs_or_weights(baseline):
    data = changing_episode(steps=12)
    saved_data = deepcopy(data.model_dump(mode="json"))
    saved_baseline = baseline._transition_probabilities.copy()
    models = [TracePredictor(), TracePredictor()]
    reports = [
        evaluate_predictor(
            model,
            [data],
            baseline,
            support_ticks=8,
            query_stride=128,
            history_ablation=True,
        )
        for model in models
    ]
    assert reports[0] == reports[1]
    assert models[0].events == models[1].events
    assert reports[0]["protocol"]["reordered_query_count"] == 1
    full = [e["symbols"] for e in models[0].events if e["tag"] == 0 and e["kind"] == "observe"]
    shuffled = [e["symbols"] for e in models[0].events if e["tag"] == 2 and e["kind"] == "observe"]
    assert full[0] == shuffled[0]
    assert full[-1] == shuffled[-1]
    assert full[1:-1] != shuffled[1:-1]
    assert sorted(full[1:-1]) == sorted(shuffled[1:-1])
    assert data.model_dump(mode="json") == saved_data
    assert np.array_equal(baseline._transition_probabilities, saved_baseline)
    for model in models:
        assert np.array_equal(model.weight, np.array([1.25]))


def test_extra_initials_and_edges_are_prepaid_and_counted_exactly(baseline):
    events = []
    result = evaluate_predictor(
        TracePredictor(events),
        [changing_episode(steps=6)],
        baseline,
        support_ticks=2,
        query_stride=2,
        history_ablation=True,
        before_work=lambda count: events.append(dict(kind="reserve", count=count)),
    )
    assert result["feedback_model_transitions"] == 32
    assert result["rollout_model_transitions"] == 120
    assert result["history_model_transitions"] == 80
    assert result["logical_model_transitions"] == 232
    assert sum(event["count"] for event in events if event["kind"] == "reserve") == 232
    assert sum(event["kind"] == "initial" for event in events) == 5
    for index, event in enumerate(events):
        if event["kind"] == "initial":
            assert events[index - 1] == dict(kind="reserve", count=0 if event["tag"] == 0 else 8)
        elif event["kind"] == "imagine":
            assert events[index - 1] == dict(kind="reserve", count=8)
        elif event["kind"] == "observe":
            assert events[index - 1]["kind"] in ("initial", "imagine")
            assert events[index - 2]["kind"] == "reserve"


@pytest.mark.parametrize("reject_at", [2, 7, 9])
def test_budget_rejection_stops_before_the_next_model_call(baseline, reject_at):
    model = TracePredictor()
    reservations = []

    def reserve(count):
        reservations.append((count, len(model.events)))
        if len(reservations) == reject_at:
            raise RuntimeError("budget exhausted")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        evaluate_predictor(
            model,
            [changing_episode(steps=6)],
            baseline,
            support_ticks=2,
            query_stride=2,
            history_ablation=True,
            before_work=reserve,
        )
    assert len(model.events) == reservations[-1][1]


def test_position_support_uses_visible_original_prefix_without_future_labels(baseline):
    source = episode(steps=6)
    payloads = [
        item.model_copy(update={"symbols": (10, 20, 30, 40, 50, 60, 70, 80)})
        for item in payloads_for(source)
    ]
    # Byte 99 is visible only in a different position; byte 0 is hidden at its
    # own position. Future byte 77 must not become seen while scoring either horizon.
    payloads[0] = payloads[0].model_copy(
        update={
            "symbols": (99, 0, 30, 40, 50, 60, 70, 80),
            "visible_mask": (True, False) + (True,) * 6,
        }
    )
    target = (10, 0, 99, 77, 50, 60, 70, 80)
    for tick in (3, 6):
        payloads[tick] = payloads[tick].model_copy(update={"symbols": target})
    result = evaluate_predictor(
        TracePredictor(),
        [episode(steps=6, payloads=payloads)],
        baseline,
        support_ticks=2,
        query_stride=128,
        history_ablation=True,
    )
    for horizon in ("1", "4"):
        for name in ("model", "copy", "no_action", "reset_history", "shuffled_history"):
            metric = result["horizons"][horizon][name]
            assert metric["count"] == 8
            assert metric["seen"]["count"] == 6
            assert metric["history_seen_at_position"]["count"] == 5
            assert metric["history_unseen_at_position"]["count"] == 3
            assert metric["history_seen_at_position"]["changed_count"] == 0
            assert metric["history_unseen_at_position"]["changed_count"] == 3


def test_no_queries_leave_history_metrics_unscored_without_model_work(baseline):
    model = TracePredictor()
    result = evaluate_predictor(model, [episode(steps=1)], baseline, history_ablation=True)
    assert result["query_count"] == 0
    assert result["history_model_transitions"] == result["logical_model_transitions"] == 0
    assert model.events == []
    for horizon in ("1", "4"):
        for name in ("reset_history", "shuffled_history"):
            metric = result["horizons"][horizon][name]
            assert metric["count"] == 0
            assert metric["nll"] is None
            assert metric["history_seen_at_position"]["count"] == 0
            assert metric["history_unseen_at_position"]["nll"] is None
            probe = result["horizons"][horizon]["history_probe"][name]
            assert probe["mean_total_variation"] is None
            assert probe["nll_delta_from_full"] is None


@pytest.mark.parametrize("invalid", [0, 1, None, "true", np.bool_(True)])
def test_history_flag_requires_a_real_boolean_before_model_work(baseline, invalid):
    model = TracePredictor()
    with pytest.raises(ValueError, match="history_ablation must be boolean"):
        evaluate_predictor(model, [episode()], baseline, history_ablation=invalid)
    assert model.events == []
