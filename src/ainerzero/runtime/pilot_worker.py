"""Bounded C0 prediction training in a disposable MLX process.

This fits a candidate and reports held-out prediction; it never promotes a
stable model, trains on development data, or opens a final evaluation set.
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
from ainerzero.data.pilot_dataset import load_pilot_dataset
from ainerzero.data.sequences import SequenceSampler
from ainerzero.data.trajectory import load_trajectory
from ainerzero.learning.baselines import NoActionBaseline
from ainerzero.runtime.c0_collection import RANDOM_ACTOR, collect_c0
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint, save_checkpoint
from ainerzero.runtime.lifecycle import TERMINAL_STATES, BudgetExceeded, RunStore


def prediction_gate(evaluation: dict) -> dict:
    """One-seed development screen, never final research acceptance."""
    results = {}
    for horizon in ("1", "4"):
        row = evaluation["horizons"][horizon]
        model = row["model"]
        candidates = [
            (name, row[name]) for name in ("copy", "no_action") if row[name]["nll"] is not None
        ]
        if model["nll"] is None or not model["changed_count"] or not candidates:
            results[horizon] = {"passed": False, "reason": "insufficient_measurable_samples"}
            continue
        name, best = min(candidates, key=lambda pair: pair[1]["nll"])
        results[horizon] = {
            "passed": model["nll"] <= 0.9 * best["nll"]
            and model["changed_nll"] <= best["changed_nll"],
            "best_baseline": name,
            "model_nll": model["nll"],
            "baseline_nll": best["nll"],
            "model_changed_nll": model["changed_nll"],
            "baseline_changed_nll": best["changed_nll"],
        }
    return {
        "status": "passed" if all(r["passed"] for r in results.values()) else "not_passed",
        "scope": "single_seed_development_only",
        "horizons": results,
        "multi_seed_acceptance": "not_evaluated",
        "goal_planning": "not_evaluated",
    }


def fit_manifest(
    pilot: dict,
    *,
    updates: int,
    train_episodes: int,
    development_episodes: int,
    symbol_augmentation: str = "none",
    dataset_source: dict | None = None,
) -> dict:
    if type(updates) is not int or not 1 <= updates <= 100:
        raise ValueError("the first fit check allows 1..100 optimizer updates")
    if type(train_episodes) is not int or not 1 <= train_episodes <= 32:
        raise ValueError("train_episodes must be 1..32")
    if type(development_episodes) is not int or not 1 <= development_episodes <= 8:
        raise ValueError("development_episodes must be 1..8")
    if symbol_augmentation not in {"none", "per_window_permutation"}:
        raise ValueError("unsupported symbol augmentation")
    return {
        **pilot,
        "purpose": "c0_prediction_fit_v1",
        "fit_check": {
            "updates": updates,
            "train_episodes": train_episodes,
            "development_episodes": development_episodes,
            "episode_ticks": 128,
            "query_stride": 8,
            "evaluation_seed": 700,
            "sampler": "uniform_windows_with_replacement",
            "checkpoint_check": "inference_optimizer_rng_roundtrip_no_resume_update",
            "symbol_augmentation": symbol_augmentation,
            "dataset_source": dataset_source,
        },
    }


def run_pilot(
    config_path: Path,
    output_root: Path,
    control_db: Path,
    experiment_id: str,
    seed: int,
    updates: int,
    train_episodes: int,
    development_episodes: int,
    dataset_path: Path | None = None,
    symbol_augmentation: str = "none",
) -> dict:
    from ainerzero.cli import pilot_manifest

    config = load_pilot_config(config_path)
    config.snapshot_for_run(seed)  # validates preregistered seed before any work
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    reused = load_pilot_dataset(dataset_path, policy) if dataset_path else None
    if reused and (len(reused[0]["train"]), len(reused[0]["development"])) != (
        train_episodes,
        development_episodes,
    ):
        raise ValueError("requested episode counts differ from the source dataset")
    manifest = fit_manifest(
        pilot_manifest(config_path)["manifest"],
        updates=updates,
        train_episodes=train_episodes,
        development_episodes=development_episodes,
        symbol_augmentation=symbol_augmentation,
        dataset_source=reused[2] if reused else None,
    )
    run_dir = Path(output_root) / f"pilot-{uuid4().hex}"
    run_dir.mkdir(parents=True)
    report_path = run_dir / "report.json"
    events = run_dir / "updates.jsonl"
    started = time.perf_counter()
    report = {
        "status": "running",
        "scope": "C0 prediction fit check; no planning or promotion",
        "experiment_id": experiment_id,
        "seed": seed,
        "requested_updates": updates,
        "actual_optimizer_steps": 0,
        "run_directory": str(run_dir.resolve()),
        "report_path": str(report_path.resolve()),
        "promoted": False,
        "symbol_augmentation": symbol_augmentation,
    }
    store = RunStore(control_db)
    run_id = None
    model = optimizer = None
    key = None
    sampler_rng = np.random.default_rng(seed + 101)
    augmentation_rng = np.random.default_rng(seed + 307)
    data_paths: dict[str, list[Path]] = {"train": [], "development": []}
    last_guard = 0.0
    last_power_check = 0.0
    initial_swap = psutil.swap_memory().used
    profile = config.resources.idle if config.resources.mode == "idle" else config.resources.active
    report["resource_mode"] = "idle" if config.resources.mode == "idle" else "active"

    def persist():
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)

    def guard(*, force=False):
        nonlocal last_guard, last_power_check
        now = time.monotonic()
        if not force and now - last_guard < 1:
            return
        last_guard = now
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("system memory reserve reached; candidate training stopped")
        if psutil.Process().memory_info().rss > profile.project_memory_gib * 2**30:
            raise RuntimeError("worker memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("system swap growth limit reached")
        if psutil.disk_usage(run_dir).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("disk reserve reached")
        if force or now - last_power_check >= 15:
            power = subprocess.run(
                ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5, check=True
            ).stdout
            last_power_check = now
            if "AC Power" not in power:
                raise RuntimeError("pilot training requires confirmed AC power")

    try:
        guard(force=True)
        experiment = store.create_experiment(manifest, f"pilot:{experiment_id}", experiment_id)
        report["manifest_hash"] = experiment.manifest_hash
        persist()
        if reused:
            data_paths = reused[0]
        for partition, count in (
            () if reused else (("train", train_episodes), ("development", development_episodes))
        ):
            for index in range(count):
                guard()
                collection = collect_c0(
                    store,
                    experiment_id,
                    seed=seed * 10000 + index,
                    partition=partition,
                    steps=128,
                    output_root=run_dir / "episodes",
                )
                if collection["actual_environment_steps"] != 128:
                    raise RuntimeError("collection budget ended before a complete training episode")
                data_paths[partition].append(Path(collection["trajectory_path"]))
        dataset = {
            partition: [
                {
                    "path": str(path.resolve()),
                    "public_sha256": hashlib.sha256(
                        (path / "public.jsonl").read_bytes()
                    ).hexdigest(),
                }
                for path in paths
            ]
            for partition, paths in data_paths.items()
        }
        atomic_write_json(run_dir / "dataset.json", dataset)
        train = [load_trajectory(p) for p in data_paths["train"]]
        development = [load_trajectory(p) for p in data_paths["development"]]
        train_worlds = {e.initial.context.environment_instance_id for e in train}
        if train_worlds & {e.initial.context.environment_instance_id for e in development}:
            raise ValueError("training and development worlds overlap")
        sampler = SequenceSampler(
            data_paths["train"],
            policy,
            burn_in=config.training.burn_in_steps,
            sequence_steps=config.training.sequence_steps,
        )
        baseline = NoActionBaseline(policy).fit(train)
        report["dataset"] = {
            "train_episodes": len(train),
            "development_episodes": len(development),
            "collected_environment_steps": 0 if reused else 128 * (len(train) + len(development)),
            "dataset_environment_steps": 128 * (len(train) + len(development)),
            "new_environment_steps": 0 if reused else 128 * (len(train) + len(development)),
            "reused": bool(reused),
            "training_windows": sampler.window_count,
            "worlds_disjoint": True,
            "manifest": str((run_dir / "dataset.json").resolve()),
        }
        run_id = str(uuid4())
        store.create_run(
            {**config.snapshot_for_run(seed), "fit_check": manifest["fit_check"]},
            run_id,
            run_id=run_id,
            experiment_id=experiment_id,
            role="model",
        )
        report["run_id"] = run_id
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        store.consume(run_id, active_seconds=10)

        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten, tree_map, tree_unflatten

        from ainerzero.learning.evaluation import evaluate_predictor
        from ainerzero.learning.pilot_model import PilotPredictor, sequence_loss

        if not mx.metal.is_available():
            raise RuntimeError("Metal unavailable; no CPU fallback for pilot training")
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(int(profile.mlx_memory_gib * 2**30))
        mx.set_cache_limit(int(profile.mlx_cache_gib * 2**30))
        mx.reset_peak_memory()
        model = PilotPredictor(config.model, key=mx.random.key(seed))
        options = dict(
            learning_rate=config.training.learning_rate,
            betas=config.training.adam_betas,
            eps=config.training.adam_epsilon,
            weight_decay=config.training.weight_decay,
            bias_correction=True,
        )
        optimizer = optim.AdamW(**options)
        optimizer.init(model.trainable_parameters())
        mx.eval(model.parameters(), optimizer.state)
        key = mx.random.key(seed + 203)
        report["parameter_count"] = sum(v.size for _, v in tree_flatten(model.parameters()))
        report["backend"] = "MLX Metal GPU"
        report["precision"] = "float32"
        report["effective_batch_size"] = config.training.effective_batch_size
        report["micro_batch_size"] = profile.micro_batch_size

        def evaluate(network, *, ablation=False):
            if store.get_run(run_id).state != "validating":
                store.transition(run_id, "validating")
            store.consume(run_id, active_seconds=90)
            begin = time.perf_counter()

            def before_work(transitions):
                guard()
                if time.perf_counter() - begin > 90:
                    raise RuntimeError("evaluation exceeded its reserved work window")
                store.consume(run_id, model_transitions=transitions)

            result = evaluate_predictor(
                network,
                development,
                baseline,
                seed=700,
                support_ticks=config.evaluation.support_ticks,
                query_stride=8,
                particles=config.evaluation.latent_particles,
                before_work=before_work,
                action_ablation=ablation,
            )
            result["elapsed_seconds"] = time.perf_counter() - begin
            return result

        report["initial_development"] = evaluate(model)
        probe_np = sampler.sample(config.training.effective_batch_size, np.random.default_rng(991))
        probe = {k: mx.array(v) for k, v in probe_np.items()}
        store.transition(run_id, "training")
        store.consume(run_id, active_seconds=10)

        def fixed_loss(network):
            return sequence_loss(network, probe, burn_in=4, beta_kl=0.1, key=mx.random.key(992))[0]

        report["initial_fixed_training_loss"] = float(fixed_loss(model).item())
        value_grad = nn.value_and_grad(model, sequence_loss)
        prior_update_seconds = 5.0
        for update in range(updates):
            guard()
            reservation = max(2.0, min(10.0, prior_update_seconds * 2))
            store.consume(run_id, optimizer_steps=1, active_seconds=reservation)
            tick = time.perf_counter()
            batch = sampler.sample(config.training.effective_batch_size, sampler_rng)
            if symbol_augmentation == "per_window_permutation":
                from ainerzero.data.augmentation import permute_symbols

                batch = permute_symbols(batch, augmentation_rng)
            key, batch_key = mx.random.split(key)
            micro = profile.micro_batch_size
            splits = config.training.effective_batch_size // micro
            micro_keys = mx.random.split(batch_key, splits)
            gradients = None
            metrics = {}
            loss_value = 0.0
            beta = config.training.kl_loss_weight * min(
                1, (update + 1) / config.training.kl_warmup_updates
            )
            for part in range(splits):
                values = {
                    k: mx.array(v[part * micro : (part + 1) * micro]) for k, v in batch.items()
                }
                (loss, parts), grads = value_grad(
                    model, values, burn_in=4, beta_kl=beta, key=micro_keys[part]
                )
                mx.eval(loss, parts, grads)
                loss_value += float(loss.item()) / splits
                for name, number in parts.items():
                    metrics[name] = metrics.get(name, 0.0) + float(number.item()) / splits
                scaled = tree_map(lambda g: g / splits, grads)
                gradients = (
                    scaled if gradients is None else tree_map(lambda a, b: a + b, gradients, scaled)
                )
                mx.eval(gradients)
            finite = mx.all(mx.stack([mx.all(mx.isfinite(g)) for _, g in tree_flatten(gradients)]))
            mx.eval(finite)
            if not bool(finite.item()) or not np.isfinite(loss_value):
                raise RuntimeError("non-finite pilot loss or gradient")
            gradients, norm = optim.clip_grad_norm(gradients, config.training.gradient_clip_norm)
            optimizer.update(model, gradients)
            mx.eval(model.parameters(), optimizer.state, key, norm)
            report["actual_optimizer_steps"] += 1
            prior_update_seconds = time.perf_counter() - tick
            entry = {
                "update": update + 1,
                "loss": loss_value,
                "beta_kl": beta,
                "gradient_norm": float(norm.item()),
                "compute_seconds": prior_update_seconds,
                **metrics,
            }
            with events.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry, allow_nan=False) + "\n")
            if prior_update_seconds > reservation:
                raise RuntimeError("optimizer update exceeded its reserved work window")
            if mx.get_active_memory() > profile.mlx_memory_gib * 2**30:
                raise RuntimeError("MLX allocation limit reached")
            if (update + 1) % 10 == 0 or update + 1 == updates:
                report["latest_update"] = entry
                persist()
            # Conservative active profile while desktop-idle detection is absent.
            rest = prior_update_seconds * (1 / profile.training_duty_cycle - 1)
            if rest:
                time.sleep(min(rest, 10.0))

        report["final_fixed_training_loss"] = float(fixed_loss(model).item())
        report["final_development"] = evaluate(model, ablation=True)
        report["prediction_gate"] = prediction_gate(report["final_development"])
        store.consume(run_id, active_seconds=20)
        tensors = {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
        tensors.update({f"optimizer.{k}": np.array(v) for k, v in tree_flatten(optimizer.state)})
        tensors["rng.mlx_key"] = np.array(key)
        checkpoint = save_checkpoint(
            run_dir / "checkpoints",
            "candidate",
            tensors,
            {
                "architecture": "pilot_predictor_v1",
                "config": config.model_dump(mode="json"),
                "optimizer": options,
                "optimizer_steps": report["actual_optimizer_steps"],
                "numpy_rng_state": sampler_rng.bit_generator.state,
                "augmentation_rng_state": augmentation_rng.bit_generator.state,
                "symbol_augmentation": symbol_augmentation,
                "dataset": dataset,
                "experiment_id": experiment_id,
                "run_id": run_id,
                "manifest_hash": experiment.manifest_hash,
            },
        )
        saved, metadata = load_checkpoint(checkpoint)
        restored = PilotPredictor(config.model, key=mx.random.key(999))
        expected = {f"model.{k}": v.shape for k, v in tree_flatten(restored.parameters())}
        if {k: v.shape for k, v in saved.items() if k.startswith("model.")} != expected:
            raise ValueError("checkpoint model keys or shapes are incompatible")
        restored.update(
            tree_unflatten(
                [(k[6:], mx.array(v)) for k, v in saved.items() if k.startswith("model.")]
            )
        )
        mx.eval(restored.parameters())
        restore_loss = float(fixed_loss(restored).item())
        parameter_error = max(
            float(np.max(np.abs(saved[f"model.{k}"] - np.array(v))))
            for k, v in tree_flatten(restored.parameters())
        )
        restored_rng = np.random.default_rng()
        restored_rng.bit_generator.state = metadata["numpy_rng_state"]
        restored_augmentation_rng = np.random.default_rng()
        restored_augmentation_rng.bit_generator.state = metadata["augmentation_rng_state"]
        restored_opt = optim.AdamW(**metadata["optimizer"])
        restored_opt.state = tree_unflatten(
            [(k[10:], mx.array(v)) for k, v in saved.items() if k.startswith("optimizer.")]
        )
        mx.eval(restored_opt.state)
        optimizer_ok = all(
            np.array_equal(np.array(value), dict(tree_flatten(optimizer.state))[name])
            for name, value in tree_flatten(restored_opt.state)
        )
        report["checkpoint"] = str(checkpoint.resolve())
        report["checks"] = {
            "fixed_training_loss_decreased": report["final_fixed_training_loss"]
            < report["initial_fixed_training_loss"],
            "checkpoint_parameters_equal": parameter_error == 0,
            "checkpoint_inference_equal": abs(restore_loss - report["final_fixed_training_loss"])
            <= 2e-5,
            "checkpoint_optimizer_equal": bool(optimizer_ok),
            "checkpoint_rng_equal": np.array_equal(saved["rng.mlx_key"], np.array(key))
            and restored_rng.bit_generator.state == sampler_rng.bit_generator.state
            and restored_augmentation_rng.bit_generator.state
            == augmentation_rng.bit_generator.state,
        }
        report["mlx_peak_bytes"] = mx.get_peak_memory()
        report["resume_training_verified"] = False
        if not all(
            value for name, value in report["checks"].items() if name.startswith("checkpoint_")
        ):
            raise RuntimeError("checkpoint restoration verification failed")
        report["status"] = "completed"
        store.transition(run_id, "completed", reason="fit_check_complete_no_promotion")
    except BaseException as exc:
        report["status"] = "stopped" if isinstance(exc, BudgetExceeded) else "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        if model is not None and optimizer is not None and key is not None:
            try:
                tensors = {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
                tensors.update(
                    {f"optimizer.{k}": np.array(v) for k, v in tree_flatten(optimizer.state)}
                )
                tensors["rng.mlx_key"] = np.array(key)
                partial = save_checkpoint(
                    run_dir / "checkpoints",
                    "interrupted",
                    tensors,
                    {
                        "architecture": "pilot_predictor_v1",
                        "optimizer_steps": report["actual_optimizer_steps"],
                        "numpy_rng_state": sampler_rng.bit_generator.state,
                        "augmentation_rng_state": augmentation_rng.bit_generator.state,
                        "config": config.model_dump(mode="json"),
                        "reason": report["error"],
                        "resume_verified": False,
                    },
                )
                report["partial_checkpoint"] = str(partial.resolve())
            except Exception as save_error:
                report["partial_checkpoint_error"] = f"{type(save_error).__name__}: {save_error}"
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            if isinstance(exc, BudgetExceeded):
                store.transition(run_id, "stopping", reason="budget_exhausted")
                store.transition(run_id, "stopped", reason="budget_exhausted")
            else:
                store.transition(run_id, "failed", reason="pilot_worker_failure")
    finally:
        if run_id is not None:
            report["run"] = store.get_run(run_id).to_dict()
        store.close()
        persist()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--control-db", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--updates", type=int, default=100)
    parser.add_argument("--train-episodes", type=int, default=16)
    parser.add_argument("--development-episodes", type=int, default=4)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument(
        "--symbol-augmentation", choices=("none", "per_window_permutation"), default="none"
    )
    args = parser.parse_args()
    report = run_pilot(
        args.config,
        args.output_dir,
        args.control_db,
        args.experiment_id,
        args.seed,
        args.updates,
        args.train_episodes,
        args.development_episodes,
        args.dataset,
        args.symbol_augmentation,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
