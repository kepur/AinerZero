"""CPU-only regrouping of frozen paired scores against a preregistered pool.

Selection means membership in the M2l training pool, not that the scored model
has already trained on it. In particular the same helper can summarize the M2k
parent scores. The old ``fitted_train`` label continues to mean the M2j 16 edges.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from math import isclose, isfinite

from ainerzero.learning.evaluation import _Summary
from ainerzero.learning.micro_memory import _digest
from ainerzero.learning.paired_memory import METHODS, _paired_result

GROUPS = ("selected_train", "unselected_train", "development")
_HASH_FIELDS = (
    "public_transition_sha256",
    "previous_input_sha256",
    "edge_input_sha256",
)
_IDENTITY_FIELDS = (
    "row",
    "world_index",
    "episode_id",
    "environment_instance_id",
    "partition",
    "group",
    "target_tick",
    "query_tick",
    "target_observation_id",
    "current_observation_id",
    "action_request_id",
    "target_visible_count",
    "changed_count",
    "previous_input_sha256",
    "edge_input_sha256",
    "previous_input_matches_fitted",
    "edge_input_matches_fitted",
    "public_transition_sha256",
)
_PAIRED_FIELDS = tuple(
    prefix + name
    for prefix in ("", "changed_")
    for name in (
        "count",
        "history_only_correct",
        "zero_only_correct",
        "both_correct",
        "neither_correct",
        "prediction_disagreements",
    )
)


def _integer(value, *, maximum=None):
    if type(value) is not int or value < 0 or (maximum is not None and value > maximum):
        raise ValueError("counts and indices must be nonnegative integers within bounds")
    return value


def _hash(value):
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("evidence requires lowercase SHA256 digests")
    return value


def _key(row):
    episode = row.get("episode_id")
    if not isinstance(episode, str) or not episode:
        raise ValueError("every query requires an episode ID")
    tick = _integer(row.get("query_tick"), maximum=128)
    if tick == 0:
        raise ValueError("query ticks must be in [1, 128]")
    return episode, tick


def _validate_scores(row):
    count = _integer(row.get("target_visible_count"), maximum=8)
    changed = _integer(row.get("changed_count"), maximum=count)
    methods = row.get("methods")
    if not isinstance(methods, Mapping) or set(methods) != set(METHODS):
        raise ValueError("all five paired methods are required")
    unchanged_counts = set()
    for metrics in methods.values():
        if not isinstance(metrics, Mapping):
            raise ValueError("method metrics must be mappings")
        if metrics.get("count") != count or metrics.get("changed_count") != changed:
            raise ValueError("method counts must match public query counts")
        unchanged = _integer(metrics.get("unchanged_count"), maximum=count - changed)
        unchanged_counts.add(unchanged)
        for prefix in ("", "changed_", "unchanged_"):
            denominator = _integer(metrics.get(prefix + "count"), maximum=count)
            for metric in ("accuracy", "nll"):
                value = metrics.get(prefix + metric)
                if denominator == 0:
                    if value is not None:
                        raise ValueError("empty metric denominators must have null scores")
                elif (
                    type(value) not in (int, float)
                    or not isfinite(value)
                    or value < 0
                    or (metric == "accuracy" and value > 1)
                ):
                    raise ValueError("scores must be finite and within their valid range")
                elif metric == "accuracy" and not isclose(
                    value * denominator, round(value * denominator), abs_tol=1e-8
                ):
                    raise ValueError("query accuracy must represent an integer correct count")
    if len(unchanged_counts) != 1:
        raise ValueError("all methods must score identical unchanged masks")
    paired = row.get("paired")
    if not isinstance(paired, Mapping):
        raise ValueError("paired correctness counts are required")
    for prefix, denominator in (("", count), ("changed_", changed)):
        values = {
            name: _integer(paired.get(prefix + name), maximum=denominator)
            for name in (
                "count",
                "history_only_correct",
                "zero_only_correct",
                "both_correct",
                "neither_correct",
                "prediction_disagreements",
            )
        }
        if (
            values["count"] != denominator
            or sum(
                values[name]
                for name in (
                    "history_only_correct",
                    "zero_only_correct",
                    "both_correct",
                    "neither_correct",
                )
            )
            != denominator
        ):
            raise ValueError("paired correctness counts must conserve target counts")
        one_only = values["history_only_correct"] + values["zero_only_correct"]
        if (
            not one_only
            <= values["prediction_disagreements"]
            <= (one_only + values["neither_correct"])
        ):
            raise ValueError("prediction disagreements conflict with paired correctness")
        for method, exclusive in (
            ("history_tail", "history_only_correct"),
            ("zero_context_tail", "zero_only_correct"),
        ):
            correct = (methods[method][prefix + "accuracy"] or 0) * denominator
            if not isclose(correct, values[exclusive] + values["both_correct"], abs_tol=1e-8):
                raise ValueError("paired and method correctness counts disagree")


def _validate_queries(report):
    if not isinstance(report, Mapping):
        raise ValueError("paired report must be a mapping")
    rows = report.get("per_query")
    if (
        not isinstance(rows, list)
        or len(rows) != 2560
        or type(report.get("query_count")) is not int
        or report["query_count"] != 2560
        or type(report.get("world_count")) is not int
        or report["world_count"] != 20
    ):
        raise ValueError("paired report must cover all 2560 queries in 20 worlds")
    identities, by_key, worlds, indices = [], {}, {}, {}
    edge_to_previous = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or any(name not in row for name in _IDENTITY_FIELDS):
            raise ValueError("paired query identity is incomplete")
        if type(row["row"]) is not int or row["row"] != index:
            raise ValueError("paired rows must retain their original complete ordering")
        key = _key(row)
        if key in by_key:
            raise ValueError("paired queries must be unique")
        by_key[key] = row
        world_index = _integer(row["world_index"], maximum=19)
        if row["target_tick"] != row["query_tick"] - 1:
            raise ValueError("paired target and query must be adjacent ticks")
        partition = row["partition"]
        if partition not in ("train", "development"):
            raise ValueError("paired queries may only contain train and development")
        if row["group"] not in (
            ("fitted_train", "other_train") if partition == "train" else ("development",)
        ):
            raise ValueError("legacy M2j groups must retain their partition semantics")
        world = row["environment_instance_id"]
        if not isinstance(world, str) or not world:
            raise ValueError("query requires an environment ID")
        identity = (key[0], partition, world_index)
        if world in worlds and worlds[world] != identity:
            raise ValueError("one world cannot span episodes, partitions or indices")
        worlds[world] = identity
        if world_index in indices and indices[world_index] != world:
            raise ValueError("world indices must identify distinct worlds")
        indices[world_index] = world
        for name in _HASH_FIELDS:
            _hash(row[name])
        edge_sha, previous_sha = row["edge_input_sha256"], row["previous_input_sha256"]
        if edge_sha in edge_to_previous and edge_to_previous[edge_sha] != previous_sha:
            raise ValueError("identical edge inputs must have identical previous inputs")
        edge_to_previous[edge_sha] = previous_sha
        _validate_scores(row)
        identities.append({name: row[name] for name in _IDENTITY_FIELDS})
    partition_counts = Counter(row["partition"] for row in rows)
    episode_counts = Counter(row["episode_id"] for row in rows)
    if (
        partition_counts != {"train": 2048, "development": 512}
        or len(worlds) != 20
        or len(episode_counts) != 20
        or set(episode_counts.values()) != {128}
    ):
        raise ValueError("paired report must retain 16 train and 4 development full worlds")
    if _digest(identities) != report.get("query_manifest_sha256"):
        raise ValueError("paired query manifest digest does not match its identities")
    return rows, by_key


def _validate_pool(evidence, by_key):
    if not isinstance(evidence, Mapping):
        raise ValueError("training evidence must be a mapping")
    samples = evidence.get("samples")
    if (
        not isinstance(samples, list)
        or len(samples) != 256
        or type(evidence.get("sample_count")) is not int
        or evidence["sample_count"] != 256
    ):
        raise ValueError("M2l requires exactly 256 selected training queries")
    if _digest(samples) != evidence.get("sample_manifest_sha256"):
        raise ValueError("training sample manifest digest mismatch")
    selected = set()
    for sample in samples:
        if not isinstance(sample, Mapping):
            raise ValueError("training samples must be identity mappings")
        key = _key(sample)
        if key in selected:
            raise ValueError("selected training queries must be unique")
        selected.add(key)
        row = by_key.get(key)
        if row is None or row["partition"] != "train":
            raise ValueError("selected samples must be present in the report training partition")
        if any(_hash(sample.get(name)) != row[name] for name in _HASH_FIELDS):
            raise ValueError("selected sample public transition or input hash mismatch")
    return selected


def _summarize(rows):
    summaries = {method: _Summary() for method in METHODS}
    paired = {name: 0 for name in _PAIRED_FIELDS}
    for row in rows:
        for method, summary in summaries.items():
            summary.add(row["methods"][method])
        for name in _PAIRED_FIELDS:
            paired[name] += row["paired"][name]
    methods = {name: summary.result() for name, summary in summaries.items()}
    return {
        "query_count": len(rows),
        "target_visible_count": paired["count"],
        "changed_count": paired["changed_count"],
        "methods": methods,
        "paired": _paired_result(paired, methods),
    }


def summarize_diverse_pairs(paired_report, training_evidence) -> dict:
    """Regroup all frozen scores without model work or result-dependent selection.

    ``paired_report`` is the direct ``evaluate_paired_memory`` return value, not
    an enclosing worker report. Hash-verified query identities determine every
    grouping; predictions and the legacy M2j group never select pool members.
    Overlap refers to exact public sensor inputs, not semantic equivalence.
    """
    rows, by_key = _validate_queries(paired_report)
    selected = _validate_pool(training_evidence, by_key)
    pool_previous = {by_key[key]["previous_input_sha256"] for key in selected}
    pool_edges = {by_key[key]["edge_input_sha256"] for key in selected}
    buckets = defaultdict(list)
    classified = []
    for row in rows:
        group = (
            "development"
            if row["partition"] == "development"
            else "selected_train"
            if _key(row) in selected
            else "unselected_train"
        )
        previous = row["previous_input_sha256"] in pool_previous
        edge = row["edge_input_sha256"] in pool_edges
        buckets[group].append(row)
        buckets[(group, "previous", previous)].append(row)
        buckets[(group, "edge", edge)].append(row)
        classified.append(
            {
                "row": row["row"],
                "episode_id": row["episode_id"],
                "query_tick": row["query_tick"],
                "group": group,
                "m2j_group": row["group"],
                "previous_input_matches_pool": previous,
                "edge_input_matches_pool": edge,
            }
        )
    groups = {}
    for group in GROUPS:
        groups[group] = _summarize(buckets[group])
        for label in ("previous", "edge"):
            groups[group][f"{label}_input_matches_pool"] = {
                str(matched).lower(): _summarize(buckets[(group, label, matched)])
                for matched in (True, False)
            }
    return {
        "schema_version": 1,
        "scope": "m2l_training_pool_regrouping_of_all_frozen_paired_queries",
        "query_manifest_sha256": paired_report["query_manifest_sha256"],
        "sample_manifest_sha256": training_evidence["sample_manifest_sha256"],
        "classification_manifest_sha256": _digest(classified),
        "sample_count": len(selected),
        "pool_unique_previous_inputs": len(pool_previous),
        "pool_unique_edge_inputs": len(pool_edges),
        "all_queries": _summarize(rows),
        "groups": groups,
        "per_query": classified,
        "protocol": {
            "selection": "preregistered_training_pool_identity_not_model_score_or_m2j_group",
            "selected_means_model_has_trained_on_pool": False,
            "m2j_fitted_train_means": "original_16_m2j_edges_only",
            "unselected_train_independent_holdout": False,
            "development_independent_acceptance": False,
            "overlap": "exact_public_inputs_without_ids_or_ticks",
            "aggregation": "target_count_weighted_scores_and_summed_paired_counts",
            "new_model_work": False,
            "promotion": "not_authorized_by_this_summary",
        },
    }
