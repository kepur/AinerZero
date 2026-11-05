"""Frozen history interventions under the CLI's existing lock and budget ledger."""

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
from ainerzero.runtime.c0_collection import RANDOM_ACTOR
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore
from ainerzero.runtime.recall_diagnostics import recall_plan, run_recall_probes
from ainerzero.runtime.residual_diagnostics import residual_plan, run_residual_probes


def history_plan() -> dict:
    return {
        "architecture": "pilot_shared_symbol_v1",
        "parameter_count": 393232,
        "optimizer_steps": 0,
        "new_environment_steps": 0,
        "methods": ["model", "reset_history", "shuffled_history", "copy", "no_action"],
        "seed": 700,
        "support_ticks": 32,
        "query_stride": 8,
        "particles": 8,
        "horizons": [1, 4],
        "history_shuffle": "shuffle_earlier_incoming_action_outcome_pairs_keep_initial_and_last_pair",
        "controls": "identical_current_observation_future_actions_and_noise_keys",
        "history_support": "same_position_target_byte_seen_in_original_prefix_only",
        "resource_seconds": {
            "initialization": 15,
            "history": 240,
            "reconstruction": 45,
            "verification": 5,
        },
        "supervised_deadline_seconds": 400,
        "selection": "one_explicit_completed_action_checkpoint_no_weight_update_or_promotion",
        "interpretation": "sensitivity_is_not_benefit; null_effect_does_not_prove_empty_memory",
    }


def validate_history_source(metadata: dict, config: dict, identity: dict) -> None:
    if (
        metadata.get("architecture") != "pilot_shared_symbol_v1"
        or metadata.get("phase") not in {"action_prediction", "action_refinement"}
        or metadata.get("config") != config
        or metadata.get("dataset_source") != identity
        or type(metadata.get("optimizer_steps")) is not int
        or metadata["optimizer_steps"] < 1
        or not metadata.get("run_id")
    ):
        raise ValueError(
            "history checkpoint architecture, phase, completed updates, dataset or config mismatch"
        )


def run_history(
    config_path,
    dataset_path,
    checkpoint_path,
    output_root,
    control_db,
    experiment_id,
    *,
    recall=False,
    residual=False,
):
    from ainerzero.cli import pilot_manifest

    started = time.perf_counter()
    config = load_pilot_config(config_path)
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    _, episodes, identity = load_pilot_dataset(dataset_path, policy)
    tensors, metadata = load_checkpoint(checkpoint_path)
    validate_history_source(metadata, config.model_dump(mode="json"), identity)
    if recall and residual:
        raise ValueError("choose only one frozen recall protocol")
    plan = residual_plan() if residual else recall_plan() if recall else history_plan()
    diagnostic_kind = "residual_recall" if residual else "recall" if recall else "history"
    declaration = pilot_manifest(config_path)["manifest"]
    source = {
        "checkpoint": str(checkpoint_path.resolve()),
        "checkpoint_manifest_sha256": hashlib.sha256(
            (checkpoint_path / "manifest.json").read_bytes()
        ).hexdigest(),
        "parent_run_id": metadata["run_id"],
        "parent_manifest_hash": metadata.get("manifest_hash"),
        "dataset": identity,
    }
    declaration.update(
        purpose=f"c0_frozen_{diagnostic_kind}_diagnosis_v1",
        diagnostic_source=source,
        **{f"{diagnostic_kind}_diagnostic": plan},
    )
    directory = Path(output_root) / f"pilot-{uuid4().hex}"
    directory.mkdir(parents=True)
    report_path = directory / "report.json"
    report = {
        "status": "running",
        "scope": (
            "train_only_external_readouts_development_scoring_not_student_capability"
            if recall or residual
            else "fixed_development_history_interventions_not_new_acceptance"
        ),
        "experiment_id": experiment_id,
        "source": source,
        "plan": plan,
        "dataset": str(dataset_path.resolve()),
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "promoted": False,
        "run_directory": str(directory.resolve()),
        "report_path": str(report_path.resolve()),
    }
    store = RunStore(control_db)
    run_id = None
    initial_swap = psutil.swap_memory().used
    last_guard = 0.0
    stage_started = None
    stage_seconds = None

    def persist():
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)

    def guard(force=False):
        nonlocal last_guard
        now = time.monotonic()
        if stage_started is not None and time.perf_counter() - stage_started > stage_seconds:
            raise RuntimeError("history diagnostic exceeded its prepaid stage window")
        if time.perf_counter() - started > plan["supervised_deadline_seconds"]:
            raise RuntimeError("history diagnostic reached supervised work deadline")
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("history diagnostic system memory reserve reached")
        if psutil.Process().memory_info().rss > config.resources.active.project_memory_gib * 2**30:
            raise RuntimeError("history diagnostic process memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("history diagnostic swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("history diagnostic disk reserve reached")
        # User policy: battery power does not block registered model work.
    def stage(name):
        nonlocal stage_started, stage_seconds
        guard(force=True)
        seconds = plan["resource_seconds"][name]
        store.consume(run_id, active_seconds=seconds)
        stage_seconds = seconds
        stage_started = time.perf_counter()
        report["current_stage"] = name
        persist()

    def reserve(count):
        guard()
        store.consume(run_id, model_transitions=count)

    try:
        guard(force=True)
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        atomic_write_json(directory / "preregistration.json", declaration)
        run_id = str(uuid4())
        snapshot = config.snapshot_for_run(0)
        snapshot[f"{diagnostic_kind}_diagnostic"] = {"plan": plan, "source": source}
        store.create_run(
            snapshot, run_id, run_id=run_id, experiment_id=experiment_id, role="auxiliary"
        )
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        report.update(run_id=run_id, manifest_hash=experiment.manifest_hash)
        stage("initialization")

        import mlx.core as mx
        from mlx.utils import tree_flatten, tree_unflatten

        from ainerzero.learning.evaluation import evaluate_predictor
        from ainerzero.learning.pilot_model import SharedSymbolPredictor
        from ainerzero.learning.reconstruction import evaluate_reconstruction

        if not mx.metal.is_available():
            raise RuntimeError("Metal unavailable; no CPU fallback")
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(int(config.resources.active.mlx_memory_gib * 2**30))
        mx.set_cache_limit(int(config.resources.active.mlx_cache_gib * 2**30))
        mx.reset_peak_memory()
        model = SharedSymbolPredictor(config.model, key=mx.random.key(999))
        expected = {f"model.{name}": v.shape for name, v in tree_flatten(model.parameters())}
        if {k: v.shape for k, v in tensors.items() if k.startswith("model.")} != expected:
            raise ValueError("history checkpoint parameter keys/shapes mismatch")
        model.update(
            tree_unflatten(
                [(k[6:], mx.array(v)) for k, v in tensors.items() if k.startswith("model.")]
            )
        )
        model.freeze()
        mx.eval(model.parameters())
        report["parameter_count"] = sum(v.size for _, v in tree_flatten(model.parameters()))
        if report["parameter_count"] != plan["parameter_count"]:
            raise ValueError("history diagnostic parameter count mismatch")
        guard(force=True)

        if recall or residual:

            def progress(result):
                report[diagnostic_kind] = result
                persist()

            runner = run_residual_probes if residual else run_recall_probes
            report[diagnostic_kind] = runner(
                model,
                episodes,
                tensors,
                plan=plan,
                source=source,
                directory=directory,
                stage=stage,
                reserve=reserve,
                guard=guard,
                progress=progress,
            )
        else:
            baseline = NoActionBaseline(policy).fit(episodes["train"])
            stage("history")
            report["evaluation"] = evaluate_predictor(
                model,
                episodes["development"],
                baseline,
                before_work=reserve,
                seed=plan["seed"],
                support_ticks=plan["support_ticks"],
                query_stride=plan["query_stride"],
                particles=plan["particles"],
                history_ablation=True,
            )
            report["history_elapsed_seconds"] = time.perf_counter() - stage_started
        guard(force=True)
        persist()

        stage("reconstruction")
        report["reconstruction"] = evaluate_reconstruction(
            model, episodes["development"], before_work=reserve
        )
        if residual and report["reconstruction"]["gate"]["status"] != "passed":
            raise RuntimeError("residual diagnostic failed current-observation reconstruction gate")
        guard(force=True)
        stage("verification")
        report["weights_unchanged"] = all(
            np.array_equal(np.array(value), tensors[f"model.{name}"])
            for name, value in tree_flatten(model.parameters())
        )
        report["logical_model_transitions"] = (
            report[diagnostic_kind]["logical_model_units"]
            if recall or residual
            else report["evaluation"]["logical_model_transitions"]
        ) + report["reconstruction"]["observation_encodes"]
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        if not report["weights_unchanged"]:
            raise RuntimeError("frozen history diagnosis changed model weights")
        guard(force=True)
        store.transition(
            run_id, "completed", reason=f"frozen_{diagnostic_kind}_diagnosis_complete_no_promotion"
        )
        report.update(status="completed", current_stage="completed")
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason=f"{diagnostic_kind}_diagnostic_failure")
    finally:
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
    protocol = parser.add_mutually_exclusive_group()
    protocol.add_argument("--recall", action="store_true")
    protocol.add_argument("--residual", action="store_true")
    args = parser.parse_args()
    report = run_history(
        args.config,
        args.dataset,
        args.checkpoint,
        args.output_dir,
        args.control_db,
        args.experiment_id,
        recall=args.recall,
        residual=args.residual,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
