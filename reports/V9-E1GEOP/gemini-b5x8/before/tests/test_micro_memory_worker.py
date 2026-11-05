"""CPU-only checks for M2j's fixed work declaration and supervised entry point."""

import argparse
import builtins
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.core.pilot import PilotConfig
from ainerzero.runtime import memory_worker
from ainerzero.runtime.lifecycle import RunStore
from ainerzero.runtime.memory_worker import local_memory_screen, memory_plan, micro_memory_plan


def test_micro_plan_preserves_capacity_and_has_explicit_effective_parameter_scope():
    plan = micro_memory_plan()
    assert plan["protocol"] == "m2j_fixed_single_edge_tail_fit_v1"
    assert plan["architecture"] == "pilot_shared_symbol_v1"
    assert plan["parameter_count"] == 393232
    assert plan["trainable_parameter_count"] == 111104
    assert plan["optimizer_tensor_parameter_count"] == 222208
    assert plan["frozen_parameter_count"] == 282128
    assert plan["parameter_count"] == (
        plan["trainable_parameter_count"] + plan["frozen_parameter_count"]
    )
    assert plan["trainable_scope"] == (
        "GRU_tail_output_rows_only_mask_gradients_project_front_after_AdamW"
    )
    assert plan["source_optimizer"] == "reset_AdamW_GRU_masked_and_projected_front"
    assert plan["automatic_promotion"] is False
    assert plan["new_environment_steps"] == 0
    assert plan["scope"] == "fixed_training_examples_single_feedback_edge_fit_not_general_memory"


def test_micro_plan_reserves_all_local_checks_and_continuous_regressions():
    plan = micro_memory_plan()
    assert plan["updates"] == 200
    assert plan["batch_size"] == 16
    assert plan["micro_batch_size"] == 4
    assert plan["burn_in"] == 0
    assert plan["sequence_steps"] == plan["transitions_per_window"] == 1
    assert plan["training_model_units_per_update"] == 32
    assert plan["training_model_units_per_update"] == plan["batch_size"] * 2
    assert plan["local_checks"] == [0, 50, 100, 150, 200]
    assert plan["local_check_model_units"] == 48
    continuous_phase = 28928 + 7232 + 5376 + 1088
    local_check_count = len(plan["local_checks"]) * 2
    units = (
        2 * continuous_phase
        + plan["updates"] * plan["training_model_units_per_update"]
        + local_check_count * plan["local_check_model_units"]
    )
    assert units == plan["expected_total_model_units"] == 92128
    seconds = plan["resource_seconds"]
    single_stages = sum(
        value for name, value in seconds.items() if name not in {"training_update", "local_check"}
    )
    total = (
        single_stages
        + plan["updates"] * seconds["training_update"]
        + local_check_count * seconds["local_check"]
    )
    assert total == plan["total_reserved_seconds_if_complete"] == 1000
    assert total < plan["supervised_deadline_seconds"] == 1500 < 1550


def test_micro_plan_has_fixed_examples_and_noise_not_augmentation_or_development_tuning():
    plan = micro_memory_plan()
    assert plan["augmentation"] == "none_fixed_batch_repeated"
    assert plan["sample_selection"] == (
        "exactly_16_train_worlds_sorted_episode_then_world_first_visible_change"
    )
    assert plan["seeds"] == {
        "latent": 2203,
        "local_new_noise": 2603,
        "memory_train": 3901,
        "memory_development": 4901,
    }
    assert plan["local_evaluation"] == (
        "one_particle_same_four_micro_batches_same_inputs_two_fixed_noise_seeds"
    )
    assert plan["selection"] == "one_fixed_run_no_dev_tuning_no_automatic_retry_or_promotion"


def test_micro_plan_is_fresh_and_cannot_mutate_m2h_plan():
    original = memory_plan()
    first = micro_memory_plan()
    second = micro_memory_plan()
    first["resource_seconds"]["training_update"] = 999
    first["local_checks"].append(500)
    first["seeds"]["latent"] = 42
    assert micro_memory_plan() == second
    assert memory_plan() == original
    assert original["resource_seconds"]["training_update"] == 5
    assert "local_check" not in original["resource_seconds"]


def local_result():
    return {
        "scope": "fixed_training_inputs_for_one_edge_memory_fit",
        "partition": "train",
        "sample_count": 16,
        "methods": {
            "memory_tail": {
                "count": 128,
                "accuracy": 0.95,
                "changed_count": 16,
                "changed_accuracy": 0.8,
            }
        },
    }


def test_local_screen_accepts_thresholds_without_claiming_generalization_or_promotion():
    result = local_result()
    original = deepcopy(result)
    screen = local_memory_screen(result, micro_memory_plan())
    assert screen["status"] == "passed"
    assert all(screen["checks"].values())
    assert screen["promotion"] is False
    assert screen["scope"] == "fixed_train_examples_fit_only"
    assert result == original


@pytest.mark.parametrize(
    "field,value,check",
    [
        ("accuracy", 0.949, "overall_accuracy"),
        ("accuracy", -0.1, "overall_accuracy"),
        ("accuracy", 1.01, "overall_accuracy"),
        ("accuracy", None, "overall_accuracy"),
        ("accuracy", True, "overall_accuracy"),
        ("accuracy", "0.95", "overall_accuracy"),
        ("accuracy", np.nan, "overall_accuracy"),
        ("accuracy", np.inf, "overall_accuracy"),
        ("changed_accuracy", 0.799, "changed_accuracy"),
        ("changed_accuracy", -0.1, "changed_accuracy"),
        ("changed_accuracy", 1.01, "changed_accuracy"),
        ("changed_accuracy", None, "changed_accuracy"),
        ("changed_accuracy", True, "changed_accuracy"),
        ("changed_accuracy", "0.8", "changed_accuracy"),
        ("changed_accuracy", np.nan, "changed_accuracy"),
        ("changed_accuracy", np.inf, "changed_accuracy"),
        ("changed_count", 15, "sufficient_changed_targets"),
        ("changed_count", 0, "sufficient_changed_targets"),
        ("changed_count", -1, "sufficient_changed_targets"),
        ("changed_count", None, "sufficient_changed_targets"),
        ("changed_count", True, "sufficient_changed_targets"),
        ("changed_count", 16.0, "sufficient_changed_targets"),
        ("changed_count", "16", "sufficient_changed_targets"),
    ],
)
def test_local_screen_rejects_insufficient_or_invalid_metrics(field, value, check):
    result = local_result()
    result["methods"]["memory_tail"][field] = value
    screen = local_memory_screen(result, micro_memory_plan())
    assert screen["status"] == "failed"
    assert screen["checks"][check] is False
    assert screen["promotion"] is False


@pytest.mark.parametrize("field", ["accuracy", "changed_accuracy", "changed_count"])
def test_local_screen_rejects_missing_metric(field):
    result = local_result()
    del result["methods"]["memory_tail"][field]
    assert local_memory_screen(result, micro_memory_plan())["status"] == "failed"


@pytest.fixture
def cli_args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return argparse.Namespace(
        config=config,
        micro_memory_training=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "source-checkpoint",
        output_dir=tmp_path / "output",
        experiment_id="micro-memory-test",
    )


@pytest.mark.parametrize("wall_limit", [1800, 120])
def test_micro_cli_holds_shared_lock_and_uses_canonical_ledger_and_supervisor(
    cli_args, monkeypatch, wall_limit
):
    cli_args.config.write_text(f"budget:\n  max_wall_seconds: {wall_limit}\n")
    root = cli_args.config.parents[1]
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.memory_worker"
        assert command.count("--local-fit") == 1
        for flag, value in (
            ("--dataset", cli_args.dataset),
            ("--checkpoint", cli_args.checkpoint),
            ("--control-db", root / "artifacts/control.sqlite3"),
        ):
            assert command[command.index(flag) + 1] == str(value.resolve())
        assert not {
            "--updates",
            "--seed",
            "--symbol-augmentation",
            "--initial-checkpoint",
            "--recall",
            "--residual",
        }.intersection(command)
        assert kwargs["timeout"] == min(1550, wall_limit)
        with pytest.raises(RuntimeError, match="already running"):
            with cli.worker_lock(root / "artifacts/locks/m0-worker.lock"):
                pytest.fail("supervisor released its shared lock during model work")
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.train_pilot_command(cli_args)["status"] == "completed"
    assert len(calls) == 1
    with cli.worker_lock(root / "artifacts/locks/m0-worker.lock"):
        pass


@pytest.mark.parametrize("outcome", ["timeout", "native_crash", "false_success"])
def test_micro_supervisor_fails_new_orphan_and_retains_report_evidence(
    cli_args, monkeypatch, outcome
):
    report_path = cli_args.output_dir / "pilot-fixture/report.json"

    def run(command, **kwargs):
        with RunStore(command[command.index("--control-db") + 1]) as store:
            store.create_run(
                {"budget": PilotConfig().budget.model_dump(mode="json")},
                "orphan",
                run_id="orphan",
            )
            store.transition("orphan", "initializing")
        report_path.parent.mkdir(parents=True)
        report_path.write_text(json.dumps({"status": "running", "retained_checks": [0, 50]}))
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        stdout = json.dumps({"status": "completed"}) if outcome == "false_success" else ""
        return subprocess.CompletedProcess(command, 0 if stdout else -9, stdout, "native failure")

    monkeypatch.setattr(subprocess, "run", run)
    result = cli.train_pilot_command(cli_args)
    assert result["status"] == "failed"
    assert result["interrupted_run_ids"] == ["orphan"]
    saved = json.loads(report_path.read_text())
    assert saved["status"] == "failed"
    assert saved["retained_checks"] == [0, 50]
    with RunStore(cli_args.config.parents[1] / "artifacts/control.sqlite3") as store:
        assert store.get_run("orphan").state == "failed"
        assert store.get_run("orphan").reason == "pilot_supervisor_cleanup"


def arguments():
    return [
        "train-micro-memory",
        "--dataset",
        "/tmp/micro-dataset.json",
        "--checkpoint",
        "/tmp/source-checkpoint",
        "--experiment-id",
        "micro-test",
    ]


def test_micro_parser_exposes_fixed_plan_only(monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        assert args.micro_memory_training is True
        assert not getattr(args, "memory_training", False)
        assert args.dataset == Path("/tmp/micro-dataset.json")
        assert args.checkpoint == Path("/tmp/source-checkpoint")
        assert not hasattr(args, "updates")
        assert not hasattr(args, "seed")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert cli.main(arguments()) == 0
    assert len(calls) == 1


@pytest.mark.parametrize("missing", ["--dataset", "--checkpoint", "--experiment-id"])
def test_micro_parser_requires_explicit_source_and_experiment(missing):
    args = arguments()
    index = args.index(missing)
    del args[index : index + 2]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "override",
    [
        ["--updates", "201"],
        ["--seed", "42"],
        ["--learning-rate", "0.1"],
        ["--batch-size", "32"],
        ["--symbol-augmentation", "per_window_permutation"],
        ["--local-fit"],
    ],
)
def test_micro_parser_rejects_training_or_mode_overrides(override):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments() + override)
    assert error.value.code == 2


def test_micro_codec_failure_preregisters_samples_and_stops_before_tensor_work(
    tmp_path, monkeypatch
):
    from ainerzero.learning import micro_memory

    config = PilotConfig()
    identity = {"hash": "micro-test-dataset"}
    metadata = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "action_refinement",
        "config": config.model_dump(mode="json"),
        "dataset_source": identity,
        "optimizer_steps": 100,
        "run_id": "source",
    }
    tensors = {
        "model.byte_embedding.weight": np.zeros((256, 16)),
        "model.symbol_readout.weight": np.zeros((256, 16)),
        "model.symbol_readout.bias": np.zeros(256),
    }
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "manifest.json").write_text('{"fixture":true}\n')
    fixed_batch = {"symbols": np.zeros((16, 2, 8), dtype=np.int32)}
    evidence = {"partition": "train", "batch_sha256": "fixed-cpu-fixture"}
    training = object()

    def select(value):
        assert value is training
        return fixed_batch, evidence

    monkeypatch.setattr(micro_memory, "select_micro_memory_samples", select)
    monkeypatch.setattr(memory_worker, "load_pilot_config", lambda _: config)
    monkeypatch.setattr(
        memory_worker,
        "load_pilot_dataset",
        lambda *_: ({}, {"train": training, "development": object()}, identity),
    )
    monkeypatch.setattr(memory_worker, "load_checkpoint", lambda _: (tensors, metadata))
    manifest = {**config.model_dump(mode="json"), "source": {"sha256": "fixture"}}
    monkeypatch.setattr(cli, "pilot_manifest", lambda _: {"manifest": deepcopy(manifest)})
    monkeypatch.setattr(memory_worker.psutil, "swap_memory", lambda: SimpleNamespace(used=0))
    monkeypatch.setattr(
        memory_worker.psutil, "virtual_memory", lambda: SimpleNamespace(available=100 * 2**30)
    )
    monkeypatch.setattr(
        memory_worker.psutil,
        "Process",
        lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=1)),
    )
    monkeypatch.setattr(
        memory_worker.psutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 2**30)
    )
    imports = []
    original_import = builtins.__import__

    def forbid_model(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx.") or name.endswith("pilot_model"):
            imports.append(name)
            raise AssertionError("failed codec must prevent model imports")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_model)
    result = memory_worker.run_memory(
        tmp_path / "config.yaml",
        tmp_path / "dataset.json",
        checkpoint,
        tmp_path / "output",
        tmp_path / "control.sqlite3",
        "micro-test",
        local_fit=True,
    )
    assert result["status"] == "failed"
    assert "bounded frozen codec compatibility check failed" in result["error"]
    assert result["actual_optimizer_steps"] == result["training_model_transitions"] == 0
    assert result["tail_protection_checks"] == 0
    assert result["local_checks"] == {}
    assert result["promoted"] is False
    assert result["fixed_samples"] == evidence
    assert imports == []
    assert "checkpoint" not in result
    declaration = json.loads((Path(result["run_directory"]) / "preregistration.json").read_text())
    assert declaration["one_step_memory"] == micro_memory_plan()
    assert declaration["purpose"] == "c0_micro_memory_fit_training_v1"
    assert declaration["fixed_samples"] == evidence
    with np.load(result["fixed_batch_path"]) as saved:
        np.testing.assert_array_equal(saved["symbols"], fixed_batch["symbols"])
    with RunStore(tmp_path / "control.sqlite3") as store:
        run = store.get_run(result["run_id"])
        assert run.state == "failed"
        assert run.reason == "micro_memory_fit_failure"
        assert run.reserved_optimizer_steps == run.reserved_model_transitions == 0
        assert run.reserved_environment_steps == 0
        assert run.reserved_active_seconds == 15
