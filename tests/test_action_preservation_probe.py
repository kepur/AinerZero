"""E13b-R1 C06a probe entry tests: plan, CLI/worker wiring, no checkpoint, cache rejection; no MLX."""

import inspect
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation as ap
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "m2md_pool_manifest.json"
REQUIRED = ["--dataset", "d", "--checkpoint", "c", "--comparison-report", "r", "--m2l-report", "m",
            "--m2l-checkpoint", "k", "--m2mc-report", "x", "--experiment-id", "e"]


def test_no_mlx_imported():
    """The CPU layer must import without MLX (checked in a fresh process).

    A single-process full-suite run has MLX loaded by other tests, so the
    process-level assertion is checked where it is meaningful: in a fresh
    interpreter, following the existing repo idiom
    (``test_old_protocols_untouched_and_no_mlx``).
    """
    code = ("import sys, ainerzero.runtime.memory_worker; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    import subprocess
    subprocess.run([sys.executable, "-c", code.format()], check=True)


def test_probe_plan_totals():
    plan = mw.action_preservation_probe_plan()
    s = plan["resource_seconds"]
    assert s == {"compatibility": 15, "initialization": 15, "teacher_cache": 60, "cache_protocol_checks": 10,
                 "teacher_repeat": 60, "training_update": 3, "verification": 10}
    assert sum(v * (3 if k == "training_update" else 1) for k, v in s.items()) == 179
    assert plan["expected_total_model_units"] == 2 * 2254 + 3 * 32 + 139 + 138 + 144 == 5025
    assert (plan["total_reserved_seconds_if_complete"], plan["supervised_deadline_seconds"],
            plan["supervisor_deadline_seconds"]) == (179, 229, 279)
    assert plan["updates"] == 3 and plan["promotion"] is False and plan["local_checks"] == []
    assert plan["learning_rate"] == 0.003 and plan["seeds"]["latent"] == 2203
    assert ap.plan_sha256(plan["action_preservation"]) == ap.FROZEN_PLAN_SHA256


def test_probe_student_units_match_registered_windows():
    f = json.loads(FIXTURE.read_text())
    table = apc.student_units_per_update(ap.preservation_windows(f["samples"], f["schedule"]))
    assert tuple(table[:3]) == mw.PROBE_STUDENT_UNITS == (139, 138, 144)


def test_production_plan_unchanged_by_probe():
    plan = mw.action_preservation_memory_plan()
    assert plan["updates"] == 200 and plan["expected_total_model_units"] == 208_546
    assert plan["supervised_deadline_seconds"] == 1660


def test_probe_never_saves_checkpoint_or_evaluates():
    source = inspect.getsource(mw.run_action_preservation_probe)
    for banned in ("save_checkpoint", "evaluate_one_step_memory", "evaluate_predictor",
                   "evaluate_reconstruction", "evaluate_paired_memory", "evaluate_zero_context_inputs",
                   "evaluate_micro_memory", "promote("):
        assert banned not in source
    assert '"checkpoint_saved": False' in source and '"promoted": False' in source
    assert "probe-teacher-cache.npz" in source and "probe-teacher-cache-manifest.json" in source
    assert 'role="model"' in source


def test_probe_cache_rejected_by_production_binding(tmp_path):
    f = json.loads(FIXTURE.read_text())
    records = {}
    for s in f["samples"]:
        r = records.setdefault(s["episode_id"], {"partition": "train",
                                                 "environment_instance_id": s["environment_instance_id"],
                                                 "public_episode_sha256": s["public_episode_sha256"],
                                                 "transitions": {}})
        r["transitions"][s["transition_index"]] = {k: s[k] for k in (
            "target_observation_id", "current_observation_id", "action_request_id",
            "public_transition_sha256", "target_tick")}
    out = apc.production_windows(f["samples"], f["schedule"], records)
    (tmp_path / "manifest.json").write_bytes(b"m2d")
    probe_run, production_run = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
    make = lambda run: apc.expected_cache_binding(checkpoint_path=tmp_path, windows=out["windows"],  # noqa: E731
                                                  keys=out["keys"], run_id=run)
    rng = np.random.default_rng(1)
    arrays = {"incoming_h": rng.standard_normal((256, 256)).astype(np.float32),
              "teacher_logits": rng.standard_normal((256, 2, 8, 256)).astype(np.float32),
              "visible_mask": np.ones((256, 8), dtype=np.bool_)}
    probe_manifest = ap.teacher_cache_manifest(make(probe_run), arrays)
    ap.verify_teacher_cache(probe_manifest, arrays, make(probe_run))
    with pytest.raises(ValueError, match="run_id"):
        ap.verify_teacher_cache(probe_manifest, arrays, make(production_run))


def _capture(monkeypatch, argv):
    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda a: seen.update(args=a) or {"status": "completed"})
    assert cli.main(argv) == 0
    return seen["args"]


def test_probe_cli_args(monkeypatch, capsys):
    args = _capture(monkeypatch, ["probe-action-preserved-memory", *REQUIRED])
    assert args.action_preservation_probe is True and not hasattr(args, "learning_rate")
    assert not getattr(args, "action_preserved_memory_training", False)
    for extra in (["--learning-rate", "0.003"], ["--updates", "3"], ["--seed", "1"]):
        with pytest.raises(SystemExit):
            cli.main(["probe-action-preserved-memory", *REQUIRED, *extra])
    for i in range(0, len(REQUIRED), 2):
        with pytest.raises(SystemExit):
            cli.main(["probe-action-preserved-memory", *(REQUIRED[:i] + REQUIRED[i + 2:])])


def test_probe_dispatch_and_timeout(monkeypatch, tmp_path):
    seen = []

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, **kw: seen.append((cmd, kw["timeout"])) or Done())
    monkeypatch.setattr(cli, "project_root", lambda _: tmp_path)
    config = ROOT / "configs" / "pilot.yaml"
    limit = cli.load_pilot_config(config).budget.max_wall_seconds

    class Args:
        pass

    a = Args()
    a.config, a.output_dir, a.experiment_id = config, tmp_path, "e"
    for name in ("dataset", "checkpoint", "comparison_report", "m2l_report", "m2l_checkpoint", "m2mc_report"):
        setattr(a, name, tmp_path / name)
    a.action_preservation_probe = True
    cli.train_pilot_command(a)
    cmd, timeout = seen[-1]
    assert timeout == min(279, limit)
    assert "--action-preservation-probe" in cmd and "--m2mc-report" in cmd
    for flag in ("--action-preservation-fit", "--relabel-fit", "--relabel-learning-rate", "--local-fit",
                 "--diverse-fit"):
        assert flag not in cmd


BASE = ["w", "--config", "c", "--dataset", "d", "--checkpoint", "k", "--output-dir", "o",
        "--control-db", "b", "--experiment-id", "e", "--action-preservation-probe",
        "--comparison-report", "r", "--m2l-report", "m", "--m2l-checkpoint", "mc", "--m2mc-report", "x"]


@pytest.mark.parametrize("extra", [["--action-preservation-fit"], ["--local-fit"], ["--diverse-fit"],
                                   ["--relabel-fit"], ["--relabel-learning-rate", "0.003"]])
def test_probe_worker_exclusive(monkeypatch, extra):
    monkeypatch.setattr(mw, "run_action_preservation_probe", lambda *a, **k: pytest.fail("must not run"))
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: pytest.fail("must not run"))
    monkeypatch.setattr(sys, "argv", [*BASE, *extra])
    with pytest.raises(SystemExit):
        mw.main()


def test_probe_worker_dispatch(monkeypatch):
    seen = {}
    monkeypatch.setattr(mw, "run_action_preservation_probe", lambda *a, **k: seen.update(k) or {"status": "failed"})
    monkeypatch.setattr(mw, "run_memory", lambda *a, **k: pytest.fail("training entry must not run"))
    monkeypatch.setattr(sys, "argv", BASE)
    monkeypatch.setattr("builtins.print", lambda *a, **k: None)
    assert mw.main() == 1
    assert seen["m2mc_report_path"] == Path("x") and seen["m2l_checkpoint_path"] == Path("mc")


def test_probe_requires_all_paths():
    with pytest.raises(ValueError, match="six input paths"):
        mw.run_action_preservation_probe(None, None, None, None, None, "e", comparison_report_path=None,
                                         m2l_report_path=None, m2l_checkpoint_path=None, m2mc_report_path=None)
