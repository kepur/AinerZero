"""CPU-only contracts for the frozen M2k paired memory diagnosis."""

import argparse
import builtins
import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainerzero import cli
from ainerzero.core.pilot import PilotConfig
from ainerzero.runtime.lifecycle import RunStore
from ainerzero.runtime.memory_worker import micro_memory_plan
from ainerzero.runtime.paired_memory_worker import (
    compare_local_anchor,
    paired_memory_plan,
    validate_paired_source,
)


def paired_inputs():
    config = PilotConfig().model_dump(mode="json")
    identity = {"manifest_sha256": "dataset", "public_sha256": {"train": ["a"]}}
    source = {
        "checkpoint": "/tmp/original",
        "run_id": "original",
        "checkpoint_manifest_sha256": "original-hash",
    }
    candidate = {
        "checkpoint": "/tmp/candidate",
        "run_id": "candidate",
        "checkpoint_manifest_sha256": "candidate-hash",
    }
    source_metadata = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "action_refinement",
        "config": deepcopy(config),
        "dataset_source": deepcopy(identity),
        "optimizer_steps": 100,
        "run_id": "original",
    }
    inherited_source = {
        "checkpoint": source["checkpoint"],
        "checkpoint_manifest_sha256": source["checkpoint_manifest_sha256"],
        "parent_run_id": source["run_id"],
        "dataset": deepcopy(identity),
    }
    fixed_samples = {"batch_sha256": "batch", "sample_manifest_sha256": "samples"}
    candidate_metadata = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "micro_memory_fit",
        "config": deepcopy(config),
        "dataset_source": deepcopy(identity),
        "optimizer_steps": 200,
        "run_id": "candidate",
        "manifest_hash": "candidate-prereg",
        "plan": micro_memory_plan(),
        "readout_protocol": micro_memory_plan()["readout"],
        "source": deepcopy(inherited_source),
        "fixed_samples": deepcopy(fixed_samples),
        "sampler": {"burn_in": 0, "sequence_steps": 1},
        "rng_states": {"fixed_seed": 2203},
    }
    source_report = {
        "status": "completed",
        "current_stage": "completed",
        "run_id": "candidate",
        "manifest_hash": "candidate-prereg",
        "checkpoint": candidate["checkpoint"],
        "checkpoint_verified": True,
        "plan": micro_memory_plan(),
        "source": deepcopy(inherited_source),
        "fixed_samples": deepcopy(fixed_samples),
        "actual_optimizer_steps": 200,
        "tail_protection_checks": 200,
        "new_environment_steps": 0,
        "promoted": False,
        "local_checks": {
            "200": {"training_noise": {"seed": 2203}, "same_inputs_new_noise": {"seed": 2603}}
        },
        "run": {"run_id": "candidate", "state": "completed"},
    }
    return (
        source_metadata,
        candidate_metadata,
        config,
        identity,
        source,
        candidate,
        source_report,
        fixed_samples,
    )


def test_paired_plan_declares_bounded_frozen_work_and_no_capacity_change():
    plan = paired_memory_plan()
    assert plan["parameter_count"] == 393232
    assert plan["optimizer_steps"] == plan["new_environment_steps"] == 0
    assert plan["automatic_promotion"] is False
    assert plan["expected_total_model_units"] == 82176
    assert sum(plan["resource_seconds"].values()) == 355
    assert plan["total_reserved_seconds_if_complete"] == 355
    assert 355 < plan["supervised_deadline_seconds"] == 600 < 650
    assert plan["resource_seconds"] == {
        "validation": 15,
        "initialization": 15,
        "local_training_noise": 5,
        "local_new_noise": 5,
        "paired": 300,
        "verification": 15,
    }


def test_paired_plan_does_not_expose_mutable_shared_declarations():
    first = paired_memory_plan()
    second = paired_memory_plan()
    first["resource_seconds"]["paired"] = 999
    assert paired_memory_plan() == second


def test_completed_candidate_lineage_is_accepted_without_mutating_inputs():
    values = paired_inputs()
    original = deepcopy(values)
    validate_paired_source(*values)
    assert values == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("architecture", "external_readout"),
        ("phase", "micro_memory_fit"),
        ("config", {}),
        ("dataset_source", {}),
        ("optimizer_steps", 0),
        ("optimizer_steps", True),
        ("optimizer_steps", 100.0),
        ("run_id", None),
    ],
)
def test_paired_source_rejects_invalid_original(field, value):
    values = paired_inputs()
    values[0][field] = value
    with pytest.raises(ValueError):
        validate_paired_source(*values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("architecture", "external_readout"),
        ("phase", "one_step_memory"),
        ("config", {}),
        ("dataset_source", {}),
        ("optimizer_steps", 0),
        ("optimizer_steps", 199),
        ("optimizer_steps", 201),
        ("optimizer_steps", True),
        ("optimizer_steps", 200.0),
        ("run_id", None),
        ("run_id", "original"),
        ("manifest_hash", "other-prereg"),
        ("readout_protocol", "new_head"),
        ("plan", {}),
        ("fixed_samples", {}),
        ("sampler", {"burn_in": 4, "sequence_steps": 16}),
        ("rng_states", {"fixed_seed": 42}),
    ],
)
def test_paired_source_rejects_unfinished_or_incompatible_candidate(field, value):
    values = paired_inputs()
    values[1][field] = value
    with pytest.raises(ValueError):
        validate_paired_source(*values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("checkpoint", "/tmp/other-source"),
        ("checkpoint_manifest_sha256", "other-hash"),
        ("parent_run_id", "other-run"),
        ("dataset", {}),
    ],
)
def test_paired_source_rejects_changed_original_lineage(field, value):
    values = paired_inputs()
    values[1]["source"][field] = value
    with pytest.raises(ValueError):
        validate_paired_source(*values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("status", "running"),
        ("run_id", "other-run"),
        ("manifest_hash", "other-prereg"),
        ("checkpoint", "/tmp/other-candidate"),
        ("checkpoint_verified", False),
        ("checkpoint_verified", 1),
        ("actual_optimizer_steps", 199),
        ("actual_optimizer_steps", True),
        ("actual_optimizer_steps", 200.0),
        ("tail_protection_checks", 199),
        ("tail_protection_checks", True),
        ("tail_protection_checks", 200.0),
        ("plan", {}),
        ("source", {}),
        ("fixed_samples", {}),
        ("local_checks", {}),
    ],
)
def test_paired_source_rejects_unverified_or_mismatched_source_report(field, value):
    values = paired_inputs()
    values[6][field] = value
    with pytest.raises(ValueError):
        validate_paired_source(*values)


def test_paired_source_rejects_changed_rebuilt_sample_evidence():
    values = paired_inputs()
    values[7]["batch_sha256"] = "changed-inputs"
    with pytest.raises(ValueError):
        validate_paired_source(*values)


def test_paired_source_requires_whole_plan_not_only_protocol_name():
    values = paired_inputs()
    values[1]["plan"]["learning_rate"] = 0.002
    with pytest.raises(ValueError):
        validate_paired_source(*values)


def anchor():
    return {
        "protocol": "m2j_fixed_batch_memory_evaluation_v1",
        "seed": 2203,
        "particles": 1,
        "sample_count": 16,
        "query_count": 16,
        "batch_sha256": "batch",
        "logical_model_transitions": 48,
        "methods": {
            "memory_tail": {
                "count": 128,
                "accuracy": 1.0,
                "changed_count": 29,
                "changed_accuracy": 1.0,
                "nll": 0.25,
            }
        },
    }


def test_local_anchor_accepts_identical_frozen_evidence_without_mutation():
    observed = anchor()
    expected = deepcopy(observed)
    original = deepcopy(observed)
    compare_local_anchor(observed, expected)
    assert observed == expected == original


@pytest.mark.parametrize(
    "field,value",
    [("protocol", "other"), ("seed", 2603), ("sample_count", 15), ("batch_sha256", "other")],
)
def test_local_anchor_rejects_different_evaluation_inputs(field, value):
    observed, expected = anchor(), anchor()
    observed[field] = value
    with pytest.raises(ValueError):
        compare_local_anchor(observed, expected)


@pytest.mark.parametrize("field,value", [("count", 127), ("accuracy", 0.5), ("nll", 0.5)])
def test_local_anchor_rejects_different_model_scores(field, value):
    observed, expected = anchor(), anchor()
    observed["methods"]["memory_tail"][field] = value
    with pytest.raises(ValueError):
        compare_local_anchor(observed, expected)


@pytest.fixture
def cli_args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return argparse.Namespace(
        config=config,
        paired_memory_diagnostic=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "original",
        candidate_checkpoint=tmp_path / "candidate",
        source_report=tmp_path / "m2j.json",
        output_dir=tmp_path / "output",
        experiment_id="paired-test",
    )


@pytest.mark.parametrize("wall_limit", [1800, 120])
def test_paired_cli_uses_shared_lock_ledger_supervisor_and_exact_lineage(
    cli_args, monkeypatch, wall_limit
):
    cli_args.config.write_text(f"budget:\n  max_wall_seconds: {wall_limit}\n")
    root = cli_args.config.parents[1]
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.paired_memory_worker"
        for flag, value in (
            ("--dataset", cli_args.dataset),
            ("--checkpoint", cli_args.checkpoint),
            ("--candidate-checkpoint", cli_args.candidate_checkpoint),
            ("--source-report", cli_args.source_report),
            ("--control-db", root / "artifacts/control.sqlite3"),
        ):
            assert command[command.index(flag) + 1] == str(value.resolve())
        assert not {"--updates", "--seed", "--local-fit", "--recall"}.intersection(command)
        assert kwargs["timeout"] == min(650, wall_limit)
        with pytest.raises(RuntimeError, match="already running"):
            with cli.worker_lock(root / "artifacts/locks/m0-worker.lock"):
                pytest.fail("supervisor released the shared lock during model work")
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.train_pilot_command(cli_args)["status"] == "completed"
    assert len(calls) == 1
    with cli.worker_lock(root / "artifacts/locks/m0-worker.lock"):
        pass


@pytest.mark.parametrize("outcome", ["timeout", "native_crash", "false_success"])
def test_paired_supervisor_terminates_orphan_and_preserves_report(cli_args, monkeypatch, outcome):
    report_path = cli_args.output_dir / "pilot-fixture/report.json"

    def run(command, **kwargs):
        with RunStore(command[command.index("--control-db") + 1]) as store:
            store.create_run(
                {"budget": PilotConfig().budget.model_dump(mode="json")},
                "orphan",
                run_id="orphan",
            )
            store.transition("orphan", "initializing")
        report_path.parent.mkdir(parents=True)
        report_path.write_text(json.dumps({"status": "running", "anchor_reproduced": True}))
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
    assert saved["anchor_reproduced"] is True
    with RunStore(cli_args.config.parents[1] / "artifacts/control.sqlite3") as store:
        assert store.get_run("orphan").state == "failed"
        assert store.get_run("orphan").reason == "pilot_supervisor_cleanup"


def arguments():
    return [
        "diagnose-paired-memory",
        "--dataset",
        "/tmp/dataset",
        "--checkpoint",
        "/tmp/original",
        "--candidate-checkpoint",
        "/tmp/candidate",
        "--source-report",
        "/tmp/m2j.json",
        "--experiment-id",
        "paired-test",
    ]


def test_paired_parser_exposes_only_frozen_diagnosis(monkeypatch):
    calls = []

    def run(args):
        calls.append(args)
        assert args.paired_memory_diagnostic is True
        assert args.checkpoint == Path("/tmp/original")
        assert args.candidate_checkpoint == Path("/tmp/candidate")
        assert args.source_report == Path("/tmp/m2j.json")
        assert not hasattr(args, "updates")
        assert not hasattr(args, "seed")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert cli.main(arguments()) == 0
    assert len(calls) == 1


@pytest.mark.parametrize(
    "missing",
    ["--dataset", "--checkpoint", "--candidate-checkpoint", "--source-report", "--experiment-id"],
)
def test_paired_parser_requires_all_lineage_inputs(missing):
    args = arguments()
    index = args.index(missing)
    del args[index : index + 2]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "override",
    [["--updates", "1"], ["--seed", "42"], ["--particles", "1"], ["--local-fit"]],
)
def test_paired_parser_rejects_unregistered_training_or_evaluation_overrides(override):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments() + override)
    assert error.value.code == 2


@pytest.mark.parametrize("failure", ["missing_ledger", "incomplete_ledger", "invalid_tensors"])
def test_paired_rejects_unconfirmed_or_invalid_candidate_before_native_work(
    tmp_path, monkeypatch, failure
):
    from ainerzero.learning import paired_memory
    from ainerzero.runtime import paired_memory_worker as worker

    (
        source_metadata,
        candidate_metadata,
        config_dict,
        identity,
        source,
        candidate,
        source_report,
        fixed_samples,
    ) = paired_inputs()
    config = PilotConfig.model_validate(config_dict)
    source_path, candidate_path = tmp_path / "original", tmp_path / "candidate"
    for path, reference in ((source_path, source), (candidate_path, candidate)):
        path.mkdir()
        (path / "manifest.json").write_text('{"fixture": true}\n')
        reference.update(
            checkpoint=str(path.resolve()),
            checkpoint_manifest_sha256=hashlib.sha256(
                (path / "manifest.json").read_bytes()
            ).hexdigest(),
        )
    candidate_metadata["source"].update(
        checkpoint=source["checkpoint"],
        checkpoint_manifest_sha256=source["checkpoint_manifest_sha256"],
    )
    source_report.update(
        checkpoint=candidate["checkpoint"],
        source=deepcopy(candidate_metadata["source"]),
        experiment_id="m2j-fixture",
    )
    db = tmp_path / "control.sqlite3"
    if failure != "missing_ledger":
        with RunStore(db) as store:
            experiment = store.create_experiment(config_dict, "m2j-fixture", "m2j-fixture")
            candidate_metadata["manifest_hash"] = source_report["manifest_hash"] = (
                experiment.manifest_hash
            )
            store.create_run(
                config_dict, "candidate", "candidate", experiment_id="m2j-fixture", role="model"
            )
            store.transition("candidate", "initializing")
            store.transition("candidate", "training")
            store.consume("candidate", optimizer_steps=200)
            if failure == "invalid_tensors":
                store.transition("candidate", "completed")
    source_report_path = tmp_path / "m2j.json"
    source_report_path.write_text(json.dumps(source_report))
    monkeypatch.setattr(worker, "load_pilot_config", lambda _: config)
    monkeypatch.setattr(
        worker, "load_pilot_dataset", lambda *_: ({}, {"train": object()}, identity)
    )
    monkeypatch.setattr(
        worker,
        "load_checkpoint",
        lambda path: ({}, source_metadata if path == source_path else candidate_metadata),
    )
    monkeypatch.setattr(worker, "select_micro_memory_samples", lambda _: ({}, fixed_samples))
    monkeypatch.setattr(
        paired_memory, "paired_memory_samples", lambda _: {"query_manifest_sha256": "queries"}
    )
    monkeypatch.setattr(cli, "pilot_manifest", lambda _: {"manifest": deepcopy(config_dict)})
    monkeypatch.setattr(worker.psutil, "swap_memory", lambda: SimpleNamespace(used=0))
    monkeypatch.setattr(
        worker.psutil, "virtual_memory", lambda: SimpleNamespace(available=100 * 2**30)
    )
    monkeypatch.setattr(
        worker.psutil,
        "Process",
        lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=1)),
    )
    monkeypatch.setattr(worker.psutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 2**30))
    imports = []
    original_import = builtins.__import__

    def forbid_native(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx.") or name.endswith("pilot_model"):
            imports.append(name)
            raise AssertionError("invalid candidate must fail before native model imports")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_native)
    result = worker.run_paired_memory(
        tmp_path / "config",
        tmp_path / "dataset",
        source_path,
        candidate_path,
        source_report_path,
        tmp_path / "output",
        db,
        "paired-fixture",
    )
    assert result["status"] == "failed"
    assert result["actual_optimizer_steps"] == result["new_environment_steps"] == 0
    assert result["reserved_model_transitions"] == 0
    assert result["local_anchors"] == {}
    assert result["checkpoint_saved"] is result["promoted"] is False
    assert imports == []
    assert json.loads(Path(result["report_path"]).read_text()) == result
    with RunStore(db) as store:
        if failure == "invalid_tensors":
            assert result["current_stage"] == "validation"
            run = store.get_run(result["run_id"])
            assert run.state == "failed"
            assert run.role == "auxiliary"
            assert run.reserved_optimizer_steps == run.reserved_model_transitions == 0
            assert run.reserved_active_seconds == 15
            assert store.get_experiment("paired-fixture").model_run_count == 0
        else:
            assert "run_id" not in result
            assert len(store.list_runs()) == (0 if failure == "missing_ledger" else 1)
