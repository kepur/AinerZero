"""No-update forward+loss smoke and single-step cost measurement.

This is the only model-touching work S1 phase 1 (this card) performs.  For each
trainable arm and for the A2-frozen D candidate it runs a fixed batch through
the model's forward+loss path only -- no gradient is taken, no optimizer step is
applied, and the parameter SHA256 before/after must be identical.

Measured quantities feed the frozen deadline rule in ``prereg.estimate_budget``:
per-step wall seconds (median of repeated forward+loss calls), process peak RSS,
MLX peak memory, and the fixed-batch loss value.
"""

from __future__ import annotations

import json
import platform
import resource
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from . import arms, data, spec


def process_peak_rss_bytes() -> int:
    """Peak RSS of this process (macOS reports bytes, Linux KiB)."""
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Linux":
        peak *= 1024
    return peak


def host_identity() -> dict:
    import psutil

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": psutil.cpu_count(),
        "total_memory_gib": psutil.virtual_memory().total / float(2**30),
    }


def _measure(
    callable_forward,
    *,
    repeats: int,
) -> tuple[list[float], Any, float]:
    """Time repeated forward calls; returns (times, last output, extra eval time)."""
    import mlx.core as mx

    times = []
    output = None
    for _ in range(int(repeats)):
        started = time.perf_counter()
        output = callable_forward()
        mx.eval(output.loss)
        times.append(time.perf_counter() - started)
    return times, output, float(np.asarray(output.loss))


def run_smoke(
    dataset_dir: Path,
    *,
    batch_size: int | None = None,
    repeats: int | None = None,
    smoke_seed: int = 0,
) -> dict:
    """Run the frozen smoke protocol; writes nothing itself."""
    import mlx.core as mx

    mx.set_default_device(mx.cpu)
    batch_size = int(spec.TIMING["smoke_batch_size"] if batch_size is None else batch_size)
    repeats = int(spec.TIMING["smoke_repeats"] if repeats is None else repeats)
    manifest = data.load_manifest(dataset_dir)
    dataset_identity = data.dataset_identity(manifest)
    train_windows = data.load_training_windows(dataset_dir)
    development_windows = data.load_development_windows(dataset_dir)
    batch = data.fixed_batch(train_windows, batch_size, seed=smoke_seed)
    result: dict[str, Any] = {
        "schema": "ainerzero.v9.s1.smoke.v1",
        "spec": spec.SPEC_NAME,
        "created_unix": time.time(),
        "host": host_identity(),
        "no_update": True,
        "gradients_computed": False,
        "updated_parameters": False,
        "batch_size": batch_size,
        "sequence_steps": int(spec.TRAIN_COMMON["sequence_steps"]),
        "repeats": repeats,
        "smoke_seed": smoke_seed,
        "dataset": {
            "dataset_digest": dataset_identity["dataset_digest"],
            "train_episodes": manifest["counts"].get("train_episodes"),
            "development_episodes": manifest["counts"].get("development_episodes"),
            "train_packets": manifest["counts"].get("train_packets"),
            "development_packets": manifest["counts"].get("development_packets"),
            "train_windows": int(len(train_windows["obs"])),
            "development_windows": int(len(development_windows["obs"])),
            "generation_seconds": float(manifest.get("generation_seconds") or 0.0),
            "total_bytes": int(manifest.get("total_bytes") or 0),
        },
        "trainable_arms": {},
        "d_candidate": {},
        "peak_process_rss_gib": 0.0,
        "peak_mlx_gib": 0.0,
        "data_generation_seconds": float(manifest.get("generation_seconds") or 0.0),
    }
    peak_process = 0
    peak_mlx = 0
    all_unchanged = True
    for arm_id in ("arm2", "arm3", "arm4"):
        model = arms.build_trainable_arm(arm_id, seed=smoke_seed)
        # Warm-up call is not timed; it also establishes deterministic memory state.
        model.forward_loss(batch)
        before = arms.parameter_sha256(model)
        mx.reset_peak_memory()
        times, output, loss = _measure(lambda: model.forward_loss(batch), repeats=repeats)
        mlx_peak = int(mx.get_peak_memory())
        after = arms.parameter_sha256(model)
        unchanged = before == after
        all_unchanged = all_unchanged and unchanged
        peak_process = max(peak_process, process_peak_rss_bytes())
        peak_mlx = max(peak_mlx, mlx_peak)
        result["trainable_arms"][arm_id] = {
            "architecture": model.ARCHITECTURE,
            "parameter_count": arms.count_parameters(model),
            "parameter_sha256_before": before,
            "parameter_sha256_after": after,
            "parameters_unchanged": unchanged,
            "loss": loss,
            "loss_components": {name: float(np.asarray(value)) for name, value in output.metrics.items()},
            "forward_loss_step_seconds": float(np.median(times)),
            "forward_loss_step_seconds_min": float(np.min(times)),
            "forward_loss_step_seconds_max": float(np.max(times)),
            "times_seconds": [float(value) for value in times],
            "peak_mlx_bytes": mlx_peak,
            "peak_mlx_gib": mlx_peak / float(2**30),
        }
    # Arm 1: load by A2 frozen identity and evaluate only.
    d_model, d_info = arms.load_d_candidate()
    d_batch = arms.d_candidate_fixed_batch()
    warm = arms.d_candidate_forward_loss(d_model, d_batch, seed=smoke_seed)
    mx.eval(warm.loss)
    d_before = arms.parameter_sha256(d_model)
    mx.reset_peak_memory()
    times, output, loss = _measure(
        lambda: arms.d_candidate_forward_loss(d_model, d_batch, seed=smoke_seed), repeats=repeats
    )
    d_peak = int(mx.get_peak_memory())
    d_after = arms.parameter_sha256(d_model)
    d_unchanged = d_before == d_after
    all_unchanged = all_unchanged and d_unchanged
    peak_process = max(peak_process, process_peak_rss_bytes())
    peak_mlx = max(peak_mlx, d_peak)
    result["d_candidate"] = {
        "harness": "evaluate_only_a2_frozen_identity",
        "architecture": d_info["architecture"],
        "parameter_count": d_info["parameter_count"],
        "optimizer_steps_in_checkpoint": d_info["optimizer_steps"],
        "parameter_sha256_before": d_before,
        "parameter_sha256_after": d_after,
        "parameters_unchanged": d_unchanged,
        "identity": d_info["identity"],
        "loss": loss,
        "loss_components": {name: float(value) for name, value in output.metrics.items()},
        "forward_loss_step_seconds": float(np.median(times)),
        "forward_loss_step_seconds_min": float(np.min(times)),
        "forward_loss_step_seconds_max": float(np.max(times)),
        "times_seconds": [float(value) for value in times],
        "peak_mlx_bytes": d_peak,
        "peak_mlx_gib": d_peak / float(2**30),
    }
    result["parameters_unchanged"] = bool(all_unchanged)
    result["peak_process_rss_gib"] = peak_process / float(2**30)
    result["peak_mlx_gib"] = peak_mlx / float(2**30)
    result["measurement_note"] = (
        "forward+loss only; no gradient/optimizer step; step times measured on the MLX CPU "
        "device without duty-cycle pacing (the training estimate applies the frozen 0.25 "
        "duty and the 3x update-cost factor in prereg.estimate_budget)"
    )
    return result


def write_smoke(metrics: Mapping[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metrics, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return path


def load_smoke(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def parameter_digests(*, seed: int = 0) -> dict:
    """Rebuild every arm from the frozen spec and hash parameters only.

    No forward pass, no dataset read: this is the independent recomputation a
    verifier uses to check a smoke report's ``parameters_unchanged`` claim
    instead of trusting the flag the smoke wrote about itself (V9.P10 F4).
    """
    import mlx.core as mx

    mx.set_default_device(mx.cpu)
    rows: dict[str, str] = {}
    for arm_id in ("arm2", "arm3", "arm4"):
        model = arms.build_trainable_arm(arm_id, seed=int(seed))
        rows[arm_id] = arms.parameter_sha256(model)
    d_model, _info = arms.load_d_candidate()
    rows["arm1"] = arms.parameter_sha256(d_model)
    return rows

