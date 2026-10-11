"""CPU-only contracts for the frozen M2m-a coverage diagnostic worker."""

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
from ainerzero.learning.evaluation import _Summary
from ainerzero.runtime.coverage_worker import (
    compare_zero_context_reproduction,
    coverage_diagnostic_plan,
    validate_coverage_source,
)
from ainerzero.runtime.lifecycle import RunStore
from ainerzero.runtime.memory_worker import diverse_memory_plan


def coverage_inputs():
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
    inherited = {
        "checkpoint": source["checkpoint"],
        "checkpoint_manifest_sha256": source["checkpoint_manifest_sha256"],
        "parent_run_id": source["run_id"],
        "dataset": deepcopy(identity),
    }
    fixed = {"batch_sha256": "micro", "sample_manifest_sha256": "micro-samples"}
    training = {
        "batch_sha256": "pool",
        "sample_manifest_sha256": "pool-samples",
        "schedule_sha256": "schedule",
        "samples": [],
    }
    queries = {"query_manifest_sha256": "queries"}
    plan = diverse_memory_plan()
    candidate_metadata = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "diverse_memory_fit",
        "config": deepcopy(config),
        "dataset_source": deepcopy(identity),
        "optimizer_steps": 200,
        "run_id": "candidate",
        "manifest_hash": "candidate-prereg",
        "plan": plan,
        "readout_protocol": plan["readout"],
        "source": deepcopy(inherited),
        "fixed_samples": deepcopy(fixed),
        "training_samples": deepcopy(training),
        "sampler": {"burn_in": 0, "sequence_steps": 1},
        "rng_states": {"fixed_seed": 2203},
    }
    source_report = {
        "status": "completed",
        "experiment_id": "m2l-fixture",
        "run_id": "candidate",
        "manifest_hash": "candidate-prereg",
        "checkpoint": candidate["checkpoint"],
        "checkpoint_verified": True,
        "plan": diverse_memory_plan(),
        "source": deepcopy(inherited),
        "fixed_samples": deepcopy(fixed),
        "training_samples": deepcopy(training),
        "actual_optimizer_steps": 200,
        "tail_protection_checks": 200,
        "new_environment_steps": 0,
        "logical_model_transitions": 174208,
        "reserved_model_transitions": 174208,
        "frozen_modules_unchanged": True,
        "source_files_unchanged": True,
        "promoted": False,
        "run": {"run_id": "candidate", "state": "completed"},
        "paired": {
            "query_manifest_sha256": "queries",
            "seed": 7103,
            "particles": 8,
            "first_edge_pairs_identical": True,
            "first_edge_pair_checks": 20,
            "per_query": [{}] * 2560,
        },
        "diverse_groups": {
            "query_manifest_sha256": "queries",
            "sample_manifest_sha256": "pool-samples",
            "per_query": [{}] * 2560,
        },
    }
    return [
        source_metadata,
        candidate_metadata,
        config,
        identity,
        source,
        candidate,
        source_report,
        fixed,
        training,
        queries,
    ]


def test_plan_reserves_registered_units_and_time_without_updates():
    plan = coverage_diagnostic_plan()
    assert plan["expected_model_units"] == {
        "zero_context_cells": 2560 * 2 * 8,
        "slot_substitution": 2 * 8 * 256 * 2 * 8,
    }
    assert plan["expected_total_model_units"] == 106496
    assert sum(plan["resource_seconds"].values()) == 410
    assert plan["total_reserved_seconds_if_complete"] == 410
    assert 410 < plan["supervised_deadline_seconds"] == 700 < plan["supervisor_timeout_seconds"]
    assert plan["optimizer_steps"] == plan["new_environment_steps"] == 0
    assert plan["automatic_promotion"] is plan["checkpoint_saved"] is False
    assert plan["substitution"]["seed"] == 7307 and plan["evaluation"]["seed"] == 7103


def test_plan_is_fresh_on_each_call():
    first = coverage_diagnostic_plan()
    first["resource_seconds"]["slot_substitution"] = 999
    first["decision_rules"]["r2_other_cell_drop_min"] = 0.5
    assert coverage_diagnostic_plan()["resource_seconds"]["slot_substitution"] == 200
    assert coverage_diagnostic_plan()["decision_rules"]["r2_other_cell_drop_min"] == 0.1


def test_completed_m2l_lineage_is_accepted_without_mutation():
    values = coverage_inputs()
    original = deepcopy(values)
    validate_coverage_source(*values)
    assert values == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("phase", "micro_memory_fit"),
        ("plan", {}),
        ("optimizer_steps", 199),
        ("optimizer_steps", 200.0),
        ("optimizer_steps", True),
        ("run_id", "original"),
        ("run_id", None),
        ("manifest_hash", None),
        ("training_samples", {"batch_sha256": "other"}),
        ("fixed_samples", {}),
        ("rng_states", {"fixed_seed": 1}),
        ("sampler", {"burn_in": 4, "sequence_steps": 16}),
        ("dataset_source", {}),
    ],
)
def test_rejects_incompatible_candidate(field, value):
    values = coverage_inputs()
    values[1][field] = value
    with pytest.raises(ValueError):
        validate_coverage_source(*values)


@pytest.mark.parametrize(
    "field,value",
    [("checkpoint", "/tmp/x"), ("checkpoint_manifest_sha256", "x"), ("parent_run_id", "x")],
)
def test_rejects_changed_m2d_lineage(field, value):
    values = coverage_inputs()
    values[1]["source"][field] = value
    with pytest.raises(ValueError):
        validate_coverage_source(*values)


def test_rejects_wrong_original_checkpoint_phase():
    values = coverage_inputs()
    values[0]["phase"] = "diverse_memory_fit"
    with pytest.raises(ValueError):
        validate_coverage_source(*values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("checkpoint", "/tmp/other"),
        ("checkpoint_verified", 1),
        ("run_id", "other"),
        ("manifest_hash", "other"),
        ("promoted", 0),
        ("actual_optimizer_steps", 200.0),
        ("tail_protection_checks", 199),
        ("logical_model_transitions", 174207),
        ("reserved_model_transitions", 0),
        ("frozen_modules_unchanged", False),
        ("source_files_unchanged", False),
        ("new_environment_steps", 1),
        ("training_samples", {}),
        ("plan", {}),
        ("run", {"run_id": "candidate", "state": "failed"}),
        ("paired", None),
        ("diverse_groups", None),
    ],
)
def test_rejects_unverified_m2l_report(field, value):
    values = coverage_inputs()
    values[6][field] = value
    with pytest.raises(ValueError):
        validate_coverage_source(*values)


@pytest.mark.parametrize(
    "path,value",
    [
        (("paired", "query_manifest_sha256"), "other"),
        (("paired", "seed"), 7104),
        (("paired", "particles"), 1),
        (("paired", "first_edge_pairs_identical"), False),
        (("paired", "per_query"), []),
        (("diverse_groups", "sample_manifest_sha256"), "other"),
        (("diverse_groups", "query_manifest_sha256"), "other"),
    ],
)
def test_rejects_changed_queries_or_pool_regrouping(path, value):
    values = coverage_inputs()
    values[6][path[0]][path[1]] = value
    with pytest.raises(ValueError):
        validate_coverage_source(*values)


def metrics(accuracy):
    return {
        "nll": 1.0 - accuracy / 2,
        "count": 8,
        "accuracy": accuracy,
        "changed_nll": None,
        "changed_count": 0,
        "changed_accuracy": None,
        "unchanged_count": 8,
        "unchanged_nll": 1.0 - accuracy / 2,
        "unchanged_accuracy": accuracy,
    }


def reproduction_fixture():
    legacy = ["selected_train", "unselected_train", "unselected_train", "development"]
    previous = [True, True, False, False]
    labels = [
        "selected_train",
        "unselected_train_previous_in_pool",
        "unselected_train_previous_not_in_pool",
        "development",
    ]
    rows = [
        {
            "row": i,
            "episode_id": f"e{i}",
            "query_tick": i + 1,
            "paired_random_seeds": [i, i + 1, i + 2],
            "zero_context_tail": metrics(a),
        }
        for i, a in enumerate((1.0, 0.875, 0.5, 0.0))
    ]
    observed = {
        "query_manifest_sha256": "q",
        "random_schedule_sha256": "k",
        "per_query": rows,
    }

    def summary(indices):
        result = _Summary()
        for i in indices:
            result.add(rows[i]["zero_context_tail"])
        return {"methods": {"zero_context_tail": result.result()}}

    groups = {"all_queries": summary(range(4)), "groups": {}}
    for group in ("selected_train", "unselected_train", "development"):
        members = [i for i, g in enumerate(legacy) if g == group]
        groups["groups"][group] = summary(members)
        for label in ("previous", "edge"):
            flags = previous if label == "previous" else [False] * 4
            groups["groups"][group][f"{label}_input_matches_pool"] = {
                str(f).lower(): summary([i for i in members if flags[i] is f])
                for f in (True, False)
            }
    groups["per_query"] = [
        {"group": g, "previous_input_matches_pool": p, "edge_input_matches_pool": False}
        for g, p in zip(legacy, previous, strict=True)
    ]
    report = {
        "paired": {
            "query_manifest_sha256": "q",
            "random_schedule_sha256": "k",
            "per_query": [
                {
                    "row": r["row"],
                    "episode_id": r["episode_id"],
                    "query_tick": r["query_tick"],
                    "paired_random_seeds": list(r["paired_random_seeds"]),
                    "methods": {"zero_context_tail": dict(r["zero_context_tail"])},
                }
                for r in rows
            ],
        },
        "diverse_groups": groups,
    }
    return observed, report, labels


def test_exact_reproduction_is_accepted():
    observed, report, labels = reproduction_fixture()
    result = compare_zero_context_reproduction(observed, report, labels)
    assert result["exact_match"] is True and result["group_summaries_checked"] == 16


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o, r, labels: o["per_query"][2]["zero_context_tail"].update(nll=0.7500000001),
        lambda o, r, labels: o["per_query"][1]["paired_random_seeds"].__setitem__(0, 9),
        lambda o, r, labels: o.update(random_schedule_sha256="other"),
        lambda o, r, labels: o.update(query_manifest_sha256="other"),
        lambda o, r, labels: labels.__setitem__(2, "unselected_train_previous_in_pool"),
        lambda o, r, labels: r["diverse_groups"]["all_queries"]["methods"][
            "zero_context_tail"
        ].update(accuracy=0.6),
    ],
)
def test_any_reproduction_difference_stops(mutate):
    observed, report, labels = reproduction_fixture()
    mutate(observed, report, labels)
    with pytest.raises(ValueError):
        compare_zero_context_reproduction(observed, report, labels)


@pytest.fixture
def cli_args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return argparse.Namespace(
        config=config,
        coverage_diagnostic=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "original",
        candidate_checkpoint=tmp_path / "candidate",
        source_report=tmp_path / "m2l.json",
        output_dir=tmp_path / "output",
        experiment_id="coverage-test",
    )


@pytest.mark.parametrize("wall_limit", [1800, 120])
def test_cli_holds_shared_lock_and_supervises_coverage_worker(cli_args, monkeypatch, wall_limit):
    cli_args.config.write_text(f"budget:\n  max_wall_seconds: {wall_limit}\n")
    root = cli_args.config.parents[1]
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.coverage_worker"
        for flag, value in (
            ("--dataset", cli_args.dataset),
            ("--checkpoint", cli_args.checkpoint),
            ("--candidate-checkpoint", cli_args.candidate_checkpoint),
            ("--source-report", cli_args.source_report),
            ("--control-db", root / "artifacts/control.sqlite3"),
        ):
            assert command[command.index(flag) + 1] == str(value.resolve())
        assert kwargs["timeout"] == min(750, wall_limit)
        with pytest.raises(RuntimeError, match="already running"):
            with cli.worker_lock(root / "artifacts/locks/m0-worker.lock"):
                pytest.fail("supervisor released the shared lock")
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.train_pilot_command(cli_args)["status"] == "completed"
    assert len(calls) == 1


def test_supervisor_marks_orphan_failed_and_never_reports_success(cli_args, monkeypatch):
    def run(command, **kwargs):
        with RunStore(command[command.index("--control-db") + 1]) as store:
            store.create_run(
                {"budget": PilotConfig().budget.model_dump(mode="json")}, "orphan", run_id="orphan"
            )
            store.transition("orphan", "initializing")
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", run)
    result = cli.train_pilot_command(cli_args)
    assert result["status"] == "failed" and result["interrupted_run_ids"] == ["orphan"]


def arguments():
    return [
        "diagnose-memory-coverage",
        "--dataset",
        "/tmp/dataset",
        "--checkpoint",
        "/tmp/original",
        "--candidate-checkpoint",
        "/tmp/candidate",
        "--source-report",
        "/tmp/m2l.json",
        "--experiment-id",
        "coverage-test",
    ]


def test_parser_exposes_only_the_frozen_diagnostic(monkeypatch):
    seen = []

    def run(args):
        seen.append(args)
        assert args.coverage_diagnostic is True
        assert not hasattr(args, "updates") and not hasattr(args, "seed")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert cli.main(arguments()) == 0 and len(seen) == 1


@pytest.mark.parametrize(
    "missing",
    ["--dataset", "--checkpoint", "--candidate-checkpoint", "--source-report", "--experiment-id"],
)
def test_parser_requires_all_lineage_inputs(missing):
    args = arguments()
    index = args.index(missing)
    del args[index : index + 2]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize(
    "override", [["--updates", "1"], ["--seed", "1"], ["--particles", "1"], ["--variants", "9"]]
)
def test_parser_rejects_unregistered_overrides(override):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments() + override)
    assert error.value.code == 2


@pytest.mark.parametrize("failure", ["missing_ledger", "incomplete_ledger", "invalid_tensors"])
def test_stops_before_native_work_and_books_only_registered_stage(tmp_path, monkeypatch, failure):
    import numpy as np

    from ainerzero.runtime import coverage_worker as worker

    values = coverage_inputs()
    source_metadata, candidate_metadata, config_dict, identity = values[:4]
    source, candidate, source_report, fixed, training, queries = values[4:]
    config = PilotConfig.model_validate(config_dict)
    source_path = tmp_path / "original"
    run_directory = tmp_path / "m2l-run"
    candidate_path = run_directory / "checkpoints" / "candidate"
    for path, reference in ((source_path, source), (candidate_path, candidate)):
        path.mkdir(parents=True)
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
    pool = {
        "symbols": np.zeros((2, 2, 8), dtype=np.int32),
        "visible_mask": np.ones((2, 2, 8), dtype=bool),
        "cursor": np.zeros((2, 2), dtype=np.int32),
        "episode_start": np.ones((2, 2), dtype=bool),
        "actions": np.zeros((2, 1), dtype=np.int32),
    }
    np.savez(run_directory / "training-pool.npz", **pool)
    from ainerzero.learning.micro_memory import _batch_digest

    for item in (training, candidate_metadata["training_samples"]):
        item["batch_sha256"] = _batch_digest(pool)
    source_report.update(
        checkpoint=candidate["checkpoint"],
        source=deepcopy(candidate_metadata["source"]),
        training_samples=deepcopy(training),
        run_directory=str(run_directory.resolve()),
        training_pool_path=str((run_directory / "training-pool.npz").resolve()),
    )
    db = tmp_path / "control.sqlite3"
    if failure != "missing_ledger":
        with RunStore(db) as store:
            experiment = store.create_experiment(config_dict, "m2l-fixture", "m2l-fixture")
            candidate_metadata["manifest_hash"] = source_report["manifest_hash"] = (
                experiment.manifest_hash
            )
            store.create_run(
                config_dict, "candidate", "candidate", experiment_id="m2l-fixture", role="model"
            )
            store.transition("candidate", "initializing")
            store.transition("candidate", "training")
            store.consume("candidate", optimizer_steps=200, model_transitions=174208)
            if failure == "invalid_tensors":
                store.transition("candidate", "completed")
    report_path = tmp_path / "m2l.json"
    report_path.write_text(json.dumps(source_report))
    monkeypatch.setattr(worker, "load_pilot_config", lambda _: config)
    monkeypatch.setattr(
        worker, "load_pilot_dataset", lambda *_: ({}, {"train": object()}, identity)
    )
    monkeypatch.setattr(
        worker,
        "load_checkpoint",
        lambda path: ({}, source_metadata if path == source_path else candidate_metadata),
    )
    monkeypatch.setattr(worker, "select_micro_memory_samples", lambda _: ({}, fixed))
    monkeypatch.setattr(worker, "select_diverse_memory_samples", lambda _: (pool, training))
    from ainerzero.learning import paired_memory

    monkeypatch.setattr(paired_memory, "paired_memory_samples", lambda _: queries)
    monkeypatch.setattr(worker, "query_frames", lambda _: ({}, {**queries, "queries": []}))
    monkeypatch.setattr(worker, "query_labels", lambda *_: ["selected_train"])
    monkeypatch.setattr(worker, "pool_position_symbol_sets", lambda _: {"sets": True})
    monkeypatch.setattr(
        worker, "classify_query_cells", lambda *_: {"classification_sha256": "cells"}
    )
    monkeypatch.setattr(
        worker,
        "build_substitution_variants",
        lambda *_: ({}, {"variant_manifest_sha256": "variants", "variants": []}),
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
    monkeypatch.setattr(
        worker.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="AC Power")
    )
    imports = []
    original_import = builtins.__import__

    def forbid_native(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx.") or name.endswith("pilot_model"):
            imports.append(name)
            raise AssertionError("invalid sources must fail before native imports")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_native)
    result = worker.run_coverage_diagnostic(
        tmp_path / "config",
        tmp_path / "dataset",
        source_path,
        candidate_path,
        report_path,
        tmp_path / "output",
        db,
        "coverage-fixture",
    )
    assert result["status"] == "failed"
    assert result["actual_optimizer_steps"] == result["new_environment_steps"] == 0
    assert result["reserved_model_transitions"] == 0
    assert result["checkpoint_saved"] is result["promoted"] is False
    assert imports == []
    assert json.loads(Path(result["report_path"]).read_text()) == result
    with RunStore(db) as store:
        if failure == "invalid_tensors":
            assert result["current_stage"] == "validation"
            run = store.get_run(result["run_id"])
            assert run.state == "failed" and run.role == "auxiliary"
            assert run.reserved_optimizer_steps == run.reserved_model_transitions == 0
            assert run.reserved_active_seconds == 15
            assert store.get_experiment("coverage-fixture").model_run_count == 0
        else:
            assert "run_id" not in result
            assert len(store.list_runs()) == (0 if failure == "missing_ledger" else 1)
