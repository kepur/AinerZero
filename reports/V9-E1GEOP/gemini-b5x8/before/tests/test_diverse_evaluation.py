"""Synthetic frozen scores only: no MLX import, model or training work."""

import builtins
import json
from copy import deepcopy

import pytest

from ainerzero.learning.diverse_evaluation import GROUPS, summarize_diverse_pairs
from ainerzero.learning.micro_memory import _digest
from ainerzero.learning.paired_memory import METHODS


def metrics(count, changed, correct, changed_correct, loss):
    unchanged = count - changed
    return {
        "count": count,
        "accuracy": correct / count if count else None,
        "nll": loss if count else None,
        "changed_count": changed,
        "changed_accuracy": changed_correct / changed if changed else None,
        "changed_nll": loss if changed else None,
        "unchanged_count": unchanged,
        "unchanged_accuracy": (correct - changed_correct) / unchanged if unchanged else None,
        "unchanged_nll": loss if unchanged else None,
    }


def resign(report):
    report["query_manifest_sha256"] = _digest(
        [
            {key: value for key, value in row.items() if key not in ("methods", "paired")}
            for row in report["per_query"]
        ]
    )


def resign_pool(evidence):
    evidence["sample_manifest_sha256"] = _digest(evidence["samples"])


@pytest.fixture(scope="module")
def reports():
    rows, samples = [], []
    for world in range(20):
        partition = "train" if world < 16 else "development"
        for tick in range(1, 129):
            count = tick % 8 + 1
            changed = min(tick % 3, count)
            h = tick % (count + 1)
            z = count - h
            hc = min(h, changed)
            zc = changed - hc
            row = {
                "row": len(rows),
                "world_index": world,
                "episode_id": f"episode-{world:02}",
                "environment_instance_id": f"world-{world:02}",
                "partition": partition,
                "group": "development"
                if partition == "development"
                else "fitted_train"
                if tick == 1
                else "other_train",
                "target_tick": tick - 1,
                "query_tick": tick,
                "target_observation_id": f"o-{world}-{tick - 1}",
                "current_observation_id": f"o-{world}-{tick}",
                "action_request_id": f"a-{world}-{tick}",
                "target_visible_count": count,
                "changed_count": changed,
                "previous_input_sha256": _digest([world % 16, tick % 32]),
                "edge_input_sha256": _digest([world % 16, tick % 64, "edge"]),
                "previous_input_matches_fitted": tick % 32 == 1,
                "edge_input_matches_fitted": tick % 64 == 1,
                "public_transition_sha256": _digest([world, tick, "transition"]),
            }
            row["methods"] = {
                method: metrics(count, changed, h, hc, tick + 0.25)
                if method == "history_tail"
                else metrics(count, changed, z, zc, tick + 0.5)
                if method == "zero_context_tail"
                else metrics(count, changed, count, changed, tick + 0.75)
                for method in METHODS
            }
            row["paired"] = {
                "count": count,
                "history_only_correct": h,
                "zero_only_correct": z,
                "both_correct": 0,
                "neither_correct": 0,
                "prediction_disagreements": count,
                "changed_count": changed,
                "changed_history_only_correct": hc,
                "changed_zero_only_correct": zc,
                "changed_both_correct": 0,
                "changed_neither_correct": 0,
                "changed_prediction_disagreements": changed,
            }
            rows.append(row)
            if partition == "train" and tick <= 16:
                samples.append(
                    {
                        key: row[key]
                        for key in (
                            "episode_id",
                            "query_tick",
                            "public_transition_sha256",
                            "previous_input_sha256",
                            "edge_input_sha256",
                        )
                    }
                )
    report = {"query_count": 2560, "world_count": 20, "per_query": rows}
    resign(report)
    evidence = {"sample_count": 256, "samples": samples}
    resign_pool(evidence)
    return report, evidence


@pytest.fixture
def editable(reports):
    return deepcopy(reports)


def test_full_coverage_new_pool_is_not_legacy_fitted_label(reports):
    report, evidence = reports
    result = summarize_diverse_pairs(report, evidence)
    assert tuple(result["groups"]) == GROUPS
    assert [result["groups"][group]["query_count"] for group in GROUPS] == [256, 1792, 512]
    assert result["all_queries"]["query_count"] == 2560
    selected = [r for r in result["per_query"] if r["group"] == "selected_train"]
    assert sum(r["m2j_group"] == "fitted_train" for r in selected) == 16
    assert sum(r["m2j_group"] == "other_train" for r in selected) == 240
    assert all(r["previous_input_matches_pool"] and r["edge_input_matches_pool"] for r in selected)
    assert result["sample_manifest_sha256"] == evidence["sample_manifest_sha256"]
    assert result["query_manifest_sha256"] == report["query_manifest_sha256"]
    assert result["classification_manifest_sha256"] == _digest(result["per_query"])
    assert result["protocol"]["selected_means_model_has_trained_on_pool"] is False
    assert result["protocol"]["unselected_train_independent_holdout"] is False
    assert result["protocol"]["development_independent_acceptance"] is False
    assert result["protocol"]["new_model_work"] is False
    json.dumps(result, allow_nan=False)


def test_no_input_mutation_and_no_mlx_import(reports, monkeypatch):
    before = deepcopy(reports)
    original = builtins.__import__

    def guard(name, *args, **kwargs):
        assert not name.startswith("mlx")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    first = summarize_diverse_pairs(*reports)
    second = summarize_diverse_pairs(*reports)
    assert first == second
    assert reports == before


def test_overlap_strata_are_input_based_not_identity_based(reports):
    result = summarize_diverse_pairs(*reports)
    groups = result["groups"]
    assert result["pool_unique_previous_inputs"] == result["pool_unique_edge_inputs"] == 256
    assert groups["selected_train"]["previous_input_matches_pool"]["false"]["query_count"] == 0
    assert groups["unselected_train"]["previous_input_matches_pool"]["true"]["query_count"] == 768
    assert groups["unselected_train"]["edge_input_matches_pool"]["true"]["query_count"] == 256
    assert groups["development"]["previous_input_matches_pool"]["true"]["query_count"] == 256
    assert groups["development"]["edge_input_matches_pool"]["true"]["query_count"] == 128


def assert_conserves(parent, children):
    for field in ("query_count", "target_visible_count", "changed_count"):
        assert parent[field] == sum(child[field] for child in children)
    for method in METHODS:
        expected = parent["methods"][method]
        for prefix in ("", "changed_", "unchanged_"):
            count = expected[prefix + "count"]
            assert count == sum(child["methods"][method][prefix + "count"] for child in children)
            for metric in ("accuracy", "nll"):
                if count:
                    value = (
                        sum(
                            (child["methods"][method][prefix + metric] or 0)
                            * child["methods"][method][prefix + "count"]
                            for child in children
                        )
                        / count
                    )
                    assert expected[prefix + metric] == pytest.approx(value)
                else:
                    assert expected[prefix + metric] is None
    for field in parent["paired"]:
        if not field.startswith("history_minus_zero"):
            assert parent["paired"][field] == sum(child["paired"][field] for child in children)


def test_scores_counts_and_paired_counts_conserve_at_every_level(reports):
    result = summarize_diverse_pairs(*reports)
    assert_conserves(result["all_queries"], list(result["groups"].values()))
    for group in result["groups"].values():
        for field in ("previous_input_matches_pool", "edge_input_matches_pool"):
            assert_conserves(group, list(group[field].values()))
        for field in ("accuracy", "nll", "changed_accuracy", "changed_nll"):
            assert group["paired"]["history_minus_zero_" + field] == pytest.approx(
                group["methods"]["history_tail"][field]
                - group["methods"]["zero_context_tail"][field]
            )


def test_empty_stratum_has_null_scores_not_success(reports):
    empty = summarize_diverse_pairs(*reports)["groups"]["selected_train"][
        "edge_input_matches_pool"
    ]["false"]
    assert empty["query_count"] == empty["changed_count"] == empty["target_visible_count"] == 0
    assert empty["methods"]["history_tail"]["accuracy"] is None
    assert empty["methods"]["history_tail"]["changed_nll"] is None
    assert empty["paired"]["history_minus_zero_accuracy"] is None
    assert empty["paired"]["count"] == 0


def test_query_weighted_aggregation_is_not_mean_of_row_accuracies(reports):
    report, evidence = reports
    summary = summarize_diverse_pairs(report, evidence)["groups"]["selected_train"]
    rows = [r for r in report["per_query"] if r["partition"] == "train" and r["query_tick"] <= 16]
    count = sum(r["target_visible_count"] for r in rows)
    weighted = (
        sum(r["methods"]["history_tail"]["accuracy"] * r["target_visible_count"] for r in rows)
        / count
    )
    plain = sum(r["methods"]["history_tail"]["accuracy"] for r in rows) / len(rows)
    assert summary["methods"]["history_tail"]["accuracy"] == pytest.approx(weighted)
    assert weighted != pytest.approx(plain)


@pytest.mark.parametrize("field", ["query_count", "world_count"])
@pytest.mark.parametrize("value", [None, True, 0, 1.0])
def test_rejects_invalid_total_counts(editable, field, value):
    report, evidence = editable
    report[field] = value
    with pytest.raises(ValueError):
        summarize_diverse_pairs(report, evidence)


@pytest.mark.parametrize("value", [None, True, 0, 256.0, 255, 257])
def test_rejects_invalid_pool_count(editable, value):
    report, evidence = editable
    evidence["sample_count"] = value
    with pytest.raises(ValueError):
        summarize_diverse_pairs(report, evidence)


@pytest.mark.parametrize("field", ["query_manifest_sha256", "sample_manifest_sha256"])
def test_requires_matching_manifest_hashes(editable, field):
    report, evidence = editable
    (report if field.startswith("query") else evidence)[field] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        summarize_diverse_pairs(report, evidence)


def test_rejects_duplicate_selected_sample_even_after_resigning(editable):
    report, evidence = editable
    evidence["samples"][1] = deepcopy(evidence["samples"][0])
    resign_pool(evidence)
    with pytest.raises(ValueError, match="unique"):
        summarize_diverse_pairs(report, evidence)


@pytest.mark.parametrize("partition", ["development", "missing"])
def test_selected_pool_cannot_include_dev_or_absent_queries(editable, partition):
    report, evidence = editable
    evidence["samples"][0]["episode_id"] = "episode-16" if partition == "development" else "absent"
    resign_pool(evidence)
    with pytest.raises(ValueError, match="training partition"):
        summarize_diverse_pairs(report, evidence)


@pytest.mark.parametrize(
    "field", ["public_transition_sha256", "previous_input_sha256", "edge_input_sha256"]
)
def test_selected_hashes_are_bound_to_the_exact_scored_query(editable, field):
    report, evidence = editable
    evidence["samples"][0][field] = "0" * 64
    resign_pool(evidence)
    with pytest.raises(ValueError, match="hash mismatch"):
        summarize_diverse_pairs(report, evidence)


def test_selected_labels_do_not_depend_on_model_scores(editable):
    report, evidence = editable
    before = summarize_diverse_pairs(report, evidence)
    for row in report["per_query"]:
        # Swap the two model branches, along with paired correctness, but never pool identities.
        row["methods"]["history_tail"], row["methods"]["zero_context_tail"] = (
            row["methods"]["zero_context_tail"],
            row["methods"]["history_tail"],
        )
        for prefix in ("", "changed_"):
            a, b = prefix + "history_only_correct", prefix + "zero_only_correct"
            row["paired"][a], row["paired"][b] = row["paired"][b], row["paired"][a]
    after = summarize_diverse_pairs(report, evidence)
    assert before["per_query"] == after["per_query"]
    assert before["classification_manifest_sha256"] == after["classification_manifest_sha256"]
    for group in GROUPS:
        assert after["groups"][group]["paired"]["history_minus_zero_nll"] == pytest.approx(
            -before["groups"][group]["paired"]["history_minus_zero_nll"]
        )


def test_legacy_fitted_label_does_not_select_pool_members(editable):
    report, evidence = editable
    for row in report["per_query"]:
        if row["partition"] == "train":
            row["group"] = "fitted_train" if row["query_tick"] == 80 else "other_train"
    resign(report)
    result = summarize_diverse_pairs(report, evidence)
    assert result["groups"]["selected_train"]["query_count"] == 256
    assert not any(
        row["m2j_group"] == "fitted_train"
        for row in result["per_query"]
        if row["group"] == "selected_train"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("row", True),
        ("row", 1),
        ("world_index", 20),
        ("episode_id", ""),
        ("query_tick", 0),
        ("query_tick", True),
        ("query_tick", 129),
        ("target_tick", 10),
        ("partition", "test"),
        ("group", "development"),
        ("environment_instance_id", ""),
        ("public_transition_sha256", "x" * 64),
        ("target_visible_count", 9),
        ("changed_count", True),
    ],
)
def test_rejects_invalid_query_identity(editable, field, value):
    report, evidence = editable
    report["per_query"][0][field] = value
    resign(report)
    with pytest.raises(ValueError):
        summarize_diverse_pairs(report, evidence)


def test_rejects_duplicate_queries(editable):
    report, evidence = editable
    report["per_query"][1] = deepcopy(report["per_query"][0])
    report["per_query"][1]["row"] = 1
    resign(report)
    with pytest.raises(ValueError, match="unique"):
        summarize_diverse_pairs(report, evidence)


def test_rejects_same_edge_with_inconsistent_previous_input(editable):
    report, evidence = editable
    report["per_query"][64]["previous_input_sha256"] = "0" * 64
    resign(report)
    with pytest.raises(ValueError, match="identical previous"):
        summarize_diverse_pairs(report, evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("count", True),
        ("changed_count", 0),
        ("unchanged_count", 2),
        ("accuracy", True),
        ("accuracy", 0.3),
        ("accuracy", -1),
        ("accuracy", 2),
        ("nll", float("inf")),
        ("nll", float("nan")),
        ("nll", None),
        ("nll", -0.1),
    ],
)
def test_rejects_invalid_method_scores(editable, field, value):
    report, evidence = editable
    report["per_query"][0]["methods"]["history_tail"][field] = value
    with pytest.raises(ValueError):
        summarize_diverse_pairs(report, evidence)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("count", 1),
        ("count", True),
        ("both_correct", 1),
        ("neither_correct", -1),
        ("history_only_correct", 0),
        ("prediction_disagreements", 0),
        ("changed_zero_only_correct", 1),
        ("changed_count", 0),
    ],
)
def test_rejects_nonconserved_paired_counts(editable, field, value):
    report, evidence = editable
    report["per_query"][0]["paired"][field] = value
    with pytest.raises(ValueError):
        summarize_diverse_pairs(report, evidence)


def test_method_and_paired_correctness_must_agree(editable):
    report, evidence = editable
    report["per_query"][0]["methods"]["history_tail"]["accuracy"] = 1
    with pytest.raises(ValueError, match="correctness counts disagree"):
        summarize_diverse_pairs(report, evidence)


def test_missing_method_and_null_empty_metric_are_rejected(editable):
    report, evidence = editable
    del report["per_query"][0]["methods"]["reset_history"]
    with pytest.raises(ValueError, match="five paired methods"):
        summarize_diverse_pairs(report, evidence)
    report, evidence = deepcopy(editable)
    # Restore the deleted control from another same-shape method first.
    report["per_query"][0]["methods"]["reset_history"] = deepcopy(
        report["per_query"][0]["methods"]["copy_current"]
    )
    report["per_query"][2]["methods"]["history_tail"]["changed_accuracy"] = 0
    with pytest.raises(ValueError, match="empty metric"):
        summarize_diverse_pairs(report, evidence)
