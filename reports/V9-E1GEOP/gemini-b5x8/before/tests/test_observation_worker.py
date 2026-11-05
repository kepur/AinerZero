import argparse
import json
import subprocess

import numpy as np
import pytest

from ainerzero.cli import train_pilot_command
from ainerzero.core.pilot import PilotConfig
from ainerzero.runtime import observation_worker
from ainerzero.runtime.observation_worker import (
    choose_reconstruction,
    observation_plan,
    sample_frames,
)


@pytest.fixture(name="args")
def observation_args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return argparse.Namespace(
        config=config, output_dir=tmp_path / "output", experiment_id="test", observation_first=True
    )


def test_observation_command_has_a_bounded_supervised_worker(args, monkeypatch):
    args.observation_first = True
    args.dataset = args.output_dir / "source-dataset.json"
    args.initial_checkpoint = args.output_dir / "saved-observation"
    args.structure = "shared_slots"

    def run(command, **kwargs):
        assert command[command.index("-m") + 1] == "ainerzero.runtime.observation_worker"
        assert "--updates" not in command
        assert kwargs["timeout"] <= 1200
        assert command[command.index("--dataset") + 1] == str(args.dataset.resolve())
        assert command[command.index("--initial-checkpoint") + 1] == str(
            args.initial_checkpoint.resolve()
        )
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert train_pilot_command(args)["status"] == "completed"


def test_action_comparison_uses_same_supervised_lock_and_timeout(args, monkeypatch):
    args.dataset = args.output_dir / "source-dataset.json"
    args.initial_checkpoint = args.output_dir / "saved-action"
    args.structure = "shared_slots"
    args.action_comparison = True

    def run(command, **kwargs):
        assert "--action-comparison" in command
        assert "--initial-checkpoint" in command
        assert kwargs["timeout"] == 1200
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert train_pilot_command(args)["status"] == "completed"


def test_action_comparison_requires_source_and_rejects_reconstruction_phase(tmp_path, monkeypatch):
    config = PilotConfig()
    monkeypatch.setattr(observation_worker, "load_pilot_config", lambda _: config)
    monkeypatch.setattr(observation_worker, "load_pilot_dataset", lambda *_: ({}, {}, {}))
    with pytest.raises(ValueError, match="requires a verified source"):
        observation_worker.run_observation(
            tmp_path, tmp_path, tmp_path, tmp_path, "test", action_comparison=True
        )
    monkeypatch.setattr(
        observation_worker,
        "load_checkpoint",
        lambda _: (
            {},
            {
                "architecture": "pilot_shared_symbol_v1",
                "phase": "reconstruction",
                "dataset_source": {},
                "config": config.model_dump(mode="json"),
            },
        ),
    )
    with pytest.raises(ValueError, match="mismatch"):
        observation_worker.run_observation(
            tmp_path,
            tmp_path,
            tmp_path,
            tmp_path,
            "test",
            structure="shared_slots",
            initial_checkpoint=tmp_path,
            action_comparison=True,
        )
    assert not list(tmp_path.glob("pilot-*"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("architecture", "pilot_predictor_v1"),
        ("phase", "action_prediction"),
        ("dataset_source", {"different": True}),
        ("config", {}),
    ],
)
def test_continuation_cannot_mix_architecture_phase_dataset_or_config(
    tmp_path, monkeypatch, field, value
):
    config = PilotConfig()
    metadata = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "reconstruction",
        "dataset_source": {"hash": "same"},
        "config": config.model_dump(mode="json"),
    }
    metadata[field] = value
    monkeypatch.setattr(observation_worker, "load_pilot_config", lambda _: config)
    monkeypatch.setattr(
        observation_worker, "load_pilot_dataset", lambda *_: ({}, {}, {"hash": "same"})
    )
    monkeypatch.setattr(observation_worker, "load_checkpoint", lambda _: ({}, metadata))
    with pytest.raises(ValueError, match="mismatch"):
        observation_worker.run_observation(
            tmp_path,
            tmp_path,
            tmp_path,
            tmp_path,
            "reject",
            structure="shared_slots",
            initial_checkpoint=tmp_path,
        )
    assert not list(tmp_path.glob("pilot-*"))


def test_predeclared_work_never_expands_parameters_or_run_budget():
    plan = observation_plan()
    assert plan["parameter_ceiling"] == 653072
    assert plan["frame_updates_each"] <= 1000
    assert plan["frame_updates_each"] * 2 + plan["action_updates_max"] <= 3000
    assert plan["automatic_promotion"] is False
    shared = observation_plan("shared_slots")
    assert shared["architectures"] == ["pilot_shared_symbol_v1"]
    assert shared["expected_parameter_counts"]["pilot_shared_symbol_v1"] < plan["parameter_ceiling"]


def phase(architecture, *, passed, checkpoint=True):
    return {
        "architecture": architecture,
        "checkpoint_verified": checkpoint,
        "reconstruction_gate": {"status": "passed" if passed else "not_passed"},
    }


def test_failed_reconstruction_or_checkpoint_never_starts_action_learning():
    assert choose_reconstruction([]) is None
    assert (
        choose_reconstruction(
            [
                phase("pilot_predictor_v1", passed=False),
                phase("pilot_observation_state_v1", passed=True, checkpoint=False),
            ]
        )
        is None
    )


def test_selects_smaller_mechanism_change_only_after_real_gate():
    old = phase("pilot_predictor_v1", passed=True)
    new = phase("pilot_observation_state_v1", passed=True)
    assert choose_reconstruction([new, old]) is old
    old["reconstruction_gate"]["status"] = "not_passed"
    assert choose_reconstruction([new, old]) is new
    shared = phase("pilot_shared_symbol_v1", passed=True)
    assert choose_reconstruction([shared]) is shared


class Sampler:
    def sample(self, size, rng):
        assert size == 16
        return {
            "symbols": rng.integers(0, 256, (16, 21, 8), dtype=np.int32),
            "visible_mask": np.ones((16, 21, 8), dtype=np.bool_),
            "cursor": np.zeros((16, 21), dtype=np.int32),
            "actions": rng.integers(0, 4, (16, 20)),
            "episode_start": np.zeros((16, 21), dtype=np.bool_),
        }


def test_frame_learning_contains_only_current_observation_fields_and_reproduces():
    first = sample_frames(Sampler(), *(np.random.default_rng(s) for s in (101, 307, 401)))
    second = sample_frames(Sampler(), *(np.random.default_rng(s) for s in (101, 307, 401)))
    assert set(first) == {"symbols", "visible_mask", "cursor"}
    assert first["symbols"].shape == first["visible_mask"].shape == (128, 8)
    assert first["cursor"].shape == (128,)
    for name in first:
        np.testing.assert_array_equal(first[name], second[name])
