"""Paired current-observation learning before a gated action-prediction phase.

No architecture grows. All work uses public admitted data and the project
ledger; the CLI supplies an exclusive lock and a hard subprocess timeout.
"""

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
from ainerzero.runtime.c0_collection import RANDOM_ACTOR
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint, save_checkpoint
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore
from ainerzero.runtime.pilot_worker import prediction_gate

FRAME_UPDATES = 750
ACTION_UPDATES = 100


def action_comparison_plan(arm: str = "all") -> dict:
    """Fixed update-matched comparison, with compute cost reported separately."""
    plan = {
        "architectures": ["pilot_shared_symbol_v1"],
        "expected_parameter_counts": {"pilot_shared_symbol_v1": 393232},
        "parameter_ceiling": 393232,
        "action_updates_max": ACTION_UPDATES,
        "arms": [
            {
                "name": "one_step_control",
                "changed_weight": 1.0,
                "rollout_horizon": 1,
                "rollout_weight": 0.0,
            },
            {
                "name": "changed_weighted",
                "changed_weight": 8.0,
                "rollout_horizon": 1,
                "rollout_weight": 0.0,
            },
            {
                "name": "changed_four_step",
                "changed_weight": 8.0,
                "rollout_horizon": 4,
                "rollout_weight": 0.5,
            },
        ],
        "sampling": "same_uniform_public_train_windows_and_per_window_byte_permutation",
        "seeds": {"windows": 1101, "augmentation": 1307, "frames": 1401, "latent": 1203},
        "optimizer": "reset_AdamW_all_parameters_trainable_same_source_weights_each_arm",
        "learning_rate": 0.0003,
        "batch_size": 16,
        "burn_in": 4,
        "sequence_steps": 20,
        "comparison": "equal_updates_and_data_draws_not_equal_compute",
        "change_labels": "both_endpoints_visible_and_different; training_loss_only; per_frame_normalization",
        "rollout": "origin_posterior_then_four_actions_without_intermediate_observations; endpoint_loss",
        "evaluation": "unchanged_unweighted_1_and_4_step_queries_plus_changed_unchanged_metrics",
        "selection": "no_automatic_selection_or_promotion; retain_all_three_candidates",
        "automatic_promotion": False,
        "minimum_update_reservation_seconds": 5.0,
    }
    if arm != "all":
        plan["arms"] = [row for row in plan["arms"] if row["name"] == arm]
        if not plan["arms"]:
            raise ValueError("unknown action comparison arm")
    plan["arm_selection"] = arm
    return plan


def observation_plan(structure: str = "paired") -> dict:
    if structure not in {"paired", "shared_slots"}:
        raise ValueError("unsupported observation structure experiment")
    return {
        "architectures": ["pilot_predictor_v1", "pilot_observation_state_v1"]
        if structure == "paired"
        else ["pilot_shared_symbol_v1"],
        "structure": structure,
        "parameter_ceiling": 653072,
        "expected_parameter_counts": {
            "pilot_predictor_v1": 653072,
            "pilot_observation_state_v1": 653072,
            "pilot_shared_symbol_v1": 393232,
        },
        "frame_updates_each": FRAME_UPDATES,
        "frame_batch_size": 128,
        "frame_micro_batch_size": 32,
        "frame_learning_rate": 0.001,
        "frame_loss": "current_observation_only_no_prior_no_kl",
        "frame_frozen_modules": ["gru", "prior", "action_embedding"],
        "frame_belief": "fresh_zero_state_per_observation",
        "frame_sampling": "128_frames_from_16_uniform_windows_after_shared_byte_relabeling",
        "seed": 0,
        "window_rng_seed": 101,
        "augmentation_rng_seed": 307,
        "frame_rng_seed": 401,
        "latent_rng_seed": 203,
        "action_updates_max": ACTION_UPDATES,
        "action_optimizer": "reset_AdamW_to_pilot_config; all_parameters_unfrozen",
        "action_kl_warmup": "restart_at_action_update_one",
        "selection": "only_checkpoint_verified_gate_passed_candidate; prefer_original_then_observation_state_then_shared_symbol; otherwise_stop",
        "gate": {
            "accuracy_min": 0.95,
            "each_position_accuracy_min": 0.95,
            "nll_max": 0.3,
            "zero_symbols_accuracy_max": 0.1,
            "zero_symbols_nll_gap_min": 2.0,
            "state_roundtrip_required": True,
        },
        "scope": "current_observation_encoding_readback_not_long_term_memory",
        "automatic_promotion": False,
    }


def choose_reconstruction(phases: list[dict]) -> dict | None:
    """Select only an evaluated, checkpoint-verified reconstruction candidate."""
    for architecture in (
        "pilot_predictor_v1",
        "pilot_observation_state_v1",
        "pilot_shared_symbol_v1",
    ):
        for phase in phases:
            if (
                phase["architecture"] == architecture
                and phase.get("reconstruction_gate", {}).get("status") == "passed"
                and phase.get("checkpoint_verified") is True
            ):
                return phase
    return None


def sample_frames(sampler, window_rng, augmentation_rng, frame_rng) -> dict:
    batch = permute_symbols(sampler.sample(16, window_rng), augmentation_rng)
    total = batch["symbols"].shape[0] * batch["symbols"].shape[1]
    indices = frame_rng.choice(total, 128, replace=False)
    return {
        "symbols": batch["symbols"].reshape(-1, 8)[indices],
        "visible_mask": batch["visible_mask"].reshape(-1, 8)[indices],
        "cursor": batch["cursor"].reshape(-1)[indices],
    }


def run_observation(
    config_path,
    dataset_path,
    output_root,
    control_db,
    experiment_id,
    structure="paired",
    initial_checkpoint=None,
    action_comparison=False,
    comparison_arm="all",
):
    from ainerzero.cli import pilot_manifest

    config = load_pilot_config(config_path)
    plan = (
        action_comparison_plan(comparison_arm) if action_comparison else observation_plan(structure)
    )
    if action_comparison and config.training.learning_rate != plan["learning_rate"]:
        raise ValueError("action comparison learning rate differs from declaration")
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    paths, episodes, identity = load_pilot_dataset(dataset_path, policy)
    initial_saved = initial_metadata = None
    if action_comparison and initial_checkpoint is None:
        raise ValueError("action comparison requires a verified source checkpoint")
    if initial_checkpoint is not None:
        if structure != "shared_slots":
            raise ValueError("paired reconstruction comparisons must start from random weights")
        initial_saved, initial_metadata = load_checkpoint(initial_checkpoint)
        if (
            initial_metadata.get("architecture") != "pilot_shared_symbol_v1"
            or initial_metadata.get("phase")
            not in (
                {"action_prediction", "action_refinement"}
                if action_comparison
                else {"reconstruction"}
            )
            or initial_metadata.get("dataset_source") != identity
            or initial_metadata.get("config") != config.model_dump(mode="json")
        ):
            raise ValueError(
                "continuation checkpoint architecture, phase, dataset or config mismatch"
            )
        plan["initialization"] = {
            "kind": "same_saved_action_weights_optimizer_and_random_streams_reset"
            if action_comparison
            else "saved_reconstruction_weights_optimizer_reset_random_streams_continued",
            "checkpoint": str(initial_checkpoint.resolve()),
            "manifest_sha256": hashlib.sha256(
                (initial_checkpoint / "manifest.json").read_bytes()
            ).hexdigest(),
            "parent_run_id": initial_metadata["run_id"],
            "parent_phase_updates": initial_metadata["optimizer_steps"],
        }
    declaration = pilot_manifest(config_path)["manifest"]
    declaration.update(
        purpose="c0_changed_multistep_comparison_v1"
        if action_comparison
        else "c0_observation_first_v1",
        observation_first=plan,
        dataset_source=identity,
    )
    directory = Path(output_root) / f"pilot-{uuid4().hex}"
    directory.mkdir(parents=True)
    report_path = directory / "report.json"
    report = {
        "status": "running",
        "experiment_id": experiment_id,
        "scope": "same_small_model_changed_and_multistep_no_promotion"
        if action_comparison
        else "current_observation_gate_then_action_prediction_no_promotion",
        "run_directory": str(directory.resolve()),
        "report_path": str(report_path.resolve()),
        "dataset": str(dataset_path.resolve()),
        "new_environment_steps": 0,
        "actual_optimizer_steps": 0,
        "phases": [],
        "promoted": False,
        "action_phase": "not_started",
        "plan": plan,
    }
    store = RunStore(control_db)
    started = time.perf_counter()
    profile = config.resources.active
    initial_swap = psutil.swap_memory().used
    last_guard = last_power = 0.0
    run_id = None
    model = optimizer = phase = None

    def persist():
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)

    def guard(force=False):
        nonlocal last_guard, last_power
        now = time.monotonic()
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if time.perf_counter() - started > 1150:
            raise RuntimeError("observation experiment reached supervised work deadline")
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("system memory reserve reached")
        if psutil.Process().memory_info().rss > profile.project_memory_gib * 2**30:
            raise RuntimeError("worker memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("disk reserve reached")
        if force or now - last_power > 15:
            power = subprocess.run(
                ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5, check=True
            ).stdout
            last_power = now
            if "AC Power" not in power:
                raise RuntimeError("observation training requires confirmed AC power")

    try:
        guard(force=True)
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        report["manifest_hash"] = experiment.manifest_hash
        atomic_write_json(directory / "preregistration.json", declaration)
        persist()
        sampler = SequenceSampler(paths["train"], policy)
        baseline = NoActionBaseline(policy).fit(episodes["train"])

        def begin_phase(architecture, kind, source=None):
            nonlocal run_id, phase, model, optimizer
            candidate_run_id = str(uuid4())
            pending = {
                "run_id": candidate_run_id,
                "architecture": architecture,
                "kind": kind,
                "actual_optimizer_steps": 0,
                "source_checkpoint": source,
            }
            snapshot = config.snapshot_for_run(0)
            snapshot["observation_phase"] = {**pending, "plan": plan}
            store.create_run(
                snapshot,
                candidate_run_id,
                run_id=candidate_run_id,
                experiment_id=experiment_id,
                role="model",
            )
            run_id, phase = candidate_run_id, pending
            model = optimizer = None
            report["phases"].append(phase)
            store.transition(run_id, "initializing")
            store.transition(run_id, "validating")
            store.consume(run_id, active_seconds=15)
            persist()

        # The first reservation precedes even the tensor runtime import.
        begin_phase(
            plan["architectures"][0],
            "action_refinement" if action_comparison else "reconstruction",
            source=str(initial_checkpoint.resolve()) if initial_checkpoint else None,
        )
        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten, tree_map, tree_unflatten

        from ainerzero.learning.evaluation import evaluate_predictor
        from ainerzero.learning.pilot_model import (
            ObservationStatePredictor,
            PilotPredictor,
            SharedSymbolPredictor,
            reconstruction_loss,
            sequence_loss,
        )
        from ainerzero.learning.reconstruction import evaluate_reconstruction, reconstruction_gate

        if not mx.metal.is_available():
            raise RuntimeError("Metal unavailable; no CPU fallback")
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(int(profile.mlx_memory_gib * 2**30))
        mx.set_cache_limit(int(profile.mlx_cache_gib * 2**30))
        mx.reset_peak_memory()
        classes = {
            "pilot_predictor_v1": PilotPredictor,
            "pilot_observation_state_v1": ObservationStatePredictor,
            "pilot_shared_symbol_v1": SharedSymbolPredictor,
        }
        options = dict(
            betas=config.training.adam_betas,
            eps=config.training.adam_epsilon,
            weight_decay=config.training.weight_decay,
            bias_correction=True,
        )

        def frozen_evaluation(network, *, predictive=False):
            if store.get_run(run_id).state != "validating":
                store.transition(run_id, "validating")
            store.consume(run_id, active_seconds=90)
            tick = time.perf_counter()

            def reserve(count):
                guard()
                if time.perf_counter() - tick > 90:
                    raise RuntimeError("evaluation exceeded its reserved window")
                store.consume(run_id, model_transitions=count)

            if predictive:
                value = evaluate_predictor(
                    network,
                    episodes["development"],
                    baseline,
                    before_work=reserve,
                    action_ablation=True,
                )
            else:
                value = evaluate_reconstruction(
                    network, episodes["development"], before_work=reserve
                )
            guard()
            value["elapsed_seconds"] = time.perf_counter() - tick
            if value["elapsed_seconds"] > 90:
                raise RuntimeError("evaluation exceeded its reserved window")
            return value

        def save_candidate(network, opt, rngs, key):
            guard(force=True)
            store.consume(run_id, active_seconds=30, model_transitions=4)
            tick = time.perf_counter()
            # A training-only probe writes a temporary observation state to disk.
            probe = sample_frames(
                sampler,
                np.random.default_rng(991),
                np.random.default_rng(992),
                np.random.default_rng(993),
            )
            probe = {k: mx.array(v[:4]) for k, v in probe.items()}
            h, _ = network.initial(4)
            observed = network.observe(h, **probe, key=mx.random.key(994))
            reference = network.decode(observed["h"], observed["z"])
            mx.eval(reference, observed["h"], observed["z"])
            tensors = {f"model.{k}": np.array(v) for k, v in tree_flatten(network.parameters())}
            tensors.update({f"optimizer.{k}": np.array(v) for k, v in tree_flatten(opt.state)})
            tensors.update(
                {
                    "rng.mlx_key": np.array(key),
                    "session.h": np.array(observed["h"]),
                    "session.z": np.array(observed["z"]),
                }
            )
            checkpoint = save_checkpoint(
                directory / "checkpoints",
                run_id,
                tensors,
                {
                    "architecture": phase["architecture"],
                    "config": config.model_dump(mode="json"),
                    "phase": phase["kind"],
                    "optimizer_steps": phase["actual_optimizer_steps"],
                    "optimizer": {
                        **options,
                        "learning_rate": 0.001
                        if phase["kind"] == "reconstruction"
                        else config.training.learning_rate,
                    },
                    "rng_states": {k: v.bit_generator.state for k, v in rngs.items()},
                    "experiment_id": experiment_id,
                    "run_id": run_id,
                    "manifest_hash": experiment.manifest_hash,
                    "dataset_source": identity,
                    "session_scope": "temporary_training_observation_state_not_permanent_knowledge",
                    "state_probe_seeds": [991, 992, 993, 994],
                    "objective": phase.get("objective"),
                    "source_checkpoint": phase.get("source_checkpoint"),
                },
            )
            saved, metadata = load_checkpoint(checkpoint)
            restored = restore_candidate(saved, metadata, phase["architecture"])
            readback = restored.decode(mx.array(saved["session.h"]), mx.array(saved["session.z"]))
            mx.eval(readback)
            error = max(
                float(np.max(np.abs(np.array(reference[k]) - np.array(readback[k]))))
                for k in reference
            )
            weights_equal = all(
                np.array_equal(np.array(v), saved[f"model.{k}"])
                for k, v in tree_flatten(restored.parameters())
            )
            opt_equal = all(
                np.array_equal(np.array(v), saved[f"optimizer.{k}"])
                for k, v in tree_flatten(opt.state)
            )
            rng_equal = metadata["rng_states"] == {
                k: v.bit_generator.state for k, v in rngs.items()
            }
            rng_equal = rng_equal and np.array_equal(np.array(key), saved["rng.mlx_key"])
            phase["checkpoint"] = str(checkpoint.resolve())
            phase["checkpoint_checks"] = {
                "model_equal": weights_equal,
                "optimizer_equal": opt_equal,
                "rng_equal": bool(rng_equal),
                "saved_state_decode_max_error": error,
            }
            phase["checkpoint_verified"] = (
                weights_equal and opt_equal and rng_equal and error <= 2e-5
            )
            phase["resume_training_verified"] = False
            if not phase["checkpoint_verified"] or time.perf_counter() - tick > 30:
                raise RuntimeError("checkpoint/state verification failed or exceeded its window")

        def restore_candidate(saved, metadata, architecture):
            if metadata["architecture"] != architecture:
                raise ValueError("checkpoint architecture mismatch despite compatible shapes")
            restored = classes[architecture](config.model, key=mx.random.key(999))
            expected = {f"model.{k}": v.shape for k, v in tree_flatten(restored.parameters())}
            if {k: v.shape for k, v in saved.items() if k.startswith("model.")} != expected:
                raise ValueError("checkpoint parameter keys/shapes mismatch")
            restored.update(
                tree_unflatten(
                    [(k[6:], mx.array(v)) for k, v in saved.items() if k.startswith("model.")]
                )
            )
            mx.eval(restored.parameters())
            return restored

        def train_phase(network, opt, *, action=False, objective=None):
            store.transition(run_id, "training")
            seeds = (
                plan["seeds"]
                if action_comparison
                else {"windows": 101, "augmentation": 307, "frames": 401, "latent": 203}
            )
            rngs = {
                name: np.random.default_rng(seeds[name])
                for name in ("windows", "augmentation", "frames")
            }
            key = mx.random.key(seeds["latent"])
            if not action and initial_metadata is not None:
                for name, rng in rngs.items():
                    rng.bit_generator.state = initial_metadata["rng_states"][name]
                key = mx.array(initial_saved["rng.mlx_key"])
            loss_function = sequence_loss if action else reconstruction_loss
            value_grad = nn.value_and_grad(network, loss_function)
            updates = ACTION_UPDATES if action else FRAME_UPDATES
            size, micro = (16, profile.micro_batch_size) if action else (128, 32)
            previous = 5.0
            for update in range(updates):
                guard()
                minimum_window = (
                    plan["minimum_update_reservation_seconds"] if action_comparison else 2.0
                )
                window = max(minimum_window, min(10.0, 2 * previous))
                # Prepay logical forward edges as well as updates/time for this
                # comparison. Backprop cost is covered by the timed reservation.
                edges = 16 * 20 if action_comparison else 0
                if objective and objective["rollout_weight"]:
                    edges += 16 * 13 * 3
                store.consume(
                    run_id, optimizer_steps=1, active_seconds=window, model_transitions=edges
                )
                tick = time.perf_counter()
                if action:
                    batch = permute_symbols(
                        sampler.sample(size, rngs["windows"]), rngs["augmentation"]
                    )
                else:
                    batch = sample_frames(
                        sampler, rngs["windows"], rngs["augmentation"], rngs["frames"]
                    )
                key, batch_key = mx.random.split(key)
                count = size // micro
                micro_keys = mx.random.split(batch_key, count)
                gradients, total, metrics = None, 0.0, {}
                kwargs = (
                    {"burn_in": 4, "beta_kl": 0.1 * min(1, (update + 1) / 100)} if action else {}
                )
                if objective:
                    kwargs.update(
                        {
                            k: objective[k]
                            for k in ("changed_weight", "rollout_horizon", "rollout_weight")
                        }
                    )
                for part in range(count):
                    values = {
                        k: mx.array(v[part * micro : (part + 1) * micro]) for k, v in batch.items()
                    }
                    (loss, parts), grads = value_grad(
                        network, values, key=micro_keys[part], **kwargs
                    )
                    mx.eval(loss, parts, grads)
                    total += float(loss.item()) / count
                    for name, number in parts.items():
                        metrics[name] = metrics.get(name, 0.0) + float(number.item()) / count
                    scaled = tree_map(lambda g: g / count, grads)
                    gradients = (
                        scaled
                        if gradients is None
                        else tree_map(lambda a, b: a + b, gradients, scaled)
                    )
                    mx.eval(gradients)
                finite = mx.all(
                    mx.stack([mx.all(mx.isfinite(v)) for _, v in tree_flatten(gradients)])
                )
                mx.eval(finite)
                if not bool(finite.item()) or not np.isfinite(total):
                    raise RuntimeError("non-finite reconstruction/action loss or gradients")
                gradients, norm = optim.clip_grad_norm(
                    gradients, config.training.gradient_clip_norm
                )
                opt.update(network, gradients)
                mx.eval(network.parameters(), opt.state, key, norm)
                previous = time.perf_counter() - tick
                phase["actual_optimizer_steps"] += 1
                report["actual_optimizer_steps"] += 1
                entry = {
                    "update": update + 1,
                    "loss": total,
                    "gradient_norm": float(norm.item()),
                    "compute_seconds": previous,
                    "training_model_transitions": edges,
                    **metrics,
                }
                with (directory / f"updates-{run_id}.jsonl").open("a") as f:
                    f.write(json.dumps(entry, allow_nan=False) + "\n")
                phase["training_compute_seconds"] = (
                    phase.get("training_compute_seconds", 0.0) + previous
                )
                if previous > window:
                    raise RuntimeError("update exceeded its prepaid work window")
                if (update + 1) % 50 == 0 or update + 1 == updates:
                    phase["latest_update"] = entry
                    persist()
                rest = previous * (1 / profile.training_duty_cycle - 1)
                if rest:
                    time.sleep(min(rest, 10.0))
            return rngs, key

        if action_comparison:
            architecture = "pilot_shared_symbol_v1"
            for index, objective in enumerate(plan["arms"]):
                if index:
                    begin_phase(
                        architecture, "action_refinement", source=str(initial_checkpoint.resolve())
                    )
                phase["objective"] = objective
                model = restore_candidate(initial_saved, initial_metadata, architecture)
                model.unfreeze()
                phase["parameter_count"] = sum(v.size for _, v in tree_flatten(model.parameters()))
                if phase["parameter_count"] != plan["parameter_ceiling"]:
                    raise RuntimeError("action comparison changed parameter count")
                optimizer = optim.AdamW(learning_rate=config.training.learning_rate, **options)
                optimizer.init(model.trainable_parameters())
                mx.eval(optimizer.state)
                phase["initial_reconstruction"] = frozen_evaluation(model)
                if reconstruction_gate(phase["initial_reconstruction"])["status"] != "passed":
                    raise RuntimeError("source candidate did not retain reconstruction gate")
                phase["initial_prediction"] = frozen_evaluation(model, predictive=True)
                report["action_phase"] = "training"
                rngs, key = train_phase(model, optimizer, action=True, objective=objective)
                phase["final_prediction"] = frozen_evaluation(model, predictive=True)
                phase["prediction_gate"] = prediction_gate(phase["final_prediction"])
                phase["final_reconstruction"] = frozen_evaluation(model)
                phase["reconstruction_gate"] = reconstruction_gate(phase["final_reconstruction"])
                save_candidate(model, optimizer, rngs, key)
                store.transition(run_id, "completed", reason="changed_multistep_arm_no_promotion")
                phase["run"] = store.get_run(run_id).to_dict()
                persist()
            report["action_phase"] = "completed"
        else:
            for index, architecture in enumerate(plan["architectures"]):
                if index:
                    begin_phase(architecture, "reconstruction")
                model = classes[architecture](config.model, key=mx.random.key(0))
                if initial_metadata is not None:
                    model = restore_candidate(initial_saved, initial_metadata, architecture)
                phase["parameter_count"] = sum(v.size for _, v in tree_flatten(model.parameters()))
                if phase["parameter_count"] != plan["expected_parameter_counts"][architecture]:
                    raise RuntimeError(
                        "architecture exceeds or differs from registered parameter count"
                    )
                model.gru.freeze()
                model.action_embedding.freeze()
                for layer in model.prior:
                    layer.freeze()
                optimizer = optim.AdamW(learning_rate=0.001, **options)
                optimizer.init(model.trainable_parameters())
                mx.eval(model.parameters(), optimizer.state)
                phase["trainable_parameter_count"] = sum(
                    v.size for _, v in tree_flatten(model.trainable_parameters())
                )
                phase["initial_reconstruction"] = frozen_evaluation(model)
                rngs, key = train_phase(model, optimizer)
                phase["final_reconstruction"] = frozen_evaluation(model)
                phase["reconstruction_gate"] = reconstruction_gate(phase["final_reconstruction"])
                save_candidate(model, optimizer, rngs, key)
                store.transition(run_id, "completed", reason="reconstruction_comparison_complete")
                phase["run"] = store.get_run(run_id).to_dict()
                persist()

            chosen = choose_reconstruction(report["phases"])
            if chosen is None:
                report["action_phase"] = "blocked_by_reconstruction_gate"
            else:
                architecture, checkpoint = chosen["architecture"], chosen["checkpoint"]
                report["selected_architecture"] = architecture
                begin_phase(architecture, "action_prediction", source=checkpoint)
                model = restore_candidate(*load_checkpoint(Path(checkpoint)), architecture)
                model.unfreeze()
                phase["parameter_count"] = sum(v.size for _, v in tree_flatten(model.parameters()))
                optimizer = optim.AdamW(learning_rate=config.training.learning_rate, **options)
                optimizer.init(model.trainable_parameters())
                mx.eval(optimizer.state)
                phase["initial_reconstruction"] = frozen_evaluation(model)
                if reconstruction_gate(phase["initial_reconstruction"])["status"] != "passed":
                    raise RuntimeError("loaded candidate did not retain reconstruction gate")
                phase["initial_prediction"] = frozen_evaluation(model, predictive=True)
                report["action_phase"] = "training"
                rngs, key = train_phase(model, optimizer, action=True)
                phase["final_prediction"] = frozen_evaluation(model, predictive=True)
                phase["prediction_gate"] = prediction_gate(phase["final_prediction"])
                phase["final_reconstruction"] = frozen_evaluation(model)
                phase["reconstruction_gate"] = reconstruction_gate(phase["final_reconstruction"])
                save_candidate(model, optimizer, rngs, key)
                report["action_phase"] = "completed"
                store.transition(run_id, "completed", reason="action_prediction_probe_no_promotion")
                phase["run"] = store.get_run(run_id).to_dict()
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        report["status"] = "completed"
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if model is not None and optimizer is not None:
            try:
                tensors = {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
                tensors.update(
                    {f"optimizer.{k}": np.array(v) for k, v in tree_flatten(optimizer.state)}
                )
                partial = save_checkpoint(
                    directory / "checkpoints",
                    f"interrupted-{uuid4().hex}",
                    tensors,
                    {
                        "architecture": phase["architecture"],
                        "phase": phase["kind"],
                        "completed_updates": phase["actual_optimizer_steps"],
                        "resume_verified": False,
                    },
                )
                report["interrupted_checkpoint"] = str(partial.resolve())
            except Exception as save_error:
                report["interrupted_checkpoint_error"] = str(save_error)
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason="observation_worker_failure")
    finally:
        if run_id is not None:
            phase["run"] = store.get_run(run_id).to_dict()
        store.close()
        persist()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--control-db", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--structure", choices=("paired", "shared_slots"), default="paired")
    parser.add_argument("--initial-checkpoint", type=Path)
    parser.add_argument("--action-comparison", action="store_true")
    parser.add_argument(
        "--comparison-arm",
        default="all",
        choices=("all", "one_step_control", "changed_weighted", "changed_four_step"),
    )
    args = parser.parse_args()
    report = run_observation(
        args.config,
        args.dataset,
        args.output_dir,
        args.control_db,
        args.experiment_id,
        args.structure,
        args.initial_checkpoint,
        args.action_comparison,
        args.comparison_arm,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
