"""M2k: frozen matched-input history diagnosis of the completed M2j candidate."""

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
from ainerzero.data.pilot_dataset import load_pilot_dataset
from ainerzero.learning.gru_intervention import _digest, _model_arrays
from ainerzero.learning.micro_memory import evaluate_micro_memory, select_micro_memory_samples
from ainerzero.learning.tail_update import verify_tail_update
from ainerzero.runtime.c0_collection import RANDOM_ACTOR
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint
from ainerzero.runtime.history_worker import validate_history_source
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore
from ainerzero.runtime.memory_worker import micro_memory_plan


def paired_memory_plan():
    seconds = {
        "validation": 15,
        "initialization": 15,
        "local_training_noise": 5,
        "local_new_noise": 5,
        "paired": 300,
        "verification": 15,
    }
    return {
        "protocol": "m2k_frozen_matched_edge_history_v1",
        "architecture": "pilot_shared_symbol_v1",
        "parameter_count": 393232,
        "optimizer_steps": 0,
        "new_environment_steps": 0,
        "automatic_promotion": False,
        "checkpoint_saved": False,
        "evaluation": {"seed": 7103, "particles": 8, "query_ticks": [1, 128]},
        "groups": {"fitted_train": 16, "other_train": 2032, "development": 512},
        "anchor_seeds": {"training_noise": 2203, "same_inputs_new_noise": 2603},
        "expected_model_units": {"anchors": 96, "paired": 82080},
        "expected_total_model_units": 82176,
        "resource_seconds": seconds,
        "total_reserved_seconds_if_complete": sum(seconds.values()),
        "supervised_deadline_seconds": 600,
        "scope": "reused_public_train_and_development_edges_not_independent_acceptance",
        "selection": "all_edges_no_result_dependent_selection_no_training_or_promotion",
        "controls": "identical_previous_observation_action_current_observation_and_last_three_keys",
        "interpretation": "conditional_history_effect_separate_from_zero_context_input_transfer",
    }


def validate_paired_source(
    source_metadata,
    candidate_metadata,
    config,
    identity,
    source,
    candidate,
    source_report,
    fixed_samples,
):
    """Bind this diagnostic to a completed, protected 200-update M2j child."""
    validate_history_source(source_metadata, config, identity)
    expected_source = {
        "checkpoint": source["checkpoint"],
        "checkpoint_manifest_sha256": source["checkpoint_manifest_sha256"],
        "parent_run_id": source_metadata["run_id"],
        "dataset": identity,
    }
    plan = micro_memory_plan()
    expected = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "micro_memory_fit",
        "config": config,
        "dataset_source": identity,
        "plan": plan,
        "source": expected_source,
        "fixed_samples": fixed_samples,
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
        raise ValueError("paired candidate lineage, fixed samples or completed M2j plan mismatch")
    expected_report = {
        "status": "completed",
        "checkpoint": candidate["checkpoint"],
        "checkpoint_verified": True,
        "run_id": candidate["run_id"],
        "manifest_hash": candidate_metadata["manifest_hash"],
        "fixed_samples": fixed_samples,
        "plan": plan,
        "source": expected_source,
        "promoted": False,
    }
    if (
        any(source_report.get(k) != v for k, v in expected_report.items())
        or source_report.get("checkpoint_verified") is not True
        or source_report.get("promoted") is not False
        or any(
            type(source_report.get(k)) is not int or source_report[k] != 200
            for k in ("actual_optimizer_steps", "tail_protection_checks")
        )
        or source_report.get("run", {}).get("state") != "completed"
        or source_report.get("run", {}).get("run_id") != candidate["run_id"]
        or set(source_report.get("local_checks", {}).get("200", {}))
        != {"training_noise", "same_inputs_new_noise"}
    ):
        raise ValueError("paired source report must verify the completed M2j candidate")


def compare_local_anchor(observed, expected):
    """Exact reproduction is an engineering check, not another training trial."""
    if observed != expected:
        raise ValueError("M2j local anchor did not reproduce exactly; stop before paired diagnosis")
    return {"exact_match": True, "seed": observed["seed"], "batch_sha256": observed["batch_sha256"]}


def run_paired_memory(
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
    from ainerzero.learning.paired_memory import evaluate_paired_memory, paired_memory_samples

    started = time.perf_counter()
    config = load_pilot_config(config_path)
    plan = paired_memory_plan()
    _, episodes, identity = load_pilot_dataset(
        dataset_path, TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    )
    source_tensors, source_metadata = load_checkpoint(checkpoint_path)
    candidate_tensors, candidate_metadata = load_checkpoint(candidate_path)
    source_report_bytes = source_report_path.read_bytes()
    source_report = json.loads(source_report_bytes)
    batch, fixed_samples = select_micro_memory_samples(episodes["train"])
    samples = paired_memory_samples(episodes)

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
    validate_paired_source(
        source_metadata,
        candidate_metadata,
        config.model_dump(mode="json"),
        identity,
        source,
        candidate,
        source_report,
        fixed_samples,
    )
    declaration = pilot_manifest(config_path)["manifest"]
    report_reference = {
        "path": str(source_report_path.resolve()),
        "sha256": hashlib.sha256(source_report_bytes).hexdigest(),
    }
    declaration.update(
        purpose="c0_frozen_paired_memory_v1",
        paired_memory=plan,
        diagnostic_sources={
            "source": source,
            "candidate": candidate,
            "report": report_reference,
            "dataset": identity,
        },
        paired_samples=samples,
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
        "dataset": identity,
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "promoted": False,
        "checkpoint_saved": False,
        "local_anchors": {},
        "run_directory": str(directory.resolve()),
        "report_path": str(report_path.resolve()),
    }
    store = RunStore(control_db)
    run_id = None
    stage_started = stage_seconds = None
    last_guard = last_power = 0.0
    initial_swap = psutil.swap_memory().used
    reserved_units = 0

    def persist():
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)

    def guard(force=False):
        nonlocal last_guard, last_power
        now = time.monotonic()
        if stage_started is not None and time.perf_counter() - stage_started > stage_seconds:
            raise RuntimeError("paired diagnostic exceeded prepaid stage window")
        if time.perf_counter() - started > plan["supervised_deadline_seconds"]:
            raise RuntimeError("paired diagnostic reached supervised deadline")
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("paired diagnostic system memory reserve reached")
        if psutil.Process().memory_info().rss > config.resources.active.project_memory_gib * 2**30:
            raise RuntimeError("paired diagnostic process memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("paired diagnostic swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("paired diagnostic disk reserve reached")
        if force or now - last_power > 15:
            power = subprocess.run(
                ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5, check=True
            ).stdout
            if "AC Power" not in power:
                raise RuntimeError("paired diagnostic requires AC power")
            last_power = now

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
            or prior.reserved_optimizer_steps != 200
            or prior.experiment_id != source_report.get("experiment_id")
        ):
            raise ValueError("canonical ledger does not confirm completed M2j source run")
        prior_experiment = store.get_experiment(prior.experiment_id)
        if prior_experiment.manifest_hash != candidate_metadata["manifest_hash"]:
            raise ValueError("canonical ledger source manifest does not match candidate")
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        atomic_write_json(directory / "preregistration.json", declaration)
        run_id = str(uuid4())
        snapshot = config.snapshot_for_run(0)
        snapshot["paired_memory"] = {"plan": plan, "source": source, "candidate": candidate}
        store.create_run(
            snapshot, run_id, run_id=run_id, experiment_id=experiment_id, role="auxiliary"
        )
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        report.update(run_id=run_id, manifest_hash=experiment.manifest_hash)
        stage("validation")
        report["source_tail_protection"] = verify_tail_update(source_tensors, candidate_tensors)
        tensors = _model_arrays(candidate_tensors, "M2j candidate")
        before_digest = _digest(tensors)
        stage("initialization")
        import mlx.core as mx
        from mlx.utils import tree_flatten, tree_unflatten

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
            raise ValueError("paired model parameter keys/shapes mismatch")
        model.update(tree_unflatten([(k[6:], mx.array(v)) for k, v in tensors.items()]))
        model.freeze()
        mx.eval(model.parameters())
        if tree_flatten(model.trainable_parameters()):
            raise RuntimeError("paired model has trainable parameters")
        for label, seed in plan["anchor_seeds"].items():
            stage("local_training_noise" if seed == 2203 else "local_new_noise")
            actual = evaluate_micro_memory(model, batch, seed=seed, before_work=reserve)
            report["local_anchors"][label] = actual
            compare_local_anchor(actual, source_report["local_checks"]["200"][label])
        report["local_anchors_reproduced_exactly"] = True
        stage("paired")
        report["paired"] = evaluate_paired_memory(
            model,
            episodes,
            before_work=reserve,
            **{k: plan["evaluation"][k] for k in ("seed", "particles")},
        )
        if report["paired"]["query_manifest_sha256"] != samples["query_manifest_sha256"]:
            raise RuntimeError("paired query identities changed after registration")
        stage("verification")
        after = {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
        report["weights_unchanged"] = (
            _digest(_model_arrays(after, "after diagnostic")) == before_digest
        )
        if not report["weights_unchanged"]:
            raise RuntimeError("frozen paired model weights changed")
        report["model_sha256"] = before_digest
        report["source_files_unchanged"] = (
            source_report_path.read_bytes() == source_report_bytes
            and reference(checkpoint_path, load_checkpoint(checkpoint_path)[1]) == source
            and reference(candidate_path, load_checkpoint(candidate_path)[1]) == candidate
        )
        if not report["source_files_unchanged"]:
            raise RuntimeError("source report or checkpoints changed during diagnosis")
        report["logical_model_transitions"] = (
            sum(v["logical_model_transitions"] for v in report["local_anchors"].values())
            + report["paired"]["logical_model_transitions"]
        )
        if (
            not report["logical_model_transitions"]
            == reserved_units
            == plan["expected_total_model_units"]
        ):
            raise RuntimeError("paired measured units do not match fixed reservations")
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        guard(force=True)
        store.transition(run_id, "completed", reason="frozen_paired_memory_complete_no_promotion")
        report.update(status="completed", current_stage="completed")
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason="frozen_paired_memory_failure")
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
    report = run_paired_memory(
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
