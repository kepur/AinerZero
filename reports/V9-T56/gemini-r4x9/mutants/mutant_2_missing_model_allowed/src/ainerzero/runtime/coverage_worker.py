"""M2m-a: frozen zero-update coverage and single-slot interference diagnosis of M2l."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil

from ainerzero.core.experience import TrainingPolicy
from ainerzero.core.pilot import load_pilot_config
from ainerzero.data.pilot_dataset import load_pilot_dataset
from ainerzero.learning.coverage_diagnostic import (
    DECISION_RULES,
    NOVEL_BUCKETS,
    SUBSTITUTION_KINDS,
    SUBSTITUTION_SEED,
    VARIANT_COUNT,
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
from ainerzero.learning.diverse_memory import select_diverse_memory_samples
from ainerzero.learning.evaluation import _Summary
from ainerzero.learning.gru_intervention import _digest, _model_arrays
from ainerzero.learning.micro_memory import _batch_digest, select_micro_memory_samples
from ainerzero.learning.tail_update import verify_tail_update
from ainerzero.runtime.c0_collection import RANDOM_ACTOR
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint
from ainerzero.runtime.history_worker import validate_history_source
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore
from ainerzero.runtime.memory_worker import diverse_memory_plan

POOL_FIELDS = ("symbols", "visible_mask", "cursor", "episode_start", "actions")


def coverage_diagnostic_plan():
    seconds = {
        "validation": 15,
        "initialization": 15,
        "zero_context_cells": 150,
        "slot_substitution": 200,
        "cpu_audit": 15,
        "verification": 15,
    }
    units = {"zero_context_cells": 2560 * 2 * 8, "slot_substitution": VARIANT_COUNT * 2 * 8}
    return {
        "protocol": "m2ma_frozen_zero_context_coverage_and_single_slot_substitution_v1",
        "architecture": "pilot_shared_symbol_v1",
        "parameter_count": 393232,
        "optimizer_steps": 0,
        "new_environment_steps": 0,
        "automatic_promotion": False,
        "checkpoint_saved": False,
        "evaluation": {"seed": 7103, "particles": 8, "branch": "zero_context_tail_only"},
        "stratification": {
            "coverage_reference": "visible_previous_frame_targets_of_m2l_256_pool_rows",
            "flags": ["same_position_seen", "global_seen", "frame_novel_count"],
            "frame_novel_buckets": [[low, high] for _, low, high in NOVEL_BUCKETS],
            "groups": [
                "selected_train",
                "unselected_train_previous_in_pool",
                "unselected_train_previous_not_in_pool",
                "development",
            ],
        },
        "substitution": {
            "seed": SUBSTITUTION_SEED,
            "kinds": list(SUBSTITUTION_KINDS),
            "variant_count": VARIANT_COUNT,
            "keys": "same_paired_keys_as_the_pool_row_query_seed_7103",
            "baseline": "a1_zero_context_predictions_of_the_same_pool_queries",
        },
        "decision_rules": dict(DECISION_RULES),
        "expected_model_units": units,
        "expected_total_model_units": sum(units.values()),
        "resource_seconds": seconds,
        "total_reserved_seconds_if_complete": sum(seconds.values()),
        "supervised_deadline_seconds": 700,
        "supervisor_timeout_seconds": 750,
        "scope": "reused_public_train_and_development_edges_not_independent_acceptance",
        "selection": "fixed_queries_and_seeded_substitutions_no_result_dependent_choice",
        "interpretation": "diagnostic_only_no_training_no_stage_b_launch_no_promotion",
    }


def validate_coverage_source(
    source_metadata,
    candidate_metadata,
    config,
    identity,
    source,
    candidate,
    source_report,
    fixed_samples,
    training_evidence,
    queries,
):
    """Bind the diagnostic to the completed, protected 200-update M2l candidate."""
    validate_history_source(source_metadata, config, identity)
    expected_source = {
        "checkpoint": source["checkpoint"],
        "checkpoint_manifest_sha256": source["checkpoint_manifest_sha256"],
        "parent_run_id": source_metadata["run_id"],
        "dataset": identity,
    }
    plan = diverse_memory_plan()
    expected = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "diverse_memory_fit",
        "config": config,
        "dataset_source": identity,
        "plan": plan,
        "source": expected_source,
        "fixed_samples": fixed_samples,
        "training_samples": training_evidence,
        "readout_protocol": plan["readout"],
        "rng_states": {"fixed_seed": 2203},
        "sampler": {"burn_in": 0, "sequence_steps": 1},
        "run_id": candidate["run_id"],
    }
    if (
        any(candidate_metadata.get(k) != v for k, v in expected.items())
        or type(candidate_metadata.get("optimizer_steps")) is not int
        or candidate_metadata["optimizer_steps"] != 200
        or not candidate_metadata.get("run_id")
        or candidate_metadata["run_id"] == source_metadata["run_id"]
        or not candidate_metadata.get("manifest_hash")
    ):
        raise ValueError("coverage candidate lineage, pool or completed M2l plan mismatch")
    expected_report = {
        "status": "completed",
        "checkpoint": candidate["checkpoint"],
        "checkpoint_verified": True,
        "run_id": candidate["run_id"],
        "manifest_hash": candidate_metadata["manifest_hash"],
        "fixed_samples": fixed_samples,
        "training_samples": training_evidence,
        "plan": plan,
        "source": expected_source,
        "promoted": False,
        "frozen_modules_unchanged": True,
        "source_files_unchanged": True,
        "new_environment_steps": 0,
        "actual_optimizer_steps": 200,
        "tail_protection_checks": 200,
        "logical_model_transitions": 174208,
        "reserved_model_transitions": 174208,
    }
    paired = source_report.get("paired")
    groups = source_report.get("diverse_groups")
    run = source_report.get("run")
    if (
        any(
            source_report.get(k) != v or type(source_report.get(k)) is not type(v)
            for k, v in expected_report.items()
        )
        or not isinstance(run, dict)
        or run.get("state") != "completed"
        or run.get("run_id") != candidate["run_id"]
        or not isinstance(paired, dict)
        or paired.get("query_manifest_sha256") != queries["query_manifest_sha256"]
        or paired.get("seed") != 7103
        or paired.get("particles") != 8
        or paired.get("first_edge_pairs_identical") is not True
        or paired.get("first_edge_pair_checks") != 20
        or not isinstance(paired.get("per_query"), list)
        or len(paired["per_query"]) != 2560
        or not isinstance(groups, dict)
        or groups.get("query_manifest_sha256") != queries["query_manifest_sha256"]
        or groups.get("sample_manifest_sha256") != training_evidence["sample_manifest_sha256"]
        or not isinstance(groups.get("per_query"), list)
        or len(groups["per_query"]) != 2560
    ):
        raise ValueError("coverage source report must verify the completed M2l candidate")


def compare_zero_context_reproduction(observed, source_report, labels):
    """A1 must reproduce M2l zero-context query and group scores exactly."""
    paired = source_report["paired"]
    rows = observed.get("per_query")
    if (
        observed.get("query_manifest_sha256") != paired["query_manifest_sha256"]
        or observed.get("random_schedule_sha256") != paired.get("random_schedule_sha256")
        or not isinstance(rows, list)
        or len(rows) != len(paired["per_query"])
    ):
        raise ValueError("zero-context reproduction used different queries or keys")
    for row, expected in zip(rows, paired["per_query"], strict=True):
        if (
            row["row"] != expected["row"]
            or row["episode_id"] != expected["episode_id"]
            or row["query_tick"] != expected["query_tick"]
            or row["paired_random_seeds"] != expected["paired_random_seeds"]
            or row["zero_context_tail"] != expected["methods"]["zero_context_tail"]
        ):
            raise ValueError(
                f"M2l zero-context score did not reproduce exactly at row {expected['row']}"
            )
    groups = source_report["diverse_groups"]
    legacy = [item["group"] for item in groups["per_query"]]
    previous = [item["previous_input_matches_pool"] for item in groups["per_query"]]
    edges = [item["edge_input_matches_pool"] for item in groups["per_query"]]
    expected_labels = [
        group
        if group != "unselected_train"
        else f"unselected_train_previous_{'in' if flag else 'not_in'}_pool"
        for group, flag in zip(legacy, previous, strict=True)
    ]
    if expected_labels != list(labels):
        raise ValueError("coverage query labels differ from the M2l pool regrouping")

    def summary(indices):
        result = _Summary()
        for index in indices:
            result.add(rows[index]["zero_context_tail"])
        return result.result()

    checks = [(range(len(rows)), groups["all_queries"])]
    for group in ("selected_train", "unselected_train", "development"):
        members = [i for i, name in enumerate(legacy) if name == group]
        checks.append((members, groups["groups"][group]))
        for label, flags in (("previous", previous), ("edge", edges)):
            for flag in (True, False):
                checks.append(
                    (
                        [i for i in members if flags[i] is flag],
                        groups["groups"][group][f"{label}_input_matches_pool"][str(flag).lower()],
                    )
                )
    for indices, expected in checks:
        if summary(list(indices)) != expected["methods"]["zero_context_tail"]:
            raise ValueError("M2l zero-context group summary did not reproduce exactly")
    return {
        "exact_match": True,
        "queries": len(rows),
        "group_summaries_checked": len(checks),
        "random_schedule_sha256": observed["random_schedule_sha256"],
    }


def _file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_coverage_diagnostic(
    config_path,
    dataset_path,
    checkpoint_path,
    candidate_path,
    source_report_path,
    output_root,
    control_db,
    experiment_id,
):
    from ainerzero.cli import pilot_manifest
    from ainerzero.learning.paired_memory import paired_memory_samples

    started = time.perf_counter()
    config = load_pilot_config(config_path)
    plan = coverage_diagnostic_plan()
    _, episodes, identity = load_pilot_dataset(
        dataset_path, TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    )
    source_tensors, source_metadata = load_checkpoint(checkpoint_path)
    candidate_tensors, candidate_metadata = load_checkpoint(candidate_path)
    source_report_bytes = source_report_path.read_bytes()
    source_report = json.loads(source_report_bytes)
    _, fixed_samples = select_micro_memory_samples(episodes["train"])
    pool, training_evidence = select_diverse_memory_samples(episodes["train"])
    queries = paired_memory_samples(episodes)

    def reference(path, metadata):
        return {
            "checkpoint": str(path.resolve()),
            "run_id": metadata["run_id"],
            "checkpoint_manifest_sha256": hashlib.sha256(
                (path / "manifest.json").read_bytes()
            ).hexdigest(),
        }

    source, candidate = (
        reference(checkpoint_path, source_metadata),
        reference(candidate_path, candidate_metadata),
    )
    validate_coverage_source(
        source_metadata,
        candidate_metadata,
        config.model_dump(mode="json"),
        identity,
        source,
        candidate,
        source_report,
        fixed_samples,
        training_evidence,
        queries,
    )
    run_directory = candidate_path.resolve().parents[1]
    pool_path = run_directory / "training-pool.npz"
    if source_report.get("run_directory") != str(run_directory) or source_report.get(
        "training_pool_path"
    ) != str(pool_path):
        raise ValueError("M2l pool must be the archive saved beside the candidate checkpoint")
    pool_bytes = pool_path.read_bytes()
    with np.load(pool_path, allow_pickle=False) as archive:
        saved_pool = {name: archive[name] for name in archive.files}
    if (
        set(saved_pool) != set(POOL_FIELDS)
        or any(
            saved_pool[k].dtype != pool[k].dtype or not np.array_equal(saved_pool[k], pool[k])
            for k in POOL_FIELDS
        )
        or _batch_digest(saved_pool) != training_evidence["batch_sha256"]
    ):
        raise ValueError("saved M2l training pool differs from the rebuilt registered pool")
    frames, frame_evidence = query_frames(episodes)
    if frame_evidence["query_manifest_sha256"] != queries["query_manifest_sha256"]:
        raise ValueError("query frames changed after registration")
    labels = query_labels(frame_evidence["queries"], training_evidence)
    symbol_sets = pool_position_symbol_sets(pool)
    classification = classify_query_cells(frames, symbol_sets)
    variants, substitution = build_substitution_variants(pool, training_evidence["samples"])
    pool_queries = {
        (row["episode_id"], row["query_tick"]): index
        for index, row in enumerate(frame_evidence["queries"])
    }
    pool_query_rows = [
        pool_queries[(row["episode_id"], row["query_tick"])] for row in training_evidence["samples"]
    ]
    declaration = pilot_manifest(config_path)["manifest"]
    report_reference = {
        "path": str(source_report_path.resolve()),
        "sha256": hashlib.sha256(source_report_bytes).hexdigest(),
        "run_id": source_report["run_id"],
        "experiment_id": source_report.get("experiment_id"),
    }
    pool_reference = {
        "path": str(pool_path),
        "sha256": hashlib.sha256(pool_bytes).hexdigest(),
        "batch_sha256": training_evidence["batch_sha256"],
        "sample_manifest_sha256": training_evidence["sample_manifest_sha256"],
        "schedule_sha256": training_evidence["schedule_sha256"],
    }
    coverage_evidence = {
        "symbol_sets": symbol_sets,
        "classification_sha256": classification["classification_sha256"],
        "query_label_sha256": hashlib.sha256(json.dumps(labels).encode()).hexdigest(),
        "pool_query_rows": pool_query_rows,
    }
    declaration.update(
        purpose="c0_frozen_coverage_diagnostic_v1",
        coverage_diagnostic=plan,
        diagnostic_sources={
            "source": source,
            "candidate": candidate,
            "report": report_reference,
            "training_pool": pool_reference,
            "dataset": identity,
        },
        paired_samples=queries,
        coverage_evidence=coverage_evidence,
        substitutions=substitution,
    )
    directory = Path(output_root) / f"pilot-{uuid4().hex}"
    directory.mkdir(parents=True)
    report_path = directory / "report.json"
    report = {
        "status": "running",
        "experiment_id": experiment_id,
        "plan": plan,
        "source": source,
        "candidate": candidate,
        "source_report": report_reference,
        "training_pool": pool_reference,
        "dataset": identity,
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "promoted": False,
        "checkpoint_saved": False,
        "coverage_evidence": coverage_evidence,
        "substitution_manifest": {k: v for k, v in substitution.items() if k != "variants"},
        "run_directory": str(directory.resolve()),
        "report_path": str(report_path.resolve()),
    }
    store = RunStore(control_db)
    run_id = None
    stage_started = stage_seconds = None
    last_guard = 0.0
    initial_swap = psutil.swap_memory().used
    reserved_units = 0

    def persist():
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)

    def guard(force=False):
        nonlocal last_guard
        now = time.monotonic()
        if stage_started is not None and time.perf_counter() - stage_started > stage_seconds:
            raise RuntimeError("coverage diagnostic exceeded prepaid stage window")
        if time.perf_counter() - started > plan["supervised_deadline_seconds"]:
            raise RuntimeError("coverage diagnostic reached supervised deadline")
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("coverage diagnostic system memory reserve reached")
        if psutil.Process().memory_info().rss > config.resources.active.project_memory_gib * 2**30:
            raise RuntimeError("coverage diagnostic process memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("coverage diagnostic swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("coverage diagnostic disk reserve reached")
        # User policy: battery power does not block registered model work.
    def stage(name):
        nonlocal stage_started, stage_seconds
        guard(force=True)
        stage_seconds = plan["resource_seconds"][name]
        store.consume(run_id, active_seconds=stage_seconds)
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
        prior = store.get_run(candidate["run_id"])
        if (
            prior.state != "completed"
            or prior.role != "model"
            or prior.experiment_id != source_report.get("experiment_id")
            or prior.reserved_optimizer_steps != 200
            or prior.reserved_environment_steps != 0
            or prior.reserved_model_transitions != 174208
        ):
            raise ValueError("canonical ledger does not confirm the completed M2l source run")
        prior_experiment = store.get_experiment(prior.experiment_id)
        if prior_experiment.manifest_hash != candidate_metadata["manifest_hash"]:
            raise ValueError("canonical ledger source manifest does not match candidate")
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        atomic_write_json(directory / "preregistration.json", declaration)
        run_id = str(uuid4())
        snapshot = config.snapshot_for_run(0)
        snapshot["coverage_diagnostic"] = {"plan": plan, "source": source, "candidate": candidate}
        store.create_run(
            snapshot, run_id, run_id=run_id, experiment_id=experiment_id, role="auxiliary"
        )
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        report.update(run_id=run_id, manifest_hash=experiment.manifest_hash)
        stage("validation")
        report["source_tail_protection"] = verify_tail_update(source_tensors, candidate_tensors)
        tensors = _model_arrays(candidate_tensors, "M2l candidate")
        before_digest = _digest(tensors)
        stage("initialization")
        import mlx.core as mx
        from mlx.utils import tree_flatten, tree_unflatten

        from ainerzero.learning.paired_memory import (
            evaluate_zero_context_cells,
            evaluate_zero_context_inputs,
        )
        from ainerzero.learning.pilot_model import SharedSymbolPredictor

        if not mx.metal.is_available():
            raise RuntimeError("Metal unavailable; no CPU fallback")
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(int(config.resources.active.mlx_memory_gib * 2**30))
        mx.set_cache_limit(int(config.resources.active.mlx_cache_gib * 2**30))
        mx.reset_peak_memory()
        model = SharedSymbolPredictor(config.model, key=mx.random.key(999))
        if {f"model.{k}": v.shape for k, v in tree_flatten(model.parameters())} != {
            k: v.shape for k, v in tensors.items()
        }:
            raise ValueError("coverage model parameter keys/shapes mismatch")
        model.update(tree_unflatten([(k[6:], mx.array(v)) for k, v in tensors.items()]))
        model.freeze()
        mx.eval(model.parameters())
        if tree_flatten(model.trainable_parameters()):
            raise RuntimeError("coverage model has trainable parameters")

        stage("zero_context_cells")
        zero = evaluate_zero_context_cells(
            model,
            episodes,
            before_work=reserve,
            **{k: plan["evaluation"][k] for k in ("seed", "particles")},
        )
        if zero["logical_model_transitions"] != plan["expected_model_units"]["zero_context_cells"]:
            raise RuntimeError("zero-context cells used unregistered model units")
        report["zero_context_reproduction"] = compare_zero_context_reproduction(
            zero, source_report, labels
        )
        argmax = np.asarray([row["cell_argmax"] for row in zero["per_query"]])
        nll = np.asarray(
            [[np.nan if v is None else v for v in row["cell_nll"]] for row in zero["per_query"]]
        )
        correct = argmax == frames["previous_symbols"]
        report["zero_context_cells"] = zero
        report["stratification"] = summarize_cell_scores(classification, correct, nll, labels)
        persist()

        stage("slot_substitution")
        seeds = [zero["per_query"][index]["paired_random_seeds"] for index in pool_query_rows]
        scored = evaluate_zero_context_inputs(
            model,
            variants,
            [seeds[v["row"]] for v in substitution["variants"]],
            before_work=reserve,
            particles=plan["evaluation"]["particles"],
        )
        if scored["logical_model_transitions"] != plan["expected_model_units"]["slot_substitution"]:
            raise RuntimeError("substitution used unregistered model units")
        pool_changed = (
            pool["visible_mask"][:, 0]
            & pool["visible_mask"][:, 1]
            & (pool["symbols"][:, 0] != pool["symbols"][:, 1])
        )
        report["substitution"] = summarize_substitutions(
            substitution,
            scored["argmax"],
            scored["nll"],
            argmax[pool_query_rows],
            pool["symbols"][:, 0],
            pool_changed,
        )
        report["substitution_variant_scores"] = [
            {
                "variant": variant["variant"],
                "argmax": scored["argmax"][index].tolist(),
                "nll": scored["nll"][index].tolist(),
            }
            for index, variant in enumerate(substitution["variants"])
        ]
        persist()

        stage("cpu_audit")
        report["slot_subspace_audit"] = slot_subspace_audit(
            tensors["model.byte_embedding.weight"], pool, frames, labels
        )
        development = report["stratification"]["development"]["same_position_seen"]["true"]
        report["decision"] = coverage_decision(report["substitution"], development["accuracy"])
        persist()

        stage("verification")
        after = {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
        report["weights_unchanged"] = (
            _digest(_model_arrays(after, "after diagnostic")) == before_digest
        )
        if not report["weights_unchanged"]:
            raise RuntimeError("frozen coverage model weights changed")
        report["model_sha256"] = before_digest
        report["source_files_unchanged"] = (
            source_report_path.read_bytes() == source_report_bytes
            and pool_path.read_bytes() == pool_bytes
            and reference(checkpoint_path, load_checkpoint(checkpoint_path)[1]) == source
            and reference(candidate_path, load_checkpoint(candidate_path)[1]) == candidate
        )
        if not report["source_files_unchanged"]:
            raise RuntimeError("source report, pool or checkpoints changed during diagnosis")
        report["logical_model_transitions"] = (
            zero["logical_model_transitions"] + scored["logical_model_transitions"]
        )
        if (
            not report["logical_model_transitions"]
            == reserved_units
            == plan["expected_total_model_units"]
        ):
            raise RuntimeError("coverage measured units do not match fixed reservations")
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        guard(force=True)
        store.transition(run_id, "completed", reason="frozen_coverage_diagnostic_complete")
        report.update(status="completed", current_stage="completed")
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason="frozen_coverage_diagnostic_failure")
    finally:
        report["reserved_model_transitions"] = reserved_units
        if run_id is not None:
            report["run"] = store.get_run(run_id).to_dict()
        store.close()
        persist()
    return report


def main():
    parser = argparse.ArgumentParser()
    for name in (
        "config",
        "dataset",
        "checkpoint",
        "candidate-checkpoint",
        "source-report",
        "output-dir",
        "control-db",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    args = parser.parse_args()
    report = run_coverage_diagnostic(
        args.config,
        args.dataset,
        args.checkpoint,
        args.candidate_checkpoint,
        args.source_report,
        args.output_dir,
        args.control_db,
        args.experiment_id,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
