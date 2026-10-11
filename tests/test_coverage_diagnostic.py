"""CPU-only contracts for M2m-a stratification, substitutions and slot audit."""

import builtins
from copy import deepcopy

import numpy as np
import pytest
from test_paired_memory import FakePairedMemory, dataset, fake_mlx  # noqa: F401

from ainerzero.learning.coverage_diagnostic import (
    DECISION_RULES,
    QUERY_GROUPS,
    SUBSTITUTION_KINDS,
    build_substitution_variants,
    classify_query_cells,
    coverage_decision,
    pool_position_symbol_sets,
    query_frames,
    query_labels,
    slot_subspace_audit,
    summarize_cell_scores,
    summarize_substitutions,
)
from ainerzero.learning.diverse_memory import _validate_pool
from ainerzero.learning.micro_memory import _digest
from ainerzero.learning.paired_memory import (
    evaluate_paired_memory,
    evaluate_zero_context_cells,
    evaluate_zero_context_inputs,
    paired_memory_samples,
)


def make_pool(seed=0):
    rng = np.random.default_rng(seed)
    pairs = rng.integers(1, 120, size=(16, 8, 2))
    pairs[..., 1] = np.where(pairs[..., 1] == pairs[..., 0], pairs[..., 0] % 119 + 1, pairs[..., 1])
    symbols = np.zeros((256, 2, 8), dtype=np.int32)
    for world in range(16):
        codes = rng.choice(256, size=16, replace=False)
        for rank, code in enumerate(codes):
            row = world * 16 + rank
            bits = [(int(code) >> p) & 1 for p in range(8)]
            previous = [pairs[world, p, bits[p]] for p in range(8)]
            current = list(previous)
            if rank % 4 == 0:
                current[0] = pairs[world, 0, 1 - bits[0]]
            symbols[row] = [previous, current]
    pool = {
        "symbols": symbols,
        "visible_mask": np.ones((256, 2, 8), dtype=bool),
        "cursor": rng.integers(0, 8, size=(256, 2)).astype(np.int32),
        "episode_start": np.tile(np.array([[True, False]]), (256, 1)),
        "actions": rng.integers(0, 4, size=(256, 1)).astype(np.int32),
    }
    _validate_pool(pool)
    return pool


def samples():
    return [{"row": row, "world_index": row // 16} for row in range(256)]


def frames_from(previous, current, visible=None):
    previous = np.asarray(previous, dtype=np.int32)
    visible = np.ones_like(previous, dtype=bool) if visible is None else np.asarray(visible)
    return {
        "previous_symbols": previous,
        "previous_visible": visible,
        "previous_cursor": np.zeros(len(previous), dtype=np.int32),
        "current_symbols": np.asarray(current, dtype=np.int32),
        "current_visible": np.ones_like(previous, dtype=bool),
        "actions": np.zeros(len(previous), dtype=np.int32),
    }


def test_pool_sets_use_previous_frame_targets_and_keep_inputs_separate():
    pool = make_pool()
    sets = pool_position_symbol_sets(pool)
    for position in range(8):
        target = set(sets["target_by_position"][position])
        assert target == set(pool["symbols"][:, 0, position].tolist())
        assert target <= set(sets["input_by_position"][position])
    assert sets["target_global"] == sorted(set().union(*map(set, sets["target_by_position"])))


def test_classification_flags_same_position_global_and_frame_novelty():
    sets = {
        "target_by_position": [[1], [2], [3], [4], [5], [6], [7], [8]],
        "target_global": [1, 2, 3, 4, 5, 6, 7, 8],
    }
    previous = [[1, 2, 3, 4, 5, 6, 7, 8], [2, 2, 9, 9, 9, 9, 9, 1], [9] * 8]
    current = [[1, 2, 3, 4, 5, 6, 7, 9], previous[1], previous[2]]
    result = classify_query_cells(frames_from(previous, current), sets)
    assert result["same_position_seen"][0].all()
    assert result["frame_novel_count"].tolist() == [0, 7, 8]
    assert result["global_seen"][1].tolist() == [True, True] + [False] * 5 + [True]
    assert result["same_position_seen"][1].tolist() == [False, True] + [False] * 6
    assert result["changed"][0].tolist() == [False] * 7 + [True]
    again = classify_query_cells(frames_from(previous, current), sets)
    assert again["classification_sha256"] == result["classification_sha256"]


def test_hidden_cells_are_never_counted_as_seen_or_scored():
    sets = {"target_by_position": [[0]] * 8, "target_global": [0]}
    visible = [[False] * 8]
    frames = frames_from([[0] * 8], [[0] * 8], visible)
    result = classify_query_cells(frames, sets)
    assert not result["same_position_seen"].any() and not result["global_seen"].any()
    assert result["frame_novel_count"].tolist() == [0]


def test_cell_summary_counts_by_group_and_stratum():
    sets = {"target_by_position": [[1]] * 8, "target_global": [1]}
    previous = [[1] * 8, [1, 1, 2, 2, 2, 2, 2, 2]]
    classification = classify_query_cells(frames_from(previous, previous), sets)
    correct = np.array([[True] * 8, [True, False] + [False] * 6])
    nll = np.where(correct, 0.1, 3.0)
    labels = ["selected_train", "development"]
    summary = summarize_cell_scores(classification, correct, nll, labels)
    assert summary["all"]["all"]["count"] == 16
    assert summary["all"]["all"]["correct"] == 9
    dev = summary["development"]
    assert dev["same_position_seen"]["true"] == {
        "count": 2,
        "correct": 1,
        "accuracy": 0.5,
        "nll": pytest.approx(1.55),
        "changed_count": 0,
        "changed_correct": 0,
        "changed_accuracy": None,
    }
    assert dev["frame_novel_count"]["6-8"]["count"] == 8
    assert dev["same_position_seen_by_frame_novel_count"]["true"]["6-8"]["count"] == 2
    assert summary["selected_train"]["frame_novel_count"]["0"]["accuracy"] == 1.0
    assert set(summary) == {"all", *QUERY_GROUPS}
    with pytest.raises(ValueError):
        summarize_cell_scores(classification, correct[:1], nll, labels)
    with pytest.raises(ValueError):
        summarize_cell_scores(classification, correct, np.full((2, 8), np.nan), labels)


def test_variants_count_order_and_kind_definitions():
    pool = make_pool()
    original = deepcopy(pool)
    batch, evidence = build_substitution_variants(pool, samples())
    assert all(np.array_equal(pool[k], original[k]) for k in pool)
    variants = evidence["variants"]
    assert evidence["variant_count"] == len(variants) == 4096 == len(batch["symbols"])
    assert [v["kind"] for v in variants[:2048]] == ["unseen_at_position"] * 2048
    assert [v["kind"] for v in variants[2048:]] == ["seen_other_world"] * 2048
    assert [(v["row"], v["position"]) for v in variants[:9]] == [(0, p) for p in range(8)] + [
        (1, 0)
    ]
    inputs = pool_position_symbol_sets(pool)["input_by_position"]
    for index, variant in enumerate(variants):
        row, position = variant["row"], variant["position"]
        world = row // 16
        replacement = variant["replacement_symbol"]
        assert replacement not in pool["symbols"][row].ravel().tolist()
        own = set(pool["symbols"][world * 16 : world * 16 + 16, :, position].ravel().tolist())
        if variant["kind"] == "unseen_at_position":
            assert replacement not in inputs[position]
        else:
            assert replacement not in own
            others = np.delete(np.arange(256), np.arange(world * 16, world * 16 + 16))
            assert replacement in pool["symbols"][others, 0, position].tolist()
        changed = pool["symbols"][row, 0] != pool["symbols"][row, 1]
        variant_changed = batch["symbols"][index, 0] != batch["symbols"][index, 1]
        assert np.array_equal(changed, variant_changed)
        assert variant["current_replaced"] is (not changed[position])
        assert variant["substituted_cell_changed"] is bool(changed[position])
        expected_current = pool["symbols"][row, 1].copy()
        if not changed[position]:
            expected_current[position] = replacement
        assert np.array_equal(batch["symbols"][index, 1], expected_current)
        assert (batch["symbols"][index, 0] != pool["symbols"][row, 0]).sum() == 1
        for name in ("visible_mask", "cursor", "episode_start", "actions"):
            assert np.array_equal(batch[name][index], pool[name][row])


def test_variants_are_deterministic_and_seed_bound():
    pool = make_pool()
    first = build_substitution_variants(pool, samples())[1]
    second = build_substitution_variants(pool, samples())[1]
    other = build_substitution_variants(pool, samples(), seed=7308)[1]
    assert first == second
    assert first["variant_manifest_sha256"] == _digest(first["variants"])
    assert other["variant_manifest_sha256"] != first["variant_manifest_sha256"]
    assert first["seed"] == 7307


@pytest.mark.parametrize("seed", [-1, 2**32, 1.0, True])
def test_variant_seed_must_be_integer(seed):
    with pytest.raises(ValueError):
        build_substitution_variants(make_pool(), samples(), seed=seed)


def test_variants_require_world_major_identities_and_visible_targets():
    pool = make_pool()
    bad = samples()
    bad[3]["world_index"] = 2
    with pytest.raises(ValueError):
        build_substitution_variants(pool, bad)
    with pytest.raises(ValueError):
        build_substitution_variants(pool, samples()[:255])
    hidden = deepcopy(pool)
    hidden["visible_mask"][5, :, 3] = False
    hidden["symbols"][5, :, 3] = 0
    with pytest.raises(ValueError):
        build_substitution_variants(hidden, samples())


def test_variants_fail_closed_without_unseen_candidates():
    saturated = make_pool()
    saturated["symbols"][:, 0, 1] = np.arange(256)
    saturated["symbols"][:, 1, 1] = saturated["symbols"][:, 0, 1]
    _validate_pool(saturated)
    with pytest.raises(ValueError, match="no unseen_at_position"):
        build_substitution_variants(saturated, samples())


def test_substitution_summary_measures_substituted_and_other_cells():
    pool = make_pool()
    batch, evidence = build_substitution_variants(pool, samples())
    previous = pool["symbols"][:, 0]
    changed = pool["symbols"][:, 0] != pool["symbols"][:, 1]
    perfect = batch["symbols"][:, 0].copy()
    nll = np.full((4096, 8), 0.5)
    result = summarize_substitutions(evidence, perfect, nll, previous, previous, changed)
    for kind in SUBSTITUTION_KINDS:
        assert result[kind]["substituted_accuracy"] == 1.0
        assert result[kind]["other_accuracy_drop"] == 0.0
        assert result[kind]["other_cell_count"] == 2048 * 7
    broken = perfect.copy()
    for index, variant in enumerate(evidence["variants"]):
        if variant["kind"] == "unseen_at_position":
            broken[index, variant["position"]] = 255 - broken[index, variant["position"]]
            broken[index, (variant["position"] + 1) % 8] = 0
    result = summarize_substitutions(evidence, broken, nll, previous, previous, changed)
    unseen = result["unseen_at_position"]
    assert unseen["substituted_accuracy"] == 0.0
    assert unseen["other_accuracy_drop"] == pytest.approx(1 / 7)
    assert unseen["other_newly_wrong"] == 2048
    assert unseen["variants_with_any_newly_wrong_other_cell"] == 2048
    assert unseen["by_position"]["3"]["variant_count"] == 256
    assert result["seen_other_world"]["other_accuracy_drop"] == 0.0
    with pytest.raises(ValueError):
        summarize_substitutions(evidence, perfect[:10], nll, previous, previous, changed)


@pytest.mark.parametrize(
    "accuracy,drop,dev,outcome,interference",
    [
        (0.5, 0.0, 0.5, "supports_coverage_or_cross_slot_interference", False),
        (0.95, 0.10, 0.0, "supports_coverage_or_cross_slot_interference", True),
        (0.9, 0.049, 0.10, "symbol_identity_not_the_bottleneck", False),
        (0.9, 0.049, 0.11, "intermediate", False),
        (0.89, 0.0, 0.0, "intermediate", False),
        (0.95, 0.05, 0.0, "intermediate", False),
    ],
)
def test_preregistered_decision_boundaries(accuracy, drop, dev, outcome, interference):
    substitutions = {
        "unseen_at_position": {"substituted_accuracy": accuracy, "other_accuracy_drop": drop}
    }
    result = coverage_decision(substitutions, dev)
    assert result["outcome"] == outcome
    assert result["cross_slot_interference_confirmed"] is interference
    assert result["promotion"] is result["automatic_stage_b"] is False
    assert result["rules"] == DECISION_RULES


@pytest.mark.parametrize("value", [None, float("nan"), "0.5"])
def test_decision_requires_measured_rates(value):
    with pytest.raises(ValueError):
        coverage_decision(
            {"unseen_at_position": {"substituted_accuracy": value, "other_accuracy_drop": 0.0}},
            0.0,
        )


def test_slot_subspace_rank_and_outside_fraction_on_toy_embedding():
    pool = make_pool()
    # Pool bytes are all below 128, so they only span dimensions 0-7 of each slot.
    embedding = np.zeros((256, 16))
    embedding[np.arange(256), np.arange(256) % 8 + 8 * (np.arange(256) >= 128)] = (
        1 + np.arange(256) / 256
    )
    labels = ["selected_train", "development"]
    inside = pool["symbols"][0, 0]
    outside = inside.copy()
    outside[2] = 200
    frames = frames_from([inside, outside], [inside, outside])
    audit = slot_subspace_audit(embedding, pool, frames, labels)
    distinct = np.unique(pool["symbols"][:, 0], axis=0)
    vectors = (embedding[distinct]).reshape(len(distinct), 128)
    assert audit["pool_slot_rank"] == np.linalg.matrix_rank(vectors) <= 64
    assert audit["pool_distinct_symbol_visibility_frames"] == len(distinct)
    assert audit["groups"]["selected_train"]["outside_norm_fraction_max"] < 1e-9
    assert audit["groups"]["development"]["outside_norm_fraction_max"] > 0
    assert audit["embedding_rank"] == 16
    assert audit["cursor_action_coverage"]["development"]["query_count"] == 1
    with pytest.raises(ValueError):
        slot_subspace_audit(embedding[:, :8], pool, frames, labels)


def test_cpu_functions_never_import_mlx(monkeypatch):
    original = builtins.__import__

    def guard(name, *args, **kwargs):
        assert not name.startswith("mlx"), "CPU coverage helpers must not import MLX"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    pool = make_pool()
    build_substitution_variants(pool, samples())
    pool_position_symbol_sets(pool)


def test_query_frames_and_labels_follow_registered_manifest(dataset):  # noqa: F811
    frames, evidence = query_frames(dataset)
    assert evidence == paired_memory_samples(dataset)
    assert len(frames["previous_symbols"]) == 2560
    pool_rows = [q for q in evidence["queries"] if q["partition"] == "train"][:256]
    training = {
        "samples": [
            {
                "episode_id": q["episode_id"],
                "query_tick": q["query_tick"],
                "previous_input_sha256": q["previous_input_sha256"],
            }
            for q in pool_rows
        ]
    }
    training["sample_manifest_sha256"] = _digest(training["samples"])
    labels = query_labels(evidence["queries"], training)
    assert labels.count("selected_train") == 256
    assert labels.count("development") == 512
    tampered = deepcopy(training)
    tampered["samples"][0]["query_tick"] = 99
    with pytest.raises(ValueError):
        query_labels(evidence["queries"], tampered)


def test_zero_context_cells_reproduce_paired_zero_branch_and_reserve_first(
    dataset,  # noqa: F811
    fake_mlx,  # noqa: F811
):
    paired = evaluate_paired_memory(FakePairedMemory(), dataset, before_work=lambda _: None)
    events, reservations = [], []
    model = FakePairedMemory(events=events)

    def reserve(count):
        reservations.append((count, len(events)))

    zero = evaluate_zero_context_cells(model, dataset, before_work=reserve)
    assert zero["logical_model_transitions"] == 2560 * 2 * 8 == sum(c for c, _ in reservations)
    assert zero["random_schedule_sha256"] == paired["random_schedule_sha256"]
    assert zero["query_manifest_sha256"] == paired["query_manifest_sha256"]
    for row, expected in zip(zero["per_query"], paired["per_query"], strict=True):
        assert row["zero_context_tail"] == expected["methods"]["zero_context_tail"]
        assert row["paired_random_seeds"] == expected["paired_random_seeds"]
        assert len(row["cell_argmax"]) == len(row["cell_nll"]) == 8
    # Every second reservation precedes the imagine/current chunk of that query.
    assert events[reservations[0][1]][0] == "initial"
    assert events[reservations[1][1]][0] == "imagine"


def test_zero_context_inputs_score_explicit_substitutions(fake_mlx):  # noqa: F811
    pool = make_pool()
    batch, evidence = build_substitution_variants(pool, samples())
    subset = {name: values[:16] for name, values in batch.items()}
    seeds = [[1, 2, 3]] * 16
    calls = []
    result = evaluate_zero_context_inputs(
        FakePairedMemory(), subset, seeds, before_work=calls.append
    )
    assert calls == [8] * 32 and result["logical_model_transitions"] == 256
    assert np.array_equal(result["argmax"], subset["symbols"][:, 0])
    assert np.isfinite(result["nll"]).all()
    with pytest.raises(ValueError):
        evaluate_zero_context_inputs(FakePairedMemory(), subset, seeds[:3], before_work=print)
    with pytest.raises(ValueError):
        evaluate_zero_context_inputs(FakePairedMemory(), subset, seeds, before_work=None)
