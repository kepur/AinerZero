import json
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.cli import main
from ainerzero.core.experience import ActorKind, TrainingPolicy
from ainerzero.core.pilot import PilotConfig
from ainerzero.data.trajectory import load_training_trajectory, load_trajectory
from ainerzero.runtime import c0_collection
from ainerzero.runtime.c0_collection import RANDOM_ACTOR, collect_c0, collection_manifest, replay_c0
from ainerzero.runtime.lifecycle import BudgetExceeded, RunStore


@pytest.fixture
def ledger(tmp_path):
    with RunStore(tmp_path / "control.db") as store:
        manifest = collection_manifest(PilotConfig().model_dump(mode="json"))
        exp = store.create_experiment(manifest, "collection-test")
        yield store, exp.experiment_id, tmp_path / "episodes"


def collect(ledger, **updates):
    store, identity, root = ledger
    return collect_c0(
        store,
        identity,
        **{"seed": 0, "partition": "train", "steps": 16, "output_root": root, **updates},
    )


def public_sequence(report):
    episode = load_trajectory(Path(report["trajectory_path"]))
    return (
        episode.initial.payload,
        [(t.action_request.action, t.next_observation.payload) for t in episode.transitions],
    )


def test_engineering_caps_never_expand_a_tighter_user_budget():
    config = PilotConfig.model_validate(
        {
            "budget": {"max_environment_steps": 4, "max_wall_seconds": 5},
            "experiment_budget": {"max_wall_seconds": 8, "max_calibration_seconds": 2},
        }
    )
    snapshot = config.model_dump(mode="json")
    manifest = collection_manifest(snapshot)
    assert manifest["budget"]["max_environment_steps"] == 4
    assert manifest["budget"]["max_wall_seconds"] == 5
    assert manifest["experiment_budget"]["max_wall_seconds"] == 8
    assert manifest["experiment_budget"]["max_calibration_seconds"] == 2
    assert "purpose" not in snapshot


def test_real_collection_replay_and_training_admission_are_connected(ledger):
    store, identity, _ = ledger
    report = collect(ledger, steps=64)
    assert report["learning_status"] == "not_started"
    assert report["actual_environment_steps"] == report["reserved_environment_steps"] == 64
    assert report["symbol_changes"] > 0
    path = Path(report["trajectory_path"])
    episode = load_training_trajectory(path, TrainingPolicy(allowed_actors=(RANDOM_ACTOR,)))
    assert len(episode.transitions) == 64
    assert all(t.action_request.actor.kind is ActorKind.BASELINE for t in episode.transitions)
    with pytest.raises(ValueError, match="not authorized"):
        load_training_trajectory(path, TrainingPolicy(allowed_actors=()))
    assert store.get_experiment(identity).reserved_environment_steps == 64
    verification = replay_c0(store, path)
    assert verification["status"] == "passed"
    assert verification["replayed_steps"] == 64
    assert store.get_experiment(identity).reserved_environment_steps == 128
    assert store.get_experiment(identity).reserved_optimizer_steps == 0
    assert store.get_experiment(identity).model_run_count == 0
    assert all(run.state == "completed" for run in store.list_runs())


def test_determinism_and_partition_namespaces(ledger):
    first = collect(ledger)
    repeated = collect(ledger)
    assert public_sequence(first) == public_sequence(repeated)
    assert first["episode_id"] != repeated["episode_id"]
    other = collect(ledger, partition="development")
    first_episode = load_trajectory(Path(first["trajectory_path"]))
    other_episode = load_trajectory(Path(other["trajectory_path"]))
    assert (
        first_episode.initial.context.environment_instance_id
        != other_episode.initial.context.environment_instance_id
    )
    with pytest.raises(ValueError, match="Only train"):
        load_training_trajectory(
            Path(other["trajectory_path"]), TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"seed": -1},
        {"seed": True},
        {"seed": 2**64},
        {"steps": 129},
        {"steps": 0},
        {"steps": False},
        {"partition": "final"},
    ],
)
def test_invalid_inputs_do_not_create_runs(ledger, updates):
    store, identity, root = ledger
    with pytest.raises(ValueError):
        collect(ledger, **updates)
    assert store.list_runs() == []
    assert store.get_experiment(identity).reserved_environment_steps == 0
    assert not root.exists()


def test_budget_reservation_precedes_every_actual_action(ledger, monkeypatch):
    store, identity, _ = ledger
    original = c0_collection.C0Environment.step
    calls = []

    def guarded_step(env, action):
        assert store.get_experiment(identity).reserved_environment_steps == 16
        calls.append(action)
        return original(env, action)

    monkeypatch.setattr(c0_collection.C0Environment, "step", guarded_step)
    collect(ledger)
    assert len(calls) == 16


def test_partial_budget_saves_completed_prefix_and_does_not_restart(tmp_path):
    manifest = collection_manifest(PilotConfig().model_dump(mode="json"))
    manifest["experiment_budget"]["max_environment_steps"] = 5
    with RunStore(tmp_path / "db") as store:
        exp = store.create_experiment(manifest, "small")
        args = (store, exp.experiment_id, tmp_path / "episodes")
        report = collect(args)
        assert report["stop_reason"] == "budget_exhausted"
        assert report["actual_environment_steps"] == 5
        assert len(load_trajectory(Path(report["trajectory_path"])).transitions) == 5
        with pytest.raises(BudgetExceeded):
            collect(args)
        assert len(store.list_runs()) == 1


def test_replay_needs_full_budget_and_does_not_charge_a_rejected_batch(tmp_path):
    manifest = collection_manifest(PilotConfig().model_dump(mode="json"))
    manifest["experiment_budget"]["max_environment_steps"] = 20
    with RunStore(tmp_path / "db") as store:
        exp = store.create_experiment(manifest, "small")
        report = collect((store, exp.experiment_id, tmp_path / "episodes"))
        with pytest.raises(ValueError, match="complete replay"):
            replay_c0(store, Path(report["trajectory_path"]))
        assert store.get_experiment(exp.experiment_id).reserved_environment_steps == 16
        assert [r.state for r in store.list_runs()].count("failed") == 1


def test_write_failure_keeps_reservation_and_marks_failed(ledger, monkeypatch):
    store, identity, _ = ledger

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(c0_collection, "save_trajectory", fail)
    with pytest.raises(OSError, match="disk full"):
        collect(ledger)
    assert store.get_experiment(identity).reserved_environment_steps == 16
    assert store.list_runs()[0].state == "failed"


def test_private_corruption_never_reports_a_successful_replay(ledger):
    store, identity, _ = ledger
    report = collect(ledger)
    path = Path(report["trajectory_path"])
    with (path / "private.json").open("ab") as handle:
        handle.write(b" ")
    with pytest.raises(ValueError, match="integrity"):
        replay_c0(store, path)
    assert store.get_experiment(identity).reserved_environment_steps == 32
    assert [r.state for r in store.list_runs()].count("failed") == 1


def test_full_episode_reports_limit_and_replays(ledger):
    report = collect(ledger, steps=128)
    assert report["stop_reason"] == "episode_limit"
    assert replay_c0(ledger[0], Path(report["trajectory_path"]))["replayed_steps"] == 128


@pytest.fixture
def cli_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    (tmp_path / "uv.lock").write_text("version=1\n")
    source = tmp_path / "src/ainerzero"
    source.mkdir(parents=True)
    (source / "cli.py").write_text("# test source identity\n")
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return config


def test_cli_real_paths_share_the_project_ledger(cli_project, capsys):
    root = cli_project.parents[1]
    output = root / "collected"
    args = [
        "collect-c0",
        "--config",
        str(cli_project),
        "--experiment-id",
        "c0-test",
        "--output-dir",
        str(output),
        "--steps",
        "8",
    ]
    assert main(args) == 0
    collected = json.loads(capsys.readouterr().out)
    assert main(["replay-c0", collected["trajectory_path"], "--config", str(cli_project)]) == 0
    assert json.loads(capsys.readouterr().out)["replayed_steps"] == 8
    with RunStore(root / "artifacts/control.sqlite3") as store:
        assert store.get_experiment("c0-test").reserved_environment_steps == 16
    assert main(args + ["--seed", "-1"]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "failed"


def test_collection_never_imports_a_neural_backend(cli_project):
    script = """
import sys
from ainerzero.cli import main
assert main(sys.argv[1:]) == 0
assert not any(name.split('.')[0] in {'mlx', 'torch'} for name in sys.modules)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "collect-c0",
            "--config",
            str(cli_project),
            "--experiment-id",
            "no-gpu",
            "--steps",
            "4",
            "--output-dir",
            str(cli_project.parents[1] / "episodes"),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
