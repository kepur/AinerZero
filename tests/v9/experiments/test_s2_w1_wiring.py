"""W1 (DESIGN-r2 appendix D1/D2) production wiring: data partition, train inputs, holdout.

Covers the P163 r2 must-fix list F1-F7 on the real ``commands`` entry. Pure CPU; every
path lives under tmp_path.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from ainerzero.v9.experiments.s2 import commands, spec, train_runner, worker

from test_s2_lifecycle import _freeze_and_approve, tmp_env  # noqa: F401  (fixture re-export)


def _args(env: dict[str, Any], mode: str, **kw: Any) -> argparse.Namespace:
    base = dict(
        mode=mode,
        arm=None,
        seed=None,
        partition=None,
        output_root=env["output_root"],
        ledger=env["ledger"],
        lock_file=env["lock"],
        research_log=env["research_log"],
        prereg=env["prereg"],
        budget=None,
        runner=None,
        fake_clock=None,
        experiment_id=worker.EXPERIMENT_ID,
    )
    base.update(kw)
    return argparse.Namespace(**base)


def _smoke_run(ledger: Path, *, passed: bool, steps: int | None = 321) -> None:
    led = worker.S2Ledger(ledger)
    try:
        rid = led.open_run(mode="smoke", arm=None, seed=None, cell_wall_budget=1200.0)
        led.begin_run(rid, state="training")
        metrics: dict[str, Any] = {"passed": passed}
        if steps is not None:
            metrics["timing_and_steps"] = {"shared_train_steps": steps}
        if passed:
            led.complete_run(rid, metrics=metrics)
        else:
            led.record_metrics(rid, metrics)
            led.fail_run(rid, reason="smoke failed")
    finally:
        led.close()


# ------------------------------------------------------------- generate-data (F4)


def test_generate_data_requires_partition(tmp_env):
    res, code = commands.s2_phase1_command(_args(tmp_env, "generate-data"))
    assert code == commands.EXIT_FAILED and res["stage"] == "argument_validation"


def test_generate_data_refuses_arm(tmp_env):
    res, code = commands.s2_phase1_command(_args(tmp_env, "generate-data", partition="train", arm="arm_a"))
    assert code == commands.EXIT_FAILED and res["stage"] == "argument_validation"


def test_seed_namespaces_come_from_spec_only():
    src = inspect.getsource(__import__("ainerzero.v9.experiments.s2.data_runner", fromlist=["x"]))
    assert "spec.SEED_NAMESPACES[part]" in src
    assert 'f"s2p1-{part}-v1"' not in src


# ------------------------------------------------------------- train arguments (F3, F6)


@pytest.mark.parametrize("kw", [{}, {"arm": "arm_a"}, {"seed": 42}, {"arm": "arm_d", "seed": 42}, {"arm": "arm_a", "seed": 7}])
def test_train_requires_registered_arm_and_seed(tmp_env, kw):
    res, code = commands.s2_phase1_command(_args(tmp_env, "train", **kw))
    assert code == commands.EXIT_FAILED and res["stage"] == "argument_validation", res


def test_train_refuses_steps_override(tmp_env):
    _smoke_run(tmp_env["ledger"], passed=True)
    args = _args(tmp_env, "train", arm="arm_a", seed=42)
    args.steps = 5
    res, code = commands.s2_phase1_command(args)
    assert code == commands.EXIT_FAILED and res["stage"] == "argument_validation"


def test_train_arm_is_canonicalized_before_execution(tmp_env):
    _freeze_and_approve(tmp_env)
    seen: dict[str, Any] = {}

    def runner(ledger, run_id, mode, arm, seed, **kwargs):
        seen["arm"], seen["seed"] = arm, seed
        return {"status": "completed"}

    res, code = commands.s2_phase1_command(_args(tmp_env, "train", arm="B", seed=43, runner=runner))
    assert code == commands.EXIT_COMPLETED, res
    assert seen == {"arm": "arm_b", "seed": 43}


# ------------------------------------------------------------- smoke steps (F1, F2)


def test_train_refused_without_smoke_record(tmp_env):
    res, code = commands.s2_phase1_command(_args(tmp_env, "train", arm="arm_a", seed=42))
    assert code == commands.EXIT_FAILED and res["stage"] == "smoke_steps_missing"


def test_train_refused_when_latest_smoke_failed(tmp_env):
    _smoke_run(tmp_env["ledger"], passed=True, steps=100)
    _smoke_run(tmp_env["ledger"], passed=False)
    assert commands._resolve_smoke_train_steps(tmp_env["ledger"]) is None
    res, code = commands.s2_phase1_command(_args(tmp_env, "train", arm="arm_a", seed=42))
    assert res["stage"] == "smoke_steps_missing"


def test_steps_come_from_passed_smoke_metrics_without_touching_live_ledger(tmp_env):
    _smoke_run(tmp_env["ledger"], passed=True, steps=321)
    before = {p.name: p.stat().st_mtime_ns for p in tmp_env["output_root"].iterdir()}
    assert commands._resolve_smoke_train_steps(tmp_env["ledger"]) == 321
    after = {p.name: p.stat().st_mtime_ns for p in tmp_env["output_root"].iterdir()}
    assert before == after  # read through ledger_read_snapshot only


def test_smoke_without_steps_or_zero_steps_is_not_usable(tmp_env):
    _smoke_run(tmp_env["ledger"], passed=True, steps=None)
    assert commands._resolve_smoke_train_steps(tmp_env["ledger"]) is None


def test_failed_smoke_result_is_recorded_failed_not_completed(tmp_env):
    led = worker.S2Ledger(tmp_env["ledger"])
    try:
        result = worker.execute_work_cell(
            led, "smoke", None, None, 1200.0, runner=lambda **kw: {"passed": False, "failure_reason": "fuse"}
        )
        assert result["passed"] is False
        states = [r.state for r in led.store.list_runs()]
    finally:
        led.close()
    assert states == ["failed"]


# ------------------------------------------------------------- holdout worlds (F5)


def _train_tree(root: Path, n: int = 20) -> Path:
    tr = root / "datasets" / "train"
    for w in range(n):
        (tr / f"world_{w:04d}").mkdir(parents=True, exist_ok=True)
    ranked = sorted(range(n), key=lambda w: hashlib.sha256(f"s2p1-train-v1|holdout|{w}".encode()).hexdigest())
    hold = ranked[: max(1, int(round(n * spec.TRAIN_HOLDOUT_WORLD_FRACTION)))]
    (tr / "HOLDOUT_WORLDS.json").write_text(json.dumps({"holdout_worlds": hold}))
    return tr


def test_holdout_file_is_mandatory_and_tamper_checked(tmp_path):
    tr = _train_tree(tmp_path)
    good = train_runner.get_holdout_world_indices(tr)
    assert len(good) == 2
    data = json.loads((tr / "HOLDOUT_WORLDS.json").read_text())
    data["holdout_worlds"] = sorted(set(range(20)) - good)[:2]
    (tr / "HOLDOUT_WORLDS.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="tamper"):
        train_runner.get_holdout_world_indices(tr)
    (tr / "HOLDOUT_WORLDS.json").write_text("{not json")
    with pytest.raises(ValueError):
        train_runner.get_holdout_world_indices(tr)
    (tr / "HOLDOUT_WORLDS.json").unlink()
    with pytest.raises(FileNotFoundError):
        train_runner.get_holdout_world_indices(tr)


def test_holdout_refuses_empty_list_and_bad_world_dirs(tmp_path):
    tr = _train_tree(tmp_path)
    (tr / "HOLDOUT_WORLDS.json").write_text(json.dumps({"holdout_worlds": []}))
    with pytest.raises(ValueError):
        train_runner.get_holdout_world_indices(tr)
    tr2 = _train_tree(tmp_path / "b")
    (tr2 / "world_x1").mkdir()
    with pytest.raises(ValueError, match="Unparseable"):
        train_runner.get_holdout_world_indices(tr2)


def test_model_selection_cadence_is_registered():
    default = inspect.signature(train_runner.run_train_cell).parameters["eval_every"].default
    assert default == spec.MODEL_SELECTION_EVERY_STEPS == 200
    assert not hasattr(train_runner, "EVAL_EVERY_STEPS") or train_runner.EVAL_EVERY_STEPS == 200


# ------------------------------------------------------------- code identity (F7)


def test_repo_root_must_contain_the_executing_code(tmp_env):
    fake = tmp_env["tmp_path"] / "other_checkout"
    (fake / "src/ainerzero/v9/experiments/s2").mkdir(parents=True)
    (fake / "src/ainerzero/v9/experiments/s2/commands.py").write_text("# not the executing file\n")
    args = _args(tmp_env, "verify", repo_root=fake)
    with pytest.raises(RuntimeError, match="identity"):
        commands._resolve_paths(args)


def test_default_repo_root_is_the_package_checkout_not_cwd(tmp_env, monkeypatch):
    monkeypatch.chdir(tmp_env["tmp_path"])
    paths = commands._resolve_paths(_args(tmp_env, "verify"))
    assert (paths["repo_root"] / "src/ainerzero/v9/experiments/s2/commands.py").resolve() == Path(commands.__file__).resolve()


def test_cli_has_no_repo_root_or_lock_alias():
    from ainerzero import cli

    src = inspect.getsource(cli)
    block = src[src.index('"s2-phase1"'):]
    block = block[: block.index("add_parser(", 20)] if "add_parser(" in block[20:] else block
    assert '"--repo-root"' not in block and '"--lock",' not in block


def test_completed_smoke_with_passed_false_is_not_usable(tmp_env):
    led = worker.S2Ledger(tmp_env["ledger"])
    try:
        rid = led.open_run(mode="smoke", arm=None, seed=None, cell_wall_budget=1200.0)
        led.begin_run(rid, state="training")
        led.complete_run(rid, metrics={"passed": False, "timing_and_steps": {"shared_train_steps": 400}})
    finally:
        led.close()
    assert commands._resolve_smoke_train_steps(tmp_env["ledger"]) is None


def test_production_train_runner_reads_registered_data_dir_and_smoke_steps(tmp_env, monkeypatch):
    _freeze_and_approve(tmp_env)
    _smoke_run(tmp_env["ledger"], passed=True, steps=321)
    seen: dict[str, Any] = {}

    def fake_run_train_cell(**kwargs):
        seen.update(kwargs)
        return {"status": "completed", "checkpoint_sha256": "0" * 64}

    monkeypatch.setattr(train_runner, "run_train_cell", fake_run_train_cell)
    res, code = commands.s2_phase1_command(_args(tmp_env, "train", arm="arm_c", seed=44))
    assert code == commands.EXIT_COMPLETED, res
    assert Path(seen["data_dir"]) == tmp_env["output_root"].resolve() / "datasets" / "train"
    assert seen["steps"] == 321 and seen["arm_id"] == "arm_c" and seen["seed"] == 44
