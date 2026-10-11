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
from ainerzero.runtime.memory_worker import memory_plan, memory_screen


def test_memory_plan_fixes_existing_capacity_work_and_supervised_budget():
    plan = memory_plan()
    assert plan["protocol"] == "m2h_one_step_previous_observation_v1"
    assert plan["architecture"] == "pilot_shared_symbol_v1"
    assert plan["parameter_count"] == 393232
    assert plan["trainable_parameter_count"] == 222208
    assert plan["parameter_count"] - plan["trainable_parameter_count"] == 171024
    assert plan["trainable_modules"] == ["gru"]
    assert plan["updates"] == 100
    assert plan["training_model_units_per_update"] == 336
    assert plan["training_model_units_per_update"] == plan["batch_size"] * (
        1 + plan["burn_in"] + plan["sequence_steps"]
    )
    assert plan["batch_size"] == 16
    assert plan["micro_batch_size"] == 4
    assert plan["transitions_per_window"] == 20
    assert plan["new_environment_steps"] == 0
    assert plan["automatic_promotion"] is False
    assert plan["source_optimizer"] == "reset_AdamW_GRU_only"
    assert plan["readout"] == "reuse_frozen_symbol_head_on_h_tail_8_by_16_after_next_observation"
    assert plan["target"] == "previous_visible_public_observation_uniform_symbol_cross_entropy"
    assert plan["selection"] == "one_fixed_run_no_dev_tuning_no_automatic_retry_or_promotion"
    reserved = (
        sum(plan["resource_seconds"].values())
        + (plan["updates"] - 1) * plan["resource_seconds"]["training_update"]
    )
    assert reserved == plan["total_reserved_seconds_if_complete"] == 1050
    assert 1050 < plan["supervised_deadline_seconds"] == 1500 < 1550


def screen_result():
    score = {"count": 1000, "accuracy": 0.95, "changed_count": 30, "changed_accuracy": 0.8}
    return {
        "methods": {
            "memory_tail": score,
            "copy_current": {**score, "changed_accuracy": 0.0},
            "reset_history": {**score, "changed_accuracy": 0.2},
        },
        "per_world": [
            {"methods": {"memory_tail": {"changed_count": 10, "changed_accuracy": 0.5}}},
            {"methods": {"memory_tail": {"changed_count": 20, "changed_accuracy": 0.95}}},
        ],
    }


def test_memory_screen_accepts_exact_thresholds_without_promotion():
    result = screen_result()
    original = deepcopy(result)
    screen = memory_screen(result, memory_plan())
    assert screen["status"] == "passed"
    assert all(screen["checks"].values())
    assert screen["promotion"] is False
    assert screen["scope"] == "reused_development_one_step_retention_only"
    assert result == original


@pytest.mark.parametrize(
    "field,value,check",
    [
        ("changed_count", 29, "sufficient_changed_targets"),
        ("accuracy", 0.949, "overall_accuracy"),
        ("accuracy", None, "overall_accuracy"),
        ("accuracy", np.nan, "overall_accuracy"),
        ("accuracy", np.inf, "overall_accuracy"),
        ("changed_accuracy", 0.799, "changed_accuracy"),
        ("changed_accuracy", None, "changed_accuracy"),
        ("changed_accuracy", np.nan, "changed_accuracy"),
        ("changed_accuracy", np.inf, "changed_accuracy"),
    ],
)
def test_memory_screen_fails_each_missing_or_insufficient_aggregate(field, value, check):
    result = screen_result()
    result["methods"]["memory_tail"][field] = value
    screen = memory_screen(result, memory_plan())
    assert screen["status"] == "failed"
    assert not screen["checks"][check]
    assert screen["promotion"] is False


@pytest.mark.parametrize("control", ["copy_current", "reset_history"])
@pytest.mark.parametrize("accuracy", [0.8, 0.81, None, np.nan, np.inf])
def test_memory_screen_must_strictly_beat_both_measured_controls(control, accuracy):
    result = screen_result()
    result["methods"][control]["changed_accuracy"] = accuracy
    screen = memory_screen(result, memory_plan())
    assert screen["status"] == "failed"
    assert not screen["checks"]["beats_current_and_reset_changed"]


@pytest.mark.parametrize("accuracy", [0.499, None, np.nan, np.inf])
def test_memory_screen_requires_every_measured_world_to_pass(accuracy):
    result = screen_result()
    result["per_world"][0]["methods"]["memory_tail"]["changed_accuracy"] = accuracy
    screen = memory_screen(result, memory_plan())
    assert screen["status"] == "failed"
    assert not screen["checks"]["each_measured_world"]


@pytest.mark.parametrize("no_worlds", [True, False])
def test_memory_screen_cannot_pass_without_any_measured_world(no_worlds):
    result = screen_result()
    result["per_world"] = (
        []
        if no_worlds
        else [{"methods": {"memory_tail": {"changed_count": 0, "changed_accuracy": None}}}]
    )
    screen = memory_screen(result, memory_plan())
    assert screen["status"] == "failed"
    assert not screen["checks"]["each_measured_world"]


def test_memory_screen_ignores_zero_change_world_beside_measured_worlds():
    result = screen_result()
    result["per_world"].append(
        {"methods": {"memory_tail": {"changed_count": 0, "changed_accuracy": None}}}
    )
    assert memory_screen(result, memory_plan())["status"] == "passed"


@pytest.mark.parametrize("control", ["copy_current", "reset_history"])
def test_memory_screen_requires_controls_to_score_same_changed_targets(control):
    result = screen_result()
    result["methods"][control]["changed_count"] = 29
    screen = memory_screen(result, memory_plan())
    assert screen["status"] == "failed"
    assert not screen["checks"]["beats_current_and_reset_changed"]


def test_memory_screen_requires_world_counts_to_match_aggregate():
    result = screen_result()
    result["per_world"][0]["methods"]["memory_tail"]["changed_count"] = 9
    screen = memory_screen(result, memory_plan())
    assert screen["status"] == "failed"
    assert not screen["checks"]["each_measured_world"]


def test_memory_cli_dispatches_fixed_worker_under_1550_second_supervisor(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    args = argparse.Namespace(
        config=config,
        memory_training=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "checkpoint",
        output_dir=tmp_path / "artifacts",
        experiment_id="memory-test",
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.memory_worker"
        assert command[command.index("--checkpoint") + 1] == str(args.checkpoint.resolve())
        assert command[command.index("--dataset") + 1] == str(args.dataset.resolve())
        assert not {
            "--updates",
            "--seed",
            "--symbol-augmentation",
            "--initial-checkpoint",
            "--recall",
        }.intersection(command)
        assert kwargs["timeout"] == 1550
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.train_pilot_command(args)["status"] == "completed"
    assert len(calls) == 1


def test_memory_cli_parser_has_fixed_plan_and_explicit_source(monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        assert args.memory_training is True
        assert not hasattr(args, "updates")
        assert not hasattr(args, "seed")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert (
        cli.main(
            [
                "train-memory",
                "--dataset",
                "/tmp/memory-dataset.json",
                "--checkpoint",
                "/tmp/memory-checkpoint",
                "--experiment-id",
                "memory-test",
            ]
        )
        == 0
    )
    assert len(calls) == 1


@pytest.mark.parametrize("missing", ["--dataset", "--checkpoint", "--experiment-id"])
def test_memory_cli_rejects_missing_source(missing):
    arguments = {
        "--dataset": "/tmp/memory-dataset.json",
        "--checkpoint": "/tmp/memory-checkpoint",
        "--experiment-id": "memory-test",
    }
    with pytest.raises(SystemExit) as error:
        cli.main(
            ["train-memory"]
            + [part for key, value in arguments.items() if key != missing for part in (key, value)]
        )
    assert error.value.code == 2


@pytest.mark.parametrize("override", [["--updates", "101"], ["--seed", "42"]])
def test_memory_cli_rejects_unregistered_training_overrides(override):
    with pytest.raises(SystemExit) as error:
        cli.main(
            [
                "train-memory",
                "--dataset",
                "/tmp/memory-dataset.json",
                "--checkpoint",
                "/tmp/memory-checkpoint",
                "--experiment-id",
                "memory-test",
                *override,
            ]
        )
    assert error.value.code == 2


def install_worker_fakes(tmp_path, monkeypatch):
    config = PilotConfig()
    identity = {"hash": "memory-test-dataset"}
    metadata = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "action_refinement",
        "config": config.model_dump(mode="json"),
        "dataset_source": identity.copy(),
        "optimizer_steps": 100,
        "run_id": "memory-test-parent",
    }
    tensors = {
        "model.byte_embedding.weight": np.zeros((256, 16)),
        "model.symbol_readout.weight": np.zeros((256, 16)),
        "model.symbol_readout.bias": np.zeros(256),
    }
    checkpoint = tmp_path / "source-checkpoint"
    checkpoint.mkdir()
    (checkpoint / "manifest.json").write_text('{"fixture": true}\n')
    options = {
        "config_path": tmp_path / "config.yaml",
        "dataset_path": tmp_path / "dataset.json",
        "checkpoint_path": checkpoint,
        "output_root": tmp_path / "output",
        "control_db": tmp_path / "control.sqlite3",
        "experiment_id": "memory-test",
    }
    manifest = {**config.model_dump(mode="json"), "source": {"sha256": "fixture"}}
    monkeypatch.setattr(memory_worker, "load_pilot_config", lambda _: config)
    monkeypatch.setattr(memory_worker, "load_pilot_dataset", lambda *_: ({}, {}, identity))
    monkeypatch.setattr(memory_worker, "load_checkpoint", lambda _: (tensors, metadata))
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
    monkeypatch.setattr(
        memory_worker.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="AC Power")
    )
    import_attempts = []
    original_import = builtins.__import__

    def forbid_model_import(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx.") or name.endswith("pilot_model"):
            import_attempts.append(name)
            raise AssertionError("codec failure must precede tensor imports and model construction")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_model_import)
    return options, metadata, tensors, import_attempts


def test_failed_fixed_codec_records_zero_student_work_without_importing_model(
    tmp_path, monkeypatch
):
    options, _, tensors, imports = install_worker_fakes(tmp_path, monkeypatch)
    originals = deepcopy(tensors)
    for tensor in tensors.values():
        tensor.flags.writeable = False
    result = memory_worker.run_memory(**options)
    assert result["status"] == "failed"
    assert "bounded frozen codec compatibility check failed" in result["error"]
    assert result["current_stage"] == "compatibility"
    assert result["actual_optimizer_steps"] == result["training_model_transitions"] == 0
    assert result["new_environment_steps"] == 0
    assert result["before"] == result["after"] == {}
    assert result["promoted"] is False
    assert not result["codec_compatibility"]["bounded_codec_compatible"]
    assert "checkpoint" not in result
    assert imports == []
    for key in tensors:
        np.testing.assert_array_equal(tensors[key], originals[key])
    assert json.loads(Path(result["report_path"]).read_text()) == result
    declaration = json.loads((Path(result["run_directory"]) / "preregistration.json").read_text())
    assert declaration["one_step_memory"] == memory_plan()
    with RunStore(options["control_db"]) as store:
        runs = store.list_runs()
        assert len(runs) == 1
        run = runs[0]
        assert run.state == "failed"
        assert run.reason == "one_step_memory_failure"
        assert run.reserved_optimizer_steps == run.reserved_model_transitions == 0
        assert run.reserved_environment_steps == 0
        assert run.reserved_active_seconds == memory_plan()["resource_seconds"]["compatibility"]
        assert store.get_experiment(options["experiment_id"]).model_run_count == 1


@pytest.mark.parametrize("damage", ["missing", "shape", "nonfinite"])
def test_malformed_codec_fails_in_registered_run_before_student_import(
    tmp_path, monkeypatch, damage
):
    options, _, tensors, imports = install_worker_fakes(tmp_path, monkeypatch)
    if damage == "missing":
        del tensors["model.symbol_readout.bias"]
    elif damage == "shape":
        tensors["model.symbol_readout.weight"] = np.zeros((16, 256))
    else:
        tensors["model.byte_embedding.weight"][0, 0] = np.inf
    result = memory_worker.run_memory(**options)
    assert result["status"] == "failed"
    assert result["actual_optimizer_steps"] == 0
    assert result["current_stage"] == "compatibility"
    assert result["run"]["state"] == "failed"
    assert result["run"]["reserved_optimizer_steps"] == 0
    assert imports == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("architecture", "external_residual_recall_probe_v1"),
        ("phase", "reconstruction"),
        ("phase", "one_step_memory"),
        ("dataset_source", {"hash": "different"}),
        ("config", {}),
        ("optimizer_steps", 0),
        ("optimizer_steps", True),
        ("optimizer_steps", 100.0),
        ("run_id", None),
    ],
)
def test_wrong_source_rejected_before_experiment_or_student(tmp_path, monkeypatch, field, value):
    options, metadata, _, imports = install_worker_fakes(tmp_path, monkeypatch)
    metadata[field] = value
    with pytest.raises(ValueError, match="mismatch"):
        memory_worker.run_memory(**options)
    assert not options["output_root"].exists()
    assert not options["control_db"].exists()
    assert imports == []
