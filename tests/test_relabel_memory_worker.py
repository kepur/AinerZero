"""CPU contracts for the bounded M2m consistent-relabel experiment entry point."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest
from test_diverse_memory_worker import worker_fixture  # noqa: F401

from ainerzero import cli
from ainerzero.runtime import memory_worker
from ainerzero.runtime.lifecycle import RunStore

UNCHANGED_FROM_M2L = (
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
    "screen",
    "automatic_promotion",
    "new_environment_steps",
    "sample_selection",
    "training_pool_size",
    "training_schedule",
    "training_distribution",
    "paired_evaluation",
    "selection",
)


def test_relabel_plan_changes_only_relabeling_and_registered_extra_evaluations():
    previous = memory_worker.diverse_memory_plan()
    plan = memory_worker.relabel_memory_plan()
    assert plan["protocol"] == "m2m_consistent_relabel_single_edge_tail_fit_v1"
    for field in UNCHANGED_FROM_M2L:
        assert plan[field] == previous[field], field
    assert plan["learning_rate"] == 0.001
    assert (plan["batch_size"], plan["micro_batch_size"]) == (16, 4)
    assert plan["updates"] == 200
    assert plan["trainable_parameter_count"] == 111104
    assert plan["frozen_parameter_count"] == 282128
    assert plan["seeds"] == {**previous["seeds"], "augmentation": 2307, "relabel_evaluation": 9103}
    assert plan["seeds"]["latent"] == 2203
    assert plan["screen"] == {
        "minimum_changed_count": 30,
        "overall_accuracy_min": 0.95,
        "changed_accuracy_min": 0.8,
        "per_world_changed_accuracy_min": 0.5,
    }
    assert plan["local_screen"] == {
        "overall_accuracy_min": 0.95,
        "changed_accuracy_min": 0.8,
        "minimum_changed_count": 16,
    }
    assert plan["automatic_promotion"] is False
    assert plan["training_permutations"] == 3200
    assert plan["relabel_evaluation"]["seed"] == 9103


def test_relabel_plan_recomputes_units_and_prepaid_seconds_exactly():
    plan = memory_worker.relabel_memory_plan()
    previous = memory_worker.diverse_memory_plan()
    seconds = plan["resource_seconds"]
    added = {"m2l_paired_cells": 300, "m2l_relabel_pool": 30, "after_relabel_pool": 30}
    assert {k: seconds[k] for k in added} == added
    assert seconds["verification"] == previous["resource_seconds"]["verification"] + 10 == 20
    assert {k: v for k, v in seconds.items() if k not in added and k != "verification"} == {
        k: v for k, v in previous["resource_seconds"].items() if k != "verification"
    }
    local_calls = 2 * len(plan["local_checks"])
    stages = sum(v for k, v in seconds.items() if k not in {"training_update", "local_check"})
    total = (
        stages + plan["updates"] * seconds["training_update"] + local_calls * seconds["local_check"]
    )
    assert total == plan["total_reserved_seconds_if_complete"] == 1670
    assert total < plan["supervised_deadline_seconds"] == 1720 < 1770 <= 1800
    assert plan["expected_total_model_units"] == 174208 + 82080 + 4096 + 4096 == 264480
    assert plan["m2l_comparison"]["paired_with_cells_model_units"] == 82080
    assert (
        plan["relabel_evaluation"]["model_units"]
        == plan["m2l_comparison"]["relabel_pool_model_units"]
        == 256 * 2 * 8
    )


def test_relabel_plan_is_fresh_and_previous_plans_are_untouched():
    diverse = memory_worker.diverse_memory_plan()
    micro = memory_worker.micro_memory_plan()
    first = memory_worker.relabel_memory_plan()
    second = memory_worker.relabel_memory_plan()
    first["seeds"]["augmentation"] = 1
    first["resource_seconds"]["verification"] = 999
    first["relabel_evaluation"]["seed"] = 1
    assert memory_worker.relabel_memory_plan() == second
    assert memory_worker.diverse_memory_plan() == diverse
    assert memory_worker.micro_memory_plan() == micro


@pytest.fixture
def relabel_args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return argparse.Namespace(
        config=config,
        relabel_memory_training=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "source-checkpoint",
        comparison_report=tmp_path / "m2k-report.json",
        m2l_report=tmp_path / "m2l-report.json",
        m2l_checkpoint=tmp_path / "m2l-checkpoint",
        output_dir=tmp_path / "output",
        experiment_id="relabel-memory-test",
    )


@pytest.mark.parametrize("wall_limit", [1800, 120])
def test_relabel_cli_passes_all_sources_holds_lock_and_bounds_timeout(
    relabel_args, monkeypatch, wall_limit
):
    relabel_args.config.write_text(f"budget:\n  max_wall_seconds: {wall_limit}\n")
    root = relabel_args.config.parents[1]
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.memory_worker"
        assert command.count("--relabel-fit") == 1
        assert "--diverse-fit" not in command and "--local-fit" not in command
        for flag, value in (
            ("--dataset", relabel_args.dataset),
            ("--checkpoint", relabel_args.checkpoint),
            ("--comparison-report", relabel_args.comparison_report),
            ("--m2l-report", relabel_args.m2l_report),
            ("--m2l-checkpoint", relabel_args.m2l_checkpoint),
            ("--control-db", root / "artifacts/control.sqlite3"),
        ):
            assert command[command.index(flag) + 1] == str(value.resolve())
        assert kwargs["timeout"] == min(1770, wall_limit)
        with pytest.raises(RuntimeError, match="already running"):
            with cli.worker_lock(root / "artifacts/locks/m0-worker.lock"):
                pytest.fail("supervisor released its shared lock during model work")
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.train_pilot_command(relabel_args)["status"] == "completed"
    assert len(calls) == 1


def arguments():
    return [
        "train-relabel-memory",
        "--dataset",
        "/tmp/d.json",
        "--checkpoint",
        "/tmp/source",
        "--comparison-report",
        "/tmp/m2k.json",
        "--m2l-report",
        "/tmp/m2l.json",
        "--m2l-checkpoint",
        "/tmp/m2l",
        "--experiment-id",
        "relabel-test",
    ]


def test_relabel_parser_exposes_fixed_protocol_only(monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        assert args.relabel_memory_training is True
        assert not getattr(args, "diverse_memory_training", False)
        assert args.m2l_report == Path("/tmp/m2l.json")
        assert args.m2l_checkpoint == Path("/tmp/m2l")
        assert not hasattr(args, "updates") and not hasattr(args, "seed")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert cli.main(arguments()) == 0 and len(calls) == 1


@pytest.mark.parametrize(
    "missing",
    [
        "--dataset",
        "--checkpoint",
        "--comparison-report",
        "--m2l-report",
        "--m2l-checkpoint",
        "--experiment-id",
    ],
)
def test_relabel_parser_requires_every_source(missing):
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
        ["--seed", "1"],
        ["--learning-rate", "0.1"],
        ["--augmentation-seed", "1"],
        ["--relabel-fit"],
        ["--diverse-fit"],
        ["--local-fit"],
    ],
)
def test_relabel_parser_rejects_overrides(override):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments() + override)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "options",
    [
        {"relabel_fit": True, "comparison_report_path": Path("r.json")},
        {"relabel_fit": True, "m2l_report_path": Path("a"), "comparison_report_path": Path("r")},
        {
            "relabel_fit": True,
            "m2l_checkpoint_path": Path("a"),
            "comparison_report_path": Path("r"),
        },
        {"m2l_report_path": Path("a"), "m2l_checkpoint_path": Path("b")},
        {
            "relabel_fit": True,
            "diverse_fit": True,
            "comparison_report_path": Path("r"),
            "m2l_report_path": Path("a"),
            "m2l_checkpoint_path": Path("b"),
        },
        {
            "relabel_fit": True,
            "local_fit": True,
            "m2l_report_path": Path("a"),
            "m2l_checkpoint_path": Path("b"),
        },
        {"relabel_fit": True, "m2l_report_path": Path("a"), "m2l_checkpoint_path": Path("b")},
    ],
)
def test_relabel_protocol_ambiguity_fails_before_reading_files(monkeypatch, options):
    def forbidden(*args, **kwargs):
        pytest.fail("protocol ambiguity must fail before configuration or model work")

    monkeypatch.setattr(memory_worker, "load_pilot_config", forbidden)
    with pytest.raises(ValueError):
        memory_worker.run_memory(None, None, None, None, None, "invalid", **options)


def test_relabel_rejects_unverified_m2l_before_ledger_or_tensor_work(
    worker_fixture,  # noqa: F811
    tmp_path,
):
    fixture = worker_fixture
    m2l_checkpoint = tmp_path / "m2l-checkpoint"
    m2l_checkpoint.mkdir()
    (m2l_checkpoint / "manifest.json").write_text("{}\n")
    m2l_report = tmp_path / "m2l.json"
    m2l_report.write_text(json.dumps({"status": "completed"}))
    with pytest.raises(ValueError, match="coverage candidate lineage"):
        memory_worker.run_memory(
            *fixture.args,
            relabel_fit=True,
            comparison_report_path=fixture.comparison_path,
            m2l_report_path=m2l_report,
            m2l_checkpoint_path=m2l_checkpoint,
        )
    assert not fixture.database.exists()
    assert fixture.imports == []
    with RunStore(fixture.database) as store:
        assert store.list_runs() == []
