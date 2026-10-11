"""CPU contracts for M2m consistent relabeling, strata and fixed reading table."""

import builtins
from copy import deepcopy

import numpy as np
import pytest
from test_coverage_diagnostic import make_pool
from test_paired_memory import FakePairedMemory, dataset, fake_mlx  # noqa: F401

from ainerzero.data.augmentation import permute_symbols
from ainerzero.learning.coverage_diagnostic import (
    classify_query_cells,
    pool_position_symbol_sets,
    summarize_cell_scores,
)
from ainerzero.learning.diverse_memory import get_diverse_batch
from ainerzero.learning.micro_memory import _digest
from ainerzero.learning.paired_memory import evaluate_paired_memory
from ainerzero.learning.relabel_memory import (
    NEXT_STEPS,
    RELABEL_EVALUATION_SEED,
    RELABEL_TRAINING_SEED,
    TRAINING_PERMUTATION_COUNT,
    compare_strata,
    next_step,
    permutation_sha256,
    regression_flags,
    relabel_batch,
    relabel_evaluation_pool,
    summarize_relabel_pool,
    training_permutation_manifest,
    transfer_level,
)


@pytest.fixture(scope="module")
def manifest():
    return training_permutation_manifest()


def test_registered_seeds_and_counts():
    assert RELABEL_TRAINING_SEED == 2307
    assert RELABEL_EVALUATION_SEED == 9103
    assert TRAINING_PERMUTATION_COUNT == 3200


def test_training_manifest_replays_the_exact_permute_symbols_draws(manifest):
    assert manifest["count"] == manifest["unique_count"] == 3200
    assert manifest["manifest_sha256"] == _digest(manifest["digests"])
    assert training_permutation_manifest() == manifest
    pool = make_pool()
    rng = np.random.default_rng(2307)
    for update in range(3):
        batch = get_diverse_batch(pool, update)
        _, digests = relabel_batch(batch, rng)
        assert digests == manifest["digests"][update * 16 : (update + 1) * 16]
    with pytest.raises(ValueError):
        training_permutation_manifest(seed=-1)
    with pytest.raises(ValueError):
        training_permutation_manifest(seed=2307.0)


def test_relabel_batch_equals_permute_symbols_and_changes_only_symbols():
    pool = make_pool()
    pool["visible_mask"][3, 0, 2] = False
    pool["symbols"][3, 0, 2] = 0
    batch = get_diverse_batch(pool, 0)
    original = deepcopy(batch)
    relabeled, digests = relabel_batch(batch, np.random.default_rng(5))
    expected = permute_symbols(batch, np.random.default_rng(5))
    assert all(np.array_equal(relabeled[k], expected[k]) for k in expected)
    assert all(np.array_equal(batch[k], original[k]) for k in batch)
    assert len(digests) == len(set(digests)) == 16
    for name in ("visible_mask", "cursor", "episode_start", "actions"):
        assert np.array_equal(relabeled[name], batch[name])
        assert relabeled[name].dtype == batch[name].dtype
    assert relabeled["symbols"].dtype == np.int32
    assert (relabeled["symbols"][~batch["visible_mask"]] == 0).all()
    rng = np.random.default_rng(5)
    for index in range(16):
        permutation = rng.permutation(256)
        mask = batch["visible_mask"][index]
        assert np.array_equal(
            relabeled["symbols"][index][mask], permutation[batch["symbols"][index][mask]]
        )
        assert digests[index] == permutation_sha256(permutation)


def test_relabel_batch_rejects_bad_inputs():
    pool = make_pool()
    with pytest.raises(TypeError):
        relabel_batch(get_diverse_batch(pool, 0), 7)
    with pytest.raises(ValueError):
        relabel_batch({"symbols": np.zeros((2, 3, 8), dtype=np.int32)}, np.random.default_rng(0))
    with pytest.raises(ValueError):
        permutation_sha256(list(range(255)) + [0])


def test_evaluation_pool_uses_unseen_bijections_and_preserves_changes(manifest):
    pool = make_pool()
    batch, evidence = relabel_evaluation_pool(pool, manifest)
    again, repeated = relabel_evaluation_pool(pool, manifest)
    assert evidence == repeated and np.array_equal(batch["symbols"], again["symbols"])
    assert evidence["seed"] == 9103 and evidence["rows"] == 256
    assert evidence["training_overlap"] == 0
    assert not set(evidence["digests"]) & set(manifest["digests"])
    assert evidence["changed_targets"] == 64
    assert evidence["visible_targets"] == 2048
    expected = permute_symbols(pool, np.random.default_rng(9103))
    assert np.array_equal(batch["symbols"], expected["symbols"])
    assert not np.array_equal(batch["symbols"], pool["symbols"])


def test_evaluation_pool_rejects_unregistered_or_overlapping_manifest(manifest):
    pool = make_pool()
    tampered = deepcopy(manifest)
    tampered["digests"][0] = "0" * 64
    with pytest.raises(ValueError):
        relabel_evaluation_pool(pool, tampered)
    with pytest.raises(ValueError):
        relabel_evaluation_pool(pool, {**manifest, "count": 3199})
    _, evidence = relabel_evaluation_pool(pool, manifest)
    overlapping = deepcopy(manifest)
    overlapping["digests"][-1] = evidence["digests"][0]
    overlapping["manifest_sha256"] = _digest(overlapping["digests"])
    with pytest.raises(ValueError, match="unseen in training"):
        relabel_evaluation_pool(pool, overlapping)


def test_relabel_pool_summary_counts_cells_and_changes(manifest):
    pool = make_pool()
    batch, _ = relabel_evaluation_pool(pool, manifest)
    argmax = batch["symbols"][:, 0].copy()
    argmax[:, 0] = (argmax[:, 0] + 1) % 256
    nll = np.full((256, 8), 0.5)
    result = summarize_relabel_pool(argmax, nll, batch)
    assert result["count"] == 2048 and result["correct"] == 2048 - 256
    assert result["changed_count"] == 64 and result["changed_correct"] == 0
    assert result["by_position"][0]["accuracy"] == 0.0
    assert result["by_position"][1]["accuracy"] == 1.0
    with pytest.raises(ValueError):
        summarize_relabel_pool(argmax[:3], nll, batch)
    bad = nll.copy()
    bad[0, 0] = np.inf
    with pytest.raises(ValueError):
        summarize_relabel_pool(argmax, bad, batch)


def frames_and_cells():
    rng = np.random.default_rng(3)
    previous = rng.integers(0, 256, size=(12, 8))
    current = previous.copy()
    current[::3, 0] = (current[::3, 0] + 1) % 256
    frames = {
        "previous_symbols": previous.astype(np.int32),
        "previous_visible": np.ones((12, 8), dtype=bool),
        "previous_cursor": np.zeros(12, dtype=np.int32),
        "current_symbols": current.astype(np.int32),
        "current_visible": np.ones((12, 8), dtype=bool),
        "actions": np.zeros(12, dtype=np.int32),
    }
    pool = make_pool()
    pool["symbols"][0, 0] = previous[0]
    classification = classify_query_cells(frames, pool_position_symbol_sets(pool))
    labels = ["selected_train"] * 3 + ["development"] * 9

    def cells(wrong_rows):
        result = []
        for row in range(12):
            argmax = previous[row].copy()
            if row in wrong_rows:
                argmax = (argmax + 1) % 256
            entry = {"argmax": argmax.tolist(), "nll": [0.25] * 8}
            result.append({"history_tail": deepcopy(entry), "zero_context_tail": deepcopy(entry)})
        return result

    return frames, classification, labels, cells


def test_strata_compare_both_branches_on_identical_cells():
    frames, classification, labels, cells = frames_and_cells()
    current, reference = cells(set()), cells({0, 5, 6})
    result = compare_strata(classification, labels, frames["previous_symbols"], current, reference)
    assert set(result["branches"]) == {"zero_context_tail", "history_tail"}
    for branch in result["branches"].values():
        diff = branch["m2m_minus_m2l"]
        assert branch["m2m"]["all"]["all"]["accuracy"] == 1.0
        assert branch["m2l"]["all"]["all"]["accuracy"] == pytest.approx(9 / 12)
        assert diff["all"]["all"]["accuracy"] == pytest.approx(3 / 12)
        assert diff["all"]["all"]["count"] == 96
        assert diff["development"]["query_count"] == 9
        expected = summarize_cell_scores(
            classification,
            np.ones((12, 8), dtype=bool),
            np.full((12, 8), 0.25),
            labels,
        )
        assert branch["m2m"] == expected
        strata = diff["all"]["same_position_seen_by_frame_novel_count"]
        assert set(strata) == {"true", "false"}
        assert set(strata["true"]) == {"0", "1-2", "3-5", "6-8"}


def test_strata_reject_misaligned_cells():
    frames, classification, labels, cells = frames_and_cells()
    with pytest.raises(ValueError):
        compare_strata(
            classification, labels, frames["previous_symbols"], cells(set())[:5], cells(set())
        )
    broken = cells(set())
    broken[0]["history_tail"]["argmax"] = [1, 2]
    with pytest.raises(ValueError):
        compare_strata(classification, labels, frames["previous_symbols"], broken, cells(set()))


@pytest.mark.parametrize(
    "accuracy,changed,level",
    [
        (0.0, 0.0, "not_transferred"),
        (0.0999, 1.0, "not_transferred"),
        (0.10, 0.0, "partial"),
        (0.7999, 1.0, "partial"),
        (0.80, 0.4999, "partial"),
        (0.80, None, "partial"),
        (0.80, 0.50, "transferred"),
        (1.0, 1.0, "transferred"),
    ],
)
def test_transfer_level_boundaries(accuracy, changed, level):
    assert transfer_level({"accuracy": accuracy, "changed_accuracy": changed}) == level


@pytest.mark.parametrize("accuracy", [None, float("nan"), 1.5, -0.1, "0.5"])
def test_transfer_level_requires_measured_accuracy(accuracy):
    with pytest.raises(ValueError):
        transfer_level({"accuracy": accuracy, "changed_accuracy": 0.5})


@pytest.mark.parametrize(
    "local,development,pool,outcome",
    [
        (False, "transferred", "transferred", "underfit"),
        (True, "transferred", "transferred", "coverage_main_cause"),
        (True, "not_transferred", "transferred", "relabel_invariance_but_development_differs"),
        (True, "not_transferred", "not_transferred", "coverage_hypothesis_rejected"),
        (True, "partial", "partial", "partial_transfer"),
        (True, "partial", "transferred", "unregistered_combination"),
        (True, "transferred", "partial", "unregistered_combination"),
        (True, "not_transferred", "partial", "unregistered_combination"),
    ],
)
def test_next_step_reading_table(local, development, pool, outcome):
    for regression in (False, True):
        result = next_step(local, development, pool, regression)
        assert result["outcome"] == outcome
        assert result["next_step"] == NEXT_STEPS[outcome]
        assert result["promotion"] is False and result["automatic_next_run"] is False
        assert result["regression_reported"] is regression
        assert (result["regression_next_step"] is None) is (not regression)


def test_next_step_rejects_unknown_levels_or_flags():
    with pytest.raises(ValueError):
        next_step(True, "high", "partial", False)
    with pytest.raises(ValueError):
        next_step(1, "partial", "partial", False)


def phase(one, four, one_nll=0.3, four_nll=0.9, recon=1.0, gate="passed"):
    return {
        "action": {
            "horizons": {
                "1": {"model": {"accuracy": one, "nll": one_nll}},
                "4": {"model": {"accuracy": four, "nll": four_nll}},
            }
        },
        "reconstruction": {
            "gate": {"status": gate},
            "model": {"accuracy": recon, "count": 544},
        },
    }


def test_regression_flags_follow_registered_limits():
    before = phase(377 / 384, 359 / 384)
    assert regression_flags(before, deepcopy(before))["regression"] is False
    ok = phase(377 / 384, 359 / 384, one_nll=0.3 + 0.049, four_nll=0.9 + 0.149)
    assert regression_flags(before, ok)["regression"] is False
    for after in (
        phase(376 / 384, 359 / 384),
        phase(377 / 384, 358 / 384),
        phase(377 / 384, 359 / 384, one_nll=0.36),
        phase(377 / 384, 359 / 384, four_nll=1.06),
        phase(377 / 384, 359 / 384, recon=543 / 544),
        phase(377 / 384, 359 / 384, gate="failed"),
    ):
        result = regression_flags(before, after)
        assert result["regression"] is True
        assert result["memory_progress_offsets_regression"] is False


def test_paired_cell_outputs_are_additive_and_consistent(dataset, fake_mlx):  # noqa: F811
    plain = evaluate_paired_memory(FakePairedMemory(), dataset, before_work=lambda _: None)
    units = []
    with_cells = evaluate_paired_memory(
        FakePairedMemory(), dataset, before_work=units.append, cell_outputs=True
    )
    cells = with_cells.pop("per_query_cells")
    assert with_cells == plain
    assert sum(units) == plain["logical_model_transitions"] == 82080
    assert len(cells) == 2560
    for row, query in zip(cells, plain["per_query"], strict=True):
        for branch in ("history_tail", "zero_context_tail"):
            nll = [value for value in row[branch]["nll"] if value is not None]
            assert len(row[branch]["argmax"]) == 8 and len(nll) == query["target_visible_count"]
    with pytest.raises(ValueError):
        evaluate_paired_memory(FakePairedMemory(), dataset, before_work=print, cell_outputs=1)


def test_cpu_relabel_functions_never_import_mlx(monkeypatch, manifest):
    original = builtins.__import__

    def forbid(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx."):
            raise AssertionError("CPU relabel helpers must not import MLX")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid)
    pool = make_pool()
    batch, _ = relabel_evaluation_pool(pool, manifest)
    relabel_batch(get_diverse_batch(pool, 1), np.random.default_rng(1))
    summarize_relabel_pool(batch["symbols"][:, 0], np.zeros((256, 8)), batch)
