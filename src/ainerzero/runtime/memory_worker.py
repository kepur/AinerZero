"""One bounded GRU-only previous-observation retention experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil

from ainerzero.core.experience import TrainingPolicy
from ainerzero.core.pilot import load_pilot_config
from ainerzero.data.augmentation import permute_symbols
from ainerzero.data.pilot_dataset import load_pilot_dataset
from ainerzero.data.sequences import SequenceSampler
from ainerzero.learning.baselines import NoActionBaseline
from ainerzero.learning.memory_codec import audit_bounded_codec
from ainerzero.runtime.c0_collection import RANDOM_ACTOR
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint, save_checkpoint
from ainerzero.runtime.history_worker import validate_history_source
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore


def memory_plan():
    return {
        "protocol": "m2h_one_step_previous_observation_v1",
        "architecture": "pilot_shared_symbol_v1",
        "parameter_count": 393232,
        "trainable_modules": ["gru"],
        "trainable_parameter_count": 222208,
        "readout": "reuse_frozen_symbol_head_on_h_tail_8_by_16_after_next_observation",
        "target": "previous_visible_public_observation_uniform_symbol_cross_entropy",
        "updates": 100,
        "learning_rate": 0.001,
        "batch_size": 16,
        "micro_batch_size": 4,
        "burn_in": 4,
        "sequence_steps": 16,
        "transitions_per_window": 20,
        "training_model_units_per_update": 336,
        "augmentation": "per_window_consistent_byte_permutation_training_only",
        "seeds": {
            "windows": 2101,
            "augmentation": 2307,
            "latent": 2203,
            "memory_train": 3901,
            "memory_development": 4901,
        },
        "evaluation": {"support_ticks": 32, "particles": 8, "query_stride": 1},
        "screen": {
            "minimum_changed_count": 30,
            "overall_accuracy_min": 0.95,
            "changed_accuracy_min": 0.8,
            "per_world_changed_accuracy_min": 0.5,
        },
        "source_optimizer": "reset_AdamW_GRU_only",
        "automatic_promotion": False,
        "new_environment_steps": 0,
        "scope": "explicit_supervised_tail_slots_reused_development_not_autonomous_memory_discovery",
        "resource_seconds": {
            "initialization": 15,
            "compatibility": 15,
            "before_memory_train": 90,
            "before_memory_development": 45,
            "before_action": 60,
            "before_reconstruction": 45,
            "training_update": 5,
            "after_memory_train": 90,
            "after_memory_development": 45,
            "after_action": 60,
            "after_reconstruction": 45,
            "checkpoint": 30,
            "verification": 10,
        },
        "total_reserved_seconds_if_complete": 1050,
        "supervised_deadline_seconds": 1500,
        "selection": "one_fixed_run_no_dev_tuning_no_automatic_retry_or_promotion",
    }


def micro_memory_plan():
    """M2j is a local fit diagnostic, separate from M2h's continuous task."""
    plan = memory_plan()
    plan.update(
        protocol="m2j_fixed_single_edge_tail_fit_v1",
        updates=200,
        trainable_parameter_count=111104,
        optimizer_tensor_parameter_count=222208,
        frozen_parameter_count=282128,
        trainable_scope="GRU_tail_output_rows_only_mask_gradients_project_front_after_AdamW",
        burn_in=0,
        sequence_steps=1,
        transitions_per_window=1,
        training_model_units_per_update=32,
        augmentation="none_fixed_batch_repeated",
        seeds={
            "latent": 2203,
            "local_new_noise": 2603,
            "memory_train": 3901,
            "memory_development": 4901,
        },
        local_checks=[0, 50, 100, 150, 200],
        local_check_model_units=48,
        local_screen={
            "overall_accuracy_min": 0.95,
            "changed_accuracy_min": 0.8,
            "minimum_changed_count": 16,
        },
        sample_selection="exactly_16_train_worlds_sorted_episode_then_world_first_visible_change",
        local_evaluation="one_particle_same_four_micro_batches_same_inputs_two_fixed_noise_seeds",
        source_optimizer="reset_AdamW_GRU_masked_and_projected_front",
        scope="fixed_training_examples_single_feedback_edge_fit_not_general_memory",
        total_reserved_seconds_if_complete=1000,
        expected_total_model_units=92128,
    )
    plan["resource_seconds"]["training_update"] = 2
    plan["resource_seconds"]["local_check"] = 5
    return plan


def diverse_memory_plan():
    """M2l expands the public input distribution at the same update budget."""
    plan = micro_memory_plan()
    plan.update(
        protocol="m2l_diverse_single_edge_tail_fit_v1",
        augmentation="none_fixed_public_pool_cyclic_schedule",
        sample_selection="16_train_worlds_4_changed_12_unchanged_unique_previous_per_world",
        training_pool_size=256,
        training_schedule="world_major_pool_rank_(zero_based_update+world_index)_mod_16",
        training_distribution="four_changed_and_twelve_unchanged_edges_per_batch",
        comparison_caveat="input_diversity_and_changed_edge_mix_both_change_from_M2j",
        scope="diverse_public_training_edges_one_step_retention_not_independent_acceptance",
        paired_evaluation={"seed": 7103, "particles": 8},
        expected_total_model_units=174208,
        total_reserved_seconds_if_complete=1300,
    )
    plan["resource_seconds"]["after_paired"] = 300
    return plan


RELABEL_LEARNING_RATES = {
    0.001: "m2m_consistent_relabel_single_edge_tail_fit_v1",
    0.003: "m2m_c_consistent_relabel_lr0003_single_edge_tail_fit_v1",
}


def relabel_memory_plan(learning_rate=0.001):
    """M2m adds only a per-sample consistent byte relabeling to the M2l protocol.

    M2m-c is the single registered learning-rate variant (0.003); every other
    field is identical to M2m stage B.  No other learning rate is accepted.
    """
    if type(learning_rate) is not float or learning_rate not in RELABEL_LEARNING_RATES:
        raise ValueError("relabel learning rate must be one registered value")
    plan = diverse_memory_plan()
    plan.update(
        protocol="m2m_consistent_relabel_single_edge_tail_fit_v1",
        augmentation="per_sample_consistent_byte_bijection_both_frames_all_visible_cells_permute_symbols",
        augmentation_scope="training_batches_only_local_checks_and_evaluations_unpermuted",
        training_permutations=3200,
        comparison_caveat="single_factor_vs_M2l_relabel_only_same_start_pool_schedule_seeds",
        scope="relabeled_public_training_edges_one_step_retention_not_independent_acceptance",
        relabel_evaluation={
            "seed": 9103,
            "rows": 256,
            "branch": "zero_context_tail",
            "particles": 8,
            "keys": "paired_query_keys_of_each_pool_row_seed_7103",
            "model_units": 4096,
            "disjoint_from_training_permutations": True,
        },
        m2l_comparison={
            "candidate": "frozen_completed_m2l_candidate_no_updates",
            "paired_with_cells_model_units": 82080,
            "relabel_pool_model_units": 4096,
            "paired_must_reproduce_m2l_report_exactly": True,
        },
        stratification={
            "coverage_reference": "visible_previous_frame_targets_of_m2l_256_pool_rows_unpermuted",
            "flags": ["same_position_seen"],
            "frame_novel_buckets": [[0, 0], [1, 2], [3, 5], [6, 8]],
            "branches": ["zero_context_tail", "history_tail"],
            "groups": [
                "all",
                "selected_train",
                "unselected_train_previous_in_pool",
                "unselected_train_previous_not_in_pool",
                "development",
            ],
            "model_units": 0,
        },
        transfer_levels={
            "not_transferred_below": 0.10,
            "transferred_min": 0.80,
            "transferred_changed_min": 0.50,
        },
        regression={
            "reconstruction": "gate_passed_and_all_544_correct",
            "action_accuracy": "not_below_before",
            "action_nll_increase_max": {"1": 0.05, "4": 0.15},
        },
        expected_total_model_units=174208 + 4096 + 82080 + 4096,
        total_reserved_seconds_if_complete=1670,
        supervised_deadline_seconds=1720,
    )
    plan["seeds"].update(augmentation=2307, relabel_evaluation=9103)
    plan["resource_seconds"].update(
        m2l_paired_cells=300, m2l_relabel_pool=30, after_relabel_pool=30, verification=20
    )
    if learning_rate != 0.001:
        plan.update(
            protocol=RELABEL_LEARNING_RATES[learning_rate],
            learning_rate=learning_rate,
            comparison_caveat=(
                "single_factor_vs_M2m_stage_B_learning_rate_only_same_start_pool_schedule_"
                "permutations_seeds_gates"
            ),
            stage_b_comparison="cpu_only_from_saved_stage_b_cells_no_model_calls",
        )
    return plan


def validate_diverse_comparison(report, *, source, identity, queries):
    """Use only a completed frozen M2k report on the same source and queries."""
    from ainerzero.runtime.paired_memory_worker import paired_memory_plan

    if not isinstance(report, dict):
        raise ValueError("diverse comparison must be a report object")
    expected_source = {
        "checkpoint": source["checkpoint"],
        "checkpoint_manifest_sha256": source["checkpoint_manifest_sha256"],
        "run_id": source["parent_run_id"],
    }
    expected = {
        "status": "completed",
        "plan": paired_memory_plan(),
        "source": expected_source,
        "dataset": identity,
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "logical_model_transitions": 82176,
        "reserved_model_transitions": 82176,
        "weights_unchanged": True,
        "source_files_unchanged": True,
        "local_anchors_reproduced_exactly": True,
        "promoted": False,
        "checkpoint_saved": False,
    }
    paired = report.get("paired", {})
    run = report.get("run", {})
    if not isinstance(paired, dict) or not isinstance(run, dict):
        raise ValueError("diverse comparison requires paired and run objects")
    if (
        any(report.get(k) != v or type(report.get(k)) is not type(v) for k, v in expected.items())
        or run.get("state") != "completed"
        or not report.get("run_id")
        or run.get("run_id") != report["run_id"]
        or not report.get("manifest_hash")
        or paired.get("query_manifest_sha256") != queries["query_manifest_sha256"]
        or paired.get("first_edge_pairs_identical") is not True
        or type(paired.get("first_edge_pair_checks")) is not int
        or paired.get("first_edge_pair_checks") != 20
        or type(paired.get("logical_model_transitions")) is not int
        or paired.get("logical_model_transitions") != 82080
        or not isinstance(paired.get("per_query"), list)
        or len(paired.get("per_query", [])) != 2560
    ):
        raise ValueError("diverse memory requires completed M2k comparison on the same source/data")


def local_memory_screen(result, plan):
    """Whether this measured training micro-batch was fitted; never acceptance."""
    score = result["methods"]["memory_tail"]
    limits = plan["local_screen"]

    def passes(name, threshold):
        value = score.get(name)
        return type(value) in (int, float) and bool(np.isfinite(value)) and threshold <= value <= 1

    checks = {
        "overall_accuracy": passes("accuracy", limits["overall_accuracy_min"]),
        "changed_accuracy": passes("changed_accuracy", limits["changed_accuracy_min"]),
        "sufficient_changed_targets": type(score.get("changed_count")) is int
        and type(score.get("count")) is int
        and limits["minimum_changed_count"] <= score["changed_count"] <= score["count"],
        "training_fit_scope": result.get("partition") == "train"
        and result.get("scope") == "fixed_training_inputs_for_one_edge_memory_fit",
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "scope": "fixed_train_examples_fit_only",
        "promotion": False,
    }


def memory_screen(result, plan):
    """Development screen only; never promotes a model or claims general memory."""
    score = result["methods"]["memory_tail"]
    limits = plan["screen"]
    changed = score["changed_count"]

    def accuracy(value):
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and np.isfinite(value)
            and 0 <= value <= 1
        )

    measured = [
        w["methods"]["memory_tail"]
        for w in result["per_world"]
        if w["methods"]["memory_tail"]["changed_count"] > 0
    ]
    checks = {
        "sufficient_changed_targets": changed >= limits["minimum_changed_count"],
        "overall_accuracy": accuracy(score["accuracy"])
        and score["accuracy"] >= limits["overall_accuracy_min"],
        "changed_accuracy": accuracy(score["changed_accuracy"])
        and score["changed_accuracy"] >= limits["changed_accuracy_min"],
        "beats_current_and_reset_changed": accuracy(score["changed_accuracy"])
        and all(
            result["methods"][name]["changed_count"] == changed
            and accuracy(result["methods"][name]["changed_accuracy"])
            and score["changed_accuracy"] > result["methods"][name]["changed_accuracy"]
            for name in ("copy_current", "reset_history")
        ),
        "each_measured_world": bool(measured)
        and sum(w["changed_count"] for w in measured) == changed
        and all(
            accuracy(w["changed_accuracy"])
            and w["changed_accuracy"] >= limits["per_world_changed_accuracy_min"]
            for w in measured
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "scope": "reused_development_one_step_retention_only",
        "promotion": False,
    }


def _compare_m2l_paired(observed, expected):
    """The frozen M2l candidate must reproduce its own paired report exactly."""
    for field in ("query_manifest_sha256", "random_schedule_sha256", "seed", "particles"):
        if observed.get(field) != expected.get(field):
            raise RuntimeError(f"M2l paired reproduction differs in {field}")
    if observed["logical_model_transitions"] != 82080 or len(observed["per_query"]) != len(
        expected["per_query"]
    ):
        raise RuntimeError("M2l paired reproduction has the wrong size")
    for row, reference in zip(observed["per_query"], expected["per_query"], strict=True):
        if row != reference:
            raise RuntimeError(
                f"M2l paired score did not reproduce exactly at row {reference['row']}"
            )
    if observed["groups"] != expected["groups"] or observed["per_world"] != expected["per_world"]:
        raise RuntimeError("M2l paired group or world summaries did not reproduce exactly")
    return {
        "exact_match": True,
        "queries": len(observed["per_query"]),
        "random_schedule_sha256": observed["random_schedule_sha256"],
        "logical_model_transitions": observed["logical_model_transitions"],
    }


def _prepare_relabel(
    config,
    episodes,
    identity,
    source,
    source_metadata,
    fixed_samples,
    pool,
    training_evidence,
    queries,
    m2l_report_path,
    m2l_checkpoint_path,
):
    """CPU-only binding to the completed M2l candidate plus all relabel evidence."""
    from ainerzero.learning.coverage_diagnostic import (
        classify_query_cells,
        pool_position_symbol_sets,
        query_frames,
        query_labels,
    )
    from ainerzero.learning.micro_memory import _batch_digest
    from ainerzero.learning.relabel_memory import (
        relabel_evaluation_pool,
        training_permutation_manifest,
    )
    from ainerzero.runtime.coverage_worker import POOL_FIELDS, validate_coverage_source

    m2l_tensors, m2l_metadata = load_checkpoint(m2l_checkpoint_path)
    m2l_report_bytes = m2l_report_path.read_bytes()
    m2l_report = json.loads(m2l_report_bytes)
    m2l_candidate = {
        "checkpoint": str(m2l_checkpoint_path.resolve()),
        "run_id": m2l_metadata["run_id"],
        "checkpoint_manifest_sha256": hashlib.sha256(
            (m2l_checkpoint_path / "manifest.json").read_bytes()
        ).hexdigest(),
    }
    validate_coverage_source(
        source_metadata,
        m2l_metadata,
        config.model_dump(mode="json"),
        identity,
        source,
        m2l_candidate,
        m2l_report,
        fixed_samples,
        training_evidence,
        queries,
    )
    run_directory = m2l_checkpoint_path.resolve().parents[1]
    pool_path = run_directory / "training-pool.npz"
    if m2l_report.get("run_directory") != str(run_directory) or m2l_report.get(
        "training_pool_path"
    ) != str(pool_path):
        raise ValueError("M2l pool must be the archive saved beside the M2l checkpoint")
    pool_bytes = pool_path.read_bytes()
    with np.load(pool_path, allow_pickle=False) as archive:
        saved = {name: archive[name] for name in archive.files}
    if (
        set(saved) != set(POOL_FIELDS)
        or any(
            saved[k].dtype != pool[k].dtype or not np.array_equal(saved[k], pool[k])
            for k in POOL_FIELDS
        )
        or _batch_digest(saved) != training_evidence["batch_sha256"]
    ):
        raise ValueError("saved M2l training pool differs from the rebuilt registered pool")
    frames, frame_evidence = query_frames(episodes)
    if frame_evidence["query_manifest_sha256"] != queries["query_manifest_sha256"]:
        raise ValueError("query frames changed after registration")
    labels = query_labels(frame_evidence["queries"], training_evidence)
    symbol_sets = pool_position_symbol_sets(pool)
    classification = classify_query_cells(frames, symbol_sets)
    positions = {
        (row["episode_id"], row["query_tick"]): index
        for index, row in enumerate(frame_evidence["queries"])
    }
    pool_query_rows = [
        positions[(row["episode_id"], row["query_tick"])] for row in training_evidence["samples"]
    ]
    seeds = [
        m2l_report["paired"]["per_query"][row]["paired_random_seeds"] for row in pool_query_rows
    ]
    training_manifest = training_permutation_manifest()
    if training_manifest["unique_count"] != training_manifest["count"]:
        raise ValueError("registered training bijections must be distinct")
    batch, evaluation = relabel_evaluation_pool(pool, training_manifest)
    m2l_reference = {
        "report": {
            "path": str(m2l_report_path.resolve()),
            "sha256": hashlib.sha256(m2l_report_bytes).hexdigest(),
            "run_id": m2l_report["run_id"],
            "experiment_id": m2l_report.get("experiment_id"),
            "manifest_hash": m2l_report["manifest_hash"],
        },
        "candidate": m2l_candidate,
        "training_pool": {
            "path": str(pool_path),
            "sha256": hashlib.sha256(pool_bytes).hexdigest(),
            "batch_sha256": training_evidence["batch_sha256"],
        },
    }
    coverage = {
        "symbol_sets": symbol_sets,
        "classification_sha256": classification["classification_sha256"],
        "query_label_sha256": hashlib.sha256(json.dumps(labels).encode()).hexdigest(),
        "pool_query_rows": pool_query_rows,
        "pool_row_seeds": seeds,
    }
    summary = {
        "m2l": m2l_reference,
        "coverage": coverage,
        "training_permutations": training_manifest,
        "relabel_evaluation": evaluation,
    }
    return {
        "declaration": summary,
        "report": {
            "m2l": m2l_reference,
            "coverage": {k: v for k, v in coverage.items() if k != "pool_row_seeds"},
            "training_permutations_sha256": training_manifest["manifest_sha256"],
            "relabel_evaluation": {k: v for k, v in evaluation.items() if k != "digests"},
        },
        "m2l_report": m2l_report,
        "m2l_report_bytes": m2l_report_bytes,
        "m2l_tensors": m2l_tensors,
        "m2l_candidate": m2l_candidate,
        "pool_path": pool_path,
        "pool_bytes": pool_bytes,
        "training_manifest": training_manifest,
        "batch": batch,
        "seeds": seeds,
        "pool_query_rows": pool_query_rows,
        "classification": classification,
        "labels": labels,
        "targets": frames["previous_symbols"],
    }


def run_memory(
    config_path,
    dataset_path,
    checkpoint_path,
    output_root,
    control_db,
    experiment_id,
    *,
    local_fit=False,
    diverse_fit=False,
    comparison_report_path=None,
    relabel_fit=False,
    m2l_report_path=None,
    m2l_checkpoint_path=None,
    relabel_learning_rate=None,
):
    from ainerzero.cli import pilot_manifest

    started = time.perf_counter()
    if diverse_fit and local_fit:
        raise ValueError("choose one memory training protocol")
    if relabel_fit and (diverse_fit or local_fit):
        raise ValueError("choose one memory training protocol")
    if bool(relabel_fit) != (m2l_report_path is not None) or bool(relabel_fit) != (
        m2l_checkpoint_path is not None
    ):
        raise ValueError("relabel memory requires exactly its M2l report and checkpoint")
    if relabel_learning_rate is not None and not relabel_fit:
        raise ValueError("learning rate variant applies only to relabel memory")
    diverse_fit = diverse_fit or relabel_fit
    if bool(diverse_fit) != (comparison_report_path is not None):
        raise ValueError("diverse memory requires its M2k comparison report only")
    local_fit = local_fit or diverse_fit
    config = load_pilot_config(config_path)
    plan = (
        relabel_memory_plan(0.001 if relabel_learning_rate is None else relabel_learning_rate)
        if relabel_fit
        else diverse_memory_plan()
        if diverse_fit
        else micro_memory_plan()
        if local_fit
        else memory_plan()
    )
    phase_name = (
        "relabel_memory_fit"
        if relabel_fit
        else "diverse_memory_fit"
        if diverse_fit
        else "micro_memory_fit"
        if local_fit
        else "one_step_memory"
    )
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    paths, episodes, identity = load_pilot_dataset(dataset_path, policy)
    source_tensors, source_metadata = load_checkpoint(checkpoint_path)
    validate_history_source(source_metadata, config.model_dump(mode="json"), identity)
    fixed_batch = sample_evidence = None
    if local_fit:
        from ainerzero.learning.micro_memory import select_micro_memory_samples

        fixed_batch, sample_evidence = select_micro_memory_samples(episodes["train"])
    source = {
        "checkpoint": str(checkpoint_path.resolve()),
        "parent_run_id": source_metadata["run_id"],
        "checkpoint_manifest_sha256": hashlib.sha256(
            (checkpoint_path / "manifest.json").read_bytes()
        ).hexdigest(),
        "dataset": identity,
    }
    diverse_pool = training_evidence = comparison = comparison_bytes = None
    if diverse_fit:
        from ainerzero.learning.diverse_evaluation import summarize_diverse_pairs
        from ainerzero.learning.diverse_memory import (
            diverse_training_schedule,
            get_diverse_batch,
            select_diverse_memory_samples,
        )
        from ainerzero.learning.paired_memory import evaluate_paired_memory, paired_memory_samples

        diverse_pool, training_evidence = select_diverse_memory_samples(episodes["train"])
        queries = paired_memory_samples(episodes)
        comparison_bytes = comparison_report_path.read_bytes()
        comparison = json.loads(comparison_bytes)
        validate_diverse_comparison(comparison, source=source, identity=identity, queries=queries)
        # CPU-only regrouping: both candidates will use the same new selection labels.
        comparison_groups = summarize_diverse_pairs(comparison["paired"], training_evidence)
        comparison_reference = {
            "path": str(comparison_report_path.resolve()),
            "sha256": hashlib.sha256(comparison_bytes).hexdigest(),
            "run_id": comparison["run_id"],
        }
    relabel = None
    if relabel_fit:
        relabel = _prepare_relabel(
            config,
            episodes,
            identity,
            source,
            source_metadata,
            sample_evidence,
            diverse_pool,
            training_evidence,
            queries,
            m2l_report_path,
            m2l_checkpoint_path,
        )
    declaration = pilot_manifest(config_path)["manifest"]
    declaration.update(
        purpose=f"c0_{phase_name}_training_v1",
        one_step_memory=plan,
        source=declaration["source"],
        student_source=source,
    )
    if local_fit:
        declaration["fixed_samples"] = sample_evidence
    if diverse_fit:
        declaration.update(
            training_samples=training_evidence,
            paired_samples=queries,
            comparison_report=comparison_reference,
        )
    if relabel_fit:
        declaration.update(relabel=relabel["declaration"])
    directory = Path(output_root) / f"pilot-{uuid4().hex}"
    directory.mkdir(parents=True)
    report_path = directory / "report.json"
    report = {
        "status": "running",
        "experiment_id": experiment_id,
        "plan": plan,
        "source": source,
        "dataset": str(dataset_path.resolve()),
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "training_model_transitions": 0,
        "before": {},
        "after": {},
        "promoted": False,
        "run_directory": str(directory.resolve()),
        "report_path": str(report_path.resolve()),
    }
    if local_fit:
        report.update(
            fixed_samples=sample_evidence,
            local_checks={},
            effective_trainable_parameter_count=111104,
            frozen_parameter_count=282128,
            tail_protection_checks=0,
        )
    if diverse_fit:
        report.update(
            training_samples=training_evidence,
            comparison_report=comparison_reference,
            comparison_groups=comparison_groups,
        )
    if relabel_fit:
        report.update(
            relabel=relabel["report"],
            relabel_pool={},
            before_matches_m2l=None,
        )
    store = RunStore(control_db)
    run_id = None
    model = optimizer = None
    stage_started = stage_seconds = None
    last_guard = last_power = 0.0
    initial_swap = psutil.swap_memory().used
    completed_units = 0
    reserved_units = 0

    def persist():
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)

    def guard(force=False):
        nonlocal last_guard, last_power
        now = time.monotonic()
        if stage_started is not None and time.perf_counter() - stage_started > stage_seconds:
            raise RuntimeError("memory experiment exceeded prepaid stage window")
        if time.perf_counter() - started > plan["supervised_deadline_seconds"]:
            raise RuntimeError("memory experiment reached supervised deadline")
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("memory experiment system memory reserve reached")
        if psutil.Process().memory_info().rss > config.resources.active.project_memory_gib * 2**30:
            raise RuntimeError("memory experiment process memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("memory experiment swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("memory experiment disk reserve reached")
        if force or now - last_power > 15:
            power = subprocess.run(
                ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5, check=True
            ).stdout
            if "AC Power" not in power:
                raise RuntimeError("memory experiment requires AC power")
            last_power = now

    def stage(name, *, updates=0, units=0):
        nonlocal stage_started, stage_seconds, reserved_units
        guard(force=True)
        stage_seconds = plan["resource_seconds"][name]
        store.consume(
            run_id, active_seconds=stage_seconds, optimizer_steps=updates, model_transitions=units
        )
        reserved_units += units
        stage_started = time.perf_counter()
        report["current_stage"] = name
        persist()

    def reserve(count):
        nonlocal reserved_units
        guard()
        store.consume(run_id, model_transitions=count)
        reserved_units += count

    try:
        guard(force=True)
        if diverse_fit:
            prior = store.get_run(comparison["run_id"])
            prior_experiment = store.get_experiment(prior.experiment_id)
            if (
                prior.state != "completed"
                or prior.experiment_id != comparison.get("experiment_id")
                or prior.role != "auxiliary"
                or prior.reserved_optimizer_steps != 0
                or prior.reserved_model_transitions != 82176
                or prior_experiment.manifest_hash != comparison["manifest_hash"]
            ):
                raise ValueError("canonical ledger does not confirm M2k comparison")
        if relabel_fit:
            m2l_report = relabel["m2l_report"]
            prior = store.get_run(m2l_report["run_id"])
            prior_experiment = store.get_experiment(prior.experiment_id)
            if (
                prior.state != "completed"
                or prior.experiment_id != m2l_report.get("experiment_id")
                or prior.role != "model"
                or prior.reserved_optimizer_steps != 200
                or prior.reserved_environment_steps != 0
                or prior.reserved_model_transitions != 174208
                or prior_experiment.manifest_hash != m2l_report["manifest_hash"]
            ):
                raise ValueError("canonical ledger does not confirm the completed M2l candidate")
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        atomic_write_json(directory / "preregistration.json", declaration)
        run_id = str(uuid4())
        snapshot = config.snapshot_for_run(0)
        snapshot["one_step_memory"] = {"plan": plan, "source": source}
        store.create_run(snapshot, run_id, run_id=run_id, experiment_id=experiment_id, role="model")
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        report.update(run_id=run_id, manifest_hash=experiment.manifest_hash)
        stage("compatibility")
        if local_fit:
            np.savez(directory / "fixed-batch.npz", **fixed_batch)
            report["fixed_batch_path"] = str((directory / "fixed-batch.npz").resolve())
        if diverse_fit:
            np.savez(directory / "training-pool.npz", **diverse_pool)
            np.save(directory / "training-schedule.npy", diverse_training_schedule())
            report["training_pool_path"] = str((directory / "training-pool.npz").resolve())
            report["training_schedule_path"] = str((directory / "training-schedule.npy").resolve())
        report["codec_compatibility"] = audit_bounded_codec(
            source_tensors["model.byte_embedding.weight"],
            source_tensors["model.symbol_readout.weight"],
            source_tensors["model.symbol_readout.bias"],
        )
        persist()
        if not report["codec_compatibility"]["bounded_codec_compatible"]:
            raise RuntimeError(
                "bounded frozen codec compatibility check failed; no student updates"
            )

        stage("initialization")
        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten, tree_map, tree_unflatten

        from ainerzero.learning.evaluation import evaluate_predictor
        from ainerzero.learning.one_step_memory import (
            evaluate_one_step_memory,
            memory_sequence_loss,
        )
        from ainerzero.learning.pilot_model import SharedSymbolPredictor
        from ainerzero.learning.reconstruction import evaluate_reconstruction

        if not mx.metal.is_available():
            raise RuntimeError("Metal unavailable; no CPU fallback")
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(int(config.resources.active.mlx_memory_gib * 2**30))
        mx.set_cache_limit(int(config.resources.active.mlx_cache_gib * 2**30))
        mx.reset_peak_memory()
        model = SharedSymbolPredictor(config.model, key=mx.random.key(999))
        expected = {f"model.{k}": v.shape for k, v in tree_flatten(model.parameters())}
        if {k: v.shape for k, v in source_tensors.items() if k.startswith("model.")} != expected:
            raise ValueError("memory source parameter keys/shapes mismatch")
        model.update(
            tree_unflatten(
                [(k[6:], mx.array(v)) for k, v in source_tensors.items() if k.startswith("model.")]
            )
        )
        model.freeze()
        model.gru.unfreeze()
        mx.eval(model.parameters())
        trainable = dict(tree_flatten(model.trainable_parameters()))
        report["parameter_count"] = sum(v.size for _, v in tree_flatten(model.parameters()))
        report["trainable_parameter_count"] = sum(v.size for v in trainable.values())
        report["trainable_keys"] = sorted(trainable)
        if (
            set(trainable) != {"gru.Wx", "gru.Wh", "gru.b", "gru.bhn"}
            or report["trainable_parameter_count"] != 222208
            or report["parameter_count"] != 393232
        ):
            raise RuntimeError("memory experiment trainable scope or parameter count mismatch")
        if local_fit:
            from ainerzero.learning.micro_memory import evaluate_micro_memory
            from ainerzero.learning.tail_update import (
                mask_gru_tail_gradients,
                project_gru_front,
                verify_tail_update,
            )

            # MLX exposes full GRU tensors; only their tail rows may actually change.
            report["optimizer_tensor_parameter_count"] = report["trainable_parameter_count"]
            report["trainable_parameter_count"] = plan["trainable_parameter_count"]
            verify_tail_update(
                source_tensors,
                {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())},
            )
        optimizer = optim.AdamW(
            learning_rate=plan["learning_rate"],
            betas=config.training.adam_betas,
            eps=config.training.adam_epsilon,
            weight_decay=config.training.weight_decay,
            bias_correction=True,
        )
        optimizer.init(model.trainable_parameters())
        mx.eval(optimizer.state)
        sampler = (
            None
            if local_fit
            else SequenceSampler(
                paths["train"],
                policy,
                burn_in=plan["burn_in"],
                sequence_steps=plan["sequence_steps"],
            )
        )
        baseline = NoActionBaseline(policy).fit(episodes["train"])

        def evaluate_phase(phase):
            nonlocal completed_units
            for partition in ("train", "development"):
                stage(f"{phase}_memory_{partition}")
                result = evaluate_one_step_memory(
                    model,
                    episodes[partition],
                    partition=partition,
                    before_work=reserve,
                    seed=plan["seeds"][f"memory_{partition}"],
                    support_ticks=32,
                    particles=8,
                )
                report[phase][f"memory_{partition}"] = result
                completed_units += result["logical_model_transitions"]
                guard(force=True)
                persist()
            stage(f"{phase}_action")
            report[phase]["action"] = evaluate_predictor(
                model, episodes["development"], baseline, before_work=reserve
            )
            completed_units += report[phase]["action"]["logical_model_transitions"]
            guard(force=True)
            stage(f"{phase}_reconstruction")
            report[phase]["reconstruction"] = evaluate_reconstruction(
                model, episodes["development"], before_work=reserve
            )
            completed_units += report[phase]["reconstruction"]["observation_encodes"]
            guard(force=True)
            persist()

        def evaluate_local(update):
            nonlocal completed_units
            if not local_fit:
                return
            results = report["local_checks"][str(update)] = {}
            for name, seed in (
                ("training_noise", plan["seeds"]["latent"]),
                ("same_inputs_new_noise", plan["seeds"]["local_new_noise"]),
            ):
                stage("local_check")
                results[name] = evaluate_micro_memory(
                    model,
                    fixed_batch,
                    seed=seed,
                    before_work=reserve,
                    micro_batch_size=plan["micro_batch_size"],
                )
                if results[name]["logical_model_transitions"] != plan["local_check_model_units"]:
                    raise RuntimeError("local memory evaluation exceeded fixed model units")
                completed_units += results[name]["logical_model_transitions"]
                guard(force=True)
                persist()

        if relabel_fit:
            from ainerzero.learning.paired_memory import evaluate_zero_context_inputs
            from ainerzero.learning.relabel_memory import summarize_relabel_pool

            stage("m2l_paired_cells")
            reference = SharedSymbolPredictor(config.model, key=mx.random.key(999))
            reference.update(
                tree_unflatten(
                    [
                        (k[6:], mx.array(v))
                        for k, v in relabel["m2l_tensors"].items()
                        if k.startswith("model.")
                    ]
                )
            )
            reference.freeze()
            mx.eval(reference.parameters())
            loaded = {f"model.{k}": np.array(v) for k, v in tree_flatten(reference.parameters())}
            if set(loaded) != {k for k in relabel["m2l_tensors"] if k.startswith("model.")} or any(
                not np.array_equal(v, relabel["m2l_tensors"][k]) for k, v in loaded.items()
            ):
                raise RuntimeError("frozen M2l comparison weights did not load exactly")
            m2l_paired = evaluate_paired_memory(
                reference,
                episodes,
                before_work=reserve,
                cell_outputs=True,
                **plan["paired_evaluation"],
            )
            completed_units += m2l_paired["logical_model_transitions"]
            m2l_cells = m2l_paired.pop("per_query_cells")
            report["m2l_paired_reproduction"] = _compare_m2l_paired(
                m2l_paired, relabel["m2l_report"]["paired"]
            )
            guard(force=True)
            persist()
            stage("m2l_relabel_pool")
            scored = evaluate_zero_context_inputs(
                reference, relabel["batch"], relabel["seeds"], before_work=reserve
            )
            completed_units += scored["logical_model_transitions"]
            report["relabel_pool"]["m2l"] = summarize_relabel_pool(
                scored["argmax"], scored["nll"], relabel["batch"]
            )
            report["relabel_pool"]["m2l_cells"] = {
                "argmax": scored["argmax"].tolist(),
                "nll": [[None if np.isnan(v) else float(v) for v in row] for row in scored["nll"]],
            }
            del reference
            guard(force=True)
            persist()
        evaluate_phase("before")
        if relabel_fit:
            report["before_matches_m2l"] = report["before"] == relabel["m2l_report"]["before"]
        if report["before"]["reconstruction"]["gate"]["status"] != "passed":
            raise RuntimeError("source current-observation reconstruction gate failed")
        evaluate_local(0)
        window_rng = None if local_fit else np.random.default_rng(plan["seeds"]["windows"])
        augmentation_rng = (
            np.random.default_rng(plan["seeds"]["augmentation"])
            if relabel_fit or not local_fit
            else None
        )
        key = mx.random.key(plan["seeds"]["latent"])
        value_grad = nn.value_and_grad(model, memory_sequence_loss)
        store.transition(run_id, "training")
        for index in range(plan["updates"]):
            stage("training_update", updates=1, units=plan["training_model_units_per_update"])
            tick = time.perf_counter()
            permutation_digests = None
            if local_fit:
                batch = get_diverse_batch(diverse_pool, index) if diverse_fit else fixed_batch
                if relabel_fit:
                    from ainerzero.learning.relabel_memory import relabel_batch

                    batch, permutation_digests = relabel_batch(batch, augmentation_rng)
                    registered = relabel["training_manifest"]["digests"][
                        index * plan["batch_size"] : (index + 1) * plan["batch_size"]
                    ]
                    if permutation_digests != registered:
                        raise RuntimeError(
                            "training bijections differ from the registered manifest"
                        )
                sample_key = key  # Fixed training noise is part of the local-fit diagnostic.
            else:
                batch = permute_symbols(
                    sampler.sample(plan["batch_size"], window_rng), augmentation_rng
                )
                key, sample_key = mx.random.split(key)
            micro = plan["micro_batch_size"]
            parts_count = plan["batch_size"] // micro
            keys = mx.random.split(sample_key, parts_count)
            gradients, total, target_count = None, 0.0, 0.0
            for part in range(parts_count):
                data = {k: mx.array(v[part * micro : (part + 1) * micro]) for k, v in batch.items()}
                (loss, metrics), grads = value_grad(
                    model, data, burn_in=plan["burn_in"], key=keys[part]
                )
                mx.eval(loss, metrics, grads)
                visible = float(metrics["visible_targets"].item())
                target_count += visible
                total += float(loss.item()) * visible
                scaled = tree_map(lambda g: g * visible, grads)
                gradients = (
                    scaled if gradients is None else tree_map(lambda a, b: a + b, gradients, scaled)
                )
                mx.eval(gradients)
                guard()
            if target_count <= 0:
                raise RuntimeError("memory training batch has no supervised visible targets")
            gradients = tree_map(lambda g: g / target_count, gradients)
            total /= target_count
            flat_grad = dict(tree_flatten(gradients))
            if (
                set(flat_grad) != set(trainable)
                or not np.isfinite(total)
                or not all(np.isfinite(np.asarray(v)).all() for v in flat_grad.values())
            ):
                raise RuntimeError("memory gradient scope or finite check failed")
            raw_front_gradient_l2 = None
            if local_fit:
                masked = mask_gru_tail_gradients(gradients)
                raw_front_gradient_l2 = float(
                    np.sqrt(
                        sum(
                            np.sum(
                                (np.asarray(flat_grad[k]) - np.asarray(v)) ** 2, dtype=np.float64
                            )
                            for k, v in tree_flatten(masked)
                        )
                    )
                )
                if not np.isfinite(raw_front_gradient_l2) or raw_front_gradient_l2 > 1e-8:
                    raise RuntimeError("single-edge memory unexpectedly has front-output gradients")
                gradients = masked
            gradients, norm = optim.clip_grad_norm(gradients, config.training.gradient_clip_norm)
            optimizer.update(model, gradients)
            if local_fit:
                # Gradient masking alone does not stop AdamW's front-row weight decay.
                project_gru_front(model, source_tensors)
            mx.eval(model.parameters(), optimizer.state, norm, key)
            report["actual_optimizer_steps"] += 1
            report["training_model_transitions"] += plan["training_model_units_per_update"]
            if local_fit:
                report["latest_tail_protection"] = verify_tail_update(
                    source_tensors,
                    {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())},
                )
                report["tail_protection_checks"] += 1
            elapsed = time.perf_counter() - tick
            entry = {
                "update": index + 1,
                "loss": total,
                "gradient_norm": float(norm.item()),
                "compute_seconds": elapsed,
            }
            if local_fit:
                entry.update(
                    raw_front_gradient_l2=raw_front_gradient_l2, frozen_parameters_verified=True
                )
            if diverse_fit:
                entry["training_sample_rows"] = diverse_training_schedule()[index].tolist()
            if relabel_fit:
                entry["permutation_sha256"] = permutation_digests
            with (directory / "updates.jsonl").open("a") as stream:
                stream.write(json.dumps(entry, allow_nan=False) + "\n")
            report["latest_update"] = entry
            guard(force=True)
            # Duty-cycle idle is not active compute; whole-run deadline still applies.
            stage_started = None
            persist()
            rest = elapsed * (1 / config.resources.active.training_duty_cycle - 1)
            idle_until = time.monotonic() + rest
            while time.monotonic() < idle_until:
                time.sleep(min(1.0, max(0.0, idle_until - time.monotonic())))
                guard()
            if local_fit and index + 1 in plan["local_checks"]:
                evaluate_local(index + 1)
        store.transition(run_id, "validating")
        if diverse_fit:
            model.freeze()
            if tree_flatten(model.trainable_parameters()):
                raise RuntimeError("diverse candidate must be frozen for final evaluations")
        evaluate_phase("after")
        report["memory_screen"] = memory_screen(report["after"]["memory_development"], plan)
        if local_fit:
            report["local_screens"] = {
                name: local_memory_screen(result, plan)
                for name, result in report["local_checks"][str(plan["updates"])].items()
            }
        if diverse_fit:
            stage("after_paired")
            report["paired"] = evaluate_paired_memory(
                model,
                episodes,
                before_work=reserve,
                **plan["paired_evaluation"],
                **({"cell_outputs": True} if relabel_fit else {}),
            )
            completed_units += report["paired"]["logical_model_transitions"]
            m2m_cells = report["paired"].pop("per_query_cells", None)
            if report["paired"]["query_manifest_sha256"] != queries["query_manifest_sha256"]:
                raise RuntimeError("diverse paired query identities changed after registration")
            report["diverse_groups"] = summarize_diverse_pairs(report["paired"], training_evidence)
            guard(force=True)
            persist()
        if relabel_fit:
            from ainerzero.learning.relabel_memory import (
                compare_strata,
                next_step,
                regression_flags,
                transfer_level,
            )

            if [
                report["paired"]["per_query"][row]["paired_random_seeds"]
                for row in relabel["pool_query_rows"]
            ] != relabel["seeds"]:
                raise RuntimeError("relabel pool keys differ from the paired pool-row keys")
            stage("after_relabel_pool")
            scored = evaluate_zero_context_inputs(
                model, relabel["batch"], relabel["seeds"], before_work=reserve
            )
            completed_units += scored["logical_model_transitions"]
            report["relabel_pool"]["m2m"] = summarize_relabel_pool(
                scored["argmax"], scored["nll"], relabel["batch"]
            )
            report["relabel_pool"]["m2m_cells"] = {
                "argmax": scored["argmax"].tolist(),
                "nll": [[None if np.isnan(v) else float(v) for v in row] for row in scored["nll"]],
            }
            report["cells"] = {"m2m": m2m_cells, "m2l": m2l_cells}
            report["stratified"] = compare_strata(
                relabel["classification"],
                relabel["labels"],
                relabel["targets"],
                m2m_cells,
                m2l_cells,
            )
            report["regression"] = regression_flags(report["before"], report["after"])
            development = report["paired"]["groups"]["development"]["methods"]["zero_context_tail"]
            report["transfer"] = next_step(
                all(item["status"] == "passed" for item in report["local_screens"].values()),
                transfer_level(development),
                transfer_level(report["relabel_pool"]["m2m"]),
                report["regression"]["regression"],
            )
            guard(force=True)
            persist()

        stage("checkpoint")
        saved = {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
        saved.update({f"optimizer.{k}": np.array(v) for k, v in tree_flatten(optimizer.state)})
        saved["rng.mlx_key"] = np.array(key)
        checkpoint = save_checkpoint(
            directory / "checkpoints",
            run_id,
            saved,
            {
                "architecture": "pilot_shared_symbol_v1",
                "phase": phase_name,
                "config": config.model_dump(mode="json"),
                "plan": plan,
                "dataset_source": identity,
                "run_id": run_id,
                "manifest_hash": experiment.manifest_hash,
                "optimizer_steps": report["actual_optimizer_steps"],
                "source": source,
                "rng_states": {
                    "fixed_seed": plan["seeds"]["latent"],
                    "augmentation": augmentation_rng.bit_generator.state,
                }
                if relabel_fit
                else {"fixed_seed": plan["seeds"]["latent"]}
                if local_fit
                else {
                    "windows": window_rng.bit_generator.state,
                    "augmentation": augmentation_rng.bit_generator.state,
                },
                "fixed_samples": sample_evidence,
                **({"training_samples": training_evidence} if diverse_fit else {}),
                **(
                    {
                        "relabel_training_permutations_sha256": relabel["training_manifest"][
                            "manifest_sha256"
                        ]
                    }
                    if relabel_fit
                    else {}
                ),
                "sampler": {"burn_in": plan["burn_in"], "sequence_steps": plan["sequence_steps"]},
                "readout_protocol": plan["readout"],
                "optimizer": {
                    "kind": "AdamW",
                    "learning_rate": plan["learning_rate"],
                    "betas": list(config.training.adam_betas),
                    "eps": config.training.adam_epsilon,
                    "weight_decay": config.training.weight_decay,
                    "bias_correction": True,
                },
                "state_scope": "offline_windows_start_zero_no_persistent_session; cross_process_training_resume_not_verified",
            },
        )
        restored, metadata = load_checkpoint(checkpoint)
        report["checkpoint"] = str(checkpoint.resolve())
        report["checkpoint_verified"] = (
            set(saved) == set(restored)
            and all(np.array_equal(v, restored[k]) for k, v in saved.items())
            and metadata["optimizer_steps"] == plan["updates"]
        )
        if not report["checkpoint_verified"]:
            raise RuntimeError("memory checkpoint roundtrip failed")
        guard(force=True)
        stage("verification")
        changed = [
            k
            for k, v in saved.items()
            if k.startswith("model.") and not np.array_equal(v, source_tensors[k])
        ]
        report["changed_model_tensors"] = sorted(changed)
        report["frozen_modules_unchanged"] = all(k.startswith("model.gru.") for k in changed)
        report["logical_model_transitions"] = completed_units + report["training_model_transitions"]
        if report["logical_model_transitions"] != reserved_units:
            raise RuntimeError("memory measured work differs from reserved model units")
        if local_fit:
            report["tail_protection"] = verify_tail_update(source_tensors, saved)
            if report["logical_model_transitions"] != plan["expected_total_model_units"]:
                raise RuntimeError("micro memory model units differ from fixed plan")
        if diverse_fit:
            load_checkpoint(checkpoint_path)  # Revalidate source weights against their manifest.
            report["source_files_unchanged"] = (
                comparison_report_path.read_bytes() == comparison_bytes
                and hashlib.sha256((checkpoint_path / "manifest.json").read_bytes()).hexdigest()
                == source["checkpoint_manifest_sha256"]
            )
            if relabel_fit:
                load_checkpoint(m2l_checkpoint_path)
                report["source_files_unchanged"] = report["source_files_unchanged"] and (
                    m2l_report_path.read_bytes() == relabel["m2l_report_bytes"]
                    and hashlib.sha256(
                        (m2l_checkpoint_path / "manifest.json").read_bytes()
                    ).hexdigest()
                    == relabel["m2l_candidate"]["checkpoint_manifest_sha256"]
                    and relabel["pool_path"].read_bytes() == relabel["pool_bytes"]
                )
            if not report["source_files_unchanged"]:
                raise RuntimeError("diverse source checkpoint or comparison report changed")
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        if not report["frozen_modules_unchanged"] or not changed:
            raise RuntimeError("memory training changed wrong tensors or did not update GRU")
        if report["after"]["reconstruction"]["gate"]["status"] != "passed":
            raise RuntimeError("memory candidate failed reconstruction regression gate")
        guard(force=True)
        store.transition(
            run_id, "completed", reason=f"{phase_name}_experiment_complete_no_promotion"
        )
        report.update(status="completed", current_stage="completed")
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason=f"{phase_name}_failure")
    finally:
        report["reserved_model_transitions"] = reserved_units
        if run_id is not None:
            report["run"] = store.get_run(run_id).to_dict()
        store.close()
        persist()
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in ("config", "dataset", "checkpoint", "output-dir", "control-db"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--local-fit", action="store_true")
    parser.add_argument("--diverse-fit", action="store_true")
    parser.add_argument("--comparison-report", type=Path)
    parser.add_argument("--relabel-fit", action="store_true")
    parser.add_argument("--m2l-report", type=Path)
    parser.add_argument("--m2l-checkpoint", type=Path)
    parser.add_argument("--relabel-learning-rate", choices=("0.001", "0.003"))
    args = parser.parse_args()
    report = run_memory(
        args.config,
        args.dataset,
        args.checkpoint,
        args.output_dir,
        args.control_db,
        args.experiment_id,
        local_fit=args.local_fit,
        diverse_fit=args.diverse_fit,
        comparison_report_path=args.comparison_report,
        relabel_fit=args.relabel_fit,
        m2l_report_path=args.m2l_report,
        m2l_checkpoint_path=args.m2l_checkpoint,
        relabel_learning_rate=(
            None if args.relabel_learning_rate is None else float(args.relabel_learning_rate)
        ),
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
