"""Bounded M0 numerical and persistence check; this is not Brain-0 training."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import numpy as np
import psutil

from ainerzero.core.config import ProjectConfig, config_hash, load_config, save_config_snapshot
from ainerzero.core.logging import configure_logging
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint, save_checkpoint
from ainerzero.runtime.lifecycle import RunStore


def numpy_reference(x: np.ndarray, y: np.ndarray, parameters: dict) -> tuple[float, dict]:
    """Independent analytic gradient for a 4 -> 16 -> 2 tanh network."""
    w1, b1 = parameters["layers.0.weight"], parameters["layers.0.bias"]
    w2, b2 = parameters["layers.2.weight"], parameters["layers.2.bias"]
    hidden = np.tanh(x @ w1.T + b1)
    prediction = hidden @ w2.T + b2
    residual = prediction - y
    output_gradient = 2 * residual / residual.size
    hidden_gradient = (output_gradient @ w2) * (1 - hidden * hidden)
    return float(np.mean(residual * residual)), {
        "layers.0.weight": hidden_gradient.T @ x,
        "layers.0.bias": hidden_gradient.sum(axis=0),
        "layers.2.weight": output_gradient.T @ hidden,
        "layers.2.bias": output_gradient.sum(axis=0),
    }


def run_smoke(
    config_path: Path,
    output_dir: Path,
    device: str,
    steps: int,
    *,
    control_db: Path | None = None,
) -> dict:
    if device not in {"cpu", "gpu"} or type(steps) is not int or not 8 <= steps <= 128:
        raise ValueError("M0 accepts cpu/gpu and 8-128 steps")
    config = load_config(config_path)
    if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
        raise RuntimeError("Available memory is below the configured system reserve")
    output_dir.mkdir(parents=True, exist_ok=True)
    if psutil.disk_usage(output_dir).free < config.resources.minimum_disk_free_gib * 2**30:
        raise RuntimeError("Available disk is below the configured reserve")

    run_id = f"m0-{device}-{uuid4().hex[:12]}"
    run_dir = output_dir / run_id
    run_dir.mkdir()
    log = configure_logging(run_dir / "events.jsonl", run_id)
    save_config_snapshot(config, run_dir / "requested_config.yaml")
    snapshot = config.model_dump(mode="json")
    # Only tighten the user's limits; this tiny test never borrows a six-hour run.
    snapshot["budget"]["max_optimizer_steps"] = min(
        config.budget.max_optimizer_steps, steps + (steps - steps // 2)
    )
    snapshot["budget"]["max_wall_seconds"] = min(config.budget.max_wall_seconds, 120.0)
    effective_config = ProjectConfig.model_validate(snapshot)
    snapshot = effective_config.model_dump(mode="json")
    save_config_snapshot(effective_config, run_dir / "config.yaml")
    database_path = control_db or output_dir / "control.sqlite3"
    store = RunStore(database_path)
    store.create_run(snapshot, request_id=run_id, run_id=run_id)
    completed_steps = 0
    optimizer_elapsed_seconds = 0.0
    reserved_non_optimizer_seconds = 2.0
    started = time.perf_counter()
    report: dict = {
        "schema_version": 1,
        "scope": "M0 tiny-network smoke, not Brain-0",
        "run_id": run_id,
        "device_requested": device,
        "config_hash": config_hash(effective_config),
        "requested_config_hash": config_hash(config),
        "status": "running",
    }
    try:
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        # Prepay all non-update work before even loading the numerical backend.
        # This bounded allowance covers setup, reference checks and restoration.
        store.consume(run_id, active_seconds=reserved_non_optimizer_seconds)

        import mlx.core as mx
        import mlx.nn as nn
        import mlx.optimizers as optim
        from mlx.utils import tree_flatten, tree_unflatten

        if device == "gpu" and not mx.metal.is_available():
            raise RuntimeError("Metal is unavailable; GPU test cannot fall back to CPU")
        mx.set_default_device(mx.gpu if device == "gpu" else mx.cpu)
        if mx.metal.is_available():
            mx.set_memory_limit(256 * 2**20)
            mx.set_cache_limit(32 * 2**20)
            mx.reset_peak_memory()
        mx.random.seed(17)

        def make_model():
            return nn.Sequential(nn.Linear(4, 16), nn.Tanh(), nn.Linear(16, 2))

        optimizer_options = {
            "learning_rate": 0.01,
            "betas": [0.9, 0.999],
            "eps": 1e-8,
            "weight_decay": 0.0001,
            "bias_correction": True,
        }
        model = make_model()
        optimizer = optim.AdamW(**optimizer_options)
        optimizer.init(model.trainable_parameters())
        mx.eval(model.parameters(), optimizer.state)
        dataset_rng = np.random.default_rng(1729)
        data_x = dataset_rng.normal(size=(128, 4)).astype(np.float32)
        data_y = np.tanh(data_x[:, :2] + 0.2 * data_x[:, 2:]).astype(np.float32)
        x, y = mx.array(data_x), mx.array(data_y)

        def loss_fn(network, batch_x, batch_y):
            return mx.mean(mx.square(network(batch_x) - batch_y))

        initial_parameters = {k: np.array(v) for k, v in tree_flatten(model.parameters())}
        value_grad = nn.value_and_grad(model, loss_fn)
        loss, gradients = value_grad(model, x, y)
        mx.eval(loss, gradients)
        reference_loss, reference_gradients = numpy_reference(data_x, data_y, initial_parameters)
        initial_loss = float(loss.item())
        gradient_error = max(
            float(np.max(np.abs(np.array(v) - reference_gradients[k])))
            for k, v in tree_flatten(gradients)
        )
        gradient_ok = all(
            np.allclose(np.array(v), reference_gradients[k], rtol=2e-4, atol=2e-5)
            for k, v in tree_flatten(gradients)
        )
        if not gradient_ok or not np.isclose(initial_loss, reference_loss, atol=2e-5):
            raise RuntimeError(
                "MLX forward/gradient does not match the independent NumPy reference"
            )
        store.transition(run_id, "training")
        order_rng = np.random.default_rng(23)
        key = mx.random.key(31)

        def train_one(network, opt, rng, random_key):
            nonlocal completed_steps, optimizer_elapsed_seconds
            store.consume(run_id, optimizer_steps=1, active_seconds=0.5)
            tick = time.perf_counter()
            indexes = rng.choice(len(data_x), size=32, replace=False)
            new_key, noise_key = mx.random.split(random_key)
            batch_x = mx.array(data_x[indexes])
            batch_x = batch_x + 0.001 * mx.random.normal(batch_x.shape, key=noise_key)
            batch_y = mx.array(data_y[indexes])
            value, grads = nn.value_and_grad(network, loss_fn)(network, batch_x, batch_y)
            finite = mx.all(mx.stack([mx.all(mx.isfinite(v)) for _, v in tree_flatten(grads)]))
            mx.eval(value, finite)
            if not bool(finite.item()) or not np.isfinite(float(value.item())):
                raise RuntimeError("Non-finite training value or gradient")
            grads, _ = optim.clip_grad_norm(grads, 1.0)
            opt.update(network, grads)
            mx.eval(network.parameters(), opt.state, new_key)
            completed_steps += 1
            elapsed = time.perf_counter() - tick
            optimizer_elapsed_seconds += elapsed
            if elapsed > 0.5:
                raise RuntimeError("A tiny step exceeded its reserved half-second work unit")
            return new_key

        halfway = steps // 2
        for _ in range(halfway):
            key = train_one(model, optimizer, order_rng, key)
        tensors = {f"model.{k}": np.array(v) for k, v in tree_flatten(model.parameters())}
        tensors.update({f"optimizer.{k}": np.array(v) for k, v in tree_flatten(optimizer.state)})
        tensors["rng.mlx_key"] = np.array(key)
        checkpoint = save_checkpoint(
            run_dir / "checkpoints",
            "midpoint",
            tensors,
            {
                "scope": "M0 tiny MLP",
                "model_shape": [4, 16, 2],
                "optimizer": optimizer_options,
                "optimizer_steps": halfway,
                "numpy_rng_state": order_rng.bit_generator.state,
                "config": snapshot,
                "seed": 1729,
            },
        )
        for _ in range(steps - halfway):
            key = train_one(model, optimizer, order_rng, key)
        final_loss = float(loss_fn(model, x, y).item())
        final_parameters = {k: np.array(v) for k, v in tree_flatten(model.parameters())}

        # Close and reopen the control store and restore all computation state.
        store.transition(run_id, "pausing", reason="checkpoint_restore_test")
        store.transition(run_id, "paused")
        store.close()
        store = RunStore(database_path)
        store.resume(run_id)
        loaded, metadata = load_checkpoint(checkpoint)
        resumed = make_model()
        resumed.update(
            tree_unflatten(
                [
                    (k.removeprefix("model."), mx.array(v))
                    for k, v in loaded.items()
                    if k.startswith("model.")
                ]
            )
        )
        resumed_opt = optim.AdamW(**metadata["optimizer"])
        resumed_opt.state = tree_unflatten(
            [
                (k.removeprefix("optimizer."), mx.array(v))
                for k, v in loaded.items()
                if k.startswith("optimizer.")
            ]
        )
        resumed_rng = np.random.default_rng()
        resumed_rng.bit_generator.state = metadata["numpy_rng_state"]
        resumed_key = mx.array(loaded["rng.mlx_key"])
        mx.eval(resumed.parameters(), resumed_opt.state)
        for _ in range(steps - halfway):
            resumed_key = train_one(resumed, resumed_opt, resumed_rng, resumed_key)

        store.transition(run_id, "validating")
        resumed_parameters = {k: np.array(v) for k, v in tree_flatten(resumed.parameters())}
        restore_error = max(
            float(np.max(np.abs(final_parameters[k] - resumed_parameters[k])))
            for k in final_parameters
        )
        optimizer_error = max(
            float(
                np.max(
                    np.abs(
                        np.array(value).astype(np.float64)
                        - np.array(dict(tree_flatten(resumed_opt.state))[name]).astype(np.float64)
                    )
                )
            )
            for name, value in tree_flatten(optimizer.state)
        )
        parameter_change = max(
            float(np.max(np.abs(final_parameters[k] - initial_parameters[k])))
            for k in final_parameters
        )
        checks = {
            "numpy_forward_gradient_match": gradient_ok,
            "finite_training": bool(np.isfinite(final_loss)),
            "loss_decreased": final_loss < initial_loss * 0.9,
            "parameters_changed": parameter_change > 1e-6,
            "restored_parameters_match": restore_error <= 2e-5,
            "restored_optimizer_matches": optimizer_error <= 2e-5,
            "restored_rng_matches": bool(np.array_equal(np.array(key), np.array(resumed_key))),
            "budget_persisted": store.get_run(run_id).reserved_optimizer_steps == completed_steps,
        }
        non_optimizer_elapsed_seconds = time.perf_counter() - started - optimizer_elapsed_seconds
        if non_optimizer_elapsed_seconds > reserved_non_optimizer_seconds:
            raise RuntimeError("Setup and validation exceeded their reserved two-second budget")
        report.update(
            {
                "status": "passed" if all(checks.values()) else "failed",
                "test_model": {
                    "architecture": "m0_tanh_mlp",
                    "layers": [4, 16, 2],
                    "dtype": "float32",
                    "initialization": "random",
                    "seed": 17,
                },
                "test_optimizer": optimizer_options,
                "reserved_seconds_per_optimizer_step": 0.5,
                "reserved_non_optimizer_seconds": reserved_non_optimizer_seconds,
                "non_optimizer_elapsed_seconds": non_optimizer_elapsed_seconds,
                "control_database": str(database_path.resolve()),
                "checks": checks,
                "initial_loss": initial_loss,
                "final_loss": final_loss,
                "gradient_max_abs_error": gradient_error,
                "restore_max_abs_error": restore_error,
                "optimizer_restore_max_abs_error": optimizer_error,
                "actual_completed_optimizer_steps": completed_steps,
                "original_trajectory_steps": steps,
                "replayed_after_restore_steps": steps - halfway,
                "parameter_count": sum(v.size for v in final_parameters.values()),
                "checkpoint": str(checkpoint.resolve()),
                "backend": "Metal GPU" if device == "gpu" else "MLX CPU",
                "elapsed_seconds": time.perf_counter() - started,
                "mlx_peak_bytes": mx.get_peak_memory() if mx.metal.is_available() else None,
            }
        )
        store.transition(
            run_id,
            "completed" if report["status"] == "passed" else "failed",
            reason="m0_verified" if report["status"] == "passed" else "m0_check_failed",
        )
        report["run"] = store.get_run(run_id).to_dict()
        log.info(
            "m0_smoke_finished",
            extra={
                "fields": {
                    "status": report["status"],
                    "actual_completed_optimizer_steps": completed_steps,
                    "initial_loss": initial_loss,
                    "final_loss": final_loss,
                }
            },
        )
    except Exception as exc:
        report.update(
            {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "actual_completed_optimizer_steps": completed_steps,
                "elapsed_seconds": time.perf_counter() - started,
            }
        )
        try:
            store.transition(run_id, "failed", reason=type(exc).__name__)
            report["run"] = store.get_run(run_id).to_dict()
        except Exception:
            pass
        log.error("m0_smoke_failed", extra={"fields": {"error_type": type(exc).__name__}})
    finally:
        store.close()
    report_path = run_dir / "report.json"
    report["report_path"] = str(report_path.resolve())
    atomic_write_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", choices=["gpu", "cpu"], required=True)
    parser.add_argument("--steps", type=int, default=64)
    parser.add_argument("--control-db", type=Path)
    args = parser.parse_args()
    try:
        report = run_smoke(
            args.config, args.output_dir, args.device, args.steps, control_db=args.control_db
        )
    except Exception as exc:
        report = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
