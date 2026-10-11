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
from ainerzero.runtime import interference_worker
from ainerzero.runtime.interference_worker import (
    VARIANTS,
    compare_variants,
    interference_plan,
    validate_interference_pair,
)
from ainerzero.runtime.lifecycle import RunStore
from ainerzero.runtime.memory_worker import memory_plan


def paired_metadata():
    config = PilotConfig().model_dump(mode="json")
    identity = {"manifest_sha256": "dataset-fixture", "public_sha256": {"train": ["a"]}}
    source = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "action_refinement",
        "config": config,
        "dataset_source": identity,
        "optimizer_steps": 100,
        "run_id": "source-fixture",
    }
    reference = {"checkpoint": "/tmp/source-fixture", "checkpoint_manifest_sha256": "abc"}
    candidate = {
        "architecture": "pilot_shared_symbol_v1",
        "phase": "one_step_memory",
        "config": deepcopy(config),
        "dataset_source": deepcopy(identity),
        "optimizer_steps": 100,
        "run_id": "candidate-fixture",
        "plan": memory_plan(),
        "readout_protocol": memory_plan()["readout"],
        "source": {**reference, "parent_run_id": source["run_id"], "dataset": deepcopy(identity)},
    }
    return source, candidate, config, identity, reference


def test_interference_plan_predeclares_three_frozen_arms_and_all_work():
    plan = interference_plan()
    assert plan["variants"] == list(VARIANTS) == ["source", "candidate", "front_reverted"]
    assert plan["parameter_count"] == 393232
    assert plan["optimizer_steps"] == plan["new_environment_steps"] == 0
    assert plan["automatic_promotion"] is plan["save_hybrid_checkpoint"] is False
    assert plan["intervention"] == {
        "Wx_Wh_b_rows": [[0, 128], [256, 384], [512, 640]],
        "bhn_rows": [[0, 128]],
        "end_exclusive": True,
    }
    assert plan["expected_model_units_per_variant"] == {
        "action": 5376,
        "memory": 7232,
        "reconstruction": 1088,
    }
    assert sum(plan["expected_model_units_per_variant"].values()) * 3 == 41088
    assert plan["expected_total_model_units"] == 41088
    assert sum(plan["resource_seconds"].values()) == 530
    assert plan["total_reserved_seconds_if_complete"] == 530
    assert 530 < plan["supervised_deadline_seconds"] == 600 < 650
    assert plan["evaluation"]["action_seed"] == 700
    assert plan["evaluation"]["memory_seed"] == 4901


@pytest.mark.parametrize("phase", ["action_prediction", "action_refinement"])
def test_pair_accepts_completed_m2h_child_of_exact_declared_source_without_mutation(phase):
    values = paired_metadata()
    values[0]["phase"] = phase
    original = deepcopy(values)
    validate_interference_pair(*values)
    assert values == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("architecture", "external_probe"),
        ("phase", "one_step_memory"),
        ("config", {}),
        ("dataset_source", {"manifest_sha256": "other"}),
        ("optimizer_steps", 0),
        ("optimizer_steps", True),
        ("optimizer_steps", 100.0),
        ("run_id", None),
    ],
)
def test_pair_rejects_ineligible_original_checkpoint(field, value):
    values = paired_metadata()
    values[0][field] = value
    with pytest.raises(ValueError, match="mismatch"):
        validate_interference_pair(*values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("architecture", "external_probe"),
        ("phase", "action_refinement"),
        ("config", {}),
        ("dataset_source", {"manifest_sha256": "other"}),
        ("optimizer_steps", 0),
        ("optimizer_steps", 99),
        ("optimizer_steps", 101),
        ("optimizer_steps", True),
        ("optimizer_steps", 100.0),
        ("run_id", None),
        ("run_id", "source-fixture"),
        ("readout_protocol", "new_trainable_readout"),
        ("plan", {}),
    ],
)
def test_pair_rejects_unfinished_or_wrong_candidate(field, value):
    values = paired_metadata()
    values[1][field] = value
    with pytest.raises(ValueError, match="mismatch"):
        validate_interference_pair(*values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("checkpoint", "/tmp/another-source"),
        ("checkpoint_manifest_sha256", "different-manifest"),
        ("parent_run_id", "another-parent"),
        ("dataset", {"manifest_sha256": "different-data"}),
    ],
)
def test_pair_rejects_each_mismatched_lineage_identity(field, value):
    values = paired_metadata()
    values[1]["source"][field] = value
    with pytest.raises(ValueError, match="mismatch"):
        validate_interference_pair(*values)


def test_pair_requires_complete_fixed_m2h_plan_not_only_protocol_name():
    values = paired_metadata()
    values[1]["plan"]["updates"] = 101
    with pytest.raises(ValueError, match="mismatch"):
        validate_interference_pair(*values)


def metric(nll=0.2):
    return {
        "count": 80,
        "changed_count": 8,
        "unchanged_count": 72,
        "accuracy": 0.9,
        "changed_accuracy": 0.0,
        "nll": nll,
    }


def comparison_results():
    control = metric(0.4)
    one = {
        "action": {
            "feedback_model_transitions": 32,
            "rollout_model_transitions": 16,
            "logical_model_transitions": 48,
            "query_count": 10,
            "episode_count": 1,
            "eval_seed": 700,
            "actor": {"actor_id": "random-fixture"},
            "assistance": [],
            "protocol": {"particles": 8, "support_ticks": 32, "query_stride": 8},
            "horizons": {
                str(h): {
                    "query_count": 10,
                    "copy": deepcopy(control),
                    "no_action": deepcopy(control),
                    "model": metric(),
                }
                for h in (1, 4)
            },
        },
        "memory": {
            "logical_model_transitions": 32,
            "feedback_model_transitions": 16,
            "initial_observation_encodes": 8,
            "reset_observation_encodes": 8,
            "budget_unit": "fixture_logical_unit",
            "seed": 4901,
            "partition": "development",
            "particles": 8,
            "support_ticks": 32,
            "query_stride": 1,
            "query_count": 10,
            "protocol": {"weight_updates": False, "fitted_readout": False},
            "methods": {
                name: deepcopy(control)
                for name in ("memory_tail", "copy_current", "fixed_current_codec", "reset_history")
            },
            "per_world": [
                {
                    "episode_id": "episode-a",
                    "environment_instance_id": "world-a",
                    "query_ticks": [32, 33],
                }
            ],
        },
        "reconstruction": {"model": metric(), "gate": {"status": "passed"}},
    }
    results = {name: deepcopy(one) for name in VARIANTS}
    for name, nll, memory_nll in zip(VARIANTS, (0.2, 2.2, 1.2), (7.0, 5.0, 6.0), strict=True):
        for h in ("1", "4"):
            results[name]["action"]["horizons"][h]["model"]["nll"] = nll
        results[name]["memory"]["methods"]["memory_tail"]["nll"] = memory_nll
    return results


def test_compare_uses_measured_same_run_scores_and_retains_memory_tradeoff():
    results = comparison_results()
    original = deepcopy(results)
    compared = compare_variants(results)
    assert compared["matched_controls_and_queries"] is True
    assert compared["promotion"] is False
    for h in ("1", "4"):
        assert compared["action_recovery"][h]["recovery_ratio"] == pytest.approx(0.5)
        assert compared["action_recovery"][h]["candidate_nll"] == 2.2
    assert compared["memory"]["candidate"]["nll"] == 5.0
    assert compared["memory"]["front_reverted"]["nll"] == 6.0
    assert results == original


@pytest.mark.parametrize("variant", ["candidate", "front_reverted"])
@pytest.mark.parametrize("control", ["copy", "no_action"])
@pytest.mark.parametrize("horizon", ["1", "4"])
def test_compare_rejects_different_action_controls(variant, control, horizon):
    results = comparison_results()
    results[variant]["action"]["horizons"][horizon][control]["nll"] += 0.1
    with pytest.raises(ValueError, match="mismatch"):
        compare_variants(results)


@pytest.mark.parametrize("field", ["count", "changed_count", "unchanged_count"])
@pytest.mark.parametrize("kind", ["action", "memory"])
def test_compare_rejects_different_scored_target_counts(field, kind):
    results = comparison_results()
    value = results["candidate"][kind]
    score = value["horizons"]["4"]["model"] if kind == "action" else value["methods"]["memory_tail"]
    score[field] += 1
    with pytest.raises(ValueError, match="mismatch"):
        compare_variants(results)


@pytest.mark.parametrize("control", ["copy_current", "fixed_current_codec", "reset_history"])
def test_compare_rejects_different_memory_controls(control):
    results = comparison_results()
    results["front_reverted"]["memory"]["methods"][control]["nll"] += 0.1
    with pytest.raises(ValueError, match="mismatch"):
        compare_variants(results)


@pytest.mark.parametrize(
    "field,value",
    [
        ("episode_id", "episode-b"),
        ("environment_instance_id", "world-b"),
        ("query_ticks", [31, 33]),
    ],
)
def test_compare_rejects_same_aggregate_on_different_memory_queries(field, value):
    results = comparison_results()
    results["candidate"]["memory"]["per_world"][0][field] = value
    with pytest.raises(ValueError, match="mismatch"):
        compare_variants(results)


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("action", "eval_seed", 701),
        ("action", "query_count", 11),
        ("action", "episode_count", 2),
        ("action", "protocol", {"particles": 4}),
        ("memory", "seed", 4902),
        ("memory", "partition", "train"),
        ("memory", "particles", 4),
        ("memory", "support_ticks", 31),
        ("memory", "query_stride", 2),
        ("memory", "query_count", 11),
        ("memory", "protocol", {"weight_updates": True}),
    ],
)
def test_compare_rejects_mismatched_random_keys_or_protocol(kind, field, value):
    results = comparison_results()
    results["candidate"][kind][field] = value
    with pytest.raises(ValueError, match="mismatch"):
        compare_variants(results)


def test_compare_rejects_current_reconstruction_difference():
    results = comparison_results()
    results["candidate"]["reconstruction"]["model"]["nll"] += 0.1
    with pytest.raises(ValueError, match="mismatch"):
        compare_variants(results)


@pytest.mark.parametrize("wrong", ["missing", "extra"])
def test_compare_requires_exactly_three_predeclared_variants(wrong):
    results = comparison_results()
    if wrong == "missing":
        del results["front_reverted"]
    else:
        results["fourth"] = deepcopy(results["source"])
    with pytest.raises(ValueError, match="three variants"):
        compare_variants(results)


@pytest.fixture
def cli_args(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="test"\n')
    config = tmp_path / "configs/pilot.yaml"
    config.parent.mkdir()
    config.write_text("{}\n")
    return argparse.Namespace(
        config=config,
        interference_diagnostic=True,
        dataset=tmp_path / "dataset.json",
        checkpoint=tmp_path / "source-checkpoint",
        candidate_checkpoint=tmp_path / "candidate-checkpoint",
        output_dir=tmp_path / "output",
        experiment_id="interference-test",
    )


@pytest.mark.parametrize("wall_limit", [1800, 120])
def test_cli_uses_shared_lock_canonical_ledger_and_bounded_worker(
    cli_args, monkeypatch, wall_limit
):
    cli_args.config.write_text(f"budget:\n  max_wall_seconds: {wall_limit}\n")
    root = cli_args.config.parents[1]
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert command[command.index("-m") + 1] == "ainerzero.runtime.interference_worker"
        for flag, value in (
            ("--dataset", cli_args.dataset),
            ("--checkpoint", cli_args.checkpoint),
            ("--candidate-checkpoint", cli_args.candidate_checkpoint),
            ("--control-db", root / "artifacts/control.sqlite3"),
        ):
            assert command[command.index(flag) + 1] == str(value.resolve())
        assert not {"--updates", "--seed", "--initial-checkpoint", "--recall"}.intersection(command)
        assert kwargs["timeout"] == min(650, wall_limit)
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
def test_supervisor_reaps_new_nonterminal_run_and_updates_saved_report(
    cli_args, monkeypatch, outcome
):
    report_path = cli_args.output_dir / "pilot-fixture/report.json"

    def run(command, **kwargs):
        db = command[command.index("--control-db") + 1]
        with RunStore(db) as store:
            store.create_run(
                {"budget": PilotConfig().budget.model_dump(mode="json")},
                "orphan",
                run_id="orphan",
            )
            store.transition("orphan", "initializing")
        report_path.parent.mkdir(parents=True)
        report_path.write_text(json.dumps({"status": "running", "retained_evidence": [1, 2]}))
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
    assert saved["retained_evidence"] == [1, 2]
    with RunStore(cli_args.config.parents[1] / "artifacts/control.sqlite3") as store:
        assert store.get_run("orphan").state == "failed"
        assert store.get_run("orphan").reason == "pilot_supervisor_cleanup"


def test_cli_parser_requires_two_explicit_checkpoints_and_exposes_no_training_knobs(monkeypatch):
    def run(args):
        assert args.interference_diagnostic is True
        assert args.checkpoint == Path("/tmp/source")
        assert args.candidate_checkpoint == Path("/tmp/candidate")
        assert not hasattr(args, "updates")
        assert not hasattr(args, "seed")
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    assert (
        cli.main(
            [
                "diagnose-interference",
                "--dataset",
                "/tmp/dataset",
                "--checkpoint",
                "/tmp/source",
                "--candidate-checkpoint",
                "/tmp/candidate",
                "--experiment-id",
                "fixture",
            ]
        )
        == 0
    )


@pytest.mark.parametrize(
    "missing", ["--dataset", "--checkpoint", "--candidate-checkpoint", "--experiment-id"]
)
def test_cli_rejects_missing_explicit_pair_inputs(missing):
    options = {
        "--dataset": "/tmp/data",
        "--checkpoint": "/tmp/source",
        "--candidate-checkpoint": "/tmp/candidate",
        "--experiment-id": "fixture",
    }
    with pytest.raises(SystemExit) as error:
        cli.main(
            ["diagnose-interference"]
            + [x for k, v in options.items() if k != missing for x in (k, v)]
        )
    assert error.value.code == 2


@pytest.mark.parametrize("extra", [["--updates", "1"], ["--seed", "42"]])
def test_cli_rejects_unregistered_training_arguments(extra):
    with pytest.raises(SystemExit) as error:
        cli.main(
            [
                "diagnose-interference",
                "--dataset",
                "/tmp/data",
                "--checkpoint",
                "/tmp/source",
                "--candidate-checkpoint",
                "/tmp/candidate",
                "--experiment-id",
                "fixture",
                *extra,
            ]
        )
    assert error.value.code == 2


def test_tensor_validation_failure_is_budgeted_and_terminal_before_model_import(
    tmp_path, monkeypatch
):
    source, candidate, config_dict, identity, reference = paired_metadata()
    config = PilotConfig.model_validate(config_dict)
    paths = [tmp_path / "source", tmp_path / "candidate"]
    for path in paths:
        path.mkdir()
        (path / "manifest.json").write_text('{"fixture": true}')
    reference.update(
        checkpoint=str(paths[0].resolve()),
        checkpoint_manifest_sha256=hashlib.sha256(
            (paths[0] / "manifest.json").read_bytes()
        ).hexdigest(),
    )
    candidate["source"].update(reference)
    monkeypatch.setattr(interference_worker, "load_pilot_config", lambda _: config)
    monkeypatch.setattr(interference_worker, "load_pilot_dataset", lambda *_: ({}, {}, identity))
    monkeypatch.setattr(
        interference_worker,
        "load_checkpoint",
        lambda path: ({}, source if path == paths[0] else candidate),
    )
    monkeypatch.setattr(cli, "pilot_manifest", lambda _: {"manifest": deepcopy(config_dict)})
    monkeypatch.setattr(interference_worker.psutil, "swap_memory", lambda: SimpleNamespace(used=0))
    monkeypatch.setattr(
        interference_worker.psutil, "virtual_memory", lambda: SimpleNamespace(available=100 * 2**30)
    )
    monkeypatch.setattr(
        interference_worker.psutil,
        "Process",
        lambda: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=1)),
    )
    monkeypatch.setattr(
        interference_worker.psutil, "disk_usage", lambda _: SimpleNamespace(free=100 * 2**30)
    )
    monkeypatch.setattr(
        interference_worker.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="AC Power")
    )
    imported = []
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "mlx" or name.startswith("mlx.") or name.endswith("pilot_model"):
            imported.append(name)
            raise AssertionError("invalid tensor pair must fail before native model imports")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    db = tmp_path / "control.sqlite3"
    result = interference_worker.run_interference(
        tmp_path / "config",
        tmp_path / "dataset",
        *paths,
        tmp_path / "output",
        db,
        "interference-validation-fixture",
    )
    assert result["status"] == "failed"
    assert result["current_stage"] == "validation"
    assert result["variants"] == {}
    assert result["actual_optimizer_steps"] == result["new_environment_steps"] == 0
    assert result["reserved_model_transitions"] == 0
    assert result["promoted"] is result["hybrid_checkpoint_saved"] is False
    assert imported == []
    assert json.loads(Path(result["report_path"]).read_text()) == result
    with RunStore(db) as store:
        run = store.get_run(result["run_id"])
        assert run.state == "failed"
        assert run.role == "auxiliary"
        assert run.reserved_optimizer_steps == run.reserved_model_transitions == 0
        assert run.reserved_environment_steps == 0
        assert run.reserved_active_seconds == 15
        assert store.get_experiment("interference-validation-fixture").model_run_count == 0
