"""CPU contracts for the bounded M2l input-diversity experiment."""

import argparse
import builtins
import hashlib
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
from ainerzero.runtime.paired_memory_worker import paired_memory_plan


def test_diverse_plan_preserves_micro_fit_capacity_update_budget_and_frozen_scope():
    previous = memory_worker.micro_memory_plan()
    plan = memory_worker.diverse_memory_plan()
    assert plan["protocol"] == "m2l_diverse_single_edge_tail_fit_v1"
    for field in (
        "architecture",
        "parameter_count",
        "trainable_parameter_count",
        "optimizer_tensor_parameter_count",
        "frozen_parameter_count",
        "trainable_scope",
        "readout",
        "target",
        "updates",
        "learning_rate",
        "batch_size",
        "micro_batch_size",
        "burn_in",
        "sequence_steps",
        "transitions_per_window",
        "training_model_units_per_update",
        "source_optimizer",
        "local_checks",
        "local_check_model_units",
        "local_screen",
        "automatic_promotion",
        "new_environment_steps",
    ):
        assert plan[field] == previous[field], field
    assert plan["parameter_count"] == 393232
    assert plan["trainable_parameter_count"] == 111104
    assert plan["frozen_parameter_count"] == 282128
    assert plan["updates"] == 200
    assert plan["burn_in"] == 0
    assert plan["sequence_steps"] == 1
    assert plan["automatic_promotion"] is False
    assert plan["new_environment_steps"] == 0


def test_diverse_plan_prepays_full_training_regressions_and_matched_after_diagnosis():
    previous = memory_worker.micro_memory_plan()
    plan = memory_worker.diverse_memory_plan()
    seconds = plan["resource_seconds"]
    assert seconds["after_paired"] == 300
    assert {name: value for name, value in seconds.items() if name != "after_paired"} == (
        previous["resource_seconds"]
    )
    local_calls = 2 * len(plan["local_checks"])
    stages = sum(
        value for name, value in seconds.items() if name not in {"training_update", "local_check"}
    )
    total = (
        stages + plan["updates"] * seconds["training_update"] + local_calls * seconds["local_check"]
    )
    assert total == plan["total_reserved_seconds_if_complete"] == 1300
    assert total < plan["supervised_deadline_seconds"] == 1500 < 1550
    assert plan["expected_total_model_units"] == 174208
    assert plan["expected_total_model_units"] == previous["expected_total_model_units"] + 82080


def test_diverse_plan_is_fresh_and_does_not_change_previous_protocols():
    micro = memory_worker.micro_memory_plan()
    continuous = memory_worker.memory_plan()
    first = memory_worker.diverse_memory_plan()
    second = memory_worker.diverse_memory_plan()
    first["resource_seconds"]["after_paired"] = 1
    first["resource_seconds"]["training_update"] = 999
    first["local_checks"].append(201)
    first["seeds"]["latent"] = 42
    assert memory_worker.diverse_memory_plan() == second
    assert memory_worker.micro_memory_plan() == micro
    assert memory_worker.memory_plan() == continuous


@pytest.fixture
def cli_args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return argparse.Namespace(
        config=config,
        diverse_memory_training=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "source-checkpoint",
        comparison_report=tmp_path / "m2k-report.json",
        output_dir=tmp_path / "output",
        experiment_id="diverse-memory-test",
    )


@pytest.mark.parametrize("wall_limit", [1800, 120])
def test_diverse_cli_holds_lock_passes_comparison_and_uses_canonical_ledger(
    cli_args, monkeypatch, wall_limit
):
    cli_args.config.write_text(f"budget:\n  max_wall_seconds: {wall_limit}\n")
    root = cli_args.config.parents[1]
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.memory_worker"
        assert command.count("--diverse-fit") == 1
        for flag, value in (
            ("--dataset", cli_args.dataset),
            ("--checkpoint", cli_args.checkpoint),
            ("--comparison-report", cli_args.comparison_report),
            ("--control-db", root / "artifacts/control.sqlite3"),
        ):
            assert command[command.index(flag) + 1] == str(value.resolve())
        assert not {
            "--updates",
            "--seed",
            "--symbol-augmentation",
            "--initial-checkpoint",
            "--local-fit",
            "--recall",
            "--residual",
        }.intersection(command)
        assert kwargs["timeout"] == min(1550, wall_limit)
        with pytest.raises(RuntimeError, match="already running"):
            with cli.worker_lock(root / "artifacts/locks/m0-worker.lock"):
                pytest.fail("supervisor released its shared lock during model work")
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.train_pilot_command(cli_args)["status"] == "completed"
    assert len(calls) == 1
    with cli.worker_lock(root / "artifacts/locks/m0-worker.lock"):
        pass


@pytest.mark.parametrize("outcome", ["timeout", "native_crash", "false_success"])
def test_diverse_supervisor_terminates_new_orphan_and_retains_comparison_evidence(
    cli_args, monkeypatch, outcome
):
    report_path = cli_args.output_dir / "pilot-fixture/report.json"
    evidence = {"sha256": "comparison-evidence", "path": str(cli_args.comparison_report)}

    def run(command, **kwargs):
        with RunStore(command[command.index("--control-db") + 1]) as store:
            store.create_run(
                {"budget": PilotConfig().budget.model_dump(mode="json")},
                "orphan",
                run_id="orphan",
            )
            store.transition("orphan", "initializing")
        report_path.parent.mkdir(parents=True)
        report_path.write_text(
            json.dumps({"status": "running", "comparison_report": evidence, "updates": [0, 50]})
        )
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        stdout = json.dumps({"status": "completed"}) if outcome == "false_success" else ""
        return subprocess.CompletedProcess(command, 0 if stdout else -9, stdout, "native failure")

    monkeypatch.setattr(subprocess, "run", run)
    result = cli.train_pilot_command(cli_args)
    assert result["status"] == "failed"
    assert result["interrupted_run_ids"] == ["orphan"]
    saved = json.loads(report_path.read_text())
    assert saved["status"] == "failed"
    assert saved["comparison_report"] == evidence
    assert saved["updates"] == [0, 50]
    with RunStore(cli_args.config.parents[1] / "artifacts/control.sqlite3") as store:
        assert store.get_run("orphan").state == "failed"
        assert store.get_run("orphan").reason == "pilot_supervisor_cleanup"


def arguments():
    return [
        "train-diverse-memory",
        "--dataset",
        "/tmp/diverse-dataset.json",
        "--checkpoint",
        "/tmp/source-checkpoint",
        "--comparison-report",
        "/tmp/m2k-report.json",
        "--experiment-id",
        "diverse-test",
    ]


def test_diverse_parser_requires_report_and_exposes_fixed_plan_only(monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        assert args.diverse_memory_training is True
        assert not getattr(args, "memory_training", False)
        assert not getattr(args, "micro_memory_training", False)
        assert args.dataset == Path("/tmp/diverse-dataset.json")
        assert args.checkpoint == Path("/tmp/source-checkpoint")
        assert args.comparison_report == Path("/tmp/m2k-report.json")
        assert not hasattr(args, "updates")
        assert not hasattr(args, "seed")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert cli.main(arguments()) == 0
    assert len(calls) == 1


@pytest.mark.parametrize(
    "missing", ["--dataset", "--checkpoint", "--comparison-report", "--experiment-id"]
)
def test_diverse_parser_requires_explicit_inputs_and_experiment(missing):
    args = arguments()
    index = args.index(missing)
    del args[index : index + 2]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "override",
    [
        ["--updates", "201"],
        ["--seed", "42"],
        ["--learning-rate", "0.1"],
        ["--batch-size", "32"],
        ["--symbol-augmentation", "per_window_permutation"],
        ["--local-fit"],
        ["--diverse-fit"],
        ["--source-report", "/tmp/other-report.json"],
    ],
)
def test_diverse_parser_rejects_training_and_mode_overrides(override):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments() + override)
    assert error.value.code == 2


def comparison_inputs():
    identity = {"manifest_sha256": "dataset", "public_sha256": {"train": ["public"]}}
    source = {
        "checkpoint": "/tmp/original",
        "checkpoint_manifest_sha256": "original-hash",
        "parent_run_id": "original",
        "dataset": deepcopy(identity),
    }
    queries = {"query_manifest_sha256": "queries"}
    report = {
        "status": "completed",
        "plan": paired_memory_plan(),
        "source": {
            "checkpoint": source["checkpoint"],
            "checkpoint_manifest_sha256": source["checkpoint_manifest_sha256"],
            "run_id": "original",
        },
        "dataset": deepcopy(identity),
        "actual_optimizer_steps": 0,
        "new_environment_steps": 0,
        "logical_model_transitions": 82176,
        "reserved_model_transitions": 82176,
        "weights_unchanged": True,
        "source_files_unchanged": True,
        "local_anchors_reproduced_exactly": True,
        "promoted": False,
        "checkpoint_saved": False,
        "run_id": "comparison",
        "experiment_id": "comparison",
        "manifest_hash": "comparison-prereg",
        "run": {"run_id": "comparison", "state": "completed"},
        "paired": {
            "query_manifest_sha256": "queries",
            "first_edge_pairs_identical": True,
            "first_edge_pair_checks": 20,
            "logical_model_transitions": 82080,
            "per_query": [{} for _ in range(2560)],
        },
    }
    return report, {"source": source, "identity": identity, "queries": queries}


def test_diverse_comparison_accepts_completed_matching_diagnosis_without_mutating():
    report, kwargs = comparison_inputs()
    originals = deepcopy((report, kwargs))
    memory_worker.validate_diverse_comparison(report, **kwargs)
    assert (report, kwargs) == originals


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "running"),
        ("status", "failed"),
        ("plan", {"protocol": "m2k_frozen_matched_edge_history_v1"}),
        ("source", {}),
        ("dataset", {}),
        ("actual_optimizer_steps", 1),
        ("actual_optimizer_steps", False),
        ("actual_optimizer_steps", 0.0),
        ("new_environment_steps", 1),
        ("new_environment_steps", False),
        ("logical_model_transitions", 82080),
        ("logical_model_transitions", 82176.0),
        ("reserved_model_transitions", 0),
        ("weights_unchanged", False),
        ("weights_unchanged", 1),
        ("source_files_unchanged", False),
        ("local_anchors_reproduced_exactly", False),
        ("promoted", True),
        ("checkpoint_saved", True),
        ("run_id", None),
        ("manifest_hash", None),
        ("run", {"run_id": "other", "state": "completed"}),
        ("run", {"run_id": "comparison", "state": "failed"}),
    ],
)
def test_diverse_comparison_rejects_wrong_lineage_or_unverified_work(field, value):
    report, kwargs = comparison_inputs()
    report[field] = value
    with pytest.raises(ValueError):
        memory_worker.validate_diverse_comparison(report, **kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("query_manifest_sha256", "other-queries"),
        ("first_edge_pairs_identical", False),
        ("first_edge_pairs_identical", 1),
        ("first_edge_pair_checks", 19),
        ("first_edge_pair_checks", 20.0),
        ("logical_model_transitions", 82079),
        ("logical_model_transitions", 82080.0),
        ("per_query", []),
    ],
)
def test_diverse_comparison_rejects_wrong_query_or_incomplete_pairing(field, value):
    report, kwargs = comparison_inputs()
    report["paired"][field] = value
    with pytest.raises(ValueError):
        memory_worker.validate_diverse_comparison(report, **kwargs)


@pytest.mark.parametrize(
    "source_field,value",
    [
        ("checkpoint", "/tmp/other-original"),
        ("checkpoint_manifest_sha256", "other-original-hash"),
        ("parent_run_id", "other-original"),
    ],
)
def test_diverse_comparison_binds_original_checkpoint_source(source_field, value):
    report, kwargs = comparison_inputs()
    kwargs["source"][source_field] = value
    with pytest.raises(ValueError):
        memory_worker.validate_diverse_comparison(report, **kwargs)


@pytest.mark.parametrize(
    "options",
    [
        {"local_fit": True, "diverse_fit": True, "comparison_report_path": Path("report.json")},
        {"diverse_fit": True},
        {"comparison_report_path": Path("report.json")},
        {"local_fit": True, "comparison_report_path": Path("report.json")},
    ],
)
def test_diverse_protocol_ambiguity_is_rejected_before_reading_files(monkeypatch, options):
    def forbidden(*args, **kwargs):
        pytest.fail("protocol ambiguity must fail before configuration or model work")

    monkeypatch.setattr(memory_worker, "load_pilot_config", forbidden)
    with pytest.raises(ValueError):
        memory_worker.run_memory(None, None, None, None, None, "invalid", **options)


@pytest.fixture
def worker_fixture(tmp_path, monkeypatch):
    from ainerzero.learning import diverse_evaluation, diverse_memory, micro_memory, paired_memory

    config = PilotConfig()
    comparison, comparison_kwargs = comparison_inputs()
    identity = comparison_kwargs["identity"]
    metadata = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "action_refinement",
        "config": config.model_dump(mode="json"),
        "dataset_source": identity,
        "optimizer_steps": 100,
        "run_id": "original",
    }
    tensors = {
        "model.byte_embedding.weight": np.zeros((256, 16)),
        "model.symbol_readout.weight": np.zeros((256, 16)),
        "model.symbol_readout.bias": np.zeros(256),
    }
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    (checkpoint / "manifest.json").write_text('{"fixture":true}\n')
    comparison["source"].update(
        checkpoint=str(checkpoint.resolve()),
        checkpoint_manifest_sha256=hashlib.sha256(
            (checkpoint / "manifest.json").read_bytes()
        ).hexdigest(),
    )
    fixed_batch = {"symbols": np.zeros((16, 2, 8), dtype=np.int32)}
    pool = {"symbols": np.zeros((256, 2, 8), dtype=np.int32)}
    fixed_samples = {"partition": "train", "batch_sha256": "fixed-cpu-fixture"}
    training_samples = {"partition": "train", "batch_sha256": "pool-cpu-fixture"}
    training = object()

    def select_fixed(value):
        assert value is training
        return fixed_batch, fixed_samples

    def select_diverse(value):
        assert value is training
        return pool, training_samples

    monkeypatch.setattr(micro_memory, "select_micro_memory_samples", select_fixed)
    monkeypatch.setattr(diverse_memory, "select_diverse_memory_samples", select_diverse)
    monkeypatch.setattr(
        paired_memory, "paired_memory_samples", lambda _: comparison_kwargs["queries"]
    )
    monkeypatch.setattr(diverse_evaluation, "summarize_diverse_pairs", lambda *args: {})
    monkeypatch.setattr(memory_worker, "load_pilot_config", lambda _: config)
    monkeypatch.setattr(
        memory_worker,
        "load_pilot_dataset",
        lambda *_: ({}, {"train": training, "development": object()}, identity),
    )
    monkeypatch.setattr(memory_worker, "load_checkpoint", lambda _: (tensors, metadata))
    manifest = {**config.model_dump(mode="json"), "source": {"sha256": "fixture"}}
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
    imports = []
    original_import = builtins.__import__

    def forbid_model(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx.") or name.endswith("pilot_model"):
            imports.append(name)
            raise AssertionError("failed preflight must prevent model imports")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_model)
    database = tmp_path / "control.sqlite3"
    comparison_path = tmp_path / "comparison.json"

    def write_comparison():
        comparison_path.write_text(json.dumps(comparison))

    write_comparison()
    return SimpleNamespace(
        comparison=comparison,
        comparison_path=comparison_path,
        write_comparison=write_comparison,
        fixed_batch=fixed_batch,
        pool=pool,
        fixed_samples=fixed_samples,
        training_samples=training_samples,
        imports=imports,
        config=config,
        database=database,
        args=(
            tmp_path / "config.yaml",
            tmp_path / "dataset.json",
            checkpoint,
            tmp_path / "output",
            database,
            "diverse-test",
        ),
    )


def test_diverse_incompatible_report_stops_before_ledger_and_tensor_work(worker_fixture):
    fixture = worker_fixture
    fixture.comparison["weights_unchanged"] = False
    fixture.write_comparison()
    with pytest.raises(ValueError, match="completed M2k comparison"):
        memory_worker.run_memory(
            *fixture.args, diverse_fit=True, comparison_report_path=fixture.comparison_path
        )
    assert not fixture.database.exists()
    assert fixture.imports == []


def test_diverse_missing_canonical_comparison_stops_before_model_work(worker_fixture):
    fixture = worker_fixture
    result = memory_worker.run_memory(
        *fixture.args, diverse_fit=True, comparison_report_path=fixture.comparison_path
    )
    assert result["status"] == "failed"
    assert result["actual_optimizer_steps"] == result["training_model_transitions"] == 0
    assert result["tail_protection_checks"] == 0
    assert result["local_checks"] == {}
    assert result["promoted"] is False
    assert fixture.imports == []
    with RunStore(fixture.database) as store:
        assert store.list_runs() == []


def test_diverse_codec_failure_preregisters_pool_and_schedule_before_tensor_work(worker_fixture):
    fixture = worker_fixture
    with RunStore(fixture.database) as store:
        experiment = store.create_experiment(
            fixture.config.model_dump(mode="json"), "comparison", "comparison"
        )
        snapshot = {"budget": fixture.config.budget.model_dump(mode="json")}
        store.create_run(
            snapshot,
            "comparison",
            run_id="comparison",
            experiment_id="comparison",
            role="auxiliary",
        )
        store.transition("comparison", "initializing")
        store.transition("comparison", "validating")
        store.consume("comparison", active_seconds=355, model_transitions=82176)
        store.transition("comparison", "completed")
        fixture.comparison["manifest_hash"] = experiment.manifest_hash
    fixture.write_comparison()
    result = memory_worker.run_memory(
        *fixture.args, diverse_fit=True, comparison_report_path=fixture.comparison_path
    )
    assert result["status"] == "failed"
    assert "bounded frozen codec compatibility check failed" in result["error"]
    assert result["actual_optimizer_steps"] == result["training_model_transitions"] == 0
    assert result["tail_protection_checks"] == 0
    assert result["local_checks"] == {}
    assert result["promoted"] is False
    assert result["training_samples"] == fixture.training_samples
    assert result["fixed_samples"] == fixture.fixed_samples
    assert fixture.imports == []
    assert "checkpoint" not in result
    declaration = json.loads((Path(result["run_directory"]) / "preregistration.json").read_text())
    assert declaration["one_step_memory"] == memory_worker.diverse_memory_plan()
    assert declaration["purpose"] == "c0_diverse_memory_fit_training_v1"
    assert declaration["training_samples"] == fixture.training_samples
    assert declaration["fixed_samples"] == fixture.fixed_samples
    with np.load(result["fixed_batch_path"]) as saved:
        np.testing.assert_array_equal(saved["symbols"], fixture.fixed_batch["symbols"])
    with np.load(result["training_pool_path"]) as saved:
        np.testing.assert_array_equal(saved["symbols"], fixture.pool["symbols"])
    schedule = np.load(result["training_schedule_path"])
    assert schedule.shape == (200, 16)
    assert schedule.dtype == np.int32
    assert ((0 <= schedule) & (schedule < 256)).all()
    with RunStore(fixture.database) as store:
        run = store.get_run(result["run_id"])
        assert run.state == "failed"
        assert run.reason == "diverse_memory_fit_failure"
        assert run.reserved_optimizer_steps == run.reserved_model_transitions == 0
        assert run.reserved_environment_steps == 0
        assert run.reserved_active_seconds == 15
