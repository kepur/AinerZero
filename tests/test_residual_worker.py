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
from ainerzero.runtime import residual_diagnostics
from ainerzero.runtime.history_worker import validate_history_source
from ainerzero.runtime.residual_diagnostics import residual_plan, run_residual_probes


def test_residual_plan_fixes_controls_external_capacity_and_independent_budget():
    plan = residual_plan()
    assert plan["architecture"] == "pilot_shared_symbol_v1"
    assert plan["parameter_count"] == 393232
    assert plan["student_optimizer_steps"] == plan["new_environment_steps"] == 0
    assert plan["protocol"] == "m2g_current_anchored_residual_v1"
    assert plan["prediction"] == "masked_current_embedding_plus_predicted_residual_for_every_sample"
    assert plan["fit_target"] == "past_embedding_minus_masked_current_embedding"
    assert plan["ridge"] == 0.01
    assert plan["delays"] == [1, 2, 4]
    assert plan["feature_kinds"] == ["full_state", "reset_state", "current_only"]
    assert plan["feature_width"] == 272
    assert plan["probe_fits"] == 10 == 1 + len(DELAYS) * len(FEATURE_KINDS)
    assert plan["linear_system_solves"] == 80 == plan["probe_fits"] * 8
    assert plan["external_probe_coefficients_each"] == 34944 == 8 * 273 * 16
    assert plan["external_probe_coefficients_total"] == 349440 == 10 * 34944
    assert (plan["train_minimum_tick"], plan["development_minimum_tick"]) == (4, 32)
    assert (plan["train_feature_seed"], plan["development_feature_seed"]) == (1901, 2901)
    assert plan["query_stride"] == 1
    assert sum(plan["resource_seconds"].values()) == 545
    assert 545 < plan["supervised_deadline_seconds"] == 620 < 650
    assert plan["fit_order"] == "all_train_only_fits_saved_before_development_feature_extraction"
    assert plan["selection"] == "fixed_single_ridge_no_dev_tuning_no_student_update_or_promotion"
    assert plan["diagnostic_scope"] == "reused_development_worlds_exploratory_not_fresh_acceptance"
    assert "fixed_current_codec" in plan["references"]
    assert "without_fit_not_memory_evidence" in plan["zero_delay_fixed_control"]


def test_residual_cli_uses_existing_supervisor_without_training_arguments(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    args = argparse.Namespace(
        config=config,
        residual_diagnostic=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "checkpoint",
        output_dir=tmp_path / "artifacts",
        experiment_id="residual-test",
    )
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.history_worker"
        assert command.count("--residual") == 1
        assert "--recall" not in command
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


def test_residual_cli_parser_requires_explicit_source_and_marks_diagnostic(monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        assert args.residual_diagnostic is True
        assert not hasattr(args, "updates")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert (
        cli.main(
            [
                "diagnose-residual-recall",
                "--dataset",
                "/tmp/fixture-dataset.json",
                "--checkpoint",
                "/tmp/fixture-checkpoint",
                "--experiment-id",
                "residual-test",
            ]
        )
        == 0
    )
    assert len(calls) == 1


@pytest.mark.parametrize("missing", ["--dataset", "--checkpoint", "--experiment-id"])
def test_residual_cli_rejects_missing_source_fields(missing):
    arguments = {
        "--dataset": "/tmp/fixture-dataset.json",
        "--checkpoint": "/tmp/fixture-checkpoint",
        "--experiment-id": "residual-test",
    }
    with pytest.raises(SystemExit) as error:
        cli.main(
            ["diagnose-residual-recall"]
            + [part for key, value in arguments.items() if key != missing for part in (key, value)]
        )
    assert error.value.code == 2


def test_external_residual_probe_cannot_be_loaded_as_student():
    config = PilotConfig().model_dump(mode="json")
    identity = {"hash": "fixture"}
    metadata = {
        "architecture": "external_residual_recall_probe_v1",
        "phase": "action_refinement",
        "config": config,
        "dataset_source": identity,
        "optimizer_steps": 100,
        "run_id": "fixture-parent",
    }
    with pytest.raises(ValueError, match="architecture"):
        validate_history_source(metadata, config, identity)


def install_residual_fakes(monkeypatch, *, damage=None):
    events, fitted, progress = [], {}, []
    model = object()
    episodes = {"train": ["train-fixture"], "development": ["development-fixture"]}
    tensors = {
        "model.byte_embedding.weight": np.zeros((256, 16)),
        "model.symbol_readout.weight": np.zeros((256, 16)),
        "model.symbol_readout.bias": np.zeros(256),
    }
    actual_save = residual_diagnostics.save_checkpoint
    actual_load = residual_diagnostics.load_checkpoint

    def probe(value):
        return {
            "feature_mean": np.zeros(2),
            "feature_scale": np.ones(2),
            "coefficients": np.full((8, 3, 16), float(value)),
            "fit_counts": np.ones(8, dtype=np.int64),
        }

    def collect(actual_model, data, embedding, *, partition, seed, before_work):
        assert actual_model is model
        assert data is episodes[partition]
        assert seed == (1901 if partition == "train" else 2901)
        events.append(("collect", partition))
        before_work(16)
        return {"partition": partition, "logical_model_units": 16}

    def rows(collection, *, delay, minimum_tick):
        partition = collection["partition"]
        assert delay in (0, *DELAYS)
        assert minimum_tick == (4 if partition == "train" else 32)
        return {
            "partition": partition,
            "delay": delay,
            "features": {kind: np.array([[0.0, 1.0], [1.0, 1.0]]) for kind in FEATURE_KINDS},
        }

    def fit_dense(data, embedding, *, ridge):
        assert data["partition"] == "train" and data["delay"] == 0
        assert ridge == 0.01
        events.append(("fit", 0))
        fitted[0] = probe(0)
        return fitted[0]

    def fit_residual(data, embedding, *, ridge):
        assert data["partition"] == "train"
        assert ridge == 0.01
        delay = data["delay"]
        events.append(("fit", delay))
        fitted[delay] = {kind: probe(delay) for kind in FEATURE_KINDS}
        return fitted[delay]

    def assert_restored(actual, original):
        for name, array in actual.items():
            assert not np.shares_memory(array, original[name])
            np.testing.assert_array_equal(array, original[name])

    def score_zero(dense, data, embedding, weight, bias):
        partition = data["partition"]
        assert data["delay"] == 0
        events.append(("score_zero", partition))
        if partition == "development":
            assert_restored(dense, fitted[0])
            if damage == "development_dense":
                dense["coefficients"][0, 0, 0] += 1
            elif damage == "development_dense_replace":
                dense["coefficients"] = dense["coefficients"] + 1
        checks = {
            "zero_residual_preserves_embedding": True,
            "zero_residual_preserves_decoding": True,
        }
        if damage == f"zero_{partition}":
            checks["zero_residual_preserves_embedding"] = False
        if damage == "zero_missing" and partition == "development":
            del checks["zero_residual_preserves_decoding"]
        # A failed dense positive control is a diagnostic finding, never a gate failure.
        return {
            "pipeline_checks": checks,
            "methods": {"dense_current_only": {"symbol_accuracy": 0.0}},
        }

    def score_residual(probes, data, embedding, weight, bias):
        partition, delay = data["partition"], data["delay"]
        events.append(("score", partition, delay))
        if partition == "development":
            for kind in FEATURE_KINDS:
                assert_restored(probes[kind], fitted[delay][kind])
            if damage == "development_residual" and delay == 1:
                probes["full_state"]["coefficients"][0, 0, 0] += 1
            elif damage == "development_residual_replace" and delay == 1:
                probes["full_state"]["coefficients"] = probes["full_state"]["coefficients"] + 1
        return {"partition": partition, "delay": delay, "fixture": True}

    def save(root, checkpoint_id, arrays, metadata):
        events.append(("save",))
        assert set(fitted) == {0, 1, 2, 4}
        assert metadata["architecture"] == "external_residual_recall_probe_v1"
        assert metadata["not_a_student_checkpoint"] is True
        assert metadata["fit_partition"] == "train"
        assert metadata["student_optimizer_steps"] == 0
        assert metadata["completed_probe_fits"] == 10
        assert len(arrays) == 40
        assert all(name.startswith(("residual.d", "dense.d0.current_only.")) for name in arrays)
        return actual_save(root, checkpoint_id, arrays, metadata)

    def load(checkpoint):
        events.append(("restore",))
        arrays, metadata = actual_load(checkpoint)
        arrays = {key: value.copy() for key, value in arrays.items()}
        if damage == "restore_value":
            arrays["residual.d1.full_state.coefficients"][0, 0, 0] += 1
        elif damage == "restore_missing":
            del arrays["dense.d0.current_only.coefficients"]
        elif damage == "restore_extra":
            arrays["unexpected"] = np.array([0.0])
        return arrays, metadata

    for name, fake in {
        "collect_probe_features": collect,
        "make_residual_rows": rows,
        "fit_zero_delay_dense": fit_dense,
        "fit_residual_rows": fit_residual,
        "score_zero_delay_controls": score_zero,
        "score_residual_rows": score_residual,
        "save_checkpoint": save,
        "load_checkpoint": load,
    }.items():
        monkeypatch.setattr(residual_diagnostics, name, fake)
    return model, episodes, tensors, events, progress


@pytest.mark.parametrize(
    "damage",
    [
        None,
        "restore_value",
        "restore_missing",
        "restore_extra",
        "development_residual",
        "development_dense",
        "development_residual_replace",
        "development_dense_replace",
        "zero_train",
        "zero_development",
        "zero_missing",
    ],
)
def test_residual_orchestration_fits_restores_and_checks_controls_before_dev_delays(
    tmp_path, monkeypatch, damage
):
    model, episodes, tensors, events, progress = install_residual_fakes(monkeypatch, damage=damage)
    original_tensors = deepcopy(tensors)
    options = {
        "plan": residual_plan(),
        "source": {"checkpoint": "frozen-student-fixture"},
        "directory": tmp_path,
        "stage": lambda name: events.append(("stage", name)),
        "reserve": lambda count: events.append(("reserve", count)),
        "guard": lambda **kwargs: None,
        "progress": lambda result: progress.append(deepcopy(result)),
    }
    if damage:
        message = (
            "roundtrip mismatch"
            if damage.startswith("restore_")
            else "pipeline check failed"
            if damage.startswith("zero_")
            else "changed frozen residual probe"
        )
        with pytest.raises(RuntimeError, match=message):
            run_residual_probes(model, episodes, tensors, **options)
    else:
        result = run_residual_probes(model, episodes, tensors, **options)
        assert result["completed_probe_fits"] == 10
        assert result["completed_linear_systems"] == 80
        assert result["student_optimizer_steps"] == 0
        assert result["logical_model_units"] == 32
        assert result["probe_checkpoint_verified"] is True
        assert result["probes_frozen_before_development"] is True
        assert result["probe_arrays_unchanged_during_development"] is True
        assert set(result["training"]) == set(result["development"]) == {"1", "2", "4"}
        assert len(result["probe_manifest_sha256"]) == 64
        assert (
            result["zero_delay"]["development"]["methods"]["dense_current_only"]["symbol_accuracy"]
            == 0
        )
        assert [item[1] for item in events if item[0] == "stage"] == [
            "train_features",
            "fit",
            "train_score",
            "probe_save",
            "development_features",
            "development_score",
        ]
    ordering = [event for event in events if event[0] in {"collect", "fit", "save", "restore"}]
    expected = [("collect", "train"), ("fit", 0), ("fit", 1), ("fit", 2), ("fit", 4)]
    if damage != "zero_train":
        expected.extend([("save",), ("restore",)])
        if not str(damage).startswith("restore_"):
            expected.append(("collect", "development"))
    assert ordering == expected
    for partition in ("train", "development"):
        scores = [event for event in events if event[:2] == ("score", partition)]
        if scores:
            assert events.index(("score_zero", partition)) < events.index(scores[0])
    if damage in {"zero_development", "zero_missing"}:
        assert not any(event[:2] == ("score", "development") for event in events)
    if damage == "zero_train":
        assert not any(event[0] == "score" for event in events)
    assert all(snapshot["student_optimizer_steps"] == 0 for snapshot in progress)
    assert progress[-1]["completed_probe_fits"] == 10
    for name in tensors:
        np.testing.assert_array_equal(tensors[name], original_tensors[name])
