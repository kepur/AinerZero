"""CPU checks for the weight025 duty migration. No MLX, no RunStore, no checkpoint rewrite."""

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.core.pilot import load_pilot_config
from ainerzero.learning.action_preservation_closure import (
    mixed_weight025_condition_plan,
    weight025_source_schedule_compat,
)
from ainerzero.runtime.history_worker import validate_history_source

ROOT = Path(__file__).resolve().parents[1]
META = (
    ROOT
    / "artifacts/pilot/pilot-92e978f05bb941768a34f13a76ddf3f5/checkpoints"
    / "f33974c9-b86f-4429-9ea9-8ea0e733142a/metadata.json"
)
M2D = ROOT / "artifacts/reports/m2d-changed-multistep.json"
M2L = ROOT / "artifacts/reports/m2l-diverse-memory.json"
OUT = ROOT / "artifacts/reports/E25-weighted/source-compat"


def _load(path):
    return json.loads(path.read_text())


def _clone(value):
    return json.loads(json.dumps(value))


@pytest.fixture(scope="module")
def pair():
    metadata = _load(META)
    live = load_pilot_config(ROOT / "configs/pilot.yaml").model_dump(mode="json")
    return metadata, live


def test_live_duty_stays_one_and_checkpoint_file_is_not_rewritten(pair):
    metadata, live = pair
    before = hashlib.sha256(META.read_bytes()).hexdigest()
    assert live["resources"]["active"]["training_duty_cycle"] == 1.0
    assert "training_duty_cycle: 1.0" in (ROOT / "configs/pilot.yaml").read_text()
    record = weight025_source_schedule_compat(metadata, live, metadata["dataset_source"])
    assert hashlib.sha256(META.read_bytes()).hexdigest() == before
    assert record["allowed_difference"] == {
        "path": "resources.active.training_duty_cycle",
        "source": 0.25,
        "live": 1.0,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata_path": str(META.relative_to(ROOT)),
        "metadata_file_sha256": before,
        "record": record,
        "live_active_training_duty_cycle": 1.0,
    }
    (OUT / "duty-migration.json").write_text(json.dumps(payload, indent=1) + "\n")


def test_old_history_validator_still_rejects_the_same_pair(pair):
    metadata, live = pair
    with pytest.raises(ValueError, match="config mismatch"):
        validate_history_source(metadata, live, metadata["dataset_source"])


def test_science_guard_and_unspecified_duty_are_rejected(pair):
    metadata, live = pair
    identity = metadata["dataset_source"]
    bumped = _clone(live)
    bumped["training"]["learning_rate"] = bumped["training"]["learning_rate"] + 1.0
    with pytest.raises(ValueError, match="learning_rate"):
        weight025_source_schedule_compat(metadata, bumped, identity)
    for path, value in (
        (("resources", "system_reserve_gib"), 8.0),
        (("resources", "swap_growth_gib"), 2.0),
        (("resources", "minimum_disk_free_gib"), 10.0),
        (("resources", "pause_training_on_battery"), False),
        (("resources", "active", "training_duty_cycle"), 0.5),
        (("resources", "idle", "training_duty_cycle"), 0.5),
    ):
        changed = _clone(live)
        node = changed
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        with pytest.raises(ValueError, match="weight025 source config mismatch"):
            weight025_source_schedule_compat(metadata, changed, identity)
    wrong_source = _clone(metadata)
    wrong_source["config"]["resources"]["active"]["training_duty_cycle"] = 0.5
    with pytest.raises(ValueError, match="training_duty_cycle"):
        weight025_source_schedule_compat(wrong_source, live, identity)


def test_older_report_snapshots_are_not_a_blanket_exemption(pair):
    _, live = pair
    m2d = _load(M2D)["phases"][0]["run"]["config_snapshot"]
    m2l = _load(M2L)["run"]["config_snapshot"]
    metadata, _ = pair
    for snapshot in (m2d, m2l):
        forged = _clone(metadata)
        forged["config"] = snapshot
        with pytest.raises(ValueError, match="weight025 source config mismatch"):
            weight025_source_schedule_compat(forged, live, metadata["dataset_source"])


def test_identity_and_optimizer_counts_stay_strict(pair):
    metadata, live = pair
    with pytest.raises(ValueError, match="dataset"):
        weight025_source_schedule_compat(metadata, live, {"not": "the source"})
    broken = _clone(metadata)
    broken["optimizer_steps"] = 0
    with pytest.raises(ValueError, match="completed updates"):
        weight025_source_schedule_compat(broken, live, metadata["dataset_source"])
    assert "source_config" not in inspect.signature(weight025_source_schedule_compat).parameters


def test_other_source_callers_keep_the_strict_validator():
    from ainerzero.runtime import (
        coverage_worker,
        interference_worker,
        memory_worker,
        paired_memory_worker,
    )

    strict = inspect.getsource(validate_history_source)
    assert 'metadata.get("config") != config' in strict
    for fn in (
        coverage_worker.validate_coverage_source,
        paired_memory_worker.validate_paired_source,
        interference_worker.validate_interference_pair,
        memory_worker.run_action_preservation_probe,
    ):
        text = inspect.getsource(fn)
        assert "validate_history_source" in text
        assert "weight025_source_schedule_compat" not in text
    memory = inspect.getsource(memory_worker.run_memory)
    assert "if action_preservation_mixed_weight025:" in memory
    assert "weight025_source_schedule_compat" in memory
    plan = mixed_weight025_condition_plan()
    assert plan["history_weight"] == 0.25
    assert "schedule_compat" not in plan
    signature = inspect.signature(memory_worker._prepare_relabel)
    assert "weight025_lineage" in signature.parameters
    assert "lineage_config" not in signature.parameters
    assert "history_config" not in signature.parameters


def test_weight025_full_cpu_chain_binds_historical_config():
    script = ROOT / "artifacts/reports/E25-weighted/source-full-chain/probe.py"
    proc = subprocess.run(
        [sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    log = json.loads((script.parent / "probe-log.json").read_text())
    assert log["strict_history_rejected"] and log["unscoped_relabel_rejected"]
    assert log["live_duty"] == 1.0 and log["historical_duty"] == 0.25
    assert log["condition_sha_unchanged"] and log["m2l_weights_loaded"] is False
    assert log["mlx_loaded"] is False
