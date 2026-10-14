"""E13b entry tests (T3, T4): plan, old-entry compatibility, CLI wiring; no MLX."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation as ap
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "m2md_pool_manifest.json"

# Canonical digests recorded before E13b modified memory_worker.py (source 1236103976ef...263e).
OLD_PLAN_SHA256 = {
    "memory_plan": "ec73cfdab0ffe3dec4992aba80dcc86dc8a526a1fd9c1ee4ce817ce991d7d51d",
    "micro_memory_plan": "2407e358866f79877da7abb4e15325bb6eff92e0c25dfe48f49dc4250396ab5d",
    "diverse_memory_plan": "535a726d00496bb9fb1572337a49cad8ba86c6bd1ec70fd54e111d2254dec797",
    "relabel_0.001": "45d4c0a39baaad61aff55120387f143eb9491e8e870fe126f1f604015d4658c4",
    "relabel_0.003": "249adc8596041098093cab8a124e27c11df0edd6b8e44ddc16cca71ecb4374a7",
}


def _d(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_no_mlx_imported():
    """The CPU layer must import without MLX (checked in a fresh process).

    A single-process full-suite run has MLX loaded by other tests, so the
    process-level assertion is checked where it is meaningful: in a fresh
    interpreter, following the existing repo idiom
    (``test_old_protocols_untouched_and_no_mlx``).
    """
    code = ("import sys, ainerzero.runtime.memory_worker, ainerzero.cli; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    import subprocess
    subprocess.run([sys.executable, "-c", code.format()], check=True)


# ---- T3

def test_t3_plan_seconds_units_deadlines():
    plan = mw.action_preservation_memory_plan()
    seconds = plan["resource_seconds"]
    assert "m2l_paired_cells" not in seconds and "m2l_relabel_pool" not in seconds
    assert (seconds["training_update"], seconds["teacher_cache"], seconds["cache_protocol_checks"]) == (3, 60, 10)
    counts = {"training_update": 200, "local_check": 10}
    assert sum(v * counts.get(k, 1) for k, v in seconds.items()) == 1610
    assert plan["total_reserved_seconds_if_complete"] == 1610
    assert plan["supervised_deadline_seconds"] == 1660 and plan["supervisor_deadline_seconds"] == 1710
    assert 178_304 + 2_254 + 27_988 == plan["expected_total_model_units"] == 208_546
    assert plan["protocol"] == ap.PROTOCOL and plan["learning_rate"] == 0.003
    assert ap.plan_sha256(plan["action_preservation"]).startswith("cb1437ef")
    assert ap.plan_sha256(plan["action_preservation"]) == ap.FROZEN_PLAN_SHA256


def test_t3_student_units_table():
    f = json.loads(FIXTURE.read_text())
    windows = ap.preservation_windows(f["samples"], f["schedule"])
    table = apc.student_units_per_update(windows)
    assert len(table) == 200 and sum(table) == 27_988 and min(table) >= 137 and max(table) <= 144
    bad = dict(windows, schedule=windows["schedule"][:-1])
    with pytest.raises(ValueError):
        apc.student_units_per_update(bad)


# ---- T4

def test_t4_old_plans_unchanged():
    plans = {"memory_plan": mw.memory_plan(), "micro_memory_plan": mw.micro_memory_plan(),
             "diverse_memory_plan": mw.diverse_memory_plan(),
             "relabel_0.001": mw.relabel_memory_plan(0.001), "relabel_0.003": mw.relabel_memory_plan(0.003)}
    assert {k: _d(v) for k, v in plans.items()} == OLD_PLAN_SHA256


def _capture(monkeypatch, argv):
    seen = {}

    def fake(args):
        seen["args"] = args
        return {"status": "completed"}

    monkeypatch.setattr(cli, "train_pilot_command", fake)
    assert cli.main(argv) == 0
    return seen["args"]


REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]


def test_t4_new_subcommand_args(monkeypatch, capsys):
    args = _capture(monkeypatch, ["train-action-preserved-memory", *REQUIRED])
    assert args.action_preserved_memory_training is True and not hasattr(args, "learning_rate")
    with pytest.raises(SystemExit):
        cli.main(["train-action-preserved-memory", *REQUIRED, "--learning-rate", "0.003"])
    for i in range(0, len(REQUIRED) - 2, 2):
        with pytest.raises(SystemExit):
            cli.main(["train-action-preserved-memory", *(REQUIRED[:i] + REQUIRED[i + 2:])])


def test_t4_old_relabel_subcommand_unchanged(monkeypatch, capsys):
    base = ["train-relabel-memory", *REQUIRED[:10], "--experiment-id", "e"]
    args = _capture(monkeypatch, base)
    assert args.learning_rate == "0.001" and not hasattr(args, "m2mc_report")
    assert not getattr(args, "action_preserved_memory_training", False)
    with pytest.raises(SystemExit):
        cli.main([*base, "--m2mc-report", "x"])


def test_t4_timeouts_and_dispatch(monkeypatch, tmp_path):
    seen = []

    class Done:
        returncode, stdout, stderr = 1, "", ""

    def fake_run(cmd, **kw):
        seen.append((cmd, kw["timeout"]))
        return Done()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    config = ROOT / "configs" / "pilot.yaml"
    limit = cli.load_pilot_config(config).budget.max_wall_seconds

    class Args:
        pass

    def run(**flags):
        a = Args()
        a.config, a.output_dir, a.experiment_id = config, tmp_path, "e"
        for name in ("dataset", "checkpoint", "comparison_report", "m2l_report", "m2l_checkpoint", "m2mc_report"):
            setattr(a, name, tmp_path / name)
        a.learning_rate = "0.001"
        for k, v in flags.items():
            setattr(a, k, v)
        monkeypatch.setattr(cli, "project_root", lambda _: tmp_path)
        cli.train_pilot_command(a)
        return seen[-1]

    cmd, timeout = run(action_preserved_memory_training=True)
    assert timeout == min(1710, limit)
    assert "--action-preservation-fit" in cmd and "--m2mc-report" in cmd
    assert "--relabel-learning-rate" not in cmd and "--relabel-fit" not in cmd and "--local-fit" not in cmd
    cmd, timeout = run(relabel_memory_training=True)
    assert timeout == min(1770, limit) and "--relabel-learning-rate" in cmd and "0.001" in cmd
    assert "--action-preservation-fit" not in cmd
    cmd, timeout = run(diverse_memory_training=True)
    assert timeout == min(1550, limit)


@pytest.mark.parametrize("extra", [
    {"relabel_learning_rate": 0.003}, {"local_fit": True}, {"diverse_fit": True}, {"relabel_fit": True},
])
def test_t4_manual_combinations_rejected(extra, tmp_path):
    with pytest.raises(ValueError, match="no manual combination"):
        mw.run_memory(None, None, None, tmp_path, tmp_path / "db", "e",
                      action_preservation_fit=True, m2mc_report_path=tmp_path / "x", **extra)


def test_t4_flag_and_report_paired():
    with pytest.raises(ValueError, match="exactly its M2m-c report"):
        mw.run_memory(None, None, None, None, None, "e", action_preservation_fit=True)
    with pytest.raises(ValueError, match="exactly its M2m-c report"):
        mw.run_memory(None, None, None, None, None, "e", m2mc_report_path=Path("x"))


def test_t4_worker_argparse_flags(monkeypatch):
    import argparse

    captured = {}
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: captured.update(k) or {"status": "failed"})
    monkeypatch.setattr(sys, "argv", ["w", "--config", "c", "--dataset", "d", "--checkpoint", "k",
                                      "--output-dir", "o", "--control-db", "b", "--experiment-id", "e",
                                      "--action-preservation-fit", "--m2mc-report", "x"])
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert captured["action_preservation_fit"] is True and captured["m2mc_report_path"] == Path("x")
    assert captured["relabel_learning_rate"] is None and captured["relabel_fit"] is False
    assert isinstance(argparse, object)
