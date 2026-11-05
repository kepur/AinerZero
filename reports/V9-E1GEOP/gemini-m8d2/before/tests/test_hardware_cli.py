import json
import subprocess
import sys

import pytest

from ainerzero.cli import main, worker_lock
from ainerzero.core.config import ProjectConfig, save_config_snapshot
from ainerzero.runtime import hardware
from ainerzero.runtime.lifecycle import RunStore


def test_diagnostic_whitelists_hardware_identifiers(monkeypatch):
    def fake_command(args, timeout=15):
        if args[0] == "system_profiler":
            return json.dumps(
                {
                    "SPHardwareDataType": [
                        {
                            "chip_type": "Apple M2 Max",
                            "machine_model": "Mac14,5",
                            "serial_number": "PRIVATE-SERIAL",
                            "platform_UUID": "PRIVATE-UUID",
                        }
                    ],
                    "SPDisplaysDataType": [{"sppci_model": "Apple M2 Max", "sppci_cores": "38"}],
                }
            )
        return "Now drawing from 'AC Power'"

    monkeypatch.setattr(hardware, "_command", fake_command)
    monkeypatch.setattr(hardware.sys, "platform", "darwin")
    report = hardware.collect_hardware(include_mlx=False)
    assert report["machine"]["chip"] == "Apple M2 Max"
    assert report["power_source"] == "ac"
    assert "PRIVATE" not in json.dumps(report)
    assert report["backend"]["available"] is None


def test_native_probe_failure_is_not_cpu_fallback(monkeypatch):
    def failure(*args, **kwargs):
        raise subprocess.CalledProcessError(-6, "probe")

    monkeypatch.setattr(hardware, "_command", failure)
    assert hardware.probe_mlx()["available"] is False


def test_cli_config_and_output_report(tmp_path, capsys):
    assert main(["check-config", "--config", "configs/brain0.yaml"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "valid"
    output = tmp_path / "report.json"
    assert main(["doctor", "--no-mlx", "--output", str(output)]) == 0
    report = json.loads(output.read_text())
    assert report["memory"]["total_bytes"] > 0
    assert report["backend"]["checked"] is False


def test_worker_lock_prevents_two_workers(tmp_path):
    path = tmp_path / "worker.lock"
    with worker_lock(path):
        with pytest.raises(RuntimeError, match="already running"):
            with worker_lock(path):
                pass
    with worker_lock(path):
        pass


def test_unimplemented_training_command_is_not_a_fake_success():
    result = subprocess.run(
        [sys.executable, "-m", "ainerzero", "train"], capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_bad_config_does_not_start_worker(tmp_path, capsys):
    config = tmp_path / "bad.yaml"
    config.write_text("budget:\n  max_optimizer_steps: -1\n")
    assert main(["smoke", "--config", str(config)]) == 1
    assert json.loads(capsys.readouterr().err)["status"] == "failed"
    assert not (tmp_path / "artifacts").exists()


def test_report_destination_does_not_reset_project_budget(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-project"\n')
    config_path = tmp_path / "configs" / "brain0.yaml"
    save_config_snapshot(ProjectConfig(), config_path)
    databases = []

    def fake_worker(command, **kwargs):
        assert kwargs["timeout"] == 120.0
        databases.append(command[command.index("--control-db") + 1])
        return subprocess.CompletedProcess(command, 0, '{"status":"passed"}', "")

    monkeypatch.setattr(subprocess, "run", fake_worker)
    for output in [tmp_path / "first", tmp_path / "second"]:
        assert main(["smoke", "--config", str(config_path), "--output-dir", str(output)]) == 0
        assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert databases == [str(tmp_path / "artifacts" / "control.sqlite3")] * 2


def test_cli_recovers_interrupted_runs_before_starting_worker(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-project"\n')
    config_path = tmp_path / "configs" / "brain0.yaml"
    config = ProjectConfig()
    save_config_snapshot(config, config_path)
    database = tmp_path / "artifacts" / "control.sqlite3"
    with RunStore(database) as store:
        for run_id in ("active", "stopping", "manual"):
            store.create_run(config.model_dump(mode="json"), run_id, run_id=run_id)
            store.transition(run_id, "initializing")
            store.transition(run_id, "training")
        store.consume("active", optimizer_steps=3, active_seconds=1)
        store.transition("stopping", "stopping")
        store.transition("manual", "pausing", reason="manual")
        store.transition("manual", "paused", reason="manual")

    calls = []

    def fake_worker(command, **kwargs):
        calls.append(command)
        assert command[command.index("--control-db") + 1] == str(database)
        # This callback is the dispatch boundary: recovery must already be
        # durable and the supervisor must still hold the exclusive worker lock.
        with RunStore(database) as store:
            active = store.get_run("active")
            assert active.state == "paused"
            assert active.resume_state == "training"
            assert active.reason == "process_restart"
            assert active.reserved_optimizer_steps == 3
            assert active.reserved_active_seconds == 1
            assert store.get_run("stopping").state == "stopped"
            assert store.get_run("manual").state == "paused"
            assert store.get_run("manual").reason == "manual"
        with pytest.raises(RuntimeError, match="already running"):
            with worker_lock(tmp_path / "artifacts" / "locks" / "m0-worker.lock"):
                pass
        return subprocess.CompletedProcess(command, 0, '{"status":"passed"}', "")

    monkeypatch.setattr(subprocess, "run", fake_worker)
    assert main(["smoke", "--config", str(config_path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert len(calls) == 1
    with RunStore(database) as store:
        assert store.get_run("active").state == "paused"
        assert store.get_run("manual").reason == "manual"


def test_cli_cannot_recover_live_runs_without_exclusive_lock(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-project"\n')
    config_path = tmp_path / "configs" / "brain0.yaml"
    config = ProjectConfig()
    save_config_snapshot(config, config_path)
    database = tmp_path / "artifacts" / "control.sqlite3"
    with RunStore(database) as store:
        store.create_run(config.model_dump(mode="json"), "live", run_id="live")
        store.transition("live", "initializing")
        store.transition("live", "training")

    def forbidden_worker(*args, **kwargs):
        pytest.fail("A second worker must not be started")

    monkeypatch.setattr(subprocess, "run", forbidden_worker)
    with worker_lock(tmp_path / "artifacts" / "locks" / "m0-worker.lock"):
        assert main(["smoke", "--config", str(config_path)]) == 1
    assert "already running" in json.loads(capsys.readouterr().err)["error"]
    with RunStore(database) as store:
        assert store.get_run("live").state == "training"


def test_cli_does_not_start_worker_when_control_database_is_corrupt(tmp_path, monkeypatch, capsys):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-project"\n')
    config_path = tmp_path / "configs" / "brain0.yaml"
    save_config_snapshot(ProjectConfig(), config_path)
    database = tmp_path / "artifacts" / "control.sqlite3"
    database.parent.mkdir()
    database.write_bytes(b"not a SQLite database")

    def forbidden_worker(*args, **kwargs):
        pytest.fail("Corrupt control state must prevent worker dispatch")

    monkeypatch.setattr(subprocess, "run", forbidden_worker)
    assert main(["smoke", "--config", str(config_path)]) == 1
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "failed"
    assert "DatabaseError" in error["error"]


@pytest.mark.parametrize("outcome", ["native_crash", "timeout", "false_success"])
def test_cli_finalizes_orphaned_worker_before_releasing_lock(
    tmp_path, monkeypatch, capsys, outcome
):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "test-project"\n')
    config_path = tmp_path / "configs" / "brain0.yaml"
    config = ProjectConfig.model_validate({"budget": {"max_wall_seconds": 3.0}})
    snapshot = config.model_dump(mode="json")
    save_config_snapshot(config, config_path)
    database = tmp_path / "artifacts" / "control.sqlite3"
    with RunStore(database) as store:
        store.create_run(snapshot, "previous", run_id="previous")
        store.transition("previous", "initializing")
        store.transition("previous", "pausing", reason="manual")
        store.transition("previous", "paused", reason="manual")

    def broken_worker(command, **kwargs):
        assert kwargs["timeout"] == 3.0
        with RunStore(database) as store:
            store.create_run(snapshot, "current", run_id="current")
            store.transition("current", "initializing")
            store.transition("current", "training")
            store.consume("current", optimizer_steps=1, active_seconds=0.5)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(
            command, -6 if outcome == "native_crash" else 0, '{"status":"passed"}', ""
        )

    real_transition = RunStore.transition

    def checked_transition(store, run_id, state, **kwargs):
        if run_id == "current" and state == "failed":
            with pytest.raises(RuntimeError, match="already running"):
                with worker_lock(tmp_path / "artifacts" / "locks" / "m0-worker.lock"):
                    pass
        return real_transition(store, run_id, state, **kwargs)

    monkeypatch.setattr(subprocess, "run", broken_worker)
    monkeypatch.setattr(RunStore, "transition", checked_transition)
    assert main(["smoke", "--config", str(config_path)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.err if outcome == "timeout" else captured.out)["status"] == "failed"
    with RunStore(database) as store:
        run = store.get_run("current")
        assert run.state == "failed"
        assert run.reason == (
            "worker_timeout" if outcome == "timeout" else "worker_exited_without_terminal_state"
        )
        assert run.reserved_optimizer_steps == 1
        assert run.reserved_active_seconds == 0.5
        assert store.get_run("previous").state == "paused"
        assert store.get_run("previous").reason == "manual"
