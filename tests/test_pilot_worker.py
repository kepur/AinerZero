import argparse
import json
import subprocess
from pathlib import Path

import pytest

from ainerzero.cli import train_pilot_command
from ainerzero.core.pilot import PilotConfig
from ainerzero.runtime.lifecycle import RunStore
from ainerzero.runtime.pilot_worker import fit_manifest, prediction_gate


@pytest.mark.parametrize(
    "values", [(0, 16, 4), (101, 16, 4), (True, 16, 4), (100, 0, 4), (100, 16, 9)]
)
def test_fit_check_cannot_expand_its_small_scope(values):
    with pytest.raises(ValueError):
        fit_manifest(
            PilotConfig().model_dump(mode="json"),
            updates=values[0],
            train_episodes=values[1],
            development_episodes=values[2],
        )


def evaluation(model_nll=0.8, changed_nll=1.0, count=8):
    row = {
        "model": {"nll": model_nll, "changed_nll": changed_nll, "changed_count": count},
        "copy": {"nll": 1.0, "changed_nll": 2.0},
        "no_action": {"nll": 2.0, "changed_nll": 3.0},
    }
    return {"horizons": {"1": row, "4": row}}


def test_acceptance_needs_both_horizons_best_baseline_and_measurable_changes():
    assert prediction_gate(evaluation())["status"] == "passed"
    assert prediction_gate(evaluation(model_nll=1.2))["status"] == "not_passed"
    assert prediction_gate(evaluation(changed_nll=2.1))["status"] == "not_passed"
    assert prediction_gate(evaluation(count=0))["status"] == "not_passed"
    result = prediction_gate(evaluation())
    assert result["multi_seed_acceptance"] == "not_evaluated"


@pytest.fixture
def args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return argparse.Namespace(
        config=config,
        output_dir=tmp_path / "output",
        experiment_id="test",
        seed=0,
        updates=2,
        train_episodes=1,
        development_episodes=1,
    )


def test_supervisor_passes_canonical_ledger_and_propagates_results(args, monkeypatch):
    def run(command, **kwargs):
        assert (
            Path(command[command.index("--control-db") + 1])
            == args.config.parents[1] / "artifacts/control.sqlite3"
        )
        assert kwargs["timeout"] <= 1200
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert train_pilot_command(args)["status"] == "completed"


def test_paired_training_forwards_dataset_and_opt_in_transform(args, monkeypatch):
    args.dataset = args.output_dir / "dataset.json"
    args.symbol_augmentation = "per_window_permutation"

    def run(command, **kwargs):
        assert command[command.index("--dataset") + 1] == str(args.dataset.resolve())
        assert command[command.index("--symbol-augmentation") + 1] == args.symbol_augmentation
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert train_pilot_command(args)["status"] == "completed"


def test_diagnostics_share_supervisor_and_have_shorter_timeout(args, monkeypatch):
    args.source_report = args.output_dir / "source.json"

    def run(command, **kwargs):
        assert command[command.index("-m") + 1] == "ainerzero.runtime.pilot_diagnostics"
        assert "--updates" not in command
        assert kwargs["timeout"] <= 180
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert train_pilot_command(args)["status"] == "completed"


def test_unknown_augmentation_is_rejected():
    with pytest.raises(ValueError, match="augmentation"):
        fit_manifest(
            {},
            updates=1,
            train_episodes=1,
            development_episodes=1,
            symbol_augmentation="invent_rules",
        )


@pytest.mark.parametrize("timeout", [False, True])
def test_native_failure_or_timeout_marks_new_live_run_failed(args, monkeypatch, timeout):
    def run(command, **kwargs):
        database = command[command.index("--control-db") + 1]
        with RunStore(database) as store:
            # A minimal old-style run still proves supervisor reaping is independent
            # of whether the worker reached model setup before crashing.
            store.create_run(
                {"budget": PilotConfig().budget.model_dump(mode="json")}, "orphan", run_id="orphan"
            )
            store.transition("orphan", "initializing")
        if timeout:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, -9, "", "native process ended")

    monkeypatch.setattr(subprocess, "run", run)
    report = train_pilot_command(args)
    assert report["status"] == "failed"
    assert report["interrupted_run_ids"] == ["orphan"]
    with RunStore(args.config.parents[1] / "artifacts/control.sqlite3") as store:
        assert store.get_run("orphan").state == "failed"
