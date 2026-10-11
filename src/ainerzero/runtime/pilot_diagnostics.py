"""Bounded frozen-candidate probes; invoked under the CLI's shared worker lock."""

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
from ainerzero.runtime.checkpoints import atomic_write_json, load_checkpoint
from ainerzero.runtime.lifecycle import TERMINAL_STATES, RunStore


def training_support(episodes) -> np.ndarray:
    support = np.zeros((8, 256), dtype=np.bool_)
    for episode in episodes:
        for observation in [episode.initial.payload] + [
            t.next_observation.payload for t in episode.transitions
        ]:
            for position, (symbol, visible) in enumerate(
                zip(observation.symbols, observation.visible_mask, strict=True)
            ):
                if visible:
                    support[position, symbol] = True
    return support


class ObservationProbe:
    """Change only observed symbol inputs; labels, masks and actions stay intact."""

    def __init__(self, model, *, zero_symbols=False):
        self.model = model
        self.zero_symbols = zero_symbols
        self.predictions = []

    def __getattr__(self, name):
        return getattr(self.model, name)

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        import mlx.core as mx

        if self.zero_symbols:
            symbols = mx.zeros_like(symbols)
        return self.model.observe(h, symbols, visible_mask, cursor, key=key)

    def imagine(self, h, z, actions, *, key):
        from ainerzero.learning.evaluation import _mean_probabilities

        result = self.model.imagine(h, z, actions, key=key)
        shape = result["logits"]["symbols"].shape
        self.predictions.append(_mean_probabilities(result["logits"]["symbols"], shape))
        return result


def run_diagnostics(config_path, source_path, output_root, control_db, experiment_id):
    from ainerzero.cli import pilot_manifest

    started = time.perf_counter()
    config = load_pilot_config(config_path)
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    if source.get("status") != "completed":
        raise ValueError("diagnostics require a completed source training report")
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    paths, episodes, identity = load_pilot_dataset(Path(source["dataset"]["manifest"]), policy)
    checkpoint = Path(source["checkpoint"])
    tensors, metadata = load_checkpoint(checkpoint)
    if metadata.get("architecture") != "pilot_predictor_v1":
        raise ValueError("unsupported source checkpoint architecture")
    if metadata.get("run_id") != source["run_id"]:
        raise ValueError("source report and checkpoint run differ")
    if metadata.get("config") != config.model_dump(mode="json"):
        raise ValueError("diagnostic configuration must match the saved candidate")
    declaration = pilot_manifest(config_path)["manifest"]
    declaration.update(
        purpose="c0_frozen_failure_diagnosis_v1",
        diagnostic={
            "source_report_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "checkpoint_manifest_sha256": hashlib.sha256(
                (checkpoint / "manifest.json").read_bytes()
            ).hexdigest(),
            "dataset": identity,
            "probes": ["training_support_mass", "zero_observed_symbols", "window_relabeling"],
            "seed": 700,
            "probe_batch_seed": 991,
            "relabel_seed": 1771,
            "actual_optimizer_steps": 0,
        },
    )
    directory = Path(output_root) / f"pilot-{uuid4().hex}"
    directory.mkdir(parents=True)
    report_path = directory / "report.json"
    report = {
        "status": "running",
        "scope": "frozen_diagnostic_no_training_no_promotion",
        "experiment_id": experiment_id,
        "source_report": str(source_path.resolve()),
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "promoted": False,
        "run_directory": str(directory.resolve()),
        "report_path": str(report_path.resolve()),
    }
    store = RunStore(control_db)
    run_id = None
    initial_swap = psutil.swap_memory().used
    last_power = 0.0
    work_started = None

    def guard():
        nonlocal last_power
        if work_started is not None and time.perf_counter() - work_started > 90:
            raise RuntimeError("frozen diagnostics exceeded the 90-second reserved window")
        if psutil.virtual_memory().available < config.resources.system_reserve_gib * 2**30:
            raise RuntimeError("insufficient system memory reserve")
        if psutil.Process().memory_info().rss > config.resources.active.project_memory_gib * 2**30:
            raise RuntimeError("diagnostic worker memory limit reached")
        if psutil.swap_memory().used - initial_swap > config.resources.swap_growth_gib * 2**30:
            raise RuntimeError("diagnostic swap growth limit reached")
        if psutil.disk_usage(directory).free < config.resources.minimum_disk_free_gib * 2**30:
            raise RuntimeError("diagnostic disk reserve reached")
        now = time.monotonic()
        if now - last_power > 15:
            power = subprocess.run(
                ["pmset", "-g", "batt"], capture_output=True, text=True, timeout=5, check=True
            ).stdout
            if "AC Power" not in power:
                raise RuntimeError("diagnostics require AC power")
            last_power = now

    try:
        guard()
        experiment = store.create_experiment(declaration, experiment_id, experiment_id)
        run_id = str(uuid4())
        snapshot = config.snapshot_for_run(0)
        snapshot["diagnostic"] = declaration["diagnostic"]
        store.create_run(
            snapshot, run_id, run_id=run_id, experiment_id=experiment_id, role="auxiliary"
        )
        store.transition(run_id, "initializing")
        store.transition(run_id, "validating")
        store.consume(run_id, active_seconds=90)
        work_started = time.perf_counter()
        report.update(run_id=run_id, manifest_hash=experiment.manifest_hash)
        atomic_write_json(report_path, report)

        import mlx.core as mx
        from mlx.utils import tree_flatten, tree_unflatten

        from ainerzero.learning.evaluation import evaluate_predictor
        from ainerzero.learning.pilot_model import PilotPredictor, sequence_loss

        if not mx.metal.is_available():
            raise RuntimeError("Metal unavailable; no silent CPU fallback")
        mx.set_default_device(mx.gpu)
        mx.set_memory_limit(int(config.resources.active.mlx_memory_gib * 2**30))
        mx.set_cache_limit(int(config.resources.active.mlx_cache_gib * 2**30))
        model = PilotPredictor(config.model, key=mx.random.key(999))
        expected = {
            f"model.{name}": value.shape for name, value in tree_flatten(model.parameters())
        }
        if {
            name: value.shape for name, value in tensors.items() if name.startswith("model.")
        } != expected:
            raise ValueError("checkpoint parameter keys or shapes differ")
        model.update(
            tree_unflatten(
                [(k[6:], mx.array(v)) for k, v in tensors.items() if k.startswith("model.")]
            )
        )
        mx.eval(model.parameters())
        baseline = NoActionBaseline(policy).fit(episodes["train"])
        support = training_support(episodes["train"])

        def reserve(transitions):
            guard()
            store.consume(run_id, model_transitions=transitions)

        evaluations, wrappers = {}, []
        for name, zero in (("original", False), ("zero_observed_symbols", True)):
            wrapper = ObservationProbe(model, zero_symbols=zero)
            evaluations[name] = evaluate_predictor(
                wrapper,
                episodes["development"],
                baseline,
                seed=700,
                training_symbol_support=support,
                before_work=reserve,
            )
            wrappers.append(wrapper)
        a, b = (np.stack(wrapper.predictions) for wrapper in wrappers)
        report["development"] = evaluations
        report["input_sensitivity"] = {
            "scope": "all_prior_calls_including_online_feedback_and_query_rollout",
            "mean_total_variation": float(np.mean(np.sum(np.abs(a - b), axis=-1) / 2)),
            "argmax_change_fraction": float(np.mean(a.argmax(-1) != b.argmax(-1))),
        }
        sampler = SequenceSampler(paths["train"], policy)
        batch = sampler.sample(16, np.random.default_rng(991))
        renamed = permute_symbols(batch, np.random.default_rng(1771))
        probes = {}
        for name, values, zero in (
            ("original", batch, False),
            ("renamed", renamed, False),
            ("zero_observed_symbols", batch, True),
        ):
            reserve(16 * 20)
            loss, metrics = sequence_loss(
                ObservationProbe(model, zero_symbols=True) if zero else model,
                {k: mx.array(v) for k, v in values.items()},
                burn_in=4,
                beta_kl=0.1,
                key=mx.random.key(992),
            )
            mx.eval(loss, metrics)
            probes[name] = {
                "total_loss": float(loss.item()),
                **{k: float(v.item()) for k, v in metrics.items()},
            }
        report["fixed_training_window_probes"] = probes
        report["training_support_counts"] = support.sum(axis=-1).tolist()
        report["weights_unchanged"] = all(
            np.array_equal(np.array(value), tensors[f"model.{name}"])
            for name, value in tree_flatten(model.parameters())
        )
        if not report["weights_unchanged"]:
            raise RuntimeError("frozen diagnostics changed weights")
        guard()
        report["status"] = "completed"
        store.transition(run_id, "completed", reason="frozen_probes_complete")
    except BaseException as exc:
        report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        if run_id is not None and store.get_run(run_id).state not in TERMINAL_STATES:
            store.transition(run_id, "failed", reason="diagnostic_failure")
    finally:
        if run_id is not None:
            report["run"] = store.get_run(run_id).to_dict()
        store.close()
        report["elapsed_seconds"] = time.perf_counter() - started
        atomic_write_json(report_path, report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--control-db", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    args = parser.parse_args()
    report = run_diagnostics(
        args.config, args.source_report, args.output_dir, args.control_db, args.experiment_id
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
