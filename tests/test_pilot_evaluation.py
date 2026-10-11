from copy import deepcopy
from uuid import uuid4

import mlx.core as mx
import numpy as np
import pytest

from ainerzero.core.contracts import ActionStatus, utc_now
from ainerzero.core.experience import (
    ActionRequestV2,
    ActionResultV2,
    DatasetPartition,
    EpisodeIdentity,
    ExperienceTransition,
    ObservationV2,
    OriginKind,
    TrainingPolicy,
)
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.environments.c0 import ACTION_SCHEMA_REVISION, ENVIRONMENT_REVISION, C0Environment
from ainerzero.learning.baselines import NoActionBaseline
from ainerzero.learning.evaluation import evaluate_predictor
from ainerzero.runtime.c0_collection import RANDOM_ACTOR


def episode(*, seed=9, steps=6, partition=DatasetPartition.DEVELOPMENT, payloads=None):
    env = C0Environment(seed)
    first = env.reset(seed)
    context = EpisodeIdentity(
        run_id=uuid4(),
        episode_id=uuid4(),
        partition=partition,
        environment_instance_id=env.instance_id,
        environment_revision=ENVIRONMENT_REVISION,
        action_schema_revision=ACTION_SCHEMA_REVISION,
    )
    before = initial = ObservationV2(
        context=context,
        step=0,
        origin=OriginKind.OBSERVED,
        payload=payloads[0] if payloads else first,
    )
    transitions = []
    for tick in range(steps):
        request = ActionRequestV2(context=context, step=tick, action=tick % 4, actor=RANDOM_ACTOR)
        observed = env.step(request.action)
        after = ObservationV2(
            context=context,
            step=tick + 1,
            origin=OriginKind.OBSERVED,
            payload=payloads[tick + 1] if payloads else observed,
        )
        now = utc_now()
        result = ActionResultV2(
            context=context,
            step=tick,
            origin=OriginKind.OBSERVED,
            request_id=request.id,
            action=request.action,
            status=ActionStatus.ACCEPTED,
            observation_id=after.id,
            submitted_at=now,
            completed_at=now,
            elapsed_ns=1,
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
    return EpisodeTrajectory(
        initial=initial, transitions=tuple(transitions), stop_reason="requested_steps"
    )


class FakePredictor:
    """Small causal model with observable calls, deterministic logits, immutable weights."""

    def __init__(self, *, mixture=False, events=None):
        self.weight = np.array([1.25])
        self.mixture = mixture
        self.events = events if events is not None else []
        self.initial_count = 0

    def initial(self, size):
        self.initial_count += 1
        self.events.append(("initial", size))
        return mx.zeros((size, 1)), mx.zeros((size, 1))

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        self.events.append(("observe", np.asarray(symbols).tolist(), np.asarray(key).tolist()))
        return {"h": h, "z": symbols[:, :1].astype(mx.float32)}

    def imagine(self, h, z, actions, *, key):
        size = actions.shape[0]
        self.events.append(("imagine", np.asarray(actions).tolist(), np.asarray(key).tolist()))
        if self.mixture:
            probabilities = np.full((size, 8, 256), 0.2 / 255)
            probabilities[:4, :, 0] = 0.8
            probabilities[4:, :, :] = 0.8 / 255
            probabilities[4:, :, 0] = 0.2
            logits = mx.array(np.log(probabilities))
        else:
            labels = (z[:, 0].astype(mx.int32) + actions) % 256
            logits = mx.broadcast_to(
                (mx.arange(256)[None, None, :] == labels[:, None, None]) * 5.0,
                (size, 8, 256),
            )
        cursor = (h[:, 0].astype(mx.int32) + actions) % 8
        return {
            "h": h + actions[:, None] + 1,
            "z": z,
            "logits": {
                "symbols": logits,
                "cursor": (mx.arange(8)[None, :] == cursor[:, None]) * 5.0,
            },
        }


@pytest.fixture(autouse=True)
def cpu_stream():
    with mx.stream(mx.cpu):
        yield


@pytest.fixture
def baseline():
    return NoActionBaseline(TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))).fit(
        [episode(partition=DatasetPartition.TRAIN)]
    )


def payloads_for(data):
    return [data.initial.payload] + [item.next_observation.payload for item in data.transitions]


def test_budget_counts_feedback_and_rollouts_before_dispatch(baseline):
    events = []
    model = FakePredictor(events=events)
    result = evaluate_predictor(
        model,
        [episode()],
        baseline,
        support_ticks=2,
        query_stride=2,
        before_work=lambda n: events.append(("reserve", n)),
    )
    assert result["query_count"] == 2
    assert result["feedback_model_transitions"] == 4 * 8
    assert result["rollout_model_transitions"] == (4 + 1) * 8
    assert result["logical_model_transitions"] == 72
    assert result["horizons"]["1"]["query_count"] == 2
    assert result["horizons"]["4"]["query_count"] == 1
    assert sum(event[1] for event in events if event[0] == "reserve") == 72
    for index, event in enumerate(events):
        if event[0] == "imagine":
            assert events[index - 1] == ("reserve", 8)
    assert sum(event[0] == "observe" for event in events) == 5


def test_future_observations_only_change_labels_not_query_predictions(baseline):
    original = episode(steps=4)
    payloads = payloads_for(original)
    altered = [payloads[0]] + [
        item.model_copy(update={"symbols": tuple((value + 91) % 256 for value in item.symbols)})
        for item in payloads[1:]
    ]
    models = [FakePredictor(), FakePredictor()]
    outputs = [
        evaluate_predictor(model, [data], baseline, support_ticks=0)
        for model, data in zip(models, [original, episode(steps=4, payloads=altered)], strict=True)
    ]
    assert models[0].events == models[1].events
    assert [event[0] for event in models[0].events].count("observe") == 1
    assert outputs[0]["logical_model_transitions"] == 4 * 8


def test_mean_particle_probabilities_precedes_nll(baseline):
    data = episode(steps=1)
    payloads = [item.model_copy(update={"symbols": (0,) * 8}) for item in payloads_for(data)]
    result = evaluate_predictor(
        FakePredictor(mixture=True),
        [episode(steps=1, payloads=payloads)],
        baseline,
        support_ticks=0,
    )
    actual = result["horizons"]["1"]["model"]["nll"]
    assert actual == pytest.approx(-np.log(0.5), abs=1e-6)
    assert actual != pytest.approx((-np.log(0.8) - np.log(0.2)) / 2)


def test_action_ablation_reuses_keys_preserves_belief_and_weights(baseline):
    data = episode()
    regular = FakePredictor()
    ablated = FakePredictor()
    weights = deepcopy(ablated.weight)
    normal_result = evaluate_predictor(regular, [data], baseline, support_ticks=2, query_stride=2)
    result = evaluate_predictor(
        ablated, [data], baseline, support_ticks=2, query_stride=2, action_ablation=True
    )
    assert result["logical_model_transitions"] == 32 + 80
    assert np.array_equal(ablated.weight, weights)
    assert [event for event in regular.events if event[0] == "observe"] == [
        event for event in ablated.events if event[0] == "observe"
    ]
    for horizon in ("1", "4"):
        assert result["horizons"][horizon]["model"] == normal_result["horizons"][horizon]["model"]
        assert "changed_nll" in result["horizons"][horizon]["action_ablation"]
        probe = result["horizons"][horizon]["action_probe"]
        assert probe["interpretation"] == "diagnostic_only_no_automatic_pass"
        assert probe["symbol_change_fraction"] == 1.0
    imagined = [event for event in ablated.events if event[0] == "imagine"]
    # Two feedback edges precede the first four-step query and its perturbation.
    assert [event[2] for event in imagined[2:6]] == [event[2] for event in imagined[6:10]]


def test_aggregation_weights_cells_and_seen_history_stops_at_query(baseline):
    source = episode(steps=1)
    full = [item.model_copy(update={"symbols": (0,) * 8}) for item in payloads_for(source)]
    partial = [
        full[0],
        full[1].model_copy(
            update={"symbols": (1,) + (0,) * 7, "visible_mask": (True,) + (False,) * 7}
        ),
    ]
    first = episode(steps=1, payloads=full)
    second = episode(seed=10, steps=1, payloads=partial)
    result = evaluate_predictor(
        FakePredictor(mixture=True), [first, second], baseline, support_ticks=0
    )
    metrics = result["horizons"]["1"]["model"]
    assert metrics["count"] == 9
    assert metrics["seen"]["count"] == 8
    assert metrics["unseen"]["count"] == 1
    assert metrics["changed_count"] == 1
    expected = (8 * -np.log(0.5) - np.log(0.5 / 255)) / 9
    assert metrics["nll"] == pytest.approx(expected, abs=1e-6)


def test_no_visible_labels_is_not_a_success(baseline):
    data = episode(steps=1)
    hidden = [
        item.model_copy(update={"symbols": (0,) * 8, "visible_mask": (False,) * 8})
        for item in payloads_for(data)
    ]
    result = evaluate_predictor(
        FakePredictor(), [episode(steps=1, payloads=hidden)], baseline, support_ticks=0
    )
    for method in ("model", "copy", "no_action"):
        metric = result["horizons"]["1"][method]
        assert metric["count"] == 0
        assert metric["nll"] is metric["accuracy"] is metric["changed_nll"] is None


def test_training_support_groups_and_mass_weight_only_visible_target_cells(baseline):
    source = episode(steps=1)
    full = [item.model_copy(update={"symbols": (0,) * 8}) for item in payloads_for(source)]
    partial = [
        full[0],
        full[1].model_copy(
            update={"symbols": (1,) + (0,) * 7, "visible_mask": (True,) + (False,) * 7}
        ),
    ]
    support = np.zeros((8, 256), dtype=np.bool_)
    support[0, 0] = support[1, 1] = True
    support[2:] = True
    result = evaluate_predictor(
        FakePredictor(mixture=True),
        [episode(steps=1, payloads=full), episode(seed=10, steps=1, payloads=partial)],
        baseline,
        support_ticks=0,
        action_ablation=True,
        training_symbol_support=support,
    )
    for method in ("model", "copy", "no_action", "action_ablation"):
        metric = result["horizons"]["1"][method]
        assert metric["count"] == 9
        known = metric["training_seen_at_position"]
        unknown = metric["training_unseen_at_position"]
        assert known["count"] == 7
        assert unknown["count"] == 2
        assert known["changed_count"] == 0
        assert unknown["changed_count"] == 1
        assert metric["nll"] == pytest.approx((7 * known["nll"] + 2 * unknown["nll"]) / 9)
        assert 0 <= metric["mean_probability_on_training_support"] <= 1
    model = result["horizons"]["1"]["model"]
    assert model["training_seen_at_position"]["nll"] == pytest.approx(-np.log(0.5), abs=1e-6)
    assert model["training_unseen_at_position"]["nll"] == pytest.approx(
        (-np.log(0.5) - np.log(0.5 / 255)) / 2, abs=1e-6
    )
    assert model["mean_probability_on_training_support"] == pytest.approx(
        (6 + 0.5 + 0.5 / 255 + 0.5) / 9, abs=1e-6
    )


def test_training_support_does_not_change_predictions_or_model_inputs(baseline):
    data = episode()
    regular, stratified = FakePredictor(), FakePredictor()
    support = np.zeros((8, 256), dtype=np.bool_)
    support[:, ::2] = True
    original_support = support.copy()
    options = dict(support_ticks=2, query_stride=2, action_ablation=True)
    normal = evaluate_predictor(regular, [data], baseline, **options)
    result = evaluate_predictor(
        stratified, [data], baseline, training_symbol_support=support, **options
    )
    assert regular.events == stratified.events
    assert np.array_equal(support, original_support)
    for horizon in ("1", "4"):
        for method in ("model", "copy", "no_action", "action_ablation"):
            metric = result["horizons"][horizon][method]
            for field in (
                "training_seen_at_position",
                "training_unseen_at_position",
                "mean_probability_on_training_support",
            ):
                assert field not in normal["horizons"][horizon][method]
                metric.pop(field)
    assert result == normal


@pytest.mark.parametrize("with_queries", [False, True])
def test_training_support_empty_visible_groups_remain_unscored(baseline, with_queries):
    source = episode(steps=1)
    hidden = [
        item.model_copy(update={"visible_mask": (False,) * 8, "symbols": (0,) * 8})
        for item in payloads_for(source)
    ]
    result = evaluate_predictor(
        FakePredictor(),
        [episode(steps=1, payloads=hidden)],
        baseline,
        support_ticks=0 if with_queries else 32,
        training_symbol_support=np.ones((8, 256), dtype=np.bool_),
    )
    for method in ("model", "copy", "no_action"):
        metric = result["horizons"]["1"][method]
        assert metric["mean_probability_on_training_support"] is None
        for group in ("training_seen_at_position", "training_unseen_at_position"):
            assert metric[group]["count"] == 0
            assert metric[group]["nll"] is None


@pytest.mark.parametrize(
    "support",
    [
        np.zeros((8, 256), dtype=np.float32),
        np.zeros((8, 256), dtype=np.int32),
        np.zeros((256, 8), dtype=np.bool_),
        np.zeros((1, 8, 256), dtype=np.bool_),
        np.zeros((8, 256), dtype=np.bool_).tolist(),
    ],
)
def test_invalid_training_support_fails_before_model_work(baseline, support):
    model = FakePredictor()
    with pytest.raises(ValueError, match="training_symbol_support"):
        evaluate_predictor(
            model, [episode()], baseline, support_ticks=0, training_symbol_support=support
        )
    assert model.events == []


@pytest.mark.parametrize("partition", ["train", "final", "quarantine"])
def test_non_development_rejected_before_model_work(baseline, partition):
    model = FakePredictor()
    with pytest.raises(ValueError, match="only development"):
        evaluate_predictor(model, [episode(partition=partition)], baseline, support_ticks=0)
    assert model.events == []


def test_revalidates_tampered_nested_evidence_and_rejects_duplicates(baseline):
    data = episode()
    transition = data.transitions[0]
    bad = transition.model_copy(
        update={
            "action_result": transition.action_result.model_copy(
                update={"origin": OriginKind.IMAGINED}
            )
        }
    )
    with pytest.raises(ValueError, match="observed evidence"):
        evaluate_predictor(
            FakePredictor(),
            [data.model_copy(update={"transitions": (bad, *data.transitions[1:])})],
            baseline,
        )
    with pytest.raises(ValueError, match="distinct"):
        evaluate_predictor(FakePredictor(), [data, data], baseline)


def test_budget_rejection_precedes_model_initialization(baseline):
    model = FakePredictor()

    def exhausted(_):
        raise RuntimeError("budget exhausted")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        evaluate_predictor(model, [episode()], baseline, support_ticks=0, before_work=exhausted)
    assert model.events == []


def test_empty_queries_and_determinism(baseline):
    data = episode(steps=1)
    model = FakePredictor()
    empty = evaluate_predictor(model, [data], baseline)
    assert empty["query_count"] == empty["logical_model_transitions"] == 0
    assert empty["horizons"]["1"]["model"]["nll"] is None
    assert model.events == []
    first = evaluate_predictor(FakePredictor(), [data], baseline, support_ticks=0)
    second = evaluate_predictor(FakePredictor(), [data], baseline, support_ticks=0)
    assert first == second


@pytest.mark.parametrize(
    "options",
    [{"particles": 1}, {"seed": True}, {"seed": -1}, {"support_ticks": -1}, {"query_stride": 0}],
)
def test_invalid_protocol_parameters_fail_before_model_work(baseline, options):
    model = FakePredictor()
    with pytest.raises(ValueError):
        evaluate_predictor(model, [episode()], baseline, **options)
    assert model.events == []


def test_actual_small_model_cpu_evaluation_preserves_parameters(baseline):
    from mlx.utils import tree_flatten

    from ainerzero.learning.pilot_model import PilotPredictor

    model = PilotPredictor(key=mx.random.key(19))
    before = {name: np.asarray(value).copy() for name, value in tree_flatten(model.parameters())}
    result = evaluate_predictor(model, [episode(steps=4)], baseline, support_ticks=0)
    assert result["horizons"]["4"]["model"]["count"] == 8
    assert np.isfinite(result["horizons"]["4"]["model"]["nll"])
    for name, value in tree_flatten(model.parameters()):
        assert np.array_equal(before[name], np.asarray(value))
