"""Frozen GRU row-reversion diagnostic under the shared CLI supervisor."""

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
from ainerzero.learning.baselines import NoActionBaseline
from ainerzero.learning.gru_intervention import (
    action_nll_recovery,
    build_front_reverted_variants,
)
from ainerzero.runtime.c0_collection import RANDOM_ACTOR
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint
from ainerzero.runtime.history_worker import validate_history_source
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore
from ainerzero.runtime.memory_worker import memory_plan

VARIANTS = ("source", "candidate", "front_reverted")


def interference_plan():
    seconds = {"validation": 15, "comparison": 5}
    for variant in VARIANTS:
        seconds.update(
            {
                f"{variant}_{k}": v
                for k, v in {
                    "initialization": 15,
                    "action": 60,
                    "memory": 45,
                    "reconstruction": 45,
                    "verification": 5,
                }.items()
            }
        )
    return {
        "protocol": "m2i_frozen_gru_front_reversion_v1",
        "architecture": "pilot_shared_symbol_v1",
        "parameter_count": 393232,
        "variants": list(VARIANTS),
        "intervention": {
            "Wx_Wh_b_rows": [[0, 128], [256, 384], [512, 640]],
            "bhn_rows": [[0, 128]],
            "end_exclusive": True,
        },
        "optimizer_steps": 0,
        "new_environment_steps": 0,
        "automatic_promotion": False,
        "save_hybrid_checkpoint": False,
        "evaluation": {
            "action_seed": 700,
            "memory_seed": 4901,
            "support_ticks": 32,
            "action_query_stride": 8,
            "memory_query_stride": 1,
            "particles": 8,
            "horizons": [1, 4],
        },
        "expected_model_units_per_variant": {
            "action": 5376,
            "memory": 7232,
            "reconstruction": 1088,
        },
        "expected_total_model_units": 41088,
        "resource_seconds": seconds,
        "total_reserved_seconds_if_complete": sum(seconds.values()),
        "supervised_deadline_seconds": 600,
        "scope": "reused_development_parameter_intervention_not_new_acceptance",
        "interpretation": "row_reversion_does_not_isolate_state_paths_or_interactions",
        "selection": "three_fixed_variants_no_optimization_search_or_promotion",
    }


def validate_interference_pair(source_metadata, candidate_metadata, config, identity, source):
    """Only the completed M2h child of the explicitly supplied source is eligible."""
    validate_history_source(source_metadata, config, identity)
    expected_source = {
        "checkpoint": source["checkpoint"],
        "checkpoint_manifest_sha256": source["checkpoint_manifest_sha256"],
        "parent_run_id": source_metadata["run_id"],
        "dataset": identity,
    }
    if (
        candidate_metadata.get("architecture") != "pilot_shared_symbol_v1"
        or candidate_metadata.get("phase") != "one_step_memory"
        or candidate_metadata.get("config") != config
        or candidate_metadata.get("dataset_source") != identity
        or type(candidate_metadata.get("optimizer_steps")) is not int
        or candidate_metadata["optimizer_steps"] != 100
        or candidate_metadata.get("plan") != memory_plan()
        or candidate_metadata.get("readout_protocol") != memory_plan()["readout"]
        or not candidate_metadata.get("run_id")
        or candidate_metadata["run_id"] == source_metadata["run_id"]
        or candidate_metadata.get("source") != expected_source
    ):
        raise ValueError(
            "interference candidate lineage, completed plan, config or dataset mismatch"
        )


def compare_variants(results):
    """Compare measured, matched controls; no pass gate or automatic model selection."""
    if set(results) != set(VARIANTS):
        raise ValueError("interference comparison requires exactly three variants")
    source = results["source"]
    for name in VARIANTS:
        value = results[name]
        for field in (
            "actor",
            "assistance",
            "episode_count",
            "eval_seed",
            "protocol",
            "query_count",
            "feedback_model_transitions",
            "rollout_model_transitions",
            "logical_model_transitions",
        ):
            if value["action"][field] != source["action"][field]:
                raise ValueError("action evaluation protocol mismatch across variants")
        for field in (
            "seed",
            "particles",
            "support_ticks",
            "query_stride",
            "query_count",
            "partition",
            "protocol",
            "logical_model_transitions",
            "feedback_model_transitions",
            "initial_observation_encodes",
            "reset_observation_encodes",
            "budget_unit",
        ):
            if value["memory"][field] != source["memory"][field]:
                raise ValueError("memory evaluation protocol mismatch across variants")
        for horizon in ("1", "4"):
            base = source["action"]["horizons"][horizon]
            observed = value["action"]["horizons"][horizon]
            for field in ("copy", "no_action", "query_count"):
                if observed[field] != base[field]:
                    raise ValueError("action control/query mismatch across variants")
            for field in ("count", "changed_count", "unchanged_count"):
                if observed["model"][field] != base["model"][field]:
                    raise ValueError("action target count mismatch across variants")
        for method in ("copy_current", "fixed_current_codec", "reset_history"):
            if value["memory"]["methods"][method] != source["memory"]["methods"][method]:
                raise ValueError("memory control mismatch across variants")

        def queries(v):
            return [
                (w["episode_id"], w["environment_instance_id"], w["query_ticks"])
                for w in v["memory"]["per_world"]
            ]

        if queries(value) != queries(source):
            raise ValueError("memory queries mismatch across variants")
        for field in ("count", "changed_count", "unchanged_count"):
            if (
                value["memory"]["methods"]["memory_tail"][field]
                != source["memory"]["methods"]["memory_tail"][field]
            ):
                raise ValueError("memory target count mismatch across variants")
        if value["reconstruction"] != source["reconstruction"]:
            raise ValueError("frozen current reconstruction mismatch across variants")
    return {
        "action_recovery": {
            h: action_nll_recovery(
                *(results[name]["action"]["horizons"][h]["model"]["nll"] for name in VARIANTS)
            )
            for h in ("1", "4")
        },
        "memory": {name: results[name]["memory"]["methods"]["memory_tail"] for name in VARIANTS},
        "matched_controls_and_queries": True,
        "promotion": False,
        "interpretation": "conditional_parameter_intervention_not_independent_state_isolation",
    }


def run_interference(
    config_path,
    dataset_path,
    checkpoint_path,
    candidate_path,
    output_root,
    control_db,
    experiment_id,
):
    from ainerzero.cli import pilot_manifest

    started = time.perf_counter()
    config = load_pilot_config(config_path)
    plan = interference_plan()
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    _, episodes, identity = load_pilot_dataset(dataset_path, policy)
    source_tensors, source_metadata = load_checkpoint(checkpoint_path)
    candidate_tensors, candidate_metadata = load_checkpoint(candidate_path)

    def reference(path, metadata):
        return {
            "checkpoint": str(path.resolve()),
            "run_id": metadata["run_id"],
            "checkpoint_manifest_sha256": hashlib.sha256(
                (path / "manifest.json").read_bytes()
            ).hexdigest(),
        }

    source = reference(checkpoint_path, source_metadata)
    candidate = reference(candidate_path, candidate_metadata)
    validate_interference_pair(
        source_metadata, candidate_metadata, config.model_dump(mode="json"), identity, source
    )
    declaration = pilot_manifest(config_path)["manifest"]
    declaration.update(
        purpose="c0_frozen_gru_interference_v1",
        interference=plan,
        diagnostic_sources={"source": source, "candidate": candidate, "dataset": identity},
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
        "dataset": identity,
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "promoted": False,
        "hybrid_checkpoint_saved": False,
        "variants": {},
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
            raise RuntimeError("interference diagnostic exceeded prepaid stage window")
        if time.perf_counter() - started > plan["supervised_deadline_seconds"]:
            raise RuntimeError("interference diagnostic reached supervised deadline")
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("interference diagnostic system memory reserve reached")
        if psutil.Process().memory_info().rss > config.resources.active.project_memory_gib * 2**30:
            raise RuntimeError("interference diagnostic process memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("interference diagnostic swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("interference diagnostic disk reserve reached")
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
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        atomic_write_json(directory / "preregistration.json", declaration)
        run_id = str(uuid4())
        snapshot = config.snapshot_for_run(0)
        snapshot["interference"] = {"plan": plan, "source": source, "candidate": candidate}
        store.create_run(
            snapshot, run_id, run_id=run_id, experiment_id=experiment_id, role="auxiliary"
        )
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        report.update(run_id=run_id, manifest_hash=experiment.manifest_hash)
        stage("validation")
        variants, report["intervention_evidence"] = build_front_reverted_variants(
            source_tensors, candidate_tensors
        )
        baseline = NoActionBaseline(policy).fit(episodes["train"])
        guard(force=True)
        for name in VARIANTS:
            stage(f"{name}_initialization")
            import mlx.core as mx
            from mlx.utils import tree_flatten, tree_unflatten

            from ainerzero.learning.evaluation import evaluate_predictor
            from ainerzero.learning.one_step_memory import evaluate_one_step_memory
            from ainerzero.learning.pilot_model import SharedSymbolPredictor
            from ainerzero.learning.reconstruction import evaluate_reconstruction

            if not mx.metal.is_available():
                raise RuntimeError("Metal unavailable; no CPU fallback")
            mx.set_default_device(mx.gpu)
            mx.set_memory_limit(int(config.resources.active.mlx_memory_gib * 2**30))
            mx.set_cache_limit(int(config.resources.active.mlx_cache_gib * 2**30))
            if name == "source":
                mx.reset_peak_memory()
            model = SharedSymbolPredictor(config.model, key=mx.random.key(999))
            tensors = variants[name]
            if {f"model.{k}": v.shape for k, v in tree_flatten(model.parameters())} != {
                k: v.shape for k, v in tensors.items()
            }:
                raise ValueError("interference model parameter keys/shapes mismatch")
            model.update(tree_unflatten([(k[6:], mx.array(v)) for k, v in tensors.items()]))
            model.freeze()
            mx.eval(model.parameters())
            if tree_flatten(model.trainable_parameters()):
                raise RuntimeError("interference variant has trainable parameters")
            result = report["variants"][name] = {}
            ev = plan["evaluation"]
            stage(f"{name}_action")
            result["action"] = evaluate_predictor(
                model,
                episodes["development"],
                baseline,
                before_work=reserve,
                seed=ev["action_seed"],
                support_ticks=ev["support_ticks"],
                query_stride=ev["action_query_stride"],
                particles=ev["particles"],
            )
            stage(f"{name}_memory")
            result["memory"] = evaluate_one_step_memory(
                model,
                episodes["development"],
                partition="development",
                before_work=reserve,
                seed=ev["memory_seed"],
                support_ticks=ev["support_ticks"],
                particles=ev["particles"],
            )
            stage(f"{name}_reconstruction")
            result["reconstruction"] = evaluate_reconstruction(
                model, episodes["development"], before_work=reserve
            )
            if result["reconstruction"]["gate"]["status"] != "passed":
                raise RuntimeError("interference current reconstruction gate failed")
            stage(f"{name}_verification")
            result["weights_unchanged"] = all(
                np.array_equal(np.array(v), tensors[f"model.{k}"])
                for k, v in tree_flatten(model.parameters())
            )
            if not result["weights_unchanged"]:
                raise RuntimeError("frozen interference variant changed model weights")
            result["logical_model_transitions"] = (
                result["action"]["logical_model_transitions"]
                + result["memory"]["logical_model_transitions"]
                + result["reconstruction"]["observation_encodes"]
            )
            measured_units = {
                "action": result["action"]["logical_model_transitions"],
                "memory": result["memory"]["logical_model_transitions"],
                "reconstruction": result["reconstruction"]["observation_encodes"],
            }
            if measured_units != plan["expected_model_units_per_variant"]:
                raise RuntimeError("interference per-variant model units differ from fixed plan")
            guard(force=True)
            persist()
            del model
        stage("comparison")
        report["comparison"] = compare_variants(report["variants"])
        report["logical_model_transitions"] = sum(
            r["logical_model_transitions"] for r in report["variants"].values()
        )
        if not (
            report["logical_model_transitions"]
            == reserved_units
            == plan["expected_total_model_units"]
        ):
            raise RuntimeError("interference measured units do not match reservations")
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        guard(force=True)
        store.transition(
            run_id, "completed", reason="frozen_gru_interference_complete_no_promotion"
        )
        report.update(status="completed", current_stage="completed")
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason="frozen_interference_failure")
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
        "output-dir",
        "control-db",
    ):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    args = parser.parse_args()
    report = run_interference(
        args.config,
        args.dataset,
        args.checkpoint,
        args.candidate_checkpoint,
        args.output_dir,
        args.control_db,
        args.experiment_id,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
