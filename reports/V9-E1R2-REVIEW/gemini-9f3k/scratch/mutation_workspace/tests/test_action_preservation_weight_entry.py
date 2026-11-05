"""CPU entry checks for the M2n-M2 CLI. No MLX, no worker launch, no real lock.

The weight025 identity record is computed from the current source tree instead of
being read from ``artifacts/reports/E25-weighted/weight025-identity.json``: that file
is a historical registration (R20261014-Relay-08/09), so the gate must reject it while
it disagrees with the live sources. The gate itself is not relaxed here.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ainerzero import cli
from ainerzero.learning.action_preservation_closure import (
    WEIGHT025_PROTOCOL,
    mixed_weight025_condition_plan,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "pilot.yaml"
# Historical E25 registration, kept as evidence. Any future weight025 run needs a
# fresh lead re-registration; this file must not be edited to make a test pass.
HISTORICAL_IDENTITY = ROOT / "artifacts/reports/E25-weighted/weight025-identity.json"
REQUIRED = [
    "--dataset", "d",
    "--checkpoint", "c",
    "--comparison-report", "r",
    "--m2l-report", "m",
    "--m2l-checkpoint", "k",
    "--m2mc-report", "x",
    "--experiment-id", "e",
]
COMMAND = "train-action-preserved-mixed-weight025-memory"


def _args(tmp_path, **flags):
    base = dict(
        config=CONFIG,
        output_dir=tmp_path,
        experiment_id="e",
        dataset=tmp_path / "d",
        checkpoint=tmp_path / "c",
        comparison_report=tmp_path / "r",
        m2l_report=tmp_path / "m",
        m2l_checkpoint=tmp_path / "k",
        m2mc_report=tmp_path / "x",
        action_preserved_mixed_weight025_training=True,
        action_preserved_mixed_training=False,
        action_preserved_memory_training=False,
        action_preservation_probe=False,
        action_preserved_lambda10_training=False,
        action_preserved_distill_training=False,
        action_preserved_history_training=False,
    )
    base.update(flags)
    return SimpleNamespace(**base)


def _live_record(root=ROOT) -> dict:
    """A weight025 identity record computed from the current sources and config."""
    plan = mixed_weight025_condition_plan()
    return {
        "protocol": WEIGHT025_PROTOCOL,
        "condition_sha256": plan["condition_sha256"],
        "design_registration_sha256": plan["design_registration_sha256"],
        "config_hash": cli.pilot_config_hash(cli.load_pilot_config(root / "configs" / "pilot.yaml")),
        "files": {
            rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
            for rel in sorted(cli.WEIGHT025_REQUIRED_FILES)
        },
    }


def _copy(record: dict) -> dict:
    return json.loads(json.dumps(record))


def test_cli_is_a_separate_command_without_scientific_knobs(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "train_pilot_command", lambda args: seen.update(vars(args)) or {"status": "completed"})
    assert cli.main([COMMAND, *REQUIRED]) == 0
    assert seen["action_preserved_mixed_weight025_training"] is True
    assert seen.get("action_preserved_mixed_training", False) is False
    assert not any(key in seen for key in ("learning_rate", "history_weight", "history_rows", "keep_lambda"))
    for flag in ("--learning-rate", "--history-weight", "--lambda", "--updates"):
        with pytest.raises(SystemExit):
            cli.main([COMMAND, *REQUIRED, flag, "0.25"])


def test_dispatch_uses_the_new_flag_and_1780(monkeypatch, tmp_path):
    captured = {}

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(cli, "verify_weight025_identity", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "project_root", lambda _path: tmp_path)
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda cmd, **kwargs: captured.update(cmd=cmd, timeout=kwargs["timeout"]) or Done(),
    )
    cli.train_pilot_command(_args(tmp_path))
    assert "--action-preservation-mixed-weight025" in captured["cmd"]
    assert "--action-preservation-mixed" not in captured["cmd"]
    assert captured["timeout"] == min(1780, cli.load_pilot_config(CONFIG).budget.max_wall_seconds)


def test_entry_is_exclusive_with_the_old_mixed_command(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("worker launched")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    report = cli.train_pilot_command(_args(tmp_path, action_preserved_mixed_training=True))
    assert report["status"] == "failed"
    assert report["fail_closed"] is True


def test_identity_matches_and_mismatch_fails_closed(monkeypatch, tmp_path):
    recorded = _live_record()
    cli.verify_weight025_identity(ROOT, recorded, config_path=CONFIG)

    # Any single registered file whose bytes drift fails the gate, and the error names it.
    for rel in sorted(cli.WEIGHT025_REQUIRED_FILES):
        bad = _copy(recorded)
        bad["files"][rel] = "ab" * 32
        with pytest.raises(RuntimeError, match="identity mismatch") as excinfo:
            cli.verify_weight025_identity(ROOT, bad, config_path=CONFIG)
        assert rel in str(excinfo.value)

    empty = _copy(recorded)
    empty["files"] = {}
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_weight025_identity(ROOT, empty, config_path=CONFIG)
    dropped = _copy(recorded)
    dropped["files"].pop("src/ainerzero/cli.py")
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_weight025_identity(ROOT, dropped, config_path=CONFIG)
    extra = _copy(recorded)
    extra["files"]["src/ainerzero/cli_extra.py"] = "cd" * 32
    with pytest.raises(RuntimeError, match="required set"):
        cli.verify_weight025_identity(ROOT, extra, config_path=CONFIG)
    not_sha = _copy(recorded)
    not_sha["files"]["src/ainerzero/cli.py"] = "not-a-sha"
    with pytest.raises(RuntimeError, match="not a sha256"):
        cli.verify_weight025_identity(ROOT, not_sha, config_path=CONFIG)

    # Missing top-level fields are rejected by the schema, not silently defaulted.
    for field in sorted({"protocol", "condition_sha256", "design_registration_sha256", "config_hash", "files"}):
        missing = _copy(recorded)
        missing.pop(field)
        with pytest.raises(RuntimeError, match=f"missing {field}"):
            cli.verify_weight025_identity(ROOT, missing, config_path=CONFIG)

    wrong_protocol = _copy(recorded)
    wrong_protocol["protocol"] = "m2m_n_mixed_single_edge_history_v1"
    with pytest.raises(RuntimeError, match="protocol"):
        cli.verify_weight025_identity(ROOT, wrong_protocol, config_path=CONFIG)

    other = tmp_path / "other.yaml"
    text = CONFIG.read_text().replace("training_duty_cycle: 1.0", "training_duty_cycle: 0.25", 1)
    other.write_text(text)
    with pytest.raises(RuntimeError, match="config_hash"):
        cli.verify_weight025_identity(ROOT, recorded, config_path=other)
    launched = {}

    def boom(*args, **kwargs):
        launched["ran"] = True
        raise AssertionError("worker launched")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    report = cli.train_pilot_command(_args(tmp_path, config=other))
    assert report["status"] == "failed" and report["fail_closed"] is True
    assert "config_hash" in report["error"]
    assert "ran" not in launched


def test_historical_identity_is_rejected_by_the_live_source(monkeypatch, tmp_path):
    """The live E25 registration must fail closed while it disagrees with the sources.

    A17 changed the shared sources, so weight025-identity.json is history
    (R20261014-Relay-08/09). If the lead re-registers weight025, that registration is
    expected to be recomputed from the sources at that time and this test revisited --
    the gate must never be widened to accept the stale bytes.
    """
    historical = json.loads(HISTORICAL_IDENTITY.read_text())
    live = _live_record()
    drifted = sorted(rel for rel, sha in historical["files"].items() if live["files"].get(rel) != sha)
    assert drifted, (
        "weight025-identity.json now matches the live sources; if the lead re-registered it, "
        "update this test instead of relaxing the gate (R20261014-Relay-09)"
    )
    for rel in drifted:
        assert rel in cli.WEIGHT025_REQUIRED_FILES

    with pytest.raises(RuntimeError, match="identity mismatch") as excinfo:
        cli.verify_weight025_identity(ROOT, historical, config_path=CONFIG)
    for rel in drifted:
        assert rel in str(excinfo.value)

    # The CLI entry reads that same file when no record is passed, and must fail closed
    # for it without launching the worker.
    with pytest.raises(RuntimeError, match="identity mismatch"):
        cli.verify_weight025_identity(ROOT, config_path=CONFIG)

    def boom(*args, **kwargs):
        raise AssertionError("worker launched")

    monkeypatch.setattr(cli.subprocess, "run", boom)
    report = cli.train_pilot_command(_args(tmp_path))
    assert report["status"] == "failed" and report["fail_closed"] is True
    assert "identity mismatch" in report["error"]
    for rel in drifted:
        assert rel in report["error"]
