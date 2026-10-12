"""M2m-c: the only registered change from stage B is learning rate 0.003."""

import json
import subprocess
from pathlib import Path

import pytest
from test_relabel_memory_worker import arguments, relabel_args  # noqa: F401

from ainerzero import cli
from ainerzero.runtime import memory_worker

ALLOWED_DIFFERENCES = {"protocol", "learning_rate", "comparison_caveat", "stage_b_comparison"}


def test_m2m_c_plan_differs_from_stage_b_only_in_learning_rate_and_labels():
    stage_b = memory_worker.relabel_memory_plan()
    candidate = memory_worker.relabel_memory_plan(0.003)
    assert candidate["learning_rate"] == 0.003 and stage_b["learning_rate"] == 0.001
    assert candidate["protocol"] == "m2m_c_consistent_relabel_lr0003_single_edge_tail_fit_v1"
    assert stage_b["protocol"] == "m2m_consistent_relabel_single_edge_tail_fit_v1"
    assert "stage_b_comparison" not in stage_b
    changed = {k for k in stage_b.keys() | candidate.keys() if stage_b.get(k) != candidate.get(k)}
    assert changed == ALLOWED_DIFFERENCES
    assert candidate["expected_total_model_units"] == 264480
    assert candidate["total_reserved_seconds_if_complete"] == 1670
    assert candidate["supervised_deadline_seconds"] == 1720
    assert candidate["updates"] == 200
    assert (candidate["batch_size"], candidate["micro_batch_size"]) == (16, 4)
    assert candidate["seeds"] == stage_b["seeds"]
    assert candidate["seeds"]["augmentation"] == 2307
    assert candidate["seeds"]["latent"] == 2203
    assert candidate["relabel_evaluation"]["seed"] == 9103
    assert candidate["automatic_promotion"] is False


def test_default_plan_is_still_stage_b_exactly():
    assert memory_worker.relabel_memory_plan() == memory_worker.relabel_memory_plan(0.001)


@pytest.mark.parametrize("rate", [0.002, 0.01, 0.0, 1, "0.003", None, 3e-3 + 1e-12])
def test_unregistered_learning_rates_are_rejected(rate):
    with pytest.raises(ValueError, match="registered"):
        memory_worker.relabel_memory_plan(rate)


def test_learning_rate_variant_requires_relabel_protocol(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("must fail before configuration")

    monkeypatch.setattr(memory_worker, "load_pilot_config", forbidden)
    with pytest.raises(ValueError, match="only to relabel"):
        memory_worker.run_memory(
            None,
            None,
            None,
            None,
            None,
            "x",
            diverse_fit=True,
            comparison_report_path=Path("r"),
            relabel_learning_rate=0.003,
        )


@pytest.mark.parametrize("rate", ["0.001", "0.003"])
def test_cli_forwards_registered_learning_rate(relabel_args, monkeypatch, rate):  # noqa: F811
    relabel_args.config.write_text("budget:\n  max_wall_seconds: 1800\n")
    relabel_args.learning_rate = rate
    seen = []

    def run(command, **kwargs):
        seen.append(command[command.index("--relabel-learning-rate") + 1])
        assert kwargs["timeout"] == 1770
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": "completed"}), "")

    monkeypatch.setattr(subprocess, "run", run)
    assert cli.train_pilot_command(relabel_args)["status"] == "completed"
    assert seen == [rate]


def test_parser_default_is_stage_b_and_accepts_only_registered(monkeypatch):
    got = []

    def run(args):
        got.append(args)
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", run)
    cli.main(arguments())
    cli.main(arguments() + ["--learning-rate", "0.003"])
    assert [a.learning_rate for a in got] == ["0.001", "0.003"]
    for bad in ("0.002", "3e-3", "0.0030"):
        with pytest.raises(SystemExit):
            cli.main(arguments() + ["--learning-rate", bad])


def test_worker_parser_accepts_only_registered(monkeypatch):
    captured = {}

    def fake(*args, **kwargs):
        captured.update(kwargs)
        return {"status": "completed"}

    monkeypatch.setattr(memory_worker, "run_memory", fake)
    base = ["w"]
    for name in ("config", "dataset", "checkpoint", "output-dir", "control-db"):
        base += [f"--{name}", "/tmp/x"]
    base += ["--experiment-id", "e", "--relabel-fit"]
    monkeypatch.setattr("sys.argv", base + ["--relabel-learning-rate", "0.003"])
    assert memory_worker.main() == 0
    assert captured["relabel_learning_rate"] == 0.003
    monkeypatch.setattr("sys.argv", base)
    memory_worker.main()
    assert captured["relabel_learning_rate"] is None
    monkeypatch.setattr("sys.argv", base + ["--relabel-learning-rate", "0.01"])
    with pytest.raises(SystemExit):
        memory_worker.main()
