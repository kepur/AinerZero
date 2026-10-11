import argparse
import json
import subprocess
from copy import deepcopy

import pytest

from ainerzero.cli import train_pilot_command
from ainerzero.core.pilot import PilotConfig
from ainerzero.runtime.history_worker import history_plan, validate_history_source


def metadata():
    return {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "action_refinement",
        "config": PilotConfig().model_dump(mode="json"),
        "dataset_source": {"hash": "same"},
        "optimizer_steps": 100,
        "run_id": "parent",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("architecture", "pilot_predictor_v1"),
        ("phase", "reconstruction"),
        ("dataset_source", {}),
        ("config", {}),
        ("optimizer_steps", 0),
        ("optimizer_steps", True),
        ("run_id", None),
    ],
)
def test_history_rejects_mismatched_or_incomplete_sources(field, value):
    original = metadata()
    bad = deepcopy(original)
    bad[field] = value
    with pytest.raises(ValueError, match="mismatch"):
        validate_history_source(bad, original["config"], original["dataset_source"])


@pytest.mark.parametrize("phase", ["action_prediction", "action_refinement"])
def test_history_accepts_matching_completed_action_weights(phase):
    original = metadata()
    original["phase"] = phase
    validate_history_source(original, original["config"], original["dataset_source"])


def test_history_plan_is_frozen_bounded_and_does_not_change_legacy_query_set():
    plan = history_plan()
    assert plan["optimizer_steps"] == plan["new_environment_steps"] == 0
    assert (plan["seed"], plan["support_ticks"], plan["query_stride"], plan["particles"]) == (
        700,
        32,
        8,
        8,
    )
    assert plan["parameter_count"] == 393232
    assert sum(plan["resource_seconds"].values()) <= plan["supervised_deadline_seconds"] < 450


def test_history_cli_uses_supervisor_and_no_training_arguments(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    args = argparse.Namespace(
        config=config,
        history_diagnostic=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "checkpoint",
        output_dir=tmp_path / "artifacts",
        experiment_id="history-test",
    )

    def run(command, **kwargs):
        assert command[command.index("-m") + 1] == "ainerzero.runtime.history_worker"
        assert command[command.index("--checkpoint") + 1] == str(args.checkpoint.resolve())
        assert command[command.index("--dataset") + 1] == str(args.dataset.resolve())
        assert "--updates" not in command
        assert kwargs["timeout"] == 450
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert train_pilot_command(args)["status"] == "completed"
