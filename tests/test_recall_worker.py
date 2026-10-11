import argparse
import json
import subprocess
from copy import deepcopy

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.cli import train_pilot_command
from ainerzero.core.pilot import PilotConfig
from ainerzero.learning.recall_probe import DELAYS, FEATURE_KINDS
from ainerzero.runtime import recall_diagnostics
from ainerzero.runtime.history_worker import validate_history_source
from ainerzero.runtime.recall_diagnostics import recall_plan, run_recall_probes


def test_recall_plan_fixes_external_capacity_and_budget_without_student_updates():
    plan = recall_plan()
    assert plan["architecture"] == "pilot_shared_symbol_v1"
    assert plan["parameter_count"] == 393232
    assert plan["student_optimizer_steps"] == plan["new_environment_steps"] == 0
    assert plan["ridge"] == 0.01
    assert plan["delays"] == [1, 2, 4]
    assert plan["feature_kinds"] == ["full_state", "reset_state", "current_only"]
    assert plan["feature_width"] == 272
    assert plan["probe_fits"] == 9 == len(plan["delays"]) * len(plan["feature_kinds"])
    assert plan["linear_system_solves"] == 72 == plan["probe_fits"] * 8
    assert plan["external_probe_coefficients_each"] == 34944 == 8 * 273 * 16
    assert plan["external_probe_coefficients_total"] == 314496 == 9 * 34944
    assert (plan["train_minimum_tick"], plan["development_minimum_tick"]) == (4, 32)
    assert plan["query_stride"] == 1
    assert sum(plan["resource_seconds"].values()) == 545
    assert 545 < plan["supervised_deadline_seconds"] == 620 < 650
    assert plan["fit_order"] == "all_train_only_fits_saved_before_development_feature_extraction"
    assert plan["selection"] == "fixed_single_ridge_no_dev_tuning_no_student_update_or_promotion"


def test_recall_cli_uses_history_supervisor_and_has_no_training_arguments(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    args = argparse.Namespace(
        config=config,
        recall_diagnostic=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "checkpoint",
        output_dir=tmp_path / "artifacts",
        experiment_id="recall-test",
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.history_worker"
        assert command.count("--recall") == 1
        assert command[command.index("--checkpoint") + 1] == str(args.checkpoint.resolve())
        assert command[command.index("--dataset") + 1] == str(args.dataset.resolve())
        assert not {
            "--updates",
            "--seed",
            "--train-episodes",
            "--development-episodes",
            "--symbol-augmentation",
            "--initial-checkpoint",
            "--action-comparison",
        }.intersection(command)
        assert kwargs["timeout"] == 650
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert train_pilot_command(args)["status"] == "completed"
    assert len(calls) == 1


def test_recall_cli_parser_marks_diagnostic_and_requires_explicit_source(monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        assert args.recall_diagnostic is True
        assert not hasattr(args, "updates")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert (
        cli.main(
            [
                "diagnose-recall",
                "--dataset",
                "/tmp/fixture-dataset.json",
                "--checkpoint",
                "/tmp/fixture-checkpoint",
                "--experiment-id",
                "recall-test",
            ]
        )
        == 0
    )
    assert len(calls) == 1


def test_external_recall_probe_cannot_be_used_as_student_checkpoint():
    config = PilotConfig().model_dump(mode="json")
    identity = {"hash": "fixture"}
    # Even otherwise compatible action metadata cannot bypass architecture identity.
    metadata = {
        "architecture": "external_recall_probe_v1",
        "phase": "action_refinement",
        "config": config,
        "dataset_source": identity,
        "optimizer_steps": 100,
        "run_id": "fixture-parent",
    }
    with pytest.raises(ValueError, match="architecture"):
        validate_history_source(metadata, config, identity)


def install_orchestration_fakes(monkeypatch, *, damage=None):
    events, fitted, progress = [], {}, []
    model = object()
    episodes = {"train": ["train-fixture"], "development": ["development-fixture"]}
    tensors = {
        "model.byte_embedding.weight": np.zeros((256, 16)),
        "model.symbol_readout.weight": np.zeros((256, 16)),
        "model.symbol_readout.bias": np.zeros(256),
    }
    actual_save = recall_diagnostics.save_checkpoint
    actual_load = recall_diagnostics.load_checkpoint

    def collect(actual_model, data, embedding, *, partition, seed, before_work):
        assert actual_model is model
        assert data is episodes[partition]
        assert (
            seed
            == recall_plan()[f"{'train' if partition == 'train' else 'development'}_feature_seed"]
        )
        events.append(("collect", partition))
        before_work(16)
        return {"partition": partition, "logical_model_units": 16}

    def rows(collection, *, delay, minimum_tick):
        partition = collection["partition"]
        assert minimum_tick == (4 if partition == "train" else 32)
        return {
            "partition": partition,
            "delay": delay,
            "features": {kind: np.array([[0.0, 1.0], [1.0, 1.0]]) for kind in FEATURE_KINDS},
        }

    def fit(data, embedding, *, ridge):
        assert data["partition"] == "train"
        assert ridge == 0.01
        events.append(("fit", data["delay"]))
        fitted[data["delay"]] = {
            kind: {
                "feature_mean": np.zeros(2),
                "feature_scale": np.ones(2),
                "coefficients": np.full((8, 3, 16), float(data["delay"])),
                "fit_counts": np.ones(8, dtype=np.int64),
            }
            for kind in FEATURE_KINDS
        }
        return fitted[data["delay"]]

    def score(probes, data, embedding, weight, bias):
        partition, delay = data["partition"], data["delay"]
        events.append(("score", partition, delay))
        if partition == "development":
            for kind in FEATURE_KINDS:
                for name, array in probes[kind].items():
                    original = fitted[delay][kind][name]
                    assert not np.shares_memory(array, original)
                    np.testing.assert_array_equal(array, original)
            if damage == "development" and delay == 1:
                probes["full_state"]["coefficients"][0, 0, 0] += 1
        return {"partition": partition, "delay": delay, "fixture": True}

    def save(root, checkpoint_id, arrays, metadata):
        events.append(("save",))
        assert len(fitted) == len(DELAYS)
        assert metadata["architecture"] == "external_recall_probe_v1"
        assert metadata["not_a_student_checkpoint"] is True
        assert metadata["fit_partition"] == "train"
        assert metadata["student_optimizer_steps"] == 0
        assert metadata["completed_probe_fits"] == 9
        assert all(name.startswith("probe.") for name in arrays)
        return actual_save(root, checkpoint_id, arrays, metadata)

    def load(checkpoint):
        events.append(("restore",))
        arrays, metadata = actual_load(checkpoint)
        arrays = {key: value.copy() for key, value in arrays.items()}
        if damage == "restore":
            arrays["probe.d1.full_state.coefficients"][0, 0, 0] += 1
        return arrays, metadata

    monkeypatch.setattr(recall_diagnostics, "collect_probe_features", collect)
    monkeypatch.setattr(recall_diagnostics, "make_probe_rows", rows)
    monkeypatch.setattr(recall_diagnostics, "fit_probe_rows", fit)
    monkeypatch.setattr(recall_diagnostics, "score_probe_rows", score)
    monkeypatch.setattr(recall_diagnostics, "save_checkpoint", save)
    monkeypatch.setattr(recall_diagnostics, "load_checkpoint", load)
    return model, episodes, tensors, events, progress


@pytest.mark.parametrize("damage", [None, "restore", "development"])
def test_probe_orchestration_saves_train_fits_before_dev_and_checks_freezing(
    tmp_path, monkeypatch, damage
):
    model, episodes, tensors, events, progress = install_orchestration_fakes(
        monkeypatch, damage=damage
    )
    original_tensors = deepcopy(tensors)
    options = {
        "plan": recall_plan(),
        "source": {"checkpoint": "frozen-student-fixture"},
        "directory": tmp_path,
        "stage": lambda name: events.append(("stage", name)),
        "reserve": lambda count: events.append(("reserve", count)),
        "guard": lambda **kwargs: None,
        "progress": lambda result: progress.append(deepcopy(result)),
    }
    if damage:
        message = "roundtrip mismatch" if damage == "restore" else "changed frozen probe"
        with pytest.raises(RuntimeError, match=message):
            run_recall_probes(model, episodes, tensors, **options)
    else:
        result = run_recall_probes(model, episodes, tensors, **options)
        assert result["completed_probe_fits"] == 9
        assert result["completed_linear_systems"] == 72
        assert result["student_optimizer_steps"] == 0
        assert result["logical_model_units"] == 32
        assert result["probe_checkpoint_verified"] is True
        assert result["probes_frozen_before_development"] is True
        assert result["probe_arrays_unchanged_during_development"] is True
        assert set(result["training"]) == set(result["development"]) == {"1", "2", "4"}
        assert len(result["probe_manifest_sha256"]) == 64
        assert [item[1] for item in events if item[0] == "stage"] == [
            "train_features",
            "fit",
            "train_score",
            "probe_save",
            "development_features",
            "development_score",
        ]
    ordering = [event for event in events if event[0] in {"collect", "fit", "save", "restore"}]
    expected = [("collect", "train"), ("fit", 1), ("fit", 2), ("fit", 4), ("save",), ("restore",)]
    if damage != "restore":
        expected.append(("collect", "development"))
    assert ordering == expected
    assert all(snapshot["student_optimizer_steps"] == 0 for snapshot in progress)
    for name in tensors:
        np.testing.assert_array_equal(tensors[name], original_tensors[name])
