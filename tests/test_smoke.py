import importlib.util
import json
from pathlib import Path

import pytest

from ainerzero.core.config import ProjectConfig, config_hash, load_config, save_config_snapshot
from ainerzero.runtime.lifecycle import RunStore
from ainerzero.runtime.smoke_worker import run_smoke


@pytest.fixture
def mlx_available():
    if importlib.util.find_spec("mlx") is None:
        pytest.skip(
            "Optional MLX dependency is not installed; use the metal extra on Apple Silicon"
        )


@pytest.mark.parametrize("steps", [16, 128])
def test_real_cpu_forward_backward_and_restored_continuation(tmp_path, mlx_available, steps):
    report = run_smoke(Path("configs/brain0.yaml"), tmp_path / "m0", "cpu", steps)
    assert report["status"] == "passed", report
    assert all(report["checks"].values())
    expected_steps = steps + steps - steps // 2
    assert report["actual_completed_optimizer_steps"] == expected_steps
    assert report["run"]["reserved_optimizer_steps"] == expected_steps
    assert report["run"]["state"] == "completed"
    assert json.loads(Path(report["report_path"]).read_text())["status"] == "passed"
    run_dir = Path(report["report_path"]).parent
    effective_config = load_config(run_dir / "config.yaml")
    requested_config = load_config(run_dir / "requested_config.yaml")
    assert report["config_hash"] == report["run"]["config_hash"] == config_hash(effective_config)
    assert report["run"]["config_snapshot"] == effective_config.model_dump(mode="json")
    assert effective_config.budget.max_optimizer_steps == expected_steps
    assert effective_config.budget.max_wall_seconds == 120.0
    assert report["requested_config_hash"] == config_hash(requested_config)
    assert requested_config == load_config("configs/brain0.yaml")


def test_low_budget_never_reports_unperformed_updates(tmp_path, mlx_available):
    config = ProjectConfig.model_validate({"budget": {"max_optimizer_steps": 2}})
    config_path = tmp_path / "budget.yaml"
    save_config_snapshot(config, config_path)
    report = run_smoke(config_path, tmp_path / "m0", "cpu", 8)
    assert report["status"] == "failed"
    assert "BudgetExceeded" in report["error"]
    assert report["actual_completed_optimizer_steps"] == 2
    assert report["run"]["reserved_optimizer_steps"] == 2
    assert report["run"]["state"] == "failed"


def test_exhausted_shared_daily_budget_blocks_before_loading_backend(tmp_path, monkeypatch):
    import builtins

    config = ProjectConfig.model_validate({"budget": {"max_daily_active_seconds": 2}})
    config_path = tmp_path / "budget.yaml"
    save_config_snapshot(config, config_path)
    database = tmp_path / "control.sqlite3"
    with RunStore(database) as store:
        previous = store.create_run(config.model_dump(mode="json"), request_id="previous")
        store.transition(previous.run_id, "initializing")
        store.transition(previous.run_id, "validating")
        store.consume(previous.run_id, active_seconds=2)
        store.transition(previous.run_id, "completed")

    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx."):
            pytest.fail("An exhausted run must not load the numerical backend")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    for destination in [tmp_path / "first", tmp_path / "second"]:
        report = run_smoke(config_path, destination, "cpu", 8, control_db=database)
        assert report["status"] == "failed"
        assert "BudgetExceeded" in report["error"]
        assert report["actual_completed_optimizer_steps"] == 0
        assert report["run"]["reserved_active_seconds"] == 0
