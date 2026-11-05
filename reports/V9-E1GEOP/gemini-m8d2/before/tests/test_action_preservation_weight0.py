"""M2n-M3-control tests: E24 mixed batch with the history half's CE+KL scaled by lambda_h=0.0.

CPU only (no MLX). Covers the isolated condition/protocol, the registered objective
0.75*(CE_s+KL_s)+0.0*(CE_h+KL_h) with the 16-row denominator, the gradient-share
telemetry, zero history gradient, worker wiring/exclusivity, fail-closed identity verification,
and 4 registered mutation tests:
1. lambda mistaken as 0.25
2. zero applied to single-edge half
3. history half skips forward / unit reduction
4. renormalization after scaling
"""

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ainerzero import cli
from ainerzero.learning import action_preservation as ap
from ainerzero.learning.action_preservation_closure import (
    A3_DESIGN_REGISTRATION_SHA256,
    CONTROL_DESIGN_REGISTRATION_SHA256,
    MIXED_CONTROL_HISTORY_WEIGHT,
    MIXED_HISTORY_WEIGHT,
    MIXED_PROTOCOL,
    WEIGHT025_PROTOCOL,
    WEIGHT0_CONTROL_PROTOCOL,
    combine_mixed_halves,
    mixed_condition_plan,
    mixed_gradient_shares,
    mixed_half_weights,
    mixed_weight025_condition_plan,
    mixed_weight0_control_condition_plan,
)
from ainerzero.runtime import memory_worker as mw

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "src" / "ainerzero" / "runtime" / "memory_worker.py"
APC = ROOT / "src" / "ainerzero" / "learning" / "action_preservation_closure.py"
IDENTITY = ROOT / "artifacts/reports/E26-weight0/weight0-identity.json"
WEIGHT025_IDENTITY = ROOT / "artifacts/reports/E25-weighted/weight025-identity.json"
E24_MIXED_CONDITION_SHA256 = "dd02c4fe58059d5c505705e35afa97042bbde2af3923239ca7b7caa6f470a4f2"
WEIGHT025_CONDITION_SHA256 = "6e98299668221d0ba970198b1af662ba5c2a1b4c9dd0f29ccb56ce0ed06041d0"
COMMAND = "train-action-preserved-mixed-weight0-control-memory"
REQUIRED = [
    "--dataset", "d",
    "--checkpoint", "c",
    "--comparison-report", "r",
    "--m2l-report", "m",
    "--m2l-checkpoint", "k",
    "--m2mc-report", "x",
    "--experiment-id", "e",
]


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _dict_map(fn, *trees):
    return {k: fn(*(t[k] for t in trees)) for k in trees[0]}


def check_weight0_objective(module):
    """The registered control objective (lambda_h=0.0); raises AssertionError on any deviation."""
    weights, denom = module.mixed_half_weights(12, 4, 0.0, protocol=WEIGHT0_CONTROL_PROTOCOL)
    assert denom == 16.0
    assert weights == {"single_edge": 12.0, "history": 0.0}
    rng = np.random.default_rng(42)
    g = {h: {"w": rng.normal(size=(3, 2)), "b": rng.normal(size=4)} for h in ("single_edge", "history")}
    got = module.combine_mixed_halves(g, weights, denom, _dict_map)
    for k in ("w", "b"):
        want = 0.75 * g["single_edge"][k] + 0.0 * g["history"][k]
        assert np.allclose(got[k], want, rtol=0, atol=1e-12), k
    ce = {"single_edge": 1.3, "history": 2.9}
    kl = {"single_edge": 0.2, "history": 0.7}
    loss = sum(weights[h] * (ce[h] + kl[h]) for h in weights) / denom
    assert loss == pytest.approx(0.75 * 1.5 + 0.0 * 3.6, abs=1e-12)


def test_no_mlx_imported():
    code = (
        "import sys, ainerzero.runtime.memory_worker, ainerzero.learning.action_preservation_closure; "
        "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_condition_vs_weight025_and_e24_digests():
    old = mixed_weight025_condition_plan()
    new = mixed_weight0_control_condition_plan()
    e24 = mixed_condition_plan()

    # E24 digest unchanged
    assert e24["condition_sha256"] == E24_MIXED_CONDITION_SHA256
    assert e24["protocol"] == MIXED_PROTOCOL

    # weight025 digest unchanged
    assert old["condition_sha256"] == WEIGHT025_CONDITION_SHA256
    assert old["protocol"] == WEIGHT025_PROTOCOL
    assert old["mixed_condition_sha256"] == E24_MIXED_CONDITION_SHA256
    assert old["history_weight"] == 0.25

    # new weight0 control condition
    assert new["protocol"] == WEIGHT0_CONTROL_PROTOCOL == "m2m_n_mixed_history_weight0_control_v1"
    assert new["mixed_condition_sha256"] == E24_MIXED_CONDITION_SHA256
    assert new["history_weight"] == 0.0
    assert new["renormalize_after_scaling"] is False
    assert new["design_registration_sha256"] == CONTROL_DESIGN_REGISTRATION_SHA256
    assert new["base_plan_sha256"] == ap.FROZEN_PLAN_SHA256

    body = {k: v for k, v in new.items() if k != "condition_sha256"}
    assert new["condition_sha256"] == _digest(body)

    # Difference between weight025 and weight0_control is strictly the registered factor
    changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    assert changed == {
        "protocol",
        "single_factor",
        "normalization",
        "condition_sha256",
        "history_weight",
        "design_registration_sha256",
    }

    # Everything else is bitwise identical
    for key in (
        "batch",
        "units",
        "seconds",
        "seeds",
        "windows",
        "sampler_geometry",
        "history_permutation",
        "keep_branch",
        "start",
        "base_plan_sha256",
        "mixed_condition_sha256",
        "mixed_protocol",
    ):
        assert new.get(key) == old.get(key), key


def test_worker_plan_differs_only_in_the_registered_factor():
    old = mw.action_preservation_mixed_weight025_memory_plan()
    new = mw.action_preservation_mixed_weight0_control_memory_plan()
    changed = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    assert changed == {"protocol", "history_weight", "action_preservation_condition"}
    assert new["history_weight"] == 0.0
    assert new["protocol"] == WEIGHT0_CONTROL_PROTOCOL
    assert new["action_preservation_condition"] == mixed_weight0_control_condition_plan()
    assert (new["single_edge_rows"], new["history_rows"], new["updates"]) == (12, 4, 200)
    assert new["training_model_units_per_update"] == 152
    assert new["expected_total_model_units"] == 202_304
    assert new["total_reserved_seconds_if_complete"] == 1_740
    assert (new["supervised_deadline_seconds"], new["supervisor_deadline_seconds"]) == (1_760, 1_780)
    assert new["seeds"] == old["seeds"] and new["seeds"]["mixed_history_augmentation"] == 2407
    assert new["keep_lambda"] == 1.0
    assert new["first_update_keep_loss_max"] == old["first_update_keep_loss_max"]
    assert new["resource_seconds"] == old["resource_seconds"]


def test_design_registration_matches_control_file_bytes():
    path = ROOT / "artifacts/reports/relay-claude-20261014/M2NM3-control-registration.json"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == CONTROL_DESIGN_REGISTRATION_SHA256
    assert mixed_weight0_control_condition_plan()["design_registration_sha256"] == actual


def test_registered_objective():
    check_weight0_objective(sys.modules["ainerzero.learning.action_preservation_closure"])


def test_weights_validation():
    # WEIGHT0_CONTROL_PROTOCOL allows 0.0
    assert mixed_half_weights(12, 4, 0.0, protocol=WEIGHT0_CONTROL_PROTOCOL) == (
        {"single_edge": 12.0, "history": 0.0},
        16.0,
    )
    # Old protocols (or None) still reject 0.0
    with pytest.raises(ValueError, match="history weight must be in"):
        mixed_half_weights(12, 4, 0.0)
    for bad in (-0.25, 1.5):
        with pytest.raises(ValueError):
            mixed_half_weights(12, 4, bad, protocol=WEIGHT0_CONTROL_PROTOCOL)


def test_gradient_share_and_zero_history_telemetry():
    rng = np.random.default_rng(11)
    halves = {h: {"a": rng.normal(size=5), "b": rng.normal(size=(2, 2))} for h in ("single_edge", "history")}
    rows = {"single_edge": 12.0, "history": 4.0}
    weights, denom = mixed_half_weights(12, 4, 0.0, protocol=WEIGHT0_CONTROL_PROTOCOL)
    out = mixed_gradient_shares(halves, rows, weights)

    # Before scaling: both halves contribute
    assert sum(v["projection_share"] for v in out["before_scaling"].values()) == pytest.approx(1.0)
    assert sum(v["norm_share"] for v in out["before_scaling"].values()) == pytest.approx(1.0)
    assert out["before_scaling"]["history"]["contribution_l2"] > 0

    # After scaling: history contribution and shares are strictly 0.0
    assert out["after_scaling"]["history"]["contribution_l2"] == 0.0
    assert out["after_scaling"]["history"]["norm_share"] == 0.0
    assert out["after_scaling"]["history"]["projection_share"] == 0.0
    assert out["after_scaling"]["single_edge"]["norm_share"] == pytest.approx(1.0)
    assert out["after_scaling"]["single_edge"]["projection_share"] == pytest.approx(1.0)
    assert out["after_scaling"]["single_edge"]["contribution_l2"] == pytest.approx(
        out["before_scaling"]["single_edge"]["contribution_l2"]
    )


# --- 4 Mutation Tests (F3: real production source mutated in a temp copy) ---
# 1. lambda mistaken as 0.25
# 2. zero applied to single-edge half
# 3. history half skips forward (unit reduction)
# 4. renormalize to weight sum after scaling

CHECKER = r"""
import sys, ast
from pathlib import Path
import numpy as np
from ainerzero.learning import action_preservation_closure as apc
from ainerzero.runtime import memory_worker as mw
plan = mw.action_preservation_mixed_weight0_control_memory_plan()
assert plan["history_weight"] == 0.0
assert plan["training_model_units_per_update"] == 152 and plan["expected_total_model_units"] == 202_304
w, d = apc.mixed_weight0_half_weights(12, 4)
assert d == 16.0 and w == {"single_edge": 12.0, "history": 0.0}, (w, d)
m = lambda f, *t: {k: f(*(x[k] for x in t)) for k in t[0]}
rng = np.random.default_rng(0)
g = {h: {"a": rng.normal(size=4)} for h in ("single_edge", "history")}
got = apc.combine_mixed_halves(g, w, d, m)
assert np.allclose(got["a"], 0.75 * g["single_edge"]["a"], rtol=0, atol=1e-12)
src = Path(mw.__file__).read_text()
assert src.count("for name, half, burn_in, rows, parts in halves:") == 1
assert "if name == \"history\" and action_preservation_mixed_weight0_control" not in src
tree = ast.parse(src)
"""

PROD_MUTANTS = {
    "lambda_025": ("src/ainerzero/learning/action_preservation_closure.py",
                   "MIXED_CONTROL_HISTORY_WEIGHT = 0.0", "MIXED_CONTROL_HISTORY_WEIGHT = 0.25"),
    "zero_on_single_edge": ("src/ainerzero/learning/action_preservation_closure.py",
                            '"single_edge": float(single_rows) * MIXED_KEEP_WEIGHT,\n'
                            '               "history": float(history_rows) * float(history_weight)}',
                            '"single_edge": float(single_rows) * float(history_weight),\n'
                            '               "history": float(history_rows)}'),
    "skip_history_forward": ("src/ainerzero/runtime/memory_worker.py",
                             "                for name, half, burn_in, rows, parts in halves:\n",
                             "                for name, half, burn_in, rows, parts in halves:\n"
                             "                    if name == \"history\" and action_preservation_mixed_weight0_control:\n"
                             "                        continue\n"),
    "renormalize_after_scaling": ("src/ainerzero/learning/action_preservation_closure.py",
                                  "return weights, float(single_rows + history_rows)",
                                  "return weights, float(sum(weights.values()))"),
}


def _run_checker(src_root):
    import os
    env = dict(os.environ, PYTHONPATH=str(src_root / "src"))
    return subprocess.run([sys.executable, "-c", CHECKER], env=env, cwd=src_root,
                          capture_output=True, text=True, check=False)


def _copy_src(tmp_path):
    import shutil
    dst = tmp_path / "repo"
    shutil.copytree(ROOT / "src", dst / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for rel in ("configs/pilot.yaml",):
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dst / rel)
    return dst


def test_checker_passes_on_unmutated_production_copy(tmp_path):
    res = _run_checker(_copy_src(tmp_path))
    assert res.returncode == 0, res.stderr


@pytest.mark.parametrize("name", sorted(PROD_MUTANTS))
def test_production_mutants_are_caught(name, tmp_path):
    rel, old, new = PROD_MUTANTS[name]
    dst = _copy_src(tmp_path)
    target = dst / rel
    text = target.read_text()
    assert text.count(old) == 1, name
    target.write_text(text.replace(old, new))
    res = _run_checker(dst)
    assert res.returncode != 0, name


# --- CLI and Identity Tests ---


def _args(tmp_path, **flags):
    base = dict(
        config=ROOT / "configs" / "pilot.yaml",
        output_dir=tmp_path,
        experiment_id="e",
        dataset=tmp_path / "d",
        checkpoint=tmp_path / "c",
        comparison_report=tmp_path / "r",
        m2l_report=tmp_path / "m",
        m2l_checkpoint=tmp_path / "k",
        m2mc_report=tmp_path / "x",
        action_preserved_mixed_weight0_control_training=True,
        action_preserved_mixed_weight025_training=False,
        action_preserved_mixed_training=False,
        action_preserved_memory_training=False,
        action_preservation_probe=False,
        action_preserved_lambda10_training=False,
        action_preserved_distill_training=False,
        action_preserved_history_training=False,
    )
    base.update(flags)
    return SimpleNamespace(**base)


def test_cli_is_a_separate_command_without_scientific_knobs(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda args: seen.update(vars(args)) or {"status": "completed"})
    assert cli.main([COMMAND, *REQUIRED]) == 0
    assert seen["action_preserved_mixed_weight0_control_training"] is True
    assert seen.get("action_preserved_mixed_training", False) is False
    assert seen.get("action_preserved_mixed_weight025_training", False) is False
    assert not any(key in seen for key in ("learning_rate", "history_weight", "history_rows", "keep_lambda"))
    for flag in ("--learning-rate", "--history-weight", "--lambda", "--updates"):
        with pytest.raises(SystemExit):
            cli.main([COMMAND, *REQUIRED, flag, "0.0"])


def test_dispatch_uses_the_new_flag_and_1780(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli, "verify_weight0_control_identity", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "project_root", lambda _path: tmp_path)
    monkeypatch.setattr(
        cli.subprocess,
        "run",
        lambda cmd, **kwargs: captured.update(cmd=cmd, timeout=kwargs["timeout"]) or Done(),
    )
    cli.train_pilot_command(_args(tmp_path))
    assert "--action-preservation-mixed-weight0-control" in captured["cmd"]
    assert "--action-preservation-mixed-weight025" not in captured["cmd"]
    assert "--action-preservation-mixed" not in captured["cmd"]
    assert captured["timeout"] == min(1780, cli.load_pilot_config(ROOT / "configs/pilot.yaml").budget.max_wall_seconds)


def test_entry_is_exclusive_with_the_old_mixed_and_weight025_commands(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("worker launched")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    for conflict in (
        {"action_preserved_mixed_training": True},
        {"action_preserved_mixed_weight025_training": True},
        {"action_preserved_history_training": True},
    ):
        report = cli.train_pilot_command(_args(tmp_path, **conflict))
        assert report["status"] == "failed"
        assert report["fail_closed"] is True


def _current_record(root, protocol, plan, required, config):
    return {
        "protocol": protocol,
        "condition_sha256": plan["condition_sha256"],
        "design_registration_sha256": plan["design_registration_sha256"],
        "config_hash": cli.pilot_config_hash(cli.load_pilot_config(config)),
        "files": {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in sorted(required)},
    }


def _w025_record(root):
    return _current_record(root, WEIGHT025_PROTOCOL, mixed_weight025_condition_plan(),
                           cli.WEIGHT025_REQUIRED_FILES, root / "configs" / "pilot.yaml")


def _w0_record(root):
    return _current_record(root, WEIGHT0_CONTROL_PROTOCOL, mixed_weight0_control_condition_plan(),
                           cli.WEIGHT0_CONTROL_REQUIRED_FILES, root / "configs" / "pilot.yaml")


def test_weight025_gate_is_strict_bytewise(tmp_path):
    assert not hasattr(cli, "WEIGHT025_FROZEN_SHAS")
    config = ROOT / "configs" / "pilot.yaml"
    record = _w025_record(ROOT)
    cli.verify_weight025_identity(ROOT, record, config_path=config)
    empty = dict(record, files={})
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_weight025_identity(ROOT, empty, config_path=config)
    for rel in ("src/ainerzero/cli.py", "src/ainerzero/runtime/memory_worker.py",
                "src/ainerzero/learning/action_preservation_closure.py"):
        bad = json.loads(json.dumps(record))
        bad["files"][rel] = "ab" * 32
        with pytest.raises(RuntimeError, match="identity mismatch"):
            cli.verify_weight025_identity(ROOT, bad, config_path=config)


@pytest.mark.parametrize("rel", ["src/ainerzero/cli.py", "src/ainerzero/runtime/memory_worker.py",
                                 "src/ainerzero/learning/action_preservation_closure.py"])
def test_tampered_source_rejected_by_both_gates(rel, tmp_path):
    import shutil
    dst = tmp_path / "repo"
    for f in sorted(cli.WEIGHT025_REQUIRED_FILES | cli.WEIGHT0_CONTROL_REQUIRED_FILES):
        (dst / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, dst / f)
    config = dst / "configs" / "pilot.yaml"
    r025, r0 = _w025_record(dst), _w0_record(dst)
    cli.verify_weight025_identity(dst, r025, config_path=config)
    cli.verify_weight0_control_identity(dst, r0, config_path=config)
    with (dst / rel).open("a") as fh:
        fh.write("\n# tampered\n")
    with pytest.raises(RuntimeError, match="identity mismatch"):
        cli.verify_weight025_identity(dst, r025, config_path=config)
    with pytest.raises(RuntimeError, match="identity mismatch"):
        cli.verify_weight0_control_identity(dst, r0, config_path=config)


def test_identity_matches_and_mismatch_fails_closed(monkeypatch, tmp_path):
    config = ROOT / "configs" / "pilot.yaml"
    recorded = _w0_record(ROOT)
    cli.verify_weight0_control_identity(ROOT, recorded, config_path=config)
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_weight0_control_identity(ROOT, dict(recorded, files={}), config_path=config)

    # Missing file
    dropped = json.loads(json.dumps(recorded))
    dropped["files"].pop("src/ainerzero/cli.py")
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_weight0_control_identity(ROOT, dropped, config_path=config)

    # Extra file
    extra = json.loads(json.dumps(recorded))
    extra["files"]["src/ainerzero/extra.py"] = "ab" * 32
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_weight0_control_identity(ROOT, extra, config_path=config)

    # Not a sha256
    not_sha = json.loads(json.dumps(recorded))
    not_sha["files"]["src/ainerzero/cli.py"] = "invalid-sha"
    with pytest.raises(RuntimeError, match="not a sha256"):
        cli.verify_weight0_control_identity(ROOT, not_sha, config_path=config)

    # Modified file content
    bad = json.loads(json.dumps(recorded))
    bad["files"]["configs/pilot.yaml"] = "ab" * 32
    with pytest.raises(RuntimeError, match="identity mismatch"):
        cli.verify_weight0_control_identity(ROOT, bad, config_path=config)

    # Wrong protocol
    wrong_proto = json.loads(json.dumps(recorded))
    wrong_proto["protocol"] = WEIGHT025_PROTOCOL
    with pytest.raises(RuntimeError, match="protocol"):
        cli.verify_weight0_control_identity(ROOT, wrong_proto, config_path=config)

    # Modified pilot config
    other = tmp_path / "other.yaml"
    text = config.read_text().replace("training_duty_cycle: 1.0", "training_duty_cycle: 0.25", 1)
    other.write_text(text)
    with pytest.raises(RuntimeError, match="config_hash"):
        cli.verify_weight0_control_identity(ROOT, recorded, config_path=other)
